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
ACTIVE_DEFERRED_JOB_STATUSES = {"queued", "running", "retry_wait"}
DEFERRED_JOB_SCHEDULER_CONTROL_ID = "deferred-jobs-control"
DEFERRED_JOB_SCHEDULER_CONTROL_SCHEMA_VERSION = 2
DEFERRED_JOB_SCHEDULER_STATES = {"enabled", "paused"}
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


# @testable infrastructure
def _deferred_job_key(identifier):
    if isinstance(identifier, Key):
        return identifier
    if hasattr(identifier, "key"):
        return identifier.key
    from .get import datastore_key

    return datastore_key(identifier)


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_transactions_retry_aborted_contention
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
# @features ai-email
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
# @features ai-email
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
# @features ai-email
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


# @testable true
# @tests tests_unit/test_023b_deferred_job_scheduler.py::test_tracking_membership_follows_recovery_required_state
# @features deferred-jobs cloud-scheduler
# @dimensions durable-membership terminal-delivery idempotency
def _deferred_job_requires_recovery(entity):
    """Return whether a durable job still needs scheduled recovery coverage."""
    return bool(
        entity
        and (
            entity.get("status") in ACTIVE_DEFERRED_JOB_STATUSES
            or entity.get("dispatch_state") == "delivery_pending"
        )
    )


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/utility.py::_update_deferred_job_scheduler_tracking
def _deferred_job_recovery_query_state(entity):
    if not entity:
        return (None, False)
    status = entity.get("status")
    return (
        status if status in ACTIVE_DEFERRED_JOB_STATUSES else None,
        entity.get("dispatch_state") == "delivery_pending",
    )


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/utility.py::_update_deferred_job_scheduler_tracking
def _deferred_job_scheduler_control_key():
    return DATA.datastore.key(KINDS.site.value, DEFERRED_JOB_SCHEDULER_CONTROL_ID)


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/utility.py::_update_deferred_job_scheduler_tracking
def _deferred_job_tracking_id(identifier):
    key = _deferred_job_key(identifier)
    if key is None:
        return str(identifier)
    if not hasattr(key, "to_legacy_urlsafe"):
        return str(key)
    encoded = key.to_legacy_urlsafe()
    return encoded.decode() if isinstance(encoded, bytes) else str(encoded)


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/utility.py::_update_deferred_job_scheduler_tracking
def _deferred_job_scheduler_control(transaction):
    key = _deferred_job_scheduler_control_key()
    control = DATA.datastore.get(key, transaction=transaction)
    if control is None:
        control = Entity(key=key, exclude_from_indexes=("tracked_jobs",))
    else:
        try:
            control.exclude_from_indexes = frozenset(
                {*control.exclude_from_indexes, "tracked_jobs"}
            )
        except AttributeError:
            pass
    return control


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/utility.py::get_deferred_job_scheduler_control
def _deferred_job_scheduler_snapshot(control=None):
    control = control or {}
    tracked_jobs = sorted(set(control.get("tracked_jobs") or ()))
    desired_state = control.get("desired_state")
    if desired_state not in DEFERRED_JOB_SCHEDULER_STATES:
        desired_state = "enabled" if tracked_jobs else "paused"
    return {
        "schema_version": int(control.get("schema_version") or 0),
        "tracked_jobs": tracked_jobs,
        "active_jobs": len(tracked_jobs),
        "desired_state": desired_state,
        "generation": int(control.get("generation") or 0),
        "applied_generation": int(control.get("applied_generation") or 0),
        "applied_state": control.get("applied_state"),
        "sync_lease_token": control.get("sync_lease_token"),
        "sync_lease_expires": control.get("sync_lease_expires"),
    }


