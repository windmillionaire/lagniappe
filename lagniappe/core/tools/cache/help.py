"""Versioned help projections in the existing workspace search index."""

import time
from typing import TypedDict, cast

from redis.commands.search.query import Query
from redis.exceptions import ResponseError

from lagniappe.reference import help_version, topics
from .core import cache
from .keys import HELP_PREFIX, SEARCH_SCORE_FIELD, Keys

class _IndexInfo(TypedDict):
    index_definition: dict[str, list[str]] | list
    attributes: list[dict[str, str] | list]
    indexing: str | int


HELP_SCORE = 0.60
READY_TIMEOUT = 30


def _decoded(value):
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, list):
        return [_decoded(item) for item in value]
    if isinstance(value, dict):
        return {_decoded(key): _decoded(item) for key, item in value.items()}
    return value


def _supports_help() -> bool:
    try:
        info = cast(_IndexInfo, _decoded(cache.redis.ft(cache.INDEX).info()))
    except ResponseError as error:
        if any(message in str(error).lower() for message in ("unknown index", "no such index", "index not found")):
            return False
        raise
    raw_definition = info["index_definition"]
    definition = raw_definition if isinstance(raw_definition, dict) else dict(zip(raw_definition[::2], raw_definition[1::2], strict=False))
    attributes = [row if isinstance(row, dict) else dict(zip(row[::2], row[1::2], strict=False)) for row in info["attributes"]]
    indexed_attributes = {field.get("attribute") for field in attributes}
    return HELP_PREFIX in definition.get("prefixes", []) and {"help_version", "keywords"} <= indexed_attributes


def ensure_help_index() -> None:
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


def _wait_ready(*, version: str | None = None, count: int | None = None) -> None:
    deadline = time.monotonic() + READY_TIMEOUT
    while True:
        info = cast(_IndexInfo, _decoded(cache.redis.ft(cache.INDEX).info()))
        if not int(info.get("indexing", 0)):
            if version is None:
                return
            result = cache.search(Query(help_clause(version)).no_content().paging(0, 0).dialect(2))
            if result.total == count:
                return
        if time.monotonic() >= deadline:
            raise TimeoutError("Help search index is still rebuilding; retry shortly.")
        time.sleep(0.05)


def help_clause(version: str) -> str:
    return f"(@kind:{{ help }} @help_version:{{ {version} }})"


def ensure_help() -> str:
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
                    "name": topic.title, "keywords": " ".join(topic.keywords),
                    "desc": topic.summary, "doc": topic.text,
                    SEARCH_SCORE_FIELD: HELP_SCORE,
                })
            pipe.execute()
        _wait_ready(version=version, count=len(corpus))
        cache.redis.set(ready_key, "ready")
    return version
