"""Function declaration and handler for loading pages/tasks that use a form."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from ..references import hash_reference


DEFAULT_LIMIT = 25
MAX_LIMIT = 100
ALLOWED_KINDS = ("page", "task")
TASK_STATUS_ALIASES = {
    "all": None,
    "any": None,
    "completed": True,
    "complete": True,
    "done": True,
    "incomplete": False,
    "open": False,
    "active": False,
    "pending": False,
}


GET_FORM_INSTANCES = types.FunctionDeclaration(
    name="get_form_instances",
    description=(
        "Load pages and/or tasks that use a specific form. Returns exact page/task "
        "hash tokens, edit permissions, task completion state, URLs, and compact "
        "current submission data keyed by schema field id. Use this before "
        "proposing reviewed batch submission updates for a form."
    ),
    parameters={
        "type": "object",
        "properties": {
            "form_id": {
                "type": "string",
                "description": "The form hash token from prompt context or tool results.",
            },
            "kinds": {
                "type": "array",
                "items": {"type": "string", "enum": list(ALLOWED_KINDS)},
                "description": "Optional instance kinds to return: page, task, or both.",
            },
            "task_status": {
                "type": "string",
                "enum": sorted(TASK_STATUS_ALIASES),
                "description": (
                    "Optional task completion filter. Use completed for completed "
                    "tasks, incomplete/open for active tasks, or all for both."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Maximum result count. Defaults to {DEFAULT_LIMIT}; capped at "
                    f"{MAX_LIMIT}."
                ),
            },
        },
        "required": ["form_id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_form_instances_filters_permissions_status_and_truncates
# @matrix ai form-schema : form-instances permissions status submission truncation
def execute_get_form_instances(args, user):
    """Return viewable page/task instances attached to a form."""
    form_id = args.get("form_id")
    if not form_id:
        return {"error": "form_id is required"}

    form = Entities.fetch_one(form_id, request=Fetch.direct())
    if not form or not isinstance(form, Entities.FORM):
        return {"error": "Form not found"}
    if (
        not form.allowed(Action.VIEW, user=user)
        or getattr(form, "reserved", False)
    ):
        return {"error": "Access denied"}

    kinds, invalid_kinds = _instance_kinds(args.get("kinds"))
    if invalid_kinds:
        return {
            "error": "Unknown instance kind filter.",
            "invalid_kinds": invalid_kinds,
            "allowed_kinds": list(ALLOWED_KINDS),
        }

    task_completed, invalid_status = _task_status(args.get("task_status"))
    if invalid_status:
        return {
            "error": "Unknown task_status filter.",
            "invalid_task_status": invalid_status,
            "allowed_task_status": sorted(TASK_STATUS_ALIASES),
        }

    limit = _limit(args.get("limit"))
    instances = [
        entity
        for entity in Entities.fetch(
            *database_get.form_instance_users(form.key),
            request=Fetch.direct(),
        )
        if _include_instance(entity, user, kinds, task_completed)
    ]
    instances.sort(key=lambda entity: (entity.kind, (entity.name or "").lower()))
    returned = instances[:limit]

    return {
        "form": _entity_result(form),
        "form_type": form.form_type,
        "field_count": len(form.schema or []),
        "instances": [_instance_result(entity, user) for entity in returned],
        "total": len(instances),
        "returned": len(returned),
        "truncated": len(instances) > len(returned),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_form_instances.py::execute_get_form_instances
# @reason argument normalization is covered through the public tool handler
def _instance_kinds(value):
    if value is None:
        return set(ALLOWED_KINDS), []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        value = [value]

    kinds = set()
    invalid = []
    for kind in value:
        if not isinstance(kind, str):
            invalid.append(str(kind))
            continue
        normalized = kind.strip().lower()
        if normalized in ALLOWED_KINDS:
            kinds.add(normalized)
        else:
            invalid.append(kind)
    return kinds or set(ALLOWED_KINDS), invalid


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_form_instances.py::execute_get_form_instances
# @reason argument normalization is covered through the public tool handler
def _task_status(value):
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, str(value)
    normalized = value.strip().lower()
    if normalized not in TASK_STATUS_ALIASES:
        return None, value
    return TASK_STATUS_ALIASES[normalized], None


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_form_instances.py::execute_get_form_instances
# @reason result limiting is covered through the public tool handler
def _limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_form_instances.py::execute_get_form_instances
# @reason permission and status filters are covered through the public tool handler
def _include_instance(entity, user, kinds, task_completed):
    if isinstance(entity, Entities.PAGE):
        return "page" in kinds and entity.allowed(Action.VIEW, user=user)
    if isinstance(entity, Entities.TASK):
        if "task" not in kinds or not entity.allowed(Action.VIEW, user=user):
            return False
        if task_completed is not None and bool(entity.completed) is not task_completed:
            return False
        return True
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_form_instances.py::execute_get_form_instances
# @reason result projection is covered through the public tool handler
def _entity_result(entity):
    return {
        "hash": hash_reference(entity),
        "kind": entity.kind,
        "name": entity.name,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_form_instances.py::execute_get_form_instances
# @reason result projection is covered through the public tool handler
def _instance_result(entity, user):
    result = {
        **_entity_result(entity),
        "url": entity.url,
        "can_edit": entity.allowed(Action.EDIT, user=user),
        "submission": entity.properties.submission.form_value,
    }
    if isinstance(entity, Entities.TASK):
        result["completed"] = bool(entity.completed)
        if entity.completed_on:
            result["completed_on"] = entity.completed_on.isoformat()
        if entity.page:
            result["page"] = _entity_result(entity.page)
    elif isinstance(entity, Entities.PAGE) and entity.model:
        result["category"] = _entity_result(entity.model)
    return result
