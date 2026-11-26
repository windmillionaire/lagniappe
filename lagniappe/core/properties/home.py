from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.user import User

from ..definitions import Action, Fetch
from ..entities import Entities
from lagniappe.core.tools.database import get as database_get
from .base_property import UNSET


class HomeProperty[Cursor: str | int = str]:
    """Base class for home page list sections.

    Each section (projects, categories, tasks, starred) is a paginated
    list with an HTML template renderer. Subclasses define ``list``
    to load their entities.
    """

    _id = "home"
    _label: str
    _list: list[Entity]

    def __init__(self, *args: object, user: User, cursor: Cursor | None = None, **kwargs: object) -> None:
        if user is None:
            raise ValueError("Home section requires a user")
        self._user = user
        self._cursor = cursor
        self._back = bool(self._cursor)

    @property
    def id(self) -> str:
        return self._id

    @property
    def value(self) -> Self:
        return self

    @property
    def label(self) -> str:
        return self._label

    @property
    def back(self) -> bool:
        return self._back

    @property
    def cursor(self) -> Cursor | None:
        return self._cursor

    @cursor.setter
    def cursor(self, value: Cursor | None) -> None:
        self._cursor = value

    @property
    def list(self) -> object:
        return getattr(self, "_list", UNSET)


class ProjectList(HomeProperty):
    _id = "projects"
    _label = "Projects"
    entity_kind = "project"

    @property
    def list(self) -> list[Entity]:
        if super().list is not UNSET:
            return self._list

        hashes = self._user.properties.restrictions.project
        db = database_get.models(
            "project",
            start_cursor=self.cursor,
            hashes=hashes,
        )

        self._list = [Entities.PROJECT(p) for p in db.results]
        self.cursor = db.next_cursor

        return self._list

class CategoryList(HomeProperty):
    _id = "categories"
    _label = "Categories"
    entity_kind = "category"

    @property
    def list(self) -> list[Entity]:
        if super().list is not UNSET:
            return self._list

        hashes = self._user.properties.restrictions.category
        db = database_get.models(
            "category",
            start_cursor=self.cursor,
            hashes=hashes,
        )
        self._list = Entities.fetch(*db.results, request=Fetch.root())
        self.cursor = db.next_cursor

        return self._list

class PageList(HomeProperty):
    _id = "pages"
    _label = "Pages"

    @property
    def list(self) -> list[Entity]:
        if super().list is not UNSET:
            return self._list

        hashes = self._user.properties.restrictions.page
        db = database_get.recent_pages(start_cursor=self.cursor, hashes=hashes)
        self._list = [
            page
            for page in Entities.fetch(*db.results, request=Fetch.direct())
            if page.allowed(Action.VIEW, user=self._user)
        ]
        self.cursor = db.next_cursor

        return self._list


class TaskList(HomeProperty):
    _id = "tasks"
    _label = "Tasks"

    @property
    def list(self) -> list[Entity]:
        if super().list is not UNSET:
            return self._list

        hashes = self._user.properties.restrictions.task
        viewer_page = self._user.page
        tasks = database_get.due_tasks(
            hashes=hashes,
            assigned_to=viewer_page,
        )
        task_pages = [
            viewer_page if viewer_page and page_key == viewer_page.key else page_key
            for task in tasks
            if (page_key := getattr(task, "db", task).get("page"))
        ]
        self._list = [
            t
            # Task permission checks inherit restrictions from both the Task's
            # Form and its parent Page's Form. Treat the Pages as direct roots
            # so routine list rendering does not require a nested request.
            for t in Entities.fetch(*tasks, *task_pages, request=Fetch.direct())
            if getattr(t, "kind", None) == "task"
            if t.allowed(Action.VIEW, user=self._user)
        ]

        return self._list

    @property
    def count(self) -> int:
        return database_get.user_task_count(self._user.page)


class StarredList(HomeProperty[str | int]):
    _id = "starred"
    _label = "Starred"

    @property
    def list(self) -> list[Entity]:
        if super().list is not UNSET:
            return self._list

        starred_keys = self._user.properties.starred.keys
        cursor = int(self.cursor) if self.cursor else 0

        if not self.cursor:
            starred = starred_keys[:10]
            next_cursor = 1 if len(starred_keys) > 10 else None
        elif len(starred_keys) > cursor * 10:
            starred = starred_keys[cursor * 10 : (cursor + 1) * 10]
            next_cursor = cursor + 1 if len(starred_keys) > (cursor + 1) * 10 else None
        else:
            starred = []
            next_cursor = None

        loaded = Entities.fetch(*starred, request=Fetch.direct())

        loaded_by_key = {entity.key: entity for entity in loaded}
        self._list = []
        self._items: list[dict[str, object]] = []
        for key in starred:
            entity = loaded_by_key.get(key)
            urlsafe_key = database_get.urlsafe_key(key)
            if entity is None:
                item: dict[str, object] = {
                    "key": urlsafe_key,
                    "state": "missing",
                    "message": "This starred item no longer exists.",
                }
                self._items.append(item)
            elif entity.allowed(Action.VIEW, user=self._user):
                self._list.append(entity)
                self._items.append({"entity": entity, "key": urlsafe_key})
            else:
                kind = str(getattr(entity, "kind", None) or "item").replace(
                    "_", " "
                )
                item = {
                    "key": urlsafe_key,
                    "state": "inaccessible",
                    "message": f"This {kind} is no longer accessible.",
                }
                self._items.append(item)
        self._cursor = next_cursor
        return self._list

    @property
    def items(self) -> list[dict[str, object]]:
        if super().list is UNSET:
            _ = self.list
        return self._items

    @property
    def count(self) -> int:
        return len(self._user.properties.starred.keys)


class NoteList(HomeProperty):
    _id = "notes"
    _label = "Notes"

    @property
    def list(self) -> list[Entity]:
        if super().list is not UNSET:
            return self._list

        notes = database_get.notes(self._user)
        self._list = Entities.fetch(*notes, request=Fetch.direct())
        return self._list


class IngressList(HomeProperty):
    _id = "ingress"
    _label = "Import Data"

    @property
    def list(self) -> list[Entity]:
        if super().list is not UNSET:
            return self._list

        files = database_get.ingress_files()
        self._list = Entities.fetch(*files, request=Fetch.direct())
        return self._list


class ToolsList(HomeProperty):
    _id = "tools"
    _label = "Plans & Reports"

    @property
    def list(self) -> list[Entity]:
        if super().list is not UNSET:
            return self._list

        db = database_get.ai_reports(self._user, start_cursor=self.cursor)
        self._list = Entities.fetch(*db.results, request=Fetch.direct())
        self.cursor = db.next_cursor
        return self._list
