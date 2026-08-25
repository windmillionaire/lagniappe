from types import SimpleNamespace

import pytest

import lagniappe.core.properties.home as home_properties


# @matrix ai-report home : pagination projects restrictions
@pytest.mark.unit
def test_home_project_list_restrictions_and_cursor(monkeypatch):
    user = SimpleNamespace(
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(project=("project-a", "project-b"))
        )
    )
    model_requests = []
    project_wrapped = []

    def get_models(kind, **kwargs):
        model_requests.append((kind, kwargs))
        return SimpleNamespace(results=["project-1", "project-2"], next_cursor="next-page")

    def wrap_project(model):
        project_wrapped.append(model)
        return SimpleNamespace(key=f"wrapped-{model}")

    monkeypatch.setattr(home_properties, "current_user", user)
    monkeypatch.setattr(home_properties.database.get, "models", get_models)
    monkeypatch.setattr(home_properties.Entities, "PROJECT", wrap_project)

    section = home_properties.ProjectList(cursor="start-page")
    projects = section.list

    assert model_requests == [
        (
            "project",
            {
                "start_cursor": "start-page",
                "hashes": ("project-a", "project-b"),
            },
        )
    ]
    assert project_wrapped == ["project-1", "project-2"]
    assert [project.key for project in projects] == [
        "wrapped-project-1",
        "wrapped-project-2",
    ]
    assert section.cursor == "next-page"
    assert section.back is True
    assert section.list is projects


# @matrix home : categories pagination restrictions
@pytest.mark.unit
def test_home_category_list_restrictions_and_cursor(monkeypatch):
    user = SimpleNamespace(
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(category=("category-a", "category-b"))
        )
    )
    model_requests = []
    fetch_requests = []
    categories = [
        SimpleNamespace(key="category-1"),
        SimpleNamespace(key="category-2"),
    ]

    def get_models(kind, **kwargs):
        model_requests.append((kind, kwargs))
        return SimpleNamespace(
            results=["category-1", "category-2"], next_cursor="category-next"
        )

    def fetch_categories(*models, request):
        fetch_requests.append((models, request))
        return categories

    monkeypatch.setattr(home_properties, "current_user", user)
    monkeypatch.setattr(home_properties.database.get, "models", get_models)
    monkeypatch.setattr(home_properties.Entities, "fetch", fetch_categories)

    section = home_properties.CategoryList(cursor="category-start")
    loaded_categories = section.list

    assert model_requests == [
        (
            "category",
            {
                "start_cursor": "category-start",
                "hashes": ("category-a", "category-b"),
            },
        )
    ]
    assert fetch_requests == [
        (("category-1", "category-2"), home_properties.Fetch.direct())
    ]
    assert loaded_categories == categories
    assert section.cursor == "category-next"
    assert section.back is True
    assert section.list is loaded_categories


# @matrix home pages : pagination restrictions
@pytest.mark.unit
def test_home_page_list_restrictions_and_cursor(monkeypatch):
    class FakePage:
        def __init__(self, key, visible):
            self.key = key
            self.visible = visible
            self.allowed_actions = []

        def allowed(self, action):
            self.allowed_actions.append(action)
            return self.visible

    user = SimpleNamespace(
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(page=("models", "page-a", "category-a"))
        )
    )
    page_requests = []
    load_requests = []
    pages = [
        FakePage("page-1", True),
        FakePage("page-2", False),
        FakePage("page-3", True),
    ]

    def recent_pages(**kwargs):
        page_requests.append(kwargs)
        return SimpleNamespace(results=["page-1", "page-2", "page-3"], next_cursor="p2")

    def load_entities(*keys, request):
        load_requests.append(keys)
        return pages

    monkeypatch.setattr(home_properties, "current_user", user)
    monkeypatch.setattr(home_properties.database.get, "recent_pages", recent_pages)
    monkeypatch.setattr(home_properties.Entities, "fetch", load_entities)

    section = home_properties.PageList(cursor="p1")
    visible_pages = section.list

    assert page_requests == [
        {
            "start_cursor": "p1",
            "hashes": ("models", "page-a", "category-a"),
        }
    ]
    assert load_requests == [("page-1", "page-2", "page-3")]
    assert visible_pages == [pages[0], pages[2]]
    assert [page.allowed_actions for page in pages] == [
        [home_properties.Action.VIEW],
        [home_properties.Action.VIEW],
        [home_properties.Action.VIEW],
    ]
    assert section.cursor == "p2"
    assert section.back is True
    assert section.list is visible_pages


