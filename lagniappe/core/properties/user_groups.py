from collections.abc import Mapping
from typing import TYPE_CHECKING

from ..definitions import Action, General, Levels, Site
from ..mixins import (
    GroupPermissionsMixin,
    PublicPermissionsMixin,
)
from ..tools.auth.context import current_context_user
from .common_entity import Permissions

if TYPE_CHECKING:
    from ..entities.group import PublicGroup as PublicGroup
    from ..entities.group import UserGroup as UserGroup
    from ..mixins.field_host import FieldUser


def get_view_hashes(permissions: Mapping[str, str]) -> list[str]:
    return [
        hash
        for hash, action in permissions.items()
        if Action[action].implies(Action.VIEW) and hash != "forms"
    ]


class GroupPermissions(GroupPermissionsMixin, Permissions["UserGroup"]):
    """Permission map for a group entity. Only Administrators can create/edit.

    Set:
        value (dict): {resource_hash: Action.name}.

    Get:
        value (dict): {resource_hash: Action.name}.
    """

    def create(
        self, form_data: Mapping[str, str] | None = None, user: FieldUser = None
    ) -> None:
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
        self._write_db_value(permissions)


class PublicPermissions(PublicPermissionsMixin, Permissions["PublicGroup"]):
    """Permission map for the public group.

    Includes a Site.PUBLIC entry set to TRUE/FALSE based on whether the
    group is active. Only Administrators can create/edit.

    Set:
        value (dict): {resource_hash: Action.name}.

    Get:
        value (dict): {resource_hash: Action.name}.
    """

    @property
    def enabled(self) -> bool:
        return (
            self.entity.active and self.value.get(Site.PUBLIC.value) == Levels.TRUE.name
        )

    @staticmethod
    def _with_defaults(permissions: Mapping[str, str] | None) -> dict[str, str]:
        permissions = dict(permissions or {})
        permissions.setdefault(General.FORMS.value, Levels.VIEW.name)
        return permissions

    @property
    def value(self) -> dict[str, str]:
        return self._with_defaults(self._read_db_value())

    @value.setter
    def value(self, value: dict[str, str] | None) -> None:
        self._write_db_value(self._with_defaults(value))

    def create(
        self, form_data: Mapping[str, str] | None = None, user: FieldUser = None
    ) -> None:
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

        self._write_db_value(permissions)
