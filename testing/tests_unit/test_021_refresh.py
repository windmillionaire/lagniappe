from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.definitions import Fetch, Restriction
from lagniappe.core.entities import Entities
from lagniappe.core.entities.index import PageIndex, TaskIndex, UserIndex
from lagniappe.core.tools.refresh import (
    RefreshCollection,
    RefreshView,
    load_refresh_collection,
    load_refresh_view,
    resolve_refresh_delta,
)
from lagniappe.core.tools.filters import FilterCache
from testing.utility.test_entities import TestEntities


def _user_restrictions():
    return SimpleNamespace(
        task=Restriction.UNRESTRICTED,
        users=Restriction.UNRESTRICTED,
        unrestricted_pages=lambda _category: Restriction.UNRESTRICTED,
    )


def _viewer():
    return SimpleNamespace(
        is_authenticated=True,
        page=SimpleNamespace(key="viewer-page"),
        properties=SimpleNamespace(restrictions=_user_restrictions()),
        has_permission=lambda *_args: True,
    )


def _task(name, hash_value, modified, due_date=None):
    task = TestEntities.get(
        "TASK",
        {
            "name": name,
            "hash": hash_value,
            "page": {"name": f"{name} Page", "hash": f"p{hash_value}"},
            "modified": modified,
        },
    )
    if due_date:
        task.due_date = due_date
    return task


# @features reconnect-refresh
# @dimensions root-fingerprint entity-view site-index
@pytest.mark.unit
def test_load_refresh_view_uses_entity_or_site_index_fingerprint():
    category = SimpleNamespace(fingerprint="category-fingerprint")

    with patch(
        "lagniappe.core.tools.refresh._view_entity",
        side_effect=[category, None],
    ) as load_entity, patch(
        "lagniappe.core.tools.refresh.database.site_fingerprint",
        return_value="tasks-fingerprint",
    ) as site_fingerprint:
        category_view = load_refresh_view({"key": "category-key"})
        task_view = load_refresh_view({"index": "tasks"})

    assert category_view == RefreshView(category, "category-fingerprint")
    assert task_view == RefreshView(None, "tasks-fingerprint")
    assert load_entity.call_count == 2
    site_fingerprint.assert_called_once_with("/tasks/index")


# @features reconnect-refresh task-index
# @dimensions root-depth ordering
@pytest.mark.unit
def test_task_index_refresh_roots_uses_both_ordered_query_streams():
    now = datetime.now(timezone.utc)
    dated = _task("Dated", "refresh-task-1", now, now + timedelta(days=1))
    undated = _task("Undated", "refresh-task-2", now - timedelta(days=1))
    parent = TaskIndex(user=_viewer())

    with patch(
        "lagniappe.core.entities.index.database.get.tasks_with_due_dates",
        return_value=SimpleNamespace(results=["dated"]),
    ) as dated_query, patch(
        "lagniappe.core.entities.index.database.get.tasks_without_due_dates",
        return_value=SimpleNamespace(results=["undated"]),
    ) as undated_query, patch(
        "lagniappe.core.entities.index.Entities.fetch",
        return_value=[undated, dated],
    ) as fetch:
        roots = parent.refresh_roots()

    assert roots == [dated, undated]
    dated_query.assert_called_once_with(
        limit=None,
        project=None,
        hashes=Restriction.UNRESTRICTED,
        assigned_to=parent.user.page,
    )
    undated_query.assert_called_once_with(
        limit=None,
        project=None,
        hashes=Restriction.UNRESTRICTED,
        assigned_to=parent.user.page,
    )
    fetch.assert_called_once_with("dated", "undated", request=Fetch.root())


# @pairs reconnect-refresh:authenticated-access permissions:own-page-only
@pytest.mark.unit
def test_load_refresh_collection_allows_task_index_without_models_permission():
    viewer = _viewer()
    viewer.has_permission = lambda *_args: False
    root = SimpleNamespace(urlsafe_key="own-task", modified=datetime.now(timezone.utc))
    parent = SimpleNamespace(refresh_roots=lambda: [root])

    with patch(
        "lagniappe.core.tools.refresh.index.TaskIndex",
        return_value=parent,
    ) as task_index:
        collection = load_refresh_collection(
            {"index": "tasks"},
            {"id": "table"},
            viewer,
            refresh_view=RefreshView(None, "task-index-fingerprint"),
        )

    task_index.assert_called_once_with(user=viewer, limit=None)
    assert collection == RefreshCollection("task-index", parent, (root,))


