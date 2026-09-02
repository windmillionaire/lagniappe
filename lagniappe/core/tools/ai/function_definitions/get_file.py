"""Function declaration and handler for retrieving file content."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities

GET_FILE = types.FunctionDeclaration(
    name="get_file",
    description=(
        "Retrieve metadata and extracted text for a file by its hash token. "
        "Set include_original=true only when the original bytes are needed for "
        "direct analysis. Transport adapters may return direct media or a "
        "short-lived download URL; extracted text is returned by default."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": (
                    "The file hash token from get_page_file_list or search results."
                ),
            },
            "include_original": {
                "type": "boolean",
                "description": (
                    "Request the original file content when available. Depending on "
                    "the client transport, the result may include direct media or a "
                    "short-lived download URL. Use only when metadata or extracted "
                    "text is not enough."
                ),
            },
        },
        "required": ["id"],
    },
)


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_file.py::execute_get_file
# @reason submitted tool boolean parsing is exercised through file tool payload tests
def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_file_tools_return_summary_and_content
# @tests tests_unit/test_015_ai_tools.py::test_ai_get_file_skips_large_original_unless_requested
# @tests tests_unit/test_015_ai_tools.py::test_ai_get_file_reports_unsupported_original_file
# @matrix ai files : attachments content get-file large-file summary unsupported
def execute_get_file(args, user):
    file_id = args.get("id")
    if not file_id:
        return {"error": "id is required"}

    entity = Entities.fetch_one(file_id, request=Fetch.direct())
    if not entity or not isinstance(entity, Entities.FILE):
        return {"error": "File not found"}

    if not entity.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    result = entity.to_ai(user)

    text_content = entity.properties.text.asset
    if text_content:
        result["content"] = text_content

    file_parts = []
    file_part = entity.properties.file.uri_to_ai
    include_original = _truthy(args.get("include_original"))
    if file_part:
        if not include_original:
            result["original_file"] = {
                "supported": True,
                "attached": False,
                "reason": (
                    "Original content was not included by default. Call get_file "
                    "again with include_original=true if the original bytes are "
                    "necessary."
                ),
            }
        else:
            result["original_file"] = {
                "supported": True,
                "attached": True,
            }
            file_parts.append(file_part)
    else:
        result["original_file"] = {
            "supported": False,
            "attached": False,
            "reason": "Original content is unavailable for this file.",
        }

    if file_parts:
        return result, file_parts

    return result
