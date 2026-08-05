"""Cache utility functions for deletion and maintenance."""

from lagniappe import CONFIG
from redis import ResponseError

from .core import cache, filter_cache
from .keys import Keys, Search

MISSING_INDEX_MESSAGES = (
    "unknown index name",
    "no such index",
    "index not found",
)


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
# @tests tests_unit/test_017_cache_query.py::test_delete_cache_flushes_db_and_recreates_indexes
# @tests tests_unit/test_017_cache_query.py::test_delete_cache_clears_only_prefixed_keys_and_recreates_indexes
# @features cache
# @dimensions redis-connection rebuild flush-db prefix-isolation
def delete_cache():
    """Clear this environment's cache and recreate its search indexes."""
    if CONFIG.PREFIX:
        cleanup_test_data()
    else:
        cache.flush()
    cache.create_index()
    filter_cache.create_index()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
# @tests tests_unit/test_017_cache_query.py::test_cleanup_test_data_ignores_redis_missing_search_index_errors
# @tests tests_unit/test_017_cache_query.py::test_cleanup_test_data_reraises_unexpected_drop_index_errors
# @features cache
# @dimensions cleanup index-recreation missing-search-index redis-errors
def cleanup_test_data():
    """Delete all keys and search indexes scoped to the configured prefix."""
    if not CONFIG.PREFIX:
        return

    pattern = f"{CONFIG.PREFIX}*"
    keys = cache.keys(pattern)
    if keys:
        cache.delete(*keys)

    _drop_index_if_exists(cache.INDEX)
    _drop_index_if_exists(filter_cache.INDEX)


# @testable false
# @covered-by lagniappe/core/tools/cache/utility.py::cleanup_test_data
# @reason missing-index handling is part of cleanup_test_data
def _drop_index_if_exists(index):
    try:
        cache.drop_index(index)
    except ResponseError as exc:
        message = str(exc).lower()
        if any(text in message for text in MISSING_INDEX_MESSAGES):
            return
        raise


# @testable infrastructure
def delete(entities):
    """Remove entities from both the hash cache and parent JSON indexes."""
    hash_map = {e.hash: e for e in entities if e and e.hash}
    existing_parents = filter_cache.get_existing_parents(hash_map.keys())

    entity_keys = set([Search[e.kind].key(e) for e in entities if e])

    if not entity_keys and not existing_parents:
        return

    with cache.pipeline() as pipe:
        to_delete = [k for k in entity_keys if k]
        if to_delete:
            pipe.delete(*to_delete)

        hashed_entities = [e for e in entities if e and e.hash]
        for e in hashed_entities:
            pipe.hdel(Keys.ENTITY_HASHES.value, e.hash)

        for h, parents in existing_parents.items():
            for parent_key in parents:
                pipe.json().delete(parent_key, f"$.{h}")

        pipe.execute()


# @testable false
# @covered-by lagniappe/core/properties/common_entity.py::Hash
# @reason collision check when generating entity hashes
def check_hash(hash):
    """Return whether a hash exists in the entity hash index."""
    return bool(cache.hget(Keys.ENTITY_HASHES.value, hash))
