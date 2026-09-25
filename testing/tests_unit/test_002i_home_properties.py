from types import SimpleNamespace

import pytest

import lagniappe.core.properties.home as home_properties
from lagniappe import CONFIG
from lagniappe.core.entities.home import Home
from testing.utility.mock_restrictions import MockRestrictions
from testing.utility.test_entities import TestEntities


# @matrix home : explicit-user validation
@pytest.mark.unit
@pytest.mark.parametrize("constructor", [Home, home_properties.HomeProperty])
def test_home_requires_explicit_user(constructor):
    with pytest.raises(TypeError, match="user"):
        constructor()
    with pytest.raises(ValueError, match="requires a user"):
        constructor(user=None)


# @source lagniappe/core/properties/home.py::TaskList
# @source lagniappe/core/properties/home.py::PageList
# @matrix home : explicit-user pagination count permissions
@pytest.mark.unit
def test_home_sections_keep_their_viewer_across_lazy_and_paginated_reads(monkeypatch):
    tasks = [
        TestEntities.get(
            "TASK",
            {
                "hash": f"task-{suffix}",
                "page": {"hash": f"page-{suffix}"},
            },
        )
        for suffix in ("a", "b")
    ]
    pages = [task.page for task in tasks]
    viewers = [
        TestEntities.get(
            "USER",
            {
                "hash": f"viewer-{suffix}",
                "page": {"hash": f"viewer-page-{suffix}"},
                "permissions": {f"page-{suffix}": "VIEW"},
            },
        )
        for suffix in ("a", "b")
    ]
    monkeypatch.setattr(CONFIG, "TEST_CURRENT_USER", None)
    monkeypatch.setattr(
        home_properties.database_get, "due_tasks", lambda **_kwargs: tasks
    )
    monkeypatch.setattr(
        home_properties.database_get,
        "recent_pages",
        lambda **_kwargs: SimpleNamespace(
            results=[page.key for page in pages],
            next_cursor="next-page",
        ),
    )
    monkeypatch.setattr(
        home_properties.Entities,
        "fetch",
        lambda *_args, **_kwargs: (
            [*tasks, *pages] if _args and hasattr(_args[0], "db") else pages
        ),
    )
    counts = {viewers[0].page.key: 2, viewers[1].page.key: 7}
    monkeypatch.setattr(
        home_properties.database_get, "user_task_count", lambda page: counts[page.key]
    )
    first, second = [Home(user=viewer) for viewer in viewers]

    with MockRestrictions().patch_cache():
        assert first.tasks.list == [tasks[0]]
        assert second.tasks.list == [tasks[1]]
        assert first.tasks.count == 2
        assert second.tasks.count == 7
        assert first.pages.list == [pages[0]]
        assert second.pages.list == [pages[1]]
        assert second.section("tasks").list == [tasks[1]]
        next_pages = first.section("pages", cursor="previous-page")
        assert next_pages.back is True
        assert next_pages.list == [pages[0]]
        assert next_pages.cursor == "next-page"
        assert first.tasks.list == [tasks[0]]

    with pytest.raises(TypeError, match="user"):
        first.section("tasks", user=viewers[1])


