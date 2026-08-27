"""Unit tests for Page entity properties in page.py.

Covers ``details``, ``Document`` (filter/cache/AI), ``Attributes`` (own vs model),
``IsPublic``, page owner save relations, and ``Page.to_cache`` when the linked
user is a public profile.

Out of scope here: ``Description``; deep ``FormSubmission`` / field hydration
(see test_004c_form_submission_integration); ``tasks`` / ``completed`` /
``view_access`` and datastore persistence (database or e2e).
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from google.cloud import datastore
import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.definitions import (
    Fetch,
    MutationEffectType,
    MutationIntent,
    MutationOperation,
)
from lagniappe.core.mutations import plan_mutation
from lagniappe.core.mixins import ColumnMixin
from lagniappe.core.properties import page_related
from lagniappe.core.properties.page_assets import Image
from lagniappe.core.properties.page_public import normalize_public_settings
from testing.utility.test_entities import TestEntities


class _EditablePageColumn(ColumnMixin):
    _editable = True


# @matrix page : details kind parent
@pytest.mark.unit
def test_page_details(get_test_entities):
    """Test details property for Page entities.

    DetailsMixin properties on Page:
    - Name: details_key="name", details_value=self.value
    - Kind: details_key="kind", details_value="user" if page has user else "page"
    - Hash: details_key="hash", details_value=self.value
    - PageModelCategory: details_key="parent", details_value=model.details (if not reserved)

    Entity.details also adds "id" (urlsafe_key) and filters out None values.
    """
    for page in get_test_entities():
        page.name = page.test_spec.get("name")

        details = page.details

        # All pages should have id, name, kind, hash
        assert details["id"] == page.urlsafe_key
        assert details["name"] == page.name
        assert details["hash"] == page.hash

        # kind = "user" if page has a user, otherwise entity_kind
        if page.user:
            assert details["kind"] == "user"
        else:
            assert details["kind"] == page.entity_kind

        # parent only present if model exists and is not reserved
        if page.model and not page.model.reserved:
            assert "parent" in details
            assert details["parent"]["id"] == page.model.urlsafe_key
        else:
            assert "parent" not in details


# @pairs deferred-jobs:active-operation pages:create-autofill
@pytest.mark.unit
def test_page_deferred_job_reference_round_trips():
    page = TestEntities.get(
        "PAGE",
        {"name": "Deferred Page", "hash": "pg008deferred"},
    )
    reference = {
        "key": "operation-key",
        "idempotency_key": "operation-request",
        "revision": 2,
    }

    page.deferred_job = reference

    assert page.deferred_job == reference
    assert json.loads(page.db["deferred_job"]) == reference
    assert "deferred_job" in page.exclude_from_index

    page.deferred_job = None

    assert page.deferred_job is None
    assert "deferred_job" not in page.db


# @matrix page : table-editability task-load
@pytest.mark.unit
def test_column_editable_does_not_load_page_tasks():
    """Generic table editability should not treat Page.completed as task state."""
    page = TestEntities.get("PAGE", {"name": "Editable", "hash": "pg008edit"})
    page._load_tasks = MagicMock(side_effect=AssertionError("_load_tasks called"))
    field = _EditablePageColumn()
    field.entity = page

    assert field.editable is True
    page._load_tasks.assert_not_called()


# @matrix page : ai-value cache document filter-value
@pytest.mark.unit
def test_page_document(get_test_entities):
    """Test Document property with CacheMixin, FilterMixin, AIMixin.

    Document has special behavior:
    - filter_value is boolean (True if entity.assets has "document")
    - cache_value and ai_value use entity.text_for_cache("document")
    - cache_key is "doc"
    - filter_key is "has_document"
    - ai_key is "page_document" for PAGE
    """
    for page in get_test_entities():
        if "attributes" in page.test_spec:
            page.db["attributes"] = page.test_spec["attributes"]
        document_text = page.text_for_cache("document")

        if document_text:
            # FilterMixin
            assert page.to_filter_index()["has_document"] is True
            # CacheMixin
            assert page.to_cache.get("doc") == document_text
            # AIMixin - ai_key is "page_document" for PAGE
            assert page.to_ai()["page_document"] == document_text
        else:
            assert page.to_filter_index()["has_document"] is False


# @matrix page : attributes defaults inheritance
@pytest.mark.unit
def test_page_attributes(get_test_entities):
    """Test Attributes property for Page entities.

    Page attributes (from CategoryAttributes): tasks, document, photo, notes, files.
    Pages can either have their own attributes or inherit from their model (category).
    entity.has(attr) returns True if attr is in db["attributes"] or if no attributes defined.
    """
    all_attrs = ["tasks", "document", "photo", "notes", "files"]

    for page in get_test_entities():
        if "attributes" in page.test_spec:
            # Page has its own attributes (overrides model if present)
            for attr in all_attrs:
                assert page.has(attr) == (attr in page.db["attributes"])

            # Verify override: if model has different attrs, page's take precedence
            if page.model and "attributes" in page.model.test_spec:
                model_attrs = page.model.test_spec["attributes"]
                page_attrs = page.test_spec["attributes"]
                for attr in all_attrs:
                    if attr in page_attrs and attr not in model_attrs:
                        assert page.has(attr) is True
                    if attr in model_attrs and attr not in page_attrs:
                        assert page.has(attr) is False

        elif page.model and "attributes" in page.model.test_spec:
            # Page inherits attributes from model (category)
            for attr in all_attrs:
                assert page.has(attr) == (attr in page.model.db["attributes"])

        else:
            # No attributes defined - all enabled by default
            for attr in all_attrs:
                assert page.has(attr) is True


# @matrix page : filter-value public
@pytest.mark.unit
def test_page_public(get_test_entities):
    """Test IsPublic property with FilterMixin.

    IsPublic has:
    - filter_value is boolean
    - filter_key is "is_public"
    - Value reads from entity.db["public"], defaults to False
    """
    for page in get_test_entities():
        is_public = page.test_spec.get("public", False)

        if "public" in page.test_spec:
            page.db["public"] = is_public

        # Property value matches db
        assert page.properties.is_public.value == page.is_public == is_public

        # Filter index
        assert page.to_filter_index()["is_public"] is is_public


# @matrix page sitemap : visibility
@pytest.mark.unit
def test_page_public_visibility_invalidates_sitemap_only_when_changed():
    page = TestEntities.get("PAGE", {"name": "Public", "hash": "public-page"})

    page.is_public = False
    assert page.mutation_intents == []

    page.is_public = True
    assert [intent.intent.value for intent in page.mutation_intents] == [
        "sitemap-invalidate"
    ]

    page.is_public = True
    assert len(page.mutation_intents) == 1


# @matrix page sitemap : metadata settings-validation
@pytest.mark.unit
def test_page_public_settings_normalize_and_invalidate_sitemap():
    page = TestEntities.get("PAGE", {"name": "Metadata", "hash": "metadata-page"})

    assert page.public_settings == {
        "version": 1,
        "allow_indexing": True,
        "title": None,
        "description": None,
        "preview_image_asset": None,
    }

    page.public_settings = {
        "title": "  Public title  ",
        "description": " Public description ",
        "preview_image_asset": "image_preview",
        "allow_indexing": True,
    }
    assert page.public_settings["title"] == "Public title"
    assert page.public_settings["description"] == "Public description"
    assert page.mutation_intents == []
    assert "public_settings" in page.exclude_from_index

    page.public_settings = {**page.public_settings, "allow_indexing": False}
    assert page.public_settings["allow_indexing"] is False
    assert page.mutation_intents[0].intent.value == "sitemap-invalidate"

    with pytest.raises(Exception, match="120 characters or fewer"):
        normalize_public_settings({"title": "x" * 121})


# @matrix cache page : public-user
@pytest.mark.unit
def test_page_to_cache_public_user(get_test_entities):
    """Page.to_cache returns {} when the page has a user with is_public (profile page)."""
    for page in get_test_entities():
        spec_user = page.test_spec.get("user")
        if spec_user and spec_user.get("public"):
            page.name = page.test_spec.get("name")
            page.user.db["public"] = bool(spec_user["public"])
            assert page.user.is_public is True
            assert page.to_cache == {}
        else:
            page.name = page.test_spec.get("name")
            if "attributes" in page.test_spec:
                page.db["attributes"] = page.test_spec["attributes"]
            text = page.text_for_cache("document")
            if text:
                assert page.to_cache.get("doc") == text


# @matrix page : cache-invalidation categories default-category model-category restrictions
@pytest.mark.unit
def test_page_categories_model_restricted_and_cache_invalidation(monkeypatch):
    page = TestEntities.get("PAGE", {"name": "Categorized", "hash": "pagecat"})
    model = TestEntities.get("CATEGORY", {"name": "Model", "hash": "modelcat"})
    new_model = TestEntities.get(
        "CATEGORY",
        {"name": "New Model", "hash": "newmodel"},
    )
    added = TestEntities.get("CATEGORY", {"name": "Added", "hash": "addedcat"})
    restricted = TestEntities.get(
        "CATEGORY",
        {"name": "Restricted", "hash": "restrictedcat"},
    )
    uncategorized = TestEntities.get(
        "CATEGORY",
        {"name": "Uncategorized Pages", "hash": "uncategorized"},
    )
    monkeypatch.setattr(
        page_related.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: uncategorized,
    )
    restricted.allowed = lambda *_args, **_kwargs: False
    page.model = model
    page.properties.categories._value = [restricted]
    page.properties.categories._all_categories = None

    assert page.properties.categories.value == [model, restricted]

    page.properties.categories.value = [model, added]

    assert page.db["categories"] == [added.key, restricted.key]
    assert page.properties.categories.value == [model, added, restricted]

    page.properties.categories.value = [added]

    assert page.model is None
    assert "model" not in page.db
    assert page.properties.categories.value == [added, restricted]

    page.model = new_model

    assert page.properties.categories.value == [new_model, added, restricted]

    page.properties.categories.remove(restricted)

    assert page.db["categories"] == [added.key]
    assert page.properties.categories.value == [new_model, added]

    page.properties.categories.remove(new_model)

    assert "model" not in page.db
    assert page.properties.categories.value == [added]

    page.properties.categories.value = []

    assert page.model is uncategorized
    assert page.db["model"] == uncategorized.key
    assert "categories" not in page.db
    assert page.properties.categories.value == [uncategorized]


# @matrix page : categories default-category model-removal users-model
@pytest.mark.unit
def test_page_categories_preserve_users_model_and_default_after_removing_only_model(
    monkeypatch,
):
    page = TestEntities.get("PAGE", {"name": "Model transitions", "hash": "pagecat2"})
    users_model = TestEntities.get(
        "USERS", {"name": "Users", "hash": "userscat2", "type": "users"}
    )
    category = TestEntities.get(
        "CATEGORY", {"name": "Only model", "hash": "onlymodelcat2"}
    )
    uncategorized = TestEntities.get(
        "CATEGORY",
        {"name": "Uncategorized Pages", "hash": "uncategorizedcat2"},
    )
    monkeypatch.setattr(
        page_related.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: uncategorized,
    )

    page.model = users_model
    page.categories = []

    assert page.model is users_model
    assert page.categories == []

    page.model = category
    page.properties.categories.remove(category)

    assert page.model is uncategorized
    assert page.categories == [uncategorized]


# @matrix category filters page : form-registration related-forms
@pytest.mark.unit
def test_page_update_registers_form_with_model_category_for_filters():
    """A page-specific form is registered on its parent category for filters."""
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Filterable Category", "hash": "cat008filters"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Page Specific Form", "hash": "form008filters"},
    )
    page = TestEntities.get(
        "PAGE",
        {"name": "Form Page", "hash": "page008filters"},
    )

    page.update({"name": "Form Page", "model": category, "form": form})

    assert category.db["forms"] == [form.key]
    assert category.properties.forms.value == [form]
    assert form.hash in category.filters.entity_fields
    assert any(c["label"] == form.name for c in category.filters.conditions)


# @pair page:default-category
@pytest.mark.unit
def test_page_update_defaults_empty_category_state_to_uncategorized(monkeypatch):
    uncategorized = TestEntities.get(
        "CATEGORY",
        {"name": "Uncategorized Pages", "hash": "uncategorized-update"},
    )
    monkeypatch.setattr(
        page_related.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: uncategorized,
    )
    page = TestEntities.get(
        "PAGE",
        {"name": "Loose Page", "hash": "page008uncategorized"},
    )

    page.update({"name": "Loose Page"})

    assert page.model is uncategorized
    assert page.db["model"] == uncategorized.key
    assert page.categories == [uncategorized]


# @matrix category filters page : form-registration save-relations
@pytest.mark.unit
def test_page_update_tracks_old_and_current_category_owners_for_save():
    old_model = TestEntities.get(
        "CATEGORY",
        {"name": "Old Model", "hash": "oldmodel008"},
    )
    old_extra = TestEntities.get(
        "CATEGORY",
        {"name": "Old Extra", "hash": "oldextra008"},
    )
    new_model = TestEntities.get(
        "CATEGORY",
        {"name": "New Model", "hash": "newmodel008"},
    )
    new_extra = TestEntities.get(
        "CATEGORY",
        {"name": "New Extra", "hash": "newextra008"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "New Page Form", "hash": "form008saverelations"},
    )
    page = TestEntities.get(
        "PAGE",
        {"name": "Tracked Page", "hash": "page008saverelations"},
    )
    page.model = old_model
    page.categories = [old_model, old_extra]

    page.update(
        {
            "name": "Tracked Page",
            "model": new_model,
            "categories": [new_extra],
            "form": form,
        }
    )

    assert page.page_list_owners == [new_model, new_extra]
    assert {intent.entity.key for intent in page.mutation_intents} == {
        old_model.key,
        old_extra.key,
        new_model.key,
        new_extra.key,
        form.key,
    }
    assert new_model.db["forms"] == [form.key]
    assert new_extra.db["forms"] == [form.key]

    plan = plan_mutation(MutationOperation.SAVE, page, registry=Entities)
    writes = {
        effect.entity.key: effect
        for effect in plan.effects
        if effect.effect is MutationEffectType.UPSERT
    }
    assert writes[page.key].property_mask is None
    assert set(writes) == {
        page.key,
        old_model.key,
        old_extra.key,
        new_model.key,
        new_extra.key,
        form.key,
    }
    assert writes[new_model.key].property_mask == ("forms", "modified")
    assert writes[new_extra.key].property_mask == ("forms", "modified")
    assert writes[old_model.key].property_mask == ("modified",)
    assert writes[old_extra.key].property_mask == ("modified",)


# @pair page:save-relations
@pytest.mark.unit
def test_page_update_keeps_current_user_before_page_without_dependency_cycle():
    user = TestEntities.get(
        "USER",
        {
            "name": "Current Page User",
            "hash": "currentpageuser008",
            "email": "current-page-user@example.test",
        },
    )
    model = TestEntities.get(
        "CATEGORY",
        {"name": "Current Model", "hash": "currentmodel008"},
    )
    page = TestEntities.get(
        "PAGE",
        {"name": "Current User Page", "hash": "currentuserpage008"},
    )
    page.user = user
    page.model = model
    page.categories = [model]
    user.properties.page._value = page
    user.db["page"] = page.key

    page.update(
        {
            "name": "Updated Current User Page",
            "model": model,
            "categories": [model],
        }
    )
    page.add_mutation_intents(
        MutationIntent.standard(user, reason="page-user-update")
    )

    assert all(
        intent.reason != "page-previous-list-owner"
        for intent in page.mutation_intents
    )
    registry = SimpleNamespace(fetch=lambda *_args, **_kwargs: [user])
    plan = plan_mutation(MutationOperation.SAVE, page, registry=registry)
    writes = [
        effect
        for effect in plan.effects
        if effect.effect is MutationEffectType.UPSERT
    ]
    by_key = {effect.entity.key: effect for effect in writes}

    assert writes.index(by_key[user.key]) < writes.index(by_key[page.key])
    assert by_key[user.key].depends_on == ()
    assert by_key[page.key].depends_on == (user,)


# @matrix page : categories validation
@pytest.mark.unit
def test_page_categories_reject_invalid_related_values():
    page = TestEntities.get("PAGE", {"name": "Invalid Categories", "hash": "pgbadcat"})

    with pytest.raises(TypeError, match="Value must be a list"):
        page.properties.categories.value = {}

    with pytest.raises(ValueError, match="Value must have a key"):
        page.properties.categories.value = [SimpleNamespace()]

    with pytest.raises(ValueError, match="Value must have a key"):
        page.properties.categories.add(SimpleNamespace())

    with pytest.raises(ValueError, match="Value must have a key"):
        page.properties.categories.remove(SimpleNamespace())


# @matrix page : db-load files
@pytest.mark.unit
def test_page_files_loads_database_files():
    page = TestEntities.get("PAGE", {"name": "Files Page", "hash": "filespage"})
    raw_file = datastore.Entity(
        key=datastore.Key("models", "file-model", project="test")
    )
    raw_file.update(
        {
            "type": "file",
            "name": "Loaded File",
            "hash": "filehash",
            "pages": [page.key],
        }
    )
    file_entity = page_related.Entities.FILE(raw_file)
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Not A File", "hash": "notfile"},
    )

    with (
        patch.object(page_related.database_get, "page_files", return_value=[raw_file])
        as page_files,
        patch.object(
            page_related.Entities,
            "fetch",
            return_value=[file_entity, category, page],
        ) as load,
    ):
        files = page.properties.files.value
        again = page.properties.files.value

    page_files.assert_called_once_with(page.key)
    load.assert_called_once_with(raw_file.key, page, request=Fetch.direct())
    assert files == [file_entity]
    assert again is files
    assert page.properties.files.sort_value == 1


# @matrix page : db-load files stale-query
@pytest.mark.unit
def test_page_files_reloads_query_results_and_skips_unlinked_files():
    page = TestEntities.get("PAGE", {"name": "Fresh Files Page", "hash": "freshpage"})
    linked_file = TestEntities.get(
        "FILE",
        {"filename": "linked.pdf", "hash": "freshlinked"},
    )
    linked_file.db["pages"] = [page.key]
    unlinked_file = TestEntities.get(
        "FILE",
        {"filename": "unlinked.pdf", "hash": "freshunlinked"},
    )
    stale_query_result = SimpleNamespace(key=unlinked_file.key)
    linked_query_result = SimpleNamespace(key=linked_file.key)

    with (
        patch.object(
            page_related.database_get,
            "page_files",
            return_value=[stale_query_result, linked_query_result],
        ),
        patch.object(
            page_related.Entities,
            "fetch",
            return_value=[unlinked_file, linked_file, page],
        ) as load,
    ):
        files = page.properties.files.value

    load.assert_called_once_with(
        unlinked_file.key, linked_file.key, page, request=Fetch.direct()
    )
    assert files == [linked_file]


# @matrix page : attach cache-parent details fallback-parent user-key
@pytest.mark.unit
def test_page_user_and_model_category_parent_keys():
    page = TestEntities.get("PAGE", {"name": "Parent Keys", "hash": "parentkeys"})
    user_key = object()
    page.db["user"] = user_key

    with patch.object(
        page_related.database_get,
        "urlsafe_key",
        return_value="safe-user",
    ) as urlsafe_key:
        assert page.properties.user.urlsafe_key == "safe-user"

    urlsafe_key.assert_called_once_with(user_key)

    model = TestEntities.get("CATEGORY", {"name": "Model", "hash": "modeldetails"})
    page.db["model"] = model.key
    page.properties.model.attach({model.key: model})

    assert page.properties.model.value is model
    assert page.properties.model.details_key == "parent"
    assert page.properties.model.details_value == model.reference_details

    reserved = TestEntities.get(
        "CATEGORY",
        {"name": "Reserved", "hash": "reservedmodel", "reserved": True},
    )
    page.properties.model.value = reserved

    assert page.properties.model.details_value is None

    fallback = TestEntities.get(
        "CATEGORY",
        {"name": "Fallback Parent", "hash": "fallbackparent"},
    )
    page.model = None
    page.categories = [fallback]

    assert page.model is None
    assert page.properties.model.details_value == fallback.reference_details
    assert page.details["parent"] == fallback.reference_details
    assert page.to_cache["parent_key"] == fallback.hash


# @matrix page : asset-lifecycle column filter-value image
@pytest.mark.unit
def test_page_image_asset_lifecycle_and_projections():
    class FakePage:
        def __init__(self):
            self.assets = {}
            self.saved = []
            self.deleted = []

        def get_asset(self, name):
            return self.assets.get(name)

        def save_asset(self, content, name, asset_type):
            self.saved.append((content, name, asset_type))
            asset = SimpleNamespace(url=f"/assets/{name}.jpg")
            self.assets[name] = asset
            return asset

        def delete_asset(self, name):
            self.deleted.append(name)
            self.assets.pop(name, None)

    page = FakePage()
    image = Image(entity=page, user=object())

    assert image.value is None
    assert image.column_value is None
    assert image.filter_value is False
    assert image.sort_value is False

    upload = object()
    image.value = upload

    assert page.saved == [(upload, "image", "image")]
    assert image.value is page.assets["image"]
    assert image.column_value == "/assets/image.jpg"
    assert image.filter_value is True
    assert image.sort_value is True

    image.delete()

    assert page.deleted == ["image"]
    assert image.value is None
    assert image.column_value is None
    assert image.filter_value is False
    assert image.sort_value is False
