"""Shared proposal preparation and execution boundary for cohesive updates.

The action registry is intentionally enabled only with the coordinated contract
cutover. These functions never save; the report runner owns the atomic write of
the returned entities and its execution receipt.
"""

from copy import deepcopy
import hashlib
import json

from google.cloud.datastore import Entity as StoredEntity, Key
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools.entity_patches import prepare_patch, _copy_entity


UPDATE_TARGETS = {
    "update_task": "task",
    "update_model_task": "model",
    "update_project": "project",
    "update_page": "page",
}
RELATION_FIELDS = {
    "page": "page", "project": "project", "model": "model",
    "form": "form", "assigned_to": "page",
    "categories": "category", "model_tasks": "model",
}


# @testable true
# @tests tests_unit/test_032g_entity_patches.py::test_update_review_and_execution_share_exact_references
# @tests tests_unit/test_032g_entity_patches.py::test_update_execution_overwrites_selected_values_but_rejects_unreviewed_proposal
# @tests tests_unit/test_032g_entity_patches.py::test_update_missing_dependencies_never_fall_back_to_entity_lookup
# @matrix entity-patch : integration review dependencies stale-state
def prepare_update_action(action, user, outputs=None):
    """Resolve one action against current entities or earlier successful outputs."""
    kind = UPDATE_TARGETS.get(action.get("type"))
    data = action.get("data")
    if not kind or not isinstance(data, dict) or set(data) != {"entity", "changes"}:
        raise ValidationError("An update requires an exact entity and a changes object.")
    changes = data["changes"]
    if not isinstance(changes, dict):
        raise ValidationError("Changes must be an object.")
    outputs = outputs if outputs is not None else {}
    target = _resolve(data["entity"], kind, outputs)
    resolved = deepcopy(changes)
    for field, expected in RELATION_FIELDS.items():
        if field not in changes:
            continue
        value = changes[field]
        if field in {"categories", "model_tasks"}:
            if not isinstance(value, list):
                raise ValidationError(f"{field} must be a list of exact references.")
            resolved[field] = [_resolve(item, expected, outputs) for item in value]
        else:
            resolved[field] = None if value is None else _resolve(value, expected, outputs)
    return prepare_patch(target, resolved, user)


# @testable true
# @tests tests_unit/test_032g_entity_patches.py::test_update_review_and_execution_share_exact_references
# @tests tests_unit/test_032g_entity_patches.py::test_update_execution_overwrites_selected_values_but_rejects_unreviewed_proposal
# @matrix entity-patch : integration review dependencies stale-state
def review_update_action(action, user, outputs=None):
    """Replace any submitted review metadata with a server-prepared snapshot."""
    prepared = prepare_update_action(action, user, outputs)
    action["_entity_update"] = {
        "proposal": _fingerprint({"type": action["type"], "data": action["data"]}),
        "sources": _sources(prepared, outputs),
        "comparison": _comparison(prepared.before, outputs),
        "before": deepcopy(prepared.before),
        "after": _comparison(prepared.after, outputs),
        "display_after": deepcopy(prepared.after),
        "removed_values": deepcopy(prepared.removed_values),
    }
    return prepared