# @testable true
# @tests tests_unit/test_023b_deferred_job_scheduler.py::test_tracking_membership_follows_recovery_required_state
# @features deferred-jobs cloud-scheduler
# @dimensions durable-membership transaction desired-state
def _update_deferred_job_scheduler_tracking(
    transaction,
    job_key,
    before,
    after,
    now,
):
    """Update recovery membership in the same transaction as a job boundary."""
    was_required = _deferred_job_requires_recovery(before)
    is_required = _deferred_job_requires_recovery(after)
    query_state_changed = _deferred_job_recovery_query_state(
        before
    ) != _deferred_job_recovery_query_state(after)
    if was_required == is_required and not query_state_changed:
        return None

    control = _deferred_job_scheduler_control(transaction)
    snapshot = _deferred_job_scheduler_snapshot(control)
    tracked_jobs = set(snapshot["tracked_jobs"])
    tracking_id = _deferred_job_tracking_id(job_key)
    if is_required:
        tracked_jobs.add(tracking_id)
    elif was_required:
        tracked_jobs.discard(tracking_id)

    control.update(
        {
            "schema_version": DEFERRED_JOB_SCHEDULER_CONTROL_SCHEMA_VERSION,
            "tracked_jobs": sorted(tracked_jobs),
            "active_jobs": len(tracked_jobs),
            "desired_state": "enabled" if tracked_jobs else "paused",
            "generation": snapshot["generation"] + 1,
            "modified": now,
        }
    )
    transaction.put(control)
    return _deferred_job_scheduler_snapshot(control)


# @testable true
# @tests tests_unit/test_023b_deferred_job_scheduler.py::test_scheduler_control_repair_is_revision_checked
# @features deferred-jobs cloud-scheduler
# @dimensions drift-repair optimistic-concurrency
@_retry_deferred_job_transaction
def repair_deferred_job_scheduler_control(job_keys, expected_generation, now):
    """Repair tracked recovery jobs if no lifecycle boundary raced the scan."""
    tracked_jobs = sorted({_deferred_job_tracking_id(key) for key in job_keys})
    with DATA.datastore.transaction() as transaction:
        control = _deferred_job_scheduler_control(transaction)
        snapshot = _deferred_job_scheduler_snapshot(control)
        if snapshot["generation"] != int(expected_generation or 0):
            return {
                "repaired": False,
                "reason": "generation",
                "control": snapshot,
            }

        desired_state = "enabled" if tracked_jobs else "paused"
        changed = (
            snapshot["tracked_jobs"] != tracked_jobs
            or snapshot["desired_state"] != desired_state
            or snapshot["schema_version"]
            != DEFERRED_JOB_SCHEDULER_CONTROL_SCHEMA_VERSION
        )
        control.update(
            {
                "schema_version": DEFERRED_JOB_SCHEDULER_CONTROL_SCHEMA_VERSION,
                "tracked_jobs": tracked_jobs,
                "active_jobs": len(tracked_jobs),
                "desired_state": desired_state,
                "generation": snapshot["generation"] + int(changed),
                "modified": now,
            }
        )
        transaction.put(control)
        return {
            "repaired": True,
            "reason": "updated" if changed else "current",
            "control": _deferred_job_scheduler_snapshot(control),
        }


# @testable true
# @tests tests_unit/test_023b_deferred_job_scheduler.py::test_scheduler_sync_serializes_state_changes_and_converges_latest_generation
# @features deferred-jobs cloud-scheduler
# @dimensions distributed-lease generation race
@_retry_deferred_job_transaction
def acquire_deferred_job_scheduler_sync(lease_token, now, *, lease_seconds):
    """Acquire the short Datastore lease serializing Scheduler API mutations."""
    with DATA.datastore.transaction() as transaction:
        control = _deferred_job_scheduler_control(transaction)
        snapshot = _deferred_job_scheduler_snapshot(control)
        current_token = snapshot["sync_lease_token"]
        lease_expires = _deferred_datetime(snapshot["sync_lease_expires"])
        if (
            current_token
            and current_token != lease_token
            and lease_expires
            and lease_expires > now
        ):
            return {"acquired": False, "control": snapshot}

        control["sync_lease_token"] = lease_token
        control["sync_lease_expires"] = now + timedelta(seconds=lease_seconds)
        transaction.put(control)
        return {
            "acquired": True,
            "control": _deferred_job_scheduler_snapshot(control),
        }


