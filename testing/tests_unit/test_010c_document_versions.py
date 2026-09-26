from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools import document_history as history
from testing.utility.test_entities import TestEntities

pytestmark = pytest.mark.unit


# @matrix document-history : backups permissions pagination generation-pinned
def test_storage_backups_are_scoped_paginated_and_generation_bound(monkeypatch):
    entity = SimpleNamespace(hash="document-owner", urlsafe_key="page-key")
    other = SimpleNamespace(hash="other-owner", urlsafe_key="other-key")
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    calls = []
    def blob(name, deleted=True):
        return SimpleNamespace(name=name, generation=1234, time_deleted=now if deleted else None, time_created=now)
    objects = [blob("document-owner_document.html"),
               blob("document-owner_document_" + "a" * 32 + ".html"),
               blob("document-owner_document_" + "b" * 32 + ".html", False),
               blob("document-owner_document_other.html"),
               blob("other-owner_document.html")]
    def listing(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(pages=iter([objects]), next_page_token="next-page")
    monkeypatch.setattr(history.assets.DATA, "bucket", lambda visibility: SimpleNamespace(list_blobs=listing))
    downloaded = []
    monkeypatch.setattr(history.assets, "get_text", lambda *args, **kwargs: downloaded.append((args, kwargs)) or "<p>Old version</p>")
    result = history.list_backups(entity)
    assert len(result["entries"]) == 2
    assert calls == [{"prefix": "document-owner_document", "versions": True, "page_size": 50, "max_results": 50, "page_token": None}]
    assert not downloaded
    token = result["entries"][0]["key"]
    assert history.read_backup(entity, token) == "<p>Old version</p>"
    assert downloaded == [(("document-owner_document.html", "private"), {"generation": 1234})]
    for owner, bad_token in [(other, token), (entity, token + "tampered")]:
        with pytest.raises(ValidationError):
            history.read_backup(owner, bad_token)
    with pytest.raises(ValidationError):
        history.list_backups(other, result["cursor"])
    history.list_backups(entity, result["cursor"])
    assert calls[-1]["page_token"] == "next-page"


# @matrix document-history : recovery idempotency empty-content
def test_recovery_pin_retry_is_scoped_and_keeps_empty_versions(monkeypatch):
    entity = SimpleNamespace(hash="page", key="page")
    user = SimpleNamespace(hash="user")
    rows, creates = {}, []
    monkeypatch.setattr(history.utility, "create_named_key", lambda kind, identifier, parent: (parent.key, identifier))
    monkeypatch.setattr(history.Entities, "fetch_one", lambda key, **kwargs: rows.get(key))
    def create(owner, **kwargs):
        creates.append(kwargs)
        return SimpleNamespace(key=kwargs["key"])
    monkeypatch.setattr(history.Entities.DOCUMENT_HISTORY, "create", create)
    monkeypatch.setattr(history.Entities, "save", lambda row: rows.update({row.key: row}))
    options = {"html": "", "name": "Before restoration", "operation_id": "a" * 64}
    first = history.recovery_pin(entity, user, **options)
    assert history.recovery_pin(entity, user, **options) is first
    assert len(creates) == 1 and creates[0]["allow_empty"] is True
    assert creates[0]["html"] == ""
    second = history.recovery_pin(entity, SimpleNamespace(hash="other-user"), **options)
    assert second.key != first.key
    changed = history.recovery_pin(entity, user, **{**options, "html": "<p>More recent work</p>"})
    assert changed.key != first.key
    with pytest.raises(ValidationError):
        history.recovery_pin(entity, user, **{**options, "operation_id": "arbitrary-path"})


# @source lagniappe/core/entities/history.py::DocumentHistory
# @matrix document-history : validation current-content
def test_empty_recovery_version_is_restorable_without_allowing_empty_manual_pins(monkeypatch):
    page = TestEntities.get("PAGE", {"name": "Empty document", "hash": "empty-recovery"})
    from lagniappe.core.entities import entity as entity_module
    monkeypatch.setattr(entity_module.database_utility, "create_key", lambda *args, **kwargs: "empty-version")
    writes = []
    monkeypatch.setattr(history.Entities.DOCUMENT_HISTORY, "save_asset", lambda self, *args: writes.append(args))
    with pytest.raises(ValidationError, match="Document content is required"):
        history.Entities.DOCUMENT_HISTORY.create(page, name="Empty", html="")
    saved = history.Entities.DOCUMENT_HISTORY.create(page, name="Before replacement", html="", allow_empty=True)
    assert saved.pinned
    assert writes == [("<p></p>", "document", "html")]
