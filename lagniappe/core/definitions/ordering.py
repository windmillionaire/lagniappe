"""Column ordering definitions."""

from enum import Enum


class Ordering(Enum):
    """Column sort strategies. Set via ColumnMixin._ordering."""

    LEXICAL = "lexical"
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    EXISTS = "exists"
    BOOLEAN = "boolean"
