"""``SubmitterMixin`` and ``normalize_submission_values`` (``004d_submitter.json``).

PAGE (and similar) entities with ``SubmitterMixin`` plus an attached form for schema.
``save_submission`` writes ``entity.db`` submission JSON and copies ``schema_version`` /
``form_hash`` from ``entity.form`` — distinct from ``Form.save()`` in
``lagniappe/core/entities/form.py``.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.mixins.submitter import normalize_submission_values
from lagniappe.core.mutations import executor as mutation_executor
from testing.utility.test_entities import TestEntities
from testing.utility.mock_submission import WebFormSubmission


class _MinimalImportProcess:
    """``import_submission`` requires ``fuzzy_match`` and ``separator``."""

    def __init__(self, fuzzy_fields=None):
        self.fuzzy_fields = set(fuzzy_fields or [])

    def fuzzy_match(self, field_id):
        return field_id in self.fuzzy_fields

    separator = ","


def _internal_link_entity(identifier, *, request):
    return SimpleNamespace(
        details={
            "id": identifier,
            "name": f"Page-{identifier}",
            "hash": identifier,
        }
    )


def _links_import_entity(get_schema, name, hash_suffix):
    entity = TestEntities.get(
        "PAGE",
        {
            "name": name,
            "hash": f"link_import_{hash_suffix}",
            "form": {
                "name": "Links",
                "hash": f"link_import_form_{hash_suffix}",
                "schema": "submission_integration_links",
            },
        },
    )
    entity.form.schema = get_schema("submission_integration_links")
    return entity


def _assert_normalize_case(entity, get_schema):
    entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
    case = entity.test_spec["normalize_case"]
    fields = entity.properties.submission.fields
    got = normalize_submission_values(WebFormSubmission(case["values"]), fields)
    assert got == case["expected"]


# @features submission
# @dimensions normalize list-filtering zero
@pytest.mark.unit
def test_normalize_list_drops_numeric_zero_keeps_string_zero(
    get_test_entities, get_schema
):
    """List normalization uses truthiness: ``0`` is dropped, ``\"0\"`` is kept."""
    for entity in get_test_entities():
        _assert_normalize_case(entity, get_schema)


# @features submission
# @dimensions patch multiple-fields
@pytest.mark.unit
def test_patch_submission_merges_multiple_fields(get_test_entities, get_schema):
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        spec = entity.test_spec
        entity.form_submission(WebFormSubmission(spec["initial_submission"]))
        entity.patch_submission(spec["patch_payload"])
        assert json.loads(entity.db["submission"]) == spec["expected_submission"]


# @features submission
# @dimensions repeating-default field-copy direct-save storage
@pytest.mark.unit
def test_save_default_field_copies_db_value_and_saves_only_submitter():
    task = TestEntities.get(
        "TASK",
        {
            "name": "Repeating default task",
            "hash": "repeat_default_task",
            "page": {"name": "Parent", "hash": "repeat_default_parent"},
        },
    )

    class _IndexableEntity(dict):
        exclude_from_indexes = frozenset()

    task._db = _IndexableEntity(task.db)
    source_value = {"nested": ["original"]}
    submission = SimpleNamespace(db_value={"repeat-field": source_value})

    with (
        patch.object(
            mutation_executor.database,
            "save_mutations",
        ) as database_save,
        patch.object(task, "save") as task_save,
    ):
        saved = task.save_default_field("repeat-field", submission)

    source_value["nested"].append("changed")

    assert saved == {"nested": ["original"]}
    assert task.default_submission == {"repeat-field": {"nested": ["original"]}}
    assert json.loads(task.db["default_submission"]) == task.default_submission
    assert "default_submission" in task.db.exclude_from_indexes
    assert list(database_save.call_args.args[0]) == [
        (task, ("default_submission",))
    ]
    task_save.assert_not_called()


# @features submission
# @dimensions repeating-default reconciliation
@pytest.mark.unit
def test_save_submission_removes_changed_repeating_defaults(get_schema):
    task = TestEntities.get(
        "TASK",
        {
            "name": "Reconcile repeating defaults",
            "hash": "reconcile_defaults",
            "page": {"name": "Parent", "hash": "reconcile_defaults_parent"},
            "form": {"name": "Inputs", "hash": "reconcile_defaults_form"},
        },
    )
    task.form.schema = get_schema("basic_inputs")
    task.db["default_submission"] = json.dumps(
        {
            "input-textab12": "unchanged",
            "input-datecd34": "2026-07-17",
            "input-numgh78": 42,
        }
    )
    task.properties.submission.value = {
        "input-textab12": "unchanged",
        "input-numgh78": 7,
    }
    task.save_submission()

    assert task.default_submission == {"input-textab12": "unchanged"}
    assert json.loads(task.db["default_submission"]) == {
        "input-textab12": "unchanged"
    }