# @features reconnect-refresh category-index
# @dimensions root-depth membership
@pytest.mark.unit
def test_page_index_refresh_roots_reuses_restricted_collection_query():
    category = TestEntities.get(
        "CATEGORY", {"name": "Refresh Category", "hash": "refresh-category"}
    )
    page = TestEntities.get(
        "PAGE", {"name": "Refresh Page", "hash": "refresh-page"}
    )
    restrictions = ["allowed-page"]
    viewer = _viewer()
    viewer.properties.restrictions.unrestricted_pages = (
        lambda candidate: restrictions if candidate is category else []
    )
    parent = PageIndex(entity=category, user=viewer)

    with patch(
        "lagniappe.core.entities.index.database.get.pages",
        return_value=SimpleNamespace(results=["page-key"]),
    ) as query, patch(
        "lagniappe.core.entities.index.Entities.fetch", return_value=[page]
    ) as fetch:
        roots = parent.refresh_roots()

    assert roots == [page]
    query.assert_called_once_with(category.key, limit=None, hashes=restrictions)
    fetch.assert_called_once_with("page-key", request=Fetch.root())


# @features reconnect-refresh user-index
# @dimensions root-depth mode
@pytest.mark.unit
def test_user_index_refresh_roots_preserves_regular_and_public_modes():
    regular = TestEntities.get(
        "USER",
        {
            "name": "Regular Refresh User",
            "hash": "refresh-user-regular",
            "page": {"name": "Regular Page", "hash": "refresh-user-page-1"},
        },
    )
    public = TestEntities.get(
        "USER",
        {
            "name": "Public Refresh User",
            "hash": "refresh-user-public",
            "public": True,
            "page": {"name": "Public Page", "hash": "refresh-user-page-2"},
        },
    )
    public_group = TestEntities.get(
        "PUBLIC_GROUP", {"name": "public", "hash": "refresh-public-group"}
    )

    regular_index = UserIndex(user=_viewer())
    public_index = UserIndex(user=_viewer(), mode="public")
    public_index._public_users_enabled = True
    public_index._public_group = public_group

    with patch(
        "lagniappe.core.entities.index.database.get.users",
        side_effect=[
            SimpleNamespace(results=["regular", "public"]),
            SimpleNamespace(results=["regular", "public"]),
        ],
    ) as query, patch(
        "lagniappe.core.entities.index.Entities.fetch",
        side_effect=[[regular, public], [regular, public]],
    ) as fetch:
        regular_roots = regular_index.refresh_roots()
        public_roots = public_index.refresh_roots()

    assert regular_roots == [regular]
    assert public_roots == [public]
    assert query.call_args_list[0].kwargs == {
        "hashes": Restriction.UNRESTRICTED,
        "limit": None,
    }
    assert query.call_args_list[1].kwargs == {
        "group": public_group.key,
        "limit": None,
    }
    assert all(call.kwargs == {"request": Fetch.root()} for call in fetch.call_args_list)


