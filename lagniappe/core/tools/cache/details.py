"""Cached entity detail retrieval and parent hydration."""

import json

from .core import cache
from .keys import Keys

DETAIL_HASH_DISALLOWED = frozenset(
    {"users", "models", "forms", "categories", "projects", "tasks"}
)


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_get_details_by_hash_hydrates_parent_and_hides_internal_keys
# @matrix cache : details-hydration missing-parent parent-key string-input
def get_details_by_hash(hashes):
    """Return cached entity details by hash, hydrating parent pointers."""
    requested_hashes = _detail_hashes(hashes)
    if not requested_hashes:
        return {}

    details = _load_cached_details(requested_hashes)
    parent_hashes = _detail_hashes(
        details_item.get("parent_key") for details_item in details.values()
    )
    missing_parent_hashes = [
        parent_hash for parent_hash in parent_hashes if parent_hash not in details
    ]
    if missing_parent_hashes:
        details.update(_load_cached_details(missing_parent_hashes))

    return _hydrate_details(details, requested_hashes)


# @testable false
# @covered-by lagniappe/core/tools/cache/details.py::get_details_by_hash
# @reason hash normalization is owned by cached detail lookup
def _detail_hashes(hashes):
    """Return a stable list of real entity hashes from hash input."""
    if hashes is None:
        return []
    if isinstance(hashes, str):
        hashes = [hashes]

    return [
        h
        for h in dict.fromkeys(h for h in hashes if h)
        if h not in DETAIL_HASH_DISALLOWED
    ]


# @testable false
# @covered-by lagniappe/core/tools/cache/details.py::get_details_by_hash
# @reason raw Redis reads are normalized and hydrated by cached detail lookup
def _load_cached_details(hashes):
    if not hashes:
        return {}

    names = cache.hmget(Keys.ENTITY_HASHES.value, hashes)
    return {
        h: _redis_detail(json.loads(names[i]))
        for i, h in enumerate(hashes)
        if names[i]
    }


# @testable false
# @covered-by lagniappe/core/tools/cache/details.py::get_details_by_hash
# @reason Redis detail storage is parent-free after cache rebuilds
def _redis_detail(details):
    return dict(details)


# @testable false
# @covered-by lagniappe/core/tools/cache/details.py::get_details_by_hash
# @reason parent hydration is owned by cached detail lookup
def _hydrate_details(details, requested_hashes):
    hydrated = {}
    for h in requested_hashes:
        details_item = details.get(h)
        if not details_item:
            continue

        hydrated_item = dict(details_item)
        parent_key = hydrated_item.pop("parent_key", None)
        parent = details.get(parent_key)
        if parent:
            hydrated_parent = dict(parent)
            hydrated_parent.pop("parent_key", None)
            hydrated_item["parent"] = hydrated_parent
        hydrated[h] = hydrated_item
    return hydrated


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_search_results_are_hydrated_from_details_hashes
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_result_parent_details_refresh_after_category_rename
# @matrix cache search : details-hydration parent-key parent-refresh snippets
def hydrate_search_results(results):
    """Attach hydrated details to formatted search results."""
    detail_hashes = []

    for result in results:
        details_key = result.get("details_key")
        parent_key = result.get("parent_key")
        if details_key:
            detail_hashes.append(details_key)
        if parent_key:
            detail_hashes.append(parent_key)

    hydrated_details = get_details_by_hash(detail_hashes)

    for result in results:
        details_key = result.pop("details_key", None)
        result.pop("parent_key", None)
        result["details"] = hydrated_details.get(details_key, {})

    return results
