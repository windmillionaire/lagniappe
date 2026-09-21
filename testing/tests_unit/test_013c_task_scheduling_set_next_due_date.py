import pytest


# @matrix task-scheduling : next-due-date recurring
@pytest.mark.unit
def test_next_due_date_recurring(get_test_entities):
    """Test set_next_due_date for recurring schedules.

    Recurring schedules calculate next due date from user_today()
    by adding the interval (days/weeks/months/years).
    """
    from datetime import datetime, timezone
    from unittest.mock import patch

    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Chicago")
    mock_today = datetime(2025, 6, 15, 0, 0, 0, tzinfo=tz)

    with patch(
        "lagniappe.core.tools.tasks.scheduling.user_today", return_value=mock_today
    ):
        with patch(
            "lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz
        ):
            tasks = get_test_entities()
            assert tasks
            for task in tasks:
                schedule_data = task.test_spec.get("schedule", {})
                expected = task.test_spec["expected"]
                task_name = task.test_spec.get("name", "Unknown")

                # Set up the recurring section
                recurring = task.properties.recurring
                recurring.section.update(schedule_data)

                # Call set_next_due_date
                schedule = task.properties.schedule
                schedule.set_next_due_date()

                expected_date = datetime.fromisoformat(expected["expected_date"]).replace(tzinfo=tz)

                assert task.due_date is not None, (
                    f"Failed for '{task_name}': due_date is None"
                )
                assert task.due_date.isoformat() == expected_date.astimezone(timezone.utc).isoformat(), (
                    f"Failed for '{task_name}': expected {expected_date}, got {task.due_date}"
                )


# @matrix task-scheduling : next-due-date postponed scheduled
@pytest.mark.unit
def test_next_due_date_scheduled(get_test_entities):
    """Test set_next_due_date for scheduled schedules.

    Scheduled schedules calculate next due date from the original due_date
    (or min(postponed_from, due_date)) and find the next occurrence after today.
    """
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Chicago")
    # Use Wednesday June 18, 2025 as mock_today (same as test_013b)
    mock_today = datetime(2025, 6, 18, 0, 0, 0, tzinfo=tz)

    with patch(
        "lagniappe.core.tools.tasks.scheduling.user_today", return_value=mock_today
    ):
        with patch(
            "lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz
        ):
            tasks = get_test_entities()
            assert tasks
            for task in tasks:
                schedule_data = task.test_spec.get("schedule", {})
                expected = task.test_spec["expected"]
                task_name = task.test_spec.get("name", "Unknown")

                # Set due_date based on days_ago
                days_ago = task.test_spec.get("days_ago", 0)
                due_date_user_tz = mock_today - timedelta(days=days_ago)
                due_date_utc = due_date_user_tz.astimezone(timezone.utc)
                task.db["due_date"] = due_date_utc

                # Set postponed_from if specified
                if "postponed_from_days_ago" in task.test_spec:
                    postponed_days_ago = task.test_spec["postponed_from_days_ago"]
                    postponed_date = mock_today - timedelta(days=postponed_days_ago)
                    task.db["postponed_from"] = postponed_date.astimezone(timezone.utc)

                # Set up the scheduled section
                scheduled = task.properties.scheduled
                scheduled.section.update(schedule_data)

                # Call set_next_due_date
                schedule = task.properties.schedule
                schedule.set_next_due_date()

                # Verify the result
                assert task.due_date is not None, (
                    f"Failed for '{task_name}': due_date is None"
                )

                assert ("days_from_today" in expected) != ("expected_date" in expected)
                if "days_from_today" in expected:
                    expected_date = mock_today + timedelta(
                        days=expected["days_from_today"]
                    )
                    assert task.due_date.isoformat() == expected_date.astimezone(timezone.utc).isoformat(), (
                        f"Failed for '{task_name}': expected {expected_date}, got {task.due_date}"
                    )
                elif "expected_date" in expected:
                    expected_date = datetime.strptime(
                        expected["expected_date"], "%Y-%m-%d"
                    ).replace(tzinfo=tz)
                    assert task.due_date.isoformat() == expected_date.astimezone(timezone.utc).isoformat(), (
                        f"Failed for '{task_name}': expected {expected_date}, got {task.due_date}"
                    )

                # Verify postponed_from was cleared
                assert task.db.get("postponed_from") is None, (
                    f"Failed for '{task_name}': postponed_from should be cleared"
                )


# @matrix task-scheduling : next-due-date periodic postponed
@pytest.mark.unit
def test_next_due_date_periodic(get_test_entities):
    """Test set_next_due_date for periodic schedules.

    Periodic schedules calculate next due date from the original due_date
    (or min(postponed_from, due_date)) and add intervals until after today.
    """
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from dateutil.relativedelta import relativedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Chicago")
    # Use Wednesday June 18, 2025 as mock_today
    mock_today = datetime(2025, 6, 18, 0, 0, 0, tzinfo=tz)

    with patch(
        "lagniappe.core.tools.tasks.scheduling.user_today", return_value=mock_today
    ):
        with patch(
            "lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz
        ):
            tasks = get_test_entities()
            assert tasks
            for task in tasks:
                schedule_data = task.test_spec.get("schedule", {})
                expected = task.test_spec["expected"]
                task_name = task.test_spec.get("name", "Unknown")

                # Set due_date based on days_ago or months_ago
                if "days_ago" in task.test_spec:
                    days_ago = task.test_spec["days_ago"]
                    due_date_user_tz = mock_today - timedelta(days=days_ago)
                elif "months_ago" in task.test_spec:
                    months_ago = task.test_spec["months_ago"]
                    due_date_user_tz = mock_today - relativedelta(months=months_ago)
                else:
                    due_date_user_tz = mock_today

                due_date_utc = due_date_user_tz.astimezone(timezone.utc)
                task.db["due_date"] = due_date_utc

                # Set postponed_from if specified
                if "postponed_from_days_ago" in task.test_spec:
                    postponed_days_ago = task.test_spec["postponed_from_days_ago"]
                    postponed_date = mock_today - timedelta(days=postponed_days_ago)
                    task.db["postponed_from"] = postponed_date.astimezone(timezone.utc)

                # Set up the periodic section
                periodic = task.properties.periodic
                periodic.section.update(schedule_data)

                # Call set_next_due_date
                schedule = task.properties.schedule
                schedule.set_next_due_date()

                # Verify the result
                assert task.due_date is not None, (
                    f"Failed for '{task_name}': due_date is None"
                )

                assert ("days_from_today" in expected) != ("expected_date" in expected)
                if "days_from_today" in expected:
                    expected_date = mock_today + timedelta(
                        days=expected["days_from_today"]
                    )
                    assert task.due_date.isoformat() == expected_date.astimezone(timezone.utc).isoformat(), (
                        f"Failed for '{task_name}': expected {expected_date}, got {task.due_date}"
                    )
                elif "expected_date" in expected:
                    expected_date = datetime.strptime(
                        expected["expected_date"], "%Y-%m-%d"
                    ).replace(tzinfo=tz)
                    assert task.due_date.isoformat() == expected_date.astimezone(timezone.utc).isoformat(), (
                        f"Failed for '{task_name}': expected {expected_date}, got {task.due_date}"
                    )

                # Verify postponed_from was cleared
                assert task.db.get("postponed_from") is None, (
                    f"Failed for '{task_name}': postponed_from should be cleared"
                )
