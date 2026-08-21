"""Date/time utilities: timezone conversion, scheduling, and due date calculation."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dateutil import parser as date_parser

from dateutil.relativedelta import relativedelta
from flask import has_request_context, session, url_for

from lagniappe import CONFIG
from . import task_queue
from .user_context import current_context_user


# @testable false
# @covered-by lagniappe/core/mixins/date.py::DateMixin
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.set_next_due_date
# @reason timezone resolution is owned by date/scheduling consumers
def user_timezone(user=None):
    """Get user's timezone from session, user DB, or UTC as fallback."""
    user = current_context_user(user)
    user_tz_str = session.get("timezone") if has_request_context() else None
    if not user_tz_str and user and user.is_authenticated:
        user_tz_str = user.db.get("timezone")
    user_tz_str = user_tz_str or "UTC"
    try:
        return ZoneInfo(user_tz_str)
    except Exception:
        return ZoneInfo("UTC")


# @testable false
# @covered-by lagniappe/core/tools/ingress.py::IngressMutationPlanner._set_history
# @reason imported date parsing is owned by the ingress task-import workflow
def parse_imported_date_as_utc(date_string):
    """Parse a date string to datetime, returning None on failure."""
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
    if not utc_dt:
        return ""

    return utc_dt.astimezone(user_timezone()).strftime("%Y-%m-%d")


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_format_date_as_input_string
# @features template-formatting
# @dimensions date input-value blank-value string-passthrough
def format_date_as_input_string(value):
    """Format date-like values for an HTML date input."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d")


# @testable false
# @covered-by lagniappe/core/tools/dates.py::add_uncomplete_task_to_queue
# @reason UTC queue date formatting is part of task uncomplete scheduling
def utc_datetime_to_utc_date_string(utc_dt):
    """Format a UTC datetime as 'YYYY-MM-DD HH:MM:SS'."""
    if not utc_dt:
        return ""

    return utc_dt.strftime("%Y-%m-%d %H:%M:%S")


# @testable false
# @covered-by lagniappe/web/routes/process/main.py::uncomplete_task
# @reason UTC queue date parsing is part of task uncomplete processing
def utc_date_string_to_utc_datetime(utc_date_string):
    """Parse a UTC date string ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS') to datetime."""
    try:
        return datetime.strptime(utc_date_string, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return datetime.strptime(utc_date_string, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )


# @testable false
# @covered-by lagniappe/core/mixins/date.py::DateMixin
# @reason user-timezone datetime projection is owned by DateMixin
def utc_datetime_to_user_datetime(utc_dt):
    """Convert a UTC datetime to the user's timezone."""
    if not utc_dt:
        return None

    return utc_dt.astimezone(user_timezone())


# @testable false
# @covered-by lagniappe/core/mixins/date.py::DateMixin
# @covered-by lagniappe/core/properties/task_scheduling.py::Periodic.update
# @reason user date parsing is owned by DateMixin and periodic schedule update
def user_date_string_to_utc_datetime(date_string):
    """Parse a YYYY-MM-DD string in the user's timezone to a UTC datetime."""
    if not date_string:
        return None

    try:
        user_tz = user_timezone()
        base_date = datetime.strptime(date_string, "%Y-%m-%d")
        now_user = datetime.now(user_tz)
        user_date_with_time = base_date.replace(
            hour=now_user.hour,
            minute=now_user.minute,
            second=now_user.second,
            microsecond=now_user.microsecond,
        ).replace(tzinfo=user_tz)
        return user_date_with_time.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid date format: {date_string}")


# @testable false
# @covered-by lagniappe/core/tools/dates.py::user_today
# @covered-by lagniappe/core/tools/dates.py::parse_imported_date_as_utc
# @reason day-boundary normalization is owned by date parsing/today helpers
def beginning_of_day(dt):
    """Get the beginning of day (00:00:00) for a given datetime."""
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)

    return datetime.combine(dt.date(), datetime.min.time(), tzinfo=dt.tzinfo)


