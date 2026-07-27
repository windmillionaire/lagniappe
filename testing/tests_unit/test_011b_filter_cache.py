from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.definitions import Action, Fetch, FetchReason, Restriction
from lagniappe.core.tools.filters.cache import FilterCache


def _user(*, models=None, task=None):
    return SimpleNamespace(
        urlsafe_key="user-key",
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(
                models=models if models is not None else [],
                task=task if task is not None else [],
            )
        ),
    )


def _parent(kind):
    return SimpleNamespace(
        kind=kind,
        hash=f"{kind}-hash",
        key=f"{kind}-key",
        urlsafe_key=f"{kind}-key",
    )


class _FilterExpression:
    def __init__(self, definitions):
        self.definitions = definitions

    def build(self):
        return "$..filter-expression"


# @features filters cache permissions
# @dimensions shared-key restrictions
@pytest.mark.unit
def test_filter_cache_uses_shared_cache_key_without_user_restrictions():
    parent = _parent("category")

    owner_cache = FilterCache(parent, user=_user(models=Restriction.UNRESTRICTED))
    restricted_cache = FilterCache(parent, user=_user(models=["category-a"]))

    assert owner_cache.cache_key == restricted_cache.cache_key
    assert owner_cache.cache_key.endswith(":all")


# @features filters cache permissions
# @dimensions query allowed related-load
@pytest.mark.unit
def test_filter_cache_query_filters_loaded_entities_by_view_permission():
    viewer = _user()
    parent = _parent("project")
    visible = SimpleNamespace(
        allowed=lambda action, user=None: action == Action.VIEW and user is viewer
    )
    hidden = SimpleNamespace(allowed=lambda action, user=None: False)
    entity_filter = SimpleNamespace(definitions=["definition"])

    with patch(
        "lagniappe.core.tools.filters.cache.FilterExpression", _FilterExpression
    ):
        with patch(
            "lagniappe.core.tools.filters.cache.filter_cache.query",
            return_value=["visible-key", "hidden-key"],
        ) as query:
            with patch(
                "lagniappe.core.tools.filters.cache.Entities.fetch",
                return_value=[visible, hidden],
            ) as load:
                results = FilterCache(parent, user=viewer).query(entity_filter)

    query.assert_called_once_with(
        FilterCache(parent, user=viewer).cache_key,
        "$..filter-expression",
    )
    load.assert_called_once_with(
        "visible-key", "hidden-key", request=Fetch.direct()
    )
    assert results == [visible]


# @features filters cache category
# @dimensions source-query restrictions pagination
@pytest.mark.unit
def test_filter_cache_loads_category_pages_without_restrictions():
    parent = _parent("category")
    page = SimpleNamespace(
        hash="page-hash",
        to_filter_index=lambda: {"id": "page-key", "name": "Page"},
    )

    with patch(
        "lagniappe.core.tools.filters.cache.database.get.pages",
        return_value=SimpleNamespace(results=["page-key"], next_cursor=None),
    ) as pages:
        with patch(
            "lagniappe.core.tools.filters.cache.Entities.fetch",
            return_value=[page],
        ):
            cache = FilterCache(parent, user=_user(models=["restricted"]))
            cache._load()

    pages.assert_called_once_with(
        parent.key,
        start_cursor=None,
        limit=100,
        hashes=Restriction.UNRESTRICTED,
    )
    assert cache._to_cache == {
        "page-hash": {"id": "page-key", "name": "Page"}
    }


class _FakeFilter:
    def __init__(self):
        self.calls = []

    def eq(self, prop, value):
        self.calls.append(("eq", prop, value))
        return self


class _FakeQuery:
    instances = []

    def __init__(self, kind):
        self.kind = kind
        self.source_filter = None
        self.orders = []
        self.instances.append(self)

    def filter(self, source_filter):
        self.source_filter = source_filter
        return self

    def order(self, *orders):
        self.orders.extend(orders)
        return self

    def fetch_all(self):
        return ["active-task-key", "completed-task-key"]


# @features filters cache project task
# @dimensions source-query all-tasks completed restrictions
@pytest.mark.unit
def test_filter_cache_loads_all_project_tasks_without_active_or_restriction_filters():
    parent = _parent("project")
    task = SimpleNamespace(
        hash="task-hash",
        to_filter_index=lambda: {
            "id": "task-key",
            "name": "Task",
            "completed": True,
        },
    )
    _FakeQuery.instances = []

    with patch("lagniappe.core.tools.filters.cache.Filter", _FakeFilter):
        with patch("lagniappe.core.tools.filters.cache.Query", _FakeQuery):
            with patch(
                "lagniappe.core.tools.filters.cache.database.get.datastore_key",
                return_value=parent.key,
            ) as datastore_key:
                with patch(
                    "lagniappe.core.tools.filters.cache.Entities.fetch",
                    return_value=[task],
                ) as load:
                    cache = FilterCache(parent, user=_user(task=["restricted"]))
                    cache._load_project_tasks()

    datastore_key.assert_called_once_with(parent)
    load.assert_called_once_with(
        "active-task-key",
        "completed-task-key",
        request=Fetch.nested(
            because=FetchReason.TASK_FILTER_INDEX_MATERIALIZATION
        ),
    )
    query = _FakeQuery.instances[0]
    assert query.source_filter.calls == [
        ("eq", "type", "task"),
        ("eq", "project", parent.key),
    ]
    assert query.orders == ["-modified"]
    assert cache._to_cache == {
        "task-hash": {
            "id": "task-key",
            "name": "Task",
            "completed": True,
        }
    }
