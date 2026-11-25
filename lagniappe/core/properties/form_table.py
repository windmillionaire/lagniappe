import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, TypedDict, cast

from ..definitions import Ordering
from ..mixins import AIMixin, ColumnMixin, FilterMixin, SearchMixin
from .base_schema import FieldDefinition, SchemaProperty, SchemaSource
from .base_submission import _is_blank_value
from .form_inputs import TextInput
from .form_links import Link
from .row_submission import (
    ColumnField,
    ImportSettings,
    RowSubmission,
    TableColumnFields,
)

if TYPE_CHECKING:
    from ..entities.entity import Entity


class TableValue(TypedDict):
    rows: list[dict[str, object]]


def validate_ai_table(
    value: object, columns: list[FieldDefinition] | None = None
) -> None:
    """Check the table envelope and exact column keys before consuming AI values."""
    if value is None:
        return
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        raise ValueError('Table value must be an object with a "rows" array.')
    allowed = {column["id"] for column in columns} if columns is not None else None
    for index, row in enumerate(value["rows"], 1):
        if not isinstance(row, dict):
            raise ValueError(f"Table row {index} must be an object keyed by column ids, not column headings.")
        if allowed is not None and set(row) - allowed:
            raise ValueError(f"Table row {index} contains unknown column ids; use the exact ids from the form schema.")


