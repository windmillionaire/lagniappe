"""Entity creation, relationship, rename, and manual report actions."""

from config.form_schema import normalize_form_schema
from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, MutationIntent, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.entities.category import UNCATEGORIZED_PAGES_NAME
from ...contracts.actions import DELETE_TARGETS

from .common import _category_form, _data, _first_data_reference, _require_allowed
from .results import (
    _entity_result,
    _submission_result,
)
from .references import (
    _resolve_entity,
)
from .checkpoints import _prepared_output_key
from datetime import UTC


def _create_form(action, _report, user, _created, context=None):
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
    form = Entities.FORM.create({"name": name, "form-type": form_type}, key=_prepared_output_key(context))
    # Feed the reviewed column defaults and field aliases to the AI content writer.
    form.properties.schema.validate_ai(normalize_form_schema(schema, form_type=form_type))
    form.ai_generated = True
    return form, [form]


def _create_category(action, _report, user, created, context=None):
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
        }, key=_prepared_output_key(context),
    )
    category.ai_generated = True
    return category, [category]


def _create_project(action, _report, user, _created, context=None):
    _require_allowed(
        Resource.PROJECT.allowed(Action.CREATE, user),
        "You do not have permission to create projects.",
    )
    data = _data(action)
    project = Entities.PROJECT.create(
        {
            "name": data.get("name") or "Generated project",
            "description": data.get("description"),
        }, key=_prepared_output_key(context),
    )
    project.ai_generated = True
    return project, [project]


def _create_model_task(action, _report, user, created, context=None):
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
        key=_prepared_output_key(context),
    )
    return model_task, [model_task]


def _create_page(action, _report, user, created, context=None):
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
        }, key=_prepared_output_key(context),
    )
    if page_form is not None and "submission" in data:
        page.ai_submission(data.get("submission") or {})
    if data.get("document"):
        from datetime import datetime
        from lagniappe.core.tools.document_crdt import append_fragment
        from .documents import document_source_quote

        record = (context or {}).get("action_record") or {}
        from .checkpoints import _assign_preallocated_key
        _assign_preallocated_key(page, record, context or {})
        if context and context.get("batch"):
            context["batch"].add_document(page)
        timestamp = record.get("document_at") or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        html = document_source_quote(_report, timestamp) + data["document"]
        snapshot, _receipt = append_fragment(None, html, record.get("idempotency_key") or "creation")
        page.properties.document.save(html=html, ydoc=snapshot)
    metadata = {}
    if page_form is not None:
        metadata["form"] = _entity_result(page_form)
    if "submission" in data:
        metadata["submission"] = _submission_result(
            page,
            data.get("submission_empty_reason"),
        )
    return page, [page], metadata


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
    return task, [task], metadata


def _suggest_page_deletion(action, _report, user, created):
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
                "type": "suggest_page_deletion",
                "action": "delete",
                "reason": (
                    "Use the page delete button to confirm cleanup after "
                    "reviewing the completed report actions."
                ),
            },
            "note": "Manual cleanup suggested.",
        },
    )


def _delete_entity(action, _report, user, created, context=None):
    action_type = action.get("type")
    kind = DELETE_TARGETS.get(action_type)
    if not kind:
        raise exceptions.ValidationError("Unsupported delete action.")
    expected_cls = {
        "page": Entities.PAGE,
        "task": Entities.TASK,
        "category": Entities.CATEGORY,
        "project": Entities.PROJECT,
        "model": Entities.MODEL_TASK,
        "file": Entities.FILE,
    }[kind]
    data = _data(action)
    entity = _resolve_entity(data.get("entity"), created, expected=expected_cls)
    _require_allowed(
        entity.allowed(Action.DELETE, user=user),
        f"You do not have permission to delete this {kind}.",
    )
    if kind == "category" and entity.name == UNCATEGORIZED_PAGES_NAME:
        raise exceptions.ValidationError("Uncategorized Pages cannot be deleted.")
    if kind == "page" and getattr(entity, "user", None):
        raise exceptions.ValidationError(
            "User personal pages cannot be deleted by a plan."
        )

    batch = context.get("batch") if isinstance(context, dict) else None
    if batch is not None and batch.indices:
        batch.commit()

    if kind == "page":
        categories = list(entity.categories)
        editable_categories = [
            category for category in categories if category.allowed(Action.EDIT, user=user)
        ]
        retained_categories = [
            category for category in categories if category not in editable_categories
        ]
        for category in editable_categories:
            entity.properties.categories.remove(category)
        if retained_categories:
            entity.save()
            if editable_categories:
                Entities.save(*editable_categories)
            return (
                entity,
                [],
                {
                    "deleted": False,
                    "note": "Removed page from editable categories; retained in other categories.",
                },
            )
        Entities.delete(entity)
        if categories:
            Entities.save(*categories)
    else:
        Entities.delete(entity)

    return (
        entity,
        [],
        {
            "deleted": True,
            "note": f"Deleted {kind}.",
        },
    )


def _skip_action(_action, _report, _user, _created):
    return None, []


def _needs_review_action(_action, _report, _user, _created):
    return None, []
