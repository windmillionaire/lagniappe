"""Direct-message notification-email quiet-window contracts."""

from datetime import datetime, timedelta, timezone

from google.cloud.datastore import Entity as DatastoreEntity
import pytest

from lagniappe.core.tools.database import notification_email as email_database
from lagniappe.core.tools.database.core import KINDS
from lagniappe.core.tools.email.notifications import capture as email_capture
from lagniappe.core.tools.email.notifications import delivery as email_delivery
from lagniappe.core.tools.email.notifications import presentation as email_presentation
from testing.utility.notification_email_fakes import (
    MemoryDatastore,
    task_recorder,
    user_row,
)


pytestmark = pytest.mark.unit


# @matrix notification-email : latest-only message quiet-window read-suppression
def test_immediate_messages_wait_for_conversation_quiet(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    store = MemoryDatastore()
    monkeypatch.setattr(email_database.DATA, "_datastore_client", store)
    monkeypatch.setattr(email_presentation.CONFIG, "APP_NAME", "Test Lagniappe")
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
    candidate = email_capture.record_message(first, conversation, recipient)
    second_time = now + timedelta(minutes=2)
    second = incoming(2, second_time, "latest")
    email_capture.record_message(second, conversation, recipient)

    assert len(tasks) == 1
    assert email_delivery.deliver(
        candidate.key.to_legacy_urlsafe().decode(),
        now=now + timedelta(minutes=5),
    ) == {"state": "rescheduled"}
    assert len(tasks) == 2

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
        candidate.key.to_legacy_urlsafe().decode(),
        now=second_time + timedelta(minutes=5),
    )

    assert result == {"state": "sent"}
    assert sent[0][0][1] == "New messages on Test Lagniappe"
    assert "latest" in sent[0][0][2]
    assert "first" not in sent[0][0][2]

    third_time = second_time + timedelta(minutes=10)
    third = incoming(3, third_time, "already read")
    candidate = email_capture.record_message(third, conversation, recipient)
    conversation["read_through"] = {recipient_id: 3}
    store.put(conversation)

    assert email_delivery.deliver(
        candidate.key.to_legacy_urlsafe().decode(),
        now=third_time + timedelta(minutes=5),
    ) == {"state": "suppressed"}
    assert len(sent) == 1

    fourth_time = third_time + timedelta(minutes=10)
    fourth = incoming(4, fourth_time, "later message")
    conversation["read_through"] = {recipient_id: 3}
    store.put(conversation)
    candidate = email_capture.record_message(fourth, conversation, recipient)

    assert email_delivery.deliver(
        candidate.key.to_legacy_urlsafe().decode(),
        now=fourth_time + timedelta(minutes=5),
    ) == {"state": "sent"}
    assert "later message" in sent[1][0][2]
    assert sent[0][1]["message_id"] != sent[1][1]["message_id"]
