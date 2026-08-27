import json
from types import SimpleNamespace

import pytest
from redis import ResponseError
from redis.exceptions import WatchError

from lagniappe.core.definitions import Restriction
from lagniappe.core.tools.cache import add as cache_add
from lagniappe.core.tools.cache import core as cache_core
from lagniappe.core.tools.cache import details as cache_details
from lagniappe.core.tools.cache import query, utility
from lagniappe.core.tools.cache import sitemap as sitemap_cache
from lagniappe.core.tools.cache.core import Cache, CacheJSON
from lagniappe.core.tools.cache.keys import SEARCH_SCORE_FIELD, Keys, Search
from lagniappe.core.tools.hosted_e2e import lease as e2e_lease


# @matrix cache : redis-connection redis-tls
def test_runtime_redis_client_uses_shared_tls_options(monkeypatch):
    settings = SimpleNamespace(REDIS_TLS=True)
    calls = []
    expected = object()

    def fake_options(received_settings, **kwargs):
        calls.append((received_settings, kwargs))
        return {"ssl": True, "ssl_cert_reqs": "required"}

    monkeypatch.setattr(cache_core, "redis_client_kwargs", fake_options)
    monkeypatch.setattr(
        cache_core.redis,
        "Redis",
        lambda **kwargs: calls.append(kwargs) or expected,
    )

    assert cache_core._create_redis_client(settings) is expected
    assert calls == [
        (
            settings,
            {"decode_responses": False},
        ),
        {"ssl": True, "ssl_cert_reqs": "required"},
    ]


def _highlight(text):
    return f"{query.HIGHLIGHT_OPEN}{text}{query.HIGHLIGHT_CLOSE}"


def _cached_json(value):
    return json.dumps(value).encode("utf-8")


# @matrix cache sitemap : epoch redis-race ttl
def test_sitemap_cache_only_publishes_for_unchanged_epoch(monkeypatch):
    built = []
    published = []

    class Pipe:
        attempts = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def watch(self, key):
            assert key == Keys.SITEMAP_EPOCH.value

        def get(self, key):
            return b"3"

        def multi(self):
            return None

        def setex(self, key, ttl, value):
            published.append((key, ttl, value))

        def execute(self):
            Pipe.attempts += 1
            if Pipe.attempts == 1:
                published.clear()
                raise WatchError()

    redis = SimpleNamespace(
        get=lambda key: None,
        pipeline=lambda: Pipe(),
    )
    monkeypatch.setattr(sitemap_cache.cache, "_redis", redis)

    result = sitemap_cache.cached_sitemap(
        lambda: built.append(True) or "<urlset />"
    )

    assert result == "<urlset />"
    assert len(built) == 2
    assert published == [
        (Keys.SITEMAP.value, sitemap_cache.SITEMAP_TTL_SECONDS, "<urlset />")
    ]


# @matrix cache sitemap : invalidation redis-failure
def test_sitemap_invalidation_advances_epoch_and_deletes_xml(monkeypatch):
    commands = []

    class Pipe:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def incr(self, key):
            commands.append(("incr", key))

        def expire(self, key, ttl):
            commands.append(("expire", key, ttl))

        def delete(self, key):
            commands.append(("delete", key))

        def execute(self):
            commands.append(("execute",))

    monkeypatch.setattr(
        sitemap_cache.cache,
        "_redis",
        SimpleNamespace(pipeline=lambda: Pipe()),
    )

    assert sitemap_cache.invalidate_sitemap() is True
    assert commands == [
        ("incr", Keys.SITEMAP_EPOCH.value),
        ("expire", Keys.SITEMAP_EPOCH.value, sitemap_cache.SITEMAP_EPOCH_TTL_SECONDS),
        ("delete", Keys.SITEMAP.value),
        ("execute",),
    ]


class _FakeDetailsCache:
    def __init__(self, details):
        self.details = details
        self.hmget_calls = []

    def hmget(self, key, fields):
        self.hmget_calls.append(list(fields))
        return [
            _cached_json(self.details[field]) if field in self.details else None
            for field in fields
        ]


