"""Permission mixins for User, UserGroup, and PublicGroup entities."""
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, cast

from ..definitions import Action, Fetch, FetchReason, General, Levels, Site, Specific
from ..entities import Entities
from ..tools import cache

if TYPE_CHECKING:
    from ..entities.group import PublicGroup as PublicGroup
    from ..entities.group import UserGroup
    from ..entities.user import User


# Config for the "assigned" section (user's group membership)
ASSIGNED_CONFIG = {
    "title": "Assigned Groups",
    "kind": "group",
    "select": {
        "kind": "group",
        "id": "assigned",
        "placeholder": "add to a user group...",
        "index": "group",
        "multiple": True,
    },
}


class PermissionsMixin[Owner: User | UserGroup]:
    """Base permission management shared by User, Group, and Public mixins.

    Provides:
        get_specific_permissions(): Entity-specific permissions grouped by section.
        add_restricted_permissions(permissions, required): Prune redundant
            permissions and mark parent restrictions.
        create_permissions(form_data): Build a {hash: Action.name} dict
            from form submission data.
    """

    if TYPE_CHECKING:
        @property
        def entity(self) -> Owner: ...
        @entity.setter
        def entity(self, value: Owner) -> None: ...

    def get_specific_permissions(self) -> dict[str, list[dict[str, object]]]:
        """Return entity-specific permissions grouped by UI section."""
        permissions = self.entity.permissions
        general_keys = {g.value for g in General}
        site_keys = {s.value for s in Site}

        # Get permissions that aren't general/site level
        specific = [
            k
            for k, p in permissions.items()
            if k not in general_keys
            and k not in site_keys
            and p != "RESTRICTED"
            and k != self.entity.hash
        ]

        # Look up entity details for these permissions
        entities = cache.get_details_by_hash(specific) if specific else {}

        # Group by section
        sections = {}
        for hash, data in entities.items():
            permission = {
                "label": data.get("name"),
                "level": Levels[permissions[hash]].name,
                "name": data.get("id"),
            }
            section_name = Specific.section(data.get("kind", "")).value
            sections.setdefault(section_name, []).append(permission)

        return sections

    def add_restricted_permissions(
        self, permissions: dict[str, Action], required: Mapping[str, Iterable[str]]
    ) -> None:
        """Prune redundant child permissions and mark parent restrictions."""
        for hash, parents in required.items():
            general_values = {g.value for g in General}
            parent_actions = {
                p: permissions.get(p, Action.RESTRICTED)
                for p in parents
                if p != hash and p not in general_values
            }
            action = permissions.get(hash, Action.NONE)
            for parent, parent_action in parent_actions.items():
                if parent_action.implies(action):
                    permissions.pop(hash, None)
                elif action.implies(parent_action):
                    permissions[parent] = parent_action
                    permissions[hash] = action

    def create_permissions(self, form_data: Mapping[str, str] | None) -> dict[str, str]:
        """Build a {hash: Action.name} dict from form submission data."""
        form_data = form_data or {}
        explicit_default_denials = {
            general.value
            for general in General
            if general.value in form_data
            and general.default != Levels.NONE
            and Action[form_data.get(general.value, Action.NONE.name)] == Action.NONE
        }
        permissions = {
            **{s.value: Action[form_data.get(s.value, Action.NONE.name)] for s in Site},
            **{g.value: Action[form_data.get(g.value, Action.NONE.name)] for g in General},
        }

        entities = Entities.fetch(
            *form_data.keys(),
            request=Fetch.nested(
                because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION
            ),
        )
        for entity in entities:
            permissions[entity.hash] = Action[form_data.get(entity.urlsafe_key, Action.NONE.name)]
        required = {e.hash: cast(Iterable[str], e.required) for e in entities}

        self.add_restricted_permissions(permissions, required)
        return {
            h: p.name
            for h, p in permissions.items()
            if p != Action.NONE or h in explicit_default_denials
        }


class UserPermissionsMixin(PermissionsMixin["User"]):
    """Permission management for User entities.

    Provides:
        combine_group_permissions(): Merge permissions from all groups
            (most permissive wins per resource).
        permissions_form(): Build section config for the permissions UI.
    """

    def combine_group_permissions(self) -> dict[str, str]:
        """Merge permissions from all groups (most permissive wins)."""
        permissions = {}

        for g in self.entity.groups:
            for resource, action in g.permissions.items():
                existing = permissions.get(resource, Action.NONE)
                if Action[action].implies(existing):
                    permissions[resource] = Action[action]

        entities = cache.get_details_by_hash(permissions.keys())
        required = {}
        for entity_hash, entity in entities.items():
            if "requires" not in entity:
                raise KeyError("requires")
            required[entity_hash] = entity["requires"]
        self.add_restricted_permissions(permissions, required)

        return {h: p.name for h, p in permissions.items() if p != Action.NONE}

    def permissions_form(self) -> dict[str, object]:
        """Build section config for the user permissions UI."""
        specific_permissions = self.get_specific_permissions()

        sections = {
            "assigned": {
                **ASSIGNED_CONFIG,
                "preload": [group.details for group in self.entity.groups],
            },
        }

        # General sections (users, models, forms)
        for section in General.user():
            sections[section.value] = section.config(self.entity.permissions)

        # Specific sections (groups, categories, projects, pages)
        for section in Specific.user():
            sections[section.value] = section.config(
                permissions=specific_permissions.get(section.value, [])
            )

        return {"sections": sections}


class PublicPermissionsMixin(PermissionsMixin["PublicGroup"]):
    """Permission management for the PublicGroup entity.

    Public permissions have restricted scope -- no user-level access,
    and limited action levels (VIEW/NONE for general, EDIT/VIEW for specific).

    Provides:
        permissions_form(): Build section config for the public permissions UI.
    """

    def permissions_form(self) -> dict[str, object]:
        """Build section config for the public permissions UI."""
        specific_permissions = self.get_specific_permissions()

        sections = {
            # Public toggle
            Site.PUBLIC.value: Site.PUBLIC.config(self.entity),
        }

        # General sections (models, forms - restricted for public)
        for section in General.public():
            config = section.config(self.entity.permissions)
            # Restrict available levels for public permissions
            if section == General.MODELS or section == General.FORMS:
                config["levels"] = ["NONE", "VIEW"]
            sections[section.value] = config

        # Specific sections (categories, projects, pages - restricted levels)
        for section in Specific.public():
            config = section.config(
                permissions=specific_permissions.get(section.value, [])
            )
            # Restrict levels for public
            config["levels"] = ["EDIT", "VIEW"]
            sections[section.value] = config

        return {"sections": sections}


class GroupPermissionsMixin(PermissionsMixin["UserGroup"]):
    """Permission management for UserGroup entities.

    Users inherit permissions from all groups they belong to
    (most permissive action wins per resource).

    Provides:
        permissions_form(): Build section config for the group permissions UI.
    """

    def permissions_form(self) -> dict[str, object]:
        """Build section config for the group permissions UI."""
        specific_permissions = self.get_specific_permissions()

        sections = {}

        # General sections (users, models, forms)
        for section in General.group():
            sections[section.value] = section.config(self.entity.permissions)

        # Specific sections (groups, categories, projects, pages)
        for section in Specific.group():
            sections[section.value] = section.config(
                permissions=specific_permissions.get(section.value, [])
            )

        return {"sections": sections}
