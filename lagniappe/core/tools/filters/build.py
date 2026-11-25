"""Build JSONPath filter expressions from compiled filter definitions."""

from collections.abc import Sequence
from ...definitions import FilterDefinition

import json
from math import isfinite
import re

from ...definitions import Comparator, FieldType

REGEX_ESCAPE = re.compile(r"([\\.^$*+?{}\[\]|()])")


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


def _regex(value, *, exact=False):
    escaped = REGEX_ESCAPE.sub(r"\\\1", value)
    pattern = f"(?i)^{escaped}$" if exact else f"(?i){escaped}"
    return json.dumps(pattern)


class FilterExpression:
    """Converts a list of filter definitions into a composite JSONPath query string."""

    def __init__(self, definitions: Sequence[FilterDefinition]) -> None:
        self.definitions = definitions

    def build(self, *, ids_only: bool = True) -> str:
        """Convert filter definitions into a single JSONPath query."""
        if not self.definitions:
            raise ValueError("Filter expression requires at least one condition")
        conditions = " && ".join(
            [f"({self._build_single_condition(d)})" for d in self.definitions]
        )

        query = f"$..[?((@.id) && {conditions})]"
        if ids_only:
            query += ".id"
        return query

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
