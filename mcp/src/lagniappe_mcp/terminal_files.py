"""Direct-to-storage transfers for local files selected by terminal clients.

Only this explicit upload manifest may expose validated storage write URLs.
Normal MCP results retain the shared adapter's private-data boundary.
"""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from lagniappe_mcp.adapter import AdapterResult, _reject_private_model_data
from lagniappe_mcp.catalog import ENRICHED_UPLOAD_RESULT_SCHEMA, UPLOAD_RESULT_SCHEMA
from lagniappe_mcp.errors import AdapterError, TransportError
from lagniappe_mcp.files import (
    _preflight_contract,
    _preflight_requested_count,
    _validate_sessions,
)
from lagniappe_mcp.limits import (
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_FILE_BYTES,
    MAX_UPLOAD_TOTAL_BYTES,
)
from lagniappe_mcp.schema import validate_value
from lagniappe_mcp.url_security import quote_path_segment


FILE_SCHEMA = {
    "type": "object",
    "required": ["filename", "content_type", "size"],
    "properties": {
        "filename": {"type": "string", "minLength": 1, "maxLength": 1024},
        "content_type": {"type": "string", "minLength": 1, "maxLength": 256},
        "size": {"type": "integer", "minimum": 1, "maximum": MAX_UPLOAD_FILE_BYTES},
    },
    "additionalProperties": False,
}
FILES_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_UPLOAD_FILES,
    "items": FILE_SCHEMA,
}
PLAN_ID_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 1024}
BATCH_ID_SCHEMA = {"type": "string", "minLength": 16, "maxLength": 128}
MANIFEST_SCHEMA = {
    "type": "object",
    "required": ["plan_id", "upload_batch_id", "files", "uploads"],
    "properties": {
        "plan_id": PLAN_ID_SCHEMA,
        "upload_batch_id": BATCH_ID_SCHEMA,
        "files": FILES_SCHEMA,
        "uploads": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_UPLOAD_FILES,
            "items": {
                "type": "object",
                "required": ["index", "filename", "session_url", "chunk_size"],
                "properties": {
                    "index": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": MAX_UPLOAD_FILES - 1,
                    },
                    "filename": FILE_SCHEMA["properties"]["filename"],
                    "session_url": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 8192,
                    },
                    "chunk_size": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


# @testable false
# @covered-by mcp/src/lagniappe_mcp/terminal_files.py::prepare_uploads
def tool_definitions(local):
    return (
        replace(
            local,
            name="prepare_file_uploads",
            kind="terminal_prepare",
            description=(
                "Terminal clients only: prepare direct storage uploads for files the user selected on this machine. "
                "Inspect each selected regular file locally for its base filename, MIME content_type and exact byte size. "
                "No Lagniappe package, repository, local MCP server or upload helper is needed. "
                "This tool returns server-issued Storage session URLs. For each uploads[index], send the corresponding "
                "whole file directly to session_url in one HTTP PUT using an ordinary HTTP client such as "
                "curl --upload-file PATH, with Content-Length equal to the declared size and the declared Content-Type. "
                "chunk_size is only a hint for optional chunked transfers; a single whole-file PUT is supported. "
                "Use HTTPS without redirects or added Authorization/cookies; disable curl's default config with --disable. "
                "Keep URLs in private temporary files or process input (mode 600 if saved), never in final answers or reports. "
                "Require HTTP 200 or 201 for every file before calling finalize_file_uploads with this plan_id and "
                "upload_batch_id. HTTP 308 means incomplete, not success; do not finalize after an error or timeout. "
                "No local path or file bytes are sent to MCP. "
                "ChatGPT conversation attachments use upload_files instead."
            ),
            input_schema={
                "type": "object",
                "required": ["plan_id", "files"],
                "properties": {"plan_id": PLAN_ID_SCHEMA, "files": FILES_SCHEMA},
                "additionalProperties": False,
            },
            output_schema=MANIFEST_SCHEMA,
        ),
        replace(
            local,
            name="finalize_file_uploads",
            kind="terminal_finalize",
            description=(
                "Terminal clients: finalize the exact batch returned by prepare_file_uploads after Storage "
                "returned HTTP 200 or 201 for every file's direct upload. Returns authoritative file references "
                "and refreshed Organize guidance. Keep the same plan_id. Never finalize an incomplete transfer. "
                "Workspace changes still require browser review."
            ),
            input_schema={
                "type": "object",
                "required": ["plan_id", "upload_batch_id"],
                "properties": {
                    "plan_id": PLAN_ID_SCHEMA,
                    "upload_batch_id": BATCH_ID_SCHEMA,
                },
                "additionalProperties": False,
            },
            output_schema=ENRICHED_UPLOAD_RESULT_SCHEMA,
        ),
    )


# @testable true
# @tests tests_unit/test_033e_mcp_terminal_files.py::test_manifest_allows_only_validated_storage_writes_and_never_oauth_secrets
# @matrix mcp-upload : terminal validation token-separation
def validate_manifest(value, *, bearer):
    validate_value(MANIFEST_SCHEMA, value, phase="upload_manifest")
    files = [SimpleNamespace(**item) for item in value["files"]]
    if sum(item.size for item in files) > MAX_UPLOAD_TOTAL_BYTES:
        raise TransportError(
            "invalid_upload_session", "The upload manifest exceeds the batch limit."
        )
    sessions = _validate_sessions(value, value["plan_id"], files)
    # Deliberate, narrow capability boundary: the fully validated URLs may
    # carry upload_id; nothing else may carry transport data or either bearer.
    screened = deepcopy(value)
    for entry in screened["uploads"]:
        url = entry.pop("session_url")
        if bearer in url:
            raise TransportError(
                "unsafe_transport_extension",
                "Upload instructions contain private authentication data.",
            )
    _reject_private_model_data(screened, bearer=bearer)
    return sessions


# @testable true
# @tests tests_unit/test_033c_mcp_server.py::test_remote_attachment_uses_shared_upload_and_preserves_pending_failure
# @matrix mcp-upload : terminal upload-batch-identity safe-result
async def prepare_uploads(adapter, arguments):
    plan_id, files = arguments["plan_id"], arguments["files"]
    contract = await adapter._load_contract(plan_id)
    _preflight_requested_count(contract, files)
    _preflight_contract(contract, [SimpleNamespace(**item) for item in files])
    created, _ = await adapter.rest.request_json(
        "POST",
        f"plans/{quote_path_segment(plan_id)}/uploads",
        body={"files": files},
    )
    if not isinstance(created, dict):
        raise TransportError(
            "invalid_upload_session", "The API returned invalid upload instructions."
        )
    # Validate the upstream envelope before projecting; unknown fields may
    # evolve, but they are never passed through to the terminal.
    batch, sessions = _validate_sessions(
        created, plan_id, [SimpleNamespace(**item) for item in files]
    )
    return AdapterResult(
        {
            "plan_id": plan_id,
            "upload_batch_id": batch,
            "files": deepcopy(files),
            "uploads": [
                {
                    "index": index,
                    "filename": item["filename"],
                    "session_url": session[0],
                    "chunk_size": session[1],
                }
                for index, (item, session) in enumerate(
                    zip(files, sessions, strict=True)
                )
            ],
        }
    )


# @testable true
# @tests tests_unit/test_033c_mcp_server.py::test_remote_attachment_uses_shared_upload_and_preserves_pending_failure
# @tests tests_unit/test_033e_mcp_terminal_files.py::test_terminal_finalize_never_accepts_incomplete_or_replaced_batch
# @matrix mcp-upload : terminal finalize-once upload-batch-identity safe-result
async def finalize_uploads(adapter, arguments):
    plan_id, batch = arguments["plan_id"], arguments["upload_batch_id"]
    route = f"plans/{quote_path_segment(plan_id)}"
    try:
        raw, _ = await adapter.rest.request_json(
            "POST", route + "/uploads/finalize", body={"upload_batch_id": batch}
        )
    except TransportError as error:
        if error.code not in {"api_timeout", "api_unavailable"}:
            raise
        # The write may already have committed. Read once; never replay it.
        raw, _ = await adapter.rest.request_json("GET", route)
    if (
        not isinstance(raw, dict)
        or raw.get("id") != plan_id
        or raw.get("uploads_pending") is not False
        or raw.get("upload_batch_id") != batch
    ):
        raise AdapterError(
            "upload_finalization_unknown",
            "The API did not confirm this upload batch. Check the existing Plan before retrying.",
        )
    value = {
        "plan": adapter._safe_plan(raw, expected_plan_id=plan_id),
        "upload_inventory": raw.get("files"),
    }
    validate_value(UPLOAD_RESULT_SCHEMA, value, phase="upstream_output")
    return await adapter._with_lifecycle_context(value, plan_id=plan_id)
