"""Entity creation, persistence, deletion, and site fingerprinting."""

from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
import json
import time
import uuid

from google.api_core import exceptions as google_exceptions
from google.cloud.datastore import Entity, Key

from lagniappe import CONFIG

from .core import DATA, KINDS
from .defaults import DEFAULT_USER_FORM, DEFAULT_USER_PAGE
from .filter import Filter, Query
from lagniappe.core.definitions.default import DefaultEnum

PREFIX = CONFIG.PREFIX
DEFERRED_JOB_TRANSACTION_RETRY_DELAYS = (0.05, 0.1, 0.2)
AI_EMAIL_EVENT_SCHEMA_VERSION = 1
AI_EMAIL_EVENT_PREFIX = "ai-email-event:"


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_database_initialize_only_marks_new_content_stores_as_fresh
# @features database-migrations setup
# @dimensions fresh-install detection reserved-seeding
def initialize():
    """Initialize data services and seed default reserved models if absent."""
    DATA.initialize()

    existing = Query(KINDS.models).filter(Filter().eq("reserved", True)).fetch_all()
    fresh_install = False

    if not existing:
        fresh_install = not any(
            Query(kind).fetch_one()
            for kind in KINDS
            if kind is not KINDS.site
        )
        partial = DATA.datastore.key(KINDS.models.value)
        keys = DATA.datastore.allocate_ids(partial, 2)

        default_user_form = Entity(keys[0])
        default_user_form.update(DEFAULT_USER_FORM)

        default_user_category = Entity(keys[1])
        default_user_category.update(DEFAULT_USER_PAGE)
        default_user_category["form"] = default_user_form.key

        DATA.datastore.put_multi([default_user_form, default_user_category])

    return fresh_install


# @testable infrastructure
def create_entity(key):
    """Create a new Datastore Entity with the given key."""
    return Entity(key)


# @testable infrastructure
def create_key(entity_kind, parent):
    """Allocate a new Datastore key for the given entity kind and optional parent."""
    kind = KINDS[entity_kind].value
    if parent and isinstance(parent, Key):
        partial = DATA.datastore.key(kind, parent=parent)
    elif parent and hasattr(parent, "key"):
        partial = DATA.datastore.key(kind, parent=parent.key)
    else:
        partial = DATA.datastore.key(kind)
    key = DATA.datastore.allocate_ids(partial, 1)[0]
    return key


# @testable infrastructure
def create_named_key(entity_kind, identifier, parent=None):
    """Create a stable complete key for an idempotent internal record."""
    kind = KINDS[entity_kind].value
    parent_key = getattr(parent, "key", parent)
    if parent_key:
        return DATA.datastore.key(kind, identifier, parent=parent_key)
    return DATA.datastore.key(kind, identifier)




# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_transactions_retry_aborted_contention
# @features deferred-jobs
# @dimensions transaction-contention retry
def _retry_deferred_job_transaction(operation):
    """Retry a complete deferred-job transaction after Datastore contention."""

    # @testable false
    # @covered-by lagniappe/core/tools/database/utility.py::_retry_deferred_job_transaction
    # @reason wrapper behavior is asserted through decorated transaction functions
    @wraps(operation)
    def retried(*args, **kwargs):
        for attempt in range(len(DEFERRED_JOB_TRANSACTION_RETRY_DELAYS) + 1):
            try:
                return operation(*args, **kwargs)
            except google_exceptions.Aborted:
                if attempt >= len(DEFERRED_JOB_TRANSACTION_RETRY_DELAYS):
                    raise
                time.sleep(DEFERRED_JOB_TRANSACTION_RETRY_DELAYS[attempt])

    return retried


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_ai_email_event_claim_is_durable_and_replay_safe
# @features ai-email webhook
# @dimensions replay transaction lease privacy
@_retry_deferred_job_transaction
def claim_ai_email_event(digest, lease_token, now, *, lease_seconds=300):
    """Claim one HMAC-digested provider event without storing its raw ID."""
    digest = str(digest or "").strip().casefold()
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("AI email event digest is invalid")
    key = create_named_key("site", f"{AI_EMAIL_EVENT_PREFIX}{digest}")
    with DATA.datastore.transaction() as transaction:
        record = DATA.datastore.get(key, transaction=transaction)
        if record is not None:
            state = str(record.get("state") or "")
            expires = record.get("lease_expires")
            if state in {"accepted", "rejected", "ignored"}:
                return {"claimed": False, "reason": "terminal", "state": state}
            if (
                state == "processing"
                and record.get("lease_token") != lease_token
                and isinstance(expires, datetime)
                and expires > now
            ):
                return {"claimed": False, "reason": "active", "state": state}
        else:
            record = Entity(key=key, exclude_from_indexes=("lease_token",))
            record["created"] = now
        record.update(
            {
                "schema_version": AI_EMAIL_EVENT_SCHEMA_VERSION,
                "state": "processing",
                "lease_token": lease_token,
                "lease_expires": now + timedelta(seconds=lease_seconds),
                "modified": now,
            }
        )
        transaction.put(record)
        return {"claimed": True, "key": key}


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_ai_email_event_claim_is_durable_and_replay_safe
# @features ai-email webhook
# @dimensions replay terminal-compaction transaction
@_retry_deferred_job_transaction
def finish_ai_email_event(digest, lease_token, state, now):
    """Compact an owned event claim to a minimal permanent tombstone."""
    if state not in {"accepted", "rejected", "ignored"}:
        raise ValueError("AI email event terminal state is invalid")
    key = create_named_key("site", f"{AI_EMAIL_EVENT_PREFIX}{digest}")
    with DATA.datastore.transaction() as transaction:
        record = DATA.datastore.get(key, transaction=transaction)
        if record is None or record.get("lease_token") != lease_token:
            return False
        created = record.get("created") or now
        compacted = Entity(key=key)
        compacted.update(
            {
                "schema_version": AI_EMAIL_EVENT_SCHEMA_VERSION,
                "state": state,
                "created": created,
                "modified": now,
                "completed": now,
            }
        )
        transaction.put(compacted)
        return True


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_ai_email_event_claim_is_durable_and_replay_safe
# @features ai-email webhook
# @dimensions replay transient-release transaction
@_retry_deferred_job_transaction
def release_ai_email_event(digest, lease_token, now):
    """Release an owned claim so a provider retry may resume it immediately."""
    key = create_named_key("site", f"{AI_EMAIL_EVENT_PREFIX}{digest}")
    with DATA.datastore.transaction() as transaction:
        record = DATA.datastore.get(key, transaction=transaction)
        if record is None or record.get("lease_token") != lease_token:
            return False
        record["state"] = "retry"
        record.pop("lease_token", None)
        record.pop("lease_expires", None)
        record["modified"] = now
        transaction.put(record)
        return True




# @testable false
# @covered-by lagniappe/core/tools/database/utility.py::commit_ingress_row
# @reason shared key normalization is exercised through public ingress cursor helpers
def _ingress_key(identifier):
    if isinstance(identifier, Key):
        return identifier
    if hasattr(identifier, "key"):
        return identifier.key
    from .get import datastore_key

    return datastore_key(identifier)


# @testable false
# @covered-by lagniappe/core/tools/database/utility.py::commit_ingress_row
# @reason stored execution decoding is exercised through public ingress cursor helpers
def _ingress_execution(entity):
    raw = entity.get("execution", "{}")
    try:
        execution = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError):
        execution = {}
    return execution if isinstance(execution, dict) else {}


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/utility.py::commit_ingress_row
def _put_mutation(writer, entity, property_mask=None):
    """Queue one full or property-masked Datastore mutation."""
    writer.put(entity)
    if property_mask is None:
        return
    mutation = writer.mutations[-1]
    mutation.update = mutation.upsert
    mutation.property_mask.paths.extend(property_mask)


