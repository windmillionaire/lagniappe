from collections.abc import Sequence
from typing import cast

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
# @matrix checkbox : ai-value explicit-false filter-value form-submit import load-save missing-field normalization projection stored-false stored-null unset
class Checkbox(ColumnMixin, AIMixin, FilterMixin, SchemaProperty[bool]):
    """Boolean checkbox field.

    On import, accepts truthy strings ("true", "1", "yes", "y") and
    falsy strings ("false", "0", "no", "n").

    Set:
        value (bool | None): Checked state.

    Get:
        value (bool): True if checked, False otherwise.
        filter_value (bool): True/False (never None).
        ai_value (bool): Same as filter_value; unset answers remain absent.
        db_value (bool): Same as filter_value.
    """

    # Property Attributes
    _label = "Checkbox"
    _icon = "checkbox"

    @property
    def value(self) -> bool | None:
        if not self.is_set:
            return None
        return bool(super().value)

    @value.setter
    def value(self, value: object) -> None:
        if value is None:
            self.unset()
        else:
            self._value = bool(value)

    def validate_submission(self, value: object) -> None:
        self.value = bool(value)

    def validate_ai(self, value: object) -> None:
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
    def sort_value(self) -> bool | None:
        return self.filter_value

    @property
    def column_value(self) -> bool | None:
        return self.filter_value

    # Ingress Attributes
    def validate_import(self, value: object) -> None:
        try:
            if value:
                value = str(cast(Sequence[object], value)[0]).lower().strip()
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
    def ai_value(self) -> bool | None:
        if not self.is_set:
            return None
        return self.filter_value

    @property
    def filter_value(self) -> bool | None:
        if not self.is_set:
            return None
        return bool(self.value)

    @property
    def db_value(self) -> bool | None:
        if not self.is_set:
            return None
        return bool(self.value)

    @db_value.setter
    def db_value(self, value: object) -> None:
        if isinstance(value, bool):
            self.value = value
        else:
            self.unset()
