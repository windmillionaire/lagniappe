"""Validated, read-only filter queries for AI workspace tools."""

from datetime import datetime, time, timezone
from math import isfinite
from types import SimpleNamespace

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Action,
    Comparator,
    Fetch,
    FieldType,
    FilterDefinition,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import dates

from .cache import FilterCache


DEFAULT_LIMIT = 25
MAX_LIMIT = 100
SUPPORTED_PARENT_KINDS = frozenset({"category", "project"})
SUPPORTED_COMPARATORS = frozenset(
    {
        Comparator.IS_TRUE,
        Comparator.IS_FALSE,
        Comparator.EQUALS,
        Comparator.GREATER_THAN,
        Comparator.LESS_THAN,
        Comparator.GREATER_EQUAL,
        Comparator.LESS_EQUAL,
        Comparator.CONTAINS,
        Comparator.IN,
        Comparator.SUBSTRING,
        Comparator.CONTAINS_ANY,
        Comparator.BETWEEN,
    }
)
SORTS = frozenset(
    {
        "modified_desc",
        "modified_asc",
        "due_date_asc",
        "due_date_desc",
        "name_asc",
    }
)


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::describe_filter_fields
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason internal catalog records are observed through public schema and compilation behavior
class _FilterField:
    """Internal field metadata used while describing and compiling filters."""

    def __init__(self, source, field, allowed_values=None):
        self.source = source
        self.field = field
        self.allowed_values = allowed_values

    @property
    def key(self):
        return (self.source.hash, self.field.filter_key)


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_describe_filter_fields_exposes_parent_relations_and_form_fields
# @tests tests_unit/test_015c_ai_filter_query.py::test_describe_filter_fields_uses_real_project_and_form_filter_surfaces
# @features ai-filter
# @dimensions schema permissions integration
def describe_filter_fields(parent, user):
    """Describe filterable fields visible to ``user`` under a project/category."""
    _validate_parent(parent, user)
    catalog = _field_catalog(parent, user)
    fields = [_field_description(entry) for entry in catalog.values()]
    fields.sort(
        key=lambda item: (
            item["source"]["kind"] != parent.kind,
            (item["source"]["name"] or "").casefold(),
            item["label"].casefold(),
        )
    )
    return {
        "parent": _entity_reference(parent),
        "result_kind": "task" if parent.kind == "project" else "page",
        "condition_logic": "all",
        "fields": fields,
    }


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_compile_filter_definitions_normalizes_dates_numbers_and_booleans
# @tests tests_unit/test_015c_ai_filter_query.py::test_compile_filter_definitions_rejects_unknown_fields_comparators_and_values
# @features ai-filter
# @dimensions compilation validation permissions
def compile_filter_definitions(parent, conditions, user):
    """Validate AI condition DTOs and build trusted ``FilterDefinition`` objects."""
    _validate_parent(parent, user)
    if not isinstance(conditions, list) or not conditions:
        raise exceptions.ValidationError("Add at least one filter condition.")
    if len(conditions) > 12:
        raise exceptions.ValidationError("A filter may contain at most 12 conditions.")

    catalog = _field_catalog(parent, user)
    definitions = []
    form_scopes = set()
    for index, condition in enumerate(conditions, 1):
        if not isinstance(condition, dict):
            raise exceptions.ValidationError(
                f"Filter condition {index} must be an object."
            )

        source_id = condition.get("source_id") or parent.hash
        source = _catalog_source(catalog, source_id)
        field_name = condition.get("field")
        entry = (
            catalog.get((source.hash, field_name))
            if source and field_name
            else None
        )
        if not entry:
            raise exceptions.ValidationError(
                f"Filter condition {index} uses an unavailable field. "
                "Call get_filter_schema for the current field list."
            )

        if entry.source.kind == "form" and entry.source.hash not in form_scopes:
            selector = catalog.get((parent.hash, "form"))
            if (
                not selector
                or not selector.allowed_values
                or entry.source.hash not in selector.allowed_values
            ):
                raise exceptions.ValidationError(
                    f"Filter condition {index} form source is not attached to "
                    f"this {parent.kind}."
                )
            definitions.append(
                FilterDefinition(
                    parent.hash,
                    selector.field.filter_key,
                    selector.field.field_type,
                    Comparator.EQUALS,
                    entry.source.hash,
                    True,
                )
            )
            form_scopes.add(entry.source.hash)

        comparator = _comparator(condition.get("comparator"), entry.field, index)
        values = condition.get("values")
        if values is None:
            values = []
        elif not isinstance(values, list):
            values = [values]

        comparator, value = _condition_value(
            entry,
            comparator,
            values,
            user,
            index,
        )
        definitions.append(
            FilterDefinition(
                entry.source.hash,
                entry.field.filter_key,
                entry.field.field_type,
                comparator,
                value,
                entry.field.is_entity_valued,
            )
        )

    return definitions


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_query_workspace_filter_uses_shared_cache_and_permission_filters_results
# @features ai-filter
# @dimensions cache-query permissions output
def query_workspace_filter(
    parent,
    conditions,
    user,
    *,
    limit=DEFAULT_LIMIT,
    sort="modified_desc",
    include_inactive=False,
):
    """Warm a shared parent cache and return permission-filtered AI records."""
    definitions = compile_filter_definitions(parent, conditions, user)
    cache = FilterCache(parent, user=user)
    cache.update(queue=False)
    results = cache.query(SimpleNamespace(definitions=definitions))
    visible = [
        result
        for result in results
        if result.allowed(Action.VIEW, user=user)
        and (include_inactive or getattr(result, "active", True))
    ]
    visible = _sort_results(visible, sort)
    result_limit = _result_limit(limit)
    returned = visible[:result_limit]
    task_pages = [
        result.page
        for result in returned
        if isinstance(result, Entities.TASK) and result.page
    ]
    if task_pages:
        # Task AI output derives categories from its parent Page. Treat those
        # Pages as direct roots only for the rows this response will serialize.
        Entities.fetch(*returned, *task_pages, request=Fetch.direct())
    return {
        "parent": _entity_reference(parent),
        "result_kind": "task" if parent.kind == "project" else "page",
        "matched": len(visible),
        "returned": len(returned),
        "truncated": len(visible) > len(returned),
        "results": [result.to_ai(user) for result in returned],
    }


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::describe_filter_fields
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason both public operations validate the parent before using its filter surface
def _validate_parent(parent, user):
    if not parent or getattr(parent, "kind", None) not in SUPPORTED_PARENT_KINDS:
        raise exceptions.ValidationError(
            "Filter parent must be a project or category."
        )
    if not parent.allowed(Action.VIEW, user=user):
        raise exceptions.ValidationError("Access denied.")


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::describe_filter_fields
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason catalog construction is observed through schema and compilation behavior
def _field_catalog(parent, user):
    catalog = {}
    for field in parent.filters.fields.values():
        _add_catalog_field(catalog, parent, field)

    for relation_field in parent.filters.entity_fields.values():
        related = relation_field.value
        if (
            not related
            or getattr(related, "reserved", False)
            or not related.allowed(Action.VIEW, user=user)
        ):
            continue
        _add_catalog_field(
            catalog,
            parent,
            relation_field,
            allowed_value=related,
        )
        if getattr(related, "kind", None) == "form":
            for field in related.filters.fields.values():
                _add_catalog_field(catalog, related, field)
    return catalog


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::_field_catalog
# @reason duplicate dynamic selectors are grouped through public schema behavior
def _add_catalog_field(catalog, source, field, allowed_value=None):
    key = (source.hash, field.filter_key)
    entry = catalog.get(key)
    if not entry:
        entry = _FilterField(
            source,
            field,
            allowed_values={} if allowed_value else None,
        )
        catalog[key] = entry
    if allowed_value:
        entry.allowed_values = entry.allowed_values or {}
        entry.allowed_values[allowed_value.hash] = allowed_value


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason source reference normalization is exercised through condition compilation
def _catalog_source(catalog, source_id):
    normalized = str(source_id or "").removeprefix("hash:")
    return next(
        (
            entry.source
            for entry in catalog.values()
            if entry.source.hash == normalized
        ),
        None,
    )


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::describe_filter_fields
# @reason field metadata projection is asserted through the public schema
def _field_description(entry):
    field = entry.field
    description = {
        "source": _entity_reference(entry.source),
        "field": field.filter_key,
        "label": field.filter_label or field.filter_key,
        "type": field.field_type.value,
        "comparators": [comparator.value for comparator in _field_comparators(field)],
        "entity_valued": bool(field.is_entity_valued),
    }
    choices = _field_choices(field)
    if choices:
        description["choices"] = choices
    if entry.allowed_values:
        description["allowed_values"] = [
            _entity_reference(entity)
            for entity in sorted(
                entry.allowed_values.values(),
                key=lambda value: (value.name or "").casefold(),
            )
        ]
    return description


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::describe_filter_fields
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason comparator compatibility is covered through schema and invalid-input tests
def _field_comparators(field):
    options = field.field_options or ()
    available = {
        Comparator[option.name]
        for option in options
        if option.name in Comparator.__members__
    }
    supported = available & SUPPORTED_COMPARATORS
    if field.field_type == FieldType.BOOLEAN:
        supported &= {Comparator.IS_TRUE, Comparator.IS_FALSE}
    elif field.field_type == FieldType.LIST:
        supported &= {Comparator.CONTAINS, Comparator.CONTAINS_ANY}
    elif field.is_entity_valued:
        supported &= {Comparator.EQUALS, Comparator.IN}
    elif field.field_type == FieldType.STRING:
        supported &= {
            Comparator.EQUALS,
            Comparator.IN,
            Comparator.SUBSTRING,
        }
    return sorted(supported, key=lambda comparator: comparator.value)


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::describe_filter_fields
# @reason categorical choices are visible in the public filter schema
def _field_choices(field):
    choices = getattr(field, "choices", None)
    if not isinstance(choices, dict):
        return []
    return [
        {"value": value, "label": label}
        for value, label in choices.items()
    ]


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason comparator parsing is asserted through invalid-input compilation tests
def _comparator(value, field, index):
    try:
        comparator = Comparator(str(value or "").strip().lower())
    except ValueError as error:
        raise exceptions.ValidationError(
            f"Filter condition {index} uses an unknown comparator."
        ) from error
    if comparator not in _field_comparators(field):
        allowed = ", ".join(item.value for item in _field_comparators(field))
        raise exceptions.ValidationError(
            f"Filter condition {index} comparator is not valid for "
            f"{field.filter_key}. Allowed: {allowed}."
        )
    return comparator


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason type-specific normalization is asserted through public compilation tests
def _condition_value(entry, comparator, values, user, index):
    field = entry.field
    if comparator in {Comparator.IS_TRUE, Comparator.IS_FALSE}:
        if values:
            raise exceptions.ValidationError(
                f"Filter condition {index} boolean comparator does not take values."
            )
        return comparator, None

    expected = 2 if comparator == Comparator.BETWEEN else None
    if expected and len(values) != expected:
        raise exceptions.ValidationError(
            f"Filter condition {index} between comparator requires two values."
        )
    if not expected and not values:
        raise exceptions.ValidationError(
            f"Filter condition {index} requires a value."
        )

    if field.is_entity_valued:
        normalized = [
            _entity_filter_value(entry, value, user, index) for value in values
        ]
    else:
        normalized = [
            _scalar_filter_value(field, value, user, index)
            for value in values
        ]

    if field.field_type == FieldType.TIMESTAMP:
        return _timestamp_condition(comparator, normalized)
    if comparator in {Comparator.IN, Comparator.CONTAINS_ANY, Comparator.BETWEEN}:
        return comparator, normalized
    if len(normalized) != 1:
        raise exceptions.ValidationError(
            f"Filter condition {index} comparator requires exactly one value."
        )
    return comparator, normalized[0]


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason entity permission and selector validation are covered through compilation tests
def _entity_filter_value(entry, value, user, index):
    entity = Entities.fetch_one(value, request=Fetch.direct())
    if not entity or not entity.allowed(Action.VIEW, user=user):
        raise exceptions.ValidationError(
            f"Filter condition {index} references an unavailable entity."
        )
    if entry.allowed_values and entity.hash not in entry.allowed_values:
        raise exceptions.ValidationError(
            f"Filter condition {index} entity is not valid for "
            f"{entry.field.filter_key}."
        )
    if entry.field.filter_key == "assigned_to" and isinstance(entity, Entities.USER):
        entity = entity.page
        if not entity or not entity.allowed(Action.VIEW, user=user):
            raise exceptions.ValidationError(
                f"Filter condition {index} assignee page is unavailable."
            )
    return entity.hash


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason scalar normalization is covered through compilation tests
def _scalar_filter_value(field, value, user, index):
    choices = getattr(field, "choices", None)
    if isinstance(choices, dict) and choices:
        if value in choices:
            return value
        label_match = next(
            (
                choice
                for choice, label in choices.items()
                if str(label).casefold() == str(value).casefold()
            ),
            None,
        )
        if label_match is not None:
            return label_match
        raise exceptions.ValidationError(
            f"Filter condition {index} value is not an available choice."
        )

    if field.field_type == FieldType.NUMBER:
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise exceptions.ValidationError(
                f"Filter condition {index} requires a number."
            ) from error
        if not isfinite(number):
            raise exceptions.ValidationError(
                f"Filter condition {index} requires a finite number."
            )
        return number
    if field.field_type == FieldType.TIMESTAMP:
        return _timestamp_value(value, user, index)

    text = str(value).strip()
    if not text:
        raise exceptions.ValidationError(
            f"Filter condition {index} contains an empty value."
        )
    return text


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason date boundary behavior is asserted through public compilation tests
def _timestamp_value(value, user, index):
    if isinstance(value, (int, float)):
        return {"instant": float(value), "date_only": False}
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as error:
        raise exceptions.ValidationError(
            f"Filter condition {index} requires an ISO date or datetime."
        ) from error

    date_only = "T" not in str(value) and " " not in str(value)
    user_timezone = dates.user_timezone(user)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=user_timezone)
    parsed = parsed.astimezone(timezone.utc)
    if not date_only:
        return {"instant": parsed.timestamp(), "date_only": False}

    local_date = parsed.astimezone(user_timezone).date()
    start = datetime.combine(local_date, time.min, tzinfo=user_timezone)
    end = datetime.combine(local_date, time.max, tzinfo=user_timezone)
    return {
        "start": start.astimezone(timezone.utc).timestamp(),
        "end": end.astimezone(timezone.utc).timestamp(),
        "date_only": True,
    }


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::compile_filter_definitions
# @reason comparator-specific date boundaries are asserted through compilation tests
def _timestamp_condition(comparator, values):
    if comparator == Comparator.BETWEEN:
        start = values[0].get("start", values[0].get("instant"))
        end = values[1].get("end", values[1].get("instant"))
        return comparator, [start, end]

    value = values[0]
    if not value["date_only"]:
        return comparator, value["instant"]
    if comparator == Comparator.EQUALS:
        return Comparator.BETWEEN, [value["start"], value["end"]]
    if comparator in {Comparator.LESS_EQUAL, Comparator.GREATER_THAN}:
        return comparator, value["end"]
    return comparator, value["start"]


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::query_workspace_filter
# @reason bounded output is asserted through public query behavior
def _result_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::query_workspace_filter
# @reason result ordering is asserted through public query behavior
def _sort_results(results, sort):
    if sort not in SORTS:
        raise exceptions.ValidationError(f"Unknown filter result sort: {sort}.")
    if sort == "name_asc":
        return sorted(results, key=lambda result: (result.name or "").casefold())

    field, descending = sort.rsplit("_", 1)
    reverse = descending == "desc"
    if not reverse:
        return sorted(
            results,
            key=lambda result: (
                getattr(result, field, None) is None,
                getattr(result, field, None),
            ),
        )
    return sorted(
        results,
        key=lambda result: (
            getattr(result, field, None) is not None,
            getattr(result, field, None),
        ),
        reverse=True,
    )


# @testable false
# @covered-by lagniappe/core/tools/filters/ai_query.py::describe_filter_fields
# @covered-by lagniappe/core/tools/filters/ai_query.py::query_workspace_filter
# @reason compact references are asserted through public schema and query output
def _entity_reference(entity):
    return {
        "kind": entity.kind,
        "hash": f"hash:{entity.hash}",
        "name": entity.name,
    }
