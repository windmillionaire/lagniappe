"""Private resumable lifecycle checkpoints and archive staging database."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from typing import Any

from installer.data_lifecycle.provider import DataLifecycleError
from installer.state import _state_dir, _write_json


LIFECYCLE_STATE_SCHEMA = 1
ARCHIVE_SQLITE_SCHEMA = 1


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_secure_directory_and_checkpoint_exact_resume
# @pairs data-lifecycle:private-state data-lifecycle:resume
def secure_directory(path: str | Path) -> Path:
    """Create an owner-only directory, failing closed when that cannot be proved."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path, 0o700)
        if path.stat().st_mode & 0o077:
            raise DataLifecycleError(f"Private lifecycle directory is not owner-only: {path}")
        return path

    username = str(os.environ.get("USERNAME") or "").strip()
    if not username:
        raise DataLifecycleError("Cannot establish a private Windows lifecycle directory: USERNAME is unavailable.")
    try:
        result = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{username}:(OI)(CI)(F)",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DataLifecycleError(f"Could not restrict lifecycle directory ACL: {path}") from error
    if result.returncode != 0:
        raise DataLifecycleError(f"Could not restrict lifecycle directory ACL: {path}")
    return path


# @testable false
# @covered-by installer/data_lifecycle/state.py::LifecycleCheckpoint
# @reason normalized command hashing is exercised through exact checkpoint resumption
def _identity(project_id: str, command: list[str], output_target: str | None) -> str:
    payload = json.dumps(
        {
            "project_id": project_id,
            "command": [str(item) for item in command],
            "output_target": str(output_target or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_secure_directory_and_checkpoint_exact_resume
# @pairs data-lifecycle:resume data-lifecycle:private-state
class LifecycleCheckpoint:
    """Durable exact-command state independent of the rewritten setup journal."""

    def __init__(
        self,
        project_id: str,
        command: list[str],
        *,
        output_target: str | None = None,
        state_root: str | Path | None = None,
    ):
        if not command or not all(isinstance(item, str) and item for item in command):
            raise DataLifecycleError("Lifecycle checkpoint command is invalid.")
        self.project_id = project_id
        self.command = list(command)
        self.output_target = str(output_target or "")
        root = Path(state_root) if state_root else _state_dir() / "data_lifecycle"
        self.root = secure_directory(root)
        self.identity = _identity(project_id, self.command, self.output_target)
        self.path = self.root / f"{self.identity}.json"
        self.payload: dict[str, Any] | None = None

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DataLifecycleError(f"Lifecycle checkpoint is corrupt: {self.path}") from error
        expected = {
            "schema": LIFECYCLE_STATE_SCHEMA,
            "identity": self.identity,
            "project_id": self.project_id,
            "command": self.command,
            "output_target": self.output_target,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise DataLifecycleError("Lifecycle checkpoint does not belong to this exact command.")
        self.payload = payload
        return payload

    def start(self, operation_id: str, **values) -> dict[str, Any]:
        existing = self.load()
        if existing:
            if existing.get("status") == "complete":
                raise DataLifecycleError("This lifecycle operation is already complete.")
            return existing
        payload = {
            "schema": LIFECYCLE_STATE_SCHEMA,
            "identity": self.identity,
            "project_id": self.project_id,
            "command": self.command,
            "output_target": self.output_target,
            "operation_id": str(operation_id),
            "status": "running",
            "checkpoint": "reserved",
            **values,
        }
        self.payload = payload
        self.save()
        return payload

    def save(self) -> None:
        if self.payload is None:
            raise DataLifecycleError("Lifecycle checkpoint has not been started.")
        _write_json(self.path, self.payload)

    def update(self, checkpoint: str, **values) -> dict[str, Any]:
        if self.payload is None:
            self.load()
        if self.payload is None:
            raise DataLifecycleError("Lifecycle checkpoint has not been started.")
        self.payload.update(values)
        self.payload["checkpoint"] = str(checkpoint)
        self.save()
        return self.payload

    def finish(self, **values) -> None:
        self.update("complete", status="complete", **values)

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)
        self.payload = None


ARCHIVE_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS metadata (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    source_key TEXT PRIMARY KEY,
    scratch_key TEXT NOT NULL UNIQUE,
    namespace TEXT NOT NULL,
    semantic_type TEXT,
    portable_id TEXT,
    kind_role TEXT NOT NULL,
    raw BLOB NOT NULL,
    status TEXT NOT NULL DEFAULT 'staged',
    UNIQUE(namespace, semantic_type, portable_id)
);
CREATE TABLE IF NOT EXISTS key_map (
    encoding TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    semantic_type TEXT NOT NULL,
    portable_id TEXT NOT NULL,
    availability TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS warnings (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    logical_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    owner TEXT NOT NULL,
    logical_name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    required INTEGER NOT NULL,
    source_role TEXT NOT NULL,
    source_path TEXT NOT NULL,
    generation TEXT,
    media_type TEXT,
    size INTEGER,
    sha256 TEXT,
    local_path TEXT
);
"""


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_archive_state_is_private_transactional_and_resumable
# @pairs data-lifecycle:sqlite-staging data-lifecycle:resume
class ArchiveState:
    """Owner-only SQLite staging store with bounded transaction checkpoints."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        secure_directory(self.path.parent)
        self.connection: sqlite3.Connection | None = None

    def _connect(self):
        new = not self.path.exists()
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(ARCHIVE_SCHEMA_SQL)
        self.connection.execute(
            "INSERT OR IGNORE INTO metadata(name, value) VALUES('schema', ?)",
            (str(ARCHIVE_SQLITE_SCHEMA),),
        )
        self.connection.commit()
        if os.name != "nt":
            os.chmod(self.path, 0o600)
        elif new:
            from installer.state import _restrict_state_file

            if not _restrict_state_file(self.path):
                self.close()
                raise DataLifecycleError("Could not restrict archive staging database ACL.")
        return self

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        return self._connect()

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @contextmanager
    def transaction(self):
        if self.connection is None:
            raise DataLifecycleError("Archive staging database is not open.")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def set_metadata(self, name: str, value: Any):
        if self.connection is None:
            raise DataLifecycleError("Archive staging database is not open.")
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
        self.connection.execute(
            "INSERT INTO metadata(name, value) VALUES(?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (str(name), serialized),
        )
        self.connection.commit()

    def get_metadata(self, name: str, default=None):
        if self.connection is None:
            raise DataLifecycleError("Archive staging database is not open.")
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE name=?", (str(name),)
        ).fetchone()
        return json.loads(row[0]) if row else default


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason secure temporary work-area selection is exercised by archive publication
def archive_work_directory(root: str | Path | None = None) -> Path:
    root = secure_directory(root or (_state_dir() / "data_lifecycle" / "archive-work"))
    path = Path(tempfile.mkdtemp(prefix="archive-", dir=root))
    return secure_directory(path)


__all__ = [
    "ARCHIVE_SQLITE_SCHEMA",
    "ArchiveState",
    "LifecycleCheckpoint",
    "archive_work_directory",
    "secure_directory",
]
