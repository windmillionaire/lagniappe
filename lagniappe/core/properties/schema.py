from copy import deepcopy
from enum import Enum
from typing import TYPE_CHECKING, Literal, cast

from config.form_schema import (
    SCHEMA_FORMAT_VERSION,
    SchemaValidationError,
    normalize_form_schema,
)

from ..exceptions import ValidationError
from ..mixins import AIMixin
from .base_db import DBProperty
from .base_schema import FieldDefinition, SchemaProperty
from .form_checkbox import Checkbox
from .form_inputs import (
    DateInput,
    EmailInput,
    NumberInput,
    TelInput,
    TextInput,
    TimeInput,
)
from .form_links import Bookmark, Link, Location
from .form_select import Radio, Select
from .form_special import HTML, Signature, Status
from .form_table import Table
from .form_textarea import Textarea
from .form_todo import TodoList
from .row_submission import ColumnField, TableColumnFields

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.form import Form
    from ..mixins.field_host import FieldUser


def _member_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value.upper()


def _valid_schema_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


type SchemaField = ColumnField | Textarea | Radio | Select | Table | TodoList | Location | Signature | HTML | Bookmark | Status


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

    @classmethod
    def create_field(cls, definition: object, entity: Entity) -> SchemaField | None:
        """Create a field instance from a schema definition."""
        if not isinstance(definition, dict):
            return None
        field_type = definition.get("input") or definition.get("type")
        name = _member_name(field_type)
        if name is None or name not in cls.__members__:
            return None
        return cls[name].value(definition, entity=entity)

    @classmethod
    def prepare_ai_field(
        cls,
        definition: FieldDefinition,
        value: object,
        entity: Entity,
        *,
        user: FieldUser = None,
    ) -> SchemaField:
        """Validate an AI value on a detached field using the acting user's context."""
        candidate = cls.create_field(deepcopy(dict(definition)), entity)
        if candidate is None:
            raise ValidationError("Field is not available in the target schema.")
        candidate.user = user
        candidate.validate_ai(value)
        if candidate.errors:
            raise ValidationError("; ".join(map(str, candidate.errors)))
        return candidate

    @classmethod
    def validate_type(cls, definition: object) -> bool:
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

def canonicalize_schema(
    value: object,
    *,
    form_type: str | None = None,
    snapshot: bool = False,
    discard_invalid: bool = False,
) -> list[FieldDefinition]:
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


class SchemaFormat(DBProperty[int, "Entity"]):
    """Durable format version for a form or form-history schema."""

    _id = "schema_format"


class Schema(AIMixin, DBProperty[list[FieldDefinition], "Entity"]):
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
    def ai_key(self) -> str:
        return self.id

    def __init__(
        self, *args: object, entity: Entity | None = None, **kwargs: object
    ) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self._fields: dict[str, SchemaField] | None = None
        self._table_fields: dict[str, ColumnField] | None = None
        self._previous: list[FieldDefinition] | Literal[False] = False

    @property
    def value(self) -> list[FieldDefinition]:
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
    def value(self, value: object) -> None:
        self.fields = None
        self._previous = self._read_db_value() or []
        canonical = canonicalize_schema(
            value,
            form_type=getattr(self.entity, "form_type", None),
            snapshot=getattr(self.entity, "entity_kind", None) == "form_history",
        )
        self._write_db_value(canonical)
        if "schema_format" in self.entity.properties:
            cast(SchemaFormat, self.entity.properties.schema_format).value = SCHEMA_FORMAT_VERSION
        else:
            self.entity.db["schema_format"] = SCHEMA_FORMAT_VERSION
        if self.entity.properties.get("filters"):
            cast("Form", self.entity).properties.filters.reset()

    @property
    def previous(self) -> list[FieldDefinition] | Literal[False]:
        return self._previous

    def validate_ai(self, value: object) -> None:
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
                cast("Form", self.entity).set_html_field(field_id, rendered_content)

    @property
    def fields(self) -> dict[str, SchemaField]:
        if self._fields is not None:
            return self._fields

        fields = [SchemaFields.create_field(s, self.entity) for s in self.value]

        self._fields = {f.id: f for f in fields if f is not None}
        return self._fields

    @fields.setter
    def fields(self, value: dict[str, SchemaField] | None) -> None:
        self._fields = value
        self._table_fields = None

    @property
    def table_fields(self) -> dict[str, ColumnField]:
        if self._table_fields is not None:
            return self._table_fields

        table_fields = {}
        for field in self.fields.values():
            if isinstance(field, Table):
                table_fields.update(field.fields)

        self._table_fields = table_fields
        return self._table_fields

    @property
    def html_fields(self) -> list[HTML]:
        return [f for f in self.fields.values() if isinstance(f, HTML)]

    @property
    def required_fields(self) -> list[SchemaField]:
        return [
            p
            for p in self.fields.values()
            if isinstance(p, SchemaProperty) and p.required
        ]
