"""Reviewed calendar-date edits to existing incomplete Tasks."""

from datetime import date, datetime

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.tools import dates

from ...schedules import validate_task_due_date
from .common import _data, _require_allowed
from .completed_tasks import _checkpoint_datetime, _restore_checkpoint_datetime, _value_fingerprint
from .references import _load_result_entity, _resolve_entity
from .results import _entity_result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/task_dates.py::_set_task_due_date
# @reason execution, recovery, and undo compare date and scheduling state
def _due_date_state(task):
    return {
        "due_date": _checkpoint_datetime(task.due_date),
        "postponed_from": _checkpoint_datetime(task.postponed_from),
        "completed": bool(task.completed),
        "completed_on": _checkpoint_datetime(task.completed_on),
        "schedule_fingerprint": _value_fingerprint(task.properties.schedule.value),
        "scheduled_uncomplete_token": task.scheduled_uncomplete_token,
        "scheduled_uncomplete_at": _checkpoint_datetime(task.scheduled_uncomplete_at),
    }


# @testable true
# @tests tests_unit/test_032f_task_due_date_action.py::test_due_date_action_sets_clears_retries_and_undoes
# @tests tests_unit/test_032f_task_due_date_action.py::test_due_date_action_rejects_uneditable_or_completed_tasks
# @matrix ai-report task-scheduling : due-date preservation permissions recovery undo
def _set_task_due_date(action, _report, user, created):
    data = _data(action)
    value = validate_task_due_date(data["due_date"])
    task = _resolve_entity(data.get("task"), created, expected=Entities.TASK)
    _require_allowed(task.allowed(Action.EDIT, user=user),
                     "You do not have permission to change this task's due date.")
    if task.completed:
        raise exceptions.ValidationError("Reopen the completed task before changing its due date.")
    user_tz = dates.user_timezone(user)
    current_date = task.due_date.astimezone(user_tz).date().isoformat() if task.due_date else None
    if current_date == value:
        return task, [], {"due_date_state": _due_date_state(task), "note": "Due date already matches."}

    # Match the calendar editor: retain the current local time on the chosen
    # date, then let the DueDate property store UTC. No recurrence reset occurs.
    task.due_date = (
        datetime.combine(date.fromisoformat(value), datetime.now(user_tz).timetz())
        if value is not None else None
    )
    return task, [task], {
        "due_date_state": _due_date_state(task),
        "note": f"Set due date to {value}." if value is not None else "Cleared due date.",
    }


# @testable true
# @tests tests_unit/test_032f_task_due_date_action.py::test_due_date_action_sets_clears_retries_and_undoes
# @tests tests_unit/test_032f_task_due_date_action.py::test_due_date_undo_rejects_newer_scheduling_changes
# @matrix ai-report task-scheduling : due-date preservation recovery undo drift
def _undo_task_due_date(record, _report, user):
    task = _load_result_entity(record.get("entity"))
    _require_allowed(isinstance(task, Entities.TASK) and task.allowed(Action.EDIT, user=user),
                     "You do not have permission to undo this task's due-date change.")
    if _due_date_state(task) != record.get("due_date_state"):
        raise exceptions.ValidationError("Task scheduling changed after this report; undo would overwrite newer work.")
    task.due_date = _restore_checkpoint_datetime(record["before"]["due_date_state"]["due_date"])
    Entities.save(task)
    return {"entity": _entity_result(task), "note": "Restored the previous due date."}