# @matrix search : exact-match partial-match special-characters stopwords term-normalization
@pytest.mark.unit
def test_search_term_list_normalizes_stopwords_and_special_characters():
    assert query._build_term_list("The A+ R&D plan, in 2024!") == [
        "(@name:plan*)",
        "(@name:2024*)",
    ]
    assert query._build_term_list("alpha/beta and this gamma", expanded=True) == [
        "((@name:alpha*) | (@desc:alpha*) | (@doc:alpha*) | (@values:alpha*))",
        "((@name:beta*) | (@desc:beta*) | (@doc:beta*) | (@values:beta*))",
        "((@name:gamma*) | (@desc:gamma*) | (@doc:gamma*) | (@values:gamma*))",
        "~((@kind:{ category | project | page }) "
        "(@name:alpha*) (@name:beta*) (@name:gamma*)) "
        "=> { $weight: 4.0; }",
    ]
    assert query._build_term_list("a an the x y") == []


# @matrix search : form-value highlighted-text html-escaping pipe-escaping snippets
@pytest.mark.unit
def test_search_snippet_extracts_highlighted_text_and_form_values():
    result = {}
    query._add_snippet(
        result,
        SimpleNamespace(
            desc=f"Description with {_highlight('hit')} and <b>raw</b>",
            doc=f"Document with {_highlight('other')}",
            keys="Ignored",
            values=f"Ignored {_highlight('value')}",
        ),
    )
    assert str(result["text"]) == (
        "Description with <b>hit</b> and &lt;b&gt;raw&lt;/b&gt;"
    )

    result = {}
    query._add_snippet(
        result,
        SimpleNamespace(
            desc="Description without highlight",
            doc=f"Document with {_highlight('<hit>')} and <script>raw</script>",
            values=f"Ignored {_highlight('value')}",
        ),
    )
    assert str(result["text"]) == (
        "Document with <b>&lt;hit&gt;</b> and &lt;script&gt;raw&lt;/script&gt;"
    )

    before = "zero one two three four five six seven eight nine ten eleven"
    after = (
        r"after0 <tail> escaped\|pipe slash\\mark after4 after5 "
        "after6 after7 after8 after9 after10"
    )
    result = {}
    query._add_snippet(
        result,
        SimpleNamespace(
            keys=r"Plain|Escaped\|<Field>",
            values=rf"not this|{before} {_highlight('needle <tag>')} {after}",
        ),
    )

    assert result["form_field"] == "Escaped|<Field>"
    assert str(result["form_value"]) == (
        "... two three four five six seven eight nine ten eleven "
        r"<b>needle &lt;tag&gt;</b> after0 &lt;tail&gt; escaped|pipe "
        r"slash\mark after4 after5 after6 after7 after8 after9 ..."
    )


# @matrix search : malformed-cache snippets
@pytest.mark.unit
def test_search_snippet_skips_highlighted_value_without_matching_key():
    result = {}
    query._add_snippet(
        result,
        SimpleNamespace(
            keys="Only Field",
            values=f"unmatched first|unmatched {_highlight('second')}",
        ),
    )

    assert "form_field" not in result
    assert "form_value" not in result


# @matrix cache : details parent-key redis-storage
@pytest.mark.unit
def test_redis_details_store_parent_key_not_parent_blob():
    entity = SimpleNamespace(
        details={
            "id": "page-id",
            "kind": "page",
            "hash": "page-hash",
            "name": "Page",
            "parent": {
                "id": "category-id",
                "kind": "category",
                "hash": "category-hash",
                "name": "Category",
            },
        }
    )

    details = cache_add._redis_details(entity)

    assert details == {
        "id": "page-id",
        "kind": "page",
        "hash": "page-hash",
        "name": "Page",
        "parent_key": "category-hash",
    }


