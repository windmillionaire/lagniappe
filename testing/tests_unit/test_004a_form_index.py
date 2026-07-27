"""Form list index UI ([lagniappe/core/entities/index.py](lagniappe/core/entities/index.py) ``FormIndex``).

Exercises table columns and ``entity.column()`` for forms in a listing context.
Does **not** cover ``Form.update``, ``Form.save``, or ``SchemaVersion`` — see
``test_004_form_properties.py`` for the ``Form`` entity.
"""

import pytest


# @features form-index
# @dimensions table columns
@pytest.mark.unit
def test_form_index_table(get_test_entities):
    """Test FormIndex.table produces correct column structure for UI.

    FormTable columns: Name, FormType, Categories, Projects, Modified
    (see ``FormTable`` in ``lagniappe/core/properties/index.py``).
    Verifies ``entity.column(field_id)`` returns correct ``column_value``.
    """
    from lagniappe.core.entities.index import FormIndex

    forms = get_test_entities()

    # set properties that need to be set via setter
    for form in forms:
        form.name = form.test_spec.get("name")
        form.form_type = form.test_spec.get("form_type")

    form_index = FormIndex()
    form_index._forms = forms

    table = form_index.table

    # 5 columns with metadata from ``Columns.columns`` (includes link/parent flags)
    assert len(table.columns) == 5
    column_keys = {
        "field",
        "title",
        "icon",
        "ordering",
        "selected",
        "link",
        "parent",
        "schema",
    }
    for col in table.columns:
        assert set(col.keys()) == column_keys

    # all selected by default
    assert table.selected == [
        "name",
        "form_type",
        "categories",
        "projects",
        "modified",
    ]

    # verify entity.column() returns correct column_value for each form
    for form in forms:
        # name - returns entity details dict
        name_col = form.column("name")
        assert name_col.column_value == form.details

        # form_type - returns the type string
        type_col = form.column("form_type")
        assert type_col.column_value == form.test_spec.get("form_type")

        # categories - returns list of category details
        cat_col = form.column("categories")
        expected_cats = [c.reference_details for c in form.categories]
        assert cat_col.column_value == expected_cats

        # projects — list of project details
        proj_col = form.column("projects")
        expected_projects = [p.reference_details for p in form.projects]
        assert proj_col.column_value == expected_projects

        # modified - column exists (value tested in test_entity_modified)
        assert form.column("modified") is not None
