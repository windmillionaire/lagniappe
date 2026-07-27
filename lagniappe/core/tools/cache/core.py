"""Redis cache clients for hash-based (search) and JSON-based (filter) entity storage."""

from datetime import timedelta

import redis
from redis import ResponseError
from redis.commands.search.field import NumericField, TagField, TextField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from config.redis import redis_client_kwargs
from lagniappe import CONFIG
from lagniappe.core.exceptions import capture

from .keys import SEARCH_SCORE_FIELD, Keys, Search


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_runtime_redis_client_uses_shared_tls_options
# @features cache
# @dimensions redis-connection redis-tls
def _create_redis_client(settings=CONFIG):
    """Create the shared runtime Redis client from application settings."""
    return redis.Redis(
        **redis_client_kwargs(
            settings,
            decode_responses=False,
        )
    )


# @testable false
# @reason used for error reporting
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


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
# @features cache
# @dimensions redis-connection
class Cache:
    """Redis hash cache client with full-text search indexing."""

    def __init__(self):
        self._redis = None
        self.INDEX = Keys.SEARCH_INDEX.value

    # @testable true
    # @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
    # @features cache
    # @dimensions redis-connection
    @property
    def redis(self):
        """Return the Redis connection, initializing if needed."""
        if not self._redis:
            self.initialize()

        return self._redis

    # @testable true
    # @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
    # @features cache
    # @dimensions redis-connection
    def initialize(self):
        """Establish the Redis connection pool."""
        if self._redis:
            return

        self._redis = _create_redis_client()

    # @testable true
    # @tests tests_unit/test_017_cache_query.py::test_search_index_indexes_empty_requires_tags
    # @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
    # @features cache
    # @dimensions index-schema redis-cloud tag-syntax empty-requires search-ranking index-recreation
    def create_index(self):
        """Create the RediSearch full-text index if it doesn't exist."""
        try:
            self.redis.ft(self.INDEX).info()
        except ResponseError:
            schema = (
                TextField("name", weight=4, sortable=True),
                TextField("desc", weight=1, sortable=True),
                TextField("doc", weight=0.5, sortable=True),
                TextField("values", weight=0.25, sortable=True),
                TagField("kind"),
                TagField("type"),
                TagField("requires", index_empty=True),
                TagField("restricted_to", index_missing=True),
            )
            definition = IndexDefinition(
                index_type=IndexType.HASH,
                prefix=[kind.value.format("") for kind in Search if kind.value],
                score_field=SEARCH_SCORE_FIELD,
            )
            try:
                self.redis.ft(self.INDEX).create_index(schema, definition=definition)
            except ResponseError:
                pass

    # @testable false
    # @covered-by lagniappe/core/tools/cache/utility.py::delete_cache
    # @reason maintenance api-wrapper owned by full cache reset workflow
    def flush(self):
        """Flush the entire Redis database."""
        self.redis.flushdb()

    # @testable false
    # @reason api-wrapper; callers own pipeline command semantics
    def pipeline(self):
        """Return a new Redis pipeline."""
        return self.redis.pipeline()

    # @testable false
    # @reason api-wrapper; callers own key selection and deletion workflow
    def delete(self, *keys):
        """Delete one or more keys in a pipeline."""
        with self.redis.pipeline() as pipe:
            pipe.delete(*keys)
            pipe.execute()

    # @testable false
    # @reason decoded Redis get wrapper used by provider-specific cache consumers
    def get(self, key):
        """Return the decoded string value for a key, or None."""
        value = self.redis.get(key)
        return value.decode("utf-8") if value else None

    # @testable false
    # @covered-by lagniappe/core/tools/cache/utility.py::check_hash
    # @reason decoded Redis hash-field wrapper
    def hget(self, key, field, expires=None):
        """Return a decoded hash field value, optionally refreshing expiry."""
        with self.pipeline() as pipe:
            pipe.hget(key, field)
            if expires:
                pipe.expire(key, expires)
            result = pipe.execute()

        value = result[0]
        return value.decode("utf-8") if value else None

    # @testable false
    # @reason decoded Redis hash-map wrapper retained for direct cache clients
    def hgetall(self, key, expires=None):
        """Return all hash fields as a decoded dict, optionally refreshing expiry."""
        with self.pipeline() as pipe:
            pipe.hgetall(key)
            if expires:
                pipe.expire(key, expires)
            result = pipe.execute()
        return {k.decode("utf-8"): v.decode("utf-8") for k, v in result[0].items()}

    # @testable false
    # @covered-by lagniappe/core/tools/cache/utility.py::cleanup_test_data
    # @reason api-wrapper used by test-data cleanup
    def keys(self, pattern):
        """Return all keys matching the given pattern."""
        return self.redis.keys(pattern)

    # @testable false
    # @covered-by lagniappe/core/tools/cache/utility.py::cleanup_test_data
    # @covered-by lagniappe/core/tools/cache/utility.py::delete_cache
    # @reason maintenance api-wrapper owned by cleanup/reset workflows
    def drop_index(self, index):
        """Drop a RediSearch index."""
        self.redis.ft(index).dropindex()

    # @testable true
    # @tests tests_unit/test_017_cache_query.py::test_cache_search_delegates_to_redisearch_client
    # @features search
    # @dimensions redis-py redis-cloud parser
    def search(self, query):
        """Execute a RediSearch query against the primary index."""
        try:
            return self.redis.ft(self.INDEX).search(query)
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

    # @testable false
    # @covered-by lagniappe/core/tools/cache/details.py::get_details_by_hash
    # @covered-by lagniappe/core/tools/cache/sync.py::get_state
    # @reason Redis hash api-wrapper used by detail and sync workflows
    def hmget(self, key, fields):
        """Return values for multiple hash fields."""
        try:
            return self.redis.hmget(key, fields)
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


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
# @features cache
# @dimensions redis-connection
class CacheJSON:
    """Redis JSON cache client for filter and relationship data."""

    def __init__(self):
        self._redis = None
        self.INDEX = Keys.JSON_INDEX.value

    # @testable true
    # @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
    # @features cache
    # @dimensions redis-connection
    @property
    def redis(self):
        """Return the Redis connection, initializing if needed."""
        if not self._redis:
            self.initialize()

        return self._redis

    # @testable true
    # @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
    # @features cache
    # @dimensions redis-connection
    def initialize(self):
        """Bind to the shared Redis connection from the hash cache."""
        self._redis = cache.redis

    # @testable false
    # @covered-by lagniappe/core/tools/cache/core.py::initialize
    # @reason index setup is owned by module-level cache startup
    def create_index(self):
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
            try:
                self.redis.ft(self.INDEX).create_index(schema, definition=definition)
            except ResponseError:
                pass

    # @testable false
    # @reason api-wrapper; currently reserved for direct JSON key deletion
    def delete(self, key):
        """Delete a JSON key."""
        self.redis.json().delete(key)

    # @testable false
    # @reason api-wrapper; currently used only for debugging/inspection
    def get(self, key):
        """Return the JSON value for a key."""
        return self.redis.json().get(key)

    # @testable false
    # @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.cache
    # @reason JSON cache existence check owned by filter-cache workflow
    def exists(self, key):
        """Check whether a key exists."""
        return self.redis.exists(key)

    # @testable false
    # @reason api-wrapper; no current direct caller owns this search helper
    def search(self, query):
        """Execute a RediSearch query against the JSON index."""
        try:
            return self.redis.ft(self.INDEX).search(query)
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

    # @testable false
    # @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.cache
    # @reason JSON document creation is owned by filter-cache population
    def create(self, key, mapping):
        """Store a JSON document with an access hash and one-day expiry."""
        parent_hash = key.split(":")[1]
        mapping["access"] = {"hash": parent_hash}
        try:
            self.redis.json().set(key, "$", mapping)
        except ResponseError as e:
            capture(e, context={"method": "create", "key": key, "mapping": mapping})
            raise e
        self.redis.expire(key, timedelta(days=1))

    # @testable false
    # @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.query
    # @reason JSONPath api-wrapper owned by filter query workflow
    def query(self, key, json_path):
        """Return a JSON value at a specific path within a key."""
        try:
            return self.redis.json().get(key, f"{json_path}")
        except ResponseError as e:
            capture(e, context={"method": "query", "key": key, "json_path": json_path})
            raise e

    # @testable false
    # @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.cache
    # @reason JSON field update is owned by filter-cache refresh workflow
    def set(self, key, mapping):
        """Update multiple JSON fields on a key and refresh expiry."""
        triplets = [(key, f"$.{k}", v) for k, v in mapping.items()]
        if triplets:
            try:
                self.redis.json().mset(triplets)
            except ResponseError as e:
                capture(e, context={"method": "set", "key": key, "mapping": mapping})
                raise e
            self.redis.expire(key, timedelta(days=1))

    # @testable false
    # @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.cache
    # @reason refresh marker query is owned by filter-cache refresh workflow
    def refresh_needed(self, cache_key):
        """Get member IDs within a specific JSON object that have refresh stubs"""
        # Use JSON path to get all members where refresh=1, then extract their ids
        refresh_members = self.redis.json().get(cache_key, "$..[?(@refresh == 1)].id")
        return refresh_members if refresh_members else []

    # @testable false
    # @covered-by lagniappe/core/tools/cache/add.py::update_json_index
    # @covered-by lagniappe/core/tools/cache/utility.py::delete
    # @reason parent-index lookup is owned by cache update/delete workflows
    def get_existing_parents(self, hashes):
        """Return a mapping of hashes to their parent JSON key IDs."""
        with self.redis.pipeline() as pipe:
            for h in hashes:
                key_query = Query(f"@cache_key:{{{h}}}").no_content()
                pipe.ft(self.INDEX).search(key_query)

        results = pipe.execute()

        return {
            h: [doc_id.decode("utf-8") for doc_id in r[1:]]
            for h, r in zip(hashes, results)
            if r and len(r) > 1
        }

    # @testable true
    # @tests tests_unit/test_017_cache_query.py::test_json_parent_lookup_skips_empty_parent_query
    # @features cache
    # @dimensions parent-index redis-cloud tag-syntax empty-parent-lookup
    def get_new_parents(self, parent_hashes):
        """Return JSON key IDs for parents matching the given hashes."""
        parent_hashes = list(parent_hashes)
        if not parent_hashes:
            return []

        new_parents = f"@hash:{{ {' | '.join(parent_hashes)} }}"
        hash_query = Query(f"{new_parents}").no_content()
        results = self.search(hash_query)
        return [doc.id for doc in results.docs]


filter_cache = CacheJSON()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_server_running
# @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
# @pair server:initialization
# @pair cache:cleanup
# @pair cache:index-recreation
def initialize():
    """Initialize both cache clients and create their search indexes."""
    cache.initialize()
    filter_cache.initialize()

    cache.create_index()
    filter_cache.create_index()
