"""Internal one-to-one messaging entities."""

from .entity import Entity
from ..properties import messaging


# @testable true
# @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair messaging:entity-contract
class MessageConversation(Entity):
    """Durable participant state and cursors for a direct-message thread."""

    entity_kind = "message_conversation"

    # @testable true
    # @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
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
                "participants": messaging.Participants,
                "visible_to": messaging.VisibleTo,
                "participant_names": messaging.ParticipantNames,
                "last_activity": messaging.LastActivity,
                "last_sender": messaging.LastSender,
                "sequence": messaging.Sequence,
                "revision": messaging.Revision,
                "unread_counts": messaging.UnreadCounts,
                "read_through": messaging.ReadThrough,
                "cleared_through": messaging.ClearedThrough,
            }
        )
        return properties


# @testable true
# @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair messaging:entity-contract
class Message(Entity):
    """One immutable plain-text message in a conversation ancestor group."""

    entity_kind = "message"

    # @testable true
    # @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
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
                "conversation": messaging.Conversation,
                "sequence": messaging.Sequence,
                "sender": messaging.Sender,
                "recipient": messaging.Recipient,
                "sender_name": messaging.SenderName,
                "recipient_name": messaging.RecipientName,
                "body": messaging.Body,
                "hidden_for": messaging.HiddenFor,
                "operation_id": messaging.OperationID,
            }
        )
        return properties
