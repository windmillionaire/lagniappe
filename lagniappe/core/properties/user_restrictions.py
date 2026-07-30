from flask import has_request_context, session
from flask_login import current_user

from ..definitions import Action, Resource, Restriction
from ..tools import cache
from .base_property import Property


# @testable false
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.value
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.search
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.task
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.form
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.user_assign_restrictions
# @covered-by lagniappe/core/properties/user_restrictions.py::Restrictions.users
class Restrictions(Property):
    """Computed access restrictions for a user.

    Determines which resource types (models, forms, users) and specific entity
    hashes the user can access. Current-user values are cached as one versioned
    Flask session blob. Properties (task, form, project, etc.) return
    ``Restriction.UNRESTRICTED`` if unrestricted, or the restriction list if
    limited.

    Get:
        value (list): Sorted list of accessible resource hashes/types.
        search (list | Restriction.UNRESTRICTED): Restrictions for search queries.
    """

    _id = "restrictions"
    _session_version = 6
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
    )
    _session_required_fields = frozenset(
        {
            "version",
            "fingerprint",
            "value",
            "belongs_to",
            "pages_by_category",
        }
    ) | frozenset(_access_fields)

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @features restrictions, permissions
    # @dimensions facets
    @property
    def value(self):
        self._ensure_loaded()
        return self._value

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @tests tests_e2e/002_home/test_002h_home_permissions.py::test_one_category_permissions
    # @features restrictions, permissions
    # @dimensions search
    @property
    def search(self):
        return self._state_value("search")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @features restrictions, permissions
    # @dimensions facets
    @property
    def task(self):
        return self._state_value("task")

    def unrestricted_pages(self, category):
        if self.entity.has_permission(category, Action.VIEW):
            return Restriction.UNRESTRICTED

        self._ensure_loaded()
        return self._state.get("pages_by_category", {}).get(category.hash, [])

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @features restrictions, permissions
    # @dimensions facets
    @property
    def form(self):
        return self._state_value("form")

    @property
    def project(self):
        return self._state_value("project")

    @property
    def models(self):
        return self._state_value("models")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @features restrictions
    # @dimensions page-list
    @property
    def page(self):
        return self._state_value("page")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_user_assign_search_permission_filter_returns_assignable_users
    # @features restrictions, permissions
    # @dimensions assign search
    @property
    def user_assign_restrictions(self):
        return self._state_value("user_assign")

    # @testable true
