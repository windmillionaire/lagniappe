"""Shared primitives for the supported in-place restore workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from google.cloud.datastore import Entity, Key

from config.datastore import (
    DEFAULT_DATABASE_ID,
    decode_urlsafe_key,
    encode_urlsafe_key,
)

from .provider import (
    RESTORE_ROOT_PREFIX,
    DataLifecycleError,
    validate_backup_id,
    validate_database_id,
)


RESTORE_NORMALIZE_PAGE_SIZE = 250
SERIALIZED_REFERENCE_PROPERTIES = frozenset({"submission", "default_submission"})
DEFERRED_JOB_CONTROL_ID = "deferred-jobs-control"
QUEUE_SNAPSHOT_FORMAT = "lagniappe-purged-cloud-tasks"
RESTORE_ARTIFACT_SCHEMA = 1
RESTORE_JOURNAL_FORMAT = "lagniappe-restore-journal"
RESTORE_JOURNAL_STATE_KEYS = frozenset(
    {
        "operation_id",
        "status",
        "checkpoint",
        "journal_revision",
        "maintenance_deployed",
        "scheduler_paused",
        "queue_paused",
        "maintenance_active",
        "request_drain_complete",
        "queue_snapshot",
        "purge_requested_at",
        "queue_purged",
        "safety_snapshot_time",
        "safety_clone_operation",
        "safety_clone_created",
        "safety_assets",
        "import_operation",
        "import_complete",
        "assets_restored",
        "asset_result",
        "normalized",
        "migrated",
        "target_validated",
        "scheduled_tasks_reconciled",
        "scheduled_task_result",
        "cache_invalidated",
        "traffic_restored",
        "queue_resumed",
        "scheduler_resumed",
        "safety_clone_cleaned",
        "restore_record",
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
        "queue_snapshot",
        "purge_requested_at",
        "safety_snapshot_time",
        "safety_clone_operation",
        "safety_assets",
        "import_operation",
        "asset_result",
        "scheduled_task_result",
        "restore_record",
    }
)


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason resume-plan compatibility is enforced before any restore mutation
def _validate_in_place_restore_plan(plan):
    if not isinstance(plan, dict):
        raise DataLifecycleError("In-place restore checkpoint plan is invalid.")
    try:
        old_database = validate_database_id(plan["old_database"])
        target_database = validate_database_id(plan["target_database"])
    except (KeyError, TypeError, DataLifecycleError) as error:
        raise DataLifecycleError(
            "In-place restore checkpoint plan is invalid."
        ) from error
    if (
        old_database != DEFAULT_DATABASE_ID
        or target_database != DEFAULT_DATABASE_ID
    ):
        raise DataLifecycleError(
            "Legacy named-database restore checkpoints cannot be resumed; "
            "inspect and archive the obsolete journal before starting a current "
            "in-place restore."
        )
    required = {
        "restore_id",
        "backup_id",
        "project_id",
        "application_version",
        "safety_database",
        "consistency",
        "queue",
        "queue_location",
        "reconciler",
        "maintenance_version",
        "runtime_service_account",
        "original_traffic",
        "traffic_split_by",
        "export_output_prefix",
        "assets_uri",
        "kind_prefix",
        "owner_email",
        "app_url",
        "merge",
        "provider_observations",
        "sequence",
    }
    if not required.issubset(plan):
        raise DataLifecycleError("In-place restore checkpoint plan is invalid.")
    try:
        validate_backup_id(plan["backup_id"])
        validate_database_id(plan["safety_database"], allow_default=False)
    except (TypeError, DataLifecycleError) as error:
        raise DataLifecycleError(
            "In-place restore checkpoint plan is invalid."
        ) from error
    return plan


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason journal projection is exercised through the resumable in-place state machine
def _remote_journal_payload(context, checkpoint, filename):
    state = checkpoint.payload
    if not isinstance(state, dict) or not isinstance(state.get("plan"), dict):
        raise DataLifecycleError("Restore checkpoint cannot be mirrored yet.")
    plan = dict(_validate_in_place_restore_plan(state["plan"]))
    if "index_path" in plan:
        plan["index_path"] = "index.yaml"
    return {
        "format": RESTORE_JOURNAL_FORMAT,
        "schema_version": RESTORE_ARTIFACT_SCHEMA,
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
    if (
        not isinstance(payload, dict)
        or payload.get("format") != RESTORE_JOURNAL_FORMAT
        or payload.get("schema_version") != RESTORE_ARTIFACT_SCHEMA
        or payload.get("project_id") != context.project_id
        or not isinstance(plan, dict)
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
    _validate_in_place_restore_plan(plan)
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
        if filename != "journal.json":
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
# @covered-by installer/data_lifecycle/restore_support.py::capture_queue_snapshot
# @reason restore artifact paths are exercised through queue-snapshot publication
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
# @covered-by installer/data_lifecycle/restore_support.py::capture_queue_snapshot
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
# @covered-by installer/data_lifecycle/restore_support.py::capture_queue_snapshot
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
        or payload.get("schema_version") != RESTORE_ARTIFACT_SCHEMA
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
# @matrix data-lifecycle : immutable-restore-record queue-purge-audit
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
    if filename != "purged-tasks.json":
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
        "schema_version": RESTORE_ARTIFACT_SCHEMA,
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


# @testable false
# @covered-by installer/data_lifecycle/restore_support.py::normalize_restored_entity
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
# @covered-by installer/data_lifecycle/restore_support.py::normalize_restored_entity
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
# @covered-by installer/data_lifecycle/restore_support.py::normalize_restored_entity
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
# @matrix data-lifecycle : deferred-state-retirement restore-key-normalization serialized-entity-details
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
# @covered-by installer/data_lifecycle/restore_support.py::normalize_restored_database
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


# @testable false
# @covered-by installer/data_lifecycle/restore_support.py::normalize_restored_database
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_generation_bound_assets
# @reason provider reads may spell the default database differently from its write client
def _bind_key_to_client_database(client, key):
    """Return the same logical key using the client's database spelling."""
    client_project = getattr(client, "project", key.project)
    client_database_value = getattr(client, "database", key.database)
    if str(key.project or "") != str(client_project or ""):
        raise DataLifecycleError("Datastore write key belongs to another project.")
    key_database = str(key.database or "")
    client_database = str(client_database_value or "")
    if key_database == client_database:
        return key
    if {key_database, client_database}.issubset({"", DEFAULT_DATABASE_ID}):
        return Key(
            *key.flat_path,
            project=client_project,
            namespace=key.namespace,
            database=client_database_value,
        )
    raise DataLifecycleError("Datastore write key belongs to another database.")


