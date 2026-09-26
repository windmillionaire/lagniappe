"""Notification-email eligibility, timing, and presence contracts."""

from datetime import datetime, timedelta, timezone

import pytest

from lagniappe.core.tools.email.notifications import policy as email_policy
from lagniappe.core.tools.email.notifications import presence as email_presence
from testing.utility.notification_email_fakes import MemoryRedis, user_row


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def fresh_activity_memo(monkeypatch):
    from collections import OrderedDict
    monkeypatch.setattr(email_presence, "_activity_memo", OrderedDict())


# @source lagniappe/core/properties/user_entity.py::NotificationEmailPreference.value
# @matrix notification-email : eligibility never-logged-in preference public-user
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
    user.notification_email_mode = "NONE"
    assert user.db["notification_email_opt_out_epoch"] == 1
    user.notification_email_mode = "DAILY"
    user.notification_email_mode = "NONE"
    assert user.db["notification_email_opt_out_epoch"] == 2

    public = user_row("public", now, public=True, mode="DAILY")
    never_logged_in = user_row("new", now, logged_in=False, mode="DAILY")
    inactive = user_row("inactive", now, mode="DAILY")
    inactive.active = False
    addressless = user_row("addressless", now, mode="DAILY")
    addressless.email = ""
    assert public.notification_email_mode == "NONE"
    assert not email_policy.eligible_user(public)
    assert not email_policy.eligible_user(never_logged_in)
    assert not email_policy.eligible_user(inactive)
    assert not email_policy.eligible_user(addressless)

    with pytest.raises(ValueError, match="Public users"):
        public.notification_email_mode = "IMMEDIATE"

    with pytest.raises(ValueError, match="NONE, IMMEDIATE, or DAILY"):
        user.notification_email_mode = "weekly"


# @matrix notification-email : coarse-request-activity presence
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


# @matrix notification-email : coarse-request-activity presence redis-loss
def test_site_activity_memo_bounds_reads_and_redis_loss_delay(monkeypatch):
    from unittest.mock import Mock
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    cache = MemoryRedis()
    cache.get = Mock(wraps=cache.get)
    monkeypatch.setattr(email_presence.redis_cache, "_redis", cache)
    recipient = user_row("recipient", now)
    assert email_presence.record_site_activity(recipient, now=now)
    for second in range(1, 60):
        assert not email_presence.record_site_activity(recipient, now=now+timedelta(seconds=second))
    assert cache.get.call_count == 1
    cache.values.clear()
    assert not email_presence.record_site_activity(recipient, now=now+timedelta(seconds=59))
    # Redis loss can delay repair until the existing coarse write boundary.
    assert email_presence.record_site_activity(recipient, now=now+timedelta(seconds=60))
    assert cache.get.call_count == 2
    assert email_presence.recently_active(recipient, now=now+timedelta(seconds=61))
    assert not email_presence.record_site_activity(recipient, now=now+timedelta(seconds=62))
    assert cache.get.call_count == 3


# @matrix notification-email : coarse-request-activity failure bounded
def test_activity_memo_retries_failures_and_bounds_memory(monkeypatch):
    from unittest.mock import Mock
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    cache = MemoryRedis()
    monkeypatch.setattr(email_presence.redis_cache, "_redis", cache)
    monkeypatch.setattr(email_presence, "capture", Mock())
    monkeypatch.setattr(email_presence, "SITE_ACTIVITY_MEMO_LIMIT", 2)
    recipient = user_row("retry", now)
    original = cache.get
    cache.get = Mock(side_effect=ConnectionError("offline"))
    assert not email_presence.record_site_activity(recipient, now=now)
    assert not email_presence._activity_memo
    cache.get = original
    assert email_presence.record_site_activity(recipient, now=now)
    for name in ('second', 'third'):
        assert email_presence.record_site_activity(user_row(name, now), now=now)
    assert len(email_presence._activity_memo) == 2
    assert email_presence._activity_key(recipient) not in email_presence._activity_memo
    cache.values.clear()
    assert email_presence.record_site_activity(recipient, now=now+timedelta(seconds=1))
    cache.set = Mock(side_effect=ConnectionError("offline"))
    failed = user_row('write-failed', now)
    assert not email_presence.record_site_activity(failed, now=now)
    assert email_presence._activity_key(failed) not in email_presence._activity_memo


# @matrix notification-email : coarse-request-activity concurrency clock
def test_activity_memo_is_safe_for_concurrent_workers_and_clock_changes(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import Mock
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    cache = MemoryRedis()
    cache.get = Mock(wraps=cache.get)
    monkeypatch.setattr(email_presence.redis_cache, "_redis", cache)
    recipient = user_row('parallel', now)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: email_presence.record_site_activity(recipient, now=now), range(40)))
    assert email_presence.recently_active(recipient, now=now)
    assert len(email_presence._activity_memo) == 1
    reads = cache.get.call_count
    assert not email_presence.record_site_activity(recipient, now=now-timedelta(seconds=1))
    assert cache.get.call_count == reads + 1
    assert email_presence.record_site_activity(recipient, now=now+timedelta(seconds=61))
    # A separate/restarted worker consults the shared Redis value immediately.
    email_presence._activity_memo.clear()
    reads = cache.get.call_count
    assert not email_presence.record_site_activity(recipient, now=now+timedelta(seconds=62))
    assert cache.get.call_count == reads + 1
