"""Shared browser and experiments-MCP request to execute a saved proposal."""

import hashlib

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, DeferredJobSpec, DeferredJobType, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.tools.experiments import can_execute
from . import ledger


# @testable true
# @tests tests_unit/test_034_experiments.py::test_execution_rejects_stale_proposals_and_reuses_exact_operations
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_stale_schema_plan_keeps_review_and_explains_recovery
# @matrix experiments : execution-policy
# @matrix ai-report : browser-review stale-proposal
def request_execution(
    report, actor, *, operation_id=None, expected_fingerprint=None, remote_mcp=False
):
    """Validate current state, then use the ordinary idempotent deferred runner."""
    if not report.available or not report.allowed(Action.EDIT, user=actor):
        raise exceptions.ValidationError(
            "You do not have permission to execute this report."
        )
    if report.db.get("superseded_by"):
        raise exceptions.ValidationError(
            "This execution was superseded by an approved correction."
        )
    parameters = {}
    if remote_mcp:
        if not can_execute(actor, remote_mcp=True):
            raise exceptions.ValidationError(
                "Experiments execution is unavailable for this actor."
            )
        if report.origin != "api" or report.properties.user.key != actor.key:
            raise exceptions.ValidationError(
                "Only the creator can execute this external plan."
            )
        if (
            not operation_id
            or not expected_fingerprint
            or expected_fingerprint
            != (report.agent_manifest or {}).get("proposal_fingerprint")
        ):
            raise exceptions.ValidationError(
                "The submitted proposal changed. Read and submit the current plan before execution."
            )
        parameters = {"experiments_execution": True}

    spec = DeferredJobSpec(
        job_type=DeferredJobType.REPORT_EXECUTION,
        actor=actor,
        idempotency_key=operation_id or None,
        inputs={"report": report},
        parameters=parameters,
        notification_body="Saving report changes...",
        notification_target=report,
        client={
            "key": report.urlsafe_key,
            "source_widget": "CreateToolReport",
            "destination": "tools:ToolReportList",
        },
    )
    if operation_id:
        key = database_utility.create_named_key(
            "job", hashlib.sha256(operation_id.encode()).hexdigest(), actor
        )
        existing = Entities.fetch_one(key, request=Fetch.direct())
        if existing is not None:
            # The service verifies the full request fingerprint, including actor,
            # plan, proposal and execution origin, before returning the receipt.
            return DeferredJobs.start(spec)

    if remote_mcp and expected_fingerprint != proposal_fingerprint(report.proposal):
        raise exceptions.ValidationError(
            "The submitted proposal changed. Read and submit the current plan before execution."
        )

    result = report.result if isinstance(report.result, dict) else {}
    if (
        not remote_mcp
        and report.status == "complete"
        and result.get("status") == "complete"
    ):
        return None, None
    retryable = (
        report.status == "failed"
        and result.get("ledger_version") == ledger.REPORT_LEDGER_VERSION
        and result.get("status") == "failed"
    )
    if report.status != "ready" and not retryable:
        raise exceptions.ValidationError(
            "Only ready or recoverable failed reports can be run."
        )
    if report.upload_manifest:
        raise exceptions.ValidationError("Finish pending uploads before execution.")

    from lagniappe.core.tools.ai.reporting.schema_updates import prepare_schema_updates
    from lagniappe.core.tools.forms import (
        changes as form_changes,
        schema_updates as form_schema_updates,
    )

    try:
        if not retryable:
            prepare_schema_updates(report.proposal, actor, verify=True)
        else:
            for record in result.get("actions", []):
                if record.get("migration_id"):
                    form = Entities.fetch_one(
                        record.get("migration_form"), request=Fetch.direct()
                    )
                    if form and form.db.get(form_changes.PENDING):
                        form_changes.recover_change(form, actor, "retry")
    except exceptions.ValidationError as error:
        if not retryable and str(error).startswith(form_schema_updates.STALE_MESSAGE):
            recovery = (
                "Ask the assistant that created it to refresh this same plan, then review the updated conversions."
                if report.origin == "api"
                else "Use Revise Plan to refresh it, then review the updated conversions."
            )
            raise exceptions.ValidationError(
                "This plan needs another review because the form or saved answers changed. Execution hasn't started. "
                + recovery
            ) from error
        raise
    from lagniappe.core.tools.ai.reporting.corrections import approve_correction

    approve_correction(report, actor)
    return DeferredJobs.start(spec)
