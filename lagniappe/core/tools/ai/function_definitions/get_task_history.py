"""Function declaration and handler for loading task completion history."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.mixins import AIMixin
from lagniappe.core.properties.schema import SchemaFields
from lagniappe.core.tools.forms.definitions import original_completion
from ..submission_values import values_by_id

DEFAULT_HISTORY_LIMIT = 10
MAX_HISTORY_LIMIT = 50


GET_TASK_HISTORY = types.FunctionDeclaration(
    name="get_task_history",
    description=(
        "Load completion history for a task, including the name and description "
        "saved for each completion, completion dates, submission values, and "
        "attached file metadata. Use this for "
        "questions about past task occurrences, recency, frequency, averages, "
        "or evidence files, such as last doctor appointments or gaps between "
        "oil changes. Use file hash tokens from the result with get_file when the "
        "answer depends on the attached file contents. The task contains current "
        "answers. Set include_original=true for its original completed answers "
        "and recorded schema; this requires edit access, as on the website."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
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
            "include_original": {
                "type": "boolean",
                "description": "Include the completed Task's original answers and schema generation (default false; requires edit access). Open Tasks return original_completion=null.",
            },
        },
        "required": ["id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_task_history_returns_dates_submissions_and_files
# @tests tests_unit/test_015_ai_tools.py::test_get_task_history_original_answers_use_saved_schema_and_permissions
# @matrix ai tasks : original-completion permissions schema-version
# @matrix ai tasks : files task-history tool-context
def execute_get_task_history(args, user):
    identifier = args.get("id")
    if not identifier:
        return {"error": "id is required"}

    task = Entities.fetch_one(identifier, request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
    if not task or not isinstance(task, Entities.TASK):
        return {"error": "Task not found"}

    if not task.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    include_original = args.get("include_original") is True
    if include_original and not task.allowed(Action.EDIT, user):
        return {"error": "Original completed answers require edit access to this Task."}

    limit = _history_limit(args.get("limit"))
    history_rows = list(task.history)
    selected = history_rows[:limit]
    result = {
        "task": task.to_ai(user),
        "count": len(history_rows),
        "limit": limit,
        "truncated": len(history_rows) > len(selected),
        "history": [history.to_ai(user) for history in selected],
    }
    if include_original:
        try:
            result["original_completion"] = _original_answers(task, user) if task.completed else None
        except ValidationError as error:
            return {"error": str(error)}
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_task_history.py::execute_get_task_history
# @reason original snapshot selection and safe projection are exercised through the public read
def _original_answers(task, user):
    original = original_completion(task)
    definition = original["definition"]
    result = {
        "generation": original["generation"],
        "schema": definition.schema,
        "schema_available": definition.error is None,
        "values": None,
    }
    if definition.error:
        # Without field types, stored entity/asset keys cannot be projected safely.
        result["error"] = definition.error
        return result
    fields, signatures = {}, {}
    for schema in definition.schema:
        field_id = schema["id"]
        if field_id not in original["submission"]:
            continue
        value = original["submission"][field_id]
        if schema["type"] == "signature":
            # The saved presence marker describes this completion; looking up
            # today's Task assets would describe a different answer.
            signatures[field_id] = bool(value)
            continue
        field = SchemaFields.create_field(schema, task)
        if isinstance(field, AIMixin):
            field.db_value = value
            fields[field_id] = field
    result["values"] = {**values_by_id(fields, user), **signatures}
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_task_history.py::execute_get_task_history
# @reason defensive argument normalization is covered through the public handler
def _history_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_HISTORY_LIMIT
    return max(1, min(limit, MAX_HISTORY_LIMIT))
