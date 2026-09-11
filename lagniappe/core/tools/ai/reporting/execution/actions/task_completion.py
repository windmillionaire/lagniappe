"""Check off existing Tasks without importing/replacing a historical event."""

from copy import deepcopy

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get

from .....database.assets import cleanup_rejected_attempt, record_attempt_asset
from .....form_definitions import compatible_values, stage_completion_guards
from .common import _data, _require_allowed
from .completed_tasks import (
    _checkpoint_datetime,
    _restore_checkpoint_datetime,
    _value_fingerprint,
    _task_state_fingerprint,
    _checkpoint_entities,
    _task_checkpoint_state,
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
        "task_state_fingerprint": _task_state_fingerprint(task),
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
# @tests tests_unit/test_020h_ai_report_execution.py::test_complete_task_undo_recovers_after_save_and_retains_history
# @matrix ai-report task-completion : preservation recovery undo drift
def _undo_complete_task(record, report, user):
    task = _load_result_entity(record.get("entity"))
    _require_allowed(
        isinstance(task, Entities.TASK) and task.allowed(Action.EDIT, user=user),
        "You do not have permission to undo this task completion.",
    )
    before = record["before"]["completion_state"]
    state = record["before"]["task"]
    history_refs = record.get("created_histories") or ([{
        "id": record["history_output_key"], "kind": "task_history",
    }] if record.get("history_output_key") else [])
    histories = _checkpoint_entities(history_refs)
    if not task.completed and histories and _completion_state(task) == before:
        current, expected = _task_checkpoint_state(task), deepcopy(state)
        # Reopening retains a completion and gives copied assets independent
        # paths. Compare their value identity when recovering an interrupted undo.
        for candidate in (current, expected):
            candidate.pop("history", None)
            candidate.pop("schema_version", None)
            candidate["assets"] = {name: {key: value for key, value in asset.items()
                if key not in {"path", "generation"}} for name, asset in candidate["assets"].items()}
        if current == expected:
            return {"entity": _entity_result(task), "note": "Task reopened; original completion retained."}
    if _completion_state(task) != record.get("completion_state"):
        raise exceptions.ValidationError(
            "Task completion changed after this report; undo would overwrite newer work."
        )
    if before["completed"]:
        return {
            "entity": _entity_result(task),
            "note": "Pre-existing completion left unchanged.",
        }
    if _task_state_fingerprint(task) != record.get("task_state_fingerprint"):
        raise exceptions.ValidationError(
            "The task changed after completion; undo would overwrite newer work."
        )

    source = task if task.completed else next(iter(histories), None)
    if source is None or (source is not task and source.properties.task.key != task.key):
        raise exceptions.ValidationError("The original completion is unavailable; undo needs review.")
    definition = source.submission_definition
    values = deepcopy(state.get("submission") or {})
    defaults = deepcopy(state.get("default_submission") or {})
    prior_form = (state.get("form") or {}).get("id")
    if prior_form != (task.form.urlsafe_key if task.form else None):
        raise exceptions.ValidationError("The task form changed; undo needs review.")
    if definition.error and (values or defaults):
        raise exceptions.ValidationError(definition.error)
    schema = task.form.schema if task.form else []
    compatible_values(definition.schema, schema, values)
    compatible_values(definition.schema, schema, defaults)
    try:
        if task.completed:
            key = database_get.datastore_key(record.get("history_output_key"))
            task.uncomplete(history_key=key)
            source = task.new_history_created[-1]
        else:
            stage_completion_guards(task)
        for name in state.get("assets", {}):
            asset = source.get_asset(name)
            copied = task.copy_asset(asset, name, isolated=True) if asset else None
            if not copied:
                raise exceptions.ValidationError("An original answer attachment is unavailable; undo needs review.")
            record_attempt_asset(task, copied.definition)
        task.properties.submission._fields = None
        task.submission = values
        task._set_default_submission(defaults)
        task.files = _checkpoint_entities(state.get("files"))
        task.linked_pages = _checkpoint_entities(state.get("linked_pages"))
        task.due_date = _restore_checkpoint_datetime(before["due_date"])
        task._clear_scheduled_uncomplete()
        if before.get("scheduled_uncomplete_token"):
            task.db["scheduled_uncomplete_token"] = before["scheduled_uncomplete_token"]
            task.db["scheduled_uncomplete_at"] = _restore_checkpoint_datetime(
                before["scheduled_uncomplete_at"]
            )
    except Exception:
        for owner in (task, *task.new_history_created):
            cleanup_rejected_attempt(owner)
        raise
    Entities.save(task)
    return {
        "entity": _entity_result(task),
        "note": "Task reopened and prior active values restored; original completion retained.",
    }
