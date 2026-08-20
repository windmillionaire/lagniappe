"""``SubmissionProperty`` and input edge cases (``004e_submission_behavior.json``).

Not ``Form`` entity lifecycle (``Form.update`` / ``Form.save``); uses attached forms
only to load schemas for submission fields.
"""

import json
from types import SimpleNamespace

import pytest

from lagniappe.core.mixins import SearchMixin
from lagniappe.core.properties.form_table import Table
from lagniappe.core.properties.base_submission import SubmissionProperty
from testing.utility.test_entities import TestEntities
from testing.utility.mock_submission import WebFormSubmission


class _BooleanSearchField(SearchMixin):
    label = "Flag"
    value = True


class _BlankSearchField(SearchMixin):
    label = "Empty"
    value = ""


class _ScalarSearchSubmission(SubmissionProperty):
    @property
    def fields(self):
        return {"flag": _BooleanSearchField()}


class _BlankSearchSubmission(SubmissionProperty):
    @property
    def fields(self):
        return {"empty": _BlankSearchField()}


def _submission_page(schema_name, name="Submission behavior"):
    entity = TestEntities.get(
        "PAGE",
        {
            "name": name,
            "hash": name.lower().replace(" ", "_"),
            "form": {
                "name": f"{name} Form",
                "hash": f"{name.lower().replace(' ', '_')}_form",
                "schema": schema_name,
            },
        },
    )
    return entity


# @features submission
# @dimensions db-value empty-field
@pytest.mark.unit
def test_submission_db_value_omits_unset_number_field(get_test_entities, get_schema):
    """``SubmissionProperty.db_value`` drops keys whose ``db_value`` is ``None``."""
    for entity in get_test_entities():
        entity.form.schema = get_schema("submission_two_numbers")
        entity.form_submission(WebFormSubmission({"num_a": "1"}))
        assert entity.properties.submission.db_value == {"num_a": 1.0}


# @features checkbox submission
# @dimensions missing-field unset projection
@pytest.mark.unit
def test_missing_stored_checkbox_is_unset_and_omitted(get_schema):
    entity = _submission_page("checkbox_only", "Missing checkbox")
    entity.form.schema = get_schema("checkbox_only")

    field = entity.properties.submission.fields["checkbox-ab12"]

    assert field.is_set is False
    assert field.value is None
    assert field.form_value is None
    assert field.filter_value is None
    assert field.db_value is None
    assert entity.properties.submission.db_value == {}


# @features checkbox submission
# @dimensions form-submit explicit-false
@pytest.mark.unit
def test_full_form_submit_missing_checkbox_persists_explicit_false(get_schema):
    entity = _submission_page("checkbox_only", "Unchecked checkbox")
    entity.form.schema = get_schema("checkbox_only")

    entity.form_submission(WebFormSubmission({}))

    saved = json.loads(entity.db["submission"])
    field = entity.properties.submission.fields["checkbox-ab12"]
    assert saved == {"checkbox-ab12": False}
    assert field.value is False
    assert field.filter_value is False
    assert field.db_value is False


# @features checkbox submission
# @dimensions stored-false load-save
@pytest.mark.unit
def test_stored_explicit_checkbox_false_survives_load_save(get_schema):
    entity = _submission_page("checkbox_only", "Stored false checkbox")
    entity.form.schema = get_schema("checkbox_only")
    entity.db["submission"] = json.dumps({"checkbox-ab12": False})

    field = entity.properties.submission.fields["checkbox-ab12"]
    assert field.value is False
    assert field.db_value is False

    entity.save_submission()

    assert json.loads(entity.db["submission"]) == {"checkbox-ab12": False}


# @features checkbox submission
# @dimensions stored-null normalization
@pytest.mark.unit
def test_stored_null_checkbox_normalizes_away_on_resave(get_schema):
    entity = _submission_page("checkbox_only", "Null checkbox")
    entity.form.schema = get_schema("checkbox_only")
    entity.db["submission"] = json.dumps({"checkbox-ab12": None})

    field = entity.properties.submission.fields["checkbox-ab12"]
    assert field.is_set is False
    assert field.value is None
    assert entity.properties.submission.db_value == {}

    entity.save_submission()

    assert "submission" not in entity.db


# @features submission
# @dimensions empty-submission blank-persistence
@pytest.mark.unit
def test_empty_submission_pops_submission_db_key(get_schema):
    entity = _submission_page("text_input_only", "Empty submission")
    entity.form.schema = get_schema("text_input_only")
    entity.db["submission"] = json.dumps({"input-textab12": "old"})

    entity.form_submission(WebFormSubmission({}))

    assert "submission" not in entity.db


