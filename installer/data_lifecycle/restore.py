"""Resumable in-place recovery-set merge into the default database."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from google.cloud.datastore import Entity, Key

from config.datastore import (
    DEFAULT_DATABASE_ID,
    decode_urlsafe_key,
    encode_urlsafe_key,
)
from installer.errors import ProviderNotFound
from installer.state import record_mutation, record_step

from .backup import CONSISTENCY_NOTICE, load_backup
from .provider import (
    RESTORE_ROOT_PREFIX,
    DataLifecycleError,
    ProviderContext,
    validate_backup_id,
    validate_database_id,
)
from .state import LifecycleCheckpoint, secure_directory


RESTORE_NORMALIZE_PAGE_SIZE = 250
SERIALIZED_REFERENCE_PROPERTIES = frozenset({"submission", "default_submission"})
DEFERRED_JOB_CONTROL_ID = "deferred-jobs-control"
QUEUE_SNAPSHOT_FORMAT = "lagniappe-purged-cloud-tasks"
RESTORE_RECORD_FORMAT = "lagniappe-restore-record"
RESTORE_RECORD_SCHEMA = 1
RESTORE_JOURNAL_FORMAT = "lagniappe-restore-journal"
RESTORE_JOURNAL_STATE_KEYS = frozenset(
    {
        "operation_id",
        "status",
        "checkpoint",
        "journal_revision",
        "target_create_operation",
        "target_created",
        "import_operation",
        "import_complete",
        "indexes_ready",
        "normalized",
        "migrated",
        "target_validated",
        "candidate_deployed",
        "maintenance_deployed",
        "scheduler_paused",
        "queue_paused",
        "maintenance_active",
        "request_drain_complete",
        "queue_snapshot",
        "purge_requested_at",
        "queue_purged",
        "queue_empty",
        "cache_rebuilt",
        "candidate_active",
        "setting_persisted",
        "configuration_sha256_after",
        "queue_resumed",
        "restore_record",
        "source_setting_persisted",
        "source_configuration_sha256_after",
        "source_cache_rebuilt",
        "source_traffic_active",
        "queue_state_restored",
        "scheduler_state_restored",
        "rollback_record",
        "rolled_back",
        "safety_snapshot_time",
        "safety_clone_operation",
        "safety_clone_created",
        "safety_assets",
        "import_operation",
        "assets_restored",
        "asset_result",
        "scheduled_tasks_reconciled",
        "scheduled_task_result",
        "traffic_restored",
        "scheduler_resumed",
        "safety_clone_cleaned",
    }
)
RESTORE_JOURNAL_BOOLEAN_KEYS = frozenset(
    key
    for key in RESTORE_JOURNAL_STATE_KEYS
    if key
    not in {
        "operation_id",
        "status",
        "checkpoint",
        "journal_revision",
        "target_create_operation",
        "import_operation",
        "queue_snapshot",
        "purge_requested_at",
        "configuration_sha256_after",
        "restore_record",
        "source_configuration_sha256_after",
        "rollback_record",
        "safety_snapshot_time",
        "safety_clone_operation",
        "safety_assets",
        "asset_result",
        "scheduled_task_result",
    }
)


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason journal projection is exercised through both resumable state machines
def _remote_journal_payload(context, checkpoint, filename):
    state = checkpoint.payload
    if not isinstance(state, dict) or not isinstance(state.get("plan"), dict):
        raise DataLifecycleError("Restore checkpoint cannot be mirrored yet.")
    plan = dict(state["plan"])
    if "index_path" in plan:
        plan["index_path"] = "index.yaml"
    return {
        "format": RESTORE_JOURNAL_FORMAT,
        "schema_version": RESTORE_RECORD_SCHEMA,
        "project_id": context.project_id,
        "application_version": context.application_version,
        "restore_id": plan["restore_id"],
        "backup_id": plan["backup_id"],
        "journal": filename,
        "plan": plan,
        "state": {
            key: state[key]
            for key in sorted(RESTORE_JOURNAL_STATE_KEYS)
            if key in state
        },
        "updated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason remote journal trust checks are exercised through state-machine mirroring
def _validate_remote_journal(context, payload, *, restore_id=None, filename=None):
    plan = payload.get("plan") if isinstance(payload, dict) else None
    state = payload.get("state") if isinstance(payload, dict) else None
    required_plan = {
        "restore_id",
        "backup_id",
        "project_id",
        "application_version",
        "old_database",
        "target_database",
        "queue",
        "queue_location",
        "reconciler",
        "maintenance_version",
        "original_traffic",
        "traffic_split_by",
    }
    if (
        not isinstance(payload, dict)
        or payload.get("format") != RESTORE_JOURNAL_FORMAT
        or payload.get("schema_version") != RESTORE_RECORD_SCHEMA
        or payload.get("project_id") != context.project_id
        or not isinstance(plan, dict)
        or not required_plan.issubset(plan)
        or not isinstance(state, dict)
        or not set(state).issubset(RESTORE_JOURNAL_STATE_KEYS)
        or payload.get("restore_id") != plan.get("restore_id")
        or payload.get("backup_id") != plan.get("backup_id")
        or payload.get("application_version")
        != plan.get("application_version")
        or plan.get("project_id") != context.project_id
        or (restore_id is not None and payload.get("restore_id") != restore_id)
        or (filename is not None and payload.get("journal") != filename)
    ):
        raise DataLifecycleError("Remote restore journal is malformed or foreign.")
    try:
        validate_backup_id(plan["backup_id"])
        validate_database_id(plan["old_database"])
        validate_database_id(plan["target_database"])
    except (KeyError, TypeError, DataLifecycleError) as error:
        raise DataLifecycleError("Remote restore journal plan is invalid.") from error
    if any(
        key in state and not isinstance(state[key], bool)
        for key in RESTORE_JOURNAL_BOOLEAN_KEYS
    ):
        raise DataLifecycleError("Remote restore journal checkpoint flags are invalid.")
    revision = state.get("journal_revision")
    if not isinstance(revision, int) or revision < 1:
        raise DataLifecycleError("Remote restore journal revision is invalid.")
    return payload


# @testable infrastructure
class MirroredRestoreCheckpoint:
    """Mirror a private local checkpoint into a secret-free recovery object."""

    def __init__(self, local, context, *, filename="journal.json"):
        if filename not in {"journal.json", "rollback-journal.json"}:
            raise DataLifecycleError("Remote restore journal filename is invalid.")
        self.local = local
        self.context = context
        self.filename = filename

    @property
    def payload(self):
        return self.local.payload

    def load(self):
        return self.local.load()

    def _sync(self):
        desired = _remote_journal_payload(self.context, self.local, self.filename)
        object_name = _restore_object_name(desired["restore_id"], self.filename)
        blob = self.context.bucket.blob(object_name)
        if not blob.exists():
            self.context.upload_json_create_only(object_name, desired)
            return
        existing, _blob = self.context.load_json_object(object_name)
        existing = _validate_remote_journal(
            self.context,
            existing,
            restore_id=desired["restore_id"],
            filename=self.filename,
        )
        remote_revision = existing["state"]["journal_revision"]
        local_revision = desired["state"]["journal_revision"]
        if remote_revision > local_revision:
            self.local.payload.update(existing["state"])
            self.local.payload["plan"] = _localize_remote_plan(existing["plan"])
            self.local.save()
            return
        if remote_revision == local_revision:
            return
        self.context.upload_json_replace(object_name, desired)

    def start(self, operation_id, **values):
        payload = self.local.start(
            operation_id, journal_revision=1, **values
        )
        self._sync()
        return payload

    def update(self, checkpoint, **values):
        revision = int((self.local.payload or {}).get("journal_revision") or 0) + 1
        payload = self.local.update(
            checkpoint, journal_revision=revision, **values
        )
        self._sync()
        return payload

    def finish(self, **values):
        self.update("complete", status="complete", **values)


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason remote plans are localized only at public resumption boundaries
def _localize_remote_plan(plan):
    localized = dict(plan)
    if "index_path" in localized:
        localized["index_path"] = str(
            (Path(__file__).resolve().parents[2] / "index.yaml").resolve()
        )
    return localized


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason remote discovery is exercised through public restore resumption
def _remote_restore_for_backup(context, backup_id):
    matches = []
    for blob in context.list_objects(f"{RESTORE_ROOT_PREFIX}/"):
        if not str(blob.name).endswith("/journal.json"):
            continue
        payload, _blob = context.load_json_object(blob.name)
        payload = _validate_remote_journal(
            context, payload, filename="journal.json"
        )
        if payload.get("backup_id") == backup_id:
            matches.append(payload)
    if len(matches) > 1:
        raise DataLifecycleError(
            "Multiple remote restore journals match this backup; remove the obsolete journal before resuming."
        )
    return matches[0] if matches else None


# @testable false
# @covered-by installer/data_lifecycle/restore.py::_legacy_rollback_restore
# @reason remote restore lookup is exercised through public rollback recovery
def _remote_restore_by_id(context, restore_id):
    object_name = _restore_object_name(restore_id, "journal.json")
    blob = context.bucket.blob(object_name)
    if not blob.exists():
        return None
    payload, _blob = context.load_json_object(object_name)
    return _validate_remote_journal(
        context, payload, restore_id=restore_id, filename="journal.json"
    )


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason remote-to-local hydration is exercised through public restore resumption
def _hydrate_local_checkpoint(local, remote):
    plan = _localize_remote_plan(remote["plan"])
    local.start(
        plan["restore_id"],
        backup_id=plan["backup_id"],
        plan=plan,
        journal_revision=remote["state"]["journal_revision"],
    )
    local.payload.update(remote["state"])
    local.payload["plan"] = plan
    local.save()
    return local.payload


# @testable false
# @covered-by installer/data_lifecycle/restore.py::capture_queue_snapshot
# @covered-by installer/data_lifecycle/restore.py::publish_successful_restore_record
# @reason restore artifact paths are exercised through their two public publishers
def _restore_object_name(restore_id, filename):
    restore_id = str(restore_id or "").strip()
    if (
        not restore_id
        or not all(character.isalnum() or character == "-" for character in restore_id)
        or "/" in str(filename)
        or "\\" in str(filename)
    ):
        raise DataLifecycleError("Restore artifact identity is invalid.")
    return f"{RESTORE_ROOT_PREFIX}/{restore_id}/{filename}"


# @testable false
# @covered-by installer/data_lifecycle/restore.py::capture_queue_snapshot
# @covered-by installer/data_lifecycle/restore.py::publish_successful_restore_record
# @reason canonical audit hashing is exercised through immutable restore artifacts
def _audit_sha256(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# @testable false
# @covered-by installer/data_lifecycle/restore.py::capture_queue_snapshot
# @reason immutable snapshot validation is exercised through capture resumption
def _queue_snapshot_descriptor(context, plan, payload, object_name):
    queue_path = (
        f"projects/{context.project_id}/locations/{plan['queue_location']}"
        f"/queues/{plan['queue']}"
    )
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if (
        not isinstance(tasks, list)
        or payload.get("format") != QUEUE_SNAPSHOT_FORMAT
        or payload.get("schema_version") != RESTORE_RECORD_SCHEMA
        or payload.get("restore_id") != plan["restore_id"]
        or payload.get("project_id") != context.project_id
        or payload.get("queue") != plan["queue"]
        or payload.get("location") != plan["queue_location"]
        or not isinstance(payload.get("captured_at"), str)
        or not payload["captured_at"]
        or payload.get("task_count") != len(tasks)
        or any(
            not isinstance(task, dict)
            or not str(task.get("name") or "").startswith(f"{queue_path}/tasks/")
            for task in tasks
        )
    ):
        raise DataLifecycleError("Purged-task snapshot is malformed or foreign.")
    return {
        "object_name": object_name,
        "uri": f"gs://{context.recovery_bucket}/{object_name}",
        "sha256": _audit_sha256(payload),
        "task_count": len(tasks),
        "captured_at": payload.get("captured_at"),
    }


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_queue_snapshot_preserves_full_task_definitions
# @pairs data-lifecycle:queue-purge-audit data-lifecycle:immutable-restore-record
def capture_queue_snapshot(
    context,
    plan,
    *,
    captured_at=None,
    filename="purged-tasks.json",
    observation="full-view tasks visible after queue pause and maintenance",
):
    """Persist the complete tasks observed immediately before a restore purge."""
    restore_id = str(plan["restore_id"])
    queue_name = str(plan["queue"])
    location = str(plan["queue_location"])
    if filename not in {"purged-tasks.json", "rollback-purged-tasks.json"}:
        raise DataLifecycleError("Queue snapshot filename is invalid.")
    object_name = _restore_object_name(restore_id, filename)
    snapshot_blob = context.bucket.blob(object_name)
    if snapshot_blob.exists():
        payload, _blob = context.load_json_object(object_name)
        return _queue_snapshot_descriptor(context, plan, payload, object_name)
    captured_at = captured_at or datetime.now(timezone.utc)
    if not isinstance(captured_at, datetime) or captured_at.tzinfo is None:
        raise DataLifecycleError("Queue snapshot time must include a timezone.")
    timestamp = captured_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    tasks = sorted(
        context.list_queue_tasks(queue_name, location),
        key=lambda task: str(task.get("name") or ""),
    )
    payload = {
        "format": QUEUE_SNAPSHOT_FORMAT,
        "schema_version": RESTORE_RECORD_SCHEMA,
        "restore_id": restore_id,
        "project_id": context.project_id,
        "queue": queue_name,
        "location": location,
        "captured_at": timestamp,
        "observation": str(observation),
        "task_count": len(tasks),
        "tasks": tasks,
    }
    descriptor = _queue_snapshot_descriptor(context, plan, payload, object_name)
    context.upload_json_create_only(object_name, payload)
    return descriptor


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_successful_restore_record_references_purged_task_snapshot
# @pairs data-lifecycle:queue-purge-audit data-lifecycle:restore-completion
def publish_successful_restore_record(
    context,
    plan,
    queue_snapshot,
    *,
    purge_requested_at,
    completed_at=None,
):
    """Publish the immutable completion record only after a successful cutover."""
    completed_at = completed_at or datetime.now(timezone.utc)
    if (
        not isinstance(completed_at, datetime)
        or completed_at.tzinfo is None
        or not isinstance(purge_requested_at, datetime)
        or purge_requested_at.tzinfo is None
    ):
        raise DataLifecycleError("Restore record times must include a timezone.")
    restore_id = str(plan["restore_id"])
    expected_snapshot = _restore_object_name(restore_id, "purged-tasks.json")
    expected_uri = f"gs://{context.recovery_bucket}/{expected_snapshot}"
    if (
        not isinstance(queue_snapshot, dict)
        or queue_snapshot.get("object_name") != expected_snapshot
        or queue_snapshot.get("uri") != expected_uri
        or not isinstance(queue_snapshot.get("task_count"), int)
        or queue_snapshot["task_count"] < 0
        or len(str(queue_snapshot.get("sha256") or "")) != 64
        or any(
            character not in "0123456789abcdef"
            for character in str(queue_snapshot.get("sha256") or "")
        )
    ):
        raise DataLifecycleError("Purged-task snapshot does not belong to this restore.")
    object_name = _restore_object_name(restore_id, "record.json")
    record_blob = context.bucket.blob(object_name)
    if record_blob.exists():
        existing, _blob = context.load_json_object(object_name)
        if (
            not isinstance(existing, dict)
            or existing.get("format") != RESTORE_RECORD_FORMAT
            or existing.get("status") != "complete"
            or existing.get("restore_id") != restore_id
            or existing.get("project_id") != context.project_id
            or existing.get("purged_tasks") != queue_snapshot
        ):
            raise DataLifecycleError("Existing successful restore record conflicts.")
        return existing
    record = {
        "format": RESTORE_RECORD_FORMAT,
        "schema_version": RESTORE_RECORD_SCHEMA,
        "status": "complete",
        "restore_id": restore_id,
        "backup_id": plan["backup_id"],
        "project_id": context.project_id,
        "application_version": context.application_version,
        "source_database_id": plan["old_database"],
        "backup_source_database_id": plan.get(
            "backup_source_database", plan["old_database"]
        ),
        "target_database_id": plan["target_database"],
        "queue": plan["queue"],
        "queue_location": plan["queue_location"],
        "reconciler": plan["reconciler"],
        "candidate_version": plan["candidate_version"],
        "maintenance_version": plan["maintenance_version"],
        "original_traffic": plan["original_traffic"],
        "traffic_split_by": plan["traffic_split_by"],
        "queue_state_before": plan.get("provider_observations", {}).get(
            "queue_state"
        ),
        "reconciler_state_before": plan.get("provider_observations", {}).get(
            "reconciler_state"
        ),
        "purge_requested_at": purge_requested_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "completed_at": completed_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "purged_tasks": dict(queue_snapshot),
        "storage_restored": False,
    }
    context.upload_json_create_only(object_name, record)
    return record


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason unreachable pre-release rollback artifact retained only for local journal diagnosis
def _legacy_publish_rollback_record(context, plan, queue_snapshot, *, completed_at=None):
    """Publish one immutable audit record after rollback is fully converged."""
    completed_at = completed_at or datetime.now(timezone.utc)
    if not isinstance(completed_at, datetime) or completed_at.tzinfo is None:
        raise DataLifecycleError("Rollback completion time must include a timezone.")
    expected_snapshot = _restore_object_name(
        plan["restore_id"], "rollback-purged-tasks.json"
    )
    if (
        not isinstance(queue_snapshot, dict)
        or queue_snapshot.get("object_name") != expected_snapshot
        or queue_snapshot.get("uri")
        != f"gs://{context.recovery_bucket}/{expected_snapshot}"
        or not isinstance(queue_snapshot.get("task_count"), int)
        or queue_snapshot["task_count"] < 0
        or len(str(queue_snapshot.get("sha256") or "")) != 64
        or any(
            character not in "0123456789abcdef"
            for character in str(queue_snapshot.get("sha256") or "")
        )
    ):
        raise DataLifecycleError("Rollback task snapshot does not belong to this restore.")
    object_name = _restore_object_name(plan["restore_id"], "rollback.json")
    blob = context.bucket.blob(object_name)
    if blob.exists():
        existing, _blob = context.load_json_object(object_name)
        if (
            existing.get("restore_id") != plan["restore_id"]
            or existing.get("project_id") != context.project_id
            or existing.get("purged_tasks") != queue_snapshot
        ):
            raise DataLifecycleError("Existing rollback record conflicts.")
        return existing
    record = {
        "format": "lagniappe-rollback-record",
        "schema_version": RESTORE_RECORD_SCHEMA,
        "status": "complete",
        "restore_id": plan["restore_id"],
        "backup_id": plan["backup_id"],
        "project_id": context.project_id,
        "restored_database_id": plan["target_database"],
        "active_database_id": plan["old_database"],
        "queue": plan["queue"],
        "queue_location": plan["queue_location"],
        "purged_tasks": dict(queue_snapshot),
        "completed_at": completed_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "target_database_deleted": False,
        "storage_restored": False,
    }
    context.upload_json_create_only(object_name, record)
    return record


# @testable false
# @covered-by installer/data_lifecycle/restore.py::normalize_restored_entity
# @reason partition validation is exercised through complete entity normalization
def _rebind_restored_key(key, *, project_id, source_database_id, target_database_id):
    if not isinstance(key, Key):
        return key, 0
    source_project = str(key.project or "")
    source_database = str(key.database or DEFAULT_DATABASE_ID)
    if source_project != project_id:
        raise DataLifecycleError(
            f"Restored key belongs to another project: {source_project!r}."
        )
    if source_database == target_database_id:
        return key, 0
    if source_database != source_database_id:
        raise DataLifecycleError(
            f"Restored key names an unexpected database: {source_database!r}."
        )
    rebound = Key(
        *key.flat_path,
        project=project_id,
        namespace=key.namespace,
        database=None if target_database_id == DEFAULT_DATABASE_ID else target_database_id,
    )
    return rebound, 1


# @testable false
# @covered-by installer/data_lifecycle/restore.py::normalize_restored_entity
# @reason recursive native values are exercised through complete entity normalization
def _normalize_native_value(value, *, project_id, source_database_id, target_database_id):
    if isinstance(value, Key):
        return _rebind_restored_key(
            value,
            project_id=project_id,
            source_database_id=source_database_id,
            target_database_id=target_database_id,
        )
    if isinstance(value, Entity):
        embedded_key, changed = _rebind_restored_key(
            value.key,
            project_id=project_id,
            source_database_id=source_database_id,
            target_database_id=target_database_id,
        )
        normalized = Entity(
            key=embedded_key,
            exclude_from_indexes=tuple(value.exclude_from_indexes or ()),
        )
        for name, item in value.items():
            normalized_item, item_changed = _normalize_native_value(
                item,
                project_id=project_id,
                source_database_id=source_database_id,
                target_database_id=target_database_id,
            )
            normalized[name] = normalized_item
            changed += item_changed
        return normalized, changed
    if isinstance(value, list):
        normalized = []
        changed = 0
        for item in value:
            normalized_item, item_changed = _normalize_native_value(
                item,
                project_id=project_id,
                source_database_id=source_database_id,
                target_database_id=target_database_id,
            )
            normalized.append(normalized_item)
            changed += item_changed
        return normalized, changed
    if isinstance(value, tuple):
        normalized, changed = _normalize_native_value(
            list(value),
            project_id=project_id,
            source_database_id=source_database_id,
            target_database_id=target_database_id,
        )
        return tuple(normalized), changed
    if isinstance(value, dict):
        normalized = {}
        changed = 0
        for name, item in value.items():
            normalized_item, item_changed = _normalize_native_value(
                item,
                project_id=project_id,
                source_database_id=source_database_id,
                target_database_id=target_database_id,
            )
            normalized[name] = normalized_item
            changed += item_changed
        return normalized, changed
    return value, 0


# @testable false
# @covered-by installer/data_lifecycle/restore.py::normalize_restored_entity
# @reason entity-details recognition is exercised through serialized submission normalization
def _normalize_reference_details(value, *, project_id, source_database_id, target_database_id):
    changed = 0
    if isinstance(value, list):
        normalized = []
        for item in value:
            normalized_item, item_changed = _normalize_reference_details(
                item,
                project_id=project_id,
                source_database_id=source_database_id,
                target_database_id=target_database_id,
            )
            normalized.append(normalized_item)
            changed += item_changed
        return normalized, changed
    if not isinstance(value, dict):
        return value, 0
    normalized = {}
    for name, item in value.items():
        normalized_item, item_changed = _normalize_reference_details(
            item,
            project_id=project_id,
            source_database_id=source_database_id,
            target_database_id=target_database_id,
        )
        normalized[name] = normalized_item
        changed += item_changed
    identifier = normalized.get("id")
    if not isinstance(identifier, str) or not isinstance(normalized.get("hash"), str):
        return normalized, changed
    try:
        key = decode_urlsafe_key(identifier)
    except (UnicodeError, ValueError):
        return normalized, changed
    rebound, key_changed = _rebind_restored_key(
        key,
        project_id=project_id,
        source_database_id=source_database_id,
        target_database_id=target_database_id,
    )
    if key_changed:
        normalized["id"] = encode_urlsafe_key(rebound)
        changed += 1
    return normalized, changed


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_normalizes_persisted_keys_before_cache_rebuild
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_discards_deferred_execution_state
# @pairs data-lifecycle:restore-key-normalization data-lifecycle:serialized-entity-details
# @pair data-lifecycle:deferred-state-retirement
def normalize_restored_entity(
    entity,
    *,
    project_id,
    source_database_id,
    target_database_id,
):
    """Rebind durable references and clear stale active-operation pointers."""
    source_database_id = validate_database_id(source_database_id)
    target_database_id = validate_database_id(target_database_id)
    key_database = str(entity.key.database or DEFAULT_DATABASE_ID)
    if str(entity.key.project or "") != project_id or key_database != target_database_id:
        raise DataLifecycleError("Restored entity is not stored in the expected target database.")
    counts = {
        "native_keys": 0,
        "serialized_ids": 0,
        "deferred_references": 0,
    }
    for name, value in list(entity.items()):
        if name == "deferred_job":
            entity.pop(name, None)
            counts["deferred_references"] += 1
            continue
        normalized, changed = _normalize_native_value(
            value,
            project_id=project_id,
            source_database_id=source_database_id,
            target_database_id=target_database_id,
        )
        counts["native_keys"] += changed
        if name in SERIALIZED_REFERENCE_PROPERTIES and isinstance(normalized, str):
            try:
                decoded = json.loads(normalized)
            except json.JSONDecodeError:
                pass
            else:
                decoded, serialized_changed = _normalize_reference_details(
                    decoded,
                    project_id=project_id,
                    source_database_id=source_database_id,
                    target_database_id=target_database_id,
                )
                if serialized_changed:
                    normalized = json.dumps(
                        decoded,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    counts["serialized_ids"] += serialized_changed
        if name == "process" and isinstance(normalized, str):
            try:
                process = json.loads(normalized)
            except json.JSONDecodeError:
                process = None
            report = process.get("report") if isinstance(process, dict) else None
            if isinstance(report, dict):
                removed = sum(
                    report.pop(reference_name, None) is not None
                    for reference_name in ("deferred-job", "deferred_job")
                )
                if removed:
                    normalized = json.dumps(
                        process,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    counts["deferred_references"] += removed
        if changed or normalized != value:
            entity[name] = normalized
    return counts


# @testable false
# @covered-by installer/data_lifecycle/restore.py::normalize_restored_database
# @reason provider pagination is exercised through the bounded database normalizer
def _restore_query_pages(query, *, page_size):
    cursor = None
    while True:
        iterator = query.fetch(limit=page_size, start_cursor=cursor)
        try:
            rows = list(next(iterator.pages))
        except StopIteration:
            return
        if not rows:
            return
        yield rows
        cursor = iterator.next_page_token
        if not cursor or len(rows) < page_size:
            return


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_normalizes_persisted_keys_before_cache_rebuild
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_discards_deferred_execution_state
# @pairs data-lifecycle:restore-key-normalization data-lifecycle:bounded-restore-scan
# @pair data-lifecycle:deferred-state-retirement
def normalize_restored_database(
    client,
    *,
    project_id,
    source_database_id,
    target_database_id,
    page_size=RESTORE_NORMALIZE_PAGE_SIZE,
    kind_prefix=None,
):
    """Normalize durable references and discard restored execution state."""
    source_database_id = validate_database_id(source_database_id)
    target_database_id = validate_database_id(target_database_id)
    if source_database_id == target_database_id:
        raise DataLifecycleError("Restore key normalization requires distinct databases.")
    if kind_prefix is None:
        from config import SETTINGS

        kind_prefix = str(SETTINGS.APP.get("PREFIX") or "")
    discarded_kinds = {f"{kind_prefix}jobs", f"{kind_prefix}job_locks"}
    site_kind = f"{kind_prefix}site"
    namespaces = {""}
    namespace_query = client.query(kind="__namespace__")
    namespace_query.keys_only()
    for page in _restore_query_pages(namespace_query, page_size=page_size):
        namespaces.update(
            str(row.key.id_or_name)
            for row in page
            if row.key.id_or_name not in (None, 1)
        )
    counts = {
        "entities_scanned": 0,
        "entities_written": 0,
        "native_keys": 0,
        "serialized_ids": 0,
        "deferred_records_deleted": 0,
        "deferred_references_cleared": 0,
    }
    for namespace in sorted(namespaces):
        kind_query = client.query(kind="__kind__", namespace=namespace or None)
        kind_query.keys_only()
        kinds = set()
        for page in _restore_query_pages(kind_query, page_size=page_size):
            kinds.update(
                str(row.key.id_or_name)
                for row in page
                if row.key.id_or_name
            )
        for kind in sorted(kinds):
            query = client.query(kind=kind, namespace=namespace or None)
            if kind in discarded_kinds:
                query.keys_only()
                for page in _restore_query_pages(query, page_size=page_size):
                    keys = [entity.key for entity in page]
                    counts["entities_scanned"] += len(keys)
                    if keys:
                        client.delete_multi(keys)
                        counts["deferred_records_deleted"] += len(keys)
                continue
            for page in _restore_query_pages(query, page_size=page_size):
                writes = []
                deletes = []
                for entity in page:
                    counts["entities_scanned"] += 1
                    if (
                        kind == site_kind
                        and entity.key.id_or_name == DEFERRED_JOB_CONTROL_ID
                    ):
                        deletes.append(entity.key)
                        continue
                    changed = normalize_restored_entity(
                        entity,
                        project_id=project_id,
                        source_database_id=source_database_id,
                        target_database_id=target_database_id,
                    )
                    counts["native_keys"] += changed["native_keys"]
                    counts["serialized_ids"] += changed["serialized_ids"]
                    counts["deferred_references_cleared"] += changed[
                        "deferred_references"
                    ]
                    if any(changed.values()):
                        writes.append(entity)
                if deletes:
                    client.delete_multi(deletes)
                    counts["deferred_records_deleted"] += len(deletes)
                if writes:
                    client.put_multi(writes)
                    counts["entities_written"] += len(writes)
    return counts


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_plan
# @reason provider location aliases are exercised by restore preflight
def _location(value):
    value = str(value or "").strip().casefold()
    return {"us": "nam5", "eu": "eur3"}.get(value, value)


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_plan
# @reason location compatibility is a restore-preflight implementation detail
def _compatible_locations(first, second):
    return bool(_location(first) and _location(first) == _location(second))


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_target_validation_requires_owner_and_reserved_models
# @pairs data-lifecycle:restore-validation data-lifecycle:owner-invariant
def validate_restored_database(
    client,
    *,
    kind_prefix="",
    owner_email,
):
    """Verify the minimum data invariants needed before a restored app can serve."""
    prefix = str(kind_prefix or "")
    owner_email = str(owner_email or "").strip().casefold()
    if not owner_email:
        raise DataLifecycleError("Configured owner email is unavailable.")
    from google.cloud.datastore.query import PropertyFilter

    model_query = client.query(kind=f"{prefix}models")
    model_query.add_filter(filter=PropertyFilter("reserved", "=", True))
    reserved = list(model_query.fetch(limit=3))
    user_query = client.query(kind=f"{prefix}users")
    user_query.add_filter(filter=PropertyFilter("email", "=", owner_email))
    users = list(user_query.fetch(limit=2))
    owners = [
        entity
        for entity in users
        if bool(entity.get("owner"))
        and str(entity.get("email") or "").strip().casefold() == owner_email
    ]
    if len(reserved) < 2:
        raise DataLifecycleError(
            "Restored database is missing the reserved Users model and form."
        )
    if len(owners) != 1:
        raise DataLifecycleError(
            "Restored database does not contain exactly one configured site owner."
        )
    return {
        "models_checked": len(reserved),
        "users_checked": len(users),
        "reserved_models": len(reserved),
        "owners": len(owners),
    }


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_plan
# @reason provider traffic response variants are exercised through restore preflight
def _traffic_observation(service, versions):
    split = service.get("split") or service.get("trafficSplit") or {}
    allocations = split.get("allocations") or {}
    allocations = {
        str(version): float(weight)
        for version, weight in allocations.items()
        if float(weight) > 0
    }
    if not allocations and isinstance(versions, list):
        for item in versions:
            if not isinstance(item, dict):
                continue
            version = str(item.get("id") or item.get("version") or "")
            weight = item.get("trafficSplit", item.get("traffic_split", 0))
            if version and weight and float(weight) > 0:
                allocations[version] = float(weight)
    if not allocations and isinstance(versions, list) and len(versions) == 1:
        version = str(versions[0].get("id") or versions[0].get("version") or "")
        if version:
            allocations[version] = 1.0
    if not allocations:
        raise DataLifecycleError("Current App Engine traffic allocation is unavailable.")
    split_by = str(split.get("shardBy") or split.get("shard_by") or "RANDOM").casefold()
    if split_by not in {"cookie", "ip", "random"}:
        raise DataLifecycleError("Current App Engine traffic split mode is unsupported.")
    return allocations, split_by


# @testable false
# @covered-by installer/data_lifecycle/restore.py::_legacy_restore_backup
# @reason provider operation extraction is owned by resumable restore orchestration
def _operation_name(payload):
    if not isinstance(payload, dict):
        return None
    return str(payload.get("name") or "").strip() or None


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_plan
# @reason unreachable pre-release named-database preflight retained only for local journal diagnosis
def _legacy_restore_plan(backup_id, context=None):
    """Perform read-only provider checks and return one exact cutover proposal."""
    context = context or ProviderContext.from_settings()
    backup_id = validate_backup_id(backup_id)
    if str(os.environ.get("FLASK_ENV") or "production").casefold() != "production":
        raise DataLifecycleError("Restore preflight requires production mode.")
    backup, _blob = load_backup(context, backup_id)
    active = context.database()
    active_mode = str(active.get("type") or active.get("databaseType") or "").casefold().replace("_", "-")
    if active_mode not in {"datastore", "datastore-mode"}:
        raise DataLifecycleError("Current active database is not in Datastore mode.")
    active_location = active.get("locationId") or active.get("location_id")
    if not _compatible_locations(active_location, backup.database_location):
        raise DataLifecycleError("Backup and active database locations are incompatible.")
    identity_seed = json.dumps(
        {
            "project": context.project_id,
            "backup": backup_id,
            "active_database": context.database_id,
            "application_version": context.application_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity_seed.encode()).hexdigest()[:8]
    date = backup_id[:8].casefold()
    restore_id = f"{date}-{digest}"
    target_database = validate_database_id(
        f"lag-restore-{date}-{digest}", allow_default=False
    )
    candidate = f"restore-{date}-{digest}"
    maintenance = f"maintenance-{date}-{digest}"
    try:
        context.database(target_database)
    except ProviderNotFound:
        pass
    else:
        raise DataLifecycleError(
            f"Proposed target database already exists: {target_database}"
        )
    from config import File, SETTINGS, constants

    region = str(SETTINGS.APP.get("RESOURCE_REGION") or "").strip()
    queue = str(SETTINGS.APP.get("TASK_QUEUE_NAME") or "").strip()
    if not region or not queue:
        raise DataLifecycleError("Current Cloud Tasks queue configuration is incomplete.")
    queue_payload = context.json_command(
        ["tasks", "queues", "describe", queue, f"--location={region}"]
    )
    reconciler = constants.DEFAULT_DEFERRED_JOB_RECONCILER_NAME
    reconciler_payload = context.json_command(
        ["scheduler", "jobs", "describe", reconciler, f"--location={region}"]
    )
    service = context.json_command(["app", "services", "describe", "default"])
    versions = context.json_command(
        ["app", "versions", "list", "--service=default"]
    )
    indexes = context.json_command(
        [
            "firestore",
            "indexes",
            "composite",
            "list",
            f"--database={context.database_id}",
        ]
    )
    version_ids = (
        {
            str(item.get("id") or item.get("version") or "")
            for item in versions
            if isinstance(item, dict)
        }
        if isinstance(versions, list)
        else set()
    )
    collisions = {candidate, maintenance}.intersection(version_ids)
    if collisions:
        raise DataLifecycleError(
            f"Proposed App Engine version already exists: {sorted(collisions)[0]}"
        )
    index_path = Path(__file__).resolve().parents[2] / "index.yaml"
    if not index_path.is_file():
        raise DataLifecycleError("Current index.yaml is missing.")
    redis_ready = all(
        SETTINGS.APP.get(key) not in (None, "")
        for key in ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD")
    )
    if not redis_ready:
        raise DataLifecycleError("Current Redis configuration is incomplete.")
    original_traffic, traffic_split_by = _traffic_observation(service, versions)
    owner_email = str(SETTINGS.APP.get("ADMIN_EMAIL") or "").strip().casefold()
    runtime_service_account = str(
        SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    if not owner_email or not runtime_service_account:
        raise DataLifecycleError(
            "Owner and runtime service-account settings are required for restore."
        )
    return {
        "restore_id": restore_id,
        "backup_id": backup_id,
        "project_id": context.project_id,
        "application_version": context.application_version,
        "old_database": context.database_id,
        "backup_source_database": backup.source_database_id,
        "target_database": target_database,
        "queue": queue,
        "queue_location": region,
        "reconciler": reconciler,
        "candidate_version": candidate,
        "maintenance_version": maintenance,
        "database_location": backup.database_location,
        "export_metadata_uri": backup.export_metadata_uri,
        "index_path": str(index_path.resolve()),
        "kind_prefix": str(SETTINGS.APP.get("PREFIX") or ""),
        "owner_email": owner_email,
        "runtime_service_account": runtime_service_account,
        "configuration_sha256_before": hashlib.sha256(
            File.APP_SETTINGS_YAML.value.read_bytes()
        ).hexdigest(),
        "original_traffic": original_traffic,
        "traffic_split_by": traffic_split_by,
        "consistency": backup.consistency,
        "storage_restored": False,
        "provider_observations": {
            "queue_state": queue_payload.get("state"),
            "reconciler_state": reconciler_payload.get("state"),
            "app_service": service.get("id") or service.get("name"),
            "version_count": len(versions) if isinstance(versions, list) else 0,
            "index_count": len(indexes) if isinstance(indexes, list) else 0,
            "redis_configured": redis_ready,
            "original_traffic": original_traffic,
            "traffic_split_by": traffic_split_by,
        },
        "sequence": [
            "create target Datastore-mode database with deletion protection",
            "import the complete managed export",
            "deploy and wait for target indexes",
            "normalize every native key and serialized submission entity reference",
            "discard restored deferred jobs, locks, control, and active pointers",
            "run idempotent migrations against the target database",
            "validate target data and reserved owner models",
            "deploy zero-traffic candidate and maintenance versions",
            "pause the deferred-job reconciler and configured Cloud Tasks queue",
            "move traffic through maintenance and wait for in-flight work to settle",
            "capture full pending task definitions and purge the configured queue",
            "wait for the purge to take effect and verify the queue is empty",
            "run the migration-gated full application cache rebuild against the target",
            "cut traffic to the validated candidate",
            "persist the active database setting and resume the same empty queue",
            "publish the successful restore record with the purged-task snapshot",
        ],
    }


# @testable false
# @covered-by installer/data_lifecycle/restore.py::_legacy_restore_plan
# @reason console rendering presents the already validated deterministic plan
def _print_plan(plan):
    print(f"Restore plan: {plan['restore_id']}")
    print(f"  Backup: {plan['backup_id']} ({plan['consistency']})")
    print(f"  Database: {plan['old_database']} -> {plan['target_database']}")
    print(f"  Queue: {plan['queue']} (paused, audited, purged, and reused)")
    print(f"  Candidate version: {plan['candidate_version']}")
    print(f"  Maintenance version: {plan['maintenance_version']}")
    print("  Application Cloud Storage: unchanged (recovery audit artifacts retained)")
    print(f"  {CONSISTENCY_NOTICE}")
    print("Proposed cutover sequence:")
    for number, step in enumerate(plan["sequence"], 1):
        print(f"  {number}. {step}")


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason exact typed confirmation is exercised by both mutating public workflows
def _confirm_mutation(expected, *, confirmation=None):
    prompt = f"Type exactly '{expected}' to continue: "
    actual = (confirmation or input)(prompt)
    if str(actual).strip() != expected:
        raise DataLifecycleError("Restore confirmation did not match; nothing changed.")


# @testable false
# @covered-by installer/data_lifecycle/restore.py::_legacy_restore_backup
# @reason ISO checkpoint parsing is exercised by restore resumption
def _checkpoint_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise DataLifecycleError("Restore checkpoint timestamp is invalid.") from error
    if parsed.tzinfo is None:
        raise DataLifecycleError("Restore checkpoint timestamp lacks a timezone.")
    return parsed


# @testable false
# @covered-by installer/data_lifecycle/restore.py::_legacy_rollback_restore
# @reason private checkpoint discovery is exercised through public rollback resumption
def _find_restore_checkpoint(project_id, restore_id, *, state_root=None):
    root = secure_directory(
        Path(state_root) if state_root else LifecycleCheckpoint(
            project_id, ["restore", "placeholder"]
        ).root
    )
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        command = payload.get("command")
        if (
            payload.get("project_id") != project_id
            or payload.get("operation_id") != restore_id
            or not isinstance(command, list)
            or command[:1] != ["restore"]
            or "--rollback" in command
        ):
            continue
        checkpoint = LifecycleCheckpoint(
            project_id,
            command,
            output_target=payload.get("output_target"),
            state_root=root,
        )
        if checkpoint.path != path:
            raise DataLifecycleError("Restore checkpoint path does not match its identity.")
        checkpoint.load()
        return checkpoint
    return None


# @testable false
# @covered-by installer/data_lifecycle/restore.py::_legacy_rollback_restore
# @reason local/remote recovery fallback is exercised by the public rollback workflow
def _load_rollback_plan(context, restore_id, *, restore_checkpoint=None, state_root=None):
    checkpoint = restore_checkpoint or _find_restore_checkpoint(
        context.project_id, restore_id, state_root=state_root
    )
    if checkpoint is not None:
        state = checkpoint.payload or checkpoint.load()
        if (
            state
            and state.get("plan")
            and (
                state.get("status") == "complete"
                or state.get("maintenance_deployed")
            )
        ):
            return state["plan"]
    remote = _remote_restore_by_id(context, restore_id)
    if remote and (
        remote["state"].get("status") == "complete"
        or remote["state"].get("maintenance_deployed")
    ):
        return _localize_remote_plan(remote["plan"])
    object_name = _restore_object_name(restore_id, "record.json")
    record, _blob = context.load_json_object(object_name)
    required = {
        "restore_id",
        "backup_id",
        "project_id",
        "application_version",
        "source_database_id",
        "target_database_id",
        "queue",
        "queue_location",
        "reconciler",
        "candidate_version",
        "maintenance_version",
        "original_traffic",
        "traffic_split_by",
    }
    if (
        not isinstance(record, dict)
        or not required.issubset(record)
        or record.get("status") != "complete"
        or record.get("restore_id") != restore_id
        or record.get("project_id") != context.project_id
    ):
        raise DataLifecycleError("Successful restore record is missing or malformed.")
    return {
        "restore_id": restore_id,
        "backup_id": record["backup_id"],
        "project_id": context.project_id,
        "application_version": record["application_version"],
        "old_database": record["source_database_id"],
        "target_database": record["target_database_id"],
        "queue": record["queue"],
        "queue_location": record["queue_location"],
        "reconciler": record["reconciler"],
        "candidate_version": record["candidate_version"],
        "maintenance_version": record["maintenance_version"],
        "original_traffic": record["original_traffic"],
        "traffic_split_by": record["traffic_split_by"],
        "provider_observations": {
            "queue_state": record.get("queue_state_before"),
            "reconciler_state": record.get("reconciler_state_before"),
        },
    }


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason unreachable pre-release named-database workflow retained only for local journal diagnosis
def _legacy_restore_backup(
    backup_id,
    *,
    dry_run=False,
    context=None,
    checkpoint=None,
    confirmation=None,
):
    """Create, validate, and cut over to an isolated named database."""
    context = context or ProviderContext.from_settings()
    backup_id = validate_backup_id(backup_id)
    if dry_run:
        plan = _legacy_restore_plan(backup_id, context=context)
        _print_plan(plan)
        return plan
    supplied_checkpoint = checkpoint is not None
    local_checkpoint = checkpoint or LifecycleCheckpoint(
        context.project_id, ["restore", backup_id]
    )
    state = local_checkpoint.load()
    remote = None
    if not state and not supplied_checkpoint:
        remote = _remote_restore_for_backup(context, backup_id)
        if remote:
            state = remote["state"]
            plan = _localize_remote_plan(remote["plan"])
        else:
            plan = None
    else:
        plan = None
    if state and state.get("status") == "complete":
        if remote:
            state = _hydrate_local_checkpoint(local_checkpoint, remote)
        plan = state.get("plan") or plan
        outcome = "was rolled back" if state.get("rolled_back") else "is already complete"
        print(f"Restore {plan['restore_id']} {outcome}.")
        return plan
    if state:
        plan = state.get("plan") or plan
        if not isinstance(plan, dict) or plan.get("backup_id") != backup_id:
            raise DataLifecycleError("Restore checkpoint plan is missing or foreign.")
    else:
        plan = _legacy_restore_plan(backup_id, context=context)
    if plan.get("application_version") != context.application_version:
        raise DataLifecycleError(
            "Restore checkpoint belongs to another application version; resume "
            "from the original checkout."
        )
    _print_plan(plan)
    expected = (
        f"RESTORE {context.project_id} {backup_id} TO {plan['target_database']}"
    )
    _confirm_mutation(expected, confirmation=confirmation)
    if remote:
        _hydrate_local_checkpoint(local_checkpoint, remote)
    checkpoint = MirroredRestoreCheckpoint(local_checkpoint, context)
    if not state:
        checkpoint.start(plan["restore_id"], backup_id=backup_id, plan=plan)
    else:
        checkpoint._sync()

    target = plan["target_database"]
    if not checkpoint.payload.get("target_created"):
        operation = checkpoint.payload.get("target_create_operation")
        if not operation:
            record_step("create protected restore target database")
            operation = _operation_name(
                context.create_database(
                    target, plan["database_location"], delete_protection=True
                )
            )
            if not operation:
                raise DataLifecycleError(
                    "Provider did not return a target database creation operation."
                )
            checkpoint.update(
                "target-create-started", target_create_operation=operation
            )
        context.wait_for_operation(operation, database_id=target)
        checkpoint.update("target-created", target_created=True)
        record_mutation(
            "create protected restore target database",
            action="create",
            resource="datastore-database",
            identifier=target,
        )

    if not checkpoint.payload.get("import_complete"):
        operation = checkpoint.payload.get("import_operation")
        if not operation:
            record_step("import managed backup into restore target")
            operation, _payload = context.start_import(
                plan["export_metadata_uri"], target
            )
            checkpoint.update("import-started", import_operation=operation)
        context.wait_for_operation(operation, database_id=target)
        checkpoint.update("import-complete", import_complete=True)

    if not checkpoint.payload.get("indexes_ready"):
        record_step("deploy target database indexes")
        context.deploy_indexes(target, plan["index_path"])
        checkpoint.update("indexes-ready", indexes_ready=True)

    if not checkpoint.payload.get("normalized"):
        record_step("normalize restored keys and discard deferred execution state")
        normalization = normalize_restored_database(
            context.datastore_client(target),
            project_id=context.project_id,
            source_database_id=plan.get(
                "backup_source_database", plan["old_database"]
            ),
            target_database_id=target,
            kind_prefix=plan["kind_prefix"],
        )
        checkpoint.update(
            "normalized", normalized=True, normalization=normalization
        )

    if not checkpoint.payload.get("migrated"):
        record_step("run target database migrations")
        migration = context.run_runtime_action("migrate", target)
        checkpoint.update("migrated", migrated=True, migration=migration)

    if not checkpoint.payload.get("target_validated"):
        record_step("validate restored owner and reserved models")
        validation = validate_restored_database(
            context.datastore_client(target),
            kind_prefix=plan["kind_prefix"],
            owner_email=plan["owner_email"],
        )
        checkpoint.update(
            "target-validated", target_validated=True, validation=validation
        )

    if not checkpoint.payload.get("candidate_deployed"):
        record_step("deploy zero-traffic restore candidate")
        if not context.version_exists(plan["candidate_version"]):
            context.deploy_application_version(plan["candidate_version"], target)
        if not context.version_exists(plan["candidate_version"]):
            raise DataLifecycleError("Restore candidate is not serving.")
        checkpoint.update("candidate-deployed", candidate_deployed=True)

    if not checkpoint.payload.get("maintenance_deployed"):
        record_step("deploy zero-traffic restore maintenance version")
        if not context.version_exists(plan["maintenance_version"]):
            context.deploy_maintenance_version(
                plan["maintenance_version"], plan["runtime_service_account"]
            )
        if not context.version_exists(plan["maintenance_version"]):
            raise DataLifecycleError("Restore maintenance version is not serving.")
        checkpoint.update("maintenance-deployed", maintenance_deployed=True)

    if not checkpoint.payload.get("scheduler_paused"):
        record_step("pause deferred-job reconciler")
        context.pause_scheduler(plan["reconciler"], plan["queue_location"])
        checkpoint.update("scheduler-paused", scheduler_paused=True)

    if not checkpoint.payload.get("queue_paused"):
        record_step("pause configured task queue")
        context.pause_queue(plan["queue"], plan["queue_location"])
        checkpoint.update("queue-paused", queue_paused=True)

    if not checkpoint.payload.get("maintenance_active"):
        record_step("move application traffic to restore maintenance")
        context.set_traffic(
            {plan["maintenance_version"]: 1.0},
            split_by=plan["traffic_split_by"],
        )
        context.wait_for_no_inflight_tasks(
            plan["queue"], plan["queue_location"]
        )
        checkpoint.update("maintenance-active", maintenance_active=True)

    if not checkpoint.payload.get("queue_snapshot"):
        record_step("capture pending task definitions before purge")
        queue_snapshot = capture_queue_snapshot(context, plan)
        checkpoint.update("queue-snapshotted", queue_snapshot=queue_snapshot)

    if not checkpoint.payload.get("queue_purged"):
        raw_time = checkpoint.payload.get("purge_requested_at")
        purge_requested_at = (
            _checkpoint_time(raw_time)
            if raw_time
            else datetime.now(timezone.utc)
        )
        if not raw_time:
            checkpoint.update(
                "queue-purge-started",
                purge_requested_at=purge_requested_at.isoformat().replace(
                    "+00:00", "Z"
                ),
            )
        record_step("purge configured task queue")
        context.purge_queue(plan["queue"], plan["queue_location"])
        checkpoint.update("queue-purged", queue_purged=True)
        record_mutation(
            "purge configured task queue",
            action="purge",
            resource="cloud-tasks-queue",
            identifier=plan["queue"],
        )
    context.wait_for_empty_queue(plan["queue"], plan["queue_location"])
    if not checkpoint.payload.get("queue_empty"):
        checkpoint.update("queue-empty", queue_empty=True)

    if not checkpoint.payload.get("cache_rebuilt"):
        record_step("rebuild Redis cache from restored database")
        cache_result = context.run_runtime_action("rebuild-cache", target)
        checkpoint.update(
            "cache-rebuilt", cache_rebuilt=True, cache_result=cache_result
        )

    if not checkpoint.payload.get("candidate_active"):
        record_step("move application traffic to restored candidate")
        context.set_traffic(
            {plan["candidate_version"]: 1.0},
            split_by=plan["traffic_split_by"],
        )
        checkpoint.update("candidate-active", candidate_active=True)

    if not checkpoint.payload.get("setting_persisted"):
        record_step("persist restored database setting")
        configuration_hash = context.persist_database_setting(target)
        checkpoint.update(
            "setting-persisted",
            setting_persisted=True,
            configuration_sha256_after=configuration_hash,
        )

    if not checkpoint.payload.get("queue_resumed"):
        record_step("resume configured task queue")
        context.resume_queue(plan["queue"], plan["queue_location"])
        checkpoint.update("queue-resumed", queue_resumed=True)

    if not checkpoint.payload.get("restore_record"):
        record_step("publish immutable successful restore record")
        restore_record = publish_successful_restore_record(
            context,
            plan,
            checkpoint.payload["queue_snapshot"],
            purge_requested_at=_checkpoint_time(
                checkpoint.payload["purge_requested_at"]
            ),
        )
        checkpoint.update(
            "restore-record-published", restore_record=restore_record
        )
    checkpoint.finish()
    print(
        f"Restore {plan['restore_id']} is complete on database {target}. "
        "The deferred-job reconciler remains paused until new durable work requires it."
    )
    return plan


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason unreachable pre-release rollback workflow retained only for local journal diagnosis
def _legacy_rollback_restore(
    restore_id,
    *,
    context=None,
    checkpoint=None,
    restore_checkpoint=None,
    confirmation=None,
    state_root=None,
):
    """Return traffic, local configuration, Redis, and execution state to source."""
    restore_id = str(restore_id or "").strip()
    if not restore_id or not all(
        character.isalnum() or character == "-" for character in restore_id
    ):
        raise DataLifecycleError("Restore ID is invalid.")
    context = context or ProviderContext.from_settings()
    original_checkpoint = restore_checkpoint or _find_restore_checkpoint(
        context.project_id, restore_id, state_root=state_root
    )
    plan = _load_rollback_plan(
        context,
        restore_id,
        restore_checkpoint=original_checkpoint,
        state_root=state_root,
    )
    if original_checkpoint is None:
        remote_restore = _remote_restore_by_id(context, restore_id)
        if remote_restore:
            original_checkpoint = LifecycleCheckpoint(
                context.project_id,
                ["restore", plan["backup_id"]],
                state_root=state_root,
            )
            _hydrate_local_checkpoint(original_checkpoint, remote_restore)
    local_rollback_checkpoint = checkpoint or LifecycleCheckpoint(
        context.project_id,
        ["restore", "--rollback", restore_id],
        state_root=state_root,
    )
    state = local_rollback_checkpoint.load()
    if state and state.get("status") == "complete":
        print(f"Rollback for restore {restore_id} is already complete.")
        return plan
    if plan.get("application_version") != context.application_version:
        raise DataLifecycleError(
            "Rollback journal belongs to another application version; use the "
            "checkout that performed the restore."
        )
    for database_id in (plan["old_database"], plan["target_database"]):
        database = context.database(database_id)
        mode = str(
            database.get("type") or database.get("databaseType") or ""
        ).casefold().replace("_", "-")
        if mode not in {"datastore", "datastore-mode"}:
            raise DataLifecycleError(
                f"Rollback database is not in Datastore mode: {database_id}."
            )
    required_versions = {
        plan["maintenance_version"], *plan["original_traffic"].keys()
    }
    missing_versions = sorted(
        version for version in required_versions if not context.version_exists(version)
    )
    if missing_versions:
        raise DataLifecycleError(
            f"Rollback App Engine version is unavailable: {missing_versions[0]}."
        )
    expected = (
        f"ROLLBACK {context.project_id} {restore_id} TO {plan['old_database']}"
    )
    _confirm_mutation(expected, confirmation=confirmation)
    checkpoint = MirroredRestoreCheckpoint(
        local_rollback_checkpoint,
        context,
        filename="rollback-journal.json",
    )
    if not state:
        checkpoint.start(restore_id, restore_id=restore_id, plan=plan)
    else:
        checkpoint._sync()

    if not checkpoint.payload.get("scheduler_paused"):
        context.pause_scheduler(plan["reconciler"], plan["queue_location"])
        checkpoint.update("scheduler-paused", scheduler_paused=True)
    if not checkpoint.payload.get("queue_paused"):
        context.pause_queue(plan["queue"], plan["queue_location"])
        checkpoint.update("queue-paused", queue_paused=True)
    if not checkpoint.payload.get("maintenance_active"):
        context.set_traffic(
            {plan["maintenance_version"]: 1.0},
            split_by=plan["traffic_split_by"],
        )
        context.wait_for_no_inflight_tasks(
            plan["queue"], plan["queue_location"]
        )
        checkpoint.update("maintenance-active", maintenance_active=True)
    if not checkpoint.payload.get("queue_snapshot"):
        queue_snapshot = capture_queue_snapshot(
            context,
            plan,
            filename="rollback-purged-tasks.json",
            observation="full-view target tasks visible before rollback purge",
        )
        checkpoint.update("queue-snapshotted", queue_snapshot=queue_snapshot)
    if not checkpoint.payload.get("queue_purged"):
        context.purge_queue(plan["queue"], plan["queue_location"])
        checkpoint.update("queue-purged", queue_purged=True)
    context.wait_for_empty_queue(plan["queue"], plan["queue_location"])
    if not checkpoint.payload.get("source_setting_persisted"):
        configuration_hash = context.persist_database_setting(plan["old_database"])
        checkpoint.update(
            "source-setting-persisted",
            source_setting_persisted=True,
            source_configuration_sha256_after=configuration_hash,
        )
    if not checkpoint.payload.get("source_cache_rebuilt"):
        cache_result = context.run_runtime_action(
            "rebuild-cache", plan["old_database"]
        )
        checkpoint.update(
            "source-cache-rebuilt",
            source_cache_rebuilt=True,
            cache_result=cache_result,
        )
    if not checkpoint.payload.get("source_traffic_active"):
        context.set_traffic(
            plan["original_traffic"], split_by=plan["traffic_split_by"]
        )
        checkpoint.update(
            "source-traffic-active", source_traffic_active=True
        )
    if not checkpoint.payload.get("queue_state_restored"):
        if (
            str(
                plan.get("provider_observations", {}).get("queue_state") or ""
            ).upper()
            == "RUNNING"
        ):
            context.resume_queue(plan["queue"], plan["queue_location"])
        checkpoint.update(
            "queue-state-restored", queue_state_restored=True
        )
    if not checkpoint.payload.get("scheduler_state_restored"):
        if (
            str(
                plan.get("provider_observations", {}).get("reconciler_state")
                or ""
            ).upper()
            == "ENABLED"
        ):
            context.resume_scheduler(plan["reconciler"], plan["queue_location"])
        checkpoint.update(
            "scheduler-state-restored", scheduler_state_restored=True
        )
    if not checkpoint.payload.get("rollback_record"):
        rollback_record = _legacy_publish_rollback_record(
            context, plan, checkpoint.payload["queue_snapshot"]
        )
        checkpoint.update(
            "rollback-record-published", rollback_record=rollback_record
        )
    if original_checkpoint is not None:
        original_mirror = MirroredRestoreCheckpoint(
            original_checkpoint, context, filename="journal.json"
        )
        original_mirror.update(
            "rolled-back",
            status="complete",
            rolled_back=True,
            rollback_record=checkpoint.payload["rollback_record"],
        )
    checkpoint.finish()
    print(
        f"Rollback {restore_id} is complete on database {plan['old_database']}. "
        f"Target database {plan['target_database']} was retained for manual cleanup."
    )
    return plan


# The released lifecycle exposes only the in-place workflow. The legacy named
# workflow above remains readable solely so pre-release local journals can be
# diagnosed; it is not reachable from the CLI.
from .restore_in_place import restore_backup, restore_plan


__all__ = [
    "capture_queue_snapshot",
    "normalize_restored_database",
    "normalize_restored_entity",
    "publish_successful_restore_record",
    "restore_backup",
    "restore_plan",
    "validate_restored_database",
]
