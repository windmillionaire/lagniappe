"""Notification creation services shared by asynchronous entry points."""

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_process_notification_requires_a_valid_user
# @pairs notifications:create notifications:body notifications:task-queue
def create_process_notification(payload, body):
    """Create a notification for the valid user named by a process payload."""
    user_key = payload.get("user_key")
    if not user_key:
        return None

    user = Entities.fetch_one(user_key, request=Fetch.direct())
    if not user or user.kind != "user":
        return None

    notification = Entities.NOTIFICATION.create({"parent": user, "body": body})
    Entities.save(notification)
    return notification
