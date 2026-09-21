import pytest
import json

from lagniappe.core.properties.form_table import Table

pytestmark = pytest.mark.unit


# @pair submission:db-value
def test_submission_value(get_test_entities, get_schema):
    """Test that submission.value loads saved submission from entity.db."""

    for entity in get_test_entities():
        schema = get_schema(entity.test_spec["form"]["schema"])
        entity.form.schema = schema

        test_submission = entity.test_spec.get("submission", {})

        # Arrange storage directly; the absent-key fixture must stay absent.
        if "submission" in entity.test_spec:
            entity.db["submission"] = json.dumps(test_submission)

        assert entity.submission == test_submission
        assert entity.properties.submission.db_value == test_submission


# @pair submission:fields
def test_submission_fields(get_test_entities, get_schema):
    """Test that submission.fields returns fields matching the form schema."""
    for entity in get_test_entities():
        schema = get_schema(entity.test_spec["form"]["schema"])
        entity.form.schema = schema

        fields = entity.properties.submission.fields

        assert len(fields) == len(schema)
        assert set(fields.keys()) == {el["id"] for el in schema}


# @pair submission:patch
def test_submission_patch(get_test_entities, get_schema):
    """Test that submission.patch updates a field and returns it."""
    for entity in get_test_entities():
        schema = get_schema(entity.test_spec["form"]["schema"])
        entity.form.schema = schema

        submission = entity.properties.submission
        field_id = schema[0]["id"]

        field = submission.patch(field_id, "patched value")

        assert field.id == field_id
        assert field.value == "patched value"
        assert submission.fields[field_id] is field
        assert submission.db_value == {field_id: "patched value"}


# @pair submission:save
def test_submission_save(get_test_entities, get_schema):
    """Test that assigning submission.value persists aggregated field db_values."""

    for entity in get_test_entities():
        schema = get_schema(entity.test_spec["form"]["schema"])
        entity.form.schema = schema

        submission = entity.properties.submission
        field_id = schema[0]["id"]

        submission.fields[field_id].value = "test value"
        submission.value = submission.db_value

        saved = json.loads(entity.db["submission"])
        assert saved == {field_id: "test value"}


# @matrix submission : condition-matching visibility
def test_submission_is_visible(get_test_entities, get_schema):
    """Test submission.is_visible for single- and multi-condition checkbox gates."""

    for entity in get_test_entities():
        schema = get_schema(entity.test_spec["form"]["schema"])
        entity.form.schema = schema

        if "submission" in entity.test_spec:
            entity.db["submission"] = json.dumps(entity.test_spec["submission"])

        submission = entity.properties.submission
        expectations = entity.test_spec["visibility"]
        assert expectations, f"{entity.name}: visibility scenario has no expectations"
        for field_id, expected_visible in expectations.items():
            assert submission.is_visible(field_id) == expected_visible, (
                f"{entity.name}: visibility of {field_id}"
            )


# @pair submission:tables
def test_submission_tables(get_test_entities, get_schema):
    """Test that submission.tables returns only Table fields."""

    for entity in get_test_entities():
        schema = get_schema(entity.test_spec["form"]["schema"])
        entity.form.schema = schema

        tables = entity.properties.submission.tables
        expected_ids = [el["id"] for el in schema if el["type"] == "table"]

        assert [field.id for field in tables] == expected_ids
        assert all(isinstance(field, Table) for field in tables)
