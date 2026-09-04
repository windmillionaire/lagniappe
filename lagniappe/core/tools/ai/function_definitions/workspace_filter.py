"""AI declarations and handlers for shared-cache workspace filter queries."""

from google.genai import types

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.filters import describe_filter_fields, query_workspace_filter


FILTER_COMPARATORS = (
    "is_true",
    "is_false",
    "eq",
    "gt",
    "lt",
    "gte",
    "lte",
    "contains",
    "in",
    "substring",
    "contains_any",
    "between",
)
FILTER_SORTS = (
    "modified_desc",
    "modified_asc",
    "due_date_asc",
    "due_date_desc",
    "name_asc",
)


GET_FILTER_SCHEMA = types.FunctionDeclaration(
    name="get_filter_schema",
    description=(
        "Describe the filterable task fields under one project or page fields "
        "under one category. Returns exact source hash tokens, field ids, value "
        "types, supported comparators, select choices, and allowed model-task/form "
        "values. Call this before query_workspace_filter when the needed fields "
        "or comparators are not already known."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": (
                    "The project or category hash token from workspace inventory "
                    "or search results."
                ),
            },
        },
        "required": ["id"],
    },
)


QUERY_WORKSPACE_FILTER = types.FunctionDeclaration(
    name="query_workspace_filter",
    description=(
        "Run a read-only structured filter over tasks in one project or pages in "
        "one category. The shared parent cache is warmed or refreshed first; "
        "results are then filtered by the current user's view permissions. Use "
        "get_filter_schema to discover source_id, field, comparator, and choice "
        "values. All conditions are combined with AND. Values are strings even "
        "for numbers and dates; use ISO YYYY-MM-DD dates."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The project or category hash token.",
            },
            "conditions": {
                "type": "array",
                "description": "One to twelve conditions, all of which must match.",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_id": {
                            "type": "string",
                            "description": (
                                "The field source hash from get_filter_schema. "
                                "Omit for ordinary project/category fields; use a "
                                "form hash for attached form submission fields."
                            ),
                        },
                        "field": {
                            "type": "string",
                            "description": "Exact field id from get_filter_schema.",
                        },
                        "comparator": {
                            "type": "string",
                            "enum": list(FILTER_COMPARATORS),
                            "description": "A comparator allowed for this field.",
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "No values for is_true/is_false; exactly two for "
                                "between; otherwise one or more as required by the "
                                "selected comparator. Entity values must be hash "
                                "tokens."
                            ),
                        },
                    },
                    "required": ["field", "comparator", "values"],
                },
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return; defaults to 25, max 100.",
            },
            "sort": {
                "type": "string",
                "enum": list(FILTER_SORTS),
                "description": "Result ordering; defaults to modified_desc.",
            },
            "include_inactive": {
                "type": "boolean",
                "description": "Include inactive records. Defaults to false.",
            },
        },
        "required": ["id", "conditions"],
    },
)


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_filter_tool_handlers_load_viewable_parents_and_return_validation_errors
# @matrix ai-filter : permissions tool-handler validation
def execute_get_filter_schema(args, user):
    """Return a permission-filtered filter schema for a project/category."""
    parent, error = _filter_parent(args, user)
    if error:
        return error
    try:
        return describe_filter_fields(parent, user)
    except exceptions.ValidationError as error:
        return {"error": str(error)}


# @testable true
# @tests tests_unit/test_015c_ai_filter_query.py::test_filter_tool_handlers_load_viewable_parents_and_return_validation_errors
# @matrix ai-filter : permissions tool-handler validation
def execute_query_workspace_filter(args, user):
    """Compile and execute a permission-filtered shared-cache query."""
    parent, error = _filter_parent(args, user)
    if error:
        return error
    try:
        return query_workspace_filter(
            parent,
            args.get("conditions"),
            user,
            limit=args.get("limit"),
            sort=args.get("sort") or "modified_desc",
            include_inactive=bool(args.get("include_inactive", False)),
        )
    except exceptions.ValidationError as error:
        return {"error": str(error)}


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/workspace_filter.py::execute_get_filter_schema
# @covered-by lagniappe/core/tools/ai/function_definitions/workspace_filter.py::execute_query_workspace_filter
# @reason parent loading and permission checks are asserted through both public handlers
def _filter_parent(args, user):
    args = args or {}
    identifier = args.get("id")
    if not identifier:
        return None, {"error": "id is required"}
    parent = Entities.fetch_one(identifier, request=Fetch.direct())
    if not parent or parent.kind not in {"project", "category"}:
        return None, {"error": "Project or category not found"}
    if not parent.allowed(Action.VIEW, user=user):
        return None, {"error": "Access denied"}
    return parent, None
