"""Unit tests for ``normalize_submission_values`` and ``patch_submission`` (``003f_submission_normalize_patch.json``)."""

import json

import pytest

from lagniappe.core.mixins.submitter import normalize_submission_values
from testing.utility.mock_submission import WebFormSubmission


def _assert_normalize_case(entity, get_schema):
    entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
    case = entity.test_spec["normalize_case"]
    fields = entity.properties.submission.fields
    got = normalize_submission_values(WebFormSubmission(case["values"]), fields)
    assert got == case["expected"]


# @matrix submission : normalize unknown-keys
@pytest.mark.unit
def test_normalize_skips_keys_not_in_schema(get_test_entities, get_schema):
    for entity in get_test_entities():
        _assert_normalize_case(entity, get_schema)


# @matrix submission : multipart normalize
@pytest.mark.unit
def test_normalize_multipart_keys_merge_under_field_id(get_test_entities, get_schema):
    for entity in get_test_entities():
        _assert_normalize_case(entity, get_schema)


# @matrix submission : list-filtering normalize
@pytest.mark.unit
def test_normalize_drops_falsy_entries_in_lists(get_test_entities, get_schema):
    for entity in get_test_entities():
        _assert_normalize_case(entity, get_schema)


# @matrix submission : patch single-field
@pytest.mark.unit
def test_patch_submission_merges_single_field(get_test_entities, get_schema):
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        spec = entity.test_spec
        entity.form_submission(WebFormSubmission(spec["initial_submission"]))
        entity.patch_submission(spec["patch_payload"])
        assert json.loads(entity.db["submission"]) == spec["expected_submission"]


# @matrix submission : json-payload patch
@pytest.mark.unit
def test_patch_submission_accepts_json_string(get_test_entities, get_schema):
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        spec = entity.test_spec
        entity.form_submission(WebFormSubmission(spec["initial_submission"]))
        entity.patch_submission(spec["patch_payload_json"])
        assert json.loads(entity.db["submission"]) == spec["expected_submission"]
