"""Notification-email digest query, grouping, and delivery contracts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key
import pytest

from lagniappe.core.definitions import NotificationEmailMode
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import notification_email as email_database
from lagniappe.core.tools.database.core import KINDS
from lagniappe.core.tools.notification_email import capture as email_capture
from lagniappe.core.tools.notification_email import delivery as email_delivery
from lagniappe.core.tools.notification_email import links as email_links
from lagniappe.core.tools.notification_email import presentation as email_presentation
from testing.utility.notification_email_fakes import (
    MemoryDatastore,
    task_recorder,
    user_row,
)
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


# @source lagniappe/core/tools/database/notification_email.py::digest_events
# @pairs notification-email:digest-query notification-email:recipient-scope
def test_daily_digest_query_retains_recipient_and_bucket_scope(monkeypatch):
    captured = {}

    class RecordingFilter:
        def __init__(self):
            self.conditions = []

        def eq(self, name, value):
            self.conditions.append((name, value))
            return self

    class RecordingQuery:
        def __init__(self, kind):
            captured["kind"] = kind
            captured["filters"] = []

        def filter(self, source_filter):
            captured["filters"].append(source_filter.conditions)
            return self

        def order(self, *properties):
            captured["order"] = properties
            return self

        def fetch_all(self):
            return ["digest-event"]

    monkeypatch.setattr(email_database, "Filter", RecordingFilter)
    monkeypatch.setattr(email_database, "Query", RecordingQuery)
    batch = {"recipient": "recipient-key", "bucket": "20260816T150000Z"}

    assert email_database.digest_events(batch) == ["digest-event"]
    assert captured == {
        "kind": KINDS.email_deliveries,
        "filters": [
            [
                ("recipient", "recipient-key"),
                ("record_type", "event"),
                ("mode", NotificationEmailMode.DAILY.name),
                ("bucket", "20260816T150000Z"),
                ("state", "pending"),
            ]
        ],
        "order": ("created",),
    }


# @source lagniappe/core/tools/notification_email/capture.py::record_notification
# @source lagniappe/core/tools/notification_email/capture.py::record_message
# @source lagniappe/core/tools/notification_email/delivery.py::deliver
# @pairs notification-email:digest notification-email:message-grouping
# @pairs notification-email:target-title notification-email:target-link
def test_daily_digest_groups_messages_and_uses_named_completion_links(monkeypatch):
    now = datetime(2026, 8, 15, 14, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(email_database.DATA, "_datastore_client", store)
    tasks = task_recorder(monkeypatch)
    monkeypatch.setattr(email_presentation.CONFIG, "APP_NAME", "Test Lagniappe")
    monkeypatch.setattr(
        email_links.CONFIG,
        "GOOGLE_LOGIN_URI",
        "https://lagniappe.example.test/login",
    )
    recipient = user_row("recipient", now, mode="DAILY")
    sender = user_row("sender", now)
    conversation = DatastoreEntity(
        key=store.key(KINDS.message_conversations.value, "conversation")
    )
    deliveries = []
    for sequence, body in ((1, "First message"), (2, "Second message")):
        message = DatastoreEntity(
            key=store.key(
                KINDS.messages.value,
                f"message-{sequence}",
                parent=conversation.key,
            )
        )
        message.update(
            {
                "sequence": sequence,
                "sender": sender.key,
                "sender_name": "Sender Name",
                "body": body,
                "created": now + timedelta(minutes=sequence),
            }
        )
        deliveries.append(
            email_capture.record_message(message, conversation, recipient)
        )

    report_parent = TestEntities.get(
        "USER",
        {"name": "Report owner", "hash": "digest-report-owner"},
    )
    organize = TestEntities.get(
        "REPORT",
        {
            "name": "Organize: Hotel files",
            "tool": "organize",
            "parent": report_parent,
        },
    )
    ask = TestEntities.get(
        "REPORT",
        {
            "name": "Ask: Hotel opening date",
            "tool": "ask",
            "parent": report_parent,
        },
    )
    page = TestEntities.get(
        "PAGE",
        {"name": "Hotel page", "hash": "digest-hotel-page"},
    )
    file = TestEntities.get(
        "FILE",
        {
            "name": "Vaccination record",
            "filename": "vaccination-record.pdf",
            "hash": "digest-file",
        },
    )
    original_target_path = email_links.target_path

    def target_path(target):
        if isinstance(target, Entities.REPORT):
            return original_target_path(target)
        return f"/{target.entity_kind}s/{target.urlsafe_key}"

    monkeypatch.setattr(email_links, "target_path", target_path)

    def capture(identifier, target, body):
        source_key = store.key(
            KINDS.activity.value,
            identifier,
            parent=recipient.key,
        )
        notification = SimpleNamespace(
            key=source_key,
            parent=recipient,
            body=body,
            db={},
            properties=SimpleNamespace(
                target=SimpleNamespace(is_set=True, value=target),
            ),
            notification_type="ordinary",
            pending=False,
        )
        delivery = email_capture.record_notification(notification, now=now)
        deliveries.append(delivery)
        return delivery

    organize_delivery = capture(
        "organize",
        organize,
        "Organize report is ready.",
    )
    ask_delivery = capture("ask", ask, "Ask report is ready.")
    autofill_delivery = capture("autofill", page, "Page autofill is ready.")
    summarize_delivery = capture(
        "summarize",
        file,
        f"File summary complete for {file.name}",
    )

    assert organize_delivery["title"] == organize.name
    assert organize_delivery["target_path"] == (
        f"/tools/reports/{organize.urlsafe_key}"
    )
    assert organize_delivery["body"] == ""
    assert ask_delivery["title"] == ask.name
    assert ask_delivery["body"] == ""
    assert autofill_delivery["title"] == f"Autofill: {page.name}"
    assert autofill_delivery["body"] == ""
    assert summarize_delivery["title"] == f"Summarize: {file.name}"
    assert summarize_delivery["body"] == ""

    batch_key = Key.from_legacy_urlsafe(tasks[0]["payload"]["delivery_key"])
    batch = store.get(batch_key)
    monkeypatch.setattr(
        email_database,
        "digest_events",
        lambda _batch: [store.get(delivery.key) for delivery in deliveries],
    )
    monkeypatch.setattr(
        email_delivery.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    sent = []
    monkeypatch.setattr(
        email_presentation.auth_email,
        "send_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or True,
    )

    result = email_delivery.deliver(
        batch.key.to_legacy_urlsafe().decode(),
        now=batch["due_at"],
    )

    assert result == {"state": "sent", "items": 6}
    _, subject, text_body, html_body = sent[0][0]
    assert subject == "Test Lagniappe daily digest"
    assert text_body.startswith(
        "Messages from Sender Name\nFirst message\n\nSecond message"
    )
    assert "Daily digest" not in text_body
    assert "<h1" not in html_body
    message_url = "https://lagniappe.example.test/messages?with="
    assert text_body.count(message_url) == 1
    assert html_body.count(message_url) == 1
    for title in (
        organize.name,
        ask.name,
        f"Autofill: {page.name}",
        f"Summarize: {file.name}",
    ):
        assert title in text_body
        assert title in html_body
    for redundant_copy in (
        "Organize report is ready.",
        "Ask report is ready.",
        "Page autofill is ready.",
        f"File summary complete for {file.name}",
    ):
        assert redundant_copy not in text_body
        assert redundant_copy not in html_body
    report_url = f"https://lagniappe.example.test/tools/reports/{organize.urlsafe_key}"
    assert report_url in text_body
    assert report_url in html_body


# @source lagniappe/core/tools/notification_email/capture.py::record_notification_event
# @source lagniappe/core/tools/notification_email/delivery.py::deliver
# @pairs notification-email:digest notification-email:timezone notification-email:full-roundup
# @pair notification-email:future-only-switch
# @pair notification-email:item-cap
def test_daily_digest_uses_next_local_eight_and_batches(monkeypatch):
    now = datetime(2026, 8, 15, 14, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(email_database.DATA, "_datastore_client", store)
    tasks = task_recorder(monkeypatch)
    recipient = user_row("recipient", now, mode="DAILY")
    recipient.db["timezone"] = "America/Los_Angeles"

    first = email_capture.record_notification_event(
        recipient,
        store.key(KINDS.activity.value, "first", parent=recipient.key),
        body="First event",
        now=now,
    )
    recipient.notification_email_mode = "IMMEDIATE"
    replay = email_capture.record_notification_event(
        recipient,
        store.key(KINDS.activity.value, "first", parent=recipient.key),
        body="First event",
        now=now + timedelta(seconds=30),
    )
    assert replay.key == first.key
    assert tasks[-1]["payload"] == tasks[0]["payload"]

    recipient.notification_email_mode = "DAILY"
    second = email_capture.record_notification_event(
        recipient,
        store.key(KINDS.activity.value, "second", parent=recipient.key),
        body="Second event",
        now=now + timedelta(minutes=1),
    )

    assert first["bucket"] == second["bucket"]
    assert first["due_at"] == datetime(2026, 8, 15, 15, tzinfo=timezone.utc)
    batch_key = Key.from_legacy_urlsafe(tasks[0]["payload"]["delivery_key"])
    batch = store.get(batch_key)
    digest_rows = [store.get(first.key), store.get(second.key)]
    for index in range(99):
        row = DatastoreEntity(
            key=store.key(
                KINDS.email_deliveries.value,
                f"extra-{index}",
            )
        )
        row.update(dict(first))
        row.update(
            {
                "body": f"Extra event {index}",
                "source_key": store.key(
                    KINDS.activity.value,
                    f"extra-source-{index}",
                    parent=recipient.key,
                )
                .to_legacy_urlsafe()
                .decode(),
            }
        )
        store.put(row)
        digest_rows.append(row)
    monkeypatch.setattr(
        email_database,
        "digest_events",
        lambda _batch: digest_rows,
    )
    monkeypatch.setattr(
        email_delivery.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    sent = []
    monkeypatch.setattr(
        email_presentation.auth_email,
        "send_email",
        lambda *args, **kwargs: sent.append(args) or True,
    )

    result = email_delivery.deliver(
        batch.key.to_legacy_urlsafe().decode(),
        now=batch["due_at"],
    )

    assert result == {"state": "sent", "items": 100}
    assert sent[0][1].endswith("daily digest")
    assert not sent[0][2].startswith(sent[0][1])
    assert "<h1" not in sent[0][3]
    assert "First event" in sent[0][2]
    assert "Second event" in sent[0][2]
    assert "1 more item is available" in sent[0][2]

