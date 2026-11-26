"""Coordinate filter builders and detect changes to their members during a scan."""

from collections.abc import Callable, Collection, Mapping
from contextlib import suppress
import json
from threading import Event, Thread
from time import monotonic, sleep
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import uuid4

from redis.exceptions import LockNotOwnedError, RedisError, WatchError
from werkzeug.exceptions import ServiceUnavailable

from .core import filter_cache
from .keys import Keys

if TYPE_CHECKING:
    from redis.client import Pipeline
    from redis.commands.json._util import JsonType
    from redis.lock import Lock
    from ...entities.entity import Entity


# A history per collection type also covers moves out of a parent whose index
# did not exist when the write ran. Unrelated Task traffic cannot trim Page history.
MEMBER_HISTORIES = {"task": Keys.PROJECT_FILTER_CHANGES.value, "page": Keys.CATEGORY_FILTER_CHANGES.value}
CHANGE_WINDOW = 128
LEASE_SECONDS = 15
WAIT_SECONDS = 30
POLL_SECONDS = 0.05


class RefreshMarker(TypedDict):
    id: str
    cache_key: str


def _append(pipe: Pipeline, history: str, affected: set[str]) -> bytes:
    # A unique checkpoint survives neither eviction nor trimming. A builder
    # that cannot find its checkpoint must read Datastore again.
    members = sorted(affected) if len(affected) <= CHANGE_WINDOW else ["*"]
    event = json.dumps([uuid4().hex, members], separators=(",", ":")).encode()
    pipe.lpush(history, event)
    pipe.ltrim(history, 0, CHANGE_WINDOW - 1)
    return event


def record_changes(entities: Collection[Entity], destinations: Mapping[str, Collection[str]] | None = None) -> None:
    """Signal committed edits before discovering existing JSON parents."""
    changes: dict[str, set[str]] = {}
    for entity in entities:
        history = MEMBER_HISTORIES.get(entity.kind)
        if history and entity.hash:
            affected = changes.setdefault(history, set())
            affected.add(entity.hash)
            if destinations:
                affected.update(destinations.get(entity.hash, ()))
    if changes:
        with filter_cache.redis.pipeline() as pipe:
            for history, affected in changes.items():
                _append(pipe, history, affected)
            pipe.execute()


def _head(history: str) -> bytes:
    # This synchronous client returns bytes. Seed an empty history so a later
    # eviction is distinguishable from a quiet interval.
    event = cast("bytes | None", filter_cache.redis.lindex(history, 0))
    if event is None:
        with filter_cache.redis.pipeline() as pipe:
            event = _append(pipe, history, set())
            pipe.execute()
    return event


def _affected(history: str, start: bytes, parent: str, rows: dict[str, JsonType]) -> bool:
    if filter_cache.redis.lindex(history, 0) == start:
        return False
    for event in filter_cache.redis.lrange(history, 0, CHANGE_WINDOW - 1):
        if event == start:
            return False
        _, members = json.loads(event)
        if "*" in members or parent in members or any(member in rows for member in members):
            return True
    return True


def _renew(lease: Lock, stop: Event) -> None:
    """Keep an active worker's lease alive. A stopped process loses it to TTL."""
    while not stop.wait(LEASE_SECONDS / 3):
        try:
            lease.reacquire()
        except RedisError:
            # The publisher independently verifies ownership at commit.
            return


def _publish(key: str, parent: str, history: str, rows: dict[str, JsonType], start: bytes, lease: Lock) -> bool:
    redis = filter_cache.redis
    document = json.dumps({**rows, "access": {"hash": parent}}, separators=(",", ":"))
    deadline = monotonic() + WAIT_SECONDS
    while monotonic() < deadline:
        with redis.pipeline() as pipe:
            try:
                pipe.watch(lease.name, history)
                if not lease.owned() or _affected(history, start, parent, rows):
                    return False
                pipe.multi()
                pipe.execute_command("JSON.SET", key, "$", document)
                pipe.expire(key, filter_cache.ttl)
                pipe.execute()
                return True
            except WatchError:
                # An unrelated edit or a lease renewal can reuse these rows.
                continue
    raise ServiceUnavailable("Filter publication is busy. Please retry.")


def _rebuild(
    key: str, parent: str, history: str, load: Callable[[], dict[str, JsonType]], *,
    force: bool, wait: float,
) -> bool:
    """Publish a fresh snapshot or join an already finished build."""
    lease = filter_cache.redis.lock(f"{key}:build", timeout=LEASE_SECONDS, thread_local=False)
    if not lease.acquire(blocking=False):
        # Waiters can all read the published root without first queuing for the lock.
        sleep(min(POLL_SECONDS, wait))
        return False
    try:
        if not force:
            pending = _pending(key)
            if pending is not None:
                return not pending
        stopped = Event()
        heartbeat = Thread(target=_renew, args=(lease, stopped), daemon=True)
        heartbeat.start()
        try:
            start = _head(history)
            rows = load()
            return _publish(key, parent, history, rows, start, lease)
        finally:
            stopped.set()
            heartbeat.join()
    finally:
        with suppress(LockNotOwnedError):
            lease.release()


def _pending(key: str) -> list[RefreshMarker] | None:
    # RedisJSON distinguishes a missing root (None) from a clean one ([]).
    return cast("list[RefreshMarker] | None", filter_cache.query(key, "$[?(@.refresh == 1)]"))


def _refresh(key: str, load: Callable[[list[str]], dict[str, JsonType]]) -> bool:
    """Update exactly the observed stubs. A concurrent edit or expiry wins."""
    with filter_cache.redis.pipeline() as pipe:
        try:
            pipe.watch(key)
            markers = _pending(key)
            if markers is None:
                return False
            if not markers:
                return True
            rows = load([marker["id"] for marker in markers])
            pipe.multi()
            if rows:
                pipe.json().mset([(key, f"$.{h}", row) for h, row in rows.items()])
            for marker in markers:
                if marker["cache_key"] not in rows:
                    pipe.json().delete(key, f"$.{marker['cache_key']}")
            pipe.expire(key, filter_cache.ttl)
            pipe.execute()
            return True
        except WatchError:
            return False


def ensure(
    key: str, parent: str, history: str, load: Callable[[], dict[str, JsonType]],
    refresh: Callable[[list[str]], dict[str, JsonType]], *, force: bool,
) -> None:
    """Serve complete indexes and preserve concurrent incremental edits."""
    deadline = monotonic() + WAIT_SECONDS
    pending = _pending(key)
    force = force and pending is not None
    while (remaining := deadline - monotonic()) > 0:
        if pending is None or force:
            if _rebuild(key, parent, history, load, force=force, wait=remaining):
                return
        elif not pending or _refresh(key, refresh):
            return
        pending = _pending(key)
    raise ServiceUnavailable("Filter is changing. Please retry.")