# @testable false
# @covered-by installer/data_lifecycle/restore_support.py::normalize_restored_database
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_generation_bound_assets
# @reason entity identity rebinding is exercised through the complete restore write paths
def _bind_entities_to_client_database(client, entities):
    entities = list(entities)
    for entity in entities:
        entity.key = _bind_key_to_client_database(client, entity.key)
    return entities


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_normalizes_persisted_keys_before_cache_rebuild
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_discards_deferred_execution_state
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_default_database_writes_use_client_partition
# @matrix data-lifecycle : bounded-restore-scan default-database-write-partition deferred-state-retirement restore-key-normalization
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
                        client.delete_multi(
                            [
                                _bind_key_to_client_database(client, key)
                                for key in keys
                            ]
                        )
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
                    client.delete_multi(
                        [
                            _bind_key_to_client_database(client, key)
                            for key in deletes
                        ]
                    )
                    counts["deferred_records_deleted"] += len(deletes)
                if writes:
                    client.put_multi(
                        _bind_entities_to_client_database(client, writes)
                    )
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
# @matrix data-lifecycle : owner-invariant restore-validation
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
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason exact typed confirmation is exercised by the public in-place workflow
def _confirm_mutation(expected, *, confirmation=None):
    from installer import FORMATTER

    formatter = FORMATTER.initialize()
    prompt = formatter.warning(f"Type {expected} to continue: ")
    actual = (confirmation or input)(prompt)
    if str(actual).strip() != expected:
        raise DataLifecycleError("Restore confirmation did not match; nothing changed.")


__all__ = [
    "MirroredRestoreCheckpoint",
    "capture_queue_snapshot",
    "normalize_restored_database",
    "normalize_restored_entity",
    "validate_restored_database",
]
