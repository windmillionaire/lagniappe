"""Function declaration and handler for loading a page's tasks."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from ..references import hash_reference
from ..task_lists import DEFAULT_TASK_LIMIT, TASK_LIMIT_SCHEMA, compact_task_list


GET_PAGE_TASKS = types.FunctionDeclaration(
    name="get_page_tasks",
    description=(
        "Load active and completed tasks belonging to a page. Prefer compact=true "
        "for discovery and duplicate-work checks: names, hashes, browser links, "
        "completion state, bounded descriptions, dates and model/form references, "
        "without schemas or submissions. Inspect task_list for counts, continuation "
        "and partial errors; follow next_cursor before claiming a complete inventory. "
        "Use get_entity on likely matches when descriptions or form values matter; "
        "use get_schema for a referenced task/form when preparing field values. "
        "Reuse sufficient search/list evidence; a duplicate check does not require both. "
        "Omit compact for the existing full task details."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The page hash token from prompt context or search results.",
            },
            "compact": {
                "type": "boolean",
                "description": "Return lightweight, paginated tasks. Defaults to false.",
            },
            "limit": TASK_LIMIT_SCHEMA,
            "cursor": {
                "type": "string",
                "description": "task_list.next_cursor from this page's previous compact get_page_tasks result. Omit on the first read; restart without it if stale.",
            },
        },
        "required": ["id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_page_tasks_returns_active_and_completed_tasks
# @matrix ai tasks : active completed page-task-context
# @matrix ai tasks : compact pagination permissions
# @tests tests_unit/test_015f_ai_task_lists.py::test_compact_tasks_*
def execute_get_page_tasks(args, user):
    identifier = args.get("id")
    if not identifier:
        return {"error": "id is required"}

    page = Entities.fetch_one(identifier, request=Fetch.direct())
    if not page or not isinstance(page, Entities.PAGE):
        return {"error": "Page not found"}

    if not page.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    if args.get("compact"):
        listing = compact_task_list(
            page,
            user,
            include_completed=True,
            limit=args.get("limit", DEFAULT_TASK_LIMIT),
            cursor=args.get("cursor"),
        )
        if "error" in listing:
            return listing
        return {"page": {"hash": hash_reference(page), "name": page.name}, **listing}
    if "limit" in args or "cursor" in args:
        return {"error": "limit and cursor require compact=true"}

    return {
        "page": {
            "hash": hash_reference(page),
            "name": page.name,
        },
        "tasks": [t.to_ai(user) for t in page.tasks],
        "completed_tasks": [t.to_ai(user) for t in page.completed],
    }
