from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, TypedDict, cast

from flask import has_request_context, session
from flask_login import current_user

from ..definitions import Action, Resource, Restriction
from ..tools import cache
from .base_property import Property

if TYPE_CHECKING:
    from ..entities.category import Category
    from ..entities.user import User as User
    from ..tools.cache.details import CachedDetail


type Access = list[str] | Restriction
type AccessField = Literal['search', 'task', 'form', 'project', 'models', 'page', 'users', 'category', 'user_assign', 'category_edit', 'user_message']
type PermissionDetails = Mapping[str, CachedDetail]


def _detail_hash(detail: CachedDetail) -> str:
    if "hash" not in detail:
        raise KeyError("hash")
    return detail["hash"]


class RestrictionState(TypedDict):
    version: int
    fingerprint: str
    value: list[str]
    belongs_to: Access
    pages_by_category: dict[str, list[str]]
    can_initiate_messages: bool
    search: Access
    task: Access
    form: Access
    project: Access
    models: Access
    page: Access
    users: Access
    category: Access
    user_assign: Access
    category_edit: Access
    user_message: Access


# @testable false
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.value
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.search
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.task
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.form
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.user_assign_restrictions
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.can_initiate_messages
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.users
class Restrictions(Property[list[str], "User"]):
    """Computed access restrictions for a user.

    Determines which resource types (models, forms, users) and specific entity
    hashes the user can access. Current-user values are cached as one versioned
    Flask session blob. Properties (task, form, project, etc.) return
    ``Restriction.UNRESTRICTED`` if unrestricted, or the restriction list if
    limited.

    Get:
        value (list): Sorted list of accessible resource hashes/types.
        search (list | Restriction.UNRESTRICTED): Restrictions for search queries.
        belongs_to (list | Restriction): Group hashes, BELONGS_TO_ALL, or BELONGS_TO_NONE.
    """

    _id = "restrictions"
    _state: RestrictionState | None = None
    _permission_details: dict[str, CachedDetail]
    _value_details: dict[str, CachedDetail]
    _session_version = 12
    _session_key = "restrictions"
    _access_fields = (
        "search",
        "task",
        "form",
        "project",
        "models",
        "page",
        "users",
        "category",
        "user_assign",
        "category_edit",
        "user_message",
    )
    _session_required_fields = frozenset(
        {
            "version",
            "fingerprint",
            "value",
            "belongs_to",
            "pages_by_category",
            "can_initiate_messages",
        }
    ) | frozenset(_access_fields)

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @matrix permissions restrictions : facets
    @property
    def value(self) -> list[str]:  # pyright: ignore[reportIncompatibleMethodOverride] -- access restrictions are computed and read-only.
        self._ensure_loaded()
        return cast(list[str], self._value)

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_only_project_permissions_that_imply_view
    # @tests tests_unit/test_009d_user_restrictions.py::test_administrator_search_membership_bypasses_restrictions
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_one_category_permissions
    # @matrix permissions restrictions : search
    @property
    def search(self) -> Access:
        return self._state_value("search")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @matrix permissions restrictions : facets
    @property
    def task(self) -> Access:
        return self._state_value("task")

    def unrestricted_pages(self, category: Category) -> Access:
        if self.entity.has_permission(category, Action.VIEW):
            return Restriction.UNRESTRICTED

        return self._ensure_loaded()["pages_by_category"].get(category.hash, [])

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @matrix permissions restrictions : facets
    @property
    def form(self) -> Access:
        return self._state_value("form")

    @property
    def project(self) -> Access:
        return self._state_value("project")

    @property
    def models(self) -> Access:
        return self._state_value("models")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @pair restrictions:page-list
    @property
    def page(self) -> Access:
        return self._state_value("page")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_user_assign_search_permission_filter_returns_assignable_users
    # @matrix permissions restrictions : assign search
    @property
    def user_assign_restrictions(self) -> Access:
        return self._state_value("user_assign")

    @property
    def user_message_restrictions(self) -> Access:
        """Users eligible for direct messages and mention suggestions."""
        return self._state_value("user_message")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_session_blob_and_fingerprint
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_empty_list_is_loaded_state
    # @pair messaging:compose-eligibility
    @property
    def can_initiate_messages(self) -> bool:
        """Session-backed capability for rendering new-message entry points."""
        return self._ensure_loaded()["can_initiate_messages"]

    # @testable true
