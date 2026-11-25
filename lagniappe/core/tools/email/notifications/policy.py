"""Recipient eligibility and delivery timing policy."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User

from datetime import datetime, time as datetime_time, timedelta, UTC

from ....definitions import NotificationEmailMode
from ....entities import Entities
from ...dates import user_timezone


IMMEDIATE_DELAY_SECONDS = 5 * 60
DIGEST_HOUR = 8
DIGEST_ITEM_LIMIT = 100
DELIVERY_LEASE_SECONDS = 5 * 60


def utc(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def mode(user: User) -> NotificationEmailMode:
    try:
        return NotificationEmailMode[user.notification_email_mode]
    except (AttributeError, KeyError, TypeError):
        return NotificationEmailMode.NONE


def preference_epoch(user: User) -> int:
    value = user.db.get("notification_email_opt_out_epoch")
    if not value:
        return 0
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        raise TypeError("Invalid notification opt-out epoch")
    return int(value)


def eligible_user(user: object) -> bool:
    """Return whether a user may receive notification email."""
    return bool(
        isinstance(user, Entities.USER)
        and getattr(user, "active", True)
        and not user.is_public
        and user.last_login
        and str(user.email or "").strip()
        and mode(user) is not NotificationEmailMode.NONE
    )


def next_digest(user: User, now: datetime) -> datetime:
    zone = user_timezone(user)
    local_now = now.astimezone(zone)
    due = datetime.combine(
        local_now.date(), datetime_time(hour=DIGEST_HOUR), tzinfo=zone
    )
    if due <= local_now:
        due += timedelta(days=1)
    return due.astimezone(UTC)