# @testable true
# @tests tests_unit/test_023b_deferred_job_scheduler.py::test_scheduler_sync_serializes_state_changes_and_converges_latest_generation
# @features deferred-jobs cloud-scheduler
# @dimensions distributed-lease generation provider-state
@_retry_deferred_job_transaction
def record_deferred_job_scheduler_sync(
    lease_token,
    actual_state,
    now,
    *,
    lease_seconds,
):
    """Record provider state and release only when the latest intent converged."""
    if actual_state not in DEFERRED_JOB_SCHEDULER_STATES:
        raise ValueError(f"Unsupported Scheduler state: {actual_state!r}")
    with DATA.datastore.transaction() as transaction:
        control = _deferred_job_scheduler_control(transaction)
        snapshot = _deferred_job_scheduler_snapshot(control)
        if snapshot["sync_lease_token"] != lease_token:
            return {"recorded": False, "reason": "lease", "control": snapshot}

        control["applied_state"] = actual_state
        converged = actual_state == snapshot["desired_state"]
        if converged:
            control["applied_generation"] = snapshot["generation"]
            control.pop("sync_lease_token", None)
            control.pop("sync_lease_expires", None)
        else:
            control["sync_lease_expires"] = now + timedelta(seconds=lease_seconds)
        control["modified"] = now
        transaction.put(control)
        return {
            "recorded": True,
            "reason": "converged" if converged else "changed",
            "control": _deferred_job_scheduler_snapshot(control),
        }


# @testable true
# @tests tests_unit/test_023b_deferred_job_scheduler.py::test_scheduler_sync_releases_lease_after_provider_failure
# @features deferred-jobs cloud-scheduler
# @dimensions distributed-lease provider-failure
@_retry_deferred_job_transaction
def release_deferred_job_scheduler_sync(lease_token, now):
    """Release a Scheduler synchronization lease still owned by the caller."""
    with DATA.datastore.transaction() as transaction:
        control = _deferred_job_scheduler_control(transaction)
        snapshot = _deferred_job_scheduler_snapshot(control)
        if snapshot["sync_lease_token"] != lease_token:
            return False
        control.pop("sync_lease_token", None)
        control.pop("sync_lease_expires", None)
        control["modified"] = now
        transaction.put(control)
        return True


