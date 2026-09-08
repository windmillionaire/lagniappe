"""Live REST catalog conversion and explicit lifecycle schemas."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from mcp import Tool
from mcp_types import ToolAnnotations
from mcp_types.version import LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS

from .errors import SchemaError, TransportError
from .limits import (
    CONTRACT_VERSION_MAX,
    CONTRACT_VERSION_MIN,
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
GET_FILE_SAFE_PROPERTIES: dict[str, dict[str, Any]] = {
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

PLAN_FILE_SCHEMA = {
    "type": "object",
    "required": ["ref", "name", "filename", "mimetype", "size"],
    "properties": {
        "ref": {"type": "string", "pattern": r"^hash:[A-Za-z0-9_-]{12}$"},
        "name": {"type": "string"},
        "filename": {"type": "string"},
        "mimetype": {"type": "string"},
        "size": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}

SAFE_PLAN_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "status",
        "tool",
        "name",
        "instructions",
        "files",
        "uploads_pending",
        "contract_version",
        "preview_url",
        "review_url",
    ],
    "properties": {
        "id": {"type": "string"},
        "status": {
            "enum": [
                "draft",
                "ready",
                "running",
                "complete",
                "failed",
                "undoing",
                "undo_failed",
            ]
        },
        "tool": {"enum": ["ask", "create", "organize"]},
        "name": {"type": "string"},
        "instructions": {"type": "string"},
        "files": {
            "type": "array",
            "maxItems": MAX_UPLOAD_FILES,
            "items": PLAN_FILE_SCHEMA,
        },
        "uploads_pending": {"type": "boolean"},
        "contract_version": {
            "type": "integer",
            "minimum": CONTRACT_VERSION_MIN,
            "maximum": CONTRACT_VERSION_MAX,
        },
        "preview_url": {"type": "string"},
        "review_url": {"type": "string"},
        "proposal": {"type": ["object", "null"]},
        "execution": {"type": ["object", "null"]},
        "original_brief": {"type": ["object", "null"]},
    },
    "additionalProperties": False,
}

ACTOR_SCHEMA = {
    "type": "object",
    "required": ["user", "credential", "capabilities"],
    "properties": {
        "user": {
            "type": "object",
            "required": ["name", "hash", "timezone", "personal_page"],
            "properties": {
                "name": {"type": "string"},
                "hash": {"type": "string"},
                "timezone": {"type": "string"},
                "personal_page": {
                    "type": "object",
                    "required": [
                        "kind",
                        "hash",
                        "name",
                        "url",
                        "can_view",
                        "can_edit",
                    ],
                    "properties": {
                        "kind": {"const": "page"},
                        "hash": {"type": "string"},
                        "name": {"type": ["string", "null"]},
                        "url": {"type": "string"},
                        "can_view": {"type": "boolean"},
                        "can_edit": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "credential": {
            "type": "object",
            "required": [
                "active",
                "display_prefix",
                "issued_at",
                "expires_at",
                "generation",
            ],
            "properties": {
                "active": {"type": "boolean"},
                "display_prefix": {"type": ["string", "null"]},
                "issued_at": {"type": ["string", "null"], "format": "date-time"},
                "expires_at": {"type": ["string", "null"], "format": "date-time"},
                "generation": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        },
        "capabilities": {
            "type": "object",
            "required": ["ask", "create", "organize"],
            "properties": {
                "ask": {"type": "boolean"},
                "create": {"type": "boolean"},
                "organize": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

SAFE_RECEIPT_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "status",
        "preview_url",
        "review_url",
        "contract_version",
        "proposal_fingerprint",
    ],
    "properties": {
        "id": {"type": "string"},
        "status": {"enum": ["ready", "complete"]},
        "preview_url": {"type": "string"},
        "review_url": {"type": "string"},
        "contract_version": {
            "type": "integer",
            "minimum": CONTRACT_VERSION_MIN,
            "maximum": CONTRACT_VERSION_MAX,
        },
        "proposal_fingerprint": {
            "oneOf": [
                {"type": "string", "minLength": 1},
                {"type": "null"},
            ]
        },
    },
    "additionalProperties": False,
}

SAFE_CONTRACT_SCHEMA = {
    "type": "object",
    "required": [
        "contract_version",
        "tool",
        "current_date",
        "timezone",
        "personal_page",
        "proposal_schema",
        "permissions",
        "required_file_refs",
        "upload_inventory",
        "file_checklist",
        "guidance_requirements",
        "uploads_supported",
        "workflow_rules",
        "reference_rules",
        "limits",
        "payload_sizes",
        "mcp_submission",
    ],
    "properties": {
        "contract_version": {
            "type": "integer",
            "minimum": CONTRACT_VERSION_MIN,
            "maximum": CONTRACT_VERSION_MAX,
        },
        "tool": {"enum": ["ask", "create", "organize"]},
        "current_date": {"type": "string", "format": "date"},
        "timezone": {"type": "string"},
        "personal_page": {"type": "object"},
        "proposal_schema": {"type": ["object", "null"]},
        "schema_scope": {"enum": ["full", "selected", "summary"]},
        "schema_actions": {"type": "array", "items": {"type": "string"}},
        "schema_instructions": {"type": "string"},
        "permissions": {"type": "object"},
        "required_file_refs": {"type": "array", "items": {"type": "string"}},
        "upload_inventory": {"type": ["object", "null"]},
        "file_checklist": {"type": "array", "items": {"type": "object"}},
        "guidance_requirements": {"type": "object"},
        "uploads_supported": {"type": "boolean"},
        "workflow_rules": {"type": "array", "items": {"type": "string"}},
        "reference_rules": {"type": "array", "items": {"type": "string"}},
        "limits": {"type": "object"},
        "payload_sizes": {"type": "object"},
        "mcp_submission": {
            "type": "object",
            "required": [
                "contract_version",
                "proposal",
                "proposal_schema",
                "instructions",
            ],
            "properties": {
                "contract_version": {"type": "integer"},
                "proposal": {"type": "object"},
                "proposal_schema": {
                    "const": "$.proposal_schema",
                    "description": "Path relative to this contract object, not the enclosing lifecycle result.",
                },
                "instructions": {"const": MCP_SUBMISSION_INSTRUCTIONS},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

SCHEMA_CONTRACT_KEYS = (
    "contract_version", "tool", "proposal_schema", "schema_scope",
    "schema_actions", "schema_instructions", "mcp_submission",
)
SAFE_SCHEMA_CONTRACT_SCHEMA = {
    "type": "object",
    "required": list(SCHEMA_CONTRACT_KEYS),
    "properties": {
        key: ({"type": "object"} if key == "proposal_schema" else SAFE_CONTRACT_SCHEMA["properties"][key])
        for key in SCHEMA_CONTRACT_KEYS
    },
    "additionalProperties": False,
}


REST_CONTRACT_SCHEMA = {
    "type": "object",
    "required": [
        *[
            item
            for item in SAFE_CONTRACT_SCHEMA["required"]
            if item != "mcp_submission"
        ],
        "submission_format",
    ],
    "properties": {
        **{
            key: value
            for key, value in SAFE_CONTRACT_SCHEMA["properties"].items()
            if key != "mcp_submission"
        },
        "submission_format": {
            "type": "object",
            "required": ["method", "url", "contract_version", "body", "rule"],
            "properties": {
                "method": {"const": "POST"},
                "url": {"type": "string", "format": "uri"},
                "contract_version": {
                    "type": "integer",
                    "minimum": CONTRACT_VERSION_MIN,
                    "maximum": CONTRACT_VERSION_MAX,
                },
                "body": {
                    "type": "object",
                    "required": ["contract_version", "proposal"],
                    "properties": {
                        "contract_version": {
                            "type": "integer",
                            "minimum": CONTRACT_VERSION_MIN,
                            "maximum": CONTRACT_VERSION_MAX,
                        },
                        "proposal": {"type": "object", "maxProperties": 0},
                    },
                    "additionalProperties": False,
                },
                "rule": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

REST_SCHEMA_CONTRACT_KEYS = (
    *[key for key in SCHEMA_CONTRACT_KEYS if key != "mcp_submission"],
    "submission_format",
)
REST_SCHEMA_CONTRACT_SCHEMA = {
    "type": "object",
    "required": list(REST_SCHEMA_CONTRACT_KEYS),
    "properties": {
        key: ({"type": "object"} if key == "proposal_schema" else REST_CONTRACT_SCHEMA["properties"][key])
        for key in REST_SCHEMA_CONTRACT_KEYS
    },
    "additionalProperties": False,
}


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
    "minItems": 1,
    "maxItems": 100,
    "items": {"type": "string", "maxLength": 100, "pattern": "^[a-z][a-z0-9_]*$"},
}

LIFECYCLE_CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "contract": SAFE_CONTRACT_SCHEMA,
        "guidelines": {"type": "object"},
        "recovery": {
            "type": "object",
            "required": ["tool", "arguments", "message"],
            "properties": {
                "tool": {"enum": ["get_plan_contract", "get_guidelines"]},
                "arguments": {
                    "type": "object",
                    "required": ["plan_id"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "task": {"const": "organize"},
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
        {"required": ["guidelines"]},
        {"required": ["recovery"]},
    ],
    "additionalProperties": False,
}
START_RESULT_SCHEMA = {
    **SAFE_PLAN_SCHEMA,
    "required": [*SAFE_PLAN_SCHEMA["required"], "context"],
    "properties": {
        **SAFE_PLAN_SCHEMA["properties"],
        "context": LIFECYCLE_CONTEXT_SCHEMA,
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


# @testable false
# @covered-by mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
def _plan_input_schema(*, selected_actions: bool = False) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["instructions"],
        "properties": {
            "instructions": {
                "type": "string",
                "minLength": 1,
                "pattern": r"\S",
            },
            "name": {"type": "string", "maxLength": 120},
            **(
                {
                    "actions": {
                        **ACTION_SELECTION_SCHEMA,
                        "description": "Known action types whose exact permitted schemas should be returned in context.contract, for example [create_task]. Omit for a summary without schemas.",
                    }
                }
                if selected_actions
                else {}
            ),
        },
        "additionalProperties": False,
    }


# @testable false
# @covered-by mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
def _plan_id_input() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["plan_id"],
        "properties": {
            "plan_id": {"type": "string", "minLength": 1, "maxLength": 2048}
        },
        "additionalProperties": False,
    }


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_get_file_schema_projects_every_transport_extension
def get_file_output_schema(rest_schema: dict[str, Any]) -> dict[str, Any]:
    """Project signed REST transport fields out of the get_file result."""
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
    # REST deliberately permits transport extensions here. MCP exposes only
    # stable descriptive fields and consumes every signed field privately.
    original["additionalProperties"] = False
    properties["delivery"] = {
        "type": "object",
        "required": ["kind"],
        "properties": {
            "kind": {"enum": ["none", "image", "audio"]},
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
                "else": {"required": ["mime_type", "size_bytes", "content_index"]},
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
    # REST permits evolving entity metadata, but this boundary cannot safely
    # infer whether an arbitrary new field is descriptive or a signed transport
    # capability. New fields therefore require an explicit adapter release.
    result.pop("propertyNames", None)
    result["additionalProperties"] = False
    return validate_schema_document(result)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_server_presents_matching_schemas_and_values_for_each_protocol
@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    kind: str
    annotations: ToolAnnotations
    rest_output_schema: dict[str, Any] | None = None
    result_paths: dict[str, Any] | None = None

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/catalog.py::ToolDefinition
    def requires_result_wrapper(self, protocol_version: str) -> bool:
        # Select by the declared schema, including nullable/union roots, so
        # every successful value matches the same advertised result shape.
        return (
            protocol_version not in MODERN_PROTOCOL_VERSIONS
            and self.output_schema.get("type") != "object"
        )

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/catalog.py::ToolDefinition
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
            meta=(
                {"lagniappe/resultPaths": result_paths}
                if result_paths is not None
                else None
            ),
        )


# @testable false
# @covered-by mcp/src/lagniappe_mcp/catalog.py::ToolDefinition
def _wrap_result_paths(value: Any) -> Any:
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


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
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
            "Get lightweight guidance and personal Page context for answering or retrieving tasks without saving a report. The client model answers using plan-free read tools; this does not call a server model or create a Plan. Answer in chat first and offer to save afterward. Only when the user wants to save, use start_ask then submit_plan. Reuse this context during the conversation.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            {
                "type": "object",
                "required": [
                    "current_date",
                    "timezone",
                    "personal_page",
                    "report_created",
                    "workflow_rules",
                ],
                "properties": {
                    "current_date": {"type": "string"},
                    "timezone": {"type": "string"},
                    "personal_page": {"type": "object"},
                    "report_created": {"const": False},
                    "workflow_rules": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
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
            "start_ask",
            f"Start a durable Ask report only when the user requests saving an answer. For ordinary questions and task lookups use answer_question and plan-free reads first. {common_start} Returns context.contract; submit the already-agreed answer without regenerating it.",
            _plan_input_schema(),
            START_RESULT_SCHEMA,
            "start_ask",
            START_ANNOTATIONS,
        ),
        ToolDefinition(
            "start_create",
            f"Start a Create Plan to create pages, tasks, or workspace structure without uploads. Use start_organize to update existing records, including completing tasks or patching submissions. {common_start} Pass actions=[\"create_task\"] or other known action names to receive their exact permitted schemas with the initial context.contract. Omit actions for a summary of permissions and allowed actions. Reuse supplied schemas; get_plan_contract can load additional schemas later on this same Plan. {review_only}",
            _plan_input_schema(selected_actions=True),
            START_RESULT_SCHEMA,
            "start_create",
            START_ANNOTATIONS,
        ),
        ToolDefinition(
            "start_organize",
            f"Start an Organize Plan to update existing records (complete tasks, patch submissions, rename or move records) or inspect and place uploaded files. Remote updates do not require a file. {common_start} Returns compact context.contract with allowed action names; fetch get_plan_contract(actions=[...]) for selected details. Discover exact targets with read tools before proposing updates. For uploads, read get_guidelines(task=organize), inspect complete evidence, and summarize and place every finalized file. {review_only}",
            _plan_input_schema(),
            START_RESULT_SCHEMA,
            "start_organize",
            START_ANNOTATIONS,
        ),
        ToolDefinition(
            "get_plan",
            "Return current Plan state, current/original brief, round-trippable proposal, and bounded execution outcomes with currently viewable result entities. Use the existing plan_id to recover or revise; do not create another Plan. Entity null means unavailable, not proof an action never ran.",
            _plan_id_input(),
            SAFE_PLAN_SCHEMA,
            "get_plan",
            READ_ANNOTATIONS,
        ),
        ToolDefinition(
            "get_plan_contract",
            "Load exact schemas for selected allowed actions. Use view=schema for a follow-up after receiving the plan context: it omits repeated workflow/inventory guidance. full includes context and, without actions, all schemas. summary includes context without schemas. Reuse selected schemas; refresh context for changed state/permissions. submit_plan independently validates against the full current contract.",
            {
                **_plan_id_input(),
                "properties": {
                    **_plan_id_input()["properties"],
                    "actions": ACTION_SELECTION_SCHEMA,
                    "view": {"enum": ["full", "summary", "schema"]},
                },
            },
            {"type": "object", "anyOf": [SAFE_CONTRACT_SCHEMA, SAFE_SCHEMA_CONTRACT_SCHEMA]},
            "get_plan_contract",
            READ_ANNOTATIONS,
        ),
        ToolDefinition(
            "upload_local_files",
            "Upload explicit readable nonempty regular files to the existing Organize Plan, then finalize the batch. Returns the finalized inventory and context.contract; reuse them. If context is unavailable, follow its recovery read without repeating the successful upload. Inspect complete file evidence before filing; summaries and clipped excerpts are not complete inspection. Relative paths resolve from the adapter working directory and symlinks follow normal operating-system resolution. Paths appear in the MCP request transcript but never in results or upstream requests.",
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
            "Save an explicitly requested Ask answer or a Create/Organize proposal to the existing plan_id. Reuse for revisions: optional name and instructions update the current brief atomically with the complete proposal; original_brief is retained. Never executes workspace changes. Validates against the fresh full contract; no separate final contract read is needed. Give preview_url for authenticated review, never claim a proposal was applied.",
            {
                "type": "object",
                "required": ["plan_id", "contract_version", "proposal"],
                "properties": {
                    "plan_id": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "contract_version": {"type": "integer"},
                    "proposal": {"type": "object"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "instructions": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 65536,
                    },
                },
                "additionalProperties": False,
            },
            SAFE_RECEIPT_SCHEMA,
            "submit",
            SUBMIT_ANNOTATIONS,
        ),
    )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
def catalog_tools(catalog: dict[str, Any]) -> tuple[ToolDefinition, ...]:
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
                + " MCP projects signed transport fields out of the result. "
                "include_original=true delivers only bounded supported image/audio content. "
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
        elif name == "get_entity":
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


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
def build_tool_registry(catalog: dict[str, Any]) -> dict[str, ToolDefinition]:
    tools = (*lifecycle_tools(), *catalog_tools(catalog))
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
