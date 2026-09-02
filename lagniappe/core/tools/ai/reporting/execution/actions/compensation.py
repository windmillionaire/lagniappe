"""Compensation adapters for deterministic report actions."""

from lagniappe.core.definitions import Action, MutationIntent
from lagniappe.core.entities import Entities

from .common import _require_allowed, _unique_entities
from .references import (
    _add_file_to_endpoint,
    _load_result_entity,
    _remove_file_from_endpoint,
)
from .results import _entity_result
from .completed_tasks import _undo_reused_completed_task


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason undo dispatch is exercised through public undo tests
def _undo_result_action(action, report, user):
    from .registry import REPORT_ACTION_ADAPTERS

    return REPORT_ACTION_ADAPTERS[action["type"]].compensate(action, report, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason create-action compensation is exercised through public undo tests
def _compensate_created(action, report, user):
    if action.get("created") is False:
        return {"note": "Reused existing entity; nothing deleted."}
    return _undo_created_result_entity(action, report, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason task compensation is exercised through completed-task undo tests
def _compensate_created_task(action, report, user):
    if action.get("created") is False and (action.get("before") or {}).get(
        "existing_task"
    ):
        return _undo_reused_completed_task(action, user)
    return _compensate_created(action, report, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason adapter binding is exercised through public undo dispatch
def _without_report(handler):
    return lambda action, _report, user: handler(action, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason manual actions are represented explicitly in public undo results
def _manual_compensation(_action, _report, _user):
    return {"note": "Manual cleanup suggestion; nothing was executed."}


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason no-op actions are represented explicitly in public undo results
def _noop_compensation(_action, _report, _user):
    return {"note": "No created entities or links to undo."}


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_adds_form_to_existing_page_with_undo
# @matrix ai-report : page-form undo
def _undo_add_form_to_page_action(action, user):
    previous = action.get("previous") or {}
    if previous.get("had_form"):
        return {"note": "Page already had this form; nothing changed."}

    page = _load_result_entity(action.get("entity"))
    if page is None:
        return {"note": "Page already missing."}
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this page's form.",
    )

    previous_details = previous.get("form")
    previous_form = _load_result_entity(previous_details)
    if previous_details and previous_form is None:
        return {"note": "Previous page form is no longer available."}

    current_owners = list(page.page_list_owners)
    page.form = previous_form
    if previous_form is not None:
        for category in page.page_list_owners:
            if isinstance(category, Entities.CATEGORY):
                category.properties.forms.add(previous_form)
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([page, previous_form, *current_owners]))
    return {
        "entity": _entity_result(page),
        "target": _entity_result(previous_form) if previous_form else None,
        "note": "Restored previous page form.",
    }


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_entities.py::test_run_report_adds_page_category_without_changing_primary_with_undo
# @matrix ai-report : add-category undo
def _undo_add_category_action(action, user):
    previous = action.get("previous") or {}
    if previous.get("had_category"):
        return {"note": "Category was already present; nothing removed."}

    page = _load_result_entity(action.get("entity"))
    category = _load_result_entity(action.get("target"))
    if page is None or category is None:
        return {"note": "Page or category already missing."}
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to remove this category from the page.",
    )
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to undo this category add.",
    )

    current_owners = list(page.page_list_owners)
    category_key = getattr(category, "key", None)
    page.categories = [
        existing
        for existing in page.categories or []
        if getattr(existing, "key", None) != category_key
    ]
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([page, category, *current_owners]))
    return {
        "entity": _entity_result(page),
        "target": _entity_result(category),
        "note": "Removed added page category.",
    }


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_moves_file_and_records_manual_page_cleanup_with_undo
# @matrix ai-report : move-file moves undo
def _undo_move_action(action, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Moved entity already missing."}
    if action.get("type") == "move_file":
        return _undo_file_move(action, entity, user)
    _require_allowed(
        entity.allowed(Action.EDIT, user=user),
        "You do not have permission to undo this move.",
    )

    if action.get("type") == "move_page":
        return _undo_page_move(action, entity, user)
    return _undo_task_move(action, entity, user)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_renames_entity_without_submission_and_undoes
# @matrix ai-report : rename undo
def _undo_rename_entity(action, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Renamed entity is missing."}
    _require_allowed(
        entity.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this entity name.",
    )
    previous_name = (action.get("before") or {}).get("name")
    entity.name = previous_name
    Entities.save(entity)
    return {
        "entity": _entity_result(entity),
        "note": "Restored previous entity name.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/compensation.py::_undo_move_action
# @reason page move restoration is covered through public undo tests
def _undo_page_move(action, page, user):
    previous = action.get("previous") or {}
    previous_model = _load_result_entity(previous.get("model"))
    previous_categories = [
        category
        for category in (
            _load_result_entity(category)
            for category in previous.get("categories") or []
        )
        if category is not None
    ]
    if previous_model is not None:
        _require_allowed(
            previous_model.allowed(Action.EDIT, user=user),
            "You do not have permission to move this page back.",
        )

    current_owners = list(page.page_list_owners)
    page.model = previous_model
    page.categories = previous_categories
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(
        *_unique_entities([page, previous_model, *previous_categories, *current_owners])
    )
    return {
        "entity": _entity_result(page),
        "target": _entity_result(previous_model) if previous_model else None,
        "note": "Restored previous page category.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/compensation.py::_undo_move_action
# @reason task move restoration is covered through public undo tests
def _undo_task_move(action, task, user):
    previous = action.get("previous") or {}
    previous_page = _load_result_entity(previous.get("page"))
    if previous_page is None:
        return {"entity": _entity_result(task), "note": "Previous page is missing."}
    _require_allowed(
        previous_page.allowed(Action.EDIT, user=user),
        "You do not have permission to move this task back.",
    )

    current_owners = list(task.task_list_owners)
    task.page = previous_page
    task.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-task-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([task, previous_page, *current_owners]))
    return {
        "entity": _entity_result(task),
        "target": _entity_result(previous_page),
        "note": "Restored previous task page.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/compensation.py::_undo_move_action
# @reason file move restoration is covered through public undo tests
def _undo_file_move(action, file, user):
    previous = action.get("previous") or {}
    source = _load_result_entity(previous.get("source"))
    target = _load_result_entity(previous.get("target"))
    if source is None:
        return {"entity": _entity_result(file), "note": "Previous source is missing."}
    if target is None:
        return {"entity": _entity_result(file), "note": "Previous target is missing."}
    _require_allowed(
        source.allowed(Action.EDIT, user=user),
        "You do not have permission to move this file back.",
    )
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to unlink this file from its target.",
    )

    _remove_file_from_endpoint(file, target)
    _add_file_to_endpoint(file, source)
    Entities.save(*_unique_entities([file, source, target]))
    return {
        "entity": _entity_result(file),
        "target": _entity_result(source),
        "note": "Restored previous file attachment.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason created-entity deletion is exercised through public undo tests
def _undo_created_result_entity(action, report, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Entity already missing."}
    _require_allowed(
        entity.allowed(Action.DELETE, user=user)
        or entity.allowed(Action.EDIT, user=user),
        "You do not have permission to delete this report-created entity.",
    )
    touched = _detach_report_files_before_delete(entity, action, report)
    if touched:
        Entities.save(*touched)
    deleted = _entity_result(entity)
    Entities.delete(entity)
    return {"entity": deleted, "note": "Deleted report-created entity."}


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason attachment unlinking is exercised through public undo tests
def _undo_attachment_action(action, user):
    file = _load_result_entity(action.get("entity"))
    target = _load_result_entity(action.get("target"))
    if file is None or target is None:
        return {"note": "Attachment target already missing."}
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to unlink this attachment.",
    )
    if (action.get("before") or {}).get("linked"):
        return {
            "entity": _entity_result(file),
            "target": _entity_result(target),
            "note": "Attachment already existed; nothing removed.",
        }
    if action.get("type") == "attach_file_to_page":
        changed = _remove_file_page_reference(file, target)
    else:
        changed = _remove_task_file_reference(target, file)
    if changed:
        Entities.save(file, target)
    return {
        "entity": _entity_result(file),
        "target": _entity_result(target),
        "note": (
            "Removed report-created file link." if changed else "Link already gone."
        ),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason file summary restoration is owned by public report compensation
def _undo_summarize_file(action, user):
    file = _load_result_entity(action.get("entity"))
    if file is None:
        return {"note": "Summarized file is missing."}
    _require_allowed(
        file.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this file summary.",
    )
    before = action.get("before") or {}
    previous = before.get("summarize") or {}
    file.summary = before.get("summary")
    summarize = file.properties.summarize
    for name in (
        "enabled",
        "search",
        "status",
        "error",
        "complete",
        "retrieval_terms",
    ):
        setattr(summarize, name, previous.get(name))
    Entities.save(file)
    return {
        "entity": _entity_result(file),
        "note": "Restored previous file summary state.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason report file preservation is exercised through public undo tests
def _detach_report_files_before_delete(entity, action, report):
    touched = []
    if isinstance(entity, Entities.PAGE):
        for file in report.input_files:
            if _remove_file_page_reference(file, entity):
                touched.append(file)
    elif isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
        files = _action_attachment_entities(action)
        if not files:
            files = list(getattr(entity, "files", []) or [])
        for file in files:
            if _remove_task_file_reference(entity, file):
                touched.append(file)
            if isinstance(entity, Entities.TASK_HISTORY):
                task = getattr(entity, "task", None)
                if task and _remove_history_task_file_reference(task, file, entity):
                    touched.append(file)
        if touched:
            touched.append(entity)
    return touched


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason attachment loading is exercised through public undo tests
def _action_attachment_entities(action):
    entities = []
    for attachment in action.get("attachments") or []:
        entity = _load_result_entity(attachment.get("entity"))
        if entity is not None:
            entities.append(entity)
    return entities


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason relationship cleanup is exercised through public undo tests
def _remove_file_page_reference(file, page):
    before = list(file.db.get("pages") or [])
    after = [key for key in before if key != page.key]
    changed = before != after
    if after:
        file.db["pages"] = after
    else:
        file.db.pop("pages", None)
    return changed


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason relationship cleanup is exercised through public undo tests
def _remove_task_file_reference(task, file, *, remove_task_attachment=True):
    task_before = list(task.db.get("files") or [])
    task_after = [key for key in task_before if key != file.key]
    file_before = list(file.db.get("tasks") or [])
    file_after = [key for key in file_before if key != task.key]
    changed = file_before != file_after
    if remove_task_attachment:
        changed = changed or task_before != task_after
        if task_after:
            task.db["files"] = task_after
        else:
            task.db.pop("files", None)
    if file_after:
        file.db["tasks"] = file_after
    else:
        file.db.pop("tasks", None)
    return changed


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason history parent reverse-link cleanup is exercised through public undo tests
def _remove_history_task_file_reference(task, file, history):
    if file.key in list(task.db.get("files") or []):
        return False

    for linked in getattr(file, "tasks", []) or []:
        if getattr(linked, "key", None) == getattr(history, "key", None):
            continue
        if getattr(linked, "entity_kind", None) != "task_history":
            continue
        if getattr(getattr(linked, "task", None), "key", None) == task.key:
            return False

    return _remove_task_file_reference(task, file, remove_task_attachment=False)
