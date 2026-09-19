"""Basic form field submission paths (form, AI, import) via ``test_submission_values``."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from lagniappe import CONFIG
from lagniappe.core.properties.form_inputs import DateInput
from lagniappe.core.tools import dates
from testing.utility.ai_report_fakes import _test_user
from testing.utility.test_entities import TestEntities

pytestmark = pytest.mark.unit


@pytest.fixture
def fixed_date_clock(monkeypatch):
    """Fix only the clock read; keep date parsing and timezone conversion real."""

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 9, 19, 12, 34, 56, 123456, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(dates, "datetime", FixedDateTime)


# @matrix date-input : ai-value column filter-value import
def test_submission_date_input(
    get_test_entities, get_schema, test_submission_values, fixed_date_clock
):
    """Test DateInput field outputs with timezone handling."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @source lagniappe/core/properties/form_inputs.py::DateInput
# @matrix date-input : ai-value column filter-value form-submission import timezone
@pytest.mark.parametrize(
    "method", ["validate_ai", "validate_import", "validate_submission"]
)
@pytest.mark.parametrize(
    "zone, day, midnight_utc, form_utc",
    [
        (
            "America/Los_Angeles",
            "2026-09-24",
            "2026-09-24T07:00:00+00:00",
            "2026-09-24T12:34:56.123456+00:00",
        ),
        (
            "America/Los_Angeles",
            "2026-01-24",
            "2026-01-24T08:00:00+00:00",
            "2026-01-24T13:34:56.123456+00:00",
        ),
        (
            "Asia/Tokyo",
            "2026-09-24",
            "2026-09-23T15:00:00+00:00",
            "2026-09-24T12:34:56.123456+00:00",
        ),
    ],
    ids=["los-angeles-summer", "los-angeles-winter", "tokyo-previous-utc-day"],
)
def test_date_input_uses_explicit_actor_without_request(
    monkeypatch, fixed_date_clock, method, zone, day, midnight_utc, form_utc
):
    """Calendar dates round-trip through storage and display without a session."""
    monkeypatch.setattr(CONFIG, "TEST_CURRENT_USER", None)
    user = _test_user("date-input-owner")
    user.db["timezone"] = zone
    page = TestEntities.get("PAGE", {"name": "Trip"})
    field = DateInput(
        {"id": "input-date", "type": "input", "input": "date"}, entity=page, user=user
    )
    getattr(field, method)(day)

    # Form dates preserve today's local clock; AI/import date-only values use midnight.
    stored_utc = form_utc if method == "validate_submission" else midnight_utc
    expected_utc = datetime.fromisoformat(stored_utc)
    assert field.value.tzinfo == timezone.utc
    assert field.value == expected_utc
    assert field.value.astimezone(ZoneInfo(zone)).date().isoformat() == day
    assert field.db_value == stored_utc

    restored = DateInput(dict(field), entity=page, user=user)
    restored.db_value = field.db_value
    assert restored.ai_value == day
    assert restored.form_value == day
    assert restored.column_value.date().isoformat() == day
    assert restored.filter_value == expected_utc.timestamp()


# @source lagniappe/core/properties/form_inputs.py::DateInput
# @matrix date-input : ai-value timezone
def test_date_input_preserves_explicit_timezone_offset(monkeypatch):
    monkeypatch.setattr(CONFIG, "TEST_CURRENT_USER", None)
    user = _test_user("date-offset-owner")
    user.db["timezone"] = "America/Los_Angeles"
    field = DateInput(
        {"id": "input-date", "type": "input", "input": "date"},
        entity=TestEntities.get("PAGE", {"name": "Trip"}),
        user=user,
    )
    field.validate_ai("2026-09-24T12:00:00+09:00")
    assert field.value == datetime(2026, 9, 24, 3, tzinfo=timezone.utc)
    assert field.ai_value == "2026-09-23"


# @matrix time-input : ai-value column filter-value import
def test_submission_time_input(get_test_entities, get_schema, test_submission_values):
    """Test TimeInput field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix text-input : ai-value filter-value import search-value
def test_submission_text_input(get_test_entities, get_schema, test_submission_values):
    """Test TextInput field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix submission text-input : column empty-field empty-value
def test_submission_text_input_empty_column_value_is_blank(
    get_test_entities, get_schema
):
    """Submission fields with no value render as blank table cells."""
    entity = get_test_entities()[0]
    entity.form.schema = get_schema("text_input_only")

    field = entity.properties.submission.fields["input-textab12"]

    assert entity.submission == {}
    assert field.value is None
    assert field.column_value is None


# @matrix number-input : ai-value filter-value import
def test_submission_number_input(get_test_entities, get_schema, test_submission_values):
    """Test NumberInput field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix email-input : ai-value filter-value import
def test_submission_email_input(get_test_entities, get_schema, test_submission_values):
    """Test EmailInput field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix tel-input : ai-value filter-value formatting import
def test_submission_tel_input(get_test_entities, get_schema, test_submission_values):
    """Test TelInput field outputs with E.164 normalization."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix checkbox : ai-value filter-value import
def test_submission_checkbox(get_test_entities, get_schema, test_submission_values):
    """Test Checkbox field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix textarea : ai-value filter-value import search-value
def test_submission_textarea(get_test_entities, get_schema, test_submission_values):
    """Test Textarea field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)
