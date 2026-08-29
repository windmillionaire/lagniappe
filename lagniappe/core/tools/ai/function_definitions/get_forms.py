"""Function declaration and handler for listing forms available in a category."""

from google.genai import types

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from ..references import hash_reference


GET_CATEGORY_FORMS = types.FunctionDeclaration(
    name="get_category_forms",
    description=(
        "List the forms (content types) in a category. Forms classify what a "
        "page is — they act as tags that group similar pages together. For "
        "example, a 'Music' category might have forms for 'Album', 'Artist', "
        "and 'Playlist'. Use this to discover what types of content exist in a "
        "category, then pass a form hash token to get_category_pages to retrieve "
        "example pages of that type. This returns the full form schema so a "
        "model can create valid submission objects with exact field ids and "
        "value shapes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The category hash token (from search results or context)",
            },
        },
        "required": ["id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_category_forms_returns_full_form_schema
# @matrix ai form-schema : autofill category-forms schema
def execute_get_category_forms(args, user):
    identifier = args.get("id")
    if not identifier:
        return {"error": "id is required"}

    category = Entities.fetch_one(identifier, request=Fetch.direct())
    if not category or not isinstance(category, Entities.CATEGORY):
        return {"error": "Category not found"}

    forms = list(category.forms)
    if category.form and category.form not in forms:
        forms.insert(0, category.form)

    if not forms:
        return {"category": category.name, "form_count": 0, "forms": []}

    return {
        "category": category.name,
        "form_count": len(forms),
        "forms": [
            {
                "hash": hash_reference(f),
                "name": f.name,
                "form_type": f.form_type,
                "schema": f.schema or [],
            }
            for f in forms
        ],
    }
