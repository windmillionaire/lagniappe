"""Unit coverage for revisioned Redis document state."""

import json
from importlib import import_module

import pytest

documents = import_module("lagniappe.core.tools.cache.documents")


class _DocumentPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.key = None
        self.pending = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def watch(self, key):
        self.key = key
        self.redis.watched.append(key)

    def get(self, key):
        assert key == self.key
        return self.redis.values.get(key)

    def multi(self):
        return None

    def set(self, key, value, *, ex):
        assert key == self.key
        self.pending = (key, value, ex)

    def execute(self):
        if (
            self.redis.conflict_state is not None
            and not self.redis.conflict_injected
        ):
            self.redis.values[self.key] = json.dumps(
                self.redis.conflict_state,
                separators=(",", ":"),
                sort_keys=True,
            )
            self.redis.conflict_injected = True
            raise documents.WatchError()
        key, value, expires = self.pending
        self.redis.values[key] = value
        self.redis.expirations[key] = expires
        self.redis.sets.append(key)
        return [True]


class _DocumentRedis:
    def __init__(self):
        self.after_getex_state = None
        self.conflict_injected = False
        self.conflict_state = None
        self.expirations = {}
        self.getex_calls = []
        self.sets = []
        self.values = {}
        self.watched = []

    def pipeline(self):
        return _DocumentPipeline(self)

    def getex(self, key, *, ex):
        self.getex_calls.append((key, ex))
        value = self.values.get(key)
        if value is not None:
            self.expirations[key] = ex
        if self.after_getex_state is not None:
            self.values[key] = json.dumps(
                self.after_getex_state,
                separators=(",", ":"),
                sort_keys=True,
            )
            self.after_getex_state = None
        return value


# @matrix polling sync : concurrency document isolation ttl
@pytest.mark.unit
def test_document_transactions_are_key_isolated_and_expiring(monkeypatch):
    redis = _DocumentRedis()
    monkeypatch.setattr(documents.cache, "_redis", redis)

    first, _ = documents._mutate(
        "page-one:document",
        {"fingerprint": "first"},
        lambda state: state.update(revision=1),
    )
    second, _ = documents._mutate(
        "page-two:document",
        {"fingerprint": "second"},
        lambda state: state.update(revision=2),
    )

    assert first["fingerprint"] == "first"
    assert second["fingerprint"] == "second"
    assert len(set(redis.watched)) == 2
    assert all(
        expires == documents.DOCUMENT_TTL_SECONDS
        for expires in redis.expirations.values()
    )


def _without_presence(monkeypatch):
    monkeypatch.setattr(
        documents,
        "_register_presence",
        lambda *_args: ([], "presence-empty"),
    )


# @matrix polling : document read-path ttl write-amplification
@pytest.mark.unit
def test_existing_document_poll_refreshes_ttl_without_full_write(monkeypatch):
    redis = _DocumentRedis()
    state = documents._new_state(
        {"ydoc": "snapshot-0", "fingerprint": "fingerprint-0"}
    )
    document_key = documents.Sync.DOCUMENTS.key("page:document")
    redis.values[document_key] = json.dumps(state)
    monkeypatch.setattr(documents.cache, "_redis", redis)
    _without_presence(monkeypatch)

    payload = documents.poll_document(
        "page:document",
        seed={"ydoc": "stale-seed"},
        client_id="client-1",
        user={"hash": "user-1"},
    )

    assert payload["generation"] == state["generation"]
    assert payload["ydoc"] == "snapshot-0"
    assert redis.getex_calls == [(document_key, documents.DOCUMENT_TTL_SECONDS)]
    assert redis.expirations[document_key] == documents.DOCUMENT_TTL_SECONDS
    assert redis.watched == []
    assert redis.sets == []


# @matrix polling : concurrency document read-path
# @matrix sync : document revision
@pytest.mark.unit
def test_document_poll_does_not_overwrite_a_concurrent_update(monkeypatch):
    redis = _DocumentRedis()
    initial_state = documents._new_state(
        {"ydoc": "snapshot-0", "fingerprint": "fingerprint-0"}
    )
    updated_state = {
        **initial_state,
        "revision": 1,
        "updates": [
            {"revision": 1, "update": "concurrent-delta", "user_hash": None}
        ],
    }
    document_key = documents.Sync.DOCUMENTS.key("page:document")
    redis.values[document_key] = json.dumps(initial_state)
    redis.after_getex_state = updated_state
    monkeypatch.setattr(documents.cache, "_redis", redis)
    _without_presence(monkeypatch)

    first_payload = documents.poll_document(
        "page:document",
        seed={"ydoc": "stale-seed"},
        client_id="client-1",
        user={"hash": "user-1"},
    )
    next_state = documents._read_document_state(
        "page:document",
        {"ydoc": "stale-seed"},
    )

    assert first_payload["revision"] == 0
    assert next_state["revision"] == 1
    assert next_state["updates"] == updated_state["updates"]
    assert documents._decode(redis.values[document_key])["revision"] == 1
    assert redis.watched == []
    assert redis.sets == []


