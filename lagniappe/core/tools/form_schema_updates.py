"""Read-only schema operations and complete, permission-checked migration impact."""

from copy import deepcopy
import hashlib
import json

from ..definitions import Action, Fetch, FetchReason
from ..entities import Entities
from ..exceptions import ValidationError
from ..properties.schema import SchemaValidationError
from . import form_conversions as conversions, form_drafts


RESTRICTED_MESSAGE = (
    "Pages/Tasks that would be affected by this change are restricted. "
    "This form can only be updated by an admin."
)
STALE_MESSAGE = "This Form or its affected submissions changed. Refresh the schema preview and review a new proposal."
OPERATIONS = frozenset(
    {"add_field", "add_select_option", "update_field", "remove_field", "reorder_fields"}
)
PATCH_KEYS = frozenset(
    {
        "type",
        "title",
        "label",
        "input",
        "placeholder",
        "required",
        "multiple",
        "location",
        "options",
        "columns",
        "visibility",
        "status",
        "layout",
        "checked",
        "address",
        "icon",
        "kind",
    }
)


# @testable infrastructure
class RestrictedFormChange(ValidationError):
    """A migration cannot expose all of its inputs to the requesting actor."""


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_operations_preserve_identity_and_validate_final_schema
# @matrix form-migration : schema-operations stable-identity validation
def apply_operations(schema, operations, form_type):
    """Apply exact-ID edits on a detached schema, then validate the whole result."""
    if not isinstance(operations, list) or not operations:
        raise ValidationError("Schema updates require at least one operation.")
    result = deepcopy(schema)
    original_ids = {field["id"] for field in schema}
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") not in OPERATIONS:
            raise ValidationError("Unsupported schema operation.")
        op = operation["op"]
        fields = {field["id"]: field for field in result}
        if op == "add_field":
            field = operation.get("field")
            if (
                not isinstance(field, dict)
                or not isinstance(field.get("id"), str)
                or not field["id"].strip()
            ):
                raise ValidationError(
                    "An added field requires an exact id and definition."
                )
            if field["id"] in original_ids or field["id"] in fields:
                raise ValidationError(
                    "An added field cannot reuse an existing or removed field ID."
                )
            if field.get("type") in {"html", "status", "signature"}:
                raise ValidationError(
                    "Schema update actions cannot add static or signature fields."
                )
            result.append(deepcopy(field))
            original_ids.add(field["id"])
            continue
        if op == "reorder_fields":
            ids = operation.get("ids")
            if not isinstance(ids, list) or any(
                not isinstance(value, str) for value in ids
            ):
                raise ValidationError("Field order requires an array of exact IDs.")
            if len(ids) != len(fields) or set(ids) != set(fields):
                raise ValidationError(
                    "Field order must include every field exactly once."
                )
            result = [fields[field_id] for field_id in ids]
            continue
        field_id = operation.get("schema_id")
        if not isinstance(field_id, str) or field_id not in fields:
            raise ValidationError(
                "Schema operation references an unavailable field ID."
            )
        field = fields[field_id]
        if op == "remove_field":
            if field_id in {"name", "description"}:
                raise ValidationError("Reserved Page fields cannot be removed.")
            result.remove(field)
        elif op == "add_select_option":
            option = operation.get("option")
            if field["type"] not in {"select", "radio"} or not isinstance(option, dict):
                raise ValidationError(
                    "An added option requires a selection field and value/label object."
                )
            field.setdefault("options", []).append(deepcopy(option))
        elif op == "update_field":
            patch = operation.get("patch")
            if not isinstance(patch, dict) or not patch or set(patch) - PATCH_KEYS:
                raise ValidationError(
                    "Field patches require supported settings and cannot change IDs."
                )
            old_type = field["type"]
            new_type = patch.get("type", old_type)
            if old_type != new_type:
                for name in (
                    "input",
                    "location",
                    "options",
                    "multiple",
                    "columns",
                    "checked",
                    "status",
                ):
                    field.pop(name, None)
            for name, value in patch.items():
                if value is None:
                    if name in {"type", "title"}:
                        raise ValidationError("Field type and title cannot be cleared.")
                    field.pop(name, None)
                else:
                    field[name] = deepcopy(value)
    try:
        return form_drafts.validate_draft_schema(result, form_type)
    except SchemaValidationError as error:
        raise ValidationError(str(error)) from error


# @testable false
# @covered-by lagniappe/core/tools/form_schema_updates.py::inspect_scope
# @reason canonical fingerprints are shared by preview, approval and worker preflight
def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/form_schema_updates.py::inspect_scope
# @reason blank collection envelopes should never require a provider call
def needs_ai_value(value):
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, dict) and (value == {"rows": []} or value == {"items": []}):
        return False
    return True


