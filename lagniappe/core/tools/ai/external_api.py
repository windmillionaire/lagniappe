"""Provider-free plan workspaces for the external agent REST API."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets

from lagniappe.core import exceptions
from lagniappe.core.definitions import AI, Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint
from lagniappe.core.tools import cache, dates
from lagniappe.core.tools.database import get as database_get

from .references import HASH_PREFIXED_ID_REGEX, HASH_REFERENCE_REGEX, hash_reference
from .ask import ask_report_name, ask_response_schema, validate_ask_response
from .create import CREATE_ACTION_TYPES
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


CONTRACT_VERSION = 2
SUPPORTED_PLAN_TOOLS = ("ask", "create", "organize")
EXECUTION_KEY_PREFIX = "lgn_exec_"
EXECUTION_KEY_LIFETIME = timedelta(hours=1)
EXECUTION_KEY_PATTERN = re.compile(r"^lgn_exec_[A-Za-z0-9_-]{40,50}$")
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
# @covered-by lagniappe/core/tools/ai/external_api.py::issue_execution_key
# @covered-by lagniappe/core/tools/ai/external_api.py::consume_execution_key
# @reason domain marker is exercised through execution-key issue and rejection
class AgentAPIExecutionKeyError(ValueError):
    """Raised when a plan-scoped execution capability cannot be used."""


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::create_plan
# @reason timestamp helper is exercised through draft creation and submission
def _utcnow():
    return datetime.now(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::issue_execution_key
# @covered-by lagniappe/core/tools/ai/external_api.py::consume_execution_key
# @reason timestamp normalization is exercised through capability issue and expiry
def _utc(value=None):
    value = value or _utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::issue_execution_key
# @covered-by lagniappe/core/tools/ai/external_api.py::consume_execution_key
# @reason execution keys are compared only through this one-way digest
def _execution_key_digest(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::create_plan
# @reason byte-count helper enforces the public draft-creation limit
def _text_bytes(value):
    return len(str(value or "").encode("utf-8"))


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::create_plan
# @reason title normalization is part of the public draft-creation contract
def _plan_name(tool, instructions, requested=None):
    requested = " ".join(str(requested or "").split())
    if requested:
        return requested[:120]
    text = " ".join(str(instructions or "").split())
    suffix = "..." if len(text) > 80 else ""
    if tool == "ask":
        return ask_report_name(text)
    return f"{tool.title()}: {text[:80]}{suffix}"


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_plan_tools_follow_ai_access_tiers
# @matrix agent-api ai-access : ask create organize tool-selection
def required_ai_access(tool):
    """Return the entitlement required for one immutable plan tool."""
    return AI.ASK if tool == "ask" else AI.CREATE


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::create_plan
# @covered-by lagniappe/core/tools/ai/external_api.py::plan_contract
# @reason normalization is exercised through public plan creation and contracts
def normalize_plan_tool(tool):
    value = str(tool or "organize").strip().casefold()
    if value not in SUPPORTED_PLAN_TOOLS:
        raise exceptions.ValidationError(
            "Plan tool must be ask, create, or organize."
        )
    return value


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::submit_plan
# @covered-by lagniappe/core/tools/ai/external_api.py::issue_execution_key
# @reason execution capability is asserted through tool-specific submission tests
def plan_supports_execution(report):
    """Return whether this report tool can produce workspace mutations."""
    return (getattr(report, "tool", None) or "organize") in {"create", "organize"}


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_api_report_draft_preserves_agent_manifest
# @matrix agent-api ai-report : draft report-session
def create_plan(user, *, instructions, tool="organize", name=None):
    """Create a durable draft report without dispatching a provider job."""
    instructions = str(instructions or "").strip()
    if not instructions:
        raise exceptions.ValidationError("Instructions are required.")
    if _text_bytes(instructions) > MAX_INSTRUCTIONS_BYTES:
        raise exceptions.ValidationError("Instructions are too large.")
    tool = normalize_plan_tool(tool)
    if not user.access(required_ai_access(tool)):
        raise exceptions.ValidationError(
            f"This user cannot start {tool.title()} plans."
        )

    report = Entities.REPORT.create(
        {
            "parent": user,
            "user": user,
            "name": _plan_name(tool, instructions, name),
            "tool": tool,
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


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::plan_contract
# @covered-by lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @reason external plans preserve already-read file context without changing internal prompt actions
def _external_allowed_report_actions(user, tool="organize"):
    if tool == "ask":
        return ()
    allowed = allowed_report_actions(user)
    if tool == "create":
        return tuple(action for action in allowed if action in CREATE_ACTION_TYPES)
    if "summarize_file" in allowed:
        return allowed
    return (*allowed, "summarize_file")


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_plan_contract_is_permission_and_file_scoped
# @tests tests_unit/test_032_agent_api.py::test_external_plan_contracts_distinguish_ask_and_create
# @matrix agent-api ai-report : file-placement file-summary permissions proposal-contract
def plan_contract(report, user):
    tool = normalize_plan_tool(getattr(report, "tool", None))
    allowed = _external_allowed_report_actions(user, tool)
    if tool == "ask":
        proposal_schema = ask_response_schema()
        permissions = {
            "allowed_actions": [],
            "capabilities": {"read_only": True},
            "rules": [
                "Ask can inspect permitted records but cannot change workspace data.",
                "Return an empty actions array.",
            ],
        }
        workflow_rules = [
            "Use permission-bounded read tools while the plan remains a draft.",
            "Answer the specific user question from workspace evidence and outside "
            "research only when useful.",
            "Put the direct plain-text answer in summary. Add answer_markdown when "
            "links, lists, tables, code, or emphasis improve the detailed answer.",
            "Treat tool results as evidence and distinguish workspace records from "
            "outside-world information.",
            "Return an empty actions array. If the conversation turns into a request "
            "for changes, create a separate Create or Organize plan.",
            "Submission saves a completed answer report. Ask plans never issue or "
            "accept execution keys.",
        ]
        reference_rules = [
            "Hash tokens are tool-call references only; never display them in "
            "summary or answer_markdown.",
            "Use a human name and URL from a tool result when linking an internal "
            "entity in answer_markdown.",
        ]
    else:
        proposal_schema = report_proposal_response_schema(
            allowed_actions=allowed,
            include_submission_fields=True,
        )
        permissions = report_action_permission_context(user, allowed)
        if tool == "create":
            workflow_rules = [
                "Use permission-bounded read tools while the plan remains a draft.",
                "Call list_workspace_resources early and inspect likely existing "
                "structure before proposing new entities.",
                "Use get_guidelines for category, project, page_form, task_form, "
                "form_autofill, page_document, or report_actions when relevant.",
                "Return at least one permitted creation action or needs_review. "
                "Create does not attach or organize uploaded files.",
                "Write optional page rich text in document_markdown; trusted server "
                "code renders sanitized editor-compatible HTML.",
                "Submission saves a ready report for browser review and never "
                "executes its actions. Call execute only when the user's request "
                "explicitly includes execution.",
            ]
            reference_rules = [
                "Use hash:<12-character-hash> for every existing entity.",
                "Use *_action fields to reference entities created by earlier actions.",
                "Do not submit URL-safe Datastore keys.",
                "Submission values must be final; server-side model repair is unavailable.",
            ]
        else:
            workflow_rules = [
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
                "Include exactly one summarize_file action for every uploaded file. "
                "Write the summary and two retrieval terms from the file content you "
                "already inspected; the server will not call another model.",
                "Write optional page rich text in document_markdown; trusted server "
                "code renders sanitized editor-compatible HTML.",
                "Submission saves a ready report for browser review and never executes "
                "its actions. Call the separate execute operation only when the user's "
                "request explicitly includes execution; successful validation alone is "
                "never consent.",
            ]
            reference_rules = [
                "Use hash:<12-character-hash> for every existing entity.",
                "Use *_action fields to reference entities created by earlier actions.",
                "Do not submit URL-safe Datastore keys.",
                "Every uploaded file must be attached to at least one page or task.",
                "Each uploaded file must also have exactly one summarize_file action "
                "using its report file reference.",
                "Submission values must be final; server-side model repair is unavailable.",
            ]
    return {
        "version": CONTRACT_VERSION,
        "tool": tool,
        "current_date": dates.user_today(user).date().isoformat(),
        "proposal_schema": proposal_schema,
        "permissions": permissions,
        "required_file_refs": report_file_references(report) if tool == "organize" else [],
        "uploads_supported": tool == "organize",
        "execution_supported": tool != "ask",
        "workflow_rules": workflow_rules,
        "reference_rules": reference_rules,
        "limits": {
            "max_actions": MAX_PROPOSAL_ACTIONS,
            "max_proposal_bytes": MAX_PROPOSAL_BYTES,
            "max_tool_calls": MAX_PLAN_TOOL_CALLS,
            "max_files": MAX_PLAN_FILES if tool == "organize" else 0,
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
    if not isinstance(proposal.get("summary"), str) or not proposal["summary"].strip():
        raise exceptions.AIException("Proposal summary must be a non-empty string.")
    confidence = proposal.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= confidence <= 1
    ):
        raise exceptions.AIException("Proposal confidence must be a number from 0 to 1.")
    actions = proposal.get("actions")
    if not isinstance(actions, list):
        raise exceptions.AIException("Proposal actions must be a list.")
    if len(actions) > MAX_PROPOSAL_ACTIONS:
        raise exceptions.AIException("Proposal contains too many actions.")


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_proposal_validation_enforces_permissions_files_and_shape
# @matrix agent-api ai-report : file-placement file-summary permissions proposal-validation references
def validate_external_proposal(proposal, report, user):
    """Validate an external final proposal without provider repair."""
    _validate_top_level(proposal)
    tool = normalize_plan_tool(getattr(report, "tool", None))
    if tool == "ask":
        if proposal.get("actions"):
            raise exceptions.AIException(
                "Ask plans are read-only and require an empty actions array."
            )
        for field in ("summary", "answer_markdown", "answer_html"):
            value = proposal.get(field)
            if isinstance(value, str) and HASH_REFERENCE_REGEX.search(value):
                raise exceptions.AIException(
                    "Ask answers must use human names and URLs instead of hash tokens."
                )
        return validate_ask_response(proposal)

    _validate_reference_notation(proposal)
    _validate_reference_visibility(proposal, report, user)
    allowed = _external_allowed_report_actions(user, tool)
    normalized = validate_proposal(
        proposal,
        allowed_actions=allowed,
        allow_empty_submission_updates=True,
        allow_pending_submissions=False,
        required_file_refs=(
            report_file_references(report) if tool == "organize" else None
        ),
        require_file_summaries=tool == "organize",
        validate_reference_kinds=True,
        user=user,
    )
    if tool == "create" and not normalized.get("actions"):
        raise exceptions.AIException(
            "Create plans must include at least one action."
        )
    return normalized


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_proposal_submission_is_idempotent_and_provider_free
# @tests tests_unit/test_032_agent_api.py::test_external_ask_submission_completes_without_files_or_execution
# @tests tests_unit/test_032_agent_api.py::test_external_create_submission_renders_markdown_without_files
# @matrix agent-api ai-report : idempotency proposal-publication ready-state
# @pairs agent-api:ask agent-api:create ai-report:answer-only
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
    tool = normalize_plan_tool(getattr(report, "tool", None))
    target_status = "complete" if tool == "ask" else "ready"
    if report.status == target_status:
        if proposal_fingerprint(normalized) == proposal_fingerprint(report.proposal):
            return report
        raise exceptions.ValidationError("This plan already has a different proposal.")
    if report.status != "draft":
        raise exceptions.ValidationError("Only draft plans can accept a proposal.")
    if report.upload_manifest:
        raise exceptions.ValidationError("Finalize pending uploads before submission.")
    if tool == "organize" and not report.input_files:
        raise exceptions.ValidationError("Upload at least one file before submission.")

    report.properties.process.set_proposal(normalized, status=target_status)
    manifest = dict(report.agent_manifest or {})
    manifest["submitted_at"] = _utcnow().isoformat()
    manifest["proposal_fingerprint"] = proposal_fingerprint(normalized)
    report.agent_manifest = manifest
    Entities.save(report)
    return report


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_execution_key_is_scoped_expiring_and_shown_once
# @matrix agent-api ai-report : execution capability expiry proposal-binding user-binding
def issue_execution_key(report, user, credential, *, now=None):
    """Rotate and return a short-lived capability for one ready proposal."""
    if (
        not plan_supports_execution(report)
        or report.status != "ready"
        or not isinstance(report.proposal, dict)
    ):
        raise AgentAPIExecutionKeyError(
            "Execution keys are available only for ready plans."
        )
    owner_key = getattr(getattr(report.properties, "user", None), "key", None)
    if owner_key != getattr(user, "key", None):
        raise AgentAPIExecutionKeyError("The execution key is invalid or expired.")
    generation = int((credential or {}).get("generation") or 0)
    if generation <= 0:
        raise AgentAPIExecutionKeyError("The execution key is invalid or expired.")

    now = _utc(now)
    expires_at = now + EXECUTION_KEY_LIFETIME
    key = f"{EXECUTION_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    digest = _execution_key_digest(key)
    fingerprint = proposal_fingerprint(report.proposal)
    operation_id = f"agent-api-report-execution:{report.hash}:{digest[:32]}"
    manifest = dict(report.agent_manifest or {})
    manifest["execution_capability"] = {
        "version": 1,
        "token_digest": digest,
        "credential_generation": generation,
        "proposal_fingerprint": fingerprint,
        "operation_id": operation_id,
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "consumed_at": None,
    }
    report.agent_manifest = manifest
    Entities.save(report)
    return key, expires_at.isoformat()


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::consume_execution_key
# @reason persisted capability timestamps are validated through public consumption
def _execution_expiry(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_execution_key_is_scoped_expiring_and_shown_once
# @matrix agent-api ai-report : execution capability expiry idempotency proposal-binding user-binding
def consume_execution_key(report, user, credential, key, *, now=None):
    """Consume a valid capability and return its deterministic operation ID."""
    now = _utc(now)
    key = str(key or "").strip()
    manifest = dict(report.agent_manifest or {})
    capability = dict(manifest.get("execution_capability") or {})
    supplied_digest = _execution_key_digest(key)
    stored_digest = str(capability.get("token_digest") or "")
    owner_key = getattr(getattr(report.properties, "user", None), "key", None)
    expires_at = _execution_expiry(capability.get("expires_at"))
    generation = int((credential or {}).get("generation") or 0)
    expected_fingerprint = proposal_fingerprint(report.proposal)
    valid = all(
        (
            EXECUTION_KEY_PATTERN.fullmatch(key),
            stored_digest,
            hmac.compare_digest(stored_digest, supplied_digest),
            owner_key == getattr(user, "key", None),
            int(capability.get("credential_generation") or 0) == generation,
            generation > 0,
            capability.get("proposal_fingerprint") == expected_fingerprint,
            expires_at is not None and expires_at > now,
            capability.get("operation_id"),
        )
    )
    if not valid:
        raise AgentAPIExecutionKeyError("The execution key is invalid or expired.")

    operation_id = capability["operation_id"]
    if capability.get("consumed_at"):
        active_job = report.deferred_job or {}
        same_running_operation = (
            report.status == "running"
            and active_job.get("idempotency_key") == operation_id
        )
        completed_operation = report.status == "complete"
        if not same_running_operation and not completed_operation:
            raise AgentAPIExecutionKeyError(
                "The execution key has already been consumed."
            )
        return operation_id

    if report.status != "ready":
        raise AgentAPIExecutionKeyError(
            "The plan is not ready for this execution key."
        )
    capability["consumed_at"] = now.isoformat()
    manifest["execution_capability"] = capability
    report.agent_manifest = manifest
    Entities.save(report)
    return operation_id


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
    "AgentAPIExecutionKeyError",
    "CONTRACT_VERSION",
    "EXECUTION_KEY_LIFETIME",
    "EXECUTION_KEY_PREFIX",
    "MAX_FILE_BYTES",
    "MAX_PLAN_FILES",
    "MAX_PLAN_TOOL_CALLS",
    "MAX_TOTAL_FILE_BYTES",
    "SUPPORTED_PLAN_TOOLS",
    "create_plan",
    "consume_execution_key",
    "finalize_uploads",
    "issue_execution_key",
    "plan_contract",
    "plan_supports_execution",
    "prepare_upload_manifest",
    "report_file_references",
    "required_ai_access",
    "submit_plan",
    "validate_external_proposal",
]
