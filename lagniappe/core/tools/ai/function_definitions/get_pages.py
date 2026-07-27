"""Function declaration and handler for loading sample pages from a category."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database

CATEGORY_PAGES_LIMIT = 5
SEARCH_LIMIT = 10


GET_CATEGORY_PAGES = types.FunctionDeclaration(
    name="get_category_pages",
    description=(
        "Load pages from a category. Use compact=true for a lightweight "
        "name/hash/description scan before creating a new page. Use the default "
        "full result when you need page examples with form data, document text, "
        "and metadata. When filtered by form_id, returns only pages of that "
        "specific type. Call get_category_forms first to discover available "
        "form types, then pass a form hash token here to get focused examples."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The category hash token from search results or context.",
            },
            "form_id": {
                "type": "string",
                "description": "The form hash token from search results or context.",
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Maximum number of pages to return (default {CATEGORY_PAGES_LIMIT}). "
                    "Use fewer for a quick overview, more for thorough analysis."
                ),
            },
            "compact": {
                "type": "boolean",
                "description": (
                    "When true, return lightweight page references only: hash, "
                    "name, page_description, form/category refs, URL, and "
                    "permissions. Use get_entity on a likely page hash to load "
                    "submission fields or document text."
                ),
            },
        },
        "required": ["id"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_category_pages_compact_returns_lightweight_page_refs
# @pairs ai:tool-context ai:compact category-pages:tool-context category-pages:compact
def execute_get_category_pages(args, user):
    identifier = args.get("id")
    form_identifier = args.get("form_id")
    compact = _bool_arg(args.get("compact"))
    if not identifier:
        return {"error": "id is required"}

    entities = Entities.fetch(identifier, form_identifier, request=Fetch.direct())
    category = next((e for e in entities if isinstance(e, Entities.CATEGORY)), None)
    form = next((e for e in entities if isinstance(e, Entities.FORM)), None)
    if not category:
        return {"error": "Category not found"}

    limit = min(args.get("limit", CATEGORY_PAGES_LIMIT), SEARCH_LIMIT)
    restrictions = user.properties.restrictions.unrestricted_pages(category)
    db = database.get.pages(category.key, form=form, limit=limit, hashes=restrictions)

    pages = Entities.fetch(*db.results, request=Fetch.direct())

    return {
        "category": category.name,
        "page_count": len(pages),
        "pages": [
            _compact_page_reference(p, user) if compact else p.to_ai(user)
            for p in pages
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_pages.py::execute_get_category_pages
# @reason boolean argument coercion is exercised through the public tool handler
def _bool_arg(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_pages.py::execute_get_category_pages
# @reason compact page projection is exercised through the public tool handler
def _compact_page_reference(page, user):
    ai_url = getattr(page, "_ai_url", None)
    data = {
        "kind": page.entity_kind,
        "hash": f"hash:{page.hash}" if getattr(page, "hash", None) else None,
        "name": page.name,
        "page_description": page.description,
        "form": _compact_entity_reference(getattr(page, "form", None), user),
        "page_categories": [
            ref
            for ref in (
                _compact_entity_reference(category, user)
                for category in getattr(page, "categories", []) or []
            )
            if ref
        ],
        "url": ai_url() if callable(ai_url) else None,
        "permissions": {
            "can_view": page.allowed(Action.VIEW, user=user),
            "can_edit": page.allowed(Action.EDIT, user=user),
            "can_create": page.allowed(Action.CREATE, user=user),
        },
    }
    return {key: value for key, value in data.items() if value not in (None, [], {})}


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/get_pages.py::_compact_page_reference
# @reason compact related projection is exercised through compact page results
def _compact_entity_reference(entity, user):
    if not entity or not entity.allowed(Action.VIEW, user):
        return None
    data = {
        "kind": getattr(entity, "entity_kind", None),
        "hash": f"hash:{entity.hash}" if getattr(entity, "hash", None) else None,
        "name": getattr(entity, "name", None),
    }
    return {key: value for key, value in data.items() if value is not None}
