from .entity import Entity
from ..properties import activity, notification, notification_aggregate
from lagniappe.core.tools.database import notifications as database_notifications
from lagniappe.core.tools.database import utility as database_utility


# @testable false
# @covered-by lagniappe/core/entities/notification.py::Notification.create
# @reason notification entity shell metadata is exercised through the process notification create path
class Notification(Entity):
    entity_kind = "notification"

    @property
    def exclude_from_index(self):
        exclude = {
            "body",
            "sender_name",
        }
        return frozenset(exclude)

    def _get_properties(self):
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
    def required(self):
        return [self.parent.hash]

    # @testable false
    # @covered-by lagniappe/web/routes/home/main.py::clear_notifications
    # @reason notification ownership and deletion are exercised through the route
    @classmethod
    def keys_for_parent(cls, parent):
        return database_notifications.notification_keys(parent)

    # @testable true
    # @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_channel_uses_menu_not_home_notes
    # @tests tests_e2e/002_home/test_002i_home_activity.py::test_home_notes_exclude_notifications
    # @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_renders_target_and_preserves_pending_state
    # @matrix activity : body create parent
    # @matrix notifications : body create parent pending target
    # @pair activity:notes-only
    @classmethod
    def create(cls, data):
        parent = data.get("parent")
        target = data.get("target")

        if data.get("identifier"):
            key = database_utility.create_named_key(
                "notification", data["identifier"], parent=parent
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
            str(data["event_type"]) if data.get("event_type") else None
        )
        new_notification.sender_name = (
            str(data["sender_name"]) if data.get("sender_name") else None
        )

        return new_notification
