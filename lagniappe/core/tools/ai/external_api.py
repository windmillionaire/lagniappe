"""Stable facade for provider-free external agent contracts and plans.

Implementations live in the external package; import concrete owners there when
composing services or replacing their collaborators in tests.
"""

from .external.contracts import (
    answer_context as answer_context,
    client_skill_markdown as client_skill_markdown,
    plan_contract as plan_contract,
    report_file_inventory as report_file_inventory,
    report_file_references as report_file_references,
    user_timezone_name as user_timezone_name,
)
from .external.definitions import (
    CONTRACT_VERSION as CONTRACT_VERSION,
    MAX_FILE_BYTES as MAX_FILE_BYTES,
    MAX_INSTRUCTIONS_BYTES as MAX_INSTRUCTIONS_BYTES,
    MAX_PLAN_FILES as MAX_PLAN_FILES,
    MAX_PLAN_TOOL_CALLS as MAX_PLAN_TOOL_CALLS,
    MAX_PROPOSAL_ACTIONS as MAX_PROPOSAL_ACTIONS,
    MAX_PROPOSAL_BYTES as MAX_PROPOSAL_BYTES,
    MAX_TOTAL_FILE_BYTES as MAX_TOTAL_FILE_BYTES,
    MAX_VALIDATION_ERRORS as MAX_VALIDATION_ERRORS,
    REFERENCE_FIELDS as REFERENCE_FIELDS,
    UPLOAD_BATCH_ID_PATTERN as UPLOAD_BATCH_ID_PATTERN,
)
from .external.plans import (
    create_plan as create_plan,
    load_plan as load_plan,
    require_draft as require_draft,
    require_submission_available as require_submission_available,
    submit_plan as submit_plan,
    submit_plan_request as submit_plan_request,
)
from .external.presentation import (
    absolute_entity_links as absolute_entity_links,
    public_execution_receipt as public_execution_receipt,
    public_plan_proposal as public_plan_proposal,
)
from .external.uploads import (
    bind_upload_file_identities as bind_upload_file_identities,
    create_upload_sessions as create_upload_sessions,
    current_upload_batch_id as current_upload_batch_id,
    finalize_upload_batch as finalize_upload_batch,
    finalize_uploads as finalize_uploads,
    prepare_upload_manifest as prepare_upload_manifest,
    require_uploads_available as require_uploads_available,
)
from .external.validation import (
    submission_validation_errors as submission_validation_errors,
    validate_external_proposal as validate_external_proposal,
)
from .planner import file_usage_schema as file_usage_schema
from .references import personal_page_reference as personal_page_reference
from .reporting.contracts.schema import (
    external_report_proposal_response_schema as external_report_proposal_response_schema,
)

__all__ = [
    "CONTRACT_VERSION",
    "MAX_FILE_BYTES",
    "MAX_INSTRUCTIONS_BYTES",
    "MAX_PLAN_FILES",
    "MAX_PLAN_TOOL_CALLS",
    "MAX_PROPOSAL_ACTIONS",
    "MAX_PROPOSAL_BYTES",
    "MAX_TOTAL_FILE_BYTES",
    "MAX_VALIDATION_ERRORS",
    "REFERENCE_FIELDS",
    "UPLOAD_BATCH_ID_PATTERN",
    "absolute_entity_links",
    "answer_context",
    "bind_upload_file_identities",
    "client_skill_markdown",
    "create_plan",
    "create_upload_sessions",
    "current_upload_batch_id",
    "external_report_proposal_response_schema",
    "file_usage_schema",
    "finalize_upload_batch",
    "finalize_uploads",
    "load_plan",
    "personal_page_reference",
    "plan_contract",
    "prepare_upload_manifest",
    "public_execution_receipt",
    "public_plan_proposal",
    "report_file_inventory",
    "report_file_references",
    "require_draft",
    "require_submission_available",
    "require_uploads_available",
    "submission_validation_errors",
    "submit_plan",
    "submit_plan_request",
    "user_timezone_name",
    "validate_external_proposal",
]
