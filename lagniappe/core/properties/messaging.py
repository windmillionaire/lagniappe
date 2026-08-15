"""Persisted properties for private messaging and notification aggregates."""

from .base_db import DBProperty


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


class Conversation(DBProperty):
    _id = "conversation"


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


# @testable true
# @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:discriminator
class NotificationType(DBProperty):
    _id = "notification_type"

    # @testable true
    # @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:discriminator
    @property
    def value(self):
        return super().value or "ordinary"

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:aggregate-count
class OrdinaryCount(DBProperty):
    _id = "ordinary_count"

    # @testable true
    # @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:aggregate-count
    @property
    def value(self):
        return int(super().value or 0)

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:aggregate-count
class UnreadMessageCount(DBProperty):
    _id = "unread_message_count"

    # @testable true
    # @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:aggregate-count
    @property
    def value(self):
        return int(super().value or 0)

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:revision
class AggregateRevision(DBProperty):
    _id = "aggregate_revision"

    # @testable true
    # @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:revision
    @property
    def value(self):
        return int(super().value or 0)

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:generation
class AggregateGeneration(DBProperty):
    _id = "aggregate_generation"

    # @testable true
    # @tests tests_unit/test_027_messaging.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:generation
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)