# @testable true
# @tests tests_unit/test_023b_deferred_job_scheduler.py::test_scheduler_control_repair_is_revision_checked
# @features deferred-jobs cloud-scheduler
# @dimensions state-read defaults
def get_deferred_job_scheduler_control():
    """Read normalized recovery/Scheduler control state without creating it."""
    control = DATA.datastore.get(_deferred_job_scheduler_control_key())
    return _deferred_job_scheduler_snapshot(control)


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_create_is_transactionally_idempotent
# @pairs deferred-jobs:start deferred-jobs:get-or-create deferred-jobs:notification deferred-jobs:idempotency
# @pair notifications:aggregate-count
@_retry_deferred_job_transaction
def create_deferred_job_if_absent(job, notification=None, lock=None):
    """Atomically insert one prepared job, notification, and optional lock."""
    key = _deferred_job_key(job)
    if key is None:
        return {"created": False, "reason": "missing-key", "entity": None}

    notification_owner = getattr(notification, "parent", None)
    ordinary_notification = bool(
        notification_owner
        and getattr(notification, "notification_type", "ordinary") == "ordinary"
    )
    if ordinary_notification:
        from .. import notification_service

        notification_service.ensure_notification_aggregate(notification_owner)

    entities = [entity for entity in (job, notification, lock) if entity is not None]
    for entity in entities:
        properties = getattr(entity, "properties", None)
        if properties is not None:
            for name in ("active", "hash", "requires", "modified", "created"):
                prop = properties.get(name)
                if prop is not None:
                    prop.update()
        try:
            entity.db.exclude_from_indexes = entity.exclude_from_index
        except AttributeError:
            pass

    with DATA.datastore.transaction() as transaction:
        existing = DATA.datastore.get(key, transaction=transaction)
        current_lock = None
        locked_job = None
        if lock is not None:
            current_lock = DATA.datastore.get(lock.key, transaction=transaction)
            if current_lock is not None:
                operation_key = _deferred_job_key(current_lock.get("operation"))
                if operation_key is not None:
                    locked_job = DATA.datastore.get(
                        operation_key,
                        transaction=transaction,
                    )
                if (
                    locked_job is not None
                    and locked_job.get("status") in ACTIVE_DEFERRED_JOB_STATUSES
                    and operation_key != key
                ):
                    return {
                        "created": False,
                        "reason": "locked",
                        "entity": locked_job,
                        "lock": current_lock,
                    }

        if existing is not None:
            if lock is not None:
                if existing.get("status") in ACTIVE_DEFERRED_JOB_STATUSES:
                    transaction.put(lock.db)
                elif current_lock is not None:
                    transaction.delete(lock.key)
            result = {
                "created": False,
                "reason": "existing",
                "entity": existing,
            }
            if lock is not None:
                result["lock"] = lock.db
            return result
        scheduler_control = _update_deferred_job_scheduler_tracking(
            transaction,
            key,
            None,
            job.db,
            datetime.now(timezone.utc),
        )
        if ordinary_notification:
            notification_service.mutate_aggregate_in_transaction(
                transaction,
                notification_owner,
                ordinary_delta=1,
            )
        for entity in entities:
            transaction.put(entity.db)
        result = {
            "created": True,
            "reason": "created",
            "entity": job.db,
        }
        if lock is not None:
            result["lock"] = lock.db
        if scheduler_control is not None:
            result["scheduler_control"] = scheduler_control
        return result


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_autofill_lock_cleanup_is_compare_and_delete
# @pairs deferred-jobs:form-lock deferred-jobs:compare-and-set
@_retry_deferred_job_transaction
def release_deferred_job_lock(identifier, operation):
    """Delete a lock only when it still belongs to ``operation``."""
    key = _deferred_job_key(identifier)
    if key is None:
        return False

    with DATA.datastore.transaction() as transaction:
        lock = DATA.datastore.get(key, transaction=transaction)
        if lock is None or lock.get("operation") != operation:
            return False
        transaction.delete(key)
        return True


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_claim_and_checkpoint_are_compare_and_set
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_status_transactions_do_not_write_actor
# @features deferred-jobs
# @dimensions lease claim duplicate-delivery
# @pairs deferred-jobs:user-write-isolation deferred-jobs:revision deferred-jobs:transaction
@_retry_deferred_job_transaction
def claim_deferred_job(identifier, lease_token, lease_expires, now):
    """Atomically claim a due job unless it is terminal or actively leased."""
    key = _deferred_job_key(identifier)
    if key is None:
        return {"claimed": False, "reason": "missing", "entity": None}

    with DATA.datastore.transaction() as transaction:
        entity = DATA.datastore.get(key, transaction=transaction)
        if entity is None:
            return {"claimed": False, "reason": "missing", "entity": None}

        status = entity.get("status")
        if status in {"succeeded", "failed", "cancelled", "superseded"}:
            return {"claimed": False, "reason": "terminal", "entity": entity}

        current_lease = entity.get("lease_expires")
        if status == "running" and current_lease and current_lease > now:
            return {"claimed": False, "reason": "active", "entity": entity}

        next_attempt = entity.get("next_attempt_at")
        if status == "retry_wait" and next_attempt and next_attempt > now:
            return {"claimed": False, "reason": "retry-wait", "entity": entity}

        before = dict(entity)
        entity["status"] = "running"
        entity["attempt"] = int(entity.get("attempt") or 0) + 1
        entity["lease_token"] = lease_token
        entity["lease_expires"] = lease_expires
        entity["dispatch_state"] = "claimed"
        entity["status_revision"] = int(entity.get("status_revision") or 0) + 1
        entity.pop("next_attempt_at", None)
        entity["modified"] = now
        transaction.put(entity)
        _update_deferred_job_scheduler_tracking(
            transaction,
            key,
            before,
            entity,
            now,
        )
        return {"claimed": True, "reason": "claimed", "entity": entity}


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_claim_and_checkpoint_are_compare_and_set
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_status_transactions_do_not_write_actor
# @features deferred-jobs
# @dimensions lease checkpoint compare-and-set
# @pairs deferred-jobs:user-write-isolation deferred-jobs:revision deferred-jobs:transaction
@_retry_deferred_job_transaction
def update_claimed_deferred_job(
    identifier,
    lease_token,
    updates,
    now,
    *,
    include_scheduler_control=False,
):
    """Atomically update a job only while the caller owns its lease."""
    key = _deferred_job_key(identifier)
    if key is None:
        return False

    with DATA.datastore.transaction() as transaction:
        entity = DATA.datastore.get(key, transaction=transaction)
        if entity is None or entity.get("lease_token") != lease_token:
            return False
        before = dict(entity)
        for name, value in updates.items():
            if value is None:
                entity.pop(name, None)
            else:
                entity[name] = value
        entity["modified"] = now
        transaction.put(entity)
        scheduler_control = _update_deferred_job_scheduler_tracking(
            transaction,
            key,
            before,
            entity,
            now,
        )
        if include_scheduler_control:
            return {
                "updated": True,
                "scheduler_control": scheduler_control,
            }
        return True


