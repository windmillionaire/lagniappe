from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.definitions import Fetch, FetchReason, Restriction
from lagniappe.core.entities import Entities
from lagniappe.core.entities.index import PageIndex, TaskIndex, UserIndex
from lagniappe.core.tools.polling.refresh import (
    RefreshCollection,
    RefreshView,
    RefreshFallback,
    load_refresh_collection,
    load_refresh_view,
    resolve_refresh_delta,
)
from lagniappe.core.tools.filters import FilterCache
from lagniappe.core.tools.filters.contract import CompiledFilter
from testing.utility.test_entities import TestEntities
from lagniappe.core.tools.cache.add import _redis_details



@pytest.fixture(autouse=True)
def cached_refresh_boundaries(monkeypatch):
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._load_cached_details", lambda _hashes: {})
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh.channel_revisions", lambda channels, _user: {channel: "tasks-revision" for channel in channels})


def _cached_row(entity, fingerprint=None):
    details = _redis_details(entity)
    if fingerprint is not None:
        details["fingerprint"] = fingerprint
    return details


def _manifest(entity):
    return {"key": entity.urlsafe_key, "hash": entity.hash, "fingerprint": entity.fingerprint}


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


# @matrix reconnect-refresh : entity-view root-fingerprint site-index
@pytest.mark.unit
def test_load_refresh_view_uses_entity_or_site_index_fingerprint():
    category = SimpleNamespace(fingerprint="category-fingerprint")

    with (
        patch(
            "lagniappe.core.tools.polling.refresh._view_entity",
            side_effect=[category, None],
        ) as load_entity,
        patch(
            "lagniappe.core.tools.polling.refresh.database_utility.site_fingerprint",
            return_value="tasks-fingerprint",
        ) as site_fingerprint,
    ):
        category_view = load_refresh_view({"key": "category-key"})
        task_view = load_refresh_view({"index": "tasks"})

    assert category_view == RefreshView(category, "category-fingerprint")
    assert task_view == RefreshView(None, "tasks-fingerprint")
    assert load_entity.call_count == 2
    site_fingerprint.assert_called_once_with("/tasks/index")


# @matrix filters polling : saved-filter permissions revision
@pytest.mark.unit
def test_saved_filter_refresh_reauthorizes_unchanged_rows_after_viewer_change(monkeypatch):
    from lagniappe.core.tools.polling.projections import filter_result_revision

    parent = TestEntities.get("PROJECT", {"hash": "reauthorize-project"})
    entity = Entities.FILTER(testing=True)
    entity.parent = parent
    entity.modified = parent.modified
    viewer = SimpleNamespace(authorization_fingerprint="before")
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._view_entity", lambda _view: entity)
    monkeypatch.setattr("lagniappe.core.tools.polling.projections.database_utility.site_fingerprint", lambda _path: "tasks")
    view = {"key": "filter", "fingerprint": filter_result_revision(entity, viewer), "authorization": "before"}
    initial = load_refresh_view(view, viewer)
    assert initial.reauthorize is False
    assert initial.fingerprint == view["fingerprint"]
    viewer.authorization_fingerprint = "after"
    loaded = load_refresh_view(view, viewer)
    assert loaded.reauthorize is True
    assert loaded.fingerprint != view["fingerprint"]

    task = _task("Hidden now", "reauthorize-task", parent.modified)
    task.allowed = lambda _action, user: False
    collection = RefreshCollection("filtered-task-index", entity, (task,))
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._load_cached_details", lambda _hashes: {task.hash: _cached_row(task)})
    monkeypatch.setattr(Entities, "fetch", lambda *_keys, request: [task])
    delta = resolve_refresh_delta(collection, [_manifest(task)], viewer,
                                  reauthorize=loaded.reauthorize)
    assert delta.remove == (task.urlsafe_key,)
    assert delta.order == delta.upsert == ()
    task.allowed = lambda _action, user: True
    delta = resolve_refresh_delta(collection, [_manifest(task)], viewer,
                                  reauthorize=True)
    assert delta.order == (task.urlsafe_key,)
    assert delta.remove == delta.upsert == ()


