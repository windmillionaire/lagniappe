from typing import TYPE_CHECKING

from ..definitions import Action
from ..entities import Entities
from ..mixins import UserPermissionsMixin
from .common_entity import Permissions

if TYPE_CHECKING:
    from ..entities.group import UserGroup
    from ..entities.user import User as User


class UserPermissions(UserPermissionsMixin, Permissions["User"]):
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

    def create(self, form_data: dict[str, str] | None = None) -> None:
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
        else:
            if form_data and not isinstance(form_data, dict):
                raise TypeError("User permission form data must be a dictionary.")
            permissions = super().create_permissions(form_data)

        # Set permissions first
        self._write_db_value(permissions)

        # User always has EDIT on their own page - add only if not already covered
        if not self.entity.has_permission(self.entity.page, Action.EDIT):
            permissions[self.entity.page.hash] = Action.EDIT.name
            self._write_db_value(permissions)

    def _public_group(self) -> UserGroup:
        for group in self.entity.groups:
            if self._is_public_group(group):
                return group

        return Entities.PUBLIC_GROUP.get()

    @staticmethod
    def _is_public_group(group: UserGroup) -> bool:
        return (
            getattr(group, "kind", None) == "public_group"
            or getattr(group, "entity_kind", None) == "public_group"
            or getattr(group, "name", None) == "public"
        )
