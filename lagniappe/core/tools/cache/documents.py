"""Revisioned Redis state for collaborative documents and presence."""

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Literal, NotRequired, TypedDict, cast

import hashlib
import json
import uuid
from contextlib import contextmanager

from redis import WatchError

from .core import cache
from .keys import Sync


class DocumentSeed(TypedDict, total=False):
    ydoc: str | None
    markup: str | None
    fingerprint: str | None


class DocumentDelta(TypedDict):
    revision: int
    update: str
    user_hash: str | None


class DocumentAuthor(TypedDict):
    hash: str
    name: str


class DocumentReader(TypedDict):
    id: str
    hash: NotRequired[str]
    name: NotRequired[str]


class PresentReader(DocumentReader):
    client_id: str


class DocumentState(TypedDict):
    generation: str
    revision: int
    base_revision: int
    ydoc: str | None
    markup: str | None
    fingerprint: str | None
    checkpoint_author_hash: str | None
    authors: dict[str, DocumentAuthor]
    updates: list[DocumentDelta]


class DocumentAcknowledgement(TypedDict):
    generation: str
    revision: int
    fingerprint: str | None
    checkpoint_accepted: bool


class DocumentPoll(TypedDict):
    generation: str
    revision: int
    fingerprint: str | None
    mode: Literal["snapshot", "delta"]
    updates: list[DocumentDelta]
    checkpoint_required: bool
    ydoc: NotRequired[str | None]
    markup: NotRequired[str | None]
    user_hash: NotRequired[str]
    authors: NotRequired[dict[str, DocumentAuthor]]
    users: NotRequired[list[PresentReader]]
    user: NotRequired[DocumentReader]
    presence_digest: NotRequired[str]


DOCUMENT_TTL_SECONDS = 300
PRESENCE_TTL_SECONDS = 60
CHECKPOINT_DELTA_COUNT = 64
MAX_TRANSACTION_ATTEMPTS = 8


@contextmanager
def document_write_lock(sync_id: str) -> Iterator[None]:
    """Serialize checkpoint preparation; durable CAS still fences expired locks."""
    with cache.redis.lock(f"{Sync.DOCUMENTS.key(sync_id)}:write", timeout=60, blocking_timeout=5):
        yield


def publish_document_checkpoint(sync_id: str, *, seed: DocumentSeed) -> DocumentState:
    """Reconcile a committed checkpoint, retaining any uncheckpointed CRDT work."""
    from lagniappe.core.tools.document_crdt import merge_documents

    def transform(state):
        state["ydoc"] = merge_documents(seed.get("ydoc"), state.get("ydoc"), *(item["update"] for item in state.get("updates", [])))
        state["generation"] = str(uuid.uuid4())
        state["revision"] = int(state["revision"]) + 1
        state["base_revision"] = state["revision"]
        state["fingerprint"] = seed.get("fingerprint")
        state["markup"] = seed.get("markup")
        state["updates"] = []
        state["authors"] = {}
        state["checkpoint_author_hash"] = None

    state, _result = _mutate(sync_id, seed, transform)
    return state


def current_document_state(
    sync_id: str, *, seed: DocumentSeed, reconcile: bool = True
) -> DocumentState:
    """Read under the write lock; only reconcile a freshly loaded durable seed."""
    state = _read_document_state(sync_id, seed)
    if reconcile and state.get("fingerprint") != seed.get("fingerprint") and seed.get("ydoc"):
        state = publish_document_checkpoint(sync_id, seed=seed)
    return state


def _new_state(seed: DocumentSeed) -> DocumentState:
    seed = seed or {}
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


def _decode(value):
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)


def _author_projection(author: object) -> DocumentAuthor | None:
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


def _mutate[T](
    sync_id: str, seed: DocumentSeed, transform: Callable[[DocumentState], T]
) -> tuple[DocumentState, T]:
    """Apply ``transform`` under an isolated optimistic document transaction."""
    document_key = Sync.DOCUMENTS.key(sync_id)
    for _attempt in range(MAX_TRANSACTION_ATTEMPTS):
        with cache.redis.pipeline() as pipe:
            try:
                pipe.watch(document_key)
                state = cast(DocumentState | None, _decode(pipe.get(document_key)))  # The document key stores this schema.
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