# @features html-field submission
# @dimensions submit-boundary asset-isolation
@pytest.mark.unit
def test_html_field_is_ignored_by_form_submission(get_schema):
    entity = _submission_page("complex_types", "HTML field ignored")
    entity.form.schema = get_schema("complex_types")

    entity.form_submission(
        WebFormSubmission({"html-instructqr": "<p>Do not save me</p>"})
    )

    html_field = entity.properties.submission.fields["html-instructqr"]
    assert html_field.db_value is None
    assert html_field.form_value is None
    assert "submission" not in entity.db
    assert "html-instructqr" not in entity.assets


# @features cache
# @dimensions default-fields cache-deduplication
@pytest.mark.unit
def test_default_entity_fields_are_not_duplicated_in_submission_search_cache():
    entity = _submission_page("default field search", "Original page name")
    entity.description = "Original page description"
    entity.form.schema = [
        {"id": "name", "type": "input", "input": "text", "title": "Name"},
        {"id": "description", "type": "textarea", "title": "Description"},
        {"id": "headline", "type": "input", "input": "text", "title": "Headline"},
    ]

    entity.form_submission(
        WebFormSubmission(
            {
                "name": "Submitted page name",
                "description": "Submitted page description",
                "headline": "Submitted headline",
            }
        )
    )

    cache = entity.to_cache

    assert cache["name"] == "Submitted page name"
    assert cache["desc"] == "Submitted page description"
    assert cache["keys"] == ["Headline"]
    assert cache["values"] == ["Submitted headline"]
    assert entity.name == "Submitted page name"
    assert entity.description == "Submitted page description"


# @pairs filter-index:unset-values filter-index:entity-metadata
@pytest.mark.unit
def test_unset_submission_fields_do_not_erase_entity_filter_metadata():
    entity = _submission_page("unset defaults", "Canonical page name")
    entity.description = "Canonical page description"
    entity.form.schema = [
        {"id": "name", "type": "input", "input": "text", "title": "Heading"},
        {"id": "description", "type": "textarea", "title": "Summary"},
    ]

    values = entity.to_filter_index()

    assert values["name"] == "Canonical page name"
    assert values["description"] == "Canonical page description"


# @features form-table
# @dimensions search-value
@pytest.mark.unit
def test_submission_search_value_merges_table_column_labels(
    get_test_entities, get_schema, test_submission_values
):
    """Search index merges top-level text labels with ``[table] column`` labels."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)
        cache = entity.to_cache
        assert "Headline" in cache["keys"]
        assert "[Items] Note" in cache["keys"]
        assert "Top story" in cache["values"]
        assert "Row one" in cache["values"]


# @features form-table
# @dimensions search-value multiple-rows
@pytest.mark.unit
def test_table_search_keys_match_multiple_row_values():
    """Table search labels repeat per populated row value for snippet lookup."""
    table = Table(
        {
            "id": "items",
            "type": "table",
            "title": "Items",
            "columns": [
                {"id": "row_note", "type": "input", "input": "text", "title": "Note"},
                {"id": "row_code", "type": "input", "input": "text", "title": "Code"},
            ],
        },
        entity=SimpleNamespace(entity_kind="page", submission={}),
    )
    table.value = {
        "rows": [
            {"row_note": "Row one", "row_code": "A1"},
            {"row_note": "Row two", "row_code": ""},
        ]
    }

    assert table.search_key == ["[Items] Note", "[Items] Code", "[Items] Note"]
    assert table.search_value == ["Row one", "A1", "Row two"]


# @features submission
# @dimensions search-value
@pytest.mark.unit
def test_submission_search_value_accepts_scalar_boolean_values():
    """``SubmissionProperty.search_value`` accepts scalar non-string values."""
    submission = _ScalarSearchSubmission()
    assert submission.search_value == {"keys": ["Flag"], "values": [True]}


# @features submission
# @dimensions search-value
@pytest.mark.unit
def test_submission_search_value_omits_blank_search_fields():
    """Blank search fields do not leave key-only cache lists behind."""
    submission = _BlankSearchSubmission()
    assert submission.search_value == {}


# @features email-input
# @dimensions form-submission validation
@pytest.mark.unit
def test_submission_email_form_accepts_non_matching_string(
    get_test_entities, get_schema, test_submission_values
):
    """Form path uses base ``validate_submission``; regex validation is import/AI-only."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features number-input
# @dimensions form-submission zero
@pytest.mark.unit
def test_submission_number_form_accepts_zero(
    get_test_entities, get_schema, test_submission_values
):
    """Numeric zero is truthy enough for ``NumberInput.validate_submission``."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features time-input
# @dimensions form-submission validation
@pytest.mark.unit
def test_submission_time_form_invalid_format_raises(get_test_entities, get_schema):
    """Bad ``HH:MM`` on form submit raises from ``strptime`` (not caught)."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        with pytest.raises(ValueError):
            entity.form_submission(WebFormSubmission({"input-timecd34": "25:99"}))