# @testable true
# @tests tests_unit/test_032g_entity_patches.py::test_update_review_and_execution_share_exact_references
# @tests tests_unit/test_032g_entity_patches.py::test_update_execution_overwrites_selected_values_but_rejects_unreviewed_proposal
# @tests tests_unit/test_032g_entity_patches.py::test_update_missing_dependencies_never_fall_back_to_entity_lookup
# @matrix entity-patch : integration review dependencies stale-state
def execute_update_action(action, report, user, created, context=None):
    """Return validated writes only when they match the server-reviewed proposal."""
    reviewed = action.get("_entity_update")
    if not isinstance(reviewed, dict) or reviewed.get("proposal") != _fingerprint({"type": action.get("type"), "data": action.get("data")}):
        raise ValidationError("This update needs a fresh review before execution.")
    prepared = prepare_update_action(action, user, created)
    if reviewed.get("sources") != _sources(prepared, created):
        raise ValidationError("The reviewed Form changed. Revise this update before execution.")
    return prepared.entity, list(prepared.writes), {
        "previous": deepcopy(prepared.before),
        "entity_update_after": deepcopy(prepared.after),
        "manual": True,
        "note": "Updated the reviewed fields. Further changes require a corrective plan.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/entity_updates.py::prepare_update_action
# @reason strict dependency resolution is exercised through preparation and execution
def _resolve(reference, kind, outputs):
    if not isinstance(reference, str) or not reference:
        raise ValidationError("Use an exact entity reference or an earlier action reference.")
    if reference.startswith(("$", "action:")):
        action_id = reference[1:] if reference.startswith("$") else reference.split(":", 1)[1]
        entity = outputs.get(action_id)
        if entity is None:
            raise ValidationError(f"Required earlier action {action_id} has no successful output.")
    else:
        from .execution.actions.references import _fetch_report_entity

        entity = outputs.get(reference)
        if entity is None:
            entity = outputs.resolve(reference) if hasattr(outputs, "resolve") else _fetch_report_entity(reference)
    if entity is None or entity.entity_kind != kind:
        raise ValidationError(f"Expected an exact {kind} reference.")
    return entity


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/entity_updates.py::execute_update_action
# @reason deterministic source fingerprints bind review to stored source state
def _sources(prepared, outputs=None):
    forms = {}
    for form in prepared.forms:
        forms[_comparison({"id": form.urlsafe_key, "name": ""}, outputs)] = _fingerprint({
            "schema": form.schema, "generation": form.generation,
            "form_type": form.form_type, "pending": form.db.get("pending_form_change"),
        })
    return forms


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/entity_updates.py::execute_update_action
# @reason earlier outputs have stable action identities across preview and execution
def _comparison(value, outputs=None):
    aliases = {entity.urlsafe_key: "$" + name for name, entity in (outputs or {}).items() if isinstance(name, str) and not name.startswith(("$", "action:")) and name != entity.urlsafe_key}
    if isinstance(value, dict):
        if set(value) == {"id", "name"}:
            return aliases.get(value["id"], value["id"])
        return {key: _comparison(child, outputs) for key, child in value.items()}
    if isinstance(value, list):
        return [_comparison(child, outputs) for child in value]
    if isinstance(value, str):
        return aliases.get(value, value)
    return value


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/entity_updates.py::execute_update_action
# @reason fingerprint encoding is shared by proposal and source checks
def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


# @testable true
# @tests tests_unit/test_032g_entity_patches.py::test_proposal_prepares_new_forms_and_model_order
# @tests tests_unit/test_032g_entity_patches.py::test_proposal_orders_models_on_a_new_project
# @matrix entity-patch : integration review dependencies stale-state
def prepare_entity_updates(proposal, user):
    """Prepare updates in proposal order without creating workspace records."""
    if not any(action.get("type") in UPDATE_TARGETS for action in proposal.get("actions", [])):
        return proposal
    outputs = {}
    action_ids = {action["id"] for action in proposal["actions"] if action.get("id")}
    touched = set()
    for index, action in enumerate(proposal["actions"], 1):
        action_id = action.get("id")
        if not action_id:
            action_id = f"update_{index}"
            while action_id in action_ids:
                action_id += "_next"
            action["id"] = action_id
            action_ids.add(action_id)
        kind, data = action.get("type"), action.get("data", {})
        if action.get("skip"):
            continue
        if kind in {"create_form", "create_project", "create_model_task"}:
            entity_kind = {"create_form": "form", "create_project": "project", "create_model_task": "model"}[kind]
            row = StoredEntity(key=Key(entity_kind, "proposal-" + action_id, project="proposal-preview"))
            row.update(kind=entity_kind, name=data.get("name"), hash="proposal-" + action_id)
            cls = {"form": Entities.FORM, "project": Entities.PROJECT, "model": Entities.MODEL_TASK}[entity_kind]
            entity = cls(row)
            if kind == "create_form":
                entity.form_type = data.get("form_type")
                entity.properties.schema.validate_ai(data.get("schema"))
            elif kind == "create_project":
                entity.description = data.get("description")
                entity.properties.model_tasks._value = []
            else:
                reference = data.get("project") or "$" + data.get("project_action", "")
                project = _resolve(reference, "project", outputs)
                if project.urlsafe_key not in outputs:
                    original = project
                    project = _copy_entity(project)
                    project.properties.model_tasks._value = list(original.model_tasks)
                    outputs[project.urlsafe_key] = project
                entity.project = project
                form_ref = data.get("form") or ("$" + data["form_action"] if data.get("form_action") else None)
                entity.form = _resolve(form_ref, "form", outputs) if form_ref else None
                entity.order = len(project.model_tasks) + 1
                project.properties.model_tasks._value = [*project.model_tasks, entity]
            outputs[action_id] = entity
            outputs[entity.urlsafe_key] = entity
        elif kind in UPDATE_TARGETS:
            prepared = review_update_action(action, user, outputs)
            target_id = prepared.entity.urlsafe_key
            if target_id in touched:
                raise ValidationError("Combine edits to the same entity into one cohesive update.")
            touched.add(target_id)
            outputs[action_id] = prepared.entity
            outputs[target_id] = prepared.entity
            # Ordering depends on all newly created models in that Project.
            if kind == "update_project" and "model_tasks" in data.get("changes", {}):
                dependencies = set(action.get("depends_on", []))
                dependencies.update(name for name, entity in outputs.items() if name in action_ids and entity.entity_kind == "model" and entity.project.key == prepared.entity.key)
                action["depends_on"] = sorted(dependencies)
        elif kind == "update_form_schema":
            # Schema migration and answer patches must be separate reviewed jobs.
            raise ValidationError("Execute Form schema migrations before planning cohesive entity updates.")
    if len(json.dumps(proposal, default=str).encode()) > 750 * 1024:
        raise ValidationError("This proposal is too large; split the updates into smaller plans.")
    return proposal


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/entity_updates.py::review_update_action
# @reason display projects the complete server-prepared before/after snapshot
def update_details(details, data, action=None):
    details.reference("Entity", data, "entity")
    review = (action or {}).get("_entity_update", {})
    before, after = review.get("before", {}), review.get("display_after", {})
    for field in sorted(data.get("changes", {})):
        values = [before.get(field), after.get(field)]
        if field in RELATION_FIELDS:
            values = [[item.get("name") for item in value] if isinstance(value, list) else value.get("name") if isinstance(value, dict) else value for value in values]
        details.add(field.replace("_", " ").title(), " → ".join(json.dumps(value, ensure_ascii=False, default=str) for value in values))
    if review.get("removed_values"):
        details.add("Removed answers", json.dumps(review["removed_values"], ensure_ascii=False, default=str))
    if (action or {}).get("type") == "update_model_task" and "form" in data.get("changes", {}):
        details.add("Existing tasks", "Unchanged. This default applies to future tasks only.")
