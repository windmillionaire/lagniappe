from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..entities.category import Category
    from ..entities.file import File
    from ..entities.page import Page
    from ..entities.user import User as User

from ..definitions import Action, Fetch, FetchReason
from ..entities import Entities
from ..mixins import (
    AIMixin,
    ColumnMixin,
    DetailsMixin,
    FilterMixin,
    RelatedEntityListMixin,
    RelatedEntityMixin,
)
from lagniappe.core.tools.database import get as database_get
from .base_db import DBProperty
from .base_property import Property


class PageCategories(
    RelatedEntityListMixin["Category"], FilterMixin, ColumnMixin, AIMixin, DBProperty["list[Category]", "Page"]
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
    _value: object

    def __init__(self, *args: object, entity: Page | None = None, **kwargs: object) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self._all_categories: list[Category] | None = None

    def _invalidate_projections(self) -> None:
        self._all_categories = None
        super()._invalidate_projections()

    @property
    def value(self) -> list[Category]:
        if isinstance(self._all_categories, list):
            self._all_categories = self._page_categories(self._all_categories)
            return self._all_categories

        categories = [self.entity.model] + [c for c in super().value]
        self._all_categories = self._page_categories(categories)

        return self._all_categories

    @staticmethod
    def _page_categories(categories: Iterable[Category | None]) -> list[Category]:
        return [
            c
            for c in categories
            if c
            and isinstance(c, Entities.CATEGORY)
            and getattr(c, "kind", None) != "users"
        ]

    @value.setter
    def value(self, value: list[Category] | None) -> None:
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
    def remove(self, value: Category) -> None:
        key = getattr(value, "key", None)
        if not key:
            raise ValueError("Value must have a key")

        model = self.entity.model
        stored_categories = [
            c for c in self._read_related_list() if c.key != key
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

    def add(self, value: Category) -> None:
        key = getattr(value, "key", None)
        if not key:
            raise ValueError("Value must have a key")

        model = self.entity.model

        if model and model.key != key:
            super().add(value)

    # AI Attributes
    @property
    def ai_key(self) -> str:
        return "page_categories"


class PageFiles(RelatedEntityListMixin["File"], Property["list[File]", "Page"]):
    """Files attached to a page. Loaded from the database on first access.

    Get:
        value (list): File entities attached to this page.
    """

    # Property Attributes
    _id = "files"
    _value: object
    _label = "Files"

    @property
    def value(self) -> list[File]:  # pyright: ignore[reportIncompatibleMethodOverride] -- The live reverse relation is read-only.
        if self.is_set:
            return super().value

        file_keys = [
            cast("Key", getattr(file, "key", file))
            for file in database_get.page_files(self.entity.key)
            if getattr(file, "key", file)
        ]
        loaded = (
            Entities.fetch(*file_keys, self.entity, request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
            if file_keys
            else []
        )

        files = [
            file for file in loaded
            if isinstance(file, Entities.FILE) and self.entity.key == file.properties.page.key
        ]
        self._value = files
        return files

    # Column Attributes
    @property
    def sort_value(self) -> int | None:
        return len(self.value) if self.value else None


class PageUser(RelatedEntityMixin["User"], DBProperty["User", "Page"]):
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
    def urlsafe_key(self) -> str | None:
        return database_get.urlsafe_key(cast("Key | None", self.entity.db.get(self.id)))


class PageModelCategory(RelatedEntityMixin["Category"], DetailsMixin, DBProperty["Category", "Page"]):
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
    _value: object
    _label = "Model"

    @property
    def value(self) -> Category | None:
        return self._read_related()

    @value.setter
    def value(self, value: Category | None) -> None:
        self._write_related(value)
        # Invalidate PageCategories cache since model is included in categories
        if self.entity and hasattr(self.entity.properties, "categories"):
            self.entity.properties.categories._all_categories = None

    # Details Attributes
    @property
    def details_key(self) -> str:
        return "parent"

    @property
    def details_value(self) -> dict[str, object] | None:
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

    def attach(self, key_map: Mapping[Key, Category]) -> None:
        key = super().key
        if key is None:
            page_key = self.entity.key
            if page_key is None:
                raise AttributeError("Page model attachment requires a page key")
            key = page_key.parent
        self._value = key_map.get(key) if key is not None else None
        self._cache_attached_entities()
