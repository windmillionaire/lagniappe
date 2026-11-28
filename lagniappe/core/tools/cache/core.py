"""Redis cache clients for hash-based (search) and JSON-based (filter) entity storage."""

from collections.abc import Collection, Iterable, Mapping
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import redis
from redis import Redis, ResponseError
from redis.client import Pipeline
from redis.commands.search.aggregation import AggregateRequest, AggregateResult
from redis.commands.search.field import NumericField, TagField, TextField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from redis.commands.search.result import Result

from config.redis import redis_connection_kwargs
from lagniappe import CONFIG, Config
from lagniappe.core.exceptions import capture
from ..auth.restrictions import RESTRICTION_SOURCES

from .keys import HELP_PREFIX, SEARCH_SCORE_FIELD, Keys, Search


if TYPE_CHECKING:
    from redis.commands.json._util import JsonType


def _create_redis_client(settings: Config = CONFIG) -> Redis:
    """Create the shared runtime Redis client from application settings."""
    client = redis.Redis(
        **redis_connection_kwargs(
            settings,
            decode_responses=False,
        )
    )
    if getattr(settings, "EXPERIMENTS_ENABLED", False) and settings.EXPERIMENTS_DIAGNOSTICS != "off":
        from lagniappe.core.tools.measurements import instrument_redis
        instrument_redis(client)
    return client


def _query_context(query):
    """Extract readable context from a RediSearch Query object."""
    if isinstance(query, Query):
        return {
            "query_string": query._query_string,
            "filters": [str(f) for f in getattr(query, "_filters", [])],
            "offset": getattr(query, "_offset", None),
            "num": getattr(query, "_num", None),
            "sort_by": getattr(query, "_sortby", None),
        }
    return {"query": str(query)}


