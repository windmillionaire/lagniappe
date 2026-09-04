"""Live REST catalog conversion and explicit lifecycle schemas."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from mcp import Tool
from mcp_types import ToolAnnotations

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
)
from .schema import inject_plan_id, json_size, validate_schema_document


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
        "proposal_schema": {"type": "object"},
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
                "proposal_schema": {"const": "$.proposal_schema"},
                "instructions": {
                    "const": "Call submit_plan with this plan_id, contract_version, and a proposal matching proposal_schema."
                },
            },
            "additionalProperties": False,
        },
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


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
def _plan_input_schema() -> dict[str, Any]:
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
        },
        "additionalProperties": False,
    }


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
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
# @tests tests_unit/test_033_mcp_adapter.py::test_low_level_server_negotiates_modern_types_without_resources
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
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/catalog.py::ToolDefinition
    def as_mcp_tool(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            annotations=self.annotations,
            meta=(
                {"lagniappe/resultPaths": deepcopy(self.result_paths)}
                if self.result_paths is not None
                else None
            ),
        )


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
# @tests tests_unit/test_033_mcp_adapter.py::test_low_level_server_negotiates_modern_types_without_resources
def lifecycle_tools() -> tuple[ToolDefinition, ...]:
    common_start = "Submission creates a browser-reviewable report and never executes workspace changes."
    return (
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
            "Start an Ask Plan for a question. Ask is read-only.",
            _plan_input_schema(),
            SAFE_PLAN_SCHEMA,
            "start_ask",
            START_ANNOTATIONS,
        ),
        ToolDefinition(
            "start_create",
            f"Start a Create Plan for a requested fileless workspace change. {common_start}",
            _plan_input_schema(),
            SAFE_PLAN_SCHEMA,
            "start_create",
            START_ANNOTATIONS,
        ),
        ToolDefinition(
            "start_organize",
            f"Start an Organize Plan when one or more files must be inspected and placed. {common_start}",
            _plan_input_schema(),
            SAFE_PLAN_SCHEMA,
            "start_organize",
            START_ANNOTATIONS,
        ),
        ToolDefinition(
            "get_plan",
            "Return current Plan state and its round-trippable proposal when present.",
            _plan_id_input(),
            SAFE_PLAN_SCHEMA,
            "get_plan",
            READ_ANNOTATIONS,
        ),
        ToolDefinition(
            "get_plan_contract",
            "Return the current safe MCP projection of the Plan contract. REST submission transport stays private; use submit_plan.",
            _plan_id_input(),
            SAFE_CONTRACT_SCHEMA,
            "get_plan_contract",
            READ_ANNOTATIONS,
        ),
        ToolDefinition(
            "upload_local_files",
            "Upload explicit readable nonempty regular files to one Organize Plan, then finalize the batch. Relative paths resolve from the adapter working directory and symlinks follow normal operating-system resolution. Paths appear in the MCP request transcript but never in results or upstream requests.",
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
            UPLOAD_RESULT_SCHEMA,
            "upload",
            UPLOAD_ANNOTATIONS,
        ),
        ToolDefinition(
            "submit_plan",
            "Validate a complete proposal against the freshly fetched contract, then publish a browser-reviewable result. This replaces any prior saved proposal but never executes it.",
            {
                "type": "object",
                "required": ["plan_id", "contract_version", "proposal"],
                "properties": {
                    "plan_id": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "contract_version": {"type": "integer"},
                    "proposal": {"type": "object"},
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
        set(catalog) != {
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
                "include_original=true delivers only bounded supported image/audio content."
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
