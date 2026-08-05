from .entity import Entity
from ..properties import activity
from ..tools import database


# @testable false
# @covered-by lagniappe/core/entities/notification.py::Notification.create
# @reason notification entity shell metadata is exercised through the process notification create path
class Notification(Entity):
    entity_kind = "notification"

    @property
    def exclude_from_index(self):
        exclude = {
            "body",
        }
        return frozenset(exclude)

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "parent": activity.AttachedParent,
                "target": activity.Target,
                "body": activity.Body,
                "pending": activity.Pending,
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
        return database.get.notification_keys(parent)

    # @testable true
    # @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_channel_uses_menu_not_home_notes
    # @tests tests_e2e/002_home/test_002i_home_activity.py::test_home_notes_exclude_notifications
    # @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_renders_target_and_preserves_pending_state
    # @pairs activity:create activity:body activity:parent
    # @pairs notifications:create notifications:body notifications:parent
    # @pairs notifications:target notifications:pending
    @classmethod
    def create(cls, data):
        parent = data.get("parent")
        target = data.get("target")

        new_notification = cls(parent=parent)
        new_notification.kind = cls.entity_kind
        new_notification.parent = parent
        new_notification.target = target
        new_notification.body = data.get("body")
        new_notification.pending = data.get("pending", False)

        return new_notification
