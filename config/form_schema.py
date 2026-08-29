"""Framework-neutral durable form-schema normalization."""

from copy import deepcopy


SCHEMA_FORMAT_VERSION = 1
_INPUT_TYPES = frozenset({"text", "date", "time", "number", "email", "tel"})
_FIELD_TYPES = frozenset(
    {
        "bookmark",
        "checkbox",
        "html",
        "input",
        "link",
        "location",
        "radio",
        "select",
        "signature",
        "status",
        "table",
        "todo",
        "textarea",
    }
)
_TABLE_FIELD_TYPES = frozenset({"checkbox", "input", "link"})
_FIELD_TITLES = {
    "bookmark": "Bookmark",
    "checkbox": "Checkbox",
    "html": "Rich Text",
    "input": "Input",
    "link": "Link",
    "location": "Location",
    "radio": "Radio Group",
    "select": "Select",
    "signature": "Signature",
    "status": "Status",
    "table": "Table",
    "todo": "Todo List",
    "textarea": "Text",
}


# @testable infrastructure
class SchemaValidationError(ValueError):
    """A schema cannot be projected into the current durable format."""


# @testable false
# @covered-by lagniappe/core/properties/schema.py::canonicalize_schema
# @reason small invalid-field policy helper owned by durable schema normalization
def _invalid(message, discard_invalid):
    if discard_invalid:
        return None
    raise SchemaValidationError(message)


# @testable false
# @covered-by lagniappe/core/properties/schema.py::canonicalize_schema
# @reason option validation is exercised through the public schema canonicalizer
def _canonical_options(value, field_id, discard_invalid):
    if value is None:
        return []
    if not isinstance(value, list):
        return _invalid(
            f"Schema field {field_id!r} options must be a list",
            discard_invalid,
        )

    options = []
    for option in value:
        if not isinstance(option, dict):
            if discard_invalid:
                continue
            raise SchemaValidationError(
                f"Schema field {field_id!r} options must contain objects"
            )
        label = option.get("label")
        option_value = option.get("value")
        if not isinstance(label, str) or not label.strip():
            if discard_invalid:
                continue
            raise SchemaValidationError(
                f"Schema field {field_id!r} option labels must be non-empty strings"
            )
        if not isinstance(option_value, str) or not option_value.strip():
            if discard_invalid:
                continue
            raise SchemaValidationError(
                f"Schema field {field_id!r} option values must be non-empty strings"
            )
        canonical = deepcopy(option)
        canonical["label"] = label.strip()
        canonical["value"] = option_value.strip()
        options.append(canonical)
    return options


# @testable false
# @covered-by lagniappe/core/properties/schema.py::canonicalize_schema
# @reason nested condition validation is exercised through the public schema canonicalizer
def _canonical_condition_list(value, field_id, attribute, discard_invalid):
    if value is None:
        return None
    if not isinstance(value, list):
        return _invalid(
            f"Schema field {field_id!r} {attribute} must be a list or null",
            discard_invalid,
        )
    if not all(isinstance(item, dict) for item in value):
        return _invalid(
            f"Schema field {field_id!r} {attribute} must contain objects",
            discard_invalid,
        )
    return deepcopy(value)


# @testable false
# @covered-by lagniappe/core/properties/schema.py::canonicalize_schema
# @reason recursive field normalization is exercised through the public schema canonicalizer
def _canonical_field(definition, *, table_column=False, discard_invalid=False):
    if not isinstance(definition, dict):
        return _invalid("Schema fields must be objects", discard_invalid)

    field_id = definition.get("id")
    if not isinstance(field_id, str) or not field_id.strip():
        return _invalid("Schema fields require a non-empty id", discard_invalid)
    field_id = field_id.strip()

    field_type = definition.get("type")
    if not isinstance(field_type, str) or not field_type.strip():
        return _invalid(f"Schema field {field_id!r} requires a type", discard_invalid)
    field_type = field_type.strip().lower()

    input_type = definition.get("input")
    if isinstance(input_type, str):
        input_type = input_type.strip().lower()
    if field_type in _INPUT_TYPES:
        input_type = field_type
        field_type = "input"
    elif field_type == "input":
        input_type = input_type or "text"

    allowed_types = _TABLE_FIELD_TYPES if table_column else _FIELD_TYPES
    if field_type not in allowed_types:
        return _invalid(
            f"Schema field {field_id!r} has unsupported type {field_type!r}",
            discard_invalid,
        )
    if field_type == "input" and input_type not in _INPUT_TYPES:
        return _invalid(
            f"Schema field {field_id!r} has unsupported input type {input_type!r}",
            discard_invalid,
        )

    field = deepcopy(definition)
    field["id"] = field_id
    field["type"] = field_type
    if field_type == "input":
        field["input"] = input_type

    title = field.get("title")
    if not isinstance(title, str) or not title.strip():
        field["title"] = _FIELD_TITLES[field_type]
    else:
        field["title"] = title.strip()

    if field_type == "link":
        location = field.get("location") or "out"
        if location not in {"in", "out"}:
            return _invalid(
                f"Schema field {field_id!r} has unsupported link location",
                discard_invalid,
            )
        field["location"] = location

    if field_type in {"radio", "select"}:
        options = _canonical_options(field.get("options"), field_id, discard_invalid)
        if options is None:
            return None
        field["options"] = options

    if "visibility" in field:
        visibility = _canonical_condition_list(
            field.get("visibility"), field_id, "visibility", discard_invalid
        )
        if visibility is None and field.get("visibility") is not None:
            return None
        field["visibility"] = visibility

    if field_type == "status":
        status = _canonical_condition_list(
            field.get("status", []), field_id, "status", discard_invalid
        )
        if status is None:
            return None
        field["status"] = status

    if field_type == "table":
        raw_columns = field.get("columns", [])
        if not isinstance(raw_columns, list):
            if discard_invalid:
                raw_columns = []
            else:
                raise SchemaValidationError(
                    f"Schema field {field_id!r} columns must be a list"
                )
        columns = []
        column_ids = set()
        for raw_column in raw_columns:
            column = _canonical_field(
                raw_column,
                table_column=True,
                discard_invalid=discard_invalid,
            )
            if column is None:
                continue
            if column["id"] in column_ids:
                if discard_invalid:
                    continue
                raise SchemaValidationError(
                    f"Schema table {field_id!r} has duplicate column id "
                    f"{column['id']!r}"
                )
            column_ids.add(column["id"])
            columns.append(column)
        field["columns"] = columns

    return field


# @testable false
# @covered-by lagniappe/core/properties/schema.py::canonicalize_schema
# @reason runtime-neutral implementation is exercised through the public schema canonicalizer
def normalize_form_schema(
    value,
    *,
    form_type=None,
    snapshot=False,
    discard_invalid=False,
):
    """Return the current durable schema projection without mutating input."""
    del snapshot
    if not isinstance(value, list):
        raise SchemaValidationError("Schema must be a list")

    fields = []
    field_ids = set()
    for definition in value:
        field = _canonical_field(definition, discard_invalid=discard_invalid)
        if field is None:
            continue
        if field["id"] in field_ids:
            if discard_invalid:
                continue
            raise SchemaValidationError(f"Duplicate schema field id {field['id']!r}")
        if form_type == "page" and field["type"] == "todo":
            if discard_invalid:
                continue
            raise SchemaValidationError("Todo lists are supported only on task forms")
        field_ids.add(field["id"])
        fields.append(field)

    return fields
