"""Build JSONPath filter expressions from filter definition objects."""

from ...definitions import Comparator, FieldType
import re

STRING_ESCAPE = re.compile(r"([^a-zA-Z0-9\s])")


# @testable false
# @covered-by lagniappe/core/tools/filters/build.py::FilterExpression.build
# @reason value escaping is part of JSONPath expression generation
def escape(value):
    """Strip non-alphanumeric characters from a string value."""
    if isinstance(value, str):
        return STRING_ESCAPE.sub("", value.strip())
    return value


# @testable false
# @covered-by lagniappe/core/tools/filters/build.py::FilterExpression.build
# @reason builder wrapper delegates source-visible behavior to build()
class FilterExpression:
    """Converts a list of filter definitions into a composite JSONPath query string."""

    def __init__(self, definitions):
        self.definitions = definitions

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_filter_expression_list_contains_accepts_scalar_form_values
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
    # @dimensions string-condition boolean-condition number-condition select-condition entity-condition compound attached-form scalar-list run-results description public document
    def build(self):
        """Convert filter definitions into a single JSONPath query."""
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
        field_path = f"@.{d.field}"

        if d.comparator == Comparator.IS_TRUE:
            return f"{field_path} == true"

        elif d.comparator == Comparator.IS_FALSE:
            return f"{field_path} == false"

        elif d.comparator == Comparator.EQUALS and d.field_type == FieldType.STRING:
            return f"{field_path} =~ '(?i)^{escape(d.value)}$'"

        elif d.comparator == Comparator.EQUALS:
            return f"{field_path} == {d.value}"

        elif d.comparator == Comparator.NOT_EQUALS:
            return f"!({field_path} == '{escape(d.value)}')"

        elif d.comparator == Comparator.GREATER_THAN:
            return f"{field_path} > {d.value}"

        elif d.comparator == Comparator.LESS_THAN:
            return f"{field_path} < {d.value}"

        elif d.comparator == Comparator.GREATER_EQUAL:
            return f"{field_path} >= {d.value}"

        elif d.comparator == Comparator.LESS_EQUAL:
            return f"{field_path} <= {d.value}"

        elif d.comparator == Comparator.BETWEEN:
            return f"({field_path} >= {d.value[0]} && {field_path} <= {d.value[1]})"

        elif d.comparator == Comparator.CONTAINS:
            value = escape(d.value)
            return f"({field_path}[?(@=='{value}')] || {field_path} == '{value}')"

        elif d.comparator == Comparator.IN:
            # Value is in a list of options
            or_conditions = []
            for value in d.value:
                or_conditions.append(f"{field_path} == '{escape(value)}'")
            return f"({' || '.join([f'({cond})' for cond in or_conditions])})"

        elif d.comparator == Comparator.SUBSTRING:
            return f"{field_path} =~ '(?i){escape(d.value)}'"

        elif d.comparator == Comparator.CONTAINS_ANY and d.field_type == FieldType.LIST:
            or_conditions = []
            for value in d.value:
                value = escape(value)
                or_conditions.append(f"{field_path}[?(@=='{value}')]")
                or_conditions.append(f"{field_path} == '{value}'")
            return f"({' || '.join([f'({cond})' for cond in or_conditions])})"

        elif d.comparator == Comparator.EXISTS:
            return f"{field_path} != null"

        elif d.comparator == Comparator.NOT_EXISTS:
            return f"{field_path} == null"
