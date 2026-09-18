"""Check off existing Tasks without importing/replacing a historical event."""


from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get

from .common import _data, _require_allowed
from .completed_tasks import _checkpoint_datetime, _value_fingerprint, _task_state_fingerprint
from .references import _resolve_entity
from .results import _entity_result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/task_completion.py::_complete_task
# @reason recovery compare only the completion-owned state
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
# @tests tests_unit/test_020h_ai_report_execution.py::test_complete_task_action_preserves_details_and_retries
# @tests tests_unit/test_020h_ai_report_execution.py::test_complete_task_action_requires_permission_and_required_fields
# @matrix ai-report task-completion : complete preservation permissions required-fields recovery
def _complete_task(action, report, user, created, context=None):
    task = _resolve_entity(_data(action).get("task"), created, expected=Entities.TASK)
    _require_allowed(
        task.allowed(Action.EDIT, user=user),
        "You do not have permission to complete this task.",
    )
    context = context or {}
    for dependency in action.get("depends_on") or []:
        prior = context.get("action_records", {}).get(dependency) or {}
        if prior.get("status") != "complete":
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
        "task_state_fingerprint": _task_state_fingerprint(task),
    }
    if histories:
        metadata.update(
            created_histories=[_entity_result(history) for history in histories],
            task_state_fingerprint=_task_state_fingerprint(task),
            note="Recorded completion in task history and reopened the next occurrence.",
        )
    return task, [task], metadata
