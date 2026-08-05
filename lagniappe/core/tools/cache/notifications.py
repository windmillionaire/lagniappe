"""Expiring Redis projection for per-user notification membership."""

from contextvars import ContextVar
import uuid

from redis import WatchError

from .core import cache
from .keys import Keys


NOTIFICATION_TTL_SECONDS = 30 * 60
NOTIFICATION_SCHEMA_VERSION = "1"
MAX_TRANSACTION_ATTEMPTS = 8
MEMBER_PREFIX = "member:"
_RECORDED_STATES = ContextVar("notification_projection_states", default=None)


# @testable infrastructure
def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value) if value is not None else None


# @testable infrastructure
def _decode_map(values):
    return {_decode(key): _decode(value) for key, value in (values or {}).items()}


# @testable infrastructure
def _user_id(user):
    if isinstance(user, str):
        return user
    return getattr(user, "urlsafe_key", None)


# @testable infrastructure
def _notification_id(notification):
    if isinstance(notification, str):
        return notification
    if hasattr(notification, "to_legacy_urlsafe"):
        return _decode(notification.to_legacy_urlsafe())
    identifier = getattr(notification, "urlsafe_key", None)
    if identifier:
        return identifier
    key = getattr(notification, "key", None)
    if key and hasattr(key, "to_legacy_urlsafe"):
        return key.to_legacy_urlsafe().decode("utf-8")
    return str(key) if key else None


# @testable infrastructure
def _owner_id(notification):
    parent = getattr(notification, "parent", None)
    return _user_id(parent)


# @testable infrastructure
def _redis_keys(user):
    identifier = _user_id(user)
    if not identifier:
        raise ValueError("Notification state requires a user key.")
    return (
        Keys.NOTIFICATIONS.value.format(identifier),
        Keys.NOTIFICATION_EPOCH.value.format(identifier),
    )


# @testable infrastructure
def _project(raw):
    values = _decode_map(raw)
    if values.get("schema") != NOTIFICATION_SCHEMA_VERSION:
        return None
    generation = values.get("generation")
    if not generation:
        return None
    try:
        revision = int(values.get("revision") or 0)
    except (TypeError, ValueError):
        return None
    members = {
        field.removeprefix(MEMBER_PREFIX)
        for field in values
        if field.startswith(MEMBER_PREFIX)
    }
    return {
        "generation": generation,
        "revision": revision,
        "count": len(members),
        "members": members,
    }


# @testable infrastructure
def public_notification_state(state):
    """Return the browser-safe projection fields, or a reported miss."""
    if not state:
        return {"generation": None, "revision": None, "count": None}
    return {
        "generation": state["generation"],
        "revision": int(state["revision"]),
        "count": int(state["count"]),
    }


# @testable infrastructure
def _record(user_id, state):
    recorded = dict(_RECORDED_STATES.get() or {})
    recorded[user_id] = public_notification_state(state)
    _RECORDED_STATES.set(recorded)


# @testable infrastructure
def clear_recorded_notification_states():
    """Clear request-local mutation state before serving another request."""
    _RECORDED_STATES.set({})


# @testable infrastructure
def take_recorded_notification_state(user):
    """Pop a request-local notification mutation result for ``user``."""
    identifier = _user_id(user)
    recorded = dict(_RECORDED_STATES.get() or {})
    state = recorded.pop(identifier, None)
    _RECORDED_STATES.set(recorded)
    return state


# @testable true
# @tests tests_unit/test_025_notification_state.py::test_warm_notification_state_is_redis_only_and_refreshes_ttl
# @tests tests_unit/test_025_notification_state.py::test_expired_notification_state_gets_a_new_generation
# @pairs notifications:redis-projection notifications:ttl notifications:generation
# @pairs notifications:datastore-read-isolation notifications:expiry notifications:cold-seed
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
    from lagniappe.core.entities import Entities

    return Entities.NOTIFICATION.keys_for_parent(user)


# @testable infrastructure
def _member_ids(values):
    return {
        identifier for value in values or () if (identifier := _notification_id(value))
    }


# @testable infrastructure
def _write_mapping(generation, revision, members):
    return {
        "schema": NOTIFICATION_SCHEMA_VERSION,
        "generation": generation,
        "revision": str(int(revision)),
        **{f"{MEMBER_PREFIX}{member}": "1" for member in sorted(members)},
    }


# @testable true
# @tests tests_unit/test_025_notification_state.py::test_cold_seed_runs_one_keys_only_query_and_is_race_safe
# @tests tests_unit/test_025_notification_state.py::test_notification_list_keys_repair_warm_projection
# @pairs notifications:cold-seed notifications:race-safety notifications:authoritative-repair
# @pairs notifications:revision notifications:membership
def seed_notification_state(
    user,
    notification_keys=None,
    *,
    keys_loader=None,
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
                    mapping=_write_mapping(generation, revision, members),
                )
                pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                pipe.expire(epoch_key, NOTIFICATION_TTL_SECONDS)
                pipe.execute()
                return {
                    "generation": generation,
                    "revision": revision,
                    "count": len(members),
                    "members": members,
                }
            except WatchError:
                continue
    raise RuntimeError("Notification state changed too frequently.")


# @testable infrastructure
def repair_notification_state(user, notification_keys):
    """Repair projection membership from keys already fetched for the list."""
    return seed_notification_state(user, notification_keys, repair=True)


# @testable infrastructure
def _group_mutations(upserts, deletes):
    grouped = {}
    for operation, values in (("upserts", upserts), ("deletes", deletes)):
        for notification in values or ():
            user_id = _owner_id(notification)
            notification_id = _notification_id(notification)
            if not user_id or not notification_id:
                continue
            grouped.setdefault(user_id, {"upserts": set(), "deletes": set()})[
                operation
            ].add(notification_id)
    return grouped


# @testable true
# @tests tests_unit/test_025_notification_state.py::test_notification_mutations_are_idempotent_and_advance_once
# @tests tests_unit/test_025_notification_state.py::test_absent_projection_mutation_updates_epoch_without_querying
# @pairs notifications:mutation notifications:idempotent-count notifications:revision
# @pairs notifications:cold-cache notifications:datastore-read-isolation
def update_notification_projection(*, upserts=(), deletes=()):
    """Apply one logical committed mutation per affected user's projection."""
    results = {}
    for user_id, changes in _group_mutations(upserts, deletes).items():
        state_key, epoch_key = _redis_keys(user_id)
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
                        pipe.delete(state_key)
                        pipe.hset(
                            state_key,
                            mapping=_write_mapping(
                                current["generation"], revision, members
                            ),
                        )
                        pipe.expire(state_key, NOTIFICATION_TTL_SECONDS)
                        state = {
                            "generation": current["generation"],
                            "revision": revision,
                            "count": len(members),
                            "members": members,
                        }
                    pipe.execute()
                    public = public_notification_state(state)
                    _record(user_id, state)
                    results[user_id] = public
                    break
                except WatchError:
                    continue
        else:
            raise RuntimeError("Notification state changed too frequently.")
    return results
