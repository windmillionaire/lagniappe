"""Task recurrence, postponement, and durable uncomplete scheduling."""

import hashlib
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from dateutil.rrule import DAILY, MONTHLY, WEEKLY, YEARLY, MO, rrule
from dateutil.rrule import weekday as rrule_weekday
from flask import url_for

from lagniappe import CONFIG
from ..dates import (
    beginning_of_day,
    user_timezone,
    user_today,
)
from ..services import task_queue


# @testable false
# @covered-by lagniappe/core/tools/tasks/scheduling.py::add_uncomplete_task_to_queue
# @reason midnight delay calculation is part of task uncomplete scheduling
def user_tomorrow_in_seconds():
    """Return seconds until midnight in the user's timezone."""
    now_user = datetime.now(user_timezone())
    tomorrow_user = beginning_of_day(now_user + timedelta(days=1))
    delay_seconds = (tomorrow_user - now_user).total_seconds()

    return delay_seconds if delay_seconds > 0 else 0


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_with_schedule_queues_uncomplete
# @matrix task-scheduling : durable-uncomplete timezone
def scheduled_uncomplete_time():
    """Return the next user-local midnight as an absolute UTC timestamp."""
    now_user = datetime.now(user_timezone())
    tomorrow_user = beginning_of_day(now_user + timedelta(days=1))
    return tomorrow_user.astimezone(timezone.utc)


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_next_recurring_due_date_preserves_interval_semantics
# @matrix task-scheduling : recurring periodic interval-semantics
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
# @covered-by lagniappe/core/tools/tasks/scheduling.py::calculate_next_scheduled_due_date
# @covered-by lagniappe/core/tools/tasks/scheduling.py::calculate_skipped_scheduled_tasks
# @reason private validation and translation are exercised by scheduled stepping and skipped counting
def _scheduled_rrule_args(scheduled):
    """Translate a valid stored calendar schedule into ``rrule`` arguments."""
    if not isinstance(scheduled, dict):
        return None

    mode = scheduled.get("mode")
    if mode == "daily":
        return DAILY, {}

    if mode == "weekly":
        days = scheduled.get("days")
        if not isinstance(days, list) or not days:
            return None
        if any(type(day) is not int or not 0 <= day <= 6 for day in days):
            return None
        return WEEKLY, {
            "wkst": MO,
            "byweekday": tuple(rrule_weekday(day) for day in sorted(set(days))),
        }

    if mode not in {"monthly", "yearly"}:
        return None

    schedule_type = scheduled.get("type")
    if schedule_type == "specific_day":
        day = scheduled.get("day")
        if type(day) is not int or not 1 <= day <= 31:
            return None
        arguments = {"bymonthday": day}
    elif schedule_type == "first_day":
        arguments = {"bymonthday": 1}
    elif schedule_type == "last_day":
        arguments = {"bymonthday": -1}
    elif schedule_type == "ordinal_weekday":
        ordinal = scheduled.get("ordinal")
        weekday_number = scheduled.get("weekday")
        if type(ordinal) is not int or ordinal not in {-1, 1, 2, 3, 4}:
            return None
        if type(weekday_number) is not int or not 0 <= weekday_number <= 6:
            return None
        arguments = {"byweekday": rrule_weekday(weekday_number)(ordinal)}
    else:
        return None

    if mode == "monthly":
        return MONTHLY, arguments

    month = scheduled.get("month")
    if type(month) is not int or not 1 <= month <= 12:
        return None

    if schedule_type == "specific_day":
        maximum_day = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[
            month - 1
        ]
        if day > maximum_day:
            return None

    return YEARLY, {"bymonth": month, **arguments}


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_next_scheduled_due_date
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_next_scheduled_due_date_rejects_invalid_rules
# @matrix task-scheduling : scheduled calendar-validation exact-boundary timezone
def calculate_next_scheduled_due_date(due_date, scheduled):
    """Return the first valid calendar occurrence strictly after ``due_date``."""
    if not isinstance(due_date, datetime):
        return None

    translated = _scheduled_rrule_args(scheduled)
    if translated is None:
        return None

    frequency, arguments = translated
    mode = scheduled["mode"]
    if mode == "yearly":
        rule_start = datetime(due_date.year, 1, 1, tzinfo=user_timezone())
    else:
        rule_start = due_date

    try:
        next_date = rrule(
            frequency,
            dtstart=rule_start,
            **arguments,
        ).after(due_date, inc=False)
    except (TypeError, ValueError):
        return None

    if next_date is not None and mode != "yearly":
        next_date = next_date.replace(microsecond=due_date.microsecond)
    return next_date


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_find_ordinal_weekday_in_month
# @pair dates:ordinal-weekday
def find_ordinal_weekday_in_month(month_start, ordinal, weekday):
    """Find the nth weekday in one month, or the last when ordinal is -1."""
    if not isinstance(month_start, datetime):
        return None
    if type(ordinal) is not int or ordinal not in {-1, 1, 2, 3, 4, 5}:
        return None
    if type(weekday) is not int or not 0 <= weekday <= 6:
        return None

    occurrence = rrule(
        MONTHLY,
        dtstart=month_start,
        until=month_start + relativedelta(months=1) - timedelta(microseconds=1),
        byweekday=rrule_weekday(weekday)(ordinal),
    ).after(month_start, inc=True)
    if occurrence is None or (occurrence.year, occurrence.month) != (
        month_start.year,
        month_start.month,
    ):
        return None
    return occurrence.replace(microsecond=month_start.microsecond)


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_next_monthly_occurrence
# @pair dates:monthly-occurrence
def calculate_next_monthly_occurrence(due_date, scheduled):
    """Find the next monthly calendar occurrence after ``due_date``."""
    if not isinstance(scheduled, dict):
        return None
    monthly = {**scheduled, "mode": "monthly"}
    return calculate_next_scheduled_due_date(due_date, monthly)


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_next_yearly_occurrence
# @pair dates:yearly-occurrence
def calculate_next_yearly_occurrence(due_date, scheduled):
    """Find the next yearly calendar occurrence after ``due_date``."""
    if not isinstance(scheduled, dict):
        return None
    yearly = {**scheduled, "mode": "yearly"}
    return calculate_next_scheduled_due_date(due_date, yearly)


