"""Function declaration and handler for loading task completion history."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities

DEFAULT_HISTORY_LIMIT = 10
MAX_HISTORY_LIMIT = 50


GET_TASK_HISTORY = types.FunctionDeclaration(
    name="get_task_history",
    description=(
        "Load completion history for a task, including the name and description "
        "saved for each completion, completion dates, submission values, and "
        "attached file metadata. Use this for Ask "
        "questions about past task occurrences, recency, frequency, averages, "
        "or evidence files, such as last doctor appointments or gaps between "
        "oil changes. Use file hash tokens from the result with get_file when the "
        "answer depends on the attached file contents."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": (
                    "The task hash token from search_entities, get_entity, "
                    "or get_page_tasks."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum number of history rows to return, newest first. "
                    f"Defaults to {DEFAULT_HISTORY_LIMIT}; max {MAX_HISTORY_LIMIT}."
                ),
            },
        },
        "required": ["task_id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_task_history_returns_dates_submissions_and_files
# @matrix ai tasks : files task-history tool-context
def execute_get_task_history(args, user):
    task_id = args.get("task_id") or args.get("id")
    if not task_id:
        return {"error": "task_id is required"}

    task = Entities.fetch_one(task_id, request=Fetch.direct())
    if not task or not isinstance(task, Entities.TASK):
        return {"error": "Task not found"}

    if not task.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    limit = _history_limit(args.get("limit"))
    history_rows = list(task.history)
    selected = history_rows[:limit]
    return {
        "task": task.to_ai(user),
        "count": len(history_rows),
        "limit": limit,
        "truncated": len(history_rows) > len(selected),
        "history": [history.to_ai(user) for history in selected],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_task_history.py::execute_get_task_history
# @reason defensive argument normalization is covered through the public handler
def _history_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_HISTORY_LIMIT
    return max(1, min(limit, MAX_HISTORY_LIMIT))
