"""Frozen safety limits for the first MCP trial release."""

API_VERSION = "v1"
CONTRACT_VERSION_MIN = 6
CONTRACT_VERSION_MAX = 6

MAX_CATALOG_BYTES = 1 * 1024 * 1024
MAX_OPENAPI_BYTES = 2 * 1024 * 1024
MAX_TOOL_COUNT = 64
MAX_TOOL_NAME_CHARS = 64
MAX_SCHEMA_BYTES = 256 * 1024
MAX_TOTAL_SCHEMA_BYTES = 2 * 1024 * 1024
MAX_STRUCTURED_RESULT_BYTES = 2 * 1024 * 1024
MAX_TEXT_FALLBACK_BYTES = 2 * 1024 * 1024
MAX_COMPLETE_FRAME_BYTES = 12 * 1024 * 1024
MAX_REQUEST_FRAME_BYTES = 4 * 1024 * 1024
MAX_REQUEST_ID_BYTES = 256
MAX_ERROR_BYTES = 4 * 1024
MAX_STDERR_BYTES = 8 * 1024
MAX_STARTUP_DIAGNOSTIC_BYTES = 8 * 1024
MAX_MEDIA_RAW_BYTES = 4 * 1024 * 1024

CONNECT_TIMEOUT_SECONDS = 5.0
RESPONSE_TIMEOUT_SECONDS = 30.0
MEDIA_TIMEOUT_SECONDS = 60.0
UPLOAD_TIMEOUT_SECONDS = 300.0
UPLOAD_OPERATION_TIMEOUT_SECONDS = 270.0
MAX_REDIRECTS = 0
MAX_UPLOAD_CHUNK_BYTES = 32 * 1024 * 1024
MIN_UPLOAD_CHUNK_BYTES = 256 * 1024
MAX_UPLOAD_CHUNKS_PER_FILE = 128
MAX_UPLOAD_FILES = 20
MAX_UPLOAD_FILE_BYTES = 30 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_RECOVERY_ATTEMPTS = 2
MAX_UPLOAD_STATUS_PROBES = 3

SUPPORTED_SCHEMA_DIALECTS = frozenset(
    {
        "https://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft/2020-12/schema#",
    }
)

MCP_INSTRUCTIONS = (
    "Use start_ask for a question, start_organize when files must be placed, "
    "and start_create for a requested fileless workspace change. Create and "
    "Organize submissions only create a browser-reviewable report; they never "
    "execute workspace changes. Use the plan_id returned by the chosen starter "
    "for reads, contracts, uploads, and submission. Inspect permitted evidence, "
    "follow the current plan contract, and send the user the preview link for "
    "authenticated review. Never claim a proposal was applied."
)
