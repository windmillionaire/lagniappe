import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities.index import Index, TaskHistoryIndex, TaskIndex
from lagniappe.core.tools.database import get as database_get

from testing.utility.test_entities import TestEntities


# @matrix task-index : active completed query-filter
@pytest.mark.unit
def test_task_query_filter_uses_completed_status_not_active_status():
    incomplete = {
        condition.property_name: condition.value
        for condition in database_get._tasks_filter(completed=False)._conditions
    }
    completed = {
        condition.property_name: condition.value
        for condition in database_get._tasks_filter(completed=True)._conditions
    }

    assert incomplete == {"type": "task", "active": True, "completed": False}
    assert completed == {"type": "task", "active": True, "completed": True}


# @matrix task-index : assignee-visibility query-filter
@pytest.mark.unit
def test_task_query_filter_includes_assignee_visibility_branch():
    assignee = TestEntities.get(
        "PAGE",
        {"name": "Assigned User Page", "hash": "assigned-task-page"},
    )

    restricted = database_get._tasks_filter(
        hashes=["visible-task"],
        assigned_to=assignee,
    )

    assert len(restricted._or_groups) == 2
    assert restricted._or_groups[0]._requires == ["visible-task"]
    assigned_condition = restricted._or_groups[1]._conditions[0]
    assert assigned_condition.property_name == "assigned_to"
    assert assigned_condition.value == assignee.key

    denied = database_get._tasks_filter(hashes=[], assigned_to=assignee)
    conditions = {
        condition.property_name: condition.value for condition in denied._conditions
    }
    assert conditions["assigned_to"] == assignee.key
    assert denied._or_groups == []

    unrestricted = database_get._tasks_filter(
        hashes=database_get.Restriction.UNRESTRICTED,
        assigned_to=assignee,
    )
    assert unrestricted._or_groups == []
    assert unrestricted._requires is None


# @matrix home task-index : due-tasks restrictions unrestricted
@pytest.mark.unit
def test_due_tasks_does_not_add_requires_filter_for_unrestricted(monkeypatch):
    captured = {}

    class FakeQuery:
        def __init__(self, kind):
            captured["kind"] = kind

        def filter(self, filter_builder):
            captured["filter"] = filter_builder
            return self

        def order(self, ordering):
            captured["order"] = ordering
            return self

        def fetch_all(self):
            return []

    monkeypatch.setattr(database_get, "Query", FakeQuery)

    assert database_get.due_tasks(database_get.Restriction.UNRESTRICTED) == []

    filter_builder = captured["filter"]
    conditions = {
        condition.property_name: condition.value
        for condition in filter_builder._conditions
    }

    assert conditions["type"] == "task"
    assert conditions["active"] is True
    assert conditions["completed"] is False
    assert filter_builder._requires is None
    assert captured["order"] == "due_date"


# @matrix task-index : columns table
@pytest.mark.unit
def test_task_index(get_test_entities):
    """Test TaskIndex produces correct column structure for UI.

    TaskIndex has columns: Completed, Name, Status, Description, Due Date,
    Assigned To, Modified.
    Verifies entity.column(field_id) returns correct column_value for each.
    """
    from lagniappe.core.entities.index import TaskIndex

    from testing.utility.test_entities import TestEntities

    index_user = TestEntities.get(
        "USER",
        {
            "name": "Index viewer",
            "hash": "idxusr1",
            "page": {"name": "Idx page", "hash": "idxpg1"},
            "owner": True,
        },
    )

    tasks = get_test_entities()

    # Set properties that need to be set via setter
    for task in tasks:
        task.name = task.test_spec.get("name")
        task.description = task.test_spec.get("description")
        if task.test_spec.get("completed"):
            task.completed = True
            task.completed_on = datetime.now(timezone.utc)

    task_index = TaskIndex(user=index_user)
    task_index._tasks = tasks

    table = task_index.table

    # 7 columns with required keys
    assert len(table.columns) == 7
    column_keys = {
        "field",
        "title",
        "icon",
        "ordering",
        "selected",
        "link",
        "parent",
        "schema",
    }
    for col in table.columns:
        assert column_keys == col.keys()

    # Verify column field order
    expected_fields = [
        "completed",
        "name",
        "status",
        "description",
        "due_date",
        "assigned_to",
        "modified",
    ]
    assert [c["field"] for c in table.columns] == expected_fields

    # Only name, due_date, modified selected by default
    assert table.selected == ["name", "due_date", "modified"]

    # Verify entity.column() returns correct column_value for each task
    for task in tasks:
        # completed - returns boolean
        completed_col = task.column("completed")
        expected_completed = True if task.test_spec.get("completed") else False
        assert completed_col.column_value == expected_completed

        # name - returns entity details dict
        name_col = task.column("name")
        assert name_col.column_value == task.details

        # description - returns description string or None
        desc_col = task.column("description")
        assert desc_col.column_value == task.description

        # due_date - column exists (value tested elsewhere due to timezone context)
        assert task.column("due_date") is not None

        # assigned_to - stores page; column_value is page details when assigned
        assigned_col = task.column("assigned_to")
        if task.assigned_to:
            assert assigned_col.column_value == task.assigned_to.reference_details
        else:
            assert assigned_col.column_value is None

        # modified - column exists (value tested elsewhere due to timezone context)
        assert task.column("modified") is not None

        if task.completed:
            assert task.column("completed").editable is True
            assert task.column("name").editable is False


