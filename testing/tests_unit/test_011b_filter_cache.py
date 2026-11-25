from types import SimpleNamespace
from unittest.mock import call, patch

import pytest

from lagniappe.core.definitions import Action, Comparator, Fetch, FetchReason, FieldType, FilterDefinition, Restriction
from lagniappe.core.tools.filters.cache import FilterCache
from lagniappe.core.tools.filters.contract import CompiledFilter


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


@pytest.mark.unit
def test_filter_cache_uses_shared_cache_key_without_user_restrictions():
    parent = _parent("category")

    owner_cache = FilterCache(parent, user=_user(models=Restriction.UNRESTRICTED))
    restricted_cache = FilterCache(parent, user=_user(models=["category-a"]))

    assert owner_cache.cache_key == restricted_cache.cache_key
    assert owner_cache.cache_key.endswith(":all-v3")


@pytest.mark.unit
def test_filter_cache_query_filters_loaded_entities_by_view_permission():
    viewer = _user()
    parent = _parent("project")
    visible = SimpleNamespace(
        allowed=lambda action, user=None: action == Action.VIEW and user is viewer
    )
    hidden = SimpleNamespace(allowed=lambda action, user=None: False)
    entity_filter = CompiledFilter(
        definitions=(FilterDefinition("source", "completed", FieldType.BOOLEAN, Comparator.IS_FALSE, None, False),),
        contract={"version": 1, "conditions": []},
        related=(),
    )

    with patch(
        "lagniappe.core.tools.filters.cache.FilterExpression", _FilterExpression
    ), patch(
        "lagniappe.core.tools.filters.cache.filter_cache.query",
        return_value=["visible-key", "hidden-key"],
    ) as query, patch(
        "lagniappe.core.tools.filters.cache.Entities.fetch",
        return_value=[visible, hidden],
    ) as load:
        results = FilterCache(parent, user=viewer).query(entity_filter)

    query.assert_called_once_with(
        FilterCache(parent, user=viewer).cache_key,
        "$..filter-expression",
    )
    load.assert_called_once_with(
        "visible-key", "hidden-key", request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION)
    )
    assert results == [visible]


@pytest.mark.unit
def test_filter_cache_rejects_uncompiled_query_definitions():
    parent = _parent("project")

    with pytest.raises(TypeError, match="CompiledFilter"):
        FilterCache(parent, user=_user()).query(
            SimpleNamespace(definitions=["untrusted"])
        )


@pytest.mark.parametrize("comparator", [Comparator.EQUALS, Comparator.SUBSTRING])
@pytest.mark.parametrize("with_scope", [False, True])
def test_filter_cache_matches_escaped_string_literals_after_redis_predicates(monkeypatch, comparator, with_scope):
    from lagniappe.core.tools.filters import cache as module

    value = 'Dr. René [a+b] "quoted" \\folder\n'
    literal = FilterDefinition("source", "name", FieldType.STRING, comparator, value, False)
    scope = FilterDefinition("source", "completed", FieldType.BOOLEAN, Comparator.IS_FALSE, None, False)
    conditions = (scope, literal) if with_scope else (literal,)
    compiled = CompiledFilter(definitions=conditions, contract={}, related=())
    calls = []
    def query(_key, expression):
        calls.append(expression)
        return [
            {"id": "match", "name": value.upper()},
            {"id": "substring", "name": f"prefix {value} suffix"},
            {"id": "different", "name": value.replace("Dr.", "DrX")},
            {"id": "missing"}, {"id": "null", "name": None}, {"access": {}},
        ]
    monkeypatch.setattr(module.filter_cache, "query", query)
    keys = FilterCache(_parent("project"), user=_user())._query_keys(compiled)
    assert keys == (["match"] if comparator == Comparator.EQUALS else ["match", "substring"])
    assert len(calls) == 1
    assert "name" not in calls[0] and not calls[0].endswith(".id")
    assert ('"completed"' in calls[0]) is with_scope


