"""Internal one-to-one messaging entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import property_types
    from datetime import datetime
    from google.cloud.datastore import Entity as DatastoreEntity
    from google.cloud.datastore import Key
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import EntityProperties
    from typing import Self


from .entity import Entity
from ..properties import message as message_properties
from ..properties import message_conversation
from lagniappe.core.tools.database import utility as database_utility


class MessageConversation(Entity):
    """Durable participant state and cursors for a direct-message thread."""
    if TYPE_CHECKING:
        participants: list[Key] | None
        visible_to: list[Key] | None
        participant_names: dict[str, str] | None
        last_activity: datetime | None
        last_sender: Key | None
        sequence: int | None
        revision: int | None
        unread_counts: dict[str, int] | None
        read_through: dict[str, int] | None
        cleared_through: dict[str, int] | None

        @property
        def properties(self) -> property_types.MessageConversationProperties: ...

    entity_kind = "message_conversation"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset(
            {
                "participant_names",
                "unread_counts",
                "read_through",
                "cleared_through",
            }
        )

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "participants": message_conversation.Participants,
                "visible_to": message_conversation.VisibleTo,
                "participant_names": message_conversation.ParticipantNames,
                "last_activity": message_conversation.LastActivity,
                "last_sender": message_conversation.LastSender,
                "sequence": message_conversation.Sequence,
                "revision": message_conversation.Revision,
                "unread_counts": message_conversation.UnreadCounts,
                "read_through": message_conversation.ReadThrough,
                "cleared_through": message_conversation.ClearedThrough,
            }
        )
        return properties

    @classmethod
    def create(cls, actor: models.User, recipient: models.User, *, key: Key, now: datetime) -> Self:
        row = database_utility.create_entity(key)
        conversation = cls(row)
        row.exclude_from_indexes = set(conversation.exclude_from_index)
        conversation.db.update(message_conversation.initial_values(actor, recipient, now))
        return conversation


class Message(Entity):
    """One immutable plain-text message in a conversation ancestor group."""
    if TYPE_CHECKING:
        conversation: Key | None
        sequence: int | None
        sender: Key | None
        recipient: Key | None
        sender_name: str | None
        recipient_name: str | None
        body: str | None
        hidden_for: list[Key] | None
        operation_id: str | None

        @property
        def properties(self) -> property_types.MessageProperties: ...

    entity_kind = "message"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset(
            {
                "body",
                "operation_id",
                "sender_name",
                "recipient_name",
                "hidden_for",
            }
        )

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "conversation": message_properties.Conversation,
                "sequence": message_properties.Sequence,
                "sender": message_properties.Sender,
                "recipient": message_properties.Recipient,
                "sender_name": message_properties.SenderName,
                "recipient_name": message_properties.RecipientName,
                "body": message_properties.Body,
                "hidden_for": message_properties.HiddenFor,
                "operation_id": message_properties.OperationID,
            }
        )
        return properties

    @classmethod
    def create(
        cls,
        conversation: models.MessageConversation | DatastoreEntity,
        actor: models.User,
        recipient: models.User,
        *,
        key: Key,
        body: str,
        operation_id: str,
        sequence: int,
        now: datetime,
    ) -> Self:
        row = database_utility.create_entity(key)
        message = cls(row)
        row.exclude_from_indexes = set(message.exclude_from_index)
        message.db.update(
            message_properties.initial_values(
                conversation,
                actor,
                recipient,
                body,
                operation_id,
                sequence,
                now,
            )
        )
        return message
