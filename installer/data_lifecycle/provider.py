"""Validated provider boundary shared by backup, archive, and restore."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from installer.errors import ProviderNotFound, ProviderTimeout, SetupError


BACKUP_FORMAT = "lagniappe-recovery-set"
BACKUP_SCHEMA_VERSION = 3
BACKUP_ROOT_PREFIX = "lagniappe-data/v3/recovery-sets"
RESTORE_ROOT_PREFIX = "lagniappe-data/v3/restores"
BACKUP_ID_PATTERN = re.compile(r"\A\d{8}T\d{6}Z-[0-9a-f]{8}\Z")
PROJECT_ID_PATTERN = re.compile(r"\A[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")
BUCKET_PATTERN = re.compile(r"\A[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]\Z")
DATABASE_PATTERN = re.compile(r"\A[a-z][a-z0-9-]{2,61}[a-z0-9]\Z")
UUID_PATTERN = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
OPERATION_PATTERN = re.compile(
    r"\Aprojects/[a-z][a-z0-9-]{4,28}[a-z0-9]/"
    r"(?:(?:databases/[^/]+/)?operations)/[A-Za-z0-9._~%-]+\Z"
)
POLL_DELAYS = (1, 2, 4, 8, 15, 30)
OPERATION_TIMEOUT_SECONDS = 6 * 60 * 60


class DataLifecycleError(SetupError):
    """Failure at a backup/archive/restore trust boundary."""

    category = "data-lifecycle"


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_identifiers_and_storage_paths_are_strict
# @matrix data-lifecycle : identifier-validation path-containment
def validate_backup_id(value: str) -> str:
    """Return one canonical user-facing backup ID or raise."""
    value = str(value or "").strip()
    if not BACKUP_ID_PATTERN.fullmatch(value) or value == "validate":
        raise DataLifecycleError(
            "Backup ID must use YYYYMMDDTHHMMSSZ- followed by 8 lowercase hex characters."
        )
    try:
        datetime.strptime(value[:16], "%Y%m%dT%H%M%SZ")
    except ValueError as error:
        raise DataLifecycleError("Backup ID contains an invalid UTC timestamp.") from error
    return value


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_identifiers_and_storage_paths_are_strict
# @pair data-lifecycle:identifier-validation
def validate_project_id(value: str) -> str:
    value = str(value or "").strip()
    if not PROJECT_ID_PATTERN.fullmatch(value):
        raise DataLifecycleError("Saved Google Cloud project ID is invalid.")
    return value


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_identifiers_and_storage_paths_are_strict
# @pair data-lifecycle:identifier-validation
def validate_database_id(value: str, *, allow_default: bool = True) -> str:
    """Validate the current Firestore multiple-database identifier contract."""
    value = str(value or "").strip()
    if allow_default and value == "(default)":
        return value
    if (
        not DATABASE_PATTERN.fullmatch(value)
        or not 4 <= len(value) <= 63
        or UUID_PATTERN.fullmatch(value)
    ):
        raise DataLifecycleError(
            "Datastore database ID must be 4-63 lowercase letters, digits, or hyphens, "
            "start with a letter, end with a letter or digit, and not resemble a UUID."
        )
    return value


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_identifiers_and_storage_paths_are_strict
# @pair data-lifecycle:identifier-validation
def validate_bucket_name(value: str) -> str:
    value = str(value or "").strip()
    if not BUCKET_PATTERN.fullmatch(value) or ".." in value:
        raise DataLifecycleError("Recovery bucket name is invalid.")
    return value


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_identifiers_and_storage_paths_are_strict
# @pair data-lifecycle:path-containment
def backup_root_uri(bucket: str, backup_id: str) -> str:
    return f"gs://{validate_bucket_name(bucket)}/{BACKUP_ROOT_PREFIX}/{validate_backup_id(backup_id)}"


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_identifiers_and_storage_paths_are_strict
# @pair data-lifecycle:path-containment
def parse_gs_uri(value: str) -> tuple[str, str]:
    """Parse an exact object URI; bucket-only and URL-shaped values are rejected."""
    value = str(value or "").strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme != "gs"
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise DataLifecycleError("Cloud Storage URI is invalid.")
    bucket = validate_bucket_name(parsed.netloc)
    path = parsed.path[1:]
    if (
        not path
        or "\\" in path
        or path.startswith("/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise DataLifecycleError("Cloud Storage object path is unsafe.")
    return bucket, path


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_manifest_validation_rejects_foreign_or_uncontained_artifacts
# @pair data-lifecycle:path-containment
def require_uri_below(uri: str, root_uri: str) -> str:
    bucket, path = parse_gs_uri(uri)
    root_bucket, root_path = parse_gs_uri(f"{root_uri}/root")
    root_path = root_path.removesuffix("/root")
    if bucket != root_bucket or not path.startswith(f"{root_path}/"):
        raise DataLifecycleError("Recovery artifact is outside its exact v3 root.")
    return path


# @testable infrastructure
@dataclass(frozen=True)
class BackupManifest:
    """Atomic v3 completion marker shared by every lifecycle consumer."""

    format: str
    schema_version: int
    status: str
    backup_id: str
    root_uri: str
    project_id: str
    application_version: str
    source_database_id: str
    database_mode: str
    database_location: str
    operation_name: str
    export_output_prefix: str
    export_metadata_uri: str
    export_started_at: str
    export_completed_at: str
    snapshot_time: str
    consistency: str
    inventory_uri: str
    inventory_sha256: str
    entity_count: int
    assets_uri: str
    assets_sha256: str
    asset_count: int
    tool_version: str

    # @testable true
    # @tests tests_tooling/test_008_data_lifecycle.py::test_manifest_validation_rejects_foreign_or_uncontained_artifacts
    # @matrix data-lifecycle : manifest path-containment
    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        expected_project: str | None = None,
        expected_backup_id: str | None = None,
        expected_bucket: str | None = None,
    ) -> "BackupManifest":
        if not isinstance(payload, dict):
            raise DataLifecycleError("Backup manifest must be a JSON object.")
        try:
            manifest = cls(
                **{field: payload[field] for field in cls.__dataclass_fields__}
            )
        except (KeyError, TypeError) as error:
            raise DataLifecycleError("Backup manifest is incomplete or malformed.") from error
        if set(payload) != set(cls.__dataclass_fields__):
            raise DataLifecycleError("Backup manifest contains unsupported fields.")
        backup_id = validate_backup_id(manifest.backup_id)
        project_id = validate_project_id(manifest.project_id)
        database_id = validate_database_id(manifest.source_database_id)
        if (
            manifest.format != BACKUP_FORMAT
            or manifest.schema_version != BACKUP_SCHEMA_VERSION
            or manifest.status != "complete"
            or manifest.database_mode != "datastore-mode"
            or manifest.consistency != "point-in-time"
        ):
            raise DataLifecycleError(
                "Recovery manifest is not a supported complete v3 point-in-time set; recreate it."
            )
        if expected_project and project_id != validate_project_id(expected_project):
            raise DataLifecycleError("Backup belongs to a different Google Cloud project.")
        if expected_backup_id and backup_id != validate_backup_id(expected_backup_id):
            raise DataLifecycleError("Backup manifest ID does not match the requested backup.")
        bucket = expected_bucket or parse_gs_uri(manifest.root_uri + "/root")[0]
        exact_root = backup_root_uri(bucket, backup_id)
        if manifest.root_uri != exact_root:
            raise DataLifecycleError("Recovery manifest root is not the exact v3 root.")
        require_uri_below(manifest.export_output_prefix + "/output", exact_root)
        metadata_path = require_uri_below(manifest.export_metadata_uri, exact_root)
        inventory_path = require_uri_below(manifest.inventory_uri, exact_root)
        assets_path = require_uri_below(manifest.assets_uri, exact_root)
        if not metadata_path.endswith(".overall_export_metadata"):
            raise DataLifecycleError("Backup export metadata URI is invalid.")
        if (
            not manifest.export_output_prefix.startswith(f"{exact_root}/datastore/")
            or manifest.export_metadata_uri.rsplit("/", 1)[0]
            != manifest.export_output_prefix
        ):
            raise DataLifecycleError("Backup export output is outside the datastore child.")
        if not OPERATION_PATTERN.fullmatch(str(manifest.operation_name or "")):
            raise DataLifecycleError("Backup export operation name is invalid.")
        for label, value in (
            ("export start", manifest.export_started_at),
            ("export completion", manifest.export_completed_at),
        ):
            try:
                datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError as error:
                raise DataLifecycleError(f"Backup {label} timestamp is invalid.") from error
        if not str(manifest.database_location or "").strip():
            raise DataLifecycleError("Backup database location is missing.")
        if database_id != "(default)":
            raise DataLifecycleError("Recovery sets must be canonicalized for (default).")
        try:
            snapshot_time = datetime.fromisoformat(
                str(manifest.snapshot_time).replace("Z", "+00:00")
            )
        except ValueError as error:
            raise DataLifecycleError("Recovery snapshot timestamp is invalid.") from error
        if snapshot_time.tzinfo is None or snapshot_time.second or snapshot_time.microsecond:
            raise DataLifecycleError("Recovery snapshot time must be a whole UTC minute.")
        if not inventory_path.endswith("/inventory.json"):
            raise DataLifecycleError("Recovery inventory URI is invalid.")
        if not assets_path.endswith("/assets.json"):
            raise DataLifecycleError("Recovery asset catalog URI is invalid.")
        for label, digest in (
            ("inventory", manifest.inventory_sha256),
            ("asset catalog", manifest.assets_sha256),
        ):
            if len(str(digest or "")) != 64 or any(
                character not in "0123456789abcdef" for character in str(digest)
            ):
                raise DataLifecycleError(f"Recovery {label} checksum is invalid.")
        if not isinstance(manifest.entity_count, int) or manifest.entity_count < 0:
            raise DataLifecycleError("Recovery entity count is invalid.")
        if not isinstance(manifest.asset_count, int) or manifest.asset_count < 0:
            raise DataLifecycleError("Recovery asset count is invalid.")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                manifest.application_version,
                manifest.tool_version,
                database_id,
            )
        ):
            raise DataLifecycleError("Backup version/database metadata is incomplete.")
        return manifest

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# @testable infrastructure
@dataclass
class ProviderContext:
    """Validated saved provider target and injectable provider adapters."""

    project_id: str
    database_id: str
    recovery_bucket: str
    application_version: str
    gcloud: Callable[..., Any] | None = None
    storage_client: Any = None
    datastore_client_factory: Callable[..., Any] | None = None
    cloud_tasks_client: Any = None
    subprocess_runner: Callable[..., Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    # @testable true
    # @tests tests_tooling/test_008_data_lifecycle.py::test_provider_context_always_uses_default_database_and_recovery_bucket
    # @pair data-lifecycle:provider-context
    @classmethod
    def from_settings(cls, settings=None, **overrides):
        if settings is None:
            from config import SETTINGS

            settings = SETTINGS
        app = settings.APP
        gcloud_config = settings.GCLOUD_CONFIG or {}
        from config.storage import recovery_bucket_name

        project = app.get("GOOGLE_CLOUD_PROJECT") or gcloud_config.get("PROJECT")
        return cls(
            project_id=validate_project_id(project),
            database_id="(default)",
            recovery_bucket=validate_bucket_name(recovery_bucket_name(app)),
            application_version=str(app.get("VERSION") or "unknown"),
            **overrides,
        )

    def _run(self, arguments: list[str], *, timeout=600):
        if not isinstance(arguments, list) or not all(
            isinstance(item, str) and item for item in arguments
        ):
            raise DataLifecycleError("Provider command must be a nonempty argument array.")
        runner = self.gcloud
        if runner is None:
            from installer.utils import run_gcloud_command

            runner = run_gcloud_command
        result = runner(arguments, timeout=timeout)
        return getattr(result, "stdout", result)

    def json_command(self, arguments: list[str], *, timeout=600):
        output = self._run([*arguments, "--project", self.project_id, "--format=json"], timeout=timeout)
        if isinstance(output, (dict, list)):
            return output
        try:
            return json.loads(str(output or ""))
        except json.JSONDecodeError as error:
            raise DataLifecycleError("Provider returned malformed JSON.") from error

    @property
    def storage(self):
        if self.storage_client is None:
            from google.cloud import storage

            self.storage_client = storage.Client(project=self.project_id)
        return self.storage_client

    @property
    def bucket(self):
        return self.storage.bucket(self.recovery_bucket)

    def database(self, database_id=None):
        return self.json_command(
            [
                "firestore",
                "databases",
                "describe",
                f"--database={validate_database_id(database_id or self.database_id)}",
            ]
        )

    def start_export(
        self, output_uri: str, *, snapshot_time: datetime | None, database_id=None
    ):
        require_uri_below(output_uri + "/output", backup_root_uri(self.recovery_bucket, output_uri.split("/")[-2]))
        if snapshot_time is not None and (
            not isinstance(snapshot_time, datetime) or snapshot_time.tzinfo is None
        ):
            raise DataLifecycleError("Point-in-time export requires a timezone-aware timestamp.")
        if snapshot_time is not None:
            snapshot_time = snapshot_time.astimezone(timezone.utc).replace(microsecond=0)
        snapshot_argument = (
            [f"--snapshot-time={snapshot_time.isoformat().replace('+00:00', 'Z')}"]
            if snapshot_time is not None
            else []
        )
        payload = self.json_command(
            [
                "firestore",
                "export",
                output_uri,
                f"--database={validate_database_id(database_id or self.database_id)}",
                *snapshot_argument,
                "--async",
            ],
            timeout=120,
        )
        name = str((payload or {}).get("name") or "").strip()
        if not OPERATION_PATTERN.fullmatch(name):
            raise DataLifecycleError("Provider did not return a valid export operation name.")
        return name, payload

    def start_native_backup_restore(self, source_backup: str, destination_database: str):
        source_backup = str(source_backup or "").strip()
        expected_prefix = f"projects/{self.project_id}/locations/"
        if (
            not source_backup.startswith(expected_prefix)
            or "/backups/" not in source_backup
            or any(part in {"", ".", ".."} for part in source_backup.split("/"))
        ):
            raise DataLifecycleError("Native backup resource name is invalid or foreign.")
        destination_database = validate_database_id(
            destination_database, allow_default=False
        )
        payload = self.json_command(
            [
                "firestore",
                "databases",
                "restore",
                f"--source-backup={source_backup}",
                f"--destination-database={destination_database}",
            ],
            timeout=120,
        )
        name = str((payload or {}).get("name") or "").strip()
        if not OPERATION_PATTERN.fullmatch(name):
            raise DataLifecycleError("Provider did not return a valid restore operation name.")
        return name, payload

    def start_import(self, metadata_uri: str, database_id: str):
        parse_gs_uri(metadata_uri)
        database_id = validate_database_id(database_id)
        payload = self.json_command(
            [
                "firestore",
                "import",
                metadata_uri,
                f"--database={database_id}",
                "--async",
            ],
            timeout=120,
        )
        name = str((payload or {}).get("name") or "").strip()
        if not OPERATION_PATTERN.fullmatch(name):
            raise DataLifecycleError("Provider did not return a valid import operation name.")
        return name, payload

    def start_clone(self, destination_database: str, *, snapshot_time: datetime):
        """Clone the default database at one whole-minute safety point."""
        destination_database = validate_database_id(
            destination_database, allow_default=False
        )
        if not isinstance(snapshot_time, datetime) or snapshot_time.tzinfo is None:
            raise DataLifecycleError("Database clone time must include a timezone.")
        snapshot_time = snapshot_time.astimezone(timezone.utc)
        if snapshot_time.second or snapshot_time.microsecond:
            raise DataLifecycleError("Database clone time must be a whole UTC minute.")
        payload = self.json_command(
            [
                "firestore",
                "databases",
                "clone",
                f"--source-database=projects/{self.project_id}/databases/(default)",
                f"--snapshot-time={snapshot_time.isoformat().replace('+00:00', 'Z')}",
                f"--destination-database={destination_database}",
            ],
            timeout=120,
        )
        name = str((payload or {}).get("name") or "").strip()
        if not OPERATION_PATTERN.fullmatch(name):
            raise DataLifecycleError("Provider did not return a valid clone operation name.")
        return name, payload

    def operation(self, name: str, *, database_id=None):
        if not OPERATION_PATTERN.fullmatch(str(name or "")):
            raise DataLifecycleError("Provider operation name is invalid.")
        return self.json_command(
            [
                "firestore",
                "operations",
                "describe",
                name,
                f"--database={validate_database_id(database_id or self.database_id)}",
            ],
            timeout=120,
        )

    # @testable true
    # @tests tests_tooling/test_008_data_lifecycle.py::test_operation_polling_resumes_and_reports_provider_failure
    # @matrix data-lifecycle : failure-propagation operation-polling
    def wait_for_operation(self, name: str, *, database_id=None, timeout=None):
        deadline = self.monotonic() + (timeout or OPERATION_TIMEOUT_SECONDS)
        attempt = 0
        while True:
            payload = self.operation(name, database_id=database_id)
            if payload.get("done"):
                if payload.get("error"):
                    detail = payload["error"].get("message") if isinstance(payload["error"], dict) else payload["error"]
                    raise DataLifecycleError(f"Provider operation failed: {detail}")
                state = str(
                    (((payload.get("metadata") or {}).get("common") or {}).get("state"))
                    or ""
                ).upper()
                if state and state not in {"SUCCESSFUL", "DONE", "COMPLETED"}:
                    raise DataLifecycleError(f"Provider operation completed in state {state}.")
                return payload
            if self.monotonic() >= deadline:
                raise ProviderTimeout(f"Provider operation did not complete: {name}")
            delay = POLL_DELAYS[min(attempt, len(POLL_DELAYS) - 1)]
            attempt += 1
            self.sleep(delay)

    def create_database(self, database_id: str, location: str, *, delete_protection=True):
        database_id = validate_database_id(database_id, allow_default=False)
        arguments = [
                "firestore",
                "databases",
                "create",
                f"--database={database_id}",
                f"--location={str(location).strip()}",
                "--type=datastore-mode",
                "--async",
            ]
        arguments.insert(-1, "--delete-protection" if delete_protection else "--no-delete-protection")
        return self.json_command(
            arguments,
            timeout=120,
        )

    def delete_database(self, database_id: str):
        database_id = validate_database_id(database_id, allow_default=False)
        self._run(
            [
                "firestore",
                "databases",
                "delete",
                f"--database={database_id}",
                "--quiet",
            ],
            timeout=600,
        )
        return {}

    def disable_database_delete_protection(self, database_id: str):
        database_id = validate_database_id(database_id, allow_default=False)
        return self.json_command(
            [
                "firestore",
                "databases",
                "update",
                f"--database={database_id}",
                "--no-delete-protection",
            ],
            timeout=600,
        )

    def datastore_client(self, database_id: str):
        database_id = validate_database_id(database_id)
        factory = self.datastore_client_factory
        if factory is None:
            from google.cloud import datastore

            factory = datastore.Client
        return factory(project=self.project_id, database=database_id)

    # @testable true
    # @tests tests_tooling/test_008_data_lifecycle.py::test_queue_snapshot_preserves_full_task_definitions
    # @matrix data-lifecycle : provider-pagination queue-purge-audit
    def list_queue_tasks(self, queue_name: str, location: str) -> list[dict[str, Any]]:
        """Return every task using FULL view so a pre-purge audit keeps payloads."""
        from google.cloud.tasks_v2.types import Task

        queue_name = str(queue_name or "").strip()
        location = str(location or "").strip()
        if (
            not queue_name
            or not location
            or any(character in queue_name or character in location for character in "/\\")
        ):
            raise DataLifecycleError("Cloud Tasks queue identity is invalid.")
        client = self.cloud_tasks_client
        if client is None:
            from google.cloud import tasks_v2

            client = tasks_v2.CloudTasksClient()
            self.cloud_tasks_client = client
        parent = client.queue_path(self.project_id, location, queue_name)
        pager = client.list_tasks(
            request={
                "parent": parent,
                "response_view": Task.View.FULL,
                "page_size": 1000,
            }
        )
        tasks = []
        for task in pager:
            if isinstance(task, dict):
                payload = json.loads(json.dumps(task))
            else:
                from google.protobuf.json_format import MessageToDict

                message = getattr(task, "_pb", task)
                payload = MessageToDict(message)
            if not isinstance(payload, dict):
                raise DataLifecycleError("Cloud Tasks returned a malformed task.")
            tasks.append(payload)
        return tasks

    def queue_state(self, queue_name: str, location: str) -> str:
        payload = self.json_command(
            [
                "tasks",
                "queues",
                "describe",
                str(queue_name),
                f"--location={str(location)}",
            ]
        )
        return str(payload.get("state") or "").upper()

    def _wait_for_state(self, observer, expected: str, label: str, *, timeout=180):
        deadline = self.monotonic() + timeout
        attempt = 0
        while observer() != expected:
            if self.monotonic() >= deadline:
                raise ProviderTimeout(f"{label} did not reach {expected} state.")
            self.sleep(POLL_DELAYS[min(attempt, len(POLL_DELAYS) - 1)])
            attempt += 1

    def pause_queue(self, queue_name: str, location: str):
        if self.queue_state(queue_name, location) != "PAUSED":
            self._run(
                [
                    "tasks",
                    "queues",
                    "pause",
                    str(queue_name),
                    f"--location={str(location)}",
                    "--project",
                    self.project_id,
                    "--quiet",
                ]
            )
        self._wait_for_state(
            lambda: self.queue_state(queue_name, location),
            "PAUSED",
            "Cloud Tasks queue",
        )

    def resume_queue(self, queue_name: str, location: str):
        if self.queue_state(queue_name, location) != "RUNNING":
            self._run(
                [
                    "tasks",
                    "queues",
                    "resume",
                    str(queue_name),
                    f"--location={str(location)}",
                    "--project",
                    self.project_id,
                    "--quiet",
                ]
            )
        self._wait_for_state(
            lambda: self.queue_state(queue_name, location),
            "RUNNING",
            "Cloud Tasks queue",
        )

    def purge_queue(self, queue_name: str, location: str):
        self._run(
            [
                "tasks",
                "queues",
                "purge",
                str(queue_name),
                f"--location={str(location)}",
                "--project",
                self.project_id,
                "--quiet",
            ]
        )

    def wait_for_empty_queue(self, queue_name: str, location: str, *, timeout=180):
        deadline = self.monotonic() + timeout
        attempt = 0
        while True:
            if not self.list_queue_tasks(queue_name, location):
                return
            if self.monotonic() >= deadline:
                raise ProviderTimeout(
                    f"Cloud Tasks purge did not empty queue {queue_name}."
                )
            self.sleep(POLL_DELAYS[min(attempt, len(POLL_DELAYS) - 1)])
            attempt += 1

    def create_scheduled_uncomplete_task(
        self,
        queue_name: str,
        location: str,
        *,
        entity_key: str,
        token: str,
        schedule_at: datetime,
        app_url: str,
        service_account: str,
    ):
        """Idempotently restore one durable scheduled-task wake-up."""
        from google.api_core.exceptions import AlreadyExists
        from google.cloud import tasks_v2
        from google.protobuf import timestamp_pb2

        client = self.cloud_tasks_client or tasks_v2.CloudTasksClient()
        self.cloud_tasks_client = client
        parent = client.queue_path(self.project_id, location, queue_name)
        identity = hashlib.sha256(
            f"{entity_key}\0{token}".encode("utf-8")
        ).hexdigest()[:32]
        body = json.dumps(
            {"key": entity_key, "token": token},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(schedule_at.astimezone(timezone.utc))
        task = {
            "name": client.task_path(
                self.project_id,
                location,
                queue_name,
                f"scheduled-uncomplete-{identity}",
            ),
            "schedule_time": timestamp,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{str(app_url).rstrip('/')}/process/uncomplete-task",
                "headers": {"Content-Type": "application/json"},
                "body": body,
                "oidc_token": {
                    "service_account_email": str(service_account),
                    "audience": f"{str(app_url).rstrip('/')}/process/uncomplete-task",
                },
            },
        }
        try:
            return client.create_task(request={"parent": parent, "task": task})
        except AlreadyExists:
            return None

    # @testable true
    # @tests tests_tooling/test_008_data_lifecycle.py::test_cutover_waits_for_dispatched_task_attempts_to_settle
    # @pair data-lifecycle:inflight-task-settlement
    def wait_for_no_inflight_tasks(
        self, queue_name: str, location: str, *, timeout=3700
    ):
        """Wait until every dispatched attempt has received a response or disappeared."""
        deadline = self.monotonic() + timeout
        attempt = 0
        while True:
            tasks = self.list_queue_tasks(queue_name, location)
            inflight = []
            for task in tasks:
                try:
                    dispatches = int(
                        task.get("dispatchCount", task.get("dispatch_count", 0))
                        or 0
                    )
                    responses = int(
                        task.get("responseCount", task.get("response_count", 0))
                        or 0
                    )
                except (TypeError, ValueError) as error:
                    raise DataLifecycleError(
                        "Cloud Tasks returned malformed dispatch counters."
                    ) from error
                if dispatches > responses:
                    inflight.append(str(task.get("name") or "unknown"))
            if not inflight:
                return
            if self.monotonic() >= deadline:
                raise ProviderTimeout(
                    "Dispatched Cloud Tasks did not settle before restore cutover: "
                    + ", ".join(inflight[:5])
                )
            self.sleep(POLL_DELAYS[min(attempt, len(POLL_DELAYS) - 1)])
            attempt += 1

    def scheduler_state(self, job_name: str, location: str) -> str:
        payload = self.json_command(
            [
                "scheduler",
                "jobs",
                "describe",
                str(job_name),
                f"--location={str(location)}",
            ]
        )
        return str(payload.get("state") or "").upper()

    def pause_scheduler(self, job_name: str, location: str):
        if self.scheduler_state(job_name, location) != "PAUSED":
            self._run(
                [
                    "scheduler",
                    "jobs",
                    "pause",
                    str(job_name),
                    f"--location={str(location)}",
                    "--project",
                    self.project_id,
                    "--quiet",
                ]
            )
        self._wait_for_state(
            lambda: self.scheduler_state(job_name, location),
            "PAUSED",
            "Deferred-job Scheduler",
        )

    def resume_scheduler(self, job_name: str, location: str):
        if self.scheduler_state(job_name, location) != "ENABLED":
            self._run(
                [
                    "scheduler",
                    "jobs",
                    "resume",
                    str(job_name),
                    f"--location={str(location)}",
                    "--project",
                    self.project_id,
                    "--quiet",
                ]
            )
        self._wait_for_state(
            lambda: self.scheduler_state(job_name, location),
            "ENABLED",
            "Deferred-job Scheduler",
        )

    def indexes_ready(self, database_id: str, *, minimum_count=0) -> bool:
        payload = self.json_command(
            [
                "datastore",
                "indexes",
                "list",
                f"--database={validate_database_id(database_id)}",
            ]
        )
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            raise DataLifecycleError("Provider returned malformed Datastore indexes.")
        return len(payload) >= int(minimum_count) and all(
            str(item.get("state") or "READY").upper() in {"READY", "SERVING"}
            for item in payload
        )

    def deploy_indexes(self, database_id: str, index_path: str | Path):
        import yaml

        index_path = Path(index_path).resolve()
        if not index_path.is_file():
            raise DataLifecycleError("Current index.yaml is missing.")
        try:
            index_config = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
            expected_count = len(index_config.get("indexes") or [])
        except (OSError, TypeError, yaml.YAMLError) as error:
            raise DataLifecycleError("Current index.yaml is malformed.") from error
        self._run(
            [
                "datastore",
                "indexes",
                "create",
                str(index_path),
                f"--database={validate_database_id(database_id)}",
                "--project",
                self.project_id,
                "--quiet",
            ],
            timeout=OPERATION_TIMEOUT_SECONDS,
        )
        deadline = self.monotonic() + OPERATION_TIMEOUT_SECONDS
        attempt = 0
        while not self.indexes_ready(database_id, minimum_count=expected_count):
            if self.monotonic() >= deadline:
                raise ProviderTimeout("Target database indexes are not serving.")
            self.sleep(POLL_DELAYS[min(attempt, len(POLL_DELAYS) - 1)])
            attempt += 1

    def version_exists(self, version_id: str) -> bool:
        try:
            payload = self.json_command(
                [
                    "app",
                    "versions",
                    "describe",
                    str(version_id),
                    "--service=default",
                ]
            )
        except SetupError as error:
            if isinstance(error, ProviderNotFound):
                return False
            raise
        return str(
            payload.get("servingStatus") or payload.get("serving_status") or ""
        ).upper() == "SERVING"

    def app_traffic(self):
        payload = self.json_command(["app", "services", "describe", "default"])
        split = payload.get("split") or payload.get("trafficSplit") or {}
        allocations = split.get("allocations") or {}
        if not isinstance(allocations, dict) or not allocations:
            raise DataLifecycleError("App Engine traffic allocation is unavailable.")
        try:
            normalized = {
                str(version).strip(): float(weight)
                for version, weight in allocations.items()
                if float(weight) > 0
            }
        except (TypeError, ValueError) as error:
            raise DataLifecycleError("App Engine traffic allocation is malformed.") from error
        split_by = str(
            split.get("shardBy") or split.get("shard_by") or "RANDOM"
        ).casefold()
        return normalized, split_by

    def deploy_maintenance_version(self, version_id: str, service_account: str):
        service_account = str(service_account or "").strip().casefold()
        if not service_account.endswith(
            f"@{self.project_id}.iam.gserviceaccount.com"
        ):
            raise DataLifecycleError("Runtime service account is invalid.")
        main_source = '''import os\nfrom http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n\nclass Handler(BaseHTTPRequestHandler):\n    def _reply(self):\n        healthy = self.path in {"/_ah/start", "/_ah/warmup", "/_ah/stop"}\n        body = b"OK" if healthy else b"Restore maintenance in progress"\n        self.send_response(200 if healthy else 503)\n        self.send_header("Cache-Control", "no-store")\n        self.send_header("Content-Type", "text/plain; charset=utf-8")\n        self.send_header("Content-Length", str(len(body)))\n        self.end_headers()\n        self.wfile.write(body)\n    do_GET = _reply\n    do_POST = _reply\n    def log_message(self, *args):\n        return\n\nThreadingHTTPServer(("0.0.0.0", int(os.environ["PORT"])), Handler).serve_forever()\n'''
        app_yaml = f'''runtime: python314\nentrypoint: python main.py\nservice_account: {service_account}\nautomatic_scaling:\n  max_instances: 1\nhandlers:\n- url: /.*\n  script: auto\n  secure: always\n'''
        with tempfile.TemporaryDirectory(prefix="lagniappe-restore-maintenance-") as raw:
            root = Path(raw)
            (root / "main.py").write_text(main_source, encoding="utf-8", newline="\n")
            (root / "app.yaml").write_text(app_yaml, encoding="utf-8", newline="\n")
            self._run(
                [
                    "app",
                    "deploy",
                    str(root / "app.yaml"),
                    f"--version={str(version_id)}",
                    "--no-promote",
                    "--project",
                    self.project_id,
                    "--quiet",
                ],
                timeout=OPERATION_TIMEOUT_SECONDS,
            )

    def set_traffic(self, allocations: dict[str, float], *, split_by="random"):
        try:
            normalized = {
                str(version).strip(): float(weight)
                for version, weight in allocations.items()
            }
        except (AttributeError, TypeError, ValueError) as error:
            raise DataLifecycleError("App Engine traffic allocation is invalid.") from error
        if (
            not normalized
            or any(not version or weight <= 0 for version, weight in normalized.items())
            or abs(sum(normalized.values()) - 1.0) > 0.000001
        ):
            raise DataLifecycleError("App Engine traffic allocation is invalid.")
        split_by = str(split_by or "random").strip().casefold()
        if split_by not in {"cookie", "ip", "random"}:
            raise DataLifecycleError("App Engine traffic split mode is invalid.")
        splits = ",".join(
            f"{version}={float(weight):.12g}"
            for version, weight in sorted(normalized.items())
        )
        self._run(
            [
                "app",
                "services",
                "set-traffic",
                "default",
                f"--splits={splits}",
                f"--split-by={split_by}",
                "--project",
                self.project_id,
                "--quiet",
            ],
            timeout=600,
        )
        deadline = self.monotonic() + 600
        attempt = 0
        while True:
            observed, observed_split_by = self.app_traffic()
            if (
                observed_split_by == split_by
                and set(observed) == set(normalized)
                and all(
                    abs(observed[version] - weight) <= 0.000001
                    for version, weight in normalized.items()
                )
            ):
                return
            if self.monotonic() >= deadline:
                raise ProviderTimeout(
                    "App Engine traffic did not reach the requested allocation."
                )
            self.sleep(POLL_DELAYS[min(attempt, len(POLL_DELAYS) - 1)])
            attempt += 1

    def run_runtime_action(self, action: str, database_id: str):
        action = str(action or "").strip()
        if action not in {"migrate", "rebuild-cache"}:
            raise DataLifecycleError("Data-lifecycle runtime action is invalid.")
        runner = self.subprocess_runner or subprocess.run

        if validate_database_id(database_id) != "(default)":
            raise DataLifecycleError("Runtime recovery actions only support (default).")
        environment = os.environ.copy()
        environment["FLASK_ENV"] = "production"
        environment["TASK_QUEUE_ENABLED"] = "false"
        result = runner(
            [
                sys.executable,
                "-m",
                "installer.data_lifecycle.runtime",
                action,
            ],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=OPERATION_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or "").strip()
            raise DataLifecycleError(
                f"Data-lifecycle runtime action {action} failed: {detail}"
            )
        try:
            return json.loads(str(result.stdout or "").splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as error:
            raise DataLifecycleError(
                f"Data-lifecycle runtime action {action} returned malformed output."
            ) from error

    def list_objects(self, prefix: str):
        if not prefix or prefix.startswith("/") or ".." in prefix.split("/"):
            raise DataLifecycleError("Cloud Storage prefix is unsafe.")
        return list(self.bucket.list_blobs(prefix=prefix))

    def load_json_object(self, object_name: str):
        if not object_name or object_name.startswith("/") or ".." in object_name.split("/"):
            raise DataLifecycleError("Cloud Storage object name is unsafe.")
        blob = self.bucket.blob(object_name)
        try:
            payload = blob.download_as_text(encoding="utf-8")
            return json.loads(payload), blob
        except Exception as error:
            raise DataLifecycleError(f"Could not read {object_name}: {error}") from error

    def upload_json_create_only(self, object_name: str, payload: dict[str, Any]):
        blob = self.bucket.blob(object_name)
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        blob.upload_from_string(
            content,
            content_type="application/json",
            if_generation_match=0,
        )
        blob.reload()
        return blob

    def upload_json_replace(self, object_name: str, payload: dict[str, Any]):
        """Replace one known JSON object using its observed generation."""
        if not object_name or object_name.startswith("/") or ".." in object_name.split("/"):
            raise DataLifecycleError("Cloud Storage object name is unsafe.")
        blob = self.bucket.blob(object_name)
        blob.reload()
        generation = getattr(blob, "generation", None)
        if generation is None:
            raise DataLifecycleError("Cloud Storage object generation is unavailable.")
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        blob.upload_from_string(
            content,
            content_type="application/json",
            if_generation_match=generation,
        )
        blob.reload()
        return blob


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason provider response normalization is exercised through backup publication
def operation_times(payload: dict[str, Any]) -> tuple[str, str]:
    metadata = payload.get("metadata") or {}
    common = metadata.get("common") or {}
    start = (
        common.get("startTime")
        or common.get("start_time")
        or metadata.get("startTime")
        or metadata.get("start_time")
    )
    end = (
        common.get("endTime")
        or common.get("end_time")
        or metadata.get("endTime")
        or metadata.get("end_time")
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(start or now), str(end or now)


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason provider response normalization is exercised through backup publication
def export_output_uri(payload: dict[str, Any]) -> str:
    response = payload.get("response") or {}
    metadata = payload.get("metadata") or {}
    value = (
        response.get("outputUrl")
        or response.get("output_url")
        or response.get("outputUriPrefix")
        or response.get("output_uri_prefix")
        or metadata.get("outputUrl")
        or metadata.get("output_url")
        or metadata.get("outputUriPrefix")
        or metadata.get("output_uri_prefix")
    )
    if not value:
        raise DataLifecycleError("Completed export did not report its output location.")
    parse_gs_uri(value)
    return str(value)


__all__ = [
    "BACKUP_FORMAT",
    "BACKUP_ROOT_PREFIX",
    "BACKUP_SCHEMA_VERSION",
    "RESTORE_ROOT_PREFIX",
    "BackupManifest",
    "DataLifecycleError",
    "ProviderContext",
    "backup_root_uri",
    "export_output_uri",
    "operation_times",
    "parse_gs_uri",
    "require_uri_below",
    "validate_backup_id",
    "validate_bucket_name",
    "validate_database_id",
    "validate_project_id",
]
