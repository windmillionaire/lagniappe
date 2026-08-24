from flask_login import current_user

from ..definitions import Action, EntityAttributes, Fetch
from ..entities import Entities
from ..tools import database
from .base_property import UNSET


# @testable infrastructure
class HomeProperty:
    """Base class for home page list sections.

    Each section (projects, categories, tasks, starred) is a paginated
    list with an HTML template renderer. Subclasses define ``list``
    to load their entities.
    """

    _id = "home"

    def __init__(self, *args, **kwargs):
        self._cursor = kwargs.get("cursor")
        self._back = True if self._cursor else False

    @property
    def id(self):
        return self._id

    @property
    def value(self):
        return self

    @property
    def label(self):
        return self._label

    @property
    def back(self):
        return self._back

    @property
    def cursor(self):
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        self._cursor = value

    @property
    def list(self):
        return getattr(self, "_list", UNSET)


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_project_list_restrictions_and_cursor
# @features home
# @dimensions projects pagination restrictions
class ProjectList(HomeProperty):
    _id = "projects"
    _label = "Projects"
    entity_kind = "project"

    @property
    def list(self):
        if super().list is not UNSET:
            return super().list

        hashes = current_user.properties.restrictions.project
        db = database.get.models(
            "project",
            start_cursor=self.cursor,
            hashes=hashes,
        )

        self._list = [Entities.PROJECT(p) for p in db.results]
        self.cursor = db.next_cursor

        return self._list

    @property
    def attributes(self):
        return EntityAttributes.project.initialize(self)


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_category_list_restrictions_and_cursor
# @features home
# @dimensions categories pagination restrictions
class CategoryList(HomeProperty):
    _id = "categories"
    _label = "Categories"
    entity_kind = "category"

    @property
    def list(self):
        if super().list is not UNSET:
            return super().list

        hashes = current_user.properties.restrictions.category
        db = database.get.models(
            "category",
            start_cursor=self.cursor,
            hashes=hashes,
        )
        self._list = Entities.fetch(*db.results, request=Fetch.direct())
        self.cursor = db.next_cursor

        return self._list

    @property
    def attributes(self):
        return EntityAttributes.category.initialize(self)


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_page_list_restrictions_and_cursor
# @features home pages
# @dimensions pagination restrictions
class PageList(HomeProperty):
    _id = "pages"
    _label = "Pages"

    @property
    def list(self):
        if super().list is not UNSET:
            return super().list

        hashes = current_user.properties.restrictions.page
        db = database.get.recent_pages(start_cursor=self.cursor, hashes=hashes)
        self._list = [
            page
            for page in Entities.fetch(*db.results, request=Fetch.direct())
            if page.allowed(Action.VIEW)
        ]
        self.cursor = db.next_cursor

        return self._list


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_task_list_restrictions_visibility_and_count
# @tests tests_e2e/002_home/test_002h_home_permissions.py::test_home_task_list_shows_view_only_page_tasks_without_controls
# @tests tests_e2e/006_tasks/test_006c_task_index.py::test_assigned_tasks_on_hidden_page_appear_on_home_and_task_index
# @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_add_due_date
# @features home
# @dimensions tasks count permissions task-list view-only
# @pairs home:assignee-visibility task-assignment:home-list
# @pair tasks:inaccessible-backing-page
class TaskList(HomeProperty):
    _id = "tasks"
    _label = "Tasks"

    @property
    def list(self):
        if super().list is not UNSET:
            return super().list

        hashes = current_user.properties.restrictions.task
        tasks = database.get.due_tasks(
            hashes=hashes,
            assigned_to=current_user.page,
        )
        task_pages = [
            page_key
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
            if t.allowed(Action.VIEW)
        ]

        return self._list

    @property
    def count(self):
        return database.get.user_task_count(current_user.page)


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_starred_list_paginates_and_cleans_stale_keys
# @tests tests_unit/test_002i_home_properties.py::test_home_starred_list_hides_but_retains_inaccessible_keys
# @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_route_rejects_inaccessible_and_missing_targets
# @features starred
# @dimensions stale-cleanup pagination view-authorization retained-inaccessible
class StarredList(HomeProperty):
    _id = "starred"
    _label = "Starred"

    @property
    def list(self):
        if super().list is not UNSET:
            return super().list

        starred_keys = current_user.properties.starred.keys
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

        loaded_keys = {entity.key for entity in loaded}
        deleted = [s for s in starred if s not in loaded_keys]
        if deleted:
            current_user.properties.starred.delete_starred_keys(deleted)
            current_user.save()

        self._list = [
            entity
            for entity in loaded
            if entity.allowed(Action.VIEW, user=current_user)
        ]
        self._cursor = next_cursor
        return self._list

    @property
    def count(self):
        return len(current_user.properties.starred.keys)


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_note_ingress_and_tool_lists_load_database_entities
# @features home
# @dimensions notes
class NoteList(HomeProperty):
    _id = "notes"
    _label = "Notes"

    @property
    def list(self):
        if super().list is not UNSET:
            return super().list

        notes = database.get.notes(current_user)
        self._list = Entities.fetch(*notes, request=Fetch.direct())
        return self._list


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_note_ingress_and_tool_lists_load_database_entities
# @features home
# @dimensions ingress
class IngressList(HomeProperty):
    _id = "ingress"
    _label = "Import Data"

    @property
    def list(self):
        if super().list is not UNSET:
            return super().list

        files = database.get.ingress_files()
        self._list = Entities.fetch(*files, request=Fetch.direct())
        return self._list


# @testable true
# @tests tests_unit/test_002i_home_properties.py::test_home_note_ingress_and_tool_lists_load_database_entities
# @features home ai-report
# @dimensions list
class ToolsList(HomeProperty):
    _id = "tools"
    _label = "Tools"

    @property
    def list(self):
        if super().list is not UNSET:
            return super().list

        reports = database.get.ai_reports(current_user)
        self._list = Entities.fetch(*reports, request=Fetch.direct())
        return self._list
