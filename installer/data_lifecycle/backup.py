"""Exact v3 database-and-asset recovery-set orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import re
from typing import Any

from installer.state import record_mutation, record_step

from .provider import (
    BACKUP_FORMAT,
    BACKUP_ROOT_PREFIX,
    BACKUP_SCHEMA_VERSION,
    BackupManifest,
    DataLifecycleError,
    ProviderContext,
    backup_root_uri,
    export_output_uri,
    operation_times,
    parse_gs_uri,
    require_uri_below,
    validate_backup_id,
    validate_database_id,
)
from .state import LifecycleCheckpoint
from .recovery_set import capture_assets, catalog_descriptor, inventory_database


CONSISTENCY_NOTICE = (
    "This manual backup binds its database inventory and referenced asset "
    "generations to one exact point-in-time snapshot."
)
RUNTIME_CATALOG_OBJECT = "data-lifecycle/recovery-catalog.json"


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason terminal animation is a presentation wrapper around tested lifecycle phases
@contextmanager
def _progress(formatter, message):
    with formatter.yaspin(text=formatter.success(message)) as spinner:
        try:
            yield spinner
        except BaseException:
            spinner.fail(formatter.fail_glyph)
            raise
        spinner.ok(formatter.ok_glyph)


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason final console rendering presents an already validated manifest
def _print_backup_summary(formatter, manifest):
    snapshot = datetime.fromisoformat(
        manifest.snapshot_time.replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    print(formatter.success(f"Backup {manifest.backup_id} is complete."))
    print(f"  Snapshot: {snapshot:%d %b %Y at %H:%M UTC}")
    print(f"  Database records: {manifest.entity_count}")
    print(f"  Referenced file versions: {manifest.asset_count}")
    print("  This manual backup is self-contained and remains available until deleted.")


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason random ID generation is validated through the public backup operation
def new_backup_id(now=None, token_hex=None):
    now = now or datetime.now(timezone.utc)
    token_hex = token_hex or secrets.token_hex
    value = f"{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{token_hex(4)}"
    return validate_backup_id(value)


# @testable false
# @covered-by installer/data_lifecycle/backup.py::load_backup
# @reason exact object naming is exercised through validated manifest loading
def manifest_object_name(backup_id: str) -> str:
    return f"{BACKUP_ROOT_PREFIX}/{validate_backup_id(backup_id)}/manifest.json"


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_manifest_validation_rejects_foreign_or_uncontained_artifacts
# @matrix data-lifecycle : manifest path-containment
def load_backup(context: ProviderContext, backup_id: str) -> tuple[BackupManifest, Any]:
    backup_id = validate_backup_id(backup_id)
    payload, blob = context.load_json_object(manifest_object_name(backup_id))
    manifest = BackupManifest.from_dict(
        payload,
        expected_project=context.project_id,
        expected_backup_id=backup_id,
        expected_bucket=context.recovery_bucket,
    )
    metadata_bucket, metadata_name = parse_gs_uri(manifest.export_metadata_uri)
    if metadata_bucket != context.recovery_bucket:
        raise DataLifecycleError("Backup export metadata is in another bucket.")
    metadata_blob = context.bucket.blob(metadata_name)
    if not metadata_blob.exists():
        raise DataLifecycleError("Backup export metadata object is missing.")
    for label, uri, expected_sha, expected_count, count_key in (
        (
            "inventory",
            manifest.inventory_uri,
            manifest.inventory_sha256,
            manifest.entity_count,
            "entity_count",
        ),
        (
            "asset catalog",
            manifest.assets_uri,
            manifest.assets_sha256,
            manifest.asset_count,
            "asset_count",
        ),
    ):
        bucket, name = parse_gs_uri(uri)
        if bucket != context.recovery_bucket:
            raise DataLifecycleError(f"Recovery {label} is in another bucket.")
        payload, _catalog_blob = context.load_json_object(name)
        observed_sha = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if observed_sha != expected_sha or payload.get(count_key) != expected_count:
            raise DataLifecycleError(f"Recovery {label} checksum/count is invalid.")
    return manifest, blob


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason point-in-time normalization is enforced by the public backup workflow
def _snapshot_time(value=None):
    value = value or datetime.now(timezone.utc) - timedelta(minutes=1)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DataLifecycleError("Recovery snapshot time must include a timezone.")
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason runtime bucket binding is exercised by exact asset capture
def _runtime_buckets(context):
    from config import SETTINGS
    from config.storage import storage_bucket_names

    return {
        role: context.storage.bucket(name)
        for role, name in storage_bucket_names(SETTINGS.APP).items()
    }


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason sanitized catalog publication follows validated backup publication
def _refresh_runtime_catalog(context):
    """Publish only non-sensitive manual-backup metadata for the admin UI."""
    from config import SETTINGS
    from config.storage import storage_bucket_names

    entries = [
        {
            "backup_id": item.backup_id,
            "snapshot_time": item.snapshot_time,
            "completed_at": item.export_completed_at,
            "application_version": item.application_version,
            "entity_count": item.entity_count,
            "asset_count": item.asset_count,
            "consistency": item.consistency,
        }
        for item in list_backups(context, announce=False)
    ]
    private_name = storage_bucket_names(SETTINGS.APP)["private"]
    blob = context.storage.bucket(private_name).blob(RUNTIME_CATALOG_OBJECT)
    blob.upload_from_string(
        json.dumps(
            {
                "format": "lagniappe-runtime-recovery-catalog",
                "schema_version": 1,
                "updated_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "recovery_sets": entries,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        content_type="application/json",
    )


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason best-effort UI projection cannot invalidate a completed recovery set
def _try_refresh_runtime_catalog(context):
    try:
        _refresh_runtime_catalog(context)
    except Exception as error:
        print(f"Warning: manual backup is valid, but the admin catalog was not refreshed: {error}")


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason immutable catalog publication is exercised by backup resumption
def _publish_catalog(context, object_name, payload):
    descriptor = catalog_descriptor(
        f"gs://{context.recovery_bucket}/{object_name}", payload
    )
    blob = context.bucket.blob(object_name)
    if blob.exists():
        existing, _blob = context.load_json_object(object_name)
        if catalog_descriptor(descriptor["uri"], existing)["sha256"] != descriptor["sha256"]:
            raise DataLifecycleError(f"Existing recovery catalog conflicts: {object_name}")
    else:
        context.upload_json_create_only(object_name, payload)
    return descriptor


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_backup_resumes_provider_operation_and_publishes_manifest_last
# @tests tests_tooling/test_008_data_lifecycle.py::test_backup_selects_completed_whole_minute_without_runtime_action
# @matrix data-lifecycle : backup manifest-last point-in-time resume
def create_backup(
    context: ProviderContext | None = None,
    *,
    backup_id: str | None = None,
    checkpoint: LifecycleCheckpoint | None = None,
    finish_checkpoint: bool = True,
    snapshot_time: datetime | None = None,
    source_database_id: str = "(default)",
    point_in_time_read: bool = True,
) -> BackupManifest:
    """Create/resume one exact manual backup and publish its marker last."""
    from installer import FORMATTER

    formatter = FORMATTER.initialize()
    context = context or ProviderContext.from_settings()
    command = ["backup", "create"]
    checkpoint = checkpoint or LifecycleCheckpoint(context.project_id, command)
    state = checkpoint.load()
    if state and state.get("status") == "complete":
        checkpoint.remove()
        state = None
    if not state and backup_id:
        backup_id = validate_backup_id(backup_id)
        manifest_blob = context.bucket.blob(manifest_object_name(backup_id))
        if manifest_blob.exists():
            manifest, _blob = load_backup(context, backup_id)
            return manifest
    context.require_asset_generation_migration(source_database_id)
    if state:
        backup_id = validate_backup_id(state["backup_id"])
        if state.get("manifest"):
            manifest, _blob = load_backup(context, backup_id)
            return manifest
    else:
        backup_id = validate_backup_id(backup_id or new_backup_id())
        if snapshot_time is None:
            snapshot_time = context.now().astimezone(timezone.utc) - timedelta(minutes=1)
        selected_snapshot = _snapshot_time(snapshot_time)
        checkpoint.start(
            backup_id,
            backup_id=backup_id,
            snapshot_time=selected_snapshot.isoformat().replace("+00:00", "Z"),
        )

    action = "Resuming" if state else "Creating"
    print(formatter.info(f"{action} manual backup {backup_id}"))
    print("The database and exact versions of referenced files will be saved.")

    selected_snapshot = _snapshot_time(
        datetime.fromisoformat(
            str(checkpoint.payload["snapshot_time"]).replace("Z", "+00:00")
        )
    )

    exact_root = backup_root_uri(context.recovery_bucket, backup_id)
    datastore_output = f"{exact_root}/datastore"
    operation_name = checkpoint.payload.get("provider_operation")
    record_step("create the point-in-time database backup")
    with _progress(
        formatter,
        "Creating point-in-time database backup (this may take several minutes)",
    ):
        if not operation_name:
            export_arguments = {
                "snapshot_time": selected_snapshot if point_in_time_read else None
            }
            if source_database_id == "(default)":
                operation_name, start_payload = context.start_export(
                    datastore_output, **export_arguments
                )
            else:
                operation_name, start_payload = context.start_export(
                    datastore_output,
                    database_id=source_database_id,
                    **export_arguments,
                )
            checkpoint.update(
                "export-started",
                provider_operation=operation_name,
                start_payload=start_payload,
            )
            record_mutation(
                "start Datastore export",
                action="create",
                resource="managed-export",
                identifier=operation_name,
                details={"backup_id": backup_id},
            )

        completed = (
            context.wait_for_operation(operation_name)
            if source_database_id == "(default)"
            else context.wait_for_operation(
                operation_name, database_id=source_database_id
            )
        )
    reported_output_uri = export_output_uri(completed).rstrip("/")
    require_uri_below(reported_output_uri, exact_root)
    objects = context.list_objects(f"{BACKUP_ROOT_PREFIX}/{backup_id}/datastore/")
    object_names = {blob.name for blob in objects}
    metadata_names = sorted(
        name for name in object_names if name.endswith(".overall_export_metadata")
    )
    if len(metadata_names) != 1:
        raise DataLifecycleError(
            "Completed export must contain exactly one overall metadata object."
        )
    metadata_name = metadata_names[0]
    metadata_uri = f"gs://{context.recovery_bucket}/{metadata_name}"
    if reported_output_uri.endswith(".overall_export_metadata"):
        if reported_output_uri != metadata_uri:
            raise DataLifecycleError("Provider export metadata does not match stored output.")
    elif not metadata_uri.startswith(f"{reported_output_uri}/"):
        raise DataLifecycleError("Provider export output does not contain its metadata object.")
    if len(object_names) < 2:
        raise DataLifecycleError("Completed export has no managed data objects.")

    inventory_name = f"{BACKUP_ROOT_PREFIX}/{backup_id}/inventory.json"
    assets_name = f"{BACKUP_ROOT_PREFIX}/{backup_id}/assets.json"
    if not checkpoint.payload.get("catalogs"):
        record_step("save referenced file versions")
        with _progress(
            formatter,
            "Scanning the database snapshot for referenced files",
        ):
            inventory, asset_references = inventory_database(
                context.datastore_client(source_database_id),
                snapshot_time=selected_snapshot,
                source_database_id=source_database_id,
                point_in_time_read=point_in_time_read,
            )
        if asset_references:
            with _progress(
                formatter,
                f"Saving {len(asset_references)} referenced file versions",
            ) as spinner:
                captured_assets = capture_assets(
                    context,
                    backup_id,
                    asset_references,
                    _runtime_buckets(context),
                    progress=lambda current, total: setattr(
                        spinner,
                        "text",
                        formatter.success(
                            f"Saving referenced file versions ({current}/{total})"
                        ),
                    ),
                )
        else:
            captured_assets = []
        assets_payload = {
            "snapshot_time": inventory["snapshot_time"],
            "asset_count": len(captured_assets),
            "assets": captured_assets,
        }
        inventory_descriptor = _publish_catalog(context, inventory_name, inventory)
        assets_descriptor = _publish_catalog(context, assets_name, assets_payload)
        checkpoint.update(
            "catalogs-captured",
            catalogs={
                "inventory": {
                    "uri": inventory_descriptor["uri"],
                    "sha256": inventory_descriptor["sha256"],
                    "count": inventory["entity_count"],
                },
                "assets": {
                    "uri": assets_descriptor["uri"],
                    "sha256": assets_descriptor["sha256"],
                    "count": assets_payload["asset_count"],
                },
            },
        )
    catalogs = checkpoint.payload["catalogs"]

    database = (
        context.database()
        if source_database_id == "(default)"
        else context.database(source_database_id)
    )
    mode = str(database.get("type") or database.get("databaseType") or "").casefold().replace("_", "-")
    if mode not in {"datastore-mode", "datastore"}:
        raise DataLifecycleError("Active database is not in Datastore mode.")
    location = str(database.get("locationId") or database.get("location_id") or "").strip()
    if not location:
        raise DataLifecycleError("Provider did not report the active database location.")
    started_at, completed_at = operation_times(completed)
    output_prefix = metadata_uri.rsplit("/", 1)[0]
    manifest = BackupManifest(
        format=BACKUP_FORMAT,
        schema_version=BACKUP_SCHEMA_VERSION,
        status="complete",
        backup_id=backup_id,
        root_uri=exact_root,
        project_id=context.project_id,
        application_version=context.application_version,
        source_database_id=context.database_id,
        database_mode="datastore-mode",
        database_location=location,
        operation_name=operation_name,
        export_output_prefix=output_prefix,
        export_metadata_uri=metadata_uri,
        export_started_at=started_at,
        export_completed_at=completed_at,
        snapshot_time=selected_snapshot.isoformat().replace("+00:00", "Z"),
        consistency="point-in-time",
        inventory_uri=catalogs["inventory"]["uri"],
        inventory_sha256=catalogs["inventory"]["sha256"],
        entity_count=int(catalogs["inventory"]["count"]),
        assets_uri=catalogs["assets"]["uri"],
        assets_sha256=catalogs["assets"]["sha256"],
        asset_count=int(catalogs["assets"]["count"]),
        tool_version=context.application_version,
    )
    BackupManifest.from_dict(
        manifest.as_dict(),
        expected_project=context.project_id,
        expected_backup_id=backup_id,
        expected_bucket=context.recovery_bucket,
    )
    manifest_blob = context.bucket.blob(manifest_object_name(backup_id))
    if manifest_blob.exists():
        existing, _blob = load_backup(context, backup_id)
        if (
            existing.operation_name != operation_name
            or existing.export_metadata_uri != metadata_uri
        ):
            raise DataLifecycleError(
                "Existing completion manifest does not belong to this export operation."
            )
        if finish_checkpoint:
            checkpoint.remove()
        else:
            checkpoint.update("backup-complete", manifest=existing.as_dict())
        _try_refresh_runtime_catalog(context)
        _print_backup_summary(formatter, existing)
        return existing
    record_step("publish the completed backup")
    context.upload_json_create_only(manifest_object_name(backup_id), manifest.as_dict())
    _try_refresh_runtime_catalog(context)
    if finish_checkpoint:
        checkpoint.remove()
    else:
        checkpoint.update("backup-complete", manifest=manifest.as_dict())
    _print_backup_summary(formatter, manifest)
    return manifest


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_backup_listing_ignores_invalid_incomplete_and_foreign_objects
# @matrix data-lifecycle : backup-list manifest
def list_backups(
    context: ProviderContext | None = None,
    *,
    announce: bool = True,
) -> list[BackupManifest]:
    context = context or ProviderContext.from_settings()
    manifests = []
    for blob in context.list_objects(f"{BACKUP_ROOT_PREFIX}/"):
        parts = str(blob.name).split("/")
        if len(parts) != 5 or parts[:3] != ["lagniappe-data", "v3", "recovery-sets"] or parts[-1] != "manifest.json":
            continue
        try:
            backup_id = validate_backup_id(parts[3])
            payload = json.loads(blob.download_as_text(encoding="utf-8"))
            manifest = BackupManifest.from_dict(
                payload,
                expected_project=context.project_id,
                expected_backup_id=backup_id,
                expected_bucket=context.recovery_bucket,
            )
        except Exception:
            continue
        manifests.append(manifest)
    manifests.sort(key=lambda item: (item.export_completed_at, item.backup_id), reverse=True)
    if announce:
        for manifest in manifests:
            print(
                f"{manifest.backup_id}  {manifest.export_completed_at}  "
                f"database={manifest.source_database_id}  {manifest.consistency}  "
                f"app={manifest.application_version}"
            )
    return manifests


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_backup_delete_requires_typed_confirmation_and_manifest_first
# @matrix data-lifecycle : backup-delete confirmation path-containment
def delete_backup(
    backup_id: str,
    context: ProviderContext | None = None,
    *,
    confirm=input,
) -> bool:
    """Delete one exact completed or incomplete v3 prefix after typed consent."""
    context = context or ProviderContext.from_settings()
    backup_id = validate_backup_id(backup_id)
    prefix = f"{BACKUP_ROOT_PREFIX}/{backup_id}/"
    objects = context.list_objects(prefix)
    if not objects:
        raise DataLifecycleError(f"Backup {backup_id} does not exist.")
    if any(not str(blob.name).startswith(prefix) for blob in objects):
        raise DataLifecycleError("Provider returned an object outside the exact backup root.")
    manifest_blob = next((blob for blob in objects if blob.name == f"{prefix}manifest.json"), None)
    if manifest_blob is not None:
        payload = json.loads(manifest_blob.download_as_text(encoding="utf-8"))
        BackupManifest.from_dict(
            payload,
            expected_project=context.project_id,
            expected_backup_id=backup_id,
            expected_bucket=context.recovery_bucket,
        )
    expected = f"DELETE {context.project_id} {backup_id}"
    print(f"This will permanently delete only gs://{context.recovery_bucket}/{prefix}")
    if str(confirm(f"Type {expected} to continue: ")).strip() != expected:
        raise DataLifecycleError("Backup deletion cancelled; confirmation did not match.")
    if manifest_blob is not None:
        generation = int(manifest_blob.generation or 0)
        if not generation:
            manifest_blob.reload()
            generation = int(manifest_blob.generation)
        manifest_blob.delete(if_generation_match=generation)
        record_mutation(
            "invalidate backup",
            action="delete",
            resource="storage-object",
            identifier=manifest_blob.name,
        )
    for blob in objects:
        if blob.name == f"{prefix}manifest.json":
            continue
        blob.delete()
    _try_refresh_runtime_catalog(context)
    print(f"Deleted backup {backup_id} from its exact v3 prefix.")
    return True


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_automatic_backup_preparation_uses_scratch_then_v3
# @matrix data-lifecycle : named-scratch-database automatic-backup-preparation
def prepare_automatic_backup(resource_name, context=None):
    """Prepare one automatic provider backup as a self-contained manual backup."""
    context = context or ProviderContext.from_settings()
    value = str(resource_name or "").strip()
    match = re.fullmatch(
        rf"projects/{re.escape(context.project_id)}/locations/([^/]+)/backups/([^/]+)",
        value,
    )
    if not match:
        raise DataLifecycleError("Native backup must be a full resource name in this project.")
    location, native_id = match.groups()
    checkpoint = LifecycleCheckpoint(
        context.project_id, ["backup", "prepare", value]
    )
    state = checkpoint.load()
    if state and state.get("status") == "complete":
        checkpoint.remove()
        state = None
    if state:
        backup_id = validate_backup_id(state["backup_id"])
        scratch = validate_database_id(
            state["scratch_database"], allow_default=False
        )
        snapshot_time = datetime.fromisoformat(
            state["snapshot_time"].replace("Z", "+00:00")
        )
    else:
        described = context.json_command(
            [
                "firestore",
                "backups",
                "describe",
                f"--backup={native_id}",
                f"--location={location}",
            ]
        )
        if str(described.get("state") or "").upper() != "READY":
            raise DataLifecycleError("Native backup is not ready.")
        source = str(described.get("database") or "")
        if not source.endswith("/databases/(default)"):
            raise DataLifecycleError("Native backup is not for the default database.")
        raw_snapshot = described.get("snapshotTime") or described.get("snapshot_time")
        try:
            snapshot_time = datetime.fromisoformat(
                str(raw_snapshot).replace("Z", "+00:00")
            ).astimezone(timezone.utc).replace(second=0, microsecond=0)
        except (AttributeError, ValueError) as error:
            raise DataLifecycleError("Native backup snapshot time is invalid.") from error
        backup_id = new_backup_id()
        scratch = validate_database_id(
            f"lag-native-{backup_id[:8].casefold()}-{backup_id[-8:]}",
            allow_default=False,
        )
        checkpoint.start(
            backup_id,
            backup_id=backup_id,
            native_backup=value,
            scratch_database=scratch,
            snapshot_time=snapshot_time.isoformat().replace("+00:00", "Z"),
        )

    if not checkpoint.payload.get("scratch_restored"):
        operation = checkpoint.payload.get("native_restore_operation")
        if not operation:
            operation, _payload = context.start_native_backup_restore(value, scratch)
            checkpoint.update(
                "native-restore-started", native_restore_operation=operation
            )
        context.wait_for_operation(operation, database_id=scratch)
        checkpoint.update("native-restore-complete", scratch_restored=True)

    manifest = create_backup(
        context,
        backup_id=backup_id,
        checkpoint=LifecycleCheckpoint(
            context.project_id, ["backup", "create", "from-native", backup_id]
        ),
        snapshot_time=snapshot_time,
        source_database_id=scratch,
        point_in_time_read=False,
    )
    checkpoint.update("recovery-set-complete", recovery_set=manifest.as_dict())
    try:
        context.disable_database_delete_protection(scratch)
    except Exception:
        pass
    context.delete_database(scratch)
    checkpoint.finish()
    checkpoint.remove()
    print(f"Prepared automatic backup {value} as manual backup {backup_id}.")
    return manifest


__all__ = [
    "CONSISTENCY_NOTICE",
    "create_backup",
    "delete_backup",
    "list_backups",
    "load_backup",
    "prepare_automatic_backup",
    "manifest_object_name",
    "new_backup_id",
]
