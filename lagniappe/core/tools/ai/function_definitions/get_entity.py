"""Function declaration and handler for loading entity details by ID."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities


GET_ENTITY = types.FunctionDeclaration(
    name="get_entity",
    description=(
        "Load the full details of a specific entity (page, task, category, "
        "project, etc.) by its hash token, as returned by "
        "search_entities. "
        "Returns all available fields including form data, dates, and "
        "relationships. For categories, the result includes the primary form "
        "and description — useful for understanding a category before "
        "drilling into its pages with get_category_pages. For forms and "
        "form-bearing pages, tasks, or model tasks, the result includes the "
        "schema needed to create valid submission objects."
    ),
    parameters={
        "type": "object",
        "properties": {
            "view": {"type": "string", "enum": ["default", "edit"]},
            "id": {
                "type": "string",
                "description": "The entity hash token from search results.",
            },
        },
        "required": ["id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_entity_returns_full_form_schema_for_ai_autofill
# @tests tests_unit/test_015_ai_tools.py::test_get_entity_returns_model_task_form_schema_for_ai_autofill
# @tests tests_unit/test_015_ai_tools.py::test_get_entity_loads_model_task_form_schema_from_stored_key
# @matrix ai : attached-form autofill model-task stored-key tool-context
# @matrix form-schema : attached-form autofill model-task schema stored-key
# @matrix ai : edit-view exact-answers shared-schema
# @matrix entity-patch : preservation validation preparation permissions
def execute_get_entity(args, user):
    identifier = args.get("id")
    if not identifier:
        return {"error": "id is required"}

    entity = _load_entity(identifier)
    if not entity:
        return {"error": "Entity not found"}

    if not entity.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    _ensure_attached_form(entity)
    if args.get("view") == "edit":
        return edit_entity(entity, user)
    entity_data = entity.to_ai(user)
    return entity_data


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_entity.py::execute_get_entity
# @reason entity lookup shape is exercised through the public get_entity tool
def _load_entity(identifier):
    entity = Entities.fetch_one(identifier, request=Fetch.root())
    if isinstance(entity, (Entities.TASK, Entities.FILE)):
        Entities.fetch_one(entity, request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
    elif isinstance(entity, Entities.TASK_HISTORY):
        Entities.fetch(
            entity, entity.properties.task.key, *entity.db.get("files", []),
            request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
        )
    elif entity is not None:
        Entities.fetch_one(entity, request=Fetch.direct())
    return entity


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_entity.py::execute_get_entity
# @reason stored-key form fallback is exercised through model-task schema tests
def _ensure_attached_form(entity):
    form_property = getattr(getattr(entity, "properties", None), "form", None)
    if not form_property:
        return
    if getattr(form_property, "is_set", False) and form_property.value:
        return

    form_key = getattr(form_property, "key", None)
    if not form_key:
        return

    form = Entities.fetch_one(form_key, request=Fetch.direct())
    if isinstance(form, Entities.FORM):
        entity.form = form


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_entity.py::execute_get_entity
# @reason edit projection shares authorization with the public entity and task readers
def edit_entity(entity, user, schemas=None):
    from copy import deepcopy
    from ..references import hash_reference
    from lagniappe.core.tools.entity_patches import PATCH_FIELDS
    result = entity.to_ai(user)
    if entity.entity_kind == "file":
        result["description"] = entity.summary
    elif "description" in entity.properties:
        result["description"] = entity.description
    result["revision"] = str(entity.modified)
    result["editable_fields"] = sorted(PATCH_FIELDS.get(entity.entity_kind, ())) if entity.allowed(Action.EDIT, user=user) and not (entity.entity_kind == "task" and entity.completed) else []
    if entity.entity_kind in {"page", "task"}:
        result["answers"] = deepcopy(entity.submission or {})
        result["generation"] = entity.generation
    if entity.entity_kind in {"task", "page", "model"} and entity.form and entity.form.allowed(Action.VIEW, user=user):
        form = entity.form
        result.pop(entity.properties.form.ai_key, None)
        reference = hash_reference(form)
        result["form"] = {"hash": reference, "name": form.name, "generation": form.generation, "revision": form.version}
        schema = deepcopy(form.schema)
        if schemas is None:
            result["form"]["schema"] = schema
        else:
            result.pop("schema", None)
            schemas[reference] = schema
    if entity.entity_kind == "project":
        result["model_tasks"] = [{"hash": hash_reference(model), "name": model.name, "order": model.order, "form": hash_reference(model.form) if model.form and model.form.allowed(Action.VIEW, user=user) else None} for model in entity.model_tasks if model.allowed(Action.VIEW, user=user)]
    return result
