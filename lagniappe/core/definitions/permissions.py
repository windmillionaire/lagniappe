"""Permission actions, resources, levels, and UI section definitions."""

from enum import Enum, auto

from ..tools.user_context import current_context_user
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
    # @features permissions
    # @dimensions action-lattice
    def implies(self, action):
        """Check if this action implies (includes) another action."""
        return self.value >= action.value if self.value else False


# @testable infrastructure
class Restriction(Enum):
    """Sentinel values for permission restriction filters.

    ``UNRESTRICTED`` means no required-access filter should be applied. It is
    intentionally distinct from an empty list, which means the user has no
    allowed hashes for that filtered view.
    """

    UNRESTRICTED = "UNRESTRICTED"

    @classmethod
    def is_unrestricted(cls, value):
        return value is cls.UNRESTRICTED

    @classmethod
    def is_denied(cls, value):
        return isinstance(value, list) and not value

    @classmethod
    def from_session(cls, value):
        return cls.UNRESTRICTED if value == cls.UNRESTRICTED.value else value

    @classmethod
    def to_session(cls, value):
        return cls.UNRESTRICTED.value if value is cls.UNRESTRICTED else value


# @testable infrastructure
# @covered-by lagniappe/core/definitions/permissions.py::Resource.allowed
class Resource(Enum):
    """Resource types for permission checking.

    Owner resources (SITE, USER_GROUPS, INGRESS) require owner.
    Global resources (USERS, MODELS, FORMS) check admin or permissions.
    Instance resources alias to their global resource.
    """

    # Owner Resources
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
    # @features permissions
    # @dimensions resource-gates anonymous default-deny
    def allowed(self, action, user=None):
        """Check if the user has at least the given action on this resource."""
        user = current_context_user(user)
        if not user:
            return False
        if not user.is_authenticated:
            return False
        if self in [Resource.SITE, Resource.USER_GROUPS, Resource.INGRESS]:
            return self._owner_resource_allowed(user)
        elif self == Resource.MODELS:
            return self._models_resource_allowed(action, user)
        elif self == Resource.FORMS:
            return self._forms_resource_allowed(action, user)
        elif self == Resource.USERS:
            return self._users_resource_allowed(action, user)

        return False

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_resource_allowed_direct_contract
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_admin_permissions
    # @features permissions
    # @dimensions owner
    def _owner_resource_allowed(self, user):
        return True if user.is_owner else False

    # @testable false
    # @covered-by lagniappe/core/definitions/permissions.py::Resource._models_resource_allowed
    # @covered-by lagniappe/core/definitions/permissions.py::Resource._forms_resource_allowed
    # @covered-by lagniappe/core/definitions/permissions.py::Resource._users_resource_allowed
    # @reason shared global-resource action lookup used by the resource-specific branches
    def _global_resource_allowed(self, action, user):
        return (
            True
            if user.is_owner
            else Action[user.permissions.get(self.value)].implies(action)
        )

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_resource_allowed_direct_contract
    # @tests tests_unit/test_009b_user_permissions.py::test_global_resources
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_directory_general_models_view_only
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_create_toggles_require_global_models_create
    # @features permissions
    # @dimensions global-resources aliases
    def _models_resource_allowed(self, action, user):
        return self._global_resource_allowed(action, user)

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_resource_allowed_direct_contract
    # @tests tests_unit/test_009b_user_permissions.py::test_global_resources
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_directory_general_forms_view_only
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_create_category_hides_form_picker_without_forms_view
    # @features permissions
    # @dimensions global-resources
    def _forms_resource_allowed(self, action, user):
        return self._global_resource_allowed(action, user)

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_global_resources
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_admin_permissions
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_directory_general_users_view_only
    # @features permissions
    # @dimensions global-resources
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
    def title(self):
        titles = {
            "groups": "User Groups",
            "categories": "Categories",
            "projects": "Projects",
            "pages": "Pages",
        }
        return titles[self.value]

    @property
    def kind(self):
        kinds = {
            "groups": "group",
            "categories": "category",
            "projects": "project",
            "pages": "page",
        }
        return kinds[self.value]

    @property
    def levels(self):
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
    def default(self):
        return Levels.VIEW

    @property
    def select(self):
        return {
            "kind": self.kind,
            "id": self.value,
            "placeholder": f"add {self.kind} access...",
            "index": self.kind,
        }

    def config(self, permissions=None):
        """Generate full UI config dict for this section."""
        return {
            "title": self.title,
            "levels": [level.name for level in self.levels],
            "kind": self.kind,
            "select": self.select,
            "permissions": permissions or [],
        }

    @classmethod
    def section(cls, kind):
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
    def user():
        return [p for p in Specific]

    @staticmethod
    def group():
        return [p for p in Specific]

    @staticmethod
    def public():
        return [Specific.CATEGORIES, Specific.PROJECTS, Specific.PAGES]


# @testable infrastructure
# @covered-by lagniappe/core/mixins/permissions.py::PermissionsMixin.create_permissions
# @covered-by lagniappe/core/mixins/permissions.py::PublicPermissionsMixin.permissions_form
class Site(Enum):
    """Site-wide boolean permission flags (public)."""

    PUBLIC = "public"

    @property
    def title(self):
        titles = {
            "public": "Public Users Allowed",
        }
        return titles[self.value]

    @property
    def levels(self):
        return [Levels.FALSE, Levels.TRUE]

    @property
    def default(self):
        return Levels.FALSE

    def config(self, entity):
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
    def title(self):
        titles = {
            "users": "Users",
            "models": "Models",
            "forms": "Forms",
        }
        return titles[self.value]

    @property
    def levels(self):
        if self == General.USERS:
            return [
                Levels.NONE,
                Levels.VIEW,
                Levels.ASSIGN,
                Levels.DELETE,
                Levels.CREATE,
            ]
        elif self in [General.MODELS, General.FORMS]:
            return [Levels.NONE, Levels.VIEW, Levels.EDIT, Levels.DELETE, Levels.CREATE]

    @property
    def default(self):
        if self == General.FORMS:
            return Levels.VIEW
        return Levels.NONE

    def config(self, permissions):
        """Generate full UI config dict for this section."""
        existing = permissions.get(self.value, self.default.name)
        return {
            "title": self.title,
            "kind": "form" if self == General.FORMS else "user",
            "levels": [level.name for level in self.levels],
            "permission": {"level": Levels[existing].name, "name": self.value},
        }

    @staticmethod
    def user():
        return [p for p in General]

    @staticmethod
    def group():
        return [p for p in General]

    @staticmethod
    def public():
        return [General.MODELS, General.FORMS]