# @matrix polling : document initialization ttl
@pytest.mark.unit
def test_missing_document_poll_initializes_from_durable_seed(monkeypatch):
    redis = _DocumentRedis()
    document_key = documents.Sync.DOCUMENTS.key("page:document")
    monkeypatch.setattr(documents.cache, "_redis", redis)
    _without_presence(monkeypatch)

    payload = documents.poll_document(
        "page:document",
        seed={"ydoc": "durable-snapshot", "fingerprint": "durable-fingerprint"},
        client_id="client-1",
        user={"hash": "user-1"},
    )

    stored = documents._decode(redis.values[document_key])
    assert payload["generation"] == stored["generation"]
    assert payload["ydoc"] == "durable-snapshot"
    assert payload["fingerprint"] == "durable-fingerprint"
    assert redis.getex_calls == [(document_key, documents.DOCUMENT_TTL_SECONDS)]
    assert redis.watched == [document_key]
    assert redis.sets == [document_key]
    assert redis.expirations[document_key] == documents.DOCUMENT_TTL_SECONDS


# @matrix polling : concurrency document initialization
@pytest.mark.unit
def test_document_poll_initialization_conflict_keeps_winning_generation(monkeypatch):
    redis = _DocumentRedis()
    winning_state = documents._new_state(
        {"ydoc": "winning-snapshot", "fingerprint": "winning-fingerprint"}
    )
    winning_state.update(
        revision=1,
        updates=[{"revision": 1, "update": "concurrent-delta", "user_hash": None}],
    )
    redis.conflict_state = winning_state
    document_key = documents.Sync.DOCUMENTS.key("page:document")
    monkeypatch.setattr(documents.cache, "_redis", redis)
    _without_presence(monkeypatch)

    payload = documents.poll_document(
        "page:document",
        seed={"ydoc": "losing-snapshot"},
        client_id="client-1",
        user={"hash": "user-1"},
    )

    stored = documents._decode(redis.values[document_key])
    assert payload["generation"] == winning_state["generation"]
    assert payload["revision"] == 1
    assert payload["updates"] == winning_state["updates"]
    assert stored["generation"] == winning_state["generation"]
    assert stored["updates"] == winning_state["updates"]
    assert redis.conflict_injected is True
    assert redis.watched == [document_key, document_key]
    assert redis.sets == [document_key]


class _PresenceRegistrationPipeline:
    def __init__(self):
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def sadd(self, key, value):
        self.commands.append(("sadd", key, value))

    def expire(self, key, seconds):
        self.commands.append(("expire", key, seconds))

    def hset(self, key, field, value):
        self.commands.append(("hset", key, field, value))

    def hexpire(self, key, seconds, field):
        self.commands.append(("hexpire", key, seconds, field))

    def smembers(self, key):
        self.commands.append(("smembers", key))

    def execute(self):
        return [1, True, 1, [1], {b"client-1"}]


# @matrix polling sync : hash-field presence ttl
@pytest.mark.unit
def test_presence_uses_expiring_client_hash_fields(monkeypatch):
    pipeline = _PresenceRegistrationPipeline()
    user = {"hash": "user-1", "name": "Example User"}
    monkeypatch.setattr(documents.cache, "pipeline", lambda: pipeline)
    monkeypatch.setattr(
        documents.cache,
        "hmget",
        lambda key, fields: [
            documents._presence_payload("client-1", user).encode("utf-8")
        ],
    )

    users, digest = documents._register_presence(
        "page:document",
        "client-1",
        user,
    )

    assert (
        "hexpire",
        documents.Sync.CLIENTS.value,
        documents.PRESENCE_TTL_SECONDS,
        "client-1",
    ) in pipeline.commands
    assert users == [{**user, "client_id": "client-1"}]
    assert len(digest) == 64


@pytest.fixture
def document_state(monkeypatch):
    state = documents._new_state(
        {"ydoc": "snapshot-0", "fingerprint": "fingerprint-0"}
    )

    def mutate(_sync_id, _seed, transform):
        result = transform(state)
        return state, result

    monkeypatch.setattr(documents, "_mutate", mutate)
    monkeypatch.setattr(
        documents,
        "_read_document_state",
        lambda _sync_id, _seed: state,
    )
    monkeypatch.setattr(
        documents,
        "_register_presence",
        lambda *_args: (
            [{"client_id": "client-1", "hash": "user-1"}],
            "presence-1",
        ),
    )
    return state


