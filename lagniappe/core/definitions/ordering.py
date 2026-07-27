"""Column ordering definitions."""

from enum import Enum


# @testable infrastructure
# @covered-by lagniappe/core/mixins/column.py::ColumnMixin.ordering
# @covered-by lagniappe/core/properties/base_columns.py::Columns.columns
class Ordering(Enum):
    """Column sort strategies. Set via ColumnMixin._ordering."""

    LEXICAL = "lexical"
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    EXISTS = "exists"
    BOOLEAN = "boolean"
