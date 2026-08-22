"""Capture committed notifications, mentions, and messages for email."""

from datetime import timedelta
from urllib.parse import quote

from ....definitions import Fetch, NotificationEmailMode
from ....entities import Entities
from ...database import notification_email as email_database
from . import dispatch, links, policy


DOCUMENT_MENTION_EVENT = "document_mention"
TASK_ASSIGNMENT_EVENT = "task_assignment"


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason shared serialization is exercised through typed capture APIs
def _event_values(*, source_type, source_key, body, title, target_path, now):
    return {
        "source_type": source_type,
        "source_key": email_database.encoded_key(source_key),
        "body": str(body or "").strip(),
        "title": str(title or "Notification").strip(),
        "target_path": str(target_path or "/"),
        "occurred_at": now,
    }


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification
# @reason target-specific copy is exercised through notification capture
def _notification_copy(target, body):
    title = "Notification"
    body = str(body or "").strip()
    target_name = str(getattr(target, "name", None) or "").strip()

    if isinstance(target, Entities.REPORT) and target.tool in {"ask", "organize"}:
        label = target.tool.title()
        title = target_name or f"{label} report"
        if body in {
            f"{label} report is ready.",
            f"{label} report revision is ready.",
        }:
            body = ""
    elif isinstance(target, (Entities.PAGE, Entities.TASK)):
        label = "Task" if isinstance(target, Entities.TASK) else "Page"
        completed = f"{label} autofill is ready."
        if body == completed or body.startswith("Autofill failed."):
            title = f"Autofill: {target_name or label}"
            if body == completed:
                body = ""
    elif isinstance(target, Entities.FILE):
        name = target_name or "file"
        completed = f"File summary complete for {name}"
        if body == completed or body.startswith("File summary failed"):
            title = f"Summarize: {name}"
            if body == completed:
                body = ""

    return title, body


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason shared persistence and dispatch are exercised through typed capture APIs
def _record_event(user, values, *, now=None):
    now = policy.utc(now)
    if not policy.eligible_user(user):
        return None
    mode = policy.mode(user)
    key = email_database.delivery_key(
        "event",
        email_database.encoded_key(user),
        values["source_type"],
        values["source_key"],
    )
    due_at = (
        now + timedelta(seconds=policy.IMMEDIATE_DELAY_SECONDS)
        if mode is NotificationEmailMode.IMMEDIATE
        else policy.next_digest(user, now)
    )
    row = email_database.new_delivery(
        key,
        user,
        record_type="event",
        mode=mode,
        due_at=due_at,
        preference_epoch=policy.preference_epoch(user),
        now=now,
    )
    row.update(values)
    if mode is NotificationEmailMode.DAILY:
        row["bucket"] = due_at.strftime("%Y%m%dT%H%M%SZ")
    row, created = email_database.put_if_absent(row)
    if created or row.get("state") == "pending":
        stored_mode = NotificationEmailMode.__members__.get(row.get("mode"))
        if stored_mode is NotificationEmailMode.DAILY:
            batch = email_database.digest_batch(
                user,
                row["due_at"],
                now,
                preference_epoch=policy.preference_epoch(user),
            )
            dispatch.schedule(batch, now=now)
        else:
            dispatch.schedule(row, now=now)
    return row


# @testable true
# @tests tests_unit/test_029b_notification_email_events.py::test_immediate_notification_is_delayed_escaped_and_delivered
# @tests tests_unit/test_029b_notification_email_events.py::test_task_assignment_email_uses_task_copy_without_headers
# @tests tests_unit/test_029d_notification_email_digest.py::test_daily_digest_groups_messages_and_uses_named_completion_links
# @pairs notification-email:notification notification-email:pending-filter
# @pair notification-email:task-assignment
# @pairs notification-email:target-title notification-email:target-link
def record_notification(notification, *, now=None):
    """Capture one final ordinary notification for email delivery."""
    if (
        notification is None
        or getattr(notification, "notification_type", "ordinary") != "ordinary"
        or getattr(notification, "pending", False)
    ):
        return None
    target_property = getattr(getattr(notification, "properties", None), "target", None)
    if target_property is None:
        target = getattr(notification, "target", None)
    elif getattr(target_property, "is_set", False):
        target = target_property.value
    else:
        target_key = getattr(target_property, "key", None)
        target = (
            Entities.fetch_one(target_key, request=Fetch.direct())
            if target_key is not None
            else None
        )
    now = policy.utc(now)
    if (
        getattr(notification, "db", {}).get("event_type") == TASK_ASSIGNMENT_EVENT
        and isinstance(target, Entities.TASK)
    ):
        sender_name = str(notification.db.get("sender_name") or "A user").strip()
        task_name = str(getattr(target, "name", None) or "task").strip()
        values = _event_values(
            source_type="notification",
            source_key=notification,
            body=f"{sender_name} assigned you the task {task_name}.",
            title="Task assigned",
            target_path=links.target_path(target),
            now=now,
        )
        values.update(
            {
                "event_type": TASK_ASSIGNMENT_EVENT,
                "sender_name": sender_name,
                "task_name": task_name,
            }
        )
        return _record_event(getattr(notification, "parent", None), values, now=now)

    title, body = _notification_copy(target, getattr(notification, "body", ""))
    values = _event_values(
        source_type="notification",
        source_key=notification,
        body=body,
        title=title,
        target_path=links.target_path(target),
        now=now,
    )
    return _record_event(getattr(notification, "parent", None), values, now=now)


