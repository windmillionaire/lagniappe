"""Maintenance-gated, in-place recovery-set merge orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os

from config.datastore import decode_urlsafe_key, encode_urlsafe_key
from installer.errors import ProviderNotFound
from installer.state import record_mutation, record_step

from .backup import CONSISTENCY_NOTICE, load_backup
from .provider import (
    DataLifecycleError,
    ProviderContext,
    RESTORE_ROOT_PREFIX,
    parse_gs_uri,
    validate_backup_id,
    validate_database_id,
)
from .recovery_set import _blob_sha256, inventory_database
from .restore_support import (
    MirroredRestoreCheckpoint,
    _compatible_locations,
    _confirm_mutation,
    _hydrate_local_checkpoint,
    _remote_restore_for_backup,
    _restore_query_pages,
    _traffic_observation,
    _validate_in_place_restore_plan,
    capture_queue_snapshot,
    normalize_restored_database,
    validate_restored_database,
)
from .state import LifecycleCheckpoint


DEFAULT_DATABASE = "(default)"


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason recovery catalog trust checks are exercised by public restore orchestration
def _load_catalog(context, uri):
    bucket, name = parse_gs_uri(uri)
    if bucket != context.recovery_bucket:
        raise DataLifecycleError("Recovery catalog belongs to another bucket.")
    payload, _blob = context.load_json_object(name)
    return payload


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_plan
# @reason key classification is part of read-only restore preflight
def _merge_counts(context, manifest):
    """Count keys the import will overwrite or resurrect without writing."""
    inventory = _load_catalog(context, manifest.inventory_uri)
    keys = [decode_urlsafe_key(item["key"]) for item in inventory["entities"]]
    client = context.datastore_client(DEFAULT_DATABASE)
    existing = 0
    for offset in range(0, len(keys), 250):
        existing += len(list(client.get_multi(keys[offset : offset + 250])))
    return {
        "snapshot_entities": len(keys),
        "overwritten": existing,
        "restored_missing": len(keys) - existing,
        "live_only": "preserved",
    }


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_dry_run_is_deterministic_and_read_only
# @matrix data-lifecycle : dry-run in-place-merge restore-preflight
def restore_plan(backup_id, context=None):
    """Perform a read-only preflight for an in-place default-database merge."""
    context = context or ProviderContext.from_settings()
    backup_id = validate_backup_id(backup_id)
    if str(os.environ.get("FLASK_ENV") or "production").casefold() != "production":
        raise DataLifecycleError("Restore preflight requires production mode.")
    if validate_database_id(context.database_id) != DEFAULT_DATABASE:
        raise DataLifecycleError("In-place restore requires the canonical (default) database.")

    backup, _blob = load_backup(context, backup_id)
    active = context.database(DEFAULT_DATABASE)
    mode = str(active.get("type") or active.get("databaseType") or "").casefold().replace("_", "-")
    if mode not in {"datastore", "datastore-mode"}:
        raise DataLifecycleError("The default database is not in Datastore mode.")
    active_location = active.get("locationId") or active.get("location_id")
    if not _compatible_locations(active_location, backup.database_location):
        raise DataLifecycleError("Backup and default database locations are incompatible.")

    identity = hashlib.sha256(
        json.dumps(
            {
                "project": context.project_id,
                "backup": backup_id,
                "application_version": context.application_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:8]
    date = backup_id[:8].casefold()
    restore_id = f"{date}-{identity}"
    safety_database = validate_database_id(
        f"lag-safety-{date}-{identity}", allow_default=False
    )
    maintenance = f"maintenance-{date}-{identity}"
    try:
        context.database(safety_database)
    except ProviderNotFound:
        pass
    else:
        raise DataLifecycleError(
            f"Proposed safety database already exists: {safety_database}"
        )

    from config import SETTINGS, constants

    region = str(SETTINGS.APP.get("RESOURCE_REGION") or "").strip()
    queue = str(SETTINGS.APP.get("TASK_QUEUE_NAME") or "").strip()
    app_url = str(SETTINGS.APP.get("APP_URL") or "").strip()
    service_account = str(
        SETTINGS.APP.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    runtime_service_account = str(
        SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    owner_email = str(SETTINGS.APP.get("ADMIN_EMAIL") or "").strip().casefold()
    if not all((region, queue, app_url, service_account, runtime_service_account, owner_email)):
        raise DataLifecycleError("Restore runtime, owner, queue, or application URL settings are incomplete.")
    if service_account != runtime_service_account:
        raise DataLifecycleError("The internal caller must be the attached runtime service account.")

    queue_payload = context.json_command(
        ["tasks", "queues", "describe", queue, f"--location={region}"]
    )
    reconciler = constants.DEFAULT_DEFERRED_JOB_RECONCILER_NAME
    reconciler_payload = context.json_command(
        ["scheduler", "jobs", "describe", reconciler, f"--location={region}"]
    )
    service = context.json_command(["app", "services", "describe", "default"])
    versions = context.json_command(["app", "versions", "list", "--service=default"])
    version_ids = {
        str(item.get("id") or item.get("version") or "")
        for item in versions
        if isinstance(item, dict)
    } if isinstance(versions, list) else set()
    if maintenance in version_ids:
        raise DataLifecycleError(f"Proposed maintenance version already exists: {maintenance}")
    original_traffic, split_by = _traffic_observation(service, versions)
    redis_ready = all(
        SETTINGS.APP.get(key) not in (None, "")
        for key in ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD")
    )
    if not redis_ready:
        raise DataLifecycleError("Current Redis configuration is incomplete.")

    return {
        "restore_id": restore_id,
        "backup_id": backup_id,
        "project_id": context.project_id,
        "application_version": context.application_version,
        "old_database": DEFAULT_DATABASE,
        "target_database": DEFAULT_DATABASE,
        "safety_database": safety_database,
        "backup_source_database": backup.source_database_id,
        "database_location": backup.database_location,
        "export_metadata_uri": backup.export_metadata_uri,
        "assets_uri": backup.assets_uri,
        "queue": queue,
        "queue_location": region,
        "reconciler": reconciler,
        "maintenance_version": maintenance,
        "kind_prefix": str(SETTINGS.APP.get("PREFIX") or ""),
        "owner_email": owner_email,
        "runtime_service_account": runtime_service_account,
        "app_url": app_url,
        "original_traffic": original_traffic,
        "traffic_split_by": split_by,
        "consistency": backup.consistency,
        "snapshot_time": backup.snapshot_time,
        "merge": _merge_counts(context, backup),
        "provider_observations": {
            "queue_state": queue_payload.get("state"),
            "reconciler_state": reconciler_payload.get("state"),
        },
        "sequence": [
            "deploy maintenance, pause producers, and wait for in-flight requests",
            "audit and purge the configured Cloud Tasks queue",
            "clone the quiescent default database and catalog its asset generations",
            "import snapshot keys into (default), overwriting matches and restoring missing keys",
            "restore exact asset bytes and bind entities to the new object generations",
            "discard nonterminal execution state, migrate, invalidate caches, and validate",
            "regenerate durable scheduled-task uncompletion wake-ups from merged data",
            "restore traffic and prior queue/scheduler state",
            "delete the temporary safety clone and publish the completion audit record",
        ],
    }


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason console rendering presents an already validated restore plan
def _print_plan(plan):
    merge = plan["merge"]
    print(f"Restore plan: {plan['restore_id']}")
    print(f"  Recovery set: {plan['backup_id']} ({plan['consistency']})")
    print("  Database: merge directly into (default)")
    print(
        "  Snapshot keys: "
        f"{merge['snapshot_entities']} ({merge['overwritten']} overwritten, "
        f"{merge['restored_missing']} restored); live-only keys are preserved"
    )
    print(f"  Safety clone: {plan['safety_database']} (removed after validation)")
    print(f"  Queue: {plan['queue']} (paused, audited, purged, then reconciled)")
    print(f"  {CONSISTENCY_NOTICE}")
    print("Proposed recovery sequence:")
    for number, step in enumerate(plan["sequence"], 1):
        print(f"  {number}. {step}")


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason whole-minute safety selection is exercised by restore orchestration
def _safety_snapshot_time(context):
    now = context.now().astimezone(timezone.utc)
    target = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    context.sleep(max(0.0, (target - now).total_seconds()) + 1.0)
    return target


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason safety generation inventory is an in-place restore checkpoint
def _publish_safety_assets(context, plan, snapshot_time):
    _inventory, assets = inventory_database(
        context.datastore_client(DEFAULT_DATABASE), snapshot_time=snapshot_time
    )
    object_name = f"{RESTORE_ROOT_PREFIX}/{plan['restore_id']}/safety-assets.json"
    payload = {
        "format": "lagniappe-safety-assets",
        "schema_version": 1,
        "restore_id": plan["restore_id"],
        "snapshot_time": snapshot_time.isoformat().replace("+00:00", "Z"),
        "asset_count": len(assets),
        "assets": assets,
        "note": "The recorded generations remain recoverable under runtime bucket version retention.",
    }
    blob = context.bucket.blob(object_name)
    if not blob.exists():
        context.upload_json_create_only(object_name, payload)
    return {
        "object_name": object_name,
        "uri": f"gs://{context.recovery_bucket}/{object_name}",
        "asset_count": len(assets),
    }


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_assets_rebinds_owner_to_new_generation
# @matrix data-lifecycle disaster-recovery : asset-generation restore-assets
def restore_generation_bound_assets(context, plan):
    """Restore recovery copies and rewrite descriptors to their new generations."""
    from config import SETTINGS
    from config.storage import storage_bucket_names

    payload = _load_catalog(context, plan["assets_uri"])
    runtime = {
        role: context.storage.bucket(name)
        for role, name in storage_bucket_names(SETTINGS.APP).items()
    }
    generation_by_identity = {}
    for asset in payload.get("assets") or []:
        recovery_name = str(asset.get("recovery_object") or "")
        try:
            source = context.bucket.blob(
                recovery_name, generation=int(asset["recovery_generation"])
            )
        except TypeError:
            source = context.bucket.blob(recovery_name)
        source.reload()
        size = int(asset.get("size") or 0)
        observed = _blob_sha256(source, size) if size else hashlib.sha256(b"").hexdigest()
        if observed != asset.get("sha256"):
            raise DataLifecycleError(f"Recovery asset checksum failed: {recovery_name}")
        target_bucket = runtime.get(asset.get("role"))
        if target_bucket is None:
            raise DataLifecycleError(f"Recovery asset role is invalid: {asset.get('role')!r}")
        copied = context.bucket.copy_blob(source, target_bucket, asset["path"])
        copied = copied or target_bucket.blob(asset["path"])
        copied.reload()
        new_generation = str(copied.generation or "")
        if not new_generation:
            raise DataLifecycleError("Restored asset has no generation metadata.")
        for owner in asset.get("owners") or []:
            generation_by_identity[(owner["key"], owner["name"])] = new_generation

    client = context.datastore_client(DEFAULT_DATABASE)
    owners = {}
    for owner_key, _name in generation_by_identity:
        owners.setdefault(owner_key, client.get(decode_urlsafe_key(owner_key)))
    if any(entity is None for entity in owners.values()):
        raise DataLifecycleError("A required recovery asset owner is missing after import.")
    for (owner_key, name), generation in generation_by_identity.items():
        entity = owners[owner_key]
        if str(entity.key.kind).endswith("site") and entity.key.id_or_name == "image":
            generations = dict(entity.get("asset_generations") or {})
            generations[name] = generation
            entity["asset_generations"] = generations
            continue
        raw = entity.get("assets") or {}
        encoded = isinstance(raw, str)
        definitions = json.loads(raw) if encoded else dict(raw)
        if name not in definitions or not isinstance(definitions[name], dict):
            raise DataLifecycleError(f"Restored asset descriptor is missing: {owner_key}:{name}")
        definitions[name]["generation"] = generation
        entity["assets"] = (
            json.dumps(definitions, sort_keys=True, separators=(",", ":"))
            if encoded
            else definitions
        )
    if owners:
        client.put_multi(list(owners.values()))
    return {"assets": len(payload.get("assets") or []), "owners": len(owners)}


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_restore_requeues_only_durable_scheduled_uncompletion
# @matrix data-lifecycle disaster-recovery : queue-reconciliation scheduled-uncomplete
def reconcile_scheduled_uncomplete_tasks(context, plan, *, now=None):
    """Backfill durable markers and recreate only scheduled uncompletion wake-ups."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise DataLifecycleError("Scheduled-task reconciliation requires UTC time.")
    client = context.datastore_client(DEFAULT_DATABASE)
    kind = f"{plan['kind_prefix']}instances"
    queued = 0
    backfilled = 0
    changed = []
    query = client.query(kind=kind)
    for page in _restore_query_pages(query, page_size=250):
        for entity in page:
            if entity.get("type") != "task":
                continue
            eligible = (
                entity.get("completed") is True
                and entity.get("active", True) is not False
                and bool(entity.get("schedule"))
            )
            token = str(entity.get("scheduled_uncomplete_token") or "")
            schedule_at = entity.get("scheduled_uncomplete_at")
            if not eligible:
                if token or schedule_at:
                    entity.pop("scheduled_uncomplete_token", None)
                    entity.pop("scheduled_uncomplete_at", None)
                    changed.append(entity)
                continue
            if not token:
                key = encode_urlsafe_key(entity.key)
                seed = f"{key}\0{entity.get('completed_on')}\0{entity.get('due')}"
                token = hashlib.sha256(seed.encode("utf-8")).hexdigest()
                schedule_at = now
                entity["scheduled_uncomplete_token"] = token
                entity["scheduled_uncomplete_at"] = schedule_at
                excluded = set(getattr(entity, "exclude_from_indexes", ()) or ())
                excluded.add("scheduled_uncomplete_token")
                entity.exclude_from_indexes = tuple(sorted(excluded))
                changed.append(entity)
                backfilled += 1
            if not isinstance(schedule_at, datetime):
                schedule_at = now
                entity["scheduled_uncomplete_at"] = schedule_at
                changed.append(entity)
            context.create_scheduled_uncomplete_task(
                plan["queue"],
                plan["queue_location"],
                entity_key=encode_urlsafe_key(entity.key),
                token=token,
                schedule_at=max(schedule_at, now),
                app_url=plan["app_url"],
                service_account=plan["runtime_service_account"],
            )
            queued += 1
    if changed:
        client.put_multi(changed)
    return {"queued": queued, "backfilled": backfilled}


