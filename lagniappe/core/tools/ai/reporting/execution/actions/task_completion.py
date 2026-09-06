"""Check off existing Tasks without importing/replacing a historical event."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get

from .common import _data, _require_allowed
from .completed_tasks import (
    _checkpoint_datetime,
    _restore_checkpoint_datetime,
    _value_fingerprint,
    _task_state_fingerprint,
    _undo_reused_completed_task,
    _checkpoint_entities,
)
from .references import _load_result_entity, _resolve_entity
from .results import _entity_result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/task_completion.py::_complete_task
# @reason recovery and undo compare only the completion-owned state
def _completion_state(task):
    return {
        "completed": bool(task.completed),
        "completed_on": _checkpoint_datetime(task.completed_on),
        "completed_by": _entity_result(task.completed_by)
        if task.completed_by
        else None,
        "due_date": _checkpoint_datetime(task.due_date),
        "scheduled_uncomplete_token": task.scheduled_uncomplete_token,
        "scheduled_uncomplete_at": _checkpoint_datetime(task.scheduled_uncomplete_at),
        "schedule_fingerprint": _value_fingerprint(task.properties.schedule.value),
    }


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_complete_task_action_preserves_details_retries_and_undoes
# @tests tests_unit/test_020h_ai_report_execution.py::test_complete_task_action_requires_permission_and_required_fields
# @matrix ai-report task-completion : complete preservation permissions required-fields recovery undo
def _complete_task(action, report, user, created, context=None):
    task = _resolve_entity(_data(action).get("task"), created, expected=Entities.TASK)
    _require_allowed(
        task.allowed(Action.EDIT, user=user),
        "You do not have permission to complete this task.",
    )
    context = context or {}
    for dependency in action.get("depends_on") or []:
        prior = context.get("action_records", {}).get(dependency) or {}
        skipped = (prior.get("updates") or {}).get("skipped") or []
        unsuccessful = any(
            item.get("reason")
            not in {"Value did not change.", "Value did not change after validation."}
            for item in skipped
        )
        if prior.get("status") != "complete" or unsuccessful:
            raise exceptions.ValidationError(
                "Required prior updates did not finish; this task was not completed."
            )
    if task.completed:
        return (
            task,
            [],
            {
                "note": "Task was already complete; no changes made.",
                "completion_state": _completion_state(task),
            },
        )
    record = context.get("action_record") or {}
    history_key = context.get("prepared_keys", {}).get(
        f"{record.get('idempotency_key')}:history"
    )
    if history_key is None and record.get("history_output_key"):
        history_key = database_get.datastore_key(record["history_output_key"])
    previous_histories = {history.urlsafe_key for history in task.new_history_created}
    task.complete(user=user, history_key=history_key)
    histories = [
        history
        for history in task.new_history_created
        if history.urlsafe_key not in previous_histories
    ]
    metadata = {
        "note": "Completed existing task.",
        "completion_state": _completion_state(task),
    }
    if histories:
        metadata.update(
            created_histories=[_entity_result(history) for history in histories],
            task_state_fingerprint=_task_state_fingerprint(task),
            note="Recorded completion in task history and reopened the next occurrence.",
        )
    return task, [task], metadata


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_complete_task_action_preserves_details_retries_and_undoes
# @tests tests_unit/test_020h_ai_report_execution.py::test_complete_task_undo_rejects_changed_completion
# @tests tests_unit/test_020h_ai_report_execution.py::test_complete_task_undo_resumes_history_cleanup
# @matrix ai-report task-completion : preservation recovery undo drift
def _undo_complete_task(record, report, user):
    task = _load_result_entity(record.get("entity"))
    _require_allowed(
        isinstance(task, Entities.TASK) and task.allowed(Action.EDIT, user=user),
        "You do not have permission to undo this task completion.",
    )
    before = record["before"]["completion_state"]
    if (
        record.get("created_histories")
        and _completion_state(task) == before
        and _task_state_fingerprint(task)
        == _value_fingerprint(record["before"]["task"])
    ):
        # A previous undo may have restored the task before history deletion failed.
        histories = _checkpoint_entities(record["created_histories"])
        if histories:
            Entities.delete(*histories)
        return {
            "entity": _entity_result(task),
            "note": "Finished completion-history cleanup.",
        }
    if _completion_state(task) != record.get("completion_state"):
        raise exceptions.ValidationError(
            "Task completion changed after this report; undo would overwrite newer work."
        )
    if before["completed"]:
        return {
            "entity": _entity_result(task),
            "note": "Pre-existing completion left unchanged.",
        }
    if record.get("created_histories"):
        if _task_state_fingerprint(task) != record.get("task_state_fingerprint"):
            raise exceptions.ValidationError(
                "The reopened task changed after completion; undo would overwrite newer work."
            )
        return _undo_reused_completed_task(record, user)
    # Undo is not Task.uncomplete(): that archives and clears submissions/files.
    task.completed = before["completed"]
    task.completed_on = _restore_checkpoint_datetime(before["completed_on"])
    task.completed_by = _load_result_entity(before.get("completed_by"))
    task.due_date = _restore_checkpoint_datetime(before["due_date"])
    task._clear_scheduled_uncomplete()
    if before.get("scheduled_uncomplete_token"):
        task.db["scheduled_uncomplete_token"] = before["scheduled_uncomplete_token"]
        task.db["scheduled_uncomplete_at"] = _restore_checkpoint_datetime(
            before["scheduled_uncomplete_at"]
        )
    Entities.save(task)
    return {
        "entity": _entity_result(task),
        "note": "Restored previous completion state without clearing task details.",
    }
