"""Root-depth collection discovery and cached-fingerprint refresh deltas."""

from collections.abc import Mapping

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.user import User
    from lagniappe.core.entities.page import Page

from dataclasses import dataclass

from lagniappe.core import exceptions

from ...definitions import Action, Fetch, FetchReason, Resource
from ...definitions.fingerprints import base_fingerprint, restricted_fingerprint
from ...entities import Entities, index
from lagniappe.core.tools.database import utility as database_utility
from .. import cache
from ..cache.details import _load_cached_details, identify_entity
from ..filters import FilterCache
from ..tasks.ordering import page_task_roots, sort_tasks
from .projections import channel_revisions, filter_result_revision


MAX_REFRESH_ROWS = 10_000
SUPPORTED_INDEXES = frozenset({"tasks", "users"})
FINGERPRINTED_INDEXES = frozenset({"forms", "tasks", "users"})


class RefreshFallback(ValueError):
    """The target must use its established full-fragment refresh path."""


@dataclass(frozen=True)
class RefreshView:
    """Loaded refresh identity and its cheap collection-level revision."""

    entity: Entity | None
    fingerprint: str | None
    reauthorize: bool = False
    authorization: str | None = None
    collection_revision: str | None = None

    def matches(self, view: Mapping[str, object]) -> bool:
        return (
            bool(view.get("fingerprint"))
            and view.get("fingerprint") == self.fingerprint
            and not self.reauthorize
            and view.get("collection_revision") == self.collection_revision
        )


@dataclass(frozen=True)
class RefreshCollection:
    """Renderer context and roots; unchanged membership reuses the client rows."""

    kind: str
    parent: Entity | index.Index
    roots: tuple[Entity, ...] | None


@dataclass(frozen=True)
class RefreshDelta:
    """Authorized changed entities and structural operations for one widget."""

    upsert: tuple[Entity, ...]
    remove: tuple[str, ...]
    order: tuple[str, ...]


def _view_entity(view):
    key = view.get("key")
    if not isinstance(key, str) or not key:
        return None
    return Entities.fetch_one(key, request=Fetch.direct())


def load_refresh_view(view: object, user: User | None = None) -> RefreshView:
    """Resolve a refresh view once, before any collection membership queries."""
    if not isinstance(view, dict):
        raise RefreshFallback("Unsupported refresh view")

    key = view.get("key")
    authorization = getattr(user, "authorization_fingerprint", None)
    reauthorize = authorization is not None and view.get("authorization") != authorization
    entity = _view_entity(view)
    if isinstance(key, str) and key and entity is None:
        raise RefreshFallback("Refresh view no longer exists")
    if entity is not None:
        if isinstance(entity, Entities.FILTER) and user is not None:
            return RefreshView(
                entity, filter_result_revision(entity, user), reauthorize, authorization,
            )
        return RefreshView(
            entity, getattr(entity, "fingerprint", None),
            reauthorize=reauthorize, authorization=authorization,
            collection_revision=(
                channel_revisions(("tasks",), user)["tasks"]
                if isinstance(entity, Entities.PAGE) and user is not None else None
            ),
        )

    view_index = view.get("index")
    if view_index not in FINGERPRINTED_INDEXES:
        return RefreshView(None, None, reauthorize, authorization)
    if view_index == "tasks" and user is not None:
        return RefreshView(
            None, channel_revisions(("tasks",), user)["tasks"], reauthorize, authorization,
        )
    return RefreshView(
        None,
        database_utility.site_fingerprint(f"/{view_index}/index"),
        reauthorize, authorization,
    )


