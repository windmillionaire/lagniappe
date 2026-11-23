from collections.abc import Iterable
from typing import TYPE_CHECKING, cast

from ..definitions import Fetch, MutationIntent, Ordering
from ..entities import Entities
from ..mixins import (
    ColumnMixin,
    FilterMixin,
    RelatedEntityListMixin,
    RelatedEntityMixin,
)
from .base_db import DBProperty

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..entities.category import UserCategory
    from ..entities.entity import Entity
    from ..entities.group import UserGroup
    from ..entities.page import Page, PageData
    from ..entities.user import User as User


class Groups(RelatedEntityListMixin["UserGroup"], FilterMixin, ColumnMixin, DBProperty[list["UserGroup"], "User"]):
    """Groups a user belongs to.

    Changing group membership triggers a permission recalculation.

    Set:
        value (list): Group entities. Triggers permissions.create()
            if the set changes.

    Get:
        value (list): Group entities.
    """

    # Property Attributes
    _id = "groups"
    _label = "Groups"
    _ordering = Ordering.CATEGORICAL
    _icon = "group"

    @property
    def value(self) -> list[UserGroup]:
        value = self._read_related_list()
        if self.entity.is_public and not self._is_public_only(value):
            value = [self._public_group(value)]
            self._write_related_list(value)
        return value

    @value.setter
    def value(self, value: list[UserGroup] | None) -> None:
        if value is not None and not isinstance(value, list):
            raise TypeError("Value must be a list")

        value = value or []
        if self.entity.is_public:
            value = [self._public_group(value)]

        for group in value:
            if not getattr(group, "key", None):
                raise ValueError("Value must have a key")

        existing = [g.key for g in self._read_related_list()]
        new = [g.key for g in value]

        if set(existing) != set(new):
            self._write_related_list(value)
            self.entity.properties.permissions.create()

    # DB Attributes
    def add(self, value: UserGroup) -> bool | None:
        if not getattr(value, "key", None):
            raise ValueError("Value must have a key")

        if self.entity.is_public:
            existing_value = self._read_related_list()
            public_group = self._public_group(existing_value)
            existing = [g.key for g in existing_value]
            self.value = [public_group]
            return set(existing) != {public_group.key}

        if super().add(value):
            self.entity.properties.permissions.create()

    def _public_group(self, value: list[UserGroup] | None = None) -> UserGroup:
        for group in value or []:
            if self._is_public_group(group):
                return group
        return Entities.PUBLIC_GROUP.get()

    def _is_public_only(self, value: list[UserGroup]) -> bool:
        return len(value) == 1 and self._is_public_group(value[0])

    @staticmethod
    def _is_public_group(group: UserGroup) -> bool:
        return (
            getattr(group, "kind", None) == "public_group"
            or getattr(group, "entity_kind", None) == "public_group"
            or getattr(group, "name", None) == "public"
        )


class UserPage(RelatedEntityMixin["Page"], DBProperty["Page", "User"]):
    """The page entity associated with a user.

    Auto-created if not provided. The user entity handles auth and
    permissions; all other user data (notes, tasks, etc.) lives on
    this page. Setting the page also syncs the user's hash.

    Set:
        value (Entity | None): Page entity. None creates a new user page.

    Get:
        value (Entity): The user's page entity.
    """

    # Property Attributes
    _id = "page"
    _value: object

    @property
    def value(self) -> Page:
        if self.is_set:
            return cast("Page", self._value)

        key = self.entity.db.get(self.id)
        if not key:
            raise RuntimeError("User page key not found")
        page = cast("Page", Entities.fetch_one(cast("Key | str", key), request=Fetch.direct()))
        self._value = page
        page.user = self.entity
        self._cache_attached_entities()
        return cast("Page", self._value)

    @value.setter
    def value(self, value: Page | None) -> None:
        page = value
        user_model = self._user_model(page)
        if not page:
            page = self._create_user_page(user_model)

        self._set_user_model(page, user_model)
        self._write_related(page)
        page.user = self.entity
        self.entity.add_mutation_intents(
            MutationIntent.standard(page, reason="user-page-mirror")
        )

    def _create_user_page(self, user_model: UserCategory) -> Page:
        data: PageData = {
            "model": user_model,
            "user": self.entity,
            "name": self.entity.name,
        }
        return Entities.PAGE.create(data)

    def _user_model(self, page: Page | None = None) -> UserCategory:
        model = page.model if page else None
        if isinstance(model, Entities.USERS):
            return model
        return Entities.USERS.get()

    def _set_user_model(self, page: Page, user_model: UserCategory) -> None:
        categories = page.categories
        page.model = user_model
        page.categories = categories


class Starred(RelatedEntityListMixin["Entity"], DBProperty[list["Entity"], "User"]):
    """Entities the user has starred (bookmarked).

    Supports toggling and bulk deletion of stale keys.

    Get:
        value (list): Starred entities.
    """

    # Property Attributes
    _id = "starred"
    _label = "Starred"

    def toggle_star(self, entity: Entity) -> bool:
        if entity.key in [s.key for s in self.value]:
            self.remove(entity)
            return False
        else:
            self.add(entity)
            return True

    def delete_starred_keys(self, keys: Iterable[Key]) -> None:
        for key in keys:
            cast("list[Key]", self.entity.db[self.id]).remove(key)
