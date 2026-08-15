from copy import deepcopy
from enum import Enum

from ..mixins import AIMixin
from .base_db import DBProperty
from .base_schema import SchemaProperty
from .form_inputs import (
    TextInput,
    DateInput,
    TimeInput,
    NumberInput,
    EmailInput,
    TelInput,
)
from .form_checkbox import Checkbox
from .form_select import Select, Radio
from .form_table import Table
from .form_todo import TodoList
from .form_links import Link, Location, Bookmark
from .form_special import Signature, HTML, Status
from .form_textarea import Textarea
from .row_submission import TableColumnFields


# @testable false
# @covered-by lagniappe/core/properties/schema.py::SchemaFields.create_field
# @covered-by lagniappe/core/properties/schema.py::SchemaFields.validate_type
# @reason small enum-member normalization helper owned by schema field validation
def _member_name(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value.upper()


# @testable false
# @covered-by lagniappe/core/properties/schema.py::Schema.validate_ai
# @reason small id guard owned by AI schema validation
def _valid_schema_id(value):
    return isinstance(value, str) and bool(value.strip())


class SchemaFields(Enum):
    TEXT = TextInput
    DATE = DateInput
    TIME = TimeInput
    NUMBER = NumberInput
    EMAIL = EmailInput
    TEL = TelInput
    TEXTAREA = Textarea
    CHECKBOX = Checkbox
    RADIO = Radio
    SELECT = Select
    TABLE = Table
    TODO = TodoList
    LINK = Link
    LOCATION = Location
    SIGNATURE = Signature
    HTML = HTML
    BOOKMARK = Bookmark
    STATUS = Status

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_create_field_unknown_returns_none
    # @tests tests_unit/test_004b_schema_core.py::test_schema_create_field_known_text_input
    # @features form-schema
    # @dimensions field-factory, unknown-type
    @classmethod
    def create_field(cls, definition, entity):
        """Create a field instance from a schema definition."""
        if not isinstance(definition, dict):
            return None
        field_type = definition.get("input") or definition.get("type")
        name = _member_name(field_type)
        if name not in cls.__members__:
            return None
        return cls[name].value(definition, entity=entity)

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_filters_invalid_top_level
    # @features form-schema
    # @dimensions validation
    @classmethod
    def validate_type(cls, definition):
        if not isinstance(definition, dict):
            return False
        schema_type = definition.get("type")
        if schema_type == "input":
            input_type = definition.get("input")
            return _member_name(input_type) in cls.__members__
        return _member_name(schema_type) in cls.__members__


SCHEMA_FORMAT_VERSION = 1

PAGE_DEFAULT_SCHEMA = [
    {
        "id": "name",
        "input": "text",
        "title": "Name",
        "placeholder": "give this page a name...",
        "type": "input",
    },
    {
        "id": "description",
        "title": "Description",
        "type": "textarea",
    },
]

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
    "todo": "To-do List",
    "textarea": "Text",
}


class SchemaValidationError(ValueError):
    """A schema cannot be projected into the current durable format."""


# @testable false
# @covered-by lagniappe/core/properties/schema.py::canonicalize_schema
# @reason field validation is exercised through the public schema canonicalizer
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
        return _invalid(f"Schema field {field_id!r} options must be a list", discard_invalid)

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
                    f"Schema table {field_id!r} has duplicate column id {column['id']!r}"
                )
            column_ids.add(column["id"])
            columns.append(column)
        field["columns"] = columns

    return field


# @testable true
# @tests tests_unit/test_004b_schema_core.py::test_schema_canonicalizer_unifies_creation_paths_without_changing_membership
# @tests tests_unit/test_004b_schema_core.py::test_schema_canonicalizer_rejects_ambiguous_durable_shapes
# @tests tests_unit/test_004b_schema_core.py::test_schema_canonicalizer_preserves_snapshot_membership
# @tests tests_unit/test_003g_todo_lists.py::test_todo_schema_is_task_only
# @pairs form-schema:canonicalization form-schema:versioning
# @pairs form-schema:membership form-schema:validation
# @pairs form-schema:history-snapshot form-schema:form-type
# @pair form-todo:task-only
def canonicalize_schema(
    value,
    *,
    form_type=None,
    snapshot=False,
    discard_invalid=False,
):
    """Return the current durable schema projection without mutating input."""

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
            raise SchemaValidationError("To-do lists are supported only on task forms")
        field_ids.add(field["id"])
        fields.append(field)

    return fields


SCHEMA_ATTRIBUTES = [
    "id",
    "label",
    "icon",
    "kind",
    "required",
    "visibility",
    "placeholder",
    "input",
    "type",
    "options",
    "multiple",
]


class SchemaFormat(DBProperty):
    """Durable format version for a form or form-history schema."""

    _id = "schema_format"


