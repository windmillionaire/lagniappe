"""Operator-only Datastore and Cloud Storage disaster-recovery commands."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from runner.context import GCLOUD_CLI, format_command

from config.storage import recovery_bucket_name, storage_bucket_names
from runner.process import run_command


BACKUP_SCHEMA_VERSION = 1
BACKUP_ROOT_PREFIX = "lagniappe-recovery/v1"
DATABASE_ID = "(default)"
BACKUP_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
LONG_OPERATION_TIMEOUT_SECONDS = 6 * 60 * 60


# @testable false
# @covered-by runner/data_recovery.py::create_backup
# @covered-by runner/data_recovery.py::restore_backup
# @reason recovery-specific failures are asserted through the public commands
class DataRecoveryError(RuntimeError):
    """Raised when a data backup or restore cannot proceed safely."""


# @testable false
# @covered-by runner/data_recovery.py::_gcloud
# @reason provider subprocess details are exercised through command-level tests
def _command_error(result, operation):
    detail = (result.stderr or result.stdout or "").strip()
    return DataRecoveryError(
        f"{operation} failed: {detail or 'gcloud returned an error'}"
    )


# @testable false
# @covered-by runner/data_recovery.py::create_backup
# @covered-by runner/data_recovery.py::restore_backup
# @reason shared provider adapter is exercised through public recovery commands
def _gcloud(
    arguments,
    *,
    check=True,
    timeout=LONG_OPERATION_TIMEOUT_SECONDS,
    announce=False,
):
    if not GCLOUD_CLI:
        raise DataRecoveryError("gcloud CLI not found")

    command = [GCLOUD_CLI, *[str(argument) for argument in arguments]]
    if announce:
        print("Running:", format_command(command), flush=True)
    try:
        result = run_command(
            command,
            check=False,
            timeout=timeout,
        )
    except RuntimeError as error:
        raise DataRecoveryError(str(error)) from error
    if check and result.returncode != 0:
        raise _command_error(result, format_command(command))
    return result


# @testable false
# @covered-by runner/data_recovery.py::_json_gcloud
# @reason JSON decoding is asserted through provider preflight and export tests
def _json_output(result, operation):
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise DataRecoveryError(f"{operation} returned invalid JSON.") from error


# @testable false
# @covered-by runner/data_recovery.py::_describe_database
# @covered-by runner/data_recovery.py::_describe_bucket
# @reason absence classification is exercised through restore preflight tests
def _is_not_found(result):
    text = f"{result.stderr or ''}\n{result.stdout or ''}".casefold()
    return any(
        marker in text
        for marker in (
            "not_found",
            "not found",
            "does not exist",
            "could not be found",
            "matched no objects",
            "matched no urls",
        )
    )


# @testable false
# @covered-by runner/data_recovery.py::_prepare_context
# @covered-by runner/data_recovery.py::create_backup
# @covered-by runner/data_recovery.py::restore_backup
# @reason structured gcloud reads are exercised through command-level tests
def _json_gcloud(arguments, operation, *, allow_absent=False):
    result = _gcloud([*arguments, "--format=json"], check=False)
    if result.returncode != 0:
        if allow_absent and _is_not_found(result):
            return None
        raise _command_error(result, operation)
    return _json_output(result, operation)


# @testable false
# @covered-by runner/data_recovery.py::_prepare_context
# @reason active-project binding is exercised through public command preflight
def _settings_context():
    from config import SETTINGS
    from runner.gcloud import config_gcloud

    if os.environ.get("FLASK_ENV", "production") != "production":
        raise DataRecoveryError(
            "Data recovery commands only operate on the production configuration."
        )

    config_gcloud()
    settings = dict(SETTINGS.APP)
    saved_project = str(settings.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    configured_project = str(
        (SETTINGS.GCLOUD_CONFIG or {}).get("PROJECT") or ""
    ).strip()
    if not saved_project or saved_project != configured_project:
        raise DataRecoveryError(
            "The saved application and gcloud projects do not match."
        )
    if not settings.get("GIBBERISH"):
        raise DataRecoveryError(
            "The canonical settings are missing the bucket naming secret."
        )

    source_buckets = storage_bucket_names(settings)
    recovery_bucket = recovery_bucket_name(settings)
    if recovery_bucket in source_buckets.values():
        raise DataRecoveryError(
            "The recovery bucket must be separate from every runtime bucket."
        )

    return {
        "project": saved_project,
        "settings": settings,
        "source_buckets": source_buckets,
        "recovery_bucket": recovery_bucket,
        "version": str(
            settings.get("VERSION") or (SETTINGS.NODE or {}).get("version") or ""
        ),
    }


# @testable false
# @covered-by runner/data_recovery.py::_prepare_context
# @reason bucket discovery is asserted through public command preflight
def _describe_bucket(bucket_name, project, *, allow_absent=False):
    return _json_gcloud(
        [
            "storage",
            "buckets",
            "describe",
            f"gs://{bucket_name}",
            f"--project={project}",
        ],
        f"Cloud Storage bucket lookup for {bucket_name}",
        allow_absent=allow_absent,
    )


# @testable false
# @covered-by runner/data_recovery.py::_prepare_context
# @covered-by runner/data_recovery.py::restore_backup
# @reason database discovery is asserted through public command preflight
def _describe_database(project, *, allow_absent=False):
    return _json_gcloud(
        [
            "firestore",
            "databases",
            "describe",
            f"--database={DATABASE_ID}",
            f"--project={project}",
        ],
        "Datastore database lookup",
        allow_absent=allow_absent,
    )


# @testable false
# @covered-by runner/data_recovery.py::_prepare_context
# @covered-by runner/data_recovery.py::_validate_manifest
# @reason database contract validation is exercised through recovery preflight tests
def _database_location(database):
    return str(
        (database or {}).get("locationId") or (database or {}).get("location_id") or ""
    ).strip()


# @testable false
# @covered-by runner/data_recovery.py::_prepare_context
# @reason database mode validation is exercised through recovery preflight tests
def _require_datastore_mode(database):
    database_type = re.sub(
        r"[^a-z]",
        "",
        str((database or {}).get("type") or "").casefold(),
    )
    if database_type != "datastoremode":
        raise DataRecoveryError(
            "The default database is not a Firestore in Datastore mode database."
        )


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_location_compatibility_accepts_datastore_multiregions
# @features disaster-recovery
# @dimensions datastore storage location
def locations_compatible(database_location, bucket_location):
    """Return whether a recovery bucket can receive this Datastore export."""
    database_location = str(database_location or "").casefold()
    bucket_location = str(bucket_location or "").casefold()
    if not database_location or not bucket_location:
        return False
    if database_location == bucket_location:
        return True
    if bucket_location == "us" and database_location.startswith("nam"):
        return True
    if bucket_location == "eu" and database_location.startswith("eur"):
        return True
    if bucket_location == "asia" and database_location.startswith("asia"):
        return True
    return False


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_prepare_context_validates_recovery_sources_and_database
# @features disaster-recovery
# @dimensions provider-preflight project-identity runtime-isolation
def _prepare_context(*, require_sources, require_database):
    context = _settings_context()
    project = context["project"]
    recovery = _describe_bucket(context["recovery_bucket"], project, allow_absent=True)
    if recovery is None:
        raise DataRecoveryError(
            "The recovery bucket is missing. Run ./setup.sh repair before using "
            "data recovery commands."
        )
    context["recovery_bucket_details"] = recovery

    if require_sources:
        for kind, bucket_name in context["source_buckets"].items():
            if _describe_bucket(bucket_name, project, allow_absent=True) is None:
                raise DataRecoveryError(
                    f"The {kind} bucket is missing. Run ./setup.sh repair before "
                    "restoring data."
                )

    database = _describe_database(project, allow_absent=not require_database)
    context["database"] = database
    if database is not None:
        _require_datastore_mode(database)
        database_location = _database_location(database)
        bucket_location = str(
            recovery.get("location") or recovery.get("locationId") or ""
        )
        if not locations_compatible(database_location, bucket_location):
            raise DataRecoveryError(
                "The recovery bucket location is not compatible with the "
                "Datastore database location."
            )
        context["database_location"] = database_location

    return context


# @testable false
# @covered-by runner/data_recovery.py::create_backup
# @reason deterministic ID shape is asserted through completed manifest behavior
def _backup_id(now=None, token=None):
    now = now or datetime.now(timezone.utc)
    token = token or secrets.token_hex(4)
    return f"{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{token}"


# @testable false
# @covered-by runner/data_recovery.py::create_backup
# @covered-by runner/data_recovery.py::_validate_manifest
# @reason path construction is asserted through command-level recovery tests
def _backup_root(recovery_bucket, backup_id):
    return f"gs://{recovery_bucket}/{BACKUP_ROOT_PREFIX}/{backup_id}"


# @testable false
# @covered-by runner/data_recovery.py::create_backup
# @reason provider export response traversal is exercised by the backup command test
def _find_value(value, names):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in names and child:
                return child
            found = _find_value(child, names)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_value(child, names)
            if found:
                return found
    return None


# @testable false
# @covered-by runner/data_recovery.py::_validate_manifest
# @covered-by runner/data_recovery.py::create_backup
# @reason URI containment is asserted by hostile-manifest recovery tests
def _require_uri_under(uri, root, label):
    uri = str(uri or "").rstrip("/")
    root = str(root or "").rstrip("/")
    if not uri.startswith("gs://") or not (uri == root or uri.startswith(f"{root}/")):
        raise DataRecoveryError(f"{label} is outside the selected recovery set.")
    return uri


# @testable false
# @covered-by runner/data_recovery.py::create_backup
# @covered-by runner/data_recovery.py::_validate_manifest
# @reason bounded object discovery is exercised through backup and restore tests
def _storage_prefix_has_objects(uri, project):
    result = _gcloud(
        [
            "storage",
            "objects",
            "list",
            f"{uri.rstrip('/')}/**",
            "--limit=1",
            f"--project={project}",
            "--format=json",
        ],
        check=False,
    )
    if result.returncode != 0:
        if _is_not_found(result):
            return False
        raise _command_error(result, f"Cloud Storage object lookup for {uri}")
    payload = _json_output(result, f"Cloud Storage object lookup for {uri}")
    return bool(payload)


# @testable false
# @covered-by runner/data_recovery.py::create_backup
# @reason create-only manifest upload is asserted through backup completion tests
def _upload_manifest(uri, manifest, project):
    with tempfile.TemporaryDirectory(prefix="lagniappe-backup-") as temp_dir:
        path = Path(temp_dir) / "manifest.json"
        path.write_text(
            f"{json.dumps(manifest, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
        _gcloud(
            [
                "storage",
                "cp",
                path,
                uri,
                "--content-type=application/json",
                "--if-generation-match=0",
                f"--project={project}",
                "--quiet",
            ],
            announce=True,
        )


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_backup_writes_manifest_only_after_all_components_complete
# @tests tests_tooling/test_008_data_recovery.py::test_backup_failure_never_publishes_manifest
# @features disaster-recovery
# @dimensions backup datastore storage completion-manifest fuzzy-window failure-isolation
def create_backup(*, now=None, token=None):
    """Create one complete Datastore and live-object recovery set."""
    context = _prepare_context(require_sources=True, require_database=True)
    backup_id = _backup_id(now=now, token=token)
    root = _backup_root(context["recovery_bucket"], backup_id)
    started_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    project = context["project"]

    print(f"Creating recovery set {backup_id} in gs://{context['recovery_bucket']}")
    datastore_started = datetime.now(timezone.utc)
    export_destination = f"{root}/datastore"
    export_result = _gcloud(
        [
            "firestore",
            "export",
            export_destination,
            f"--database={DATABASE_ID}",
            f"--project={project}",
            "--format=json",
        ],
        announce=True,
    )
    export_payload = _json_output(export_result, "Datastore export")
    output_uri = _find_value(
        export_payload,
        {"outputUriPrefix", "output_uri_prefix"},
    )
    output_uri = _require_uri_under(
        output_uri or export_destination,
        export_destination,
        "Datastore export output",
    )
    datastore_completed = datetime.now(timezone.utc)

    storage_manifest = {}
    for kind, bucket_name in context["source_buckets"].items():
        component_started = datetime.now(timezone.utc)
        backup_uri = f"{root}/storage/{kind}/objects"
        _gcloud(
            [
                "storage",
                "rsync",
                f"gs://{bucket_name}",
                backup_uri,
                "--recursive",
                "--checksums-only",
                "--no-clobber",
                f"--project={project}",
            ],
            announce=True,
        )
        has_objects = _storage_prefix_has_objects(backup_uri, project)
        storage_manifest[kind] = {
            "source_bucket": bucket_name,
            "backup_uri": backup_uri,
            "empty": not has_objects,
            "started_at": component_started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    manifest = {
        "schema": BACKUP_SCHEMA_VERSION,
        "status": "complete",
        "backup_id": backup_id,
        "root_uri": root,
        "project": project,
        "app_version": context["version"],
        "consistency": "fuzzy",
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "database": {
            "id": DATABASE_ID,
            "type": "DATASTORE_MODE",
            "location": context["database_location"],
            "output_uri_prefix": output_uri,
            "started_at": datastore_started.isoformat(),
            "completed_at": datastore_completed.isoformat(),
        },
        "storage": storage_manifest,
    }
    manifest_uri = f"{root}/manifest.json"
    _upload_manifest(manifest_uri, manifest, project)
    print(f"Recovery set complete: {backup_id}")
    return manifest


# @testable false
# @covered-by runner/data_recovery.py::list_backups
# @reason manifest enumeration is exercised through public list behavior
def _manifest_uris(context):
    pattern = f"gs://{context['recovery_bucket']}/{BACKUP_ROOT_PREFIX}/*/manifest.json"
    result = _gcloud(
        [
            "storage",
            "ls",
            pattern,
            f"--project={context['project']}",
        ],
        check=False,
    )
    if result.returncode != 0:
        if _is_not_found(result):
            return []
        raise _command_error(result, "Recovery manifest listing")
    return sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("gs://")
    )


# @testable false
# @covered-by runner/data_recovery.py::list_backups
# @covered-by runner/data_recovery.py::_load_manifest
# @reason manifest download is exercised through list and restore behavior
def _download_manifest(uri, project):
    result = _gcloud(
        [
            "storage",
            "cat",
            uri,
            f"--project={project}",
        ]
    )
    return _json_output(result, f"Recovery manifest {uri}")


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_list_backups_ignores_invalid_or_incomplete_manifests
# @features disaster-recovery
# @dimensions backup-list completion-manifest validation
def list_backups():
    """Print and return completed recovery sets in newest-first order."""
    context = _prepare_context(require_sources=False, require_database=False)
    backups = []
    for uri in _manifest_uris(context):
        try:
            manifest = _download_manifest(uri, context["project"])
        except DataRecoveryError as error:
            print(f"Skipping unreadable recovery manifest {uri}: {error}")
            continue
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != BACKUP_SCHEMA_VERSION
            or manifest.get("status") != "complete"
            or not BACKUP_ID_PATTERN.fullmatch(str(manifest.get("backup_id") or ""))
        ):
            print(f"Skipping invalid or incomplete recovery manifest {uri}")
            continue
        backups.append(manifest)

    backups.sort(key=lambda item: str(item.get("completed_at") or ""), reverse=True)
    if not backups:
        print("No completed recovery sets found.")
        return []

    print("Completed recovery sets:")
    for manifest in backups:
        print(
            "  "
            f"{manifest['backup_id']}  "
            f"{manifest.get('completed_at') or '(unknown time)'}  "
            f"version {manifest.get('app_version') or '(unknown)'}"
        )
    return backups


# @testable false
# @covered-by runner/data_recovery.py::restore_backup
# @reason deterministic manifest loading is exercised through restore tests
def _load_manifest(context, backup_id):
    if not BACKUP_ID_PATTERN.fullmatch(str(backup_id or "")):
        raise DataRecoveryError("Invalid recovery-set ID.")
    uri = f"{_backup_root(context['recovery_bucket'], backup_id)}/manifest.json"
    return _download_manifest(uri, context["project"])


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_restore_rejects_manifest_paths_outside_recovery_set
# @tests tests_tooling/test_008_data_recovery.py::test_restore_rejects_other_project_manifest
# @tests tests_tooling/test_008_data_recovery.py::test_restore_rejects_database_location_mismatch_before_mutation
# @tests tests_tooling/test_008_data_recovery.py::test_restore_purges_before_import_and_mirrors_storage
# @features disaster-recovery
# @dimensions restore manifest-validation project-identity path-containment location
def _validate_manifest(context, manifest, backup_id):
    if not isinstance(manifest, dict):
        raise DataRecoveryError("The recovery manifest is not a JSON object.")
    if manifest.get("schema") != BACKUP_SCHEMA_VERSION:
        raise DataRecoveryError("Unsupported recovery manifest schema.")
    if manifest.get("status") != "complete":
        raise DataRecoveryError("The selected recovery set is incomplete.")
    if manifest.get("backup_id") != backup_id:
        raise DataRecoveryError("The recovery manifest ID does not match its path.")
    if manifest.get("project") != context["project"]:
        raise DataRecoveryError(
            "The recovery set belongs to a different Google Cloud project."
        )

    root = _backup_root(context["recovery_bucket"], backup_id)
    if manifest.get("root_uri") != root:
        raise DataRecoveryError("The recovery manifest root is invalid.")

    database = manifest.get("database")
    if not isinstance(database, dict):
        raise DataRecoveryError("The recovery manifest database entry is invalid.")
    if database.get("id") != DATABASE_ID:
        raise DataRecoveryError("The recovery set is not for the default database.")
    if (
        re.sub(
            r"[^a-z]",
            "",
            str(database.get("type") or "").casefold(),
        )
        != "datastoremode"
    ):
        raise DataRecoveryError("The recovery set is not for Datastore mode.")
    if not database.get("location"):
        raise DataRecoveryError("The recovery manifest has no database location.")
    manifest_location = str(database["location"]).casefold()
    target_database = context.get("database")
    if (
        target_database is not None
        and _database_location(target_database).casefold() != manifest_location
    ):
        raise DataRecoveryError(
            "The target database location differs from the recovery set."
        )
    recovery_location = str(
        context["recovery_bucket_details"].get("location")
        or context["recovery_bucket_details"].get("locationId")
        or ""
    )
    if not locations_compatible(manifest_location, recovery_location):
        raise DataRecoveryError(
            "The recovery bucket location is incompatible with the recovery set."
        )
    _require_uri_under(
        database.get("output_uri_prefix"),
        f"{root}/datastore",
        "Datastore export output",
    )

    storage = manifest.get("storage")
    if not isinstance(storage, dict) or set(storage) != set(context["source_buckets"]):
        raise DataRecoveryError("The recovery manifest has an invalid bucket set.")
    for kind, source_bucket in context["source_buckets"].items():
        component = storage.get(kind)
        if not isinstance(component, dict):
            raise DataRecoveryError(f"The {kind} storage manifest entry is invalid.")
        if component.get("source_bucket") != source_bucket:
            raise DataRecoveryError(
                f"The {kind} bucket does not match the recovered settings."
            )
        if not isinstance(component.get("empty"), bool):
            raise DataRecoveryError(
                f"The {kind} storage manifest has an invalid empty marker."
            )
        expected_uri = f"{root}/storage/{kind}/objects"
        if component.get("backup_uri") != expected_uri:
            raise DataRecoveryError(f"The {kind} backup path is invalid.")

    return manifest


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_validate_artifacts_enforces_manifest_empty_markers
# @features disaster-recovery
# @dimensions restore artifact-validation
def _validate_artifacts(context, manifest):
    project = context["project"]
    database_uri = manifest["database"]["output_uri_prefix"]
    if not _storage_prefix_has_objects(database_uri, project):
        raise DataRecoveryError("The Datastore export files are missing.")

    for kind, component in manifest["storage"].items():
        has_objects = _storage_prefix_has_objects(
            component["backup_uri"],
            project,
        )
        if bool(component.get("empty")) == has_objects:
            raise DataRecoveryError(
                f"The {kind} backup contents do not match its manifest."
            )


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_restore_offline_rejects_traffic
# @features disaster-recovery
# @dimensions restore offline-gate
def _restore_offline(context, *, enforce):
    project = context["project"]
    app = _json_gcloud(
        ["app", "describe", f"--project={project}"],
        "App Engine application lookup",
        allow_absent=True,
    )
    if app is None:
        return True
    status = str(app.get("servingStatus") or app.get("serving_status") or "").upper()
    if status == "USER_DISABLED":
        return True

    versions = _json_gcloud(
        [
            "app",
            "versions",
            "list",
            "--hide-no-traffic",
            f"--project={project}",
        ],
        "App Engine traffic lookup",
    )
    if not versions:
        return True

    message = (
        "App Engine is still serving traffic. Disable the application before "
        "restoring so no writes can occur during purge and import."
    )
    if enforce:
        raise DataRecoveryError(message)
    print(f"WARNING: {message}")
    return False


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_mirror_storage_uses_exact_delete_semantics
# @features disaster-recovery
# @dimensions restore storage-mirror exact-replacement
def _mirror_storage(context, manifest, *, dry_run):
    results = []
    for kind, component in manifest["storage"].items():
        destination = f"gs://{context['source_buckets'][kind]}"
        if component.get("empty"):
            temp_context = tempfile.TemporaryDirectory(
                prefix=f"lagniappe-empty-{kind}-"
            )
            source = temp_context.name
        else:
            temp_context = None
            source = component["backup_uri"]
        try:
            arguments = [
                "storage",
                "rsync",
                source,
                destination,
                "--recursive",
                "--checksums-only",
                "--delete-unmatched-destination-objects",
                f"--project={context['project']}",
            ]
            if dry_run:
                arguments.append("--dry-run")
            results.append(
                _gcloud(
                    arguments,
                    announce=not dry_run,
                )
            )
        finally:
            if temp_context is not None:
                temp_context.cleanup()
    return results


# @testable false
# @covered-by runner/data_recovery.py::restore_backup
# @reason provider dry-run parsing is exercised through restore verification
def _dry_run_reports_changes(results):
    markers = (
        "would copy",
        "would delete",
        "would remove",
        "copying gs://",
        "deleting gs://",
    )
    for result in results:
        output = f"{result.stdout or ''}\n{result.stderr or ''}".casefold()
        if any(marker in output for marker in markers):
            return True
    return False


# @testable false
# @covered-by runner/data_recovery.py::restore_backup
# @reason cache invalidation is part of the destructive restore boundary
def _flush_redis_cache():
    try:
        from lagniappe.core.tools.cache.utility import delete_cache

        delete_cache()
    except Exception as error:
        raise DataRecoveryError(
            "Data was restored, but Redis could not be flushed. Keep the "
            "application offline and repair the cache before serving traffic."
        ) from error


# @testable true
# @tests tests_tooling/test_008_data_recovery.py::test_restore_cancelled_before_any_mutation
# @tests tests_tooling/test_008_data_recovery.py::test_restore_purges_before_import_and_mirrors_storage
# @tests tests_tooling/test_008_data_recovery.py::test_restore_creates_missing_default_database
# @features disaster-recovery
# @dimensions restore confirmation storage-mirror datastore-purge import cache-flush failure-isolation missing-database create location
def restore_backup(backup_id, *, dry_run=False, input_fn=None):
    """Replace production data with one completed recovery set."""
    context = _prepare_context(require_sources=True, require_database=False)
    manifest = _load_manifest(context, backup_id)
    _validate_manifest(context, manifest, backup_id)
    _validate_artifacts(context, manifest)
    offline = _restore_offline(context, enforce=not dry_run)

    print(f"Recovery set: {backup_id}")
    print(f"Target project: {context['project']}")
    print(
        "Datastore: purge every entity, then import "
        f"{manifest['database']['output_uri_prefix']}"
    )
    for kind, component in manifest["storage"].items():
        state = "empty snapshot" if component.get("empty") else component["backup_uri"]
        print(
            f"Storage {kind}: replace gs://{context['source_buckets'][kind]} "
            f"from {state}"
        )

    if dry_run:
        if offline:
            results = _mirror_storage(context, manifest, dry_run=True)
            if _dry_run_reports_changes(results):
                print("Storage differences would be replaced.")
            else:
                print("Storage already matches this recovery set.")
        print("Dry run complete; no data was changed.")
        return True

    expected = f"RESTORE {context['project']} {backup_id}"
    prompt = (
        "This permanently replaces Datastore and live Storage contents.\n"
        f"Type '{expected}' to continue: "
    )
    answer = (input_fn or input)(prompt).strip()
    if answer != expected:
        print("Restore cancelled.")
        return False

    print("Mirroring Cloud Storage recovery data...")
    _mirror_storage(context, manifest, dry_run=False)

    database = _describe_database(context["project"], allow_absent=True)
    if database is None:
        print("Creating the missing default Datastore mode database...")
        _gcloud(
            [
                "firestore",
                "databases",
                "create",
                f"--database={DATABASE_ID}",
                f"--location={manifest['database']['location']}",
                "--type=datastore-mode",
                f"--project={context['project']}",
                "--quiet",
                "--format=json",
            ],
            announce=True,
        )
    else:
        _require_datastore_mode(database)
        if _database_location(database) != manifest["database"]["location"]:
            raise DataRecoveryError(
                "The target database location differs from the recovery set."
            )
        print("Purging every Datastore entity...")
        _gcloud(
            [
                "firestore",
                "bulk-delete",
                f"--database={DATABASE_ID}",
                f"--project={context['project']}",
                "--quiet",
                "--format=json",
            ],
            announce=True,
        )

    print("Importing Datastore recovery data...")
    _gcloud(
        [
            "firestore",
            "import",
            manifest["database"]["output_uri_prefix"],
            f"--database={DATABASE_ID}",
            f"--project={context['project']}",
            "--quiet",
            "--format=json",
        ],
        announce=True,
    )

    print("Flushing Redis cache data...")
    _flush_redis_cache()

    verification = _mirror_storage(context, manifest, dry_run=True)
    if _dry_run_reports_changes(verification):
        raise DataRecoveryError(
            "Storage verification found differences after the restore. Keep "
            "the application offline and rerun the restore."
        )

    print(
        f"Recovery set {backup_id} restored successfully. Keep the application "
        "offline until smoke checks pass, then re-enable it manually."
    )
    return True
