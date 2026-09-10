"""Bounded external discovery without changing native full-text search."""

import json
from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import Restriction
from lagniappe.core.tools.ai.function_definitions import search as ai_search
from lagniappe.core.tools.cache import details as cache_details
from lagniappe.core.tools.cache import query


pytestmark = pytest.mark.unit


def _document(identifier, name, *, score=1, kind="page", **fields):
    return SimpleNamespace(
        id=f"{query.CONFIG.PREFIX}{kind}:{identifier}",
        kind=kind,
        name=name,
        score=score,
        details_key=identifier,
        **fields,
    )


def _install_cache(monkeypatch, batches, *, missing=()):
    detail_rows = {
        doc.details_key: {
            "hash": doc.details_key,
            "name": doc.name,
            "kind": doc.kind,
        }
        for docs in batches
        for doc in docs
        if doc.details_key not in missing
    }

    class SearchCache:
        def __init__(self):
            self.queries = []
            self.detail_reads = []
            self.deleted = []

        def search(self, redis_query):
            docs = batches[len(self.queries)]
            self.queries.append(redis_query)
            return SimpleNamespace(docs=docs, total=len(docs))

        def hmget(self, key, fields):
            self.detail_reads.append((key, fields))
            return [
                json.dumps(detail_rows[field]).encode() if field in detail_rows else None
                for field in fields
            ]

        def delete(self, *keys):
            self.deleted.extend(keys)

    cache = SearchCache()
    monkeypatch.setattr(query, "cache", cache)
    monkeypatch.setattr(cache_details, "cache", cache)
    return cache


# @matrix search : term-relaxation permissions bounded-query cached-details
def test_candidate_search_groups_relaxed_terms_inside_access_scope(monkeypatch):
    cache = _install_cache(
        monkeypatch,
        [[], [_document("rain-task", "Rain collection", kind="task")]],
    )

    results = query.candidate_search(
        "Rain garden",
        ["models", "actor"],
        ["gardenteam"],
        kinds=["task"],
        parent_hash="garden-category",
        limit=2,
    )

    assert [result["name"] for result in results] == ["Rain collection"]
    assert len(cache.queries) == 2
    scope = (
        "(@kind:{ task | model }) (@requires:{ garden-category }) "
        "(@requires:{ models | actor }) "
        "(ismissing(@restricted_to_page) | @restricted_to_page:{ gardenteam }) "
        "(ismissing(@restricted_to_page_form) | @restricted_to_page_form:{ gardenteam }) "
        "(ismissing(@restricted_to_task_form) | @restricted_to_task_form:{ gardenteam })"
    )
    assert all(request._query_string.endswith(scope) for request in cache.queries)
    assert cache.queries[1]._query_string.startswith(
        "(((@name:rain*) | (@desc:rain*) | (@doc:rain*) | (@values:rain*)) | "
        "((@name:garden*) | (@desc:garden*) | (@doc:garden*) | (@values:garden*))) "
    )
    assert all(request._offset == 0 and request._num == 25 for request in cache.queries)
    assert all(request._with_scores for request in cache.queries)
    assert cache.detail_reads
    assert results[0]["details"]["hash"] == "rain-task"
    assert "_candidate_score" not in results[0]


# @matrix search : candidate-ranking term-relaxation bounded-query
def test_candidate_search_ranks_exact_strict_and_name_coverage(monkeypatch):
    strict = _document("strict", "Community allotment", score=1)
    shared_name = _document("many", "Rain garden", score=0.1)
    weak = _document("weak", "Rain forecast", score=100)
    duplicate = _document("strict", "Community allotment", score=1000)
    cache = _install_cache(monkeypatch, [[strict], [weak, duplicate, shared_name]])

    results = query.candidate_search(
        "Rain garden planning", Restriction.UNRESTRICTED, Restriction.BELONGS_TO_ALL, limit=3
    )

    assert [result["id"] for result in results] == ["strict", "many", "weak"]
    assert len(cache.queries) == 2

    exact = _document("exact", "  RAIN   GARDEN  ", score=0.01)
    _install_cache(monkeypatch, [[
        weak, exact, _document("two", "Rain garden plans", score=200)
    ]])
    results = query.candidate_search("rain garden", ["models"], [], limit=2)
    assert [result["id"] for result in results] == ["exact", "two"]


# @matrix search : candidate-ranking term-relaxation permissions bounded-query
@pytest.mark.parametrize(
    "text,required,documents,expected_queries",
    [
        ("rain garden", [], [], 0),
        ("a and the !", ["models"], [], 0),
        ("rain", ["models"], [], 1),
        ("rain RAIN", ["models"], [], 1),
        ("rain garden", ["models"], [_document("exact", "Rain Garden")], 1),
        (
            "rain garden",
            ["models"],
            [_document(str(index), f"Rain garden {index}") for index in range(3)],
            1,
        ),
        (" ".join(f"term{index}" for index in range(13)), ["models"], [], 1),
    ],
)
def test_candidate_search_skips_unnecessary_or_queries(
    monkeypatch, text, required, documents, expected_queries
):
    cache = _install_cache(monkeypatch, [documents])

    query.candidate_search(text, required, [], limit=1000)

    assert len(cache.queries) == expected_queries
    assert all(request._num <= 100 for request in cache.queries)