# @testable true
# @tests tests_unit/test_006d_ingress_service.py::test_ingress_status_update_is_cursor_checked
# @tests tests_unit/test_006d_ingress_service.py::test_ingress_stop_is_durable_and_preserves_current_row_boundary
# @features ingress
# @dimensions status cursor compare-and-set stop failure
def update_ingress_status(identifier, status, now, *, expected_cursor=None, error=None):
    """Atomically stop or fail active ingress work without replacing its cursor."""

    key = _ingress_key(identifier)
    if key is None:
        return {"updated": False, "reason": "missing", "entity": None}
    with DATA.datastore.transaction() as transaction:
        entity = DATA.datastore.get(key, transaction=transaction)
        if entity is None:
            return {"updated": False, "reason": "missing", "entity": None}
        execution = _ingress_execution(entity)
        cursor = int(execution.get("cursor") or 0)
        if expected_cursor is not None and cursor != int(expected_cursor):
            return {
                "updated": False,
                "reason": "cursor",
                "entity": entity,
                "execution": execution,
            }
        current = execution.get("status", "idle")
        if current not in {"queued", "running", "stop_requested"}:
            return {
                "updated": False,
                "reason": current,
                "entity": entity,
                "execution": execution,
            }
        execution["status"] = status
        if error is None:
            execution.pop("error", None)
        else:
            execution["error"] = error
        execution.pop("lease_token", None)
        execution.pop("lease_expires", None)
        entity["execution"] = json.dumps(execution)
        entity["modified"] = now
        transaction.put(entity)
        return {
            "updated": True,
            "reason": status,
            "entity": entity,
            "execution": execution,
        }


# @testable true
# @tests tests_unit/test_006d_ingress_service.py::test_ingress_row_commit_requires_expected_cursor_and_applies_masks
# @tests tests_unit/test_006d_ingress_service.py::test_ingress_row_commit_rejects_duplicate_cursor
# @features ingress
# @dimensions cursor compare-and-set durable-commit property-mask duplicate-delivery
def commit_ingress_row(
    identifier,
    expected_cursor,
    ingress_entity,
    writes,
    now,
):
    """Commit one planned row and advance its ingress cursor atomically."""

    key = _ingress_key(identifier)
    if key is None:
        return {"committed": False, "reason": "missing"}

    raw_writes = {
        entity.key: (entity.db, property_mask)
        for entity, property_mask in writes
        if getattr(entity, "key", None) and entity.key != key
    }
    fingerprints = update_site_fingerprints(
        ingress_entity.db, *(raw for raw, _ in raw_writes.values())
    )

    with DATA.datastore.transaction() as transaction:
        stored = DATA.datastore.get(key, transaction=transaction)
        if stored is None:
            return {"committed": False, "reason": "missing"}
        stored_execution = _ingress_execution(stored)
        if int(stored_execution.get("cursor") or 0) != int(expected_cursor):
            return {
                "committed": False,
                "reason": "cursor",
                "entity": stored,
                "execution": stored_execution,
            }
        if stored_execution.get("status") not in {"queued", "running"}:
            return {
                "committed": False,
                "reason": "state",
                "entity": stored,
                "execution": stored_execution,
            }

        candidate = ingress_entity.db
        candidate_execution = _ingress_execution(candidate)
        candidate_execution["cursor"] = expected_cursor + 1
        candidate_execution.pop("lease_token", None)
        candidate_execution.pop("lease_expires", None)
        candidate["execution"] = json.dumps(candidate_execution)
        candidate["modified"] = now

        for raw, property_mask in raw_writes.values():
            _put_mutation(transaction, raw, property_mask)
        for fingerprint in fingerprints:
            transaction.put(fingerprint)
        transaction.put(candidate)
        return {
            "committed": True,
            "reason": "stopped"
            if candidate_execution.get("status") == "stopped"
            else "committed",
            "entity": candidate,
            "execution": candidate_execution,
        }


