"""Datastore records and transactions for notification-email delivery."""

from datetime import datetime, timedelta
from hashlib import sha256
import uuid

from google.cloud.datastore import Entity as DatastoreEntity

from ...definitions import NotificationEmailMode
from ...properties import notification_email as delivery_values
from ..email.notifications.errors import NotificationEmailError
from .core import DATA, KINDS
from .filter import Filter, Query
from .get import datastore_key, urlsafe_key
from .utility import create_named_key


DELIVERY_EXCLUDED_FIELDS = (
    "body",
    "title",
    "target_path",
    "source_key",
    "sender_name",
    "lease_token",
)


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason key normalization is exercised through public capture APIs
def encoded_key(value):
    return urlsafe_key(getattr(value, "key", value))


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason deterministic identities are exercised through idempotent capture
def delivery_key(*parts):
    identity = sha256("\0".join(str(part) for part in parts).encode()).hexdigest()
    return create_named_key("email_delivery", identity)


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason delivery construction is exercised through public capture APIs
def new_delivery(
    key,
    user,
    *,
    record_type,
    mode,
    due_at,
    preference_epoch,
    now,
):
    row = DatastoreEntity(key=key, exclude_from_indexes=DELIVERY_EXCLUDED_FIELDS)
    row.update(
        delivery_values.initial_values(
            user,
            record_type=record_type,
            mode=mode,
            due_at=due_at,
            preference_epoch=preference_epoch,
            now=now,
        )
    )
    return row


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason transactional idempotency is exercised through event replay
def put_if_absent(row):
    with DATA.datastore.transaction() as transaction:
        existing = DATA.datastore.get(row.key, transaction=transaction)
        if existing is not None:
            return existing, False
        transaction.put(row)
    return row, True


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason daily batch creation is exercised through digest capture
def digest_batch(user, due_at, now, *, preference_epoch):
    bucket = due_at.strftime("%Y%m%dT%H%M%SZ")
    key = delivery_key("digest-batch", encoded_key(user), bucket)
    row = new_delivery(
        key,
        user,
        record_type="digest-batch",
        mode=NotificationEmailMode.DAILY,
        due_at=due_at,
        preference_epoch=preference_epoch,
        now=now,
    )
    row["bucket"] = bucket
    return put_if_absent(row)[0]


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_message
# @reason quiet-window replacement is exercised through message capture
def upsert_message_candidate(
    key,
    recipient,
    values,
    *,
    due_at,
    preference_epoch,
    now,
):
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(key, transaction=transaction)
        schedule = bool(
            row is None
            or row.get("state") != "pending"
            or not row.get("scheduled_sequence")
        )
        if row is None:
            row = new_delivery(
                key,
                recipient,
                record_type="message-candidate",
                mode=NotificationEmailMode.IMMEDIATE,
                due_at=due_at,
                preference_epoch=preference_epoch,
                now=now,
            )
        row.update(values)
        row.update(
            {
                "due_at": due_at,
                "state": "pending",
                "preference_epoch": preference_epoch,
                "modified": now,
            }
        )
        transaction.put(row)
    return row, schedule


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_message
# @reason scheduled-sequence compare-and-set is exercised through message capture
def mark_message_scheduled(row, sequence, task_name, now):
    if not task_name:
        return False
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(row.key, transaction=transaction)
        if current is None or int(current.get("message_sequence") or 0) != int(
            sequence
        ):
            return False
        current["scheduled_sequence"] = int(sequence)
        current["modified"] = now
        transaction.put(current)
    return True


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason direct lookup is exercised through queued delivery
def get_delivery(identifier):
    key = datastore_key(identifier)
    return DATA.datastore.get(key) if key else None


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason lease acquisition is exercised through queued delivery
def claim_delivery(row, now, *, lease_seconds):
    token = str(uuid.uuid4())
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(row.key, transaction=transaction)
        if current is None or current.get("state") in {"sent", "suppressed"}:
            return None
        expires = current.get("lease_expires")
        if (
            current.get("state") == "sending"
            and isinstance(expires, datetime)
            and expires > now
        ):
            raise NotificationEmailError("Notification email delivery is active.")
        current.update(
            {
                "state": "sending",
                "lease_token": token,
                "lease_expires": now + timedelta(seconds=lease_seconds),
                "modified": now,
            }
        )
        transaction.put(current)
    return current, token


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason terminal compaction is exercised through queued delivery
def finish_delivery(row, token, state, now, *, expected_sequence=None):
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(row.key, transaction=transaction)
        if current is None or current.get("lease_token") != token:
            return False
        if expected_sequence is not None and int(
            current.get("message_sequence") or 0
        ) != int(expected_sequence):
            return False
        compacted = DatastoreEntity(key=current.key)
        compacted.update(delivery_values.terminal_values(current, state, now))
        transaction.put(compacted)
    return True


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason retry release is exercised through queued delivery failures
def release_delivery(row, token, now):
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(row.key, transaction=transaction)
        if current is None or current.get("lease_token") != token:
            return False
        current["state"] = "pending"
        current["modified"] = now
        current.pop("lease_token", None)
        current.pop("lease_expires", None)
        transaction.put(current)
    return True


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason send-time conversation suppression is exercised through delivery
def message_is_actionable(row, user):
    conversation = DATA.datastore.get(row.get("conversation"))
    message = DATA.datastore.get(row.get("message"))
    if conversation is None or message is None:
        return False
    sequence = int(row.get("message_sequence") or 0)
    user_id = encoded_key(user)
    return bool(
        int(conversation.get("sequence") or 0) == sequence
        and conversation.get("last_sender") != user.key
        and int((conversation.get("read_through") or {}).get(user_id) or 0) < sequence
        and int((conversation.get("cleared_through") or {}).get(user_id) or 0)
        < sequence
        and user.key not in set(message.get("hidden_for") or ())
    )


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason send-time notification suppression is exercised through delivery
def event_is_actionable(row):
    if row.get("source_type") != "notification":
        return True
    key = datastore_key(row.get("source_key"))
    return bool(key and DATA.datastore.get(key) is not None)


# @testable true
# @tests tests_unit/test_029d_notification_email_digest.py::test_daily_digest_query_retains_recipient_and_bucket_scope
# @matrix notification-email : digest-query recipient-scope
def digest_events(batch):
    return list(
        Query(KINDS.email_deliveries)
        .filter(
            Filter()
            .eq("recipient", batch.get("recipient"))
            .eq("record_type", "event")
            .eq("mode", NotificationEmailMode.DAILY.name)
            .eq("bucket", batch.get("bucket"))
            .eq("state", "pending")
        )
        .order("created")
        .fetch_all()
    )


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason digest tombstone compaction is exercised through delivery
def compact_events(rows, state, now):
    compacted = []
    for row in rows:
        item = DatastoreEntity(key=row.key)
        item.update(delivery_values.terminal_values(row, state, now))
        compacted.append(item)
    if compacted:
        DATA.datastore.put_multi(compacted)
