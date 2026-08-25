"""``FormSubmission`` integration: cached ``fields`` and derived links.

Targets PAGE entities with an **attached** form (schema from JSON). Does **not**
exercise ``Form.save()`` or ``SchemaVersion``; ``save_submission`` updates the
**page** ``db`` submission and form metadata keys, not the ``Form`` entity record.
See ``004c_form_submission_integration.json``.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from testing.utility.mock_submission import WebFormSubmission
from testing.utility.test_entities import TestEntities


# @matrix submission : cache fields stale-db
@pytest.mark.unit
def test_submission_fields_stale_when_db_submission_changes(
    get_test_entities, get_schema
):
    """``fields`` is cached; mutating ``db['submission']`` alone does not refresh field values."""
    for entity in get_test_entities():
        spec = entity.test_spec
        entity.form.schema = get_schema(spec["form"]["schema"])
        entity.db["submission"] = json.dumps(spec["initial_submission_json"])
        submission = entity.properties.submission
        assert submission.fields["note"].db_value == "first"
        entity.db["submission"] = json.dumps(spec["mutated_submission_json"])
        assert submission.fields["note"].db_value == spec["expected_stale_note"]


# @matrix form-table submission : derived-page-keys internal links row-submission
@pytest.mark.unit
def test_submission_links_internal_top_level_and_table_row(
    get_test_entities, get_schema
):
    for entity in get_test_entities():
        spec = entity.test_spec
        entity.form.schema = get_schema(spec["form"]["schema"])

        def _fake_entities_get(identifier, *, request):
            return SimpleNamespace(
                details={
                    "id": identifier,
                    "name": f"Page-{identifier}",
                    "hash": identifier,
                    "kind": "page",
                }
            )

        rows = {"rows": [{"row_rel": "target_b"}]}
        with (
            patch(
                "lagniappe.core.properties.form_links.Entities.fetch_one",
                side_effect=_fake_entities_get,
            ),
            patch(
                "lagniappe.core.mixins.submitter.database.get.datastore_key",
                side_effect=lambda identifier: f"key:{identifier}",
            ),
        ):
            entity.form_submission(
                WebFormSubmission(
                    {
                        "top_link": "target_a",
                        "with_rows": json.dumps(rows),
                    }
                )
            )

            assert entity.derived_page_keys == ["key:target_a"]

        submission = entity.properties.submission
        # Top-level internal links resolve to entity details dicts; table row
        # links keep stored ids as strings until separately validated.
        def _internal_hash(link):
            return link.get("hash") if isinstance(link, dict) else link

        hashes = [_internal_hash(link) for link in submission.links]
        assert hashes == spec["expected_link_hashes"]


# @matrix link submission : internal stale-target
@pytest.mark.unit
def test_submission_internal_link_missing_target_clears_value(get_schema):
    entity = TestEntities.get(
        "PAGE",
        {
            "name": "Missing link target",
            "hash": "missing_link_pg",
            "form": {
                "name": "Links",
                "hash": "missing_link_form",
                "schema": "submission_integration_links",
            },
        },
    )
    entity.form.schema = get_schema("submission_integration_links")

    with patch(
        "lagniappe.core.properties.form_links.Entities.fetch_one", return_value=None
    ):
        entity.form_submission(WebFormSubmission({"top_link": "missing_target"}))

    assert entity.properties.submission.fields["top_link"].value is None
    assert "submission" not in entity.db
