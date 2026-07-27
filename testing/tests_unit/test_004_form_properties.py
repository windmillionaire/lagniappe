"""Form entity surface from [entities/form.py](lagniappe/core/entities/form.py) and [properties/form.py](lagniappe/core/properties/form.py).

Covers: ``FormType``, ``Schema`` → ``fields``, ``table_fields``, ``html_fields``,
``FormFilters.conditions``, schema-change cache behavior, ``Form.update``, and
``Form.save`` schema history, and ``SchemaVersion.update``.

Out of scope here: ``get_html_field`` / ``set_html_field`` (e2e), ``used_by``.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.definitions import MutationEffectType, MutationOperation
from lagniappe.core.entities import form as form_module
from lagniappe.core.entities import Entities
from lagniappe.core.mutations import plan_mutation
from lagniappe.core.properties.schema import SCHEMA_FORMAT_VERSION
from testing.utility.test_entities import TestEntities


# @features form-schema
# @dimensions cache
@pytest.mark.unit
def test_form_schema_change_refreshes_table_fields_and_filter_conditions(get_schema):
    """Replacing ``form.schema`` must invalidate table and filter caches."""
    form = TestEntities.get("FORM", {"name": "Schema cache", "hash": "form_sch_cache"})
    form.schema = get_schema("complex_types")
    assert set(form.table_fields) == {
        "row-namecd12",
        "row-emailef34",
        "row-primarygh",
    }
    assert [c["label"] for c in form.filters.conditions] == [
        "Website",
        "Related Page",
        "Address",
        "Signature",
        "Reference",
    ]

    form.schema = get_schema("basic_inputs")
    assert form.table_fields == {}
    assert [c["label"] for c in form.filters.conditions] == [
        "Text Field",
        "Date Field",
        "Time Field",
        "Number Field",
        "Email Field",
        "Phone Field",
    ]


# @features form
# @dimensions update schema form-type
@pytest.mark.unit
def test_form_update_sets_name_form_type_and_schema(get_schema):
    """``Form.update`` handles ``name``, ``form-type``, and ``schema`` (str or list)."""
    form = TestEntities.get("FORM", {"name": "Old", "form_type": "page", "hash": "form_upd"})
    payload = {
        "name": "New Name",
        "form-type": "task",
        "schema": json.dumps(get_schema("integration_one_text")),
    }
    form.update(payload)
    assert form.name == "New Name"
    assert form.form_type == "task"
    assert form.schema == get_schema("integration_one_text")

    form.update({"schema": get_schema("number_input_only")})
    assert form.schema == get_schema("number_input_only")


# @features form-schema
# @dimensions canonicalization write-gateway membership
@pytest.mark.unit
def test_form_schema_write_gateway_canonicalizes_without_adding_page_fields():
    page_form = TestEntities.get(
        "FORM",
        {
            "name": "Page form",
            "form_type": "page",
            "hash": "canonical_page_form",
        },
    )
    page_form.form_type = "page"
    page_form.set_schema([{"id": "notes", "type": "textarea"}])

    assert [field["id"] for field in page_form.schema] == ["notes"]
    assert page_form.schema_format == SCHEMA_FORMAT_VERSION

    page_form.schema = [{"id": "contact", "type": "EMAIL"}]
    assert page_form.schema[-1] == {
        "id": "contact",
        "type": "input",
        "input": "email",
        "title": "Input",
    }
    assert page_form.db["schema_format"] == SCHEMA_FORMAT_VERSION

    page_form.set_schema(
        [
            {"id": "name", "type": "input", "title": "Page heading"},
            {"id": "description", "type": "textarea", "title": "Summary"},
        ]
    )
    assert page_form.schema == [
        {
            "id": "name",
            "type": "input",
            "input": "text",
            "title": "Page heading",
        },
        {"id": "description", "type": "textarea", "title": "Summary"},
    ]


# @features form
# @dimensions schema-version update
@pytest.mark.unit
def test_schema_version_update_changes_when_schema_changes(get_schema):
    """``SchemaVersion.update`` returns prior hash or ``False`` when unchanged."""
    form = TestEntities.get("FORM", {"name": "Ver", "hash": "form_ver"})
    form.db.pop("version", None)
    form.schema = get_schema("integration_one_text")
    first = form.properties.version.update()
    assert first is None or first is False
    assert form.version

    same = form.properties.version.update()
    assert same is False

    form.schema = get_schema("number_input_only")
    previous_hash = form.version
    bumped = form.properties.version.update()
    assert bumped == previous_hash
    assert form.version != previous_hash


# @features form
# @dimensions save schema-history relations
# @source lagniappe/core/mutations/save.py::FormMutation.plan_save
@pytest.mark.unit
def test_form_save_records_schema_history_on_version_change(get_schema):
    """The Form planner should stage history for the previous schema."""
    form = TestEntities.get("FORM", {"name": "History", "hash": "form_history"})
    form.schema = get_schema("integration_one_text")
    form.properties.version.update()
    previous_version = form.version
    previous_schema = form.schema
    form.schema = get_schema("number_input_only")
    history = SimpleNamespace(
        key="fake-form-history-key",
        entity_kind="form_history",
        properties={},
        processes={},
        mutation_intents=[],
    )

    with (
        patch.object(
            form_module.Entities.FORM_HISTORY,
            "create",
            return_value=history,
        ) as create_history,
        patch.object(form_module.database.get, "form_users", return_value=[]),
        patch.object(form_module.Entities, "fetch", return_value=[]),
    ):
        plan = plan_mutation(MutationOperation.SAVE, form, registry=Entities)

    create_history.assert_called_once_with(form, previous_version)
    assert form.properties.schema.previous == previous_schema
    assert form.version != previous_version
    writes = [
        effect
        for effect in plan.effects
        if effect.effect is MutationEffectType.UPSERT
    ]
    assert [effect.entity for effect in writes[:2]] == [history, form]
    assert all(effect.property_mask is None for effect in writes[:2])


# @features form-type
# @dimensions property column details cache
@pytest.mark.unit
def test_form_type(get_test_entities):
    """Test FormType property with ColumnMixin, DetailsMixin, CacheMixin.

    FormType is a simple categorical property for form classification.
    - column_value: value (for table display)
    - details_value: value
    - cache_value: value
    - cache_key: "type"
    """
    for form in get_test_entities():
        form.form_type = form.test_spec.get("form_type")

        # property value
        assert (
            form.form_type
            == form.properties.form_type.value
            == form.test_spec.get("form_type")
        )

        # DetailsMixin - details_value
        assert form.details["form_type"] == form.form_type

        # ColumnMixin - column_value
        assert form.column("form_type").column_value == form.form_type

        # CacheMixin - cache_key is "type", cache_value is value
        assert form.to_cache["type"] == form.form_type


# @features form-schema
# @dimensions property fields
@pytest.mark.unit
def test_form_schema(get_test_entities, get_schema):
    """Test Schema property setter creates correct field objects.

    Sets schema from JSON, verifies form.fields dict has correct field IDs
    and each field has the expected id and label (from schema title).
    """
    forms = get_test_entities()
    schemas = [get_schema(f.test_spec["schema"]) for f in forms]

    for form, schema in zip(forms, schemas):
        form.schema = schema

        # schema value is the raw schema list
        assert form.schema == schema

        # fields dict has correct keys (field IDs from schema)
        assert set(form.fields.keys()) == {el["id"] for el in schema}

        # each field has correct id and label
        for element in schema:
            field = form.fields[element["id"]]
            assert field.id == element["id"]
            assert field.label == element["title"]


# @features form-schema form-table
# @dimensions table-fields
@pytest.mark.unit
def test_form_table_fields(get_test_entities, get_schema):
    """Test table_fields returns column fields from Table elements."""
    for form in get_test_entities():
        form.schema = get_schema(form.test_spec["schema"])
        table_fields = form.table_fields

        if "complex" in form.test_spec["schema"]:
            assert set(table_fields.keys()) == {
                "row-namecd12",
                "row-emailef34",
                "row-primarygh",
            }
        else:
            assert table_fields == {}


# @features form-schema html-field
# @dimensions html-fields
@pytest.mark.unit
def test_form_html_fields(get_test_entities, get_schema):
    """Test html_fields returns HTML field objects."""
    for form in get_test_entities():
        form.schema = get_schema(form.test_spec["schema"])
        html_fields = form.html_fields

        if "complex" in form.test_spec["schema"]:
            assert len(html_fields) == 1
            assert html_fields[0].id == "html-instructqr"
        else:
            assert html_fields == []


# @features form filters
# @dimensions conditions schema-fields exclude-table-fields
@pytest.mark.unit
def test_form_filters(get_test_entities, get_schema):
    """Test FormFilters.conditions transforms schema into filter conditions.

    Each condition has: field (filter_key), label, kind, icon.
    Non-filterable fields (e.g. html) are excluded.
    Table fields are excluded because their submissions are multi-row values.
    """
    non_filterable = {"html", "table"}

    for form in get_test_entities():
        schema = get_schema(form.test_spec["schema"])
        form.schema = schema

        conditions = form.filters.conditions

        # build expected labels (tables expand to column titles, skip non-filterable)
        expected_labels = []
        for el in schema:
            if el["type"] in non_filterable:
                continue
            expected_labels.append(el["title"])

        # each condition has required keys
        for cond in conditions:
            assert {"field", "label", "kind", "icon"} <= cond.keys()

        # labels match expected
        assert [c["label"] for c in conditions] == expected_labels
