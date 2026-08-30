"""Unit tests for Category entity properties wired in category entity and category.py.

Covers ``CategoryFilters`` (conditions, entity-valued form conditions, page
``to_filter_index``), ``Category.schema`` (delegates to ``form.schema``), and
``RelatedForms.add``.

Out of scope here: ``PageIndex.pages`` (database + ``url_for``),
``Category.save`` / full ``create`` persistence, and ``ai_generated``—use e2e or
other suites where those paths are mocked or exercised end-to-end.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from google.cloud import datastore
import pytest

from lagniappe.core.definitions import Action, MutationIntentType
from lagniappe.core.entities.category import Category, UNCATEGORIZED_PAGES_NAME
from lagniappe.core.entities import category as category_module
from testing.utility.test_entities import TestEntities, TestUser as UtilityTestUser


# @matrix category filters page : conditions entity-fields filter-value
@pytest.mark.unit
def test_category_filters(get_test_entities, get_schema):
    """Test CategoryFilters conditions and page filter index values.

    Base filter fields (see lagniappe/core/properties/category.py CategoryFilters):
    Name, Description, Categories, Document, Image, IsPublic, Modified—seven
    conditions plus one entity-valued row per distinct form in entity_fields
    (primary ``form`` + any extras from ``forms``).

    Tests category.filters.conditions shape and page to_filter_index alignment.
    """
    entities = get_test_entities()
    categories = [e for e in entities if e.entity_kind == "category"]
    pages = [e for e in entities if e.entity_kind == "page"]

    # set schema on category forms
    for category in categories:
        category.name = category.test_spec.get("name")
        if category.form:
            category.form.schema = get_schema(category.test_spec["form"]["schema"])

    # set page properties and schemas on page forms
    for page in pages:
        page.name = page.test_spec.get("name")
        page.description = page.test_spec.get("description")
        if "public" in page.test_spec:
            page.db["public"] = page.test_spec["public"]
        if page.form and not page.form.schema:
            page.form.schema = get_schema(page.test_spec["form"]["schema"])

    for category in categories:
        # attach all pages to this category as their model
        for page in pages:
            page.model = category

        # verify category.filters.conditions structure
        conditions = category.filters.conditions
        # 7 base filter fields + 1 entity field per form
        form_count = 1 if category.form else 0
        expected_count = 7 + form_count
        assert len(conditions) == expected_count

        base_keys = {"field", "label", "kind", "icon"}
        entity_keys = base_keys | {"hash", "key"}
        for cond in conditions:
            assert cond.keys() in (base_keys, entity_keys), (
                f"Unexpected condition keys: {set(cond.keys())}"
            )

        # verify set_field_attributes modifications
        name_field = category.filters.fields["name"]
        assert name_field.filter_label == "Page Name"
        assert name_field.filter_kind == "page"

        modified_field = category.filters.fields["modified"]
        assert modified_field.filter_kind == "page"

        # if category has form, entity_fields should include form hash
        if category.form:
            assert category.form.hash in category.filters.entity_fields

        # test filter values on pages
        for page in pages:
            page_index = page.to_filter_index()

            for f in category.properties.filters.conditions:
                field_key = f["field"]
                if "hash" in f:
                    # entity-valued condition (form) — only pages with a fixture form;
                    # others may inherit form from model category without a form filter key
                    if field_key == "form" and page.test_spec.get("form"):
                        assert page_index["form"] == page.properties.form.filter_value
                elif field_key == "categories":
                    assert page_index[field_key] == [category.hash]
                elif field_key in category.filters.fields:
                    property_id = category.filters.fields[field_key].id
                    if page.properties.get(property_id):
                        assert (
                            page_index.get(field_key)
                            == page.properties[property_id].filter_value
                        )


# @matrix category form-schema : delegation schema
@pytest.mark.unit
def test_category_schema(get_test_entities, get_schema):
    """Category.schema mirrors attached form.schema when a form exists; else None."""
    for category in get_test_entities():
        if category.test_spec.get("form"):
            category.form.schema = get_schema(category.test_spec["form"]["schema"])
            assert category.schema is category.form.schema
        else:
            assert category.schema is None


# @matrix category form permissions : attached-form cache restricted-access
@pytest.mark.unit
def test_category_restricted_to_follows_attached_form():
    viewer = UtilityTestUser(
        owner=False,
        permissions={"models": "VIEW", "forms": "VIEW"},
    )
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Restricted Form Category", "hash": "cat007r"},
    )
    form = TestEntities.get(
        "FORM",
        {
            "name": "Restricted Form",
            "hash": "form007r",
            "restricted_to": ["secret_group"],
        },
    )

    category.form = form

    assert category.restricted_to == ["secret_group", "owner"]
    assert not category.allowed(Action.VIEW, user=viewer)
    assert category.to_cache["restricted_to"] == "secret_group,owner"


# @matrix category pages : default-category get-create
@pytest.mark.unit
def test_uncategorized_pages_get_create():
    existing = datastore.Entity(
        key=datastore.Key("models", "uncategorized-pages", project="test")
    )
    existing.update(
        {
            "name": UNCATEGORIZED_PAGES_NAME,
            "type": "category",
            "active": True,
        }
    )

    with patch.object(
        category_module.database_get,
        "category_by_name",
        return_value=existing,
    ):
        category = Category.get_uncategorized_pages()

    assert isinstance(category, Category)
    assert category.name == UNCATEGORIZED_PAGES_NAME

    created = Mock()
    with (
        patch.object(
            category_module.database_get,
            "category_by_name",
            return_value=None,
        ),
        patch.object(Category, "create", return_value=created) as create,
    ):
        assert Category.get_uncategorized_pages() is created

    create.assert_called_once_with({"name": UNCATEGORIZED_PAGES_NAME})
    created.save.assert_called_once_with()


# @matrix category filters form : entity-fields related-forms
@pytest.mark.unit
def test_category_filters_related_forms(get_test_entities, get_schema):
    """entity_fields adds RelatedForm rows for primary form plus forms from ``forms``."""
    category = get_test_entities()[0]
    category.name = category.test_spec.get("name")
    category.form.schema = get_schema(category.test_spec["form"]["schema"])

    related = TestEntities.get(
        "FORM",
        {
            "name": "Related Form",
            "hash": "relform1",
            "schema": "selection_types",
        },
    )
    related.schema = get_schema("selection_types")
    category.properties.forms.value = [related]
    category.properties.filters.reset()

    assert category.form.hash in category.filters.entity_fields
    assert related.hash in category.filters.entity_fields
    assert len(category.filters.conditions) == 7 + 2


# @matrix category filters permissions : conditions entity-fields view-access
@pytest.mark.unit
def test_category_filter_conditions_include_only_viewable_forms():
    category = Category(testing=True)
    category.db.update(
        {"name": "Filtered Category", "hash": "filtered_category", "type": "category"}
    )
    primary = TestEntities.get(
        "FORM", {"name": "Primary Form", "hash": "primary_visible_form"}
    )
    related = TestEntities.get(
        "FORM", {"name": "Related Form", "hash": "related_visible_form"}
    )
    hidden = TestEntities.get(
        "FORM", {"name": "Hidden Form", "hash": "hidden_category_form"}
    )
    primary.allowed = lambda action, user=None: True
    related.allowed = lambda action, user=None: True
    hidden.allowed = lambda action, user=None: False

    category.form = primary
    category.properties.forms.value = [related, hidden]

    entity_hashes = {
        condition["hash"]
        for condition in category.filters.conditions
        if "hash" in condition
    }

    assert primary.hash in entity_hashes
    assert related.hash in entity_hashes
    assert hidden.hash not in entity_hashes


# @matrix category form : add duplicate-primary related-forms relation-registration
@pytest.mark.unit
def test_related_forms_add_skips_primary_form_and_registers_relation():
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Related Forms Category", "hash": "catrel"},
    )
    primary = TestEntities.get(
        "FORM",
        {"name": "Primary Form", "hash": "primary_form"},
    )
    related = TestEntities.get(
        "FORM",
        {"name": "Related Form", "hash": "related_form"},
    )
    category.form = primary
    forms = category.properties.forms

    forms.add(primary)

    assert forms.value == []
    assert category.db.get("forms", []) == []
    assert category.mutation_intents == []

    forms.add(related)
    forms.add(related)

    assert forms.value == [related]
    assert category.db["forms"] == [related.key]
    assert len(category.mutation_intents) == 1
    assert category.mutation_intents[0].intent is MutationIntentType.TOUCH
    assert category.mutation_intents[0].entity is related


# @matrix category form : related-forms validation
@pytest.mark.unit
def test_related_forms_add_rejects_value_without_key():
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Invalid Related Forms Category", "hash": "catrelbad"},
    )

    with pytest.raises(ValueError, match="Value must have a key"):
        category.properties.forms.add(SimpleNamespace())