class Table(AIMixin, FilterMixin, ColumnMixin, SearchMixin, SchemaProperty[TableValue]):
    """Inline table field with column definitions and row submissions.

    Each column is a TableColumnField (TextInput, DateInput, etc.).
    Rows are managed as RowSubmission instances.

    Set:
        value (list | dict): List of row dicts, or {rows: [...]}.

    Get:
        value (dict): {rows: [row submission values]}.
        fields (dict): {field_id: TableColumnField} from column definitions.
        rows (list[RowSubmission]): Validated row submission objects.
        filter_value (dict): {field_id: [values across all rows]}.
        ai_value (dict): {rows: [{column_id: typed AI value}]}.
        db_value (dict | None): {rows: [row dicts]}, or None if empty.
    """

    _icon = "table"

    def __init__(
        self, *args: SchemaSource, entity: Entity | None = None, **kwargs: object
    ) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self._fields: dict[str, ColumnField] | None = None
        self._rows: list[RowSubmission] | None = None
        self._search_fields: list[TextInput] | None = None
        self._import_process: ImportSettings | None = None

    # Property Attributes
    @property
    def value(self) -> TableValue:
        if self.is_set:
            return cast(TableValue, self._value)

        self._value = {"rows": [r.db_value for r in self.rows]}
        return cast(TableValue, self._value)

    @value.setter
    def value(self, value: object) -> None:
        value = cast(TableValue | list[dict[str, object]], value or {})
        rows = value if isinstance(value, list) else value.get("rows", [])
        self._rows = [RowSubmission(self, row) for row in rows]
        if self._rows:
            self._value = {"rows": [r.db_value for r in self._rows]}
        else:
            self.unset()

    @property
    def columns(self) -> list[FieldDefinition]:
        return cast(list[FieldDefinition], self.get("columns", []))

    @property
    def rows(self) -> list[RowSubmission]:
        if self._rows is not None:
            return self._rows

        self._rows = []
        return self._rows

    @property
    def fields(self) -> dict[str, ColumnField]:
        if self._fields is not None:
            return self._fields

        fields = [TableColumnFields.create_field(c, self) for c in self.columns]

        self._fields = {f.id: f for f in fields if f is not None}
        return self._fields

    @property
    def links(self) -> list[Link]:
        return [
            f
            for r in self.rows
            for f in r.fields.values()
            if isinstance(f, Link) and f.is_entity_valued
        ]

    def reset(self) -> None:
        super().reset()
        self._rows = None

    def set_import_process(self, import_process: ImportSettings | None) -> None:
        self._import_process = import_process

    # Ingress Attributes
    def validate_import(self, rows: object) -> None:  # pyright: ignore[reportIncompatibleMethodOverride] -- preserve the existing keyword for this table validator.
        # rows should be a list of lists, each list containing the values for a single row
        # rows should be in the same order as the column fields
        self.reset()
        if not rows:
            return
        for row in cast(Iterable[list[object]], rows):
            if len(row) != len(self.fields):
                raise ValueError("Row length does not match number of columns")
            row_submission = RowSubmission.validate_import(
                self, row, self._import_process
            )
            for field in row_submission.fields.values():
                self.warnings.extend(field.warnings)
                self.errors.extend(field.errors)
            if row_submission.db_value:
                self.rows.append(row_submission)
        if self.rows:
            self._value = {"rows": [r.db_value for r in self.rows]}
        else:
            self.unset()

    # AI Attributes
    def validate_ai(self, ai_submission: object) -> None:  # pyright: ignore[reportIncompatibleMethodOverride] -- preserve the existing keyword for this table validator.
        validate_ai_table(ai_submission, self.columns)
        self.reset()
        if not ai_submission:
            return
        # ai_submission should be a dict with a "rows" key that contains a list of submission values for each row
        # each row should be a dict with the field ids as keys and the submission values as values
        for row in cast(TableValue, ai_submission).get("rows", []):
            row_submission = RowSubmission.validate_ai(self, row)
            for field in row_submission.fields.values():
                self.errors.extend(field.errors)
                self.warnings.extend(field.warnings)
            self.rows.append(row_submission)
        if self.rows:
            self._value = {"rows": [r.db_value for r in self.rows]}
        else:
            self.unset()

    @property
    def ai_value(self) -> TableValue | None:
        rows = []
        for row in self.rows:
            row_dict = {}
            for column_id, field in row.fields.items():
                field.user = self.user
                if isinstance(field, AIMixin) and field.is_set:
                    value = field.ai_value
                    if value is not None:
                        row_dict[column_id] = value
            rows.append(row_dict)
        return {"rows": rows} if rows else None

    def validate_row_submission(self, values: dict[str, object]) -> dict[str, object]:
        # values are sent from the frontend as a single row submission
        # they are returned and the form is submitted with a complete "rows" list
        new_row = RowSubmission.validate_submission(self, values)
        return {field_id: f.form_value for field_id, f in new_row.fields.items()}

    def validate_submission(self, value: object) -> None:
        # values are sent from the frontend as a complete "rows" list from a json-formatted hidden input
        # the rows have already been validated, so we can just add them to the list
        value = json.loads(value) if isinstance(value, str) else value
        self.value = value

    # Column Attributes
    _ordering = Ordering.EXISTS

    @property
    def sort_value(self) -> bool:
        return bool(self.value)

    @property
    def column_value(self) -> dict[str, int] | None:
        num_rows = len(self.value.get("rows", []))
        if not num_rows:
            return None
        return {"num_rows": num_rows}

    # Filter Attributes
    @property
    def filter_value(self) -> dict[str, list[object]]:
        # returns a dict with the field ids as keys and a list of filter values for each row
        filter_values = {
            field_id: [r.fields[field_id].filter_value for r in self.rows]
            for field_id in self.fields
        }
        return {k: v for k, v in filter_values.items() if v}

    # Search Attributes
    @property
    def search_fields(self) -> list[TextInput]:
        if self._search_fields is not None:
            return self._search_fields

        self._search_fields = [
            f for f in self.fields.values() if isinstance(f, SearchMixin)
        ]
        return self._search_fields

    @property
    def search_key(self) -> list[str | None]:
        return [key for key, _value in self._search_pairs()]

    @property
    def search_value(self) -> list[object]:
        return [value for _key, value in self._search_pairs()]

    def _search_pairs(self) -> list[tuple[str | None, object]]:
        pairs = []
        for row in self.rows:
            for field in self.search_fields:
                cell = row.fields[field.id]
                if not isinstance(cell, SearchMixin):
                    continue
                value = cell.search_value
                if value is not None and value != "":
                    pairs.append((field.search_key, value))
        return pairs

    @property
    def form_value(self) -> TableValue | None:
        return {"rows": [r.form_value for r in self.rows]} if self.rows else None

    @property
    def db_value(self) -> TableValue | None:
        rows = []
        for row in self.rows:
            row_value = {
                k: v
                for k, v in row.db_value.items()
                if not _is_blank_value(v)
            }
            if row_value:
                rows.append(row_value)
        return {"rows": rows} if rows else None

    @db_value.setter
    def db_value(self, value: object) -> None:
        value = cast(TableValue | list[dict[str, object]], value or {})
        rows = value if isinstance(value, list) else value.get("rows", [])
        self._rows = [RowSubmission(self, row) for row in rows]
        if self._rows:
            self._value = {"rows": [r.db_value for r in self._rows]}
        else:
            self.unset()
