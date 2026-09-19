"""Document poll projection against Redis with counted durable asset reads."""

from datetime import datetime, timezone
from importlib import import_module
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from lagniappe.core.definitions import Action
from lagniappe.core.entities.page import Page
from lagniappe.core.entities.project import Project
from lagniappe.core.tools.cache import documents
from lagniappe.core.tools.database import assets

poll = import_module("lagniappe.web.routes.home.poll")

pytestmark = pytest.mark.e2e


# @matrix polling : document read-path
@pytest.mark.parametrize("entity_type", [Page, Project], ids=["page", "project"])
@pytest.mark.parametrize("legacy_html", [False, True], ids=["ydoc", "legacy-html"])
def test_document_poll_loads_storage_only_on_cache_miss(
    monkeypatch, entity_type, legacy_html,
):
    identity = f"test-poll-{uuid4().hex}"
    sync_id = f"{identity}:document"
    client_id = f"{identity}:client"
    viewer = SimpleNamespace(details={"hash": identity, "name": "Poll viewer"})
    monkeypatch.setattr(poll, "current_user", viewer)
    stored_assets = {
        "document": {"type": "html", "path": "saved.html", "fingerprint": "saved"},
    }
    if not legacy_html:
        stored_assets["snapshot"] = {"type": "ydoc", "path": "saved.ydoc"}
    get_text = Mock(return_value="<p>Saved legacy document</p>" if legacy_html else "saved-ydoc")
    monkeypatch.setattr(assets, "get_text", get_text)

    def fresh_entity():
        # Every poll receives a new entity, as in separate HTTP requests, so
        # per-instance property memoization cannot hide an eager Storage read.
        entity = entity_type(testing=True)
        entity.db.update(hash=identity, assets=json.dumps(stored_assets))
        entity.modified = datetime(2026, 9, 19, tzinfo=timezone.utc)
        entity.allowed = Mock(return_value=True)
        return entity

    descriptor = {
        "id": f"document:{sync_id}", "type": "document", "sync_id": sync_id,
        "generation": None, "revision": 0, "presence_digest": None,
    }
    document_key = documents.Sync.DOCUMENTS.key(sync_id)
    presence_key = documents.Sync.PRESENCE.key(sync_id)
    try:
        cold = poll._document_result(descriptor, fresh_entity(), client_id)
        assert cold["status"] == "changed"
        snapshot = cold["payload"]
        assert snapshot["mode"] == "snapshot"
        assert snapshot["ydoc"] == (None if legacy_html else "saved-ydoc")
        assert snapshot["markup"] == ("<p>Saved legacy document</p>" if legacy_html else None)
        get_text.assert_called_once_with("saved.html" if legacy_html else "saved.ydoc", "private")

        descriptor.update({
            key: snapshot[key] for key in ("generation", "revision", "presence_digest")
        })
        get_text.reset_mock()
        for _ in range(3):
            entity = fresh_entity()
            warm = poll._document_result(descriptor, entity, client_id)
            assert warm == {
                "id": descriptor["id"], "type": "document", "status": "unchanged",
                "revision": 0, "poll_after_ms": 2_000,
            }
            entity.allowed.assert_called_once_with(Action.VIEW, user=viewer)
        get_text.assert_not_called()

        documents.cache.redis.delete(document_key)
        recovered = poll._document_result(descriptor, fresh_entity(), client_id)
        assert recovered["status"] == "changed"
        assert recovered["payload"]["generation"] != snapshot["generation"]
        assert recovered["payload"]["mode"] == "snapshot"
        assert recovered["payload"]["ydoc"] == snapshot["ydoc"]
        assert recovered["payload"]["markup"] == snapshot["markup"]
        get_text.assert_called_once_with("saved.html" if legacy_html else "saved.ydoc", "private")
    finally:
        documents.close_presence(client_id, [sync_id])
        documents.cache.redis.delete(document_key, presence_key)


# @matrix polling : authorization document unavailable
@pytest.mark.parametrize("unavailable", ["missing", "forbidden", "wrong-document", "no-document"])
def test_document_poll_rejects_unavailable_documents_before_loading_state(monkeypatch, unavailable):
    viewer = SimpleNamespace(details={"hash": "viewer"})
    monkeypatch.setattr(poll, "current_user", viewer)
    read_cache = Mock(side_effect=AssertionError("Unavailable documents must not read Redis."))
    monkeypatch.setattr(poll.cache, "poll_document", read_cache)
    load_seed = Mock(side_effect=AssertionError("Unavailable documents must not load Storage."))
    entity = SimpleNamespace(
        allowed=Mock(return_value=unavailable != "forbidden"),
        state=load_seed,
        sync_ids={} if unavailable == "no-document" else {
            "document": {"id": "other:document" if unavailable == "wrong-document" else "page:document"},
        },
    )
    descriptor = {
        "id": "document:page", "type": "document", "sync_id": "page:document",
        "generation": None, "revision": 0, "presence_digest": None,
    }

    result = poll._document_result(
        descriptor, None if unavailable == "missing" else entity, "client",
    )

    assert result == {
        "id": "document:page", "type": "document", "status": "unavailable",
        "poll_after_ms": 2_000,
    }
    if unavailable != "missing":
        entity.allowed.assert_called_once_with(Action.VIEW, user=viewer)
    read_cache.assert_not_called()
    load_seed.assert_not_called()
