"""Batched, retryable reconciliation of indexed inherited restrictions."""

from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    from ...entities.entity import Entity
    from ...properties.common_entity import Kind

import json
from uuid import uuid4

from flask import url_for
from redis.commands.search.query import Query as SearchQuery

from config.datastore import encode_urlsafe_key
from lagniappe import CONFIG
from ...definitions import Fetch, FetchReason
from ...definitions.fingerprints import restricted_fingerprint
from ...tools.auth.restrictions import RESTRICTION_SOURCES, normalize_restrictions, restriction_fields
from ...tools.database.core import KINDS
from ...tools.database.filter import Filter, Query
from ...tools.services import task_queue
from .core import cache
from .add import update
from .details import _load_cached_details, identify_entity
from .keys import Keys, Search

class ReconcileTask(TypedDict):
    source_key: str
    owner_keys: NotRequired[list[str]]
    cursor: NotRequired[str | None]
    revision: NotRequired[str]
    offset: NotRequired[int]


BATCH_SIZE = 100
SOURCES = {"form", "page", "task"}
VERIFICATION_ATTEMPTS = 3


def prepare_changes(entities: Iterable[Entity]) -> list[Entity]:
    """Preserve required permission work before replacing source cache rows."""
    sources = [entity for entity in entities
               if entity.kind in SOURCES and not getattr(entity, "_testing", False)]
    if not sources:
        return []
    with cache.pipeline() as pipe:
        for entity in sources:
            pipe.hget(Keys.ENTITY_HASHES.value, entity.hash)
            pipe.hget(Keys.RESTRICTION_PENDING.value, entity.urlsafe_key)
        previous = pipe.execute()
    changes = []
    with cache.pipeline() as pipe:
        for entity, old, pending in zip(sources, previous[::2], previous[1::2], strict=True):
            before = normalize_restrictions(json.loads(old).get("restricted_to")) if old else {}
            # Forms also compare their durable source during Save. A missing
            # cache row is not a restriction change for a newly created Form.
            # An existing stale row can recover a retry before a pending write.
            changed = (entity.kind != "form" or old is not None) and before != entity.restricted_to
            if pending or changed or getattr(entity, "_reconcile_restrictions", False):
                # Keep this intent outside the replaceable search row so a
                # failed source projection/queue write remains retryable.
                pipe.hset(Keys.RESTRICTION_PENDING.value, entity.urlsafe_key, "1")
                entity._reconcile_restrictions = True
                changes.append(entity)
        pipe.execute()
    return changes


def dispatch_changes(changes: Iterable[Entity]) -> None:
    for entity in changes:
        enqueue({
            "source_key": entity.urlsafe_key,
            "owner_keys": list(getattr(entity, "_restriction_owner_keys", ())),
        })
        with cache.pipeline() as pipe:
            pipe.hdel(Keys.RESTRICTION_PENDING.value, entity.urlsafe_key)
            pipe.execute()
        entity._reconcile_restrictions = False


def enqueue(payload: ReconcileTask) -> None:
    if CONFIG.local and not CONFIG.TASK_QUEUE_ENABLED:
        next_batch: ReconcileTask | None = payload
        while next_batch is not None:
            next_batch = reconcile_batch(**next_batch)
        return
    identity = task_queue.create_task(
        url_for("process.reconcile_restrictions", _external=True), dict(payload),
        task_id=f"restrictions-{uuid4().hex}", dispatch_deadline_seconds=300,
    )
    if not identity:
        raise RuntimeError("Restriction reconciliation could not be queued; retry saving.")


def _projection(current, source, *, own_form=False):
    """Replace only this source's clauses and recalculate the cached revision."""
    restrictions = normalize_restrictions(current.get("restricted_to"))
    source_restrictions = normalize_restrictions(source.restricted_to)
    if source.kind == "form":
        clauses = ("task_form" if source.form_type == "task" else "page_form",)
    elif source.kind == "page":
        clauses = ("page", "page_form")
    else:
        clauses = RESTRICTION_SOURCES
    for clause in clauses:
        if source_restrictions.get(clause):
            restrictions[clause] = source_restrictions[clause]
        else:
            restrictions.pop(clause, None)
    _, kind = identify_entity(current)
    version = None
    if kind in {"page", "task"}:
        version = (source.version or "") if own_form else current.get("form_version", "")
    return {
        "restricted_to": restrictions,
        "form_version": version,
        "fingerprint": restricted_fingerprint(
            current["modified"], restrictions, form_version=version,
        ),
    }


def _write_projections(details, rows, projections):
    """Write calculated permissions and fingerprints as one Redis batch."""
    with cache.pipeline() as pipe:
        for key in rows.values():
            pipe.exists(key)
        indexed = pipe.execute()
    with cache.pipeline() as pipe:
        for (entity_hash, key), exists in zip(rows.items(), indexed, strict=True):
            patch = projections[entity_hash]
            current = {**details[entity_hash], **patch}
            if not current["restricted_to"]:
                current.pop("restricted_to")
            if current["form_version"] is None:
                current.pop("form_version")
            pipe.hset(Keys.ENTITY_HASHES.value, entity_hash, json.dumps(current))
            if exists:
                fields = restriction_fields(patch["restricted_to"])
                for clause in RESTRICTION_SOURCES:
                    field = f"restricted_to_{clause}"
                    if field in fields:
                        pipe.hset(key, field, fields[field])
                    else:
                        pipe.hdel(key, field)
        pipe.execute()


