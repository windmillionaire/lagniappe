"""Pure values and request-local state for notification projections."""

from contextvars import ContextVar

from .keys import Keys


NOTIFICATION_SCHEMA_VERSION = "2"
MEMBER_PREFIX = "member:"
_RECORDED_STATES = ContextVar("notification_projection_states", default=None)


# @testable infrastructure
def decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value) if value is not None else None


# @testable infrastructure
def decode_map(values):
    return {decode(key): decode(value) for key, value in (values or {}).items()}


# @testable infrastructure
def user_id(user):
    if isinstance(user, str):
        return user
    return getattr(user, "urlsafe_key", None)


# @testable infrastructure
def notification_id(notification):
    if isinstance(notification, str):
        return notification
    if hasattr(notification, "to_legacy_urlsafe"):
        return decode(notification.to_legacy_urlsafe())
    identifier = getattr(notification, "urlsafe_key", None)
    if identifier:
        return identifier
    key = getattr(notification, "key", None)
    if key and hasattr(key, "to_legacy_urlsafe"):
        return key.to_legacy_urlsafe().decode("utf-8")
    return str(key) if key else None


# @testable infrastructure
def owner_id(notification):
    return user_id(getattr(notification, "parent", None))


# @testable infrastructure
def redis_keys(user):
    identifier = user_id(user)
    if not identifier:
        raise ValueError("Notification state requires a user key.")
    return (
        Keys.NOTIFICATIONS.value.format(identifier),
        Keys.NOTIFICATION_EPOCH.value.format(identifier),
    )


# @testable infrastructure
def project(raw):
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
def record(user, state):
    recorded = dict(_RECORDED_STATES.get() or {})
    recorded[user_id(user)] = public_notification_state(state)
    _RECORDED_STATES.set(recorded)


# @testable infrastructure
def clear_recorded_notification_states():
    """Clear request-local mutation state before serving another request."""
    _RECORDED_STATES.set({})


# @testable infrastructure
def take_recorded_notification_state(user):
    """Pop a request-local notification mutation result for ``user``."""
    identifier = user_id(user)
    recorded = dict(_RECORDED_STATES.get() or {})
    state = recorded.pop(identifier, None)
    _RECORDED_STATES.set(recorded)
    return state


# @testable infrastructure
def member_ids(values):
    return {
        identifier for value in values or () if (identifier := notification_id(value))
    }


# @testable infrastructure
def write_mapping(
    generation,
    revision,
    members,
    *,
    ordinary_count=None,
    unread_message_count=0,
    message_revision=0,
):
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
def group_mutations(upserts, deletes):
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
