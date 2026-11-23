from collections.abc import Mapping
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

from flask import url_for

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..restrictions import QueryHashes
    from .category import Category
    from .entity import Entity
    from .form import Form
    from .group import PublicGroup, UserGroup
    from .page import Page
    from .task import Task
    from .user import User

from ..definitions import Action, Restriction, Fetch, FetchReason
from ..entities import Entities
from ..properties import category, index
from ..tools import cache
from lagniappe.core.tools.database import get as database_get
from ..tools.auth.context import current_context_user
from ..tools.tasks.ordering import sort_tasks
from .site import Site


class CollectionOptions(TypedDict, total=False):
    cursor: str | None
    limit: int | None
    user: User | None


class IndexOptions(CollectionOptions, total=False):
    entity: Entity | None


class Index(Site):
    """Paginated list view for an entity type. Provides cursor-based
    pagination, user-scoped permission filtering, and table column config.
    """

    _route = None
    _append: str | bool | None = False

    def __init__(
        self, *args: object, cursor: str | None = None, limit: int | None = 25,
        user: User | None = None, entity: Entity | None = None, **kwargs: object,
    ) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self._cursor = cursor
        self._limit = limit
        self._user = current_context_user(user)

    @property
    def append(self) -> str | bool | None:
        return self._append

    @append.setter
    def append(self, value: str | bool | None) -> None:
        self._append = value

    @property
    def user(self) -> User | None:
        return self._user

    @user.setter
    def user(self, value: User | None) -> None:
        self._user = value

    @property
    def _viewer(self) -> User:
        if self.user is None:
            raise AttributeError("This index requires a viewer")
        return self.user

    @property
    def cursor(self) -> str | None:
        return self._cursor

    @cursor.setter
    def cursor(self, value: str | None) -> None:
        self._cursor = value

    @property
    def limit(self) -> int | None:
        return self._limit

    @limit.setter
    def limit(self, value: int | None) -> None:
        self._limit = value


