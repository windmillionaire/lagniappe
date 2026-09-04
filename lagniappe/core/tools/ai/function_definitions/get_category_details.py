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
            "id": {
                "type": "string",
                "description": "The category hash token from prompt context or search results.",
            },
        },
        "required": ["id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_category_details_uses_canonical_id_and_checks_permission
# @matrix ai categories : category-details permissions tool-context
def execute_get_category_details(args, user):
    identifier = args.get("id")
    if not identifier:
        return {"error": "id is required"}

    category = Entities.fetch_one(identifier, request=Fetch.direct())
    if not category or not isinstance(category, Entities.CATEGORY):
        return {"error": "Category not found"}

    if not category.allowed(Action.VIEW, user):
        return {"error": "Access denied"}

    return category.to_ai(user)
