"""Persisted direct-message conversation state and pure transitions."""

import hashlib

from .base_db import DBProperty


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::serialize_conversation
# @reason key encoding is exercised through browser projections
def encoded_identifier(value):
    """Return the stable urlsafe identity for an entity or Datastore key."""
    key = getattr(value, "key", value)
    identifier = getattr(value, "urlsafe_key", None)
    if identifier:
        return str(identifier)
    if key is not None and hasattr(key, "to_legacy_urlsafe"):
        encoded = key.to_legacy_urlsafe()
        return encoded.decode("utf-8") if isinstance(encoded, bytes) else str(encoded)
    return str(key) if key is not None else None


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::send_message_record
# @reason participant normalization is exercised through transactional state
def participant_id(user):
    return encoded_identifier(user)


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:deterministic-key
def conversation_identity(first, second):
    participants = sorted((participant_id(first), participant_id(second)))
    return hashlib.sha256("\0".join(participants).encode()).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::require_participant
# @reason membership comparison is exercised through authorized reads and writes
def participant(conversation, user):
    return getattr(user, "key", user) in set(conversation.get("participants") or ())


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::serialize_conversation
# @reason peer selection is exercised through conversation projection
def peer_key(conversation, user):
    user_key = getattr(user, "key", user)
    return next(
        (key for key in conversation.get("participants") or () if key != user_key),
        None,
    )


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::send_message_record
# @reason exact raw conversation construction is exercised through first send
def initial_values(actor, recipient, now):
    actor_id = participant_id(actor)
    recipient_id = participant_id(recipient)
    return {
        "type": "message_conversation",
        "kind": "message_conversation",
        "participants": [actor.key, recipient.key],
        "visible_to": [actor.key, recipient.key],
        "participant_names": {
            actor_id: actor.name,
            recipient_id: recipient.name,
        },
        "last_activity": now,
        "last_sender": actor.key,
        "sequence": 0,
        "revision": 0,
        "unread_counts": {actor_id: 0, recipient_id: 0},
        "read_through": {actor_id: 0, recipient_id: 0},
        "cleared_through": {actor_id: 0, recipient_id: 0},
        "active": True,
        "created": now,
        "modified": now,
    }


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::send_message_record
# @reason the pure transition is exercised within the atomic send contract
def apply_send(conversation, actor, recipient, now):
    """Advance one conversation after accepting a new message."""
    actor_id = participant_id(actor)
    recipient_id = participant_id(recipient)
    sequence = int(conversation.get("sequence") or 0) + 1
    unread = dict(conversation.get("unread_counts") or {})
    unread[recipient_id] = int(unread.get(recipient_id) or 0) + 1
    unread.setdefault(actor_id, 0)
    names = dict(conversation.get("participant_names") or {})
    names.update({actor_id: actor.name, recipient_id: recipient.name})
    conversation.update(
        {
            "visible_to": [actor.key, recipient.key],
            "participant_names": names,
            "last_activity": now,
            "last_sender": actor.key,
            "sequence": sequence,
            "revision": int(conversation.get("revision") or 0) + 1,
            "unread_counts": unread,
            "modified": now,
        }
    )
    return sequence


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::mark_conversation_read
# @reason the pure transition is exercised within the atomic read contract
def apply_read(conversation, user, now):
    """Clear a participant's unread cursor and return the prior unread count."""
    user_id = participant_id(user)
    unread = dict(conversation.get("unread_counts") or {})
    prior = int(unread.get(user_id) or 0)
    if not prior:
        return 0
    unread[user_id] = 0
    read_through = dict(conversation.get("read_through") or {})
    read_through[user_id] = int(conversation.get("sequence") or 0)
    conversation["unread_counts"] = unread
    conversation["read_through"] = read_through
    conversation["revision"] = int(conversation.get("revision") or 0) + 1
    conversation["modified"] = now
    return prior


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::hide_message_for_user
# @reason the pure transition is exercised within the atomic hide contract
def apply_hidden_message(conversation, message, user):
    """Remove one still-unread hidden inbound message from conversation counts."""
    user_id = participant_id(user)
    unread = dict(conversation.get("unread_counts") or {})
    read_through = int((conversation.get("read_through") or {}).get(user_id) or 0)
    if not (
        message.get("recipient") == user.key
        and int(message.get("sequence") or 0) > read_through
        and int(unread.get(user_id) or 0) > 0
    ):
        return False
    unread[user_id] = int(unread[user_id]) - 1
    conversation["unread_counts"] = unread
    conversation["revision"] = int(conversation.get("revision") or 0) + 1
    return True


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::clear_message_conversation
# @reason the pure transition is exercised within the atomic clear contract
def apply_clear(conversation, user, now):
    """Advance one participant's clear horizon and return cleared unread count."""
    user_id = participant_id(user)
    unread = dict(conversation.get("unread_counts") or {})
    prior = int(unread.get(user_id) or 0)
    unread[user_id] = 0
    cleared = dict(conversation.get("cleared_through") or {})
    cleared[user_id] = int(conversation.get("sequence") or 0)
    conversation["unread_counts"] = unread
    conversation["cleared_through"] = cleared
    conversation["visible_to"] = [
        key for key in conversation.get("visible_to") or () if key != user.key
    ]
    conversation["revision"] = int(conversation.get("revision") or 0) + 1
    conversation["modified"] = now
    return prior


class Participants(DBProperty):
    _id = "participants"


class VisibleTo(DBProperty):
    _id = "visible_to"


class ParticipantNames(DBProperty):
    _id = "participant_names"
    json = True


class LastActivity(DBProperty):
    _id = "last_activity"


class LastSender(DBProperty):
    _id = "last_sender"


class Sequence(DBProperty):
    _id = "sequence"


class Revision(DBProperty):
    _id = "revision"


class UnreadCounts(DBProperty):
    _id = "unread_counts"
    json = True


class ReadThrough(DBProperty):
    _id = "read_through"
    json = True


class ClearedThrough(DBProperty):
    _id = "cleared_through"
    json = True