# @features reconnect-refresh permissions
# @dimensions modified direct-depth authorization removal ordering
@pytest.mark.unit
def test_resolve_refresh_delta_expands_only_changed_roots_and_authorizes_before_upsert():
    unchanged = SimpleNamespace(
        urlsafe_key="a", modified=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    changed = SimpleNamespace(
        urlsafe_key="b", modified=datetime(2026, 1, 2, tzinfo=timezone.utc)
    )
    rejected = SimpleNamespace(
        urlsafe_key="c", modified=datetime(2026, 1, 3, tzinfo=timezone.utc)
    )
    changed_full = SimpleNamespace(
        urlsafe_key="b",
        allowed=lambda *_args, **_kwargs: True,
    )
    rejected_full = SimpleNamespace(
        urlsafe_key="c",
        allowed=lambda *_args, **_kwargs: False,
    )
    collection = RefreshCollection(
        kind="task-index",
        parent=None,
        roots=(unchanged, changed, rejected),
    )
    rows = [
        {"key": "a", "modified": unchanged.modified.isoformat()},
        {"key": "b", "modified": "old"},
        {"key": "deleted", "modified": "old"},
    ]

    with patch(
        "lagniappe.core.tools.refresh.Entities.fetch",
        return_value=[changed_full, rejected_full],
    ) as fetch:
        delta = resolve_refresh_delta(collection, rows, _viewer())

    fetch.assert_called_once_with("b", "c", request=Fetch.direct())
    assert delta.upsert == (changed_full,)
    assert delta.remove == ("deleted",)
    assert delta.order == ("a", "b")


# @features reconnect-refresh
# @dimensions target-validation root-depth component-identity
@pytest.mark.unit
def test_load_refresh_collection_resolves_component_from_view_entity():
    page = TestEntities.get(
        "PAGE", {"name": "Refresh Context", "hash": "refresh-context"}
    )
    page.allowed = lambda *_args, **_kwargs: True
    roots = (SimpleNamespace(urlsafe_key="task", modified=datetime.now(timezone.utc)),)
    view = {"key": page.urlsafe_key, "index": None}
    target = {"id": "tasks"}

    with patch(
        "lagniappe.core.tools.refresh.Entities.fetch_one", return_value=page
    ) as fetch_page, patch(
        "lagniappe.core.tools.refresh.page_task_roots", return_value=list(roots)
    ) as task_roots:
        collection = load_refresh_collection(view, target, _viewer())

    fetch_page.assert_called_once_with(page.urlsafe_key, request=Fetch.direct())
    task_roots.assert_called_once_with(page)
    assert collection == RefreshCollection("page-tasks", page, roots)


# @features reconnect-refresh filters
# @dimensions root-depth membership
@pytest.mark.unit
def test_filter_cache_query_roots_uses_root_fetch_without_permission_expansion():
    parent = SimpleNamespace(hash="refresh-filter-parent")
    filter_entity = SimpleNamespace(definitions=[])
    filter_cache = FilterCache(parent, user=_viewer())

    with patch.object(
        filter_cache, "_query_keys", return_value=["first", "second"]
    ) as query, patch(
        "lagniappe.core.tools.filters.cache.Entities.fetch",
        return_value=["first-root", "second-root"],
    ) as fetch:
        roots = filter_cache.query_roots(filter_entity)

    query.assert_called_once_with(filter_entity)
    fetch.assert_called_once_with("first", "second", request=Fetch.root())
    assert roots == ["first-root", "second-root"]


# @pair reconnect-refresh:cache-refresh
# @pair reconnect-refresh:root-depth
# @pair reconnect-refresh:component-identity
# @pair filters:cache-refresh
@pytest.mark.unit
def test_load_refresh_collection_refreshes_saved_filter_cache_before_root_query():
    project = TestEntities.get(
        "PROJECT", {"name": "Refresh Filter Project", "hash": "filter-project"}
    )
    task = _task(
        "Filtered Root",
        "filtered-root",
        datetime.now(timezone.utc),
    )
    filter_entity = Entities.FILTER(testing=True)
    filter_entity.db["hash"] = "saved-filter"
    filter_entity.parent = project
    filter_entity.allowed = lambda *_args, **_kwargs: True
    filter_entity.related_entities_allowed = lambda *_args, **_kwargs: True
    filter_cache = SimpleNamespace(
        update=lambda **_kwargs: None,
        query_roots=lambda _filter: [task],
    )
    viewer = _viewer()

    with patch(
        "lagniappe.core.tools.refresh._view_entity", return_value=filter_entity
    ), patch(
        "lagniappe.core.tools.refresh.FilterCache", return_value=filter_cache
    ) as cache_type, patch.object(
        filter_cache, "update", wraps=filter_cache.update
    ) as update, patch.object(
        filter_cache, "query_roots", wraps=filter_cache.query_roots
    ) as query:
        collection = load_refresh_collection(
            {"key": "filter-key", "hash": "saved-filter"},
            {"id": "table"},
            viewer,
        )

    cache_type.assert_called_once_with(project, user=viewer)
    update.assert_called_once_with(queue=False)
    query.assert_called_once_with(filter_entity)
    assert collection == RefreshCollection(
        "filtered-task-index", filter_entity, (task,)
    )