# @matrix cache : kind-score search-ranking
@pytest.mark.unit
def test_kind_search_score_prioritizes_high_level_entities():
    assert cache_add._kind_search_score("category") == "1.0"
    assert cache_add._kind_search_score("page") == "1.0"
    assert cache_add._kind_search_score("project") == "0.95"
    assert cache_add._kind_search_score("task") == "0.65"
    assert cache_add._kind_search_score("model") == "0.65"
    assert cache_add._kind_search_score("file") == "0.55"
    assert cache_add._kind_search_score("form") == "0.75"


# @matrix cache : details parent-key redis-storage
@pytest.mark.unit
def test_cache_update_writes_pointer_search_rows_and_parent_free_details(monkeypatch):
    hset_calls = []

    class FakePipe:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def delete(self, key):
            return None

        def hset(self, key, *args, mapping=None):
            hset_calls.append((key, mapping, args))

        def execute(self):
            return None

    class FakeCache:
        def pipeline(self):
            return FakePipe()

    entity = SimpleNamespace(
        hash="page-hash",
        kind="page",
        urlsafe_key="page-id",
        to_cache={
            "id": "page-id",
            "kind": "page",
            "name": "Page",
            "hash": "page-hash",
            "details_key": "page-hash",
            "parent_key": "category-hash",
            "details": '{"legacy": true}',
        },
        details={
            "id": "page-id",
            "kind": "page",
            "hash": "page-hash",
            "name": "Page",
            "parent": {
                "id": "category-id",
                "kind": "category",
                "hash": "category-hash",
                "name": "Category",
            },
        },
    )

    monkeypatch.setattr(cache_add, "cache", FakeCache())

    cache_add.update(entity, update=False)

    search_key = Search.page.key(entity)
    search_mapping = next(
        mapping for key, mapping, args in hset_calls if key == search_key
    )
    assert search_mapping["details_key"] == "page-hash"
    assert search_mapping["parent_key"] == "category-hash"
    assert search_mapping[SEARCH_SCORE_FIELD] == "1.0"
    assert "details" not in search_mapping

    details_call = next(
        (key, args)
        for key, mapping, args in hset_calls
        if key == Keys.ENTITY_HASHES.value
    )
    assert details_call[1][0] == "page-hash"
    details = json.loads(details_call[1][1])
    assert details["parent_key"] == "category-hash"
    assert "parent" not in details


# @pairs cache:delete search:user-projection
def test_cache_delete_removes_page_and_user_search_projections(monkeypatch):
    deleted = []

    class FakePipe:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def delete(self, *keys):
            deleted.extend(keys)

        def hdel(self, *_args):
            return None

        def execute(self):
            return None

    monkeypatch.setattr(
        utility.filter_cache,
        "get_existing_parents",
        lambda _hashes: {},
    )
    monkeypatch.setattr(
        utility.cache,
        "pipeline",
        lambda: FakePipe(),
    )
    page = SimpleNamespace(
        hash="deleted-user-page-hash",
        kind="page",
        urlsafe_key="deleted-user-page-key",
    )

    utility.delete([page])

    assert set(deleted) == {
        Search.page.key(page),
        Search.user.key(page),
    }


