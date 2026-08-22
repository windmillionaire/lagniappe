"""Entity creation, relationship, rename, and manual report actions."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, MutationIntent, Resource
from lagniappe.core.entities import Entities

from .common import (
    PAGE_FORM_TYPE_ERROR,
    _category_form,
    _data,
    _first_data_reference,
    _require_allowed,
    _require_form_type,
    _unique_entities,
)
from .results import (
    _entity_result,
    _submission_result,
)
from .references import (
    _resolve_entity,
)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @pair ai-report:create-order
def _create_form(action, _report, user, _created):
    _require_allowed(
        Resource.FORMS.allowed(Action.CREATE, user),
        "You do not have permission to create forms.",
    )
    data = _data(action)
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise exceptions.ValidationError("Create form actions require data.name.")
    form_type = data.get("form_type") or data.get("form-type")
    if form_type not in {"page", "task"}:
        raise exceptions.ValidationError("Create form actions require data.form_type.")
    schema = data.get("schema")
    if not isinstance(schema, list) or not schema:
        raise exceptions.ValidationError(
            "Create form actions require at least one schema field."
        )
    form = Entities.FORM.create(
        {
            "name": name,
            "form-type": form_type,
            "schema": schema,
        }
    )
    form.ai_generated = True
    return form, [form]


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @pair ai-report:create-order
def _create_category(action, _report, user, created):
    _require_allowed(
        Resource.CATEGORY.allowed(Action.CREATE, user),
        "You do not have permission to create categories.",
    )
    data = _data(action)
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
        optional=True,
    )
    category = Entities.CATEGORY.create(
        {
            "name": data.get("name") or "Generated category",
            "description": data.get("description"),
            "form": form,
            "attributes": data.get("attributes"),
        }
    )
    category.ai_generated = True
    return category, [category]


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @pair ai-report:create-order
def _create_project(action, _report, user, _created):
    _require_allowed(
        Resource.PROJECT.allowed(Action.CREATE, user),
        "You do not have permission to create projects.",
    )
    data = _data(action)
    project = Entities.PROJECT.create(
        {
            "name": data.get("name") or "Generated project",
            "description": data.get("description"),
            "attributes": data.get("attributes"),
        }
    )
    project.ai_generated = True
    return project, [project]


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @pair ai-report:create-order
def _create_model_task(action, _report, user, created):
    data = _data(action)
    project = _resolve_entity(
        data.get("project")
        or data.get("project_id")
        or data.get("project_ref")
        or data.get("project_action"),
        created,
        expected=Entities.PROJECT,
    )
    _require_allowed(
        project.allowed(Action.EDIT, user=user),
        "You do not have permission to edit this project.",
    )
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
        optional=True,
    )
    model_task = Entities.MODEL_TASK.create(
        project,
        {
            "name": data.get("name") or "Generated model task",
            "form": form,
        },
    )
    return model_task, [model_task, project]


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_uses_category_form_from_stored_key_for_page_submission
# @pair ai-report:create-order
# @pair ai-report:default-category
# @pair ai-report:submission-completion
# @pair ai-report:persistence
def _create_page(action, _report, user, created):
    data = _data(action)
    category = _resolve_entity(
        data.get("category")
        or data.get("category_id")
        or data.get("category_ref")
        or data.get("category_action")
        or data.get("model")
        or data.get("model_id")
        or data.get("model_action"),
        created,
        expected=Entities.CATEGORY,
        optional=True,
    )
    if category is None:
        category = Entities.CATEGORY.get_uncategorized_pages()
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to create pages in this category.",
    )
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
        optional=True,
    )
    page_form = form or _category_form(category)
    page = Entities.PAGE.create(
        {
            "name": data.get("name") or "Generated page",
            "description": data.get("description"),
            "model": category,
            "categories": data.get("categories") or [],
            "form": page_form,
            "attributes": data.get("attributes"),
        }
    )
    if page_form is not None and "submission" in data:
        page.ai_submission(data.get("submission") or {})
    if data.get("document"):
        page.properties.document.html = data["document"]
    metadata = {}
    if page_form is not None:
        metadata["form"] = _entity_result(page_form)
    if "submission" in data:
        metadata["submission"] = _submission_result(
            page,
            data.get("submission_empty_reason"),
        )
    return page, [page, category], metadata


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_adds_form_to_existing_page_with_undo
# @pair ai-report:page-form
# @pair ai-report:idempotent
def _add_form_to_page(action, _report, user, created):
    data = _data(action)
    page = _resolve_entity(
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action"),
        created,
        expected=Entities.PAGE,
    )
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
    )
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to add a form to this page.",
    )
    _require_form_type(form, "page", PAGE_FORM_TYPE_ERROR)

    previous_form = page.form
    previous_owners = list(page.page_list_owners)
    had_form = previous_form is not None and getattr(
        previous_form, "key", None
    ) == getattr(form, "key", None)
    if not had_form:
        page.form = form
        for category in page.page_list_owners:
            if isinstance(category, Entities.CATEGORY):
                category.properties.forms.add(form)
        page.add_mutation_intents(
            *(
                MutationIntent.touch(
                    owner,
                    reason="report-page-previous-owner",
                )
                for owner in previous_owners
            )
        )

    metadata = {
        "target": _entity_result(form),
        "form": _entity_result(form),
        "previous": {
            "form": _entity_result(previous_form) if previous_form else None,
            "had_form": had_form,
        },
    }
    if had_form:
        metadata["note"] = "Page already had this form."
    return page, _unique_entities([page, form, *previous_owners]), metadata


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_entities.py::test_run_report_adds_page_category_without_changing_primary_with_undo
# @pair ai-report:add-category
# @pair ai-report:deterministic-run
# @pair ai-report:idempotent
# @pair categories:add-category
# @pair categories:deterministic-run
# @pair categories:idempotent
# @pair categories:undo
def _add_category(action, _report, user, created):
    data = _data(action)
    page = _resolve_entity(
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action"),
        created,
        expected=Entities.PAGE,
    )
    category = _resolve_entity(
        data.get("category")
        or data.get("category_id")
        or data.get("category_ref")
        or data.get("category_action")
        or data.get("model")
        or data.get("model_id")
        or data.get("model_ref")
        or data.get("model_action"),
        created,
        expected=Entities.CATEGORY,
    )
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to add categories to this page.",
    )
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to add this category to pages.",
    )

    previous_categories = list(page.categories or [])
    previous_owners = list(page.page_list_owners)
    had_category = any(
        getattr(existing, "key", None) == getattr(category, "key", None)
        for existing in previous_categories
    )
    if not had_category:
        page.categories = [*previous_categories, category]
        if page.form:
            category.properties.forms.add(page.form)
        page.add_mutation_intents(
            *(
                MutationIntent.touch(
                    owner,
                    reason="report-page-previous-owner",
                )
                for owner in previous_owners
            )
        )

    metadata = {
        "target": _entity_result(category),
        "previous": {
            "had_category": had_category,
        },
    }
    if had_category:
        metadata["note"] = "Page already had this category."
    return page, _unique_entities([page, category, *previous_owners]), metadata


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @pair ai-report:moves
def _move_page(action, _report, user, created):
    data = _data(action)
    page = _resolve_entity(
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action"),
        created,
        expected=Entities.PAGE,
    )
    category = _resolve_entity(
        data.get("category")
        or data.get("category_id")
        or data.get("category_ref")
        or data.get("category_action")
        or data.get("model")
        or data.get("model_id")
        or data.get("model_ref")
        or data.get("model_action"),
        created,
        expected=Entities.CATEGORY,
    )
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to move this page.",
    )
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to move pages to this category.",
    )

    previous_model = page.model
    previous_categories = list(page.categories or [])
    previous_owners = list(page.page_list_owners)

    previous_model_key = getattr(previous_model, "key", None)
    category_key = getattr(category, "key", None)
    page.categories = [
        category,
        *[
            existing
            for existing in previous_categories
            if getattr(existing, "key", None) not in {previous_model_key, category_key}
        ],
    ]
    if page.form:
        category.properties.forms.add(page.form)
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-previous-owner",
            )
            for owner in previous_owners
        )
    )

    metadata = {
        "target": _entity_result(category),
        "moved": {
            "from": _entity_result(previous_model) if previous_model else None,
            "to": _entity_result(category),
        },
        "previous": {
            "model": _entity_result(previous_model) if previous_model else None,
            "categories": [
                _entity_result(category) for category in previous_categories
            ],
        },
    }
    return page, _unique_entities([page, category, *previous_owners]), metadata


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @pair ai-report:moves
def _move_task(action, _report, user, created):
    data = _data(action)
    task = _resolve_entity(
        data.get("task")
        or data.get("task_id")
        or data.get("task_ref")
        or data.get("task_action"),
        created,
        expected=Entities.TASK,
    )
    page = _resolve_entity(
        _first_data_reference(data, "to_page", "page"),
        created,
        expected=Entities.PAGE,
    )
    _require_allowed(
        task.allowed(Action.EDIT, user=user),
        "You do not have permission to move this task.",
    )
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to move tasks to this page.",
    )

    previous_page = task.page
    previous_owners = list(task.task_list_owners)
    task.page = page
    task.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-task-previous-owner",
            )
            for owner in previous_owners
        )
    )

    metadata = {
        "target": _entity_result(page),
        "page": _entity_result(page),
        "moved": {
            "from": _entity_result(previous_page) if previous_page else None,
            "to": _entity_result(page),
        },
        "previous": {
            "page": _entity_result(previous_page) if previous_page else None,
        },
    }
    return task, _unique_entities([task, page, *previous_owners]), metadata


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_renames_entity_without_submission_and_undoes
# @pair ai-report:rename
def _rename_entity(action, _report, user, created):
    data = _data(action)
    entity = _resolve_entity(_first_data_reference(data, "entity"), created)
    _require_allowed(
        entity.allowed(Action.EDIT, user=user),
        "You do not have permission to rename this entity.",
    )
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise exceptions.ValidationError("Rename entity actions require data.name.")

    previous_name = entity.name
    entity.name = name.strip()
    return (
        entity,
        [entity],
        {
            "previous": {"name": previous_name},
            "note": f"Renamed {previous_name} to {entity.name}.",
        },
    )


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_moves_file_and_records_manual_page_cleanup_with_undo
# @pair ai-report:manual-cleanup
def _manual_delete_page_action(action, _report, user, created):
    data = _data(action)
    page = _resolve_entity(
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action"),
        created,
        expected=Entities.PAGE,
    )
    _require_allowed(
        page.allowed(Action.VIEW, user=user),
        "You do not have permission to view this page.",
    )
    return (
        page,
        [],
        {
            "manual": {
                "type": "delete_page",
                "action": "delete",
                "reason": (
                    "Use the page delete button to confirm cleanup after "
                    "reviewing the completed report actions."
                ),
            },
            "note": "Manual cleanup suggested.",
        },
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason skip actions are covered through deterministic report action dispatch
def _skip_action(_action, _report, _user, _created):
    return None, []


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason review actions are covered through deterministic report action dispatch
def _needs_review_action(_action, _report, _user, _created):
    return None, []