def _publish_completion(owners):
    from ...entities import Entities
    from ..database import utility as database_utility

    database_utility.advance_site_fingerprints("task")
    if owners:
        Entities.touch(*owners)
        update(*owners)


def _collection_owner_keys(entities):
    """Collect list owners from stored references in root Page/Task rows."""
    keys = set()
    for entity in entities:
        if entity.kind == "page":
            keys.update(entity.db.get("categories") or ())
            parent = entity.db.get("model")
        elif entity.kind == "task":
            parent = entity.db.get("project")
        else:
            continue
        if parent:
            keys.add(parent)
    return {encode_urlsafe_key(key) for key in keys}


def _membership_revision():
    from ..database import utility as database_utility

    paths = ("/pages/index", "/tasks/index")
    revisions = database_utility.site_fingerprints(paths)
    values = []
    for path in paths:
        value = revisions[path]
        if value is None:
            raise ValueError(f"Missing site fingerprint for {path}")
        values.append(value)
    return ":".join(values)


def reconcile_batch(
    source_key: str,
    cursor: str | None = None,
    offset: int = 0,
    revision: str | None = None,
    owner_keys: Collection[str] | None = None,
) -> ReconcileTask | None:
    from ...entities import Entities

    nested = Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION)
    source = Entities.fetch_one(source_key, request=nested)
    if source is None:
        return None
    if source.kind not in SOURCES:
        raise ValueError("Invalid restriction reconciliation source")
    source_fingerprint = source.fingerprint
    owners_to_update = set(owner_keys or ())
    restart: ReconcileTask = {"source_key": source_key, "owner_keys": sorted(owners_to_update)}
    current_revision = _membership_revision()
    if revision is not None and revision != current_revision:
        return restart
    revision = current_revision
    next_cursor = None
    if source.kind == "form":
        instances = Query(KINDS.instances).filter(Filter().eq("form", source.key)).limit(BATCH_SIZE).cursor(cursor).fetch()
        next_cursor = instances.next_cursor
        roots = [entity for entity in Entities.fetch(*instances, request=Fetch.root())
                 if entity.kind in {"page", "task"}]
    else:
        roots = [source]
    owners_to_update.update(_collection_owner_keys(roots))
    restart["owner_keys"] = sorted(owners_to_update)
    root_hashes = [entity.hash for entity in roots]
    docs, total = [], 0
    if root_hashes:
        query = SearchQuery(
            "(@kind:{page | user | task | file}) (@requires:{ " + " | ".join(root_hashes) + " })"
        ).dialect(2).sort_by("details_key").paging(int(offset), BATCH_SIZE)
        result = cache.search(query)
        docs, total = result.docs, result.total
    rows = {doc.details_key: doc.id for doc in docs}
    # Task.requires omits its own hash. Roots also retain details when their
    # search row is absent, so always include roots explicitly.
    for entity in roots:
        cache_kind = cast("Kind", entity.properties.kind).cache_value
        if cache_kind is None:
            raise ValueError("Restriction reconciliation requires a stored entity kind.")
        rows[entity.hash] = Search[cache_kind].key(entity)
    details = _load_cached_details(rows)
    projections = {
        entity_hash: _projection(
            current, source,
            own_form=source.kind == "form" and entity_hash in root_hashes,
        )
        for entity_hash, current in details.items()
    }
    rows = {h: key for h, key in rows.items() if h in projections}
    _write_projections(details, rows, projections)

    # Fresh keys force a new read. The resolved fingerprint includes inherited
    # permissions even when the descendant's own modified value is unchanged.
    for _attempt in range(VERIFICATION_ATTEMPTS):
        identifiers = {key for h in rows if (key := identify_entity(details[h])[0]) is not None} | {source_key}
        current = {entity.hash: entity for entity in Entities.fetch(*sorted(identifiers), request=nested)}
        missing = rows.keys() - current.keys()
        if missing:
            with cache.pipeline() as pipe:
                for entity_hash in missing:
                    pipe.hdel(Keys.ENTITY_HASHES.value, entity_hash)
                    pipe.delete(rows.pop(entity_hash))
                    entity_key, kind = identify_entity(details[entity_hash])
                    if kind == "page":
                        pipe.delete(Search.page.value.format(entity_key), Search.user.value.format(entity_key))
                pipe.execute()
        cached = _load_cached_details(rows)
        changed = [current[h] for h in rows
                   if h in cached and current[h].fingerprint != cached[h].get("fingerprint")]
        if not changed:
            break
        update(*changed, update=False)
    else:
        raise RuntimeError("Entities kept changing during restriction reconciliation; retry")

    if source.hash not in current:
        return None
    if current[source.hash].fingerprint != source_fingerprint:
        return restart
    if _membership_revision() != revision:
        return restart
    if int(offset) + BATCH_SIZE < total:
        return {**restart, "cursor": cursor,
                "offset": int(offset) + BATCH_SIZE, "revision": revision}
    if next_cursor:
        return {**restart, "cursor": next_cursor,
                "offset": 0, "revision": revision}
    owners = Entities.fetch(*sorted(owners_to_update), request=Fetch.direct()) if owners_to_update else []
    _publish_completion([owner for owner in owners if owner.kind in {"category", "project"}])
    return None
