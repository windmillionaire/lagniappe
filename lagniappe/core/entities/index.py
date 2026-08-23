from flask import url_for

from ..definitions import Action, Restriction, Fetch
from ..entities import Entities
from ..properties import category, index
from ..tools import cache, database
from ..tools.auth.context import current_context_user
from ..tools.tasks.ordering import sort_tasks
from .site import Site


# @testable true
# @tests tests_unit/test_010_task_index.py::test_index_base_cursor_limit_user_and_append_state
# @features index
# @dimensions pagination state user-scope
class Index(Site):
    """Paginated list view for an entity type. Provides cursor-based
    pagination, user-scoped permission filtering, and table column config.
    """

    _route = None
    _append = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cursor = kwargs.get("cursor")
        self._limit = kwargs.get("limit", 25)
        self._user = current_context_user(kwargs.get("user"))

    @property
    def append(self):
        return self._append

    @append.setter
    def append(self, value):
        self._append = value

    @property
    def user(self):
        return self._user

    @user.setter
    def user(self, value):
        self._user = value

    @property
    def cursor(self):
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        self._cursor = value

    @property
    def limit(self):
        return self._limit

    @limit.setter
    def limit(self, value):
        self._limit = value


# @testable true
# @tests tests_unit/test_010_task_index.py::test_task_index
# @features task-index
# @dimensions table
class TaskIndex(Index):
    """Task list view for a project or global task index.

    Pagination uses two Datastore queries in order (due-dated tasks first, then
    tasks with no due date). The ``undated`` query param marks the second
    stream: cursors from the first query are invalid for the second, so load-more
    URLs include ``undated=1`` when switching.
    """

    _kind = "task"
    _tasks = None

    # @testable true
    # @tests tests_unit/test_010_task_index.py::test_task_index_paginates_dated_then_undated_tasks_with_restrictions
    # @tests tests_e2e/006_tasks/test_006c_task_index.py::test_assigned_tasks_on_hidden_page_appear_on_home_and_task_index
    # @features task-index
    # @dimensions restrictions
    # @pair task-index:assignee-visibility
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._undated = bool(kwargs.get("undated"))
        self._project = (
            self.entity if isinstance(self.entity, Entities.PROJECT) else None
        )
        self._restrictions = self.user.properties.restrictions.task
        self._assigned_to = self.user.page if self._project is None else None

    def _get_properties(self):
        return {
            "table": index.TaskTable,
        }

    @property
    def route(self):
        return url_for("tasks.rows")

    # @testable true
    # @tests tests_unit/test_010_task_index.py::test_task_index_paginates_dated_then_undated_tasks_with_restrictions
    # @tests tests_e2e/006_tasks/test_006c_task_index.py::test_assigned_tasks_on_hidden_page_appear_on_home_and_task_index
    # @features task-index
    # @dimensions pagination undated restrictions
    def undated_tasks(self):
        db = database.get.tasks_without_due_dates(
            start_cursor=self.cursor,
            limit=self.limit,
            project=self._project,
            hashes=self._restrictions,
            assigned_to=self._assigned_to,
        )
        self.cursor = db.next_cursor
        self.append = (
            url_for("tasks.rows", cursor=self.cursor, undated=1)
            if self.cursor
            else False
        )

        return [
            task
            for task in Entities.fetch(*db.results, request=Fetch.direct())
            if task.allowed(Action.VIEW)
        ]

    # @testable true
    # @tests tests_unit/test_010_task_index.py::test_task_index_paginates_dated_then_undated_tasks_with_restrictions
    # @tests tests_e2e/006_tasks/test_006c_task_index.py::test_assigned_tasks_on_hidden_page_appear_on_home_and_task_index
    # @features task-index
    # @dimensions pagination dated undated restrictions
    def dated_tasks(self):
        db = database.get.tasks_with_due_dates(
            start_cursor=self.cursor,
            limit=self.limit,
            project=self._project,
            hashes=self._restrictions,
            assigned_to=self._assigned_to,
        )
        if not db.results:
            return self.undated_tasks()
        self.cursor = db.next_cursor
        if self.cursor:
            self.append = url_for("tasks.rows", cursor=self.cursor)
        else:
            self.append = url_for("tasks.rows", undated=1)
        return [
            task
            for task in Entities.fetch(*db.results, request=Fetch.direct())
            if task.allowed(Action.VIEW)
        ]

    # @testable true
    # @tests tests_unit/test_010_task_index.py::test_task_index_paginates_dated_then_undated_tasks_with_restrictions
    # @features task-index
    # @dimensions pagination
    @property
    def tasks(self):
        if self._tasks is not None:
            return self._tasks

        if self._undated:
            self._tasks = self.undated_tasks()
        else:
            self._tasks = self.dated_tasks()

        return self._tasks

    # @testable true
    # @tests tests_unit/test_021_refresh.py::test_task_index_refresh_roots_uses_both_ordered_query_streams
    # @features reconnect-refresh task-index
    # @dimensions root-depth ordering
    def refresh_roots(self):
        """Return the complete task-index membership without relationships.

        Refresh intentionally reruns the normal dated and undated query recipes.
        Permission checks happen only after a changed root is expanded by the
        refresh reconciler; the root pass owns membership, order, and modified
        timestamps.
        """
        dated = database.get.tasks_with_due_dates(
            limit=None,
            project=self._project,
            hashes=self._restrictions,
            assigned_to=self._assigned_to,
        )
        undated = database.get.tasks_without_due_dates(
            limit=None,
            project=self._project,
            hashes=self._restrictions,
            assigned_to=self._assigned_to,
        )
        roots = Entities.fetch(
            *dated.results,
            *undated.results,
            request=Fetch.root(),
        )
        return sort_tasks([task for task in roots if isinstance(task, Entities.TASK)])


