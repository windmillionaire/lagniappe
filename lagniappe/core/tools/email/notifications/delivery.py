"""Queued notification-email delivery orchestration."""

from ....definitions import Fetch
from ....entities import Entities
from ....properties import notification_email as delivery_values
from ...database import notification_email as email_database
from . import dispatch, policy, presence, presentation
from .errors import NotificationEmailError


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason direct recipient loading is internal to queued delivery
def _load_user(row):
    user = Entities.fetch_one(row.get("recipient"), request=Fetch.direct())
    return user if isinstance(user, Entities.USER) else None


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason send-time opt-out enforcement is exercised through delivery
def _valid_for_user(row, user):
    return bool(
        policy.eligible_user(user)
        and int(row.get("preference_epoch") or 0)
        == policy.preference_epoch(user)
    )


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason immediate suppression and send behavior is owned by public delivery
def _deliver_immediate(row, now):
    if row.get("due_at") and row["due_at"] > now:
        if row.get("record_type") != "message-candidate":
            raise NotificationEmailError("Notification email is not due yet.")
        task_name = dispatch.schedule(
            row, task_suffix=row.get("message_sequence"), now=now
        )
        if task_name:
            email_database.mark_message_scheduled(
                row, row.get("message_sequence"), task_name, now
            )
        else:
            raise NotificationEmailError(
                "Notification email quiet-window scheduling failed."
            )
        return {"state": "rescheduled"}

    claimed = email_database.claim_delivery(
        row, now, lease_seconds=policy.DELIVERY_LEASE_SECONDS
    )
    if claimed is None:
        return {"state": "complete"}
    row, token = claimed
    user = _load_user(row)
    sequence = row.get("message_sequence")
    try:
        valid = user is not None and _valid_for_user(row, user)
        if row.get("record_type") == "message-candidate":
            valid = valid and email_database.message_is_actionable(row, user)
        else:
            valid = valid and email_database.event_is_actionable(row)
        if valid and presence.recently_active(user, now=now):
            valid = False
        if not valid:
            email_database.finish_delivery(
                row,
                token,
                "suppressed",
                now,
                expected_sequence=sequence,
            )
            return {"state": "suppressed"}
        presentation.send(user, row, [row])
        email_database.finish_delivery(
            row, token, "sent", now, expected_sequence=sequence
        )
        return {"state": "sent"}
    except Exception:
        email_database.release_delivery(row, token, now)
        raise


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason digest selection and send behavior is owned by public delivery
def _deliver_digest(batch, now):
    if batch.get("due_at") and batch["due_at"] > now:
        raise NotificationEmailError("Notification email digest is not due yet.")
    claimed = email_database.claim_delivery(
        batch, now, lease_seconds=policy.DELIVERY_LEASE_SECONDS
    )
    if claimed is None:
        return {"state": "complete"}
    batch, token = claimed
    rows = email_database.digest_events(batch)
    user = _load_user(batch)
    valid_rows = [
        row for row in rows if user is not None and _valid_for_user(row, user)
    ]
    try:
        if not valid_rows:
            email_database.compact_events(rows, "suppressed", now)
            email_database.finish_delivery(batch, token, "suppressed", now)
            return {"state": "suppressed"}
        visible = valid_rows[: policy.DIGEST_ITEM_LIMIT]
        presentation.send(
            user,
            batch,
            visible,
            digest=True,
            overflow=max(0, len(valid_rows) - len(visible)),
        )
        valid_keys = {row.key for row in valid_rows}
        email_database.compact_events(valid_rows, "sent", now)
        email_database.compact_events(
            [row for row in rows if row.key not in valid_keys],
            "suppressed",
            now,
        )
        email_database.finish_delivery(batch, token, "sent", now)
        return {"state": "sent", "items": len(visible)}
    except Exception:
        email_database.release_delivery(batch, token, now)
        raise


# @testable true
# @tests tests_unit/test_029b_notification_email_events.py::test_immediate_notification_is_delayed_escaped_and_delivered
# @tests tests_unit/test_029b_notification_email_events.py::test_document_mention_email_uses_concise_copy_and_document_tab
# @tests tests_unit/test_029b_notification_email_events.py::test_task_assignment_email_uses_task_copy_without_headers
# @tests tests_unit/test_029c_notification_email_messages.py::test_immediate_messages_wait_for_conversation_quiet
# @tests tests_unit/test_029d_notification_email_digest.py::test_daily_digest_uses_next_local_eight_and_batches
# @tests tests_unit/test_029d_notification_email_digest.py::test_daily_digest_groups_messages_and_uses_named_completion_links
# @matrix notification-email : digest document-mention html idempotency immediate item-cap message message-grouping presence-suppression read-suppression task-assignment
def deliver(delivery_identifier, *, now=None):
    """Deliver, suppress, or reschedule one opaque queued delivery."""
    now = policy.utc(now)
    row = email_database.get_delivery(delivery_identifier)
    if row is None:
        return {"state": "missing"}
    if row.get("schema_version") != delivery_values.DELIVERY_SCHEMA_VERSION:
        raise NotificationEmailError("Notification email delivery version is invalid.")
    if row.get("record_type") == "digest-batch":
        return _deliver_digest(row, now)
    if row.get("record_type") in {"event", "message-candidate"}:
        return _deliver_immediate(row, now)
    raise NotificationEmailError("Notification email delivery type is invalid.")