# @testable true
# @tests tests_unit/test_013d_date_utilities.py::test_calculate_postponed_due_date
# @pair dates:postponement
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
# @covered-by lagniappe/core/tools/tasks/scheduling.py::add_uncomplete_task_to_queue
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
# @matrix task-completion task-scheduling : complete schedule-queue
def add_uncomplete_task_to_queue(task):
    """Record an uncompletion intent or apply a near-term recurrence now."""
    next_due = task.due_date

    if due_in_home_task_window(next_due):
        task.uncomplete()
        task.due_date = next_due
        return None

    if not CONFIG.production:
        task.uncomplete()
        task.due_date = next_due
        return None

    task._defer_scheduled_uncomplete(scheduled_uncomplete_time())
    return task.scheduled_uncomplete_token


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_add_uncomplete_task_to_queue_future_due_queues_in_production
# @matrix cloud-tasks task-scheduling : durable-uncomplete idempotency post-commit
def dispatch_scheduled_uncomplete(task, *, task_id_suffix=None):
    """Dispatch the durable marker currently persisted on ``task``."""
    token = task.scheduled_uncomplete_token
    schedule_at = task.scheduled_uncomplete_at
    if not token or not schedule_at or not task.completed:
        return None

    identity = token if not task_id_suffix else f"{token}:{task_id_suffix}"
    task_id = f"task-uncomplete-{hashlib.sha256(identity.encode()).hexdigest()[:40]}"
    endpoint = url_for("process.uncomplete_task", _external=True)
    return task_queue.create_task(
        endpoint=endpoint,
        payload={"key": task.urlsafe_key, "token": token},
        schedule_at=schedule_at,
        task_id=task_id,
    )


# @testable true
# @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_recurring
# @matrix task-scheduling : next-due-date recurring
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
# @matrix task-scheduling : next-due-date postponed scheduled
def get_next_scheduled_date(starting_due_date, scheduled):
    """Get the next scheduled date that falls after today."""
    next_due_date = calculate_next_scheduled_due_date(starting_due_date, scheduled)
    while next_due_date and next_due_date <= user_today():
        next_due_date = calculate_next_scheduled_due_date(next_due_date, scheduled)

    return next_due_date


# @testable true
# @tests tests_unit/test_013c_task_scheduling_set_next_due_date.py::test_next_due_date_periodic
# @matrix task-scheduling : next-due-date periodic postponed
def get_next_periodic_date(starting_due_date, periodic):
    """Get the next periodic date that falls after today."""
    next_due_date = calculate_next_recurring_due_date(starting_due_date, periodic)
    while next_due_date and next_due_date <= user_today():
        next_due_date = calculate_next_recurring_due_date(next_due_date, periodic)

    return next_due_date


# @testable true
# @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_scheduled
# @tests tests_unit/test_013b_task_scheduling_skipped.py::test_skipped_scheduled_calendar_boundaries
# @matrix task-scheduling : scheduled skipped
def calculate_skipped_scheduled_tasks(task, scheduled):
    """Calculate how many times a scheduled task should have been completed between the starting due date and today"""
    if _scheduled_rrule_args(scheduled) is None:
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
# @matrix task-scheduling : periodic recurring skipped
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
# @covered-by lagniappe/core/tools/tasks/scheduling.py::calculate_skipped_scheduled_tasks
# @reason monthly occurrence lookup is part of skipped scheduled-task counting
def calculate_monthly_occurrence_for_date(month_start, scheduled):
    """Calculate the configured occurrence bounded to one month."""
    if not isinstance(month_start, datetime) or not isinstance(scheduled, dict):
        return None

    translated = _scheduled_rrule_args({**scheduled, "mode": "monthly"})
    if translated is None:
        return None
    frequency, arguments = translated
    occurrence = rrule(
        frequency,
        dtstart=month_start,
        until=month_start + relativedelta(months=1) - timedelta(microseconds=1),
        **arguments,
    ).after(month_start, inc=True)
    if occurrence is None or (occurrence.year, occurrence.month) != (
        month_start.year,
        month_start.month,
    ):
        return None
    return occurrence.replace(microsecond=month_start.microsecond)


# @testable false
# @covered-by lagniappe/core/tools/tasks/scheduling.py::calculate_skipped_scheduled_tasks
# @reason yearly occurrence lookup is part of skipped scheduled-task counting
def calculate_yearly_occurrence_for_year(year, scheduled):
    """Calculate the configured occurrence bounded to one year."""
    if type(year) is not int or not isinstance(scheduled, dict):
        return None

    translated = _scheduled_rrule_args({**scheduled, "mode": "yearly"})
    if translated is None:
        return None
    frequency, arguments = translated
    year_start = datetime(year, 1, 1, tzinfo=user_timezone())
    occurrence = rrule(
        frequency,
        dtstart=year_start,
        until=year_start + relativedelta(years=1) - timedelta(microseconds=1),
        **arguments,
    ).after(year_start, inc=True)
    if occurrence is None or occurrence.year != year:
        return None
    return occurrence