# @matrix cache : details-hydration missing-parent parent-key string-input
@pytest.mark.unit
def test_get_details_by_hash_hydrates_parent_and_hides_internal_keys(monkeypatch):
    fake_cache = _FakeDetailsCache(
        {
            "page-hash": {
                "id": "page-id",
                "kind": "page",
                "hash": "page-hash",
                "name": "Page",
                "parent_key": "category-hash",
            },
            "category-hash": {
                "id": "category-id",
                "kind": "category",
                "hash": "category-hash",
                "name": "Fresh Category",
            },
            "orphan-hash": {
                "id": "orphan-id",
                "kind": "page",
                "hash": "orphan-hash",
                "name": "Orphan",
                "parent_key": "missing-hash",
            },
        }
    )
    monkeypatch.setattr(cache_details, "cache", fake_cache)

    details = cache_details.get_details_by_hash("page-hash")

    assert fake_cache.hmget_calls == [["page-hash"], ["category-hash"]]
    assert list(details) == ["page-hash"]
    assert details["page-hash"]["parent"]["name"] == "Fresh Category"
    assert "parent_key" not in details["page-hash"]
    assert "parent_key" not in details["page-hash"]["parent"]

    fake_cache.hmget_calls.clear()
    details = cache_details.get_details_by_hash(["page-hash", "category-hash"])

    assert fake_cache.hmget_calls == [["page-hash", "category-hash"]]
    assert set(details) == {"page-hash", "category-hash"}
    assert details["page-hash"]["parent"]["name"] == "Fresh Category"
    assert "parent" not in details["category-hash"]

    fake_cache.hmget_calls.clear()
    details = cache_details.get_details_by_hash("orphan-hash")

    assert fake_cache.hmget_calls == [["orphan-hash"], ["missing-hash"]]
    assert details["orphan-hash"]["name"] == "Orphan"
    assert "parent" not in details["orphan-hash"]
    assert "parent_key" not in details["orphan-hash"]


# @matrix cache search : details-hydration parent-key snippets
@pytest.mark.unit
def test_search_results_are_hydrated_from_details_hashes(monkeypatch):
    doc = SimpleNamespace(
        id=f"{query.CONFIG.PREFIX}page:page-id",
        kind="page",
        name="Page",
        details_key="page-hash",
        parent_key="category-hash",
        desc=f"Page description {_highlight('needle')}",
    )

    class FakeCache(_FakeDetailsCache):
        def search(self, redis_query):
            return SimpleNamespace(docs=[doc], total=1)

    fake_cache = FakeCache(
        {
            "page-hash": {
                "id": "page-id",
                "kind": "page",
                "hash": "page-hash",
                "name": "Page",
                "parent_key": "category-hash",
            },
            "category-hash": {
                "id": "category-id",
                "kind": "category",
                "hash": "category-hash",
                "name": "Category",
            },
        }
    )
    monkeypatch.setattr(query, "cache", fake_cache)
    monkeypatch.setattr(cache_details, "cache", fake_cache)

    entity_results = query.entity_search("Page", Restriction.UNRESTRICTED, [])
    kind_results = query.kind_search(
        "Page", "page", Restriction.UNRESTRICTED, [], include_users=False
    )
    full_results, total = query.search("Page", [], [])

    for result in [entity_results[0], kind_results[0], full_results[0]]:
        assert result["details"]["parent"]["name"] == "Category"
        assert "details_key" not in result
        assert "parent_key" not in result

    assert total == 1
    assert str(full_results[0]["text"]) == "Page description <b>needle</b>"


# @pairs cache:self-repair search:stale-row
def test_search_prunes_stale_rows_without_entity_details(monkeypatch):
    deleted = []
    monkeypatch.setattr(
        query,
        "hydrate_search_results",
        lambda results: results,
    )
    monkeypatch.setattr(
        query.cache,
        "delete",
        lambda *keys: deleted.extend(keys),
    )
    current = {
        "id": "current-page",
        "kind": "page",
        "details": {"hash": "current-hash"},
    }
    stale = {
        "id": "deleted-user-page",
        "kind": "user",
        "details": {},
    }

    results, stale_count = query._current_search_results([current, stale])

    assert results == [current]
    assert stale_count == 1
    assert deleted == [Search.user.value.format("deleted-user-page")]


