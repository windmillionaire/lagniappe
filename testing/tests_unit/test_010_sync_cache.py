"""Unit coverage for Redis sync registration helpers."""

import json
from importlib import import_module

import pytest

from lagniappe.core.tools.cache.keys import Sync

sync_cache = import_module("lagniappe.core.tools.cache.sync")


class _FakePipeline:
    def __init__(self):
        self.commands = []
        self.hget_result = None
        self.smembers_result = {b"token-1"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def sadd(self, key, value):
        self.commands.append(("sadd", key, value))

    def expire(self, key, value):
        self.commands.append(("expire", key, value))

    def hset(self, key, field, value):
        self.commands.append(("hset", key, field, value))

    def hexpire(self, key, ttl, field):
        self.commands.append(("hexpire", key, ttl, field))

    def hget(self, key, field):
        self.commands.append(("hget", key, field))

    def hdel(self, key, *fields):
        self.commands.append(("hdel", key, *fields))

    def srem(self, key, value):
        self.commands.append(("srem", key, value))

    def smembers(self, key):
        self.commands.append(("smembers", key))

    def execute(self):
        results = []
        for command, *_args in self.commands:
            if command == "hget":
                results.append(self.hget_result)
            elif command == "smembers":
                results.append(self.smembers_result)
            else:
                results.append(True)
        return results


class _FakeCache:
    def __init__(self):
        self.pipe = _FakePipeline()
        self.hmget_calls = []
        self.valid_tokens = None

    def pipeline(self):
        return self.pipe

    def hmget(self, key, tokens):
        self.hmget_calls.append((key, list(tokens)))
        return [
            json.dumps({"name": "Test User", "token": token})
            if self.valid_tokens is None or token in self.valid_tokens
            else None
            for token in tokens
        ]


# @features sync
# @dimensions composite-sync-id registration
@pytest.mark.unit
def test_sync_id_hashes_parse_widget_ids():
    assert sync_cache._entity_hashes("abc:document") == ["abc"]
    assert sync_cache._entity_hashes("abc:form") == ["abc"]
    assert sync_cache._entity_hashes("abc:def:form") == ["abc", "def"]
    assert sync_cache._entity_hashes(None) == []


# @features sync
# @dimensions document sync-state composite-sync-id registration
@pytest.mark.unit
def test_get_state_registers_every_hash_in_composite_sync_id(monkeypatch):
    fake_cache = _FakeCache()
    monkeypatch.setattr(sync_cache, "cache", fake_cache)

    state, users = sync_cache.get_state(
        "pagehash:formhash:form",
        "token-1",
        {"name": "Test User"},
    )

    assert state == {}
    assert users == [{"name": "Test User", "token": "token-1"}]

    sadd_keys = [entry[1] for entry in fake_cache.pipe.commands if entry[0] == "sadd"]
    assert Sync.WIDGET.key("pagehash:formhash:form") in sadd_keys
    assert Sync.ENTITY.key("pagehash") in sadd_keys
    assert Sync.ENTITY.key("formhash") in sadd_keys


# @features sync
# @dimensions sync-state state-only
@pytest.mark.unit
def test_get_cached_state_does_not_register_viewer(monkeypatch):
    fake_cache = _FakeCache()
    fake_cache.pipe.hget_result = json.dumps({"submission": {"field": "value"}})
    monkeypatch.setattr(sync_cache, "cache", fake_cache)

    state = sync_cache.get_cached_state("pagehash:formhash:form")

    assert state == {"submission": {"field": "value"}}
    assert ("hget", Sync.STATE.value, "pagehash:formhash:form") in fake_cache.pipe.commands
    assert (
        "hexpire",
        Sync.STATE.value,
        sync_cache.FIVE_MINUTES,
        "pagehash:formhash:form",
    ) in fake_cache.pipe.commands
    assert not any(command[0] == "sadd" for command in fake_cache.pipe.commands)
    assert not any(command[0] == "hset" for command in fake_cache.pipe.commands)


# @features sync
# @dimensions sync-state invalidation
@pytest.mark.unit
def test_clear_state_deletes_cached_widget_state(monkeypatch):
    fake_cache = _FakeCache()
    monkeypatch.setattr(sync_cache, "cache", fake_cache)

    sync_cache.clear_state("pagehash:formhash:form")

    assert fake_cache.pipe.commands == [
        ("hdel", Sync.STATE.value, "pagehash:formhash:form")
    ]


# @features sync
# @dimensions document stale-sessions composite-sync-id deregistration
@pytest.mark.unit
def test_deregister_removes_token_from_composite_hashes(monkeypatch):
    fake_cache = _FakeCache()
    monkeypatch.setattr(sync_cache, "cache", fake_cache)

    sync_cache.deregister("token-1", ["pagehash:formhash:form"])

    srem_keys = [entry[1] for entry in fake_cache.pipe.commands if entry[0] == "srem"]
    assert Sync.WIDGET.key("pagehash:formhash:form") in srem_keys
    assert Sync.ENTITY.key("pagehash") in srem_keys
    assert Sync.ENTITY.key("formhash") in srem_keys


# @features sync
# @dimensions stale-token invalidation
@pytest.mark.unit
def test_discard_viewer_tokens_invalidates_registrations(monkeypatch):
    fake_cache = _FakeCache()
    monkeypatch.setattr(sync_cache, "cache", fake_cache)

    sync_cache.discard_viewer_tokens(["token-1", "token-2", "token-1", None])

    assert ("hdel", Sync.USERS.value, "token-1", "token-2") in (
        fake_cache.pipe.commands
    )


# @features sync
# @dimensions active-viewers entity-registration dedupe empty-input stale-sessions
@pytest.mark.unit
def test_active_viewers_unions_entity_registration_sets(monkeypatch):
    fake_cache = _FakeCache()
    monkeypatch.setattr(sync_cache, "cache", fake_cache)

    assert sync_cache.active_viewers([]) == set()
    assert fake_cache.pipe.commands == []

    assert sync_cache.active_viewers(["pagehash", "formhash"]) == {"token-1"}
    assert fake_cache.hmget_calls == [(Sync.USERS.value, ["token-1"])]
    assert fake_cache.pipe.commands == [
        ("smembers", Sync.ENTITY.key("pagehash")),
        ("smembers", Sync.ENTITY.key("formhash")),
    ]

    fake_cache.valid_tokens = set()
    assert sync_cache.active_viewers(["pagehash"]) == set()
