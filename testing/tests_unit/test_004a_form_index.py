"""Form list index UI ([lagniappe/core/entities/index.py](lagniappe/core/entities/index.py) ``FormIndex``).

Exercises table columns and ``entity.column()`` for forms in a listing context.
Does **not** cover ``Form.update``, ``Form.save``, or ``SchemaVersion`` — see
``test_004_form_properties.py`` for the ``Form`` entity.
"""

import pytest


# @matrix form-index : columns table
@pytest.mark.unit
def test_form_index_table(get_test_entities):
    """Test FormIndex.table produces correct column structure for UI.

    FormTable columns: Name, FormType, Categories, Projects, Modified
    (see ``FormTable`` in ``lagniappe/core/properties/index.py``).
    Verifies ``entity.column(field_id)`` returns correct ``column_value``.
    """
    from lagniappe.core.entities.index import FormIndex

    forms = get_test_entities()

    for form in forms:
        form.name = form.test_spec["name"]
        form.form_type = form.test_spec["form_type"]
        # The JSON helper materializes these fixture relations lazily.
        _ = form.categories
        _ = form.projects

    form_index = FormIndex()
    form_index._forms = forms

    table = form_index.table

    assert table.columns == [
        {
            "field": "name",
            "title": "Name",
            "icon": "text",
            "ordering": "lexical",
            "selected": True,
            "link": True,
            "parent": True,
            "schema": {"type": "input", "input": "text"},
        },
        {
            "field": "form_type",
            "title": "Form Type",
            "icon": "form",
            "ordering": "categorical",
            "selected": True,
            "link": True,
            "parent": True,
            "schema": None,
        },
        {
            "field": "categories",
            "title": "Categories",
            "icon": "category",
            "ordering": "categorical",
            "selected": True,
            "link": True,
            "parent": True,
            "schema": None,
        },
        {
            "field": "projects",
            "title": "Projects",
            "icon": "project",
            "ordering": "categorical",
            "selected": True,
            "link": True,
            "parent": True,
            "schema": None,
        },
        {
            "field": "modified",
            "title": "Modified",
            "icon": "date",
            "ordering": "numeric",
            "selected": True,
            "link": True,
            "parent": True,
            "schema": None,
        },
    ]
    assert table.selected == [
        "name",
        "form_type",
        "categories",
        "projects",
        "modified",
    ]

    for form in forms:
        expected = form.test_spec["expected_columns"]
        assert form.column("name").column_value == expected["name"]
        assert form.column("form_type").column_value == expected["form_type"]
        assert form.column("categories").column_value == expected["categories"]
        assert form.column("projects").column_value == expected["projects"]