# @matrix search : empty-access permissions redis-cloud tag-syntax
@pytest.mark.unit
def test_search_queries_use_redis_cloud_compatible_tag_syntax(monkeypatch):
    calls = []

    class FakeCache:
        def search(self, redis_query):
            calls.append(redis_query._query_string)
            return SimpleNamespace(docs=[], total=0)

    monkeypatch.setattr(query, "cache", FakeCache())

    assert (
        query.kind_search("Alpha", "project", ["models", "abc123"], [], models=True)
        == []
    )

    assert calls[0] == (
        "(@name:Alpha*) (@kind:{ project | model }) "
        "(ismissing(@restricted_to)) (@requires:{ models | abc123 })"
    )

    calls.clear()
    assert (
        query.kind_search(
            "Alpha",
            "project",
            Restriction.UNRESTRICTED,
            [],
            models=True,
        )
        == []
    )

    assert calls[0] == (
        "(@name:Alpha*) (@kind:{ project | model }) (ismissing(@restricted_to))"
    )

    calls.clear()
    assert query.search("Alpha", [], [], kinds=["task"]) == ([], 0)

    assert calls[0] == (
        "((@name:Alpha*) | (@desc:Alpha*) | (@doc:Alpha*) | (@values:Alpha*)) "
        "~((@kind:{ category | project | page }) (@name:Alpha*)) "
        "=> { $weight: 4.0; } "
        '(@kind:{ task | model }) (@requires:{""}) '
        "(ismissing(@restricted_to))"
    )
    assert ":{}" not in calls[0]


# @matrix search : permissions validation
@pytest.mark.unit
def test_search_permission_fragments_require_lists():
    with pytest.raises(TypeError, match="Required must be a list"):
        query._add_required("models")

    with pytest.raises(TypeError, match="Restricted to must be a list"):
        query._add_restricted_to("group")

    with pytest.raises(TypeError, match="Required must be a list"):
        query.search("Alpha", False, [])


# @matrix cache : empty-requires index-schema redis-cloud search-ranking tag-syntax
@pytest.mark.unit
def test_search_index_indexes_empty_requires_tags():
    captured = {}

    class FakeSearch:
        def info(self):
            raise ResponseError("unknown index name")

        def create_index(self, schema, definition=None):
            captured["schema"] = schema
            captured["definition"] = definition

    class FakeRedis:
        def ft(self, index):
            return FakeSearch()

    cache = Cache()
    cache._redis = FakeRedis()

    cache.create_index()

    requires = next(field for field in captured["schema"] if field.name == "requires")
    text_weights = {
        field.name: field.redis_args()[field.redis_args().index("WEIGHT") + 1]
        for field in captured["schema"]
        if "WEIGHT" in field.redis_args()
    }
    assert text_weights == {
        "name": 4,
        "desc": 1,
        "doc": 0.5,
        "values": 0.25,
    }
    assert "INDEXEMPTY" in requires.redis_args()
    assert "SCORE_FIELD" in captured["definition"].args
    assert SEARCH_SCORE_FIELD in captured["definition"].args


# @matrix search : parser redis-cloud redis-py
@pytest.mark.unit
def test_cache_search_delegates_to_redisearch_client():
    captured = {}
    expected = SimpleNamespace(total=1, docs=[])

    class FakeSearch:
        def search(self, redis_query):
            captured["query"] = redis_query
            return expected

    class FakeRedis:
        def ft(self, index):
            captured["index"] = index
            return FakeSearch()

    cache = Cache()
    cache._redis = FakeRedis()
    redis_query = query.Query("(@name:Marc*)").paging(0, 10)

    results = cache.search(redis_query)

    assert results is expected
    assert captured == {"index": cache.INDEX, "query": redis_query}


# @matrix cache : empty-parent-lookup parent-index redis-cloud tag-syntax
@pytest.mark.unit
def test_json_parent_lookup_skips_empty_parent_query():
    assert CacheJSON().get_new_parents([]) == []


