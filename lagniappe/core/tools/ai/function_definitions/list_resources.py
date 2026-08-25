"""Function declaration and handler for listing workspace model resources."""

import json
from collections import defaultdict
from datetime import timedelta

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database
from lagniappe.core.tools.cache.core import cache as redis_cache
from lagniappe.core.tools.cache.keys import Keys
from ..references import hash_reference


RESOURCE_CACHE_TTL = int(timedelta(minutes=5).total_seconds())


LIST_WORKSPACE_RESOURCES = types.FunctionDeclaration(
    name="list_workspace_resources",
    description=(
        "List the existing workspace model resources in one compact inventory. "
        "Use this before narrower searches when you need to understand available "
        "categories, projects, model tasks, and reusable forms. Returns category "
        "names with attached form names, project names with model task/form names, "
        "and forms that are not attached to a category or model task. Model-task "
        "forms include a schema_ref handle for get_schema without inlining schemas."
    ),
    parameters={
        "type": "object",
        "properties": {},
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_list_workspace_resources_caches_inventory
# @matrix ai : redis-cache resource-inventory
def execute_list_workspace_resources(_args, user):
    """Return a cached, permission-filtered inventory of model resources."""
    cache_key = _resource_cache_key(user)
    cached = redis_cache.get(cache_key)
    if cached:
        return json.loads(cached)

    inventory = build_workspace_resource_inventory(user)
    redis_cache.redis.set(
        cache_key,
        json.dumps(inventory, default=str),
        ex=RESOURCE_CACHE_TTL,
    )
    return inventory


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_list_workspace_resources_caches_inventory
# @matrix ai : categories forms projects resource-inventory
def build_workspace_resource_inventory(user):
    """Build a compact inventory of viewable model resources for an AI prompt."""
    models = [
        entity
        for entity in Entities.fetch(*database.get.all_models(), request=Fetch.direct())
        if _can_list(entity, user)
    ]

    categories = [entity for entity in models if isinstance(entity, Entities.CATEGORY)]
    projects = [entity for entity in models if isinstance(entity, Entities.PROJECT)]
    model_tasks = [
        entity for entity in models if isinstance(entity, Entities.MODEL_TASK)
    ]
    forms = [entity for entity in models if isinstance(entity, Entities.FORM)]
    tasks_by_project = _model_tasks_by_project(model_tasks, user)

    attached_form_keys = set()
    category_items = [
        _format_category(category, user, attached_form_keys)
        for category in sorted(categories, key=_sort_name)
    ]
    project_items = [
        _format_project(project, user, attached_form_keys, tasks_by_project)
        for project in sorted(projects, key=_sort_name)
    ]
    standalone_forms = [
        _format_form(form)
        for form in sorted(forms, key=_sort_name)
        if form.key not in attached_form_keys
    ]

    return {
        "categories": category_items,
        "projects": project_items,
        "standalone_forms": standalone_forms,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::execute_list_workspace_resources
# @reason cache-key fallback behavior is covered through cached handler behavior
def _resource_cache_key(user):
    user_key = (
        getattr(user, "hash", None)
        or getattr(user, "urlsafe_key", None)
        or getattr(user, "email", None)
        or "anonymous"
    )
    return Keys.AI_RESOURCE_INVENTORY.value.format(user_key)


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason permission filtering is exercised through inventory shape tests
def _can_list(entity, user):
    return (
        entity
        and getattr(entity, "active", True)
        and not getattr(entity, "reserved", False)
        and entity.allowed(Action.VIEW, user=user)
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason deterministic ordering is observable in inventory tests
def _sort_name(entity):
    return (getattr(entity, "name", "") or "").lower()


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason model-task grouping is exercised through inventory shape tests
def _model_tasks_by_project(model_tasks, user):
    tasks_by_project = defaultdict(list)
    for model_task in model_tasks:
        if not _can_list(model_task, user) or not model_task.project:
            continue
        tasks_by_project[model_task.project.key].append(model_task)
    return tasks_by_project


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason category projection is exercised through inventory shape tests
def _format_category(category, user, attached_form_keys):
    forms = _category_forms(category, user)
    attached_form_keys.update(form.key for form in forms)
    return {
        "hash": hash_reference(category),
        "name": category.name,
        "can_edit": category.allowed(Action.EDIT, user=user),
        "forms": [_format_form(form) for form in forms],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason project projection is exercised through inventory shape tests
def _format_project(project, user, attached_form_keys, tasks_by_project):
    model_tasks = tasks_by_project.get(project.key, [])
    return {
        "hash": hash_reference(project),
        "name": project.name,
        "can_edit": project.allowed(Action.EDIT, user=user),
        "model_tasks": [
            _format_model_task(model_task, user, attached_form_keys)
            for model_task in sorted(model_tasks, key=lambda task: task.order or 0)
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason model task projection is exercised through inventory shape tests
def _format_model_task(model_task, user, attached_form_keys):
    form = _attached_form(model_task)
    form = form if form and _can_list(form, user) else None
    if form:
        attached_form_keys.add(form.key)
    return {
        "hash": hash_reference(model_task),
        "name": model_task.name,
        "can_edit": model_task.allowed(Action.EDIT, user=user),
        "form": _format_model_task_form(model_task, form) if form else None,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason category form selection is exercised through inventory shape tests
def _category_forms(category, user):
    forms = []
    seen = set()
    primary_form = _attached_form(category)
    related_forms = getattr(category, "forms", []) or []
    for form in [primary_form, *related_forms]:
        if not form or form.key in seen or not _can_list(form, user):
            continue
        seen.add(form.key)
        forms.append(form)
    return forms


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason stored form relation recovery is exercised through inventory shape tests
def _attached_form(entity):
    form_property = getattr(getattr(entity, "properties", None), "form", None)
    if form_property:
        if getattr(form_property, "is_set", False):
            form = form_property.value
            if form:
                return form

        form_key = getattr(form_property, "key", None)
    else:
        form = getattr(entity, "form", None)
        if form:
            return form
        form_key = None

    if not form_key:
        db = getattr(entity, "db", None)
        form_key = db.get("form") if isinstance(db, dict) else None
    if not form_key:
        return None

    loaded = Entities.fetch_one(form_key, request=Fetch.direct())
    return loaded if isinstance(loaded, Entities.FORM) else None


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason form projection is exercised through inventory shape tests
def _format_form(form):
    return {
        "hash": hash_reference(form),
        "name": form.name,
        "form_type": form.form_type,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/list_resources.py::build_workspace_resource_inventory
# @reason model-task form schema handles are asserted through inventory shape tests
def _format_model_task_form(model_task, form):
    formatted = _format_form(form)
    formatted["schema_ref"] = hash_reference(model_task)
    return formatted
