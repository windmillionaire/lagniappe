"""Persisted messaging, mention, and notification schema contracts."""

import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.entities.message import Message, MessageConversation
from lagniappe.core.entities.mention import MentionMarker
from lagniappe.core.entities.notification import Notification
from lagniappe.core.entities.user import User
from lagniappe.core.tools.database.migration_steps.v0_1_messaging import (
    canonicalize_notification_record,
)
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


# @matrix mentions : entity-contract idempotency index-exclusion
# @matrix messaging : entity-contract index-exclusion owner-opt-in polling-revision
# @matrix notifications : aggregate-count discriminator generation revision
def test_messaging_entities_and_owner_toggles_are_fail_closed():
    user = User(testing=True)
    assert user.allow_messages_and_mentions is False
    assert user.allow_task_assignments is False

    user.allow_messages_and_mentions = "true"
    user.allow_task_assignments = True
    assert user.allow_messages_and_mentions is True
    assert user.allow_task_assignments is True

    user.allow_messages_and_mentions = "false"
    user.allow_task_assignments = None
    assert user.allow_messages_and_mentions is False
    assert user.allow_task_assignments is False
    assert "allow_messages_and_mentions" not in user.db
    assert "allow_task_assignments" not in user.db

    conversation = MessageConversation(testing=True)
    message = Message(testing=True)
    marker = MentionMarker(testing=True)
    assert "participant_names" in conversation.exclude_from_index
    assert "body" in message.exclude_from_index
    assert "hidden_for" in message.exclude_from_index
    assert marker.exclude_from_index == frozenset({"occurrence_id", "display_name"})

    notification = Notification(testing=True)
    assert notification.notification_type == "ordinary"
    notification.ordinary_count = 3
    notification.unread_message_count = 2
    notification.aggregate_revision = 7
    notification.message_revision = 5
    notification.aggregate_generation = "generation-a"
    assert notification.ordinary_count == 3
    assert notification.unread_message_count == 2
    assert notification.aggregate_revision == 7
    assert notification.message_revision == 5
    assert notification.aggregate_generation == "generation-a"
# @matrix migrations : idempotency notification-discriminator
def test_notification_discriminator_migration_is_idempotent():
    notification = {"type": "notification"}
    first = canonicalize_notification_record(notification)
    second = canonicalize_notification_record(notification)

    assert first.changed is True
    assert notification["notification_type"] == "ordinary"
    assert second.changed is False
    assert canonicalize_notification_record({"type": "note"}).changed is False
# @matrix task-assignment : idempotency self-exclusion transition
def test_task_assignment_notice_uses_stable_transition_identity(monkeypatch):
    task = TestEntities.get("TASK", {"name": "Review", "hash": "task-notice"})
    actor = TestEntities.get(
        "USER",
        {
            "name": "Alice",
            "hash": "assignment-actor",
            "page": {"name": "Alice Page", "hash": "assignment-actor-page"},
        },
    )
    recipient = TestEntities.get(
        "USER",
        {
            "name": "Bob",
            "hash": "assignment-recipient",
            "page": {"name": "Bob Page", "hash": "assignment-recipient-page"},
        },
    )
    recipient.page.properties.user._value = recipient
    task.db["assignment_revision"] = 4
    captured = []
    notice = Notification(testing=True)
    notice._key = "assignment-notice"
    monkeypatch.setattr(
        Entities.NOTIFICATION,
        "create",
        lambda data: captured.append(data) or notice,
    )

    task._add_assignment_notice(actor, recipient.page)
    task._add_assignment_notice(actor, recipient.page)
    assert captured[0]["identifier"] == captured[1]["identifier"]
    assert captured[0]["parent"] is recipient
    assert captured[0]["target"] is task
    assert captured[0]["body"] == "Alice assigned you a task."
    assert captured[0]["event_type"] == "task_assignment"
    assert captured[0]["sender_name"] == "Alice"

    captured.clear()
    actor.page.properties.user._value = actor
    task._add_assignment_notice(actor, actor.page)
    assert captured == []

