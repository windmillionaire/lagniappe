"""Inspection and recoverable-error classification for report actions."""


from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.tools.database import get as database_get

from .common import TASK_FORM_TYPE_ERROR, _data
from .results import (
    _entity_result,
)
from .references import _fetch_report_entity, _file_attached_to_endpoint
from .task_completion import _completion_state
from .completed_tasks import (
    _is_completed_task_event,
    _task_state_fingerprint,
    _value_fingerprint,
)

ACTION_APPLIED = "applied"
ACTION_NOT_APPLIED = "not-applied"
ACTION_DRIFTED = "drifted"


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/recovery.py::_inspect_action_applied
# @reason expected state is asserted through move, update, and task retries
def _expected_action_state(action, record):
    action_type = action.get("type")
    expected = {
        "entity": (record.get("entity") or {}).get("id"),
        "target": (record.get("target") or {}).get("id"),
    }
    if action_type in {"update_task", "update_page", "update_project", "update_model_task"}:
        expected["entity_update_after"] = record.get("entity_update_after")
    if action_type == "complete_task":
        expected["completion_state"] = record.get("completion_state")
        expected["task_state_fingerprint"] = record.get("task_state_fingerprint")
    if action_type in {"update_form_schema"}:
        expected["schema_fingerprint"] = record.get("schema_fingerprint")
    if action_type == "summarize_file":
        data = _data(action)
        expected["summary"] = (
            data.get("summary") or data.get("description") or ""
        ).strip()
        expected["retrieval_terms"] = [
            term.strip()
            for term in (data.get("retrieval_terms") or [])
            if isinstance(term, str) and term.strip()
        ][:2]
        expected["search"] = data.get("search", True) is not False
    if action_type == "create_task" and _is_completed_task_event(_data(action)):
        expected["task"] = (record.get("target") or {}).get("id")
        expected["task_state_fingerprint"] = record.get("task_state_fingerprint")
    return expected


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason recovery authorization is enforced through the public runner
def _recovery_entity_allowed(entity, user):
    if entity is None:
        return False
    return bool(entity.allowed(Action.EDIT, user=user))


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason stored reference comparison is exercised through move recovery
def _stored_reference_key(entity, name):
    value = entity.db.get(name)
    return _urlsafe_key_value(value)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason key normalization is exercised through action state inspection
