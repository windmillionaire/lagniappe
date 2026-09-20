import pytest


# @matrix task-scheduling : periodic recurring skipped
@pytest.mark.unit
def test_skipped_recurring(get_test_entities):
    """Test skipped calculation for recurring/periodic schedules.

    Tests calculate_skipped_recurring_tasks which counts how many
    intervals have passed between starting_due_date and today.
    """
    from datetime import datetime, timezone
    from unittest.mock import patch

    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Chicago")

    # Use a fixed "today" for consistent testing
    mock_today = datetime(2025, 6, 15, 0, 0, 0, tzinfo=tz)

    tasks = get_test_entities()
    assert tasks

    with patch(
        "lagniappe.core.tools.tasks.scheduling.user_today", return_value=mock_today
    ):
        with patch(
            "lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz
        ):
            for task in tasks:
                schedule_data = task.test_spec.get("schedule", {})
                expected = task.test_spec["expected"]
                task_name = task.test_spec["name"]
                due = datetime.fromisoformat(task.test_spec["starting_due_date"]).replace(tzinfo=tz)
                task.due_date = due.astimezone(timezone.utc)

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
    from datetime import datetime, timezone
    from unittest.mock import patch

    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Chicago")

    # Use a fixed "today" for consistent testing - pick a Wednesday
    mock_today = datetime(2025, 6, 18, 0, 0, 0, tzinfo=tz)  # Wednesday

    tasks = get_test_entities()
    assert tasks

    with patch(
        "lagniappe.core.tools.tasks.scheduling.user_today", return_value=mock_today
    ):
        with patch(
            "lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz
        ):
            for task in tasks:
                schedule_data = task.test_spec.get("schedule", {})
                expected = task.test_spec.get("expected", {})
                task_name = task.test_spec.get("name", "Unknown")

                due_date_user_tz = datetime.fromisoformat(task.test_spec["starting_due_date"]).replace(tzinfo=tz)
                task.due_date = due_date_user_tz.astimezone(timezone.utc)

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
    """Both endpoints are excluded, and invalid calendar dates are skipped."""
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
        # Only June 16 and 17 were skipped; the original due date and today are excluded.
        user_today.return_value = datetime(2025, 6, 18, tzinfo=tz)
        assert scheduling.calculate_skipped_scheduled_tasks(
            task_due(2025, 6, 15), {"mode": "daily"}
        ) == 2

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


# @matrix task-scheduling : scheduled skipped exact-boundary timezone
@pytest.mark.unit
@pytest.mark.parametrize("rule, start, today, expected", [
    pytest.param({"mode": "daily"}, "2025-06-17", "2025-06-18", 0, id="daily-yesterday"),
    pytest.param({"mode": "daily"}, "2025-06-16", "2025-06-18", 1, id="daily-two-days-ago"),
    pytest.param({"mode": "daily"}, "2025-06-18", "2025-06-18", 0, id="daily-today"),
    pytest.param({"mode": "daily"}, "2025-06-19", "2025-06-18", 0, id="daily-future"),
    pytest.param({"mode": "daily"}, "2025-06-15T23:30", "2025-06-18", 2, id="local-not-utc-date"),
    pytest.param({"mode": "daily"}, "2025-03-08T09:30", "2025-03-11", 2, id="spring-dst"),
    pytest.param({"mode": "daily"}, "2025-11-01T09:30", "2025-11-04", 2, id="fall-dst"),
    pytest.param({"mode": "weekly", "days": [2]}, "2025-06-11", "2025-06-18", 0, id="weekly-today"),
    pytest.param({"mode": "weekly", "days": [2]}, "2025-06-11", "2025-06-19", 1, id="weekly-yesterday"),
    pytest.param({"mode": "monthly", "type": "specific_day", "day": 25},
                 "2025-01-10", "2025-02-01", 1, id="initial-partial-month"),
    pytest.param({"mode": "monthly", "type": "specific_day", "day": 25},
                 "2025-01-10", "2025-01-25", 0, id="monthly-today"),
    pytest.param({"mode": "monthly", "type": "specific_day", "day": 25},
                 "2025-01-25T09:30", "2025-02-26", 1, id="monthly-excludes-original"),
    pytest.param({"mode": "monthly", "type": "specific_day", "day": 31},
                 "2025-01-30", "2025-04-01", 2, id="initial-month-and-sparse-day"),
    pytest.param({"mode": "monthly", "type": "ordinal_weekday", "ordinal": 1, "weekday": 0},
                 "2025-03-01", "2025-06-18", 4, id="initial-month-ordinal-weekday"),
    pytest.param({"mode": "yearly", "type": "specific_day", "month": 12, "day": 25},
                 "2023-01-01", "2025-06-18", 2, id="initial-partial-year"),
    pytest.param({"mode": "yearly", "type": "specific_day", "month": 12, "day": 25},
                 "2023-01-01", "2024-12-25", 1, id="yearly-today"),
    pytest.param({"mode": "yearly", "type": "specific_day", "month": 12, "day": 25},
                 "2023-12-25T09:30", "2024-12-26", 1, id="yearly-excludes-original"),
    pytest.param({"mode": "yearly", "type": "specific_day", "month": 2, "day": 29},
                 "2024-01-01", "2024-03-01", 1, id="initial-leap-year"),
])
def test_skipped_scheduled_counts_only_occurrences_between_baseline_and_today(
    monkeypatch, rule, start, today, expected
):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from lagniappe.core.tools.tasks import scheduling
    from testing.utility.test_entities import TestEntities

    tz = ZoneInfo("America/Chicago")
    monkeypatch.setattr(scheduling, "user_timezone", lambda: tz)
    monkeypatch.setattr(scheduling, "user_today", lambda: datetime.fromisoformat(today).replace(tzinfo=tz))
    task = TestEntities.get("TASK", {"name": "Missed occurrences"})
    task.due_date = datetime.fromisoformat(start).replace(tzinfo=tz).astimezone(timezone.utc)
    task.properties.scheduled.section.update(rule)

    assert task.properties.schedule.skipped == expected


# @matrix task-scheduling : scheduled skipped postponed
@pytest.mark.unit
@pytest.mark.parametrize("due, postponed", [("2025-06-17", "2025-06-15"), ("2025-06-15", "2025-06-17")])
def test_skipped_scheduled_preserves_earliest_due_date_baseline(monkeypatch, due, postponed):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from lagniappe.core.tools.tasks import scheduling
    from testing.utility.test_entities import TestEntities

    tz = ZoneInfo("America/Chicago")
    monkeypatch.setattr(scheduling, "user_timezone", lambda: tz)
    monkeypatch.setattr(scheduling, "user_today", lambda: datetime(2025, 6, 18, tzinfo=tz))
    task = TestEntities.get("TASK", {"name": "Postponed occurrences"})
    task.due_date = datetime.fromisoformat(due).replace(tzinfo=tz).astimezone(timezone.utc)
    task.db["postponed_from"] = datetime.fromisoformat(postponed).replace(tzinfo=tz).astimezone(timezone.utc)
    task.properties.scheduled.section.update({"mode": "daily"})

    assert task.properties.schedule.skipped == 2  # June 16 and 17.