class TaskIndex(Index):
    """Task list view for a project or global task index.

    Pagination uses two Datastore queries in order (due-dated tasks first, then
    tasks with no due date). The ``undated`` query param marks the second
    stream: cursors from the first query are invalid for the second, so load-more
    URLs include ``undated=1`` when switching.
    """

    if TYPE_CHECKING:
        table: index.TaskTable

    _kind = "task"
    _tasks: list[Task] | None = None

    def __init__(self, *args: object, undated: bool = False, **kwargs: Unpack[IndexOptions]) -> None:
        super().__init__(*args, **kwargs)
        self._undated = bool(undated)
        owner = self.entity
        self._project = owner if isinstance(owner, Entities.PROJECT) else None
        self._restrictions: QueryHashes = self._viewer.properties.restrictions.task
        self._assigned_to = self._viewer.page if self._project is None else None

    def _get_properties(self) -> dict[str, type[index.TaskTable]]:
        return {
            "table": index.TaskTable,
        }

    @property
    def route(self) -> str:
        return url_for("tasks.rows")

    def undated_tasks(self) -> list[Task]:
        db = database_get.tasks_without_due_dates(
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
            cast("Task", task)
            for task in Entities.fetch(
                *db.results,
                request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
            )
            if task.allowed(Action.VIEW, user=self.user)
        ]

    def dated_tasks(self) -> list[Task]:
        db = database_get.tasks_with_due_dates(
            start_cursor=self.cursor,
            limit=self.limit,
            project=self._project,
            hashes=self._restrictions,
            assigned_to=self._assigned_to,
        )
        if not db.results:
            self.cursor = None  # The undated query has its own cursor space.
            return self.undated_tasks()
        self.cursor = db.next_cursor
        if self.cursor:
            self.append = url_for("tasks.rows", cursor=self.cursor)
        else:
            self.append = url_for("tasks.rows", undated=1)
        return [
            cast("Task", task)
            for task in Entities.fetch(
                *db.results,
                request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
            )
            if task.allowed(Action.VIEW, user=self.user)
        ]

    @property
    def tasks(self) -> list[Task]:
        if self._tasks is not None:
            return self._tasks

        if self._undated:
            self._tasks = self.undated_tasks()
        else:
            self._tasks = self.dated_tasks()

        return self._tasks

    def refresh_roots(self) -> list[Task]:
        """Return the complete task-index membership without relationships.

        Refresh intentionally reruns the normal dated and undated query recipes.
        Permission checks happen only after a changed root is expanded by the
        refresh reconciler; the root pass owns membership, order, and modified
        timestamps.
        """
        dated = database_get.tasks_with_due_dates(
            limit=None,
            project=self._project,
            hashes=self._restrictions,
            assigned_to=self._assigned_to,
        )
        undated = database_get.tasks_without_due_dates(
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


class TaskHistoryIndex(Index):
    """Task history list view for a task."""

    if TYPE_CHECKING:
        table: index.TaskHistoryTable

    _kind = "task"

    def _get_properties(self) -> dict[str, type[index.TaskHistoryTable]]:
        return {
            "table": index.TaskHistoryTable,
        }


class PageIndex(Index):
    """Page list view for a category."""

    if TYPE_CHECKING:
        table: category.CategoryTable

    _kind = "page"
    _pages: list[Page] | None = None

    @property
    def _category(self) -> Category:
        # Category.index registers this index with its category as owner.
        return cast("Category", self.entity)

    def _get_properties(self) -> dict[str, type[category.CategoryTable]]:
        return {
            "table": category.CategoryTable,
        }

    @property
    def route(self) -> str:
        return url_for("categories.rows", key=self._category.urlsafe_key)

    @property
    def pages(self) -> list[Page]:
        if self._pages is not None:
            return self._pages

        restrictions = self._viewer.properties.restrictions.unrestricted_pages(self._category)
        limit = self.limit if not self.cursor else None

        # Saved category indexes always use the paginated database result.
        db = database_get.pages(
            cast("Key", self._category.key),
            start_cursor=self.cursor,
            limit=limit,
            hashes=restrictions,
        )
        self.cursor = db.next_cursor

        self._pages = [
            cast("Page", page)
            for page in Entities.fetch(*db.results, request=Fetch.direct())
            if page.allowed(Action.VIEW, user=self.user)
        ]

        self.append = (
            url_for("categories.rows", key=self._category.urlsafe_key, cursor=self.cursor)
            if self.cursor
            else None
        )

        return self._pages

    def refresh_roots(self) -> list[Page]:
        """Return every page in this category at root depth."""
        restrictions = self._viewer.properties.restrictions.unrestricted_pages(self._category)
        # Saved category indexes always use the paginated database result.
        db = database_get.pages(
            cast("Key", self._category.key),
            limit=None,
            hashes=restrictions,
        )
        return [
            page
            for page in Entities.fetch(*db.results, request=Fetch.root())
            if isinstance(page, Entities.PAGE)
        ]


class FormIndex(Index):
    """Form list view with related category/project resolution."""

    if TYPE_CHECKING:
        table: index.FormTable

    _kind = "form"
    _forms: list[Form] | None = None

    def _get_properties(self) -> dict[str, type[index.FormTable]]:
        return {
            "table": index.FormTable,
        }

    @property
    def route(self) -> str:
        return url_for("forms.rows")

    @property
    def forms(self) -> list[Form]:
        if self._forms is not None:
            return self._forms

        hashes = self._viewer.properties.restrictions.form

        if not Restriction.is_unrestricted(hashes):
            self._forms = []
            return self._forms

        db = database_get.forms(start_cursor=self.cursor, limit=self.limit)
        form_users = database_get.form_users(*db.results)
        entities = Entities.fetch(*db.results, *form_users, request=Fetch.direct())

        self._forms = [
            e
            for e in entities
            if isinstance(e, Entities.FORM)
            and not e.db.get("reserved")
            and e.allowed(Action.VIEW, user=self.user)
        ]

        loaded_categories = [e for e in entities if isinstance(e, Entities.CATEGORY)]
        loaded_model_tasks = [e for e in entities if isinstance(e, Entities.MODEL_TASK)]

        for f in self._forms:
            f.categories = [
                e
                for e in loaded_categories
                if (e.form and e.form.key == f.key)
                or f.key in e.properties.forms.keys
                and e.allowed(Action.VIEW, user=self.user)
            ]
            f.projects = [
                p
                for p in {
                    e.project.key: e.project
                    for e in loaded_model_tasks
                    if e.project and e.form and e.form.key == f.key
                }.values()
                if p.allowed(Action.VIEW, user=self.user)
            ]

        self.cursor = db.next_cursor
        self.append = url_for("forms.rows", cursor=self.cursor) if self.cursor else None

        return self._forms


class UserIndex(Index):
    """User list view with group management."""

    if TYPE_CHECKING:
        table: index.UserTable

    _kind = "user"
    _users: list[User] | None = None
    _public_users_enabled: bool
    _regular_mode = "regular"
    _public_mode = "public"

    def __init__(self, *args: object, mode: str | None = None, **kwargs: Unpack[IndexOptions]) -> None:
        super().__init__(*args, **kwargs)
        self._mode = (
            self._public_mode
            if mode == self._public_mode
            else self._regular_mode
        )

    def _get_properties(self) -> dict[str, type[index.UserTable]]:
        return {
            "table": index.UserTable,
        }

    @property
    def route(self) -> str:
        if self.mode == self._public_mode:
            return url_for("users.rows", mode=self._public_mode)
        return url_for("users.rows")

    @property
    def users(self) -> list[User]:
        if self._users is not None:
            return self._users

        if self.mode == self._public_mode:
            return self._load_public_users()

        return self._load_regular_users()

    def _load_regular_users(self) -> list[User]:
        restrictions = self._viewer.properties.restrictions.users

        db = database_get.users(
            start_cursor=self.cursor, hashes=restrictions, limit=self.limit
        )
        self._users = [
            user
            for row in Entities.fetch(
                *db.results,
                request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
            )
            if not (user := cast("User", row)).is_public and user.allowed(Action.VIEW, self.user)
        ]
        self.cursor = db.next_cursor

        self.append = url_for("users.rows", cursor=self.cursor) if self.cursor else None

        return self._users

    def _load_public_users(self) -> list[User]:
        if not self.public_users_enabled:
            self._users = []
            return self._users

        db = database_get.users(
            start_cursor=self.cursor,
            group=self.public_group.key,
            limit=self.limit,
        )
        self._users = [
            user
            for row in Entities.fetch(
                *db.results,
                request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
            )
            if (user := cast("User", row)).is_public and user.allowed(Action.VIEW, self.user)
        ]
        self.cursor = db.next_cursor

        self.append = (
            url_for("users.rows", cursor=self.cursor, mode=self._public_mode)
            if self.cursor
            else None
        )

        return self._users

    def refresh_roots(self) -> list[Page]:
        """Return the Pages represented by authorized User rows at root depth."""
        if self.mode == self._public_mode:
            if not self.public_users_enabled:
                return []
            db = database_get.users(
                group=self.public_group.key,
                limit=None,
            )
            expected_public = True
        else:
            db = database_get.users(
                hashes=self._viewer.properties.restrictions.users,
                limit=None,
            )
            expected_public = False

        users = [
            user
            for user in Entities.fetch(*db.results, request=Fetch.root())
            if isinstance(user, Entities.USER)
            and bool(user.is_public) is expected_public
            and user.allowed(Action.VIEW, self.user)
        ]
        page_keys = [user.properties.page.key for user in users]
        pages = {
            page.key: page
            for page in Entities.fetch(*page_keys, request=Fetch.root())
            if isinstance(page, Entities.PAGE)
        }
        return [pages[key] for key in page_keys if key in pages]

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def public_users_enabled(self) -> bool:
        if getattr(self, "_public_users_enabled", None) is not None:
            return self._public_users_enabled

        self._public_users_enabled = Entities.PUBLIC_GROUP.enabled()

        return self._public_users_enabled

    @property
    def groups(self) -> list[UserGroup]:
        if cached := getattr(self, "_groups", None):
            return cached

        restrictions = self._viewer.properties.restrictions.users
        if Restriction.is_unrestricted(restrictions):
            groups = database_get.groups(hashes=restrictions)
        else:
            restricted = cache.get_details_by_hash(restrictions)
            allowed_groups = {
                detail["id"] for detail in cast("Mapping[str, Mapping[str, str]]", restricted).values()
                if detail["kind"] == "group"
            }
            groups = database_get.groups(hashes=sorted(allowed_groups))

        self._groups = [
            g
            for g in Entities.fetch(*groups, request=Fetch.direct())
            if isinstance(g, Entities.USER_GROUP) and g.allowed(Action.VIEW, user=self.user)
        ]

        return self._groups

    @property
    def public_group(self) -> PublicGroup:
        if getattr(self, "_public_group", None) is not None:
            return self._public_group

        self._public_group = Entities.PUBLIC_GROUP.get()

        return self._public_group