def _filtered_roots(filter_entity, user, *, unchanged=False):
    if not filter_entity.allowed(Action.VIEW, user=user):
        raise RefreshFallback("Filter context is no longer viewable")
    if not filter_entity.related_entities_allowed(user):
        raise RefreshFallback("Filter references are no longer viewable")

    parent = filter_entity.parent
    if not isinstance(parent, (Entities.PROJECT, Entities.CATEGORY)):
        raise RefreshFallback("Unsupported filter parent")

    if unchanged:
        kind = (
            "filtered-task-index"
            if isinstance(parent, Entities.PROJECT) else "filtered-page-index"
        )
        return kind, None

    try:
        compiled = filter_entity.compile(user)
    except exceptions.ValidationError as error:
        raise RefreshFallback("Filter definition is no longer valid") from error

    filter_cache = FilterCache(parent, user=user)
    filter_cache.update(queue=False)
    roots = filter_cache.query_roots(compiled)
    if isinstance(parent, Entities.PROJECT):
        tasks = [root for root in roots if isinstance(root, Entities.TASK)]
        return "filtered-task-index", tuple(sort_tasks(tasks))

    pages = [root for root in roots if isinstance(root, Entities.PAGE)]
    return "filtered-page-index", tuple(pages)


def load_refresh_collection(view: object, target: object, user: User, refresh_view: RefreshView | None = None) -> RefreshCollection:
    """Load one allowlisted collection without expanding its row relationships."""
    if not isinstance(view, dict) or not isinstance(target, dict):
        raise RefreshFallback("Unsupported refresh target")

    component_id = target.get("id")
    refresh_view = refresh_view or load_refresh_view(view)
    entity = refresh_view.entity
    unchanged = refresh_view.matches(view)

    if isinstance(entity, Entities.FILTER) and component_id == "table":
        if view.get("hash") != entity.hash:
            raise RefreshFallback("Filter view identity changed")
        kind, roots = _filtered_roots(entity, user, unchanged=unchanged)
        return RefreshCollection(kind, entity, roots)

    if isinstance(entity, Entities.PAGE) and component_id == "tasks":
        if not entity.allowed(Action.VIEW, user=user):
            raise RefreshFallback("Page task context is no longer viewable")
        return RefreshCollection(
            "page-tasks",
            entity,
            None if unchanged else tuple(page_task_roots(entity)),
        )

    if isinstance(entity, Entities.CATEGORY) and component_id == "table":
        if not entity.allowed(Action.RESTRICTED, user=user):
            raise RefreshFallback("Page index context is no longer viewable")
        parent = index.PageIndex(entity=entity, user=user, limit=None)
        return RefreshCollection(
            "page-index", parent, None if unchanged else tuple(parent.refresh_roots()),
        )

    view_index = view.get("index")
    if entity is not None or view_index not in SUPPORTED_INDEXES:
        raise RefreshFallback("Unsupported refresh view")

    if view_index == "tasks" and component_id == "table":
        parent = index.TaskIndex(user=user, limit=None)
        return RefreshCollection(
            "task-index", parent, None if unchanged else tuple(parent.refresh_roots()),
        )

    if component_id != "table" or not user.has_permission(
        Resource.USERS,
        Action.VIEW,
    ):
        raise RefreshFallback("User index is no longer viewable")
    mode = view.get("mode")
    if mode not in {"regular", "public"}:
        raise RefreshFallback("Invalid user index mode")
    parent = index.UserIndex(user=user, mode=mode, limit=None)
    return RefreshCollection(
        "user-index", parent, None if unchanged else tuple(parent.refresh_roots()),
    )


def _client_fingerprints(rows):
    if not isinstance(rows, list) or len(rows) > MAX_REFRESH_ROWS:
        raise RefreshFallback("Invalid refresh row manifest")

    fingerprints = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RefreshFallback("Invalid refresh row")
        key = row.get("key")
        entity_hash = row.get("hash")
        fingerprint = row.get("fingerprint")
        if not all(isinstance(value, str) and value for value in (key, entity_hash, fingerprint)):
            raise RefreshFallback("Invalid refresh row identity")
        if key in fingerprints:
            raise RefreshFallback("Duplicate refresh row")
        fingerprints[key] = (entity_hash, fingerprint)
    return fingerprints


