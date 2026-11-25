"""Coordinate Project filter builders and detect Task edits during materialization."""

from collections.abc import Callable, Collection
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
    from redis.commands.json._util import JsonType
    from redis.lock import Lock


# One short, bounded history also covers moves out of a Project that had no
# published index when the write ran. Store identifiers only.
CHANGE_WINDOW = 128
LEASE_SECONDS = 15
WAIT_SECONDS = 30
POLL_SECONDS = 0.05


class RefreshMarker(TypedDict):
    id: str
    cache_key: str


def _record(affected: set[str]) -> bytes:
    # A unique checkpoint survives neither eviction nor trimming. A builder
    # that cannot find its checkpoint must read Datastore again.
    members = sorted(affected) if len(affected) <= CHANGE_WINDOW else ["*"]
    event = json.dumps([uuid4().hex, members], separators=(",", ":")).encode()
    key = Keys.PROJECT_FILTER_CHANGES.value
    with filter_cache.redis.pipeline() as pipe:
        pipe.lpush(key, event)
        pipe.ltrim(key, 0, CHANGE_WINDOW - 1)
        pipe.execute()
    return event


def record_task_changes(tasks: Collection[str], projects: Collection[str] = ()) -> None:
    """Signal committed Task changes before discovering existing JSON parents."""
    if tasks:
        _record(set(tasks).union(projects))


def _head() -> bytes:
    # This synchronous client returns bytes. Seed an empty history so a later
    # eviction is distinguishable from a quiet interval.
    event = cast("bytes | None", filter_cache.redis.lindex(Keys.PROJECT_FILTER_CHANGES.value, 0))
    return event or _record(set())


def _affected(start: bytes, project: str, rows: dict[str, JsonType]) -> bool:
    key = Keys.PROJECT_FILTER_CHANGES.value
    if filter_cache.redis.lindex(key, 0) == start:
        return False
    for event in filter_cache.redis.lrange(key, 0, CHANGE_WINDOW - 1):
        if event == start:
            return False
        _, members = json.loads(event)
        if "*" in members or project in members or any(member in rows for member in members):
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


def _publish(key: str, project: str, rows: dict[str, JsonType], start: bytes, lease: Lock) -> bool:
    redis = filter_cache.redis
    change_key = Keys.PROJECT_FILTER_CHANGES.value
    document = json.dumps({**rows, "access": {"hash": project}}, separators=(",", ":"))
    deadline = monotonic() + WAIT_SECONDS
    while monotonic() < deadline:
        with redis.pipeline() as pipe:
            try:
                pipe.watch(lease.name, change_key)
                if not lease.owned() or _affected(start, project, rows):
                    return False
                pipe.multi()
                pipe.execute_command("JSON.SET", key, "$", document)
                pipe.expire(key, filter_cache.ttl)
                pipe.execute()
                return True
            except WatchError:
                # A write to another Project or a lease renewal can reuse these rows.
                continue
    raise ServiceUnavailable("Project filter publication is busy. Please retry.")


def _rebuild(
    key: str, project: str, load: Callable[[], dict[str, JsonType]], *,
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
            start = _head()
            rows = load()
            return _publish(key, project, rows, start, lease)
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
    key: str, project: str, load: Callable[[], dict[str, JsonType]],
    refresh: Callable[[list[str]], dict[str, JsonType]], *, force: bool,
) -> None:
    """Serve complete Project indexes and preserve concurrent incremental edits."""
    deadline = monotonic() + WAIT_SECONDS
    pending = _pending(key)
    force = force and pending is not None
    while (remaining := deadline - monotonic()) > 0:
        if pending is None or force:
            if _rebuild(key, project, load, force=force, wait=remaining):
                return
        elif not pending or _refresh(key, refresh):
            return
        pending = _pending(key)
    raise ServiceUnavailable("Project filter is changing. Please retry.")
