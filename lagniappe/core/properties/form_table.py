import json

from ..definitions import Ordering
from ..mixins import AIMixin, FilterMixin, ColumnMixin, SearchMixin
from .base_submission import _is_blank_value
from .base_schema import SchemaProperty
from .form_links import Link
from .row_submission import RowSubmission, TableColumnFields


# @testable false
# @covered-by lagniappe/core/properties/form_table.py::Table.value
# @covered-by lagniappe/core/properties/form_table.py::Table.fields
# @covered-by lagniappe/core/properties/form_table.py::Table.links
# @covered-by lagniappe/core/properties/form_table.py::Table.validate_import
# @covered-by lagniappe/core/properties/form_table.py::Table.validate_row_submission
# @covered-by lagniappe/core/properties/form_table.py::Table.ai_value
# @covered-by lagniappe/core/properties/form_table.py::Table.filter_value
# @covered-by lagniappe/core/properties/form_table.py::Table.search_value
# @reason table behavior is owned by row construction and projection properties
class Table(AIMixin, FilterMixin, ColumnMixin, SearchMixin, SchemaProperty):
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
        ai_value (dict): {field_id: [AI values across all rows]}.
        db_value (dict | None): {rows: [row dicts]}, or None if empty.
    """

    _icon = "table"

    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, entity=entity, **kwargs)
        self._fields = None
        self._rows = None
        self._search_fields = None
        self._import_process = None

    # Property Attributes
    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_form_single_row
    # @tests tests_unit/test_003e_tables.py::test_table_form_empty
    # @tests tests_unit/test_003e_tables.py::test_table_form_mixed_column_types
    # @features form-table
    # @dimensions form-submission, db-value, empty, mixed-columns
    @property
    def value(self):
        if self.is_set:
            return self._value

        self._value = {"rows": [r.db_value for r in self.rows]}
        return self._value

    @value.setter
    def value(self, value):
        value = value or {}
        rows = value if isinstance(value, list) else value.get("rows", [])
        self._rows = [RowSubmission(self, row) for row in rows]
        if self._rows:
            self._value = {"rows": [r.db_value for r in self._rows]}
        else:
            self.unset()

    @property
    def columns(self):
        return self.get("columns", [])

    @property
    def rows(self):
        if self._rows is not None:
            return self._rows

        self._rows = []
        return self._rows

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_table_fields
    # @features form-table
    # @dimensions table-fields
    @property
    def fields(self):
        if self._fields is not None:
            return self._fields

        fields = [TableColumnFields.create_field(c, self) for c in self.columns]

        self._fields = {f.id: f for f in fields if f is not None}
        return self._fields

    # @testable true
    # @tests tests_unit/test_004c_form_submission_integration.py::test_submission_links_internal_top_level_and_table_row
    # @features form-table
    # @dimensions links, internal, row-submission
    @property
    def links(self):
        return [
            f
            for r in self.rows
            for f in r.fields.values()
            if isinstance(f, Link) and f.is_entity_valued
        ]

    def reset(self):
        super().reset()
        self._rows = None

    def set_import_process(self, import_process):
        self._import_process = import_process

    # Ingress Attributes
    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_import_single_row
    # @tests tests_unit/test_003e_tables.py::test_table_import_multiple_rows
    # @tests tests_unit/test_003e_tables.py::test_table_import_mixed_column_types
    # @tests tests_unit/test_003e_tables.py::test_table_import_row_length_mismatch
    # @tests tests_unit/test_003e_tables.py::test_table_validate_import_row_length_mismatch_raises_value_error
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_table_internal_link_exact_match
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_table_internal_link_fuzzy_match_warning
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_table_internal_link_no_match_records_error
    # @features form-table
    # @dimensions import, validation, internal, fuzzy-match, no-match
    def validate_import(self, rows):
        # rows should be a list of lists, each list containing the values for a single row
        # rows should be in the same order as the column fields
        self.reset()
        if not rows:
            return
        for row in rows:
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
    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_ai_multiple_rows
    # @features form-table
    # @dimensions ai-value, multiple-rows
    def validate_ai(self, ai_submission):
        self.reset()
        if not ai_submission:
            return
        # ai_submission should be a dict with a "rows" key that contains a list of submission values for each row
        # each row should be a dict with the field ids as keys and the submission values as values
        for row in ai_submission.get("rows", []):
            self.rows.append(RowSubmission.validate_ai(self, row))
        if self.rows:
            self._value = {"rows": [r.db_value for r in self.rows]}
        else:
            self.unset()

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_ai_multiple_rows
    # @tests tests_unit/test_003e_tables.py::test_table_import_multiple_rows
    # @features form-table
    # @dimensions ai-value, multiple-rows
    @property
    def ai_value(self):
        rows = []
        for row in self.rows:
            row_dict = {}
            for field in self.fields.values():
                value = row.fields[field.id].ai_value
                if value:
                    row_dict[field.get("title")] = value
            if row_dict:
                rows.append(row_dict)
        return rows or None

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_text_email_checkbox
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_external_link_column
    # @tests tests_unit/test_003e_tables.py::test_table_row_submission_internal_link_column
    # @features form-table
    # @dimensions row-submission
    def validate_row_submission(self, values):
        # values are sent from the frontend as a single row submission
        # they are returned and the form is submitted with a complete "rows" list
        new_row = RowSubmission.validate_submission(self, values)
        return {field_id: f.form_value for field_id, f in new_row.fields.items()}

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_validate_submission_invalid_json
    # @features form-table
    # @dimensions form-submission, validation
    def validate_submission(self, value):
        # values are sent from the frontend as a complete "rows" list from a json-formatted hidden input
        # the rows have already been validated, so we can just add them to the list
        value = json.loads(value) if isinstance(value, str) else value
        self.value = value

    # Column Attributes
    _ordering = Ordering.EXISTS

    @property
    def sort_value(self):
        return True if self.value else False

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_form_single_row
    # @tests tests_unit/test_003e_tables.py::test_table_form_empty
    # @tests tests_unit/test_003e_tables.py::test_table_form_mixed_column_types
    # @features form-table
    # @dimensions column, empty, mixed-columns
    @property
    def column_value(self):
        num_rows = len(self.value.get("rows", []))
        if not num_rows:
            return None
        return {"num_rows": num_rows}

    # Filter Attributes
    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_import_multiple_rows
    # @features form-table
    # @dimensions filter-value, multiple-rows
    @property
    def filter_value(self):
        # returns a dict with the field ids as keys and a list of filter values for each row
        filter_values = {
            field_id: [r.fields[field_id].filter_value for r in self.rows]
            for field_id in self.fields.keys()
        }
        return {k: v for k, v in filter_values.items() if v}

    # Search Attributes
    @property
    def search_fields(self):
        if self._search_fields is not None:
            return self._search_fields

        self._search_fields = [
            f for f in self.fields.values() if isinstance(f, SearchMixin)
        ]
        return self._search_fields

    @property
    def search_key(self):
        return [key for key, _value in self._search_pairs()]

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_form_mixed_column_types
    # @tests tests_unit/test_004e_submission_behavior.py::test_submission_search_value_merges_table_column_labels
    # @tests tests_unit/test_004e_submission_behavior.py::test_table_search_keys_match_multiple_row_values
    # @features form-table
    # @dimensions search-value, multiple-rows
    @property
    def search_value(self):
        return [value for _key, value in self._search_pairs()]

    def _search_pairs(self):
        pairs = []
        for row in self.rows:
            for field in self.search_fields:
                value = row.fields[field.id].search_value
                if value is not None and value != "":
                    pairs.append((field.search_key, value))
        return pairs

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_form_empty
    # @features form-table
    # @dimensions form-submission, empty
    @property
    def form_value(self):
        return {"rows": [r.form_value for r in self.rows]} if self.rows else None

    # @testable true
    # @tests tests_unit/test_003e_tables.py::test_table_form_single_row
    # @features form-table
    # @dimensions db-value
    @property
    def db_value(self):
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
    def db_value(self, value):
        value = value or {}
        rows = value if isinstance(value, list) else value.get("rows", [])
        self._rows = [RowSubmission(self, row) for row in rows]
        if self._rows:
            self._value = {"rows": [r.db_value for r in self._rows]}
        else:
            self.unset()
