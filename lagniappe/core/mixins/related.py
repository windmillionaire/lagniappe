from ..definitions import Action, FieldType, FilterOptions, MutationIntent, Ordering
from ..properties.base_db import DBProperty
from ..properties.base_property import UNSET
from ..exceptions import capture_unloaded_relation


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_related.py::Categories
# @covered-by lagniappe/core/properties/common_related.py::Projects
# @covered-by lagniappe/core/properties/page_related.py::PageCategories
# @covered-by lagniappe/core/properties/user_related.py::Groups
class RelatedEntityListMixin:
    _touch_members = True
    """Adds storage for a list of related entities.

    Stores entity keys in entity.db and expects loaded values to be attached
    by Entity.attach(key_map). All derived values
    (column and AI) are permission-checked and exclude reserved entities;
    filter values and ``value`` itself are returned unfiltered so filter-index
    materialization is permission-neutral.

    Provides:
        value (list): Entity list (unfiltered). Setter persists keys.
        column_value (list[dict]): Permission-checked entity details.
        sort_value (dict): {hash: name} for categorical ordering.
        ai_value (list[str]): Permission-checked entity names.
        filter_value (list[str]): Related entity hashes, excluding reserved entities.
        add(entity): Prepend an entity to the list.
        remove(entity): Remove an entity from the list.
        attach(key_map): Populate from a pre-loaded key map.
    """

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_related_property_writes_refresh_entity_and_column_projections
    # @features related-properties cache
    # @dimensions cache-invalidation details column-value parent-pointer
    def _invalidate_projections(self):
        self._column_value = None
        if self.entity:
            self.entity._details = None
            self.entity._to_cache = None

    @property
    def sort_value(self):
        return {e["hash"]: e["name"] for e in self.column_value}

    @property
    def column_value(self):
        if getattr(self, "_column_value", None) is not None:
            return self._column_value
        elif not self.value:
            return []

        self._column_value = [
            e.reference_details
            for e in self.value
            if e.allowed(Action.VIEW, self.user) and not e.reserved
        ]

        return self._column_value

    # DB Attributes
    def attach(self, key_map):
        if not isinstance(self, DBProperty):
            return
        self._value = [
            key_map[k] for k in self.entity.db.get(self.id, []) if k in key_map
        ]
        self._cache_attached_entities()
        self._invalidate_projections()

    def _attached_entities_from_value(self):
        value = getattr(self, "_value", UNSET)
        if not isinstance(value, list):
            return {}

        return {item.key: item for item in value if getattr(item, "key", None)}

    def _cache_attached_entities(self):
        self._attached = self._attached_entities_from_value()
        return self._attached

    @property
    def attached_entities(self):
        if getattr(self, "_attached", None) is None:
            return self._cache_attached_entities()

        return self._attached

    # Property Attributes
    @property
    def value(self):
        if self.is_set:
            return self._value

        if isinstance(self, DBProperty) and self.entity:
            keys = self.entity.db.get(self.id, [])
            if keys:
                capture_unloaded_relation(self, relation_type="list", keys=keys)
            self._value = []
        else:
            self._value = []

        return self._value

    @value.setter
    def value(self, value):
        if value is not None and not isinstance(value, list):
            raise TypeError("Value must be a list")
        for item in value or []:
            if not getattr(item, "key", None):
                raise ValueError("Value must have a key")

        self._value = value or []
        self._cache_attached_entities()

        if isinstance(self, DBProperty) and self.entity:
            keys = [e.key for e in self._value]
            if keys in self._blank_values:
                self.entity.db.pop(self.id, None)
            else:
                self.entity.db[self.id] = keys
        self._invalidate_projections()

    # Entity Attributes
    def add(self, value):
        key = getattr(value, "key", None)
        if not key:
            raise ValueError("Value must have a key")

        if key not in [v.key for v in self.value]:
            self.value.insert(0, value)
            if isinstance(self, DBProperty) and self.entity:
                keys = [v.key for v in self.value]
                if keys in self._blank_values:
                    self.entity.db.pop(self.id, None)
                else:
                    self.entity.db[self.id] = keys
                if self._touch_members:
                    self.entity.add_mutation_intents(
                        MutationIntent.touch(
                            value,
                            reason=(
                                f"{self.entity.entity_kind}.{self.id}-list-member"
                            ),
                        )
                    )
            self._cache_attached_entities()
            self._invalidate_projections()
            return True
        return False

    def remove(self, value):
        key = getattr(value, "key", None)
        if not key:
            raise ValueError("Value must have a key")

        if key and key in [v.key for v in self.value]:
            self.value = [v for v in self.value if v.key != value.key]
            return True
        return False

    @property
    def keys(self):
        if not isinstance(self, DBProperty):
            return []
        return self.entity.db.get(self.id, [])

    # AI Attributes
    @property
    def ai_value(self):
        return [
            _ai_entity_reference(e)
            for e in self.value
            if e.allowed(Action.VIEW, self.user) and not e.reserved
        ]

    # Filter Attributes
    _field_type = FieldType.LIST
    _field_options = FilterOptions.LIST.value
    _is_entity_valued = True

    @property
    def filter_value(self):
        hashes = [e.hash for e in self.value if not e.reserved]
        return hashes if hashes else None

    def filter_details(self, condition):
        details = super().filter_details(condition)
        if len(condition.value_list) > 1:
            details["text"] = "is any of"
            details["or"] = [
                condition.entity_map[h].reference_details
                for h in condition.value_list
            ]
        elif len(condition.value_list) == 1:
            details["text"] = "is"
            details["entity"] = condition.entity_map[
                condition.value_list[0]
            ].reference_details
        return details


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_related.py::AttachedForm
# @covered-by lagniappe/core/properties/common_related.py::RelatedForm
# @covered-by lagniappe/core/properties/common_related.py::AttachedProject
# @covered-by lagniappe/core/properties/project.py::ModelTaskProject
# @covered-by lagniappe/core/properties/task_related.py::AssignedTo
class RelatedEntityMixin:
    """Adds storage for a single related entity.

    Stores the entity key in entity.db and expects loaded values to be attached
    by Entity.attach(key_map). All derived values
    (column and AI) are permission-checked and exclude reserved entities;
    filter values and ``value`` itself are returned unfiltered so filter-index
    materialization is permission-neutral.

    Provides:
        value (Entity | None): The related entity. Setter persists key.
        column_value (dict | None): Permission-checked entity details.
        sort_value (dict | None): {hash: name} for categorical ordering.
        ai_value (str | None): Permission-checked entity name.
        filter_value (str | None): Related entity hash, excluding reserved entities.
        details_value (dict | None): Entity details for the API.
        key: The stored entity key (without loading).
        exists (bool): Whether a key is stored.
        hash (str | None): The entity's hash (delegates to value).
        name (str | None): The entity's name (delegates to value).
        attach(key_map): Populate from a pre-loaded key map.
    """

    # Entity Attributes
    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_related_property_writes_refresh_entity_and_column_projections
    # @features related-properties cache
    # @dimensions cache-invalidation details column-value parent-pointer
    def _invalidate_projections(self):
        self._column_value = None
        if self.entity:
            self.entity._details = None
            self.entity._to_cache = None

    @property
    def keys(self):
        if not isinstance(self, DBProperty) or not self.entity:
            return []
        return [self.entity.db.get(self.id)]

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_related_attach_caches_attached_entity_map
    # @features relations
    # @dimensions attach-cache
    def attach(self, key_map):
        if not isinstance(self, DBProperty) or not self.entity:
            return
        self._value = key_map.get(self.entity.db.get(self.id))
        self._cache_attached_entities()
        self._invalidate_projections()

    def _attached_entities_from_value(self):
        value = getattr(self, "_value", UNSET)
        if not value or not getattr(value, "key", None):
            return {}

        return {value.key: value}

    def _cache_attached_entities(self):
        self._attached = self._attached_entities_from_value()
        return self._attached

    @property
    def attached_entities(self):
        if getattr(self, "_attached", None) is None:
            return self._cache_attached_entities()

        return self._attached

    @property
    def key(self):
        if self.is_set and self._value:
            return self._value.key
        elif isinstance(self, DBProperty) and self.entity:
            return self.entity.db.get(self.id)
        else:
            return None

    @property
    def exists(self):
        return self.entity.db.get(self.id) is not None

    @property
    def urlsafe_key(self):
        return self.value.urlsafe_key if self.value else None

    @property
    def hash(self):
        return self.value.hash if self.value else None

    @property
    def name(self):
        return self.value.name if self.value else None

    # Property Attributes
    @property
    def value(self):
        if self.is_set:
            return self._value

        if isinstance(self, DBProperty) and self.entity:
            key = self.entity.db.get(self.id)
            if key:
                capture_unloaded_relation(self, relation_type="single", keys=[key])
            self._value = None
        else:
            self._value = None

        return self._value

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_related_entity_setter_rejects_values_without_key
    # @features relations
    # @dimensions validation key-validation
    @value.setter
    def value(self, value):
        if value is not None and not getattr(value, "key", None):
            raise ValueError("Value must have a key")

        if value is None:
            self.unset()
        else:
            self._value = value
        self._cache_attached_entities()

        if isinstance(self, DBProperty) and self.entity:
            if value:
                self.entity.db[self.id] = value.key
            else:
                self.entity.db.pop(self.id, None)
        self._invalidate_projections()

    # Details Attributes
    @property
    def details_value(self):
        return self.value.reference_details if self.value else None

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    @property
    def sort_value(self):
        return {self.value.hash: self.value.name} if self.value else None

    @property
    def column_value(self):
        if getattr(self, "_column_value", None) is not None:
            return self._column_value
        elif not self.value:
            return None

        self._column_value = (
            self.value.reference_details
            if self.value.allowed(Action.VIEW, self.user) and not self.value.reserved
            else None
        )

        return self._column_value

    # AI Attributes
    @property
    def ai_value(self):
        if (
            not self.value
            or not self.value.allowed(Action.VIEW, self.user)
            or self.value.reserved
        ):
            return None

        return _ai_entity_reference(self.value)

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value
    _is_entity_valued = True

    @property
    def filter_value(self):
        if not self.value:
            return None

        return self.value.hash if not self.value.reserved else None

    def filter_details(self, condition):
        details = super().filter_details(condition)
        if len(condition.value_list) > 1:
            details["text"] = "is one of"
            details["or"] = [
                condition.entity_map[h].reference_details
                for h in condition.value_list
            ]
        elif len(condition.value_list) == 1:
            details["text"] = "is"
            details["entity"] = condition.entity_map[
                condition.value_list[0]
            ].reference_details
        return details


# @testable false
# @covered-by lagniappe/core/mixins/related.py::RelatedEntityMixin
# @covered-by lagniappe/core/mixins/related.py::RelatedEntityListMixin
# @reason AI reference projection is exercised through related property output
def _ai_entity_reference(entity):
    details = _ai_reference_value(entity.reference_details)
    if getattr(entity, "hash", None):
        details["hash"] = f"hash:{entity.hash}"
    return details


# @testable false
# @covered-by lagniappe/core/mixins/related.py::_ai_entity_reference
# @reason recursive sanitization is covered through related AI reference projection
def _ai_reference_value(value):
    if isinstance(value, dict):
        reference = {}
        for key, child in value.items():
            if key == "id":
                continue
            if key == "hash" and isinstance(child, str):
                reference[key] = child if child.startswith("hash:") else f"hash:{child}"
            else:
                reference[key] = _ai_reference_value(child)
        return reference
    if isinstance(value, list):
        return [_ai_reference_value(child) for child in value]
    return value
