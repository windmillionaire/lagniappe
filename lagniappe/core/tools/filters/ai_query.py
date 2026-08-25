"""Validated, read-only filter queries for AI workspace tools."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities

from .cache import FilterCache
from .contract import compile_filter_contract, describe_filter_contract


DEFAULT_LIMIT = 25
MAX_LIMIT = 100
SORTS = frozenset(
    {
        "modified_desc",
        "modified_asc",
        "due_date_asc",
        "due_date_desc",
        "name_asc",
    }
)


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_describe_filter_fields_exposes_parent_relations_and_form_fields
# @tests tests_unit/test_015c_ai_filter_query.py::test_describe_filter_fields_uses_real_project_and_form_filter_surfaces
# @features ai-filter
# @dimensions schema permissions integration
def describe_filter_fields(parent, user):
    """Describe filterable fields visible to ``user`` under a project/category."""
    return describe_filter_contract(parent, user)


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_compile_filter_definitions_normalizes_dates_numbers_and_booleans
# @tests tests_unit/test_015c_ai_filter_query.py::test_compile_filter_definitions_rejects_unknown_fields_comparators_and_values
# @features ai-filter
# @dimensions compilation validation permissions
def compile_filter_definitions(parent, conditions, user):
    """Compile AI condition DTOs through the shared filter contract."""
    compiled = compile_filter_contract(
        parent,
        {"version": 1, "conditions": conditions},
        user,
        allow_default_source=True,
    )
    return list(compiled.definitions)


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
    compiled = compile_filter_contract(
        parent,
        {"version": 1, "conditions": conditions},
        user,
        allow_default_source=True,
    )
    cache = FilterCache(parent, user=user)
    cache.update(queue=False)
    results = cache.query(compiled)
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