# @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_category_search_permission_filter_returns_editable_categories
# @tests tests_e2e/002_home/test_002k_home_pages.py::test_home_page_create_visible_for_category_editor
    # @matrix permissions restrictions : category-edit search
    @property
    def category_edit_restrictions(self) -> Access:
        return self._state_value("category_edit")

    # @testable true
    # @tests tests_unit/test_020b_ai_planner.py::test_action_catalog_uses_create_update_delete_permissions
    # @matrix ai-report : action-capabilities permissions
    # @pair permissions:own-page
    @property
    def ai_action_capabilities(self) -> dict[str, bool]:
        """Live create/update/delete hints for action discovery, never target authorization."""
        return self._ai_action_capabilities()

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @matrix permissions restrictions : facets
    @property
    def users(self) -> Access:
        return self._state_value("users")

    @property
    def category(self) -> Access:
        return self._state_value("category")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_builds_group_membership_from_stored_requires
    # @tests tests_unit/test_009d_user_restrictions.py::test_administrator_search_membership_bypasses_restrictions
    # @tests tests_unit/test_009d_user_restrictions.py::test_session_membership_refreshes_without_permission_map_change
    # @matrix permissions restrictions : group-membership session-blob
    # @matrix permissions : group-membership stored-requires
    # @pair restrictions:search
    # @pair restrictions:root-fetch
    @property
    def belongs_to(self) -> Access:
        return self._ensure_loaded()["belongs_to"]

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_clear_removes_session_blob
    # @matrix permissions restrictions : clear session-blob
    def clear(self) -> None:
        if has_request_context():
            session.pop(self._session_key, None)
        self.unset()
        self._state = None
        self._permission_details = {}
        self._value_details = {}

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_empty_list_is_loaded_state
    # @matrix permissions restrictions : empty-access loaded-state
    def _ensure_loaded(self) -> RestrictionState:
        if self._state is not None and self.is_set:
            return self._state

        state = self._session_state()
        if state:
            self._load_state(state)
        else:
            self._create()
        assert self._state is not None
        return self._state

    def _state_value(self, key: AccessField) -> Access:
        return self._ensure_loaded()[key]

    def _session_enabled(self) -> bool:
        if not has_request_context():
            return False

        try:
            return current_user.is_authenticated and getattr(
                self.entity, "key", None
            ) == getattr(current_user, "key", None)
        except RuntimeError:
            return False

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_session_blob_and_fingerprint
    # @matrix permissions restrictions : empty-access session-blob stale-session
    def _session_state(self) -> RestrictionState | None:
        if not self._session_enabled():
            return None

        stored = session.get(self._session_key)
        if not isinstance(stored, dict):
            session.pop(self._session_key, None)
            return None

        state = self._deserialize_session_state(stored)
        if state is None:
            return None
        return state

    def _deserialize_session_state(
        self, stored: Mapping[str, object]
    ) -> RestrictionState | None:
        if not self._session_required_fields <= stored.keys():
            return None
        if stored["version"] != self._session_version:
            return None
        if stored["fingerprint"] != self._fingerprint():
            return None
        if not self._session_blob_types_valid(stored):
            return None

        state = dict(stored)
        for key in (*self._access_fields, "belongs_to"):
            state[key] = Restriction.from_session(state[key])
        return cast(RestrictionState, state)

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restriction_session_markers_validate_their_own_scope
    # @matrix permissions restrictions : session-blob validation
    @classmethod
    def _session_blob_types_valid(cls, stored: Mapping[str, object]) -> bool:
        return (
            isinstance(stored["value"], list)
            and (
                isinstance(stored["belongs_to"], list)
                or stored["belongs_to"] in (
                    Restriction.BELONGS_TO_ALL.value,
                    Restriction.BELONGS_TO_NONE.value,
                )
            )
            and all(
                isinstance(stored[key], list)
                or stored[key] == Restriction.UNRESTRICTED.value
                for key in cls._access_fields
            )
            and isinstance(stored["pages_by_category"], dict)
            and isinstance(stored["can_initiate_messages"], bool)
        )

    def _load_state(self, state: RestrictionState) -> None:
        self._state = state
        self._value = list(state["value"])
        self._permission_details = {}
        self._value_details = {}

    def _save_state(self) -> None:
        if not self._session_enabled():
            return

        session[self._session_key] = self._session_blob()

    def _session_blob(self) -> dict[str, object]:
        assert self._state is not None
        blob: dict[str, object] = dict(self._state)
        for key in (*self._access_fields, "belongs_to"):
            blob[key] = Restriction.to_session(blob[key])
        return blob

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_session_membership_refreshes_without_permission_map_change
    # @matrix permissions restrictions : group-membership session-blob
    def _fingerprint(self) -> str:
        return self.entity.authorization_fingerprint

    @staticmethod
    def _sorted_hashes(details: PermissionDetails, *kinds: str) -> list[str]:
        return sorted(
            {_detail_hash(item) for item in details.values() if item.get("kind") in kinds}
        )

    @staticmethod
    def _has_access(restrictions: Access) -> bool:
        return Restriction.is_unrestricted(restrictions) or bool(restrictions)

    def _permission_hashes(
        self, details: PermissionDetails, kind: str, action: Action
    ) -> list[str]:
        return sorted(
            _detail_hash(details_item)
            for details_item in details.values()
            if details_item.get("kind") == kind
            and Action[self.entity.permissions.get(_detail_hash(details_item), Action.NONE.name)].implies(
                action
            )
        )

    def _pages_by_category(self, details: PermissionDetails) -> dict[str, list[str]]:
        pages = {}
        for item in details.values():
            if item.get("kind") != "page":
                continue
            for parent_hash in item.get("requires", []):
                pages.setdefault(parent_hash, []).append(_detail_hash(item))
        return {key: sorted(value) for key, value in pages.items()}

    @staticmethod
    def _page_restrictions(models: Access) -> Access:
        return ["models"] if Restriction.is_unrestricted(models) else models

    def _task_restrictions(self, can_view_models: bool) -> Access:
        if self.entity.is_admin:
            return Restriction.UNRESTRICTED
        if can_view_models:
            return ["models"]
        return self._sorted_hashes(self._value_details, "page", "category")

    # @testable false
    # @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.ai_action_capabilities
    # @reason resource-level hints are exercised through action discovery and session tests
    def _ai_action_capabilities(self) -> dict[str, bool]:
        self._ensure_loaded()
        self._ensure_permission_details()
        can_create_models = self.entity.has_permission(Resource.MODELS, Action.CREATE)
        can_edit_models = self.entity.has_permission(Resource.MODELS, Action.EDIT)
        can_create_forms = self.entity.has_permission(Resource.FORMS, Action.CREATE)
        can_create_pages = self._has_access(self.category_edit_restrictions)
        can_edit_pages = (
            can_create_pages
            or self.entity.has_permission(self.entity.page, Action.EDIT)
            or self._has_permission_kind(self._permission_details, "page", Action.EDIT)
        )
        can_edit_projects = can_edit_models or self._has_permission_kind(
            self._permission_details, "project", Action.EDIT
        )
        # Tasks inherit Page editing; exact restrictions and assignment are checked
        # on each target, not inferred from these discovery hints.
        can_edit_tasks = can_edit_pages or self._has_permission_kind(
            self._permission_details, "task", Action.EDIT
        )
        can_delete_models = self.entity.has_permission(Resource.MODELS, Action.DELETE)
        can_delete_categories = can_delete_models or self._has_permission_kind(
            self._permission_details, "category", Action.DELETE
        )
        can_edit_forms = self.entity.has_permission(Resource.FORMS, Action.EDIT)

        return {
            "can_create_forms": can_create_forms,
            "can_create_categories": can_create_models,
            "can_create_projects": can_create_models,
            "can_create_pages": can_create_pages,
            "can_create_model_tasks": can_create_models or can_edit_projects,
            "can_update_pages": can_edit_pages,
            "can_update_tasks": can_edit_tasks,
            "can_update_forms": can_edit_forms,
            "can_delete_pages": (
                can_delete_categories
                or self._has_permission_kind(
                    self._permission_details,
                    "page",
                    Action.DELETE,
                )
            ),
        }

    def _ensure_permission_details(self) -> None:
        if self._permission_details or not self.entity.permissions:
            return
        permission_hashes = list(self.entity.permissions.keys())
        self._permission_details = (
            cache.get_details_by_hash(permission_hashes) if permission_hashes else {}
        )

    def _has_permission_kind(
        self, details: PermissionDetails, kind: str, action: Action
    ) -> bool:
        for item in details.values():
            if item.get("kind") != kind:
                continue
            level = Action[self.entity.permissions.get(item.get("hash", ""), Action.NONE.name)]
            if level.implies(action):
                return True
        return False

    def _create(self) -> None:
        if self.entity.is_admin:
            restricted_to = ["forms", "models", "users"]
            belongs_to = []
        else:
            restricted_to = [
                h
                for h, action in self.entity.permissions.items()
                if Action[action].implies(Action.VIEW)
            ]

            # ``User.requires`` persists the user's group hashes. Permission
            # checks can therefore build request restrictions from the root
            # user row without expanding the group relationship graph.
            belongs_to = [
                required for required in self.entity.requires if required != "users"
            ]

        value = sorted(list(restricted_to))
        permission_hashes = list(self.entity.permissions.keys())
        self._permission_details = (
            cache.get_details_by_hash(permission_hashes) if permission_hashes else {}
        )
        self._value_details = {
            h: details for h, details in self._permission_details.items() if h in value
        }

        can_view_models = self.entity.has_permission(Resource.MODELS, Action.VIEW)
        can_view_forms = self.entity.has_permission(Resource.FORMS, Action.VIEW)
        can_view_users = self.entity.has_permission(Resource.USERS, Action.VIEW)
        can_assign_users = self.entity.has_permission(Resource.USERS, Action.ASSIGN)
        can_edit_models = self.entity.has_permission(Resource.MODELS, Action.EDIT)

        task = self._task_restrictions(can_view_models)
        form = Restriction.UNRESTRICTED if can_view_forms or "forms" in value else value
        project = (
            Restriction.UNRESTRICTED
            if can_view_models
            else self._sorted_hashes(self._value_details, "project")
        )
        models = (
            Restriction.UNRESTRICTED if can_view_models or "models" in value else value
        )
        page = self._page_restrictions(models)
        user_assign = (
            Restriction.UNRESTRICTED
            if can_assign_users
            else self._permission_hashes(
                self._permission_details,
                "group",
                Action.ASSIGN,
            )
        )
        user_message = (
            Restriction.UNRESTRICTED
            if self.entity.is_admin or can_view_users
            else sorted(
                set(belongs_to)
                | set(
                    self._permission_hashes(
                        self._permission_details,
                        "group",
                        Action.VIEW,
                    )
                )
            )
        )
        can_initiate_messages = bool(
            not self.entity.is_public
            and not Restriction.is_denied(user_message)
        )
        if not can_initiate_messages and self._session_enabled():
            owner = cache.get_owner_projection()
            can_initiate_messages = bool(
                owner
                and owner.get("allow_messages_and_mentions")
                and owner.get("key") != self.entity.urlsafe_key
            )
        category_edit = (
            Restriction.UNRESTRICTED
            if can_edit_models
            else self._permission_hashes(
                self._permission_details,
                "category",
                Action.EDIT,
            )
        )
        users = (
            Restriction.UNRESTRICTED if can_view_users or "users" in value else value
        )
        category = (
            Restriction.UNRESTRICTED
            if can_view_models
            else self._sorted_hashes(self._permission_details, "category")
        )
        self._value = value
        self._state = {
            "version": self._session_version,
            "fingerprint": self._fingerprint(),
            "value": value,
            "belongs_to": (
                Restriction.BELONGS_TO_ALL if self.entity.is_admin
                else belongs_to or Restriction.BELONGS_TO_NONE
            ),
            "search": Restriction.UNRESTRICTED if self.entity.is_admin else value,
            "task": task,
            "form": form,
            "project": project,
            "models": models,
            "page": page,
            "user_assign": user_assign,
            "user_message": user_message,
            "can_initiate_messages": can_initiate_messages,
            "category_edit": category_edit,
            "users": users,
            "category": category,
            "pages_by_category": self._pages_by_category(self._value_details),
        }
        self._save_state()