# @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
# @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_category_search_permission_filter_returns_editable_categories
# @tests tests_e2e/002_home/test_002k_home_pages.py::test_home_page_create_visible_for_category_editor
    # @features restrictions, permissions
    # @dimensions category-edit search
    @property
    def category_edit_restrictions(self):
        return self._state_value("category_edit")

    # @testable true
    # @tests tests_unit/test_020_ai_reports.py::test_report_prompts_filter_actions_by_user_permissions
    # @features ai-report
    # @dimensions action-capabilities permissions
    @property
    def ai_action_capabilities(self):
        return self._ai_action_capabilities()

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions
    # @features restrictions, permissions
    # @dimensions facets
    @property
    def users(self):
        return self._state_value("users")

    @property
    def category(self):
        return self._state_value("category")

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_builds_group_membership_from_stored_requires
    # @pair restrictions:root-fetch
    # @pair permissions:stored-requires
    # @pair permissions:group-membership
    @property
    def belongs_to(self):
        self._ensure_loaded()
        return self._state["belongs_to"]

    # @testable true
    # @tests tests_unit/test_009d_user_restrictions.py::test_restrictions_clear_removes_session_blob
    # @features restrictions permissions
    # @dimensions clear session-blob
    def clear(self):
        if has_request_context():
            session.pop(self._session_key, None)
        self.unset()
        self._state = None
        self._permission_details = {}
        self._value_details = {}

    def _ensure_loaded(self):
        if getattr(self, "_state", None) is not None and self.is_set:
            return

        state = self._session_state()
        if state:
            self._load_state(state)
        else:
            self._create()

    def _state_value(self, key):
        self._ensure_loaded()
        return self._state[key]

    def _session_enabled(self):
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
    # @features restrictions permissions
    # @dimensions session-blob stale-session empty-access
    def _session_state(self):
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

    def _deserialize_session_state(self, stored):
        if not self._session_required_fields <= stored.keys():
            return None
        if stored["version"] != self._session_version:
            return None
        if stored["fingerprint"] != self._fingerprint():
            return None
        if not self._session_blob_types_valid(stored):
            return None

        state = dict(stored)
        for key in self._access_fields:
            state[key] = Restriction.from_session(state[key])
        return state

    @staticmethod
    def _session_blob_types_valid(stored):
        return (
            isinstance(stored["value"], list)
            and isinstance(stored["belongs_to"], list)
            and isinstance(stored["pages_by_category"], dict)
        )

    def _load_state(self, state):
        self._state = state
        self._value = list(state["value"])
        self._permission_details = {}
        self._value_details = {}

    def _save_state(self):
        if not self._session_enabled():
            return

        session[self._session_key] = self._session_blob()

    def _session_blob(self):
        blob = dict(self._state)
        for key in self._access_fields:
            blob[key] = Restriction.to_session(blob[key])
        return blob

    def _fingerprint(self):
        return self.entity.permissions_fingerprint

    @staticmethod
    def _sorted_hashes(details, *kinds):
        return sorted(
            {item["hash"] for item in details.values() if item.get("kind") in kinds}
        )

    @staticmethod
    def _has_access(restrictions):
        return Restriction.is_unrestricted(restrictions) or bool(restrictions)

    def _permission_hashes(self, details, kind, action):
        return sorted(
            details_item["hash"]
            for details_item in details.values()
            if details_item.get("kind") == kind
            and Action[self.entity.permissions.get(details_item["hash"])].implies(
                action
            )
        )

    def _pages_by_category(self, details):
        pages = {}
        for item in details.values():
            if item.get("kind") != "page":
                continue
            for parent_hash in item.get("requires", []):
                pages.setdefault(parent_hash, []).append(item["hash"])
        return {key: sorted(value) for key, value in pages.items()}

    @staticmethod
    def _page_restrictions(models):
        return ["models"] if Restriction.is_unrestricted(models) else models

    def _task_restrictions(self, can_view_models):
        if self.entity.is_owner:
            return Restriction.UNRESTRICTED
        if can_view_models:
            return ["models"]
        return self._sorted_hashes(self._value_details, "page", "category")

    def _ai_action_capabilities(self):
        self._ensure_loaded()
        self._ensure_permission_details()
        can_create_models = self.entity.has_permission(Resource.MODELS, Action.CREATE)
        can_edit_models = self.entity.has_permission(Resource.MODELS, Action.EDIT)
        can_create_forms = self.entity.has_permission(Resource.FORMS, Action.CREATE)
        can_create_pages = self._has_access(self.category_edit_restrictions)
        can_edit_categories = can_edit_models or self._has_access(
            self.category_edit_restrictions
        )
        can_edit_pages = (
            can_edit_models
            or can_edit_categories
            or self._has_permission_kind(self._permission_details, "page", Action.EDIT)
        )
        can_edit_projects = can_edit_models or self._has_permission_kind(
            self._permission_details, "project", Action.EDIT
        )
        can_edit_tasks = can_edit_models or self._has_permission_kind(
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
            "can_create_tasks": can_edit_pages or can_create_pages,
            "can_attach_files_to_pages": can_edit_pages or can_create_pages,
            "can_attach_files_to_tasks": can_edit_tasks or can_edit_pages,
            "can_move_pages": can_edit_pages and can_edit_categories,
            "can_move_tasks": can_edit_tasks and can_edit_pages,
            "can_move_files": can_edit_pages or can_edit_tasks,
            "can_rename_entities": any(
                (
                    can_edit_models,
                    can_edit_forms,
                    can_edit_categories,
                    can_edit_pages,
                    can_edit_projects,
                    can_edit_tasks,
                )
            ),
            "can_update_form_schemas": can_edit_forms,
            "can_update_submissions": can_edit_pages or can_edit_tasks,
            "can_delete_pages": (
                can_delete_categories
                or self._has_permission_kind(
                    self._permission_details,
                    "page",
                    Action.DELETE,
                )
            ),
            "can_summarize_report_files": True,
        }

    def _ensure_permission_details(self):
        if self._permission_details or not self.entity.permissions:
            return
        permission_hashes = list(self.entity.permissions.keys())
        self._permission_details = (
            cache.get_details_by_hash(permission_hashes) if permission_hashes else {}
        )

    def _has_permission_kind(self, details, kind, action):
        for item in details.values():
            if item.get("kind") != kind:
                continue
            level = Action[self.entity.permissions.get(item.get("hash"))]
            if level.implies(action):
                return True
        return False

    def _create(self):
        if self.entity.is_owner:
            restricted_to = ["forms", "models", "users"]
            belongs_to = ["owner"]
        else:
            restricted_to = [
                h
                for h in self.entity.permissions
                if Action[self.entity.permissions[h]] != Action.RESTRICTED
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
            "belongs_to": belongs_to,
            "search": Restriction.UNRESTRICTED if self.entity.is_owner else value,
            "task": task,
            "form": form,
            "project": project,
            "models": models,
            "page": page,
            "user_assign": user_assign,
            "category_edit": category_edit,
            "users": users,
            "category": category,
            "pages_by_category": self._pages_by_category(self._value_details),
        }
        self._save_state()
