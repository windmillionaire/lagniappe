"""Recipient eligibility and delivery timing policy."""

from datetime import datetime, time as datetime_time, timedelta, timezone

from ....definitions import NotificationEmailMode
from ....entities import Entities
from ...dates import user_timezone


IMMEDIATE_DELAY_SECONDS = 5 * 60
DIGEST_HOUR = 8
DIGEST_ITEM_LIMIT = 100
DELIVERY_LEASE_SECONDS = 5 * 60


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason clock normalization is exercised through capture and delivery
def utc(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/policy.py::eligible_user
# @reason preference normalization is owned by recipient eligibility
def mode(user):
    try:
        return NotificationEmailMode[user.notification_email_mode]
    except (AttributeError, KeyError, TypeError):
        return NotificationEmailMode.NONE


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/delivery.py::deliver
# @reason opt-out generations are enforced through delivery
def preference_epoch(user):
    return int(user.db.get("notification_email_opt_out_epoch") or 0)


# @testable true
# @tests tests_unit/test_029a_notification_email_policy.py::test_notification_email_preference_defaults_and_eligibility
# @pairs notification-email:eligibility notification-email:public-user notification-email:never-logged-in
def eligible_user(user):
    """Return whether a user may receive notification email."""
    return bool(
        isinstance(user, Entities.USER)
        and getattr(user, "active", True)
        and not user.is_public
        and user.last_login
        and str(user.email or "").strip()
        and mode(user) is not NotificationEmailMode.NONE
    )


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason local digest timing is exercised through public event capture
def next_digest(user, now):
    zone = user_timezone(user)
    local_now = now.astimezone(zone)
    due = datetime.combine(
        local_now.date(), datetime_time(hour=DIGEST_HOUR), tzinfo=zone
    )
    if due <= local_now:
        due += timedelta(days=1)
    return due.astimezone(timezone.utc)
