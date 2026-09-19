"""Unit tests for CategoryTable via PageIndex with in-memory pages.

``PageIndex.pages`` and route integration hit the database/Flask stack—covered in e2e
(e.g. testing/tests_e2e/test_007_category_index.py), not here.
"""

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
    assert categories and pages

    # Set properties that need to be set via setter
    for category in categories:
        category.name = category.test_spec.get("name")

    for page in pages:
        page.name = page.test_spec.get("name")
        page.description = page.test_spec.get("description")

    for category in categories:
        # Attach pages to category as their model
        for page in pages:
            page.model = category

        page_index = category.index()
        page_index._pages = pages

        table = page_index.table

        assert [
            (c["field"], c["title"], c["icon"], c["ordering"], c["selected"])
            for c in table.columns
        ] == [
            ("image", "Image", "image", "exists", False),
            ("name", "Name", "text", "lexical", True),
            ("form", "Form", "form", "categorical", False),
            ("description", "Description", "textarea", None, False),
            ("modified", "Modified", "date", "numeric", True),
        ]
        assert table.selected == ["name", "modified"]
        assert table.fields["name"].link is True
        assert table.fields["name"].parent is False

        # Verify entity.column() returns correct column_value for each page
        for page in pages:
            # image - returns asset URL if exists, None otherwise
            image_col = page.column("image")
            if page.assets.get("image"):
                assert image_col.column_value == "https://test.example/test.jpg"
            else:
                assert image_col.column_value is None

            # name - returns entity details dict
            name_col = page.column("name")
            assert {key: name_col.column_value[key] for key in ("name", "hash", "kind")} == {
                "name": page.test_spec["name"], "hash": page.test_spec["hash"], "kind": "page",
            }

            # form — assert own fixture form; pages without one may inherit category form
            form_col = page.column("form")
            if page.test_spec.get("form"):
                assert {key: form_col.column_value[key] for key in ("name", "hash", "kind")} == {
                    "name": "Page Form", "hash": "pgform1", "kind": "form",
                }
            elif page.model and page.model.form:
                assert {key: form_col.column_value[key] for key in ("name", "hash", "kind")} == {
                    "name": "Category Form", "hash": "catform", "kind": "form",
                }

            # description - returns description string
            desc_col = page.column("description")
            assert desc_col.column_value == page.test_spec.get("description")