# @testable false
# @covered-by lagniappe/core/properties/index.py::TaskHistoryTable
# @reason table property owns task history list rendering; this entity only selects the table property
class TaskHistoryIndex(Index):
    """Task history list view for a task."""

    _kind = "task"

    def _get_properties(self):
        return {
            "table": index.TaskHistoryTable,
        }


# @testable false
# @covered-by lagniappe/core/entities/index.py::PageIndex.pages
# @reason page index query/filter behavior is owned by the pages property
class PageIndex(Index):
    """Page list view for a category."""

    _kind = "page"
    _pages = None

    def _get_properties(self):
        return {
            "table": category.CategoryTable,
        }

    @property
    def route(self):
        return url_for("categories.rows", key=self.entity.urlsafe_key)

    # @testable true
    # @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_restricted_page_is_not_listed_for_outsider_on_category_index
    # @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_renders_first_batch_before_cursor_continuation
    # @features pages
    # @dimensions access-restrictions index-filter cursor-pagination
    # @pair pages:access-restrictions
    # @pair pages:index-filter
    # @pair pages:cursor-pagination
    @property
    def pages(self):
        if self._pages is not None:
            return self._pages

        restrictions = self.user.properties.restrictions.unrestricted_pages(self.entity)
        limit = self.limit if not self.cursor else None

        db = database.get.pages(
            self.entity.key,
            start_cursor=self.cursor,
            limit=limit,
            hashes=restrictions,
        )
        self.cursor = db.next_cursor

        self._pages = [
            page
            for page in Entities.fetch(*db.results, request=Fetch.direct())
            if page.allowed(Action.VIEW)
        ]

        self.append = (
            url_for("categories.rows", key=self.entity.urlsafe_key, cursor=self.cursor)
            if self.cursor
            else None
        )

        return self._pages

    # @testable true
    # @tests tests_unit/test_021_refresh.py::test_page_index_refresh_roots_reuses_restricted_collection_query
    # @features reconnect-refresh category-index
    # @dimensions root-depth membership
    def refresh_roots(self):
        """Return every page in this category at root depth."""
        restrictions = self.user.properties.restrictions.unrestricted_pages(self.entity)
        db = database.get.pages(
            self.entity.key,
            limit=None,
            hashes=restrictions,
        )
        return [
            page
            for page in Entities.fetch(*db.results, request=Fetch.root())
            if isinstance(page, Entities.PAGE)
        ]