# @testable false
# @covered-by lagniappe/core/tools/database/utility.py::claim_deferred_job_recovery
# @reason recovery-only timestamp normalization is exercised through the transactional claim
def _deferred_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


# @testable false
# @covered-by lagniappe/core/tools/database/utility.py::claim_deferred_job_recovery
# @reason private due-state matrix is exercised through the transactional recovery claim
def _deferred_recovery_due(entity, now, grace):
    dispatching_at = _deferred_datetime(entity.get("dispatched_at"))
    if (
        entity.get("dispatch_state") == "dispatching"
        and dispatching_at
        and dispatching_at + grace > now
    ):
        return False

    status = entity.get("status")
    if status == "running":
        lease_expires = _deferred_datetime(entity.get("lease_expires"))
        return lease_expires is None or lease_expires + grace <= now
    if status == "retry_wait":
        next_attempt = _deferred_datetime(entity.get("next_attempt_at"))
        return next_attempt is None or next_attempt + grace <= now
    if status == "queued":
        if entity.get("dispatch_state") == "dispatched":
            return dispatching_at is None or dispatching_at + grace <= now
        last_update = _deferred_datetime(
            entity.get("modified") or entity.get("created")
        )
        return last_update is None or last_update + grace <= now
    return False


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_recovery_claim_is_compare_and_set
# @features deferred-jobs
# @dimensions reconciliation compare-and-set lease grace maximum-age
@_retry_deferred_job_transaction
def claim_deferred_job_recovery(
    identifier,
    expected_revision,
    now,
    *,
    grace_seconds,
    max_age_seconds,
    stale_updates,
):
    """Claim exactly one stale transition or atomically fail over-age work."""
    key = _deferred_job_key(identifier)
    if key is None:
        return {"claimed": False, "reason": "missing", "entity": None}

    grace = timedelta(seconds=grace_seconds)
    with DATA.datastore.transaction() as transaction:
        entity = DATA.datastore.get(key, transaction=transaction)
        if entity is None:
            return {"claimed": False, "reason": "missing", "entity": None}
        if entity.get("status") not in {"queued", "running", "retry_wait"}:
            return {"claimed": False, "reason": "terminal", "entity": entity}
        if int(entity.get("status_revision") or 0) != int(expected_revision or 0):
            return {"claimed": False, "reason": "revision", "entity": entity}

        before = dict(entity)
        created = _deferred_datetime(entity.get("created"))
        if created and (now - created).total_seconds() >= max_age_seconds:
            for name, value in stale_updates.items():
                if value is None:
                    entity.pop(name, None)
                else:
                    entity[name] = value
            entity["status_revision"] = int(entity.get("status_revision") or 0) + 1
            entity["modified"] = now
            transaction.put(entity)
            _update_deferred_job_scheduler_tracking(
                transaction,
                key,
                before,
                entity,
                now,
            )
            return {
                "claimed": True,
                "reason": "maximum-age",
                "action": "failed",
                "entity": entity,
            }

        if not _deferred_recovery_due(entity, now, grace):
            return {"claimed": False, "reason": "not-due", "entity": entity}

        entity["dispatch_state"] = "dispatching"
        entity["dispatched_at"] = now
        entity["status_revision"] = int(entity.get("status_revision") or 0) + 1
        if entity.get("status") == "retry_wait":
            entity["next_attempt_at"] = now
        entity["modified"] = now
        transaction.put(entity)
        _update_deferred_job_scheduler_tracking(
            transaction,
            key,
            before,
            entity,
            now,
        )
        return {
            "claimed": True,
            "reason": "stale",
            "action": "redispatch",
            "entity": entity,
        }


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_recovery_claim_is_compare_and_set
# @features deferred-jobs
# @dimensions reconciliation dispatch compare-and-set worker-race
@_retry_deferred_job_transaction
def update_deferred_job_recovery_dispatch(
    identifier,
    expected_revision,
    updates,
    now,
):
    """Finish a reconciler dispatch only if no worker has claimed it first."""
    key = _deferred_job_key(identifier)
    if key is None:
        return False
    with DATA.datastore.transaction() as transaction:
        entity = DATA.datastore.get(key, transaction=transaction)
        if (
            entity is None
            or int(entity.get("status_revision") or 0)
            != int(expected_revision or 0)
            or entity.get("dispatch_state") != "dispatching"
        ):
            return False
        for name, value in updates.items():
            if value is None:
                entity.pop(name, None)
            else:
                entity[name] = value
        entity["modified"] = now
        transaction.put(entity)
        return True


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_terminal_transition_revokes_the_active_lease
# @features deferred-jobs
# @dimensions cancellation tombstone lease compare-and-set terminal-race
@_retry_deferred_job_transaction
def transition_active_deferred_job(identifier, updates, now):
    """Atomically tombstone active work without overwriting a terminal result."""
    key = _deferred_job_key(identifier)
    if key is None:
        return {"transitioned": False, "reason": "missing", "entity": None}
    with DATA.datastore.transaction() as transaction:
        entity = DATA.datastore.get(key, transaction=transaction)
        if entity is None:
            return {"transitioned": False, "reason": "missing", "entity": None}
        if entity.get("status") in {"succeeded", "failed", "cancelled", "superseded"}:
            return {"transitioned": False, "reason": "terminal", "entity": entity}
        before = dict(entity)
        for name, value in updates.items():
            if value is None:
                entity.pop(name, None)
            else:
                entity[name] = value
        entity["status_revision"] = int(entity.get("status_revision") or 0) + 1
        entity["modified"] = now
        transaction.put(entity)
        scheduler_control = _update_deferred_job_scheduler_tracking(
            transaction,
            key,
            before,
            entity,
            now,
        )
        result = {
            "transitioned": True,
            "reason": "transitioned",
            "entity": entity,
        }
        if scheduler_control is not None:
            result["scheduler_control"] = scheduler_control
        return result


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
