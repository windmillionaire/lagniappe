"""External API plans."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....entities.entity import Entity
    from ....entities import Identifier
    from ..external_operations import PlanWriter
    from ....entities.ai_report import AIReport
    from ....entities.user import User

import uuid
from copy import deepcopy
from datetime import datetime, UTC

from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint
from lagniappe.core.tools.database import agent_api as agent_api_store
from lagniappe.core.tools.notifications import service as notification_service

from ..external_operations import (
    ExternalPlanError,
    claimed_plan_save,
    raise_plan_operation_error,
    release_plan_operation_claim,
)
from .definitions import (
    CONTRACT_VERSION,
    MAX_INSTRUCTIONS_BYTES,
    MAX_PLAN_NAME_CHARACTERS,
    _text_bytes,
)
from .validation import submission_validation_errors, validate_external_proposal


# @testable false
# @covered-by lagniappe/core/tools/ai/external/plans.py::create_plan
# @reason timestamp helper is exercised through draft creation and submission
def _utcnow():
    return datetime.now(UTC)


# @testable false
# @covered-by lagniappe/core/tools/ai/external/plans.py::create_plan
# @reason title normalization is part of the public draft-creation contract
def _plan_name(instructions, requested=None):
    requested = " ".join(str(requested or "").split())
    if requested:
        return requested[:MAX_PLAN_NAME_CHARACTERS]
    text = " ".join(str(instructions or "").split())
    return f"AI: {text[:80]}{'...' if len(text) > 80 else ''}" if text else "AI plan"


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_api_report_draft_preserves_agent_manifest
# @matrix agent-api ai-report : draft report-session
# @pair agent-api:entitlement-independent
def create_plan(
    user: User,
    *,
    instructions: object = "",
    name: object = None,
    remote_mcp: bool = False,
    revises_plan_id: object = None,
    require_review: bool = False,
) -> AIReport:
    """Create a durable draft report without dispatching a provider job."""
    if revises_plan_id is not None and (not isinstance(revises_plan_id, str) or not revises_plan_id):
        raise exceptions.ValidationError("revises_plan_id must be a nonempty plan ID.")
    instructions = str(instructions or "").strip()
    if _text_bytes(instructions) > MAX_INSTRUCTIONS_BYTES:
        raise exceptions.ValidationError("Instructions are too large.")

    manifest = {
        "version": 1,
        "source": "remote_mcp" if remote_mcp else "api",
        "contract_version": CONTRACT_VERSION,
        "created_at": _utcnow().isoformat(),
        "original_brief": {
            "name": _plan_name(instructions, name),
            "instructions": instructions,
        },
    }
    if require_review:
        manifest["require_review"] = True

    report = Entities.REPORT.create(
        {
            "parent": user,
            "user": user,
            "name": _plan_name(instructions, name),
            "instructions": instructions,
            "origin": "api",
            "status": "draft",
            "pending": False,
            "agent_manifest": manifest,
        }
    )
    if revises_plan_id:
        from ..reporting.corrections import link_correction, save_correction
        source = Entities.fetch_one(revises_plan_id, request=Fetch.direct())
        if not isinstance(source, Entities.REPORT):
            raise exceptions.ValidationError("Choose an available plan that you created.")
        link_correction(report, source, user)
        save_correction(report, source)
    else:
        Entities.save(report)
    return report


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_proposal_submission_is_idempotent_and_provider_free
# @tests tests_unit/test_032_agent_api.py::test_external_ask_submission_completes_without_files_or_execution
# @tests tests_unit/test_032_agent_api.py::test_external_create_submission_renders_markdown_without_files
# @matrix agent-api ai-report : idempotency proposal-publication ready-state remote-update
# @pairs agent-api:ask agent-api:create ai-report:answer-only agent-api:answer-only
# @pairs agent-api:ask-revision agent-api:create-revision agent-api:organize-revision
def submit_plan(
    report: AIReport,
    user: User,
    proposal: object,
    *,
    contract_version: object,
    file_usage: object,
    save: PlanWriter | None = None,
    name: object = None,
    instructions: object = None,
    require_review: object = None,
) -> AIReport:
    if getattr(report, "result", None):
        raise exceptions.ValidationError(
            "A plan cannot be revised after execution has begun."
        )
    try:
        value = contract_version or 0
        if not isinstance(value, (str, int, float)):
            raise TypeError("Contract version must be numeric.")
        submitted_contract_version = int(value)
    except (TypeError, ValueError) as error:
        raise exceptions.ValidationError(
            "Unsupported plan contract version."
        ) from error
    if submitted_contract_version != CONTRACT_VERSION:
        raise exceptions.ValidationError("Unsupported plan contract version.")
    public_references = {}
    normalized = validate_external_proposal(
        proposal,
        report,
        user,
        file_usage=file_usage,
        instructions=instructions,
        resolved_references=public_references,
    )
    brief = {
        field: value
        for field, value in (("name", name), ("instructions", instructions))
        if value is not None
    }
    normalized_brief: dict[str, str] = {}
    for field, value in brief.items():
        maximum = MAX_PLAN_NAME_CHARACTERS if field == "name" else MAX_INSTRUCTIONS_BYTES
        if (
            not isinstance(value, str)
            or not value.strip()
            or (len(value) if field == "name" else _text_bytes(value)) > maximum
        ):
            raise exceptions.ValidationError(f"Invalid Plan {field}.")
        normalized_brief[field] = value.strip()
    brief_changed = any(
        getattr(report, field) != value for field, value in normalized_brief.items()
    )
    review_changed = (
        require_review is not None
        and bool((report.agent_manifest or {}).get("require_review", False))
        != bool(require_review)
    )
    if report.status in {"draft", "ready"} or (
        report.output_kind == "answer" and report.status == "complete"
    ):
        if (
            not brief_changed
            and not review_changed
            and file_usage == (report.file_usage or [])
            and proposal_fingerprint(normalized)
            == proposal_fingerprint(report.proposal)
        ):
            return report
    else:
        raise exceptions.ValidationError(
            "Only draft or browser-review-ready plans can accept a proposal."
        )
    if report.upload_manifest:
        raise exceptions.ValidationError("Finalize pending uploads before submission.")
    if (
        not report.input_files
        and not str(
            instructions if instructions is not None else report.instructions or ""
        ).strip()
    ):
        raise exceptions.ValidationError(
            "Provide instructions or finalized files before submission."
        )

    report.file_usage = deepcopy(file_usage)
    report.properties.process.set_proposal(normalized)
    manifest = dict(report.agent_manifest or {})
    if brief_changed:
        manifest.setdefault(
            "original_brief", {"name": report.name, "instructions": report.instructions}
        )
        for field, value in normalized_brief.items():
            setattr(report, field, value)
    manifest["submitted_at"] = _utcnow().isoformat()
    manifest["proposal_fingerprint"] = proposal_fingerprint(normalized)
    manifest["public_references"] = public_references
    if require_review is not None:
        if require_review:
            manifest["require_review"] = True
        else:
            manifest.pop("require_review", None)
    report.agent_manifest = manifest
    (save or Entities.save)(report)
    return report


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_api_ignores_provider_entitlement_but_rechecks_public_eligibility
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_plan_resources_hide_other_users_plans
# @matrix agent-api : creator-bound entitlement-independent generic-not-found plan-isolation stale-plan
def load_plan(plan_id: Identifier, user: User) -> AIReport:
    report = Entities.fetch_one(plan_id, request=Fetch.direct())
    return require_plan_access(report, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/external/plans.py::load_plan
# @reason loaded and supplied reports have the same creator/origin/availability boundary
def require_plan_access(report: Entity | None, user: User) -> AIReport:
    actor = user
    owner_key = getattr(report.properties.user, "key", None) if report else None
    if (
        not isinstance(report, Entities.REPORT)
        or report.origin != "api"
        or owner_key != actor.key
    ):
        raise ExternalPlanError("not_found", "Plan not found.")
    if not report.available:
        raise ExternalPlanError("plan_unavailable", "this plan is no longer available")
    return report


# @testable false
# @covered-by lagniappe/web/routes/api/main.py::execute_tool
# @reason draft-state gating is exercised through plan-scoped operations
def require_draft(report: AIReport) -> None:
    if report.status != "draft":
        raise ExternalPlanError(
            "plan_not_draft",
            "This operation is only available while the plan is a draft.",
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/external/plans.py::submit_plan_request
# @reason both the transport precheck and claimed submission use this state gate
def require_submission_available(report: AIReport) -> str:
    reusable_status = "complete" if report.output_kind == "answer" else "ready"
    if report.status not in {"draft", reusable_status}:
        raise ExternalPlanError(
            "plan_state_conflict", "This plan cannot accept a proposal in its current state."
        )
    return reusable_status


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_external_agent_api_requires_bearer_and_dispatches_as_bound_user
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_submission_is_serialized_with_upload_operations
# @matrix agent-api : submission
# @pairs agent-api:concurrency agent-api:plan-operation
# @pairs mcp-upload:concurrency mcp-upload:plan-operation
def submit_plan_request(report: AIReport, user: User, data: dict[str, object], *, request_id: str | None) -> AIReport:
    require_plan_access(report, user)
    plan_id = report.urlsafe_key
    reusable_status = require_submission_available(report)
    operation_id = uuid.uuid4().hex
    claim_token = uuid.uuid4().hex
    key = report.key
    assert key is not None
    claim_outcome = agent_api_store.claim_plan_operation(
        key,
        phase="submit",
        operation_id=operation_id,
        claim_token=claim_token,
    )
    if claim_outcome != agent_api_store.PLAN_OPERATION_CLAIMED:
        if claim_outcome == agent_api_store.PLAN_OPERATION_INVALID:
            raise ExternalPlanError(
                "plan_state_conflict",
                "This plan cannot accept a proposal in its current state.",
            )
        raise_plan_operation_error(claim_outcome)

    try:
        # Submission shares the per-report operation claim so it cannot
        # overwrite a newly staged manifest or be overwritten by a stale
        # upload creator.
        report = load_plan(plan_id, user)
        reusable_status = require_submission_available(report)
        validation_errors = submission_validation_errors(
            data,
            report,
            user,
        )
        if validation_errors:
            raise ExternalPlanError(
                "validation_failed",
                "Submission failed validation.",
                details={"errors": validation_errors},
            )
        save = claimed_plan_save(
            report,
            user=user, request_id=request_id,
            phase="submit",
            operation_id=operation_id,
            claim_token=claim_token,
        )
        try:
            submitted = submit_plan(
                report,
                user,
                data.get("proposal"),
                contract_version=data.get("contract_version"),
                file_usage=data.get("file_usage"),
                save=save,
                **{
                    field: data[field]
                    for field in ("name", "instructions", "require_review")
                    if field in data
                },
            )
            notification_service.publish_plan_notification(submitted, user)
        except exceptions.ValidationError as error:
            if report.status == reusable_status:
                raise ExternalPlanError("plan_state_conflict", str(error)) from error
            raise
    finally:
        release_plan_operation_claim(
            report,
            phase="submit",
            operation_id=operation_id,
            claim_token=claim_token,
        )
    return submitted
