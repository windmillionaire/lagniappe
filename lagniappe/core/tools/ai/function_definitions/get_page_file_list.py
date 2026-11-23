"""Function declaration and handler for listing files attached to a page."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from ..references import hash_reference


GET_PAGE_FILE_LIST = types.FunctionDeclaration(
    name="get_page_file_list",
    description=(
        "List all files attached to a page. Returns file metadata including "
        "display_name, filename, mimetype, hash token, and a large-file flag "
        "when known. Use the returned hash with get_file to retrieve summaries, "
        "extracted text, and small original files. Large originals require an "
        "explicit get_file include_original request."
    ),
    parameters=types.Schema.model_validate({
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The page hash token from prompt context or search results.",
            },
        },
        "required": ["id"],
    }),
)


def execute_get_page_file_list(args: Mapping[str, object], user: User) -> Mapping[str, object]:
    identifier = args.get("id")
    if not isinstance(identifier, str) or not identifier:
        return {"error": "id is required"}

    page = Entities.fetch_one(identifier, request=Fetch.direct())
    if not page or not isinstance(page, Entities.PAGE):
        return {"error": "Page not found"}

    if not page.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    files = []
    for f in page.files:
        files.append(f.to_ai(user))

    return {
        "page": {
            "hash": hash_reference(page),
            "name": page.name,
        },
        "files": files,
    }