# @matrix polling sync : author-attribution delta document presence revision snapshot
@pytest.mark.unit
def test_revisioned_document_poll_returns_snapshot_then_deltas(document_state):
    initial = documents.poll_document(
        "page:document",
        seed={},
        client_id="client-1",
        user={"hash": "user-1"},
    )
    assert initial["mode"] == "snapshot"
    assert initial["ydoc"] == "snapshot-0"
    assert "user_hash" not in initial
    assert initial["users"][0]["client_id"] == "client-1"

    acknowledgement = documents.apply_document_update(
        "page:document",
        seed={},
        generation=document_state["generation"],
        revision=0,
        update="delta-1",
        author={"hash": "user-1", "name": "First User"},
    )
    assert acknowledgement["revision"] == 1

    changed = documents.poll_document(
        "page:document",
        seed={},
        client_id="client-1",
        user={"hash": "user-1"},
        generation=document_state["generation"],
        revision=0,
        presence_digest="presence-1",
    )
    assert changed["mode"] == "delta"
    assert changed["updates"] == [
        {"revision": 1, "update": "delta-1", "user_hash": "user-1"}
    ]
    assert changed["authors"] == {
        "user-1": {"hash": "user-1", "name": "First User"}
    }
    assert "users" not in changed

    checkpoint = documents.apply_document_update(
        "page:document",
        seed={},
        generation=document_state["generation"],
        revision=1,
        update="delta-2",
        ydoc="snapshot-2",
        author={"hash": "user-1", "name": "First User"},
    )
    assert checkpoint["checkpoint_accepted"] is True

    compacted = documents.poll_document(
        "page:document",
        seed={},
        client_id="client-1",
        user={"hash": "user-1"},
        generation=document_state["generation"],
        revision=1,
        presence_digest="presence-1",
    )
    assert compacted["mode"] == "snapshot"
    assert compacted["ydoc"] == "snapshot-2"
    assert compacted["user_hash"] == "user-1"
    assert compacted["authors"] == {
        "user-1": {"hash": "user-1", "name": "First User"}
    }
    assert compacted["updates"] == []

    documents.apply_document_update(
        "page:document",
        seed={},
        generation=document_state["generation"],
        revision=2,
        update="delta-3",
        author={"hash": "user-1", "name": "First User"},
    )
    documents.apply_document_update(
        "page:document",
        seed={},
        generation=document_state["generation"],
        revision=3,
        update="delta-4",
        ydoc="snapshot-4",
        author={"hash": "user-2", "name": "Second User"},
    )
    mixed_authors = documents.poll_document(
        "page:document",
        seed={},
        client_id="client-1",
        user={"hash": "user-1"},
        generation=document_state["generation"],
        revision=2,
        presence_digest="presence-1",
    )
    assert mixed_authors["mode"] == "snapshot"
    assert "user_hash" not in mixed_authors
    assert "authors" not in mixed_authors


# @matrix polling sync : compaction concurrency document revision
@pytest.mark.unit
def test_revisioned_document_update_preserves_stale_branch_delta(document_state):
    current = documents.apply_document_update(
        "page:document",
        seed={},
        generation=document_state["generation"],
        revision=0,
        update="delta-current",
    )
    stale = documents.apply_document_update(
        "page:document",
        seed={},
        generation=document_state["generation"],
        revision=0,
        update="delta-stale",
        ydoc="stale-checkpoint",
    )

    assert current["revision"] == 1
    assert stale["revision"] == 2
    assert stale["checkpoint_accepted"] is False
    assert document_state["ydoc"] == "snapshot-0"
    assert [item["update"] for item in document_state["updates"]] == [
        "delta-current",
        "delta-stale",
    ]


# @matrix polling sync : document fingerprint persistence
@pytest.mark.unit
def test_revisioned_document_asset_refresh_keeps_live_generation(document_state):
    generation = document_state["generation"]
    document_state["updates"].append({"revision": 1, "update": "delta"})
    documents.update_document_asset(
        "page:document",
        seed={"fingerprint": "fingerprint-1", "markup": "<p>Saved</p>"},
    )

    assert document_state["generation"] == generation
    assert document_state["fingerprint"] == "fingerprint-1"
    assert document_state["updates"] == [{"revision": 1, "update": "delta"}]


class _PresencePipeline:
    def __init__(self):
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def srem(self, key, value):
        self.commands.append(("srem", key, value))

    def hdel(self, key, value):
        self.commands.append(("hdel", key, value))

    def execute(self):
        return [True] * len(self.commands)


# @matrix polling sync : document lifecycle presence
@pytest.mark.unit
def test_revisioned_presence_close_removes_client(monkeypatch):
    pipeline = _PresencePipeline()
    monkeypatch.setattr(documents.cache, "pipeline", lambda: pipeline)

    documents.close_presence(
        "client-1",
        ["page:document", "page:document", "project:document"],
    )

    assert sum(command[0] == "srem" for command in pipeline.commands) == 2
    assert pipeline.commands[-1][0] == "hdel"
