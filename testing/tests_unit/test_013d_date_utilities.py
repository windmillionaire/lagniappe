"""Unit tests for complex date utility functions in core/tools/tasks/scheduling.py."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from lagniappe.core.tools import dates as generic_dates
from lagniappe.core.tools.tasks import scheduling as dates


# @pair dates:ordinal-weekday
@pytest.mark.unit
def test_find_ordinal_weekday_in_month():
    """Test finding nth weekday or last weekday in a month."""
    # June 2025 starts on a Sunday (weekday 6)
    # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    month_start = datetime(2025, 6, 1)

    # 1st Monday (June 2)
    assert dates.find_ordinal_weekday_in_month(month_start, 1, 0) == datetime(
        2025, 6, 2
    )
    # 3rd Wednesday (June 18)
    assert dates.find_ordinal_weekday_in_month(month_start, 3, 2) == datetime(
        2025, 6, 18
    )
    # Last Friday (June 27)
    assert dates.find_ordinal_weekday_in_month(month_start, -1, 4) == datetime(
        2025, 6, 27
    )
    # 5th Tuesday (None - June 2025 has 4 Tuesdays: 3, 10, 17, 24)
    assert dates.find_ordinal_weekday_in_month(month_start, 5, 1) is None


# @pair dates:monthly-occurrence
@pytest.mark.unit
def test_calculate_next_monthly_occurrence():
    """Test monthly occurrence calculation with various modes."""
    # Wednesday June 18, 2025
    due_date = datetime(2025, 6, 18)

    # Specific day in future: June 20
    sched = {"type": "specific_day", "day": 20}
    assert dates.calculate_next_monthly_occurrence(due_date, sched) == datetime(
        2025, 6, 20
    )

    # Specific day in past: July 15 (June 15 is before June 18)
    sched = {"type": "specific_day", "day": 15}
    assert dates.calculate_next_monthly_occurrence(due_date, sched) == datetime(
        2025, 7, 15
    )

    # First day: July 1
    sched = {"type": "first_day"}
    assert dates.calculate_next_monthly_occurrence(due_date, sched) == datetime(
        2025, 7, 1
    )

    # Last day in future: June 30
    sched = {"type": "last_day"}
    assert dates.calculate_next_monthly_occurrence(due_date, sched) == datetime(
        2025, 6, 30
    )

    # Last day (already past): July 31
    past_due_date = datetime(2025, 6, 30)
    assert dates.calculate_next_monthly_occurrence(past_due_date, sched) == datetime(
        2025, 7, 31
    )

    # Ordinal weekday: 4th Friday (June 27)
    sched = {"type": "ordinal_weekday", "ordinal": 4, "weekday": 4}
    assert dates.calculate_next_monthly_occurrence(due_date, sched) == datetime(
        2025, 6, 27
    )

    # Ordinal weekday (past): July 3rd Monday (July 21)
    # June 3rd Monday was June 16, which is before June 18
    sched = {"type": "ordinal_weekday", "ordinal": 3, "weekday": 0}
    assert dates.calculate_next_monthly_occurrence(due_date, sched) == datetime(
        2025, 7, 21
    )


# @pair dates:yearly-occurrence
@pytest.mark.unit
def test_calculate_next_yearly_occurrence():
    """Test yearly occurrence calculation."""
    from unittest.mock import patch

    tz = ZoneInfo("UTC")
    due_date = datetime(2025, 6, 18, tzinfo=tz)

    with patch("lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz):
        # August 15, 2025
        sched = {"type": "specific_day", "month": 8, "day": 15}
        assert dates.calculate_next_yearly_occurrence(due_date, sched) == datetime(
            2025, 8, 15, tzinfo=tz
        )

        # January 10, 2026 (past in current year)
        sched = {"type": "specific_day", "month": 1, "day": 10}
        assert dates.calculate_next_yearly_occurrence(due_date, sched) == datetime(
            2026, 1, 10, tzinfo=tz
        )

        # Last day of February 2028 (leap year)
        leap_due = datetime(2028, 2, 1, tzinfo=tz)
        sched = {"type": "last_day", "month": 2}
        assert dates.calculate_next_yearly_occurrence(leap_due, sched) == datetime(
            2028, 2, 29, tzinfo=tz
        )


# @pair dates:postponement
@pytest.mark.unit
def test_calculate_postponed_due_date():
    """Test postponement calculation relative to mocked today."""
    from unittest.mock import patch

    tz = ZoneInfo("America/Chicago")
    # Wednesday June 18, 2025
    mock_now = datetime(2025, 6, 18, 10, 0, 0, tzinfo=tz)

    with patch("lagniappe.core.tools.tasks.scheduling.user_timezone", return_value=tz):
        with patch("lagniappe.core.tools.tasks.scheduling.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            # Mock strptime/timedelta/etc if needed, but dates.py uses them from the original datetime module
            # Let's ensure mock_datetime has the same attributes as the real datetime class
            from datetime import datetime as real_datetime

            mock_datetime.side_effect = real_datetime
            mock_datetime.strptime = real_datetime.strptime
            mock_datetime.combine = real_datetime.combine
            mock_datetime.min = real_datetime.min
            mock_datetime.max = real_datetime.max

            # Tomorrow: Thursday June 19
            assert dates.calculate_postponed_due_date(
                "tomorrow"
            ) == mock_now + dates.timedelta(days=1)

            # Weekend: Saturday June 21
            # weekday() 0=Mon, 2=Wed. 5-2=3 days to Saturday.
            assert dates.calculate_postponed_due_date(
                "weekend"
            ) == mock_now + dates.timedelta(days=3)

            # Remaining days this week: Thursday June 19 through Sunday June 22
            for weekday, offset in {
                "thursday": 1,
                "friday": 2,
                "saturday": 3,
                "sunday": 4,
            }.items():
                assert dates.calculate_postponed_due_date(
                    f"this-week-{weekday}"
                ) == mock_now + dates.timedelta(days=offset)

            # Today and elapsed weekdays are not valid postponement targets.
            assert dates.calculate_postponed_due_date("this-week-wednesday") is None
            assert dates.calculate_postponed_due_date("this-week-tuesday") is None

            # Next week: Monday June 23
            # 7-2=5 days to Monday.
            assert dates.calculate_postponed_due_date(
                "next-week"
            ) == mock_now + dates.timedelta(days=5)

            # Explicit next-week weekdays: Monday June 23 through Friday June 27
            for weekday, offset in {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
            }.items():
                assert dates.calculate_postponed_due_date(
                    f"next-week-{weekday}"
                ) == mock_now + dates.timedelta(days=5 + offset)


# @matrix template-formatting : blank-value date input-value string-passthrough
@pytest.mark.unit
def test_format_date_as_input_string():
    assert generic_dates.format_date_as_input_string(None) == ""
    assert generic_dates.format_date_as_input_string("") == ""
    assert generic_dates.format_date_as_input_string("2026-07-13") == "2026-07-13"
    assert generic_dates.format_date_as_input_string(datetime(2026, 7, 13, 18, 30)) == (
        "2026-07-13"
    )
