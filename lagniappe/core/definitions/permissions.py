"""Permission actions, resources, levels, and UI section definitions."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.user import User


from enum import Enum, auto

from ..restrictions import Restriction  # noqa: F401 - re-exported by definitions
from .default import DefaultEnum


# @testable infrastructure
# @covered-by lagniappe/core/definitions/permissions.py::Action.implies
class Action(Enum, metaclass=DefaultEnum):
    """Hierarchical permission actions in ascending order of privilege.

    Higher actions imply all lower ones (e.g. DELETE implies EDIT, VIEW).
    Unknown action names resolve to NONE via DefaultEnum.
    """

    NONE = 0
    RESTRICTED = auto()
    VIEW = auto()
    ASSIGN = auto()
    EDIT = auto()
    DELETE = auto()
    PUBLISH = auto()
    CREATE = auto()
    PERMISSIONS = auto()
    ALL = auto()

    DEFAULT = NONE

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_resource_allowed_direct_contract
    # @pair permissions:action-lattice
    def implies(self, action: Action) -> bool:
        """Check if this action implies (includes) another action."""
        return self.value >= action.value if self.value else False


# @testable infrastructure
# @covered-by lagniappe/core/definitions/permissions.py::Resource.allowed
class Resource(Enum):
    """Resource types for permission checking.

    Administrative resources (SITE, USER_GROUPS, INGRESS) require an Admin.
    Global resources (USERS, MODELS, FORMS) check Admin or permissions.
    Instance resources alias to their global resource.
    """

    # Administrative Resources
    SITE = "site"
    USER_GROUPS = "groups"
    INGRESS = "ingress"

    # Global Resources
    USERS = "users"
    MODELS = "models"
    FORMS = "forms"
    PROJECTS = MODELS
    TASKS = MODELS
    FILTER = MODELS

    # Instance Resources (aliases to global resources)
    USER = USERS
    FORM = FORMS
    USER_GROUP = USER_GROUPS
    GROUP = USER_GROUPS
    PUBLIC_GROUP = USER_GROUPS
    PAGE = MODELS
    CATEGORY = MODELS
    PROJECT = MODELS
    TASK = MODELS
    FILE = MODELS
    MODEL = MODELS
    TASK_HISTORY = TASKS
    REPORT = MODELS

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_resource_allowed_direct_contract
    # @matrix permissions : anonymous default-deny resource-gates
    def allowed(self, action: Action, user: User | None = None) -> bool:
        """Check if the user has at least the given action on this resource."""
        from ..tools.auth.context import current_context_user

        viewer = current_context_user(user)
        if not viewer:
            return False
        if not viewer.is_authenticated:
            return False
        if self in [Resource.SITE, Resource.USER_GROUPS, Resource.INGRESS]:
            return self._admin_resource_allowed(viewer)
        elif self == Resource.MODELS:
            return self._models_resource_allowed(action, viewer)
        elif self == Resource.FORMS:
            return self._forms_resource_allowed(action, viewer)
        elif self == Resource.USERS:
            return self._users_resource_allowed(action, viewer)

        return False

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_resource_allowed_direct_contract
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_admin_permissions
    # @matrix permissions : admin owner
    def _admin_resource_allowed(self, user):
        return bool(getattr(user, "is_admin", getattr(user, "is_owner", False)))

    # @testable false
    # @covered-by lagniappe/core/definitions/permissions.py::Resource._models_resource_allowed
    # @covered-by lagniappe/core/definitions/permissions.py::Resource._forms_resource_allowed
    # @covered-by lagniappe/core/definitions/permissions.py::Resource._users_resource_allowed
    # @reason shared global-resource action lookup used by the resource-specific branches
    def _global_resource_allowed(self, action, user):
        return (
            True
            if getattr(user, "is_admin", getattr(user, "is_owner", False))
            else Action[user.permissions.get(self.value)].implies(action)
        )

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_resource_allowed_direct_contract
    # @tests tests_unit/test_009b_user_permissions.py::test_global_resources
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_directory_general_models_view_only
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_create_toggles_require_global_models_create
    # @matrix permissions : aliases global-resources
    def _models_resource_allowed(self, action, user):
        return self._global_resource_allowed(action, user)

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_resource_allowed_direct_contract
    # @tests tests_unit/test_009b_user_permissions.py::test_global_resources
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_directory_general_forms_view_only
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_create_category_hides_form_picker_without_forms_view
    # @matrix permissions : global-resources resource-gates
    def _forms_resource_allowed(self, action, user):
        return self._global_resource_allowed(action, user)

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_global_resources
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_admin_permissions
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_directory_general_users_view_only
    # @pair permissions:global-resources
    def _users_resource_allowed(self, action, user):
        return self._global_resource_allowed(action, user)


# @testable infrastructure
# @covered-by lagniappe/core/mixins/permissions.py::PermissionsMixin.create_permissions
# @covered-by lagniappe/core/mixins/permissions.py::UserPermissionsMixin.permissions_form
# @covered-by lagniappe/core/mixins/permissions.py::PublicPermissionsMixin.permissions_form
# @covered-by lagniappe/core/mixins/permissions.py::GroupPermissionsMixin.permissions_form
class Levels(Enum):
    """Permission levels for the UI form. Includes boolean variants
    (FALSE/TRUE) for checkbox-style permissions like admin status.
    """

    NONE = "NONE"
    FALSE = "FALSE"
    TRUE = "TRUE"
    RESTRICTED = "RESTRICTED"
    VIEW = "VIEW"
    ASSIGN = "ASSIGN"
    EDIT = "EDIT"
    DELETE = "DELETE"
    PUBLISH = "PUBLISH"
    CREATE = "CREATE"


# @testable infrastructure
# @covered-by lagniappe/core/mixins/permissions.py::PermissionsMixin.get_specific_permissions
# @covered-by lagniappe/core/mixins/permissions.py::UserPermissionsMixin.permissions_form
# @covered-by lagniappe/core/mixins/permissions.py::PublicPermissionsMixin.permissions_form
# @covered-by lagniappe/core/mixins/permissions.py::GroupPermissionsMixin.permissions_form
class Specific(Enum):
    """Entity-level permission sections (individual categories, projects, etc.).

    Each section defines its available levels, UI config, and facet selector
    for the permissions form.
    """

    GROUPS = "groups"
    CATEGORIES = "categories"
    PROJECTS = "projects"
    PAGES = "pages"

    @property
    def title(self) -> str:
        titles = {
            "groups": "User Groups",
            "categories": "Categories",
            "projects": "Projects",
            "pages": "Pages",
        }
        return titles[self.value]

    @property
    def kind(self) -> str:
        kinds = {
            "groups": "group",
            "categories": "category",
            "projects": "project",
            "pages": "page",
        }
        return kinds[self.value]

    @property
    def levels(self) -> list[Levels]:
        levels = [Levels.VIEW, Levels.EDIT]

        if self == Specific.GROUPS:
            levels.append(Levels.ASSIGN)
        elif self in [Specific.CATEGORIES, Specific.PROJECTS]:
            levels.append(Levels.PUBLISH)
            levels.append(Levels.DELETE)
            levels.append(Levels.CREATE)
        elif self == Specific.PAGES:
            levels.append(Levels.PUBLISH)

        return levels

    @property
    def default(self) -> Levels:
        return Levels.VIEW

    @property
    def select(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "id": self.value,
            "placeholder": f"add {self.kind} access...",
            "index": self.kind,
        }

    def config(
        self, permissions: list[dict[str, object]] | None = None
    ) -> dict[str, object]:
        """Generate full UI config dict for this section."""
        return {
            "title": self.title,
            "levels": [level.name for level in self.levels],
            "kind": self.kind,
            "select": self.select,
            "permissions": permissions or [],
        }

    @classmethod
    def section(cls, kind: str) -> Specific:
        if kind == "category":
            return cls.CATEGORIES
        elif kind == "project":
            return cls.PROJECTS
        elif kind == "page":
            return cls.PAGES
        elif kind == "group":
            return cls.GROUPS
        else:
            raise ValueError(f"Invalid section kind: {kind}")

    @staticmethod
    def user() -> list[Specific]:
        return [p for p in Specific]

    @staticmethod
    def group() -> list[Specific]:
        return [p for p in Specific]

    @staticmethod
    def public() -> list[Specific]:
        return [Specific.CATEGORIES, Specific.PROJECTS, Specific.PAGES]


# @testable infrastructure
# @covered-by lagniappe/core/mixins/permissions.py::PermissionsMixin.create_permissions
# @covered-by lagniappe/core/mixins/permissions.py::PublicPermissionsMixin.permissions_form
class Site(Enum):
    """Site-wide boolean permission flags (public)."""

    PUBLIC = "public"

    @property
    def title(self) -> str:
        titles = {
            "public": "Public Users Allowed",
        }
        return titles[self.value]

    @property
    def levels(self) -> list[Levels]:
        return [Levels.FALSE, Levels.TRUE]

    @property
    def default(self) -> Levels:
        return Levels.FALSE

    def config(self, entity: Entity) -> dict[str, object]:
        """Generate full UI config dict for this site flag."""
        if self == Site.PUBLIC:
            level = Levels.TRUE.name if entity.active else Levels.FALSE.name
        else:
            raise ValueError(f"Invalid site section: {self}")

        return {
            "title": self.title,
            "levels": [level.name for level in self.levels],
            "permission": {"level": level, "name": self.value},
        }


# @testable infrastructure
# @covered-by lagniappe/core/mixins/permissions.py::PermissionsMixin.create_permissions
# @covered-by lagniappe/core/mixins/permissions.py::UserPermissionsMixin.permissions_form
# @covered-by lagniappe/core/mixins/permissions.py::PublicPermissionsMixin.permissions_form
# @covered-by lagniappe/core/mixins/permissions.py::GroupPermissionsMixin.permissions_form
class General(Enum):
    """Global permission sections (users, models, forms).

    Permissions on entire resource types rather than specific entities.
    """

    USERS = "users"
    MODELS = "models"
    FORMS = "forms"

    @property
    def title(self) -> str:
        titles = {
            "users": "Users",
            "models": "Models",
            "forms": "Forms",
        }
        return titles[self.value]

    @property
    def levels(self) -> list[Levels]:
        if self == General.USERS:
            return [
                Levels.NONE,
                Levels.VIEW,
                Levels.ASSIGN,
                Levels.DELETE,
                Levels.CREATE,
            ]
        return [Levels.NONE, Levels.VIEW, Levels.EDIT, Levels.DELETE, Levels.CREATE]

    @property
    def default(self) -> Levels:
        if self == General.FORMS:
            return Levels.VIEW
        return Levels.NONE

    def config(self, permissions: Mapping[str, str]) -> dict[str, object]:
        """Generate full UI config dict for this section."""
        existing = permissions.get(self.value, self.default.name)
        return {
            "title": self.title,
            "kind": "form" if self == General.FORMS else "user",
            "levels": [level.name for level in self.levels],
            "permission": {"level": Levels[existing].name, "name": self.value},
        }

    @staticmethod
    def user() -> list[General]:
        return [p for p in General]

    @staticmethod
    def group() -> list[General]:
        return [p for p in General]

    @staticmethod
    def public() -> list[General]:
        return [General.MODELS, General.FORMS]
