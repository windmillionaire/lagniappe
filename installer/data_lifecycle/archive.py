"""Resumable managed-backup to validated portable archive orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile

from installer.state import record_mutation, record_step
from installer.errors import ProviderConflict, ProviderNotFound
from runner.context import REPOSITORY_ROOT

from .assets import AssetCollector
from .backup import CONSISTENCY_NOTICE, create_backup, load_backup, new_backup_id
from .html import OfflineHTMLBuilder
from .portable import (
    PORTABLE_FORMAT,
    PORTABLE_SCHEMA_VERSION,
    ShardWriter,
    canonical_json,
    load_schema,
)
from .provider import (
    DataLifecycleError,
    ProviderContext,
    parse_gs_uri,
    validate_backup_id,
    validate_database_id,
)
from .staging import portable_records, stage_database
from .state import ArchiveState, LifecycleCheckpoint, secure_directory
from .validation import file_descriptor, validate_archive


PRIVATE_ARCHIVE_NOTICE = (
    "This archive contains private owner-visible content and is not encrypted. "
    "Protect it as sensitive data."
)


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason terminal animation wraps tested archive phases without changing their contracts
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
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason timestamp formatting is an internal archive-orchestration detail
def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason default path selection is exercised through archive publication
def _default_output(backup_id, zip_output):
    suffix = ".zip" if zip_output else ""
    return REPOSITORY_ROOT / "archives" / f"{backup_id}{suffix}"


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason output normalization is exercised through archive publication
def _output_path(path, *, zip_output):
    path = Path(path).expanduser().resolve()
    if zip_output and path.suffix.casefold() != ".zip":
        path = path.with_suffix(".zip")
    return path


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason overwrite protection is part of the public archive workflow
def _validate_output(path, *, zip_output):
    path = _output_path(path, zip_output=zip_output)
    if path.exists():
        if path.is_symlink() or zip_output or not path.is_dir() or any(path.iterdir()):
            raise DataLifecycleError(f"Refusing to overwrite existing archive output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason scratch naming is validated through the resumable archive workflow
def _scratch_database_id(backup_id, checkpoint_identity):
    stamp = backup_id[:8].casefold()
    value = f"lag-archive-{stamp}-{checkpoint_identity[:8]}"
    return validate_database_id(value, allow_default=False)


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason conflict recovery is exercised through the resumable archive workflow
def _wait_for_scratch_database(context, database_id, *, timeout=600):
    """Wait for an already-started scratch creation operation to become visible."""
    deadline = context.monotonic() + timeout
    attempt = 0
    while True:
        try:
            return context.database(database_id)
        except ProviderNotFound:
            if context.monotonic() >= deadline:
                raise DataLifecycleError(
                    "The reserved archive scratch database did not become available."
                )
            delays = (1, 2, 4, 8, 15, 30)
            context.sleep(delays[min(attempt, len(delays) - 1)])
            attempt += 1


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason private file creation is exercised by archive publication and validation
def _write_private(path, payload, *, binary=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if binary:
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding="utf-8", newline="\n")
    if os.name != "nt":
        os.chmod(path, 0o600)


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason provider response extraction is an internal orchestration adapter
def _provider_operation(payload):
    if not isinstance(payload, dict):
        return None
    return str(payload.get("name") or "").strip() or None


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason runtime bucket binding is exercised through archive asset collection
class _RecoveryAssetBucket:
    """Present immutable recovery objects through their original asset identity."""

    def __init__(self, context, role, bucket_name, entries):
        self.context = context
        self.role = role
        # AssetCollector uses this identity to rewrite canonical runtime URLs.
        # Reads still resolve exclusively through the immutable recovery copy.
        self.name = bucket_name
        self.entries = entries

    def blob(self, name, generation=None):
        key = (str(name), str(generation or ""))
        asset = self.entries.get(key)
        if asset is None:
            raise DataLifecycleError(
                f"Manual backup has no exact {self.role} asset {name!r} generation {generation!r}."
            )
        try:
            return self.context.bucket.blob(
                asset["recovery_object"],
                generation=int(asset["recovery_generation"]),
            )
        except TypeError:
            return self.context.bucket.blob(asset["recovery_object"])


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason exact recovery bindings are exercised through portable archive asset collection
def _recovery_buckets(context, backup):
    from config import SETTINGS
    from config.storage import storage_bucket_names

    bucket, name = parse_gs_uri(backup.assets_uri)
    if bucket != context.recovery_bucket:
        raise DataLifecycleError("Recovery asset catalog belongs to another bucket.")
    payload, _blob = context.load_json_object(name)
    by_role = {role: {} for role in ("private", "public", "history")}
    for asset in payload.get("assets") or []:
        role = asset.get("role")
        if role not in by_role:
            raise DataLifecycleError(f"Recovery asset role is invalid: {role!r}")
        by_role[role][(str(asset["path"]), str(asset["generation"]))] = asset
    runtime_names = storage_bucket_names(SETTINGS.APP)
    return {
        role: _RecoveryAssetBucket(context, role, runtime_names[role], entries)
        for role, entries in by_role.items()
    }


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason warning projection is exercised through archive publication and validation
def _warnings(state):
    values = []
    for row in state.connection.execute("SELECT id, code, details FROM warnings ORDER BY id"):
        try:
            details = json.loads(row["details"])
        except json.JSONDecodeError:
            details = {"message": row["details"]}
        values.append({"id": row["id"], "code": row["code"], **details})
    return values


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason bundle assembly is exercised through the public archive workflow
def _write_bundle(
    bundle,
    *,
    backup,
    records,
    assets,
    warnings,
    asset_window,
    created_at,
):
    schema_payload = canonical_json(load_schema())
    _write_private(bundle / "data" / "schema.json", schema_payload, binary=True)
    by_type = {}
    for record in records:
        by_type.setdefault(record["identity"]["type"], []).append(record)
    shard_writer = ShardWriter(bundle)
    shards = []
    type_counts = {}
    for semantic_type in sorted(by_type):
        sorted_records = sorted(
            by_type[semantic_type],
            key=lambda record: (
                record["identity"]["namespace"],
                record["identity"]["id"],
            ),
        )
        descriptors = shard_writer.write_type(semantic_type, sorted_records)
        for descriptor in descriptors:
            descriptor["type"] = semantic_type
        shards.extend(descriptors)
        type_counts[semantic_type] = len(sorted_records)
        for record in sorted_records:
            for child_type, children in (record.get("children") or {}).items():
                type_counts[child_type] = type_counts.get(child_type, 0) + len(children)
    catalog = {
        "format": PORTABLE_FORMAT,
        "schema_version": PORTABLE_SCHEMA_VERSION,
        "archive_id": backup.backup_id,
        "source_backup_id": backup.backup_id,
        "source_application_version": backup.application_version,
        "export_consistency": backup.consistency,
        "created_at": created_at,
        "asset_collection": asset_window,
        "warnings": warnings,
        "feature_flags": {
            "canonical_documents": True,
            "derived_ydoc_reconstruction": True,
            "future_import_planner": True,
            "owner_scoped_children": True,
        },
        "shards": shards,
        "type_counts": type_counts,
        "assets": assets,
    }
    catalog_payload = canonical_json(catalog)
    _write_private(bundle / "data" / "archive.json", catalog_payload, binary=True)
    html_result = OfflineHTMLBuilder(
        bundle,
        backup_id=backup.backup_id,
        created_at=created_at,
        consistency="point-in-time database and generation-bound recovery assets",
        warnings=warnings,
    ).build(records, assets)
    readme = f"""# Lagniappe private portable archive

