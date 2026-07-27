"""Function declaration and handler for loading a single form schema."""

from google.genai import types

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from ..debug import ai_debug
from ..references import hash_reference


GET_SCHEMA = types.FunctionDeclaration(
    name="get_schema",
    description=(
        "Load the form schema for one form-bearing entity. Accepts a form, "
        "page, task, or model task hash token and returns the attached form schema with "
        "exact field ids and value shapes. Use this after the compact workspace "
        "inventory or a search result identifies the likely structure."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The form, page, task, or model task hash token.",
            },
        },
        "required": ["id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_schema_returns_schema_for_form_bearing_entities
# @features ai form-schema
# @dimensions tool-context page task model-task form
def execute_get_schema(args, user):
    """Return the schema for a form, page, task, or model task."""
    identifier = args.get("id")
    ai_debug("tool.get_schema.request", identifier=identifier)
    if not identifier:
        ai_debug("tool.get_schema.result", error="id is required")
        return {"error": "id is required"}

    entity = Entities.fetch_one(identifier, request=Fetch.direct())
    if not entity:
        ai_debug("tool.get_schema.result", identifier=identifier, error="not found")
        return {"error": "Entity not found"}
    if not entity.allowed(Action.VIEW, user=user):
        ai_debug(
            "tool.get_schema.result",
            entity=_entity_result(entity),
            error="access denied",
        )
        return {"error": "Access denied"}

    form = _schema_form(entity)
    if not form:
        ai_debug(
            "tool.get_schema.result",
            entity=_entity_result(entity),
            form=None,
            field_count=0,
        )
        return {
            "entity": _entity_result(entity),
            "form": None,
            "schema": [],
            "field_count": 0,
        }
    if not form.allowed(Action.VIEW, user=user) or getattr(form, "reserved", False):
        ai_debug(
            "tool.get_schema.result",
            entity=_entity_result(entity),
            form=_entity_result(form),
            error="access denied",
        )
        return {"error": "Access denied"}

    schema = form.schema or []
    ai_debug(
        "tool.get_schema.result",
        entity=_entity_result(entity),
        form=_entity_result(form),
        form_type=form.form_type,
        field_count=len(schema),
        fields=_schema_debug_fields(schema),
    )
    return {
        "entity": _entity_result(entity),
        "form": _entity_result(form),
        "form_type": form.form_type,
        "schema": schema,
        "field_count": len(schema),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_schema.py::execute_get_schema
# @reason form source selection is asserted through the public schema tool
def _schema_form(entity):
    if isinstance(entity, Entities.FORM):
        return entity
    if isinstance(entity, Entities.PAGE):
        return _attached_form(entity)
    if isinstance(entity, Entities.MODEL_TASK):
        return _attached_form(entity)
    if isinstance(entity, Entities.TASK):
        return _attached_form(entity)
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_schema.py::execute_get_schema
# @reason stored form relation access is asserted through the public schema tool
def _attached_form(entity):
    form_property = getattr(getattr(entity, "properties", None), "form", None)
    if not form_property:
        return None
    if getattr(form_property, "is_set", False):
        form = form_property.value
        if form:
            return form

    form_key = getattr(form_property, "key", None)
    if not form_key:
        db = getattr(entity, "db", None)
        form_key = db.get("form") if isinstance(db, dict) else None
    if not form_key:
        return None

    loaded = Entities.fetch_one(form_key, request=Fetch.direct())
    if isinstance(loaded, Entities.FORM):
        exceptions.capture(
            "AI get_schema recovered an attached form from a stored relation key.",
            context={
                "ai_get_schema": {
                    "entity": _entity_result(entity),
                    "form": _entity_result(loaded),
                    "form_key": str(form_key),
                }
            },
            level="warning",
        )
        return loaded

    if loaded:
        loaded_context = _entity_result(loaded)
    else:
        loaded_context = None

    if loaded_context:
        message = "AI get_schema loaded a stored form key that was not a form."
    else:
        message = "AI get_schema found a stored form key but could not load the form."
    exceptions.capture(
        message,
        context={
            "ai_get_schema": {
                "entity": _entity_result(entity),
                "loaded": loaded_context,
                "form_key": str(form_key),
            }
        },
        level="warning",
    )
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_schema.py::execute_get_schema
# @reason entity projection is asserted through the public schema tool
def _entity_result(entity):
    return {
        "hash": hash_reference(entity),
        "kind": entity.kind,
        "name": entity.name,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_schema.py::execute_get_schema
# @reason debug-only compact schema logging is not behavior-bearing
def _schema_debug_fields(schema):
    fields = []
    for field in schema or []:
        if not isinstance(field, dict):
            continue
        fields.append(
            {
                "id": field.get("id"),
                "title": field.get("title") or field.get("label"),
                "type": field.get("type"),
                "input": field.get("input"),
            }
        )
    return fields
