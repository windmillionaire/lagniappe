import pytest


# @matrix task-scheduling : periodic recurring skipped
@pytest.mark.unit
def test_skipped_recurring(get_test_entities):
    """Test skipped calculation for recurring/periodic schedules.

    Tests calculate_skipped_recurring_tasks which counts how many
    intervals have passed between starting_due_date and today.
    """
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Chicago")

    # Use a fixed "today" for consistent testing
    mock_today = datetime(2025, 6, 15, 0, 0, 0, tzinfo=tz)

    with patch(
        "lagniappe.core.tools.tasks.scheduling.user_today", return_value=mock_today
    ):
        with patch(
            "lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz
        ):
            for task in get_test_entities():
                schedule_data = task.test_spec.get("schedule", {})
                days_ago = task.test_spec.get("days_ago", 0)
                expected = task.test_spec.get("expected", {})
                task_name = task.test_spec.get("name", "Unknown")

                # Set due_date based on days_ago (in user tz, then convert to UTC for storage)
                due_date_user_tz = mock_today - timedelta(days=days_ago)
                due_date_utc = due_date_user_tz.astimezone(timezone.utc)
                task.db["due_date"] = due_date_utc

                # Set up the periodic section
                periodic = task.properties.periodic
                periodic.section.update(schedule_data)

                # Calculate skipped through schedule property
                schedule = task.properties.schedule
                skipped = schedule.skipped

                assert skipped == expected["skipped"], (
                    f"Failed for '{task_name}': expected {expected['skipped']}, got {skipped}"
                )


# @matrix task-scheduling : scheduled skipped
@pytest.mark.unit
def test_skipped_scheduled(get_test_entities):
    """Test skipped calculation for scheduled schedules.

    Tests calculate_skipped_scheduled_tasks which counts missed
    occurrences between starting_due_date and today for:
    - daily: simple day count
    - weekly: count matching weekdays
    - monthly: count monthly occurrences
    - yearly: count yearly occurrences
    """
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from dateutil.relativedelta import relativedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Chicago")

    # Use a fixed "today" for consistent testing - pick a Wednesday
    mock_today = datetime(2025, 6, 18, 0, 0, 0, tzinfo=tz)  # Wednesday

    with patch(
        "lagniappe.core.tools.tasks.scheduling.user_today", return_value=mock_today
    ):
        with patch(
            "lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz
        ):
            for task in get_test_entities():
                schedule_data = task.test_spec.get("schedule", {})
                expected = task.test_spec.get("expected", {})
                task_name = task.test_spec.get("name", "Unknown")

                # Calculate due_date based on test spec (in user tz)
                if "days_ago" in task.test_spec:
                    days_ago = task.test_spec["days_ago"]
                    from_weekday = task.test_spec.get("from_weekday")

                    if from_weekday is not None:
                        # Find the most recent occurrence of that weekday, then go back days_ago
                        current_weekday = mock_today.weekday()
                        days_to_weekday = (current_weekday - from_weekday) % 7
                        if days_to_weekday == 0 and days_ago > 0:
                            days_to_weekday = 7
                        due_date_user_tz = mock_today - timedelta(
                            days=days_to_weekday + days_ago - 7
                        )
                    else:
                        due_date_user_tz = mock_today - timedelta(days=days_ago)

                elif "months_ago" in task.test_spec:
                    months_ago = task.test_spec["months_ago"]
                    from_day = task.test_spec.get("from_day", 1)
                    due_date_user_tz = mock_today - relativedelta(months=months_ago)
                    try:
                        due_date_user_tz = due_date_user_tz.replace(day=from_day)
                    except ValueError:
                        due_date_user_tz = due_date_user_tz.replace(day=28)

                elif "years_ago" in task.test_spec:
                    years_ago = task.test_spec["years_ago"]
                    from_month = task.test_spec.get("from_month", 1)
                    due_date_user_tz = mock_today - relativedelta(years=years_ago)
                    due_date_user_tz = due_date_user_tz.replace(month=from_month, day=1)

                else:
                    due_date_user_tz = mock_today

                # Convert to UTC for storage
                due_date_utc = due_date_user_tz.astimezone(timezone.utc)
                task.db["due_date"] = due_date_utc

                # Set up the scheduled section
                scheduled = task.properties.scheduled
                scheduled.section.update(schedule_data)

                # Calculate skipped through schedule property
                schedule = task.properties.schedule
                skipped = schedule.skipped

                assert skipped == expected["skipped"], (
                    f"Failed for '{task_name}': due={due_date_user_tz}, today={mock_today}, "
                    f"expected {expected['skipped']}, got {skipped}"
                )


# @matrix task-scheduling : scheduled skipped
@pytest.mark.unit
def test_skipped_scheduled_calendar_boundaries():
    """Skipped counts retain their endpoint rules while sparse dates are skipped."""
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import patch

    from zoneinfo import ZoneInfo

    from lagniappe.core.tools.tasks import scheduling

    tz = ZoneInfo("America/Chicago")

    def task_due(year, month, day):
        return SimpleNamespace(
            due_date=datetime(year, month, day, tzinfo=tz),
            postponed_from=None,
        )

    with (
        patch(
            "lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz
        ),
        patch("lagniappe.core.tools.tasks.scheduling.user_today") as user_today,
    ):
        # Daily counting includes the occurrence on today.
        user_today.return_value = datetime(2025, 6, 18, tzinfo=tz)
        assert scheduling.calculate_skipped_scheduled_tasks(
            task_due(2025, 6, 15), {"mode": "daily"}
        ) == 3

        # Weekly counting excludes the selected weekday on today.
        assert scheduling.calculate_skipped_scheduled_tasks(
            task_due(2025, 6, 11), {"mode": "weekly", "days": [2]}
        ) == 0

        # A day-31 rule has no February occurrence but does occur in March.
        user_today.return_value = datetime(2025, 4, 1, tzinfo=tz)
        assert scheduling.calculate_skipped_scheduled_tasks(
            task_due(2025, 1, 31),
            {"mode": "monthly", "type": "specific_day", "day": 31},
        ) == 1

        # February 29 occurs once between 2020 and March 2025.
        user_today.return_value = datetime(2025, 3, 1, tzinfo=tz)
        assert scheduling.calculate_skipped_scheduled_tasks(
            task_due(2020, 2, 29),
            {
                "mode": "yearly",
                "type": "specific_day",
                "month": 2,
                "day": 29,
            },
        ) == 1

        assert scheduling.calculate_skipped_scheduled_tasks(
            task_due(2020, 1, 1),
            {"mode": "weekly", "days": []},
        ) == 0