# @matrix status task-index : computed-column mixed-forms
@pytest.mark.unit
def test_task_index_status_column_derives_messages_from_mixed_forms(get_schema):
    """TaskTable exposes one status column that resolves each task's own form."""
    from lagniappe.core.entities.index import TaskIndex

    index_user = TestEntities.get(
        "USER",
        {
            "name": "Status index viewer",
            "hash": "idxsts1",
            "page": {"name": "Status page", "hash": "idxstpg1"},
            "owner": True,
        },
    )

    completed_form = TestEntities.get(
        "FORM", {"name": "Completed Status Form", "hash": "frm010s1"}
    )
    completed_form.schema = get_schema("status_only")
    review_form = TestEntities.get(
        "FORM", {"name": "Review Status Form", "hash": "frm010s2"}
    )
    review_form.schema = [
        {"id": "review-trigger", "type": "checkbox", "title": "Needs Review"},
        {
            "id": "review-status",
            "type": "status",
            "title": "Review Status",
            "status": [
                {
                    "id": "review-trigger",
                    "value": True,
                    "text": "Needs Review",
                }
            ],
        },
    ]
    plain_form = TestEntities.get(
        "FORM", {"name": "Plain Task Form", "hash": "frm010s3"}
    )
    plain_form.schema = get_schema("basic_inputs")

    completed_task = TestEntities.get(
        "TASK",
        {
            "name": "Completed Status Task",
            "hash": "tsk010s1",
            "page": {"name": "Completed Status Page", "hash": "pg010s1"},
        },
    )
    completed_task.properties.form._value = completed_form
    completed_task.db["submission"] = json.dumps({"checkbox-trigger": True})

    review_task = TestEntities.get(
        "TASK",
        {
            "name": "Review Status Task",
            "hash": "tsk010s2",
            "page": {"name": "Review Status Page", "hash": "pg010s2"},
        },
    )
    review_task.properties.form._value = review_form
    review_task.db["submission"] = json.dumps({"review-trigger": True})

    inactive_task = TestEntities.get(
        "TASK",
        {
            "name": "Inactive Status Task",
            "hash": "tsk010s3",
            "page": {"name": "Inactive Status Page", "hash": "pg010s3"},
        },
    )
    inactive_task.properties.form._value = completed_form
    inactive_task.db["submission"] = json.dumps({"checkbox-trigger": False})

    plain_task = TestEntities.get(
        "TASK",
        {
            "name": "Plain Status Task",
            "hash": "tsk010s4",
            "page": {"name": "Plain Status Page", "hash": "pg010s4"},
        },
    )
    plain_task.properties.form._value = plain_form

    task_index = TaskIndex(user=index_user)
    table = task_index.table

    assert [column["field"] for column in table.columns] == [
        "completed",
        "name",
        "status",
        "description",
        "due_date",
        "assigned_to",
        "modified",
    ]
    assert table.fields["status"].label == "Status"
    assert table.fields["status"].selected is False
    assert table.selected == ["name", "due_date", "modified"]

    assert completed_task.column("status").column_value == ["Completed"]
    assert completed_task.column("status").sort_value is True
    assert review_task.column("status").column_value == ["Needs Review"]
    assert review_task.column("status").sort_value is True
    assert inactive_task.column("status").column_value == []
    assert inactive_task.column("status").sort_value is False
    assert plain_task.column("status").column_value is None
    assert plain_task.column("status").sort_value is None


# @matrix tasks : attachments columns history table
@pytest.mark.unit
def test_task_history_index_includes_attachments_column():
    """Task history tables expose attachments as an optional column."""
    task = TestEntities.get(
        "TASK",
        {
            "name": "History parent",
            "hash": "thidx1",
            "page": {"name": "Parent", "hash": "pgidx1"},
        },
    )

    task_history_index = TaskHistoryIndex(entity=task)
    table = task_history_index.table

    assert [column["field"] for column in table.columns] == [
        "completed_on",
        "name",
        "description",
        "completed_by",
        "files",
    ]
    assert table.fields["files"].label == "Attachments"
    assert table.fields["files"].selected is False


