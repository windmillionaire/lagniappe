"""Basic form field submission paths (form, AI, import) via ``test_submission_values``."""

import pytest

pytestmark = pytest.mark.unit


# @features date-input
# @dimensions ai-value, filter-value, import, column
def test_submission_date_input(get_test_entities, get_schema, test_submission_values):
    """Test DateInput field outputs with timezone handling."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features time-input
# @dimensions ai-value, filter-value, import, column
def test_submission_time_input(get_test_entities, get_schema, test_submission_values):
    """Test TimeInput field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features text-input
# @dimensions ai-value, filter-value, search-value, import
def test_submission_text_input(get_test_entities, get_schema, test_submission_values):
    """Test TextInput field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features submission text-input
# @dimensions column empty-field empty-value
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


# @features number-input
# @dimensions ai-value, filter-value, import
def test_submission_number_input(get_test_entities, get_schema, test_submission_values):
    """Test NumberInput field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features email-input
# @dimensions ai-value, filter-value, import
def test_submission_email_input(get_test_entities, get_schema, test_submission_values):
    """Test EmailInput field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features tel-input
# @dimensions ai-value, filter-value, import, formatting
def test_submission_tel_input(get_test_entities, get_schema, test_submission_values):
    """Test TelInput field outputs with E.164 normalization."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features checkbox
# @dimensions ai-value, filter-value, import
def test_submission_checkbox(get_test_entities, get_schema, test_submission_values):
    """Test Checkbox field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features textarea
# @dimensions ai-value, filter-value, search-value, import
def test_submission_textarea(get_test_entities, get_schema, test_submission_values):
    """Test Textarea field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)
