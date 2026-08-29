from thefuzz import process

from ..definitions import FieldType, FilterOptions, Ordering
from ..mixins import AIMixin, ColumnMixin, FilterMixin
from .base_schema import SchemaProperty


# @testable true
# @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_radio
# @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_single
# @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_multiple
# @matrix radio select : filter-value
class CategoricalElement(ColumnMixin, AIMixin, FilterMixin, SchemaProperty):
    """Base class for fields with a fixed set of choices (select, radio).

    Maps between internal option values and display labels. Supports
    fuzzy matching on import and separator-based splitting for multi-value
    columns.

    Set:
        value (str | list): Selected option value(s). Lists are collapsed
            to a single value when ``multiple`` is False.

    Get:
        value (str | list): Selected option value(s).
        column_value (dict): {label: value} for display.
        sort_value (dict): {value: label} for categorical ordering.
        ai_value (str | list): Option label(s) for AI context.
        choices (dict): {value: label} from the schema options.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._separator = None
        self._fuzzy_match = None

    @property
    def separator(self):
        return self._separator

    @separator.setter
    def separator(self, value):
        self._separator = value

    @property
    def fuzzy_match(self):
        return self._fuzzy_match

    @fuzzy_match.setter
    def fuzzy_match(self, value):
        self._fuzzy_match = value

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_multiple
    # @pair select:multiple
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if isinstance(value, list) and len(value) > 0 and not self.multiple:
            value = value[0]
        elif isinstance(value, str) and self.multiple:
            value = [value]
        SchemaProperty.value.fset(self, value)

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    @property
    def sort_value(self):
        if not self.value:
            return None
        elif isinstance(self.value, list):
            return {v: self.choices[v] for v in self.value if v in self.choices}
        elif self.value in self.choices:
            return {self.value: self.choices[self.value]}
        else:
            return None

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_radio
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_single
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_multiple
    # @matrix radio select : column
    @property
    def column_value(self):
        if not self.value:
            return None
        elif isinstance(self.value, list):
            return {self.choices[v]: v for v in self.value if v in self.choices}
        else:
            return (
                {self.choices[self.value]: self.value}
                if self.value in self.choices
                else None
            )

    # Ingress Attributes
    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_radio
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_multiple
    # @matrix radio select : fuzzy-match import
    def _match_value(self, value):
        if not value:
            return None

        matched = value
        if self.fuzzy_match and self.choices:
            result = process.extractOne(value, self.choices.values())
            if not result or result[1] < 70:
                self.warnings.append(
                    f"No match found for value '{value}' in column '{self.label}' (Closest match: '{result[0]}')"
                )
            elif result[1] < 90:
                self.warnings.append(
                    f"Weak match found for value '{value}' in column '{self.label}': '{result[0]}'"
                )
                matched = result[0]
            else:
                matched = result[0]

        match_value = next((k for k, v in self.choices.items() if v == matched), None)
        return match_value

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_single
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_multiple
    # @matrix select : import multiple separator
    def validate_import(self, values):
        if not values:
            self.value = None
            return

        matched = []

        for value in values:
            imported = (
                [v for v in value.split(self.separator)] if self.separator else [value]
            )
            for v in imported:
                matched.append(self._match_value(v.strip()))

        if self.multiple:
            self.value = [s for s in matched if s]
        elif matched:
            self.value = max(matched, key=matched.count)
        else:
            self.value = None

    # AI Attributes
    def validate_ai(self, value):
        values = value if isinstance(value, list) else [value]
        matches = [v for v in values if v in self.choices]
        if not matches:
            matches = [k for k, v in self.choices.items() if v in values]
        self.value = matches

    # @testable true
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_radio
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_single
    # @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_multiple
    # @matrix radio select : ai-value
    @property
    def ai_value(self):
        if isinstance(self.value, list):
            return [self.choices[v] for v in self.value]
        elif self.value:
            return self.choices[self.value]

        return None

    # Filter Attributes
    _placeholder = "select options..."
    _is_categorical = True

    @property
    def choices(self):
        if getattr(self, "_choices", None):
            return self._choices

        self._choices = {o["value"]: o["label"] for o in self.get("options", [])}
        return self._choices

    @property
    def field_options(self):
        return FilterOptions.LIST.value

    @property
    def field_type(self):
        return FieldType.LIST if self.multiple else FieldType.STRING

    # @testable true
    # @tests tests_unit/test_012b_form_conditions.py::test_form_select_filters
    # @matrix select : condition-definition multiple select
    def filter_details(self, condition):
        """Return display details with option labels."""
        details = super().filter_details(condition)
        labels = [self.choices.get(v, v) for v in condition.value_list]
        if len(labels) > 1:
            details["text"] = "is any of"
            details["or"] = labels
        elif len(labels) == 1:
            details["text"] = "is"
            details["value"] = labels[0]
        return details


class Radio(CategoricalElement):
    """Single-select radio button field. Always stores one value."""

    _icon = "radio"


# @testable true
# @tests tests_unit/test_003b_submission_links_and_select.py::test_submission_select_multiple
# @matrix select : multiple separator
class Select(CategoricalElement):
    """Dropdown select field. Supports single or multi-select via ``multiple``."""

    _icon = "select"
