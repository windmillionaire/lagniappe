from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from . import property_types
    from google.cloud.datastore import Key
    from lagniappe.core.entities.entity import EntityProperties
    from typing import Self


from .entity import Entity
from ..properties import activity, notification, notification_aggregate
from lagniappe.core.tools.database import notifications as database_notifications
from lagniappe.core.tools.database import utility as database_utility


class NotificationCreation(TypedDict, total=False):
    parent: Entity
    target: Entity | None
    identifier: str
    body: str | None
    pending: bool
    event_type: str | None
    sender_name: str | None


# @testable false
# @covered-by lagniappe/core/entities/notification.py::Notification.create
# @reason notification entity shell metadata is exercised through the process notification create path
class Notification(Entity):
    if TYPE_CHECKING:
        event_type: str | None
        sender_name: str | None
        ordinary_count: int
        unread_message_count: int
        aggregate_revision: int
        message_revision: int
        aggregate_generation: str | None

        parent: Entity | None
        target: Entity | None
        notification_type: str
        pending: bool
        body: str | None

        @property
        def properties(self) -> property_types.NotificationProperties: ...

    entity_kind = "notification"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        exclude = {
            "body",
            "sender_name",
        }
        return frozenset(exclude)

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "parent": activity.AttachedParent,
                "target": notification.Target,
                "body": activity.Body,
                "pending": notification.Pending,
                "notification_type": notification.NotificationType,
                "event_type": notification.EventType,
                "sender_name": notification.SenderName,
                "ordinary_count": notification_aggregate.OrdinaryCount,
                "unread_message_count": notification_aggregate.UnreadMessageCount,
                "aggregate_revision": notification_aggregate.AggregateRevision,
                "message_revision": notification_aggregate.MessageRevision,
                "aggregate_generation": notification_aggregate.AggregateGeneration,
            }
        )
        return properties

    @property
    def required(self) -> list[str]:
        parent = self.parent
        if parent is None:
            raise AttributeError(f"{type(self).__name__} requires an attached parent")
        return [parent.hash]

    # @testable false
    # @covered-by lagniappe/web/routes/home/main.py::clear_notifications
    # @reason notification ownership and deletion are exercised through the route
    @classmethod
    def keys_for_parent(cls, parent: Entity | Key) -> list[Key]:
        return database_notifications.notification_keys(parent)

    # @testable true
    # @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_renders_target_and_preserves_pending_state
    # @matrix notifications : body create
    @classmethod
    def create(cls, data: NotificationCreation) -> Self:
        parent = data.get("parent")
        target = data.get("target")

        if identifier := data.get("identifier"):
            key = database_utility.create_named_key(
                "notification", identifier, parent=parent
            )
            new_notification = cls(database_utility.create_entity(key))
        else:
            new_notification = cls(parent=parent)
        new_notification.kind = cls.entity_kind
        new_notification.parent = parent
        new_notification.target = target
        new_notification.body = data.get("body")
        new_notification.pending = data.get("pending", False)
        new_notification.notification_type = "ordinary"
        new_notification.event_type = (
            str(event_type) if (event_type := data.get("event_type")) else None
        )
        new_notification.sender_name = (
            str(sender_name) if (sender_name := data.get("sender_name")) else None
        )

        return new_notification
