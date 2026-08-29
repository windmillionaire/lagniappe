from ..definitions import Fetch
from ..properties import user_groups
from lagniappe.core.tools.database import get as database_get
from .entity import Entity
from . import Entities


# @testable true
# @tests tests_unit/test_009e_user_groups.py::test_group_permissions
# @tests tests_unit/test_009e_user_groups.py::test_user_group_create_rejects_public_and_initializes_permissions
# @matrix user-groups : create permissions reserved-name save
# @pair user-groups:views
class UserGroup(Entity):
    entity_kind = "group"

    @property
    def exclude_from_index(self):
        return frozenset({"permissions"})

    @property
    def required(self):
        return [self.hash, "users"]

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "permissions": user_groups.GroupPermissions,
            }
        )
        return properties

    @classmethod
    def create(cls, name):
        if name == "public":
            raise ValueError("public is a reserved group name")

        return cls.new(name)

    @classmethod
    def new(cls, name):
        new_group = cls()
        new_group.name = name
        new_group.kind = cls.entity_kind
        new_group.properties.permissions.create()

        return new_group

    # @testable true
    # @tests tests_unit/test_009e_user_groups.py::test_save_permissions_refreshes_member_users_with_current_group
    # @matrix permissions public-groups user-groups : cache-invalidation member-refresh permission-update
    def save_permissions(self, form_data=None):
        self.properties.permissions.create(form_data)

        users_in_group = database_get.users(group=self.key, limit=None)
        loaded = Entities.fetch(self, *users_in_group.results, request=Fetch.direct())
        users = [entity for entity in loaded if entity.key != self.key]
        for user in users:
            user.properties.permissions.create()

        Entities.save(*users, self)
        return users

# @testable true
# @tests tests_unit/test_009e_user_groups.py::test_public_permissions
# @tests tests_unit/test_009e_user_groups.py::test_public_group_get_create_and_enabled_state
# @matrix public-groups : create enabled get permissions
class PublicGroup(UserGroup):
    entity_kind = "public_group"

    @property
    def required(self):
        return [self.hash, "site"]

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "permissions": user_groups.PublicPermissions,
            }
        )
        return properties

    @classmethod
    def enabled(cls):
        exists = database_get.public_group()
        if not exists:
            return False
        public_group = cls(exists)
        return public_group.properties.permissions.enabled

    @classmethod
    def create(cls):
        return cls.new("public")

    @classmethod
    def get(cls):
        exists = database_get.public_group()
        if exists:
            return cls(exists)
        else:
            return cls.create()
