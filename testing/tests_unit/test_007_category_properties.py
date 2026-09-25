"""Unit tests for Category entity properties wired in category entity and category.py.

Covers ``CategoryFilters`` (conditions, entity-valued form conditions, page
``to_filter_index``), ``Category.schema`` (delegates to ``form.schema``), and
``RelatedForms.add``.

Out of scope here: ``PageIndex.pages`` (database + ``url_for``),
``Category.save`` / full ``create`` persistence, and ``ai_generated``—use e2e or
other suites where those paths are mocked or exercised end-to-end.
"""

from datetime import datetime, timezone
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
    assert categories and pages

    # set schema on category forms
    for category in categories:
        category.name = category.test_spec.get("name")
        if category.form:
            category.form.schema = get_schema(category.test_spec["form"]["schema"])

    # set page properties and schemas on page forms
    for page in pages:
        page.modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
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
            if "form" not in page.test_spec:
                page.form = category.form

        # verify category.filters.conditions structure
        conditions = category.filters.conditions
        assert [c["field"] for c in conditions if "hash" not in c] == [
            "name", "description", "categories", "has_document", "has_image",
            "is_public", "modified",
        ]
        assert [(c["field"], c["hash"]) for c in conditions if "hash" in c] == [
            tuple(item) for item in category.test_spec["expected_entity_fields"]
        ]

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

            projected_fields = {
                "name", "description", "categories", "has_document", "has_image",
                "is_public", "modified", "form",
            }
            expected_form = page.test_spec.get("form", category.test_spec.get("form"))
            assert {key: value for key, value in page_index.items()
                    if key in projected_fields} == {
                **page.test_spec["expected_filter"],
                "categories": [category.hash], "modified": 1767225600.0,
                **({"form": expected_form["hash"]} if expected_form else {}),
            }


# @matrix category form-schema : delegation schema
@pytest.mark.unit
def test_category_schema(get_test_entities, get_schema):
    """Category.schema mirrors attached form.schema when a form exists; else None."""
    entities = get_test_entities()
    assert entities
    for category in entities:
        if category.test_spec.get("form"):
            category.form.schema = get_schema(category.test_spec["form"]["schema"])
            assert category.schema is category.form.schema
        else:
            assert category.schema is None


# @matrix category permissions : attached-form cache restricted-access
# @source lagniappe/core/entities/category.py::Category
@pytest.mark.unit
def test_category_access_is_independent_of_attached_form_restrictions():
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
    page = TestEntities.get(
        "PAGE", {"name": "Restricted Form Page", "hash": "page007r"}
    )
    page.form = form
    page.model = category

    assert not form.allowed(Action.VIEW, user=viewer)
    assert category.allowed(Action.VIEW, user=viewer)
    assert not any(field.startswith("restricted_to") for field in category.to_cache)
    assert not page.allowed(Action.VIEW, user=viewer)
    assert page.to_cache["restricted_to_page_form"] == "secret_group"
    assert not category.allowed(
        Action.VIEW,
        user=UtilityTestUser(owner=False, permissions={"forms": "VIEW"}),
    )


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
    assert [(c["field"], c["hash"]) for c in category.filters.conditions
            if "hash" in c] == [("form", "primform1"), ("form", "relform1")]


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
@pytest.mark.parametrize("primary_loaded", [True, False])
def test_related_forms_add_skips_primary_form_and_registers_relation(primary_loaded):
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
    if primary_loaded:
        category.form = primary
    else:
        category.db["form"] = primary.key
    forms = category.properties.forms

    forms.add(primary)

    assert forms.value == []
    assert category.db.get("forms", []) == []
    assert category.mutation_intents == []
    assert related.key not in category.related_entities

    forms.add(related)
    forms.add(related)

    assert forms.value == [related]
    assert category.db["forms"] == [related.key]
    assert category.related_entities[related.key] is related
    assert len(category.mutation_intents) == 1
    assert category.mutation_intents[0].intent is MutationIntentType.TOUCH
    assert category.mutation_intents[0].entity is related


# @matrix category form : add related-forms relation-registration
@pytest.mark.unit
def test_related_forms_add_existing_key_does_not_load_other_forms():
    category = TestEntities.get("CATEGORY", {"name": "Stored form registry"})
    current = TestEntities.get("FORM", {"name": "Current page form"})
    other = TestEntities.get("FORM", {"name": "Another page's form"})
    category.db["forms"] = [current.key, other.key]
    forms = category.properties.forms
    assert not forms.is_set

    assert forms.add(current) is False

    assert forms.keys == [current.key, other.key]
    assert not forms.is_set
    assert category.mutation_intents == []


# @matrix category form : related-forms validation
@pytest.mark.unit
def test_related_forms_add_rejects_value_without_key():
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Invalid Related Forms Category", "hash": "catrelbad"},
    )

    with pytest.raises(ValueError, match="Value must have a key"):
        category.properties.forms.add(SimpleNamespace())
