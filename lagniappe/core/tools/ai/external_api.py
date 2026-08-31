"""Provider-free plan workspaces for the external agent REST API."""

from datetime import datetime, timezone
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import get as database_get

from .references import HASH_PREFIXED_ID_REGEX, HASH_REFERENCE_REGEX, hash_reference
from .reporting.uploads import (
    finalize_report_upload_manifest,
    prepare_report_upload_manifest,
)
from .reporting.contracts.permissions import (
    allowed_report_actions,
    report_action_permission_context,
)
from .reporting.contracts.schema import report_proposal_response_schema
from .reporting.proposals.validation import validate_proposal


CONTRACT_VERSION = 1
MAX_INSTRUCTIONS_BYTES = 65536
MAX_PROPOSAL_BYTES = 1024 * 1024
MAX_PROPOSAL_ACTIONS = 100
MAX_PLAN_TOOL_CALLS = 100
MAX_PLAN_FILES = 20
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_TOTAL_FILE_BYTES = 50 * 1024 * 1024

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


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::create_plan
# @reason timestamp helper is exercised through draft creation and submission
def _utcnow():
    return datetime.now(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::create_plan
# @reason byte-count helper enforces the public draft-creation limit
def _text_bytes(value):
    return len(str(value or "").encode("utf-8"))


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::create_plan
# @reason title normalization is part of the public draft-creation contract
def _plan_name(instructions, requested=None):
    requested = " ".join(str(requested or "").split())
    if requested:
        return requested[:120]
    text = " ".join(str(instructions or "").split())
    suffix = "..." if len(text) > 80 else ""
    return f"Organize: {text[:80]}{suffix}"


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_api_report_draft_preserves_agent_manifest
# @matrix agent-api ai-report : draft report-session
def create_plan(user, *, instructions, name=None):
    """Create a durable draft report without dispatching a provider job."""
    instructions = str(instructions or "").strip()
    if not instructions:
        raise exceptions.ValidationError("Instructions are required.")
    if _text_bytes(instructions) > MAX_INSTRUCTIONS_BYTES:
        raise exceptions.ValidationError("Instructions are too large.")

    report = Entities.REPORT.create(
        {
            "parent": user,
            "user": user,
            "name": _plan_name(instructions, name),
            "tool": "organize",
            "instructions": instructions,
            "origin": "api",
            "status": "draft",
            "pending": False,
            "agent_manifest": {
                "version": 1,
                "contract_version": CONTRACT_VERSION,
                "created_at": _utcnow().isoformat(),
            },
        }
    )
    Entities.save(report)
    return report


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::plan_contract
# @reason reference projection is asserted through the public plan contract
def report_file_references(report):
    return [reference for file in report.input_files if (reference := hash_reference(file))]


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_plan_contract_is_permission_and_file_scoped
# @matrix agent-api ai-report : file-placement permissions proposal-contract
def plan_contract(report, user):
    allowed = allowed_report_actions(user)
    return {
        "version": CONTRACT_VERSION,
        "tool": "organize",
        "proposal_schema": report_proposal_response_schema(
            allowed_actions=allowed,
            include_submission_fields=True,
        ),
        "permissions": report_action_permission_context(user, allowed),
        "required_file_refs": report_file_references(report),
        "workflow_rules": [
            "Upload and finalize at least one file before submitting a proposal.",
            "Read tools are available only while the plan remains a draft.",
            "Before analyzing files, call get_guidelines with task=organize and "
            "follow that shared end-to-end workflow; retrieve the specialized "
            "guideline bundles it requires.",
            "Apply the organize guidance in two phases: settle structure and file "
            "assignments first, then use the form_autofill bundle and exact schemas "
            "to add final form submissions or updates before submission. The server "
            "will not call a model to complete or repair them.",
            "Fetch this contract after finalizing uploads and immediately before "
            "constructing the proposal.",
            "Submission saves a ready report for browser review and never executes "
            "its actions.",
        ],
        "reference_rules": [
            "Use hash:<12-character-hash> for every existing entity.",
            "Use *_action fields to reference entities created by earlier actions.",
            "Do not submit URL-safe Datastore keys.",
            "Every uploaded file must be attached to at least one page or task.",
            "Submission values must be final; server-side model repair is unavailable.",
        ],
        "limits": {
            "max_actions": MAX_PROPOSAL_ACTIONS,
            "max_proposal_bytes": MAX_PROPOSAL_BYTES,
            "max_tool_calls": MAX_PLAN_TOOL_CALLS,
            "max_files": MAX_PLAN_FILES,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_file_bytes": MAX_TOTAL_FILE_BYTES,
        },
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @reason recursive string discovery belongs to external proposal validation
def _walk_strings(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, str):
        yield value


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @reason reference-field traversal belongs to external proposal validation
def _reference_values(proposal):
    for action in proposal.get("actions") or []:
        data = action.get("data") if isinstance(action, dict) else None
        if not isinstance(data, dict):
            continue
        for field, value in data.items():
            if field not in REFERENCE_FIELDS:
                continue
            if isinstance(value, dict):
                value = value.get("id") or value.get("key") or value.get("hash")
            if isinstance(value, str) and value:
                yield field, value


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @reason notation checks are exercised through the public validator
def _validate_reference_notation(proposal):
    for _field, value in _reference_values(proposal):
        if value.startswith(("$", "action:")):
            continue
        if HASH_REFERENCE_REGEX.fullmatch(value):
            continue
        if HASH_PREFIXED_ID_REGEX.fullmatch(value) or database_get.is_urlsafe_key(value):
            raise exceptions.AIException(
                "Proposal references must use hash:<12-character-hash>, not internal ids."
            )
        raise exceptions.AIException(
            "Proposal contains an invalid existing-entity reference."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @reason visibility checks are exercised through the public validator
def _validate_reference_visibility(proposal, report, user):
    hashes = {
        match
        for text in _walk_strings(proposal)
        for match in HASH_REFERENCE_REGEX.findall(text)
    }
    if not hashes:
        return
    details = cache.get_details_by_hash(sorted(hashes))
    if not isinstance(details, dict) or set(details) != hashes or any(
        not isinstance(details.get(value), dict) or not details[value].get("id")
        for value in hashes
    ):
        raise exceptions.AIException(
            "Proposal contains an inaccessible or unknown entity reference."
        )

    entities = Entities.fetch(
        *[details[value].get("id") for value in hashes],
        request=Fetch.direct(),
    )
    by_hash = {entity.hash: entity for entity in entities if entity}
    report_files = {file.hash for file in report.input_files}
    for value in hashes:
        entity = by_hash.get(value)
        if not entity or (
            value not in report_files and not entity.allowed(Action.VIEW, user=user)
        ):
            raise exceptions.AIException(
                "Proposal contains an inaccessible or unknown entity reference."
            )


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @reason shape and size checks are exercised through the public validator
def _validate_top_level(proposal):
    if not isinstance(proposal, dict):
        raise exceptions.AIException("Proposal must be a JSON object.")
    try:
        encoded = json.dumps(proposal, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise exceptions.AIException("Proposal must contain valid JSON values.") from error
    if len(encoded.encode("utf-8")) > MAX_PROPOSAL_BYTES:
        raise exceptions.AIException("Proposal is too large.")
    if not isinstance(proposal.get("summary"), str):
        raise exceptions.AIException("Proposal summary must be a string.")
    if not isinstance(proposal.get("confidence"), (int, float)) or isinstance(
        proposal.get("confidence"), bool
    ):
        raise exceptions.AIException("Proposal confidence must be a number.")
    actions = proposal.get("actions")
    if not isinstance(actions, list):
        raise exceptions.AIException("Proposal actions must be a list.")
    if len(actions) > MAX_PROPOSAL_ACTIONS:
        raise exceptions.AIException("Proposal contains too many actions.")


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_proposal_validation_enforces_permissions_files_and_shape
# @matrix agent-api ai-report : file-placement permissions proposal-validation references
def validate_external_proposal(proposal, report, user):
    """Validate an external final proposal without provider repair."""
    _validate_top_level(proposal)
    _validate_reference_notation(proposal)
    _validate_reference_visibility(proposal, report, user)
    return validate_proposal(
        proposal,
        allowed_actions=allowed_report_actions(user),
        allow_empty_submission_updates=True,
        allow_pending_submissions=False,
        required_file_refs=report_file_references(report),
        validate_reference_kinds=True,
    )


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_proposal_submission_is_idempotent_and_provider_free
# @matrix agent-api ai-report : idempotency proposal-publication ready-state
def submit_plan(report, user, proposal, *, contract_version):
    try:
        submitted_contract_version = int(contract_version or 0)
    except (TypeError, ValueError) as error:
        raise exceptions.ValidationError(
            "Unsupported plan contract version."
        ) from error
    if submitted_contract_version != CONTRACT_VERSION:
        raise exceptions.ValidationError("Unsupported plan contract version.")
    normalized = validate_external_proposal(proposal, report, user)
    if report.status == "ready":
        if proposal_fingerprint(normalized) == proposal_fingerprint(report.proposal):
            return report
        raise exceptions.ValidationError("This plan already has a different proposal.")
    if report.status != "draft":
        raise exceptions.ValidationError("Only draft plans can accept a proposal.")
    if report.upload_manifest:
        raise exceptions.ValidationError("Finalize pending uploads before submission.")
    if not report.input_files:
        raise exceptions.ValidationError("Upload at least one file before submission.")

    report.properties.process.set_proposal(normalized, status="ready")
    manifest = dict(report.agent_manifest or {})
    manifest["submitted_at"] = _utcnow().isoformat()
    manifest["proposal_fingerprint"] = proposal_fingerprint(normalized)
    report.agent_manifest = manifest
    Entities.save(report)
    return report


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/uploads.py::prepare_report_upload_manifest
# @reason external wrapper fixes the input name for the tested shared normalizer
def prepare_upload_manifest(records):
    """Normalize signed upload records for an external plan checkpoint."""
    return prepare_report_upload_manifest(records, input_name="agent-api-files")


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_upload_finalization_binds_report_user
# @matrix agent-api ai-report : temporary-view-ownership upload-finalization
def finalize_uploads(report, user):
    """Finalize external uploads and make draft files visible to their submitter."""

    # @testable false
    # @covered-by lagniappe/core/tools/ai/external_api.py::finalize_uploads
    # @reason callback binds report ownership inside the public finalizer
    def create_file(*, upload, data):
        return Entities.FILE.create(upload=upload, data=data, report_user=user)

    return finalize_report_upload_manifest(
        report,
        user,
        file_factory=create_file,
    )


__all__ = [
    "CONTRACT_VERSION",
    "MAX_FILE_BYTES",
    "MAX_PLAN_FILES",
    "MAX_PLAN_TOOL_CALLS",
    "MAX_TOTAL_FILE_BYTES",
    "create_plan",
    "finalize_uploads",
    "plan_contract",
    "prepare_upload_manifest",
    "report_file_references",
    "submit_plan",
    "validate_external_proposal",
]
