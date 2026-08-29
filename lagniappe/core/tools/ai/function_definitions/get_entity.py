"""Function declaration and handler for loading entity details by ID."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
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
    entity_data = entity.to_ai(user)
    return entity_data


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_entity.py::execute_get_entity
# @reason entity lookup shape is exercised through the public get_entity tool
def _load_entity(identifier):
    entity = Entities.fetch_one(identifier, request=Fetch.direct())
    if isinstance(entity, Entities.TASK) and entity.page:
        # Task AI output includes categories derived from its parent Page. Make
        # that Page an explicit direct root without widening every entity kind.
        Entities.fetch(entity, entity.page, request=Fetch.direct())
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