@pytest.mark.unit
def test_filter_cache_loads_category_pages_without_restrictions():
    parent = _parent("category")
    pages_by_key = {
        "page-key-1": SimpleNamespace(
            hash="page-hash-1",
            to_filter_index=lambda: {"id": "page-key-1", "name": "Page 1"},
        ),
        "page-key-2": SimpleNamespace(
            hash="page-hash-2",
            to_filter_index=lambda: {"id": "page-key-2", "name": "Page 2"},
        ),
    }

    with patch(
        "lagniappe.core.tools.filters.cache.database_get.pages",
        side_effect=[
            SimpleNamespace(results=["page-key-1"], next_cursor="cursor-2"),
            SimpleNamespace(results=["page-key-2"], next_cursor=None),
        ],
    ) as pages, patch(
        "lagniappe.core.tools.filters.cache.Entities.fetch",
        side_effect=lambda *keys, **_kwargs: [pages_by_key[key] for key in keys],
    ):
        cache = FilterCache(parent, user=_user(models=["restricted"]))
        cache._load()

    assert pages.call_args_list == [
        call(
            parent.key,
            start_cursor=None,
            limit=100,
            hashes=Restriction.UNRESTRICTED,
        ),
        call(
            parent.key,
            start_cursor="cursor-2",
            limit=100,
            hashes=Restriction.UNRESTRICTED,
        ),
    ]
    assert cache._to_cache == {
        "page-hash-1": {"id": "page-key-1", "name": "Page 1"},
        "page-hash-2": {"id": "page-key-2", "name": "Page 2"},
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


@pytest.mark.unit
def test_filter_cache_loads_all_project_tasks_without_active_or_restriction_filters():
    parent = _parent("project")
    active = SimpleNamespace(
        hash="active-hash",
        to_filter_index=lambda: {"id": "active-task-key", "name": "Active", "completed": False},
    )
    task = SimpleNamespace(
        hash="task-hash",
        to_filter_index=lambda: {
            "id": "task-key",
            "name": "Task",
            "completed": True,
        },
    )
    _FakeQuery.instances = []

    with (
        patch("lagniappe.core.tools.filters.cache.Filter", _FakeFilter),
        patch("lagniappe.core.tools.filters.cache.Query", _FakeQuery),
        patch(
            "lagniappe.core.tools.filters.cache.database_get.datastore_key",
            return_value=parent.key,
        ) as datastore_key,
        patch(
            "lagniappe.core.tools.filters.cache.Entities.fetch",
            return_value=[active, task],
        ) as load,
    ):
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
        "active-hash": {"id": "active-task-key", "name": "Active", "completed": False},
        "task-hash": {
            "id": "task-key",
            "name": "Task",
            "completed": True,
        }
    }


def test_edits_completion_and_project_moves_keep_actual_filter_members(monkeypatch):
    from unittest.mock import MagicMock
    from lagniappe.core.tools.cache import add

    project = _parent("project")
    current = FilterCache(project, user=_user()).cache_key
    former = current.replace(project.hash, "former-project")
    rows = {current: {"edited": {}, "completed": {}}, former: {"moved": {}}}
    tasks = [
        SimpleNamespace(kind="task", hash=name, urlsafe_key=f"id-{name}", project=project,
                        required=["page-hash"], categories=[])
        for name in ("edited", "completed", "new", "moved")
    ]
    tasks[1].completed = True
    pipe = MagicMock()
    commands = pipe.__enter__.return_value.json.return_value
    commands.set.side_effect = lambda key, path, value: rows[key].update({path[2:]: value})
    commands.delete.side_effect = lambda key, path: rows[key].pop(path[2:])
    monkeypatch.setattr(add.cache, "pipeline", lambda: pipe)
    monkeypatch.setattr(add.filter_cache, "get_existing_parents", lambda hashes: {
        h: [key for key, members in rows.items() if h in members] for h in hashes
    })
    monkeypatch.setattr(add.filter_cache, "get_new_parents", lambda parents: [
        current for h in parents if h == project.hash
    ])

    add.update_json_index(tasks)

    assert rows[former] == {}
    assert rows[current] == {
        name: {"id": f"id-{name}", "cache_key": name, "refresh": 1}
        for name in ("edited", "completed", "new", "moved")
    }