# @testable true
# @tests tests_unit/test_029b_notification_email_events.py::test_immediate_notification_is_delayed_escaped_and_delivered
# @tests tests_unit/test_029d_notification_email_digest.py::test_daily_digest_uses_next_local_eight_and_batches
# @tests tests_unit/test_029d_notification_email_digest.py::test_daily_digest_groups_messages_and_uses_named_completion_links
# @pairs notification-email:immediate notification-email:digest notification-email:idempotency
# @pairs notification-email:timezone notification-email:full-roundup
# @pair notification-email:future-only-switch
def record_notification_event(user, source_key, *, body, target=None, now=None):
    """Capture a known final notification at a direct transaction boundary."""
    now = policy.utc(now)
    values = _event_values(
        source_type="notification",
        source_key=source_key,
        body=body,
        title="Notification",
        target_path=links.target_path(target),
        now=now,
    )
    return _record_event(user, values, now=now)


# @testable true
# @tests tests_unit/test_029b_notification_email_events.py::test_document_mention_email_uses_concise_copy_and_document_tab
# @pair notification-email:document-mention
def record_document_mention(user, source_key, *, document, now=None):
    """Capture a document mention with its dedicated email presentation."""
    now = policy.utc(now)
    document_name = str(getattr(document, "name", None) or "document").strip()
    values = _event_values(
        source_type="notification",
        source_key=source_key,
        body=f"You were mentioned in the {document_name} document.",
        title="Document mention",
        target_path=f"{links.target_path(document)}?tab=document",
        now=now,
    )
    values.update(
        {"event_type": DOCUMENT_MENTION_EVENT, "document_name": document_name}
    )
    return _record_event(user, values, now=now)


# @testable true
# @tests tests_unit/test_029c_notification_email_messages.py::test_immediate_messages_wait_for_conversation_quiet
# @tests tests_unit/test_029d_notification_email_digest.py::test_daily_digest_groups_messages_and_uses_named_completion_links
# @pairs notification-email:message notification-email:quiet-window notification-email:latest-only
def record_message(message, conversation, recipient, *, now=None):
    """Capture a newly-created inbound direct message."""
    now = policy.utc(now or message.get("created"))
    if not policy.eligible_user(recipient):
        return None
    conversation_id = email_database.encoded_key(conversation.key)
    values = _event_values(
        source_type="message",
        source_key=message.key,
        body=message.get("body"),
        title=f"Message from {message.get('sender_name') or 'a user'}",
        target_path=f"/messages?with={quote(conversation_id, safe='')}",
        now=now,
    )
    values.update(
        {
            "conversation": conversation.key,
            "message": message.key,
            "message_sequence": int(message.get("sequence") or 0),
            "sender": message.get("sender"),
            "sender_name": message.get("sender_name") or "a user",
        }
    )
    if policy.mode(recipient) is NotificationEmailMode.DAILY:
        return _record_event(recipient, values, now=now)

    key = email_database.delivery_key(
        "message-candidate", email_database.encoded_key(recipient), conversation_id
    )
    due_at = now + timedelta(seconds=policy.IMMEDIATE_DELAY_SECONDS)
    row, schedule = email_database.upsert_message_candidate(
        key,
        recipient,
        values,
        due_at=due_at,
        preference_epoch=policy.preference_epoch(recipient),
        now=now,
    )
    if schedule:
        task_name = dispatch.schedule(
            row, task_suffix=row["message_sequence"], now=now
        )
        email_database.mark_message_scheduled(
            row, row["message_sequence"], task_name, now
        )
    return row
