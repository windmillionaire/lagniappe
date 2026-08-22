"""Persisted direct-message values, identity, validation, and projection."""

import hashlib

from ..exceptions import ValidationError
from .base_db import DBProperty
from .message_conversation import encoded_identifier, participant_id


MESSAGE_BODY_LIMIT = 1000
OPERATION_ID_LIMIT = 128


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:body-validation
def normalize_body(value):
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


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:idempotency
def normalize_operation_id(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Message operation ID is required.")
    operation_id = value.strip()
    if len(operation_id) > OPERATION_ID_LIMIT:
        raise ValidationError("Message operation ID is too long.")
    return operation_id


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:deterministic-key
def message_identity(sender, operation_id):
    identity = f"{participant_id(sender)}\0{operation_id}"
    return hashlib.sha256(identity.encode()).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::send_message_record
# @reason exact raw message construction is exercised through the transaction boundary
def initial_values(conversation, actor, recipient, body, operation_id, sequence, now):
    return {
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


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::send_message_record
# @reason replay comparison is exercised through idempotent send behavior
def payload_matches(row, actor, recipient, body, operation_id):
    return bool(
        row.get("sender") == actor.key
        and row.get("recipient") == recipient.key
        and row.get("body") == body
        and row.get("operation_id") == operation_id
    )


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:chronological-display
def projection(row, viewer):
    sender_id = encoded_identifier(row.get("sender"))
    recipient_id = encoded_identifier(row.get("recipient"))
    return {
        "id": encoded_identifier(row.key),
        "sequence": int(row.get("sequence") or 0),
        "sender": {
            "id": sender_id,
            "name": row.get("sender_name") or "Deleted user",
        },
        "recipient": {
            "id": recipient_id,
            "name": row.get("recipient_name") or "Deleted user",
        },
        "body": row.get("body") or "",
        "created": row.get("created").isoformat() if row.get("created") else None,
        "mine": row.get("sender") == viewer.key,
    }


class Conversation(DBProperty):
    _id = "conversation"


class Sequence(DBProperty):
    _id = "sequence"


class Sender(DBProperty):
    _id = "sender"


class Recipient(DBProperty):
    _id = "recipient"


class SenderName(DBProperty):
    _id = "sender_name"


class RecipientName(DBProperty):
    _id = "recipient_name"


class Body(DBProperty):
    _id = "body"


class HiddenFor(DBProperty):
    _id = "hidden_for"


class OperationID(DBProperty):
    _id = "operation_id"
