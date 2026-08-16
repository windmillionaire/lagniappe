"""Focused contracts for event-driven notification email delivery."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key
import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.tools import notification_email
from lagniappe.core.tools.database.core import KINDS


pytestmark = pytest.mark.unit


class MemoryDatastore:
    def __init__(self):
        self.rows = {}

    def key(self, kind, identifier=None, parent=None):
        return Key(kind, identifier, parent=parent, project="notification-email-test")

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, key, transaction=None):
        return self.rows.get(key)

    def put(self, row):
        self.rows[row.key] = row

    def put_multi(self, rows):
        for row in rows:
            self.put(row)


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *, ex=None):
        self.values[key] = str(value).encode("utf-8")
        self.expirations[key] = ex
        return True


def user_row(identifier, now, *, mode="IMMEDIATE", public=False, logged_in=True):
    key = Key(
        KINDS.users.value,
        identifier,
        project="notification-email-test",
    )
    row = DatastoreEntity(key=key)
    row.update(
        {
            "type": "user",
            "kind": "user",
            "name": identifier.title(),
            "email": f"{identifier}@example.test",
            "last_login": now if logged_in else None,
            "public": public,
            "active": True,
            "notification_email_mode": mode,
        }
    )
    return Entities.USER(row)


def task_recorder(monkeypatch):
    tasks = []

    def create_task(endpoint, payload, delay_seconds=0, *, task_id=None, **_kwargs):
        tasks.append(
            {
                "endpoint": endpoint,
                "payload": payload,
                "delay": delay_seconds,
                "task_id": task_id,
            }
        )
        return task_id

    monkeypatch.setattr(notification_email.task_queue, "create_task", create_task)
    return tasks


# @source lagniappe/core/properties/user_entity.py::NotificationEmailPreference.value
# @source lagniappe/core/tools/notification_email.py::eligible_user
# @pairs notification-email:preference notification-email:eligibility
# @pairs notification-email:public-user notification-email:never-logged-in
def test_notification_email_preference_defaults_and_eligibility():
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    user = user_row("managed", now)
    user.db.pop("notification_email_mode")

    assert user.notification_email_mode == "DAILY"
    assert notification_email.eligible_user(user)

    user.notification_email_mode = "NONE"
    assert user.notification_email_mode == "NONE"
    assert user.db["notification_email_opt_out_epoch"] == 1
    assert not notification_email.eligible_user(user)

    public = user_row("public", now, public=True, mode="DAILY")
    never_logged_in = user_row("new", now, logged_in=False, mode="DAILY")
    assert public.notification_email_mode == "NONE"
    assert not notification_email.eligible_user(public)
    assert not notification_email.eligible_user(never_logged_in)

    with pytest.raises(ValueError, match="NONE, IMMEDIATE, or DAILY"):
        user.notification_email_mode = "weekly"


# @source lagniappe/core/tools/notification_email.py::record_site_activity
# @source lagniappe/core/tools/notification_email.py::recently_active
# @pairs notification-email:presence notification-email:coarse-request-activity
def test_site_activity_is_coarse_and_expires(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    cache = MemoryRedis()
    monkeypatch.setattr(notification_email.redis_cache, "_redis", cache)
    recipient = user_row("recipient", now)

    assert notification_email.record_site_activity(recipient, now=now)
    assert cache.expirations[next(iter(cache.expirations))] == 10 * 60
    assert notification_email.recently_active(recipient, now=now)

    assert not notification_email.record_site_activity(
        recipient,
        now=now + timedelta(seconds=30),
    )
    assert notification_email.record_site_activity(
        recipient,
        now=now + timedelta(seconds=61),
    )
    assert not notification_email.recently_active(
        recipient,
        now=now + timedelta(minutes=11, seconds=2),
    )


# @source lagniappe/core/tools/notification_email.py::record_notification_event
# @source lagniappe/core/tools/notification_email.py::deliver
# @pairs notification-email:immediate notification-email:html notification-email:idempotency
# @pair notification-email:presence-suppression
# @pairs notification-email:notification notification-email:pending-filter
def test_immediate_notification_is_delayed_escaped_and_delivered(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(notification_email.DATA, "_datastore_client", store)
    tasks = task_recorder(monkeypatch)
    recipient = user_row("recipient", now)
    source_key = store.key(KINDS.activity.value, "notice", parent=recipient.key)
    source = DatastoreEntity(key=source_key)
    source.update({"type": "notification", "notification_type": "ordinary"})
    store.put(source)

    assert (
        notification_email.record_notification(
            SimpleNamespace(notification_type="aggregate", pending=False),
            now=now,
        )
        is None
    )
    assert (
        notification_email.record_notification(
            SimpleNamespace(notification_type="ordinary", pending=True),
            now=now,
        )
        is None
    )

    delivery = notification_email.record_notification(
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

    replay = notification_email.record_notification_event(
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
        notification_email.Entities,
        "fetch_one",
        fetch_unloaded_target,
    )
    unloaded_delivery = notification_email.record_notification(
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
        notification_email.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    monkeypatch.setattr(
        notification_email, "recently_active", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(
        notification_email.auth_email,
        "send_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or True,
    )

    result = notification_email.deliver(
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
    active_delivery = notification_email.record_notification_event(
        recipient,
        active_source_key,
        body="Visible on site",
        now=now + timedelta(minutes=10),
    )
    monkeypatch.setattr(
        notification_email,
        "recently_active",
        lambda *_args, **_kwargs: True,
    )

    assert notification_email.deliver(
        active_delivery.key.to_legacy_urlsafe().decode(),
        now=now + timedelta(minutes=15),
    ) == {"state": "suppressed"}
    assert len(sent) == 1


# @source lagniappe/core/tools/notification_email.py::record_document_mention
# @source lagniappe/core/tools/notification_email.py::deliver
# @pair notification-email:document-mention
def test_document_mention_email_uses_concise_copy_and_document_tab(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(notification_email.DATA, "_datastore_client", store)
    task_recorder(monkeypatch)
    monkeypatch.setattr(notification_email.CONFIG, "APP_NAME", "Test Lagniappe")
    monkeypatch.setattr(
        notification_email.CONFIG,
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

    delivery = notification_email.record_document_mention(
        recipient,
        source_key,
        document=document,
        now=now,
    )

    assert delivery["body"] == "You were mentioned in the Roadmap & Launch document."
    assert delivery["target_path"] == "/pages/roadmap?tab=document"

    sent = []
    monkeypatch.setattr(
        notification_email.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    monkeypatch.setattr(
        notification_email,
        "recently_active",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        notification_email.auth_email,
        "send_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or True,
    )

    result = notification_email.deliver(
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


# @source lagniappe/core/tools/notification_email.py::record_notification
# @source lagniappe/core/tools/notification_email.py::deliver
# @pair notification-email:task-assignment
def test_task_assignment_email_uses_task_copy_without_headers(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(notification_email.DATA, "_datastore_client", store)
    task_recorder(monkeypatch)
    monkeypatch.setattr(notification_email.CONFIG, "APP_NAME", "Test Lagniappe")
    monkeypatch.setattr(
        notification_email.CONFIG,
        "GOOGLE_LOGIN_URI",
        "https://lagniappe.example.test/login",
    )
    monkeypatch.setattr(
        notification_email,
        "_target_path",
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
            "event_type": notification_email.TASK_ASSIGNMENT_EVENT,
            "sender_name": "Alice & Bob",
        },
        properties=SimpleNamespace(
            target=SimpleNamespace(is_set=True, value=task),
        ),
        notification_type="ordinary",
        pending=False,
    )

    delivery = notification_email.record_notification(notification, now=now)

    assert delivery["event_type"] == notification_email.TASK_ASSIGNMENT_EVENT
    assert delivery["sender_name"] == "Alice & Bob"
    assert delivery["task_name"] == "Review <Launch>"
    assert delivery["target_path"] == "/tasks/assigned-task"

    sent = []
    monkeypatch.setattr(
        notification_email.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    monkeypatch.setattr(
        notification_email,
        "recently_active",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        notification_email.auth_email,
        "send_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or True,
    )

    result = notification_email.deliver(
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


# @source lagniappe/core/tools/notification_email.py::record_message
# @source lagniappe/core/tools/notification_email.py::deliver
# @pairs notification-email:message notification-email:quiet-window notification-email:latest-only
# @pair notification-email:read-suppression
def test_immediate_messages_wait_for_conversation_quiet(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(notification_email.DATA, "_datastore_client", store)
    monkeypatch.setattr(notification_email.CONFIG, "APP_NAME", "Test Lagniappe")
    tasks = task_recorder(monkeypatch)
    recipient = user_row("recipient", now)
    sender = user_row("sender", now)
    recipient_id = recipient.urlsafe_key
    conversation_key = store.key(KINDS.message_conversations.value, "conversation")
    conversation = DatastoreEntity(key=conversation_key)

    def incoming(sequence, created, body):
        conversation.update(
            {
                "sequence": sequence,
                "last_sender": sender.key,
                "read_through": {recipient_id: 0},
                "cleared_through": {recipient_id: 0},
            }
        )
        store.put(conversation)
        key = store.key(
            KINDS.messages.value, f"message-{sequence}", parent=conversation_key
        )
        message = DatastoreEntity(key=key)
        message.update(
            {
                "sequence": sequence,
                "sender": sender.key,
                "recipient": recipient.key,
                "sender_name": "Sender",
                "body": body,
                "hidden_for": [],
                "created": created,
            }
        )
        store.put(message)
        return message

    first = incoming(1, now, "first")
    candidate = notification_email.record_message(first, conversation, recipient)
    second_time = now + timedelta(minutes=2)
    second = incoming(2, second_time, "latest")
    notification_email.record_message(second, conversation, recipient)

    assert len(tasks) == 1
    assert notification_email.deliver(
        candidate.key.to_legacy_urlsafe().decode(),
        now=now + timedelta(minutes=5),
    ) == {"state": "rescheduled"}
    assert len(tasks) == 2

    sent = []
    monkeypatch.setattr(
        notification_email.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    monkeypatch.setattr(
        notification_email, "recently_active", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(
        notification_email.auth_email,
        "send_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or True,
    )

    result = notification_email.deliver(
        candidate.key.to_legacy_urlsafe().decode(),
        now=second_time + timedelta(minutes=5),
    )

    assert result == {"state": "sent"}
    assert sent[0][0][1] == "New messages on Test Lagniappe"
    assert "latest" in sent[0][0][2]
    assert "first" not in sent[0][0][2]

    third_time = second_time + timedelta(minutes=10)
    third = incoming(3, third_time, "already read")
    candidate = notification_email.record_message(third, conversation, recipient)
    conversation["read_through"] = {recipient_id: 3}
    store.put(conversation)

    assert notification_email.deliver(
        candidate.key.to_legacy_urlsafe().decode(),
        now=third_time + timedelta(minutes=5),
    ) == {"state": "suppressed"}
    assert len(sent) == 1

    fourth_time = third_time + timedelta(minutes=10)
    fourth = incoming(4, fourth_time, "later message")
    conversation["read_through"] = {recipient_id: 3}
    store.put(conversation)
    candidate = notification_email.record_message(fourth, conversation, recipient)

    assert notification_email.deliver(
        candidate.key.to_legacy_urlsafe().decode(),
        now=fourth_time + timedelta(minutes=5),
    ) == {"state": "sent"}
    assert "later message" in sent[1][0][2]
    assert sent[0][1]["message_id"] != sent[1][1]["message_id"]


# @source lagniappe/core/tools/notification_email.py::_digest_events
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

    monkeypatch.setattr(notification_email, "Filter", RecordingFilter)
    monkeypatch.setattr(notification_email, "Query", RecordingQuery)
    batch = {"recipient": "recipient-key", "bucket": "20260816T150000Z"}

    assert notification_email._digest_events(batch) == ["digest-event"]
    assert captured == {
        "kind": KINDS.email_deliveries,
        "filters": [
            [
                ("recipient", "recipient-key"),
                ("record_type", "event"),
                ("mode", notification_email.NotificationEmailMode.DAILY.name),
                ("bucket", "20260816T150000Z"),
                ("state", "pending"),
            ]
        ],
        "order": ("created",),
    }


# @source lagniappe/core/tools/notification_email.py::record_notification_event
# @source lagniappe/core/tools/notification_email.py::deliver
# @pairs notification-email:digest notification-email:timezone notification-email:full-roundup
# @pair notification-email:future-only-switch
# @pair notification-email:item-cap
def test_daily_digest_uses_next_local_eight_and_batches(monkeypatch):
    now = datetime(2026, 8, 15, 14, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(notification_email.DATA, "_datastore_client", store)
    tasks = task_recorder(monkeypatch)
    recipient = user_row("recipient", now, mode="DAILY")
    recipient.db["timezone"] = "America/Los_Angeles"

    first = notification_email.record_notification_event(
        recipient,
        store.key(KINDS.activity.value, "first", parent=recipient.key),
        body="First event",
        now=now,
    )
    recipient.notification_email_mode = "IMMEDIATE"
    replay = notification_email.record_notification_event(
        recipient,
        store.key(KINDS.activity.value, "first", parent=recipient.key),
        body="First event",
        now=now + timedelta(seconds=30),
    )
    assert replay.key == first.key
    assert tasks[-1]["payload"] == tasks[0]["payload"]

    recipient.notification_email_mode = "DAILY"
    second = notification_email.record_notification_event(
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
        notification_email,
        "_digest_events",
        lambda _batch: digest_rows,
    )
    monkeypatch.setattr(
        notification_email.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: recipient,
    )
    sent = []
    monkeypatch.setattr(
        notification_email.auth_email,
        "send_email",
        lambda *args, **kwargs: sent.append(args) or True,
    )

    result = notification_email.deliver(
        batch.key.to_legacy_urlsafe().decode(),
        now=batch["due_at"],
    )

    assert result == {"state": "sent", "items": 100}
    assert sent[0][1].endswith("daily digest")
    assert "First event" in sent[0][2]
    assert "Second event" in sent[0][2]
    assert "1 more item is available" in sent[0][2]
