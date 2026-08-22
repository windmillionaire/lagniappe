"""Notification-email eligibility, timing, and presence contracts."""

from datetime import datetime, timedelta, timezone

import pytest

from lagniappe.core.tools.email.notifications import policy as email_policy
from lagniappe.core.tools.email.notifications import presence as email_presence
from testing.utility.notification_email_fakes import MemoryRedis, user_row


pytestmark = pytest.mark.unit


# @source lagniappe/core/properties/user_entity.py::NotificationEmailPreference.value
# @source lagniappe/core/tools/email/notifications/policy.py::eligible_user
# @pairs notification-email:preference notification-email:eligibility
# @pairs notification-email:public-user notification-email:never-logged-in
def test_notification_email_preference_defaults_and_eligibility():
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    user = user_row("managed", now)
    user.db.pop("notification_email_mode")

    assert user.notification_email_mode == "DAILY"
    assert email_policy.eligible_user(user)

    user.notification_email_mode = "NONE"
    assert user.notification_email_mode == "NONE"
    assert user.db["notification_email_opt_out_epoch"] == 1
    assert not email_policy.eligible_user(user)

    public = user_row("public", now, public=True, mode="DAILY")
    never_logged_in = user_row("new", now, logged_in=False, mode="DAILY")
    assert public.notification_email_mode == "NONE"
    assert not email_policy.eligible_user(public)
    assert not email_policy.eligible_user(never_logged_in)

    with pytest.raises(ValueError, match="NONE, IMMEDIATE, or DAILY"):
        user.notification_email_mode = "weekly"


# @source lagniappe/core/tools/email/notifications/presence.py::record_site_activity
# @source lagniappe/core/tools/email/notifications/presence.py::recently_active
# @pairs notification-email:presence notification-email:coarse-request-activity
def test_site_activity_is_coarse_and_expires(monkeypatch):
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    cache = MemoryRedis()
    monkeypatch.setattr(email_presence.redis_cache, "_redis", cache)
    recipient = user_row("recipient", now)

    assert email_presence.record_site_activity(recipient, now=now)
    assert cache.expirations[next(iter(cache.expirations))] == 10 * 60
    assert email_presence.recently_active(recipient, now=now)

    assert not email_presence.record_site_activity(
        recipient,
        now=now + timedelta(seconds=30),
    )
    assert email_presence.record_site_activity(
        recipient,
        now=now + timedelta(seconds=61),
    )
    assert not email_presence.recently_active(
        recipient,
        now=now + timedelta(minutes=11, seconds=2),
    )