# @testable false
# @covered-by lagniappe/core/entities/index.py::FormIndex.forms
# @reason form index behavior is owned by the forms collection property
class FormIndex(Index):
    """Form list view with related category/project resolution."""

    _kind = "form"
    _forms = None

    def _get_properties(self):
        return {
            "table": index.FormTable,
        }

    @property
    def route(self):
        return url_for("forms.rows")

    # @testable true
    # @tests tests_e2e/003_forms/test_003c_access_restrictions.py::test_form_index_lists_group_restricted_form_only_for_group_member
    # @tests tests_e2e/003_forms/test_003d_form_permissions.py::test_form_index_lists_forms_but_hides_create_without_forms_create
    # @features forms
    # @dimensions index-view index-filter
    @property
    def forms(self):
        if self._forms is not None:
            return self._forms

        hashes = self.user.properties.restrictions.form

        if not Restriction.is_unrestricted(hashes):
            self._forms = []
            return self._forms

        db = database.get.forms(start_cursor=self.cursor, limit=self.limit)
        form_users = database.get.form_users(*db.results)
        entities = Entities.fetch(*db.results, *form_users, request=Fetch.direct())

        self._forms = [
            e
            for e in entities
            if isinstance(e, Entities.FORM)
            and not e.db.get("reserved")
            and e.allowed(Action.VIEW)
        ]

        loaded_categories = [e for e in entities if isinstance(e, Entities.CATEGORY)]
        loaded_model_tasks = [e for e in entities if isinstance(e, Entities.MODEL_TASK)]

        for f in self._forms:
            f.categories = [
                e
                for e in loaded_categories
                if (e.form and e.form.key == f.key)
                or f.key in e.properties.forms.keys
                and e.allowed(Action.VIEW)
            ]
            f.projects = [
                p
                for p in {
                    e.project.key: e.project
                    for e in loaded_model_tasks
                    if e.project and e.form and e.form.key == f.key
                }.values()
                if p.allowed(Action.VIEW)
            ]

        self.cursor = db.next_cursor
        self.append = url_for("forms.rows", cursor=self.cursor) if self.cursor else None

        return self._forms


