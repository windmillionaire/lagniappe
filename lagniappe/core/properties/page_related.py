from ..definitions import Action, Fetch
from ..entities import Entities
from ..mixins import (
    AIMixin,
    ColumnMixin,
    DetailsMixin,
    FilterMixin,
    RelatedEntityListMixin,
    RelatedEntityMixin,
)
from ..tools import database
from .base_db import DBProperty
from .base_property import Property


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_categories_model_restricted_and_cache_invalidation
# @tests tests_unit/test_008_page_properties.py::test_page_categories_preserve_users_model_and_default_after_removing_only_model
# @tests tests_unit/test_008_page_properties.py::test_page_categories_reject_invalid_related_values
# @matrix page : cache-invalidation categories default-category model-category model-removal restrictions users-model
class PageCategories(
    RelatedEntityListMixin, FilterMixin, ColumnMixin, AIMixin, DBProperty
):
    """Categories a page belongs to, including its model category when applicable.

    Real category models are included in the getter but stored separately
    in the model property. The reserved Users model is not a page category.
    The setter preserves categories the user can't view and removes an omitted
    model without promoting another selected category. When that would leave
    the page with no model or categories, Uncategorized Pages becomes its model.

    Set:
        value (list): Category entities (model handled separately).

    Get:
        value (list): All real categories including the model category.
    """

    # Property Attributes
    _id = "categories"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._all_categories = None

    # @testable false
    # @covered-by lagniappe/core/properties/page_related.py::PageCategories
    # @reason page-category projection tests exercise the domain cache through the owning property
    def _invalidate_projections(self):
        self._all_categories = None
        super()._invalidate_projections()

    @property
    def value(self):
        if isinstance(self._all_categories, list):
            self._all_categories = self._page_categories(self._all_categories)
            return self._all_categories

        categories = [self.entity.model] + [c for c in super().value]
        self._all_categories = self._page_categories(categories)

        return self._all_categories

    @staticmethod
    def _page_categories(categories):
        return [
            c
            for c in categories
            if c
            and isinstance(c, Entities.CATEGORY)
            and getattr(c, "kind", None) != "users"
        ]

    @value.setter
    def value(self, value):
        if value is not None and not isinstance(value, list):
            raise TypeError("Value must be a list")
        for category in value or []:
            if not getattr(category, "key", None):
                raise ValueError("Value must have a key")

        value = value or []
        model = self.entity.model
        current_categories = self.value
        restricted = [c for c in current_categories if not c.allowed(Action.VIEW)]
        restricted_keys = {c.key for c in restricted}
        submitted_keys = [c.key for c in value]

        stored_value = []
        for category in value:
            if model and category.key == model.key:
                continue
            if category.key not in restricted_keys:
                stored_value.append(category)

        existing_keys = {c.key for c in stored_value}
        stored_value.extend(c for c in restricted if c.key not in existing_keys)
        new_categories = [c.key for c in stored_value]

        if (
            model
            and model.key not in submitted_keys
            and getattr(model, "kind", None) != "users"
        ):
            self.entity.model = None

        self._value = stored_value
        if new_categories:
            self.entity.db[self.id] = new_categories
        else:
            self.entity.db.pop(self.id, None)
        self._invalidate_projections()

        if (
            self.entity.model is None
            and not stored_value
            and (model is not None or current_categories)
        ):
            self.entity.model = Entities.CATEGORY.get_uncategorized_pages()

    # Entity Attributes
    def remove(self, value):
        key = getattr(value, "key", None)
        if not key:
            raise ValueError("Value must have a key")

        model = self.entity.model
        stored_categories = [
            c for c in RelatedEntityListMixin.value.fget(self) if c.key != key
        ]

        self._value = stored_categories
        if stored_categories:
            self.entity.db[self.id] = [c.key for c in stored_categories]
        else:
            self.entity.db.pop(self.id, None)
        self._invalidate_projections()

        if model and model.key == key:
            self.entity.model = None
            if not stored_categories:
                self.entity.model = Entities.CATEGORY.get_uncategorized_pages()

    def add(self, value):
        key = getattr(value, "key", None)
        if not key:
            raise ValueError("Value must have a key")

        model = self.entity.model

        if model and model.key != key:
            super().add(value)

    # AI Attributes
    @property
    def ai_key(self):
        return "page_categories"


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_files_loads_database_files
# @tests tests_unit/test_008_page_properties.py::test_page_files_reloads_query_results_and_skips_unlinked_files
# @matrix page : db-load files
class PageFiles(RelatedEntityListMixin, Property):
    """Files attached to a page. Loaded from the database on first access.

    Get:
        value (list): File entities attached to this page.
    """

    # Property Attributes
    _id = "files"
    _label = "Files"

    @property
    def value(self):
        if self.is_set:
            return super().value

        file_keys = [
            getattr(file, "key", file)
            for file in database.get.page_files(self.entity.key)
            if getattr(file, "key", file)
        ]
        loaded = (
            Entities.fetch(*file_keys, self.entity, request=Fetch.direct())
            if file_keys
            else []
        )

        Property.value.fset(
            self,
            [
                file
                for file in loaded
                if isinstance(file, Entities.FILE)
                and self.entity.key in file.properties.pages.keys
            ],
        )
        return self._value

    # Column Attributes
    @property
    def sort_value(self):
        return len(self.value) if self.value else None


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_user_and_model_category_parent_keys
# @pair page:user-key
class PageUser(RelatedEntityMixin, DBProperty):
    """The user who owns this page (only set for user pages).

    Set:
        value (Entity): User entity.

    Get:
        value (Entity): User entity.
    """

    # Property Attributes
    _id = "user"
    _label = "User"

    @property
    def urlsafe_key(self):
        return database.get.urlsafe_key(self.entity.db.get(self.id))


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_details
# @tests tests_unit/test_008_page_properties.py::test_page_user_and_model_category_parent_keys
# @matrix page : attach cache-parent details fallback-parent
class PageModelCategory(RelatedEntityMixin, DetailsMixin, DBProperty):
    """The primary/model category for a page.

    Setting this invalidates the PageCategories cache since the model
    is included in the categories list. Reserved categories are
    excluded from details output.

    Set:
        value (Entity): Category entity.

    Get:
        value (Entity): Category entity.
        details_value (dict | None): Model details, or the first category's
            details when no model is assigned (None if reserved).

    Overrides:
        details_key: Returns "parent".
    """

    # Property Attributes
    _id = "model"
    _label = "Model"

    @RelatedEntityMixin.value.setter
    def value(self, value):
        RelatedEntityMixin.value.fset(self, value)
        # Invalidate PageCategories cache since model is included in categories
        if self.entity and hasattr(self.entity.properties, "categories"):
            self.entity.properties.categories._all_categories = None

    # Details Attributes
    @property
    def details_key(self):
        return "parent"

    @property
    def details_value(self):
        model = self.entity.model
        parent_entity = model
        if model is None and self.entity.categories:
            parent_entity = self.entity.categories[0]

        parent = (
            parent_entity.reference_details
            if parent_entity and not parent_entity.reserved
            else None
        )
        if parent:
            parent.pop("parent", None)
        return parent

    def attach(self, key_map):
        key = super().key or self.entity.key.parent
        self._value = key_map.get(key)
        self._cache_attached_entities()
