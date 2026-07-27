"""Root-depth collection discovery and permission-safe refresh deltas."""

from dataclasses import dataclass

from ..definitions import Action, Fetch, Resource
from ..entities import Entities, index
from . import database, utility
from .filters import FilterCache


MAX_REFRESH_ROWS = 10_000
SUPPORTED_INDEXES = frozenset({"tasks", "users"})
FINGERPRINTED_INDEXES = frozenset({"forms", "tasks", "users"})


class RefreshFallback(ValueError):
    """The target must use its established full-fragment refresh path."""


# @testable false
# @covered-by lagniappe/core/tools/refresh.py::load_refresh_view
# @reason immutable value object only carries the resolved view and fingerprint
@dataclass(frozen=True)
class RefreshView:
    """Loaded refresh identity and its cheap collection-level revision."""

    entity: object
    fingerprint: str | None


@dataclass(frozen=True)
class RefreshCollection:
    """Authoritative root membership plus the renderer context for one widget."""

    kind: str
    parent: object
    roots: tuple


@dataclass(frozen=True)
class RefreshDelta:
    """Authorized changed entities and structural operations for one widget."""

    upsert: tuple
    remove: tuple
    order: tuple


# @testable false
# @covered-by lagniappe/core/tools/refresh.py::load_refresh_collection
# @reason keyed view loading is owned by the allowlisted collection loader
def _view_entity(view):
    key = view.get("key")
    if not isinstance(key, str) or not key:
        return None
    return Entities.fetch_one(key, request=Fetch.direct())


# @testable true
# @tests tests_unit/test_021_refresh.py::test_load_refresh_view_uses_entity_or_site_index_fingerprint
# @features reconnect-refresh
# @dimensions root-fingerprint entity-view site-index
def load_refresh_view(view):
    """Resolve a refresh view once, before any collection membership queries."""
    if not isinstance(view, dict):
        raise RefreshFallback("Unsupported refresh view")

    key = view.get("key")
    entity = _view_entity(view)
    if isinstance(key, str) and key and entity is None:
        raise RefreshFallback("Refresh view no longer exists")
    if entity is not None:
        return RefreshView(entity, getattr(entity, "fingerprint", None))

    view_index = view.get("index")
    if view_index not in FINGERPRINTED_INDEXES:
        return RefreshView(None, None)
    return RefreshView(
        None,
        database.site_fingerprint(f"/{view_index}/index"),
    )


# @testable false
# @covered-by lagniappe/core/tools/refresh.py::load_refresh_collection
# @covered-by lagniappe/web/responses.py::task_combine_delta
# @reason page-task root ordering is exercised through its collection and delta consumers
def page_task_roots(page):
    roots = Entities.fetch(
        *database.get.page_tasks(page),
        request=Fetch.root(),
    )
    tasks = [task for task in roots if isinstance(task, Entities.TASK)]
    active = utility.sort_tasks([task for task in tasks if not task.completed])
    completed = sorted(
        [task for task in tasks if task.completed],
        key=lambda task: task.modified,
        reverse=True,
    )
    return active + completed


# @testable false
# @covered-by lagniappe/core/tools/refresh.py::load_refresh_collection
# @reason saved-filter cache refresh and ordering are owned by collection loading
def _filtered_roots(filter_entity, user):
    if not filter_entity.allowed(Action.VIEW, user=user):
        raise RefreshFallback("Filter context is no longer viewable")
    if not filter_entity.related_entities_allowed(user):
        raise RefreshFallback("Filter references are no longer viewable")

    parent = filter_entity.parent
    if not isinstance(parent, (Entities.PROJECT, Entities.CATEGORY)):
        raise RefreshFallback("Unsupported filter parent")

    filter_cache = FilterCache(parent, user=user)
    filter_cache.update(queue=False)
    roots = filter_cache.query_roots(filter_entity)
    if isinstance(parent, Entities.PROJECT):
        tasks = [root for root in roots if isinstance(root, Entities.TASK)]
        return "filtered-task-index", tuple(utility.sort_tasks(tasks))

    pages = [root for root in roots if isinstance(root, Entities.PAGE)]
    return "filtered-page-index", tuple(pages)


