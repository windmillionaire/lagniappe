"""Ordinary-notification, mention, and assignment email contracts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from google.cloud.datastore import Entity as DatastoreEntity
import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import notification_email as email_database
from lagniappe.core.tools.database.core import KINDS
from lagniappe.core.tools.email.notifications import capture as email_capture
from lagniappe.core.tools.email.notifications import delivery as email_delivery
from lagniappe.core.tools.email.notifications import links as email_links
from lagniappe.core.tools.email.notifications import presentation as email_presentation
from testing.utility.notification_email_fakes import (
    MemoryDatastore,
    task_recorder,
    user_row,
)


pytestmark = pytest.mark.unit


# @source lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @source lagniappe/core/tools/email/notifications/delivery.py::deliver
# @pairs notification-email:immediate notification-email:html notification-email:idempotency
# @pair notification-email:presence-suppression
# @pairs notification-email:notification notification-email:pending-filter
def test_immediate_notification_is_delayed_escaped_and_delivered(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(email_database.DATA, "_datastore_client", store)
    tasks = task_recorder(monkeypatch)
    recipient = user_row("recipient", now)
    source_key = store.key(KINDS.activity.value, "notice", parent=recipient.key)
    source = DatastoreEntity(key=source_key)
    source.update({"type": "notification", "notification_type": "ordinary"})
    store.put(source)

    assert (
        email_capture.record_notification(
            SimpleNamespace(notification_type="aggregate", pending=False),
            now=now,
        )
        is None
    )
    assert (
        email_capture.record_notification(
            SimpleNamespace(notification_type="ordinary", pending=True),
            now=now,
        )
        is None
    )

    delivery = email_capture.record_notification(
        SimpleNamespace(
            key=source_key,
            parent=recipient,
            body="Ready <b>now</b>",
            target=None,
            notification_type="ordinary",
            pending=False,
        ),
        now=now,
    )

    replay = email_capture.record_notification_event(
        recipient,
        source_key,
        body="Ready <b>now</b>",
        target=None,
        now=now,
    )

    assert replay.key == delivery.key
    assert delivery["due_at"] == now + timedelta(minutes=5)
    assert tasks[0]["task_id"] == tasks[1]["task_id"]

    class UnloadedTargetNotification(SimpleNamespace):
        @property
        def target(self):
            raise AssertionError("record_notification accessed an unloaded target")

    unloaded_source_key = store.key(
        KINDS.activity.value,
        "unloaded-target-notice",
        parent=recipient.key,
    )
    unloaded_target_key = store.key("page", "unloaded-target")
    unloaded_target = SimpleNamespace(url="/pages/unloaded-target")

    def fetch_unloaded_target(identifier, **_kwargs):
        assert identifier == unloaded_target_key
        return unloaded_target

    monkeypatch.setattr(
        email_capture.Entities,
        "fetch_one",
        fetch_unloaded_target,
    )
    unloaded_delivery = email_capture.record_notification(
        UnloadedTargetNotification(
            key=unloaded_source_key,
            parent=recipient,
            body="Target was not hydrated",
            properties=SimpleNamespace(
                target=SimpleNamespace(is_set=False, key=unloaded_target_key)
            ),
            notification_type="ordinary",
            pending=False,
        ),
        now=now,
    )
    assert unloaded_delivery["target_path"] == unloaded_target.url

    sent = []
    monkeypatch.setattr(
        email_delivery.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    monkeypatch.setattr(
        email_delivery.presence,
        "recently_active",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        email_presentation.smtp,
        "send_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or True,
    )

    result = email_delivery.deliver(
        delivery.key.to_legacy_urlsafe().decode(),
        now=now + timedelta(minutes=5),
    )

    assert result == {"state": "sent"}
    assert sent[0][0][0] == "recipient@example.test"
    assert "Ready &lt;b&gt;now&lt;/b&gt;" in sent[0][0][3]
    assert store.get(delivery.key)["state"] == "sent"

    active_source_key = store.key(
        KINDS.activity.value,
        "active-notice",
        parent=recipient.key,
    )
    active_source = DatastoreEntity(key=active_source_key)
    active_source.update({"type": "notification", "notification_type": "ordinary"})
    store.put(active_source)
    active_delivery = email_capture.record_notification_event(
        recipient,
        active_source_key,
        body="Visible on site",
        now=now + timedelta(minutes=10),
    )
    monkeypatch.setattr(
        email_delivery.presence,
        "recently_active",
        lambda *_args, **_kwargs: True,
    )

    assert email_delivery.deliver(
        active_delivery.key.to_legacy_urlsafe().decode(),
        now=now + timedelta(minutes=15),
    ) == {"state": "suppressed"}
    assert len(sent) == 1


# @source lagniappe/core/tools/email/notifications/capture.py::record_document_mention
# @source lagniappe/core/tools/email/notifications/delivery.py::deliver
# @pair notification-email:document-mention
def test_document_mention_email_uses_concise_copy_and_document_tab(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(email_database.DATA, "_datastore_client", store)
    task_recorder(monkeypatch)
    monkeypatch.setattr(email_presentation.CONFIG, "APP_NAME", "Test Lagniappe")
    monkeypatch.setattr(
        email_links.CONFIG,
        "GOOGLE_LOGIN_URI",
        "https://lagniappe.example.test/login",
    )
    recipient = user_row("recipient", now)
    source_key = store.key(
        KINDS.activity.value,
        "document-mention",
        parent=recipient.key,
    )
    source = DatastoreEntity(key=source_key)
    source.update({"type": "notification", "notification_type": "ordinary"})
    store.put(source)
    document = SimpleNamespace(name="Roadmap & Launch", url="/pages/roadmap")

    delivery = email_capture.record_document_mention(
        recipient,
        source_key,
        document=document,
        now=now,
    )

    assert delivery["body"] == "You were mentioned in the Roadmap & Launch document."
    assert delivery["target_path"] == "/pages/roadmap?tab=document"

    sent = []
    monkeypatch.setattr(
        email_delivery.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    monkeypatch.setattr(
        email_delivery.presence,
        "recently_active",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        email_presentation.smtp,
        "send_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or True,
    )

    result = email_delivery.deliver(
        delivery.key.to_legacy_urlsafe().decode(),
        now=now + timedelta(minutes=5),
    )

    assert result == {"state": "sent"}
    _, subject, text_body, html_body = sent[0][0]
    assert subject == "Test Lagniappe document mention"
    assert text_body == (
        "You were mentioned in the Roadmap & Launch document.\n"
        "https://lagniappe.example.test/pages/roadmap?tab=document"
    )
    assert "<h1" not in html_body
    assert "<h2" not in html_body
    assert (
        "You were mentioned in the <i>Roadmap &amp; Launch</i> document." in html_body
    )
    assert (
        'href="https://lagniappe.example.test/pages/roadmap?tab=document"' in html_body
    )


# @source lagniappe/core/tools/email/notifications/capture.py::record_notification
# @source lagniappe/core/tools/email/notifications/delivery.py::deliver
# @pair notification-email:task-assignment
def test_task_assignment_email_uses_task_copy_without_headers(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(email_database.DATA, "_datastore_client", store)
    task_recorder(monkeypatch)
    monkeypatch.setattr(email_presentation.CONFIG, "APP_NAME", "Test Lagniappe")
    monkeypatch.setattr(
        email_links.CONFIG,
        "GOOGLE_LOGIN_URI",
        "https://lagniappe.example.test/login",
    )
    monkeypatch.setattr(
        email_capture.links,
        "target_path",
        lambda _target: "/tasks/assigned-task",
    )
    recipient = user_row("recipient", now)
    source_key = store.key(
        KINDS.activity.value,
        "task-assignment",
        parent=recipient.key,
    )
    source = DatastoreEntity(key=source_key)
    source.update({"type": "notification", "notification_type": "ordinary"})
    store.put(source)
    task_row = DatastoreEntity(key=store.key(KINDS.instances.value, "assigned-task"))
    task_row.update(
        {
            "type": "task",
            "kind": "task",
            "name": "Review <Launch>",
            "active": True,
            "completed": False,
        }
    )
    task = Entities.TASK(task_row)
    notification = SimpleNamespace(
        key=source_key,
        parent=recipient,
        body="Alice & Bob assigned you a task.",
        db={
            "event_type": email_capture.TASK_ASSIGNMENT_EVENT,
            "sender_name": "Alice & Bob",
        },
        properties=SimpleNamespace(
            target=SimpleNamespace(is_set=True, value=task),
        ),
        notification_type="ordinary",
        pending=False,
    )

    delivery = email_capture.record_notification(notification, now=now)

    assert delivery["event_type"] == email_capture.TASK_ASSIGNMENT_EVENT
    assert delivery["sender_name"] == "Alice & Bob"
    assert delivery["task_name"] == "Review <Launch>"
    assert delivery["target_path"] == "/tasks/assigned-task"

    sent = []
    monkeypatch.setattr(
        email_delivery.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    monkeypatch.setattr(
        email_delivery.presence,
        "recently_active",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        email_presentation.smtp,
        "send_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or True,
    )

    result = email_delivery.deliver(
        delivery.key.to_legacy_urlsafe().decode(),
        now=now + timedelta(minutes=5),
    )

    assert result == {"state": "sent"}
    _, subject, text_body, html_body = sent[0][0]
    assert subject == "Task assigned on Test Lagniappe"
    assert text_body == (
        "Alice & Bob assigned you the task Review <Launch>.\n"
        "https://lagniappe.example.test/tasks/assigned-task"
    )
    assert "<h1" not in html_body
    assert "<h2" not in html_body
    assert (
        "Alice &amp; Bob assigned you the task <i>Review &lt;Launch&gt;</i>."
        in html_body
    )
    assert 'href="https://lagniappe.example.test/tasks/assigned-task"' in html_body
