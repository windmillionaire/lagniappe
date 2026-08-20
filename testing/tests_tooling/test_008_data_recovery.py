"""Tooling tests for operator-only data backup and restore commands."""

from datetime import datetime, timezone
import json
import subprocess
import sys
import types

import pytest

from runner import data_recovery
import run


pytestmark = pytest.mark.tooling

BACKUP_ID = "20260725T120000Z-1234abcd"


def _context():
    return {
        "project": "project-1",
        "settings": {"VERSION": "1.25"},
        "source_buckets": {
            "history": "history-source",
            "private": "private-source",
            "public": "public-source",
            "export": "export-source",
        },
        "recovery_bucket": "recovery-source",
        "recovery_bucket_details": {"location": "US"},
        "database": {
            "type": "DATASTORE_MODE",
            "locationId": "nam5",
        },
        "database_location": "nam5",
        "version": "1.25",
    }


def _manifest(context=None, *, backup_id=BACKUP_ID):
    context = context or _context()
    root = (
        f"gs://{context['recovery_bucket']}/"
        f"{data_recovery.BACKUP_ROOT_PREFIX}/{backup_id}"
    )
    return {
        "schema": data_recovery.BACKUP_SCHEMA_VERSION,
        "status": "complete",
        "backup_id": backup_id,
        "root_uri": root,
        "project": context["project"],
        "app_version": context["version"],
        "consistency": "fuzzy",
        "started_at": "2026-07-25T12:00:00+00:00",
        "completed_at": "2026-07-25T12:05:00+00:00",
        "database": {
            "id": data_recovery.DATABASE_ID,
            "type": "DATASTORE_MODE",
            "location": "nam5",
            "output_uri_prefix": f"{root}/datastore/export-1",
            "started_at": "2026-07-25T12:00:00+00:00",
            "completed_at": "2026-07-25T12:01:00+00:00",
        },
        "storage": {
            kind: {
                "source_bucket": bucket,
                "backup_uri": f"{root}/storage/{kind}/objects",
                "empty": False,
                "started_at": "2026-07-25T12:01:00+00:00",
                "completed_at": "2026-07-25T12:05:00+00:00",
            }
            for kind, bucket in context["source_buckets"].items()
        },
    }