# @features submission form-table
# @dimensions import validation error-message
@pytest.mark.unit
def test_import_submission_validation_error_includes_field_and_payload(
    get_test_entities, get_schema
):
    for entity in get_test_entities():
        spec = entity.test_spec
        entity.form.schema = get_schema(spec["form"]["schema"])
        with pytest.raises(ValidationError) as excinfo:
            entity.import_submission(
                spec["import_submission"],
                _MinimalImportProcess(),
            )
        msg = str(excinfo.value)
        assert spec["expected_error_substring"] in msg
        assert "Row length does not match number of columns" in msg


# @features text-input
# @dimensions import list-normalization
@pytest.mark.unit
def test_text_input_validate_import_space_joins_list_values(get_schema):
    entity = TestEntities.get(
        "PAGE", {"name": "Text input import page", "hash": "txtimp"}
    )
    form = TestEntities.get("FORM", {"name": "F", "hash": "txtimpf"})
    form.schema = get_schema("text_input_only")
    entity.form = form
    field = entity.properties.submission.fields["input-textab12"]

    field.validate_import(["Ada", "", None, "Lovelace"])

    assert field.value == "Ada Lovelace"
    assert field.errors == []


# @features submission text-input
# @dimensions import list-normalization save
@pytest.mark.unit
def test_import_submission_space_joins_input_list_values():
    entity = TestEntities.get(
        "PAGE", {"name": "Import list page", "hash": "implist"}
    )
    form = TestEntities.get("FORM", {"name": "F", "hash": "implistf"})
    form.schema = [
        {
            "id": "name",
            "type": "input",
            "input": "text",
            "title": "Name",
        }
    ]
    entity.form = form

    entity.import_submission(
        {"name": ["Ada", "", None, "Lovelace"]},
        _MinimalImportProcess(),
    )

    assert json.loads(entity.db["submission"]) == {"name": "Ada Lovelace"}
    assert entity.name == "Ada Lovelace"


# @features submission link
# @dimensions import internal entity-resolution
@pytest.mark.unit
def test_import_submission_internal_link_exact_match(get_schema, monkeypatch):
    entity = _links_import_entity(get_schema, "Import exact link", "exact")
    calls = []

    def find_page(value, match_field_label="Name", fuzzy=False, error_label=None):
        calls.append((value, match_field_label, fuzzy, error_label))
        return {"id": "target_a", "warnings": [], "errors": []}

    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.files.find_page", find_page
    )
    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.Entities.fetch_one",
        _internal_link_entity,
    )

    entity.import_submission(
        {"top_link": "Target Page"},
        _MinimalImportProcess(),
    )

    assert calls == [("Target Page", "Name", False, "Top link")]
    assert json.loads(entity.db["submission"]) == {
        "top_link": {
            "id": "target_a",
            "name": "Page-target_a",
            "hash": "target_a",
        }
    }


# @features submission link
# @dimensions ai-value internal entity-resolution
@pytest.mark.unit
def test_ai_submission_internal_link_plaintext_resolves(get_schema, monkeypatch):
    entity = _links_import_entity(get_schema, "AI exact link", "ai_exact")
    calls = []

    def find_page(value, match_field_label="Name", fuzzy=False, error_label=None):
        calls.append((value, match_field_label, fuzzy, error_label))
        return {"id": "target_ai", "warnings": [], "errors": []}

    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.files.find_page", find_page
    )
    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.Entities.fetch_one",
        _internal_link_entity,
    )
    entity.ai_submission({"top_link": "Target Page"})

    assert calls == [("Target Page", "Name", None, "Top link")]
    assert json.loads(entity.db["submission"]) == {
        "top_link": {
            "id": "target_ai",
            "name": "Page-target_ai",
            "hash": "target_ai",
        }
    }


# @features submission link
# @dimensions ai-value internal entity-resolution fallback
@pytest.mark.unit
def test_ai_submission_internal_link_falls_back_to_value_setter(
    get_schema,
    monkeypatch,
):
    entity = _links_import_entity(get_schema, "AI id fallback link", "ai_id")
    calls = []

    def find_page(value, match_field_label="Name", fuzzy=False, error_label=None):
        calls.append((value, match_field_label, fuzzy, error_label))
        return {"id": None, "warnings": [], "errors": ["No page match."]}

    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.files.find_page", find_page
    )
    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.Entities.fetch_one",
        _internal_link_entity,
    )
    entity.ai_submission({"top_link": "target_ai_id"})

    assert calls == [("target_ai_id", "Name", None, "Top link")]
    assert json.loads(entity.db["submission"]) == {
        "top_link": {
            "id": "target_ai_id",
            "name": "Page-target_ai_id",
            "hash": "target_ai_id",
        }
    }