# @matrix cache : flush-db rebuild
@pytest.mark.unit
def test_delete_cache_flushes_db_and_recreates_indexes(monkeypatch):
    calls = []

    class FakeCache:
        INDEX = "search-idx"

        def create_index(self):
            calls.append(("create", self.INDEX))

        def flush(self):
            calls.append(("flush", self.INDEX))

    class FakeFilterCache:
        INDEX = "filter-idx"

        def create_index(self):
            calls.append(("create", self.INDEX))

    monkeypatch.setattr(utility, "cache", FakeCache())
    monkeypatch.setattr(utility, "filter_cache", FakeFilterCache())
    monkeypatch.setattr(utility, "CONFIG", SimpleNamespace(PREFIX=""))

    utility.delete_cache()

    assert calls == [
        ("flush", "search-idx"),
        ("create", "search-idx"),
        ("create", "filter-idx"),
    ]


# @matrix cache : prefix-isolation rebuild
@pytest.mark.unit
def test_delete_cache_clears_only_prefixed_keys_and_recreates_indexes(monkeypatch):
    calls = []

    class FakeCache:
        INDEX = "test-search-idx"

        def create_index(self):
            calls.append(("create", self.INDEX))

        def flush(self):
            pytest.fail("a prefixed cache rebuild must not flush the Redis database")

        def keys(self, pattern):
            calls.append(("keys", pattern))
            return ["test-one", "test-two"]

        def delete(self, *keys):
            calls.append(("delete", keys))

        def drop_index(self, index):
            calls.append(("drop", index))

    class FakeFilterCache:
        INDEX = "test-filter-idx"

        def create_index(self):
            calls.append(("create", self.INDEX))

    monkeypatch.setattr(utility, "cache", FakeCache())
    monkeypatch.setattr(utility, "filter_cache", FakeFilterCache())
    monkeypatch.setattr(utility, "CONFIG", SimpleNamespace(PREFIX="test-"))

    utility.delete_cache()

    assert calls == [
        ("keys", "test-*"),
        ("delete", ("test-one", "test-two")),
        ("drop", "test-search-idx"),
        ("drop", "test-filter-idx"),
        ("create", "test-search-idx"),
        ("create", "test-filter-idx"),
    ]


# @matrix cache : cleanup missing-search-index
@pytest.mark.unit
def test_cleanup_test_data_ignores_redis_missing_search_index_errors(monkeypatch):
    missing_index_messages = (
        "Unknown Index name",
        "SEARCH_INDEX_NOT_FOUND Index not found: search-idx",
    )

    for missing_index_message in missing_index_messages:
        calls = []

        class FakeCache:
            INDEX = "search-idx"

            def keys(self, pattern):
                calls.append(("keys", pattern))
                return ["test-one"]

            def delete(self, *keys):
                calls.append(("delete", keys))

            def drop_index(self, index):
                calls.append(("drop", index))
                raise ResponseError(missing_index_message)

        monkeypatch.setattr(utility, "CONFIG", SimpleNamespace(PREFIX="test-"))
        monkeypatch.setattr(utility, "cache", FakeCache())
        monkeypatch.setattr(
            utility,
            "filter_cache",
            SimpleNamespace(INDEX="filter-idx"),
        )

        utility.cleanup_test_data()

        assert calls == [
            ("keys", "test-*"),
            ("delete", ("test-one",)),
            ("drop", "search-idx"),
            ("drop", "filter-idx"),
        ]


# @matrix cache : cleanup redis-errors
@pytest.mark.unit
def test_cleanup_test_data_reraises_unexpected_drop_index_errors(monkeypatch):
    class FakeCache:
        INDEX = "idx"

        def keys(self, pattern):
            return []

        def drop_index(self, index):
            raise ResponseError("Redis is unavailable")

    monkeypatch.setattr(utility, "CONFIG", SimpleNamespace(PREFIX="test-"))
    monkeypatch.setattr(utility, "cache", FakeCache())
    monkeypatch.setattr(utility, "filter_cache", SimpleNamespace(INDEX="filter-idx"))

    with pytest.raises(ResponseError, match="Redis is unavailable"):
        utility.cleanup_test_data()


class _LeaseRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = str(value)
        return True

    def get(self, key):
        return self.values.get(key)

    def eval(self, script, count, key, run_id, *arguments):
        assert count == 1
        if self.values.get(key) != run_id:
            return 0
        if "expire" in script:
            return 1
        del self.values[key]
        return 1