# @testable false
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.set_next_due_date
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.skipped
# @covered-by lagniappe/core/tools/deferred_job_adapters.py::AutofillAdapter.prepare
# @reason current user-day boundary is owned by task scheduling behaviors
def user_today(user=None):
    """Return the beginning of today in the user's timezone."""
    now = datetime.now(user_timezone(user))

    return beginning_of_day(now)


# @testable false
# @covered-by lagniappe/core/tools/dates.py::add_uncomplete_task_to_queue
# @reason midnight delay calculation is part of task uncomplete scheduling
def user_tomorrow_in_seconds():
    """Return seconds until midnight in the user's timezone."""
    now_user = datetime.now(user_timezone())
    tomorrow_user = beginning_of_day(now_user + timedelta(days=1))
    delay_seconds = (tomorrow_user - now_user).total_seconds()

    return delay_seconds if delay_seconds > 0 else 0


# @testable false
# @covered-by lagniappe/core/tools/dates.py::get_next_recurring_date
# @covered-by lagniappe/core/tools/dates.py::get_next_periodic_date
# @reason interval stepping is owned by next recurring/periodic due-date helpers
def calculate_next_recurring_due_date(date, recurring):
    """Add one interval (day/week/month/year) to a date using a recurring config."""
    if not recurring or not date:
        return None

    try:
        interval = int(recurring.get("interval", 0))
    except (ValueError, TypeError):
        return None

    unit = recurring.get("unit")

    if unit == "day":
        delta = relativedelta(days=interval)
    elif unit == "week":
        delta = relativedelta(weeks=interval)
    elif unit == "month":
        delta = relativedelta(months=interval)
    elif unit == "year":
        delta = relativedelta(years=interval)
    else:
        return None

    return date + delta


