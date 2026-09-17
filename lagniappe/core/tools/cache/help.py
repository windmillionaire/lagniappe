"""Versioned help projections in the existing workspace search index."""

import time

from redis.commands.search.query import Query
from redis.exceptions import ResponseError

from lagniappe.reference import help_version, topics
from .core import cache
from .keys import HELP_PREFIX, SEARCH_SCORE_FIELD, Keys

HELP_SCORE = 0.60
READY_TIMEOUT = 30


# @testable false
# @covered-by lagniappe/core/tools/cache/help.py::ensure_help_index
# @reason Redis metadata uses byte values even when its outer keys are decoded
def _decoded(value):
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, list):
        return [_decoded(item) for item in value]
    if isinstance(value, dict):
        return {_decoded(key): _decoded(item) for key, item in value.items()}
    return value


# @testable false
# @covered-by lagniappe/core/tools/cache/help.py::ensure_help_index
# @reason inspecting the primary schema gates its one-time migration
def _supports_help():
    try:
        info = _decoded(cache.redis.ft(cache.INDEX).info())
    except ResponseError as error:
        if any(message in str(error).lower() for message in ("unknown index", "no such index", "index not found")):
            return False
        raise
    raw_definition = info["index_definition"]
    definition = raw_definition if isinstance(raw_definition, dict) else dict(zip(raw_definition[::2], raw_definition[1::2]))
    attributes = [row if isinstance(row, dict) else dict(zip(row[::2], row[1::2])) for row in info["attributes"]]
    return HELP_PREFIX in definition.get("prefixes", []) and any(
        field.get("attribute") == "help_version" for field in attributes
    )


# @testable true
# @tests tests_unit/test_035_help.py::test_index_upgrade_preserves_hashes_and_is_serialized
# @tests tests_unit/test_035_help.py::test_index_upgrade_does_not_hide_provider_failures
# @matrix help : index-upgrade provider-failure
def ensure_help_index():
    """Extend an old index's prefix set without deleting its underlying data."""
    if _supports_help():
        return
    with cache.redis.lock(Keys.SEARCH_INDEX_LOCK.value, timeout=60, blocking_timeout=READY_TIMEOUT):
        if _supports_help():
            return
        try:
            cache.redis.ft(cache.INDEX).dropindex(delete_documents=False)
        except ResponseError as error:
            if not any(message in str(error).lower() for message in ("unknown index", "no such index", "index not found")):
                raise
        cache.create_index()
        _wait_ready()


# @testable false
# @covered-by lagniappe/core/tools/cache/help.py::ensure_help
# @covered-by lagniappe/core/tools/cache/help.py::ensure_help_index
# @reason bounded indexing readiness is part of publishing the version marker
def _wait_ready(*, version=None, count=None):
    deadline = time.monotonic() + READY_TIMEOUT
    while True:
        info = _decoded(cache.redis.ft(cache.INDEX).info())
        if not int(info.get("indexing", 0)):
            if version is None:
                return
            result = cache.search(Query(help_clause(version)).no_content().paging(0, 0).dialect(2))
            if result.total == count:
                return
        if time.monotonic() >= deadline:
            raise TimeoutError("Help search index is still rebuilding; retry shortly.")
        time.sleep(0.05)


# @testable false
# @covered-by lagniappe/core/tools/cache/help.py::ensure_help
# @reason version filtering is shared by population verification and callers
def help_clause(version):
    return f"(@kind:{{ help }} @help_version:{{ {version} }})"


# @testable true
# @tests tests_unit/test_035_help.py::test_population_is_versioned_atomic_and_skips_warm_start
# @tests tests_unit/test_035_help.py::test_failed_population_is_retryable_and_cache_loss_repopulates
# @tests tests_unit/test_035_help.py::test_population_rechecks_readiness_after_lock
# @matrix help : publication version cache-recovery
def ensure_help():
    """Publish a complete source version once per Redis namespace."""
    version = help_version()
    ready_key = Keys.HELP_READY.value.format(version)
    if cache.redis.get(ready_key):
        return version
    with cache.redis.lock(Keys.HELP_LOCK.value.format(version), timeout=60, blocking_timeout=READY_TIMEOUT):
        if cache.redis.get(ready_key):
            return version
        ensure_help_index()
        corpus = topics()
        with cache.pipeline() as pipe:
            for topic in corpus.values():
                pipe.hset(f"{HELP_PREFIX}{version}:{topic.id}", mapping={
                    "kind": "help", "topic_id": topic.id, "help_version": version,
                    "name": topic.title, "desc": topic.summary, "doc": topic.text,
                    SEARCH_SCORE_FIELD: HELP_SCORE,
                })
            pipe.execute()
        _wait_ready(version=version, count=len(corpus))
        cache.redis.set(ready_key, "ready")
    return version