# @testable false
# @covered-by installer/data_lifecycle/restore_in_place.py::restore_backup
# @reason completion publication occurs only after the public workflow converges
def _completion_record(context, plan, checkpoint):
    object_name = f"{RESTORE_ROOT_PREFIX}/{plan['restore_id']}/record.json"
    payload = {
        "format": "lagniappe-in-place-restore",
        "schema_version": 2,
        "status": "complete",
        "restore_id": plan["restore_id"],
        "backup_id": plan["backup_id"],
        "project_id": context.project_id,
        "database_id": DEFAULT_DATABASE,
        "merge": plan["merge"],
        "safety_database_id": plan["safety_database"],
        "purged_tasks": checkpoint.payload["queue_snapshot"],
        "assets": checkpoint.payload.get("asset_result"),
        "scheduled_uncompletion": checkpoint.payload.get("scheduled_task_result"),
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    blob = context.bucket.blob(object_name)
    if blob.exists():
        existing, _blob = context.load_json_object(object_name)
        if existing.get("restore_id") != plan["restore_id"] or existing.get("backup_id") != plan["backup_id"]:
            raise DataLifecycleError("Existing restore completion record conflicts.")
        return existing
    context.upload_json_create_only(object_name, payload)
    return payload


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_in_place_restore_is_confirmed_resumable_and_has_no_rollback
# @tests tests_tooling/test_008_data_lifecycle.py::test_in_place_restore_rejects_legacy_named_database_checkpoint
# @matrix data-lifecycle : confirmation in-place-merge legacy-journal-rejection queue-purge-audit remote-journal restore resume
def restore_backup(
    backup_id,
    *,
    dry_run=False,
    context=None,
    checkpoint=None,
    confirmation=None,
):
    """Merge one exact recovery set into `(default)` under maintenance."""
    context = context or ProviderContext.from_settings()
    backup_id = validate_backup_id(backup_id)
    if dry_run:
        plan = restore_plan(backup_id, context=context)
        _print_plan(plan)
        return plan

    local = checkpoint or LifecycleCheckpoint(context.project_id, ["restore", backup_id])
    state = local.load()
    remote = None
    if not state and checkpoint is None:
        remote = _remote_restore_for_backup(context, backup_id)
        if remote:
            state = _hydrate_local_checkpoint(local, remote)
            plan = state["plan"]
        else:
            plan = None
    else:
        plan = None
    if state and state.get("status") == "complete":
        completed_plan = _validate_in_place_restore_plan(state.get("plan"))
        print(f"Restore {completed_plan['restore_id']} is already complete.")
        return completed_plan
    plan = _validate_in_place_restore_plan(
        (state or {}).get("plan")
        or plan
        or restore_plan(backup_id, context=context)
    )
    if plan.get("application_version") != context.application_version:
        raise DataLifecycleError("Restore checkpoint belongs to another application version.")
    _print_plan(plan)
    expected = f"RESTORE {context.project_id} {backup_id} INTO (default)"
    _confirm_mutation(expected, confirmation=confirmation)
    checkpoint = MirroredRestoreCheckpoint(local, context)
    if not state:
        checkpoint.start(plan["restore_id"], backup_id=backup_id, plan=plan)
    else:
        checkpoint._sync()

    if not checkpoint.payload.get("maintenance_deployed"):
        record_step("deploy zero-traffic restore maintenance version")
        if not context.version_exists(plan["maintenance_version"]):
            context.deploy_maintenance_version(
                plan["maintenance_version"], plan["runtime_service_account"]
            )
        checkpoint.update("maintenance-deployed", maintenance_deployed=True)
    if not checkpoint.payload.get("scheduler_paused"):
        context.pause_scheduler(plan["reconciler"], plan["queue_location"])
        checkpoint.update("scheduler-paused", scheduler_paused=True)
    if not checkpoint.payload.get("queue_paused"):
        context.pause_queue(plan["queue"], plan["queue_location"])
        checkpoint.update("queue-paused", queue_paused=True)
    if not checkpoint.payload.get("maintenance_active"):
        context.set_traffic(
            {plan["maintenance_version"]: 1.0}, split_by=plan["traffic_split_by"]
        )
        context.wait_for_no_inflight_tasks(plan["queue"], plan["queue_location"])
        checkpoint.update("maintenance-active", maintenance_active=True)
    if not checkpoint.payload.get("request_drain_complete"):
        # App Engine standard requests may continue on their selected version
        # after the traffic switch. Drain one full request deadline before the
        # safety point so no pre-maintenance writer can race the clone/import.
        context.sleep(65.0)
        checkpoint.update("request-drain-complete", request_drain_complete=True)
    if not checkpoint.payload.get("queue_snapshot"):
        checkpoint.update(
            "queue-snapshotted",
            queue_snapshot=capture_queue_snapshot(context, plan),
        )
    if not checkpoint.payload.get("queue_purged"):
        requested = datetime.now(timezone.utc)
        checkpoint.update(
            "queue-purge-started",
            purge_requested_at=requested.isoformat().replace("+00:00", "Z"),
        )
        context.purge_queue(plan["queue"], plan["queue_location"])
        checkpoint.update("queue-purged", queue_purged=True)
        record_mutation(
            "purge configured task queue",
            action="purge",
            resource="cloud-tasks-queue",
            identifier=plan["queue"],
        )
    context.wait_for_empty_queue(plan["queue"], plan["queue_location"])

    if not checkpoint.payload.get("safety_snapshot_time"):
        safety_time = _safety_snapshot_time(context)
        checkpoint.update(
            "safety-time-selected",
            safety_snapshot_time=safety_time.isoformat().replace("+00:00", "Z"),
        )
    safety_time = datetime.fromisoformat(
        checkpoint.payload["safety_snapshot_time"].replace("Z", "+00:00")
    )
    if not checkpoint.payload.get("safety_clone_created"):
        operation = checkpoint.payload.get("safety_clone_operation")
        if not operation:
            operation, _payload = context.start_clone(
                plan["safety_database"], snapshot_time=safety_time
            )
            checkpoint.update("safety-clone-started", safety_clone_operation=operation)
        context.wait_for_operation(operation, database_id=plan["safety_database"])
        checkpoint.update("safety-clone-created", safety_clone_created=True)
    if not checkpoint.payload.get("safety_assets"):
        checkpoint.update(
            "safety-assets-cataloged",
            safety_assets=_publish_safety_assets(context, plan, safety_time),
        )

    if not checkpoint.payload.get("import_complete"):
        operation = checkpoint.payload.get("import_operation")
        if not operation:
            operation, _payload = context.start_import(
                plan["export_metadata_uri"], DEFAULT_DATABASE
            )
            checkpoint.update("import-started", import_operation=operation)
        context.wait_for_operation(operation, database_id=DEFAULT_DATABASE)
        checkpoint.update("import-complete", import_complete=True)
    if not checkpoint.payload.get("assets_restored"):
        result = restore_generation_bound_assets(context, plan)
        checkpoint.update("assets-restored", assets_restored=True, asset_result=result)
    if not checkpoint.payload.get("normalized"):
        result = normalize_restored_database(
            context.datastore_client(DEFAULT_DATABASE),
            project_id=context.project_id,
            source_database_id=DEFAULT_DATABASE,
            target_database_id=DEFAULT_DATABASE,
            kind_prefix=plan["kind_prefix"],
        )
        checkpoint.update("normalized", normalized=True, normalization=result)
    if not checkpoint.payload.get("migrated"):
        result = context.run_runtime_action("migrate", DEFAULT_DATABASE)
        checkpoint.update("migrated", migrated=True, migration=result)
    if not checkpoint.payload.get("target_validated"):
        result = validate_restored_database(
            context.datastore_client(DEFAULT_DATABASE),
            kind_prefix=plan["kind_prefix"],
            owner_email=plan["owner_email"],
        )
        checkpoint.update("target-validated", target_validated=True, validation=result)
    if not checkpoint.payload.get("scheduled_tasks_reconciled"):
        result = reconcile_scheduled_uncomplete_tasks(context, plan)
        checkpoint.update(
            "scheduled-tasks-reconciled",
            scheduled_tasks_reconciled=True,
            scheduled_task_result=result,
        )
    if not checkpoint.payload.get("cache_invalidated"):
        context.invalidate_cache()
        checkpoint.update("cache-invalidated", cache_invalidated=True)
    if not checkpoint.payload.get("traffic_restored"):
        context.set_traffic(plan["original_traffic"], split_by=plan["traffic_split_by"])
        checkpoint.update("traffic-restored", traffic_restored=True)
    if not checkpoint.payload.get("queue_resumed"):
        if str(plan["provider_observations"].get("queue_state") or "").upper() == "RUNNING":
            context.resume_queue(plan["queue"], plan["queue_location"])
        checkpoint.update("queue-state-restored", queue_resumed=True)
    if not checkpoint.payload.get("scheduler_resumed"):
        if str(plan["provider_observations"].get("reconciler_state") or "").upper() == "ENABLED":
            context.resume_scheduler(plan["reconciler"], plan["queue_location"])
        checkpoint.update("scheduler-state-restored", scheduler_resumed=True)
    if not checkpoint.payload.get("safety_clone_cleaned"):
        context.disable_database_delete_protection(plan["safety_database"])
        context.delete_database(plan["safety_database"])
        checkpoint.update("safety-clone-cleaned", safety_clone_cleaned=True)
    if not checkpoint.payload.get("restore_record"):
        record = _completion_record(context, plan, checkpoint)
        checkpoint.update("restore-record-published", restore_record=record)
    checkpoint.finish()
    print(
        f"Restore {plan['restore_id']} merged into (default): "
        f"{plan['merge']['overwritten']} keys reset and "
        f"{plan['merge']['restored_missing']} missing keys restored."
    )
    print(
        "Cache data was cleared. Sign in as the Owner, then open "
        "Admin → Site Settings → Maintenance and select Refresh Cache."
    )
    return plan


__all__ = [
    "reconcile_scheduled_uncomplete_tasks",
    "restore_backup",
    "restore_generation_bound_assets",
    "restore_plan",
]
