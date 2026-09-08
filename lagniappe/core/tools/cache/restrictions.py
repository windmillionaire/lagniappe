"""Batched, retryable reconciliation of indexed inherited restrictions."""

import json
from uuid import uuid4

from flask import url_for
from redis.commands.search.query import Query as SearchQuery

from lagniappe import CONFIG
from ...definitions import Fetch
from ...tools.auth.restrictions import combine_restrictions, prepare_permissions
from ...tools.database.core import KINDS
from ...tools.database.filter import Filter, Query
from ...tools.services import task_queue
from .core import cache
from .details import _load_cached_details
from .keys import Keys, Search

BATCH_SIZE = 100
SOURCES = {"form", "page", "task"}


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_change_detection_and_forced_retry
# @matrix permissions cache : change-detection retry
def previous_restrictions(entities):
    sources = [entity for entity in entities
               if entity.entity_kind in SOURCES and not getattr(entity, "_testing", False)]
    if not sources:
        return []
    prepare_permissions(*sources)
    with cache.pipeline() as pipe:
        for entity in sources:
            pipe.hget(Search[entity.properties.kind.cache_value].key(entity), "restricted_to")
            pipe.hget(Keys.RESTRICTION_PENDING.value, entity.urlsafe_key)
        previous = pipe.execute()
    changes = []
    with cache.pipeline() as pipe:
        for entity, old, pending in zip(sources, previous[::2], previous[1::2]):
            before = old.decode() if isinstance(old, bytes) else old
            if pending or before != entity.properties.restricted_to.cache_value or getattr(entity, "_reconcile_restrictions", False):
                # Keep this intent outside the replaceable search row so a
                # failed source projection/queue write remains retryable.
                pipe.hset(Keys.RESTRICTION_PENDING.value, entity.urlsafe_key, "1")
                entity._reconcile_restrictions = True
            changes.append((entity, old))
        pipe.execute()
    return changes


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconciliation_change_detection_and_forced_retry
# @matrix permissions cache : change-detection retry
def dispatch_changes(previous):
    for entity, old in previous:
        before = old.decode() if isinstance(old, bytes) else old
        after = entity.properties.restricted_to.cache_value
        if before != after or getattr(entity, "_reconcile_restrictions", False):
            enqueue({"source_key": entity.urlsafe_key})
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


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_cached_restrictions_resolve_file_task_page_and_form
# @matrix permissions cache : cached-sources file-parent page-precedence
def effective(details, entity_hash):
    item = details[entity_hash]
    kind = item.get("kind")
    if kind in {"page", "user", "form"}:
        return combine_restrictions(item.get("restricted_to"), [])
    if kind == "task":
        parent = item.get("parent_key")
        if not parent or "form_key" not in item:
            raise RuntimeError("Task permission metadata needs rebuilding")
        form = item.get("form_key")
        return combine_restrictions(effective(details, parent), effective(details, form) if form else [])
    if kind == "file" and item.get("parent_key"):
        return effective(details, item["parent_key"])
    raise RuntimeError("Missing File permission parent")


# @testable false
# @covered-by lagniappe/core/tools/cache/restrictions.py::reconcile_batch
# @reason source records only need permission fields, not display projections
def _permission_details(entity):
    details = {"kind": entity.entity_kind}
    if entity.entity_kind in {"form", "page"}:
        details["restricted_to"] = entity.restricted_to or []
    elif entity.entity_kind == "task":
        details["parent_key"] = entity.page.hash
        details["form_key"] = entity.form.hash if entity.form else None
    elif entity.entity_kind == "file":
        details["parent_key"] = entity.owner.hash if entity.owner else None
    return details