# @matrix search : term-relaxation cached-details permissions
def test_candidate_search_keeps_default_search_and_stale_repair(monkeypatch):
    stale = _document("stale", "Rain garden")
    live = _document("live", "Rain collection")
    cache = _install_cache(monkeypatch, [[stale], [live]], missing=["stale"])

    results = query.candidate_search("rain garden", ["models"], [])

    assert [result["id"] for result in results] == ["live"]
    assert cache.deleted == [query.Search.page.value.format("stale")]
    assert len(cache.queries) == 2

    cache = _install_cache(monkeypatch, [[]])
    assert query.search("rain garden", ["models"], []) == ([], 0)
    assert len(cache.queries) == 1
    assert cache.queries[0]._query_string.startswith(
        "((@name:rain*) | (@desc:rain*) | (@doc:rain*) | (@values:rain*)) "
        "((@name:garden*) | (@desc:garden*) | (@doc:garden*) | (@values:garden*)) "
    )


def _actor():
    return SimpleNamespace(properties=SimpleNamespace(
        restrictions=SimpleNamespace(search=["models"], belongs_to=["team"])
    ))


# @matrix ai search : candidate-routing cached-details
# @pair ai:search-url
def test_external_candidates_use_cached_context_without_entity_loading(monkeypatch):
    calls = []

    def candidates(text, required, belongs_to, **kwargs):
        calls.append((text, required, belongs_to, kwargs))
        return [
            {
                "id": "task-key",
                "kind": "task",
                "name": "Fix search",
                "details": {
                    "hash": "abcdef123456",
                    "completed": True,
                    "parent": {"hash": "123456abcdef", "name": "Filtering"},
                },
            },
            {
                "id": "open-task", "kind": "task", "name": "Review",
                "details": {"hash": "deadbeef1234"},
            },
        ]

    monkeypatch.setattr(ai_search.cache, "candidate_search", candidates)
    monkeypatch.setattr(ai_search.Entities, "fetch", lambda *args, **kwargs: pytest.fail(
        "Visible cached candidates must not trigger full entity loading"
    ))

    results = ai_search.execute_search(
        {"query": "search bug", "kinds": ["tasks"], "limit": 99},
        _actor(),
        candidate_search=True,
    )

    assert calls == [
        ("search bug", ["models"], ["team"], {"kinds": ["task"], "parent_hash": None, "limit": 25})
    ]
    assert results[0]["completed"] is True
    assert results[1]["completed"] is False
    assert results[0]["parent"] == {"hash": "hash:123456abcdef", "name": "Filtering"}
    assert results[0]["hash"] == "hash:abcdef123456"
    assert results[0]["url"] == "/tasks/task-key"
    assert results[1]["url"] == "/tasks/open-task"
    assert "permissions" not in results[0]
    assert "details" not in results[0]


# @matrix ai search : candidate-routing parent-scope
def test_candidate_scope_preserves_native_and_exact_modes(monkeypatch):
    calls = []
    parent = SimpleNamespace(hash="parent", allowed=lambda action, user=None: True)
    monkeypatch.setattr(ai_search.Entities, "CATEGORY", parent.__class__)
    monkeypatch.setattr(ai_search.Entities, "fetch_one", lambda *args, **kwargs: parent)
    monkeypatch.setattr(ai_search.cache, "candidate_search", lambda *args, **kwargs: calls.append(
        ("candidate", kwargs)
    ) or [])
    monkeypatch.setattr(ai_search.cache, "search", lambda *args, **kwargs: calls.append(
        ("native", kwargs)
    ) or ([], 0))
    monkeypatch.setattr(ai_search.cache, "exact_name_search", lambda *args, **kwargs: calls.append(
        ("exact", kwargs)
    ) or [])
    monkeypatch.setattr(ai_search.Entities, "fetch", lambda *args, **kwargs: [])
    args = {"query": "Rain garden", "kinds": ["page"], "parent_id": "category-key"}

    assert ai_search.execute_search(args, _actor())["error"]
    assert not calls
    invalid_kind = ai_search.execute_search(
        {**args, "kinds": ["task"]}, _actor(), candidate_search=True
    )
    assert invalid_kind == {"error": 'parent_id is supported only for searches with kinds=["page"].'}
    assert not calls
    assert ai_search.execute_search(args, _actor(), candidate_search=True) == []
    assert calls[-1] == ("candidate", {"kinds": ["page"], "parent_hash": "parent", "limit": 10})
    assert ai_search.execute_search(
        {**args, "match_mode": "exact_name"}, _actor(), candidate_search=True
    ) == []
    assert calls[-1][0] == "exact"

    assert ai_search.execute_search({"query": "Rain garden"}, _actor()) == []
    assert calls[-1][0] == "native"
    parent.allowed = lambda action, user=None: False
    before = len(calls)
    assert ai_search.execute_search(args, _actor(), candidate_search=True) == {"error": "Access denied"}
    assert len(calls) == before
