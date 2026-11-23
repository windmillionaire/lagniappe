"""Persisted direct-message values, identity, validation, and projection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from google.cloud.datastore import Entity as DatastoreEntity
    from google.cloud.datastore import Key
    from lagniappe.core.entities import types as models


import hashlib

from ..exceptions import ValidationError
from .base_db import DBProperty
from .message_conversation import encoded_identifier, participant_id


MESSAGE_BODY_LIMIT = 1000
OPERATION_ID_LIMIT = 128


def normalize_body(value: object) -> str:
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


def normalize_operation_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Message operation ID is required.")
    operation_id = value.strip()
    if len(operation_id) > OPERATION_ID_LIMIT:
        raise ValidationError("Message operation ID is too long.")
    return operation_id


def message_identity(sender: models.User | Key, operation_id: str) -> str:
    identity = f"{participant_id(sender)}\0{operation_id}"
    return hashlib.sha256(identity.encode()).hexdigest()


def initial_values(conversation: models.MessageConversation | DatastoreEntity, actor: models.User, recipient: models.User, body: str, operation_id: str, sequence: int, now: datetime) -> dict[str, object]:
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


def payload_matches(row: Mapping[str, object], actor: models.User, recipient: models.User, body: str, operation_id: str) -> bool:
    return bool(
        row.get("sender") == actor.key
        and row.get("recipient") == recipient.key
        and row.get("body") == body
        and row.get("operation_id") == operation_id
    )


def projection(row: DatastoreEntity, viewer: models.User) -> dict[str, object]:
    created = row.get("created")
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
        "created": created.isoformat() if created else None,
        "mine": row.get("sender") == viewer.key,
    }


class Conversation(DBProperty["Key"]):
    _id = "conversation"


class Sequence(DBProperty[int]):
    _id = "sequence"


class Sender(DBProperty["Key"]):
    _id = "sender"


class Recipient(DBProperty["Key"]):
    _id = "recipient"


class SenderName(DBProperty[str]):
    _id = "sender_name"


class RecipientName(DBProperty[str]):
    _id = "recipient_name"


class Body(DBProperty[str]):
    _id = "body"


class HiddenFor(DBProperty["list[Key]"]):
    _id = "hidden_for"


class OperationID(DBProperty[str]):
    _id = "operation_id"
