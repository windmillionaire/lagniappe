"""Deferred-job Datastore transactions and Scheduler control records."""

from datetime import datetime, timedelta, timezone

from google.cloud.datastore import Entity, Key
from google.cloud.datastore import query as datastore_query
from config.datastore import encode_urlsafe_key

from .core import DATA, KINDS
from .transactions import retry_aborted


ACTIVE_DEFERRED_JOB_STATUSES = {"queued", "running", "retry_wait"}
TERMINAL_DEFERRED_JOB_STATUSES = {
    "succeeded",
    "failed",
    "cancelled",
    "superseded",
}
DEFERRED_JOB_SCHEDULER_CONTROL_ID = "deferred-jobs-control"
DEFERRED_JOB_SCHEDULER_CONTROL_SCHEMA_VERSION = 2
DEFERRED_JOB_SCHEDULER_STATES = {"enabled", "paused"}


# @testable infrastructure
def recent_records(limit=100):
    """Return the newest durable job records for the admin projection."""
    query = DATA.datastore.query(kind=KINDS.jobs.value)
    query.order = ["-modified"]
    return list(query.fetch(limit=min(max(int(limit), 1), 250)))


# @testable infrastructure
def recovery_records(*, limit):
    """Return active or delivery-pending records in recovery order."""
    records = []
    per_status = (
        None
        if limit is None
        else max(int(limit) // len(ACTIVE_DEFERRED_JOB_STATUSES), 1)
    )
    for status in ACTIVE_DEFERRED_JOB_STATUSES:
        query = DATA.datastore.query(kind=KINDS.jobs.value)
        query.add_filter(filter=datastore_query.PropertyFilter("status", "=", status))
        query.order = ["modified"]
        records.extend(query.fetch(limit=per_status))

    delivery_query = DATA.datastore.query(kind=KINDS.jobs.value)
    delivery_query.add_filter(
        filter=datastore_query.PropertyFilter(
            "dispatch_state",
            "=",
            "delivery_pending",
        )
    )
    delivery_query.order = ["modified"]
    records.extend(delivery_query.fetch(limit=per_status))
    records = list({record.key: record for record in records}.values())
    records.sort(
        key=lambda record: (
            _deferred_datetime(record.get("modified")) or datetime.now(timezone.utc)
        )
    )
    if limit is not None:
        records = records[: int(limit)]
    return records


# @testable true
# @tests tests_unit/test_023b_deferred_job_service.py::test_delete_terminal_jobs_preserves_active_and_incomplete_delivery
# @matrix deferred-jobs : retention terminal-delivery
def delete_terminal_records(*, before=None, batch_size=500):
    """Delete retained terminal jobs without touching unfinished delivery."""
    batch_size = max(int(batch_size), 1)
    query = DATA.datastore.query(kind=KINDS.jobs.value)
    if before is not None:
        query.add_filter(filter=datastore_query.PropertyFilter("created", "<", before))
        query.order = ["created"]

    deleted = 0
    keys = []
    for record in query.fetch():
        created = _deferred_datetime(record.get("created"))
        if before is not None and (created is None or created >= before):
            continue
        if record.get("status") not in TERMINAL_DEFERRED_JOB_STATUSES:
            continue
        if record.get("dispatch_state") == "delivery_pending":
            continue
        keys.append(record.key)
        if len(keys) < batch_size:
            continue
        DATA.datastore.delete_multi(keys)
        deleted += len(keys)
        keys = []

    if keys:
        DATA.datastore.delete_multi(keys)
        deleted += len(keys)
    return deleted


# @testable infrastructure
def _deferred_job_key(identifier):
    if isinstance(identifier, Key):
        return identifier
    if hasattr(identifier, "key"):
        return identifier.key
    from .get import datastore_key

    return datastore_key(identifier)


# @testable true
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_tracking_membership_follows_recovery_required_state
# @matrix cloud-scheduler deferred-jobs : durable-membership idempotency terminal-delivery
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
# @covered-by lagniappe/core/tools/database/deferred_jobs.py::_update_deferred_job_scheduler_tracking
def _deferred_job_recovery_query_state(entity):
    if not entity:
        return (None, False)
    status = entity.get("status")
    return (
        status if status in ACTIVE_DEFERRED_JOB_STATUSES else None,
        entity.get("dispatch_state") == "delivery_pending",
    )


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/deferred_jobs.py::_update_deferred_job_scheduler_tracking
def _deferred_job_scheduler_control_key():
    return DATA.datastore.key(KINDS.site.value, DEFERRED_JOB_SCHEDULER_CONTROL_ID)


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/deferred_jobs.py::_update_deferred_job_scheduler_tracking
def _deferred_job_tracking_id(identifier):
    key = _deferred_job_key(identifier)
    if key is None:
        return str(identifier)
    if not hasattr(key, "to_legacy_urlsafe"):
        return str(key)
    return encode_urlsafe_key(key)


# @testable infrastructure
# @covered-by lagniappe/core/tools/database/deferred_jobs.py::_update_deferred_job_scheduler_tracking
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
# @covered-by lagniappe/core/tools/database/deferred_jobs.py::get_deferred_job_scheduler_control
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
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_tracking_membership_follows_recovery_required_state
# @matrix cloud-scheduler deferred-jobs : desired-state durable-membership transaction
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
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_control_repair_is_revision_checked
# @matrix cloud-scheduler deferred-jobs : drift-repair optimistic-concurrency
@retry_aborted
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
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_sync_serializes_state_changes_and_converges_latest_generation
# @matrix cloud-scheduler deferred-jobs : distributed-lease generation race
@retry_aborted
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
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_sync_serializes_state_changes_and_converges_latest_generation
# @matrix cloud-scheduler deferred-jobs : distributed-lease generation provider-state
@retry_aborted
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
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_sync_releases_lease_after_provider_failure
# @matrix cloud-scheduler deferred-jobs : distributed-lease provider-failure
@retry_aborted
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
# @tests tests_unit/test_023f_deferred_job_scheduler.py::test_scheduler_control_repair_is_revision_checked
# @matrix cloud-scheduler deferred-jobs : defaults state-read
def get_deferred_job_scheduler_control():
    """Read normalized recovery/Scheduler control state without creating it."""
    control = DATA.datastore.get(_deferred_job_scheduler_control_key())
    return _deferred_job_scheduler_snapshot(control)


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_create_is_transactionally_idempotent
# @matrix deferred-jobs : get-or-create idempotency notification start
# @pair notifications:aggregate-count
@retry_aborted
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
        from . import notifications as notification_database

        notification_database.ensure_notification_aggregate(notification_owner)

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
            notification_database.mutate_notification_aggregate(
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
# @tests tests_unit/test_023a_deferred_job_properties.py::test_autofill_lock_cleanup_is_compare_and_delete
# @matrix deferred-jobs : compare-and-set form-lock
@retry_aborted
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
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_claim_and_checkpoint_are_compare_and_set
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_status_transactions_do_not_write_actor
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_transactions_retry_aborted_contention
# @matrix deferred-jobs : claim compare-and-set duplicate-delivery lease retry revision transaction transaction-contention user-write-isolation
@retry_aborted
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
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_claim_and_checkpoint_are_compare_and_set
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_status_transactions_do_not_write_actor
# @matrix deferred-jobs : checkpoint compare-and-set lease revision transaction user-write-isolation
@retry_aborted
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
# @covered-by lagniappe/core/tools/database/deferred_jobs.py::claim_deferred_job_recovery
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
# @covered-by lagniappe/core/tools/database/deferred_jobs.py::claim_deferred_job_recovery
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
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_recovery_claim_is_compare_and_set
# @matrix deferred-jobs : compare-and-set grace lease maximum-age reconciliation
@retry_aborted
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
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_recovery_claim_is_compare_and_set
# @matrix deferred-jobs : compare-and-set dispatch reconciliation worker-race
@retry_aborted
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
            or int(entity.get("status_revision") or 0) != int(expected_revision or 0)
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
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_terminal_transition_revokes_the_active_lease
# @matrix deferred-jobs : cancellation compare-and-set lease terminal-race tombstone
@retry_aborted
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
