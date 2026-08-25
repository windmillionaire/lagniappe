"""Inspection and recoverable-error classification for report actions."""

import copy

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.tools import database

from .common import (
    PAGE_FORM_TYPE_ERROR,
    SUBMISSION_UPDATE_ROWS_ERROR,
    TASK_FORM_TYPE_ERROR,
    _data,
)
from .results import (
    _entity_result,
)
from .references import (
    _fetch_report_entity,
    _file_attached_to_endpoint,
    _load_result_entity,
)
from .forms import _submission_previous_value
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
    if action_type == "update_submission_fields":
        applied = {
            item.get("index"): item
            for item in (record.get("updates") or {}).get("applied") or []
        }
        expected["updates"] = [
            {
                "entity": (applied[index].get("entity") or {}).get("id"),
                "schema_id": update.get("schema_id") or update.get("field_id"),
                "value": copy.deepcopy(update.get("new_value")),
            }
            for index, update in enumerate((_data(action).get("updates") or []), 1)
            if index in applied
        ]
    if action_type == "rename_entity":
        expected["name"] = str(_data(action).get("name") or "").strip()
    if action_type == "update_form_schema":
        expected["schema_fingerprint"] = record.get("schema_fingerprint")
    if action_type == "summarize_file":
        expected["summary"] = (
            _data(action).get("summary") or _data(action).get("description") or ""
        ).strip()
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
    encoded = database.get.urlsafe_key(value)
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
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_validates_completed_move_and_update_prefix[move]
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_validates_completed_move_and_update_prefix[update]
# @tests tests_unit/test_020h_ai_report_execution.py::test_completed_task_retry_and_undo_restore_reused_task
# @matrix ai-report : batch-field-patch completed-prefix completed-task moves permissions post-commit-checkpoint recovery
def _inspect_action_applied(action, report, user, record):
    action_type = action.get("type")
    if record.get("status") == "skipped" or action_type in {
        "skip",
        "needs_review",
        "delete_page",
    }:
        return ACTION_APPLIED

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

    target_id = expected.get("target")
    target = _fetch_report_entity(target_id) if target_id else None
    if action_type == "add_form_to_page":
        return (
            ACTION_APPLIED
            if _stored_reference_key(entity, "form") == target_id
            else ACTION_DRIFTED
        )
    if action_type == "add_category":
        keys = [
            _urlsafe_key_value(key)
            for key in [entity.db.get("model"), *(entity.db.get("categories") or [])]
            if key
        ]
        return ACTION_APPLIED if target_id in keys else ACTION_DRIFTED
    if action_type == "move_page":
        category_ids = {
            _urlsafe_key_value(key)
            for key in [entity.db.get("model"), *(entity.db.get("categories") or [])]
            if key
        }
        return ACTION_APPLIED if target_id in category_ids else ACTION_DRIFTED
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
    if action_type == "rename_entity":
        return ACTION_APPLIED if entity.name == expected.get("name") else ACTION_DRIFTED
    if action_type == "update_submission_fields":
        for update in expected.get("updates") or []:
            target_entity = _fetch_report_entity(update.get("entity"))
            if target_entity is None:
                return ACTION_DRIFTED
            current = _submission_previous_value(target_entity, update.get("schema_id"))
            if current["value"] != update.get("value"):
                return ACTION_DRIFTED
        return ACTION_APPLIED
    if action_type == "update_form_schema":
        return (
            ACTION_APPLIED
            if _value_fingerprint(entity.schema or [])
            == expected.get("schema_fingerprint")
            else ACTION_DRIFTED
        )
    if action_type in {"attach_file_to_page", "attach_file_to_task"}:
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
            else ACTION_DRIFTED
        )
    return ACTION_APPLIED


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason compensation inspection is exercised through repeat-safe undo
def _inspect_action_compensated(record, report, user):
    action_type = record.get("type")
    before = record.get("before") or {}
    if action_type in {"skip", "needs_review", "delete_page"}:
        return ACTION_APPLIED
    if action_type.startswith("create_"):
        if record.get("created") is False:
            if action_type == "create_task" and before.get("existing_task"):
                task = _load_result_entity(before.get("entity"))
                if task is None or not _recovery_entity_allowed(task, user):
                    return ACTION_DRIFTED
                return (
                    ACTION_APPLIED
                    if _task_state_fingerprint(task)
                    == _value_fingerprint(before.get("task"))
                    else ACTION_NOT_APPLIED
                )
            return ACTION_APPLIED
        return (
            ACTION_APPLIED
            if _load_result_entity(record.get("entity")) is None
            else ACTION_NOT_APPLIED
        )

    entity = _load_result_entity(record.get("entity"))
    if entity is None:
        return ACTION_DRIFTED
    if action_type == "add_form_to_page":
        previous_id = (before.get("form") or {}).get("id")
        return (
            ACTION_APPLIED
            if _stored_reference_key(entity, "form") == previous_id
            else ACTION_NOT_APPLIED
        )
    if action_type == "add_category":
        target_id = (record.get("target") or {}).get("id")
        keys = {
            _urlsafe_key_value(key)
            for key in [entity.db.get("model"), *(entity.db.get("categories") or [])]
            if key
        }
        present = target_id in keys
        expected_present = bool(before.get("had_category"))
        return ACTION_APPLIED if present is expected_present else ACTION_NOT_APPLIED
    if action_type in {"move_page", "move_task"}:
        previous_id = (before.get("parent") or {}).get("id")
        if action_type == "move_page":
            category_ids = {
                _urlsafe_key_value(key)
                for key in [
                    entity.db.get("model"),
                    *(entity.db.get("categories") or []),
                ]
                if key
            }
            return ACTION_APPLIED if previous_id in category_ids else ACTION_NOT_APPLIED
        return (
            ACTION_APPLIED
            if _stored_reference_key(entity, "page") == previous_id
            else ACTION_NOT_APPLIED
        )
    if action_type == "move_file":
        source = _load_result_entity(before.get("source"))
        target = _load_result_entity(before.get("target"))
        if source is None or target is None:
            return ACTION_DRIFTED
        return (
            ACTION_APPLIED
            if _file_attached_to_endpoint(entity, source)
            and not _file_attached_to_endpoint(entity, target)
            else ACTION_NOT_APPLIED
        )
    if action_type == "rename_entity":
        return (
            ACTION_APPLIED if entity.name == before.get("name") else ACTION_NOT_APPLIED
        )
    if action_type == "update_submission_fields":
        for previous in before.get("updates") or []:
            target = _load_result_entity(previous.get("entity"))
            if target is None:
                return ACTION_DRIFTED
            current = _submission_previous_value(target, previous.get("schema_id"))
            if current["had_value"] != previous.get("had_value") or current[
                "value"
            ] != previous.get("previous_value"):
                return ACTION_NOT_APPLIED
        return ACTION_APPLIED
    if action_type == "update_form_schema":
        return (
            ACTION_APPLIED
            if _value_fingerprint(entity.schema or [])
            == _value_fingerprint(before.get("schema") or [])
            else ACTION_NOT_APPLIED
        )
    if action_type in {"attach_file_to_page", "attach_file_to_task"}:
        target = _load_result_entity(record.get("target"))
        if target is None:
            return ACTION_DRIFTED
        linked = _file_attached_to_endpoint(entity, target)
        return (
            ACTION_APPLIED
            if linked is bool(before.get("linked"))
            else ACTION_NOT_APPLIED
        )
    if action_type == "summarize_file":
        summarize = entity.properties.summarize
        previous = before.get("summarize") or {}
        restored = (
            entity.summary == before.get("summary")
            and summarize.enabled == previous.get("enabled")
            and summarize.search == previous.get("search")
            and summarize.status == previous.get("status")
            and summarize.error == previous.get("error")
            and summarize.complete == previous.get("complete")
        )
        return ACTION_APPLIED if restored else ACTION_NOT_APPLIED
    return ACTION_APPLIED


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason recoverable action errors are asserted through full report execution
def _is_recoverable_action_error(_action, error):
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
    if action_record.get("type") in {
        "attach_file_to_page",
        "attach_file_to_task",
    } and message.startswith("Referenced entity not found:"):
        return "Skipped because a referenced attachment target was not found."
    if action_record.get("type") == "create_task" and message == TASK_FORM_TYPE_ERROR:
        return (
            "Skipped because the action referenced a page form instead of a task form."
        )
    if (
        action_record.get("type") == "add_form_to_page"
        and message == PAGE_FORM_TYPE_ERROR
    ):
        return (
            "Skipped because the action referenced a task form instead of a page form."
        )
    if (
        action_record.get("type") == "update_submission_fields"
        and message == SUBMISSION_UPDATE_ROWS_ERROR
    ):
        return "Skipped because no executable submission field updates were provided."
    return "Skipped because this action could not be completed."


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_skips_empty_submission_update_and_continues
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_skips_invalid_completed_task_events_and_continues
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_skips_task_that_references_page_form_and_continues
# @matrix ai-report : completed-task continue empty-update mismatched-form recoverable
def _record_recoverable_action_error(action_record, error):
    message = str(error)
    action_record["status"] = "skipped"
    action_record["error"] = message
    action_record["note"] = _recoverable_action_error_note(action_record, message)
