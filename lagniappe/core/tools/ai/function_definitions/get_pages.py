"""Function declaration and handler for loading sample pages from a category."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get

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
                "minimum": 1,
                "maximum": SEARCH_LIMIT,
                "description": (
                    f"Maximum number of pages to return (default {CATEGORY_PAGES_LIMIT}). "
                    f"The hard maximum is {SEARCH_LIMIT}; follow next_cursor when "
                    "has_more is true for a more thorough scan."
                ),
            },
            "cursor": {
                "type": "string",
                "description": (
                    "Opaque next_cursor from a previous get_category_pages result "
                    "for the same category and form filter."
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
# @tests tests_unit/test_015_ai_tools.py::test_get_category_pages_reports_effective_limit_and_pagination
# @matrix ai category-pages : compact pagination tool-context
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

    raw_limit = args.get("limit", CATEGORY_PAGES_LIMIT)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        return {
            "error": f"limit must be an integer from 1 to {SEARCH_LIMIT}",
            "minimum": 1,
            "maximum": SEARCH_LIMIT,
        }
    requested_limit = raw_limit
    # Preserve older integer callers while making the clamp visible in output.
    effective_limit = min(max(requested_limit, 1), SEARCH_LIMIT)
    cursor = args.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        return {"error": "cursor must be a string"}
    cursor = cursor.strip() if cursor else None
    restrictions = user.properties.restrictions.unrestricted_pages(category)
    db = database_get.pages(
        category.key,
        form=form,
        start_cursor=cursor,
        limit=effective_limit,
        hashes=restrictions,
    )

    pages = Entities.fetch(*db.results, request=Fetch.direct())
    next_cursor = getattr(db, "next_cursor", None)

    return {
        "category": category.name,
        "requested_limit": requested_limit,
        "effective_limit": effective_limit,
        "returned_count": len(pages),
        "has_more": bool(next_cursor),
        "next_cursor": next_cursor,
        # Retained for older callers; returned_count is the unambiguous name.
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
