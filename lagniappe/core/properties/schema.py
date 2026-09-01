from copy import deepcopy
from enum import Enum

from config.form_schema import (
    SCHEMA_FORMAT_VERSION,
    SchemaValidationError,
    normalize_form_schema,
)

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
    # @matrix form-schema : field-factory unknown-type
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
    # @pair form-schema:validation
    @classmethod
    def validate_type(cls, definition):
        if not isinstance(definition, dict):
            return False
        schema_type = definition.get("type")
        if schema_type == "input":
            input_type = definition.get("input")
            return _member_name(input_type) in cls.__members__
        return _member_name(schema_type) in cls.__members__


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

# @testable true
# @tests tests_unit/test_004b_schema_core.py::test_schema_canonicalizer_unifies_creation_paths_without_changing_membership
# @tests tests_unit/test_004b_schema_core.py::test_schema_canonicalizer_rejects_ambiguous_durable_shapes
# @tests tests_unit/test_004b_schema_core.py::test_schema_canonicalizer_preserves_snapshot_membership
# @tests tests_unit/test_003g_todo_lists.py::test_todo_schema_is_task_only
# @matrix form-schema : canonicalization form-type history-snapshot membership validation versioning
# @pair form-todo:task-only
def canonicalize_schema(
    value,
    *,
    form_type=None,
    snapshot=False,
    discard_invalid=False,
):
    """Return the current durable schema projection without mutating input."""
    return normalize_form_schema(
        value,
        form_type=form_type,
        snapshot=snapshot,
        discard_invalid=discard_invalid,
    )


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
    # @matrix form-schema : cache property
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
    # @pair form-schema:previous
    @property
    def previous(self):
        return self._previous

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_filters_invalid_top_level
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_html_calls_set_html_field
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_table_filters_bad_columns
    # @matrix form-schema form-table : ai-value columns validation
    def validate_ai(self, value):
        from ..tools.ai.form_content import prepare_static_form_element

        candidates = deepcopy(value)
        valid = []
        static_content = {}
        for element in candidates if isinstance(candidates, list) else []:
            if not isinstance(element, dict) or not _valid_schema_id(element.get("id")):
                continue
            element, rendered_content = prepare_static_form_element(
                element,
                form_type=getattr(self.entity, "form_type", None),
            )
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
            if rendered_content is not None:
                static_content.setdefault(element["id"], rendered_content)
            valid.append(element)

        elements = canonicalize_schema(
            valid,
            form_type=getattr(self.entity, "form_type", None),
            discard_invalid=True,
        )
        self.value = elements
        valid_ids = {element["id"] for element in elements}
        for field_id, rendered_content in static_content.items():
            if field_id in valid_ids:
                self.entity.set_html_field(field_id, rendered_content)

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_previous_and_fields_cache
    # @tests tests_unit/test_004_form_properties.py::test_form_schema
    # @matrix form-schema : cache fields property
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
    # @matrix form-schema form-table : table-fields
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
    # @matrix form-schema html-field : html-fields
    @property
    def html_fields(self):
        return [f for f in self.fields.values() if isinstance(f, HTML)]

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_required_fields
    # @pair form-schema:required-fields
    @property
    def required_fields(self):
        return [
            p
            for p in self.fields.values()
            if isinstance(p, SchemaProperty) and p.required
        ]