class Cache:
    """Redis hash cache client with full-text search indexing."""

    def __init__(self) -> None:
        self._redis: Redis | None = None
        self.INDEX = Keys.SEARCH_INDEX.value

    @property
    def redis(self) -> Redis:
        """Return the Redis connection, initializing if needed."""
        if not self._redis:
            self.initialize()

        assert self._redis is not None
        return self._redis

    def initialize(self) -> None:
        """Establish the Redis connection pool."""
        if self._redis:
            return

        self._redis = _create_redis_client()

    def create_index(self) -> None:
        """Create the RediSearch full-text index if it doesn't exist."""
        try:
            self.redis.ft(self.INDEX).info()
        except ResponseError as error:
            if not any(message in str(error).lower() for message in ("unknown index", "no such index", "index not found")):
                raise
            schema = (
                TextField("name", weight=4, sortable=True),
                TextField("keywords", weight=2, sortable=True),
                TextField("desc", weight=1, sortable=True),
                TextField("doc", weight=0.5, sortable=True),
                TextField("values", weight=0.25, sortable=True),
                TagField("details_key", sortable=True, no_index=True),
                TagField("kind"),
                TagField("help_version"),
                TagField("type"),
                TagField("requires", index_empty=True),
                *(TagField(f"restricted_to_{source}", index_missing=True)
                  for source in RESTRICTION_SOURCES),
            )
            definition = IndexDefinition(
                index_type=IndexType.HASH,
                prefix=[kind.value.format("") for kind in Search if kind.value] + [HELP_PREFIX],
                score_field=SEARCH_SCORE_FIELD,
            )
            try:
                self.redis.ft(self.INDEX).create_index(list(schema), definition=definition)
            except ResponseError as error:
                if "index already exists" not in str(error).lower():
                    raise

    def flush(self) -> None:
        """Flush the entire Redis database."""
        self.redis.flushdb()

    def pipeline(self) -> Pipeline:
        """Return a new Redis pipeline."""
        return self.redis.pipeline()

    def delete(self, *keys: str | bytes) -> None:
        """Delete one or more keys in a pipeline."""
        with self.redis.pipeline() as pipe:
            pipe.delete(*keys)
            pipe.execute()

    def get(self, key: str | bytes) -> str | None:
        """Return the decoded string value for a key, or None."""
        # This client is constructed with decode_responses=False.
        value = cast(bytes | None, self.redis.get(key))
        return value.decode("utf-8") if value else None

    def hget(self, key: str, field: str, expires: int | timedelta | None = None) -> str | None:
        """Return a decoded hash field value, optionally refreshing expiry."""
        with self.pipeline() as pipe:
            pipe.hget(key, field)
            if expires:
                pipe.expire(key, expires)
            result = pipe.execute()

        value = result[0]
        return value.decode("utf-8") if value else None

    def hgetall(self, key: str, expires: int | timedelta | None = None) -> dict[str, str]:
        """Return all hash fields as a decoded dict, optionally refreshing expiry."""
        with self.pipeline() as pipe:
            pipe.hgetall(key)
            if expires:
                pipe.expire(key, expires)
            result = pipe.execute()
        return {k.decode("utf-8"): v.decode("utf-8") for k, v in result[0].items()}

    def keys(self, pattern: str) -> list[bytes]:
        """Return all keys matching the given pattern."""
        return cast(list[bytes], self.redis.keys(pattern))  # Response decoding is disabled.

    def drop_index(self, index: str) -> None:
        """Drop a RediSearch index."""
        self.redis.ft(index).dropindex()

    def search(self, query: Query | str) -> Result:
        """Execute a RediSearch query against the primary index."""
        try:
            # A synchronous search on a client returns Result. The SDK also types pipelines and profiles here.
            return cast(Result, self.redis.ft(self.INDEX).search(query))
        except ResponseError as e:
            capture(
                e,
                context={
                    "method": "search",
                    "index": self.INDEX,
                    "error": str(e),
                    **_query_context(query),
                },
            )
            raise e

    def aggregate(self, query: AggregateRequest) -> AggregateResult:
        """Execute a RediSearch aggregation query against the primary index."""
        try:
            return cast(AggregateResult, self.redis.ft(self.INDEX).aggregate(query))
        except ResponseError as e:
            capture(
                e,
                context={
                    "method": "aggregate",
                    "index": self.INDEX,
                    "error": str(e),
                },
            )
            raise e

    def hmget(self, key: str, fields: Iterable[str]) -> list[bytes | None]:
        """Return values for multiple hash fields."""
        try:
            return cast(list[bytes | None], self.redis.hmget(key, fields))  # Response decoding is disabled.
        except ResponseError as e:
            capture(
                e,
                context={
                    "method": "hmget",
                    "key": key,
                    "fields": fields,
                    "error": str(e),
                },
            )
            raise e


cache = Cache()