# @testable true
# @tests tests_unit/test_009_user_index.py::test_user_index
# @features user-index
# @dimensions table
class UserIndex(Index):
    """User list view with group management."""

    _kind = "user"
    _users = None
    _regular_mode = "regular"
    _public_mode = "public"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mode = (
            self._public_mode
            if kwargs.get("mode") == self._public_mode
            else self._regular_mode
        )

    def _get_properties(self):
        return {
            "table": index.UserTable,
        }

    @property
    def route(self):
        if self.mode == self._public_mode:
            return url_for("users.rows", mode=self._public_mode)
        return url_for("users.rows")

    # @testable true
    # @tests tests_unit/test_009_user_index.py::test_user_index_loads_users_groups_public_group_and_append_cursor
    # @tests tests_unit/test_009_user_index.py::test_user_index_regular_mode_excludes_public_users
    # @tests tests_unit/test_009_user_index.py::test_user_index_public_mode_loads_public_group_users_and_preserves_append_mode
    # @tests tests_unit/test_009_user_index.py::test_user_index_public_mode_returns_empty_when_public_users_disabled
    # @pair user-index:pagination
    # @pair user-index:restrictions
    # @pair user-index:public-users
    # @pair user-index:mode
    # @pair user-index:regular-mode
    # @pair user-index:public-mode
    # @pair public-users:mode
    # @pair public-users:pagination
    # @pair public-users:public-mode
    @property
    def users(self):
        if self._users is not None:
            return self._users

        if self.mode == self._public_mode:
            return self._load_public_users()

        return self._load_regular_users()

    # @testable false
    # @covered-by lagniappe/core/entities/index.py::UserIndex.users
    # @reason helper keeps mode-specific query paths readable
    def _load_regular_users(self):
        restrictions = self.user.properties.restrictions.users

        db = database.get.users(
            start_cursor=self.cursor, hashes=restrictions, limit=self.limit
        )
        self._users = [
            u
            for u in Entities.fetch(*db.results, request=Fetch.direct())
            if not u.is_public and u.allowed(Action.VIEW, self.user)
        ]
        self.cursor = db.next_cursor

        self.append = url_for("users.rows", cursor=self.cursor) if self.cursor else None

        return self._users

    # @testable false
    # @covered-by lagniappe/core/entities/index.py::UserIndex.users
    # @reason helper keeps mode-specific query paths readable
    def _load_public_users(self):
        if not self.public_users_enabled:
            self._users = []
            return self._users

        db = database.get.users(
            start_cursor=self.cursor,
            group=self.public_group.key,
            limit=self.limit,
        )
        self._users = [
            u
            for u in Entities.fetch(*db.results, request=Fetch.direct())
            if u.is_public and u.allowed(Action.VIEW, self.user)
        ]
        self.cursor = db.next_cursor

        self.append = (
            url_for("users.rows", cursor=self.cursor, mode=self._public_mode)
            if self.cursor
            else None
        )

        return self._users

    # @testable true
    # @tests tests_unit/test_021_refresh.py::test_user_index_refresh_roots_preserves_regular_and_public_modes
    # @features reconnect-refresh user-index
    # @dimensions root-depth mode
    def refresh_roots(self):
        """Return the selected user-index mode without relationship expansion."""
        if self.mode == self._public_mode:
            if not self.public_users_enabled:
                return []
            db = database.get.users(
                group=self.public_group.key,
                limit=None,
            )
            expected_public = True
        else:
            db = database.get.users(
                hashes=self.user.properties.restrictions.users,
                limit=None,
            )
            expected_public = False

        return [
            user
            for user in Entities.fetch(*db.results, request=Fetch.root())
            if isinstance(user, Entities.USER)
            and bool(user.is_public) is expected_public
            and user.allowed(Action.VIEW, self.user)
        ]

    @property
    def mode(self):
        return self._mode

    # @testable true
    # @tests tests_unit/test_009_user_index.py::test_user_index_public_mode_returns_empty_when_public_users_disabled
    # @features user-index
    # @dimensions public-users enabled
    @property
    def public_users_enabled(self):
        if getattr(self, "_public_users_enabled", None) is not None:
            return self._public_users_enabled

        self._public_users_enabled = Entities.PUBLIC_GROUP.enabled()

        return self._public_users_enabled

    # @testable true
    # @tests tests_unit/test_009_user_index.py::test_user_index_loads_users_groups_public_group_and_append_cursor
    # @features user-index
    # @dimensions restrictions groups
    @property
    def groups(self):
        if getattr(self, "_groups", None):
            return self._groups

        restrictions = self.user.properties.restrictions.users
        if Restriction.is_unrestricted(restrictions):
            groups = database.get.groups(hashes=restrictions)
        else:
            restricted = cache.get_details_by_hash(restrictions)
            allowed_groups = {
                g["id"] for g in restricted.values() if g["kind"] == "group"
            }
            groups = database.get.groups(hashes=sorted(allowed_groups))

        self._groups = [
            g
            for g in Entities.fetch(*groups, request=Fetch.direct())
            if isinstance(g, Entities.USER_GROUP) and g.allowed(Action.VIEW)
        ]

        return self._groups

    # @testable true
    # @tests tests_unit/test_009_user_index.py::test_user_index_loads_users_groups_public_group_and_append_cursor
    # @features user-index
    # @dimensions public-group
    @property
    def public_group(self):
        if getattr(self, "_public_group", None) is not None:
            return self._public_group

        self._public_group = Entities.PUBLIC_GROUP.get()

        return self._public_group
