"""Revisioned Redis state for collaborative documents and presence."""

import hashlib
import json
import uuid

from redis import WatchError

from .core import cache
from .keys import Sync


DOCUMENT_TTL_SECONDS = 300
PRESENCE_TTL_SECONDS = 60
CHECKPOINT_DELTA_COUNT = 64
MAX_TRANSACTION_ATTEMPTS = 8


# @testable false
# @covered-by lagniappe/core/tools/cache/documents.py::poll_document
# @covered-by lagniappe/core/tools/cache/documents.py::apply_document_update
# @reason stored-state normalization is exercised through the public cache operations
def _new_state(seed):
    seed = dict(seed or {})
    return {
        "generation": str(uuid.uuid4()),
        "revision": 0,
        "base_revision": 0,
        "ydoc": seed.get("ydoc"),
        "markup": seed.get("markup"),
        "fingerprint": seed.get("fingerprint"),
        "checkpoint_author_hash": None,
        "authors": {},
        "updates": [],
    }


# @testable false
# @covered-by lagniappe/core/tools/cache/documents.py::poll_document
# @covered-by lagniappe/core/tools/cache/documents.py::apply_document_update
# @reason Redis byte decoding is exercised through public document-state operations
def _decode(value):
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)


# @testable false
# @covered-by lagniappe/core/tools/cache/documents.py::apply_document_update
# @reason author projection is exercised through the public document update contract
def _author_projection(author):
    """Return the minimal identity needed to attribute a transient revision."""
    if not isinstance(author, dict):
        return None
    author_hash = author.get("hash")
    name = author.get("name")
    if not isinstance(author_hash, str) or not author_hash:
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    return {"hash": author_hash, "name": name.strip()}


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_document_transactions_are_key_isolated_and_expiring
# @features sync polling
# @dimensions document concurrency isolation ttl
def _mutate(sync_id, seed, transform):
    """Apply ``transform`` under an isolated optimistic document transaction."""
    document_key = Sync.DOCUMENTS.key(sync_id)
    for _attempt in range(MAX_TRANSACTION_ATTEMPTS):
        with cache.redis.pipeline() as pipe:
            try:
                pipe.watch(document_key)
                state = _decode(pipe.get(document_key))
                if state is None:
                    state = _new_state(seed)
                result = transform(state)
                pipe.multi()
                pipe.set(
                    document_key,
                    json.dumps(state, separators=(",", ":"), sort_keys=True),
                    ex=DOCUMENT_TTL_SECONDS,
                )
                pipe.execute()
                return state, result
            except WatchError:
                continue
    raise RuntimeError("Collaborative document state changed too frequently.")