class CacheJSON:
    """Redis JSON cache client for filter and relationship data."""

    ttl = timedelta(days=1)

    def __init__(self) -> None:
        self._redis: Redis | None = None
        self.INDEX = Keys.JSON_INDEX.value

    @property
    def redis(self) -> Redis:
        """Return the Redis connection, initializing if needed."""
        if not self._redis:
            self.initialize()

        assert self._redis is not None
        return self._redis

    def initialize(self) -> None:
        """Bind to the shared Redis connection from the hash cache."""
        self._redis = cache.redis

    def create_index(self) -> None:
        """Create the JSON search index if it doesn't exist."""
        try:
            self.redis.ft(self.INDEX).info()
        except ResponseError:
            schema = (
                TagField("$.access.hash", as_name="hash"),
                TagField("$..cache_key", as_name="cache_key"),
                NumericField("$..refresh", as_name="refresh"),
            )
            definition = IndexDefinition(
                index_type=IndexType.JSON,
                prefix=[f"{CONFIG.PREFIX}JSON:"],
            )
            with suppress(ResponseError):
                self.redis.ft(self.INDEX).create_index(list(schema), definition=definition)

    def delete(self, key: str) -> None:
        """Delete a JSON key."""
        self.redis.json().delete(key)

    def get(self, key: str) -> JsonType:
        """Return the JSON value for a key."""
        return self.redis.json().get(key)

    def exists(self, key: str) -> int:
        """Check whether a key exists."""
        return self.redis.exists(key)

    def search(self, query: Query | str) -> Result:
        """Execute a RediSearch query against the JSON index."""
        try:
            # A synchronous search on a client returns Result. The SDK also types pipelines and profiles here.
            return cast(Result, self.redis.ft(self.INDEX).search(query))
        except ResponseError as e:
            capture(
                e,
                context={
                    "method": "search",
                    "index": self.INDEX,
                    "error": str(e),
                    **_query_context(query),
                },
            )
            raise e

    def create(self, key: str, mapping: dict[str, JsonType]) -> None:
        """Store a JSON document with an access hash and one-day expiry."""
        parent_hash = key.rsplit(":", 2)[-2]
        mapping["access"] = {"hash": parent_hash}
        try:
            self.redis.json().set(key, "$", mapping)
        except ResponseError as e:
            capture(e, context={"method": "create", "key": key, "mapping": mapping})
            raise e
        self.redis.expire(key, self.ttl)

    def query(self, key: str, json_path: str) -> JsonType:
        """Return a JSON value at a specific path within a key."""
        try:
            return self.redis.json().get(key, f"{json_path}")
        except ResponseError as e:
            capture(e, context={"method": "query", "key": key, "json_path": json_path})
            raise e

    def set(self, key: str, mapping: Mapping[str, JsonType]) -> None:
        """Update multiple JSON fields on a key and refresh expiry."""
        triplets: list[tuple[str, str, JsonType]] = [(key, f"$.{k}", v) for k, v in mapping.items()]
        if triplets:
            try:
                self.redis.json().mset(triplets)
            except ResponseError as e:
                capture(e, context={"method": "set", "key": key, "mapping": mapping})
                raise e
            self.redis.expire(key, self.ttl)

    def refresh_needed(self, cache_key: str) -> list[str]:
        """Get member IDs within a specific JSON object that have refresh stubs"""
        # Use JSON path to get all members where refresh=1, then extract their ids
        refresh_members = self.redis.json().get(cache_key, "$[?(@.refresh == 1)].id")
        # This JSONPath selects only identifiers from persisted refresh markers.
        return cast(list[str], refresh_members) if refresh_members else []

    def _parent_ids(self, query: Query, result: Result) -> list[str]:
        # RediSearch returns ten documents by default. A category-backed Page
        # or a batch spanning Projects can match more parent caches.
        if result.total > len(result.docs):
            result = self.search(query.paging(0, result.total))
        return [doc.id for doc in result.docs]

    def get_existing_parents(self, hashes: Collection[str]) -> dict[str, list[str]]:
        """Return a mapping of hashes to their parent JSON key IDs."""
        queries = {h: Query(f"@cache_key:{{{h}}}").no_content() for h in hashes}
        with self.redis.pipeline() as pipe:
            for query in queries.values():
                pipe.ft(self.INDEX).search(query)
            results = pipe.execute()

        parents = {}
        for (entity_hash, query), raw in zip(queries.items(), results, strict=True):
            result = Result.from_resp3(raw) if isinstance(raw, dict) else Result(raw, hascontent=False)
            if result.docs:
                parents[entity_hash] = self._parent_ids(query, result)
        return parents

    def get_new_parents(self, parent_hashes: Iterable[str]) -> list[str]:
        """Return JSON key IDs for parents matching the given hashes."""
        parent_hashes = list(parent_hashes)
        if not parent_hashes:
            return []

        query = Query(f"@hash:{{ {' | '.join(parent_hashes)} }}").no_content()
        return self._parent_ids(query, self.search(query))


filter_cache = CacheJSON()


def initialize() -> None:
    """Initialize both cache clients and create their search indexes."""
    cache.initialize()
    filter_cache.initialize()

    cache.create_index()
    filter_cache.create_index()
    from .help import ensure_help

    ensure_help()
