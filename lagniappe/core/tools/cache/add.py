"""Cache write operations for entity hash and JSON index updates."""

from collections.abc import Collection
from typing import TYPE_CHECKING, cast
from redis.typing import EncodableT, FieldT

if TYPE_CHECKING:
    from ...entities.entity import Entity

import json

from .core import cache, filter_cache
from .keys import SEARCH_SCORE_FIELD, Keys, Search
from ...definitions.fingerprints import base_fingerprint
from ..auth.restrictions import normalize_restrictions

DEFAULT_SEARCH_SCORE = "0.75"
KIND_SEARCH_SCORES = {
    "category": "1.0",
    "page": "1.0",
    "project": "0.95",
    "task": "0.65",
    "model": "0.65",
    "file": "0.55",
}

# Only revision validity changes: preserve cached display/permission fields,
# including any concurrent refresh, and never create an incomplete cache row.
_INVALIDATE_REVISIONS = """
for _, field in ipairs(ARGV) do
    local value = redis.call('HGET', KEYS[1], field)
    if value then
        local row = cjson.decode(value)
        if not row.revision_stale then
            -- Append to the serialized root object, retaining JSON arrays
            -- exactly (Lua cjson re-encodes empty arrays as objects).
            local separator = next(row) and ',' or ''
            local marked = string.gsub(value, '}%s*$', separator .. '"revision_stale":true}', 1)
            redis.call('HSET', KEYS[1], field, marked)
        end
    end
end
"""


def invalidate_revisions(*entities: Entity) -> None:
    """Invalidate modified-only owners without rebuilding their relation graph."""
    owners = {entity.hash: entity for entity in entities if entity.hash}
    if not owners:
        return
    parents = filter_cache.get_existing_parents(owners.keys())
    with cache.pipeline() as pipe:
        pipe.eval(_INVALIDATE_REVISIONS, 1, Keys.ENTITY_HASHES.value, *owners)
        for entity_hash, indexes in parents.items():
            for index in indexes:
                pipe.json().set(
                    index, f"$.{entity_hash}",
                    {"refresh": 1, "id": owners[entity_hash].urlsafe_key, "cache_key": entity_hash},
                    xx=True,
                )
        pipe.execute()


def _escape_pipe(text):
    """Escape only pipe and backslash for safe joining/splitting."""
    if not isinstance(text, str):
        return "" if text is None else str(text)
    # First escape backslashes, then pipes
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _redis_details(entity):
    """Return entity details as Redis stores them, with parent represented by hash."""
    details = dict(entity.details)
    parent = details.pop("parent", None)
    if isinstance(parent, dict) and parent.get("hash"):
        details["parent_key"] = parent["hash"]
    kind = entity.entity_kind
    modified = getattr(entity, "modified", None)
    if modified:
        details["modified"] = base_fingerprint(modified)
    details["fingerprint"] = entity.fingerprint
    restrictions = normalize_restrictions(getattr(entity, "restricted_to", None))
    if restrictions:
        details["restricted_to"] = restrictions
    else:
        details.pop("restricted_to", None)
    if kind == "form":
        details["form_version"] = entity.version or ""
    elif kind in {"page", "task"}:
        form = entity.form
        details["form_version"] = (form.version or "") if form else ""
        if form is None and getattr(entity, "db", {}).get("form"):
            details.pop("form_hash", None)
        else:
            details["form_hash"] = form.hash if form and not form.reserved else None
    if kind == "file":
        owner = entity.owner
        if owner:
            details["parent_key"] = owner.hash
    return details


def _kind_search_score(kind):
    """Return the RediSearch document score for an entity kind."""
    return KIND_SEARCH_SCORES.get(kind, DEFAULT_SEARCH_SCORE)


def delete_entity_from_search(kind: str, entity: Entity) -> None:
    """Delete an entity from the search index."""
    key = Search[kind].key(entity)
    if not key:
        return
    cache.delete(key)


def update(*entities: Entity, update: bool = True) -> None:
    """Write entity data to the hash cache and update JSON indexes."""
    cacheable = [e for e in entities if getattr(e, "to_cache", None)]
    if not cacheable:
        return

    update_json = []

    with cache.pipeline() as pipe:
        for entity in cacheable:
            cache_map = dict(entity.to_cache)
            cache_map.pop("details", None)

            key = Search[cast(str, cache_map["kind"])].key(entity)
            if not key:
                continue
            pipe.delete(key)

            if getattr(entity, "searchable", True) is False:
                if entity.hash:
                    pipe.hset(
                        Keys.ENTITY_HASHES.value,
                        entity.hash,
                        json.dumps(_redis_details(entity)),
                    )
                continue

            if not cache_map.get("name"):
                continue

            cache_map[SEARCH_SCORE_FIELD] = _kind_search_score(cache_map["kind"])

            if cache_map.get("keys") and cache_map.get("values"):
                cache_map["keys"] = "|".join(
                    _escape_pipe(k) for k in cast(list[str], cache_map["keys"])
                )
                cache_map["values"] = "|".join(
                    _escape_pipe(v) for v in cast(list[str], cache_map["values"])
                )

            # Form search lists have been encoded above. All remaining Redis fields are scalar.
            pipe.hset(key, mapping=cast(dict[FieldT, EncodableT], cache_map))

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


def update_json_index(entities: Collection[Entity]) -> None:
    """Propagate entity changes to parent JSON filter indexes."""
    if not entities:
        return

    entity_hash_map = {entity.hash: entity for entity in entities}
    members: dict[str, set[str]] = {}
    for entity in entities:
        if entity.kind == "task":
            if project := getattr(entity, "project", None):
                members.setdefault(project.hash, set()).add(entity.hash)
        elif entity.kind == "page":
            for category in getattr(entity, "categories", ()):
                members.setdefault(category.hash, set()).add(entity.hash)

    existing = filter_cache.get_existing_parents(entity_hash_map.keys())
    indexes = set(filter_cache.get_new_parents(members))
    for keys in existing.values():
        indexes.update(keys)
    if not indexes:
        return

    with cache.pipeline() as pipe:
        for key in indexes:
            parent_hash = key.rsplit(":", 2)[-2]
            current = members.get(parent_hash, set())
            for entity_hash in current:
                entity = entity_hash_map[entity_hash]
                pipe.json().set(key, f"$.{entity_hash}", {
                    "refresh": 1, "id": entity.urlsafe_key, "cache_key": entity_hash,
                })
            for entity_hash, keys in existing.items():
                if key in keys and entity_hash not in current:
                    pipe.json().delete(key, f"$.{entity_hash}")
        pipe.execute()