def _urlsafe_key_value(value):
    if not value:
        return None
    encoded = database_get.urlsafe_key(value)
    if encoded:
        return encoded
    legacy = getattr(value, "to_legacy_urlsafe", None)
    if callable(legacy):
        result = legacy()
        return result.decode() if isinstance(result, bytes) else str(result)
    return getattr(value, "name", None) or str(value)


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_stops_when_completed_prefix_permission_is_revoked
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @tests tests_unit/test_020h_ai_report_execution.py::test_completed_task_retry_preserves_reused_completion
# @matrix ai-report : completed-prefix completed-task permissions post-commit-checkpoint recovery
# @pair ai-report:skipped-prefix
def _inspect_action_applied(action, report, user, record):
    action_type = action.get("type")
    if record.get("status") == "skipped" or action_type in {
        "skip",
        "needs_review",
        "suggest_page_deletion",
    }:
        return ACTION_APPLIED

    if action_type == "append_page_document":
        from .documents import inspect_document_append

        return inspect_document_append(record, user)

    expected = record.get("expected") or {}
    entity_id = expected.get("entity") or (record.get("entity") or {}).get("id")
    entity = _fetch_report_entity(entity_id) if entity_id else None
    if action_type.startswith("create_"):
        if action_type == "create_task" and expected.get("task"):
            task = _fetch_report_entity(expected["task"])
            if task is None or not _recovery_entity_allowed(task, user):
                return ACTION_DRIFTED
            fingerprint = expected.get("task_state_fingerprint")
            if fingerprint and _task_state_fingerprint(task) != fingerprint:
                return ACTION_DRIFTED
            return ACTION_APPLIED
        if entity is not None:
            if not _recovery_entity_allowed(entity, user):
                return ACTION_DRIFTED
            return ACTION_APPLIED
        output_key = record.get("output_key")
        if output_key:
            entity = _fetch_report_entity(output_key)
            if entity is not None:
                record["entity"] = _entity_result(entity)
                record["created"] = True
                record["expected"] = {
                    "entity": entity.urlsafe_key,
                    "target": None,
                }
                return ACTION_APPLIED
        return ACTION_NOT_APPLIED
    if not expected:
        return ACTION_NOT_APPLIED
    if entity is None and entity_id:
        return ACTION_DRIFTED
    if entity is not None and not _recovery_entity_allowed(entity, user):
        return ACTION_DRIFTED

    if action_type in {"update_task", "update_page", "update_project", "update_model_task"}:
        from lagniappe.core.tools.entity_patches import _projection
        if entity is not None and _projection(entity) == expected.get("entity_update_after"):
            return ACTION_APPLIED
        # A later completion can advance the recurrence or archive this submission.
        # Its full post-completion fingerprint is the authoritative final state.
        records = (report.result or {}).get("actions", [])
        position = next((index for index, prior in enumerate(records) if prior.get("id") == record.get("id")), len(records))
        for later in records[position + 1:]:
            if later.get("type") == "complete_task" and later.get("status") == "complete" and (later.get("entity") or {}).get("id") == entity_id and (later.get("expected") or {}).get("task_state_fingerprint"):
                return _inspect_action_applied({"type": "complete_task"}, report, user, later)
        return ACTION_DRIFTED

    target_id = expected.get("target")
    target = _fetch_report_entity(target_id) if target_id else None
    if action_type == "move_task":
        return (
            ACTION_APPLIED
            if _stored_reference_key(entity, "page") == target_id
            else ACTION_DRIFTED
        )
    if action_type == "move_file":
        if target is None:
            return ACTION_DRIFTED
        source_id = ((record.get("before") or {}).get("source") or {}).get("id")
        source = _fetch_report_entity(source_id) if source_id else None
        if _file_attached_to_endpoint(entity, target) and (
            source is None or not _file_attached_to_endpoint(entity, source)
        ):
            return ACTION_APPLIED
        return ACTION_DRIFTED
    if action_type == "complete_task":
        if expected.get("task_state_fingerprint") and _task_state_fingerprint(entity) != expected["task_state_fingerprint"]:
            return ACTION_DRIFTED
        return ACTION_APPLIED if _completion_state(entity) == expected.get("completion_state") else ACTION_DRIFTED
    if action_type in {"update_form_schema"}:
        return (
            ACTION_APPLIED
            if _value_fingerprint(entity.schema or [])
            == expected.get("schema_fingerprint")
            else ACTION_DRIFTED
        )
    if action_type == "attach_file":
        if target is None:
            return ACTION_DRIFTED
        return (
            ACTION_APPLIED
            if _file_attached_to_endpoint(entity, target)
            else ACTION_DRIFTED
        )
    if action_type == "summarize_file":
        return (
            ACTION_APPLIED
            if entity.summary == expected.get("summary")
            and entity.properties.summarize.complete is True
            and list(entity.properties.summarize.retrieval_terms or [])
            == expected.get("retrieval_terms")
            and entity.properties.summarize.search is expected.get("search")
            else ACTION_DRIFTED
        )
    return ACTION_APPLIED


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason recoverable action errors are asserted through full report execution
def _is_recoverable_action_error(_action, error):
    if _action.get("type") in {"update_form_schema"}:
        return False
    if _action.get("type") == "append_page_document":
        return False  # A document conflict must remain retryable, not be skipped.
    return isinstance(error, exceptions.ValidationError) and not str(error).startswith(
        "You do not have permission"
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason required placement failures are asserted through full report execution
def _is_required_file_placement(action):
    from .registry import REPORT_ACTION_ADAPTERS

    adapter = REPORT_ACTION_ADAPTERS.get(action.get("type"))
    return bool(adapter and adapter.required)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_marks_missing_file_placements_failed_and_continues
# @matrix ai-report : attachments partial-result
def _record_required_file_placement_error(action_record, error):
    action_record["status"] = "failed"
    action_record["error"] = str(error)
    action_record["note"] = "This required file placement was not completed."


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/recovery.py::_record_recoverable_action_error
# @reason recoverable action error notes are asserted through full report execution
def _recoverable_action_error_note(action_record, message):
    if message == "Referenced report file was not found.":
        return "Skipped because a referenced report file was not found."
    if action_record.get("type") == "attach_file" and message.startswith("Referenced entity not found:"):
        return "Skipped because a referenced attachment target was not found."
    if action_record.get("type") == "create_task" and message == TASK_FORM_TYPE_ERROR:
        return (
            "Skipped because the action referenced a page form instead of a task form."
        )
    return "Skipped because this action could not be completed."


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_skips_invalid_completed_task_events_and_continues
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_skips_task_that_references_page_form_and_continues
# @matrix ai-report : completed-task continue mismatched-form recoverable
def _record_recoverable_action_error(action_record, error):
    message = str(error)
    action_record["status"] = "skipped"
    action_record["error"] = message
    action_record["note"] = _recoverable_action_error_note(action_record, message)
