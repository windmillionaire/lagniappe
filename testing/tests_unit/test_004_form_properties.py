"""Form entity surface from [entities/form.py](lagniappe/core/entities/form.py) and [properties/form.py](lagniappe/core/properties/form.py).

Covers: ``FormType``, ``Schema`` → ``fields``, ``table_fields``, ``html_fields``,
``FormFilters.conditions``, schema-change cache behavior, ``Form.update``, and
``Form.save`` publication, and ``SchemaVersion.update``.

Out of scope here: ``get_html_field`` / ``set_html_field`` (e2e).
"""

import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from lagniappe.core.definitions import MutationEffectType, MutationOperation
from lagniappe.core.entities import form as form_module
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.mutations import plan_mutation
from lagniappe.core.properties.schema import SCHEMA_FORMAT_VERSION
from lagniappe.core.properties.form import FormGeneration, requires_submission_conversion
from testing.utility.test_entities import TestEntities


# @pair form-schema:cache
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


# @matrix form : form-type schema update
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


# @matrix form-schema : canonicalization membership write-gateway
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


# @matrix form : schema-version update
@pytest.mark.unit
def test_schema_version_update_changes_when_schema_changes():
    """Initial publication and changed schemas refresh the content fingerprint."""
    form = TestEntities.get("FORM", {"name": "Ver", "hash": "form_ver"})
    form.db.pop("version", None)
    form.schema = [{"id": "answer", "type": "input", "input": "text"}]
    assert form.properties.version.update() is None
    assert form.version
    assert form.properties.version.update() is False
    form.schema = [{"id": "answer", "type": "input", "input": "number"}]
    previous_hash = form.version
    assert form.properties.version.update() == previous_hash
    assert form.version != previous_hash
    assert form.properties.version.update() is False


