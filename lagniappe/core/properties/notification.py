"""Persisted ordinary-notification values."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity


from ..mixins import RelatedEntityMixin
from .base_db import DBProperty


type _Target = Entity


class Target(RelatedEntityMixin[_Target], DBProperty[_Target]):
    """The entity an ordinary notification points back to."""

    _id = "target"


class Pending(DBProperty[bool]):
    """Whether a notification represents work still in progress."""

    _id = "pending"
    _truthy = {True, "true", "True", "1", "on", "yes"}

    @property
    def value(self) -> bool:
        return self.entity.db.get(self.db_key, False) in self._truthy

    @value.setter
    def value(self, value: object) -> None:
        pending = value in self._truthy
        self._value = pending
        if pending:
            self.entity.db[self.db_key] = True
        else:
            self.entity.db.pop(self.db_key, None)


class NotificationType(DBProperty[str]):
    _id = "notification_type"

    @property
    def value(self) -> str:
        return super().value or "ordinary"

    @value.setter
    def value(self, value: str | None) -> None:
        self._write_db_value(value)


class EventType(DBProperty[str]):
    _id = "event_type"


class SenderName(DBProperty[str]):
    _id = "sender_name"
