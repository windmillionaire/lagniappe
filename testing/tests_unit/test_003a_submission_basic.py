"""Basic form field submission paths (form, AI, import) via ``test_submission_values``."""

import pytest

from lagniappe import CONFIG
from lagniappe.core.properties.form_inputs import DateInput
from testing.utility.ai_report_fakes import _test_user
from testing.utility.test_entities import TestEntities

pytestmark = pytest.mark.unit


# @matrix date-input : ai-value column filter-value import
def test_submission_date_input(get_test_entities, get_schema, test_submission_values):
    """Test DateInput field outputs with timezone handling."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @source lagniappe/core/properties/form_inputs.py::DateInput
# @matrix date-input : ai-value column form-submission import timezone
@pytest.mark.parametrize("method", ["validate_ai", "validate_import", "validate_submission"])
@pytest.mark.parametrize("zone, day", [
    ("America/Los_Angeles", "2026-09-24"),
    ("America/Los_Angeles", "2026-01-24"),
    ("Asia/Tokyo", "2026-09-24"),
])
def test_date_input_uses_explicit_actor_without_request(monkeypatch, method, zone, day):
    """Calendar dates round-trip through storage and display without a session."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(CONFIG, "TEST_CURRENT_USER", None)
    user = _test_user("date-input-owner")
    user.db["timezone"] = zone
    page = TestEntities.get("PAGE", {"name": "Trip"})
    field = DateInput({"id": "input-date", "type": "input", "input": "date"}, entity=page, user=user)
    getattr(field, method)(day)

    assert field.value.tzinfo == timezone.utc
    assert field.value.astimezone(ZoneInfo(zone)).date().isoformat() == day
    if method != "validate_submission":
        assert field.value == datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)

    restored = DateInput(dict(field), entity=page, user=user)
    restored.db_value = field.db_value
    assert restored.ai_value == day
    assert restored.form_value == day
    assert restored.column_value.date().isoformat() == day


# @source lagniappe/core/properties/form_inputs.py::DateInput
# @matrix date-input : ai-value timezone
def test_date_input_preserves_explicit_timezone_offset(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(CONFIG, "TEST_CURRENT_USER", None)
    user = _test_user("date-offset-owner")
    user.db["timezone"] = "America/Los_Angeles"
    field = DateInput({"id": "input-date", "type": "input", "input": "date"},
        entity=TestEntities.get("PAGE", {"name": "Trip"}), user=user)
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
