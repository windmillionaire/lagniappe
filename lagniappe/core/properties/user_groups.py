from ..definitions import General, Levels, Site, Action
from ..mixins import (
    GroupPermissionsMixin,
    PublicPermissionsMixin,
)
from ..tools.user_context import current_context_user
from .common_entity import Permissions


# @testable true
# @tests tests_unit/test_009e_user_groups.py::test_group_permissions
# @features user-groups, permissions
# @dimensions views, form-data, restricted
def get_view_hashes(permissions):
    return [
        hash
        for hash, action in permissions.items()
        if Action[action].implies(Action.VIEW) and hash != "forms"
    ]


# @testable false
# @covered-by lagniappe/core/properties/user_groups.py::GroupPermissions.create
class GroupPermissions(GroupPermissionsMixin, Permissions):
    """Permission map for a group entity. Only Administrators can create/edit.

    Set:
        value (dict): {resource_hash: Action.name}.

    Get:
        value (dict): {resource_hash: Action.name}.
    """

    # @testable true
    # @tests tests_unit/test_009e_user_groups.py::test_group_permissions
    # @tests tests_unit/test_009e_user_groups.py::test_group_permissions_owner_only_and_unauthenticated_defaults
    # @tests tests_unit/test_009e_user_groups.py::test_general_forms_none_round_trips_for_default_view_permission
    # @features user-groups, permissions
    # @dimensions form-data, restricted, views, default-denial
    def create(self, form_data=None, user=None):
        user = current_context_user(user)
        if not user or not user.is_authenticated:
            return

        if not getattr(user, "is_admin", getattr(user, "is_owner", False)):
            raise PermissionError(
                "only site owner or an administrator can create group permissions"
            )

        permissions = super().create_permissions(form_data)
        view_hashes = get_view_hashes(permissions)
        self.entity.db["views"] = view_hashes
        Permissions.value.fset(self, permissions)


# @testable false
# @covered-by lagniappe/core/properties/user_groups.py::PublicPermissions.create
class PublicPermissions(PublicPermissionsMixin, Permissions):
    """Permission map for the public group.

    Includes a Site.PUBLIC entry set to TRUE/FALSE based on whether the
    group is active. Only Administrators can create/edit.

    Set:
        value (dict): {resource_hash: Action.name}.

    Get:
        value (dict): {resource_hash: Action.name}.
    """

    # @testable true
    # @tests tests_unit/test_009e_user_groups.py::test_public_group_get_create_and_enabled_state
    # @features public-groups
    # @dimensions enabled, permissions
    @property
    def enabled(self):
        return (
            self.entity.active
            and self.value.get(Site.PUBLIC.value) == Levels.TRUE.name
        )

    @staticmethod
    def _with_defaults(permissions):
        permissions = dict(permissions or {})
        permissions.setdefault(General.FORMS.value, Levels.VIEW.name)
        return permissions

    @property
    def value(self):
        return self._with_defaults(Permissions.value.fget(self))

    @value.setter
    def value(self, value):
        Permissions.value.fset(self, self._with_defaults(value))

    # @testable true
    # @tests tests_unit/test_009e_user_groups.py::test_public_permissions
    # @tests tests_unit/test_009e_user_groups.py::test_public_permissions_default_forms_view_is_stored
    # @tests tests_unit/test_009e_user_groups.py::test_group_permissions_owner_only_and_unauthenticated_defaults
    # @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_public_permissions
    # @features public-groups, permissions
    # @dimensions public, active, permissions
    def create(self, form_data=None, user=None):
        user = current_context_user(user)
        if not user or not user.is_authenticated:
            self._value = {Site.PUBLIC.value: Levels.FALSE.name}
            return

        if not getattr(user, "is_admin", getattr(user, "is_owner", False)):
            raise PermissionError(
                "only site owner or an administrator can create public permissions"
            )

        if form_data and Site.PUBLIC.value in form_data:
            self.entity.active = form_data.get(Site.PUBLIC.value) == Levels.TRUE.name

        permissions = self._with_defaults(super().create_permissions(form_data))
        permissions[Site.PUBLIC.value] = (
            Levels.TRUE.name if self.entity.active else Levels.FALSE.name
        )

        view_hashes = get_view_hashes(permissions)
        self.entity.db["views"] = view_hashes

        Permissions.value.fset(self, permissions)