# @testable false
# @covered-by lagniappe/core/tools/form_schema_updates.py::inspect_scope
# @reason value preconditions bind an exact entity, generation and schema pair
def value_fingerprint(entity, change, values):
    return fingerprint(
        {
            "entity": entity.urlsafe_key,
            "form": str(entity.db.get("form")),
            "generation": entity.generation,
            "source": change["source"],
            "target": change["target"],
            "present": change["id"] in values,
            "value": values.get(change["id"]),
        }
    )


# @testable false
# @covered-by lagniappe/core/tools/form_schema_updates.py::inspect_scope
# @reason scope checks materialize the relations needed by normal permission rules
def require_visible(entity, actor):
    entity = Entities.fetch_one(
        entity,
        request=Fetch.nested(
            because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION
        ),
    )
    if not entity or not entity.allowed(Action.VIEW, user=actor):
        raise RestrictedFormChange(RESTRICTED_MESSAGE)
    return entity


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_scope_is_exhaustive_permission_checked_and_projects_only_affected_values
# @matrix form-migration : complete-scope permissions affected-values pagination
def inspect_scope(form, changes, actor, *, include_values=False, ensure_active=None):
    """Check every attached live row; never mistake a filtered page for full scope."""
    from . import dates, form_changes

    if not form.allowed(Action.EDIT, user=actor) or form.reserved:
        raise ValidationError("You do not have permission to update this Form.")
    impact, members = [], []
    if not changes:
        return {"scope_fingerprint": fingerprint([]), "instances": [], "total": 0}
    cursor = None
    while True:
        batch = form_changes.target_batch(form, cursor)
        for raw in batch:
            if ensure_active:
                ensure_active()
            entity = form_changes.load_target(raw)
            if not entity:
                continue
            entity = require_visible(entity, actor)
            values = form_changes.json_value(entity.db, "submission")
            fields, hashes = [], []
            for change in changes:
                source_hash = value_fingerprint(entity, change, values)
                hashes.append(source_hash)
                if change["id"] not in values:
                    continue
                before = values[change["id"]]
                ai = change["rule"] == "ai" and needs_ai_value(before)
                if change["rule"] != "ai":
                    after, reason = conversions.convert_value(
                        before,
                        change["source"],
                        change["target"],
                        mapping=change["map"],
                        zone=str(dates.user_timezone(actor)),
                    )
                    if after is not conversions.MISSING and fingerprint(
                        before
                    ) == fingerprint(after):
                        continue
                else:
                    reason = "ai" if ai else "unset"
                    if not ai:
                        continue
                item = {
                    "schema_id": change["id"],
                    "title": change["source"].get("title", change["id"]),
                    "rule": change["rule"],
                    "reason": reason,
                    "source_fingerprint": source_hash,
                }
                if ai and include_values:
                    item["value"] = deepcopy(before)
                fields.append(item)
            members.append([entity.urlsafe_key, entity.generation, hashes])
            if fields:
                impact.append(
                    {
                        "id": entity.urlsafe_key,
                        "kind": entity.entity_kind,
                        "fields": fields,
                    }
                )
        cursor = batch.next_cursor
        if not cursor:
            break
    return {
        "scope_fingerprint": fingerprint(members),
        "instances": impact,
        "total": len(members),
    }


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_external_candidates_require_exact_coverage_and_source_fingerprints
# @matrix form-migration : candidate-validation stale-value complete-scope
def validate_candidates(candidates, scope, changes):
    """Require one strict result for every populated AI conversion and no others."""
    if not isinstance(candidates, list):
        raise ValidationError("Prepared conversions must be an array.")
    required = {
        (item["id"], field["schema_id"]): field["source_fingerprint"]
        for item in scope["instances"]
        for field in item["fields"]
        if field["rule"] == "ai"
    }
    by_field = {change["id"]: change for change in changes}
    found = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValidationError("Each prepared conversion must be an object.")
        if set(candidate) - {
            "entity",
            "schema_id",
            "source_fingerprint",
            "value",
            "unresolved_reason",
        }:
            raise ValidationError(
                "Prepared conversions contain unsupported properties."
            )
        key = (candidate.get("entity"), candidate.get("schema_id"))
        if (
            any(not isinstance(value, str) for value in key)
            or key not in required
            or key in found
        ):
            raise ValidationError(
                "Prepared conversions contain duplicate or unexpected entity/field targets."
            )
        if candidate.get("source_fingerprint") != required[key]:
            raise ValidationError(STALE_MESSAGE)
        conversions.validate_ai_candidate(candidate, by_field[key[1]]["target"])
        found.add(key)
    if found != set(required):
        raise ValidationError(
            "AI conversions are missing. Call preview_form_schema_update with include_values=true, follow every next_cursor, and prepare every required entity/field conversion."
        )
    return deepcopy(candidates)