# @matrix hosted-e2e : lease prefix-isolation
def test_e2e_lease_key_is_outside_test_cleanup_prefix(monkeypatch):
    monkeypatch.setattr(
        e2e_lease,
        "CONFIG",
        SimpleNamespace(GOOGLE_CLOUD_PROJECT="project-1", PREFIX="test-"),
    )

    key = e2e_lease.e2e_lease_key()

    assert key.startswith("lagniappe:e2e:lease:")
    assert not key.startswith("test-")


# @matrix hosted-e2e : authentication concurrency deployment-binding expiry heartbeat lease ownership replay
def test_e2e_lease_acquire_heartbeat_and_owner_release(monkeypatch):
    monkeypatch.setattr(
        e2e_lease,
        "CONFIG",
        SimpleNamespace(GOOGLE_CLOUD_PROJECT="project-1", PREFIX="test-"),
    )
    client = _LeaseRedis()
    owner = "owner_abcdefghijklmnopqrstuvwxyz"
    contender = "contender_abcdefghijklmnopqrstuv"

    assert e2e_lease.acquire_e2e_lease(owner, client=client)
    assert not e2e_lease.acquire_e2e_lease(contender, client=client)
    assert e2e_lease.heartbeat_e2e_lease(owner, client=client)
    version = "e2e-abcdef1234567890"
    source = "b" * 40
    assert e2e_lease.bind_e2e_deployment(
        owner,
        version,
        source,
        client=client,
    )
    assert e2e_lease.e2e_deployment_lease_active(
        version,
        source,
        run_id=owner,
        client=client,
    )
    assert not e2e_lease.e2e_deployment_lease_active(
        version,
        source,
        run_id=contender,
        client=client,
    )
    digest = "a" * 64
    assert e2e_lease.consume_e2e_bootstrap_token(digest, owner, client=client)
    assert not e2e_lease.consume_e2e_bootstrap_token(digest, owner, client=client)
    assert not e2e_lease.release_e2e_lease(contender, client=client)
    assert e2e_lease.e2e_lease_active(owner, client=client)
    assert e2e_lease.release_e2e_lease(owner, client=client)
    assert e2e_lease.current_e2e_lease(client=client) is None
    assert not e2e_lease.e2e_deployment_lease_active(
        version,
        source,
        client=client,
    )
    assert e2e_lease.acquire_e2e_lease(contender, client=client)
    assert e2e_lease.consume_e2e_bootstrap_token(
        digest,
        contender,
        client=client,
    )
    assert e2e_lease.release_e2e_lease(contender, client=client)

    with e2e_lease.E2ELease(
        owner,
        client=client,
        heartbeat_seconds=100,
    ) as lease:
        lease.assert_active()
    assert e2e_lease.current_e2e_lease(client=client) is None


# @matrix hosted-e2e : heartbeat lease-ownership transfer
def test_e2e_lease_handoff_keeps_owner_for_heartbeat_adoption(monkeypatch):
    monkeypatch.setattr(
        e2e_lease,
        "CONFIG",
        SimpleNamespace(GOOGLE_CLOUD_PROJECT="project-1", PREFIX="test-"),
    )
    client = _LeaseRedis()
    owner = "owner_abcdefghijklmnopqrstuvwxyz"
    lease = e2e_lease.E2ELease(
        owner,
        client=client,
        heartbeat_seconds=100,
    )
    lease.__enter__()

    assert lease.handoff() == owner
    lease.__exit__(None, None, None)
    assert e2e_lease.current_e2e_lease(client=client) == owner

    with e2e_lease.E2ELeaseHeartbeat(
        owner,
        client=client,
        heartbeat_seconds=100,
    ) as adopter:
        adopter.assert_active()
    assert e2e_lease.current_e2e_lease(client=client) == owner
    assert e2e_lease.release_e2e_lease(owner, client=client)
