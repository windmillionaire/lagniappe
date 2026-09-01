"""Provider-free plan workspaces for the external agent REST API."""

from datetime import datetime, timezone
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint
from lagniappe.core.tools import cache, dates
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.files.html import render_markdown, strip_tags

from .references import (
    HASH_PREFIXED_ID_REGEX,
    HASH_REFERENCE_REGEX,
    hash_reference,
    personal_page_reference,
)
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


CONTRACT_VERSION = 4
SUPPORTED_PLAN_TOOLS = ("ask", "create", "organize")
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


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_client_skill_markdown_is_minimal_and_discovery_first
# @matrix agent-api : bootstrap discovery secret-handling tool-envelope
def client_skill_markdown(base_url):
    """Return the canonical minimal client skill for this API deployment."""
    base_url = str(base_url or "").rstrip("/")
    return f"""---
name: lagniappe
description: Use the user's personal Lagniappe workspace to answer questions, organize files, or create pages, projects, and tasks.
---

# Lagniappe API

Use `{base_url}` when a request needs the user's personal workspace context,
file organization, or workspace creation.

Read the bearer key from `$LAGNIAPPE_API_KEY`. Never print it, store it in a
file, or put it in a URL. Start with the API discovery endpoint, read its
`openapi_url`, and then call its `actor_url` to verify the user and capabilities.

Tool calls wrap inputs as `{{"arguments": {{...}}}}`. Treat live discovery,
OpenAPI, and plan contracts as authoritative. Create and Organize only prepare
proposals; the user approves workspace changes on the authenticated website.
"""


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
# @tests tests_unit/test_032_agent_api.py::test_external_plan_tool_selection_is_provider_independent
# @matrix agent-api : ask create organize tool-selection
def normalize_plan_tool(tool):
    value = str(tool or "organize").strip().casefold()
    if value not in SUPPORTED_PLAN_TOOLS:
        raise exceptions.ValidationError(
            "Plan tool must be ask, create, or organize."
        )
    return value


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_api_report_draft_preserves_agent_manifest
# @matrix agent-api ai-report : draft report-session
# @pair agent-api:entitlement-independent
def create_plan(user, *, instructions, tool="organize", name=None):
    """Create a durable draft report without dispatching a provider job."""
    instructions = str(instructions or "").strip()
    if not instructions:
        raise exceptions.ValidationError("Instructions are required.")
    if _text_bytes(instructions) > MAX_INSTRUCTIONS_BYTES:
        raise exceptions.ValidationError("Instructions are too large.")
    tool = normalize_plan_tool(tool)

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
# @reason persisted timezone projection is asserted through the public contract
def user_timezone_name(user):
    data = getattr(user, "db", None)
    return str(data.get("timezone") or "UTC") if isinstance(data, dict) else "UTC"


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
# @pairs agent-api:create-revision agent-api:organize-revision
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
            "Use permission-bounded read tools while investigating. They remain "
            "available after an Ask submission so a conversational follow-up can "
            "refine the saved answer.",
            "Answer the specific user question from workspace evidence and outside "
            "research only when useful.",
            "Put the direct plain-text answer in summary. Add answer_markdown when "
            "links, lists, tables, code, or emphasis improve the detailed answer.",
            "Treat tool results as evidence and distinguish workspace records from "
            "outside-world information.",
            "Return an empty actions array. If the conversation turns into a request "
            "for changes, create a separate Create or Organize plan.",
            "When an answer is ready, fetch the latest contract and submit it without "
            "waiting for separate save confirmation. Submission only saves the "
            "read-only answer report; it does not modify workspace records. Then give "
            "the user the answer and preview_url.",
            "A later valid Ask submission replaces that plan's saved answer.",
        ]
        reference_rules = [
            "Hash tokens are tool-call references only; never display them in "
            "summary or answer_markdown.",
            "Use a human name and URL from a tool result when linking an internal "
            "entity in answer_markdown. The tool-provided URL may contain a hash "
            "token in its link destination; use a human name as the link label. "
            "Trusted server rendering resolves known hash destinations to ordinary "
            "browser URLs.",
        ]
    else:
        proposal_schema = report_proposal_response_schema(
            allowed_actions=allowed,
            include_submission_fields=True,
        )
        permissions = report_action_permission_context(user, allowed)
        if tool == "create":
            workflow_rules = [
                "Use permission-bounded read tools while the plan is draft or ready.",
                "Call list_workspace_resources early and inspect likely existing "
                "structure before proposing new entities.",
                "Use get_guidelines for category, project, page_form, task_form, "
                "form_autofill, page_document, or report_actions when relevant.",
                "Return at least one permitted creation action or needs_review. "
                "Create does not attach or organize uploaded files.",
                "Write optional page rich text in document_markdown; trusted server "
                "code renders sanitized editor-compatible HTML.",
                "Submission validates and saves a ready report for browser review; "
                "it never applies the proposal to the workspace. Present preview_url "
                "and direct the user to review and approve it on the authenticated "
                "website. The external API has no execution operation.",
                "A ready Create proposal remains conversationally revisable. For "
                "follow-up changes, continue reading as needed, revise the complete "
                "proposal, and submit it again. Each valid resubmission replaces the "
                "previous proposal until browser execution starts.",
            ]
            reference_rules = [
                "Use hash:<12-character-hash> for every existing entity.",
                "A field ending in *_action takes the exact id of an earlier action "
                "in this proposal that creates the referenced entity; it never takes "
                "a workspace hash or entity id.",
                "Do not submit URL-safe Datastore keys.",
                "data.submission is the Form field-value object to create with a new "
                "Page or Task, keyed by exact Form schema ids; it is not an existing "
                "submission reference.",
                "Submission values must be final; server-side model repair is unavailable.",
            ]
        else:
            workflow_rules = [
                "Upload and finalize at least one file before submitting a proposal.",
                "Read tools remain available while the plan is draft or ready so a "
                "conversational follow-up can refine the proposal.",
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
                "Submission validates and saves a ready report for browser review; "
                "it never applies the proposal to the workspace. Present preview_url "
                "and direct the user to review and approve it on the authenticated "
                "website. The external API has no execution operation.",
                "A ready Organize proposal remains conversationally revisable. For "
                "follow-up changes, continue reading as needed, revise the complete "
                "proposal, and submit it again. Each valid resubmission replaces the "
                "previous proposal until browser execution starts.",
            ]
            reference_rules = [
                "Use hash:<12-character-hash> for every existing entity.",
                "A field ending in *_action takes the exact id of an earlier action "
                "in this proposal that creates the referenced entity; it never takes "
                "a workspace hash or entity id.",
                "Do not submit URL-safe Datastore keys.",
                "data.submission is the Form field-value object to create with a new "
                "Page or Task, keyed by exact Form schema ids; it is not an existing "
                "submission reference.",
                "Every uploaded file must be attached to at least one page or task.",
                "Each uploaded file must also have exactly one summarize_file action "
                "using its report file reference.",
                "Submission values must be final; server-side model repair is unavailable.",
            ]
    personal_page = personal_page_reference(user)
    workflow_rules.insert(
        0,
        "personal_page is the authenticated user's guaranteed editable Page. "
        "It intentionally does not appear in workspace search and shares its "
        "public hash with the user; use personal_page.hash as a Page reference "
        "when the user asks about or requests Tasks on their own Page.",
    )
    return {
        "version": CONTRACT_VERSION,
        "tool": tool,
        "current_date": dates.user_today(user).date().isoformat(),
        "timezone": user_timezone_name(user),
        "personal_page": personal_page,
        "submission_format": {
            "contract_version": CONTRACT_VERSION,
            "body": {
                "contract_version": CONTRACT_VERSION,
                "proposal": "<object matching proposal_schema>",
            },
            "rule": (
                "POST this wrapper object to submit_url; do not post the proposal "
                "object as the top-level request body."
            ),
        },
        "proposal_schema": proposal_schema,
        "permissions": permissions,
        "required_file_refs": report_file_references(report) if tool == "organize" else [],
        "uploads_supported": tool == "organize",
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


# @testable false
# @covered-by lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @reason Ask hash-token checks distinguish rendered labels from link destinations
def _ask_visible_text(field, value):
    if field == "answer_markdown":
        return strip_tags(render_markdown(value))
    return value


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_proposal_validation_enforces_permissions_files_and_shape
# @tests tests_unit/test_032_agent_api.py::test_external_ask_submission_allows_hash_token_in_named_link_destination
# @matrix agent-api ai-report : file-placement file-summary permissions proposal-validation references
# @pairs agent-api:ask ai-report:answer-only
def validate_external_proposal(proposal, report, user):
    """Validate an external final proposal without provider repair."""
    _validate_top_level(proposal)
    tool = normalize_plan_tool(getattr(report, "tool", None))
    if tool == "ask":
        unexpected = set(proposal) - {
            "summary",
            "answer_markdown",
            "confidence",
            "actions",
        }
        if unexpected:
            raise exceptions.AIException(
                "Ask proposal contains unsupported fields: "
                f"{', '.join(sorted(unexpected))}."
            )
        if proposal.get("actions"):
            raise exceptions.AIException(
                "Ask plans are read-only and require an empty actions array."
            )
        for field in ("summary", "answer_markdown"):
            value = proposal.get(field)
            visible_text = (
                _ask_visible_text(field, value) if isinstance(value, str) else value
            )
            if isinstance(visible_text, str) and HASH_REFERENCE_REGEX.search(
                visible_text
            ):
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
# @pairs agent-api:ask-revision agent-api:create-revision agent-api:organize-revision
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
    elif report.status != "draft":
        raise exceptions.ValidationError(
            "Only draft or browser-review-ready plans can accept a proposal."
        )
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
    "SUPPORTED_PLAN_TOOLS",
    "client_skill_markdown",
    "create_plan",
    "finalize_uploads",
    "plan_contract",
    "prepare_upload_manifest",
    "report_file_references",
    "submit_plan",
    "user_timezone_name",
    "validate_external_proposal",
]