class Fingerprint(Enum, metaclass=DefaultEnum):
    """Maps entity types and URL segments to site fingerprint identifiers."""

    # kind name
    category = "categories"
    project = "projects"
    page = "pages"
    ingress = "ingress"
    task = "tasks"
    form = "forms"
    user = "users"
    group = "users"
    public_group = "users"
    note = "home"
    notification = None
    report = "reports"

    # url segment
    categories = category
    projects = project
    pages = page
    tasks = task
    forms = form
    users = user
    notes = note
    activity = note
    notifications = notification
    reports = report

    DEFAULT = None


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_save_persists_user_and_users_fingerprint_record
# @features users caching
# @dimensions site-fingerprint save
def save(*entities):
    """Persist entities to Datastore and update their site fingerprints."""
    to_save = {e.key: e.db for e in entities if getattr(e, "key", None)}
    to_update = update_site_fingerprints(*to_save.values())

    DATA.datastore.put_multi(list(to_save.values()) + to_update)


# @testable false
# @covered-by lagniappe/core/tools/database/utility.py::save_mutations
# @reason neutral-mask selection is asserted through the public mutation writer
def _advances_site_fingerprint(entity, mask):
    fields = set(mask or ())
    if entity.db.get("type") == "notification":
        return False
    if entity.db.get("type") == "page" and fields and fields.issubset(
        {"deferred_job"}
    ):
        return False
    if not fields:
        return True
    return not (
        entity.db.get("type") in {"page", "project"}
        and "document_history" in fields
        and fields.issubset({"assets", "document_history"})
    )


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_save_mutations_applies_property_masks_and_fingerprints
# @tests tests_unit/test_018_database_utility.py::test_notification_save_and_delete_skip_site_fingerprints
# @features mutations database
# @dimensions property-mask update full-upsert site-fingerprint document-checkpoint
# @pairs database:property-mask database:update database:full-upsert
# @pairs database:site-fingerprint database:document-checkpoint
# @pairs mutations:property-mask mutations:update mutations:full-upsert
# @pairs mutations:site-fingerprint mutations:document-checkpoint
# @pairs notifications:mutation notifications:site-fingerprint-isolation
def save_mutations(writes):
    """Persist full and property-masked entity writes in one Datastore batch.

    ``writes`` contains ``(typed_entity, property_mask)`` pairs. A ``None`` mask
    is a normal full upsert. A non-empty mask is converted to an ``update``
    mutation so a missing row fails rather than being recreated with only the
    selected properties.
    """
    writes = [
        (entity, None if mask is None else tuple(dict.fromkeys(mask)))
        for entity, mask in writes
        if getattr(entity, "key", None)
    ]
    if not writes:
        return

    for entity, mask in writes:
        if mask == ():
            raise ValueError("Property-masked writes require at least one property")
        if mask is not None and getattr(entity.key, "is_partial", False):
            raise ValueError("Property-masked writes require a complete entity key")

    fingerprint_entities = [
        entity.db
        for entity, mask in writes
        if _advances_site_fingerprint(entity, mask)
    ]
    fingerprints = (
        update_site_fingerprints(*fingerprint_entities)
        if fingerprint_entities
        else []
    )
    with DATA.datastore.batch() as batch:
        for entity, mask in writes:
            _put_mutation(batch, entity.db, mask)

        for fingerprint in fingerprints:
            batch.put(fingerprint)


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_save_raw_persists_datastore_entities_without_typed_save_hooks
# @features database migrations
# @dimensions raw-save site-fingerprint
def save_raw(*entities):
    """Persist raw Datastore entities without running typed entity save hooks.

    Maintenance migrations use this path so malformed legacy properties do not
    need to survive typed entity construction. Site fingerprints still change,
    while business timestamps and unrelated fields remain untouched.
    """
    to_save = {
        entity.key: entity
        for entity in entities
        if getattr(entity, "key", None)
    }
    if not to_save:
        return

    to_update = update_site_fingerprints(*to_save.values())

    DATA.datastore.put_multi(list(to_save.values()) + to_update)


