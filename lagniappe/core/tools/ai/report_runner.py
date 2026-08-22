"""Deterministic ledger orchestration for stored AI report proposals."""

import hashlib
import json

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache

from .reporting.proposals import validate_proposal
from .reporting.actions.lifecycle import (
    ACTION_APPLIED,
    ACTION_DRIFTED,
    ACTION_NOT_APPLIED,
    REPORT_ACTION_ADAPTERS,
    ReportActionAdapter,
    _expected_action_state,
    _execute_action,
    _is_recoverable_action_error,
    _is_required_file_placement,
    _record_action_result,
    _record_recoverable_action_error,
    _record_required_file_placement_error,
)
from .reporting.actions.operations import (
    PAGE_FORM_TYPE_ERROR,
    SUBMISSION_UPDATE_ROWS_ERROR,
    TASK_FORM_TYPE_ERROR,
    _diagnostic_entity,
    _diagnostic_schema,
    _entity_result,
    _load_result_entity,
    _remember_created,
)

# Stable ledger API plus compatibility seams used by existing callers/tests.
__all__ = (
    "ACTION_APPLIED",
    "ACTION_DRIFTED",
    "ACTION_NOT_APPLIED",
    "PAGE_FORM_TYPE_ERROR",
    "REPORT_ACTION_ADAPTERS",
    "REPORT_LEDGER_VERSION",
    "SUBMISSION_UPDATE_ROWS_ERROR",
    "TASK_FORM_TYPE_ERROR",
    "ReportActionAdapter",
    "_diagnostic_schema",
    "_entity_result",
    "_execute_action",
    "cache",
    "run_report",
    "undo_report",
)

REPORT_LEDGER_VERSION = 1


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020_ai_reports.py::test_run_report_marks_missing_file_placements_failed_and_continues
# @tests tests_unit/test_020_ai_reports.py::test_run_report_skips_invalid_completed_task_events_and_continues
# @tests tests_unit/test_020_ai_reports.py::test_run_report_rejects_saved_pending_submissions_before_execution
# @tests tests_unit/test_020_ai_reports.py::test_run_report_checks_deferred_execution_guard
# @tests tests_unit/test_020_ai_reports.py::test_run_report_propagates_deferred_control_stop
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_stops_when_completed_prefix_permission_is_revoked
# @tests tests_unit/test_020_ai_reports.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_validates_completed_move_and_update_prefix
# @tests tests_unit/test_020_ai_reports.py::test_completed_task_retry_and_undo_restore_reused_task
# @tests tests_unit/test_020_ai_reports.py::test_run_report_uses_category_form_from_stored_key_for_page_submission
# @tests tests_unit/test_020_ai_reports.py::test_run_report_attach_file_to_task_targets_created_task
# @features ai-report
# @dimensions deterministic-run create-order partial-result validation recoverable continue skip-action execute persistence attachments recovery create idempotency completed-prefix post-commit-checkpoint reuse compensation permissions cancellation
def run_report(report, user, ensure_active=None):
    """Execute or resume a stored AI report proposal from durable checkpoints."""
    ensure_active = ensure_active or (lambda: None)
    ensure_active()
    proposal = validate_proposal(
        report.proposal,
        allow_empty_submission_updates=True,
        allow_pending_submissions=False,
    )
    proposal_fingerprint = _proposal_fingerprint(proposal)
    existing = report.result if isinstance(report.result, dict) else {}
    resuming = (
        existing.get("ledger_version") == REPORT_LEDGER_VERSION
        and existing.get("status") != "undone"
    )
    if resuming:
        result = existing
        if result.get("proposal_fingerprint") != proposal_fingerprint:
            raise exceptions.ValidationError(
                "This report proposal changed after execution started."
            )
        _validate_report_ledger(proposal, result)
    else:
        result = _new_report_ledger(report, proposal, proposal_fingerprint)

    result["status"] = "running"
    result.pop("failed_at", None)
    result.pop("undo", None)
    created = _restore_completed_action_entities(result)
    context = _build_report_run_context(proposal)
    context["action_records"] = {
        record.get("id"): record for record in result["actions"] if record.get("id")
    }

    report.status = "running"
    report.pending = True
    report.error = None
    report.result = result
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
            report.status = "failed"
            report.pending = False
            report.error = str(error)
            report.result = result
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
        report.status = "failed"
        report.pending = False
        report.error = (
            "One or more files could not be attached to their planned page or "
            "task. Review the failed file placement before retrying or undoing "
            "the completed actions."
        )
        report.result = result
        Entities.save(report)
        return result

    result["status"] = "complete"
    report.status = "complete"
    report.pending = False
    report.result = result
    report.error = None
    ensure_active()
    Entities.save(report)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason proposal identity is exercised through public retry behavior
