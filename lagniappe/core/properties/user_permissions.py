from ..definitions import Action
from ..entities import Entities
from ..mixins import UserPermissionsMixin
from .common_entity import Permissions


# @testable false
# @covered-by lagniappe/core/properties/user_permissions.py::UserPermissions.create
class UserPermissions(UserPermissionsMixin, Permissions):
    """Computed permission map for a user.

    Resolution order: application Administrators skip persisting a map.
    Public users get the public group's permissions. Users in groups get
    combined group permissions (most permissive per resource). Users with no
    groups fall back to ``create_permissions(form_data)``. The user always gets
    EDIT on their own page if not already allowed.

    Set:
        value (dict): {resource_hash: Action.name}.

    Get:
        value (dict): {resource_hash: Action.name}.
    """

    # @testable true
    # @tests tests_unit/test_009c_user_permissions_form.py::test_form_permissions
    # @tests tests_unit/test_009b_user_permissions.py::test_combine_groups
    # @tests tests_unit/test_009a_user.py::test_public_user_permissions_inherit_public_group_defaults_without_mutating_group
    # @matrix permissions : combine-groups form-data no-groups restricted
    # @pair permissions:public-group-defaults
    def create(self, form_data=None):
        self.entity.properties.restrictions.clear()
        self.entity.invalidate_cache = True

        if self.entity.is_admin:
            return
        elif self.entity.is_public:
            public_group = self._public_group()
            self.entity.groups = [public_group]
            permissions = dict(public_group.permissions)
        elif self.entity.groups:
            permissions = self.combine_group_permissions()
        elif isinstance(form_data, dict) or not form_data:
            permissions = super().create_permissions(form_data)

        # Set permissions first
        Permissions.value.fset(self, permissions)

        # User always has EDIT on their own page - add only if not already covered
        if not self.entity.has_permission(self.entity.page, Action.EDIT):
            permissions[self.entity.page.hash] = Action.EDIT.name
            Permissions.value.fset(self, permissions)

    # @testable false
    # @covered-by lagniappe/core/properties/user_permissions.py::UserPermissions.create
    # @reason public users should reuse an already-attached public group when recalculating
    def _public_group(self):
        for group in self.entity.groups:
            if self._is_public_group(group):
                return group

        return Entities.PUBLIC_GROUP.get()

    @staticmethod
    def _is_public_group(group):
        return (
            getattr(group, "kind", None) == "public_group"
            or getattr(group, "entity_kind", None) == "public_group"
            or getattr(group, "name", None) == "public"
        )
