"""Link, select, and radio submission paths (``003b_submission_links_and_select.json``).

Location field edge cases and Places helpers are in ``test_003d_submission_location.py``.
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


# @features radio
# @dimensions ai-value, filter-value, import, column, fuzzy-match
def test_submission_radio(get_test_entities, get_schema, test_submission_values):
    """Test Radio field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features select
# @dimensions ai-value, filter-value, import, column
def test_submission_select_single(
    get_test_entities, get_schema, test_submission_values
):
    """Test Select single field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features select
# @dimensions ai-value, filter-value, import, column, multiple, separator, fuzzy-match
def test_submission_select_multiple(
    get_test_entities, get_schema, test_submission_values
):
    """Test Select multiple field outputs."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @features link
# @dimensions ai-value, filter-value, import, external
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


# @features bookmark
# @dimensions ai-value, filter-value
def test_submission_bookmark(get_test_entities, get_schema, test_submission_values):
    """Test Bookmark field outputs with mocked metadata fetch."""
    with patch(
        "lagniappe.core.properties.form_links.external.get_bookmark_metadata",
        return_value={},
    ):
        for entity in get_test_entities():
            entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
            test_submission_values(entity)


# @features bookmark
# @dimensions replace-fields side-effects
def test_submission_bookmark_replace_flags_update_entity_fields(
    get_test_entities, get_schema, test_submission_values
):
    """Test Bookmark replacement flags update the entity and save fetched image."""
    metadata = {
        "name": "Fetched Bookmark Title",
        "description": "Fetched bookmark description",
        "image": "https://images.example/bookmark.png",
    }
    downloaded = {"success": True, "file": "image-content"}

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

            def save_asset(content, name, asset_type, visibility="private"):
                saved_assets.append((content, name, asset_type, visibility))
                return True

            entity.save_asset = save_asset
            entity.form.schema = get_schema(entity.test_spec["form"]["schema"])

            test_submission_values(entity)

            assert entity.name == metadata["name"]
            assert entity.description == metadata["description"]
            assert saved_assets == [
                ("image-content", "bookmark-ab12", "image", "private")
            ]
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


# @features location
# @dimensions ai-value, filter-value, import, column
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
