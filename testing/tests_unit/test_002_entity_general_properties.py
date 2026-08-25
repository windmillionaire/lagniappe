"""Unit tests for base Entity properties shared across all entity types."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key

from lagniappe.core.definitions import MutationIntent, Ordering
from lagniappe.core.entities import Entities
from lagniappe.core.entities import site as site_module
from lagniappe.core.entities.entity import Entity
from lagniappe.core.entities.site import Site
from lagniappe.core.exceptions import PropertyError
from lagniappe.core.mutations import executor as mutation_executor
from lagniappe.core.mixins import ColumnMixin, FilterMixin
from lagniappe.core.properties import common_entity
from lagniappe.core.properties.base_columns import Columns
from lagniappe.core.properties.base_db import DBProperty
from lagniappe.core.properties.base_property import Property
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


class _FakeEntity:
    def __init__(self, key):
        self.key = key

    def __repr__(self):
        return f"{type(self).__name__}({self.key})"

    def __eq__(self, other):
        return type(self) is type(other) and self.key == other.key

    def __hash__(self):
        return hash((type(self), self.key))


class _SiteLazyProperty(Property):
    _id = "lazy"


class _DBBlankProperty(DBProperty):
    _id = "blank"


class _DBKeepListProperty(DBProperty):
    _id = "keep"
    _blank_values = (None,)


class _MissingIdProperty(Property):
    pass


class _ColumnProperty(ColumnMixin, Property):
    _id = "column"


class _MissingFieldType(FilterMixin):
    pass


class _BadColumns(Columns):
    column_fields = (_SiteLazyProperty,)


class _SiteBrokenProperty(Property):
    _id = "broken"

    def __init__(self, *args, **kwargs):
        raise RuntimeError("construction failed")


class _TestSite(Site):
    _kind = "test-site"

    def _get_properties(self):
        return {
            "lazy": _SiteLazyProperty,
            "broken": _SiteBrokenProperty,
        }


class _KeylessEntity(Entity):
    entity_kind = "keyless"


class _MissingKindEntity(Entity):
    pass


class _FakeEntityDB(dict):
    pass


class _SaveOrderProperty:
    def __init__(self, entity, calls, name):
        self.entity = entity
        self.calls = calls
        self.name = name

    def update(self):
        self.calls.append(self.name)
        if self.name == "hash":
            self.entity.db["hash"] = "persisted_hash"
        elif self.name == "requires":
            self.entity.db["requires"] = [self.entity.db.get("hash"), "models"]


class _SaveOrderEntity:
    entity_kind = "category"
    key = "save-order-entity"
    exclude_from_index = frozenset()
    processes = {}

    def __init__(self):
        self.db = _FakeEntityDB()
        self.calls = []
        self.properties = {
            name: _SaveOrderProperty(self, self.calls, name)
            for name in ("hash", "requires")
        }


def _cache_payload(entity):
    cache = entity.to_cache
    if not cache:
        assert cache == {}
    return cache


def _expected_cache_requires(entity):
    if entity.entity_kind == "page" and entity.user:
        return entity.user.required
    return entity.required


# @matrix active : property public-user
def test_entity_active(get_test_entities):
    """Test that Active property returns correct boolean value.

    Public-user pages always read as inactive even when db active is True.
    """
    for entity in get_test_entities():
        spec_user = entity.test_spec.get("user")
        if spec_user and spec_user.get("public"):
            entity.active = True
            assert entity.active is False
            assert entity.properties.active.value is False
            continue

        test_value = entity.test_spec.get("active", True)
        entity.active = test_value

        # property value
        assert entity.active == test_value == entity.properties.active.value


# @pair active:validation
def test_entity_active_rejects_non_bool():
    entity = TestEntities.get("PROJECT", {"name": "Active Validation", "hash": "actv"})

    with pytest.raises(TypeError, match="active must be a boolean"):
        entity.active = "yes"


# @matrix permissions : authenticated-user filter-index-neutral
def test_context_exports_authentication_and_filter_index_neutrality():
    entity = TestEntities.get("PROJECT", {"name": "Auth Export", "hash": "authx"})
    anonymous = SimpleNamespace(is_authenticated=False)

    with pytest.raises(PermissionError, match="user must be authenticated"):
        entity.to_ai(user=anonymous)

    assert entity.to_filter_index(user=anonymous)["name"] == "Auth Export"


# @matrix ai entity submission : single-merge submission-fields
def test_entity_to_ai_merges_submission_fields_without_nested_duplicate():
    form = TestEntities.get("FORM", {"name": "Contact Form", "hash": "aiform"})
    form.schema = [
        {
            "id": "input-addressab12",
            "type": "input",
            "input": "text",
            "title": "Address",
        },
        {
            "id": "input-notescd34",
            "type": "textarea",
            "title": "Notes",
        },
    ]
    page = TestEntities.get("PAGE", {"name": "Contractor", "hash": "aipage"})
    page.form = form
    page.submission = {
        "input-addressab12": "123 Main St",
        "input-notescd34": "Use side entrance.",
    }

    ai_values = page.to_ai()

    assert ai_values["Address"] == "123 Main St"
    assert ai_values["Notes"] == "Use side entrance."
    assert "input-addressab12" not in ai_values
    assert "input-notescd34" not in ai_values
    assert "submission" not in ai_values


# @pair entity:key-validation
def test_entity_key_access_without_key_raises_runtime_error():
    entity = _KeylessEntity(testing=True)
    entity._testing = False
    entity._temporary = False
    entity._key = None
    entity._db = {}

    with pytest.raises(RuntimeError, match="no key assigned"):
        _ = entity.urlsafe_key

    with pytest.raises(RuntimeError, match="no key assigned"):
        _ = entity.db


# @matrix entity : dedupe key-validation typed-intent validation
def test_entity_add_mutation_intents_requires_typed_intents_and_dedupes():
    entity = _KeylessEntity(testing=True)
    relation = SimpleNamespace(key="relation-key")
    duplicate = SimpleNamespace(key="relation-key")
    first = MutationIntent.touch(relation, reason="dependent")
    repeated = MutationIntent.touch(duplicate, reason="dependent")

    entity.add_mutation_intents(first, repeated)

    assert entity.mutation_intents == [first]
    with pytest.raises(ValueError, match="must have a key"):
        entity.add_mutation_intents(
            MutationIntent.touch(SimpleNamespace(), reason="missing-key")
        )
    with pytest.raises(TypeError, match="must be MutationIntent"):
        entity.add_mutation_intents(relation)


# @pairs entities:save-order requires:hash-before-requires
def test_save_entities_updates_hash_before_requires():
    entity = _SaveOrderEntity()

    with (
        patch.object(mutation_executor.cache, "update") as cache_update,
        patch.object(
            mutation_executor.database, "save_mutations"
        ) as database_save,
    ):
        Entities.save(entity)

    assert entity.calls == ["hash", "requires"]
    assert entity.db["requires"] == ["persisted_hash", "models"]
    cache_update.assert_called_once_with(entity)
    assert list(database_save.call_args.args[0]) == [(entity, None)]


# @pairs requires:persisted-requires users:user-before-page
def test_save_entities_updates_and_persists_user_before_owned_page():
    class EntityDict(dict):
        pass

    page = TestEntities.get(
        "PAGE",
        {"name": "Owner Page", "hash": "owner-page"},
    )
    user = TestEntities.get(
        "USER",
        {"name": "Owner", "hash": "owner-user", "groups": []},
        page=page,
    )
    page.properties.user._value = user
    page._db = EntityDict(page.db)
    user._db = EntityDict(user.db)

    assert user.db["requires"] == ["users"]
    user.test_spec["groups"] = [
        {"name": "Editors", "hash": "editors"},
    ]

    with (
        patch.object(Entities, "fetch", return_value=[user]),
        patch.object(mutation_executor.cache, "update"),
        patch.object(
            mutation_executor.database, "save_mutations"
        ) as database_save,
    ):
        Entities.save(page, user)

    assert user.db["requires"] == ["users", "editors"]
    assert "editors" in page.db["requires"]
    assert list(database_save.call_args.args[0]) == [(user, None), (page, None)]


# @matrix entity : initialization validation
def test_entity_requires_subclass_entity_kind():
    with pytest.raises(NotImplementedError, match="requires entity_kind"):
        _MissingKindEntity(testing=True)


# @matrix entity : empty-datastore-entity initialization key-preservation
def test_entity_preserves_key_from_empty_datastore_entity():
    raw = DatastoreEntity(
        key=Key(
            "instances",
            "empty-record",
            project="entity-constructor-test",
        )
    )

    entity = _KeylessEntity(raw, testing=True)

    assert entity.db is raw
    assert entity.key == raw.key


# @matrix property : initialization validation
def test_property_contract_errors_are_explicit():
    entity = SimpleNamespace(entity_kind="fake")

    with pytest.raises(NotImplementedError, match="requires _id"):
        _MissingIdProperty(entity=entity)

    with pytest.raises(ValueError, match="requires entity"):
        _SiteLazyProperty()

    missing_kind = _SiteLazyProperty(entity=SimpleNamespace(entity_kind=None))
    with pytest.raises(NotImplementedError, match="requires kind"):
        _ = missing_kind.kind

    with pytest.raises(NotImplementedError, match="requires icon"):
        _ = _SiteLazyProperty(entity=entity).icon


# @matrix property : explicit-false explicit-none unset
def test_property_unset_state_is_distinct_from_explicit_values():
    entity = SimpleNamespace(entity_kind="fake")
    prop = _SiteLazyProperty(entity=entity)

    assert prop.is_set is False
    assert prop.value is None
    assert prop.db_value is None

    prop.value = False
    assert prop.is_set is True
    assert prop.value is False
    assert prop.db_value is False

    prop.value = None
    assert prop.is_set is True
    assert prop.value is None
    assert prop.db_value is None

    prop.unset()
    assert prop.is_set is False
    assert prop.value is None


# @matrix db-property : blank-values explicit-false missing-key
def test_db_property_blanks_pop_but_explicit_false_persists():
    entity = SimpleNamespace(entity_kind="fake", db={})
    prop = _DBBlankProperty(entity=entity)

    assert prop.value is None
    assert prop.is_set is False

    prop.value = False
    assert prop.is_set is True
    assert prop.value is False
    assert entity.db["blank"] is False

    prop.value = []
    assert prop.is_set is False
    assert "blank" not in entity.db

    prop.value = {"nested": "value"}
    assert prop.value == {"nested": "value"}
    assert entity.db["blank"] == {"nested": "value"}

    prop.value = {}
    assert prop.is_set is False
    assert "blank" not in entity.db


# @pair db-property:custom-blank-values
def test_db_property_custom_blank_values_can_keep_empty_lists():
    entity = SimpleNamespace(entity_kind="fake", db={})
    prop = _DBKeepListProperty(entity=entity)

    prop.value = []
    assert prop.is_set is True
    assert prop.value == []
    assert entity.db["keep"] == []

    prop.value = None
    assert prop.is_set is False
    assert "keep" not in entity.db


# @matrix forms : access-restrictions inheritance side-effect-free stable-order stored-projection
@pytest.mark.parametrize("parent_name", ["page", "form"])
def test_restricted_to_effective_projection_does_not_alias_sources(parent_name):
    stored = ["stored-group", "stored-group"]
    direct = common_entity.RestrictedTo(
        entity=SimpleNamespace(entity_kind="form", db={"restricted_to": stored})
    )

    assert direct.stored == stored
    assert direct.stored is not stored
    assert direct.value == ["stored-group", "owner"]
    assert direct.value is not stored
    assert stored == ["stored-group", "stored-group"]

    inherited = ["inherited-group", "inherited-group"]
    parent = SimpleNamespace(restricted_to=inherited)
    entity = SimpleNamespace(
        entity_kind="task",
        db={},
        page=None,
        form=None,
        groups=[],
    )
    setattr(entity, parent_name, parent)
    from_parent = common_entity.RestrictedTo(entity=entity)

    assert from_parent.value == ["inherited-group", "owner"]
    assert from_parent.value is not inherited
    assert inherited == ["inherited-group", "inherited-group"]

    groups = [
        SimpleNamespace(hash="group-one"),
        SimpleNamespace(hash="group-two"),
        SimpleNamespace(hash="group-one"),
    ]
    from_groups = common_entity.RestrictedTo(
        entity=SimpleNamespace(
            entity_kind="user",
            db={},
            page=None,
            form=None,
            groups=groups,
        )
    )

    assert from_groups.value == ["group-one", "group-two", "owner"]
    assert [group.hash for group in groups] == [
        "group-one",
        "group-two",
        "group-one",
    ]


# @matrix forms : access-restrictions owner-restricted side-effect-free stable-order
def test_restricted_to_add_preserves_first_seen_order():
    stored = ["group-two", "group-one", "group-two"]
    entity = SimpleNamespace(
        entity_kind="form",
        db={"restricted_to": stored},
    )
    restricted_to = common_entity.RestrictedTo(entity=entity)

    restricted_to.add("group-three")

    assert entity.db["restricted_to"] == [
        "group-two",
        "group-one",
        "group-three",
    ]
    assert stored == ["group-two", "group-one", "group-two"]
    assert restricted_to.value == [
        "group-two",
        "group-one",
        "group-three",
        "owner",
    ]


# @matrix property : column filter validation
def test_column_and_filter_contract_errors_are_explicit():
    entity = SimpleNamespace(entity_kind="fake")
    column = _ColumnProperty(entity=entity)

    column._ordering = "bad"
    with pytest.raises(TypeError, match="Ordering"):
        _ = column.ordering

    with pytest.raises(TypeError, match="Ordering"):
        column.ordering = "bad"

    column.ordering = Ordering.LEXICAL
    assert column.ordering == Ordering.LEXICAL

    with pytest.raises(NotImplementedError, match="requires _field_type"):
        _ = _MissingFieldType().field_type

    with pytest.raises(TypeError, match="ColumnMixin"):
        _ = _BadColumns(entity=entity).fields


# @matrix site : db-key validation
def test_site_missing_key_raises_runtime_error():
    site = _TestSite("missing-site")

    with patch.object(site_module.site_database, "key", return_value=None):
        with pytest.raises(RuntimeError, match="no key assigned"):
            _ = site.urlsafe_key

        with pytest.raises(RuntimeError, match="no key assigned"):
            _ = site.db


# @matrix requires : cache details property
def test_entity_requires(get_test_entities):
    """Test Requires property returns list and cache_value is comma-separated.

    Each entity type builds its required list differently:
    - Project/Category: [hash, "models"]
    - Page: [hash, "users", *group_hashes, "models", *category_hashes]
      for user pages with categories, [hash, "models", *category_hashes]
      for categorized pages, or [hash] for standalone pages.
    - Task: delegates to page.required
    - User: ["users", *group_hashes]
    - ModelTask: [project.hash, "models"]
    - Form: ["forms"]
    - File: [hash, "models", *pages_requires...]
    - Filter: [hash, entity.hash, creator.hash]
    - UserGroup: [hash, "users"]
    - PublicGroup/Ingress: [hash, "site"]
    """
    for entity in get_test_entities():
        # The expected value comes from should_match in test_spec
        # Compare as sets since some entities use set() which has unpredictable order
        assert set(entity.test_spec.get("should_match", [])) == set(entity.required)

        # property value
        assert entity.properties.requires.value == entity.required

        # CacheMixin - cache_value is comma-separated string
        if cache := _cache_payload(entity):
            assert cache["requires"] == ",".join(_expected_cache_requires(entity))

        # DetailsMixin - details_value is the list
        assert entity.details["requires"] == entity.required


# @matrix hash : cache details filter property
def test_entity_hash(get_test_entities):
    """Test that Hash property returns correct value."""
    for entity in get_test_entities():
        test_value = entity.test_spec.get("hash")

        # property value
        assert entity.properties.hash.value == entity.hash == test_value

        # DetailsMixin - details_value
        assert entity.details["hash"] == test_value

        # FilterMixin - filter_key is "cache_key"
        assert entity.to_filter_index()["cache_key"] == test_value

        # AIMixin - AI gets an explicit hash token instead of a long entity id.
        assert entity.to_ai()["hash"] == f"hash:{test_value}"
        assert "id" not in entity.to_ai()

        # CacheMixin - cache output uses the hash value
        if cache := _cache_payload(entity):
            assert cache["hash"] == test_value


# @matrix name : ai cache column details filter property sort
def test_entity_name(get_test_entities):
    """Test Name property with all mixins: Cache, Column, Details, AI, Filter.

    Name has special behavior:
    - sort_value/filter_value strip leading "The " and lowercase
    - column_value returns entity.details (not just the name)
    - cache_value returns the name for search indexing
    - ai_key is usually {entity_kind}_name; File uses display_name
    """
    for entity in get_test_entities():
        test_value = entity.test_spec.get("name")
        # entity.db["name"] = test_value  # Set via db since name property is overridden

        # property value
        assert entity.properties.name.value == test_value == entity.name

        # sort_value - strips "The " prefix and lowercases
        expected_sort = test_value.replace("The ", "").lower() if test_value else None
        assert entity.properties.name.sort_value == expected_sort

        # DetailsMixin - details_value is the name, appears in entity.details
        assert entity.details["name"] == test_value

        # FilterMixin - should NOT strip "The " or lowercase
        assert entity.to_filter_index()["name"] == test_value

        # CacheMixin - cache_value returns the name.
        if cache := _cache_payload(entity):
            assert cache.get("name") == test_value

        # AIMixin - the property owns its AI key.
        ai_value = entity.to_ai().get(entity.properties.name.ai_key)
        assert ai_value == test_value

        # ColumnMixin - column_value returns entity.details dict
        assert entity.column("name").column_value == entity.details


# @matrix name : import list-normalization
def test_entity_name_list_values_normalized_on_write_and_import():
    entity = TestEntities.get("PAGE", {"name": "Original", "hash": "name_list"})

    entity.name = ["Ada", "", None, "Lovelace"]

    assert entity.name == "Ada Lovelace"
    assert entity.db["name"] == "Ada Lovelace"

    entity.properties.name.validate_import(["Grace", None, "", "Hopper"])

    assert entity.name == "Grace Hopper"
    assert entity.db["name"] == "Grace Hopper"


# @pair db-property:cache-invalidation
def test_db_property_write_refreshes_entity_details_and_cache():
    entity = TestEntities.get(
        "PROJECT",
        {"name": "Original Cache Name", "hash": "db_property_cache_refresh"},
    )

    assert entity.details["name"] == "Original Cache Name"
    assert entity.to_cache["details_key"] == entity.hash
    assert entity.to_cache["name"] == "Original Cache Name"
    assert "details" not in entity.to_cache

    entity.name = "Updated Cache Name"

    assert entity.details["name"] == "Updated Cache Name"
    assert entity.to_cache["name"] == "Updated Cache Name"


# @matrix cache related-properties : cache-invalidation column-value details parent-pointer
def test_related_property_writes_refresh_entity_and_column_projections():
    page = TestEntities.get(
        "PAGE",
        {"name": "Related Cache Page", "hash": "related_cache_page"},
    )
    first_model = TestEntities.get(
        "CATEGORY",
        {"name": "First Model", "hash": "related_cache_model_first"},
    )
    second_model = TestEntities.get(
        "CATEGORY",
        {"name": "Second Model", "hash": "related_cache_model_second"},
    )
    first_form = TestEntities.get(
        "FORM",
        {"name": "First Form", "hash": "related_cache_form_first"},
    )
    second_form = TestEntities.get(
        "FORM",
        {"name": "Second Form", "hash": "related_cache_form_second"},
    )
    first_category = TestEntities.get(
        "CATEGORY",
        {"name": "First Category", "hash": "related_cache_category_first"},
    )
    second_category = TestEntities.get(
        "CATEGORY",
        {"name": "Second Category", "hash": "related_cache_category_second"},
    )

    page.model = first_model
    page.form = first_form
    page.categories = [first_model, first_category]

    assert page.details["parent"]["hash"] == first_model.hash
    assert page.to_cache["parent_key"] == first_model.hash
    assert page.properties.form.column_value["hash"] == first_form.hash
    assert {value["hash"] for value in page.properties.categories.column_value} == {
        first_model.hash,
        first_category.hash,
    }

    page.model = second_model
    page.form = second_form
    page.categories = [second_model, second_category]

    assert page.details["parent"]["hash"] == second_model.hash
    assert page.to_cache["parent_key"] == second_model.hash
    assert page.properties.form.column_value["hash"] == second_form.hash
    assert {value["hash"] for value in page.properties.categories.column_value} == {
        second_model.hash,
        second_category.hash,
    }

    page.db["categories"] = [first_category.key]
    page.properties.categories.attach({first_category.key: first_category})

    assert {value["hash"] for value in page.properties.categories.column_value} == {
        second_model.hash,
        first_category.hash,
    }


# @matrix cache : details-key parent-key
def test_entity_to_cache_stores_detail_parent_pointers():
    page = TestEntities.get(
        "PAGE",
        {
            "name": "Pointer Page",
            "hash": "cache_pointer_page",
            "model": {"name": "Pointer Category", "hash": "cache_pointer_category"},
        },
    )

    cache = page.to_cache

    assert cache["details_key"] == page.hash
    assert cache["parent_key"] == page.model.hash
    assert "details" not in cache


# @matrix modified : column date filter property
def test_entity_modified(get_test_entities):
    """Test Modified property with DateMixin, ColumnMixin, FilterMixin.

    Modified stores datetime in UTC but displays in user timezone.
    We mock user_timezone() to test timezone conversion.
    """
    for entity in get_test_entities():
        # Get timezone from test_spec (reusable for other date properties)
        tz_name = entity.test_spec.get("timezone", "America/Chicago")
        test_tz = ZoneInfo(tz_name)

        with patch("lagniappe.core.tools.dates.user_timezone", return_value=test_tz):
            # Get the UTC datetime that was set by the fixture
            assert entity.modified.tzinfo == timezone.utc

            # property value - stored in UTC
            assert entity.properties.modified.value == entity.modified

            # ColumnMixin - column_value converts to user timezone
            column_val = entity.column("modified").column_value
            assert column_val == entity.modified.astimezone(test_tz)

            # FilterMixin - filter_value is Unix timestamp
            filter_value = entity.to_filter_index().get("modified")
            assert filter_value == entity.modified.timestamp()

            # Test setting a datetime in user timezone - should convert to UTC
            user_dt = datetime(2024, 6, 15, 14, 30, 0, tzinfo=test_tz)
            entity.modified = user_dt

            # Value should be stored in UTC
            assert entity.modified == user_dt.astimezone(timezone.utc)

            # column_value should convert back to user timezone
            assert entity.column("modified").column_value == user_dt


# @matrix created : initialized-once update
def test_entity_created_update_initializes_once():
    entity = TestEntities.get(
        "PROJECT",
        {"name": "Created Project", "hash": "created_project"},
    )
    entity.db.pop("created", None)
    first_created = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    later_created = datetime(2024, 6, 7, 8, 9, 10, tzinfo=timezone.utc)

    with patch("lagniappe.core.properties.common_entity.datetime") as mock_datetime:
        mock_datetime.now.return_value = first_created
        entity.properties.created.update()

    assert entity.created == first_created
    assert entity.db["created"] == first_created

    with patch("lagniappe.core.properties.common_entity.datetime") as mock_datetime:
        mock_datetime.now.return_value = later_created
        entity.properties.created.update()

    assert entity.created == first_created
    assert entity.db["created"] == first_created


# @matrix public-id : generation persistence uniqueness
def test_public_id_generation_is_unique_and_persisted():
    entity = TestEntities.get(
        "PROJECT",
        {"name": "Public Project", "hash": "public_project"},
    )

    with (
        patch.object(
            common_entity,
            "short_uuid",
            side_effect=["duplicate-id", "unique-id"],
        ) as short_uuid,
        patch.object(
            common_entity.database.get,
            "public_pages",
            side_effect=[object(), None],
        ) as public_pages,
    ):
        assert entity.properties.public_id.value == "unique-id"
        assert entity.properties.public_id.value == "unique-id"

    assert entity.db["public_id"] == "unique-id"
    assert short_uuid.call_count == 2
    assert [call.args[0] for call in public_pages.call_args_list] == [
        "duplicate-id",
        "unique-id",
    ]

    existing = TestEntities.get(
        "PROJECT",
        {"name": "Existing Public Project", "hash": "existing_public_project"},
    )
    existing.db["public_id"] = "existing-id"

    with patch.object(common_entity, "short_uuid") as short_uuid:
        assert existing.properties.public_id.value == "existing-id"

    short_uuid.assert_not_called()


# @matrix property : descriptor error-wrapping
def test_property_getattribute_wraps_descriptor_attribute_error():
    class BrokenProperty(Property):
        _id = "broken"

        @property
        def fragile(self):
            raise AttributeError("missing nested value")

    entity = _FakeEntity("owner")
    prop = BrokenProperty(entity=entity, user=object())

    with pytest.raises(PropertyError) as error:
        prop.fragile

    assert error.value.entity is entity
    assert isinstance(error.value.__cause__, AttributeError)
    assert "fragile" in str(error.value)
    assert "broken" in str(error.value)
    assert getattr(prop, "missing", "fallback") == "fallback"


# @matrix site : db-key error-wrapping lazy-properties
def test_site_lazy_properties_database_key_and_error_context():
    site_key = object()
    site_db = {"name": "Site DB"}

    with (
        patch.object(site_module.site_database, "key", return_value=site_key),
        patch.object(site_module.database.get, "urlsafe_key", return_value="safe-site"),
        patch.object(site_module.site_database, "get_or_create", return_value=site_db),
    ):
        site = _TestSite("main")

        lazy_property = site.lazy
        assert lazy_property is site.lazy
        assert isinstance(lazy_property, _SiteLazyProperty)
        assert lazy_property.entity is site

        assert site.key is site_key
        assert site.urlsafe_key == "safe-site"
        assert site.db == site_db

        with pytest.raises(PropertyError) as error:
            site.broken

    assert error.value.entity is site
    assert isinstance(error.value.__cause__, RuntimeError)
    assert "broken" in str(error.value)
    assert "_TestSite" in str(error.value)


# @matrix kind : cache db-key details property
def test_entity_kind(get_test_entities):
    """Test Kind property with DetailsMixin, CacheMixin.

    Kind has special behavior:
    - db_key is "type" not "kind" (reads from entity.db["type"])
    - details_value returns "user" for PAGE entities with db["user"], else returns value
    - cache_value returns details_value
    """
    for entity in get_test_entities():
        # Kind reads from db["type"]
        assert entity.kind == entity.properties.kind.value == entity.db["type"]

        # PAGE with user is special - details_value returns "user" instead of "page"
        is_user_page = entity.entity_kind == "page" and entity.user
        expected_kind = "user" if is_user_page else entity.entity_kind

        # DetailsMixin - details_value
        assert entity.details["kind"] == expected_kind

        # CacheMixin - cache_value returns details_value
        if cache := _cache_payload(entity):
            assert cache["kind"] == expected_kind
