"""Home task-count semantics against the managed testing Datastore."""

from types import SimpleNamespace
from uuid import uuid4

from google.cloud.datastore import Entity
import pytest

from lagniappe.core.tools.database import get
from lagniappe.core.tools.database.core import DATA, KINDS
from lagniappe.core.tools.database.filter import Filter, Query

pytestmark = pytest.mark.e2e


# @matrix database : count aggregation
# @matrix home : task-count ownership assignment deduplication
def test_user_task_count_aggregates_owned_and_assigned_tasks_once():
    client = DATA.datastore
    identity = f"task-count-{uuid4().hex}"
    owner = client.key(KINDS.instances.value, f"{identity}-owner")
    other = client.key(KINDS.instances.value, f"{identity}-other")
    empty = client.key(KINDS.instances.value, f"{identity}-empty")
    cases = {
        "owned": {"page": owner},
        "assigned": {"page": other, "assigned_to": owner},
        "both": {"page": owner, "assigned_to": owner, "requires": ["one", "two"]},
        "owned-assigned-elsewhere": {"page": owner, "assigned_to": other},
        "unrelated": {"page": other, "assigned_to": other},
        "linked-only": {"page": other, "linked_pages": [owner]},
        "inactive": {"page": owner, "assigned_to": owner, "active": False},
        "completed": {"page": owner, "assigned_to": owner, "completed": True},
        "wrong-type": {"page": owner, "assigned_to": owner, "type": "page"},
        "missing-active": {"page": owner, "active": None},
        "missing-completed": {"assigned_to": owner, "completed": None},
    }
    rows = {}
    for name, fields in cases.items():
        row = Entity(key=client.key(KINDS.instances.value, f"{identity}-{name}"))
        row.update(type="task", active=True, completed=False)
        row.update(fields)
        for field in ("active", "completed"):
            if row.get(field) is None:
                row.pop(field, None)
        rows[name] = row

    try:
        client.put_multi(list(rows.values()))
        assert get.user_task_count(SimpleNamespace(key=owner)) == 4
        assert get.user_task_count(SimpleNamespace(key=empty)) == 0

        rows["both"]["completed"] = True
        client.put(rows["both"])
        assert get.user_task_count(SimpleNamespace(key=owner)) == 3

        rows["assigned"]["assigned_to"] = other
        client.put(rows["assigned"])
        assert get.user_task_count(SimpleNamespace(key=owner)) == 2
    finally:
        client.delete_multi([row.key for row in rows.values()])


# @source lagniappe/core/tools/database/filter.py::Query.count
# @matrix database : count aggregation deduplication
def test_count_aggregation_deduplicates_array_matches():
    client = DATA.datastore
    identity = f"array-count-{uuid4().hex}"
    parent = client.key(KINDS.instances.value, identity)
    row = Entity(key=client.key(KINDS.instances.value, "array", parent=parent))
    row["requires"] = ["one", "two"]
    try:
        client.put(row)
        query = Query(KINDS.instances, ancestor=parent).filter(Filter().requires(["one", "two"]))
        assert len(query.fetch_all()) == 1
        assert query.count() == 1
    finally:
        client.delete(row.key)