# @testable false
# @covered-by lagniappe/core/tools/dates.py::get_next_scheduled_date
# @reason scheduled occurrence stepping is owned by next scheduled due-date helper
def calculate_next_scheduled_due_date(due_date, scheduled):
    """Calculate the next occurrence after due_date for a scheduled config (daily/weekly/monthly/yearly)."""
    mode = scheduled.get("mode")

    if mode == "daily":
        # Next day after now
        next_date = due_date + timedelta(days=1)
        return next_date

    elif mode == "weekly":
        days = scheduled.get("days", [])

        # Find next occurrence of any of the selected days
        current_date = due_date
        for i in range(1, 8):  # Check next 7 days
            check_date = current_date + timedelta(days=i)
            weekday = check_date.weekday()  # 0=Monday, 1=Tuesday, etc.
            if weekday in days:
                return check_date

        return None

    elif mode == "monthly":
        return calculate_next_monthly_occurrence(due_date, scheduled)

    elif mode == "yearly":
        return calculate_next_yearly_occurrence(due_date, scheduled)

    return None


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_find_ordinal_weekday_in_month
# @features dates
# @dimensions ordinal-weekday
def find_ordinal_weekday_in_month(month_start, ordinal, weekday):
    """Find the nth weekday in a month, or last if ordinal is -1"""
    if ordinal == -1:
        # Find last occurrence
        # Start from last day of month and work backwards
        last_day = month_start + relativedelta(months=1, days=-1)
        for i in range(7):
            check_date = last_day - timedelta(days=i)
            check_weekday = check_date.weekday()  # 0=Monday, 1=Tuesday, etc.
            if check_weekday == weekday:
                return check_date
    else:
        # Find nth occurrence
        count = 0
        current = month_start
        while current.month == month_start.month:
            current_weekday = current.weekday()  # 0=Monday, 1=Tuesday, etc.
            if current_weekday == weekday:
                count += 1
                if count == ordinal:
                    return current
            current += timedelta(days=1)

    return None


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_next_monthly_occurrence
# @features dates
# @dimensions monthly-occurrence
def calculate_next_monthly_occurrence(due_date, scheduled):
    """Find the next monthly occurrence after due_date (specific day, first/last, or ordinal weekday)."""
    schedule_type = scheduled.get("type")
    # Get beginning of first day of current month
    month_start = due_date.replace(day=1)
    day = scheduled.get("day")
    if schedule_type == "specific_day" and not day:
        return None

    # @testable false
    # @covered-by lagniappe/core/tools/dates.py::calculate_next_monthly_occurrence
    # @reason specific-day recursion is part of monthly occurrence calculation
    def _get_next_date(delta=0):
        next_date = month_start + relativedelta(months=delta)
        try:
            next_date = next_date.replace(day=day)
        except ValueError:
            return None
        if next_date > due_date:
            return next_date
        return _get_next_date(delta + 1)

    if schedule_type == "specific_day":
        for delta in range(3):
            next_date = _get_next_date(delta)
            if next_date:
                return next_date
        return None

    elif schedule_type == "first_day":
        # First day of next month
        return month_start + relativedelta(months=1)

    elif schedule_type == "last_day":
        # Last day of current month if in future, otherwise last day of next month
        last_day_current = month_start + relativedelta(months=1, days=-1)
        if last_day_current > due_date:
            return last_day_current
        else:
            return month_start + relativedelta(months=2, days=-1)

    elif schedule_type == "ordinal_weekday":
        ordinal = scheduled.get("ordinal")
        weekday = scheduled.get("weekday")
        if ordinal is None or weekday is None:
            return None

        # Try current month first
        next_date = find_ordinal_weekday_in_month(month_start, ordinal, weekday)
        if next_date and next_date > due_date:
            return next_date

        # Try next month
        next_month = month_start + relativedelta(months=1)
        return find_ordinal_weekday_in_month(next_month, ordinal, weekday)

    return None


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_next_yearly_occurrence
# @features dates
# @dimensions yearly-occurrence
def calculate_next_yearly_occurrence(due_date, scheduled):
    """Find the next yearly occurrence after due_date."""
    tz = user_timezone()
    schedule_type = scheduled.get("type")
    month = scheduled.get("month")
    day = scheduled.get("day")
    if not month:
        return None
    elif schedule_type == "specific_day" and not day:
        return None

    current_year = due_date.year

    # @testable false
    # @covered-by lagniappe/core/tools/dates.py::calculate_next_yearly_occurrence
    # @reason year-local occurrence selection is part of yearly occurrence calculation
    def _get_next_date(year_start, schedule_type, scheduled):
        next_date = None
        if schedule_type == "specific_day":
            try:
                next_date = datetime(year_start.year, month, day, tzinfo=tz)
            except ValueError:
                pass
        elif schedule_type == "first_day":
            next_date = year_start
        elif schedule_type == "last_day":
            next_date = year_start + relativedelta(months=1, days=-1)
        elif schedule_type == "ordinal_weekday":
            ordinal = scheduled.get("ordinal")
            weekday = scheduled.get("weekday")
            if ordinal is not None and weekday is not None:
                next_date = find_ordinal_weekday_in_month(year_start, ordinal, weekday)
        return next_date

    # Try current year first
    year_start = datetime(current_year, month, 1, tzinfo=tz)
    next_date = _get_next_date(year_start, schedule_type, scheduled)

    # If date is in the future, use it
    if next_date and next_date > due_date:
        return next_date

    # Otherwise try next year
    next_year_start = datetime(current_year + 1, month, 1, tzinfo=tz)
    next_date = _get_next_date(next_year_start, schedule_type, scheduled)

    return next_date


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_postponed_due_date
# @features dates
# @dimensions postponement
def calculate_postponed_due_date(value):
    """Calculate a new due date from one of the home-page postpone options."""
    now_user = datetime.now(user_timezone())
    this_weekday_targets = {
        "this-week-monday": 0,
        "this-week-tuesday": 1,
        "this-week-wednesday": 2,
        "this-week-thursday": 3,
        "this-week-friday": 4,
        "this-week-saturday": 5,
        "this-week-sunday": 6,
    }
    next_weekday_offsets = {
        "next-week": 0,
        "next-week-monday": 0,
        "next-week-tuesday": 1,
        "next-week-wednesday": 2,
        "next-week-thursday": 3,
        "next-week-friday": 4,
    }

    if value == "tomorrow":
        new_date = now_user + timedelta(days=1)
    elif value == "weekend":
        days_to_saturday = (5 - now_user.weekday()) % 7 or 7
        new_date = now_user + timedelta(days=days_to_saturday)
    elif value in this_weekday_targets:
        days_to_target = this_weekday_targets[value] - now_user.weekday()
        new_date = (
            now_user + timedelta(days=days_to_target)
            if days_to_target > 0
            else None
        )
    elif value in next_weekday_offsets:
        next_monday = (7 - now_user.weekday()) % 7 or 7
        new_date = now_user + timedelta(
            days=next_monday + next_weekday_offsets[value]
        )
    else:
        new_date = None

    return new_date


