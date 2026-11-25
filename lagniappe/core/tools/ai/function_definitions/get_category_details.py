"""Function declaration and handler for loading a page's model category."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities


GET_CATEGORY_DETAILS = types.FunctionDeclaration(
    name="get_category_details",
    description=(
        "Load the full details of a category by its hash token. Use this when "
        "the page form being autofilled requires context from its parent "
        "category — for example, when generating content that should match the "
        "category's theme, conventions, or descriptive context."
    ),
    parameters=types.Schema.model_validate({
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The category hash token from prompt context or search results.",
            },
        },
        "required": ["id"],
    }),
)


def execute_get_category_details(args: Mapping[str, object], user: User) -> Mapping[str, object]:
    identifier = args.get("id")
    if not isinstance(identifier, str) or not identifier:
        return {"error": "id is required"}

    category = Entities.fetch_one(identifier, request=Fetch.direct())
    if not category or not isinstance(category, Entities.CATEGORY):
        return {"error": "Category not found"}

    if not category.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    return category.to_ai(user)