# @testable true
# @tests tests_unit/test_021_refresh.py::test_load_refresh_collection_resolves_component_from_view_entity
# @tests tests_unit/test_021_refresh.py::test_load_refresh_collection_refreshes_saved_filter_cache_before_root_query
# @features reconnect-refresh
# @dimensions target-validation root-depth component-identity
# @pair reconnect-refresh:target-validation
# @pair reconnect-refresh:root-depth
# @pair reconnect-refresh:component-identity
# @pair reconnect-refresh:cache-refresh
# @pair filters:cache-refresh
def load_refresh_collection(view, target, user, refresh_view=None):
    """Load one allowlisted collection without expanding its row relationships."""
    if not isinstance(view, dict) or not isinstance(target, dict):
        raise RefreshFallback("Unsupported refresh target")

    component_id = target.get("id")
    refresh_view = refresh_view or load_refresh_view(view)
    entity = refresh_view.entity

    if isinstance(entity, Entities.FILTER) and component_id == "table":
        if view.get("hash") != entity.hash:
            raise RefreshFallback("Filter view identity changed")
        kind, roots = _filtered_roots(entity, user)
        return RefreshCollection(kind, entity, roots)

    if isinstance(entity, Entities.PAGE) and component_id == "tasks":
        if not entity.allowed(Action.VIEW, user=user):
            raise RefreshFallback("Page task context is no longer viewable")
        return RefreshCollection(
            "page-tasks",
            entity,
            tuple(page_task_roots(entity)),
        )

    if isinstance(entity, Entities.CATEGORY) and component_id == "table":
        if not entity.allowed(Action.RESTRICTED, user=user):
            raise RefreshFallback("Page index context is no longer viewable")
        parent = index.PageIndex(entity=entity, user=user, limit=None)
        return RefreshCollection("page-index", parent, tuple(parent.refresh_roots()))

    view_index = view.get("index")
    if entity is not None or view_index not in SUPPORTED_INDEXES:
        raise RefreshFallback("Unsupported refresh view")

    if view_index == "tasks" and component_id == "table":
        if not user.has_permission(Resource.TASKS, Action.RESTRICTED):
            raise RefreshFallback("Task index is no longer viewable")
        parent = index.TaskIndex(user=user, limit=None)
        return RefreshCollection("task-index", parent, tuple(parent.refresh_roots()))

    if component_id != "table" or not user.has_permission(
        Resource.USERS,
        Action.VIEW,
    ):
        raise RefreshFallback("User index is no longer viewable")
    mode = view.get("mode")
    if mode not in {"regular", "public"}:
        raise RefreshFallback("Invalid user index mode")
    parent = index.UserIndex(user=user, mode=mode, limit=None)
    return RefreshCollection("user-index", parent, tuple(parent.refresh_roots()))


# @testable false
# @covered-by lagniappe/core/tools/refresh.py::resolve_refresh_delta
# @reason manifest validation is part of delta resolution
def _client_modified(rows):
    if not isinstance(rows, list) or len(rows) > MAX_REFRESH_ROWS:
        raise RefreshFallback("Invalid refresh row manifest")

    modified_rows = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RefreshFallback("Invalid refresh row")
        key = row.get("key")
        modified = row.get("modified")
        if not isinstance(key, str) or not key or not isinstance(modified, str):
            raise RefreshFallback("Invalid refresh row identity")
        if key in modified_rows:
            raise RefreshFallback("Duplicate refresh row")
        modified_rows[key] = modified
    return modified_rows


# @testable false
# @covered-by lagniappe/core/tools/refresh.py::resolve_refresh_delta
# @reason root modified serialization is part of delta comparison
def _modified_token(entity):
    modified = getattr(entity, "modified", None)
    if not modified or not hasattr(modified, "isoformat"):
        raise RefreshFallback("Refresh root has no modified timestamp")
    return modified.isoformat()


# @testable true
# @tests tests_unit/test_021_refresh.py::test_resolve_refresh_delta_expands_only_changed_roots_and_authorizes_before_upsert
# @features reconnect-refresh permissions
# @dimensions modified direct-depth authorization removal ordering
def resolve_refresh_delta(collection, rows, user):
    """Compare roots, then direct-fetch and authorize only changed/new rows."""
    client = _client_modified(rows)
    roots = {}
    for root in collection.roots:
        key = root.urlsafe_key
        roots.setdefault(key, root)

    changed = [
        root
        for key, root in roots.items()
        if client.get(key) != _modified_token(root)
    ]
    changed_keys = {root.urlsafe_key for root in changed}
    expanded = {
        entity.urlsafe_key: entity
        for entity in Entities.fetch(
            *(root.urlsafe_key for root in changed),
            request=Fetch.direct(),
        )
    }

    remove = set(client).difference(roots)
    upsert = []
    order = []
    for key, root in roots.items():
        if key not in changed_keys:
            order.append(key)
            continue

        entity = expanded.get(key)
        if entity and entity.allowed(Action.VIEW, user=user):
            upsert.append(entity)
            order.append(key)
        elif key in client:
            remove.add(key)

    return RefreshDelta(
        upsert=tuple(upsert),
        remove=tuple(key for key in client if key in remove),
        order=tuple(order),
    )
