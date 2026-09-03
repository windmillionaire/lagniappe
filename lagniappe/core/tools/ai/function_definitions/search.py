"""Function declaration and handler for workspace entity search."""

from google.genai import types

from lagniappe.core.definitions import Action, Fetch, SearchFacets
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache

SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 25
SEARCH_KIND_ALIASES = {
    facet.value.kind: facet.value.kind
    for facet in SearchFacets
}
SEARCH_KIND_ALIASES.update(
    {
        facet.value.name: facet.value.kind
        for facet in SearchFacets
    }
)
SEARCH_KIND_ALIASES["model"] = "model"
ALLOWED_SEARCH_KINDS = tuple(sorted(SEARCH_KIND_ALIASES))
SEARCH_MATCH_MODES = ("keywords", "exact_name")


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_search_entity_urls_and_result_scrubbing
# @pair ai:search-url
def entity_url(result):
    entity_ref = result.get("hash") or result["id"]
    if result["kind"] == "category":
        return f"/categories/{entity_ref}"
    elif result["kind"] == "task" and "parent" in result:
        return f"/tasks/{entity_ref}"
    elif result["kind"] == "model" and "parent" in result:
        parent = result["parent"]
        parent_ref = parent.get("hash") or parent["id"]
        return (
            f"/projects/{parent_ref}/tasks/{entity_ref}?completed=false"
        )
    else:
        return f"/{result['kind']}s/{entity_ref}"


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_search_entity_urls_and_result_scrubbing
# @matrix ai : parent-hydration result-scrubbing
def format_search_result(result):
    formatted = dict(result)
    details = formatted.get("details")
    if isinstance(details, dict) and details.get("hash"):
        formatted["hash"] = f"hash:{details['hash']}"
    if (
        "parent" not in formatted
        and isinstance(details, dict)
        and details.get("parent")
    ):
        formatted["parent"] = _format_detail_hashes(details["parent"])
    formatted["url"] = entity_url(formatted)
    if formatted.get("hash"):
        formatted.pop("id", None)
    formatted.pop("details", None)
    return formatted


# @testable false
# @covered-by lagniappe/core/tools/ai/function_definitions/search.py::format_search_result
# @reason nested hash-token projection is covered through formatted search results
def _format_detail_hashes(details):
    if not isinstance(details, dict):
        return details
    formatted = dict(details)
    if formatted.get("hash"):
        formatted["hash"] = f"hash:{formatted['hash']}"
        formatted.pop("id", None)
    if isinstance(formatted.get("parent"), dict):
        formatted["parent"] = _format_detail_hashes(formatted["parent"])
    return formatted


SEARCH_ENTITIES = types.FunctionDeclaration(
    name="search_entities",
    description=(
        "Search the workspace by keyword for pages, tasks, categories, "
        "projects, files, and forms. Returns names, types, hash tokens, and "
        "matching snippets. Use the returned hash with get_entity to load full details, "
        "get_file to retrieve file content, or get_category_pages to load "
        "sample pages from a category. Also useful for finding forms by name "
        "across the entire workspace. Use match_mode=exact_name for a bounded, "
        "case-insensitive full-name lookup. Exact Page lookup may also be scoped "
        "to one Category with parent_id; exact matches include permissions."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search terms (keywords or phrases)",
            },
            "kinds": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": list(ALLOWED_SEARCH_KINDS),
                },
                "description": (
                    "Optional entity kinds or facet names to search, such as "
                    "page/pages, task/tasks, category/categories, project/projects, "
                    "file/files, form/forms, user/users, or model."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Maximum result count. Defaults to {SEARCH_LIMIT}; capped at "
                    f"{MAX_SEARCH_LIMIT}."
                ),
            },
            "match_mode": {
                "type": "string",
                "enum": list(SEARCH_MATCH_MODES),
                "description": (
                    "keywords uses the existing full-text search. exact_name uses "
                    "a separate bounded full-name cache lookup. Defaults to keywords."
                ),
            },
            "parent_id": {
                "type": "string",
                "description": (
                    "Optional Category hash token for exact_name Page lookup. "
                    "It is rejected for keyword search or non-Page kinds."
                ),
            },
        },
        "required": ["query"],
    },
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_search_entity_filter_arguments
# @covered-by lagniappe/core/tools/ai/function_definitions/search.py::format_search_result
# @matrix ai : search-filter search-limit
def execute_search(args, user):
    query = args.get("query", "")
    restrictions = user.properties.restrictions.search
    belongs_to = user.properties.restrictions.belongs_to
    kinds, invalid_kinds = _search_kinds(args.get("kinds"))
    if invalid_kinds:
        return {
            "error": "Unknown search kind filter.",
            "invalid_kinds": invalid_kinds,
            "allowed_kinds": list(ALLOWED_SEARCH_KINDS),
        }

    limit = _search_limit(args.get("limit"))

    match_mode = str(args.get("match_mode") or "keywords").strip().casefold()
    if match_mode not in SEARCH_MATCH_MODES:
        return {
            "error": "Unknown search match mode.",
            "allowed_match_modes": list(SEARCH_MATCH_MODES),
        }
    parent_hash = None
    if args.get("parent_id"):
        if match_mode != "exact_name" or kinds != ["page"]:
            return {
                "error": (
                    "parent_id is supported only for exact_name searches with "
                    "kinds=[\"page\"]."
                )
            }
        parent = Entities.fetch_one(args["parent_id"], request=Fetch.direct())
        if not isinstance(parent, Entities.CATEGORY):
            return {"error": "Parent Category not found."}
        if not parent.allowed(Action.VIEW, user=user):
            return {"error": "Access denied"}
        parent_hash = parent.hash

    if match_mode == "exact_name":
        results = cache.exact_name_search(
            query,
            restrictions,
            belongs_to,
            kinds=kinds,
            parent_hash=parent_hash,
            limit=limit,
        )
        return _exact_results_with_permissions(results, user)

    results, _ = cache.search(
        query,
        restrictions,
        belongs_to,
        kinds=kinds,
        limit=limit,
    )
    return [format_search_result(result) for result in results]


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_exact_name_search_is_parent_scoped_and_returns_permissions
# @matrix ai search : exact-name parent-scope permissions
def _exact_results_with_permissions(results, user):
    entities = Entities.fetch(
        *[result.get("id") for result in results if result.get("id")],
        request=Fetch.direct(),
    )
    by_id = {entity.urlsafe_key: entity for entity in entities if entity}
    formatted = []
    for result in results:
        entity = by_id.get(result.get("id"))
        if not entity:
            continue
        item = format_search_result(result)
        item["permissions"] = {
            "can_view": entity.allowed(Action.VIEW, user=user),
            "can_edit": entity.allowed(Action.EDIT, user=user),
            "can_create": entity.allowed(Action.CREATE, user=user),
        }
        formatted.append(item)
    return formatted


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_search_entity_filter_arguments
# @pair ai:search-filter
def _search_kinds(value):
    if value is None:
        return None, []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        value = [value]

    kinds = []
    invalid = []
    for kind in value:
        if not isinstance(kind, str):
            invalid.append(str(kind))
            continue
        normalized = SEARCH_KIND_ALIASES.get(kind.strip().lower())
        if normalized:
            kinds.append(normalized)
        else:
            invalid.append(kind)

    if invalid:
        return None, invalid
    kinds = list(dict.fromkeys(kinds))
    return kinds or None, []


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_search_entity_filter_arguments
# @pair ai:search-limit
def _search_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = SEARCH_LIMIT
    return max(1, min(limit, MAX_SEARCH_LIMIT))
