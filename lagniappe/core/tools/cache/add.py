"""Cache write operations for entity hash and JSON index updates."""

import json

from .core import cache, filter_cache
from .keys import SEARCH_SCORE_FIELD, Keys, Search

DEFAULT_SEARCH_SCORE = "0.75"
KIND_SEARCH_SCORES = {
    "category": "1.0",
    "page": "1.0",
    "project": "0.95",
    "task": "0.65",
    "model": "0.65",
    "file": "0.55",
}


# @testable false
# @covered-by lagniappe/core/tools/cache/query.py::_add_snippet
# @reason cache-write escaping is read back through search snippet formatting
def _escape_pipe(text):
    """Escape only pipe and backslash for safe joining/splitting."""
    if not isinstance(text, str):
        return "" if text is None else str(text)
    # First escape backslashes, then pipes
    return text.replace("\\", "\\\\").replace("|", "\\|")


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_redis_details_store_parent_key_not_parent_blob
# @matrix cache : details parent-key redis-storage
def _redis_details(entity):
    """Return entity details as Redis stores them, with parent represented by hash."""
    details = dict(entity.details)
    parent = details.pop("parent", None)
    if isinstance(parent, dict) and parent.get("hash"):
        details["parent_key"] = parent["hash"]
    return details


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_kind_search_score_prioritizes_high_level_entities
# @matrix cache : kind-score search-ranking
def _kind_search_score(kind):
    """Return the RediSearch document score for an entity kind."""
    return KIND_SEARCH_SCORES.get(kind, DEFAULT_SEARCH_SCORE)


# @testable infrastructure
def delete_entity_from_search(kind, entity):
    """Delete an entity from the search index."""
    key = Search[kind].key(entity)
    if not key:
        return
    cache.delete(key)


# @testable infrastructure
def update(*entities, update=True):
    """Write entity data to the hash cache and update JSON indexes."""
    cacheable = [e for e in entities if getattr(e, "to_cache", None)]
    if not cacheable:
        return

    update_json = []

    with cache.pipeline() as pipe:
        for entity in cacheable:
            cache_map = dict(entity.to_cache)
            cache_map.pop("details", None)

            key = Search[cache_map["kind"]].key(entity)
            if not key:
                continue
            pipe.delete(key)

            if not cache_map.get("name"):
                continue

            cache_map[SEARCH_SCORE_FIELD] = _kind_search_score(cache_map["kind"])

            if cache_map.get("keys") and cache_map.get("values"):
                cache_map["keys"] = "|".join(
                    _escape_pipe(k) for k in cache_map.get("keys")
                )
                cache_map["values"] = "|".join(
                    _escape_pipe(v) for v in cache_map.get("values")
                )

            pipe.hset(key, mapping=cache_map)

            if entity.hash:
                pipe.hset(
                    Keys.ENTITY_HASHES.value,
                    entity.hash,
                    json.dumps(_redis_details(entity)),
                )

            if entity.kind in ["page", "task"] and update:
                update_json.append(entity)

        pipe.execute()

    update_json_index(update_json)


# @testable infrastructure
def update_json_index(entities):
    """Propagate entity changes to parent JSON filter indexes."""
    if not entities:
        return

    # Get existing parents that have active indexes
    entity_hash_map = {e.hash: e for e in entities}
    existing_parents = filter_cache.get_existing_parents(entity_hash_map.keys())

    parents = {}
    for entity_hash, parent_keys in existing_parents.items():
        for p in parent_keys:
            parent_hash = p.split(":")[1]
            parent_ops = parents.setdefault(
                parent_hash, {"cache_key": p, "remove": [], "update": []}
            )
            if parent_hash not in entity_hash_map[entity_hash].required:
                parent_ops["remove"].append(entity_hash)
            else:
                parent_ops["update"].append(entity_hash)

    # If a parent was added, get the new parents that have active indexes
    new_parents = {}
    for e in entities:
        project = getattr(e, "project", None)
        if project and project.hash not in parents.keys():
            new_parents.setdefault(e.project.hash, []).append(e.hash)

        categories = [c.hash for c in getattr(e, "categories", [])]
        for h in [h for h in categories if h not in parents.keys()]:
            new_parents.setdefault(h, []).append(e.hash)

    if not new_parents and not parents:
        return

    for p in filter_cache.get_new_parents(new_parents.keys()):
        parent_hash = p.split(":")[1]
        parent_ops = parents.setdefault(parent_hash, {"cache_key": p, "update": []})
        parent_ops["update"].extend(new_parents[parent_hash])

    with cache.pipeline() as pipe:
        for parent_hash, parent_ops in parents.items():
            for h in parent_ops["update"]:
                pipe.json().set(
                    parent_ops["cache_key"],
                    f"$.{h}",
                    {"refresh": 1, "id": entity_hash_map[h].urlsafe_key},
                )
            for h in parent_ops.get("remove", []):
                pipe.json().delete(parent_ops["cache_key"], f"$.{h}")

        pipe.execute()