def _read_document_state(
    sync_id: str, seed: DocumentSeed | Callable[[], DocumentSeed]
) -> DocumentState:
    """Read with a sliding TTL; resolve a seed mapping or factory only on a miss."""
    document_key = Sync.DOCUMENTS.key(sync_id)
    state = cast(DocumentState | None, _decode(
        cache.redis.getex(
            document_key,
            ex=DOCUMENT_TTL_SECONDS,
        )
    ))
    if state is not None:
        return state

    # Load durable assets outside WATCH, once even if initialization retries.
    # _mutate rechecks Redis so a concurrent generation wins over this seed.
    if callable(seed):
        seed = seed()
    state, _result = _mutate(sync_id, seed, lambda current: None)
    return state


def _presence_payload(client_id, user):
    return json.dumps(
        {**dict(user or {}), "client_id": client_id},
        separators=(",", ":"),
        sort_keys=True,
    )


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
    users = [json.loads(value) for value in raw_users if value]
    users.sort(key=lambda value: value.get("client_id", ""))
    digest = hashlib.sha256(
        json.dumps(users, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return users, digest


def poll_document(
    sync_id: str,
    *,
    seed: DocumentSeed | Callable[[], DocumentSeed],
    client_id: str,
    user: Mapping[str, object],
    generation: str | None = None,
    revision: int | None = None,
    presence_digest: str | None = None,
) -> DocumentPoll:
    """Return changes after ``revision``; ``seed`` may be a lazy fallback factory."""
    state = _read_document_state(sync_id, seed)
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
    # A snapshot starts at this generation's base, not the previous client's cursor.
    delta_start = int(state["base_revision"]) if requires_snapshot else known_revision
    updates = [
        update
        for update in state.get("updates", [])
        if int(update.get("revision") or 0) > delta_start
    ]
    payload: DocumentPoll = {
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
        if generation_matches and (checkpoint_author := state.get("checkpoint_author_hash")):
            payload["user_hash"] = checkpoint_author
    referenced_authors = {
        update.get("user_hash") for update in updates if update.get("user_hash")
    }
    if checkpoint_author := payload.get("user_hash"):
        referenced_authors.add(checkpoint_author)
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
                "user": cast(DocumentReader, dict(user or {})),
                "presence_digest": current_presence_digest,
            }
        )
    return payload


def apply_document_update(
    sync_id: str,
    *,
    seed: DocumentSeed,
    generation: str | None = None,
    revision: int | None = None,
    update: str | None = None,
    ydoc: str | None = None,
    author: Mapping[str, object] | None = None,
) -> DocumentAcknowledgement:
    """Append one Yjs update and compact only from a current client."""
    projected_author = _author_projection(author)
    author_hash = projected_author["hash"] if projected_author else None

    def transform(state: DocumentState) -> DocumentAcknowledgement:
        previous_revision = int(state.get("revision") or 0)
        current_client = (
            generation == state.get("generation")
            and int(revision or 0) == previous_revision
        )
        if update:
            next_revision = previous_revision + 1
            state["revision"] = next_revision
            if projected_author:
                state.setdefault("authors", {})[projected_author["hash"]] = projected_author
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


def update_document_asset(sync_id: str, *, seed: DocumentSeed) -> DocumentState:
    """Refresh durable document metadata without discarding live revisions."""

    def transform(state):
        state["fingerprint"] = seed.get("fingerprint")
        state["markup"] = seed.get("markup")
        return None

    state, _result = _mutate(sync_id, seed, transform)
    return state


def close_presence(client_id: str, sync_ids: Iterable[str] | None) -> None:
    """Remove a browser client from the supplied collaborative documents."""
    if not client_id:
        return
    with cache.pipeline() as pipe:
        for sync_id in dict.fromkeys(sync_ids or ()):
            pipe.srem(Sync.PRESENCE.key(sync_id), client_id)
        pipe.hdel(Sync.CLIENTS.value, client_id)
        pipe.execute()


def clear_document(sync_id: str) -> None:
    """Discard an externally invalidated live generation."""
    cache.redis.delete(Sync.DOCUMENTS.key(sync_id))
