"""Deferred-job Datastore transactions and Scheduler control records."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict, runtime_checkable

from google.cloud.datastore import Entity, Key
from google.cloud.datastore import query as datastore_query

from config.datastore import encode_urlsafe_key

from .core import DATA, KINDS
from .transactions import retry_aborted

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity as DomainEntity

    from .get import Identifier


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


@runtime_checkable
class _IndexedRow(Protocol):
    exclude_from_indexes: set[str]


class SchedulerSnapshot(TypedDict):
    schema_version: int
    tracked_jobs: list[str]
    active_jobs: int
    desired_state: str
    generation: int
    applied_generation: int
    applied_state: str | None
    sync_lease_token: str | None
    sync_lease_expires: datetime | None


class SchedulerRepair(TypedDict):
    repaired: bool
    reason: str
    control: SchedulerSnapshot


class SchedulerSync(TypedDict):
    recorded: bool
    reason: str
    control: SchedulerSnapshot


class SchedulerClaim(TypedDict):
    acquired: bool
    control: SchedulerSnapshot


class JobUpdate(TypedDict):
    updated: bool
    scheduler_control: SchedulerSnapshot | None


class JobOutcome[Row = Entity](TypedDict):
    entity: Row | None
    reason: str
    scheduler_control: NotRequired[SchedulerSnapshot]


class JobCreate(JobOutcome[Entity | dict[str, object]]):
    created: bool
    lock: NotRequired[Entity | dict[str, object]]


class JobClaim(JobOutcome[Entity]):
    claimed: bool
    action: NotRequired[str]


class JobTransition(JobOutcome[Entity]):
    transitioned: bool


def recent_records(limit: int = 100) -> list[Entity]:
    """Return the newest durable job records for the admin projection."""
    query = DATA.datastore.query(kind=KINDS.jobs.value)
    query.order = ["-modified"]
    return list(query.fetch(limit=min(max(int(limit), 1), 250)))


def recovery_records(*, limit: int) -> list[Entity]:
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
            _deferred_datetime(record.get("modified")) or datetime.now(UTC)
        )
    )
    if limit is not None:
        records = records[: int(limit)]
    return records


def delete_terminal_records(
    *, before: datetime | None = None, batch_size: int = 500
) -> int:
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
        if record.get("autofill_receipt"):
            # Review candidates are product data until editors acknowledge them,
            # even when their diagnostic operation is otherwise purgeable.
            inputs = record.get("inputs") or "{}"
            inputs = json.loads(inputs) if isinstance(inputs, str) else inputs
            target_key = _deferred_job_key((inputs.get("target") or {}).get("id"))
            target = DATA.datastore.get(target_key) if target_key else None
            refs = (target or {}).get("autofill_reviews") or "{}"
            refs = json.loads(refs) if isinstance(refs, str) else refs
            if encode_urlsafe_key(record.key) in refs.values():
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


def _deferred_job_key(identifier):
    if isinstance(identifier, Key):
        return identifier
    if hasattr(identifier, "key"):
        return identifier.key
    from .get import datastore_key

    return datastore_key(identifier)


def _deferred_job_requires_recovery(entity):
    """Return whether a durable job still needs scheduled recovery coverage."""
    return bool(
        entity
        and (
            entity.get("status") in ACTIVE_DEFERRED_JOB_STATUSES
            or entity.get("dispatch_state") == "delivery_pending"
        )
    )


def _deferred_job_recovery_query_state(entity):
    if not entity:
        return (None, False)
    status = entity.get("status")
    return (
        status if status in ACTIVE_DEFERRED_JOB_STATUSES else None,
        entity.get("dispatch_state") == "delivery_pending",
    )


def _deferred_job_scheduler_control_key():
    return DATA.datastore.key(KINDS.site.value, DEFERRED_JOB_SCHEDULER_CONTROL_ID)


def _deferred_job_tracking_id(identifier):
    key = _deferred_job_key(identifier)
    if key is None:
        return str(identifier)
    if not hasattr(key, "to_legacy_urlsafe"):
        return str(key)
    return encode_urlsafe_key(key)


def _deferred_job_scheduler_control(transaction):
    key = _deferred_job_scheduler_control_key()
    control = DATA.datastore.get(key, transaction=transaction)
    if control is None:
        control = Entity(key=key, exclude_from_indexes=("tracked_jobs",))
    else:
        with suppress(AttributeError):
            control.exclude_from_indexes = set(control.exclude_from_indexes) | {"tracked_jobs"}
    return control


def _deferred_job_scheduler_snapshot(control=None) -> SchedulerSnapshot:
    control = control or {}
    tracked_jobs: list[str] = sorted(set(control.get("tracked_jobs") or ()))
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


@retry_aborted
def repair_deferred_job_scheduler_control(
    job_keys: Iterable[Key], expected_generation: int, now: datetime
) -> SchedulerRepair:
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


@retry_aborted
def acquire_deferred_job_scheduler_sync(
    lease_token: str, now: datetime, *, lease_seconds: int
) -> SchedulerClaim:
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


@retry_aborted
def record_deferred_job_scheduler_sync(
    lease_token: str,
    actual_state: str,
    now: datetime,
    *,
    lease_seconds: int,
) -> SchedulerSync:
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


@retry_aborted
def release_deferred_job_scheduler_sync(lease_token: str, now: datetime) -> bool:
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


def get_deferred_job_scheduler_control() -> SchedulerSnapshot:
    """Read normalized recovery/Scheduler control state without creating it."""
    control = DATA.datastore.get(_deferred_job_scheduler_control_key())
    return _deferred_job_scheduler_snapshot(control)


@retry_aborted
def create_deferred_job_if_absent(
    job: DomainEntity,
    notification: DomainEntity | None = None,
    lock: DomainEntity | None = None,
    *,
    writes: Iterable[tuple[DomainEntity, Iterable[str] | None]] = (),
    guards: Iterable[tuple[Key, Mapping[str, object] | None]] = (),
) -> JobCreate:
    """Atomically insert one prepared job, notification, and optional lock."""
    key = _deferred_job_key(job)
    if key is None:
        return {"created": False, "reason": "missing-key", "entity": None}

    notification_owner = getattr(notification, "parent", None)
    ordinary_notification = bool(
        notification_owner
        and getattr(notification, "notification_type", "ordinary") == "ordinary"
    )
    if ordinary_notification and notification_owner is not None:
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
        raw = entity.db
        if isinstance(raw, _IndexedRow):
            raw.exclude_from_indexes = set(entity.exclude_from_index)

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
        from .utility import check_mutation_guards, _put_mutation

        check_mutation_guards(transaction, guards)
        scheduler_control = _update_deferred_job_scheduler_tracking(
            transaction,
            key,
            None,
            job.db,
            datetime.now(UTC),
        )
        if ordinary_notification and notification_owner is not None:
            from . import notifications as notification_database

            notification_database.mutate_notification_aggregate(
                transaction,
                notification_owner,
                ordinary_delta=1,
            )
        for entity in entities:
            transaction.put(entity.db)
        for entity, mask in writes:
            raw = entity.db
            if isinstance(raw, _IndexedRow):
                raw.exclude_from_indexes = set(entity.exclude_from_index)
            _put_mutation(transaction, raw, mask)
        result: JobCreate = {
            "created": True,
            "reason": "created",
            "entity": job.db,
        }
        if lock is not None:
            result["lock"] = lock.db
        if scheduler_control is not None:
            result["scheduler_control"] = scheduler_control
        return result


@retry_aborted
def release_deferred_job_lock(identifier: Identifier, operation: str | None) -> bool:
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


@retry_aborted
def claim_deferred_job(
    identifier: Identifier, lease_token: str, lease_expires: datetime, now: datetime
) -> JobClaim:
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


def owns_deferred_job_claim(identifier: Identifier, lease_token: str) -> bool:
    """Read current token ownership without extending or modifying the lease.

    Terminal delivery can still own a token until cleanup releases it. Mutations
    must continue to fence ownership inside their own transaction.
    """
    key = _deferred_job_key(identifier)
    if key is None:
        return False
    entity = DATA.datastore.get(key)
    return entity is not None and entity.get("lease_token") == lease_token


@retry_aborted
def update_claimed_deferred_job(
    identifier: Identifier,
    lease_token: str,
    updates: Mapping[str, object],
    now: datetime,
    *,
    include_scheduler_control: bool = False,
) -> bool | JobUpdate:
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


def _deferred_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


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


@retry_aborted
def claim_deferred_job_recovery(
    identifier: Identifier,
    expected_revision: int,
    now: datetime,
    *,
    grace_seconds: int,
    max_age_seconds: int,
    stale_updates: Mapping[str, object],
) -> JobClaim:
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
        if (
            created and (now - created).total_seconds() >= max_age_seconds
            and not entity.get("autofill_receipt")
        ):
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


@retry_aborted
def update_deferred_job_recovery_dispatch(
    identifier: Identifier,
    expected_revision: int,
    updates: Mapping[str, object],
    now: datetime,
) -> bool:
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


@retry_aborted
def transition_active_deferred_job(
    identifier: Identifier, updates: Mapping[str, object], now: datetime
) -> JobTransition:
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
        # Applying answers and writing this receipt are one transaction. Once it
        # wins, cancellation must not claim to have prevented that application.
        if entity.get("autofill_receipt"):
            return {"transitioned": False, "reason": "applied", "entity": entity}
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
        result: JobTransition = {
            "transitioned": True,
            "reason": "transitioned",
            "entity": entity,
        }
        if scheduler_control is not None:
            result["scheduler_control"] = scheduler_control
        return result
