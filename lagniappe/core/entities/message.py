"""Internal one-to-one messaging entities."""

from .entity import Entity
from ..properties import message as message_properties
from ..properties import message_conversation
from ..tools import database


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pairs messaging:entity-contract messaging:polling-revision
class MessageConversation(Entity):
    """Durable participant state and cursors for a direct-message thread."""

    entity_kind = "message_conversation"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair messaging:index-exclusion
    @property
    def exclude_from_index(self):
        return frozenset(
            {
                "participant_names",
                "unread_counts",
                "read_through",
                "cleared_through",
            }
        )

    # @testable false
    # @covered-by lagniappe/core/entities/message.py::MessageConversation
    # @reason property registry composition is exercised through the entity contract
    def _get_properties(self):
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
    def create(cls, actor, recipient, *, key, now):
        conversation = cls(database.create_entity(key))
        conversation.db.exclude_from_indexes = conversation.exclude_from_index
        conversation.db.update(message_conversation.initial_values(actor, recipient, now))
        return conversation


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair messaging:entity-contract
class Message(Entity):
    """One immutable plain-text message in a conversation ancestor group."""

    entity_kind = "message"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair messaging:index-exclusion
    @property
    def exclude_from_index(self):
        return frozenset(
            {
                "body",
                "operation_id",
                "sender_name",
                "recipient_name",
                "hidden_for",
            }
        )

    # @testable false
    # @covered-by lagniappe/core/entities/message.py::Message
    # @reason property registry composition is exercised through the entity contract
    def _get_properties(self):
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
        conversation,
        actor,
        recipient,
        *,
        key,
        body,
        operation_id,
        sequence,
        now,
    ):
        message = cls(database.create_entity(key))
        message.db.exclude_from_indexes = message.exclude_from_index
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
