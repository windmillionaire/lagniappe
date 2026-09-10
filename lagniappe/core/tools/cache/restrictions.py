"""Batched, retryable reconciliation of indexed inherited restrictions."""

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

BATCH_SIZE = 100
SOURCES = {"form", "page", "task"}
VERIFICATION_ATTEMPTS = 3


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_change_detection_and_forced_retry
# @matrix permissions cache : change-detection retry form-version
def previous_restrictions(entities):
    sources = [entity for entity in entities
               if entity.entity_kind in SOURCES and not getattr(entity, "_testing", False)]
    if not sources:
        return []
    with cache.pipeline() as pipe:
        for entity in sources:
            pipe.hget(Keys.ENTITY_HASHES.value, entity.hash)
            pipe.hget(Keys.RESTRICTION_PENDING.value, entity.urlsafe_key)
        previous = pipe.execute()
    changes = []
    with cache.pipeline() as pipe:
        for entity, old, pending in zip(sources, previous[::2], previous[1::2]):
            before = _source_signature(entity, json.loads(old) if old else {})
            if pending or before != _source_signature(entity) or getattr(entity, "_reconcile_restrictions", False):
                # Keep this intent outside the replaceable search row so a
                # failed source projection/queue write remains retryable.
                pipe.hset(Keys.RESTRICTION_PENDING.value, entity.urlsafe_key, "1")
                entity._reconcile_restrictions = True
            changes.append((entity, before))
        pipe.execute()
    return changes


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_change_detection_and_forced_retry
# @matrix permissions cache : change-detection retry form-version
def dispatch_changes(previous):
    for entity, old in previous:
        after = _source_signature(entity)
        if old != after or getattr(entity, "_reconcile_restrictions", False):
            enqueue({
                "source_key": entity.urlsafe_key,
                "owner_keys": list(getattr(entity, "_restriction_owner_keys", ())),
            })
            with cache.pipeline() as pipe:
                pipe.hdel(Keys.RESTRICTION_PENDING.value, entity.urlsafe_key)
                pipe.execute()
            entity._reconcile_restrictions = False


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_enqueue_uses_current_source_key
# @matrix permissions : queue dispatch
def enqueue(payload):
    if CONFIG.local and not CONFIG.TASK_QUEUE_ENABLED:
        while payload is not None:
            payload = reconcile_batch(**payload)
        return
    identity = task_queue.create_task(
        url_for("process.reconcile_restrictions", _external=True), payload,
        task_id=f"restrictions-{uuid4().hex}", dispatch_deadline_seconds=300,
    )
    if not identity:
        raise RuntimeError("Restriction reconciliation could not be queued; retry saving.")


# @testable false
# @covered-by lagniappe/core/tools/cache/restrictions.py::previous_restrictions
# @reason source signature comparison owns restriction and schema invalidation
def _source_signature(entity, details=None):
    restrictions = entity.restricted_to if details is None else details.get("restricted_to")
    version = None
    if entity.entity_kind == "form":
        version = (entity.version or "") if details is None else details.get("form_version")
    return normalize_restrictions(restrictions), version


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_cached_restrictions_resolve_file_task_page_and_form
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_restriction_projection_preserves_own_form_versions_and_base_modified
# @matrix permissions cache : source-clauses preserved-fields fingerprint form-version no-descendant-writes
def _projection(current, source, *, own_form=False):
    """Replace only this source's clauses and recalculate the cached revision."""
    restrictions = normalize_restrictions(current.get("restricted_to"))
    source_restrictions = normalize_restrictions(source.restricted_to)
    if source.entity_kind == "form":
        clauses = ("task_form" if source.form_type == "task" else "page_form",)
    elif source.entity_kind == "page":
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


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_restriction_batch_updates_only_projection_fields
# @matrix permissions cache : preserved-fields restriction-removal batch-write
def _write_projections(details, rows, projections):
    """Write calculated permissions and fingerprints as one Redis batch."""
    with cache.pipeline() as pipe:
        for key in rows.values():
            pipe.exists(key)
        indexed = pipe.execute()
    with cache.pipeline() as pipe:
        for (entity_hash, key), exists in zip(rows.items(), indexed):
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


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_completion_publishes_existing_collection_revisions
# @matrix permissions cache : channel-invalidation reconciliation
def _publish_completion(owners):
    from ...entities import Entities
    from ..database import utility as database_utility

    database_utility.advance_site_fingerprints("task")
    if owners:
        Entities.touch(*owners)
        update(*owners)


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_collects_owner_keys_without_loading_relations
# @matrix permissions cache : owner-reuse no-extra-read
def _collection_owner_keys(entities):
    """Collect list owners from stored references in root Page/Task rows."""
    keys = set()
    for entity in entities:
        if entity.entity_kind == "page":
            keys.update(entity.db.get("categories") or ())
            parent = entity.db.get("model")
        elif entity.entity_kind == "task":
            parent = entity.db.get("project")
        else:
            continue
        if parent:
            keys.add(parent)
    return {encode_urlsafe_key(key) for key in keys}