# @matrix reconnect-refresh task-index : ordering root-depth
@pytest.mark.unit
def test_task_index_refresh_roots_uses_both_ordered_query_streams():
    now = datetime.now(timezone.utc)
    dated = _task("Dated", "refresh-task-1", now, now + timedelta(days=1))
    undated = _task("Undated", "refresh-task-2", now - timedelta(days=1))
    parent = TaskIndex(user=_viewer())

    with (
        patch(
            "lagniappe.core.entities.index.database_get.tasks_with_due_dates",
            return_value=SimpleNamespace(results=["dated"]),
        ) as dated_query,
        patch(
            "lagniappe.core.entities.index.database_get.tasks_without_due_dates",
            return_value=SimpleNamespace(results=["undated"]),
        ) as undated_query,
        patch(
            "lagniappe.core.entities.index.Entities.fetch",
            return_value=[undated, dated],
        ) as fetch,
    ):
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


# @pairs permissions:own-page-only reconnect-refresh:authenticated-access
@pytest.mark.unit
def test_load_refresh_collection_allows_task_index_without_models_permission():
    viewer = _viewer()
    viewer.has_permission = lambda *_args: False
    root = SimpleNamespace(urlsafe_key="own-task", modified=datetime.now(timezone.utc))
    parent = SimpleNamespace(refresh_roots=lambda: [root])

    with patch(
        "lagniappe.core.tools.polling.refresh.index.TaskIndex",
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


# @matrix category-index reconnect-refresh : membership root-depth
@pytest.mark.unit
def test_page_index_refresh_roots_reuses_restricted_collection_query():
    category = TestEntities.get(
        "CATEGORY", {"name": "Refresh Category", "hash": "refresh-category"}
    )
    page = TestEntities.get("PAGE", {"name": "Refresh Page", "hash": "refresh-page"})
    restrictions = ["allowed-page"]
    viewer = _viewer()
    viewer.properties.restrictions.unrestricted_pages = lambda candidate: (
        restrictions if candidate is category else []
    )
    parent = PageIndex(entity=category, user=viewer)

    with (
        patch(
            "lagniappe.core.entities.index.database_get.pages",
            return_value=SimpleNamespace(results=["page-key"]),
        ) as query,
        patch(
            "lagniappe.core.entities.index.Entities.fetch", return_value=[page]
        ) as fetch,
    ):
        roots = parent.refresh_roots()

    assert roots == [page]
    query.assert_called_once_with(category.key, limit=None, hashes=restrictions)
    fetch.assert_called_once_with("page-key", request=Fetch.root())


# @matrix reconnect-refresh user-index : mode root-depth page-canonical
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

    with (
        patch(
            "lagniappe.core.entities.index.database_get.users",
            side_effect=[
                SimpleNamespace(results=["regular", "public"]),
                SimpleNamespace(results=["regular", "public"]),
            ],
        ) as query,
        patch(
            "lagniappe.core.entities.index.Entities.fetch",
            side_effect=[[regular, public], [regular.page], [regular, public], [public.page]],
        ) as fetch,
    ):
        regular_roots = regular_index.refresh_roots()
        public_roots = public_index.refresh_roots()

    assert regular_roots == [regular.page]
    assert public_roots == [public.page]
    assert query.call_args_list[0].kwargs == {
        "hashes": Restriction.UNRESTRICTED,
        "limit": None,
    }
    assert query.call_args_list[1].kwargs == {
        "group": public_group.key,
        "limit": None,
    }
    assert all(
        call.kwargs == {"request": Fetch.root()} for call in fetch.call_args_list
    )
    assert fetch.call_args_list[1].args == (regular.page.key,)
    assert fetch.call_args_list[3].args == (public.page.key,)


# @matrix permissions reconnect-refresh : authorization direct-depth modified ordering removal
@pytest.mark.unit
def test_resolve_refresh_delta_expands_only_changed_roots_and_authorizes_before_upsert():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    unchanged = _task("Unchanged", "a", now)
    changed = _task("Changed", "b", now + timedelta(days=1))
    rejected = _task("Rejected", "c", now + timedelta(days=2))
    changed.allowed = lambda *_args, **_kwargs: True
    rejected.allowed = lambda *_args, **_kwargs: False
    collection = RefreshCollection("task-index", None, (unchanged, changed, rejected))
    rows = [_manifest(unchanged), {**_manifest(changed), "fingerprint": "old"},
            {"key": "deleted", "hash": "deleted", "fingerprint": "old"}]
    cached = {root.hash: _cached_row(root) for root in collection.roots}
    with patch("lagniappe.core.tools.polling.refresh._load_cached_details", return_value=cached) as cache_read, patch(
        "lagniappe.core.tools.polling.refresh.Entities.fetch", return_value=[changed, rejected]
    ) as fetch:
        delta = resolve_refresh_delta(collection, rows, _viewer())

    cache_read.assert_called_once_with(["a", "b", "c"])
    fetch.assert_called_once_with(changed, rejected, request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
    assert delta.upsert == (changed,)
    assert delta.remove == ("deleted",)
    assert delta.order == (unchanged.urlsafe_key, changed.urlsafe_key)


# @matrix reconnect-refresh : component-identity root-depth target-validation
@pytest.mark.unit
def test_load_refresh_collection_resolves_component_from_view_entity():
    page = TestEntities.get(
        "PAGE", {"name": "Refresh Context", "hash": "refresh-context"}
    )
    page.allowed = lambda *_args, **_kwargs: True
    roots = (SimpleNamespace(urlsafe_key="task", modified=datetime.now(timezone.utc)),)
    view = {"key": page.urlsafe_key, "index": None}
    target = {"id": "tasks"}

    with (
        patch(
            "lagniappe.core.tools.polling.refresh.Entities.fetch_one", return_value=page
        ) as fetch_page,
        patch(
            "lagniappe.core.tools.polling.refresh.page_task_roots",
            return_value=list(roots),
        ) as task_roots,
    ):
        collection = load_refresh_collection(view, target, _viewer())

    fetch_page.assert_called_once_with(page.urlsafe_key, request=Fetch.direct())
    task_roots.assert_called_once_with(page)
    assert collection == RefreshCollection("page-tasks", page, roots)


# @matrix filters reconnect-refresh : membership root-depth
@pytest.mark.unit
def test_filter_cache_query_roots_uses_root_fetch_without_permission_expansion():
    parent = SimpleNamespace(hash="refresh-filter-parent")
    filter_entity = SimpleNamespace(definitions=[])
    filter_cache = FilterCache(parent, user=_viewer())

    with (
        patch.object(
            filter_cache, "_query_keys", return_value=["first", "second"]
        ) as query,
        patch(
            "lagniappe.core.tools.filters.cache.Entities.fetch",
            return_value=["first-root", "second-root"],
        ) as fetch,
    ):
        roots = filter_cache.query_roots(filter_entity)

    query.assert_called_once_with(filter_entity)
    fetch.assert_called_once_with("first", "second", request=Fetch.root())
    assert roots == ["first-root", "second-root"]


# @matrix reconnect-refresh : cache-refresh component-identity root-depth
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
    compiled = CompiledFilter(
        definitions=(),
        contract={"version": 1, "conditions": []},
        related=(),
    )
    filter_entity.compile = lambda _user: compiled
    filter_cache = SimpleNamespace(
        update=lambda **_kwargs: None,
        query_roots=lambda _filter: [task],
    )
    viewer = _viewer()

    with (
        patch(
            "lagniappe.core.tools.polling.refresh._view_entity",
            return_value=filter_entity,
        ),
        patch(
            "lagniappe.core.tools.polling.refresh.FilterCache",
            return_value=filter_cache,
        ) as cache_type,
        patch.object(filter_cache, "update", wraps=filter_cache.update) as update,
        patch.object(
            filter_cache, "query_roots", wraps=filter_cache.query_roots
        ) as query,
    ):
        collection = load_refresh_collection(
            {"key": "filter-key", "hash": "saved-filter"},
            {"id": "table"},
            viewer,
        )

    cache_type.assert_called_once_with(project, user=viewer)
    update.assert_called_once_with(queue=False)
    query.assert_called_once_with(compiled)
    assert collection == RefreshCollection(
        "filtered-task-index", filter_entity, (task,)
    )


# @matrix permissions reconnect-refresh : authorization modified removal
# @source lagniappe/core/tools/polling/refresh.py::resolve_refresh_delta
@pytest.mark.unit
@pytest.mark.parametrize("cache_state", ["missing", "wrong-key", "wrong-kind", "stale-base", "restriction-change"])
def test_refresh_cache_holes_and_changed_restrictions_require_authorization(monkeypatch, cache_state):
    task = _task("Cached task", "cache-refresh", datetime(2026, 1, 1, tzinfo=timezone.utc))
    details = _cached_row(task)
    rows = [_manifest(task)]
    if cache_state == "missing":
        details = {}
    elif cache_state == "wrong-key":
        details["id"] = "another-entity"
    elif cache_state == "wrong-kind":
        details["kind"] = "page"
    elif cache_state == "stale-base":
        details["modified"] = "older-base"
    else:
        details["fingerprint"] = "new-restriction-fingerprint"
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._load_cached_details", lambda _hashes: {task.hash: details})
    task.allowed = lambda *_args, **_kwargs: False
    with patch.object(Entities, "fetch", return_value=[task]) as fetch:
        delta = resolve_refresh_delta(RefreshCollection("task-index", None, (task,)), rows, _viewer())
    assert fetch.call_count == 1
    assert delta.remove == (task.urlsafe_key,)
    assert delta.upsert == delta.order == ()


# @matrix permissions reconnect-refresh : authorization modified
# @matrix permissions cache : identity user-page no-extra-read
@pytest.mark.unit
@pytest.mark.parametrize("kind", ["task", "page", "user-page"])
def test_warm_refresh_preserves_rows_without_expanding_relations(monkeypatch, kind):
    modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    if kind == "task":
        entity = _task("Unchanged", "warm-refresh", modified)
    else:
        spec = {"name": "Unchanged", "hash": "warm-refresh", "modified": modified}
        if kind == "user-page":
            spec["user"] = {"name": "Viewer", "hash": "warm-refresh-user"}
        entity = TestEntities.get("PAGE", spec)
    details = _cached_row(entity)
    assert details["id"] == entity.urlsafe_key
    assert details["kind"] == ("user" if kind == "user-page" else kind)
    assert "entity_key" not in details and "entity_kind" not in details
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._load_cached_details", lambda _hashes: {entity.hash: details})
    with patch.object(Entities, "fetch", return_value=[]) as fetch:
        delta = resolve_refresh_delta(RefreshCollection("task-index" if kind == "task" else "page-index", None, (entity,)), [_manifest(entity)], _viewer())
    fetch.assert_not_called()
    assert delta.order == (entity.urlsafe_key,)
    assert delta.upsert == delta.remove == ()


# @matrix reconnect-refresh : entity-view root-fingerprint
# @source lagniappe/core/tools/polling/refresh.py::load_refresh_view
@pytest.mark.unit
def test_page_refresh_tracks_tasks_separately_from_page_fingerprint(monkeypatch):
    page = TestEntities.get("PAGE", {"name": "Page", "hash": "page-refresh"})
    viewer = SimpleNamespace(authorization_fingerprint="viewer")
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._view_entity", lambda _view: page)
    loaded = load_refresh_view({"key": page.urlsafe_key, "authorization": "viewer"}, viewer)
    assert loaded.fingerprint == page.fingerprint
    assert loaded.collection_revision == "tasks-revision"
    assert loaded.reauthorize is False


# @matrix reconnect-refresh : target-validation
# @source lagniappe/core/tools/polling/refresh.py::resolve_refresh_delta
@pytest.mark.unit
def test_legacy_refresh_manifest_falls_back_instead_of_trusting_timestamps():
    with pytest.raises(RefreshFallback):
        resolve_refresh_delta(RefreshCollection("task-index", None, ()), [{"key": "old", "modified": "date"}], _viewer())


# @matrix reconnect-refresh : root-fingerprint membership no-extra-read
# @source lagniappe/core/tools/polling/refresh.py::load_refresh_collection
# @source lagniappe/core/tools/polling/refresh.py::resolve_refresh_delta
@pytest.mark.unit
@pytest.mark.parametrize("change", [None, "parent", "authorization", "collection"])
def test_refresh_reuses_membership_only_while_all_parent_revisions_match(monkeypatch, change):
    category = TestEntities.get("CATEGORY", {"name": "Cached membership", "hash": "category"})
    category.allowed = lambda *_args, **_kwargs: True
    page = TestEntities.get("PAGE", {"name": "Existing page", "hash": "page"})
    view = {"key": category.urlsafe_key, "fingerprint": category.fingerprint}
    loaded = RefreshView(
        category,
        "new-parent" if change == "parent" else category.fingerprint,
        reauthorize=change == "authorization",
        collection_revision="new-collection" if change == "collection" else None,
    )
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._load_cached_details",
                        lambda _hashes: {page.hash: _cached_row(page)})
    page.allowed = lambda *_args, **_kwargs: True
    with patch.object(PageIndex, "refresh_roots", return_value=[page]) as query, patch.object(
        Entities, "fetch", return_value=[page]
    ) as fetch:
        collection = load_refresh_collection(view, {"id": "table"}, _viewer(), loaded)
        delta = resolve_refresh_delta(collection, [_manifest(page)], _viewer(),
                                      reauthorize=loaded.reauthorize)
    if change:
        query.assert_called_once_with()
    else:
        query.assert_not_called()
        assert collection.roots is None
    if change == "authorization":
        assert fetch.call_count == 1
    else:
        fetch.assert_not_called()
    assert delta.order == (page.urlsafe_key,)
    assert delta.upsert == delta.remove == ()


# @matrix reconnect-refresh permissions : cached-fingerprint authorization no-extra-read
# @source lagniappe/core/tools/polling/refresh.py::resolve_refresh_delta
@pytest.mark.unit
def test_unchanged_parent_refresh_loads_only_rows_with_changed_cached_fingerprints(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    unchanged = _task("Unchanged", "same", now)
    changed = _task("Changed", "changed", now)
    hidden = _task("Newly hidden", "hidden", now)
    changed.allowed = lambda *_args, **_kwargs: True
    hidden.allowed = lambda *_args, **_kwargs: False
    rows = [_manifest(task) for task in (unchanged, changed, hidden)]
    cached = {task.hash: _cached_row(task) for task in (unchanged, changed, hidden)}
    cached[changed.hash]["fingerprint"] = "new-form-version"
    cached[hidden.hash]["fingerprint"] = "new-restrictions"
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._load_cached_details", lambda _hashes: cached)
    with patch.object(Entities, "fetch", return_value=[changed, hidden]) as fetch:
        delta = resolve_refresh_delta(RefreshCollection("task-index", None, None), rows, _viewer())
    fetch.assert_called_once_with(changed.urlsafe_key, hidden.urlsafe_key,
                                  request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
    assert delta.upsert == (changed,)
    assert delta.remove == (hidden.urlsafe_key,)
    assert delta.order == (unchanged.urlsafe_key, changed.urlsafe_key)


# @matrix reconnect-refresh user-index : page-canonical authorization
# @source lagniappe/core/tools/polling/refresh.py::resolve_refresh_delta
@pytest.mark.unit
@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("unchanged_parent", [True, False])
def test_user_index_refresh_authorizes_page_projection_through_its_user(monkeypatch, allowed, unchanged_parent):
    page = TestEntities.get("PAGE", {
        "name": "User Page", "hash": "user-page", "user": {"name": "Member"},
    })
    page.allowed = lambda *_args, **_kwargs: pytest.fail("User row must use User authorization")
    page.user.allowed = lambda *_args, **_kwargs: allowed
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._load_cached_details",
                        lambda _hashes: {page.hash: _cached_row(page, "changed")})
    with patch.object(Entities, "fetch", return_value=[page]):
        delta = resolve_refresh_delta(RefreshCollection("user-index", None, None if unchanged_parent else (page,)),
                                      [_manifest(page)], _viewer())
    assert delta.upsert == ((page,) if allowed else ())
    assert delta.order == ((page.urlsafe_key,) if allowed else ())
    assert delta.remove == (() if allowed else (page.urlsafe_key,))


# @matrix user-index : page-canonical user-fields no-extra-read
# @source lagniappe/core/tools/polling/refresh.py::resolve_refresh_delta
@pytest.mark.unit
def test_user_index_revision_refreshes_user_fields_with_unchanged_page_fingerprint(monkeypatch):
    modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    page = TestEntities.get("PAGE", {
        "name": "User Page", "hash": "profile-page", "modified": modified,
        "user": {"name": "Member", "hash": "profile-user", "modified": modified},
    })
    rows = [_manifest(page)]
    cached = _cached_row(page)
    page.user.email = "updated@example.test"
    page.user.last_login = modified + timedelta(days=1)
    page.user.modified = modified + timedelta(days=1)
    page.user.allowed = lambda *_args, **_kwargs: True
    assert page.fingerprint == rows[0]["fingerprint"] == cached["fingerprint"]
    monkeypatch.setattr("lagniappe.core.tools.polling.refresh._load_cached_details",
                        lambda _hashes: {page.hash: cached})

    with patch.object(Entities, "fetch", return_value=[page]) as fetch:
        delta = resolve_refresh_delta(RefreshCollection("user-index", None, (page,)),
                                      rows, _viewer())
    fetch.assert_called_once_with(page, request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
    assert delta.upsert == (page,)
    assert delta.upsert[0].user.email == "updated@example.test"
    assert delta.upsert[0].user.last_login == modified + timedelta(days=1)
    assert delta.order == (page.urlsafe_key,)
    assert delta.remove == ()

    with patch.object(Entities, "fetch") as fetch:
        unchanged = resolve_refresh_delta(RefreshCollection("user-index", None, None),
                                          rows, _viewer())
    fetch.assert_not_called()
    assert unchanged.order == (page.urlsafe_key,)
    assert unchanged.upsert == unchanged.remove == ()
