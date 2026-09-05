"""Real Redis contracts for the bounded external candidate search path."""

import json
from uuid import uuid4

import pytest

from lagniappe.core.tools.cache import query
from lagniappe.core.tools.cache.core import cache
from lagniappe.core.tools.cache.keys import Keys, Search


pytestmark = pytest.mark.e2e


# @matrix search : candidate-ranking term-relaxation permissions bounded-query cached-details
def test_candidate_search_keeps_redis_scope_and_ranks_partial_names(monkeypatch):
    token = uuid4().hex[:12]
    rain, garden, work = (f"{word}{token}" for word in ("rain", "garden", "work"))
    required, parent, group = (uuid4().hex[:12] for _ in range(3))
    search_text = f"{rain} {garden} {work}"
    rows = [
        ("strict", "Catalog", search_text, "page", f"{required},{parent}", group),
        ("partial", f"{rain} {garden}", "", "page", f"{required},{parent}", group),
        ("weak", rain, "", "page", f"{required},{parent}", group),
        ("hidden", search_text, "", "page", f"{required},{parent}", uuid4().hex[:12]),
        ("other-parent", search_text, "", "page", required, group),
        ("other-kind", search_text, "", "project", f"{required},{parent}", group),
    ]
    keys, hashes, identifiers = [], [], {}
    queries = []
    original_search = cache.search

    def search(redis_query):
        queries.append(redis_query)
        return original_search(redis_query)

    monkeypatch.setattr(cache, "search", search)
    try:
        with cache.pipeline() as pipe:
            for label, name, description, kind, requires, restricted_to in rows:
                identifier, entity_hash = uuid4().hex, uuid4().hex[:12]
                identifiers[label] = identifier
                key = Search[kind].value.format(identifier)
                keys.append(key)
                hashes.append(entity_hash)
                pipe.hset(key, mapping={
                    "name": name,
                    "desc": description,
                    "kind": kind,
                    "requires": requires,
                    "restricted_to": restricted_to,
                    "details_key": entity_hash,
                })
                pipe.hset(Keys.ENTITY_HASHES.value, entity_hash, json.dumps({
                    "hash": entity_hash, "name": name, "kind": kind,
                }))
            pipe.execute()

        results = query.candidate_search(
            search_text, [required], [group], kinds=["page"], parent_hash=parent, limit=3
        )
        assert [result["id"] for result in results] == [
            identifiers["strict"], identifiers["partial"], identifiers["weak"]
        ]
        assert len(queries) == 2
        assert all(result["details"]["hash"] in hashes for result in results)
        assert all(request._num <= 100 for request in queries)

        ordinary, _total = query.search(search_text, [required], [group], kinds=["page"])
        assert identifiers["strict"] in {result["id"] for result in ordinary}
        assert identifiers["partial"] not in {result["id"] for result in ordinary}
        assert identifiers["weak"] not in {result["id"] for result in ordinary}

        exact = query.candidate_search(
            f"{rain} {garden}", [required], [group], kinds=["page"], parent_hash=parent
        )
        assert exact[0]["id"] == identifiers["partial"]
        assert len(queries) == 4  # One native query and one exact-hit candidate query.
    finally:
        with cache.pipeline() as pipe:
            if keys:
                pipe.delete(*keys)
            if hashes:
                pipe.hdel(Keys.ENTITY_HASHES.value, *hashes)
            pipe.execute()
