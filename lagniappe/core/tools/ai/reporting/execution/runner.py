"""Deterministic execution of stored AI report proposals."""

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities

from ..proposals.validation import validate_proposal
from .actions.base import (
    ACTION_APPLIED,
    ACTION_DRIFTED,
)
from .actions.checkpoints import _record_action_result
from .actions.recovery import (
    _expected_action_state,
    _is_recoverable_action_error,
    _is_required_file_placement,
    _record_recoverable_action_error,
    _record_required_file_placement_error,
)
from .actions.registry import REPORT_ACTION_ADAPTERS
from .actions.results import (
    _diagnostic_entity,
)
from .ledger import (
    REPORT_LEDGER_VERSION,
    _new_report_ledger,
    _restore_completed_action_entities,
    _restore_created_action_entity,
    _validate_report_ledger,
    proposal_fingerprint,
)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_marks_missing_file_placements_failed_and_continues
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_skips_invalid_completed_task_events_and_continues
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_rejects_saved_pending_submissions_before_execution
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_checks_deferred_execution_guard
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_propagates_deferred_control_stop
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_stops_when_completed_prefix_permission_is_revoked
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_validates_completed_move_and_update_prefix
# @tests tests_unit/test_020h_ai_report_execution.py::test_completed_task_retry_and_undo_restore_reused_task
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_uses_category_form_from_stored_key_for_page_submission
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_attach_file_to_task_targets_created_task
# @features ai-report
# @dimensions deterministic-run create-order partial-result validation recoverable continue skip-action execute persistence attachments recovery create idempotency completed-prefix post-commit-checkpoint reuse compensation permissions cancellation stale-proposal
def run_report(report, user, ensure_active=None):
    """Execute or resume a stored AI report proposal from durable checkpoints."""
    ensure_active = ensure_active or (lambda: None)
    ensure_active()
    proposal = validate_proposal(
        report.proposal,
        allow_empty_submission_updates=True,
        allow_pending_submissions=False,
    )
    fingerprint = proposal_fingerprint(proposal)
    existing = report.result if isinstance(report.result, dict) else {}
    resuming = (
        existing.get("ledger_version") == REPORT_LEDGER_VERSION
        and existing.get("status") != "undone"
    )
    if resuming:
        result = existing
        if result.get("proposal_fingerprint") != fingerprint:
            raise exceptions.ValidationError(
                "This report proposal changed after execution started."
            )
        _validate_report_ledger(proposal, result)
    else:
        result = _new_report_ledger(report, proposal, fingerprint)

    result["status"] = "running"
    result.pop("failed_at", None)
    result.pop("undo", None)
    created = _restore_completed_action_entities(result)
    context = _build_report_run_context(proposal)
    context["action_records"] = {
        record.get("id"): record for record in result["actions"] if record.get("id")
    }

    report.properties.process.begin_execution(result)
    ensure_active()
    Entities.save(report)

    for index, action in enumerate(proposal.get("actions", [])):
        ensure_active()
        action_record = result["actions"][index]
        adapter = REPORT_ACTION_ADAPTERS[action["type"]]
        if action_record.get("status") in {"complete", "skipped"}:
            state = adapter.inspect_applied(action, report, user, action_record)
            if action_record.get("status") == "complete" and state != ACTION_APPLIED:
                return _fail_report_recovery(
                    report,
                    result,
                    action_record,
                    index,
                    "Recorded report action state has changed; recovery stopped.",
                )
            continue

        if action.get("skip") is True:
            action_record["status"] = "skipped"
            action_record["note"] = action.get("reason") or "Skipped by user."
            Entities.save(report)
            continue

        try:
            if action_record.get("status") in {"applying", "failed"}:
                state = adapter.inspect_applied(action, report, user, action_record)
                if state == ACTION_APPLIED:
                    action_record["status"] = "complete"
                    action_record.pop("error", None)
                    Entities.save(report)
                    _restore_created_action_entity(created, action_record)
                    continue
                if state == ACTION_DRIFTED:
                    return _fail_report_recovery(
                        report,
                        result,
                        action_record,
                        index,
                        "Recorded report action state has changed; recovery stopped.",
                    )

            if not action_record.get("prepared"):
                adapter.prepare(
                    action,
                    report,
                    user,
                    created,
                    context,
                    action_record,
                )
                ensure_active()
                action_record["prepared"] = True
            action_record["status"] = "applying"
            action_record["attempts"] = int(action_record.get("attempts") or 0) + 1
            action_record.pop("error", None)
            report.result = result
            Entities.save(report)

            context["action_record"] = action_record
            entity, to_save, metadata = adapter.apply(
                action,
                report,
                user,
                created,
                context,
            )
            ensure_active()
            _record_action_result(
                action_record,
                action,
                entity,
                to_save,
                metadata,
                created,
                context,
            )
            action_record["expected"] = _expected_action_state(
                action,
                action_record,
            )
            action_record["status"] = "complete"
            action_record.pop("error", None)
            report.result = result
            Entities.save(*to_save, report)
        except Exception as error:
            from lagniappe.core.tools.deferred_jobs.errors import (
                DeferredJobClaimLostError,
                DeferredJobDeadlineError,
                DeferredJobInfrastructureError,
            )

            if isinstance(
                error,
                (
                    DeferredJobClaimLostError,
                    DeferredJobDeadlineError,
                    DeferredJobInfrastructureError,
                ),
            ):
                raise
            if _is_recoverable_action_error(action, error):
                if _is_required_file_placement(action):
                    _record_required_file_placement_error(action_record, error)
                    exceptions.capture(
                        error,
                        context={
                            "ai_report_runner": {
                                "operation": "required_file_placement_failed",
                                "report": _diagnostic_entity(report),
                                "action": {
                                    "id": action.get("id"),
                                    "type": action.get("type"),
                                    "display_label": action.get("display_label"),
                                },
                                "error": str(error),
                            }
                        },
                    )
                else:
                    _record_recoverable_action_error(action_record, error)
                Entities.save(report)
                continue
            action_record["status"] = "failed"
            action_record["error"] = str(error)
            result["status"] = "failed"
            result["failed_at"] = index + 1
            report.properties.process.fail(str(error), result=result)
            Entities.save(report)
            return result

    failed_placements = [
        (index, record)
        for index, record in enumerate(result["actions"])
        if record.get("status") == "failed"
        and record.get("type") in {"attach_file_to_page", "attach_file_to_task"}
    ]
    if failed_placements:
        result["status"] = "failed"
        result["failed_at"] = failed_placements[0][0] + 1
        message = (
            "One or more files could not be attached to their planned page or "
            "task. Review the failed file placement before retrying or undoing "
            "the completed actions."
        )
        report.properties.process.fail(message, result=result)
        Entities.save(report)
        return result

    result["status"] = "complete"
    report.properties.process.complete_execution(result)
    ensure_active()
    Entities.save(report)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason recovery failure persistence is exercised through public retry tests
def _fail_report_recovery(report, result, record, index, message):
    record["status"] = "failed"
    record["error"] = message
    result["status"] = "failed"
    result["failed_at"] = index + 1
    report.properties.process.fail(message, result=result)
    Entities.save(report)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason run-scoped report context setup is verified through report execution
def _build_report_run_context(proposal):
    return {}