# @matrix home : count permissions tasks view-only
@pytest.mark.unit
def test_home_task_list_restrictions_visibility_and_count(monkeypatch):
    class FakeTask:
        def __init__(self, key, visible):
            self.key = key
            self.kind = "task"
            self.visible = visible
            self.allowed_actions = []

        def allowed(self, action):
            self.allowed_actions.append(action)
            return self.visible

    user = SimpleNamespace(
        page="user-page",
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(task=("task-a", "task-b"))
        ),
    )
    due_requests = []
    load_requests = []
    count_requests = []
    tasks = [
        FakeTask("task-1", True),
        FakeTask("task-2", False),
        FakeTask("task-3", True),
    ]

    stored_tasks = [
        {"id": "task-1", "page": "page-1"},
        {"id": "task-2", "page": "page-2"},
        {"id": "task-3", "page": "page-3"},
    ]

    def due_tasks(**kwargs):
        due_requests.append(kwargs)
        return stored_tasks

    def load_entities(*keys, request):
        load_requests.append(keys)
        return tasks

    def user_task_count(page):
        count_requests.append(page)
        return 7

    monkeypatch.setattr(home_properties, "current_user", user)
    monkeypatch.setattr(home_properties.database.get, "due_tasks", due_tasks)
    monkeypatch.setattr(home_properties.Entities, "fetch", load_entities)
    monkeypatch.setattr(
        home_properties.database.get, "user_task_count", user_task_count
    )

    section = home_properties.TaskList()
    visible_tasks = section.list

    assert due_requests == [
        {
            "hashes": ("task-a", "task-b"),
            "assigned_to": "user-page",
        }
    ]
    assert load_requests == [
        (
            *stored_tasks,
            "page-1",
            "page-2",
            "page-3",
        )
    ]
    assert visible_tasks == [tasks[0], tasks[2]]
    assert [task.allowed_actions for task in tasks] == [
        [home_properties.Action.VIEW],
        [home_properties.Action.VIEW],
        [home_properties.Action.VIEW],
    ]
    assert section.list is visible_tasks
    assert section.count == 7
    assert count_requests == ["user-page"]


# @matrix starred : pagination stale-cleanup view-authorization
@pytest.mark.unit
def test_home_starred_list_paginates_and_cleans_stale_keys(monkeypatch):
    class FakeStarred:
        def __init__(self, keys):
            self.keys = list(keys)
            self.deleted = []

        def delete_starred_keys(self, keys):
            self.deleted.extend(keys)
            self.keys = [key for key in self.keys if key not in keys]

    class FakeUser:
        def __init__(self, starred):
            self.properties = SimpleNamespace(starred=starred)
            self.saved = False

        def save(self):
            self.saved = True

    starred_keys = [f"starred-{index}" for index in range(12)]
    stale_key = "starred-3"
    starred = FakeStarred(starred_keys)
    user = FakeUser(starred)
    loaded_requests = []

    class FakeEntity:
        def __init__(self, key, visible=True):
            self.key = key
            self.visible = visible
            self.allowed_requests = []

        def allowed(self, action, user=None):
            self.allowed_requests.append((action, user))
            return self.visible

    def load_entities(*keys, request):
        loaded_requests.append(keys)
        return [FakeEntity(key) for key in keys if key != stale_key]

    monkeypatch.setattr(home_properties, "current_user", user)
    monkeypatch.setattr(home_properties.Entities, "fetch", load_entities)

    section = home_properties.StarredList()
    loaded = section.list

    assert loaded_requests == [tuple(starred_keys[:10])]
    assert [entity.key for entity in loaded] == [
        key for key in starred_keys[:10] if key != stale_key
    ]
    assert starred.deleted == [stale_key]
    assert stale_key not in starred.keys
    assert section.cursor == 1
    assert section.count == 11
    assert user.saved is True
    assert all(
        entity.allowed_requests == [(home_properties.Action.VIEW, user)]
        for entity in loaded
    )


