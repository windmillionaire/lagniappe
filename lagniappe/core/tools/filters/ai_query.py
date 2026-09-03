"""Validated, read-only filter queries for AI workspace tools."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities

from .cache import FilterCache
from .contract import compile_filter_contract, describe_filter_contract


DEFAULT_LIMIT = 25
MAX_LIMIT = 100
MAX_SERIALIZATION_ERRORS = 5
RECOVERABLE_RESULT_ERRORS = (
    exceptions.UnloadedRelationError,
    exceptions.PropertyError,
    AttributeError,
    KeyError,
    TypeError,
    ValueError,
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


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_describe_filter_fields_exposes_parent_relations_and_form_fields
# @tests tests_unit/test_015c_ai_filter_query.py::test_describe_filter_fields_uses_real_project_and_form_filter_surfaces
# @matrix ai-filter : integration permissions schema
def describe_filter_fields(parent, user):
    """Describe filterable fields visible to ``user`` under a project/category."""
    return describe_filter_contract(parent, user)


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_compile_filter_definitions_normalizes_dates_numbers_and_booleans
# @tests tests_unit/test_015c_ai_filter_query.py::test_compile_filter_definitions_rejects_unknown_fields_comparators_and_values
# @matrix ai-filter : compilation permissions validation
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
# @matrix ai-filter : cache-query output permissions
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
    selected = visible[:result_limit]
    task_pages = []
    for result in selected:
        if not isinstance(result, Entities.TASK):
            continue
        try:
            page = result.page
        except RECOVERABLE_RESULT_ERRORS:
            continue
        if page:
            task_pages.append(page)
    if task_pages:
        # Task AI output includes direct Task relations such as completed_by and
        # categories derived through the parent Page. The filter UI needs only
        # row projections, but this AI boundary serializes that two-hop graph.
        try:
            Entities.fetch(
                *selected,
                *task_pages,
                request=Fetch.nested(
                    because=FetchReason.AI_FILTER_RESULT_SERIALIZATION
                ),
            )
        except RECOVERABLE_RESULT_ERRORS:
            # Serialization below isolates affected rows and returns a bounded
            # corrective result instead of promoting legacy data to an API 500.
            pass
    serialized, serialization_errors = _serialize_results(selected, user)
    return {
        "parent": _entity_reference(parent),
        "result_kind": "task" if parent.kind == "project" else "page",
        "matched": len(visible),
        "returned": len(serialized),
        "truncated": len(visible) > len(selected),
        "results": serialized,
        **(
            {
                "serialization_errors": serialization_errors,
                "incomplete": True,
            }
            if serialization_errors
            else {}
        ),
    }


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_query_workspace_filter_reports_bounded_row_serialization_errors
# @matrix ai-filter : legacy-record bounded-error output
def _serialize_results(results, user):
    """Serialize rows independently so one legacy record cannot hide all matches."""
    serialized = []
    errors = []
    omitted_errors = 0
    for result in results:
        try:
            serialized.append(result.to_ai(user))
        except RECOVERABLE_RESULT_ERRORS:
            if len(errors) < MAX_SERIALIZATION_ERRORS:
                errors.append(
                    {
                        "code": "unrepresentable_result",
                        "entity": _entity_reference(result),
                        "message": (
                            "This matching record could not be represented for AI "
                            "output. Open and resave it, or inspect it in the app."
                        ),
                    }
                )
            else:
                omitted_errors += 1
    if omitted_errors:
        errors.append(
            {
                "code": "additional_unrepresentable_results",
                "count": omitted_errors,
                "message": "Additional matching records could not be represented.",
            }
        )
    return serialized, errors


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
