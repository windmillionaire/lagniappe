"""
Wall-clock helpers in the test runner's local timezone.

Use these in E2E assertions where DOM or user-visible dates follow the machine's
local calendar (e.g. ``data-due-date`` strings), instead of naive ``datetime.now()``
or ``date.today()`` which can disagree with the browser/OS when TZ differs from UTC.

Related:
    ``datetime.now().astimezone()`` — aware datetime in the system local zone (PEP 495).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


def local_now() -> datetime:
    """Current time as a timezone-aware datetime in the system local timezone."""
    return datetime.now().astimezone()


def local_today() -> date:
    """Today's calendar date in the system local timezone."""
    return local_now().date()


def local_date_iso() -> str:
    """Today's date as ISO 8601 ``YYYY-MM-DD`` in the local timezone."""
    return local_today().isoformat()


def local_date_plus_days_iso(days: int) -> str:
    """ISO date string for *local* today plus *days* (can be negative)."""
    return (local_today() + timedelta(days=days)).isoformat()


def local_postponed_next_week_iso(weekday_offset: int = 0) -> str:
    """
    A weekday in next week (ISO), using the runner's local calendar.

    ``weekday_offset`` is zero for Monday and four for Friday. This matches the
    ``next-week-*`` postpone values when the app and runner share a calendar day.
    """
    today = local_today()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    return (today + timedelta(days=days_to_monday + weekday_offset)).isoformat()


def local_date_from_utc_datetime(utc_datetime: datetime) -> date:
    """Local date from a UTC datetime."""
    return utc_datetime.astimezone()
