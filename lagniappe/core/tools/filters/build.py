"""Build JSONPath filter expressions from compiled filter definitions."""

import json
from math import isfinite
import re

from ...definitions import Comparator, FieldType

REGEX_ESCAPE = re.compile(r"([\\.^$*+?{}\[\]|()])")


# @testable false
# @covered-by lagniappe/core/tools/filters/build.py::FilterExpression.build
# @reason scalar encoding is exercised through complete JSONPath expressions
def _literal(value):
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        if not isfinite(value):
            raise ValueError("Filter expression requires finite numbers")
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise ValueError("Filter expression requires scalar values")


# @testable false
# @covered-by lagniappe/core/tools/filters/build.py::FilterExpression.build
# @reason regex escaping is exercised through complete JSONPath expressions
def _regex(value, *, exact=False):
    escaped = REGEX_ESCAPE.sub(r"\\\1", value)
    pattern = f"(?i)^{escaped}$" if exact else f"(?i){escaped}"
    return json.dumps(pattern)


# @testable false
# @covered-by lagniappe/core/tools/filters/build.py::FilterExpression.build
# @reason builder wrapper delegates source-visible behavior to build()
class FilterExpression:
    """Converts a list of filter definitions into a composite JSONPath query string."""

    def __init__(self, definitions):
        self.definitions = definitions

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_filter_expression_list_contains_accepts_scalar_form_values
    # @tests tests_unit/test_011_filters.py::test_filter_expression_encodes_field_names_and_literal_regex_values
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_multiple_conditions
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_text_condition
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_number_condition
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_checkbox_condition
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_attached_form_select_condition
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_name
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_page_description
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_additional_category
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_public_page
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_document_asset
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_text_condition
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_number_condition
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_checkbox_condition
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_by_attached_form_select_condition
    # @features filters
    # @dimensions string-condition boolean-condition number-condition select-condition entity-condition compound attached-form scalar-list run-results description public document jsonpath escaping punctuation regex-literal field-name
    def build(self):
        """Convert filter definitions into a single JSONPath query."""
        if not self.definitions:
            raise ValueError("Filter expression requires at least one condition")
        conditions = " && ".join(
            [f"({self._build_single_condition(d)})" for d in self.definitions]
        )

        query = f"$..[?((@.id) && {conditions})].id"
        return query

    # @testable false
    # @covered-by lagniappe/core/tools/filters/build.py::FilterExpression.build
    # @reason per-condition fragments are covered through composite filter expressions
    def _build_single_condition(self, d):
        """Build a single JSONPath condition from a filter definition."""
        field_path = f"@[{json.dumps(d.field)}]"

        if d.comparator == Comparator.IS_TRUE:
            return f"{field_path} == true"

        elif d.comparator == Comparator.IS_FALSE:
            return f"{field_path} == false"

        elif d.comparator == Comparator.EQUALS and d.field_type == FieldType.STRING:
            return f"{field_path} =~ {_regex(d.value, exact=True)}"

        elif d.comparator == Comparator.EQUALS:
            return f"{field_path} == {_literal(d.value)}"

        elif d.comparator == Comparator.GREATER_THAN:
            return f"{field_path} > {_literal(d.value)}"

        elif d.comparator == Comparator.LESS_THAN:
            return f"{field_path} < {_literal(d.value)}"

        elif d.comparator == Comparator.GREATER_EQUAL:
            return f"{field_path} >= {_literal(d.value)}"

        elif d.comparator == Comparator.LESS_EQUAL:
            return f"{field_path} <= {_literal(d.value)}"

        elif d.comparator == Comparator.BETWEEN:
            return (
                f"({field_path} >= {_literal(d.value[0])} && "
                f"{field_path} <= {_literal(d.value[1])})"
            )

        elif d.comparator == Comparator.CONTAINS:
            value = _literal(d.value)
            return f"({field_path}[?(@=={value})] || {field_path} == {value})"

        elif d.comparator == Comparator.IN:
            conditions = [f"{field_path} == {_literal(value)}" for value in d.value]
            return f"({' || '.join([f'({item})' for item in conditions])})"

        elif d.comparator == Comparator.SUBSTRING:
            return f"{field_path} =~ {_regex(d.value)}"

        elif d.comparator == Comparator.CONTAINS_ANY and d.field_type == FieldType.LIST:
            or_conditions = []
            for value in d.value:
                literal = _literal(value)
                or_conditions.append(f"{field_path}[?(@=={literal})]")
                or_conditions.append(f"{field_path} == {literal}")
            return f"({' || '.join([f'({cond})' for cond in or_conditions])})"

        raise ValueError(f"Unsupported filter comparator: {d.comparator.value}")