# @matrix tasks : columns description history name table
@pytest.mark.unit
def test_task_history_index_includes_snapshot_columns(get_schema):
    """Only completion date and preserved text are selected by default."""
    form = TestEntities.get(
        "FORM", {"name": "History form", "hash": "frmthidx2"}
    )
    form.schema = get_schema("basic_inputs")
    task = TestEntities.get(
        "TASK",
        {
            "name": "History parent",
            "hash": "thidx2",
            "page": {"name": "Parent", "hash": "pgidx2"},
        },
    )
    task.properties.form._value = form

    table = TaskHistoryIndex(entity=task).table

    assert table.selected == ["completed_on", "name", "description"]
    assert all(
        field.selected == (field.id in table.selected)
        for field in table.fields.values()
    )
    assert table.fields["name"].label == "Name"
    assert table.fields["name"].selected is True
    assert table.fields["name"].link is False
    assert table.fields["name"].parent is False
    assert table.fields["description"].label == "Description"
    assert table.fields["description"].selected is True


# @matrix index : pagination state user-scope
@pytest.mark.unit
def test_index_base_cursor_limit_user_and_append_state():
    """Base Index stores pagination and user state without owning queries."""

    class DummyIndex(Index):
        def _get_properties(self):
            return {}

    user = SimpleNamespace(name="Index User")
    index = DummyIndex(cursor="start-cursor", limit=7, user=user)

    assert index.cursor == "start-cursor"
    assert index.limit == 7
    assert index.user is user
    assert index.append is False

    index.cursor = "next-cursor"
    index.limit = 3
    index.append = "/rows?cursor=next"

    assert index.cursor == "next-cursor"
    assert index.limit == 3
    assert index.append == "/rows?cursor=next"


# @matrix task-index : dated pagination restrictions undated
@pytest.mark.unit
def test_task_index_paginates_dated_then_undated_tasks_with_restrictions():
    """TaskIndex coordinates dated/undated task streams and row append URLs."""
    project = TestEntities.get("PROJECT", {"name": "Project", "hash": "prj010"})
    user = SimpleNamespace(
        properties=SimpleNamespace(restrictions=SimpleNamespace(task=["cat010"]))
    )
    dated_task = TestEntities.get(
        "TASK",
        {
            "name": "Dated",
            "hash": "tsk010a",
            "page": {"name": "Parent", "hash": "pg010a"},
        },
    )
    undated_task = TestEntities.get(
        "TASK",
        {
            "name": "Undated",
            "hash": "tsk010b",
            "page": {"name": "Parent", "hash": "pg010b"},
        },
    )

    def fake_url_for(endpoint, **kwargs):
        pieces = [endpoint]
        pieces.extend(f"{key}={value}" for key, value in sorted(kwargs.items()))
        return "/" + "&".join(pieces)

    with patch("lagniappe.core.entities.index.url_for", side_effect=fake_url_for):
        with patch(
            "lagniappe.core.entities.index.database_get.tasks_with_due_dates",
            return_value=SimpleNamespace(results=["dated-key"], next_cursor=None),
        ) as dated_query:
            with patch(
                "lagniappe.core.entities.index.database_get.tasks_without_due_dates"
            ) as undated_query:
                with patch(
                    "lagniappe.core.entities.index.Entities.fetch",
                    return_value=[dated_task],
                ) as load:
                    index = TaskIndex(
                        cursor="cursor-1",
                        limit=2,
                        user=user,
                        entity=project,
                    )
                    tasks = index.tasks

    dated_query.assert_called_once_with(
        start_cursor="cursor-1",
        limit=2,
        project=project,
        hashes=["cat010"],
        assigned_to=None,
    )
    undated_query.assert_not_called()
    load.assert_called_once_with("dated-key", request=Fetch.direct())
    assert tasks == [dated_task]
    assert index.cursor is None
    assert index.append == "/tasks.rows&undated=1"
    assert index.tasks is tasks

    with patch("lagniappe.core.entities.index.url_for", side_effect=fake_url_for):
        with patch(
            "lagniappe.core.entities.index.database_get.tasks_with_due_dates",
            return_value=SimpleNamespace(results=[], next_cursor="ignored"),
        ) as dated_query:
            with patch(
                "lagniappe.core.entities.index.database_get.tasks_without_due_dates",
                return_value=SimpleNamespace(
                    results=["undated-key"], next_cursor="cursor-2"
                ),
            ) as undated_query:
                with patch(
                    "lagniappe.core.entities.index.Entities.fetch",
                    return_value=[undated_task],
                ) as load:
                    index = TaskIndex(
                        cursor="cursor-1",
                        limit=2,
                        user=user,
                        entity=project,
                    )
                    tasks = index.tasks

    dated_query.assert_called_once_with(
        start_cursor="cursor-1",
        limit=2,
        project=project,
        hashes=["cat010"],
        assigned_to=None,
    )
    undated_query.assert_called_once_with(
        start_cursor="cursor-1",
        limit=2,
        project=project,
        hashes=["cat010"],
        assigned_to=None,
    )
    load.assert_called_once_with("undated-key", request=Fetch.direct())
    assert tasks == [undated_task]
    assert index.cursor == "cursor-2"
    assert index.append == "/tasks.rows&cursor=cursor-2&undated=1"
