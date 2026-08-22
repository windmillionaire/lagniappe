"""Compensation orchestration for executed AI reports."""

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities

from .actions.base import ACTION_APPLIED, ACTION_DRIFTED
from .actions.registry import REPORT_ACTION_ADAPTERS
from .ledger import REPORT_LEDGER_VERSION


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_undo_report_deletes_created_entities_and_unlinks_files
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_adds_form_to_existing_page_with_undo
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @tests tests_unit/test_020h_ai_report_execution.py::test_undo_report_compensates_completed_prefix_of_failed_report
# @tests tests_unit/test_020h_ai_report_execution.py::test_completed_task_retry_and_undo_restore_reused_task
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_renames_entity_without_submission_and_undoes
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
    report.properties.process.begin_undo(result)
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
            report.properties.process.fail_undo(str(error), result)
            Entities.save(report)
            return undo

    undo["status"] = "complete"
    result["status"] = "undone"
    result["undone"] = True
    report.properties.process.complete_undo(result)
    Entities.save(report)
    return undo
