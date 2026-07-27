from enum import Enum

from ..definitions import FieldType
from .base_submission import SubmissionProperty
from .form_inputs import (
    DateInput,
    EmailInput,
    NumberInput,
    TelInput,
    TextInput,
    TimeInput,
)
from .form_links import Link
from .form_checkbox import Checkbox


# @testable false
# @covered-by lagniappe/core/properties/row_submission.py::TableColumnFields.create_field
# @covered-by lagniappe/core/properties/row_submission.py::TableColumnFields.validate_type
# @reason small enum-member normalization helper owned by table column validation
def _member_name(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value.upper()


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
    # @features form-table
    # @dimensions table-fields, search-value
    @classmethod
    def create_field(cls, definition, table):
        """Create a field instance from a column definition dict."""
        if not isinstance(definition, dict):
            return None
        field_type = definition.get("input") or definition.get("type")
        name = _member_name(field_type)
        if name not in cls.__members__:
            return None

        field = cls[name].value(definition, entity=table.entity)
        field.icon = "column"
        field.label = f"[{table.label}] {field.label}"
        field.field_type = FieldType.LIST
        return field

    # @testable true
    # @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_table_filters_bad_columns
    # @features form-schema, form-table
    # @dimensions validation, columns
    @classmethod
    def validate_type(cls, definition):
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

    def __init__(self, table, row=None):
        self.table = table
        self.user = table.user
        SubmissionProperty.value.fset(self, row)

    @property
    def fields(self):
        if getattr(self, "_fields", None):
            return self._fields

        fields = {
            c["id"]: TableColumnFields.create_field(c, self.table)
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
    # @features form-table
    # @dimensions import
    @classmethod
    def validate_import(cls, table, list_of_values, import_process=None):
        row = cls(table)
        for field_id, value in zip(row.fields.keys(), list_of_values):
            field = row.fields[field_id]
            field.reset()
            if import_process and hasattr(field, "fuzzy_match"):
                field.fuzzy_match = import_process.fuzzy_match(field_id)
                if hasattr(field, "separator"):
                    field.separator = import_process.separator
            field.validate_import(value)
        return row

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_ai_multiple_rows
    # @features form-table
    # @dimensions ai-value, multiple-rows
    @classmethod
    def validate_ai(cls, table, values):
        row = cls(table)
        for field_id, field in row.fields.items():
            field.reset()
            field.validate_ai(values.get(field_id, None))
        return row

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_text_email_checkbox
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_external_link_column
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_internal_link_column
    # @features form-table
    # @dimensions row-submission
    @classmethod
    def validate_submission(cls, table, values):
        row = cls(table)
        for field_id, field in row.fields.items():
            field.reset()
            value = values.get(field_id)
            if isinstance(value, list) and not field.multiple and value:
                value = value[0]
            field.validate_submission(value)
        return row
