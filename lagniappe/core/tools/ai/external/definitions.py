"""External API definitions."""

from typing import TypedDict



from lagniappe.core.report_contracts import (
    MAX_PROPOSAL_ACTIONS as MAX_PROPOSAL_ACTIONS,
    UPLOAD_BATCH_ID_PATTERN as UPLOAD_BATCH_ID_PATTERN,
)


class ObjectSchema(TypedDict):
    type: str
    additionalProperties: bool
    required: list[str]
    properties: dict[str, dict[str, object]]



CONTRACT_VERSION = 10
MAX_INSTRUCTIONS_BYTES = 65536
MAX_PROPOSAL_BYTES = 1024 * 1024
MAX_PLAN_TOOL_CALLS = 100
MAX_PLAN_FILES = 20
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_TOTAL_FILE_BYTES = 50 * 1024 * 1024
MAX_VALIDATION_ERRORS = 20
MAX_PLAN_NAME_CHARACTERS = 120
DEFAULT_CONTRACT_VIEW = "summary"
CONTRACT_VIEWS = ("full", "summary", "schema")
SCHEMA_CONTRACT_FIELDS = (
    "contract_version", "submission_format", "proposal_schema", "file_usage_schema",
    "schema_scope", "schema_actions", "schema_instructions",
)
UPLOAD_INPUT_NAME = "agent-api-files"
REFERENCE_FIELDS = frozenset(
    {
        "category",
        "entity",
        "file",
        "form",
        "from_page",
        "from_task",
        "model",
        "page",
        "project",
        "task",
        "to_page",
        "to_task",
    }
)


def _text_bytes(value):
    return len(str(value or "").encode("utf-8"))


def create_plan_request_schema() -> ObjectSchema:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {
            "instructions": {
                "type": "string",
                "description": f"The question or requested work, limited to {MAX_INSTRUCTIONS_BYTES:,} UTF-8 bytes.",
            },
            "name": {
                "type": "string",
                "maxLength": MAX_PLAN_NAME_CHARACTERS,
                "description": "Optional browser-review label.",
            },
            "revises_plan_id": {
                "type": ["string", "null"],
                "minLength": 1,
                "description": "Optional creator-owned stopped execution to correct. Omit or use null for a new independent Plan.",
            },
            "require_review": {
                "type": "boolean",
                "description": "When true, lock this Plan to browser review only so external execution is rejected.",
            },
        },
    }


def submission_request_schema() -> ObjectSchema:
    from ..planner import file_usage_schema

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["contract_version", "proposal", "file_usage"],
        "properties": {
            "contract_version": {"type": "integer", "const": CONTRACT_VERSION},
            "proposal": {
                "type": "object",
                "description": "Must match the current plan contract's proposal_schema.",
            },
            "file_usage": file_usage_schema(),
            "name": {"type": "string", "minLength": 1, "maxLength": MAX_PLAN_NAME_CHARACTERS},
            "instructions": {
                "type": "string",
                "minLength": 1,
                "description": f"Updated current brief, at most {MAX_INSTRUCTIONS_BYTES} UTF-8 bytes. Original brief is retained; updates are atomic with proposal submission.",
            },
            "require_review": {
                "type": "boolean",
                "description": "When true, lock this submitted Plan to browser review only.",
            },
            "execute": {
                "type": "boolean",
                "description": "When true and execution is enabled for this connection, immediately start executing the submitted proposal (requires operation_id).",
            },
            "operation_id": {
                "type": "string",
                "pattern": r"^[A-Za-z0-9._-]{1,128}$",
                "description": "Stable client operation ID (1–128 ASCII letters, digits, dots, underscores, or hyphens) when execute is true.",
            },
        },
    }


def upload_file_schema() -> ObjectSchema:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["filename", "size"],
        "properties": {
            "filename": {"type": "string", "minLength": 1, "pattern": r"\S"},
            "content_type": {
                "type": "string", "minLength": 1, "pattern": r"\S",
                "default": "application/octet-stream",
            },
            "size": {
                "type": "integer", "minimum": 1, "maximum": MAX_FILE_BYTES,
                "description": "Exact file size in bytes.",
            },
        },
    }


def upload_batch_schema() -> dict[str, object]:
    return {
        "type": "string",
        "pattern": UPLOAD_BATCH_ID_PATTERN,
        "description": "Opaque server-issued identity for exactly one upload batch. Return it unchanged when finalizing that batch.",
    }


def upload_request_schema() -> ObjectSchema:
    return {
        "type": "object", "additionalProperties": False, "required": ["files"],
        "properties": {"files": {
            "type": "array", "minItems": 1, "maxItems": MAX_PLAN_FILES,
            "items": {"$ref": "#/components/schemas/UploadFile"},
        }},
    }


def finalize_request_schema() -> ObjectSchema:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["upload_batch_id"],
        "properties": {"upload_batch_id": upload_batch_schema()},
    }
