"""Generic timezone conversion and date parsing utilities."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser
from flask import has_request_context, session

from .auth.context import current_context_user


# @testable false
# @covered-by lagniappe/core/mixins/date.py::DateMixin
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.set_next_due_date
# @reason timezone resolution is owned by date/scheduling consumers
def user_timezone(user=None):
    """Get the request or user's timezone, falling back to UTC."""
    user = current_context_user(user)
    user_timezone_name = session.get("timezone") if has_request_context() else None
    if not user_timezone_name and user and user.is_authenticated:
        user_timezone_name = user.db.get("timezone")
    try:
        return ZoneInfo(user_timezone_name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


# @testable false
# @covered-by lagniappe/core/tools/ingress.py::IngressMutationPlanner._set_history
# @reason imported date parsing is owned by the ingress task-import workflow
def parse_imported_date_as_utc(date_string):
    """Parse a date string as UTC, returning None on failure."""
    try:
        date = date_parser.parse(date_string)
        if not date.tzinfo:
            date = date.replace(tzinfo=user_timezone())
        return beginning_of_day(date).astimezone(timezone.utc)
    except (ValueError, TypeError, date_parser.ParserError):
        return None


# @testable false
# @covered-by lagniappe/core/mixins/date.py::DateMixin
# @reason user-facing date formatting is owned by DateMixin projections
def utc_datetime_to_user_date_string(utc_dt):
    """Format a UTC datetime as YYYY-MM-DD in the user's timezone."""
    return utc_dt.astimezone(user_timezone()).strftime("%Y-%m-%d") if utc_dt else ""


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_format_date_as_input_string
# @features template-formatting
# @dimensions date input-value blank-value string-passthrough
def format_date_as_input_string(value):
    """Format a date-like value for an HTML date input."""
    if not value:
        return ""
    return value if isinstance(value, str) else value.strftime("%Y-%m-%d")


# @testable false
# @covered-by lagniappe/core/tools/tasks/scheduling.py::add_uncomplete_task_to_queue
# @reason UTC queue date formatting is part of task uncomplete scheduling
def utc_datetime_to_utc_date_string(utc_dt):
    """Format a UTC datetime as YYYY-MM-DD HH:MM:SS."""
    return utc_dt.strftime("%Y-%m-%d %H:%M:%S") if utc_dt else ""


# @testable false
# @covered-by lagniappe/web/routes/process/main.py::uncomplete_task
# @reason UTC queue date parsing is part of task uncomplete processing
def utc_date_string_to_utc_datetime(value):
    """Parse a YYYY-MM-DD or YYYY-MM-DD HH:MM:SS UTC value."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.replace(tzinfo=timezone.utc)


# @testable false
# @covered-by lagniappe/core/mixins/date.py::DateMixin
# @reason user-timezone datetime projection is owned by DateMixin
def utc_datetime_to_user_datetime(utc_dt):
    """Convert a UTC datetime to the user's timezone."""
    return utc_dt.astimezone(user_timezone()) if utc_dt else None


# @testable false
# @covered-by lagniappe/core/mixins/date.py::DateMixin
# @covered-by lagniappe/core/properties/task_scheduling.py::Periodic.update
# @reason user date parsing is owned by DateMixin and periodic schedule update
def user_date_string_to_utc_datetime(date_string):
    """Parse YYYY-MM-DD in the user's timezone and preserve the current time."""
    if not date_string:
        return None
    try:
        user_tz = user_timezone()
        base_date = datetime.strptime(date_string, "%Y-%m-%d")
        now_user = datetime.now(user_tz)
        value = base_date.replace(
            hour=now_user.hour,
            minute=now_user.minute,
            second=now_user.second,
            microsecond=now_user.microsecond,
            tzinfo=user_tz,
        )
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid date format: {date_string}")


# @testable false
# @covered-by lagniappe/core/tools/dates.py::user_today
# @covered-by lagniappe/core/tools/dates.py::parse_imported_date_as_utc
# @reason day-boundary normalization is owned by date parsing and today helpers
def beginning_of_day(value):
    """Return midnight at the supplied datetime's timezone."""
    if not value.tzinfo:
        value = value.replace(tzinfo=timezone.utc)
    return datetime.combine(value.date(), datetime.min.time(), tzinfo=value.tzinfo)


# @testable false
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.set_next_due_date
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.skipped
# @covered-by lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.prepare
# @reason current user-day boundary is owned by task scheduling behaviors
def user_today(user=None):
    """Return the beginning of today in the user's timezone."""
    return beginning_of_day(datetime.now(user_timezone(user)))
