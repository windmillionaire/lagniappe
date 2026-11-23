"""Function declaration and handler for workspace entity search."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...cache.details import SearchRecord
    from lagniappe.core.entities.user import User

from google.genai import types

from lagniappe.core.definitions import Action, Fetch, FetchReason, SearchFacets
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache

SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 25
SEARCH_KIND_ALIASES = {
    facet.value.kind: facet.value.kind
    for facet in SearchFacets
    if facet.value.kind != "help"
}
SEARCH_KIND_ALIASES.update(
    {
        facet.value.name: facet.value.kind
        for facet in SearchFacets
        if facet.value.kind != "help"
    }
)
SEARCH_KIND_ALIASES["model"] = "model"
ALLOWED_SEARCH_KINDS = tuple(sorted(SEARCH_KIND_ALIASES))
SEARCH_MATCH_MODES = ("keywords", "exact_name")
CANDIDATE_SEARCH_DESCRIPTION = (
    "Find visible workspace candidates by keywords or an approximate name. "
    "Returns bounded names, types, public references, parent context, matching "
    "snippets, and cached Task completion state. Sparse multiword keyword searches "
    "may include ranked any-term candidates; exact names and stronger matches "
    "rank first. Use one short discriminating query and compare these candidates "
    "before loading full content or schema only when needed. Results are already "
    "view-authorized; visibility does not imply edit/create permission. "
    "With kinds=[\"page\"], parent_id scopes candidates to a viewable Category. "
    "Use match_mode=exact_name only when full-name equality is required."
)


def entity_url(result: SearchRecord) -> str:
    entity_ref = result["id"]
    details = result.get("details")
    parent = result.get("parent")
    if parent is None and isinstance(details, dict):
        parent = details.get("parent")
    if result["kind"] == "category":
        return f"/categories/{entity_ref}"
    elif result["kind"] == "task" and "parent" in result:
        return f"/tasks/{entity_ref}"
    elif result["kind"] == "model" and parent:
        parent_ref = parent["id"]
        return (
            f"/projects/{parent_ref}/tasks/{entity_ref}?completed=false"
        )
    else:
        return f"/{result['kind']}s/{entity_ref}"


def format_search_result(result: SearchRecord) -> SearchRecord:
    formatted = dict(result)
    # Build browser links before projecting canonical IDs into tool references.
    formatted["url"] = entity_url(result)
    details = formatted.get("details")
    if isinstance(details, dict) and details.get("hash"):
        formatted["hash"] = f"hash:{details['hash']}"
    if (
        "parent" not in formatted
        and isinstance(details, dict)
        and details.get("parent")
    ):
        formatted["parent"] = _format_detail_hashes(details["parent"])
    if formatted.get("hash"):
        formatted.pop("id", None)
    formatted.pop("details", None)
    return formatted


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
    description=CANDIDATE_SEARCH_DESCRIPTION,
    parameters=types.Schema.model_validate({
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
                    "keywords returns bounded ranked candidates and may relax sparse "
                    "multiword queries; exact_name requires normalized full-name "
                    "equality. Defaults to keywords."
                ),
            },
            "parent_id": {
                "type": "string",
                "description": (
                    'Optional viewable Category hash token when kinds is exactly ["page"]. '
                    "Applies to keyword candidates and exact-name lookup."
                ),
            },
        },
        "required": ["query"],
    }),
)


def execute_search(args: Mapping[str, object], user: User, *, candidate_search: bool = False) -> Mapping[str, object] | list[dict[str, object]]:
    query = args.get("query", "")
    if not isinstance(query, str):
        return {"error": "query must be a string"}
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
    if parent_id := args.get("parent_id"):
        if (match_mode != "exact_name" and not candidate_search) or kinds != ["page"]:
            return {
                "error": (
                    "parent_id is supported only for "
                    + ("" if candidate_search else "exact_name ")
                    + "searches with "
                    "kinds=[\"page\"]."
                )
            }
        if not isinstance(parent_id, str):
            return {"error": "Parent Category not found."}
        parent = Entities.fetch_one(parent_id, request=Fetch.direct())
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

    if candidate_search:
        results = cache.candidate_search(
            query,
            restrictions,
            belongs_to,
            kinds=kinds,
            parent_hash=parent_hash,
            limit=limit,
        )
        formatted = []
        for result in results:
            item = format_search_result(result)
            if result.get("kind") == "task":
                # The existing cached details omit false values.
                item["completed"] = result.get("details", {}).get("completed") is True
            formatted.append(item)
        return formatted

    results, _ = cache.search(
        query,
        restrictions,
        belongs_to,
        kinds=kinds,
        limit=limit,
    )
    return [format_search_result(result) for result in results]


def _exact_results_with_permissions(results, user):
    entities = Entities.fetch(
        *[result.get("id") for result in results if result.get("id")],
        request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
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


def _search_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = SEARCH_LIMIT
    return max(1, min(limit, MAX_SEARCH_LIMIT))
