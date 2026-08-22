"""Best-effort Redis presence used for email suppression."""

from lagniappe import CONFIG

from ....exceptions import capture
from ...cache.core import cache as redis_cache
from ...database import notification_email as email_database
from .links import identity
from .policy import utc


SITE_ACTIVITY_SECONDS = 10 * 60
SITE_ACTIVITY_WRITE_SECONDS = 60


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/presence.py::record_site_activity
# @reason Redis key construction is owned by coarse activity recording
def _activity_key(user):
    return f"{CONFIG.PREFIX}SITE_ACTIVITY:{identity(email_database.encoded_key(user))}"


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/presence.py::record_site_activity
# @reason Redis wire normalization is exercised through coarse activity recording
def _timestamp(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return float(value)


# @testable true
# @tests tests_unit/test_029a_notification_email_policy.py::test_site_activity_is_coarse_and_expires
# @pairs notification-email:presence notification-email:coarse-request-activity
def record_site_activity(user, *, now=None):
    """Record coarse authenticated activity without creating browser traffic."""
    now = utc(now)
    key = _activity_key(user)
    try:
        current = redis_cache.redis.get(key)
        if current and now.timestamp() - _timestamp(current) < SITE_ACTIVITY_WRITE_SECONDS:
            return False
        redis_cache.redis.set(key, str(now.timestamp()), ex=SITE_ACTIVITY_SECONDS)
        return True
    except Exception as error:
        capture(error, context={"operation": "notification-email-site-activity"})
        return False


# @testable true
# @tests tests_unit/test_029a_notification_email_policy.py::test_site_activity_is_coarse_and_expires
# @tests tests_unit/test_029b_notification_email_events.py::test_immediate_notification_is_delayed_escaped_and_delivered
# @pairs notification-email:presence notification-email:presence-suppression
def recently_active(user, *, now=None):
    """Return a best-effort recent-activity hint; cache failure fails open."""
    now = utc(now)
    try:
        value = redis_cache.redis.get(_activity_key(user))
        return bool(value and now.timestamp() - _timestamp(value) <= SITE_ACTIVITY_SECONDS)
    except Exception as error:
        capture(error, context={"operation": "notification-email-presence-check"})
        return False
