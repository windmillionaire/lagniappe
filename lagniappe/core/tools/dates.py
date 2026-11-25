"""Generic timezone conversion and date parsing utilities."""

from datetime import date, datetime, UTC
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..mixins.field_host import FieldUser

from zoneinfo import ZoneInfo

from dateutil import parser as date_parser
from flask import has_request_context, session

from .auth.context import current_context_user

type DateUser = FieldUser | Literal[False]


def user_timezone(user: DateUser = None) -> ZoneInfo:
    """Get the request or user's timezone, falling back to UTC."""
    if user is None:
        user = current_context_user()
    user_timezone_name = session.get("timezone") if has_request_context() else None
    if not user_timezone_name and user and user.is_authenticated:
        user_timezone_name = user.db.get("timezone")
    try:
        return ZoneInfo(user_timezone_name if isinstance(user_timezone_name, str) and user_timezone_name else "UTC")
    except Exception:
        return ZoneInfo("UTC")


def parse_imported_date_as_utc(
    date_string: str | None, *, user: DateUser = None
) -> datetime | None:
    """Parse an imported calendar day as UTC, using the actor's zone if unzoned."""
    if date_string is None:
        return None
    try:
        date = date_parser.parse(date_string)
        if not date.tzinfo:
            date = date.replace(tzinfo=user_timezone(user))
        return beginning_of_day(date).astimezone(UTC)
    except (ValueError, TypeError, date_parser.ParserError):
        return None


def utc_datetime_to_user_date_string(
    utc_dt: datetime | None, *, user: DateUser = None
) -> str:
    """Format a UTC datetime as YYYY-MM-DD in the user's timezone."""
    return utc_dt.astimezone(user_timezone(user)).strftime("%Y-%m-%d") if utc_dt else ""


def format_date_as_input_string(value: date | str | None) -> str:
    """Format a date-like value for an HTML date input."""
    if not value:
        return ""
    return value if isinstance(value, str) else value.strftime("%Y-%m-%d")


def utc_datetime_to_utc_date_string(utc_dt: datetime | None) -> str:
    """Format a UTC datetime as YYYY-MM-DD HH:MM:SS."""
    return utc_dt.strftime("%Y-%m-%d %H:%M:%S") if utc_dt else ""


def utc_date_string_to_utc_datetime(value: str) -> datetime:
    """Parse a YYYY-MM-DD or YYYY-MM-DD HH:MM:SS UTC value."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.replace(tzinfo=UTC)


def utc_datetime_to_user_datetime(
    utc_dt: datetime | None, *, user: DateUser = None
) -> datetime | None:
    """Convert a UTC datetime to the user's timezone."""
    return utc_dt.astimezone(user_timezone(user)) if utc_dt else None


def user_date_string_to_utc_datetime(
    date_string: str | None, *, user: DateUser = None
) -> datetime | None:
    """Parse YYYY-MM-DD in the user's timezone and preserve the current time."""
    if not date_string:
        return None
    try:
        user_tz = user_timezone(user)
        base_date = datetime.strptime(date_string, "%Y-%m-%d")
        now_user = datetime.now(user_tz)
        value = base_date.replace(
            hour=now_user.hour,
            minute=now_user.minute,
            second=now_user.second,
            microsecond=now_user.microsecond,
            tzinfo=user_tz,
        )
        return value.astimezone(UTC)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid date format: {date_string}") from None


def beginning_of_day(value: datetime) -> datetime:
    """Return midnight at the supplied datetime's timezone."""
    if not value.tzinfo:
        value = value.replace(tzinfo=UTC)
    return datetime.combine(value.date(), datetime.min.time(), tzinfo=value.tzinfo)


def user_today(user: DateUser = None) -> datetime:
    """Return the beginning of today in the user's timezone."""
    return beginning_of_day(datetime.now(user_timezone(user)))