# @testable false
# @covered-by lagniappe/core/tools/cache/documents.py::poll_document
# @reason presence serialization is exercised through the public poll contract
def _presence_payload(client_id, user):
    return json.dumps(
        {**dict(user or {}), "client_id": client_id},
        separators=(",", ":"),
        sort_keys=True,
    )


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_presence_uses_expiring_client_hash_fields
# @features sync polling
# @dimensions presence ttl hash-field
def _register_presence(sync_id, client_id, user):
    presence_key = Sync.PRESENCE.key(sync_id)
    with cache.pipeline() as pipe:
        pipe.sadd(presence_key, client_id)
        pipe.expire(presence_key, DOCUMENT_TTL_SECONDS)
        pipe.hset(
            Sync.CLIENTS.value,
            client_id,
            _presence_payload(client_id, user),
        )
        pipe.hexpire(
            Sync.CLIENTS.value,
            PRESENCE_TTL_SECONDS,
            client_id,
        )
        pipe.smembers(presence_key)
        client_ids = pipe.execute()[-1]

    client_ids = sorted(
        value.decode("utf-8") if isinstance(value, bytes) else str(value)
        for value in client_ids
    )
    raw_users = cache.hmget(Sync.CLIENTS.value, client_ids) if client_ids else []
    users = [_decode(value) for value in raw_users if value]
    users.sort(key=lambda value: value.get("client_id", ""))
    digest = hashlib.sha256(
        json.dumps(users, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return users, digest


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_revisioned_document_poll_returns_snapshot_then_deltas
# @features sync polling
# @dimensions document revision snapshot delta presence author-attribution
def poll_document(
    sync_id,
    *,
    seed,
    client_id,
    user,
    generation=None,
    revision=None,
    presence_digest=None,
):
    """Return the state changes and presence visible after ``revision``."""
    state, _result = _mutate(sync_id, seed, lambda current: None)
    users, current_presence_digest = _register_presence(
        sync_id,
        client_id,
        user,
    )
    known_revision = int(revision or 0)
    generation_matches = generation == state["generation"]
    requires_snapshot = (
        not generation_matches or known_revision < int(state["base_revision"])
    )
    updates = [
        update
        for update in state.get("updates", [])
        if int(update.get("revision") or 0) > known_revision
    ]
    payload = {
        "generation": state["generation"],
        "revision": int(state["revision"]),
        "fingerprint": state.get("fingerprint"),
        "mode": "snapshot" if requires_snapshot else "delta",
        "updates": updates,
        "checkpoint_required": (
            len(state.get("updates", [])) >= CHECKPOINT_DELTA_COUNT
        ),
    }
    if requires_snapshot:
        payload["ydoc"] = state.get("ydoc")
        payload["markup"] = state.get("markup")
        if generation_matches and state.get("checkpoint_author_hash"):
            payload["user_hash"] = state["checkpoint_author_hash"]
    referenced_authors = {
        update.get("user_hash") for update in updates if update.get("user_hash")
    }
    if payload.get("user_hash"):
        referenced_authors.add(payload["user_hash"])
    authors = state.get("authors", {})
    projected_authors = {
        author_hash: authors[author_hash]
        for author_hash in referenced_authors
        if author_hash in authors
    }
    if projected_authors:
        payload["authors"] = projected_authors
    if presence_digest != current_presence_digest:
        payload.update(
            {
                "users": users,
                "user": dict(user or {}),
                "presence_digest": current_presence_digest,
            }
        )
    return payload


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_revisioned_document_update_preserves_stale_branch_delta
# @tests tests_unit/test_010_sync_cache.py::test_revisioned_document_poll_returns_snapshot_then_deltas
# @features sync polling
# @dimensions document revision concurrency compaction author-attribution
def apply_document_update(
    sync_id,
    *,
    seed,
    generation=None,
    revision=None,
    update=None,
    ydoc=None,
    author=None,
):
    """Append one Yjs update and compact only from a current client."""
    author = _author_projection(author)
    author_hash = author["hash"] if author else None

    # @testable false
    # @covered-by lagniappe/core/tools/cache/documents.py::apply_document_update
    # @reason transaction-local state mutation is asserted through update acknowledgements
    def transform(state):
        previous_revision = int(state.get("revision") or 0)
        current_client = (
            generation == state.get("generation")
            and int(revision or 0) == previous_revision
        )
        if update:
            next_revision = previous_revision + 1
            state["revision"] = next_revision
            if author:
                state.setdefault("authors", {})[author_hash] = author
            state.setdefault("updates", []).append(
                {
                    "revision": next_revision,
                    "update": update,
                    "user_hash": author_hash,
                }
            )
        if current_client and ydoc:
            checkpoint_authors = {
                item.get("user_hash")
                for item in state.get("updates", [])
            }
            state["ydoc"] = ydoc
            state["base_revision"] = int(state["revision"])
            state["checkpoint_author_hash"] = (
                checkpoint_authors.pop() if len(checkpoint_authors) == 1 else None
            )
            state["updates"] = []
        referenced_authors = {
            item.get("user_hash")
            for item in state.get("updates", [])
            if item.get("user_hash")
        }
        if state.get("checkpoint_author_hash"):
            referenced_authors.add(state["checkpoint_author_hash"])
        state["authors"] = {
            item_hash: item
            for item_hash, item in state.get("authors", {}).items()
            if item_hash in referenced_authors
        }
        return {
            "generation": state["generation"],
            "revision": int(state["revision"]),
            "fingerprint": state.get("fingerprint"),
            "checkpoint_accepted": bool(current_client and ydoc),
        }

    _state, result = _mutate(sync_id, seed, transform)
    return result


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_revisioned_document_asset_refresh_keeps_live_generation
# @features sync polling
# @dimensions document persistence fingerprint
def update_document_asset(sync_id, *, seed):
    """Refresh durable document metadata without discarding live revisions."""

    # @testable false
    # @covered-by lagniappe/core/tools/cache/documents.py::update_document_asset
    # @reason transaction-local asset refresh is asserted through the public operation
    def transform(state):
        state["fingerprint"] = seed.get("fingerprint")
        state["markup"] = seed.get("markup")
        return None

    state, _result = _mutate(sync_id, seed, transform)
    return state


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_revisioned_presence_close_removes_client
# @features sync polling
# @dimensions document presence lifecycle
def close_presence(client_id, sync_ids):
    """Remove a browser client from the supplied collaborative documents."""
    if not client_id:
        return
    with cache.pipeline() as pipe:
        for sync_id in dict.fromkeys(sync_ids or ()):
            pipe.srem(Sync.PRESENCE.key(sync_id), client_id)
        pipe.hdel(Sync.CLIENTS.value, client_id)
        pipe.execute()


# @testable false
# @covered-by lagniappe/core/mutations/executor.py::execute_post_commit
# @reason external entity invalidation calls this one-command cache boundary
def clear_document(sync_id):
    """Discard an externally invalidated live generation."""
    cache.redis.delete(Sync.DOCUMENTS.key(sync_id))