- Archive ID: `{backup.backup_id}`
- Created: `{created_at}`
- Status: `{'degraded' if warnings else 'clean'}`

{PRIVATE_ARCHIVE_NOTICE}

This is a portable, source-key-free owner archive. Open `site/index.html`
directly in a browser for the offline presentation. `data/archive.json`, the
per-type shards, canonical document payloads, and `data/schema.json` are the
normative `lagniappe-portable/v1` interchange data.

{CONSISTENCY_NOTICE} Referenced Storage assets were read from the immutable
recovery copies captured with that manual backup. The portable conversion ran
from `{asset_window['started_at']}` through `{asset_window['completed_at']}`.
Missing optional assets make this archive degraded; missing required canonical
document content prevents publication.

The source manual backup retains provider keys for same-project restore. This
portable archive replaces them with typed portable IDs for top-level records
and parent-scoped keys for task history and messages. Existing entity hashes
remain ordinary application data; the archive does not create new ones. The
bundle is not itself a provider restore artifact.
"""
    _write_private(bundle / "README.md", readme)
    return catalog, html_result


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason completion-manifest assembly is exercised through archive validation
def _root_manifest(bundle, *, backup, catalog, warnings, html_result, created_at):
    files = sorted(
        (
            file_descriptor(path, bundle)
            for path in bundle.rglob("*")
            if path.is_file() and path.name != "manifest.json" and ".parts" not in path.parts
        ),
        key=lambda item: item["path"],
    )
    asset_count = len(catalog["assets"])
    return {
        "format": PORTABLE_FORMAT,
        "schema_version": PORTABLE_SCHEMA_VERSION,
        "status": "complete",
        "archive_status": "degraded" if warnings else "clean",
        "archive_id": backup.backup_id,
        "source_backup_id": backup.backup_id,
        "source_application_version": backup.application_version,
        "tool_version": backup.tool_version,
        "created_at": created_at,
        "export_consistency": backup.consistency,
        "asset_collection": catalog["asset_collection"],
        "counts": {
            "entities": sum(catalog["type_counts"].values()),
            "shards": len(catalog["shards"]),
            "assets": asset_count,
            "pages": html_result["pages"],
            "warnings": len(warnings),
        },
        "warnings": [{"id": value["id"], "code": value["code"]} for value in warnings],
        "key_audit_passed": True,
        "catalog_sha256": hashlib.sha256((bundle / "data" / "archive.json").read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256((bundle / "data" / "schema.json").read_bytes()).hexdigest(),
        "files": files,
    }


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason atomic directory publication is part of the public archive workflow
def _publish_directory(bundle, output):
    temporary_parent = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.publishing-", dir=output.parent)
    )
    secure_directory(temporary_parent)
    temporary = temporary_parent / output.name
    shutil.copytree(bundle, temporary)
    secure_directory(temporary)
    os.replace(temporary, output)
    temporary_parent.rmdir()


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason atomic ZIP publication is part of the public archive workflow
def _publish_zip(bundle, output, manifest):
    temporary_parent = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.publishing-", dir=output.parent)
    )
    secure_directory(temporary_parent)
    temporary = temporary_parent / output.name
    declared = [item["path"] for item in manifest["files"]]
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for relative in declared:
            archive.write(bundle / PurePosixPath(relative), relative)
        archive.write(bundle / "manifest.json", "manifest.json")
    if os.name != "nt":
        os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    temporary_parent.rmdir()


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason final permission hardening is exercised through archive publication
def _restrict_tree(root):
    if os.name == "nt":
        secure_directory(root)
        return
    for path in Path(root).rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    os.chmod(root, 0o700)


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason cleanup and retained failure state are archive workflow invariants
def _cleanup_successful_archive(context, checkpoint, output):
    scratch_database = checkpoint.payload.get("scratch_database")
    work = Path(checkpoint.payload.get("work_directory") or checkpoint.root)
    raw_state_path = work / "staging.sqlite3"
    record_step("delete successful archive scratch database")
    context.delete_database(scratch_database)
    raw_state_path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(f"{raw_state_path}{suffix}").unlink(missing_ok=True)
    expected_work = (checkpoint.root / "archive-work" / checkpoint.identity).resolve()
    if work.resolve() != expected_work:
        raise DataLifecycleError("Refusing to remove an unowned archive work directory.")
    if work.exists():
        shutil.rmtree(work)
    checkpoint.remove()


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_archive_build_publishes_manifest_last_and_retains_failed_scratch_state
# @matrix portable-archive : cleanup publication workflow
def build_archive(
    backup_id=None,
    *,
    output=None,
    zip_output=False,
    context=None,
):
    """Create/resume one portable archive and publish only after validation."""
    from installer import FORMATTER

    formatter = FORMATTER.initialize()
    context = context or ProviderContext.from_settings()
    explicit_backup = backup_id is not None
    explicit_output = output is not None
    backup_id = validate_backup_id(backup_id) if backup_id else None
    requested_output = _output_path(output, zip_output=zip_output) if explicit_output else None
    command = ["archive", *([backup_id] if explicit_backup else [])]
    if requested_output is not None:
        command.extend(["--output", str(requested_output)])
    if zip_output:
        command.append("--zip")
    checkpoint = LifecycleCheckpoint(
        context.project_id,
        command,
        output_target=str(
            requested_output
            or (_default_output(backup_id, zip_output).resolve() if backup_id else "")
        ),
    )
    state = checkpoint.load()
    if state:
        backup_id = validate_backup_id(state["backup_id"])
    else:
        backup_id = backup_id or new_backup_id()
        checkpoint.start(backup_id, backup_id=backup_id, zip=bool(zip_output))
        state = checkpoint.payload
    output = requested_output or _default_output(backup_id, zip_output).resolve()
    if state and state.get("status") == "complete":
        result = validate_archive(output)
        checkpoint.remove()
        print(f"Archive {result['archive_id']} is already complete at {output}")
        return output
    if state and state.get("published_path"):
        validate_archive(output)
        try:
            with _progress(formatter, "Removing the temporary archive database"):
                _cleanup_successful_archive(context, checkpoint, output)
        except Exception as error:
            checkpoint.update("cleanup-failed", cleanup_error=str(error))
            raise DataLifecycleError(
                f"Archive remains valid at {output}, but scratch cleanup failed again. "
                f"Retained scratch database: {checkpoint.payload.get('scratch_database')}."
            ) from error
        print(f"Archive published at {output}. {PRIVATE_ARCHIVE_NOTICE}")
        return output
    _validate_output(output, zip_output=zip_output)

    if explicit_backup or checkpoint.payload.get("recovery_set_ready"):
        backup, _blob = load_backup(context, backup_id)
    else:
        backup = create_backup(
            context,
            backup_id=backup_id,
            checkpoint=LifecycleCheckpoint(
                context.project_id,
                ["backup", "create", "for-archive", backup_id],
            ),
        )
        checkpoint.update("recovery-set-ready", recovery_set_ready=True)
    work = secure_directory(checkpoint.root / "archive-work" / checkpoint.identity)
    raw_state_path = work / "staging.sqlite3"
    bundle = secure_directory(work / "bundle")
    scratch_database = checkpoint.payload.get("scratch_database") or _scratch_database_id(
        backup_id, checkpoint.identity
    )
    checkpoint.update("scratch-reserved", scratch_database=scratch_database, work_directory=str(work))

    if not checkpoint.payload.get("scratch_created"):
        record_step("create archive scratch Datastore database")
        created = False
        operation = checkpoint.payload.get("scratch_create_operation")
        try:
            existing = context.database(scratch_database)
        except ProviderNotFound:
            existing = None
        if existing is None:
            with _progress(
                formatter,
                "Creating the temporary archive database (this may take several minutes)",
            ):
                if not operation:
                    try:
                        response = context.create_database(
                            scratch_database,
                            backup.database_location,
                            delete_protection=False,
                        )
                    except ProviderConflict:
                        existing = _wait_for_scratch_database(
                            context, scratch_database
                        )
                    else:
                        operation = _provider_operation(response)
                        if not operation:
                            raise DataLifecycleError(
                                "Provider did not return an operation for scratch database creation."
                            )
                        checkpoint.update(
                            "scratch-create-started",
                            scratch_create_operation=operation,
                        )
                        created = True
                if existing is None:
                    context.wait_for_operation(
                        operation, database_id=scratch_database
                    )
                    existing = context.database(scratch_database)
        mode = str(
            existing.get("type") or existing.get("databaseType") or ""
        ).casefold().replace("_", "-")
        location = str(
            existing.get("locationId") or existing.get("location_id") or ""
        ).strip()
        expected_name = f"projects/{context.project_id}/databases/{scratch_database}"
        if (
            str(existing.get("name") or "") != expected_name
            or mode not in {"datastore", "datastore-mode"}
            or location != backup.database_location
        ):
            raise DataLifecycleError(
                "The reserved archive scratch database has unexpected provider settings."
            )
        checkpoint.update("scratch-created", scratch_created=True)
        if created:
            record_mutation(
                "create archive scratch database",
                action="create",
                resource="datastore-database",
                identifier=scratch_database,
            )

    if not checkpoint.payload.get("import_complete"):
        operation = checkpoint.payload.get("import_operation")
        record_step("import managed backup into archive scratch database")
        with _progress(
            formatter,
            "Importing the manual backup (this may take several minutes)",
        ):
            if not operation:
                operation, _payload = context.start_import(
                    backup.export_output_prefix, scratch_database
                )
                checkpoint.update("scratch-import-started", import_operation=operation)
            context.wait_for_operation(operation, database_id=scratch_database)
        checkpoint.update("scratch-import-complete", import_complete=True)

    with ArchiveState(raw_state_path) as archive_state:
        if not archive_state.get_metadata("scan_complete", False):
            from config import SETTINGS

            record_step("scan archive scratch database in bounded pages")
            client = context.datastore_client(scratch_database)
            with _progress(formatter, "Scanning the saved database"):
                stage_database(
                    client,
                    archive_state,
                    source_project=context.project_id,
                    source_database=backup.source_database_id,
                    prefix=str(SETTINGS.APP.get("PREFIX") or ""),
                )
            archive_state.set_metadata("scan_complete", True)
            checkpoint.update("scratch-scan-complete")
        with _progress(
            formatter,
            "Collecting saved files and building the portable archive",
        ):
            records = portable_records(archive_state)
            collector = AssetCollector(
                archive_state, bundle, _recovery_buckets(context, backup)
            )
            assets, _asset_warnings = collector.collect()
            warnings = _warnings(archive_state)
            asset_window = {
                "started_at": collector.started_at,
                "completed_at": collector.completed_at,
                "consistency": "recovery-set-generations",
            }
            created_at = _now()
            catalog, html_result = _write_bundle(
                bundle,
                backup=backup,
                records=records,
                assets=assets,
                warnings=warnings,
                asset_window=asset_window,
                created_at=created_at,
            )
            parts = bundle / ".parts"
            if parts.exists():
                shutil.rmtree(parts)
            manifest = _root_manifest(
                bundle,
                backup=backup,
                catalog=catalog,
                warnings=warnings,
                html_result=html_result,
                created_at=created_at,
            )
            temporary_manifest = bundle / ".manifest.json.tmp"
            _write_private(
                temporary_manifest,
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            )
            os.replace(temporary_manifest, bundle / "manifest.json")
            _restrict_tree(bundle)
            validate_archive(bundle)
        checkpoint.update("bundle-validated", archive_status=manifest["archive_status"])

    record_step("publish validated private archive")
    with _progress(formatter, "Publishing and validating the portable archive"):
        if zip_output:
            _publish_zip(bundle, output, manifest)
        else:
            _publish_directory(bundle, output)
        validate_archive(output)
    checkpoint.update("archive-published", published_path=str(output))

    try:
        with _progress(formatter, "Removing the temporary archive database"):
            _cleanup_successful_archive(context, checkpoint, output)
    except Exception as error:
        checkpoint.update("cleanup-failed", cleanup_error=str(error))
        raise DataLifecycleError(
            f"Archive was published and validated at {output}, but cleanup failed. "
            f"Retained scratch database: {scratch_database}; retained work state: {work}. "
            "Rerun the exact archive command to finish cleanup."
        ) from error
    print(f"Archive published at {output}. {PRIVATE_ARCHIVE_NOTICE}")
    return output


__all__ = ["PRIVATE_ARCHIVE_NOTICE", "build_archive"]
