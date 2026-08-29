"""Unit tests for table field submissions (entities from ``003e_tables.json``)."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.mixins.submitter import normalize_submission_values
from lagniappe.core.properties.form_links import Link
from lagniappe.core.properties.row_submission import RowSubmission
from testing.utility.mock_submission import WebFormSubmission
from testing.utility.test_entities import TestEntities


class _MinimalImportProcess:
    def fuzzy_match(self, field_id):
        return False

    separator = ","


def _run_row_submission_case(entity, get_schema):
    entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
    mock = entity.test_spec.get("mock_link_attributes")
    ctx = (
        patch(
            "lagniappe.core.properties.form_links.external.get_link_attributes",
            return_value=mock,
        )
        if mock
        else nullcontext()
    )
    with ctx:
        rs = entity.test_spec["row_submission"]
        table = entity.properties.submission.fields[rs["table_id"]]
        row = table.validate_row_submission(
            normalize_submission_values(
                WebFormSubmission(rs["values"]),
                table.fields,
            )
        )
        assert row == entity.test_spec["expected_row"]


# @matrix form-table : column db-value form-submission
@pytest.mark.unit
def test_table_form_single_row(get_test_entities, get_schema, test_submission_values):
    """Hidden JSON input with one row round-trips through validate_submission."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix form-table : ai-value multiple-rows
@pytest.mark.unit
def test_table_ai_multiple_rows(get_test_entities, get_schema, test_submission_values):
    """AI ingress supplies ``{rows: [{col_id: v}, ...]}``."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix form-table : column empty form-submission
@pytest.mark.unit
def test_table_form_empty(get_test_entities, get_schema, test_submission_values):
    """Empty ``rows`` yields null ``form_value`` and null ``column_value``."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @pair form-table:import
@pytest.mark.unit
def test_table_import_single_row(get_test_entities, get_schema, test_submission_values):
    """CSV-style list of values per row matches column field order."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix form-table : ai-value filter-value import multiple-rows
@pytest.mark.unit
def test_table_import_multiple_rows(get_test_entities, get_schema, test_submission_values):
    """Multiple import rows preserve order for filter/AI projections."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @pair form-table:row-submission
@pytest.mark.unit
def test_table_row_submission_text_email_checkbox(get_test_entities, get_schema):
    """Row validator coerces checkbox ``on`` and builds column ``form_value`` dict."""
    for entity in get_test_entities():
        _run_row_submission_case(entity, get_schema)


# @matrix link : external metadata row-submission
@pytest.mark.unit
def test_table_row_submission_external_link_column(get_test_entities, get_schema):
    """Multipart external link keys collapse to ``{url, title}`` (metadata mocked)."""
    for entity in get_test_entities():
        _run_row_submission_case(entity, get_schema)


# @matrix form-table : column form-submission mixed-columns search-value
@pytest.mark.unit
def test_table_form_mixed_column_types(get_test_entities, get_schema, test_submission_values):
    """Table row: text (search), time, number, tel (date columns use same path as top-level dates)."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @pair form-table:import
@pytest.mark.unit
def test_table_import_mixed_column_types(get_test_entities, get_schema, test_submission_values):
    """Import row order matches columns for text, time, number, tel."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix link : entity-resolution internal row-submission
@pytest.mark.unit
def test_table_row_submission_internal_link_column(get_test_entities, get_schema):
    """Internal link column resolves via ``Entities.fetch_one`` on validation."""
    for entity in get_test_entities():
        spec = entity.test_spec
        entity.form.schema = get_schema(spec["form"]["schema"])
        table = entity.properties.submission.fields[spec["row_submission"]["table_id"]]
        normalized = normalize_submission_values(
            WebFormSubmission(spec["row_submission"]["values"]),
            table.fields,
        )

        def _fake_get(identifier, *, request):
            return SimpleNamespace(
                details={
                    "id": identifier,
                    "name": f"Page-{identifier}",
                    "hash": identifier,
                }
            )

        with patch(
            "lagniappe.core.properties.form_links.Entities.fetch_one",
            side_effect=_fake_get,
        ):
            new_row = RowSubmission.validate_submission(table, normalized)
        got = {fid: f.form_value for fid, f in new_row.fields.items()}
        assert got == spec["expected_row"]
        hashes = [
            f.value.get("hash")
            for f in new_row.fields.values()
            if isinstance(f, Link) and f.is_entity_valued and f.value
        ]
        assert hashes == spec["expected_link_hashes"]


# @matrix form-table : import validation
@pytest.mark.unit
def test_table_import_row_length_mismatch(get_test_entities, get_schema):
    for entity in get_test_entities():
        spec = entity.test_spec
        entity.form.schema = get_schema(spec["form"]["schema"])
        with pytest.raises(ValidationError) as excinfo:
            entity.import_submission(
                spec["import_submission"],
                _MinimalImportProcess(),
            )
        assert spec["expected_error_substring"] in str(excinfo.value)
        assert "Row length does not match number of columns" in str(excinfo.value)


# @matrix form-table : import validation
@pytest.mark.unit
def test_table_validate_import_row_length_mismatch_raises_value_error(
    get_schema,
):
    entity = TestEntities.get(
        "PAGE",
        {
            "name": "Direct row length page",
            "hash": "page_direct_badrow",
            "form": {
                "name": "Two col form",
                "hash": "form_direct_badrow",
                "schema": "integration_two_column_table",
            },
        },
    )
    entity.form.schema = get_schema("integration_two_column_table")
    table = entity.properties.submission.fields["tbl"]

    with pytest.raises(ValueError, match="Row length does not match"):
        table.validate_import([["only_one_cell"]])


# @matrix form-table : form-submission validation
@pytest.mark.unit
def test_table_validate_submission_invalid_json(get_test_entities, get_schema):
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        table = entity.properties.submission.fields["type_grid"]
        with pytest.raises(json.JSONDecodeError):
            table.validate_submission("{not valid json")
