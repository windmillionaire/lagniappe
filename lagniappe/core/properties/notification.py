"""Persisted ordinary-notification values."""

from ..mixins import RelatedEntityMixin
from .base_db import DBProperty


class Target(RelatedEntityMixin, DBProperty):
    """The entity an ordinary notification points back to."""

    _id = "target"


# @testable false
# @covered-by lagniappe/core/entities/notification.py::Notification.create
# @reason pending normalization is exercised through notification creation
class Pending(DBProperty):
    """Whether a notification represents work still in progress."""

    _id = "pending"
    _truthy = {True, "true", "True", "1", 1, "on", "yes"}

    # @testable false
    # @covered-by lagniappe/core/entities/notification.py::Notification.create
    # @reason getter and setter form one normalization contract
    @property
    def value(self):
        return self.entity.db.get(self.db_key, False) in self._truthy

    @value.setter
    def value(self, value):
        pending = value in self._truthy
        self._value = pending
        if pending:
            self.entity.db[self.db_key] = True
        else:
            self.entity.db.pop(self.db_key, None)


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:discriminator
class NotificationType(DBProperty):
    _id = "notification_type"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:discriminator
    @property
    def value(self):
        return super().value or "ordinary"

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


class EventType(DBProperty):
    _id = "event_type"


class SenderName(DBProperty):
    _id = "sender_name"
