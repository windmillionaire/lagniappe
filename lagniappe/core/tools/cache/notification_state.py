"""Pure values and request-local state for notification projections."""

from collections.abc import Collection, Iterable, Mapping
from contextvars import ContextVar
from typing import TypedDict, cast, overload

from google.cloud.datastore import Key
from redis.typing import FieldT

from config.datastore import encode_urlsafe_key

from .keys import Keys


class PublicNotificationState(TypedDict):
    generation: str | None
    revision: int | None
    count: int | None


class NotificationState(TypedDict):
    generation: str
    revision: int
    message_revision: int
    ordinary_count: int
    unread_message_count: int
    count: int
    members: set[str]


NOTIFICATION_SCHEMA_VERSION = "2"
MEMBER_PREFIX = "member:"
_RECORDED_STATES: ContextVar[dict[str | None, PublicNotificationState] | None] = ContextVar("notification_projection_states", default=None)


# @testable infrastructure
@overload
def decode(value: str | bytes) -> str: ...

@overload
def decode(value: object) -> str | None: ...

def decode(value: object) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value) if value is not None else None


# @testable infrastructure
def decode_map[K: str | bytes, V: str | bytes](values: Mapping[K, V] | None) -> dict[str, str]:
    return {decode(key): decode(value) for key, value in (values or {}).items()}


# @testable infrastructure
def user_id(user: object) -> str | None:
    if isinstance(user, str):
        return user
    return getattr(user, "urlsafe_key", None)


# @testable infrastructure
def notification_id(notification: object) -> str | None:
    if isinstance(notification, str):
        return notification
    if hasattr(notification, "to_legacy_urlsafe"):
        try:
            return encode_urlsafe_key(cast(Key, notification))
        except AttributeError:
            return decode(cast(Key, notification).to_legacy_urlsafe())
    identifier = getattr(notification, "urlsafe_key", None)
    if identifier:
        return identifier
    key = getattr(notification, "key", None)
    if key and hasattr(key, "to_legacy_urlsafe"):
        try:
            return encode_urlsafe_key(key)
        except AttributeError:
            return decode(key.to_legacy_urlsafe())
    return str(key) if key else None


# @testable infrastructure
def owner_id(notification: object) -> str | None:
    return user_id(getattr(notification, "parent", None))


# @testable infrastructure
def redis_keys(user: object) -> tuple[str, str]:
    identifier = user_id(user)
    if not identifier:
        raise ValueError("Notification state requires a user key.")
    return (
        Keys.NOTIFICATIONS.value.format(identifier),
        Keys.NOTIFICATION_EPOCH.value.format(identifier),
    )


# @testable infrastructure
def project[K: str | bytes, V: str | bytes](raw: Mapping[K, V] | None) -> NotificationState | None:
    values = decode_map(raw)
    if values.get("schema") != NOTIFICATION_SCHEMA_VERSION:
        return None
    generation = values.get("generation")
    if not generation:
        return None
    try:
        revision = int(values.get("revision") or 0)
        message_revision = int(values.get("message_revision") or 0)
        ordinary_count = int(values.get("ordinary_count") or 0)
        unread_message_count = int(values.get("unread_message_count") or 0)
    except (TypeError, ValueError):
        return None
    if ordinary_count < 0 or unread_message_count < 0:
        return None
    members = {
        field.removeprefix(MEMBER_PREFIX)
        for field in values
        if field.startswith(MEMBER_PREFIX)
    }
    return {
        "generation": generation,
        "revision": revision,
        "message_revision": max(0, message_revision),
        "ordinary_count": max(0, ordinary_count),
        "unread_message_count": max(0, unread_message_count),
        "count": max(0, ordinary_count) + max(0, unread_message_count),
        "members": members,
    }


# @testable infrastructure
def public_notification_state(state: NotificationState | None) -> PublicNotificationState:
    """Return the browser-safe projection fields, or a reported miss."""
    if not state:
        return {"generation": None, "revision": None, "count": None}
    return {
        "generation": state["generation"],
        "revision": int(state["revision"]),
        "count": int(state["count"]),
    }


# @testable infrastructure
def record(user: object, state: NotificationState | None) -> None:
    recorded = dict(_RECORDED_STATES.get() or {})
    recorded[user_id(user)] = public_notification_state(state)
    _RECORDED_STATES.set(recorded)


# @testable infrastructure
def clear_recorded_notification_states() -> None:
    """Clear request-local mutation state before serving another request."""
    _RECORDED_STATES.set({})


# @testable infrastructure
def take_recorded_notification_state(user: object) -> PublicNotificationState | None:
    """Pop a request-local notification mutation result for ``user``."""
    identifier = user_id(user)
    recorded = dict(_RECORDED_STATES.get() or {})
    state = recorded.pop(identifier, None)
    _RECORDED_STATES.set(recorded)
    return state


# @testable infrastructure
def member_ids(values: Iterable[object] | None) -> set[str]:
    return {
        identifier for value in values or () if (identifier := notification_id(value))
    }


# @testable infrastructure
def write_mapping(
    generation: str,
    revision: int,
    members: Collection[str],
    *,
    ordinary_count: int | None = None,
    unread_message_count: int = 0,
    message_revision: int = 0,
) -> dict[FieldT, str]:
    if ordinary_count is None:
        ordinary_count = len(members)
    return {
        "schema": NOTIFICATION_SCHEMA_VERSION,
        "generation": generation,
        "revision": str(int(revision)),
        "message_revision": str(max(0, int(message_revision))),
        "ordinary_count": str(max(0, int(ordinary_count))),
        "unread_message_count": str(max(0, int(unread_message_count))),
        **{f"{MEMBER_PREFIX}{member}": "1" for member in sorted(members)},
    }


# @testable infrastructure
def group_mutations(upserts: Iterable[object], deletes: Iterable[object]) -> dict[str, dict[str, set[str]]]:
    grouped = {}
    for operation, values in (("upserts", upserts), ("deletes", deletes)):
        for notification in values or ():
            user = owner_id(notification)
            identifier = notification_id(notification)
            if not user or not identifier:
                continue
            grouped.setdefault(user, {"upserts": set(), "deletes": set()})[
                operation
            ].add(identifier)
    return grouped