def _proposal_fingerprint(proposal):
    canonical = json.dumps(
        proposal,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason action identity is asserted through public retry behavior
def _action_idempotency_key(report, proposal_fingerprint, index, action):
    value = ":".join(
        (
            report.urlsafe_key,
            proposal_fingerprint,
            str(index),
            str(action.get("id") or ""),
            str(action.get("type") or ""),
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason ledger construction is asserted through public retry behavior
def _new_report_ledger(report, proposal, proposal_fingerprint):
    return {
        "ledger_version": REPORT_LEDGER_VERSION,
        "proposal_fingerprint": proposal_fingerprint,
        "status": "running",
        "actions": [
            {
                "id": action.get("id"),
                "type": action.get("type"),
                "display_label": action.get("display_label"),
                "idempotency_key": _action_idempotency_key(
                    report,
                    proposal_fingerprint,
                    index,
                    action,
                ),
                "status": "pending",
                "attempts": 0,
            }
            for index, action in enumerate(proposal.get("actions") or [])
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason ledger validation is exercised through public resume behavior
def _validate_report_ledger(proposal, result):
    actions = proposal.get("actions") or []
    records = result.get("actions") or []
    if len(actions) != len(records):
        raise exceptions.ValidationError("Stored report recovery ledger is invalid.")
    for action, record in zip(actions, records):
        if (
            record.get("id") != action.get("id")
            or record.get("type") != action.get("type")
            or not record.get("idempotency_key")
        ):
            raise exceptions.ValidationError(
                "Stored report recovery ledger does not match the proposal."
            )


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason created-reference restoration is exercised through dependent retries
def _restore_completed_action_entities(result):
    created = {}
    for record in result.get("actions") or []:
        if record.get("status") != "complete":
            continue
        _restore_created_action_entity(created, record)
    return created


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason created-reference restoration is exercised through dependent retries
def _restore_created_action_entity(created, record):
    if not str(record.get("type") or "").startswith("create_"):
        return
    entity = _load_result_entity(record.get("entity"))
    if entity is None:
        return
    action = {"id": record.get("id")}
    _remember_created(created, action, entity)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason recovery failure persistence is exercised through public retry tests
def _fail_report_recovery(report, result, record, index, message):
    record["status"] = "failed"
    record["error"] = message
    result["status"] = "failed"
    result["failed_at"] = index + 1
    report.status = "failed"
    report.pending = False
    report.error = message
    report.result = result
    Entities.save(report)
    return result


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_undo_report_deletes_created_entities_and_unlinks_files
# @tests tests_unit/test_020_ai_reports.py::test_run_report_adds_form_to_existing_page_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_undo_report_compensates_completed_prefix_of_failed_report
# @tests tests_unit/test_020_ai_reports.py::test_completed_task_retry_and_undo_restore_reused_task
# @tests tests_unit/test_020_ai_reports.py::test_run_report_renames_entity_without_submission_and_undoes
# @features ai-report
# @dimensions deterministic-run undo delete-links report-files page-form idempotent idempotency compensation failed-prefix recovery completed-task reuse created-entities file-links rename
def undo_report(report, user):
    """Compensate a complete report or the completed prefix of a failed report."""
    result = report.result if isinstance(report.result, dict) else {}
    if result.get("ledger_version") != REPORT_LEDGER_VERSION:
        raise exceptions.ValidationError("This report has no recovery ledger.")
    if result.get("status") == "undone" or result.get("undone"):
        raise exceptions.ValidationError("This report has already been undone.")
    if report.status not in {"complete", "failed", "undo_failed", "undoing"}:
        raise exceptions.ValidationError(
            "Only complete or partially completed reports can be undone."
        )

    completed_indexes = [
        index
        for index, action in enumerate(result.get("actions") or [])
        if action.get("status") == "complete"
    ]
    if not completed_indexes:
        raise exceptions.ValidationError(
            "This report has no completed actions to undo."
        )

    undo = result.get("undo") if isinstance(result.get("undo"), dict) else None
    if not undo or undo.get("status") not in {"running", "failed"}:
        undo = {
            "status": "running",
            "actions": [
                {
                    "action_index": index,
                    "id": result["actions"][index].get("id"),
                    "type": result["actions"][index].get("type"),
                    "status": "pending",
                    "attempts": 0,
                }
                for index in reversed(completed_indexes)
            ],
        }
    else:
        undo["status"] = "running"
    result["undo"] = undo
    report.status = "undoing"
    report.pending = True
    report.error = None
    report.result = result
    Entities.save(report)

    for undo_record in undo["actions"]:
        action = result["actions"][undo_record["action_index"]]
        adapter = REPORT_ACTION_ADAPTERS[action["type"]]
        if undo_record.get("status") == "complete":
            continue
        try:
            if undo_record.get("status") in {"applying", "failed"}:
                state = adapter.inspect_compensated(action, report, user)
                if state == ACTION_APPLIED:
                    undo_record["status"] = "complete"
                    undo_record.pop("error", None)
                    Entities.save(report)
                    continue
                if state == ACTION_DRIFTED:
                    raise exceptions.ValidationError(
                        "Recorded report action state changed during undo."
                    )

            undo_record["status"] = "applying"
            undo_record["attempts"] = int(undo_record.get("attempts") or 0) + 1
            undo_record.pop("error", None)
            Entities.save(report)
            summary = adapter.compensate(action, report, user)
            undo_record.update(summary)
            undo_record["status"] = "complete"
            Entities.save(report)
        except Exception as error:
            undo_record["status"] = "failed"
            undo_record["error"] = str(error)
            undo["status"] = "failed"
            result["undo"] = undo
            report.result = result
            report.status = "undo_failed"
            report.pending = False
            report.error = str(error)
            Entities.save(report)
            return undo

    undo["status"] = "complete"
    result["status"] = "undone"
    result["undone"] = True
    report.status = "ready"
    report.pending = False
    report.error = None
    report.result = result
    Entities.save(report)
    return undo


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason run-scoped report context setup is verified through report execution
def _build_report_run_context(proposal):
    return {}
