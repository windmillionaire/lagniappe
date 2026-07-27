"""``Schema`` / ``SchemaFields`` AI ingress and field helpers (``004b_schema_core.json``).

Uses FORM test entities. Covers schema list mutation, ``validate_ai``, ``previous``,
and ``required_fields`` — not ``Form.save()`` or version hashing (see
``test_004_form_properties.py``).
"""

import copy

import pytest

from lagniappe.core.properties.form_inputs import TextInput
from lagniappe.core.properties.schema import (
    SchemaFields,
    SchemaValidationError,
    canonicalize_schema,
)


# @features form-schema
# @dimensions ai-value validation
@pytest.mark.unit
def test_schema_validate_ai_filters_invalid_top_level(get_test_entities):
    for entity in get_test_entities():
        schema = entity.properties.schema
        schema.validate_ai(copy.deepcopy(entity.test_spec["ai_payload"]))
        assert [e["id"] for e in schema.value] == entity.test_spec["expected_ids"]


# @features form-schema html-field
# @dimensions ai-value validation
@pytest.mark.unit
def test_schema_validate_ai_html_calls_set_html_field(get_test_entities):
    for entity in get_test_entities():
        calls = []
        entity.set_html_field = lambda fid, html: calls.append([fid, html])
        schema = entity.properties.schema
        schema.validate_ai(copy.deepcopy(entity.test_spec["ai_payload"]))
        assert calls == entity.test_spec["expected_set_html_calls"]
        assert [e["id"] for e in schema.value] == entity.test_spec["expected_ids"]
        assert "html" not in schema.value[0]


# @features form-schema form-table
# @dimensions ai-value validation columns
@pytest.mark.unit
def test_schema_validate_ai_table_filters_bad_columns(get_test_entities):
    for entity in get_test_entities():
        schema = entity.properties.schema
        schema.validate_ai(copy.deepcopy(entity.test_spec["ai_payload"]))
        table = schema.value[0]
        assert table["id"] == "rows"
        assert [c["id"] for c in table["columns"]] == entity.test_spec[
            "expected_table_column_ids"
        ]


# @features form-schema
# @dimensions previous cache fields
@pytest.mark.unit
def test_schema_previous_and_fields_cache(get_test_entities):
    for entity in get_test_entities():
        schema = entity.properties.schema
        first = copy.deepcopy(entity.test_spec["schema_first"])
        second = copy.deepcopy(entity.test_spec["schema_second"])
        schema.value = first
        schema.value = second
        assert schema.previous == first
        assert list(schema.fields.keys()) == ["b"]


# @features form-schema
# @dimensions required-fields
@pytest.mark.unit
def test_schema_required_fields(get_test_entities):
    for entity in get_test_entities():
        schema = entity.properties.schema
        schema.value = copy.deepcopy(entity.test_spec["schema_value"])
        got = [f.id for f in schema.required_fields]
        assert got == entity.test_spec["expected_required_ids"]


# @features form-schema
# @dimensions field-factory unknown-type
@pytest.mark.unit
def test_schema_create_field_unknown_returns_none(get_test_entities):
    for entity in get_test_entities():
        field = SchemaFields.create_field(
            entity.test_spec["bad_definition"],
            entity=entity,
        )
        assert field is None


# @features form-schema text-input
# @dimensions field-factory
@pytest.mark.unit
def test_schema_create_field_known_text_input(get_test_entities):
    for entity in get_test_entities():
        field = SchemaFields.create_field(
            entity.test_spec["good_definition"],
            entity=entity,
        )
        assert isinstance(field, TextInput)
        assert field.id == "t"


# @features form-schema
# @dimensions canonicalization versioning membership
@pytest.mark.unit
def test_schema_canonicalizer_unifies_creation_paths_without_changing_membership():
    builder = [{"id": "notes", "type": "input"}]
    ai = [{"id": "notes", "type": "text", "title": ""}]
    ingress = [{"id": "notes", "type": "INPUT", "input": "TEXT"}]

    results = [
        canonicalize_schema(value, form_type="page")
        for value in (builder, ai, ingress)
    ]

    assert results[0] == results[1] == results[2]
    assert [field["id"] for field in results[0]] == ["notes"]
    assert results[0][0] == {
        "id": "notes",
        "type": "input",
        "input": "text",
        "title": "Input",
    }
    assert builder == [{"id": "notes", "type": "input"}]


# @features form-schema
# @dimensions canonicalization validation
@pytest.mark.unit
def test_schema_canonicalizer_rejects_ambiguous_durable_shapes():
    with pytest.raises(SchemaValidationError, match="Duplicate schema field id"):
        canonicalize_schema(
            [
                {"id": "duplicate", "type": "input"},
                {"id": "duplicate", "type": "textarea"},
            ]
        )

    with pytest.raises(SchemaValidationError, match="options must be a list"):
        canonicalize_schema(
            [{"id": "choice", "type": "select", "options": "invalid"}]
        )

    with pytest.raises(SchemaValidationError, match="visibility must be a list"):
        canonicalize_schema(
            [
                {
                    "id": "conditional",
                    "type": "input",
                    "visibility": {"id": "trigger", "value": True},
                }
            ]
        )


# @features form-schema
# @dimensions canonicalization history-snapshot membership
@pytest.mark.unit
def test_schema_canonicalizer_preserves_snapshot_membership():
    raw = [{"id": "historical", "type": "textarea"}]

    live = canonicalize_schema(raw, form_type="page")
    snapshot = canonicalize_schema(raw, form_type="page", snapshot=True)

    assert [field["id"] for field in live] == ["historical"]
    assert [field["id"] for field in snapshot] == ["historical"]
