from collections.abc import Iterable
from enum import Enum
from typing import TYPE_CHECKING, Protocol, Self, cast

from ..definitions import FieldType
from .base_submission import SubmissionProperty
from .form_checkbox import Checkbox
from .form_inputs import (
    DateInput,
    EmailInput,
    NumberInput,
    TelInput,
    TextInput,
    TimeInput,
)
from .form_links import Link

if TYPE_CHECKING:
    from .form_table import Table


class ImportSettings(Protocol):
    @property
    def separator(self) -> str | None: ...

    def fuzzy_match(self, field_id: str) -> bool: ...


# @testable false
# @covered-by lagniappe/core/properties/row_submission.py::TableColumnFields.create_field
# @covered-by lagniappe/core/properties/row_submission.py::TableColumnFields.validate_type
# @reason small enum-member normalization helper owned by table column validation
def _member_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value.upper()


type ColumnField = Checkbox | DateInput | EmailInput | Link | NumberInput | TelInput | TextInput | TimeInput


class TableColumnFields(Enum):
    """Registry of field types allowed in table columns."""

    TEXT = TextInput
    DATE = DateInput
    TIME = TimeInput
    NUMBER = NumberInput
    EMAIL = EmailInput
    TEL = TelInput
    CHECKBOX = Checkbox
    LINK = Link

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_table_fields
    # @tests tests_unit/test_004e_submission_behavior.py::test_submission_search_value_merges_table_column_labels
    # @matrix form-table : search-value table-fields timezone
    @classmethod
    def create_field(cls, definition: object, table: Table) -> ColumnField | None:
        """Create a field instance from a column definition dict."""
        if not isinstance(definition, dict):
            return None
        field_type = definition.get("input") or definition.get("type")
        name = _member_name(field_type)
        if name is None or name not in cls.__members__:
            return None

        field = cls[name].value(definition, entity=table.entity, user=table.user)
        field.icon = "column"
        field.label = f"[{table.label}] {field.label}"
        field.field_type = FieldType.LIST
        return field

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_table_filters_bad_columns
    # @matrix form-schema form-table : columns validation
    @classmethod
    def validate_type(cls, definition: object) -> bool:
        if not isinstance(definition, dict):
            return False
        schema_type = definition.get("type")
        if schema_type == "input":
            input_type = definition.get("input")
            return _member_name(input_type) in cls.__members__
        return _member_name(schema_type) in cls.__members__


# @testable false
# @covered-by lagniappe/core/properties/row_submission.py::RowSubmission.validate_import
# @covered-by lagniappe/core/properties/row_submission.py::RowSubmission.validate_ai
# @covered-by lagniappe/core/properties/row_submission.py::RowSubmission.validate_submission
# @reason row behavior is owned by import, AI, and form-submission constructors
class RowSubmission(SubmissionProperty):
    """A single row within a Table field's submission.

    Fields are built from the table's column definitions (via
    TableColumnFields). Provides class methods for validating rows
    from different input sources (import, AI, form submission).

    Get:
        fields (dict): {field_id: field instance} for this row's columns.
        db_value (dict): {field_id: value}, excluding None values.
    """

    def __init__(
        self, table: Table, row: dict[str, object] | str | None = None
    ) -> None:
        self.table = table
        self.user = table.user
        self._set_submission(row)

    @property
    def fields(self) -> dict[str, ColumnField]:
        if getattr(self, "_fields", None):
            return self._fields

        fields = {
            cast(str, c["id"]): TableColumnFields.create_field(c, self.table)
            for c in self.table.columns
        }
        self._fields = {k: v for k, v in fields.items() if v is not None}

        for field_id, field in self._fields.items():
            if field_id in self.value:
                field.db_value = self.value[field_id]
            else:
                field.unset()

        return self._fields

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_import_single_row
    # @tests tests_unit/test_003e_tables.py::test_table_import_multiple_rows
    # @tests tests_unit/test_003e_tables.py::test_table_import_mixed_column_types
    # @pair form-table:import
    @classmethod
    def validate_import(
        cls,
        table: Table,
        list_of_values: Iterable[object],
        import_process: ImportSettings | None = None,
    ) -> Self:
        row = cls(table)
        for field_id, value in zip(row.fields.keys(), list_of_values, strict=False):
            field = row.fields[field_id]
            field.reset()
            if import_process and isinstance(field, Link):
                field.fuzzy_match = import_process.fuzzy_match(field_id)
            field.validate_import(value)
        return row

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_ai_multiple_rows
    # @matrix form-table : ai-value multiple-rows
    @classmethod
    def validate_ai(cls, table: Table, values: dict[str, object]) -> Self:
        row = cls(table)
        for field_id, field in row.fields.items():
            field.reset()
            field.validate_ai(values.get(field_id))
        return row

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_text_email_checkbox
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_external_link_column
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_internal_link_column
    # @matrix form-table link : row-submission
    @classmethod
    def validate_submission(cls, table: Table, values: dict[str, object]) -> Self:
        row = cls(table)
        for field_id, field in row.fields.items():
            field.reset()
            value = values.get(field_id)
            if isinstance(value, list) and not field.multiple and value:
                value = value[0]
            field.validate_submission(value)
        return row