# @matrix starred : retained-inaccessible view-authorization
@pytest.mark.unit
def test_home_starred_list_hides_but_retains_inaccessible_keys(monkeypatch):
    class FakeEntity:
        def __init__(self, key, visible):
            self.key = key
            self.visible = visible

        def allowed(self, action, user=None):
            assert action is home_properties.Action.VIEW
            assert user is current_user
            return self.visible

    class FakeStarred:
        keys = ["visible", "restricted", "missing"]

        def __init__(self):
            self.deleted = []

        def delete_starred_keys(self, keys):
            self.deleted.extend(keys)
            self.keys = [key for key in self.keys if key not in keys]

    starred = FakeStarred()
    current_user = SimpleNamespace(
        properties=SimpleNamespace(starred=starred),
        save=lambda: None,
    )
    visible = FakeEntity("visible", True)
    restricted = FakeEntity("restricted", False)

    monkeypatch.setattr(home_properties, "current_user", current_user)
    monkeypatch.setattr(
        home_properties.Entities,
        "fetch",
        lambda *keys, request: [visible, restricted],
    )

    section = home_properties.StarredList()

    assert section.list == [visible]
    assert starred.deleted == ["missing"]
    assert starred.keys == ["visible", "restricted"]
    assert section.count == 2


# @matrix ai-report home : ingress list notes query tools
@pytest.mark.unit
def test_home_note_ingress_and_tool_lists_load_database_entities(monkeypatch):
    user = SimpleNamespace(email="owner@example.com")
    load_requests = []
    notes_requests = []
    ingress_requests = []
    ai_report_requests = []

    def get_notes(requested_user):
        notes_requests.append(requested_user)
        return ["note-1", "note-2"]

    def get_ingress_files():
        ingress_requests.append(True)
        return ["ingress-1"]

    def get_ai_reports(requested_user):
        ai_report_requests.append(requested_user)
        return ["report-1"]

    def load_entities(*keys, request):
        load_requests.append(keys)
        return [SimpleNamespace(key=key) for key in keys]

    monkeypatch.setattr(home_properties, "current_user", user)
    monkeypatch.setattr(home_properties.database.get, "notes", get_notes)
    monkeypatch.setattr(
        home_properties.database.get, "ingress_files", get_ingress_files
    )
    monkeypatch.setattr(home_properties.database.get, "ai_reports", get_ai_reports)
    monkeypatch.setattr(home_properties.Entities, "fetch", load_entities)

    note_section = home_properties.NoteList()
    ingress_section = home_properties.IngressList()
    tools_section = home_properties.ToolsList()
    notes = note_section.list
    ingress_files = ingress_section.list
    reports = tools_section.list

    assert notes_requests == [user]
    assert ingress_requests == [True]
    assert ai_report_requests == [user]
    assert load_requests == [("note-1", "note-2"), ("ingress-1",), ("report-1",)]
    assert [note.key for note in notes] == ["note-1", "note-2"]
    assert [ingress.key for ingress in ingress_files] == ["ingress-1"]
    assert [report.key for report in reports] == ["report-1"]
    assert note_section.list is notes
    assert ingress_section.list is ingress_files
    assert tools_section.list is reports