# @matrix form : generation value-conversion
@pytest.mark.unit
@pytest.mark.parametrize("previous,proposed", [
    ([{"id": "answer", "type": "textarea"}], []),
    ([{"id": "reference", "type": "bookmark"}], []),
    ([{"id": "answer", "type": "textarea"}], [{"id": "answer", "type": "checkbox"}]),
    ([{"id": "answer", "type": "input", "input": "text"}], [{"id": "answer", "type": "input", "input": "number"}]),
    ([{"id": "choice", "type": "select", "options": [{"value": "a", "label": "A"}]}],
     [{"id": "choice", "type": "select", "multiple": True, "options": [{"value": "a", "label": "A"}]}]),
    ([{"id": "link", "type": "link", "location": "out"}], [{"id": "link", "type": "link", "location": "in"}]),
    ([{"id": "choice", "type": "radio", "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]}],
     [{"id": "choice", "type": "radio", "options": [{"value": "b", "label": "B"}]}]),
    ([{"id": "table", "type": "table", "columns": [{"id": "answer", "type": "input", "input": "text"}]}],
     [{"id": "table", "type": "table", "columns": []}]),
    ([{"id": "table", "type": "table", "columns": [{"id": "answer", "type": "input", "input": "text"}]}],
     [{"id": "table", "type": "table", "columns": [{"id": "answer", "type": "input", "input": "number"}]}]),
])
def test_submission_conversion_requires_changes_to_existing_values(previous, proposed):
    assert requires_submission_conversion(previous, proposed)


# @matrix form : generation value-conversion
@pytest.mark.unit
def test_submission_conversion_preserves_presentation_and_additions():
    form = TestEntities.get("FORM", {"name": "Presentation", "hash": "versioned-labels"})
    form.schema = [
        {"id": "answer", "type": "input", "input": "text", "title": "Answer"},
        {"id": "choice", "type": "select", "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]},
        {"id": "table", "type": "table", "columns": [{"id": "item", "type": "input", "input": "text", "title": "Item"}]},
        {"id": "instructions", "type": "html", "title": "Instructions"},
    ]
    saved = deepcopy(form.schema)
    proposed = deepcopy(saved)
    proposed[0].update(title="Updated answer", placeholder="More guidance", required=True)
    proposed[1]["options"] = [{"value": "b", "label": "Second"}, {"value": "a", "label": "First"}, {"value": "c", "label": "New"}]
    proposed[2]["columns"][0]["title"] = "Equipment"
    proposed[2]["columns"].append({"id": "quantity", "type": "input", "input": "number"})
    proposed[3]["title"] = "Updated instructions"
    proposed.append({"id": "additional", "type": "textarea"})
    form.schema = list(reversed(proposed))
    assert not requires_submission_conversion(saved, form.schema)
    assert not requires_submission_conversion([], form.schema)


# @matrix form : generation value-conversion
@pytest.mark.unit
def test_submission_conversion_ignores_fields_without_answers_and_unused_link_setting():
    """Static fields have no answers; Link always stores one value dictionary."""
    for kind in ("html", "status"):
        previous = [{"id": "display", "type": kind}]
        assert not requires_submission_conversion(previous, [])
        assert not requires_submission_conversion(
            previous, [{"id": "display", "type": "textarea"}],
        )
        assert requires_submission_conversion(
            [{"id": "answer", "type": "textarea"}], [{"id": "answer", "type": kind}],
        )
    previous = [{"id": "link", "type": "link", "location": "in"}]
    proposed = [{"id": "link", "type": "link", "location": "in", "multiple": True}]
    assert not requires_submission_conversion(previous, proposed)
    assert not requires_submission_conversion(
        [{"id": "table", "type": "table", "columns": previous}],
        [{"id": "table", "type": "table", "columns": proposed}],
    )


# @matrix form : generation defaults
@pytest.mark.unit
@pytest.mark.parametrize("legacy", [{}, {"version": "legacy-hash"}, {"schema_version": "older-hash"}])
def test_form_generation_defaults_to_zero_without_reinterpreting_legacy_versions(legacy):
    form = TestEntities.get("FORM", {"name": "Generation", "hash": "form-generation"})
    form.db.pop("generation", None)
    form.db.update(legacy)
    before = dict(form.db)
    generation = FormGeneration(entity=form)
    assert generation.value == 0
    assert form.db == before


# @matrix form : generation validation
@pytest.mark.unit
def test_form_generation_stores_nonnegative_integers():
    form = TestEntities.get("FORM", {"name": "Generation", "hash": "generation-value"})
    generation = FormGeneration(entity=form)
    generation.value = 0
    assert generation.value == form.db["generation"] == 0
    generation.value = 2
    assert FormGeneration(entity=form).value == 2
    for invalid in (-1, True, 1.5, "2", None):
        with pytest.raises(ValidationError, match="nonnegative integer"):
            generation.value = invalid
        assert generation.value == form.db["generation"] == 2


# @matrix form : schema-version update content-fingerprint
@pytest.mark.unit
def test_schema_version_tracks_metadata_and_static_content():
    form = TestEntities.get("FORM", {
        "name": "Content", "hash": "form-content-version", "assets": {},
    })
    form.schema = [
        {"id": "answer", "type": "input", "title": "Answer"},
        {"id": "instructions", "type": "html"},
    ]
    form.assets.update({
        "instructions": {"type": "html", "fingerprint": "first-html"},
        "image_instructions_one": {"type": "image", "fingerprint": "first-image"},
    })
    form.properties.version.update()
    previous = form.version

    edited = deepcopy(form.schema)
    edited[0]["title"] = "Updated label"
    form.schema = edited
    assert form.properties.version.update() == previous
    assert form.version != previous
    previous = form.version

    form.form_type = "page" if form.form_type == "task" else "task"
    assert form.properties.version.update() == previous
    assert form.version != previous
    previous = form.version

    form.assets["instructions"]["fingerprint"] = "second-html"
    assert form.properties.version.update() == previous
    assert form.version != previous
    previous = form.version

    form.assets["image_instructions_one"]["fingerprint"] = "second-image"
    assert form.properties.version.update() == previous
    assert form.version != previous
    assert FormGeneration(entity=form).value == 0
    assert form.properties.version.update() is False


# @matrix form : schema-version update content-fingerprint
@pytest.mark.unit
def test_schema_version_ignores_name_storage_paths_and_unrelated_assets():
    form = TestEntities.get("FORM", {
        "name": "Content", "hash": "form-content-stable", "assets": {},
    })
    form.schema = [{"id": "instructions", "type": "html"}]
    form.assets.update({
        "instructions": {"type": "html", "fingerprint": "same-html", "path": "before.html"},
        "image_instructions_one": {"type": "image", "fingerprint": "same-image", "path": "before.png"},
    })
    form.properties.version.update()
    before = form.version
    form.name = "Updated display name"
    form.assets["instructions"]["path"] = "copied.html"
    form.assets["image_instructions_one"]["path"] = "copied.png"
    form.assets["unrelated"] = {"type": "image", "fingerprint": "other-content"}
    generation = FormGeneration(entity=form)
    generation.value = 3
    assert form.properties.version.update() is False
    assert form.version == before


# @matrix form : schema-version update content-fingerprint
@pytest.mark.unit
def test_schema_version_requires_static_content_fingerprints():
    form = TestEntities.get("FORM", {
        "name": "Content", "hash": "form-content-missing", "assets": {},
    })
    form.schema = [{"id": "instructions", "type": "html"}]
    form.assets["instructions"] = {"type": "html", "fingerprint": "saved-html"}
    form.properties.version.update()
    before = form.version
    form.assets["instructions"].pop("fingerprint")
    with pytest.raises(ValidationError, match="fingerprint"):
        form.properties.version.update()
    assert form.version == before


# @matrix form : relations save content-fingerprint generation
@pytest.mark.unit
def test_form_save_refreshes_content_version_without_archiving_compatible_edits(get_schema):
    """A label edit changes cached content without archiving an answer generation."""
    from google.cloud import datastore

    row = datastore.Entity(key=datastore.Key("models", "history-form", project="test-project"))
    row.update(type="form", form_type="task", hash="history-form", name="History",
               schema=json.dumps(get_schema("integration_one_text")),
               version="legacy-before", generation=4)
    source = Entities.FORM(row)
    form = Entities.FORM(deepcopy(row))
    previous_schema = deepcopy(source.schema)
    edited = deepcopy(previous_schema)
    edited[0]["title"] = "Updated label"
    form.schema = edited
    with (
        patch.object(form_module.database_get, "form_users", return_value=[]),
        patch.object(form_module.Entities, "fetch", return_value=[]),
        patch.object(form_module.Entities, "fetch_one", return_value=source),
    ):
        plan = plan_mutation(MutationOperation.SAVE, form, registry=Entities)

    assert form.properties.schema.previous == previous_schema
    assert form.schema[0]["title"] == "Updated label"
    assert form.version != source.version == "legacy-before"
    assert form.generation == source.generation == 4
    assert source.schema == previous_schema
    writes = [
        effect
        for effect in plan.effects
        if effect.effect is MutationEffectType.UPSERT
    ]
    assert [effect.entity for effect in writes] == [form]
    assert all(effect.property_mask is None for effect in writes)


# @matrix forms cache : owner-reuse no-extra-read
# @pair form-schema:cache
@pytest.mark.unit
@pytest.mark.parametrize("kind", ["category", "model"])
def test_form_save_refreshes_users_with_edited_form_schema(monkeypatch, kind):
    from datetime import datetime, timezone
    from google.cloud import datastore
    from lagniappe.core.tools.database.core import KINDS

    modified = datetime(2026, 9, 10, tzinfo=timezone.utc)
    form_key = datastore.Key(KINDS.models.value, "edited-form", project="form-reuse")
    project_key = datastore.Key(KINDS.models.value, "owner-project", project="form-reuse")
    owner_key = datastore.Key(KINDS.models.value, f"form-{kind}", project="form-reuse")
    persisted_form = datastore.Entity(key=form_key)
    persisted_form.update(type="form", hash="editedform", name="Edited Form", modified=modified,
                          form_type="task" if kind == "model" else "page", version="old-version")
    edited_row = datastore.Entity(key=form_key)
    edited_row.update(persisted_form)
    form = Entities.FORM(edited_row)
    owner_row = datastore.Entity(key=owner_key)
    owner_row.update(type=kind, hash=f"owner{kind}", name="Form user", modified=modified,
                     form=form_key, requires=["models"])
    project_row = datastore.Entity(key=project_key)
    project_row.update(type="project", hash="ownerproject", name="Project", modified=modified)
    if kind == "model":
        owner_row["project"] = project_key
    records = {row.key: row for row in (persisted_form, owner_row, project_row)}
    reads = []

    def fetch_rows(keys):
        reads.extend(keys)
        return [records[key] for key in keys if key in records]

    monkeypatch.setattr(form_module.database_get, "form_users", lambda _form: [owner_row])
    monkeypatch.setattr(form_module.database_get, "entities", fetch_rows)

    form.set_schema([{"id": "subject", "type": "input", "title": "Updated subject"}])
    plan = plan_mutation(MutationOperation.SAVE, form, registry=Entities)
    owner = next(
        effect.entity for effect in plan.effects
        if effect.effect is MutationEffectType.CACHE_REFRESH and effect.entity.key == owner_key
    )

    assert owner.form is form
    assert owner.form.schema == form.schema
    assert owner.form.schema[-1]["title"] == "Updated subject"
    assert owner.form.version == form.version != "old-version"
    assert reads.count(form_key) == 1
    assert form.generation == 0
    assert persisted_form["version"] == "old-version"


# @matrix form-type : cache column details property
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
        expected = form.test_spec["expected"]
        form.form_type = form.test_spec["form_type"]
        form_type = form.properties.form_type

        assert form.form_type == form_type.value == expected["value"]
        assert form_type.sort_value == expected["sort_value"]
        assert form.details["form_type"] == expected["details_value"]
        assert form.column("form_type").column_value == expected["column_value"]
        assert form_type.cache_key == "type"
        assert form_type.cache_value == expected["cache_value"]
        assert form.to_cache["type"] == expected["cache_value"]


# @matrix form-schema : fields property
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

        assert form.schema == schema
        assert {
            field_id: {"id": field.id, "label": field.label}
            for field_id, field in form.fields.items()
        } == form.test_spec["expected_fields"]


# @matrix form-schema form-table : table-fields
@pytest.mark.unit
def test_form_table_fields(get_test_entities, get_schema):
    """Test table_fields returns column fields from Table elements."""
    for form in get_test_entities():
        form.schema = get_schema(form.test_spec["schema"])
        assert list(form.table_fields) == form.test_spec["expected_table_fields"]


# @matrix form-schema html-field : html-fields
@pytest.mark.unit
def test_form_html_fields(get_test_entities, get_schema):
    """Test html_fields returns HTML field objects."""
    for form in get_test_entities():
        form.schema = get_schema(form.test_spec["schema"])
        assert [field.id for field in form.html_fields] == form.test_spec[
            "expected_html_fields"
        ]


# @matrix filters form : conditions exclude-table-fields schema-fields
@pytest.mark.unit
def test_form_filters(get_test_entities, get_schema):
    """Test FormFilters.conditions transforms schema into filter conditions.

    Each condition has: field (filter_key), label, kind, icon.
    Non-filterable fields (e.g. html) are excluded.
    Table fields are excluded because their submissions are multi-row values.
    """
    for form in get_test_entities():
        form.schema = get_schema(form.test_spec["schema"])
        assert [
            [condition[key] for key in ("field", "label", "kind", "icon")]
            for condition in form.filters.conditions
        ] == form.test_spec["expected_conditions"]
