"""Live REST catalog conversion and explicit lifecycle schemas."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
import re
import json
from importlib.resources import files
from typing import cast

from mcp import Tool
from mcp_types import ToolAnnotations
from mcp_types.version import LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS

from .errors import SchemaError, TransportError
from .limits import (
    MAX_CATALOG_BYTES,
    MAX_SCHEMA_BYTES,
    MAX_TOOL_COUNT,
    MAX_TOOL_NAME_CHARS,
    MAX_TOTAL_SCHEMA_BYTES,
    MAX_UPLOAD_FILES,
    MCP_RESULT_INSTRUCTIONS,
    MCP_SUBMISSION_INSTRUCTIONS,
)
from .schema import (
    inject_plan_id,
    json_size,
    validate_schema_document,
    wrap_result_schema,
)


TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
GET_FILE_PRIVATE_FIELDS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "download_url",
        "expires_in",
        "session_url",
        "token",
        "upload_id",
        "upload_url",
        "x-goog-signature",
    }
)
GET_FILE_SAFE_PROPERTIES: dict[str, dict[str, object]] = {
    "hash": {"type": "string"},
    "display_name": {"type": "string"},
    "filename": {"type": "string"},
    "mimetype": {"type": "string"},
    "large": {"type": "boolean"},
    "summary": {"type": "string"},
    "permissions": {
        "type": "object",
        "required": ["can_view", "can_edit", "can_create"],
        "properties": {
            "can_view": {"type": "boolean"},
            "can_edit": {"type": "boolean"},
            "can_create": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "url": {"type": "string"},
    "content": {"type": "string"},
    "error": {"type": "string"},
}

def _model_projection(source: dict, fields: tuple[str, ...]) -> dict:
    """Keep an explicit allowlist at the boundary that removes private transport fields."""
    return {
        "type": "object", "additionalProperties": False,
        "required": [name for name in source["required"] if name in fields],
        "properties": {name: source["properties"][name] for name in fields},
    }


_WIRE = json.loads(files(__package__).joinpath("wire_schemas.json").read_text(encoding="utf-8"))
ACTOR_SCHEMA = _WIRE["Actor"]
PLAN_FILE_SCHEMA = _WIRE["PlanFile"]
SAFE_PLAN_SCHEMA = _model_projection(_WIRE["Plan"], (
    "id", "status", "name", "instructions", "files", "uploads_pending", "contract_version",
    "preview_url", "review_url", "correction", "superseded_by", "output_kind", "file_usage",
    "proposal", "execution", "original_brief", "action_summary", "require_review",
))
SAFE_RECEIPT_SCHEMA = _model_projection(_WIRE["SubmissionReceipt"], (
    "id", "status", "preview_url", "review_url", "contract_version", "proposal_fingerprint",
    "action_summary", "operation", "execution",
))

MCP_SUBMISSION_SCHEMA = {
    "type": "object",
    "required": [
        "contract_version",
        "proposal",
        "proposal_schema",
        "instructions",
        "file_usage",
    ],
    "properties": {
        "contract_version": {"type": "integer"},
        "proposal": {"type": "object"},
        "file_usage": {"type": "array"},
        "proposal_schema": {
            "const": "$.proposal_schema",
            "description": "Path relative to this contract object, not the enclosing lifecycle result.",
        },
        "instructions": {"const": MCP_SUBMISSION_INSTRUCTIONS},
    },
    "additionalProperties": False,
}

REST_CONTRACT_SCHEMA = _WIRE["PlanContract"]
REST_SCHEMA_CONTRACT_SCHEMA = _WIRE["PlanSchemaContract"]


def _mcp_contract(rest: dict) -> dict:
    public = _model_projection(rest, tuple(key for key in rest["properties"] if key != "submission_format"))
    public["properties"]["mcp_submission"] = MCP_SUBMISSION_SCHEMA
    public["required"].append("mcp_submission")
    return public


SAFE_CONTRACT_SCHEMA = _mcp_contract(REST_CONTRACT_SCHEMA)
SAFE_SCHEMA_CONTRACT_SCHEMA = _mcp_contract(REST_SCHEMA_CONTRACT_SCHEMA)


UPLOAD_RESULT_SCHEMA = {
    "type": "object",
    "required": ["plan", "upload_inventory"],
    "properties": {
        "plan": SAFE_PLAN_SCHEMA,
        "upload_inventory": {
            "type": "array",
            "maxItems": MAX_UPLOAD_FILES,
            "items": PLAN_FILE_SCHEMA,
        },
    },
    "additionalProperties": False,
}

ACTION_SELECTION_SCHEMA = {
    "type": "array",
    "maxItems": 100,
    "items": {"type": "string", "maxLength": 100, "pattern": "^[a-z][a-z0-9_]*$"},
}

LIFECYCLE_CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "contract": SAFE_CONTRACT_SCHEMA,
        "recovery": {
            "type": "object",
            "required": ["tool", "arguments", "message"],
            "properties": {
                "tool": {"const": "get_plan_contract"},
                "arguments": {
                    "type": "object",
                    "required": ["plan_id"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "actions": ACTION_SELECTION_SCHEMA,
                        "view": {"enum": ["full", "summary", "schema"]},
                    },
                    "additionalProperties": False,
                },
                "message": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "oneOf": [
        {"required": ["contract"]},
        {"required": ["recovery"]},
    ],
    "additionalProperties": False,
}
# A new Plan needs live permissions and any explicitly requested action schemas.
# The full guidance remains discoverable through get_plan_contract on the same ID.
START_CONTRACT_FIELDS = (
    "contract_version", "current_date", "timezone", "personal_page", "proposal_schema",
    "schema_scope", "schema_actions", "required_file_refs", "uploads_supported",
)
START_SUBMISSION_INSTRUCTIONS = (
    "Call submit_plan with this plan_id, contract_version, proposal and file_usage. "
    "Read get_plan_contract with view=schema and actions for exact schemas, "
    "or view=full for workflow, file and permission rules. Reuse this plan_id."
)
START_CONTRACT_SCHEMA = {
    "type": "object",
    "required": [key for key in START_CONTRACT_FIELDS if key in SAFE_CONTRACT_SCHEMA["required"]]
                + ["permissions", "mcp_submission"],
    "properties": {
        **{key: SAFE_CONTRACT_SCHEMA["properties"][key] for key in START_CONTRACT_FIELDS},
        "permissions": {"type": "object", "properties": {"allowed_actions": ACTION_SELECTION_SCHEMA},
                        "additionalProperties": False},
        "mcp_submission": {
            **SAFE_CONTRACT_SCHEMA["properties"]["mcp_submission"],
            "properties": {
                **SAFE_CONTRACT_SCHEMA["properties"]["mcp_submission"]["properties"],
                "instructions": {"const": START_SUBMISSION_INSTRUCTIONS},
            },
        },
    },
    "additionalProperties": False,
}
START_RESULT_SCHEMA = {
    **SAFE_PLAN_SCHEMA,
    "required": [*SAFE_PLAN_SCHEMA["required"], "context"],
    "properties": {
        **SAFE_PLAN_SCHEMA["properties"],
        "context": {
            **LIFECYCLE_CONTEXT_SCHEMA,
            "properties": {**LIFECYCLE_CONTEXT_SCHEMA["properties"], "contract": START_CONTRACT_SCHEMA},
        },
    },
}
ENRICHED_UPLOAD_RESULT_SCHEMA = {
    **UPLOAD_RESULT_SCHEMA,
    "required": [*UPLOAD_RESULT_SCHEMA["required"], "context"],
    "properties": {
        **UPLOAD_RESULT_SCHEMA["properties"],
        "context": LIFECYCLE_CONTEXT_SCHEMA,
    },
}


def _plan_input_schema() -> dict[str, object]:
    schema = _model_projection(_WIRE["createPlan"], ("instructions", "name", "revises_plan_id", "require_review"))
    schema["properties"]["revises_plan_id"] = {
        **schema["properties"]["revises_plan_id"],
        "description": "Creator-owned stopped execution to correct. Omit or use null for an independent Plan. Read current workspace state; propose only additional changes.",
    }
    schema["properties"]["require_review"] = {
        **schema["properties"]["require_review"],
        "description": "When true, lock this Plan to browser review only so external execution is rejected.",
    }
    schema["properties"]["actions"] = {
        **ACTION_SELECTION_SCHEMA,
        "description": "Known action types whose exact permitted schemas should be returned in context.contract, for example [create_task]. Use [] for a saved answer without changes. Omit for a summary without schemas.",
    }
    return schema


def _plan_id_input(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "required": ["plan_id"],
        "properties": {
            "plan_id": {"type": "string", "minLength": 1, "maxLength": 2048},
            **properties,
        },
        "additionalProperties": False,
    }


def get_file_output_schema(rest_schema: dict[str, object]) -> dict[str, object]:
    """Expose a scoped original download alongside bounded inline media."""
    result = validate_schema_document(rest_schema)
    rest_properties = result.setdefault("properties", {})
    if not isinstance(rest_properties, dict):
        raise SchemaError("invalid_schema", "get_file output properties are invalid.")
    properties = {
        field: deepcopy(rest_properties.get(field, schema))
        for field, schema in GET_FILE_SAFE_PROPERTIES.items()
    }
    if "original_file" in rest_properties:
        properties["original_file"] = deepcopy(rest_properties["original_file"])
    result["properties"] = properties
    original = properties.get("original_file")
    if not isinstance(original, dict):
        raise SchemaError(
            "invalid_schema", "get_file output lacks original_file schema."
        )
    original_properties = original.get("properties")
    if not isinstance(original_properties, dict):
        raise SchemaError("invalid_schema", "get_file original_file schema is invalid.")
    safe_original_fields = {"supported", "attached", "reason"}
    original["properties"] = {
        field: schema
        for field, schema in original_properties.items()
        if field in safe_original_fields
    }
    required_original = original.get("required")
    if isinstance(required_original, list):
        original["required"] = [
            field for field in required_original if field in safe_original_fields
        ]
    original["properties"].update({
        "download_url": {"type": "string", "minLength": 1, "maxLength": 8192},
        "expires_in": {"type": "integer", "minimum": 1, "maximum": 300},
    })
    # Only the explicit download variant may expose a signed read capability.
    original["additionalProperties"] = False
    properties["delivery"] = {
        "type": "object",
        "required": ["kind"],
        "properties": {
            "kind": {"enum": ["none", "image", "audio", "download"]},
            "mime_type": {"type": "string"},
            "size_bytes": {"type": "integer", "minimum": 0},
            "content_index": {"type": "integer", "minimum": 1},
        },
        "allOf": [
            {
                "if": {"properties": {"kind": {"const": "none"}}, "required": ["kind"]},
                "then": {
                    "not": {
                        "anyOf": [
                            {"required": ["mime_type"]},
                            {"required": ["size_bytes"]},
                            {"required": ["content_index"]},
                        ]
                    }
                },
                "else": {
                    "if": {"properties": {"kind": {"const": "download"}}},
                    "then": {
                        "required": ["mime_type"],
                        "not": {"anyOf": [
                            {"required": ["size_bytes"]},
                            {"required": ["content_index"]},
                        ]},
                    },
                    "else": {"required": ["mime_type", "size_bytes", "content_index"]},
                },
            }
        ],
        "additionalProperties": False,
    }
    required = result.setdefault("required", [])
    if not isinstance(required, list):
        raise SchemaError("invalid_schema", "get_file required fields are invalid.")
    required[:] = [field for field in required if field in properties]
    if "delivery" not in required:
        required.append("delivery")
    cast(list[object], result.setdefault("allOf", [])).append({
        "if": {"properties": {"delivery": {"properties": {"kind": {"const": "download"}}}}},
        "then": {
            "required": ["original_file"],
            "properties": {"original_file": {
                "required": ["supported", "attached", "download_url", "expires_in"],
                "properties": {"supported": {"const": True}, "attached": {"const": False}},
            }},
        },
        "else": {"properties": {"original_file": {"not": {"anyOf": [
            {"required": ["download_url"]}, {"required": ["expires_in"]},
        ]}}}},
    })
    # REST permits evolving entity metadata, but this boundary cannot safely
    # infer whether an arbitrary new field is descriptive or a signed transport
    # capability. New fields therefore require an explicit adapter release.
    result.pop("propertyNames", None)
    result["additionalProperties"] = False
    return validate_schema_document(result)


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    kind: str
    annotations: ToolAnnotations
    rest_output_schema: dict[str, object] | None = None
    result_paths: dict[str, object] | None = None

    def requires_result_wrapper(self, protocol_version: str) -> bool:
        # Select by the declared schema, including nullable/union roots, so
        # every successful value matches the same advertised result shape.
        return (
            protocol_version not in MODERN_PROTOCOL_VERSIONS
            and self.output_schema.get("type") != "object"
        )

    def as_mcp_tool(self, protocol_version: str = LATEST_MODERN_VERSION) -> Tool:
        wrapped = self.requires_result_wrapper(protocol_version)
        result_paths = (
            _wrap_result_paths(self.result_paths)
            if wrapped
            else deepcopy(self.result_paths)
        )
        return Tool(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            output_schema=(
                wrap_result_schema(self.output_schema)
                if wrapped
                else self.output_schema
            ),
            annotations=self.annotations,
            _meta=(
                {"lagniappe/resultPaths": result_paths}
                if result_paths is not None
                else None
            ),
        )


def _wrap_result_paths(value: object) -> object:
    """Keep catalog JSONPath hints relative to the advertised MCP value."""
    if isinstance(value, dict):
        return {key: _wrap_result_paths(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_wrap_result_paths(child) for child in value]
    if isinstance(value, str) and (value == "$" or value.startswith(("$.", "$["))):
        return "$.result" + value[1:]
    return value


READ_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    open_world_hint=True,
)
START_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
UPLOAD_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
SUBMIT_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=True,
)


def lifecycle_tools() -> tuple[ToolDefinition, ...]:
    common_start = (
        "Each call creates a new report. Reuse the returned id as plan_id for "
        "reads, uploads, submission, and revisions of this request. Never restart "
        "to recover clipped output. If context is unavailable, follow its "
        "recovery read without repeating the successful start."
    )
    review_only = "Submission saves a browser-reviewable proposal; it never executes workspace changes."
    return (
        ToolDefinition(
            "answer_question",
            "Get lightweight guidance and personal Page context for answering questions, retrieving tasks, or looking up how Lagniappe works via get_help without saving a report. The client model answers using plan-free read tools; this does not call a server model or create a Plan. Answer in chat first and offer to save afterward. Only when the user wants to save, use start_plan then submit_plan. Reuse this context during the conversation.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            _WIRE["AnswerContext"],
            "answer_context",
            READ_ANNOTATIONS,
        ),
        ToolDefinition(
            "get_actor",
            "Return the current actor, capabilities, timezone, and personal Page.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            ACTOR_SCHEMA,
            "actor",
            READ_ANNOTATIONS,
        ),
        ToolDefinition(
            "start_plan",
            f"Start one Plan for workspace changes, file organization, or an explicitly requested saved answer. For ordinary questions use answer_question and plan-free reads without saving. Instructions and uploads are optional individually; publishing needs at least one. {common_start} Pass actions=[\"create_task\"] or other known actions for selected schemas, or omit for compact context. Use get_plan_contract with view=full for workflow and permission rules. Continue the same Plan for mixed requests and revisions. {review_only}",
            _plan_input_schema(),
            START_RESULT_SCHEMA,
            "start_plan",
            START_ANNOTATIONS,
        ),
        ToolDefinition(
            "get_plan",
            "Return current Plan state, current/original brief, and bounded execution outcomes with currently viewable result entities. Defaults to include_proposal=false for compact status polling; pass include_proposal=true to fetch the full round-trippable proposal body. Before execution, revise the existing plan_id. After execution, start_plan with revises_plan_id creates a linked correction; never replay successful creations. Entity null means unavailable, not proof an action never ran.",
            _plan_id_input({
                "include_proposal": {
                    "type": "boolean",
                    "description": "Include the full round-trippable proposal body (default false for compact polling).",
                },
            }),
            SAFE_PLAN_SCHEMA,
            "get_plan",
            READ_ANNOTATIONS,
        ),
        ToolDefinition(
            "get_plan_contract",
            "Load exact schemas for selected allowed actions; actions=[] returns a saved-answer schema with no changes. Use view=schema for a follow-up after receiving the plan context: it omits repeated workflow/inventory guidance. full includes context and, without actions, all schemas. The default summary includes context without schemas. Reuse selected schemas; refresh context for changed state/permissions. Submission uses the API's current validation and permissions.",
            _plan_id_input({
                "actions": ACTION_SELECTION_SCHEMA,
                "view": {"enum": ["full", "summary", "schema"]},
            }),
            {"type": "object", "anyOf": [SAFE_CONTRACT_SCHEMA, SAFE_SCHEMA_CONTRACT_SCHEMA]},
            "get_plan_contract",
            READ_ANNOTATIONS,
        ),
        ToolDefinition(
            "upload_local_files",
            "Upload explicit readable nonempty regular files to the existing Plan, then finalize the batch. Returns the finalized inventory and context.contract; reuse them. If context is unavailable, follow its recovery read without repeating the successful upload. Inspect complete file evidence before filing; summaries and clipped excerpts are not complete inspection. Relative paths resolve from the adapter working directory and symlinks follow normal operating-system resolution. Paths appear in the MCP request transcript but never in results or upstream requests.",
            {
                "type": "object",
                "required": ["plan_id", "files"],
                "properties": {
                    "plan_id": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "files": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_UPLOAD_FILES,
                        "items": {
                            "type": "object",
                            "required": ["path"],
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": "An absolute path or a path relative to the adapter working directory.",
                                }
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            ENRICHED_UPLOAD_RESULT_SCHEMA,
            "upload",
            UPLOAD_ANNOTATIONS,
        ),
        ToolDefinition(
            "submit_plan",
            "Save an explicitly requested answer or a mutation proposal to the existing plan_id. Reuse for revisions: optional name and instructions update the current brief atomically with the complete proposal; original_brief is retained. Never executes workspace changes. The API validates against current permissions and state; no separate final contract read is needed. Give preview_url for authenticated review, never claim a proposal was applied.",
            {
                "type": "object",
                "required": ["plan_id", "contract_version", "proposal", "file_usage"],
                "properties": {
                    "plan_id": {"type": "string", "minLength": 1, "maxLength": 2048},
                    # The server validates candidate versions and per-file usage, returning
                    # field-level correction details to the client.
                    "contract_version": {"type": _WIRE["submitPlan"]["properties"]["contract_version"]["type"]},
                    "proposal": _WIRE["submitPlan"]["properties"]["proposal"],
                    "file_usage": {"type": "array", "items": {"type": "object"}},
                    "name": _WIRE["submitPlan"]["properties"]["name"],
                    "instructions": {
                        **_WIRE["submitPlan"]["properties"]["instructions"],
                        "maxLength": 65536,
                    },
                    "require_review": {
                        "type": "boolean",
                        "description": "When true, lock this Plan to browser review only.",
                    },
                },
                "additionalProperties": False,
            },
            SAFE_RECEIPT_SCHEMA,
            "submit",
            SUBMIT_ANNOTATIONS,
        ),
    )


def catalog_tools(catalog: Mapping[str, object]) -> tuple[ToolDefinition, ...]:
    """Validate and convert every REST read into one fixed-route MCP tool."""
    if json_size(catalog) > MAX_CATALOG_BYTES:
        raise TransportError(
            "catalog_too_large", "REST tool catalog exceeds the adapter limit."
        )
    expected_envelope = {
        "success": {"result": "<value matching the selected output_schema>"},
        "failure": {
            "error": {"code": "tool_error", "message": "<message>"},
            "request_id": "<request id>",
        },
    }
    if (
        set(catalog)
        != {
            "tools",
            "view",
            "selected_count",
            "reference_format",
            "execution_envelope",
        }
        or catalog.get("view") != "full"
        or catalog.get("reference_format") != "hash:<12-character-hash>"
        or catalog.get("execution_envelope") != expected_envelope
    ):
        raise TransportError(
            "invalid_catalog", "REST tool catalog metadata is incompatible."
        )
    entries = catalog.get("tools")
    if not isinstance(entries, list):
        raise TransportError(
            "invalid_catalog", "REST tool catalog is missing its tools array."
        )
    if len(entries) > MAX_TOOL_COUNT:
        raise TransportError(
            "catalog_too_large", "REST tool catalog contains too many tools."
        )
    selected_count = catalog.get("selected_count")
    if (
        isinstance(selected_count, bool)
        or not isinstance(selected_count, int)
        or selected_count != len(entries)
    ):
        raise TransportError(
            "invalid_catalog", "REST tool catalog count does not match its tools."
        )
    reserved = {tool.name for tool in lifecycle_tools()}
    seen: set[str] = set()
    result: list[ToolDefinition] = []
    total_schema_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise TransportError(
                "invalid_catalog", "REST tool definition must be an object."
            )
        if set(entry) != {
            "name",
            "description",
            "input_schema",
            "output_schema",
            "result_paths",
        }:
            raise TransportError(
                "invalid_catalog",
                "REST tool definition does not match the frozen catalog shape.",
            )
        name = entry.get("name")
        if (
            not isinstance(name, str)
            or len(name) > MAX_TOOL_NAME_CHARS
            or not TOOL_NAME_PATTERN.fullmatch(name)
        ):
            raise TransportError(
                "invalid_catalog", "REST catalog contains an invalid MCP tool name."
            )
        if name in seen or name in reserved:
            raise TransportError(
                "invalid_catalog",
                "REST catalog contains a duplicate or reserved tool name.",
            )
        seen.add(name)
        description = entry.get("description")
        if not isinstance(description, str):
            raise TransportError(
                "invalid_catalog", f"REST tool {name} has no description."
            )
        result_paths = entry.get("result_paths")
        if not isinstance(result_paths, dict):
            raise TransportError(
                "invalid_catalog", f"REST tool {name} has invalid result paths."
            )
        input_schema = inject_plan_id(entry.get("input_schema"))
        rest_output = validate_schema_document(entry.get("output_schema"))
        output_schema = (
            get_file_output_schema(rest_output) if name == "get_file" else rest_output
        )
        if name == "get_file":
            description = (
                description
                + " MCP include_original=true delivers small supported images/audio inline. "
                "Other originals, including PDFs and oversized media, return "
                "delivery.kind=download with original_file.download_url and expires_in. "
                "Use your HTTP/file or browsing tools to fetch and read that original; "
                "a URL or summary alone is not source inspection. Fetch with HTTPS GET "
                "without added Authorization, cookies, or redirects. On expiry, request "
                "get_file again with the same id. Keep temporary URLs out of answers, "
                "reports, and logs; use the ordinary file URL for citations. "
                "Inspect complete file evidence once; a summary or clipped excerpt "
                "is not complete inspection. Independent file reads can run in parallel. "
                + MCP_RESULT_INSTRUCTIONS
            )
        elif name == "query_workspace_filter":
            description += " " + MCP_RESULT_INSTRUCTIONS
        elif name == "search_entities":
            description += (
                " Returned hits are view-authorized; reuse their evidence. "
                "Load full details only for information missing from the results."
            )
        elif name in {"get_entity", "get_entities"}:
            description += (
                " Reuse attached Form schemas and other returned evidence; "
                "fetch again only for missing information or relevant changes."
            )
        for schema in (input_schema, output_schema):
            size = json_size(schema)
            if size > MAX_SCHEMA_BYTES:
                raise SchemaError(
                    "schema_too_large",
                    f"REST tool {name} schema exceeds the adapter limit.",
                )
            total_schema_bytes += size
        result.append(
            ToolDefinition(
                name,
                description,
                input_schema,
                output_schema,
                "read",
                READ_ANNOTATIONS,
                rest_output,
                deepcopy(result_paths),
            )
        )
    if total_schema_bytes > MAX_TOTAL_SCHEMA_BYTES:
        raise SchemaError(
            "catalog_too_large",
            "Published tool schemas exceed the aggregate adapter limit.",
        )
    return tuple(sorted(result, key=lambda item: item.name))


def build_tool_registry(catalog: Mapping[str, object], *, execute_plan: bool = False) -> dict[str, ToolDefinition]:
    tools = (*lifecycle_tools(), *catalog_tools(catalog), *((execution_tool(),) if execute_plan else ()))
    if execute_plan:
        updated_tools = []
        for tool in tools:
            if tool.name == "submit_plan":
                submit_schema = deepcopy(tool.input_schema)
                cast(dict[str, object], submit_schema["properties"]).update(
                    {
                        "execute": {
                            **_WIRE["submitPlan"]["properties"]["execute"],
                            "description": "When true, immediately start executing the submitted proposal (requires operation_id). Plans marked require_review or containing form schema changes, review items, or flagged issues still pause in ready state for browser review.",
                        },
                        "operation_id": {
                            **_WIRE["submitPlan"]["properties"]["operation_id"],
                            "description": "Stable operation ID (required when execute is true).",
                        },
                    }
                )
                tool = replace(
                    tool,
                    description=tool.description.replace(
                        "Give preview_url for authenticated review, never claim a proposal was applied.",
                        "Pass execute=true with a stable operation_id to run safe proposals immediately, or call execute_plan with the returned fingerprint; poll get_plan for the outcome. Respect user requests for review by setting require_review=true.",
                    ),
                    input_schema=submit_schema,
                )
            updated_tools.append(tool)
        tools = tuple(updated_tools)
    if len(tools) > MAX_TOOL_COUNT:
        raise TransportError(
            "catalog_too_large", "Published MCP catalog contains too many tools."
        )
    published_schema_bytes = sum(
        json_size(tool.input_schema) + json_size(tool.output_schema) for tool in tools
    )
    if published_schema_bytes > MAX_TOTAL_SCHEMA_BYTES:
        raise SchemaError(
            "catalog_too_large",
            "Published tool schemas exceed the aggregate adapter limit.",
        )
    return {tool.name: tool for tool in tools}


def execution_tool() -> ToolDefinition:
    return ToolDefinition(
        "execute_plan",
        "Execute an already submitted proposal when automatic plan execution is enabled for this connection. Use the proposal_fingerprint returned by submit_plan and a stable operation_id. Retry an uncertain request with those same values; poll get_plan for outcomes and never recreate successful actions. Plans marked require_review or containing form schema changes, review items, or flagged issues still require browser review. Current permissions and the exact proposal are checked again. This applies app records, not shell commands or deployments.",
        {
            **_plan_id_input(_WIRE["executePlan"]["properties"]),
            "required": ["plan_id", *_WIRE["executePlan"]["required"]],
        },
        {
            "type": "object",
            "required": ["plan", "operation"],
            "properties": {"plan": SAFE_PLAN_SCHEMA, "operation": SAFE_RECEIPT_SCHEMA["properties"]["operation"]},
            "additionalProperties": False,
        },
        "execute_plan",
        ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True),
    )
