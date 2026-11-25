from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast

from ..definitions import Fetch
from ..properties import user_groups
from lagniappe.core.tools.database import get as database_get
from .entity import Entity, EntityProperties
from . import Entities


if TYPE_CHECKING:
    from . import property_types
    from .user import User


class UserGroup(Entity):
    if TYPE_CHECKING:
        permissions: dict[str, str]

        @property
        def properties(self) -> property_types.UserGroupProperties: ...

    entity_kind = "group"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset({"permissions"})

    @property
    def required(self) -> list[str]:
        return [self.hash, "users"]

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "permissions": user_groups.GroupPermissions,
            }
        )
        return properties

    @classmethod
    def create(cls, name: str) -> Self:
        if name == "public":
            raise ValueError("public is a reserved group name")

        return cls.new(name)

    @classmethod
    def new(cls, name: str) -> Self:
        new_group = cls()
        new_group.name = name
        new_group.kind = cls.entity_kind
        new_group.properties.permissions.create()

        return new_group

    def save_permissions(self, form_data: Mapping[str, str] | None = None) -> list[User]:
        self.properties.permissions.create(form_data)

        users_in_group = database_get.users(group=self.key, limit=None)
        loaded = Entities.fetch(self, *users_in_group.results, request=Fetch.direct())
        # The query only requests users. The group itself was an extra direct root.
        users = [cast("User", entity) for entity in loaded if entity.key != self.key]
        for user in users:
            user.properties.permissions.create()

        Entities.save(*users, self)
        return users

class PublicGroup(UserGroup):
    entity_kind = "public_group"

    @property
    def required(self) -> list[str]:
        return [self.hash, "site"]

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "permissions": user_groups.PublicPermissions,
            }
        )
        return properties

    @classmethod
    def enabled(cls) -> bool:
        exists = database_get.public_group()
        if not exists:
            return False
        public_group = cls(exists)
        return cast(user_groups.PublicPermissions, public_group.properties.permissions).enabled

    @classmethod
    def create(cls) -> Self:  # pyright: ignore[reportIncompatibleMethodOverride] -- The singleton is always named public.
        return cls.new("public")

    @classmethod
    def get(cls) -> Self:
        exists = database_get.public_group()
        if exists:
            return cls(exists)
        else:
            return cls.create()
