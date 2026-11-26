"""Function declaration and handler for retrieving file content."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User
    from lagniappe.core.properties.file_assets import FilePart

from google.genai import types

from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.definitions.asset import FileAsset
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import assets as storage_assets

GET_FILE = types.FunctionDeclaration(
    name="get_file",
    description=(
        "Retrieve metadata and extracted text for a file by its hash token. "
        "Set include_original=true only when the original bytes are needed for "
        "direct analysis. Transport adapters may return direct media or a "
        "short-lived download URL; extracted text is returned by default."
    ),
    parameters=types.Schema.model_validate({
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
    }),
)


def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def execute_get_file(args: Mapping[str, object], user: User, *, external: bool = False) -> Mapping[str, object] | tuple[Mapping[str, object], list[FilePart]]:
    file_id = args.get("id")
    if not isinstance(file_id, str) or not file_id:
        return {"error": "id is required"}

    entity = Entities.fetch_one(file_id, request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
    if not entity or not isinstance(entity, Entities.FILE):
        return {"error": "File not found"}

    if not entity.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    result = entity.to_ai(user)

    text_content = entity.properties.text.asset
    if text_content:
        result["content"] = text_content

    include_original = _truthy(args.get("include_original"))
    file_part = entity.properties.file.uri_to_ai
    reason = (
        "Original content was not included by default. Call get_file "
        "again with include_original=true if the original bytes are necessary."
    )
    if external:
        asset = entity.properties.file.value
        if isinstance(asset, FileAsset) and asset.path:
            if include_original:
                result["original_file"] = {
                    "supported": True,
                    "attached": False,
                    "download_url": storage_assets.get_signed_url(asset.path, expires_in=300),
                    "expires_in": 300,
                }
                return result
            if not file_part:
                reason = (
                    "Original content was not included by default. Call get_file "
                    "again with include_original=true to receive a five-minute signed "
                    "download URL."
                )
            result["original_file"] = {"supported": True, "attached": False, "reason": reason}
            return result

    if file_part and include_original:
        result["original_file"] = {"supported": True, "attached": True}
        return result, [file_part]

    result["original_file"] = {
        "supported": bool(file_part),
        "attached": False,
        "reason": reason if file_part else "Original content is unavailable for this file.",
    }
    return result