def _form_versions(roots, hashes, details):
    if any(root is not None for root in roots.values()):
        # A changed collection may be observed before its Form cache write.
        # Root relation keys let one durable batch close that publication window.
        keys = {root.db.get("form") for root in roots.values() if root.db.get("form")}
        versions = {
            form.key: form.version or ""
            for form in Entities.fetch(*keys, request=Fetch.root())
            if form.entity_kind == "form"
        } if keys else {}
        return {
            key: versions.get(root.db["form"]) if root.db.get("form") else ""
            for key, root in roots.items()
        }

    form_hashes = {
        pointer for entity_hash in hashes.values()
        if (pointer := details.get(entity_hash, {}).get("form_hash"))
    }
    forms = _load_cached_details(sorted(form_hashes)) if form_hashes else {}
    versions = {}
    for key, entity_hash in hashes.items():
        row = details.get(entity_hash, {})
        form_hash = row.get("form_hash")
        if form_hash:
            source = forms.get(form_hash, {})
            versions[key] = source.get("form_version") if source.get("kind") == "form" else None
        elif "form_hash" in row and form_hash is None:
            # Explicit null also covers reserved Forms, which have no cache row.
            versions[key] = row.get("form_version", "")
        else:
            versions[key] = None
    return versions


def _cached_fingerprint(key, kind, details, root=None, *, form_version=None):
    if (
        details.get("revision_stale")
        or form_version is None or identify_entity(details) != (key, kind)
        or (root is not None and (
            not getattr(root, "modified", None)
            or details.get("modified") != base_fingerprint(root.modified or root.created)
        ))
    ):
        return None
    if details.get("form_version") != form_version:
        if not details.get("modified"):
            return None
        return restricted_fingerprint(
            details["modified"], details.get("restricted_to"), form_version=form_version,
        )
    return details.get("fingerprint")


def resolve_refresh_delta(collection: RefreshCollection, rows: object, user: User, *, reauthorize: bool = False) -> RefreshDelta:
    """Compare cached fingerprints and expand only rows needing authorization."""
    client = _client_fingerprints(rows)
    if collection.roots is None:
        roots = dict.fromkeys(client)
        hashes = {key: row[0] for key, row in client.items()}
    else:
        roots = {root.urlsafe_key: root for root in collection.roots}
        hashes = {key: value if isinstance(value := root.db.get("hash"), str) else None for key, root in roots.items()}
    kind = (
        "page"
        if collection.kind in {"page-index", "filtered-page-index", "user-index"}
        else "task"
    )
    try:
        details = _load_cached_details([h for h in hashes.values() if h])
        form_versions = _form_versions(roots, hashes, details)
    except Exception as error:
        exceptions.capture(error, context={"operation": "refresh-fingerprints"})
        details = {}
        form_versions = {}

    # User account columns can change without changing their Page fingerprint.
    refresh_users = collection.kind == "user-index" and collection.roots is not None
    changed_keys = {
        key
        for key, root in roots.items()
        if refresh_users
        or not hashes[key]
        or key not in client
        or client[key] != (
            hashes[key], _cached_fingerprint(
                key, kind, details.get(hashes[key] or "", {}), root,
                form_version=form_versions.get(key),
            )
        )
    }
    candidates = [
        root if root is not None else key
        for key, root in roots.items()
        if reauthorize or key in changed_keys
    ]
    expanded = {
        entity.urlsafe_key: entity
        for entity in Entities.fetch(
            *candidates,
            request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
        )
    } if candidates else {}

    remove = set(client).difference(roots)
    upsert = []
    order = []
    for key in roots:
        if key not in changed_keys and not reauthorize:
            order.append(key)
            continue

        entity = expanded.get(key)
        if entity and entity.entity_kind != kind:
            entity = None
        permission_entity = (
            cast("Page", entity).user if entity and collection.kind == "user-index" else entity
        )
        if permission_entity and permission_entity.allowed(Action.VIEW, user=user):
            if key in changed_keys:
                upsert.append(entity)
            order.append(key)
        elif key in client:
            remove.add(key)

    if upsert:
        # Refresh only projections we already loaded and authorized. This also
        # teaches legacy rows their Form pointer after their first safe refresh.
        refreshed = {entity.key: entity for entity in upsert}
        for entity in upsert:
            form = entity.form
            if form and not form.reserved:
                refreshed[form.key] = form
        try:
            cache.update(*refreshed.values(), update=False)
        except Exception as error:
            exceptions.capture(error, context={"operation": "refresh-projections"})

    return RefreshDelta(
        upsert=tuple(upsert),
        remove=tuple(key for key in client if key in remove),
        order=tuple(order),
    )