# @testable false
# @covered-by lagniappe/core/tools/cache/restrictions.py::reconcile_batch
# @reason existing membership revisions make offset continuation safe across moves
def _membership_revision():
    from ..database import utility as database_utility

    paths = ("/pages/index", "/tasks/index")
    revisions = database_utility.site_fingerprints(paths)
    return ":".join(revisions[path] for path in paths)


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconcile_preserves_local_page_groups_and_removes_form_restrictions
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_restarts_when_membership_changes_between_or_during_batches
# @tests tests_e2e/009_search/test_009e_form_restrictions.py::test_form_restrictions_reconcile_existing_descendants
# @tests tests_e2e/009_search/test_009e_form_restrictions.py::test_restriction_reconciliation_visits_every_indexed_batch
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_verifies_repairs_and_retries
# @tests tests_e2e/009_search/test_009e_form_restrictions.py::test_restriction_reconciliation_repairs_concurrent_changes
# @matrix permissions search : reconciliation local-restrictions removal batching duplicate-names source-clauses source-save
# @matrix permissions cache : owner-reuse
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_reads_available_cache_details_without_recovery
# @matrix permissions cache : batching concurrent-move continuation-restart concurrent-save deleted-row preserved-fields fingerprint reconciliation retry cache-miss no-extra-read
def reconcile_batch(source_key, cursor=None, offset=0, revision=None, owner_keys=None):
    from ...entities import Entities

    nested = Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION)
    source = Entities.fetch_one(source_key, request=nested)
    if source is None:
        return None
    if source.entity_kind not in SOURCES:
        raise ValueError("Invalid restriction reconciliation source")
    source_fingerprint = source.fingerprint
    owner_keys = set(owner_keys or ())
    restart = {"source_key": source_key, "owner_keys": sorted(owner_keys)}
    current_revision = _membership_revision()
    if revision is not None and revision != current_revision:
        return restart
    revision = current_revision
    next_cursor = None
    if source.entity_kind == "form":
        instances = Query(KINDS.instances).filter(Filter().eq("form", source.key)).limit(BATCH_SIZE).cursor(cursor).fetch()
        next_cursor = instances.next_cursor
        roots = [entity for entity in Entities.fetch(*instances, request=Fetch.root())
                 if entity.entity_kind in {"page", "task"}]
    else:
        roots = [source]
    owner_keys.update(_collection_owner_keys(roots))
    restart["owner_keys"] = sorted(owner_keys)
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
    rows.update((entity.hash, Search[entity.properties.kind.cache_value].key(entity)) for entity in roots)
    details = _load_cached_details(rows)
    projections = {
        entity_hash: _projection(
            current, source,
            own_form=source.entity_kind == "form" and entity_hash in root_hashes,
        )
        for entity_hash, current in details.items()
    }
    rows = {h: key for h, key in rows.items() if h in projections}
    _write_projections(details, rows, projections)

    # Fresh keys force a new read. The resolved fingerprint includes inherited
    # permissions even when the descendant's own modified value is unchanged.
    for _attempt in range(VERIFICATION_ATTEMPTS):
        identifiers = {identify_entity(details[h])[0] for h in rows} | {source_key}
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
    owners = Entities.fetch(*sorted(owner_keys), request=Fetch.direct()) if owner_keys else []
    _publish_completion([owner for owner in owners if owner.entity_kind in {"category", "project"}])
    return None
