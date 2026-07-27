import pytest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from lagniappe.core.exceptions import AIException

_AI_PATCH = "lagniappe.core.properties.task_scheduling.ai.generate_schedule"
_USER_TZ_PATCH = "lagniappe.core.tools.dates.user_timezone"


# @features task-scheduling
# @dimensions recurring update validation
@pytest.mark.unit
def test_task_recurring(get_test_entities):
    """Test Recurring schedule property (ProcessProperty).

    Recurring has:
    - attributes: interval (int), unit (string)
    - update() parses interval, sets error if invalid
    - complete=True on success
    """
    for task in get_test_entities():
        form_data = task.test_spec.get("form_data", {})
        expected = task.test_spec.get("expected", {})

        recurring = task.properties.recurring
        recurring.update(form_data)

        if "error" in expected:
            assert recurring.error == expected["error"]
            assert recurring.complete is None
        else:
            assert recurring.error is None
            assert recurring.complete == expected.get("complete")
            assert recurring.interval == expected.get("interval")
            assert recurring.unit == expected.get("unit")

            section = recurring.section
            assert section.get("interval") == expected.get("interval")
            assert section.get("unit") == expected.get("unit")


# @features task-scheduling
# @dimensions scheduled update ai-generation validation
@pytest.mark.unit
def test_task_scheduled(get_test_entities):
    """Test Scheduled schedule property (ProcessProperty).

    Scheduled has:
    - modes: daily (no AI), weekly (no AI), monthly (AI), yearly (AI)
    - create() calls ai.generate_schedule (dict or AIException)
    """
    for task in get_test_entities():
        form_data = task.test_spec.get("form_data", {})
        expected = task.test_spec.get("expected", {})
        ai_response = task.test_spec.get("ai_response")
        existing = task.test_spec.get("existing", {})

        scheduled = task.properties.scheduled

        with patch(_USER_TZ_PATCH, return_value=ZoneInfo("UTC")):
            if existing:
                scheduled.section.update(existing)

            scheduled.update(form_data)

            if "mode" in expected:
                assert scheduled.mode == expected["mode"]

            assert scheduled.generate == expected.get("generate", False)

            if expected.get("mode") == "daily":
                assert scheduled.generate is False

            elif expected.get("mode") == "weekly":
                assert scheduled.generate is False
                assert scheduled.days == expected.get("days")

            elif scheduled.generate and ai_response:
                if ai_response.get("success") is False:
                    with patch(
                        _AI_PATCH,
                        side_effect=AIException(ai_response["error"]),
                    ):
                        scheduled.create()

                    assert scheduled.error == expected["error"]
                    assert scheduled.complete is None
                else:
                    payload = {k: v for k, v in ai_response.items() if k != "success"}
                    with patch(_AI_PATCH, return_value=payload):
                        scheduled.create()

                    assert scheduled.error is None
                    assert scheduled.complete == expected.get("complete")
                    assert scheduled.description == expected.get("description")
                    assert scheduled.type == expected.get("type")

                    if expected.get("type") == "specific_day":
                        assert scheduled.day == expected.get("day")
                    elif expected.get("type") == "ordinal_weekday":
                        assert scheduled.ordinal == expected.get("ordinal")
                        assert scheduled.weekday == expected.get("weekday")

                    if expected.get("mode") == "yearly":
                        assert scheduled.month == expected.get("month")

            elif "error" in expected:
                assert scheduled.error == expected["error"]


# @features task-scheduling
# @dimensions periodic update ai-generation validation
@pytest.mark.unit
def test_task_periodic(get_test_entities):
    """Test Periodic schedule property (ProcessProperty).

    update() requires start-date; create() uses ai.generate_schedule (dict or AIException).
    """
    for task in get_test_entities():
        form_data = task.test_spec.get("form_data", {})
        expected = task.test_spec.get("expected", {})
        ai_response = task.test_spec.get("ai_response")
        existing = task.test_spec.get("existing", {})

        periodic = task.properties.periodic

        with patch(_USER_TZ_PATCH, return_value=ZoneInfo("UTC")):
            if existing:
                periodic.section.update(existing)

            periodic.update(form_data)

            assert periodic.generate == expected.get("generate", False)

            if periodic.generate and ai_response:
                if ai_response.get("success") is False:
                    with patch(
                        _AI_PATCH,
                        side_effect=AIException(ai_response["error"]),
                    ):
                        periodic.create()

                    assert periodic.error == expected["error"]
                    assert periodic.complete is None
                else:
                    payload = {k: v for k, v in ai_response.items() if k != "success"}
                    with patch(_AI_PATCH, return_value=payload):
                        periodic.create()

                    assert periodic.error is None
                    assert periodic.complete == expected.get("complete")
                    assert periodic.description == expected.get("description")
                    assert periodic.unit == expected.get("unit")
                    assert periodic.interval == expected.get("interval")

            elif "error" in expected:
                assert periodic.error == expected["error"]
            else:
                if "description" in expected:
                    assert periodic.description == expected["description"]
                if "user_prompt" in expected:
                    assert periodic.user_prompt == expected["user_prompt"]


# @features task-scheduling
# @dimensions coordinator update active-process
@pytest.mark.unit
def test_task_schedule(get_test_entities):
    """Test Schedule coordinator: update() routes by checkbox; active is the ProcessProperty."""
    for task in get_test_entities():
        form_data = task.test_spec.get("form_data", {})
        expected = task.test_spec.get("expected", {})

        schedule = task.properties.schedule

        with patch(_USER_TZ_PATCH, return_value=ZoneInfo("UTC")):
            result = schedule.update(form_data)

        expected_type = expected.get("schedule_type")

        if expected_type is None:
            assert result is None
        else:
            assert result is not None
            assert result.section_id == expected.get("section_id")
            assert schedule.active is result
            assert schedule.active.section_id == expected.get("section_id")
