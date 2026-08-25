"""Completed-task reuse, history, recovery, and compensation."""

import copy
import hashlib
import json
import re
from datetime import datetime

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, MutationIntent
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database, dates

from ....debug import ai_debug
from .common import (
    _first_data_reference,
    _require_allowed,
    _safe_entity_relation,
    _stored_relation_key,
    _unique_entities,
)
from .results import (
    _capture_missing_task_submission,
    _diagnostic_entity,
    _entity_result,
    _submission_result,
    _task_structure_result,
)
from .references import (
    _load_result_entity,
    _resolve_action_page,
    _resolve_entity,
)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason before-state serialization is exercised through compensation tests
def _snapshot_entity(entity):
    return _entity_result(entity) if entity is not None else None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason checkpoint date serialization is exercised through task recovery
def _checkpoint_datetime(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason task checkpoint content is asserted through task recovery and undo
def _task_checkpoint_state(task):
    if task is None:
        return None
    return {
        "entity": _entity_result(task),
        "name": task.name,
        "description": task.description,
        "completed": bool(task.completed),
        "completed_on": _checkpoint_datetime(task.completed_on),
        "due_date": _checkpoint_datetime(task.due_date),
        "submission": copy.deepcopy(task.submission),
        "history": bool(task.db.get("history", False)),
        "page": _snapshot_entity(task.page),
        "form": _snapshot_entity(task.form),
        "project": _snapshot_entity(task.project),
        "model": _snapshot_entity(task.model),
        "assigned_to": _snapshot_entity(task.assigned_to),
        "assigned_by": _snapshot_entity(task.assigned_by),
        "completed_by": _snapshot_entity(task.completed_by),
        "linked_pages": [_entity_result(page) for page in task.linked_pages or []],
        "files": [_entity_result(file) for file in task.files or []],
        "assets": copy.deepcopy(getattr(task, "assets", {}) or {}),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason completed-task checkpointing is asserted through retry and undo
def _capture_completed_task_before(action, data, user, created):
    page = _resolve_action_page(data, created, user)
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
        optional=True,
    )
    project = _resolve_entity(
        data.get("project")
        or data.get("project_id")
        or data.get("project_ref")
        or data.get("project_action"),
        created,
        expected=Entities.PROJECT,
        optional=True,
    )
    model = _resolve_entity(
        data.get("model")
        or data.get("model_id")
        or data.get("model_ref")
        or data.get("model_action"),
        created,
        expected=Entities.MODEL_TASK,
        optional=True,
    )
    form = form or _model_task_form(model)
    existing = _find_completed_task_match(
        action,
        data,
        created,
        page,
        form,
        project,
        model,
        user,
    )
    return {
        "existing_task": existing is not None,
        "task": _task_checkpoint_state(existing),
        "entity": _snapshot_entity(existing),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason state fingerprints are exercised through completed-prefix validation
def _value_fingerprint(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason task state validation is exercised through completed-task retry
def _task_state_fingerprint(task):
    return _value_fingerprint(_task_checkpoint_state(task))


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/tasks.py::_create_task
# @reason completed task event detection is covered through report-run behavior
def _is_completed_task_event(data):
    return bool(
        data.get("completed_on") or data.get("completed-on") or data.get("completed")
    )


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_records_dateless_historical_task_completion
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_records_older_completed_event_without_mutating_live_task
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_promotes_newer_completed_event_to_live_task
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_reuses_one_created_task_for_multiple_completed_events
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_keeps_untargeted_same_model_tasks_distinct
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_loads_model_task_form_from_stored_key_for_history
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_reuses_existing_task_for_completed_event
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_automatically_reuses_dated_completed_task_family
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_keeps_ambiguous_completed_task_families_distinct
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_rejects_completed_task_target_from_another_page
# @matrix ai-report task-completion tasks : ambiguity attachments automatic-task-family completed-task description distinct-task duplicate-task-prevention existing-task explicit-task-identity history-name lazy-load live-task model-form name newest-completion older-event period-name same-model same-report submission
def _record_completed_task_event(
    action,
    data,
    page,
    form,
    project,
    model,
    report,
    user,
    created,
    context,
):
    action_record = context.get("action_record") or {}
    completed_on = _parse_completed_task_completed_on(data)
    submission = data.get("submission") if "submission" in data else None

    task, created_task = _find_or_create_completed_task(
        action,
        data,
        page,
        form,
        project,
        model,
        user,
        created,
    )
    _ensure_task_form_from_model(task, model)
    if form and not getattr(task, "form", None):
        task.form = form

    if created_task:
        name = _completed_event_task_name(action, data, page, model)
    else:
        name = task.name or _completed_event_task_name(action, data, page, model)
    description = data.get("description")
    project = _safe_entity_relation(task, "project") or project
    model = _safe_entity_relation(task, "model") or model
    task_form = _safe_entity_relation(task, "form") or form
    ai_debug(
        "report_runner.completed_task_event.resolved",
        report=_diagnostic_entity(report),
        action={
            "id": action.get("id"),
            "type": action.get("type"),
            "display_label": action.get("display_label"),
            "data_keys": sorted(data.keys()),
            "completed_on": completed_on,
            "submission_key_present": "submission" in data,
            "submission_field_count": (
                len(submission) if isinstance(submission, dict) else None
            ),
        },
        task=_diagnostic_entity(task),
        created_task=created_task,
        page=_diagnostic_entity(page),
        project=_diagnostic_entity(project),
        model=_diagnostic_entity(model),
        form=_diagnostic_entity(task_form),
        files=[],
    )
    if task_form is not None and "submission" not in data:
        _capture_missing_task_submission(
            action,
            data,
            report,
            page,
            project,
            model,
            task_form,
        )
    if _completed_event_belongs_in_history(task, completed_on):
        history_key = context.setdefault("prepared_keys", {}).get(
            action_record.get("idempotency_key")
        )
        if history_key is None and action_record.get("output_key"):
            history_key = database.get.datastore_key(action_record["output_key"])
        history = task.create_history_entry(
            completed_on=completed_on,
            files=[],
            submission=submission,
            name=name,
            description=description,
            form=task_form,
            history_key=history_key,
        )
        metadata = _task_structure_result(task, project, model, task_form)
        metadata.update(
            {
                "page": _entity_result(page),
                "created": True,
                "target": _entity_result(task),
                "submission": _submission_result(
                    history,
                    data.get("submission_empty_reason"),
                ),
                "task_state_fingerprint": _task_state_fingerprint(task),
                "note": "Recorded as task history.",
            }
        )
        return history, _unique_entities([history, task]), metadata

    archived = []
    if _should_archive_live_completion(task):
        history_key = context.setdefault("prepared_keys", {}).get(
            f"{action_record.get('idempotency_key')}:history"
        )
        if history_key is None and action_record.get("history_output_key"):
            history_key = database.get.datastore_key(
                action_record["history_output_key"]
            )
        task.uncomplete(history_key=history_key)
        archived = list(getattr(task, "new_history_created", []) or [])

    _apply_completed_task_event(
        task,
        name,
        description,
        completed_on,
        [],
        submission,
        task_form,
    )
    saved = [task, page]
    for history in archived:
        saved.extend([history, *history.files])

    metadata = _task_structure_result(task, project, model, task_form)
    metadata.update(
        {
            "page": _entity_result(page),
            "created": created_task,
            "target": _entity_result(task),
            "submission": _submission_result(
                task,
                data.get("submission_empty_reason"),
            ),
            "created_histories": [_entity_result(history) for history in archived],
            "task_state_fingerprint": _task_state_fingerprint(task),
            "note": (
                "Moved the previous completion to history."
                if archived
                else "Recorded as the task's current completion."
            ),
        }
    )
    return task, _unique_entities(saved), metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason task reuse is covered through completed event report-run tests
def _find_or_create_completed_task(
    action,
    data,
    page,
    form,
    project,
    model,
    user,
    created,
):
    task = _find_completed_task_match(
        action,
        data,
        created,
        page,
        form,
        project,
        model,
        user,
    )
    if task is not None:
        return task, False

    name = _completed_event_task_name(action, data, page, model)
    task = Entities.TASK.create(
        {
            "page": page,
            "name": name,
            "description": data.get("description"),
            "form": form,
            "project": project,
            "model": model,
        }
    )
    return task, True


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_find_or_create_completed_task
# @reason task naming is verified through report-run completed event tests
def _completed_event_task_name(action, data, page, model):
    raw_name = data.get("name") or ""
    name = _strip_history_event_name(raw_name, getattr(page, "name", None))
    if name:
        return name
    if model and getattr(model, "name", None):
        return model.name
    return "Generated task"


_MONTH_NAMES = (
    "jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|"
    "aug|august|sep|sept|september|oct|october|nov|november|dec|december"
)
_NUMERIC_DATE_PATTERN = (
    r"(?:\d{4}[-_/ ]\d{1,2}[-_/ ]\d{1,2}|"
    r"\d{1,2}[-_/ ]\d{1,2}[-_/ ]\d{2,4})"
)
_MONTH_DATE_PATTERN = (
    rf"(?:(?:{_MONTH_NAMES})\.?\s+\d{{1,2}},?\s+\d{{4}}|"
    rf"(?:{_MONTH_NAMES})\.?\s+\d{{4}})"
)
_EVENT_DATE_PATTERN = rf"(?:{_NUMERIC_DATE_PATTERN}|{_MONTH_DATE_PATTERN})"


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_completed_event_task_name
# @reason normalized names are covered through report-run completed event tests
def _strip_history_event_name(value, page_name=None):
    name = " ".join(str(value or "").replace("_", " ").split())
    name = re.sub(r"\.(pdf|png|jpe?g|heic|txt|csv)$", "", name, flags=re.I)
    for _ in range(3):
        before = name
        name = re.sub(rf"^\s*{_EVENT_DATE_PATTERN}\s+", "", name, flags=re.I)
        name = _strip_leading_page_name(name, page_name)
        name = re.sub(
            rf"\s*(?:-|:|,)?\s*{_EVENT_DATE_PATTERN}\s*$",
            "",
            name,
            flags=re.I,
        )
        name = re.sub(
            (
                r"\s+(?:receipt|bill|invoice|payment confirmation|"
                r"confirmation|certificate|instal{1,2}ments?)\s*$"
            ),
            "",
            name,
            flags=re.I,
        )
        name = name.strip(" -:,.")
        if name == before:
            break
    return name or None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_strip_history_event_name
# @reason page prefix cleanup is covered through report-run tracker reuse tests
def _strip_leading_page_name(name, page_name):
    if not page_name:
        return name
    return re.sub(
        rf"^\s*{re.escape(str(page_name).strip())}\b\s*(?:-|:)?\s*",
        "",
        name,
        flags=re.I,
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_find_or_create_completed_task
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_capture_completed_task_before
# @reason deterministic task-family matching is exercised through report-run reuse tests
def _find_completed_task_match(
    action,
    data,
    created,
    page,
    form,
    project,
    model,
    user,
):
    """Resolve an explicit target or one unambiguous completed-task family."""
    task = _resolve_completed_task_target(
        data,
        created,
        page,
        form,
        project,
        model,
        user,
        optional=True,
    )
    if task is not None:
        return task

    name = _completed_event_task_name(action, data, page, model)
    matches = [
        candidate
        for candidate in _completed_task_candidates(page, created)
        if candidate.allowed(Action.EDIT, user=user)
        and _completed_task_family_matches(
            candidate,
            page,
            project,
            model,
            form,
            name,
        )
    ]
    return matches[0] if len(matches) == 1 else None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_find_completed_task_match
# @reason candidate collection is exercised through completed-task reuse and retry tests
def _completed_task_candidates(page, created):
    candidates = [*_page_task_candidates(page)]
    candidates.extend(
        entity
        for entity in created.values()
        if isinstance(entity, Entities.TASK)
        and _same_entity(_safe_entity_relation(entity, "page"), page)
    )
    unique = {}
    for task in candidates:
        key = getattr(task, "key", None)
        if key is not None:
            unique[key] = task
    return list(unique.values())


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_find_completed_task_match
# @reason exact task-family matching is exercised through completed-task reuse tests
def _completed_task_family_matches(task, page, project, model, form, name):
    if not _same_entity(_safe_entity_relation(task, "page"), page):
        return False
    if not _same_entity(_safe_entity_relation(task, "model"), model):
        return False
    if project is not None and not _same_entity(
        _safe_entity_relation(task, "project"), project
    ):
        return False

    task_form = _safe_entity_relation(task, "form") or _model_task_form(
        _safe_entity_relation(task, "model")
    )
    if form is not None and not _same_entity(task_form, form):
        return False

    return _normalized_task_name_key(task.name) == _normalized_task_name_key(name)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_completed_task_family_matches
# @reason normalized task-family names are exercised through dated completed-task reuse tests
def _normalized_task_name_key(name):
    name = _strip_history_event_name(name) or str(name or "")
    name = re.sub(r"[^a-z0-9]+", " ", name.lower())
    return " ".join(name.split())


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_find_completed_task_match
# @reason page task loading fallback is covered through completed-task reuse tests
def _page_task_candidates(page):
    candidates = []
    for attr in ("_tasks", "_completed"):
        values = getattr(page, attr, None)
        if isinstance(values, list):
            candidates.extend(values)

    if not candidates:
        try:
            candidates.extend(page.tasks or [])
            candidates.extend(page.completed or [])
        except Exception:
            pass

    unique = {}
    for task in candidates:
        key = getattr(task, "key", None)
        if key:
            unique[key] = task
    return list(unique.values())


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_rejects_completed_task_target_from_another_page
# @matrix ai-report : explicit-task-identity page-validation
# @matrix task-completion tasks : page-validation
def _resolve_completed_task_target(
    data,
    created,
    page,
    form,
    project,
    model,
    user,
    optional=False,
):
    reference = _first_data_reference(data, "task")
    if not reference:
        if optional:
            return None
        raise exceptions.ValidationError("Missing required task reference.")

    task = _resolve_entity(reference, created, expected=Entities.TASK)
    _require_allowed(
        task.allowed(Action.EDIT, user=user),
        "You do not have permission to record history for this task.",
    )
    if not _same_entity(_safe_entity_relation(task, "page"), page):
        raise exceptions.ValidationError(
            "Completed task target does not belong to the referenced page."
        )

    actual_project = _safe_entity_relation(task, "project")
    actual_model = _safe_entity_relation(task, "model")
    actual_form = _safe_entity_relation(task, "form") or _model_task_form(actual_model)
    for label, supplied, actual in (
        ("project", project, actual_project),
        ("model task", model, actual_model),
        ("form", form, actual_form),
    ):
        if supplied is not None and not _same_entity(supplied, actual):
            raise exceptions.ValidationError(
                f"Completed task target has a different {label}."
            )
    return task


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_resolve_completed_task_target
# @reason relation identity comparison is exercised through completed-target validation
def _same_entity(left, right):
    if left is None or right is None:
        return left is right
    return getattr(left, "key", None) == getattr(right, "key", None)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason archive suppression is verified through completion promotion tests
def _should_archive_live_completion(task):
    if not task.completed:
        return False
    return bool(task.completed_on or task.files or _task_has_submission_data(task))


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason dated and dateless event placement is exercised through report-run completion tests
def _completed_event_belongs_in_history(task, completed_on):
    if not task.completed:
        return False
    if completed_on is None:
        return True
    current_completed_on = task.completed_on
    return current_completed_on is not None and completed_on <= current_completed_on


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason live task mutation is verified through completion event tests
def _apply_completed_task_event(
    task,
    name,
    description,
    completed_on,
    files,
    submission,
    form,
):
    task.name = name
    task.description = description
    if form:
        task.form = form
    task.completed = True
    task.completed_on = completed_on
    task.completed_by = None
    task.assigned_to = None
    task.due_date = None
    task.files = list(files or [])
    if submission is not None:
        task.ai_submission(submission)
    else:
        task.submission = None
        task.linked_pages = []


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason blank-submission detection is exercised through completion event tests
def _task_has_submission_data(task):
    return bool(getattr(task, "submission", None))


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/tasks.py::_create_task
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason model-form inheritance is verified through report-run completed event tests
def _model_task_form(model):
    if model is None:
        return None

    form_property = getattr(getattr(model, "properties", None), "form", None)
    if form_property is not None and getattr(form_property, "is_set", False):
        form = form_property.value
        if form is not None:
            return form

    form_key = _stored_relation_key(model, "form")
    if not form_key:
        return None

    form = Entities.fetch_one(form_key, request=Fetch.direct())
    if form is not None:
        exceptions.capture(
            "AI report runner recovered a model task form from a stored relation key.",
            context={
                "ai_report_runner": {
                    "operation": "model_task_form_relation_recovered",
                    "model": _diagnostic_entity(model),
                    "form": _diagnostic_entity(form),
                    "form_key": str(form_key),
                }
            },
            level="warning",
        )
    else:
        exceptions.capture(
            "AI report runner found a model task form key but could not load the form.",
            context={
                "ai_report_runner": {
                    "operation": "model_task_form_relation_missing",
                    "model": _diagnostic_entity(model),
                    "form_key": str(form_key),
                }
            },
            level="warning",
        )
    return form if isinstance(form, Entities.FORM) else None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/tasks.py::_create_task
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason existing task repair is verified through report-run completed event tests
def _ensure_task_form_from_model(task, model=None):
    if getattr(task, "form", None):
        return
    form = _model_task_form(model or getattr(task, "model", None))
    if form is not None:
        task.form = form


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_skips_invalid_completed_task_events_and_continues
# @matrix ai-report : completed-task validation
def _parse_completed_task_completed_on(data):
    raw = data.get("completed_on") or data.get("completed-on")
    if not raw and data.get("completed") is True:
        return None
    raw = raw or data.get("completed")
    if not raw:
        raise exceptions.ValidationError(
            "Completed task evidence requires completed: true or a date."
        )

    completed_on = dates.parse_imported_date_as_utc(raw)
    if not completed_on:
        raise exceptions.ValidationError(
            "Completed task evidence completion date is invalid."
        )
    return completed_on


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason checkpoint resolution is exercised through completed-task undo
def _checkpoint_entity(details):
    return _load_result_entity(details) if details else None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason checkpoint resolution is exercised through completed-task undo
def _checkpoint_entities(details):
    return [
        entity
        for entity in (_checkpoint_entity(item) for item in details or [])
        if entity is not None
    ]


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason date restoration is exercised through completed-task undo
def _restore_checkpoint_datetime(value):
    if not value or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason asset restoration is owned by completed-task compensation
def _restore_task_checkpoint_assets(task, state, histories):
    previous = copy.deepcopy(state.get("assets") or {})
    for name, definition in list(task.assets.items()):
        if previous.get(name) != definition:
            task.delete_asset(name)

    task._assets = previous
    task.db["assets"] = json.dumps(previous)
    for history in histories:
        for name in list(getattr(history, "assets", {}).keys()):
            if name in previous:
                task.copy_asset(history.get_asset(name), name)


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_completed_task_retry_and_undo_restore_reused_task
# @matrix ai-report : compensation completed-task reuse
def _undo_reused_completed_task(action, user):
    before = action.get("before") or {}
    state = before.get("task") or {}
    task = _load_result_entity(before.get("entity"))
    if task is None:
        return {"note": "Reused task is missing."}
    _require_allowed(
        task.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this task.",
    )

    histories = _checkpoint_entities(action.get("created_histories"))
    _restore_task_checkpoint_assets(task, state, histories)
    current_relations = [
        getattr(task, name, None)
        for name in (
            "page",
            "form",
            "project",
            "model",
            "assigned_to",
            "assigned_by",
            "completed_by",
        )
    ]
    current_relations.extend(list(task.linked_pages or []))
    current_relations.extend(list(task.files or []))

    task.name = state.get("name")
    task.description = state.get("description")
    task.completed = bool(state.get("completed"))
    task.completed_on = _restore_checkpoint_datetime(state.get("completed_on"))
    task.due_date = _restore_checkpoint_datetime(state.get("due_date"))
    task.submission = copy.deepcopy(state.get("submission"))
    task.page = _checkpoint_entity(state.get("page"))
    task.form = _checkpoint_entity(state.get("form"))
    task.project = _checkpoint_entity(state.get("project"))
    task.model = _checkpoint_entity(state.get("model"))
    task.assigned_to = _checkpoint_entity(state.get("assigned_to"))
    task.assigned_by = _checkpoint_entity(state.get("assigned_by"))
    task.completed_by = _checkpoint_entity(state.get("completed_by"))
    task.linked_pages = _checkpoint_entities(state.get("linked_pages"))
    task.files = _checkpoint_entities(state.get("files"))
    task.db["history"] = bool(state.get("history", False))

    restored_relations = [
        getattr(task, name, None)
        for name in (
            "page",
            "form",
            "project",
            "model",
            "assigned_to",
            "assigned_by",
            "completed_by",
        )
    ]
    restored_relations.extend(task.linked_pages or [])
    restored_relations.extend(task.files or [])
    relations = _unique_entities([*current_relations, *restored_relations])
    if relations:
        task.add_mutation_intents(
            *(
                MutationIntent.touch(
                    relation,
                    reason="report-task-restored-relation",
                )
                for relation in relations
            )
        )
    Entities.save(*_unique_entities([task, *relations]))
    if histories:
        Entities.delete(*histories)
    return {
        "entity": _entity_result(task),
        "note": "Restored the task state from before the report action.",
    }
