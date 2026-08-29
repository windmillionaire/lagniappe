"""Function declaration and handler for loading a page's tasks."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from ..references import hash_reference


GET_PAGE_TASKS = types.FunctionDeclaration(
    name="get_page_tasks",
    description=(
        "Load active and completed tasks belonging to a page. Tasks carry rich "
        "data such as form submissions, descriptions, dates, and linked "
        "entities. Use this before deciding whether new evidence belongs to an "
        "existing task or a distinct task on the same page."
    ),
    parameters={
        "type": "object",
        "properties": {
            "page_id": {
                "type": "string",
                "description": "The page hash token from prompt context or search results.",
            },
        },
        "required": ["page_id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_page_tasks_returns_active_and_completed_tasks
# @matrix ai tasks : active completed page-task-context
def execute_get_page_tasks(args, user):
    page_id = args.get("page_id")
    if not page_id:
        return {"error": "page_id is required"}

    page = Entities.fetch_one(page_id, request=Fetch.direct())
    if not page or not isinstance(page, Entities.PAGE):
        return {"error": "Page not found"}

    if not page.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    return {
        "page": {
            "hash": hash_reference(page),
            "name": page.name,
        },
        "tasks": [t.to_ai(user) for t in page.tasks],
        "completed_tasks": [t.to_ai(user) for t in page.completed],
    }