# @features submission link
# @dimensions import internal fuzzy-match weak-match
@pytest.mark.unit
def test_import_submission_internal_link_fuzzy_match_warning(
    get_schema, monkeypatch
):
    entity = _links_import_entity(get_schema, "Import fuzzy link", "fuzzy")

    def find_page(value, match_field_label="Name", fuzzy=False, error_label=None):
        assert fuzzy is True
        return {
            "id": "target_a",
            "warnings": ["Weak match for Top link: 'Target Page'"],
            "errors": [],
        }

    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.files.find_page", find_page
    )
    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.Entities.fetch_one",
        _internal_link_entity,
    )

    entity.import_submission(
        {"top_link": "Targt Page"},
        _MinimalImportProcess(fuzzy_fields={"top_link"}),
    )

    field = entity.properties.submission.fields["top_link"]
    assert field.warnings == ["Weak match for Top link: 'Target Page'"]
    assert field.value["hash"] == "target_a"


# @features submission link
# @dimensions import internal no-match
@pytest.mark.unit
def test_import_submission_internal_link_no_match_records_error(
    get_schema, monkeypatch
):
    entity = _links_import_entity(get_schema, "Import missing link", "missing")

    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.files.find_page",
        lambda *args, **kwargs: {
            "id": None,
            "warnings": [],
            "errors": ["No page found for Top link: 'Missing Page'"],
        },
    )

    entity.import_submission(
        {"top_link": "Missing Page"},
        _MinimalImportProcess(),
    )

    field = entity.properties.submission.fields["top_link"]
    assert field.errors == ["No page found for Top link: 'Missing Page'"]
    assert "submission" not in entity.db


# @features submission form-table link
# @dimensions import internal entity-resolution
@pytest.mark.unit
def test_import_submission_table_internal_link_exact_match(get_schema, monkeypatch):
    entity = _links_import_entity(get_schema, "Import table exact link", "table_exact")
    calls = []

    def find_page(value, match_field_label="Name", fuzzy=False, error_label=None):
        calls.append((value, match_field_label, fuzzy, error_label))
        return {"id": "target_b", "warnings": [], "errors": []}

    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.files.find_page", find_page
    )
    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.Entities.fetch_one",
        _internal_link_entity,
    )

    entity.import_submission(
        {"with_rows": [["Target Page"]]},
        _MinimalImportProcess(),
    )

    assert calls == [("Target Page", "Name", False, "[With rows] Related")]
    assert json.loads(entity.db["submission"]) == {
        "with_rows": {
            "rows": [
                {
                    "row_rel": {
                        "id": "target_b",
                        "name": "Page-target_b",
                        "hash": "target_b",
                    }
                }
            ]
        }
    }


# @features submission form-table link
# @dimensions import internal fuzzy-match weak-match
@pytest.mark.unit
def test_import_submission_table_internal_link_fuzzy_match_warning(
    get_schema, monkeypatch
):
    entity = _links_import_entity(get_schema, "Import table fuzzy link", "table_fuzzy")

    def find_page(value, match_field_label="Name", fuzzy=False, error_label=None):
        assert fuzzy is True
        return {
            "id": "target_b",
            "warnings": ["Weak match for [With rows] Related: 'Target Page'"],
            "errors": [],
        }

    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.files.find_page", find_page
    )
    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.Entities.fetch_one",
        _internal_link_entity,
    )

    entity.import_submission(
        {"with_rows": [["Targt Page"]]},
        _MinimalImportProcess(fuzzy_fields={"row_rel"}),
    )

    field = entity.properties.submission.fields["with_rows"]
    assert field.warnings == ["Weak match for [With rows] Related: 'Target Page'"]
    assert field.value["rows"][0]["row_rel"]["hash"] == "target_b"


# @features submission form-table link
# @dimensions import internal no-match
@pytest.mark.unit
def test_import_submission_table_internal_link_no_match_records_error(
    get_schema, monkeypatch
):
    entity = _links_import_entity(get_schema, "Import table missing link", "table_missing")

    monkeypatch.setattr(
        "lagniappe.core.properties.form_links.files.find_page",
        lambda *args, **kwargs: {
            "id": None,
            "warnings": [],
            "errors": ["No page found for [With rows] Related: 'Missing Page'"],
        },
    )

    entity.import_submission(
        {"with_rows": [["Missing Page"]]},
        _MinimalImportProcess(),
    )

    field = entity.properties.submission.fields["with_rows"]
    assert field.errors == ["No page found for [With rows] Related: 'Missing Page'"]
    assert "submission" not in entity.db


# @features submission form-table
# @dimensions import list-normalization
@pytest.mark.unit
def test_import_submission_preserves_table_row_lists_during_input_list_normalization(
    get_schema,
):
    entity = TestEntities.get(
        "PAGE", {"name": "Import table page", "hash": "imptbl"}
    )
    form = TestEntities.get("FORM", {"name": "F", "hash": "imptblf"})
    form.schema = get_schema("integration_two_column_table")
    entity.form = form

    entity.import_submission(
        {"tbl": [["Ada", "Lovelace"]]},
        _MinimalImportProcess(),
    )

    assert json.loads(entity.db["submission"]) == {
        "tbl": {"rows": [{"a": "Ada", "b": "Lovelace"}]}
    }