def _completed(command, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


# @features disaster-recovery
# @dimensions provider-preflight project-identity runtime-isolation
def test_prepare_context_validates_recovery_sources_and_database(monkeypatch):
    context = _context()
    settings_context = {
        key: value
        for key, value in context.items()
        if key not in {"database", "database_location", "recovery_bucket_details"}
    }
    bucket_calls = []

    monkeypatch.setattr(
        data_recovery,
        "_settings_context",
        lambda: settings_context,
    )

    def describe_bucket(bucket, project, *, allow_absent):
        bucket_calls.append((bucket, project, allow_absent))
        return {"location": "US"}

    monkeypatch.setattr(data_recovery, "_describe_bucket", describe_bucket)
    monkeypatch.setattr(
        data_recovery,
        "_describe_database",
        lambda project, *, allow_absent: context["database"],
    )

    prepared = data_recovery._prepare_context(
        require_sources=True,
        require_database=True,
    )

    assert prepared["database_location"] == "nam5"
    assert prepared["recovery_bucket_details"] == {"location": "US"}
    assert [call[0] for call in bucket_calls] == [
        context["recovery_bucket"],
        *context["source_buckets"].values(),
    ]
    assert all(call[1:] == ("project-1", True) for call in bucket_calls)


# @features disaster-recovery
# @dimensions datastore storage location
def test_location_compatibility_accepts_datastore_multiregions():
    assert data_recovery.locations_compatible("nam5", "US")
    assert data_recovery.locations_compatible("eur3", "EU")
    assert data_recovery.locations_compatible("us-central1", "us-central1")
    assert not data_recovery.locations_compatible("nam5", "EU")
    assert not data_recovery.locations_compatible("", "US")


# @features disaster-recovery
# @dimensions backup datastore storage completion-manifest fuzzy-window
def test_backup_writes_manifest_only_after_all_components_complete(monkeypatch):
    context = _context()
    events = []
    root = f"gs://recovery-source/{data_recovery.BACKUP_ROOT_PREFIX}/{BACKUP_ID}"

    monkeypatch.setattr(
        data_recovery,
        "_prepare_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        data_recovery,
        "_storage_prefix_has_objects",
        lambda uri, project: True,
    )

    def gcloud(arguments, **kwargs):
        events.append(("gcloud", list(arguments)))
        if arguments[:2] == ["firestore", "export"]:
            return _completed(
                arguments,
                stdout=json.dumps(
                    {"response": {"outputUriPrefix": f"{root}/datastore/export-1"}}
                ),
            )
        return _completed(arguments)

    uploaded = []

    def upload(uri, manifest, project):
        events.append(("upload", uri))
        uploaded.append((uri, manifest, project))

    monkeypatch.setattr(data_recovery, "_gcloud", gcloud)
    monkeypatch.setattr(data_recovery, "_upload_manifest", upload)

    manifest = data_recovery.create_backup(
        now=datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
        token="1234abcd",
    )

    assert manifest["backup_id"] == BACKUP_ID
    assert manifest["consistency"] == "fuzzy"
    assert set(manifest["storage"]) == set(context["source_buckets"])
    assert all(not item["empty"] for item in manifest["storage"].values())
    assert (
        len(
            [
                event
                for event in events
                if event[0] == "gcloud" and event[1][:2] == ["storage", "rsync"]
            ]
        )
        == 4
    )
    assert events[-1][0] == "upload"
    assert uploaded == [
        (
            f"{root}/manifest.json",
            manifest,
            "project-1",
        )
    ]


# @features disaster-recovery
# @dimensions backup failure-isolation completion-manifest
def test_backup_failure_never_publishes_manifest(monkeypatch):
    context = _context()
    monkeypatch.setattr(
        data_recovery,
        "_prepare_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        data_recovery,
        "_upload_manifest",
        lambda *args: pytest.fail("failed backups must not publish a manifest"),
    )

    def gcloud(arguments, **kwargs):
        if arguments[:2] == ["firestore", "export"]:
            root = (
                "gs://recovery-source/"
                f"{data_recovery.BACKUP_ROOT_PREFIX}/{BACKUP_ID}/datastore"
            )
            return _completed(
                arguments,
                stdout=json.dumps(
                    {"response": {"outputUriPrefix": f"{root}/export-1"}}
                ),
            )
        raise data_recovery.DataRecoveryError("copy failed")

    monkeypatch.setattr(data_recovery, "_gcloud", gcloud)

    with pytest.raises(data_recovery.DataRecoveryError, match="copy failed"):
        data_recovery.create_backup(
            now=datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
            token="1234abcd",
        )


# @features disaster-recovery
# @dimensions backup-list completion-manifest validation
def test_list_backups_ignores_invalid_or_incomplete_manifests(
    monkeypatch,
    capsys,
):
    context = _context()
    complete = _manifest(context)
    incomplete = {**complete, "status": "incomplete"}
    invalid = {**complete, "schema": 999}
    manifests = {
        "gs://recovery/complete.json": complete,
        "gs://recovery/incomplete.json": incomplete,
        "gs://recovery/invalid.json": invalid,
    }
    monkeypatch.setattr(
        data_recovery,
        "_prepare_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        data_recovery,
        "_manifest_uris",
        lambda selected: list(manifests),
    )
    monkeypatch.setattr(
        data_recovery,
        "_download_manifest",
        lambda uri, project: manifests[uri],
    )

    assert data_recovery.list_backups() == [complete]
    output = capsys.readouterr().out
    assert BACKUP_ID in output
    assert output.count("Skipping invalid or incomplete") == 2


# @features disaster-recovery
# @dimensions restore manifest-validation path-containment
def test_restore_rejects_manifest_paths_outside_recovery_set():
    context = _context()
    manifest = _manifest(context)
    manifest["database"]["output_uri_prefix"] = "gs://unrelated-bucket/stolen-export"

    with pytest.raises(
        data_recovery.DataRecoveryError,
        match="outside the selected recovery set",
    ):
        data_recovery._validate_manifest(context, manifest, BACKUP_ID)


# @features disaster-recovery
# @dimensions restore manifest-validation project-identity
def test_restore_rejects_other_project_manifest():
    context = _context()
    manifest = _manifest(context)
    manifest["project"] = "other-project"

    with pytest.raises(
        data_recovery.DataRecoveryError,
        match="different Google Cloud project",
    ):
        data_recovery._validate_manifest(context, manifest, BACKUP_ID)


# @features disaster-recovery
# @dimensions restore manifest-validation location
def test_restore_rejects_database_location_mismatch_before_mutation():
    context = _context()
    manifest = _manifest(context)
    manifest["database"]["location"] = "eur3"

    with pytest.raises(
        data_recovery.DataRecoveryError,
        match="target database location differs",
    ):
        data_recovery._validate_manifest(context, manifest, BACKUP_ID)


# @features disaster-recovery
# @dimensions restore artifact-validation
def test_validate_artifacts_enforces_manifest_empty_markers(monkeypatch):
    context = _context()
    manifest = _manifest(context)
    object_states = {
        manifest["database"]["output_uri_prefix"]: True,
        **{component["backup_uri"]: True for component in manifest["storage"].values()},
    }
    monkeypatch.setattr(
        data_recovery,
        "_storage_prefix_has_objects",
        lambda uri, project: object_states[uri],
    )

    data_recovery._validate_artifacts(context, manifest)

    manifest["storage"]["private"]["empty"] = True
    with pytest.raises(
        data_recovery.DataRecoveryError,
        match="private backup contents",
    ):
        data_recovery._validate_artifacts(context, manifest)


# @features disaster-recovery
# @dimensions restore offline-gate
def test_restore_offline_rejects_traffic(monkeypatch, capsys):
    context = _context()

    def json_gcloud(arguments, operation, **kwargs):
        if arguments[:2] == ["app", "describe"]:
            return {"servingStatus": "SERVING"}
        return [{"id": "serving-version"}]

    monkeypatch.setattr(data_recovery, "_json_gcloud", json_gcloud)

    with pytest.raises(
        data_recovery.DataRecoveryError,
        match="still serving traffic",
    ):
        data_recovery._restore_offline(context, enforce=True)

    assert not data_recovery._restore_offline(context, enforce=False)
    assert "WARNING" in capsys.readouterr().out


# @features disaster-recovery
# @dimensions restore storage-mirror exact-replacement
def test_mirror_storage_uses_exact_delete_semantics(monkeypatch):
    context = _context()
    manifest = _manifest(context)
    calls = []

    def gcloud(arguments, **kwargs):
        calls.append((list(arguments), kwargs))
        return _completed(arguments)

    monkeypatch.setattr(data_recovery, "_gcloud", gcloud)

    results = data_recovery._mirror_storage(
        context,
        manifest,
        dry_run=True,
    )

    assert len(results) == 4
    for kind, (arguments, kwargs) in zip(manifest["storage"], calls):
        assert arguments[:2] == ["storage", "rsync"]
        assert arguments[2] == manifest["storage"][kind]["backup_uri"]
        assert arguments[3] == f"gs://{context['source_buckets'][kind]}"
        assert "--delete-unmatched-destination-objects" in arguments
        assert "--dry-run" in arguments
        assert kwargs == {"announce": False}


# @features disaster-recovery
# @dimensions restore confirmation failure-isolation
def test_restore_cancelled_before_any_mutation(monkeypatch):
    context = _context()
    manifest = _manifest(context)
    monkeypatch.setattr(
        data_recovery,
        "_prepare_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        data_recovery,
        "_load_manifest",
        lambda selected, backup_id: manifest,
    )
    monkeypatch.setattr(data_recovery, "_validate_artifacts", lambda *args: None)
    monkeypatch.setattr(
        data_recovery,
        "_restore_offline",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        data_recovery,
        "_mirror_storage",
        lambda *args, **kwargs: pytest.fail(
            "cancelled restores must not mutate storage"
        ),
    )
    monkeypatch.setattr(
        data_recovery,
        "_gcloud",
        lambda *args, **kwargs: pytest.fail(
            "cancelled restores must not mutate Datastore"
        ),
    )

    assert not data_recovery.restore_backup(
        BACKUP_ID,
        input_fn=lambda prompt: "cancel",
    )


# @features disaster-recovery
# @dimensions restore storage-mirror datastore-purge import cache-flush
def test_restore_purges_before_import_and_mirrors_storage(monkeypatch):
    context = _context()
    manifest = _manifest(context)
    events = []
    monkeypatch.setattr(
        data_recovery,
        "_prepare_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        data_recovery,
        "_load_manifest",
        lambda selected, backup_id: manifest,
    )
    monkeypatch.setattr(data_recovery, "_validate_artifacts", lambda *args: None)
    monkeypatch.setattr(
        data_recovery,
        "_restore_offline",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        data_recovery,
        "_mirror_storage",
        lambda *args, dry_run: events.append(("mirror", dry_run)) or [],
    )
    monkeypatch.setattr(
        data_recovery,
        "_describe_database",
        lambda *args, **kwargs: {
            "type": "DATASTORE_MODE",
            "locationId": "nam5",
        },
    )

    def gcloud(arguments, **kwargs):
        events.append((arguments[1], list(arguments)))
        return _completed(arguments, stdout="{}")

    monkeypatch.setattr(data_recovery, "_gcloud", gcloud)
    monkeypatch.setattr(
        data_recovery,
        "_flush_redis_cache",
        lambda: events.append(("flush", None)),
    )

    confirmation = f"RESTORE project-1 {BACKUP_ID}"
    assert data_recovery.restore_backup(
        BACKUP_ID,
        input_fn=lambda prompt: confirmation,
    )

    assert events == [
        ("mirror", False),
        (
            "bulk-delete",
            [
                "firestore",
                "bulk-delete",
                "--database=(default)",
                "--project=project-1",
                "--quiet",
                "--format=json",
            ],
        ),
        (
            "import",
            [
                "firestore",
                "import",
                manifest["database"]["output_uri_prefix"],
                "--database=(default)",
                "--project=project-1",
                "--quiet",
                "--format=json",
            ],
        ),
        ("flush", None),
        ("mirror", True),
    ]


# @features disaster-recovery
# @dimensions restore missing-database create import location
def test_restore_creates_missing_default_database(monkeypatch):
    context = _context()
    manifest = _manifest(context)
    calls = []
    monkeypatch.setattr(
        data_recovery,
        "_prepare_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        data_recovery,
        "_load_manifest",
        lambda selected, backup_id: manifest,
    )
    monkeypatch.setattr(data_recovery, "_validate_artifacts", lambda *args: None)
    monkeypatch.setattr(
        data_recovery,
        "_restore_offline",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        data_recovery,
        "_mirror_storage",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        data_recovery,
        "_describe_database",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(data_recovery, "_flush_redis_cache", lambda: None)

    def gcloud(arguments, **kwargs):
        calls.append(list(arguments))
        return _completed(arguments, stdout="{}")

    monkeypatch.setattr(data_recovery, "_gcloud", gcloud)

    assert data_recovery.restore_backup(
        BACKUP_ID,
        input_fn=lambda prompt: f"RESTORE project-1 {BACKUP_ID}",
    )
    assert [call[1] for call in calls] == ["databases", "import"]
    assert "--database=(default)" in calls[0]
    assert "--location=nam5" in calls[0]
    assert "--type=datastore-mode" in calls[0]


def test_run_py_backup_and_restore_dispatch(monkeypatch):
    events = []

    class FakeRecoveryError(RuntimeError):
        pass

    module = types.ModuleType("runner.data_recovery")
    module.DataRecoveryError = FakeRecoveryError
    module.create_backup = lambda: events.append("create")
    module.list_backups = lambda: events.append("list")
    module.restore_backup = lambda backup_id, dry_run=False: (
        events.append(("restore", backup_id, dry_run)) or True
    )
    monkeypatch.setitem(sys.modules, "runner.data_recovery", module)

    assert run.run_backup_command(["create"]) == 0
    assert run.run_backup_command(["list"]) == 0
    assert run.run_restore_command([BACKUP_ID, "--dry-run"]) == 0
    assert events == [
        "create",
        "list",
        ("restore", BACKUP_ID, True),
    ]