# @testable false
# @covered-by lagniappe/core/tools/dates.py::add_uncomplete_task_to_queue
# @covered-by lagniappe/web/routes/tasks/main.py::_home_task_response
# @reason home-window visibility is exercised through task queue and home response flows
def due_in_home_task_window(due_date):
    """Return whether a due date belongs in the home task list window."""
    if not due_date:
        return False

    next_week = datetime.now(timezone.utc) + timedelta(days=7)
    return due_date <= next_week


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_with_schedule_queues_uncomplete
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_with_near_term_schedule_uncompletes_immediately
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_add_uncomplete_task_to_queue_future_due_queues_in_production
# @features task-completion task-scheduling
# @dimensions complete schedule-queue
def add_uncomplete_task_to_queue(task):
    """Queue a task to be uncompleted at midnight (or do it immediately in dev)."""
    next_due = task.due_date

    if due_in_home_task_window(next_due):
        task.uncomplete()
        task.due_date = next_due
        return None

    delay_seconds = user_tomorrow_in_seconds()

    payload = {
        "key": task.urlsafe_key,
        "next_due_date": utc_datetime_to_utc_date_string(next_due),
    }
    endpoint = url_for("process.uncomplete_task", _external=True)
    if CONFIG.production:
        return task_queue.create_task(
            endpoint=endpoint, payload=payload, delay_seconds=delay_seconds
        )
    else:
        task.uncomplete()
        task.due_date = next_due
        return None


# @testable true
# @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_recurring
# @features task-scheduling
# @dimensions next-due-date recurring
def get_next_recurring_date(recurring, starting_due_date=None):
    """Get the next recurring date from today (or a starting date)."""
    if starting_due_date is None:
        starting_due_date = user_today()
    return calculate_next_recurring_due_date(starting_due_date, recurring)


# @testable false
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.set_next_due_date
# @covered-by lagniappe/core/properties/task_scheduling.py::Schedule.skipped
# @reason schedule baseline selection is owned by next-due/skipped behaviors
def get_starting_due_date(task):
    """Get the earliest of postponed_from/due_date, or now if neither exists."""
    candidates = [d for d in [task.postponed_from, task.due_date] if d]
    if candidates:
        earliest = min(candidates)
        return earliest.astimezone(user_timezone())
    return datetime.now(user_timezone())


# @testable true
# @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_scheduled
# @features task-scheduling
# @dimensions next-due-date scheduled postponed
def get_next_scheduled_date(starting_due_date, scheduled):
    """Get the next scheduled date that falls after today."""
    next_due_date = calculate_next_scheduled_due_date(starting_due_date, scheduled)
    while next_due_date and next_due_date <= user_today():
        next_due_date = calculate_next_scheduled_due_date(next_due_date, scheduled)

    return next_due_date


# @testable true
# @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_periodic
# @features task-scheduling
# @dimensions next-due-date periodic postponed
def get_next_periodic_date(starting_due_date, periodic):
    """Get the next periodic date that falls after today."""
    next_due_date = calculate_next_recurring_due_date(starting_due_date, periodic)
    while next_due_date and next_due_date <= user_today():
        next_due_date = calculate_next_recurring_due_date(next_due_date, periodic)

    return next_due_date


