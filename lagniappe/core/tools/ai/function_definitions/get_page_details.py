"""Function declaration and handler for loading a page and its related context."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities


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
        "on the page's topic, category, or task data."
    ),
    parameters={
        "type": "object",
        "properties": {
            "page_id": {
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
        },
        "required": ["page_id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_page_details_includes_file_summaries_by_default
# @matrix ai files pages tasks : exclusions page-details projection summary
def execute_get_page_details(args, user):
    page_id = args.get("page_id")
    if not page_id:
        return {"error": "page_id is required"}

    page = Entities.fetch_one(page_id, request=Fetch.direct())
    if not page or not isinstance(page, Entities.PAGE):
        return {"error": "Page not found"}

    if not page.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    result = {"page": page.to_ai(user)}

    if page.model:
        result["category"] = page.model.to_ai(user)

    if not args.get("exclude_tasks"):
        result["tasks"] = [t.to_ai(user) for t in page.tasks]

    if not args.get("exclude_files"):
        result["files"] = [f.to_ai(user) for f in page.files]

    return result
