"""Pure, identity-addressed AI proposals for the form builder's local draft."""

from copy import deepcopy
import re

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools.files.html import render_markdown
from lagniappe.core.tools.form_drafts import validate_draft_schema

NEW_IDENTITY = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


# @testable false
# @covered-by lagniappe/core/tools/ai/form_draft.py::prepare_generated_changes
# @reason exact operation members are part of the generated-proposal validation contract
def _members(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional):
        raise ValidationError("The generated change contains unsupported settings.")
    if set(required) - set(value):
        raise ValidationError("The generated change is missing a required setting.")


# @testable false
# @covered-by lagniappe/core/tools/ai/form_draft.py::prepare_generated_changes
# @reason exact identity resolution is owned by proposal validation
def _find(items, identity, key="id"):
    if not isinstance(identity, str) or not identity:
        raise ValidationError("Generated edits require an exact existing identity.")
    matches = [item for item in items if item.get(key) == identity]
    if len(matches) != 1:
        raise ValidationError("A generated edit refers to an unknown or ambiguous identity.")
    return matches[0]


# @testable false
# @covered-by lagniappe/core/tools/ai/form_draft.py::prepare_generated_changes
# @reason generated text values are validated at the proposal boundary
def _text(value, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValidationError("Generated labels must be non-empty text.")
    return value if empty else value.strip()


# @testable false
# @covered-by lagniappe/core/tools/ai/form_draft.py::prepare_generated_changes
# @reason new provider identities must work with existing asset paths and UI selectors
def _new_identities(field):
    identities = [field.get("id")]
    identities.extend(option.get("value") for option in field.get("options", []))
    if any(not isinstance(value, str) or not NEW_IDENTITY.fullmatch(value) for value in identities):
        raise ValidationError("New generated identities must use only letters, numbers, underscores or hyphens.")
    for column in field.get("columns", []):
        _new_identities(column)


# @testable true
# @tests tests_unit/test_004f_form_draft_generation.py::*
# @matrix forms ai : draft-generation stable-identity validation no-side-effects
def prepare_generated_changes(result, draft, *, form_type, image_sources=None):
    """Validate an entire proposal without mutating its draft or any entity.

    The provider writes Markdown sidecars; the browser receives sanitized HTML.
    Existing fields are patched by identity, so omitted settings survive exactly.
    """
    _members(result, ("operations",), ("content_markdown",))
    if not isinstance(result["operations"], list):
        raise ValidationError("Generated operations must be a list.")
    content = result.get("content_markdown", {})
    if not isinstance(content, dict):
        raise ValidationError("Generated static content must be an object.")

    schema = validate_draft_schema(deepcopy(draft["schema"]), form_type)
    operations = []
    for raw in result["operations"]:
        if not isinstance(raw, dict):
            raise ValidationError("Every generated operation must be an object.")
        operation = deepcopy(raw)
        op = operation.get("op")
        if op == "add_field":
            _members(operation, ("op", "field"))
            field = operation["field"]
            if not isinstance(field, dict) or "html" in field or "content_markdown" in field:
                raise ValidationError("Use the content_markdown sidecar for static content.")
            if not isinstance(field.get("id"), str) or field["id"] != field["id"].strip():
                raise ValidationError("Generated field identities must be exact non-blank strings.")
            if any(item["id"] == field.get("id") for item in schema):
                raise ValidationError("Generated additions must have new field identities.")
            schema.append(field)
        elif op == "update_field":
            _members(operation, ("op", "field_id", "changes"))
            changes = operation["changes"]
            _members(changes, (), ("title", "placeholder"))
            field = _find(schema, operation["field_id"])
            for key, value in changes.items():
                changes[key] = _text(value, empty=key == "placeholder")
            field.update(changes)
        elif op == "update_option":
            _members(operation, ("op", "field_id", "value", "label"))
            field = _find(schema, operation["field_id"])
            if field["type"] not in {"radio", "select"}:
                raise ValidationError("Only radio/select options can be relabelled.")
            option = _find(field.get("options", []), operation["value"], "value")
            operation["label"] = option["label"] = _text(operation["label"])
        elif op == "update_column":
            _members(operation, ("op", "field_id", "column_id", "title"))
            field = _find(schema, operation["field_id"])
            if field["type"] != "table":
                raise ValidationError("Only table columns can be relabelled.")
            column = _find(field.get("columns", []), operation["column_id"])
            operation["title"] = column["title"] = _text(operation["title"])
        else:
            raise ValidationError(
                "This change needs migration support. Generate additions or label/content edits instead."
            )
        operations.append(operation)

    canonical = validate_draft_schema(schema, form_type)
    fields = {field["id"]: field for field in canonical}
    # Return the normalized addition, not a second whole-schema replacement.
    for operation in operations:
        if operation["op"] == "add_field":
            _new_identities(fields[operation["field"]["id"]])
            operation["field"] = deepcopy(fields[operation["field"]["id"]])

    html_fields = {}
    for field_id, markdown in content.items():
        field = _find(canonical, field_id)
        if field["type"] != "html" or form_type != "task":
            raise ValidationError("Static content must address an existing task-form HTML field.")
        _text(markdown, empty=True)
        html_fields[field_id] = str(render_markdown(
            markdown, image_sources=(image_sources or {}).get(field_id, ()),
        ))
    return {"operations": operations, "html_fields": html_fields}