# @testable true
# @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_scheduled
# @features task-scheduling
# @dimensions skipped scheduled
def calculate_skipped_scheduled_tasks(task, scheduled):
    """Calculate how many times a scheduled task should have been completed between the starting due date and today"""
    if not scheduled:
        return 0

    starting_due_date = get_starting_due_date(task)
    today = user_today()

    if not starting_due_date or starting_due_date >= today:
        return 0

    mode = scheduled.get("mode")
    count = 0

    if mode == "daily":
        delta = today - starting_due_date
        return max(0, delta.days)

    elif mode == "weekly":
        days = scheduled.get("days", [])
        current = starting_due_date + timedelta(days=1)

        while current < today:
            weekday = current.weekday()  # 0=Monday, 1=Tuesday, etc.
            if weekday in days:
                count += 1
            current += timedelta(days=1)

    elif mode == "monthly":
        current_month = starting_due_date.replace(day=1) + relativedelta(months=1)

        while current_month < today:
            occurrence = calculate_monthly_occurrence_for_date(current_month, scheduled)
            if occurrence and starting_due_date < occurrence < today:
                count += 1
            current_month += relativedelta(months=1)

    elif mode == "yearly":
        start_year = starting_due_date.year + 1
        end_year = today.year

        for year in range(start_year, end_year + 1):
            occurrence = calculate_yearly_occurrence_for_year(year, scheduled)
            if occurrence and starting_due_date < occurrence < today:
                count += 1

    return count


# @testable true
# @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_recurring
# @features task-scheduling
# @dimensions skipped recurring periodic
def calculate_skipped_recurring_tasks(task, periodic):
    """Calculate how many times a recurring task should have been completed between the starting due date and today"""
    if not periodic:
        return 0

    starting_due_date = get_starting_due_date(task)
    today = user_today()

    if not starting_due_date or starting_due_date >= today:
        return 0

    try:
        interval = int(periodic.get("interval", 0))
    except (ValueError, TypeError):
        return 0

    unit = periodic.get("unit")

    if interval <= 0:
        return 0

    # Calculate the time delta for one interval
    if unit == "day":
        delta = relativedelta(days=interval)
    elif unit == "week":
        delta = relativedelta(weeks=interval)
    elif unit == "month":
        delta = relativedelta(months=interval)
    elif unit == "year":
        delta = relativedelta(years=interval)
    else:
        return 0

    # Count how many intervals fit between the dates
    count = 0
    current_date = starting_due_date + delta

    while current_date < today:
        count += 1
        current_date += delta

    return count


# @testable false
# @covered-by lagniappe/core/tools/dates.py::calculate_skipped_scheduled_tasks
# @reason monthly occurrence lookup is part of skipped scheduled-task counting
def calculate_monthly_occurrence_for_date(month_start, scheduled):
    """Calculate the specific occurrence date for a month"""
    schedule_type = scheduled.get("type")

    if schedule_type == "specific_day":
        day = scheduled.get("day")
        if day:
            try:
                return month_start.replace(day=day)
            except ValueError:
                return None

    elif schedule_type == "first_day":
        return month_start

    elif schedule_type == "last_day":
        return month_start + relativedelta(months=1, days=-1)

    elif schedule_type == "ordinal_weekday":
        ordinal = scheduled.get("ordinal")
        weekday = scheduled.get("weekday")
        if ordinal is not None and weekday is not None:
            return find_ordinal_weekday_in_month(month_start, ordinal, weekday)

    return None


# @testable false
# @covered-by lagniappe/core/tools/dates.py::calculate_skipped_scheduled_tasks
# @reason yearly occurrence lookup is part of skipped scheduled-task counting
def calculate_yearly_occurrence_for_year(year, scheduled):
    """Calculate the specific occurrence date for a year"""
    month = scheduled.get("month")
    tz = user_timezone()
    if not month:
        return None

    schedule_type = scheduled.get("type")
    year_start = datetime(year, month, 1, tzinfo=tz)

    if schedule_type == "specific_day":
        day = scheduled.get("day")
        if day:
            try:
                return datetime(year, month, day, tzinfo=tz)
            except ValueError:
                return None

    elif schedule_type == "first_day":
        return year_start

    elif schedule_type == "last_day":
        return year_start + relativedelta(months=1, days=-1)

    elif schedule_type == "ordinal_weekday":
        ordinal = scheduled.get("ordinal")
        weekday = scheduled.get("weekday")
        if ordinal is not None and weekday is not None:
            return find_ordinal_weekday_in_month(year_start, ordinal, weekday)

    return None
