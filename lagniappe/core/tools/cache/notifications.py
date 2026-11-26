"""Redis persistence for the per-user notification projection."""

from collections.abc import Callable, Iterable, Mapping
import uuid

from typing import TYPE_CHECKING, cast

from redis import WatchError

from .core import cache
from .notification_state import (
    AggregateCounts,
    NotificationState,
    PublicNotificationState,
    clear_recorded_notification_states as clear_recorded_notification_states,
    decode as _decode,
    group_mutations as _group_mutations,
    member_ids as _member_ids,
    project as _project,
    public_notification_state,
    record as _record,
    redis_keys as _redis_keys,
    take_recorded_notification_state as take_recorded_notification_state,
    user_id as _user_id,
    write_mapping as _write_mapping,
)


NOTIFICATION_TTL_SECONDS = 30 * 60
if TYPE_CHECKING:
    from ...entities.user import User


MAX_TRANSACTION_ATTEMPTS = 8


def _aggregate_count(aggregate: Mapping[str, object], field: str) -> int:
    # Datastore rows also contain keys, timestamps and unrelated metadata.
    return int(cast(int | str, aggregate.get(field) or 0))


def _ordered_counts(
    current: NotificationState | None, aggregate: Mapping[str, object] | None,
    members: set[str],
) -> AggregateCounts:
    """Keep durable count ordering independent of Redis membership revisions."""
    generation = str((aggregate or {}).get("aggregate_generation") or "")
    revision = (
        _aggregate_count(aggregate, "aggregate_revision")
        if aggregate is not None and "aggregate_revision" in aggregate else -1
    )
    if current and current["aggregate_revision"] >= 0 and (
        aggregate is None or (
            generation == current["aggregate_generation"]
            and revision < current["aggregate_revision"]
        )
    ):
        aggregate = current
        generation = current["aggregate_generation"]
        revision = current["aggregate_revision"]
    if aggregate is None:
        return {
            "ordinary_count": len(members),
            "unread_message_count": current["unread_message_count"] if current else 0,
            "message_revision": current["message_revision"] if current else 0,
            "aggregate_generation": "",
            "aggregate_revision": -1,
        }
    return {
        "ordinary_count": _aggregate_count(aggregate, "ordinary_count"),
        "unread_message_count": _aggregate_count(aggregate, "unread_message_count"),
        "message_revision": _aggregate_count(aggregate, "message_revision"),
        "aggregate_generation": generation,
        "aggregate_revision": revision,
    }


def peek_notification_state(user: object) -> NotificationState | None:
    """Read warm notification state and slide its expiration without seeding."""
    state_key, epoch_key = _redis_keys(user)
    with cache.redis.pipeline() as pipe:
        pipe.hgetall(state_key)
        pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
        pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
        values = pipe.execute()[0]
    return _project(values)


def _default_keys_loader(user):
    from lagniappe.core.tools.database import notifications as database_notifications

    return database_notifications.notification_keys(user)


def seed_notification_state(
    user: object,
    notification_keys: Iterable[object] | None = None,
    *,
    keys_loader: Callable[[object], Iterable[object]] | None = None,
    aggregate_loader: Callable[[object], Mapping[str, object] | None] | None = None,
    repair: bool = False,
) -> NotificationState:
    """Seed or repair notification membership under an epoch-guarded transaction."""
    state_key, epoch_key = _redis_keys(user)
    loader = keys_loader or _default_keys_loader

    for _attempt in range(MAX_TRANSACTION_ATTEMPTS):
        with cache.redis.pipeline() as pipe:
            try:
                pipe.watch(state_key, epoch_key)
                current = _project(pipe.hgetall(state_key))
                if current and not repair:
                    pipe.multi()
                    pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                    pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
                    pipe.execute()
                    return current

                raw_epoch = _decode(pipe.get(epoch_key))
                epoch = int(raw_epoch or 0)
                values = (
                    notification_keys if notification_keys is not None else loader(user)
                )
                members = _member_ids(values)
                if aggregate_loader:
                    aggregate = aggregate_loader(user)
                else:
                    try:
                        from lagniappe.core.tools.database import notifications as database_notifications

                        aggregate = database_notifications.get_notification_aggregate(cast("User", user))
                        if aggregate is None:
                            aggregate = database_notifications.repair_notification_aggregate(
                                cast("User", user), ordinary_count=len(members)
                            )
                    except Exception:
                        aggregate = None
                counts = _ordered_counts(current, aggregate, members)

                changed = bool(current and (
                    members != current["members"]
                    or counts["ordinary_count"] != current["ordinary_count"]
                    or counts["unread_message_count"] != current["unread_message_count"]
                    or counts["message_revision"] != current["message_revision"]
                ))
                generation = current["generation"] if current else str(uuid.uuid4())
                revision = (
                    current["revision"] + 1
                    if current and changed
                    else epoch
                    if not current
                    else current["revision"]
                )
                pipe.multi()
                if changed:
                    pipe.incr(epoch_key)
                else:
                    pipe.set(epoch_key, str(epoch))
                pipe.delete(state_key)
                pipe.hset(
                    state_key,
                    mapping=_write_mapping(generation, revision, members, **counts),
                )
                pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
                pipe.execute()
                return {
                    "generation": generation,
                    "revision": revision,
                    **counts,
                    "count": counts["ordinary_count"] + counts["unread_message_count"],
                    "members": members,
                }
            except WatchError:
                continue
    raise RuntimeError("Notification state changed too frequently.")


