from ..definitions import FieldType, FilterOptions, Ordering
from ..exceptions import ValidationError
from ..mixins import AIMixin, ColumnMixin, FilterMixin
from .base_schema import SchemaProperty


# @testable true
# @tests tests_unit/test_003a_submission_basic.py::test_submission_checkbox
# @tests tests_unit/test_004e_submission_behavior.py::test_missing_stored_checkbox_is_unset_and_omitted
# @tests tests_unit/test_004e_submission_behavior.py::test_full_form_submit_missing_checkbox_persists_explicit_false
# @tests tests_unit/test_004e_submission_behavior.py::test_stored_explicit_checkbox_false_survives_load_save
# @tests tests_unit/test_004e_submission_behavior.py::test_stored_null_checkbox_normalizes_away_on_resave
# @features checkbox
# @dimensions ai-value, filter-value, import, missing-field, unset, projection, form-submit, explicit-false, stored-false, load-save, stored-null, normalization
class Checkbox(ColumnMixin, AIMixin, FilterMixin, SchemaProperty):
    """Boolean checkbox field.

    On import, accepts truthy strings ("true", "1", "yes", "y") and
    falsy strings ("false", "0", "no", "n").

    Set:
        value (bool | None): Checked state.

    Get:
        value (bool): True if checked, False otherwise.
        filter_value (bool): True/False (never None).
        ai_value (str): String representation of filter_value.
        db_value (bool): Same as filter_value.
    """

    # Property Attributes
    _label = "Checkbox"
    _icon = "checkbox"

    @property
    def value(self):
        if not self.is_set:
            return None
        return bool(super().value)

    @value.setter
    def value(self, value):
        if value is None:
            self.unset()
        else:
            SchemaProperty.value.fset(self, bool(value))

    def validate_submission(self, value):
        self.value = bool(value)

    def validate_ai(self, value):
        self.value = bool(value)

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.CHECKBOX.value
    _field_text = "is"
    _default = "IS_TRUE"

    # Column Attributes
    _ordering = Ordering.BOOLEAN
    _editable = True

    @property
    def sort_value(self):
        return self.filter_value

    @property
    def column_value(self):
        return self.filter_value

    # Ingress Attributes
    def validate_import(self, value):
        try:
            if value:
                value = str(value[0]).lower().strip()
                if value in ["false", "0", "no", "n"]:
                    self.value = False
                elif value:
                    self.value = True
                else:
                    raise ValueError
            else:
                self.value = False
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError):
            self.errors.append(
                f"Invalid boolean value '{value}' in column '({self.label})'"
            )

    # AI Attributes
    @property
    def ai_value(self):
        if not self.is_set:
            return None
        return str(self.filter_value)

    @property
    def filter_value(self):
        if not self.is_set:
            return None
        return bool(self.value)

    @property
    def db_value(self):
        if not self.is_set:
            return None
        return bool(self.value)

    @db_value.setter
    def db_value(self, value):
        if isinstance(value, bool):
            self.value = value
        else:
            self.unset()
