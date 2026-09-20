import json
from copy import deepcopy
from unittest.mock import patch
from zoneinfo import ZoneInfo

from google.cloud import datastore
import pytest

from lagniappe.core.exceptions import AIException
from lagniappe.core.entities import Entities
from testing.utility.test_entities import TestEntities

_AI_PATCH = "lagniappe.core.properties.task_scheduling.ai_dates.generate_schedule"
_USER_TZ_PATCH = "lagniappe.core.tools.dates.user_timezone"


# @matrix task-scheduling : ai-generation periodic scheduled prompt-reuse
@pytest.mark.unit
@pytest.mark.parametrize("section_name, form_data, response", [
    ("scheduled", {"schedule-type": "monthly", "monthly-description": "First day"},
     {"text": "Every month on day 1", "type": "specific_day", "day": 1}),
    ("periodic", {"periodic-description": "Every three days", "start-date": "2026-09-20"},
     {"text": "Every three days", "unit": "day", "interval": 3}),
])
def test_generated_schedule_prompt_survives_reload_and_avoids_regeneration(
    section_name, form_data, response
):
    task = TestEntities.get("TASK", {"name": "Scheduled task"})
    schedule = task.properties[section_name]
    schedule.user_prompt = "Previous prompt"
    schedule.section["user_prompt"] = "Legacy prompt"
    prompt = form_data.get("monthly-description") or form_data["periodic-description"]
    with patch(_USER_TZ_PATCH, return_value=ZoneInfo("UTC")):
        schedule.update(form_data)
        with patch(_AI_PATCH, return_value=deepcopy(response)) as generate:
            schedule.create()
        generate.assert_called_once()
        assert schedule.user_prompt == prompt
        assert "user_prompt" not in schedule.section
        stored = datastore.Entity(key=task.key)
        stored.update(deepcopy(task.db))
        stored["schedule"] = json.dumps(task.get_process("schedule"))
        assert json.loads(stored["schedule"])[section_name]["user-prompt"] == prompt

        restored_task = Entities.TASK(stored)
        restored = restored_task.properties[section_name]
        before = deepcopy(restored.section)
        restored.update(form_data)
        with patch(_AI_PATCH, side_effect=AssertionError("Unchanged prompt must be reused")):
            restored.create()
        assert restored.section == before
        assert restored.user_prompt == prompt
        if section_name == "periodic":
            assert restored_task.due_date.date() == task.due_date.date()


# @matrix task-scheduling : recurring update validation
@pytest.mark.unit
def test_task_recurring(get_test_entities):
    """Test Recurring schedule property (ProcessProperty).

    Recurring has:
    - attributes: interval (int), unit (string)
    - update() parses interval, sets error if invalid
    - complete=True on success
    """
    tasks = get_test_entities()
    assert tasks
    for task in tasks:
        form_data = task.test_spec["form_data"]
        expected = task.test_spec["expected"]

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


# @matrix task-scheduling : ai-generation scheduled update validation
@pytest.mark.unit
def test_task_scheduled(get_test_entities):
    """Test Scheduled schedule property (ProcessProperty).

    Scheduled has:
    - modes: daily (no AI), weekly (no AI), monthly (AI), yearly (AI)
    - create() calls ai_dates.generate_schedule (dict or AIException)
    """
    tasks = get_test_entities()
    assert tasks
    for task in tasks:
        form_data = task.test_spec["form_data"]
        expected = task.test_spec["expected"]
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
                with patch(_AI_PATCH, side_effect=AssertionError("Simple schedules need no AI")):
                    scheduled.create()

            elif expected.get("mode") == "weekly":
                assert scheduled.generate is False
                with patch(_AI_PATCH, side_effect=AssertionError("Simple schedules need no AI")):
                    scheduled.create()
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


# @matrix task-scheduling : ai-generation periodic update validation
@pytest.mark.unit
def test_task_periodic(get_test_entities):
    """Test Periodic schedule property (ProcessProperty).

    update() requires start-date; create() uses ai_dates.generate_schedule (dict or AIException).
    """
    tasks = get_test_entities()
    assert tasks
    for task in tasks:
        form_data = task.test_spec["form_data"]
        expected = task.test_spec["expected"]
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
                with patch(_AI_PATCH, side_effect=AssertionError("Existing prompt needs no AI")):
                    periodic.create()
                assert task.due_date.date().isoformat() == form_data["start-date"]
                if "description" in expected:
                    assert periodic.description == expected["description"]
                if "user_prompt" in expected:
                    assert periodic.user_prompt == expected["user_prompt"]


# @matrix task-scheduling : active-process coordinator update
@pytest.mark.unit
def test_task_schedule(get_test_entities):
    """Test Schedule coordinator: update() routes by checkbox; active is the ProcessProperty."""
    tasks = get_test_entities()
    assert tasks
    for task in tasks:
        form_data = task.test_spec["form_data"]
        expected = task.test_spec["expected"]

        schedule = task.properties.schedule
        if expected.get("schedule_type") != "recurring":
            schedule.value["recurring"] = {"interval": 1, "unit": "week"}

        with patch(_USER_TZ_PATCH, return_value=ZoneInfo("UTC")):
            result = schedule.update(form_data)

        expected_type = expected.get("schedule_type")

        if expected_type is None:
            assert result is None
            assert schedule.active is None
            assert schedule.value == {}
        else:
            assert result is not None
            assert result.section_id == expected.get("section_id")
            assert schedule.active is result
            assert set(schedule.value) == {expected["section_id"]}
