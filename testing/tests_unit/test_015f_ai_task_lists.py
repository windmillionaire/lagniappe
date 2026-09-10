"""Compact task discovery retains enough context for accurate follow-up reads."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import Action
from lagniappe.core.tools.ai.function_definitions import (
    get_page_details,
    get_page_tasks,
)


pytestmark = pytest.mark.unit


class Task:
    def __init__(self, number, *, completed=False, visible=True):
        self.hash = f"{number:012x}"
        self.name = f"Task {number:03}"
        self.completed = completed
        self.visible = visible
        self.modified = datetime(2026, 9, 8, tzinfo=timezone.utc)
        self.description = "Repair the page navigation."
        self.project = self.model = self.form = None
        self.due_date = self.completed_on = None

    def allowed(self, action, user=None):
        return self.visible and action == Action.VIEW

    def _ai_url(self):
        return f"/tasks/task-key-{self.hash}"

    def to_ai(self, user=None):
        pytest.fail("Compact discovery must not serialize task forms or submissions")


class Page:
    hash = "page00000001"
    name = "Home"
    model = None
    files = []

    def __init__(self, tasks):
        self.tasks = [task for task in tasks if not task.completed]
        self.completed = [task for task in tasks if task.completed]

    def allowed(self, action, user=None):
        return True

    def to_ai(self, user=None):
        return {"page_name": self.name, "page_description": "Homepage work"}


@pytest.fixture
def task_page(monkeypatch):
    user = SimpleNamespace(
        hash="user00000001",
        is_authenticated=True,
        db={"timezone": "America/Los_Angeles"},
    )
    page = Page([Task(1), Task(2, completed=True), Task(3, visible=False)])
    monkeypatch.setattr(get_page_tasks.Entities, "PAGE", Page)
    monkeypatch.setattr(
        get_page_tasks.Entities,
        "fetch_one",
        lambda identifier, request: page if identifier == f"hash:{page.hash}" else None,
    )
    return page, user


def read_tasks(page, user, **options):
    return get_page_tasks.execute_get_page_tasks(
        {"id": f"hash:{page.hash}", "compact": True, **options}, user
    )


def read_details(page, user, **options):
    return get_page_details.execute_get_page_details(
        {"id": f"hash:{page.hash}", "compact_tasks": True, **options}, user
    )


# @matrix ai tasks : compact permissions
def test_compact_tasks_preserve_identity_scope_and_followup_references(task_page):
    page, user = task_page

    class Form:
        hash = "form00000001"
        name = "Bug"
        entity_kind = "form"

        def allowed(self, action, user=None):
            return True

        @property
        def schema(self):
            pytest.fail("Compact lists must not load a form schema")

    page.tasks[0].form = Form()
    page.tasks[0].model = SimpleNamespace(
        allowed=lambda *a, **kw: False, name="Hidden model"
    )
    page.tasks[0].description = "x" * 501
    page.tasks[0].due_date = datetime(2026, 9, 9, 2, tzinfo=timezone.utc)
    page.completed[0].completed_on = datetime(2026, 9, 8, 1)
    result = read_tasks(page, user)
    assert result["page"] == {"hash": f"hash:{page.hash}", "name": "Home"}
    (row,) = result["tasks"]
    assert row == {
        "hash": "hash:000000000001",
        "kind": "task",
        "name": "Task 001",
        "url": "/tasks/task-key-000000000001",
        "completed": False,
        "description": "x" * 500,
        "description_truncated": True,
        "permissions": {"can_view": True, "can_edit": False},
        "form": {"hash": "hash:form00000001", "kind": "form", "name": "Bug"},
        "due_date": "2026-09-08",
    }
    (completed,) = result["completed_tasks"]
    assert completed["completed"] is True
    assert completed["completed_on"] == "2026-09-07"
    assert completed["description_truncated"] is False
    assert result["task_list"] == {
        "scope": "active_and_completed",
        "limit": 25,
        "total_count": 2,
        "active_count": 1,
        "completed_count": 1,
        "returned_count": 2,
        "has_more": False,
        "next_cursor": None,
        "incomplete": False,
    }


# @matrix ai tasks : compact pagination permissions
def test_compact_tasks_paginate_visible_active_and_completed_rows(task_page):
    page, user = task_page
    first = read_tasks(page, user, limit=1)
    assert [row["name"] for row in first["tasks"]] == ["Task 001"]
    assert first["completed_tasks"] == []
    assert first["task_list"]["total_count"] == 2
    assert first["task_list"]["has_more"] is True
    second = read_tasks(page, user, limit=1, cursor=first["task_list"]["next_cursor"])
    assert second["tasks"] == []
    assert [row["name"] for row in second["completed_tasks"]] == ["Task 002"]
    assert second["task_list"]["has_more"] is False
    assert second["task_list"]["next_cursor"] is None


# @matrix ai tasks : compact pagination
@pytest.mark.parametrize(
    "change", ["revision", "membership", "permission", "page", "user", "scope"]
)
def test_compact_tasks_reject_stale_or_mismatched_cursors(task_page, change):
    page, user = task_page
    cursor = read_tasks(page, user, limit=1)["task_list"]["next_cursor"]
    if change == "revision":
        page.tasks[0].modified = datetime(2026, 9, 9, tzinfo=timezone.utc)
    elif change == "membership":
        page.tasks.append(Task(4))
    elif change == "permission":
        page.completed[0].visible = False
    elif change == "page":
        page.hash = "page00000002"
    elif change == "user":
        user.hash = "user00000002"
    result = (
        read_details(page, user, task_cursor=cursor)
        if change == "scope"
        else read_tasks(page, user, cursor=cursor)
    )
    assert "Restart this task list without a cursor" in result["error"]


# @matrix ai tasks : compact pagination
@pytest.mark.parametrize(
    "options",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"limit": "25"},
        {"cursor": "garbage"},
        {"cursor": "e30="},
        {"cursor": "W10="},
        {"cursor": ""},
        {"cursor": 3},
        {"cursor": "x" * 513},
        {"compact": False, "limit": 1},
    ],
)
def test_compact_tasks_reject_invalid_paging_arguments(task_page, options):
    page, user = task_page
    assert "error" in read_tasks(page, user, **options)


# @matrix ai tasks : compact pagination
def test_compact_tasks_empty_and_default_bounded_results(task_page):
    page, user = task_page
    page.tasks = []
    page.completed = []
    empty = read_tasks(page, user)
    assert empty["tasks"] == empty["completed_tasks"] == []
    assert empty["task_list"]["total_count"] == 0
    assert empty["task_list"]["has_more"] is False
    page.tasks = [Task(number) for number in range(26)]
    bounded = read_tasks(page, user)
    assert len(bounded["tasks"]) == 25
    assert bounded["task_list"]["total_count"] == 26
    assert bounded["task_list"]["has_more"] is True


# @matrix ai tasks : compact
def test_compact_tasks_disclose_partial_failure_without_losing_continuation(task_page):
    page, user = task_page
    page.tasks[0]._ai_url = lambda: (_ for _ in ()).throw(
        ValueError("private submission details")
    )
    result = read_tasks(page, user, limit=1)
    assert result["tasks"] == []
    assert result["task_list"]["incomplete"] is True
    assert result["task_list"]["returned_count"] == 0
    assert result["task_list"]["total_count"] == 2
    assert result["task_list"]["serialization_errors"] == [
        {
            "hash": "hash:000000000001",
            "message": "Task details could not be read. Use get_entity for this task.",
        }
    ]
    next_result = read_tasks(page, user, cursor=result["task_list"]["next_cursor"])
    assert next_result["completed_tasks"][0]["name"] == "Task 002"
    assert next_result["task_list"]["incomplete"] is False
    final = read_tasks(page, user)
    assert final["task_list"]["has_more"] is False
    assert final["task_list"]["incomplete"] is True


# @matrix ai tasks : compact permissions
def test_compact_tasks_reject_inaccessible_page(task_page):
    page, user = task_page
    page.allowed = lambda *args, **kwargs: False
    assert read_tasks(page, user) == {"error": "Access denied"}


# @matrix ai tasks : compact
def test_compact_tasks_real_entities_support_focused_schema_and_detail_reads(
    monkeypatch,
):
    from lagniappe.core.tools.ai.function_definitions import get_entity, get_schema
    from testing.utility.test_entities import TestEntities

    page = TestEntities.get("PAGE", {"name": "Home", "hash": "page00000001"})
    form = TestEntities.get("FORM", {"name": "Bug", "hash": "form00000001"})
    form.form_type = "task"
    form.schema = [{"id": "textarea-notes", "type": "textarea", "title": "Notes"}]
    task = TestEntities.get("TASK", {"name": "Navigation", "hash": "task00000001"})
    task.page = page
    task.form = form
    task.submission = {"textarea-notes": "Only fetch these details when needed."}
    page._tasks = [task]
    page._completed = []
    user = SimpleNamespace(
        hash="user00000001",
        is_authenticated=True,
        is_owner=True,
        has_permission=lambda *args, **kwargs: True,
        db={},
    )
    registry = {f"hash:{entity.hash}": entity for entity in (page, form, task)}
    monkeypatch.setattr(
        get_page_tasks.Entities,
        "fetch_one",
        lambda identifier, request: registry[identifier] if isinstance(identifier, str) else identifier,
    )
    monkeypatch.setattr(
        get_entity.Entities, "fetch", lambda *entities, request: list(entities)
    )

    compact = read_tasks(page, user)
    assert compact["task_list"]["incomplete"] is False
    (row,) = compact["tasks"]
    assert row["url"] == task.url
    schema = get_schema.execute_get_schema({"id": row["form"]["hash"]}, user)
    assert schema["schema"] == form.schema
    details = get_entity.execute_get_entity({"id": row["hash"]}, user)
    assert details["task_name"] == "Navigation"
    assert details["Notes"] == "Only fetch these details when needed."


# @matrix ai tasks : compact pagination permissions
def test_compact_page_details_keep_active_scope_and_page_context(task_page):
    page, user = task_page
    page.tasks.append(Task(4))
    first = read_details(page, user, task_limit=1)
    assert first["page"] == page.to_ai(user)
    assert first["files"] == []
    assert "completed_tasks" not in first
    assert first["task_list"]["scope"] == "active"
    assert first["task_list"]["total_count"] == 2
    assert first["task_list"]["completed_count"] == 0
    assert [row["name"] for row in first["tasks"]] == ["Task 001"]
    second = read_details(page, user, task_cursor=first["task_list"]["next_cursor"])
    assert [row["name"] for row in second["tasks"]] == ["Task 004"]
    assert second["task_list"]["has_more"] is False
    assert "error" in read_details(page, user, task_cursor="invalid")
    assert "error" in read_details(page, user, compact_tasks=False, task_limit=1)


# @matrix ai tasks : compact
def test_compact_page_details_exclusions_take_precedence(task_page):
    page, user = task_page
    result = read_details(
        page, user, exclude_tasks=True, exclude_files=True, task_cursor="invalid"
    )
    assert result == {"page": page.to_ai(user)}
