"""Unit tests for CategoryTable via PageIndex with in-memory pages.

``PageIndex.pages`` and route integration hit the database/Flask stack—covered in e2e
(e.g. testing/tests_e2e/test_007_category_index.py), not here.
"""

from types import SimpleNamespace

import pytest


# @matrix category-index : columns table
@pytest.mark.unit
def test_category_index(get_test_entities):
    """Test CategoryTable produces correct column structure for UI.

    CategoryTable has columns: Image, Name, AttachedForm, Description, Modified.
    Verifies entity.column(field_id) returns correct column_value for each.
    """
    entities = get_test_entities()
    categories = [e for e in entities if e.entity_kind == "category"]
    pages = [e for e in entities if e.entity_kind == "page"]

    # Set properties that need to be set via setter
    for category in categories:
        category.name = category.test_spec.get("name")

    for page in pages:
        page.name = page.test_spec.get("name")
        page.description = page.test_spec.get("description")
        raw = page.test_spec.get("assets", {}).get("image")
        if isinstance(raw, dict):
            page.test_spec.setdefault("assets", {})["image"] = SimpleNamespace(
                url=f"https://test.example/{raw.get('path', 'image')}"
            )

    for category in categories:
        # Attach pages to category as their model
        for page in pages:
            page.model = category

        page_index = category.index()
        page_index._pages = pages

        table = page_index.table

        # 5 base columns; each column dict includes at least table metadata keys
        assert len(table.columns) == 5
        required = {"field", "title", "icon", "ordering", "selected"}
        for col in table.columns:
            assert required.issubset(col.keys()), f"Missing keys in {col.keys()}"

        # Verify column field order
        expected_fields = ["image", "name", "form", "description", "modified"]
        assert [c["field"] for c in table.columns] == expected_fields

        # Verify entity.column() returns correct column_value for each page
        for page in pages:
            # image - returns asset URL if exists, None otherwise
            image_col = page.column("image")
            if page.assets.get("image"):
                assert image_col.column_value is not None
            else:
                assert image_col.column_value is None

            # name - returns entity details dict
            name_col = page.column("name")
            assert name_col.column_value == page.details

            # form — assert own fixture form; pages without one may inherit category form
            form_col = page.column("form")
            if page.test_spec.get("form"):
                assert form_col.column_value == page.form.reference_details
            elif page.model and page.model.form:
                assert form_col.column_value == page.model.form.reference_details

            # description - returns description string
            desc_col = page.column("description")
            assert desc_col.column_value == page.description

            # modified - column exists (value tested elsewhere due to timezone context)
            assert page.column("modified") is not None
