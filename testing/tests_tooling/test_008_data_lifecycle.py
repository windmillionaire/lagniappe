"""Provider-neutral contracts for setup-owned backup and portable archives."""

from datetime import date, datetime, timezone
import hashlib
import json
import os
from types import SimpleNamespace
import zipfile

from google.cloud.datastore import Entity, Key
from google.cloud.datastore.helpers import GeoPoint
import pytest

from config.datastore import decode_urlsafe_key, encode_urlsafe_key
from installer.data_lifecycle import archive as archive_module
from installer.data_lifecycle import backup as backup_module
from installer.data_lifecycle import restore as restore_module
from installer.data_lifecycle import restore_in_place
from installer.data_lifecycle.archive import _root_manifest, _write_bundle
from installer.data_lifecycle.assets import AssetCollector
from installer.data_lifecycle.backup import create_backup, delete_backup, list_backups
from installer.data_lifecycle.html import OfflineHTMLBuilder, sanitize_stored_html
from installer.data_lifecycle.portable import (
    DecodedEntity,
    ImportPlanner,
    MissingReference,
    PortableReference,
    ShardWriter,
    ValueCodec,
    canonical_json,
    parse_reference_string,
    portable_name,
    reference_string,
    unportable_name,
)
from installer.data_lifecycle.provider import (
    BACKUP_FORMAT,
    BACKUP_ROOT_PREFIX,
    BackupManifest,
    DataLifecycleError,
    ProviderContext,
    backup_root_uri,
    parse_gs_uri,
    require_uri_below,
    validate_backup_id,
    validate_database_id,
)
from installer.data_lifecycle.recovery_set import capture_assets, inventory_database
from installer.data_lifecycle.staging import portable_records, stage_database
from installer.data_lifecycle.state import ArchiveState, LifecycleCheckpoint, secure_directory
from installer.data_lifecycle.validation import file_descriptor, validate_archive
from installer.errors import ProviderNotFound


pytestmark = pytest.mark.tooling
BACKUP_ID = "20260823T120000Z-deadbeef"
PROJECT_ID = "project-demo1"
BUCKET = "recovery-demo1"
OPERATION = f"projects/{PROJECT_ID}/databases/(default)/operations/export-1"


def _manifest(**overrides):
    root = backup_root_uri(BUCKET, BACKUP_ID)
    values = {
        "format": BACKUP_FORMAT,
        "schema_version": 3,
        "status": "complete",
        "backup_id": BACKUP_ID,
        "root_uri": root,
        "project_id": PROJECT_ID,
        "application_version": "0.3.0",
        "source_database_id": "(default)",
        "database_mode": "datastore-mode",
        "database_location": "nam5",
        "operation_name": OPERATION,
        "export_output_prefix": f"{root}/datastore/export-1",
        "export_metadata_uri": f"{root}/datastore/export-1/export-1.overall_export_metadata",
        "export_started_at": "2026-08-23T12:00:00Z",
        "export_completed_at": "2026-08-23T12:01:00Z",
        "snapshot_time": "2026-08-23T12:00:00Z",
        "consistency": "point-in-time",
        "inventory_uri": f"{root}/inventory.json",
        "inventory_sha256": "a" * 64,
        "entity_count": 0,
        "assets_uri": f"{root}/assets.json",
        "assets_sha256": "b" * 64,
        "asset_count": 0,
        "tool_version": "0.3.0",
    }
    values.update(overrides)
    return BackupManifest(**values)


def _record(semantic_type="page", portable_id="abc123def456", properties=None, *, children=None):
    roles = {
        "user": "users",
        "page": "instances",
        "task": "instances",
        "message_conversation": "message_conversations",
    }
    record = {
        "identity": {
            "type": semantic_type,
            "id": portable_id,
            "namespace": "",
            "kind_role": roles.get(semantic_type, "instances"),
            "ancestors": [],
        },
        "exclude_from_indexes": [],
        "properties": properties or {"name": "Archived page"},
    }
    if children:
        record["children"] = children
    return record


class _Blob:
    def __init__(self, name, payload=b"", *, generation=1, exists=True, content_type=None):
        self.name = name
        self.payload = payload
        self.generation = generation
        self._exists = exists
        self.size = len(payload)
        self.content_type = content_type
        self.deleted = []

    def exists(self):
        return self._exists

    def reload(self):
        if not self._exists:
            raise FileNotFoundError(self.name)

    def download_as_text(self, encoding="utf-8"):
        return self.payload.decode(encoding)

    def download_as_bytes(self, start=0, end=None, **_kwargs):
        if not self._exists:
            raise FileNotFoundError(self.name)
        return self.payload[start : None if end is None else end + 1]

    def upload_from_string(self, value, **_kwargs):
        if self._exists:
            raise AssertionError("create-only upload attempted to overwrite")
        self.payload = value.encode() if isinstance(value, str) else value
        self.size = len(self.payload)
        self._exists = True

    def delete(self, **kwargs):
        self.deleted.append(kwargs)
        self._exists = False


class _Bucket:
    def __init__(self, blobs=()):
        self.blobs = {blob.name: blob for blob in blobs}

    def blob(self, name, generation=None):
        blob = self.blobs.setdefault(name, _Blob(name, exists=False))
        if generation is not None and str(blob.generation) != str(generation):
            return _Blob(name, exists=False, generation=generation)
        return blob

    def list_blobs(self, prefix):
        return [blob for name, blob in sorted(self.blobs.items()) if name.startswith(prefix) and blob._exists]

    def copy_blob(self, source, destination_bucket, destination_name, **_kwargs):
        copied = _Blob(
            destination_name,
            source.payload,
            generation=10,
            content_type=source.content_type,
        )
        destination_bucket.blobs[destination_name] = copied
        return copied


