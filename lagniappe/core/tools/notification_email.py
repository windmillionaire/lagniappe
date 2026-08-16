"""Event-driven notification email capture, scheduling, and delivery."""

from datetime import datetime, time as datetime_time, timedelta, timezone
from hashlib import sha256
from html import escape
from math import ceil
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

from google.cloud.datastore import Entity as DatastoreEntity

from lagniappe import CONFIG

from ..definitions import Fetch, NotificationEmailMode
from ..entities import Entities
from ..exceptions import capture
from . import auth_email, database, task_queue
from .cache.core import cache as redis_cache
from .database.core import DATA, KINDS
from .database.filter import Filter, Query
from .dates import user_timezone


IMMEDIATE_DELAY_SECONDS = 5 * 60
SITE_ACTIVITY_SECONDS = 10 * 60
SITE_ACTIVITY_WRITE_SECONDS = 60
DELIVERY_LEASE_SECONDS = 5 * 60
DIGEST_HOUR = 8
DIGEST_ITEM_LIMIT = 100
DELIVERY_SCHEMA_VERSION = 1


class NotificationEmailError(RuntimeError):
    """Raised when a queued notification email cannot be completed yet."""


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason shared clock normalization is exercised through event capture and delivery
def _utc(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @covered-by lagniappe/core/tools/notification_email.py::record_message
# @reason key normalization is exercised through the public capture APIs
def _encoded_key(value):
    key = getattr(value, "key", value)
    return database.get.urlsafe_key(key)


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason deterministic identities are internal to captured delivery records
def _identity(*parts):
    return sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason deterministic delivery keys are internal to captured delivery records
def _delivery_key(*parts):
    return database.create_named_key("email_delivery", _identity(*parts))


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason canonical application links are exercised through rendered delivery
def _origin():
    configured = (
        str(getattr(CONFIG, "GOOGLE_LOGIN_URI", "") or "").strip()
        or str(getattr(CONFIG, "APP_URL", "") or "").strip()
        or str(getattr(CONFIG, "BASE_URL", "") or "").strip()
    )
    parsed = urlsplit(configured)
    if parsed.scheme and parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
    return configured.rstrip("/")


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason absolute application links are exercised through rendered delivery
def _absolute_url(path):
    path = str(path or "/").strip()
    if path.startswith(("https://", "http://")):
        return path
    return f"{_origin()}/{path.lstrip('/')}"


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason target resolution is exercised through notification event capture
def _target_path(target):
    if target is not None:
        try:
            path = target.url
        except (AttributeError, RuntimeError):
            path = None
        if path:
            return str(path)
    return "/"


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::eligible_user
# @reason preference normalization is owned by recipient eligibility
def _mode(user):
    try:
        return NotificationEmailMode[user.notification_email_mode]
    except (AttributeError, KeyError, TypeError):
        return NotificationEmailMode.NONE


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason opt-out generations are enforced by public delivery
def _epoch(user):
    return int(user.db.get("notification_email_opt_out_epoch") or 0)


# @testable true
# @tests tests_unit/test_029_notification_email.py::test_notification_email_preference_defaults_and_eligibility
# @pairs notification-email:eligibility notification-email:public-user notification-email:never-logged-in
def eligible_user(user):
    """Return whether a user may receive notification email."""
    return bool(
        isinstance(user, Entities.USER)
        and getattr(user, "active", True)
        and not user.is_public
        and user.last_login
        and str(user.email or "").strip()
        and _mode(user) is not NotificationEmailMode.NONE
    )


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_site_activity
# @reason Redis key construction is owned by coarse activity recording
def _activity_key(user_identifier):
    return f"{CONFIG.PREFIX}SITE_ACTIVITY:{_identity(_encoded_key(user_identifier))}"


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_site_activity
# @reason Redis wire normalization is exercised through coarse activity recording
def _timestamp(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return float(value)


# @testable true
# @tests tests_unit/test_029_notification_email.py::test_site_activity_is_coarse_and_expires
# @pairs notification-email:presence notification-email:coarse-request-activity
def record_site_activity(user_identifier, *, now=None):
    """Record coarse authenticated activity without creating browser traffic."""
    now = _utc(now)
    key = _activity_key(user_identifier)
    try:
        current = redis_cache.redis.get(key)
        if current:
            current = _timestamp(current)
            if now.timestamp() - current < SITE_ACTIVITY_WRITE_SECONDS:
                return False
        redis_cache.redis.set(key, str(now.timestamp()), ex=SITE_ACTIVITY_SECONDS)
        return True
    except Exception as error:
        capture(error, context={"operation": "notification-email-site-activity"})
        return False


# @testable true
# @tests tests_unit/test_029_notification_email.py::test_site_activity_is_coarse_and_expires
# @tests tests_unit/test_029_notification_email.py::test_immediate_notification_is_delayed_escaped_and_delivered
# @pairs notification-email:presence notification-email:presence-suppression
def recently_active(user_identifier, *, now=None):
    """Return a best-effort recent-activity hint; cache failure fails open."""
    now = _utc(now)
    try:
        value = redis_cache.redis.get(_activity_key(user_identifier))
        if not value:
            return False
        return now.timestamp() - _timestamp(value) <= SITE_ACTIVITY_SECONDS
    except Exception as error:
        capture(error, context={"operation": "notification-email-presence-check"})
        return False


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason local digest scheduling is exercised through public event capture
def _next_digest(user, now):
    zone = user_timezone(user)
    local_now = now.astimezone(zone)
    due = datetime.combine(
        local_now.date(), datetime_time(hour=DIGEST_HOUR), tzinfo=zone
    )
    if due <= local_now:
        due += timedelta(days=1)
    return due.astimezone(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @covered-by lagniappe/core/tools/notification_email.py::record_message
# @reason delivery row construction is exercised through the public capture APIs
def _new_delivery(key, user, *, record_type, mode, due_at, now):
    row = DatastoreEntity(
        key=key,
        exclude_from_indexes=(
            "body",
            "title",
            "target_path",
            "source_key",
            "sender_name",
            "lease_token",
        ),
    )
    row.update(
        {
            "type": "notification_email_delivery",
            "schema_version": DELIVERY_SCHEMA_VERSION,
            "record_type": record_type,
            "recipient": user.key,
            "mode": mode.name,
            "preference_epoch": _epoch(user),
            "due_at": due_at,
            "state": "pending",
            "created": now,
            "modified": now,
        }
    )
    return row


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason digest bucket identity is exercised through daily event capture
def _digest_bucket(due_at):
    return due_at.strftime("%Y%m%dT%H%M%SZ")


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason transactional idempotency is exercised through event replay
def _put_if_absent(row):
    with DATA.datastore.transaction() as transaction:
        existing = DATA.datastore.get(row.key, transaction=transaction)
        if existing is not None:
            return existing, False
        transaction.put(row)
    return row, True


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @reason digest batch creation is exercised through daily event capture
def _batch_for(user, due_at, now):
    bucket = _digest_bucket(due_at)
    key = _delivery_key("digest-batch", _encoded_key(user), bucket)
    row = _new_delivery(
        key,
        user,
        record_type="digest-batch",
        mode=NotificationEmailMode.DAILY,
        due_at=due_at,
        now=now,
    )
    row["bucket"] = bucket
    return _put_if_absent(row)[0]


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @covered-by lagniappe/core/tools/notification_email.py::record_message
# @reason one-off task dispatch is exercised through the public capture APIs
def _schedule(row, *, task_suffix=None, now=None):
    now = _utc(now)
    endpoint = f"{_origin()}/process/notification-email"
    encoded = _encoded_key(row.key)
    suffix = task_suffix or row.get("bucket") or row.get("source_key") or encoded
    task_id = f"notification-email-{_identity(encoded, suffix)[:32]}"
    delay = max(0, ceil((row["due_at"] - now).total_seconds()))
    try:
        return task_queue.create_task(
            endpoint,
            {"delivery_key": encoded},
            delay_seconds=delay,
            task_id=task_id,
        )
    except Exception as error:
        capture(
            error,
            context={
                "operation": "notification-email-enqueue",
                "delivery_key": encoded,
            },
        )
        return None


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_message
# @reason quiet-window sequencing is exercised through message capture
def _mark_message_scheduled(row, sequence, task_name, now):
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
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @covered-by lagniappe/core/tools/notification_email.py::record_message
# @reason event serialization is exercised through the public capture APIs
def _event_values(*, source_type, source_key, body, title, target_path, now):
    return {
        "source_type": source_type,
        "source_key": _encoded_key(source_key),
        "body": str(body or "").strip(),
        "title": str(title or "Notification").strip(),
        "target_path": str(target_path or "/"),
        "occurred_at": now,
    }


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::record_notification_event
# @covered-by lagniappe/core/tools/notification_email.py::record_message
# @reason shared event persistence is owned by the typed public capture APIs
def _record_event(user, values, *, now=None):
    now = _utc(now)
    if not eligible_user(user):
        return None
    mode = _mode(user)
    source_identity = values["source_key"]
    key = _delivery_key(
        "event",
        _encoded_key(user),
        values["source_type"],
        source_identity,
    )
    due_at = (
        now + timedelta(seconds=IMMEDIATE_DELAY_SECONDS)
        if mode is NotificationEmailMode.IMMEDIATE
        else _next_digest(user, now)
    )
    row = _new_delivery(
        key,
        user,
        record_type="event",
        mode=mode,
        due_at=due_at,
        now=now,
    )
    row.update(values)
    if mode is NotificationEmailMode.DAILY:
        row["bucket"] = _digest_bucket(due_at)
    row, created = _put_if_absent(row)
    if created or row.get("state") == "pending":
        stored_mode = NotificationEmailMode.__members__.get(row.get("mode"))
        if stored_mode is NotificationEmailMode.DAILY:
            _schedule(_batch_for(user, row["due_at"], now), now=now)
        else:
            _schedule(row, now=now)
    return row


# @testable true
# @tests tests_unit/test_029_notification_email.py::test_immediate_notification_is_delayed_escaped_and_delivered
# @pairs notification-email:notification notification-email:pending-filter
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
        # Mutation plans may carry a persisted notification without hydrating
        # its target. Email capture is supplementary and must not turn that
        # missing projection into an unloaded-relation failure.
        target_key = getattr(target_property, "key", None)
        target = (
            Entities.fetch_one(target_key, request=Fetch.direct())
            if target_key is not None
            else None
        )
    return record_notification_event(
        getattr(notification, "parent", None),
        notification,
        body=getattr(notification, "body", ""),
        target=target,
        now=now,
    )


# @testable true
# @tests tests_unit/test_029_notification_email.py::test_immediate_notification_is_delayed_escaped_and_delivered
# @tests tests_unit/test_029_notification_email.py::test_daily_digest_uses_next_local_eight_and_batches
# @pairs notification-email:immediate notification-email:digest notification-email:idempotency
# @pairs notification-email:timezone notification-email:full-roundup
# @pair notification-email:future-only-switch
def record_notification_event(user, source_key, *, body, target=None, now=None):
    """Capture a known final notification at a direct transaction boundary."""
    values = _event_values(
        source_type="notification",
        source_key=source_key,
        body=body,
        title="Notification",
        target_path=_target_path(target),
        now=_utc(now),
    )
    return _record_event(user, values, now=now)


# @testable true
# @tests tests_unit/test_029_notification_email.py::test_immediate_messages_wait_for_conversation_quiet
# @pairs notification-email:message notification-email:quiet-window notification-email:latest-only
def record_message(message, conversation, recipient, *, now=None):
    """Capture a newly-created inbound direct message."""
    now = _utc(now or message.get("created"))
    if not eligible_user(recipient):
        return None
    conversation_id = _encoded_key(conversation.key)
    target_path = f"/messages?with={quote(conversation_id, safe='')}"
    values = _event_values(
        source_type="message",
        source_key=message.key,
        body=message.get("body"),
        title=f"Message from {message.get('sender_name') or 'a user'}",
        target_path=target_path,
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
    if _mode(recipient) is NotificationEmailMode.DAILY:
        return _record_event(recipient, values, now=now)

    key = _delivery_key("message-candidate", _encoded_key(recipient), conversation_id)
    due_at = now + timedelta(seconds=IMMEDIATE_DELAY_SECONDS)
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(key, transaction=transaction)
        schedule = bool(
            row is None
            or row.get("state") != "pending"
            or not row.get("scheduled_sequence")
        )
        if row is None:
            row = _new_delivery(
                key,
                recipient,
                record_type="message-candidate",
                mode=NotificationEmailMode.IMMEDIATE,
                due_at=due_at,
                now=now,
            )
        row.update(values)
        row.update(
            {
                "due_at": due_at,
                "state": "pending",
                "preference_epoch": _epoch(recipient),
                "modified": now,
            }
        )
        transaction.put(row)
    if schedule:
        task_name = _schedule(row, task_suffix=row["message_sequence"], now=now)
        _mark_message_scheduled(
            row,
            row["message_sequence"],
            task_name,
            now,
        )
    return row


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason direct recipient loading is internal to queued delivery
def _load_user(row):
    user = Entities.fetch_one(row.get("recipient"), request=Fetch.direct())
    if not isinstance(user, Entities.USER):
        return None
    return user


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason lease acquisition is exercised through public delivery
def _claim(row, now):
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
                "lease_expires": now + timedelta(seconds=DELIVERY_LEASE_SECONDS),
                "modified": now,
            }
        )
        transaction.put(current)
    return current, token


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason terminal compaction is exercised through public delivery
def _finish(row, token, state, now, *, expected_sequence=None):
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(row.key, transaction=transaction)
        if current is None or current.get("lease_token") != token:
            return False
        if expected_sequence is not None and int(
            current.get("message_sequence") or 0
        ) != int(expected_sequence):
            return False
        created = current.get("created") or now
        compacted = DatastoreEntity(key=current.key)
        compacted.update(
            {
                "type": "notification_email_delivery",
                "schema_version": DELIVERY_SCHEMA_VERSION,
                "record_type": current.get("record_type"),
                "recipient": current.get("recipient"),
                "mode": current.get("mode"),
                "state": state,
                "created": created,
                "modified": now,
                "completed": now,
            }
        )
        if current.get("bucket"):
            compacted["bucket"] = current["bucket"]
        transaction.put(compacted)
    return True


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason retry release is internal to queued delivery
def _release(row, token, now):
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
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason send-time opt-out enforcement is exercised through public delivery
def _valid_for_user(row, user):
    return bool(
        eligible_user(user)
        and int(row.get("preference_epoch") or 0) == _epoch(user)
    )


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason conversation suppression checks are exercised through public delivery
def _message_still_actionable(row, user):
    conversation = DATA.datastore.get(row.get("conversation"))
    message = DATA.datastore.get(row.get("message"))
    if conversation is None or message is None:
        return False
    sequence = int(row.get("message_sequence") or 0)
    user_id = _encoded_key(user)
    return bool(
        int(conversation.get("sequence") or 0) == sequence
        and conversation.get("last_sender") != user.key
        and int((conversation.get("read_through") or {}).get(user_id) or 0)
        < sequence
        and int((conversation.get("cleared_through") or {}).get(user_id) or 0)
        < sequence
        and user.key not in set(message.get("hidden_for") or ())
    )


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason notification suppression checks are exercised through public delivery
def _event_still_actionable(row):
    if row.get("source_type") != "notification":
        return True
    key = database.get.datastore_key(row.get("source_key"))
    return bool(key and DATA.datastore.get(key) is not None)


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason stable SMTP identity is internal to queued delivery
def _message_id(row):
    domain = urlsplit(_origin()).hostname or "localhost"
    delivery_version = (
        row.get("message_sequence")
        or row.get("source_key")
        or row.get("bucket")
        or "delivery"
    )
    identity = _identity(_encoded_key(row.key), delivery_version)[:32]
    return f"<notification-{identity}@{domain}>"


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason multipart rendering is exercised through public delivery
def _render_email(subject, items, *, digest=False, overflow=0):
    app_name = str(getattr(CONFIG, "APP_NAME", "Lagniappe") or "Lagniappe")
    text_lines = [subject, ""]
    html_items = []
    for item in items:
        title = str(item.get("title") or "Notification")
        body = str(item.get("body") or "")
        url = _absolute_url(item.get("target_path"))
        text_lines.extend((title, body, url, ""))
        html_items.append(
            '<section style="margin:0 0 18px">'
            f'<h2 style="font-size:16px;margin:0 0 6px">{escape(title)}</h2>'
            f'<div style="white-space:pre-wrap;margin:0 0 6px">{escape(body)}</div>'
            f'<a href="{escape(url, quote=True)}">Open in {escape(app_name)}</a>'
            "</section>"
        )
    if overflow:
        noun = "item is" if overflow == 1 else "items are"
        notice = f"{overflow} more {noun} available in {app_name}."
        text_lines.extend((notice, _absolute_url("/"), _absolute_url("/messages")))
        html_items.append(
            f"<p>{escape(notice)} "
            f'<a href="{escape(_absolute_url("/"), quote=True)}">Notifications</a> · '
            f'<a href="{escape(_absolute_url("/messages"), quote=True)}">Messages</a></p>'
        )
    heading = "Daily digest" if digest else subject
    html = (
        '<div style="font-family:system-ui,-apple-system,sans-serif;'
        'font-size:15px;line-height:1.45;color:#222;max-width:680px">'
        f'<h1 style="font-size:20px;margin:0 0 18px">{escape(heading)}</h1>'
        f"{''.join(html_items)}"
        "</div>"
    )
    return "\n".join(text_lines).strip(), html


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason SMTP composition is exercised through public delivery
def _send(user, row, items, *, digest=False, overflow=0):
    app_name = str(getattr(CONFIG, "APP_NAME", "Lagniappe") or "Lagniappe")
    if digest:
        subject = f"{app_name} daily digest"
    elif (
        row.get("source_type") == "message"
        or row.get("record_type") == "message-candidate"
    ):
        subject = f"New message from {row.get('sender_name') or 'a user'}"
    else:
        subject = f"New notification from {app_name}"
    text_body, html_body = _render_email(
        subject,
        items,
        digest=digest,
        overflow=overflow,
    )
    return auth_email.send_email(
        user.email,
        subject,
        text_body,
        html_body,
        message_id=_message_id(row),
    )


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason immediate suppression and send behavior is owned by public delivery
def _deliver_immediate(row, now):
    if row.get("due_at") and row["due_at"] > now:
        if row.get("record_type") != "message-candidate":
            raise NotificationEmailError("Notification email is not due yet.")
        task_name = _schedule(
            row,
            task_suffix=row.get("message_sequence"),
            now=now,
        )
        if task_name:
            _mark_message_scheduled(
                row,
                row.get("message_sequence"),
                task_name,
                now,
            )
        else:
            raise NotificationEmailError(
                "Notification email quiet-window scheduling failed."
            )
        return {"state": "rescheduled"}
    claimed = _claim(row, now)
    if claimed is None:
        return {"state": "complete"}
    row, token = claimed
    user = _load_user(row)
    sequence = row.get("message_sequence")
    try:
        valid = user is not None and _valid_for_user(row, user)
        if row.get("record_type") == "message-candidate":
            valid = valid and _message_still_actionable(row, user)
        else:
            valid = valid and _event_still_actionable(row)
        if valid and recently_active(user, now=now):
            valid = False
        if not valid:
            _finish(row, token, "suppressed", now, expected_sequence=sequence)
            return {"state": "suppressed"}
        _send(user, row, [row])
        _finish(row, token, "sent", now, expected_sequence=sequence)
        return {"state": "sent"}
    except Exception:
        _release(row, token, now)
        raise


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason digest query shape is owned by public delivery
def _digest_events(batch):
    return list(
        Query(KINDS.email_deliveries)
        .filter(Filter().eq("recipient", batch.get("recipient")))
        .filter(Filter().eq("record_type", "event"))
        .filter(Filter().eq("mode", NotificationEmailMode.DAILY.name))
        .filter(Filter().eq("bucket", batch.get("bucket")))
        .filter(Filter().eq("state", "pending"))
        .order("created")
        .fetch_all()
    )


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason event tombstone compaction is owned by public delivery
def _compact_events(rows, state, now):
    compacted = []
    for row in rows:
        item = DatastoreEntity(key=row.key)
        item.update(
            {
                "type": "notification_email_delivery",
                "schema_version": DELIVERY_SCHEMA_VERSION,
                "record_type": "event",
                "recipient": row.get("recipient"),
                "mode": row.get("mode"),
                "bucket": row.get("bucket"),
                "state": state,
                "created": row.get("created") or now,
                "modified": now,
                "completed": now,
            }
        )
        compacted.append(item)
    if compacted:
        DATA.datastore.put_multi(compacted)


# @testable false
# @covered-by lagniappe/core/tools/notification_email.py::deliver
# @reason digest send behavior is owned by public delivery
def _deliver_digest(batch, now):
    if batch.get("due_at") and batch["due_at"] > now:
        raise NotificationEmailError("Notification email digest is not due yet.")
    claimed = _claim(batch, now)
    if claimed is None:
        return {"state": "complete"}
    batch, token = claimed
    rows = _digest_events(batch)
    user = _load_user(batch)
    valid_rows = [
        row for row in rows if user is not None and _valid_for_user(row, user)
    ]
    try:
        if not valid_rows:
            _compact_events(rows, "suppressed", now)
            _finish(batch, token, "suppressed", now)
            return {"state": "suppressed"}
        visible = valid_rows[:DIGEST_ITEM_LIMIT]
        _send(
            user,
            batch,
            visible,
            digest=True,
            overflow=max(0, len(valid_rows) - len(visible)),
        )
        valid_keys = {row.key for row in valid_rows}
        _compact_events(valid_rows, "sent", now)
        _compact_events(
            [row for row in rows if row.key not in valid_keys],
            "suppressed",
            now,
        )
        _finish(batch, token, "sent", now)
        return {"state": "sent", "items": len(visible)}
    except Exception:
        _release(batch, token, now)
        raise


# @testable true
# @tests tests_unit/test_029_notification_email.py::test_immediate_notification_is_delayed_escaped_and_delivered
# @tests tests_unit/test_029_notification_email.py::test_immediate_messages_wait_for_conversation_quiet
# @tests tests_unit/test_029_notification_email.py::test_daily_digest_uses_next_local_eight_and_batches
# @pairs notification-email:immediate notification-email:message notification-email:digest
# @pairs notification-email:html notification-email:presence-suppression
# @pairs notification-email:read-suppression notification-email:idempotency
# @pair notification-email:item-cap
def deliver(delivery_identifier, *, now=None):
    """Deliver, suppress, or reschedule one opaque queued delivery."""
    now = _utc(now)
    key = database.get.datastore_key(delivery_identifier)
    row = DATA.datastore.get(key) if key else None
    if row is None:
        return {"state": "missing"}
    if row.get("schema_version") != DELIVERY_SCHEMA_VERSION:
        raise NotificationEmailError("Notification email delivery version is invalid.")
    if row.get("record_type") == "digest-batch":
        return _deliver_digest(row, now)
    if row.get("record_type") in {"event", "message-candidate"}:
        return _deliver_immediate(row, now)
    raise NotificationEmailError("Notification email delivery type is invalid.")


__all__ = [
    "DIGEST_HOUR",
    "DIGEST_ITEM_LIMIT",
    "IMMEDIATE_DELAY_SECONDS",
    "NotificationEmailError",
    "deliver",
    "eligible_user",
    "record_message",
    "record_notification",
    "record_notification_event",
    "record_site_activity",
    "recently_active",
]
