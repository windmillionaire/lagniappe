"""Function declaration and handler for loading entity details by ID."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from lagniappe.core.entities import Identifier
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.page import Page
    from lagniappe.core.entities.task import Task
    from lagniappe.core.entities.model_task import ModelTask
    from lagniappe.core.entities.project import Project
    from lagniappe.core.entities.user import User

from google.genai import types

from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from ..page_document import document_edit_projection
from ..references import normalize_hash_references, stored_file_identifiers


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
        "schema needed to create valid submission objects. An editable Page in edit view "
        "includes page_document_markdown and a flag indicating whether it can be round-tripped."
    ),
    parameters=types.Schema.model_validate({
        "type": "object",
        "properties": {
            "view": {"type": "string", "enum": ["default", "edit"]},
            "id": {
                "type": "string",
                "description": "The entity hash token from search results.",
            },
        },
        "required": ["id"],
    }),
)


MAX_ENTITY_IDS = 20
GET_ENTITIES = types.FunctionDeclaration(
    name="get_entities",
    description=(
        "Load full details for one or more known entity hashes together, including "
        "descriptions, dates, relationships and attached form schemas. Pass a one-item "
        "array for one entity. Use view=edit for editable fields and Page document "
        "Markdown. Results follow input order, including repeats. Each position "
        "contains either an entity or an error. Reuse details already in search or page results."
    ),
    parameters=types.Schema.model_validate({
        "type": "object",
        "properties": {
            "ids": {
                "type": "array", "items": {"type": "string", "minLength": 1},
                "minItems": 1, "maxItems": MAX_ENTITY_IDS,
                "description": "Entity hash tokens from context, search or a previous tool result.",
            },
            "view": {"type": "string", "enum": ["default", "edit"]},
        },
        "required": ["ids"],
    }),
)


def execute_get_entities(args: Mapping[str, object], user: User) -> Mapping[str, object]:
    ids = args.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_ENTITY_IDS:
        return {"error": f"ids must contain between 1 and {MAX_ENTITY_IDS} entity IDs"}
    if not all(isinstance(identifier, str) and identifier.strip() for identifier in ids):
        return {"error": "Each entity ID must be a nonempty string"}
    view = args.get("view", "default")
    if view not in ("default", "edit"):
        return {"error": "view must be default or edit"}

    keys = [database_get.datastore_key(identifier) for identifier in normalize_hash_references(ids)]
    entities = Entities.fetch(*keys, request=Fetch.root())
    groups: dict[Fetch, list[Identifier]] = {}
    for entity in entities:
        request, roots = _relation_roots(entity)
        groups.setdefault(request, []).extend(roots)
    for request, roots in groups.items():
        Entities.fetch(*roots, request=request)

    rows = {}
    for entity in entities:
        if entity.allowed(Action.VIEW, user):
            try:
                rows[entity.key] = {"entity": _project_entity(entity, user, edit=view == "edit")}
            except Exception:
                # A damaged record should neither hide its neighbors nor expose stored data.
                rows[entity.key] = {"error": "Entity details could not be read"}
    # Position identifies unsuccessful inputs without exposing resolved storage keys
    # or distinguishing a missing entity from one the caller cannot view.
    return {"results": [rows.get(key, {"error": "Entity unavailable"}) for key in keys]}


def execute_get_entity(args: Mapping[str, object], user: User) -> Mapping[str, object]:
    identifier = args.get("id")
    if not isinstance(identifier, str) or not identifier:
        return {"error": "id is required"}

    entity = Entities.fetch_one(identifier, request=Fetch.root())
    if not entity:
        return {"error": "Entity not found"}
    request, roots = _relation_roots(entity)
    if len(roots) == 1:
        Entities.fetch_one(entity, request=request)
    else:
        Entities.fetch(*roots, request=request)
    if not entity.allowed(Action.VIEW, user):
        return {"error": "Access denied"}
    return _project_entity(entity, user, edit=args.get("view") == "edit")


def _project_entity(entity: Entity, user: User, *, edit: bool) -> dict[str, object]:
    _ensure_attached_form(entity)
    return edit_entity(entity, user) if edit else entity.to_ai(user)


def _relation_roots(entity: Entity) -> tuple[Fetch, list[Identifier]]:
    if isinstance(entity, (Entities.TASK, Entities.FILE, Entities.TASK_HISTORY)):
        roots: list[Identifier] = [entity]
        if isinstance(entity, Entities.TASK_HISTORY):
            roots.extend([entity.properties.task.key, *stored_file_identifiers(entity)])
        return Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION), roots
    return Fetch.direct(), [entity]


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


def edit_entity(entity: Entity, user: User, schemas: dict[str, list[dict[str, object]]] | None = None) -> dict[str, object]:
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
    if entity.entity_kind == "page" and entity.allowed(Action.EDIT, user=user):
        page = cast("Page", entity)
        result.update(document_edit_projection(
            page.properties.document.source_html, has_snapshot=bool(page.get_asset("snapshot")),
        ))
    form_owner = cast("Task | Page | ModelTask", entity)
    if entity.entity_kind in {"task", "page", "model"} and (form := form_owner.form) and form.allowed(Action.VIEW, user=user):
        if ai_key := form_owner.properties.form.ai_key:
            result.pop(ai_key, None)
        reference = hash_reference(form)
        assert reference is not None
        result["form"] = form_details = {"hash": reference, "name": form.name, "generation": form.generation, "revision": form.version}
        schema = deepcopy(form.schema)
        if schemas is None:
            form_details["schema"] = schema
        else:
            result.pop("schema", None)
            schemas[reference] = schema
    if entity.entity_kind == "project":
        result["model_tasks"] = [{"hash": hash_reference(model), "name": model.name, "order": model.order, "form": hash_reference(model.form) if model.form and model.form.allowed(Action.VIEW, user=user) else None} for model in cast("Project", entity).model_tasks if model.allowed(Action.VIEW, user=user)]
    return result