# @matrix data-lifecycle : identifier-validation path-containment
def test_identifiers_and_storage_paths_are_strict():
    assert validate_backup_id(BACKUP_ID) == BACKUP_ID
    assert validate_database_id("archive-db") == "archive-db"
    assert parse_gs_uri(f"gs://{BUCKET}/safe/object") == (BUCKET, "safe/object")
    assert require_uri_below(
        f"{backup_root_uri(BUCKET, BACKUP_ID)}/datastore/object",
        backup_root_uri(BUCKET, BACKUP_ID),
    ).endswith("/datastore/object")
    for invalid in ("validate", "20260823T120000Z-DEADBEEF", "../backup"):
        with pytest.raises(DataLifecycleError):
            validate_backup_id(invalid)
    for invalid in ("abc", "Uppercase", "1234", "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(DataLifecycleError):
            validate_database_id(invalid, allow_default=False)
    for invalid in ("https://bucket/object", f"gs://{BUCKET}/../object", f"gs://{BUCKET}"):
        with pytest.raises(DataLifecycleError):
            parse_gs_uri(invalid)


# @matrix data-lifecycle : manifest path-containment
def test_manifest_validation_rejects_foreign_or_uncontained_artifacts():
    valid = _manifest().as_dict()
    assert BackupManifest.from_dict(
        valid,
        expected_project=PROJECT_ID,
        expected_backup_id=BACKUP_ID,
        expected_bucket=BUCKET,
    ).backup_id == BACKUP_ID
    direct_output = {
        **valid,
        "export_output_prefix": f"{valid['root_uri']}/datastore",
        "export_metadata_uri": (
            f"{valid['root_uri']}/datastore/datastore.overall_export_metadata"
        ),
    }
    assert BackupManifest.from_dict(
        direct_output,
        expected_project=PROJECT_ID,
        expected_backup_id=BACKUP_ID,
        expected_bucket=BUCKET,
    ).export_output_prefix.endswith("/datastore")
    with pytest.raises(DataLifecycleError, match="different Google Cloud project"):
        BackupManifest.from_dict(valid, expected_project="another-proj1")
    escaped = {**valid, "export_metadata_uri": f"gs://{BUCKET}/elsewhere/file.overall_export_metadata"}
    with pytest.raises(DataLifecycleError, match="outside"):
        BackupManifest.from_dict(escaped, expected_bucket=BUCKET)
    with pytest.raises(DataLifecycleError, match="unsupported fields"):
        BackupManifest.from_dict({**valid, "credential": "secret"})


# @pair data-lifecycle:provider-context
def test_provider_context_always_uses_default_database_and_recovery_bucket():
    settings = SimpleNamespace(
        APP={
            "GOOGLE_CLOUD_PROJECT": PROJECT_ID,
            "DATASTORE_DATABASE_ID": "archive-db",
            "VERSION": "0.3.0",
            "GIBBERISH": "stable-secret",
            "PREFIX": "test-",
        },
        GCLOUD_CONFIG={"PROJECT": "wrong-project"},
    )
    context = ProviderContext.from_settings(settings, gcloud=lambda *_args, **_kwargs: {})
    assert context.project_id == PROJECT_ID
    assert context.database_id == "(default)"
    assert context.recovery_bucket.startswith("test-recovery-")


# @matrix data-lifecycle migrations : read-only asset-generation prerequisite
def test_lifecycle_requires_completed_asset_generation_migration(monkeypatch):
    from config import SETTINGS
    from config.data_migrations import ASSET_GENERATION_MIGRATION_ID

    records = {}

    class Client:
        def key(self, kind, identifier):
            return kind, identifier

        def get(self, key):
            return records.get(key)

    client = Client()
    client_arguments = {}

    def client_factory(**kwargs):
        client_arguments.update(kwargs)
        return client

    context = ProviderContext(
        PROJECT_ID,
        "(default)",
        BUCKET,
        "0.3.0",
        datastore_client_factory=client_factory,
    )
    monkeypatch.setattr(SETTINGS, "APP", {"PREFIX": "test-"})
    key = (
        "test-site",
        f"data-migration:{ASSET_GENERATION_MIGRATION_ID}",
    )

    with pytest.raises(DataLifecycleError, match="select Apply Updates"):
        context.require_asset_generation_migration()
    assert client_arguments == {"project": PROJECT_ID, "database": ""}

    records[key] = {
        "ledger_schema": 1,
        "migration_id": ASSET_GENERATION_MIGRATION_ID,
        "state": "complete",
    }
    assert context.require_asset_generation_migration() == records[key]


# @matrix data-lifecycle : cache-invalidation framework-neutral restore
def test_restore_cache_invalidation_uses_setup_redis_connection(monkeypatch):
    from config import SETTINGS

    observed = {}

    class RedisClient:
        def flushdb(self):
            observed["flushed"] = True

    monkeypatch.setattr(
        SETTINGS,
        "APP",
        {
            "REDIS_HOST": "redis.example.test",
            "REDIS_PORT": 16379,
            "REDIS_PASSWORD": "test-password",
            "REDIS_TLS": False,
        },
    )

    def redis_client(**options):
        observed["options"] = options
        return RedisClient()

    monkeypatch.setattr("redis.Redis", redis_client)
    context = ProviderContext(PROJECT_ID, "(default)", BUCKET, "0.3.0")

    context.invalidate_cache()

    assert observed["flushed"] is True
    assert observed["options"] == {
        "host": "redis.example.test",
        "port": 16379,
        "password": "test-password",
        "socket_connect_timeout": 10,
        "socket_timeout": 30,
    }


# @matrix data-lifecycle : immutable-restore-record provider-pagination queue-purge-audit
def test_queue_snapshot_preserves_full_task_definitions():
    class TasksClient:
        def __init__(self):
            self.request = None
            self.calls = 0

        def queue_path(self, project, location, queue):
            return f"projects/{project}/locations/{location}/queues/{queue}"

        def list_tasks(self, *, request):
            self.request = request
            self.calls += 1
            parent = request["parent"]
            return [
                {
                    "name": f"{parent}/tasks/task-b",
                    "scheduleTime": "2026-08-24T12:00:00Z",
                    "httpRequest": {
                        "url": "https://example.test/process/jobs",
                        "body": "eyJqb2Jfa2V5IjoiYWIifQ==",
                    },
                },
                {
                    "name": f"{parent}/tasks/task-a",
                    "httpRequest": {
                        "url": "https://example.test/process/uncomplete-task",
                        "body": "eyJrZXkiOiJhYSJ9",
                    },
                },
            ]

    bucket = _Bucket()
    client = TasksClient()
    context = ProviderContext(
        PROJECT_ID,
        "(default)",
        BUCKET,
        "0.3.0",
        storage_client=SimpleNamespace(bucket=lambda _name: bucket),
        cloud_tasks_client=client,
    )
    plan = {
        "restore_id": "20260823-deadbeef",
        "queue": "lagniappe-tasks",
        "queue_location": "us-central1",
    }
    snapshot = restore_module.capture_queue_snapshot(
        context,
        plan,
        captured_at=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
    )

    assert client.request["response_view"] == 2
    assert client.request["page_size"] == 1000
    payload = json.loads(bucket.blob(snapshot["object_name"]).download_as_text())
    assert snapshot["task_count"] == 2
    assert snapshot["sha256"]
    assert [task["name"].rsplit("/", 1)[-1] for task in payload["tasks"]] == [
        "task-a",
        "task-b",
    ]
    assert payload["tasks"][1]["httpRequest"]["body"] == "eyJqb2Jfa2V5IjoiYWIifQ=="
    resumed = restore_module.capture_queue_snapshot(
        context,
        plan,
        captured_at=datetime(2026, 8, 23, 12, 30, tzinfo=timezone.utc),
    )
    assert resumed == snapshot
    assert client.calls == 1


# @pair data-lifecycle:inflight-task-settlement
def test_cutover_waits_for_dispatched_task_attempts_to_settle():
    observations = iter(
        [
            [{"name": "task-a", "dispatchCount": 1, "responseCount": 0}],
            [{"name": "task-a", "dispatchCount": 1, "responseCount": 1}],
        ]
    )
    delays = []
    context = ProviderContext(
        PROJECT_ID,
        "(default)",
        BUCKET,
        "0.3.0",
        sleep=delays.append,
    )
    context.list_queue_tasks = lambda _queue, _location: next(observations)

    context.wait_for_no_inflight_tasks("lagniappe-tasks", "us-central1")

    assert delays == [1]


# @matrix data-lifecycle : failure-propagation operation-polling
def test_operation_polling_resumes_and_reports_provider_failure(monkeypatch):
    states = iter([{"done": False}, {"done": True, "metadata": {"common": {"state": "SUCCESSFUL"}}}])
    context = ProviderContext(PROJECT_ID, "(default)", BUCKET, "0.3", sleep=lambda _delay: None)
    monkeypatch.setattr(context, "operation", lambda *_args, **_kwargs: next(states))
    assert context.wait_for_operation(OPERATION)["done"] is True
    monkeypatch.setattr(context, "operation", lambda *_args, **_kwargs: {"done": True, "error": {"message": "denied"}})
    with pytest.raises(DataLifecycleError, match="denied"):
        context.wait_for_operation(OPERATION)


# @matrix data-lifecycle : database-create operation-provider-contract
def test_database_creation_uses_current_operation_gcloud_contract():
    calls = []

    def gcloud(arguments, *, timeout):
        calls.append((arguments, timeout))
        return {
            "name": f"projects/{PROJECT_ID}/databases/scratch-db/operations/create-1",
        }

    context = ProviderContext(
        PROJECT_ID,
        "(default)",
        BUCKET,
        "0.3.0",
        gcloud=gcloud,
    )

    result = context.create_database(
        "scratch-db", "nam5", delete_protection=False
    )

    arguments, timeout = calls[0]
    assert result["name"].endswith("/operations/create-1")
    assert arguments[:3] == ["firestore", "databases", "create"]
    assert "--no-delete-protection" in arguments
    assert "--async" not in arguments
    assert timeout == 120


# @matrix data-lifecycle : private-state resume
def test_secure_directory_and_checkpoint_exact_resume(tmp_path):
    private = secure_directory(tmp_path / "private")
    if os.name != "nt":
        assert private.stat().st_mode & 0o077 == 0
    checkpoint = LifecycleCheckpoint(PROJECT_ID, ["archive"], state_root=private)
    checkpoint.start(BACKUP_ID, backup_id=BACKUP_ID)
    checkpoint.update("export-started", provider_operation=OPERATION)
    resumed = LifecycleCheckpoint(PROJECT_ID, ["archive"], state_root=private)
    assert resumed.load()["provider_operation"] == OPERATION
    different = LifecycleCheckpoint(PROJECT_ID, ["archive", BACKUP_ID], state_root=private)
    assert different.load() is None


# @matrix data-lifecycle : resume sqlite-staging
def test_archive_state_is_private_transactional_and_resumable(tmp_path):
    path = tmp_path / "private" / "archive.sqlite3"
    with ArchiveState(path) as state:
        state.set_metadata("cursor", {"page": 2})
        with pytest.raises(RuntimeError):
            with state.transaction() as connection:
                connection.execute("INSERT INTO warnings VALUES('x', 'test', '{}')")
                raise RuntimeError("rollback")
        assert state.connection.execute("SELECT COUNT(*) FROM warnings").fetchone()[0] == 0
    with ArchiveState(path) as resumed:
        assert resumed.get_metadata("cursor") == {"page": 2}
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def _backup_context():
    root_name = f"{BACKUP_ROOT_PREFIX}/{BACKUP_ID}/datastore"
    metadata = _Blob(f"{root_name}/datastore.overall_export_metadata", b"metadata")
    data = _Blob(f"{root_name}/all_namespaces/all_kinds/output-0", b"data")
    manifest = _Blob(f"{BACKUP_ROOT_PREFIX}/{BACKUP_ID}/manifest.json", exists=False)
    bucket = _Bucket([metadata, data, manifest])
    context = SimpleNamespace(
        project_id=PROJECT_ID,
        database_id="(default)",
        recovery_bucket=BUCKET,
        application_version="0.3.0",
        bucket=bucket,
        starts=0,
        expected_snapshot=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        require_asset_generation_migration=lambda database: database == "(default)",
    )

    def start_export(output, *, snapshot_time):
        assert output == f"gs://{BUCKET}/{BACKUP_ROOT_PREFIX}/{BACKUP_ID}/datastore"
        assert snapshot_time == context.expected_snapshot
        context.starts += 1
        return OPERATION, {"name": OPERATION}

    context.start_export = start_export
    context.wait_for_operation = lambda _name: {
        "done": True,
        "metadata": {
            "common": {
                "state": "SUCCESSFUL",
                "startTime": "2026-08-23T12:00:00Z",
                "endTime": "2026-08-23T12:01:00Z",
            },
            "outputUrl": f"gs://{BUCKET}/{metadata.name}",
        },
    }
    context.list_objects = lambda prefix: bucket.list_blobs(prefix)
    context.database = lambda: {"type": "DATASTORE_MODE", "locationId": "nam5"}
    context.datastore_client = lambda _database: _ScanClient(
        {
            ("", "__namespace__"): [
                _entity(Key("__namespace__", 1, project=PROJECT_ID), value=1)
            ],
            ("", "__kind__"): [],
        }
    )

    def upload(name, payload):
        blob = bucket.blob(name)
        blob.upload_from_string(json.dumps(payload))
        return blob

    context.upload_json_create_only = upload
    context.load_json_object = lambda name: (json.loads(bucket.blob(name).download_as_text()), bucket.blob(name))
    return context


# @matrix data-lifecycle : backup manifest-last resume
def test_backup_resumes_provider_operation_and_publishes_manifest_last(tmp_path):
    context = _backup_context()
    checkpoint = LifecycleCheckpoint(PROJECT_ID, ["backup", "create"], state_root=tmp_path)
    completed_wait = context.wait_for_operation
    interrupted = False

    def interrupt_once(operation):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        return completed_wait(operation)

    context.wait_for_operation = interrupt_once
    with pytest.raises(KeyboardInterrupt):
        create_backup(
            context,
            backup_id=BACKUP_ID,
            checkpoint=checkpoint,
            snapshot_time=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )
    assert context.starts == 1
    assert checkpoint.load()["provider_operation"] == OPERATION
    manifest = create_backup(context, backup_id=BACKUP_ID, checkpoint=checkpoint)
    assert manifest.backup_id == BACKUP_ID
    assert context.starts == 1
    assert checkpoint.load() is None
    fresh = LifecycleCheckpoint(
        PROJECT_ID,
        ["backup", "create", "repeat"],
        state_root=tmp_path / "repeat-state",
    )
    assert create_backup(context, backup_id=BACKUP_ID, checkpoint=fresh) == manifest
    assert context.starts == 1
    assert fresh.load() is None


# @matrix data-lifecycle : backup point-in-time framework-neutral
def test_backup_selects_completed_whole_minute_without_runtime_action(tmp_path):
    context = _backup_context()
    context.expected_snapshot = datetime(2026, 8, 23, 11, 59, tzinfo=timezone.utc)
    context.now = lambda: datetime(
        2026, 8, 23, 12, 0, 20, tzinfo=timezone.utc
    )
    checkpoint = LifecycleCheckpoint(
        PROJECT_ID,
        ["backup", "create", "live"],
        state_root=tmp_path / "live-state",
    )

    manifest = create_backup(context, backup_id=BACKUP_ID, checkpoint=checkpoint)

    assert manifest.snapshot_time == "2026-08-23T11:59:00Z"


# @matrix data-lifecycle : backup-list manifest
def test_backup_listing_ignores_invalid_incomplete_and_foreign_objects():
    valid = _manifest()
    blobs = [
        _Blob(f"{BACKUP_ROOT_PREFIX}/{BACKUP_ID}/manifest.json", json.dumps(valid.as_dict()).encode()),
        _Blob(f"{BACKUP_ROOT_PREFIX}/incomplete/datastore/chunk", b"x"),
        _Blob(f"{BACKUP_ROOT_PREFIX}/bad-id/manifest.json", b"{}"),
    ]
    context = SimpleNamespace(
        project_id=PROJECT_ID,
        recovery_bucket=BUCKET,
        list_objects=lambda _prefix: blobs,
    )
    assert list_backups(context) == [valid]


# @matrix data-lifecycle : backup-delete confirmation path-containment
def test_backup_delete_requires_typed_confirmation_and_manifest_first():
    manifest_blob = _Blob(
        f"{BACKUP_ROOT_PREFIX}/{BACKUP_ID}/manifest.json",
        json.dumps(_manifest().as_dict()).encode(),
        generation=7,
    )
    data_blob = _Blob(f"{BACKUP_ROOT_PREFIX}/{BACKUP_ID}/datastore/chunk", b"x")
    context = SimpleNamespace(
        project_id=PROJECT_ID,
        recovery_bucket=BUCKET,
        list_objects=lambda _prefix: [data_blob, manifest_blob],
    )
    with pytest.raises(DataLifecycleError, match="cancelled"):
        delete_backup(BACKUP_ID, context, confirm=lambda _prompt: "no")
    assert delete_backup(
        BACKUP_ID,
        context,
        confirm=lambda _prompt: f"DELETE {PROJECT_ID} {BACKUP_ID}",
    )
    assert manifest_blob.deleted == [{"if_generation_match": 7}]
    assert data_blob.deleted == [{}]


# @matrix data-lifecycle : named-scratch-database automatic-backup-preparation
def test_automatic_backup_preparation_uses_scratch_then_v3(monkeypatch, tmp_path):
    native = f"projects/{PROJECT_ID}/locations/nam5/backups/native-1"
    calls = []
    checkpoint = LifecycleCheckpoint(
        PROJECT_ID,
        ["backup", "prepare", "native-1"],
        state_root=tmp_path / "native-state",
    )
    monkeypatch.setattr(
        backup_module,
        "LifecycleCheckpoint",
        lambda *_args, **_kwargs: checkpoint,
    )
    monkeypatch.setattr(backup_module, "new_backup_id", lambda: BACKUP_ID)
    manifest = _manifest()

    def create_recovery_set(context, **kwargs):
        calls.append(("create-backup", kwargs))
        return manifest

    monkeypatch.setattr(backup_module, "create_backup", create_recovery_set)

    class Context:
        project_id = PROJECT_ID

        def json_command(self, arguments):
            if arguments == ["firestore", "backups", "list"]:
                return [{"name": native}]
            assert arguments[:3] == ["firestore", "backups", "describe"]
            assert "--backup=native-1" in arguments
            assert "--location=nam5" in arguments
            return {
                "state": "READY",
                "database": f"projects/{PROJECT_ID}/databases/(default)",
                "snapshotTime": "2026-08-23T12:00:00Z",
            }

        def start_native_backup_restore(self, source, destination):
            calls.append(("restore", source, destination))
            return OPERATION, {"name": OPERATION}

        def wait_for_operation(self, operation, *, database_id):
            calls.append(("wait", operation, database_id))

        def disable_database_delete_protection(self, database_id):
            calls.append(("unprotect", database_id))

        def delete_database(self, database_id):
            calls.append(("delete", database_id))

    result = backup_module.prepare_automatic_backup("native-1", context=Context())

    scratch = calls[0][2]
    assert result == manifest
    assert calls[0] == ("restore", native, scratch)
    assert calls[1] == ("wait", OPERATION, scratch)
    assert calls[2][0] == "create-backup"
    assert calls[2][1]["source_database_id"] == scratch
    assert calls[2][1]["point_in_time_read"] is False
    assert calls[-2:] == [("unprotect", scratch), ("delete", scratch)]
    assert not checkpoint.path.exists()


# @matrix portable-json : path-safety reference-escaping
def test_portable_names_and_reference_strings_are_lossless():
    for value in ("simple", "UPPER / café", "ref:literal"):
        assert unportable_name(portable_name(value)) == value
    reference = PortableReference("page", "abc123", "Owner Space")
    encoded_reference = reference_string(reference)
    assert encoded_reference.startswith("ref:")
    assert parse_reference_string(encoded_reference) == reference
    codec = ValueCodec(string_normalizer=lambda value, _path: reference if value == "source-key" else value)
    encoded = codec.encode({"source-key": "source-key", "literal": "ref:page:abc123"})
    assert "ref:" in next(key for key in encoded if key.startswith("ref:"))
    assert encoded["literal"] == "literal:ref:page:abc123"


# @matrix portable-json : canonical-encoding round-trip value-codec
def test_value_codec_round_trips_every_supported_value():
    key = Key("users", "one", project=PROJECT_ID)
    nested = Entity(key=key, exclude_from_indexes=("secret",))
    nested.update({"value": 1})
    codec = ValueCodec(reference_resolver=lambda _key: PortableReference("user", "userhash"))
    value = {
        "none": None,
        "bool": True,
        "integer": 1,
        "float": 1.5,
        "datetime": datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        "date": date(2026, 8, 23),
        "bytes": b"\x00archive",
        "point": GeoPoint(1.25, -2.5),
        "key": key,
        "entity": nested,
        "missing": MissingReference("file", "f" * 64, "missing-1"),
        "list": ["literal:already", "ref:literal"],
    }
    encoded = codec.encode(value)
    decoded = ValueCodec().decode(encoded)
    assert codec.encode(decoded) == encoded
    assert isinstance(decoded["entity"], DecodedEntity)
    with pytest.raises(DataLifecycleError, match="Non-string map key"):
        codec.encode({1: "invalid"})


# @matrix portable-json : deterministic-order entity-envelope sharding
def test_shard_writer_enforces_count_bytes_and_ordering(tmp_path, monkeypatch):
    from installer.data_lifecycle import portable

    monkeypatch.setattr(portable, "MAX_SHARD_RECORDS", 2)
    records = [_record(portable_id=f"abc123def45{number}") for number in range(3)]
    descriptors = ShardWriter(tmp_path).write_type("page", records)
    assert [item["count"] for item in descriptors] == [2, 1]
    assert all(item["bytes"] == len((tmp_path / item["path"]).read_bytes()) for item in descriptors)
    with pytest.raises(DataLifecycleError, match="strictly identity-sorted"):
        ShardWriter(tmp_path / "bad").write_type("page", reversed(records))


# @matrix portable-json : import-planner two-pass-resolution
def test_import_planner_is_source_independent_and_resolves_two_pass_references(tmp_path):
    user = _record("user", "userhash0001", {"name": "Owner"})
    user_reference = PortableReference("user", "userhash0001")
    page = _record(
        "page",
        "pagehash0001",
        {
            "owner": user_reference.as_tag(),
            "by_owner": {reference_string(user_reference): True},
            "literal": {"literal:ref:user:userhash0001": True},
        },
    )
    planned = ImportPlanner(target_prefix="test-").plan([user, page])
    assert planned["recipe"] == "lagniappe-target-key/v1"
    assert planned["identity_count"] == 2
    assert PROJECT_ID not in canonical_json(planned).decode()
    missing = _record("page", "pagehash0002", {"owner": PortableReference("user", "missinghash1").as_tag()})
    with pytest.raises(DataLifecycleError, match="unresolved"):
        ImportPlanner().plan([missing])
    bundle = tmp_path / "bundle"
    _archive_bundle(bundle)
    assert ImportPlanner(target_prefix="test-").plan_bundle(bundle)["identity_count"] == 1


class _PageIterator:
    def __init__(self, rows):
        self.pages = iter([rows] if rows else [])
        self.next_page_token = None


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def keys_only(self):
        return self

    def fetch(self, **_kwargs):
        return _PageIterator(self.rows)


class _ScanClient:
    def __init__(self, rows):
        self.rows = rows

    def query(self, kind, namespace=None):
        return _Query(self.rows.get((namespace or "", kind), []))


# @matrix data-lifecycle disaster-recovery : asset-generation inventory point-in-time
def test_recovery_inventory_uses_one_read_time_and_requires_asset_generations():
    snapshot = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
    page = _entity(
        Key("instances", "page", project=PROJECT_ID),
        type="page",
        assets={
            "document": {
                "path": "documents/page.html",
                "visibility": "private",
                "generation": "7",
            }
        },
    )
    rows = {
        ("", "__namespace__"): [_entity(Key("__namespace__", 1, project=PROJECT_ID))],
        ("", "__kind__"): [_entity(Key("__kind__", "instances", project=PROJECT_ID))],
        ("", "instances"): [page],
    }
    inventory, assets = inventory_database(_ScanClient(rows), snapshot_time=snapshot)
    assert inventory["snapshot_time"] == "2026-08-24T12:00:00Z"
    assert inventory["entity_count"] == 1
    assert assets[0]["generation"] == "7"

    page["assets"]["document"].pop("generation")
    with pytest.raises(DataLifecycleError, match="generation is missing"):
        inventory_database(_ScanClient(rows), snapshot_time=snapshot)


# @matrix data-lifecycle disaster-recovery file : asset-generation uploaded-file
def test_recovery_inventory_includes_uploaded_file_asset_generations():
    snapshot = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
    uploaded_file = _entity(
        Key("instances", "file", project=PROJECT_ID),
        type="file",
        filename="notes.txt",
        assets=json.dumps(
            {
                "file": {
                    "type": "file",
                    "path": "files/notes.txt",
                    "generation": "11",
                    "size": 42,
                },
                "text": {
                    "type": "text",
                    "path": "files/notes_text.txt",
                    "generation": "12",
                },
            }
        ),
    )
    rows = {
        ("", "__namespace__"): [_entity(Key("__namespace__", 1, project=PROJECT_ID))],
        ("", "__kind__"): [_entity(Key("__kind__", "instances", project=PROJECT_ID))],
        ("", "instances"): [uploaded_file],
    }

    _inventory, assets = inventory_database(_ScanClient(rows), snapshot_time=snapshot)

    assert [(asset["path"], asset["generation"]) for asset in assets] == [
        ("files/notes.txt", "11"),
        ("files/notes_text.txt", "12"),
    ]
    assert all(asset["owners"][0]["name"] in {"file", "text"} for asset in assets)


# @matrix data-lifecycle storage : asset-generation checksum immutable-copy
def test_capture_recovery_assets_copies_exact_generation_create_only():
    source = _Bucket([_Blob("documents/page.html", b"hello", generation=7)])
    recovery = _Bucket()
    context = SimpleNamespace(bucket=recovery)
    assets = [
        {
            "role": "private",
            "path": "documents/page.html",
            "generation": "7",
            "owners": [{"key": "owner", "name": "document"}],
        }
    ]
    captured = capture_assets(
        context,
        BACKUP_ID,
        assets,
        {"private": source},
    )
    assert captured[0]["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert captured[0]["recovery_generation"] == "10"
    recovery_blob = recovery.blob(captured[0]["recovery_object"])
    assert recovery_blob.payload == b"hello"
    recovery_blob.payload = b"conflict"
    recovery_blob.size = len(recovery_blob.payload)
    with pytest.raises(DataLifecycleError, match="copy conflicts"):
        capture_assets(context, BACKUP_ID, assets, {"private": source})


# @matrix data-lifecycle disaster-recovery : queue-reconciliation scheduled-uncomplete
def test_restore_requeues_only_durable_scheduled_uncompletion():
    task = _entity(
        Key("instances", "task", project=PROJECT_ID),
        type="task",
        completed=True,
        active=True,
        schedule={"frequency": "weekly"},
    )

    class Client(_ScanClient):
        def __init__(self):
            super().__init__({("", "instances"): [task]})
            self.written = []

        def put_multi(self, entities):
            self.written.extend(entities)

    client = Client()
    queued = []
    context = SimpleNamespace(
        datastore_client=lambda database: client,
        create_scheduled_uncomplete_task=lambda *args, **kwargs: queued.append(
            (args, kwargs)
        ),
    )
    result = restore_in_place.reconcile_scheduled_uncomplete_tasks(
        context,
        {
            "kind_prefix": "",
            "queue": "lagniappe-tasks",
            "queue_location": "us-central1",
            "app_url": "https://example.test",
            "runtime_service_account": f"runtime@{PROJECT_ID}.iam.gserviceaccount.com",
        },
        now=datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
    )
    assert result == {"queued": 1, "backfilled": 1}
    assert len(queued) == 1
    assert queued[0][1]["token"] == task["scheduled_uncomplete_token"]
    assert task["scheduled_uncomplete_at"] == datetime(
        2026, 8, 24, 12, tzinfo=timezone.utc
    )


# @matrix data-lifecycle disaster-recovery : asset-generation restore-assets
def test_restore_assets_rebinds_owner_to_new_generation(monkeypatch):
    from config import SETTINGS
    from config.storage import storage_bucket_names

    monkeypatch.setitem(SETTINGS.APP, "GIBBERISH", "restore-assets-test")
    owner_key = Key("instances", "page", project=PROJECT_ID)
    owner = _entity(
        owner_key,
        type="page",
        assets={
            "document": {
                "path": "documents/page.html",
                "generation": "7",
            }
        },
    )
    recovery_name = "lagniappe-data/v3/recovery-sets/source/assets/object"
    recovery = _Bucket([_Blob(recovery_name, b"hello", generation=9)])
    target = _Bucket()
    catalog_name = f"{BACKUP_ROOT_PREFIX}/{BACKUP_ID}/assets.json"
    catalog = {
        "asset_count": 1,
        "assets": [
            {
                "role": "private",
                "path": "documents/page.html",
                "generation": "7",
                "size": 5,
                "sha256": hashlib.sha256(b"hello").hexdigest(),
                "recovery_object": recovery_name,
                "recovery_generation": "9",
                "owners": [
                    {"key": encode_urlsafe_key(owner_key), "name": "document"}
                ],
            }
        ],
    }
    recovery.blob(catalog_name).upload_from_string(json.dumps(catalog))

    class Client:
        def get(self, key):
            assert key == owner_key
            return owner

        def put_multi(self, entities):
            assert entities == [owner]

    private_name = storage_bucket_names(SETTINGS.APP)["private"]
    context = SimpleNamespace(
        recovery_bucket=BUCKET,
        bucket=recovery,
        storage=SimpleNamespace(
            bucket=lambda name: target if name == private_name else _Bucket()
        ),
        load_json_object=lambda name: (catalog, recovery.blob(name)),
        datastore_client=lambda database: Client(),
    )
    result = restore_in_place.restore_generation_bound_assets(
        context,
        {"assets_uri": f"gs://{BUCKET}/{catalog_name}"},
    )
    assert result == {"assets": 1, "owners": 1}
    assert owner["assets"]["document"]["generation"] == "10"
    assert target.blob("documents/page.html").payload == b"hello"


def _entity(key, **values):
    row = Entity(key=key)
    row.update(values)
    return row


# @matrix portable-json : bounded-scan entity-envelope entity-selection key-replacement portable-identity typed-references
def test_staging_selects_durable_types_and_builds_typed_identity_map(tmp_path):
    user = _entity(Key("users", "owner", project=PROJECT_ID, database="scratch-db"), type="user", hash="userhash0001")
    excluded = _entity(Key("activity", "notice", project=PROJECT_ID, database="scratch-db"), type="notification")
    unknown = _entity(Key("future", "one", project=PROJECT_ID, database="scratch-db"), type="future")
    meta_project = PROJECT_ID
    kinds = ["users", "activity", "future"]
    rows = {
        ("", "__namespace__"): [_entity(Key("__namespace__", 1, project=meta_project), value=1)],
        ("", "__kind__"): [_entity(Key("__kind__", kind, project=meta_project), value=kind) for kind in kinds],
        ("", "users"): [user],
        ("", "activity"): [excluded],
        ("", "future"): [unknown],
    }
    with ArchiveState(tmp_path / "stage.sqlite3") as state:
        counts = stage_database(
            _ScanClient(rows),
            state,
            source_project=PROJECT_ID,
            source_database="source-db",
        )
        assert counts["included"] == 1
        assert counts["unknown-kind:future"] == 1
        assert counts["excluded-type:notification"] == 1
        assert portable_records(state)[0]["identity"]["type"] == "user"


# @matrix portable-json : entity-envelope key-replacement typed-references
def test_staging_replaces_source_and_scratch_keys_recursively(tmp_path):
    scratch_user = Key("users", "owner", project=PROJECT_ID, database="scratch-db")
    source_user = Key("users", "owner", project=PROJECT_ID, database="source-db")
    scratch_page = Key("instances", "page", project=PROJECT_ID, database="scratch-db")
    user = _entity(scratch_user, type="user", hash="userhash0001")
    page = _entity(
        scratch_page,
        type="page",
        hash="pagehash0001",
        owner=scratch_user,
        owner_string=encode_urlsafe_key(source_user),
        json_contract=json.dumps(
            {
                encode_urlsafe_key(source_user): "ref:literal",
                "owner": encode_urlsafe_key(source_user),
            }
        ),
    )
    kinds = ["users", "instances"]
    rows = {
        ("", "__namespace__"): [_entity(Key("__namespace__", 1, project=PROJECT_ID), value=1)],
        ("", "__kind__"): [_entity(Key("__kind__", kind, project=PROJECT_ID), value=kind) for kind in kinds],
        ("", "users"): [user],
        ("", "instances"): [page],
    }
    with ArchiveState(tmp_path / "stage.sqlite3") as state:
        stage_database(_ScanClient(rows), state, source_project=PROJECT_ID, source_database="source-db")
        page_record = next(item for item in portable_records(state) if item["identity"]["type"] == "page")
        assert page_record["properties"]["owner"] == {"$ref": {"type": "user", "id": "userhash0001"}}
        assert page_record["properties"]["owner_string"] == {"$ref": {"type": "user", "id": "userhash0001"}}
        contract = json.loads(page_record["properties"]["json_contract"])
        assert contract == {
            "owner": "ref:user:userhash0001",
            "ref:user:userhash0001": "literal:ref:literal",
        }
        ImportPlanner().plan(portable_records(state))
        payload = canonical_json(page_record).decode()
        assert encode_urlsafe_key(scratch_user) not in payload
        assert encode_urlsafe_key(source_user) not in payload


# @matrix portable-json : import-planner natural-identity owner-scoped-children
def test_history_and_messages_are_nested_and_replanned_under_their_owners(tmp_path):
    partition = {"project": PROJECT_ID, "database": "scratch-db"}
    actor_key = Key("users", "actor", **partition)
    recipient_key = Key("users", "recipient", **partition)
    task_key = Key("instances", "task", **partition)
    history_key = Key("instances", "task", "history", 17, **partition)
    conversation_key = Key("message_conversations", "source-thread", **partition)
    message_key = Key(
        "message_conversations", "source-thread", "messages", 4, **partition
    )
    rows = {
        ("", "__namespace__"): [
            _entity(Key("__namespace__", 1, project=PROJECT_ID), value=1)
        ],
        ("", "__kind__"): [
            _entity(Key("__kind__", kind, project=PROJECT_ID), value=kind)
            for kind in ("users", "instances", "history", "message_conversations", "messages")
        ],
        ("", "users"): [
            _entity(actor_key, type="user", hash="actorhash001"),
            _entity(recipient_key, type="user", hash="recipient001"),
        ],
        ("", "instances"): [
            _entity(task_key, type="task", hash="taskhash0001", name="Task")
        ],
        ("", "history"): [
            _entity(
                history_key,
                type="task_history",
                task=task_key,
                name="Completed task",
            )
        ],
        ("", "message_conversations"): [
            _entity(
                conversation_key,
                type="message_conversation",
                participants=[actor_key, recipient_key],
            )
        ],
        ("", "messages"): [
            _entity(
                message_key,
                type="message",
                conversation=conversation_key,
                sender=actor_key,
                recipient=recipient_key,
                operation_id="send-001",
                body="Hello",
            )
        ],
    }
    with ArchiveState(tmp_path / "nested.sqlite3") as state:
        stage_database(
            _ScanClient(rows),
            state,
            source_project=PROJECT_ID,
            source_database="source-db",
        )
        records = portable_records(state)

    task = next(record for record in records if record["identity"]["type"] == "task")
    conversation = next(
        record
        for record in records
        if record["identity"]["type"] == "message_conversation"
    )
    history = task["children"]["task_history"][0]
    message = conversation["children"]["message"][0]
    assert history["key"] == {"id": 17}
    assert message["key"] == {"id": 4}
    assert "hash" not in history["properties"]
    assert "hash" not in message["properties"]
    assert conversation["identity"]["id"].startswith("conversation-")

    plan = ImportPlanner(target_prefix="test-").plan(records)
    history_plan = next(
        row for row in plan["entities"] if row["identity"].get("type") == "task_history"
    )
    message_plan = next(
        row for row in plan["entities"] if row["identity"].get("type") == "message"
    )
    task_plan = next(
        row for row in plan["entities"] if row["identity"].get("type") == "task"
    )
    conversation_plan = next(
        row
        for row in plan["entities"]
        if row["identity"].get("type") == "message_conversation"
    )
    assert history_plan["target_key"].startswith(task_plan["target_key"] + "/")
    assert message_plan["target_key"].startswith(conversation_plan["target_key"] + "/")
    assert history_plan["target_key"].endswith("/test-history:id:17")
    assert plan["identity_count"] == 6
    payload = canonical_json(records).decode()
    assert "source-thread" not in payload
    assert "scratch-db" not in payload and "source-db" not in payload


class _AssetBucket:
    def __init__(self, payloads):
        self.payloads = payloads

    def blob(self, name):
        payload = self.payloads.get(name)
        return _Blob(name, payload or b"", generation=4, exists=payload is not None, content_type="application/octet-stream")


# @matrix portable-archive : assets generation-binding resume
def test_asset_collection_is_generation_bound_resumable_and_deduplicated(tmp_path):
    with ArchiveState(tmp_path / "assets.sqlite3") as state:
        owner = canonical_json(
            {"type": "file", "id": "filehash0001", "namespace": ""}
        ).decode()
        for logical_id, logical_name, source_path in (
            ("logical-1", "first.bin", "one"),
            ("logical-2", "second.bin", "two"),
            ("logical-3", "missing.bin", "missing"),
        ):
            state.connection.execute(
                "INSERT INTO assets(logical_id,state,owner,logical_name,asset_type,required,source_role,source_path) "
                "VALUES(?, 'pending', ?, ?, 'file', 0, 'private', ?)",
                (logical_id, owner, logical_name, source_path),
            )
        state.connection.commit()
        collector = AssetCollector(
            state,
            tmp_path / "bundle",
            {"private": _AssetBucket({"one": b"same bytes", "two": b"same bytes"})},
        )
        descriptors, warnings = collector.collect()
        available = [item for item in descriptors if item["status"] == "available"]
        assert len({item["path"] for item in available}) == 1
        assert all(item["generation"] == "4" for item in available)
        assert len(warnings) == 1
    with ArchiveState(tmp_path / "documents.sqlite3") as state:
        owner = canonical_json(
            {"type": "page", "id": "pagehash0001", "namespace": ""}
        ).decode()
        for logical_id, name, asset_type, source_path in (
            ("a" * 64, "document", "html", "source/document.html"),
            ("b" * 64, "photo", "image", "source/photo.png"),
        ):
            state.connection.execute(
                "INSERT INTO assets(logical_id,state,owner,logical_name,asset_type,required,source_role,source_path) "
                "VALUES(?, 'pending', ?, ?, ?, 1, 'private', ?)",
                (logical_id, owner, name, asset_type, source_path),
            )
        state.connection.commit()
        bundle = tmp_path / "document-bundle"
        collector = AssetCollector(
            state,
            bundle,
            {
                "private": _AssetBucket(
                    {
                        "source/document.html": b"<p><img src='source/photo.png'></p>",
                        "source/photo.png": b"image bytes",
                    }
                )
            },
        )
        descriptors, warnings = collector.collect()
        assert warnings == []
        document = next(item for item in descriptors if item["name"] == "document")
        canonical = (bundle / document["canonical_document"]).read_text()
        assert "source/photo.png" not in canonical
        assert "assets/sha256" in canonical


# @matrix portable-archive : html-sanitization no-network
def test_html_sanitizer_removes_active_and_remote_content():
    source = "<script>alert(1)</script><a href='https://example.com'>remote</a><a href='ref:page:abc123'>local</a><img src='javascript:alert(1)'>"
    sanitized = sanitize_stored_html(
        source,
        page_path="site/page/current/index.html",
        identities={("", "page", "abc123")},
    )
    assert "script" not in sanitized
    assert "https://" not in sanitized
    assert "javascript:" not in sanitized
    assert "../abc123/index.html" in sanitized


# @matrix portable-archive : navigation offline-html owner-content
def test_html_archive_renders_owner_sections_and_local_navigation(tmp_path):
    records = [
        _record("page", "pagehash0001", {"name": "Private page", "public": False}),
        _record(
            "message_conversation",
            "conversation-" + "a" * 64,
            {"name": "Private conversation"},
            children={
                "message": [
                    {
                        "key": {"id": 1},
                        "exclude_from_indexes": ["body"],
                        "properties": {"body": "Private message"},
                    }
                ]
            },
        ),
    ]
    result = OfflineHTMLBuilder(
        tmp_path,
        backup_id=BACKUP_ID,
        created_at="2026-08-23T12:00:00Z",
        consistency="eventually consistent",
    ).build(records)
    assert result["pages"] == 3
    index = (tmp_path / "site" / "index.html").read_text()
    search = (tmp_path / "site" / "search-index.js").read_text()
    conversation = (
        tmp_path
        / "site"
        / "message_conversation"
        / ("conversation-" + "a" * 64)
        / "index.html"
    ).read_text()
    assert "Pages (1)" in index and "Conversations (private) (1)" in index
    assert index.count("<script") == 1 and "addEventListener" in search
    assert "sensitive private content" in conversation
    assert "Messages (1)" in conversation and "Private message" in conversation
    assert "Archive home" in conversation


def _archive_bundle(root, *, records=None):
    root.mkdir(parents=True)
    backup = _manifest()
    records = list(records or [_record()])
    created = "2026-08-23T12:02:00Z"
    catalog, html_result = _write_bundle(
        root,
        backup=backup,
        records=records,
        assets=[],
        warnings=[],
        asset_window={"started_at": created, "completed_at": created, "consistency": "recovery-set-generations"},
        created_at=created,
    )
    manifest = _root_manifest(
        root,
        backup=backup,
        catalog=catalog,
        warnings=[],
        html_result=html_result,
        created_at=created,
    )
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    return manifest


# @matrix portable-archive : key-audit path-safety validation
def test_archive_validation_accepts_canonical_directory_and_zip(tmp_path):
    bundle = tmp_path / "bundle"
    manifest = _archive_bundle(bundle)
    assert validate_archive(bundle)["entities"] == 1
    output = tmp_path / "bundle.zip"
    archive_module._publish_zip(bundle, output, manifest)
    assert validate_archive(output)["archive_id"] == BACKUP_ID


# @matrix portable-archive : owner-scoped-children validation
def test_archive_validation_counts_children_without_separate_identity_pages(tmp_path):
    bundle = tmp_path / "nested-bundle"
    task = _record(
        "task",
        "taskhash0001",
        {"name": "Task"},
        children={
            "task_history": [
                {
                    "key": {"id": 17},
                    "exclude_from_indexes": [],
                    "properties": {"name": "Completed task"},
                }
            ]
        },
    )
    manifest = _archive_bundle(bundle, records=[task])
    assert manifest["counts"]["entities"] == 2
    assert manifest["counts"]["pages"] == 2
    assert validate_archive(bundle)["entities"] == 2
    task_page = (bundle / "site" / "task" / "taskhash0001" / "index.html").read_text()
    assert "Task history (1)" in task_page and "Completed task" in task_page
    assert not (bundle / "site" / "task_history").exists()


# @matrix portable-archive : key-audit path-safety validation
def test_archive_validation_rejects_traversal_extra_files_bad_checksums_and_keys(tmp_path):
    bundle = tmp_path / "bundle"
    manifest = _archive_bundle(bundle)
    (bundle / "extra.txt").write_text("extra")
    with pytest.raises(DataLifecycleError, match="inventory mismatch"):
        validate_archive(bundle)
    (bundle / "extra.txt").unlink()
    (bundle / "README.md").write_text("changed")
    with pytest.raises(DataLifecycleError, match="size mismatch|checksum mismatch"):
        validate_archive(bundle)
    token = encode_urlsafe_key(Key("users", "owner", project=PROJECT_ID))
    (bundle / "README.md").write_text(f"source {token}")
    descriptor = file_descriptor(bundle / "README.md", bundle)
    manifest["files"] = [descriptor if item["path"] == "README.md" else item for item in manifest["files"]]
    (bundle / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    with pytest.raises(DataLifecycleError, match="Datastore key token"):
        validate_archive(bundle)
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape", b"x")
        archive.writestr("manifest.json", b"{}")
    with pytest.raises(DataLifecycleError, match="Unsafe archive path"):
        validate_archive(unsafe)


# @matrix portable-archive : cleanup publication workflow
def test_archive_build_publishes_manifest_last_and_retains_failed_scratch_state(tmp_path, monkeypatch):
    real_checkpoint = LifecycleCheckpoint

    def checkpoint(project_id, command, output_target=None):
        return real_checkpoint(project_id, command, output_target=output_target, state_root=tmp_path / "state")

    monkeypatch.setattr(archive_module, "LifecycleCheckpoint", checkpoint)
    monkeypatch.setattr(archive_module, "load_backup", lambda *_args: (_manifest(), object()))
    monkeypatch.setattr(archive_module, "stage_database", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(archive_module, "portable_records", lambda _state: [_record()])
    monkeypatch.setattr(archive_module, "_recovery_buckets", lambda _context, _backup: {})

    class Collector:
        started_at = "2026-08-23T12:02:00Z"
        completed_at = "2026-08-23T12:02:01Z"

        def __init__(self, *_args, **_kwargs):
            pass

        def collect(self):
            return [], []

    monkeypatch.setattr(archive_module, "AssetCollector", Collector)

    class Context:
        project_id = PROJECT_ID
        deleted = False
        fail_cleanup = True
        database_payload = None
        monotonic = staticmethod(lambda: 0)
        sleep = staticmethod(lambda _delay: None)

        def database(self, database_id):
            if self.database_payload is None:
                raise ProviderNotFound("absent")
            assert self.database_payload["name"].endswith(f"/databases/{database_id}")
            return self.database_payload

        def create_database(self, database_id, location, **_kwargs):
            self.pending_database = {
                "name": f"projects/{PROJECT_ID}/databases/{database_id}",
                "type": "DATASTORE_MODE",
                "locationId": location,
            }
            return {
                "name": f"projects/{PROJECT_ID}/databases/{database_id}/operations/create-1"
            }

        def start_import(self, *_args, **_kwargs):
            return OPERATION, {}

        def wait_for_operation(self, *_args, **_kwargs):
            if hasattr(self, "pending_database"):
                self.database_payload = self.pending_database
                del self.pending_database
            return {"done": True}

        def datastore_client(self, *_args):
            return object()

        def delete_database(self, *_args):
            if self.fail_cleanup:
                raise RuntimeError("cleanup unavailable")
            self.deleted = True
            self.database_payload = None
            return {}

    context = Context()
    output = tmp_path / "published"
    with pytest.raises(DataLifecycleError, match="cleanup failed"):
        archive_module.build_archive(BACKUP_ID, output=output, context=context)
    assert validate_archive(output)["archive_id"] == BACKUP_ID
    assert list((tmp_path / "state" / "archive-work").rglob("staging.sqlite3"))
    context.fail_cleanup = False
    assert archive_module.build_archive(BACKUP_ID, output=output, context=context) == output.resolve()
    assert context.deleted is True
    assert not list((tmp_path / "state" / "archive-work").rglob("staging.sqlite3"))


class _RestoreContext:
    project_id = PROJECT_ID
    database_id = "(default)"
    application_version = "0.3.0"
    recovery_bucket = BUCKET

    def require_asset_generation_migration(self, database_id):
        assert database_id == "(default)"
        return {"migration_id": "AST-001", "state": "complete"}

    def database(self, database_id=None):
        if database_id not in {None, "(default)"}:
            raise ProviderNotFound("absent")
        return {"type": "DATASTORE_MODE", "locationId": "nam5"}

    def datastore_client(self, database_id):
        assert database_id == "(default)"
        return SimpleNamespace(get_multi=lambda keys: [])

    def json_command(self, arguments):
        if arguments[:3] == ["tasks", "queues", "describe"]:
            if arguments[3] == "lagniappe-tasks":
                return {"state": "RUNNING"}
            raise ProviderNotFound("absent")
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {"state": "PAUSED"}
        if arguments[:3] == ["app", "services", "describe"]:
            return {"id": "default"}
        if arguments[:3] == ["app", "versions", "list"]:
            return [{"id": "current"}]
        if arguments[:3] == ["firestore", "indexes", "composite"]:
            return []
        raise AssertionError(arguments)


# @matrix data-lifecycle : bounded-restore-scan restore-key-normalization serialized-entity-details
def test_restore_normalizes_persisted_keys_before_cache_rebuild():
    source_key = Key(
        "instances",
        "linked-page",
        project=PROJECT_ID,
        database="source-db",
    )
    target_key = Key(
        "instances",
        "restored-page",
        project=PROJECT_ID,
        database="target-db",
    )
    embedded = Entity(key=source_key)
    embedded["value"] = "embedded"
    row = _entity(
        target_key,
        type="page",
        parent=source_key,
        related=[source_key],
        embedded=embedded,
        submission=json.dumps(
            {
                "link": {
                    "id": encode_urlsafe_key(source_key),
                    "hash": "linkedpage01",
                    "name": "Linked page",
                },
                "ordinary_field": {"id": "input-ab12", "name": "Input"},
            }
        ),
    )
    rows = {
        ("", "__namespace__"): [
            _entity(Key("__namespace__", 1, project=PROJECT_ID), value=1)
        ],
        ("", "__kind__"): [
            _entity(Key("__kind__", "instances", project=PROJECT_ID), value="instances")
        ],
        ("", "instances"): [row],
    }

    class RestoreClient(_ScanClient):
        def __init__(self, values):
            super().__init__(values)
            self.writes = []

        def put_multi(self, values):
            self.writes.extend(values)

        def delete_multi(self, _keys):
            raise AssertionError("durable restore fixture should not delete records")

    client = RestoreClient(rows)
    counts = restore_module.normalize_restored_database(
        client,
        project_id=PROJECT_ID,
        source_database_id="source-db",
        target_database_id="target-db",
    )
    assert counts == {
        "entities_scanned": 1,
        "entities_written": 1,
        "native_keys": 3,
        "serialized_ids": 1,
        "deferred_records_deleted": 0,
        "deferred_references_cleared": 0,
    }
    assert row["parent"].database == "target-db"
    assert row["related"][0].database == "target-db"
    assert row["embedded"].key.database == "target-db"
    submission = json.loads(row["submission"])
    rebound = decode_urlsafe_key(submission["link"]["id"])
    assert rebound.database == "target-db"
    assert submission["ordinary_field"]["id"] == "input-ab12"

    repeated = restore_module.normalize_restored_database(
        client,
        project_id=PROJECT_ID,
        source_database_id="source-db",
        target_database_id="target-db",
    )
    assert repeated["entities_written"] == 0
    assert repeated["native_keys"] == 0
    assert repeated["serialized_ids"] == 0


# @matrix data-lifecycle : bounded-restore-scan deferred-state-retirement
def test_restore_discards_deferred_execution_state():
    def target_key(kind, name):
        return Key(kind, name, project=PROJECT_ID, database="target-db")

    page = _entity(
        target_key("instances", "page"),
        type="page",
        deferred_job=json.dumps({"key": "stale-job"}),
    )
    report = _entity(
        target_key("activity", "report"),
        type="report",
        process=json.dumps(
            {
                "report": {
                    "status": "running",
                    "deferred-job": {"key": "stale-job"},
                }
            }
        ),
    )
    job = _entity(target_key("jobs", "job"), type="job", status="running")
    lock = _entity(target_key("job_locks", "lock"), type="job_lock")
    control = _entity(target_key("site", "deferred-jobs-control"), active_jobs=1)
    rows = {
        ("", "__namespace__"): [
            _entity(Key("__namespace__", 1, project=PROJECT_ID), value=1)
        ],
        ("", "__kind__"): [
            _entity(Key("__kind__", kind, project=PROJECT_ID), value=kind)
            for kind in ("activity", "instances", "job_locks", "jobs", "site")
        ],
        ("", "activity"): [report],
        ("", "instances"): [page],
        ("", "job_locks"): [lock],
        ("", "jobs"): [job],
        ("", "site"): [control],
    }

    class RestoreClient(_ScanClient):
        def __init__(self, values):
            super().__init__(values)
            self.writes = []
            self.deleted = []

        def put_multi(self, values):
            self.writes.extend(values)

        def delete_multi(self, keys):
            self.deleted.extend(keys)
            deleted = set(keys)
            for row_key, values in self.rows.items():
                if row_key[1] not in {"__kind__", "__namespace__"}:
                    self.rows[row_key] = [row for row in values if row.key not in deleted]

    client = RestoreClient(rows)
    counts = restore_module.normalize_restored_database(
        client,
        project_id=PROJECT_ID,
        source_database_id="target-db",
        target_database_id="target-db",
        kind_prefix="",
    )
    assert counts["deferred_records_deleted"] == 3
    assert counts["deferred_references_cleared"] == 2
    assert counts["native_keys"] == 0
    assert {key.kind for key in client.deleted} == {"job_locks", "jobs", "site"}
    assert "deferred_job" not in page
    assert "deferred-job" not in json.loads(report["process"])["report"]

    repeated = restore_module.normalize_restored_database(
        client,
        project_id=PROJECT_ID,
        source_database_id="target-db",
        target_database_id="target-db",
        kind_prefix="",
    )
    assert repeated["deferred_records_deleted"] == 0
    assert repeated["deferred_references_cleared"] == 0
    assert repeated["entities_written"] == 0


# @pair data-lifecycle:legacy-journal-rejection
def test_in_place_restore_rejects_legacy_named_database_checkpoint(tmp_path):
    for complete in (False, True):
        checkpoint = LifecycleCheckpoint(
            PROJECT_ID,
            ["restore", BACKUP_ID],
            state_root=tmp_path / f"legacy-restore-state-{complete}",
        )
        checkpoint.start(
            "legacy-restore",
            backup_id=BACKUP_ID,
            plan={
                "restore_id": "legacy-restore",
                "backup_id": BACKUP_ID,
                "project_id": PROJECT_ID,
                "application_version": "0.3.0",
                "old_database": "(default)",
                "target_database": "lag-restore-legacy",
            },
        )
        if complete:
            checkpoint.finish()
        context = SimpleNamespace(
            project_id=PROJECT_ID,
            application_version="0.3.0",
        )

        with pytest.raises(DataLifecycleError, match="Legacy named-database"):
            restore_module.restore_backup(
                BACKUP_ID,
                context=context,
                checkpoint=checkpoint,
                confirmation=lambda _prompt: pytest.fail(
                    "legacy checkpoints must fail before confirmation"
                ),
            )


# @matrix data-lifecycle : dry-run in-place-merge restore-preflight
def test_restore_dry_run_is_deterministic_and_read_only(monkeypatch):
    monkeypatch.setattr(restore_in_place, "load_backup", lambda *_args: (_manifest(), object()))
    monkeypatch.setattr(
        restore_in_place,
        "_load_catalog",
        lambda *_args: {"entities": [], "entity_count": 0},
    )
    monkeypatch.setenv("FLASK_ENV", "production")
    from config import SETTINGS

    monkeypatch.setitem(SETTINGS.APP, "RESOURCE_REGION", "us-central1")
    monkeypatch.setitem(SETTINGS.APP, "TASK_QUEUE_NAME", "lagniappe-tasks")
    monkeypatch.setitem(SETTINGS.APP, "REDIS_HOST", "127.0.0.1")
    monkeypatch.setitem(SETTINGS.APP, "REDIS_PORT", 6379)
    monkeypatch.setitem(SETTINGS.APP, "REDIS_PASSWORD", "configured")
    monkeypatch.setitem(SETTINGS.APP, "APP_URL", "https://example.test")
    account = f"runtime@{PROJECT_ID}.iam.gserviceaccount.com"
    monkeypatch.setitem(SETTINGS.APP, "RUNTIME_SERVICE_ACCOUNT_EMAIL", account)
    monkeypatch.setitem(SETTINGS.APP, "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL", account)
    monkeypatch.setitem(SETTINGS.APP, "ADMIN_EMAIL", "owner@example.test")
    first = restore_module.restore_plan(BACKUP_ID, context=_RestoreContext())
    second = restore_module.restore_plan(BACKUP_ID, context=_RestoreContext())
    assert first == second
    assert first["target_database"] == "(default)"
    assert first["safety_database"].startswith("lag-safety-")
    assert first["queue"] == "lagniappe-tasks"
    assert first["provider_observations"]["reconciler_state"] == "PAUSED"
    assert "target_queue" not in first
    assert any("purge the configured" in step for step in first["sequence"])


# @matrix data-lifecycle : owner-invariant restore-validation
def test_target_validation_requires_owner_and_reserved_models():
    class Query:
        def __init__(self, rows):
            self.rows = rows

        def add_filter(self, *, filter):
            self.rows = [
                row
                for row in self.rows
                if row.get(filter.property_name) == filter.value
            ]
            return self

        def fetch(self, *, limit):
            return self.rows[:limit]

    class Client:
        def __init__(self, values):
            self.values = values

        def query(self, *, kind):
            return Query(self.values.get(kind, []))

    rows = {
        "models": [
            {"reserved": True, "type": "form"},
            {"reserved": True, "type": "users"},
        ],
        "users": [
            {"owner": True, "email": "owner@example.com"},
            {"owner": False, "email": "person@example.com"},
        ],
    }
    result = restore_module.validate_restored_database(
        Client(rows), owner_email="OWNER@example.com"
    )
    assert result["reserved_models"] == 2
    assert result["owners"] == 1
    with pytest.raises(DataLifecycleError, match="site owner"):
        restore_module.validate_restored_database(
            Client({**rows, "users": []}), owner_email="owner@example.com"
        )


# @matrix data-lifecycle : confirmation in-place-merge queue-purge-audit remote-journal restore resume
def test_in_place_restore_is_confirmed_resumable_and_has_no_rollback(
    monkeypatch, tmp_path
):
    """The released restore is resumable and has no automatic rollback path."""
    plan = {
        "restore_id": "restore-id",
        "backup_id": BACKUP_ID,
        "project_id": PROJECT_ID,
        "application_version": "0.3.0",
        "consistency": "point-in-time",
        "old_database": "(default)",
        "target_database": "(default)",
        "safety_database": "lag-safety-test",
        "backup_source_database": "(default)",
        "queue": "lagniappe-tasks",
        "queue_location": "us-central1",
        "reconciler": "lagniappe-deferred-jobs-reconciler",
        "maintenance_version": "maintenance",
        "runtime_service_account": f"runtime@{PROJECT_ID}.iam.gserviceaccount.com",
        "original_traffic": {"current": 1.0},
        "traffic_split_by": "random",
        "export_metadata_uri": "gs://recovery-demo1/export/metadata",
        "assets_uri": "gs://recovery-demo1/assets.json",
        "kind_prefix": "",
        "owner_email": "owner@example.com",
        "app_url": "https://example.test",
        "merge": {
            "snapshot_entities": 4,
            "overwritten": 3,
            "restored_missing": 1,
            "live_only": "preserved",
        },
        "provider_observations": {
            "queue_state": "RUNNING",
            "reconciler_state": "ENABLED",
        },
        "sequence": [],
    }

    class Context:
        project_id = PROJECT_ID
        database_id = "(default)"
        recovery_bucket = BUCKET
        application_version = "0.3.0"

        def __init__(self):
            self.calls = []
            self.versions = {"current"}
            self.bucket = _Bucket()

        def version_exists(self, version):
            return version in self.versions

        def deploy_maintenance_version(self, version, account):
            self.calls.append(("deploy-maintenance", version, account))
            self.versions.add(version)

        def pause_scheduler(self, job, location):
            self.calls.append(("pause-scheduler", job, location))

        def resume_scheduler(self, job, location):
            self.calls.append(("resume-scheduler", job, location))

        def pause_queue(self, queue, location):
            self.calls.append(("pause-queue", queue, location))

        def resume_queue(self, queue, location):
            self.calls.append(("resume-queue", queue, location))

        def set_traffic(self, allocations, *, split_by):
            self.calls.append(("traffic", allocations, split_by))

        def wait_for_no_inflight_tasks(self, queue, location):
            self.calls.append(("settled", queue, location))

        def sleep(self, seconds):
            self.calls.append(("sleep", seconds))

        def list_queue_tasks(self, _queue, _location):
            return []

        def purge_queue(self, queue, location):
            self.calls.append(("purge", queue, location))

        def wait_for_empty_queue(self, queue, location):
            self.calls.append(("empty", queue, location))

        def start_clone(self, database, *, snapshot_time):
            self.calls.append(("clone", database, snapshot_time))
            return "clone-operation", {}

        def start_import(self, uri, database):
            self.calls.append(("import", uri, database))
            return "import-operation", {}

        def wait_for_operation(self, operation, *, database_id):
            self.calls.append(("wait", operation, database_id))

        def datastore_client(self, database):
            self.calls.append(("client", database))
            return object()

        def invalidate_cache(self):
            self.calls.append(("invalidate-cache",))

        def disable_database_delete_protection(self, database):
            self.calls.append(("unprotect", database))

        def delete_database(self, database):
            self.calls.append(("delete", database))

        def upload_json_create_only(self, object_name, payload):
            blob = self.bucket.blob(object_name)
            blob.upload_from_string(json.dumps(payload), if_generation_match=0)
            return blob

        def upload_json_replace(self, object_name, payload):
            blob = self.bucket.blob(object_name)
            blob.payload = json.dumps(payload).encode()
            blob.generation += 1
            return blob

        def load_json_object(self, object_name):
            blob = self.bucket.blob(object_name)
            return json.loads(blob.download_as_text()), blob

        def list_objects(self, prefix):
            return self.bucket.list_blobs(prefix)

    context = Context()
    monkeypatch.setattr(restore_in_place, "restore_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(
        restore_in_place,
        "_safety_snapshot_time",
        lambda _context: datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        restore_in_place,
        "_publish_safety_assets",
        lambda *_args: {"object_name": "safety-assets.json", "asset_count": 0},
    )
    monkeypatch.setattr(
        restore_in_place,
        "restore_generation_bound_assets",
        lambda *_args: {"assets": 2, "owners": 1},
    )
    monkeypatch.setattr(
        restore_in_place,
        "normalize_restored_database",
        lambda *_args, **_kwargs: {"entities_scanned": 4},
    )
    monkeypatch.setattr(
        restore_in_place,
        "validate_restored_database",
        lambda *_args, **_kwargs: {"owners": 1, "reserved_models": 2},
    )
    monkeypatch.setattr(
        restore_in_place,
        "reconcile_scheduled_uncomplete_tasks",
        lambda *_args, **_kwargs: {"queued": 1, "backfilled": 0},
    )
    checkpoint = LifecycleCheckpoint(
        PROJECT_ID, ["restore", BACKUP_ID], state_root=tmp_path / "restore-state"
    )
    with pytest.raises(DataLifecycleError, match="confirmation"):
        restore_module.restore_backup(
            BACKUP_ID,
            context=context,
            checkpoint=checkpoint,
            confirmation=lambda _prompt: "no",
        )
    assert context.calls == []

    restored = restore_module.restore_backup(
        BACKUP_ID,
        context=context,
        checkpoint=checkpoint,
        confirmation=lambda _prompt: f"RESTORE {PROJECT_ID} {BACKUP_ID} INTO (default)",
    )
    assert restored == plan
    assert checkpoint.load()["status"] == "complete"
    assert ("import", plan["export_metadata_uri"], "(default)") in context.calls
    assert ("resume-queue", "lagniappe-tasks", "us-central1") in context.calls
    assert ("invalidate-cache",) in context.calls
    assert ("delete", "lag-safety-test") in context.calls
    assert not hasattr(restore_module, "rollback_restore")
    assert "rollback_restore" not in restore_module.__all__

    calls = list(context.calls)
    assert restore_module.restore_backup(
        BACKUP_ID,
        context=context,
        checkpoint=checkpoint,
        confirmation=lambda _prompt: (_ for _ in ()).throw(AssertionError()),
    ) == plan
    assert context.calls == calls

    recovered_checkpoint = LifecycleCheckpoint(
        PROJECT_ID,
        ["restore", BACKUP_ID],
        state_root=tmp_path / "recovered-restore-state",
    )
    monkeypatch.setattr(
        restore_in_place,
        "LifecycleCheckpoint",
        lambda *_args, **_kwargs: recovered_checkpoint,
    )
    assert restore_module.restore_backup(
        BACKUP_ID,
        context=context,
        confirmation=lambda _prompt: (_ for _ in ()).throw(AssertionError()),
    ) == plan
    assert recovered_checkpoint.load()["status"] == "complete"
    assert context.calls == calls


# @matrix data-lifecycle : cli-routing read-only
def test_lifecycle_cli_routes_nested_commands_and_read_only_boundaries():
    from installer.__main__ import _local_only, _parser, _read_only

    parser = _parser()
    backup_list = parser.parse_args(["backup", "list"])
    archive_validate = parser.parse_args(["archive", "validate", "bundle.zip"])
    restore_dry = parser.parse_args(["restore", BACKUP_ID, "--dry-run"])
    backup_create = parser.parse_args(["backup", "create"])
    backup_prepare = parser.parse_args(["backup", "prepare", "automatic-id"])
    assert _read_only(backup_list)
    assert _read_only(archive_validate) and _local_only(archive_validate)
    assert _read_only(restore_dry)
    assert not _read_only(backup_create)
    assert not _read_only(backup_prepare)
    assert backup_prepare.backup_id == "automatic-id"
