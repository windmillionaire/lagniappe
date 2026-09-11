"""Function declaration and handler for loading a page and its related context."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from ..task_lists import DEFAULT_TASK_LIMIT, TASK_LIMIT_SCHEMA, compact_task_list


GET_PAGE_DETAILS = types.FunctionDeclaration(
    name="get_page_details",
    description=(
        "Load the full details of a page, including its model category, tasks, "
        "and attached file metadata and summaries. Tasks are not simple "
        "checkboxes — they carry rich data such "
        "as form submissions, descriptions, and linked entities, and often "
        "represent goals, project details, or structured records. Use this "
        "when a form requires context from the page — for example, generating "
        "a summary, writing creative content, or filling fields that depend "
        "on the page's topic, category, or task data. Set compact_tasks=true for "
        "a bounded active-task list without task schemas/submissions; task_list "
        "describes counts, continuation and partial errors. Use get_page_tasks "
        "with compact=true when discovery also needs completed tasks."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The page hash token from prompt context or search results.",
            },
            "exclude_tasks": {
                "type": "boolean",
                "description": (
                    "When true, omit the page's tasks from the response. "
                    "Tasks are included by default."
                ),
            },
            "exclude_files": {
                "type": "boolean",
                "description": (
                    "When true, omit files attached to the page. File metadata "
                    "and summaries are included by default."
                ),
            },
            "compact_tasks": {
                "type": "boolean",
                "description": "Return compact active tasks; page/category and file details keep their existing shape. Defaults to false; exclude_tasks takes precedence.",
            },
            "task_limit": TASK_LIMIT_SCHEMA,
            "task_cursor": {
                "type": "string",
                "description": "task_list.next_cursor from this page's previous compact_tasks read. Continue with get_page_details using compact_tasks=true, or restart without it if stale.",
            },
        },
        "required": ["id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_page_details_includes_file_summaries_by_default
# @matrix ai files pages tasks : exclusions page-details projection summary
# @matrix ai tasks : compact pagination permissions
# @tests tests_unit/test_015f_ai_task_lists.py::test_compact_page_details_*
def execute_get_page_details(args, user):
    identifier = args.get("id")
    if not identifier:
        return {"error": "id is required"}

    page = Entities.fetch_one(identifier, request=Fetch.direct())
    if not page or not isinstance(page, Entities.PAGE):
        return {"error": "Page not found"}

    if not page.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    result = {"page": page.to_ai(user)}

    if page.model:
        result["category"] = page.model.to_ai(user)

    if not args.get("exclude_tasks"):
        if args.get("compact_tasks"):
            listing = compact_task_list(
                page,
                user,
                include_completed=False,
                limit=args.get("task_limit", DEFAULT_TASK_LIMIT),
                cursor=args.get("task_cursor"),
            )
            if "error" in listing:
                return listing
            result.update(listing)
        elif "task_limit" in args or "task_cursor" in args:
            return {"error": "task_limit and task_cursor require compact_tasks=true"}
        else:
            result["tasks"] = [t.to_ai(user) for t in page.tasks]

    if not args.get("exclude_files"):
        result["files"] = [f.to_ai(user) for f in page.files]

    return result
