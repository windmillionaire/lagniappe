"""Redis persistence for the per-user notification projection."""

import uuid

from redis import WatchError

from .core import cache
from .notification_state import (
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
MAX_TRANSACTION_ATTEMPTS = 8


# @testable true
# @tests tests_unit/test_025_notification_state.py::test_warm_notification_state_is_redis_only_and_refreshes_ttl
# @tests tests_unit/test_025_notification_state.py::test_expired_notification_state_gets_a_new_generation
# @matrix notifications : cold-seed datastore-read-isolation expiry generation redis-projection ttl
def peek_notification_state(user):
    """Read warm notification state and slide its expiration without seeding."""
    state_key, epoch_key = _redis_keys(user)
    with cache.redis.pipeline() as pipe:
        pipe.hgetall(state_key)
        pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
        pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
        values = pipe.execute()[0]
    return _project(values)


# @testable infrastructure
def _default_keys_loader(user):
    from .. import database

    return database.notification_keys(user)


# @testable true
# @tests tests_unit/test_025_notification_state.py::test_cold_seed_runs_one_keys_only_query_and_is_race_safe
# @tests tests_unit/test_025_notification_state.py::test_notification_list_keys_repair_warm_projection
# @matrix notifications : authoritative-repair cold-seed membership race-safety revision
def seed_notification_state(
    user,
    notification_keys=None,
    *,
    keys_loader=None,
    aggregate_loader=None,
    repair=False,
):
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
                        from .. import database

                        aggregate = database.get_notification_aggregate(user)
                        if aggregate is None:
                            aggregate = database.repair_notification_aggregate(
                                user, ordinary_count=len(members)
                            )
                    except Exception:
                        aggregate = None
                ordinary_count = (
                    int(aggregate.get("ordinary_count") or 0)
                    if aggregate is not None
                    else len(members)
                )
                unread_message_count = (
                    int(aggregate.get("unread_message_count") or 0)
                    if aggregate is not None
                    else 0
                )
                message_revision = (
                    int(aggregate.get("message_revision") or 0)
                    if aggregate is not None
                    else 0
                )

                changed = bool(current and members != current["members"])
                generation = current["generation"] if current else str(uuid.uuid4())
                revision = (
                    current["revision"] + 1
                    if changed
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
                    mapping=_write_mapping(
                        generation,
                        revision,
                        members,
                        ordinary_count=ordinary_count,
                        unread_message_count=unread_message_count,
                        message_revision=message_revision,
                    ),
                )
                pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
                pipe.execute()
                return {
                    "generation": generation,
                    "revision": revision,
                    "message_revision": message_revision,
                    "ordinary_count": ordinary_count,
                    "unread_message_count": unread_message_count,
                    "count": ordinary_count + unread_message_count,
                    "members": members,
                }
            except WatchError:
                continue
    raise RuntimeError("Notification state changed too frequently.")


# @testable infrastructure
def repair_notification_state(user, notification_keys, aggregate=None):
    """Repair projection membership from keys already fetched for the list."""
    return seed_notification_state(
        user,
        notification_keys,
        aggregate_loader=(lambda _user: aggregate) if aggregate is not None else None,
        repair=True,
    )


# @testable true
# @tests tests_unit/test_025_notification_state.py::test_notification_mutations_are_idempotent_and_advance_once
# @tests tests_unit/test_025_notification_state.py::test_absent_projection_mutation_updates_epoch_without_querying
# @matrix notifications : cold-cache datastore-read-isolation idempotent-count mutation revision
def update_notification_projection(*, upserts=(), deletes=(), aggregates=None):
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
                    state = None
                    if current:
                        members = set(current["members"])
                        members.difference_update(changes["deletes"])
                        members.update(changes["upserts"])
                        revision = current["revision"] + 1
                        aggregate = (aggregates or {}).get(user)
                        ordinary_count = (
                            int(aggregate.get("ordinary_count") or 0)
                            if aggregate is not None
                            else len(members)
                        )
                        unread_message_count = (
                            int(aggregate.get("unread_message_count") or 0)
                            if aggregate is not None
                            else current.get("unread_message_count", 0)
                        )
                        message_revision = (
                            int(aggregate.get("message_revision") or 0)
                            if aggregate is not None
                            else current.get("message_revision", 0)
                        )
                        pipe.delete(state_key)
                        pipe.hset(
                            state_key,
                            mapping=_write_mapping(
                                current["generation"],
                                revision,
                                members,
                                ordinary_count=ordinary_count,
                                unread_message_count=unread_message_count,
                                message_revision=message_revision,
                            ),
                        )
                        pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                        state = {
                            "generation": current["generation"],
                            "revision": revision,
                            "message_revision": message_revision,
                            "ordinary_count": ordinary_count,
                            "unread_message_count": unread_message_count,
                            "count": ordinary_count + unread_message_count,
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


# @testable true
# @tests tests_unit/test_025_notification_state.py::test_durable_aggregate_publish_preserves_members_and_exact_combined_count
# @matrix notifications : aggregate-count redis-projection revision
def publish_notification_aggregate(user, aggregate):
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
                revision = max(
                    (current or {}).get("revision", 0) + 1,
                    int(aggregate.get("aggregate_revision") or 0),
                    epoch + 1,
                )
                ordinary_count = int(aggregate.get("ordinary_count") or 0)
                unread_message_count = int(aggregate.get("unread_message_count") or 0)
                message_revision = int(aggregate.get("message_revision") or 0)
                pipe.multi()
                pipe.set(epoch_key, str(revision))
                pipe.delete(state_key)
                pipe.hset(
                    state_key,
                    mapping=_write_mapping(
                        generation,
                        revision,
                        members,
                        ordinary_count=ordinary_count,
                        unread_message_count=unread_message_count,
                        message_revision=message_revision,
                    ),
                )
                pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
                pipe.execute()
                state = {
                    "generation": generation,
                    "revision": revision,
                    "message_revision": message_revision,
                    "ordinary_count": ordinary_count,
                    "unread_message_count": unread_message_count,
                    "count": ordinary_count + unread_message_count,
                    "members": members,
                }
                _record(identifier, state)
                return state
            except WatchError:
                continue
    raise RuntimeError("Notification state changed too frequently.")
