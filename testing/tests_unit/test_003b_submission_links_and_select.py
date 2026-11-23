"""Link, select, and radio submission paths (``003b_submission_links_and_select.json``).

Location field edge cases and Places helpers are in ``test_003d_submission_location.py``.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.properties.form_select import Select
from lagniappe.core.tools.http import OutboundResult, OutboundStatus

pytestmark = pytest.mark.unit


# @matrix radio : ai-value column filter-value fuzzy-match import
def test_submission_radio(get_test_entities, get_schema, test_submission_values):
    """Test Radio field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix select : ai-value column filter-value import
def test_submission_select_single(
    get_test_entities, get_schema, test_submission_values
):
    """Test Select single field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix select : ai-value column filter-value fuzzy-match import multiple separator
def test_submission_select_multiple(
    get_test_entities, get_schema, test_submission_values
):
    """Test Select multiple field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix link : ai-value external filter-value import
def test_submission_link_external(
    get_test_entities, get_schema, test_submission_values
):
    """Test Link external field outputs with mocked external calls."""
    with patch(
        "lagniappe.core.properties.form_links.external.get_link_attributes",
        return_value={"name": "Mocked Title"},
    ):
        for entity in get_test_entities():
            entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
            test_submission_values(entity)


# @matrix bookmark : ai-value filter-value
def test_submission_bookmark(get_test_entities, get_schema, test_submission_values):
    """Test Bookmark field outputs with mocked metadata fetch."""
    with patch(
        "lagniappe.core.properties.form_links.external.get_bookmark_metadata",
        return_value={},
    ):
        for entity in get_test_entities():
            entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
            test_submission_values(entity)


# @matrix bookmark : replace-fields side-effects
def test_submission_bookmark_replace_flags_update_entity_fields(
    get_test_entities, get_schema, test_submission_values
):
    """Test Bookmark replacement flags update the entity and save fetched image."""
    metadata = {
        "name": "Fetched Bookmark Title",
        "description": "Fetched bookmark description",
        "image": "https://images.example/bookmark.png",
    }
    downloaded = OutboundResult(
        OutboundStatus.OK,
        body=b"image-content",
        media_type="image/png",
        size=len(b"image-content"),
    )

    with (
        patch(
            "lagniappe.core.properties.form_links.external.get_bookmark_metadata",
            return_value=metadata,
        ) as get_metadata,
        patch(
            "lagniappe.core.properties.form_links.download_image",
            return_value=downloaded,
        ) as download_image,
    ):
        for entity in get_test_entities():
            saved_assets = []

            def save_asset(content, name, asset_type, visibility="private", *, saved_assets=saved_assets):
                saved_assets.append((content, name, asset_type, visibility))
                return True

            entity.save_asset = save_asset
            entity.form.schema = get_schema(entity.test_spec["form"]["schema"])

            test_submission_values(entity)

            assert entity.name == metadata["name"]
            assert entity.description == metadata["description"]
            assert len(saved_assets) == 1
            saved_image, saved_name, saved_type, visibility = saved_assets[0]
            assert saved_image.getvalue() == b"image-content"
            assert saved_image.content_type == "image/png"
            assert (saved_name, saved_type, visibility) == (
                "bookmark-ab12",
                "image",
                "private",
            )
            get_metadata.assert_called_once_with(
                {
                    "url": "https://bookmark.example.com",
                    "title": "Original Bookmark",
                    "replace-image": "on",
                    "replace-name": "on",
                    "replace-description": "on",
                }
            )
            download_image.assert_called_once_with(metadata["image"])


# @matrix location : ai-value column filter-value import
def test_submission_location(get_test_entities, get_schema, test_submission_values):
    """Test Location field outputs with mocked place details."""
    # Use side_effect (not return_value) so each validation gets a fresh dict.
    mocked_location = {"id": "mock_place_123", "name": "Mocked Location"}

    def _fresh_place_response(*_a, **_k):
        return mocked_location.copy()

    with (
        patch(
            "lagniappe.core.properties.form_links.location.get_place_details",
            side_effect=_fresh_place_response,
        ),
        patch(
            "lagniappe.core.properties.form_links.location.resolve_location_query",
            side_effect=_fresh_place_response,
        ),
    ):
        for entity in get_test_entities():
            entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
            test_submission_values(entity)


def test_select_fuzzy_lookup_without_a_candidate_and_read_only_options(monkeypatch):
    field = Select(
        {"id": "category", "options": [{"value": "h", "label": "Home"}]},
        entity=SimpleNamespace(entity_kind="page"),
    )
    field.fuzzy_match = True
    monkeypatch.setattr(
        "lagniappe.core.properties.form_select.process.extractOne",
        lambda *_: None,
    )
    field.validate_import(values=["Unknown"])
    assert field.value is None
    assert len(field.warnings) == 1
    assert "No match found" in field.warnings[0]
    with pytest.raises(AttributeError):
        field.choices = {}
    with pytest.raises(AttributeError):
        field.field_type = None
