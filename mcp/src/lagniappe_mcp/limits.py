"""Safety limits and the supported shared AI contract version."""

API_VERSION = "v1"
CONTRACT_VERSION_MIN = 7
CONTRACT_VERSION_MAX = 7

MAX_CATALOG_BYTES = 1 * 1024 * 1024
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

MCP_RESULT_INSTRUCTIONS = (
    "Inspect one complete text or structured representation of each result, "
    "plus any separately delivered media. Preserve counts, "
    "continuation/truncation flags, and partial errors. "
    "If host output clips, re-render the retained result in smaller sections, "
    "or repeat only the necessary read with the same plan_id; never start "
    "another Plan to change output formatting."
)

MCP_SUBMISSION_INSTRUCTIONS = (
    "Call submit_plan with this plan_id, contract_version, and a proposal "
    "matching proposal_schema. If it is null (summary view), first fetch "
    "get_plan_contract with the selected actions for their exact schemas. "
    "Optional name/instructions revise the current brief with the proposal. "
    "Keep this plan_id for investigation, submission, "
    "and revisions of the same request; starting again creates another report. "
    "The adapter fetches the current contract again "
    "before validating and submitting; do not add a separate final contract "
    "read solely to repeat that check. Refresh context after relevant workspace "
    "changes or a schema/permission error. The proposal_schema path is relative "
    "to this contract object, including when it is returned in context.contract. "
    + MCP_RESULT_INSTRUCTIONS
)

# Some hosts prepend this to every tool description. Keep tool-specific
# instructions in the descriptions and working context so short discovery
# excerpts still expose each tool's purpose.
MCP_INSTRUCTIONS = "Answer with plan-free reads; save Ask on request. Create/Organize require browser review."