def repair_notification_state(
    user: object,
    notification_keys: Iterable[object],
    aggregate: Mapping[str, object] | None = None,
) -> NotificationState:
    """Repair projection membership from keys already fetched for the list."""
    return seed_notification_state(
        user,
        notification_keys,
        aggregate_loader=(lambda _user: aggregate) if aggregate is not None else None,
        repair=True,
    )


def update_notification_projection(
    *, upserts: Iterable[object] = (), deletes: Iterable[object] = (),
    aggregates: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, PublicNotificationState]:
    """Apply one logical committed mutation per affected user's projection."""
    results = {}
    for user, changes in _group_mutations(upserts, deletes).items():
        state_key, epoch_key = _redis_keys(user)
        for _attempt in range(MAX_TRANSACTION_ATTEMPTS):
            with cache.redis.pipeline() as pipe:
                try:
                    pipe.watch(state_key, epoch_key)
                    current = _project(pipe.hgetall(state_key))
                    pipe.get(epoch_key)
                    pipe.multi()
                    pipe.incr(epoch_key)
                    pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
                    state: NotificationState | None = None
                    if current:
                        members = set(current["members"])
                        members.difference_update(changes["deletes"])
                        members.update(changes["upserts"])
                        revision = current["revision"] + 1
                        aggregate = (aggregates or {}).get(user)
                        counts = _ordered_counts(current, aggregate, members)
                        pipe.delete(state_key)
                        pipe.hset(
                            state_key,
                            mapping=_write_mapping(current["generation"], revision, members, **counts),
                        )
                        pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                        state = {
                            "generation": current["generation"],
                            "revision": revision,
                            **counts,
                            "count": counts["ordinary_count"] + counts["unread_message_count"],
                            "members": members,
                        }
                    pipe.execute()
                    public = public_notification_state(state)
                    _record(user, state)
                    results[user] = public
                    break
                except WatchError:
                    continue
        else:
            raise RuntimeError("Notification state changed too frequently.")
    return results


def publish_notification_aggregate(
    user: object, aggregate: Mapping[str, object], *,
    load_current: Callable[[], Mapping[str, object] | None] | None = None,
) -> NotificationState:
    """Mirror canonical durable counts without reading notification history."""
    identifier = _user_id(user)
    state_key, epoch_key = _redis_keys(identifier)
    for _attempt in range(MAX_TRANSACTION_ATTEMPTS):
        with cache.redis.pipeline() as pipe:
            try:
                pipe.watch(state_key, epoch_key)
                current = _project(pipe.hgetall(state_key))
                raw_epoch = _decode(pipe.get(epoch_key))
                epoch = int(raw_epoch or 0)
                members = set(current.get("members", ())) if current else set()
                generation = current.get("generation") if current else str(uuid.uuid4())
                snapshot = aggregate
                if load_current and (
                    not current or current["aggregate_revision"] < 0
                    or current["aggregate_generation"] != str(aggregate.get("aggregate_generation") or "")
                ):
                    # A cold or legacy cache has no comparable durable revision.
                    snapshot = load_current() or aggregate
                counts = _ordered_counts(current, snapshot, members)
                if (
                    current and counts["aggregate_revision"] > _aggregate_count(snapshot, "aggregate_revision")
                ):
                    _record(identifier, current)
                    return current
                revision = max(
                    (current or {}).get("revision", 0) + 1, counts["aggregate_revision"], epoch + 1,
                )
                pipe.multi()
                pipe.set(epoch_key, str(revision))
                pipe.delete(state_key)
                pipe.hset(
                    state_key,
                    mapping=_write_mapping(generation, revision, members, **counts),
                )
                pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
                pipe.execute()
                state: NotificationState = {
                    "generation": generation,
                    "revision": revision,
                    **counts,
                    "count": counts["ordinary_count"] + counts["unread_message_count"],
                    "members": members,
                }
                _record(identifier, state)
                return state
            except WatchError:
                continue
    raise RuntimeError("Notification state changed too frequently.")