# @matrix home : pagination projects restrictions
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
        return SimpleNamespace(
            results=["project-1", "project-2"], next_cursor="next-page"
        )

    def wrap_project(model):
        project_wrapped.append(model)
        return SimpleNamespace(key=f"wrapped-{model}")

    monkeypatch.setattr(home_properties.database_get, "models", get_models)
    monkeypatch.setattr(home_properties.Entities, "PROJECT", wrap_project)

    section = home_properties.ProjectList(user=user, cursor="start-page")
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

    monkeypatch.setattr(home_properties.database_get, "models", get_models)
    monkeypatch.setattr(home_properties.Entities, "fetch", fetch_categories)

    section = home_properties.CategoryList(user=user, cursor="category-start")
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

        def allowed(self, action, *, user):
            self.allowed_actions.append((action, user))
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
        load_requests.append((keys, request))
        return pages

    monkeypatch.setattr(home_properties.database_get, "recent_pages", recent_pages)
    monkeypatch.setattr(home_properties.Entities, "fetch", load_entities)

    section = home_properties.PageList(user=user, cursor="p1")
    visible_pages = section.list

    assert page_requests == [
        {
            "start_cursor": "p1",
            "hashes": ("models", "page-a", "category-a"),
        }
    ]
    assert load_requests == [
        (("page-1", "page-2", "page-3"), home_properties.Fetch.direct())
    ]
    assert visible_pages == [pages[0], pages[2]]
    assert [page.allowed_actions for page in pages] == [
        [(home_properties.Action.VIEW, user)],
        [(home_properties.Action.VIEW, user)],
        [(home_properties.Action.VIEW, user)],
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

        def allowed(self, action, *, user):
            self.allowed_actions.append((action, user))
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
        load_requests.append((keys, request))
        return tasks

    def user_task_count(page):
        count_requests.append(page)
        return 7

    monkeypatch.setattr(home_properties.database_get, "due_tasks", due_tasks)
    monkeypatch.setattr(home_properties.Entities, "fetch", load_entities)
    monkeypatch.setattr(
        home_properties.database_get, "user_task_count", user_task_count
    )

    section = home_properties.TaskList(user=user)
    visible_tasks = section.list

    assert due_requests == [
        {
            "hashes": ("task-a", "task-b"),
            "assigned_to": "user-page",
        }
    ]
    assert load_requests == [
        (
            (
                *stored_tasks,
                "page-1",
                "page-2",
                "page-3",
            ),
            home_properties.Fetch.direct(),
        )
    ]
    assert visible_tasks == [tasks[0], tasks[2]]
    assert [task.allowed_actions for task in tasks] == [
        [(home_properties.Action.VIEW, user)],
        [(home_properties.Action.VIEW, user)],
        [(home_properties.Action.VIEW, user)],
    ]
    assert section.list is visible_tasks
    assert section.count == 7
    assert count_requests == ["user-page"]


# @matrix starred : missing-placeholder pagination view-authorization
@pytest.mark.unit
def test_home_starred_list_paginates_and_marks_missing_keys(monkeypatch):
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
        loaded_requests.append((keys, request))
        return [FakeEntity(key) for key in keys if key != stale_key]

    monkeypatch.setattr(home_properties.Entities, "fetch", load_entities)
    monkeypatch.setattr(
        home_properties.database_get,
        "urlsafe_key",
        lambda key: f"urlsafe:{key}",
    )

    section = home_properties.StarredList(user=user)
    loaded = section.list

    assert loaded_requests == [
        (tuple(starred_keys[:10]), home_properties.Fetch.direct())
    ]
    assert [entity.key for entity in loaded] == [
        key for key in starred_keys[:10] if key != stale_key
    ]
    missing = [item for item in section.items if "entity" not in item]
    assert len(missing) == 1
    assert missing[0]["key"] == f"urlsafe:{stale_key}"
    assert missing[0]["state"] == "missing"
    assert "no longer exists" in missing[0]["message"]
    assert [item.get("key") for item in section.items] == [
        f"urlsafe:{key}" for key in starred_keys[:10]
    ]
    assert starred.deleted == []
    assert stale_key in starred.keys
    assert section.cursor == 1
    assert section.count == 12
    assert user.saved is False
    assert all(
        entity.allowed_requests == [(home_properties.Action.VIEW, user)]
        for entity in loaded
    )

    next_section = home_properties.StarredList(user=user, cursor="1")
    next_loaded = next_section.list

    assert loaded_requests == [
        (tuple(starred_keys[:10]), home_properties.Fetch.direct()),
        (tuple(starred_keys[10:]), home_properties.Fetch.direct()),
    ]
    assert [entity.key for entity in next_loaded] == starred_keys[10:]
    assert [item["key"] for item in next_section.items] == [
        f"urlsafe:{key}" for key in starred_keys[10:]
    ]
    assert next_section.cursor is None
    assert next_section.count == 12


# @matrix starred : inaccessible-placeholder retained-inaccessible view-authorization
@pytest.mark.unit
def test_home_starred_list_hides_but_retains_inaccessible_keys(monkeypatch):
    class FakeEntity:
        def __init__(self, key, visible):
            self.key = key
            self.visible = visible

        def allowed(self, action, user=None):
            assert action is home_properties.Action.VIEW
            assert user is viewer
            return self.visible

    class FakeStarred:
        keys = ["visible", "restricted", "missing"]

        def __init__(self):
            self.deleted = []

        def delete_starred_keys(self, keys):
            self.deleted.extend(keys)
            self.keys = [key for key in self.keys if key not in keys]

    starred = FakeStarred()
    viewer = SimpleNamespace(
        properties=SimpleNamespace(starred=starred),
        save=lambda: None,
    )
    visible = FakeEntity("visible", True)
    restricted = FakeEntity("restricted", False)
    load_requests = []

    def load_entities(*keys, request):
        load_requests.append((keys, request))
        return [visible, restricted]

    monkeypatch.setattr(
        home_properties.Entities,
        "fetch",
        load_entities,
    )
    monkeypatch.setattr(
        home_properties.database_get,
        "urlsafe_key",
        lambda key: f"urlsafe:{key}",
    )

    section = home_properties.StarredList(user=viewer)

    assert section.list == [visible]
    placeholders = [item for item in section.items if "entity" not in item]
    assert [(item["key"], item["state"]) for item in placeholders] == [
        ("urlsafe:restricted", "inaccessible"),
        ("urlsafe:missing", "missing"),
    ]
    assert "no longer accessible" in placeholders[0]["message"]
    assert "no longer exists" in placeholders[1]["message"]
    assert [item.get("entity", item.get("key")) for item in section.items] == [
        visible,
        "urlsafe:restricted",
        "urlsafe:missing",
    ]
    assert starred.deleted == []
    assert starred.keys == ["visible", "restricted", "missing"]
    assert section.count == 3
    assert load_requests == [
        (("visible", "restricted", "missing"), home_properties.Fetch.direct())
    ]


# @matrix home : ingress list notes query tools
# @matrix ai-report : list query tools
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
        load_requests.append((keys, request))
        return [SimpleNamespace(key=key) for key in keys]

    monkeypatch.setattr(home_properties.database_get, "notes", get_notes)
    monkeypatch.setattr(
        home_properties.database_get, "ingress_files", get_ingress_files
    )
    monkeypatch.setattr(home_properties.database_get, "ai_reports", get_ai_reports)
    monkeypatch.setattr(home_properties.Entities, "fetch", load_entities)

    note_section = home_properties.NoteList(user=user)
    ingress_section = home_properties.IngressList(user=user)
    tools_section = home_properties.ToolsList(user=user)
    notes = note_section.list
    ingress_files = ingress_section.list
    reports = tools_section.list

    assert notes_requests == [user]
    assert ingress_requests == [True]
    assert ai_report_requests == [user]
    assert load_requests == [
        (("note-1", "note-2"), home_properties.Fetch.direct()),
        (("ingress-1",), home_properties.Fetch.direct()),
        (("report-1",), home_properties.Fetch.direct()),
    ]
    assert [note.key for note in notes] == ["note-1", "note-2"]
    assert [ingress.key for ingress in ingress_files] == ["ingress-1"]
    assert [report.key for report in reports] == ["report-1"]
    assert note_section.list is notes
    assert ingress_section.list is ingress_files
    assert tools_section.list is reports
    assert tools_section.label == "Plans & Reports"