# @testable false
# @covered-by lagniappe/core/properties/schema.py::Schema.value
# @covered-by lagniappe/core/properties/schema.py::Schema.previous
# @covered-by lagniappe/core/properties/schema.py::Schema.fields
# @covered-by lagniappe/core/properties/schema.py::Schema.table_fields
# @covered-by lagniappe/core/properties/schema.py::Schema.html_fields
# @covered-by lagniappe/core/properties/schema.py::Schema.required_fields
# @covered-by lagniappe/core/properties/schema.py::Schema.validate_ai
class Schema(AIMixin, DBProperty):
    """Form schema stored as a JSON list of field definitions.

    Each field definition is a dict with keys like id, title, type,
    input, options, etc. The fields property instantiates SchemaProperty
    subclasses from these definitions.

    Set:
        value (list[dict]): Field definition dicts. Clears the fields cache.

    Get:
        value (list[dict]): Field definition dicts (defaults to []).
        fields (dict): {field_id: SchemaProperty instance}.
        required_fields (list): Fields where ``required`` is True.
    """

    _id = "schema"
    json = True

    @property
    def ai_key(self):
        return self.id

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fields = None
        self._table_fields = None
        self._previous = False

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_previous_and_fields_cache
    # @tests tests_unit/test_004_form_properties.py::test_form_schema
    # @tests tests_unit/test_004_form_properties.py::test_form_schema_change_refreshes_table_fields_and_filter_conditions
    # @features form-schema
    # @dimensions property, cache
    @property
    def value(self):
        value = super().value or []
        if self.entity.db.get("schema_format") == SCHEMA_FORMAT_VERSION:
            return value

        try:
            return canonicalize_schema(
                value,
                form_type=getattr(self.entity, "form_type", None),
                snapshot=getattr(self.entity, "entity_kind", None) == "form_history",
            )
        except SchemaValidationError:
            # Migration reports malformed rows for repair. Until Apply Updates
            # runs, preserve the old reader's ability to expose the raw schema.
            return value

    @value.setter
    def value(self, value):
        self.fields = None
        self._previous = DBProperty.value.fget(self) or []
        canonical = canonicalize_schema(
            value,
            form_type=getattr(self.entity, "form_type", None),
            snapshot=getattr(self.entity, "entity_kind", None) == "form_history",
        )
        DBProperty.value.fset(self, canonical)
        if "schema_format" in self.entity.properties:
            self.entity.properties.schema_format.value = SCHEMA_FORMAT_VERSION
        else:
            self.entity.db["schema_format"] = SCHEMA_FORMAT_VERSION
        if self.entity.properties.get("filters"):
            self.entity.properties.filters.reset()

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_previous_and_fields_cache
    # @features form-schema
    # @dimensions previous
    @property
    def previous(self):
        return self._previous

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_filters_invalid_top_level
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_html_calls_set_html_field
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_table_filters_bad_columns
    # @features form-schema, form-table
    # @dimensions ai-value, validation, columns
    def validate_ai(self, value):
        candidates = deepcopy(value)
        valid = []
        for element in candidates if isinstance(candidates, list) else []:
            if not isinstance(element, dict) or not _valid_schema_id(element.get("id")):
                continue
            if not SchemaFields.validate_type(element):
                continue
            if element.get("type") == "table":
                columns = element.get("columns", [])
                if not isinstance(columns, list):
                    columns = []
                element["columns"] = [
                    column
                    for column in columns
                    if isinstance(column, dict)
                    and _valid_schema_id(column.get("id"))
                    and TableColumnFields.validate_type(column)
                ]
            if element.get("type") == "html" and _valid_schema_id(element.get("id")):
                html = element.pop("html", None)
                if html is not None:
                    self.entity.set_html_field(element["id"], html)
            valid.append(element)

        elements = canonicalize_schema(
            valid,
            form_type=getattr(self.entity, "form_type", None),
            discard_invalid=True,
        )
        self.value = elements

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_previous_and_fields_cache
    # @tests tests_unit/test_004_form_properties.py::test_form_schema
    # @features form-schema
    # @dimensions fields, cache, property
    @property
    def fields(self):
        if getattr(self, "_fields", None) is not None:
            return self._fields

        fields = [SchemaFields.create_field(s, self.entity) for s in self.value]

        self._fields = {f.id: f for f in fields if f is not None}
        return self._fields

    @fields.setter
    def fields(self, value):
        self._fields = value
        self._table_fields = None

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_table_fields
    # @features form-schema, form-table
    # @dimensions table-fields
    @property
    def table_fields(self):
        if getattr(self, "_table_fields", None) is not None:
            return self._table_fields

        table_fields = {}
        for field in self.fields.values():
            if isinstance(field, Table):
                table_fields.update(field.fields)

        self._table_fields = table_fields
        return self._table_fields

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_html_fields
    # @features form-schema, html-field
    # @dimensions html-fields
    @property
    def html_fields(self):
        return [f for f in self.fields.values() if isinstance(f, HTML)]

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_required_fields
    # @features form-schema
    # @dimensions required-fields
    @property
    def required_fields(self):
        return [
            p
            for p in self.fields.values()
            if isinstance(p, SchemaProperty) and p.required
        ]