# @testable false
# @covered-by lagniappe/core/tools/cache/restrictions.py::reconcile_batch
# @reason batched permission metadata loading belongs to reconciliation
def _details(hashes, overrides):
    from ...entities import Entities

    details = dict(overrides)
    pending = set(hashes)
    for item in overrides.values():
        if item.get("kind") in {"task", "file"}:
            pending.update(value for value in (item.get("parent_key"), item.get("form_key")) if value)
    pending -= details.keys()
    for _depth in range(4):
        if not pending:
            break
        found = _load_cached_details(sorted(pending))
        missing = pending - found.keys()
        if missing:
            # Cache holes must not silently remove a permission source. Only
            # missing metadata is recovered from root Datastore records.
            for kind in (KINDS.models, KINDS.instances, KINDS.files):
                rows = []
                missing_hashes = list(missing)
                for start in range(0, len(missing_hashes), 30):
                    rows.extend(Query(kind).filter(Filter().contains("hash", missing_hashes[start:start + 30])).fetch_all())
                entities = Entities.fetch(*rows, request=Fetch.root())
                prepare_permissions(*entities)
                found.update((entity.hash, _permission_details(entity)) for entity in entities)
                missing -= found.keys()
                if not missing:
                    break
            if missing:
                raise RuntimeError("Permission source details are unavailable; retry reconciliation")
        details.update(found)
        pending = set()
        for item in found.values():
            if item.get("kind") in {"task", "file"}:
                pending.update(value for value in (item.get("parent_key"), item.get("form_key")) if value)
        pending -= details.keys()
    return details


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_reconcile_preserves_page_overrides_and_removes_restrictions
# @tests tests_e2e/009_search/test_009e_form_restrictions.py::test_form_restrictions_reconcile_existing_descendants
# @tests tests_e2e/009_search/test_009e_form_restrictions.py::test_restriction_reconciliation_visits_every_indexed_batch
# @matrix permissions search : reconciliation page-override removal batching duplicate-names page-precedence source-save
def reconcile_batch(source_key, cursor=None, offset=0):
    from ...entities import Entities

    source = Entities.fetch_one(source_key, request=Fetch.root())
    if source is None:
        return None
    if source.entity_kind not in SOURCES:
        raise ValueError("Invalid restriction reconciliation source")
    next_cursor = None
    if source.entity_kind == "form":
        instances = Query(KINDS.instances).filter(Filter().eq("form", source.key)).limit(BATCH_SIZE).cursor(cursor).fetch()
        next_cursor = instances.next_cursor
        roots = Entities.fetch(*instances, request=Fetch.root())
        roots = [entity for entity in roots if entity.entity_kind in {"page", "task"}
                 and not (entity.entity_kind == "page" and entity.db.get("restricted_to"))]
    else:
        roots = [source]
    prepare_permissions(source, *roots)
    overrides = {entity.hash: _permission_details(entity) for entity in [source, *roots]}
    root_hashes = [entity.hash for entity in roots]
    docs, total = [], 0
    if root_hashes:
        query = SearchQuery(
            "(@kind:{page | user | task | file}) (@requires:{ " + " | ".join(root_hashes) + " })"
        ).dialect(2).sort_by("details_key").paging(int(offset), BATCH_SIZE)
        result = cache.search(query)
        docs, total = result.docs, result.total
    rows = {doc.id: (doc.details_key, getattr(doc, "restricted_to", None)) for doc in docs}
    with cache.pipeline() as pipe:
        for entity in roots:
            pipe.hgetall(Search[entity.properties.kind.cache_value].key(entity))
        stored_roots = pipe.execute()
    for entity, stored in zip(roots, stored_roots):
        if stored:
            old = stored.get(b"restricted_to", stored.get("restricted_to"))
            rows[Search[entity.properties.kind.cache_value].key(entity)] = (entity.hash, old)
    details = _details([h for h, _old in rows.values()], overrides)
    with cache.pipeline() as pipe:
        for key, (entity_hash, old) in rows.items():
            value = ",".join(effective(details, entity_hash)) or None
            old = old.decode() if isinstance(old, bytes) else old
            if old == value:
                continue
            # Conditional field patch: a deleted search row is never resurrected.
            pipe.eval("if redis.call('EXISTS',KEYS[1]) == 1 then "
                      "if ARGV[1] == '' then return redis.call('HDEL',KEYS[1],'restricted_to') "
                      "else return redis.call('HSET',KEYS[1],'restricted_to',ARGV[1]) end end",
                      1, key, value or "")
        for entity in roots:
            if entity.entity_kind == "page":
                # Patch the JSON value in place so unrelated cached details are
                # preserved; no full descendant projection is regenerated.
                pipe.eval("local raw=redis.call('HGET',KEYS[1],ARGV[1]); if raw then "
                          "local d=cjson.decode(raw); d.restricted_to=cjson.decode(ARGV[2]); "
                          "return redis.call('HSET',KEYS[1],ARGV[1],cjson.encode(d)) end",
                          1, Keys.ENTITY_HASHES.value, entity.hash,
                          json.dumps(entity.restricted_to or []))
        pipe.execute()
    if int(offset) + BATCH_SIZE < total:
        return {"source_key": source_key, "cursor": cursor, "offset": int(offset) + BATCH_SIZE}
    if next_cursor:
        return {"source_key": source_key, "cursor": next_cursor, "offset": 0}
    return None