# @testable false
# @reason delete side effects are owned by E2E coverage against configured services
def delete_entities(entities):
    """Delete durable rows and update fingerprints in one Datastore batch."""
    to_delete = {e.key: e.db for e in entities if getattr(e, "key", None)}
    if not to_delete:
        return
    to_update = update_site_fingerprints(
        *(
            entity
            for entity in to_delete.values()
            if entity.get("type") != "notification"
        )
    )

    with DATA.datastore.batch() as batch:
        for entity in to_update:
            batch.put(entity)
        for key in to_delete:
            batch.delete(key)


# @testable false
# @covered-by lagniappe/core/mutations/executor.py::execute_post_commit
# @reason blob cleanup is a post-commit provider effect covered by entity deletion
def delete_blobs(private_paths, public_paths):
    """Delete post-commit storage blobs and return provider error messages."""
    errors = []

    # @testable false
    # @covered-by lagniappe/core/tools/database/utility.py::delete_blobs
    # @reason provider callback only normalizes an error into the outcome
    def record_error(error):
        errors.append(str(error))

    if private_paths:
        DATA.private_bucket.delete_blobs(
            [path for path in private_paths if path], on_error=record_error
        )
    if public_paths:
        DATA.public_bucket.delete_blobs(
            [path for path in public_paths if path], on_error=record_error
        )
    return errors


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_update_site_fingerprints_upserts_missing_users_fingerprint
# @features users caching
# @dimensions site-fingerprint invalidation
def update_site_fingerprints(*entities):
    fingerprints = set(Fingerprint[e.get("type")].value for e in entities)
    keys = [DATA.datastore.key("site", f) for f in fingerprints if f]

    missing = []
    records = DATA.datastore.get_multi(keys, missing=missing)
    records = [r for r in records if r] + missing
    for record in records:
        record["fingerprint"] = str(uuid.uuid4())

    return records


# @testable false
# @reason site fingerprint creation is persistence-owned and covered by route/E2E workflows
def site_fingerprint(path):
    """Return the current fingerprint UUID for a URL path, creating one if needed."""
    return site_fingerprints((path,)).get(path)


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_channel_revisions_batch_only_requested_site_fingerprints
# @tests tests_unit/test_018_database_utility.py::test_site_fingerprints_batch_reads_only_resolved_paths
# @pairs polling:channel polling:batching polling:mounted-scope
def site_fingerprints(paths):
    """Return fingerprints for ``paths`` through one bounded multi-read."""
    paths = tuple(dict.fromkeys(path for path in paths if isinstance(path, str)))
    indexes = {}
    for path in paths:
        parts = [part for part in path.split("/") if part]
        index = (
            "home"
            if not parts
            else next((part for part in parts if Fingerprint[part].value), None)
        )
        if index:
            indexes[path] = index

    keys_by_index = {
        index: DATA.datastore.key("site", index)
        for index in dict.fromkeys(indexes.values())
    }
    missing = []
    records = DATA.datastore.get_multi(list(keys_by_index.values()), missing=missing)
    for record in missing:
        record["fingerprint"] = str(uuid.uuid4())
    if missing:
        DATA.datastore.put_multi(missing)
    by_key = {record.key: record for record in [*records, *missing] if record}

    return {
        path: by_key[keys_by_index[index]].get("fingerprint")
        for path, index in indexes.items()
    }


# @testable infrastructure
def cleanup_test_data():
    """Delete all test Datastore entities and Storage objects (testing only)."""
    if not CONFIG.testing:
        return

    for kind in set([k.value for k in KINDS if k.value]):
        entities = Query(kind).fetch_all()
        if entities:
            DATA.datastore.delete_multi(entities)

    DATA.delete_buckets()
