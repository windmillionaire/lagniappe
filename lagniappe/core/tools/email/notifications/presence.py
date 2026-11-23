"""Best-effort Redis presence used for email suppression."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User
    from datetime import datetime

from collections import OrderedDict
from threading import Lock

from lagniappe import CONFIG

from ....exceptions import capture
from ...cache.core import cache as redis_cache
from ...database import notification_email as email_database
from .links import identity
from .policy import utc


SITE_ACTIVITY_SECONDS = 10 * 60
SITE_ACTIVITY_WRITE_SECONDS = 60
SITE_ACTIVITY_MEMO_LIMIT = 4096
_activity_memo = OrderedDict()
_activity_memo_lock = Lock()


def _activity_check_due(key, timestamp):
    with _activity_memo_lock:
        previous = _activity_memo.get(key)
        if previous and previous[0] <= timestamp < previous[1]:
            _activity_memo.move_to_end(key)
            return False
    return True


def _remember_activity(key, timestamp, recorded):
    deadline = min(timestamp + SITE_ACTIVITY_WRITE_SECONDS, recorded + SITE_ACTIVITY_WRITE_SECONDS)
    with _activity_memo_lock:
        _activity_memo[key] = (timestamp, deadline)
        _activity_memo.move_to_end(key)
        while len(_activity_memo) > SITE_ACTIVITY_MEMO_LIMIT:
            _activity_memo.popitem(last=False)


def _activity_key(user):
    return f"{CONFIG.PREFIX}SITE_ACTIVITY:{identity(email_database.encoded_key(user))}"


def _timestamp(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return float(value)


def record_site_activity(user: User, *, now: datetime | None = None) -> bool:
    """Record coarse authenticated activity without creating browser traffic."""
    now = utc(now)
    timestamp = now.timestamp()
    key = _activity_key(user)
    if not _activity_check_due(key, timestamp):
        return False
    try:
        current = redis_cache.redis.get(key)
        if current and timestamp - _timestamp(current) < SITE_ACTIVITY_WRITE_SECONDS:
            _remember_activity(key, timestamp, _timestamp(current))
            return False
        redis_cache.redis.set(key, str(timestamp), ex=SITE_ACTIVITY_SECONDS)
        _remember_activity(key, timestamp, timestamp)
        return True
    except Exception as error:
        capture(error, context={"operation": "notification-email-site-activity"})
        return False


def recently_active(user: User, *, now: datetime | None = None) -> bool:
    """Return a best-effort recent-activity hint; cache failure fails open."""
    now = utc(now)
    try:
        value = redis_cache.redis.get(_activity_key(user))
        return bool(value and now.timestamp() - _timestamp(value) <= SITE_ACTIVITY_SECONDS)
    except Exception as error:
        capture(error, context={"operation": "notification-email-presence-check"})
        return False
