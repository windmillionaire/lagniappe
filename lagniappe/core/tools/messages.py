"""Transactional one-to-one managed-user messaging service."""

from datetime import datetime, timezone
import hashlib

from google.cloud.datastore import Entity as DatastoreEntity

from ..definitions import Fetch
from ..entities import Entities
from ..exceptions import ValidationError
from . import collaboration, database, notification_email, notification_service
from .database.core import DATA, KINDS
from .database.filter import Filter, Query


CONVERSATION_PAGE_SIZE = 25
HISTORY_PAGE_SIZE = 50
MESSAGE_BODY_LIMIT = 1000
OPERATION_ID_LIMIT = 128


class MessageConflict(RuntimeError):
    pass


# @testable false
# @covered-by lagniappe/core/tools/messages.py::mark_read
# @reason conflict payload is exercised through revision-aware read transitions
class MessageRevisionConflict(RuntimeError):
    def __init__(self, conversation):
        super().__init__("Conversation changed; refresh and try again.")
        self.conversation = conversation


# @testable false
# @covered-by lagniappe/core/tools/messages.py::serialize_conversation
# @covered-by lagniappe/core/tools/messages.py::serialize_message
# @reason key encoding is internal to the public JSON serializers
def _encoded_key(value):
    key = getattr(value, "key", value)
    return database.get.urlsafe_key(key)


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason participant encoding is exercised through deterministic send state
def _participant_id(user):
    return _encoded_key(user)


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason deterministic identity is asserted through idempotent send coverage
def _conversation_key(first, second):
    participants = sorted((_participant_id(first), _participant_id(second)))
    identifier = hashlib.sha256("\0".join(participants).encode()).hexdigest()
    return database.create_named_key("message_conversation", identifier)


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason sender-scoped identity is asserted through idempotent send coverage
def _message_key(conversation_key, sender, operation_id):
    identity = f"{_participant_id(sender)}\0{operation_id}"
    identifier = hashlib.sha256(identity.encode()).hexdigest()
    return database.create_named_key("message", identifier, parent=conversation_key)


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason initial state construction is exercised through transactional send
def _new_conversation(key, actor, recipient, now):
    actor_id = _participant_id(actor)
    recipient_id = _participant_id(recipient)
    row = DatastoreEntity(
        key=key,
        exclude_from_indexes=(
            "participant_names",
            "unread_counts",
            "read_through",
            "cleared_through",
        ),
    )
    row.update(
        {
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
    )
    return row


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason message-row construction is exercised through transactional send
def _new_message(
    key,
    conversation,
    actor,
    recipient,
    *,
    body,
    operation_id,
    sequence,
    now,
):
    row = DatastoreEntity(
        key=key,
        exclude_from_indexes=(
            "body",
            "operation_id",
            "sender_name",
            "recipient_name",
            "hidden_for",
        ),
    )
    row.update(
        {
            "type": "message",
            "kind": "message",
            "conversation": conversation.key,
            "sequence": sequence,
            "sender": actor.key,
            "recipient": recipient.key,
            "sender_name": actor.name,
            "recipient_name": recipient.name,
            "body": body,
            "hidden_for": [],
            "operation_id": operation_id,
            "active": True,
            "created": now,
            "modified": now,
        }
    )
    return row


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason body validation is exercised through the public send boundary
def _validated_body(value):
    if not isinstance(value, str):
        raise ValidationError("Message body is required.")
    body = value.strip()
    if not body:
        raise ValidationError("Message body is required.")
    if len(body) > MESSAGE_BODY_LIMIT:
        raise ValidationError(
            f"Message body must be {MESSAGE_BODY_LIMIT} characters or fewer."
        )
    return body


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason operation validation is exercised through the public send boundary
def _validated_operation_id(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Message operation ID is required.")
    operation_id = value.strip()
    if len(operation_id) > OPERATION_ID_LIMIT:
        raise ValidationError("Message operation ID is too long.")
    return operation_id


# @testable false
# @covered-by lagniappe/core/tools/messages.py::conversation_history
# @reason participant membership is exercised through history authorization
def _participant(conversation, user):
    return user.key in set(conversation.get("participants") or ())


# @testable false
# @covered-by lagniappe/core/tools/messages.py::conversation_history
# @reason participant enforcement is exercised through history authorization
def _require_participant(conversation, user):
    if not conversation or not _participant(conversation, user):
        raise PermissionError("Conversation is unavailable.")


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason replay comparison is exercised through operation conflict coverage
def _message_payload_matches(row, actor, recipient, body, operation_id):
    return bool(
        row.get("sender") == actor.key
        and row.get("recipient") == recipient.key
        and row.get("body") == body
        and row.get("operation_id") == operation_id
    )


# @testable false
# @covered-by lagniappe/core/tools/messages.py::send_message
# @reason transaction implementation is exercised through the public idempotent send boundary
@notification_service.retry_transaction
def _send_transaction(
    actor,
    recipient,
    body,
    operation_id,
    *,
    require_existing=False,
):
    conversation_key = _conversation_key(actor, recipient)
    message_key = _message_key(conversation_key, actor, operation_id)
    now = datetime.now(timezone.utc)
    with DATA.datastore.transaction() as transaction:
        existing_message = DATA.datastore.get(message_key, transaction=transaction)
        if existing_message is not None:
            if not _message_payload_matches(
                existing_message, actor, recipient, body, operation_id
            ):
                raise MessageConflict("Operation ID was already used.")
            conversation = DATA.datastore.get(
                conversation_key, transaction=transaction
            )
            return existing_message, conversation, None, False

        conversation = DATA.datastore.get(conversation_key, transaction=transaction)
        if conversation is None and require_existing:
            raise PermissionError("Conversation is unavailable.")
        if conversation is None:
            conversation = _new_conversation(
                conversation_key, actor, recipient, now
            )
        _require_participant(conversation, actor)
        if recipient.key not in set(conversation.get("participants") or ()):
            raise PermissionError("Conversation is unavailable.")

        actor_id = _participant_id(actor)
        recipient_id = _participant_id(recipient)
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
        message = _new_message(
            message_key,
            conversation,
            actor,
            recipient,
            body=body,
            operation_id=operation_id,
            sequence=sequence,
            now=now,
        )
        aggregate = notification_service.mutate_aggregate_in_transaction(
            transaction, recipient, message_delta=1
        )
        transaction.put(conversation)
        transaction.put(message)
    return message, conversation, aggregate, True


# @testable true
# @tests tests_unit/test_027_messaging.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_inbound_message_allows_reply_without_compose_permission
# @pairs messaging:idempotency messaging:deterministic-key messaging:unread-count messaging:reply-permission
# @pair notifications:aggregate-count
def send_message(
    actor,
    recipient_identifier,
    body,
    operation_id,
    conversation_identifier=None,
):
    """Send or idempotently replay one direct message."""
    recipient = collaboration.resolve_user(recipient_identifier)
    if not recipient:
        raise PermissionError("Recipient is not eligible for messages.")
    can_initiate = collaboration.recipient_allowed(
        actor, recipient, channel="message"
    )
    reply_key = (
        database.get.datastore_key(conversation_identifier)
        if conversation_identifier
        else None
    )
    reply_matches = bool(
        reply_key and reply_key == _conversation_key(actor, recipient)
    )
    if conversation_identifier and not reply_matches:
        raise PermissionError("Conversation is unavailable.")
    if not can_initiate and not reply_matches:
        raise PermissionError("Recipient is not eligible for messages.")
    body = _validated_body(body)
    operation_id = _validated_operation_id(operation_id)
    notification_service.ensure_notification_aggregate(recipient)
    message, conversation, aggregate, created = _send_transaction(
        actor,
        recipient,
        body,
        operation_id,
        require_existing=not can_initiate,
    )
    if aggregate is not None:
        notification_service.publish_notification_aggregate(recipient, aggregate)
    if created:
        try:
            notification_email.record_message(message, conversation, recipient)
        except Exception as error:
            from ..exceptions import capture

            capture(error, context={"operation": "message-email-capture"})
    return {
        "message": serialize_message(message, actor),
        "conversation": serialize_conversation(conversation, actor),
        "created": created,
    }


# @testable false
# @covered-by lagniappe/core/tools/messages.py::serialize_conversation
# @reason peer selection is internal to conversation serialization
def _conversation_peer(conversation, user):
    return next(
        (
            key
            for key in conversation.get("participants") or ()
            if key != user.key
        ),
        None,
    )


# @testable false
# @covered-by lagniappe/core/tools/messages.py::conversations
# @covered-by lagniappe/core/tools/messages.py::conversation_history
# @reason batched peer state is exposed through conversation payloads
def _peer_status(rows, user):
    peers = {
        _conversation_peer(row, user)
        for row in rows
        if _conversation_peer(row, user) is not None
    }
    loaded = {
        entity.key: entity
        for entity in Entities.fetch(*peers, request=Fetch.direct())
        if isinstance(entity, Entities.USER)
    }
    return {
        key: {
            "peer_available": bool(
                loaded.get(key)
                and collaboration.recipient_allowed(
                    user, loaded[key], channel="message"
                )
            ),
            "peer_replyable": bool(
                loaded.get(key) and collaboration.managed_user(loaded[key])
            ),
            "peer_deleted": key not in loaded,
        }
        for key in peers
    }


# @testable false
# @covered-by lagniappe/core/tools/messages.py::conversations
# @covered-by lagniappe/core/tools/messages.py::conversation_history
# @reason serialization is asserted through list and history service payloads
def serialize_conversation(
    conversation,
    user,
    *,
    peer_available=True,
    peer_replyable=True,
    peer_deleted=False,
):
    user_id = _participant_id(user)
    peer_key = _conversation_peer(conversation, user)
    peer_id = _encoded_key(peer_key) if peer_key else None
    names = conversation.get("participant_names") or {}
    return {
        "id": _encoded_key(conversation.key),
        "peer": {
            "id": peer_id,
            "name": names.get(peer_id) or "Deleted user",
            "available": bool(peer_available),
            "replyable": bool(peer_replyable),
            "deleted": bool(peer_deleted),
        },
        "last_activity": (
            conversation.get("last_activity").isoformat()
            if conversation.get("last_activity")
            else None
        ),
        "last_sender": _encoded_key(conversation.get("last_sender"))
        if conversation.get("last_sender")
        else None,
        "unread": int((conversation.get("unread_counts") or {}).get(user_id) or 0),
        "revision": int(conversation.get("revision") or 0),
        "sequence": int(conversation.get("sequence") or 0),
    }


# @testable false
# @covered-by lagniappe/core/tools/messages.py::conversation_history
# @reason serialization is asserted through chronological history payloads
def serialize_message(message, viewer):
    sender_id = _encoded_key(message.get("sender"))
    recipient_id = _encoded_key(message.get("recipient"))
    return {
        "id": _encoded_key(message.key),
        "sequence": int(message.get("sequence") or 0),
        "sender": {
            "id": sender_id,
            "name": message.get("sender_name") or "Deleted user",
        },
        "recipient": {
            "id": recipient_id,
            "name": message.get("recipient_name") or "Deleted user",
        },
        "body": message.get("body") or "",
        "created": message.get("created").isoformat()
        if message.get("created")
        else None,
        "mine": message.get("sender") == viewer.key,
    }


# @testable true
# @tests tests_unit/test_027_messaging.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pairs messaging:conversation-page messaging:compose-eligibility
def conversations(user, cursor=None, limit=CONVERSATION_PAGE_SIZE):
    if not collaboration.managed_user(user):
        raise PermissionError("Messaging is available to managed users only.")
    page = (
        Query(KINDS.message_conversations)
        .filter(Filter().eq("visible_to", user.key))
        .order("-last_activity")
        .limit(limit)
        .cursor(cursor)
        .fetch()
    )
    rows = list(page)
    peer_status = _peer_status(rows, user)
    return {
        "conversations": [
            serialize_conversation(
                row,
                user,
                **peer_status.get(
                    _conversation_peer(row, user),
                    {
                        "peer_available": False,
                        "peer_replyable": False,
                        "peer_deleted": True,
                    },
                ),
            )
            for row in rows
        ],
        "cursor": page.next_cursor,
    }


# @testable false
# @covered-by lagniappe/core/tools/messages.py::conversation_history
# @covered-by lagniappe/web/routes/messages/main.py::clear_modal
# @reason participant lookup is exercised through the history and modal boundaries
def get_conversation(user, conversation_identifier):
    key = database.get.datastore_key(conversation_identifier)
    conversation = DATA.datastore.get(key) if key else None
    _require_participant(conversation, user)
    return conversation


# @testable true
# @tests tests_unit/test_027_messaging.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pairs messaging:history-page messaging:clear-horizon messaging:chronological-display
def conversation_history(
    user,
    conversation_identifier,
    cursor=None,
    limit=HISTORY_PAGE_SIZE,
):
    conversation = get_conversation(user, conversation_identifier)
    peer_key = _conversation_peer(conversation, user)
    peer_status = _peer_status([conversation], user).get(
        peer_key,
        {
            "peer_available": False,
            "peer_replyable": False,
            "peer_deleted": True,
        },
    )
    user_id = _participant_id(user)
    cleared = int((conversation.get("cleared_through") or {}).get(user_id) or 0)
    visible = []
    next_cursor = cursor
    exhausted = False
    while len(visible) < limit and not exhausted:
        requested = max(limit, limit - len(visible))
        page = (
            Query(KINDS.messages, ancestor=conversation.key)
            .order("-sequence")
            .limit(requested)
            .cursor(next_cursor)
            .fetch()
        )
        next_cursor = page.next_cursor
        for row in page:
            if int(row.get("sequence") or 0) <= cleared:
                exhausted = True
                break
            if user.key not in set(row.get("hidden_for") or ()):
                visible.append(row)
                if len(visible) == limit:
                    break
        if not page.next_cursor:
            exhausted = True
    return {
        "conversation": serialize_conversation(
            conversation, user, **peer_status
        ),
        "messages": [serialize_message(row, user) for row in reversed(visible)],
        "cursor": None if exhausted else next_cursor,
    }


# @testable false
# @covered-by lagniappe/core/tools/messages.py::mark_read
# @reason transaction implementation is exercised through revision-aware read coverage
@notification_service.retry_transaction
def _read_transaction(user, conversation_key, expected_revision):
    with DATA.datastore.transaction() as transaction:
        conversation = DATA.datastore.get(
            conversation_key, transaction=transaction
        )
        _require_participant(conversation, user)
        if expected_revision is not None and int(
            conversation.get("revision") or 0
        ) != int(expected_revision):
            raise MessageRevisionConflict(serialize_conversation(conversation, user))
        user_id = _participant_id(user)
        unread = dict(conversation.get("unread_counts") or {})
        prior = int(unread.get(user_id) or 0)
        if not prior:
            return conversation, None
        unread[user_id] = 0
        read_through = dict(conversation.get("read_through") or {})
        read_through[user_id] = int(conversation.get("sequence") or 0)
        conversation["unread_counts"] = unread
        conversation["read_through"] = read_through
        conversation["revision"] = int(conversation.get("revision") or 0) + 1
        conversation["modified"] = datetime.now(timezone.utc)
        aggregate = notification_service.mutate_aggregate_in_transaction(
            transaction, user, message_delta=-prior
        )
        transaction.put(conversation)
    return conversation, aggregate


# @testable true
# @tests tests_unit/test_027_messaging.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pairs messaging:read-race messaging:unread-count notifications:aggregate-count
def mark_read(user, conversation_identifier, expected_revision=None):
    key = database.get.datastore_key(conversation_identifier)
    if not key:
        raise ValueError("Conversation key is invalid.")
    notification_service.ensure_notification_aggregate(user)
    conversation, aggregate = _read_transaction(user, key, expected_revision)
    if aggregate is not None:
        notification_service.publish_notification_aggregate(user, aggregate)
    peer_key = _conversation_peer(conversation, user)
    peer_status = _peer_status([conversation], user).get(
        peer_key,
        {
            "peer_available": False,
            "peer_replyable": False,
            "peer_deleted": True,
        },
    )
    return serialize_conversation(
        conversation, user, **peer_status
    )


# @testable false
# @covered-by lagniappe/core/tools/messages.py::hide_message
# @reason transaction implementation is exercised through per-copy delete coverage
@notification_service.retry_transaction
def _hide_message_transaction(user, message_key):
    with DATA.datastore.transaction() as transaction:
        message = DATA.datastore.get(message_key, transaction=transaction)
        if message is None:
            return None, None
        conversation = DATA.datastore.get(
            message.key.parent, transaction=transaction
        )
        _require_participant(conversation, user)
        hidden = set(message.get("hidden_for") or ())
        if user.key in hidden:
            return conversation, None
        hidden.add(user.key)
        message["hidden_for"] = list(hidden)
        message["modified"] = datetime.now(timezone.utc)
        aggregate = None
        user_id = _participant_id(user)
        unread = dict(conversation.get("unread_counts") or {})
        read_through = int(
            (conversation.get("read_through") or {}).get(user_id) or 0
        )
        if (
            message.get("recipient") == user.key
            and int(message.get("sequence") or 0) > read_through
            and int(unread.get(user_id) or 0) > 0
        ):
            unread[user_id] = int(unread[user_id]) - 1
            conversation["unread_counts"] = unread
            conversation["revision"] = int(conversation.get("revision") or 0) + 1
            aggregate = notification_service.mutate_aggregate_in_transaction(
                transaction, user, message_delta=-1
            )
            transaction.put(conversation)
        transaction.put(message)
    return conversation, aggregate


# @testable true
# @tests tests_unit/test_027_messaging.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pairs messaging:per-copy-delete messaging:unread-count
def hide_message(user, message_identifier):
    key = database.get.datastore_key(message_identifier)
    if not key:
        raise ValueError("Message key is invalid.")
    notification_service.ensure_notification_aggregate(user)
    conversation, aggregate = _hide_message_transaction(user, key)
    if aggregate is not None:
        notification_service.publish_notification_aggregate(user, aggregate)
    return bool(conversation)


# @testable false
# @covered-by lagniappe/core/tools/messages.py::clear_conversation
# @reason transaction implementation is exercised through clear-horizon coverage
@notification_service.retry_transaction
def _clear_conversation_transaction(user, conversation_key):
    with DATA.datastore.transaction() as transaction:
        conversation = DATA.datastore.get(
            conversation_key, transaction=transaction
        )
        _require_participant(conversation, user)
        user_id = _participant_id(user)
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
        conversation["modified"] = datetime.now(timezone.utc)
        aggregate = None
        if prior:
            aggregate = notification_service.mutate_aggregate_in_transaction(
                transaction, user, message_delta=-prior
            )
        transaction.put(conversation)
    return conversation, aggregate


# @testable true
# @tests tests_unit/test_027_messaging.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pairs messaging:clear-horizon messaging:new-after-clear messaging:unread-count
def clear_conversation(user, conversation_identifier):
    key = database.get.datastore_key(conversation_identifier)
    if not key:
        raise ValueError("Conversation key is invalid.")
    notification_service.ensure_notification_aggregate(user)
    conversation, aggregate = _clear_conversation_transaction(user, key)
    if aggregate is not None:
        notification_service.publish_notification_aggregate(user, aggregate)
    return serialize_conversation(conversation, user)
