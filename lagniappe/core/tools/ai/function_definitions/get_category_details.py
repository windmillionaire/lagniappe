"""Function declaration and handler for loading a page's model category."""

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
    parameters={
        "type": "object",
        "properties": {
            "category_id": {
                "type": "string",
                "description": "The category hash token from prompt context or search results.",
            },
        },
        "required": ["category_id"],
    },
)


# @testable false
# @reason category loading, permissions, and to_ai projection are data/E2E-owned for AI tool stories
def execute_get_category_details(args, user):
    category_id = args.get("category_id")
    if not category_id:
        return {"error": "category_id is required"}

    category = Entities.fetch_one(category_id, request=Fetch.direct())
    if not category or not isinstance(category, Entities.CATEGORY):
        return {"error": "Category not found"}

    if not category.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    return category.to_ai(user)
