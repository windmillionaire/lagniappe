"""Durable local ownership for E2E and managed test-server sessions."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
from time import monotonic, sleep
from typing import Callable

from config import APP_DIR, Directory, File, SETTINGS, _atomic_write_text
from runner.context import format_command


SESSION_SCHEMA_VERSION = 1
SESSION_NONCE_ENV = "LAGNIAPPE_TEST_SESSION_NONCE"
SESSION_MODE_ENV = "LAGNIAPPE_TEST_SESSION_MODE"
SESSION_MODES = frozenset({"local-e2e", "managed-server"})
SESSION_PHASES = frozenset(
    {
        "acquiring",
        "starting",
        "seeding",
        "ready",
        "stopping",
        "recovery-required",
    }
)
HEARTBEAT_SECONDS = 60
RECOVERY_COMMAND = "venv/bin/python run.py test-server --recover"
SESSION_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "nonce",
        "mode",
        "phase",
        "created_at",
        "heartbeat_at",
        "repository",
        "base_url",
        "port",
        "data_namespace",
        "artifact_namespaces",
        "command",
        "recovery_hint",
        "owner",
        "keeper",
        "server",
        "attachment",
    }
)


class TestSessionError(RuntimeError):
    """Base error for local test-session ownership."""


class TestSessionBusy(TestSessionError):
    """Raised when another local session already has a durable record."""


class TestSessionStateError(TestSessionError):
    """Raised when persisted state is malformed or no longer trustworthy."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_paths():
    return File.TEST_SESSION_STATE.value, File.TEST_SESSION_LOCK.value


@contextmanager
def session_transition_lock():
    """Serialize one short state transition; never hold this for a session."""
    _state_path, lock_path = _state_paths()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _require_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise TestSessionStateError(f"Test-session state has invalid {name}.")
    return value


def _validate_process_identity(value, name):
    if not isinstance(value, dict):
        raise TestSessionStateError(f"Test-session state has invalid {name}.")
    required = {"pid", "pgid", "boot_id", "started", "command_sha256"}
    if set(value) != required:
        raise TestSessionStateError(f"Test-session state has invalid {name} fields.")
    if not isinstance(value["pid"], int) or value["pid"] <= 0:
        raise TestSessionStateError(f"Test-session state has invalid {name} PID.")
    if not isinstance(value["pgid"], int) or value["pgid"] <= 0:
        raise TestSessionStateError(f"Test-session state has invalid {name} PGID.")
    for field in ("boot_id", "started", "command_sha256"):
        _require_string(value[field], f"{name}.{field}")
    return value


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_corrupt_session_state_fails_closed
# @matrix test-session : corrupt-state fail-closed schema
def validate_session_state(value):
    """Return a strict local state record or fail closed."""
    if not isinstance(value, dict):
        raise TestSessionStateError("Test-session state must be a JSON object.")
    if set(value) != SESSION_STATE_FIELDS:
        raise TestSessionStateError("Test-session state fields are unsupported.")
    if value.get("schema_version") != SESSION_SCHEMA_VERSION:
        raise TestSessionStateError("Test-session state schema is unsupported.")
    if value.get("mode") not in SESSION_MODES:
        raise TestSessionStateError("Test-session state has an invalid mode.")
    if value.get("phase") not in SESSION_PHASES:
        raise TestSessionStateError("Test-session state has an invalid phase.")
    for field in (
        "nonce",
        "created_at",
        "heartbeat_at",
        "repository",
        "base_url",
        "command",
        "recovery_hint",
    ):
        _require_string(value.get(field), field)
    if not isinstance(value.get("port"), int) or value["port"] <= 0:
        raise TestSessionStateError("Test-session state has an invalid port.")
    namespace = value.get("data_namespace")
    if not isinstance(namespace, dict) or set(namespace) != {"project", "prefix"}:
        raise TestSessionStateError("Test-session data namespace is invalid.")
    _require_string(namespace.get("project"), "data_namespace.project")
    _require_string(namespace.get("prefix"), "data_namespace.prefix")
    artifacts = value.get("artifact_namespaces")
    if not isinstance(artifacts, list) or not all(
        isinstance(path, str) and path for path in artifacts
    ):
        raise TestSessionStateError("Test-session artifact namespaces are invalid.")
    _validate_process_identity(value.get("owner"), "owner")
    for field in ("keeper", "server", "attachment"):
        process = value.get(field)
        if process is not None:
            if field == "attachment":
                if not isinstance(process, dict) or set(process) != {
                    "id",
                    "command",
                    "created_at",
                    "process",
                }:
                    raise TestSessionStateError(
                        "Test-session browser attachment is invalid."
                    )
                _require_string(process["id"], "attachment.id")
                _require_string(process["command"], "attachment.command")
                _require_string(process["created_at"], "attachment.created_at")
                _validate_process_identity(process["process"], "attachment.process")
            else:
                _validate_process_identity(process, field)
    return value


def load_session_state(*, strict=True):
    state_path, _lock_path = _state_paths()
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        if strict:
            raise TestSessionStateError(
                f"Cannot read valid test-session state at {state_path}."
            ) from error
        return None
    return validate_session_state(value) if strict else value


def write_session_state(state):
    validate_session_state(state)
    state_path, _lock_path = _state_paths()
    _atomic_write_text(
        state_path,
        f"{json.dumps(state, indent=2, sort_keys=True)}\n",
        owner_only=True,
    )


def remove_session_state(nonce):
    state_path, _lock_path = _state_paths()
    with session_transition_lock():
        state = load_session_state()
        if state is None:
            return False
        if state["nonce"] != nonce:
            raise TestSessionBusy(_busy_message(state))
        state_path.unlink(missing_ok=True)
        return True


def _ps_value(pid: int, field: str) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", f"{field}="],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TestSessionStateError(
            f"Could not inspect process {pid} with POSIX ps ({error})."
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip()
        if detail:
            raise PermissionError(detail)
        return None
    value = " ".join(result.stdout.split())
    return value or None


def _boot_identity() -> str:
    started = _ps_value(1, "lstart")
    if not started:
        raise TestSessionStateError("Could not determine the current boot identity.")
    return hashlib.sha256(started.encode("utf-8")).hexdigest()


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_process_identity_rejects_reused_pid
# @tests tests_tooling/test_005_test_session.py::test_capture_process_identity_uses_portable_ps_fingerprint
# @matrix test-session : command-fingerprint pid-reuse portability process-start
def capture_process_identity(pid: int) -> dict | None:
    """Capture portable identity fields that distinguish PID reuse."""
    pid_value = _ps_value(int(pid), "pid")
    if pid_value is None:
        return None
    pgid = _ps_value(int(pid), "pgid")
    started = _ps_value(int(pid), "lstart")
    command = _ps_value(int(pid), "command")
    if not pgid or not started or not command:
        raise TestSessionStateError(f"Process {pid} identity is incomplete.")
    if _ps_value(int(pid), "lstart") != started:
        raise TestSessionStateError(
            f"Process {pid} changed while its identity was inspected."
        )
    return {
        "pid": int(pid_value),
        "pgid": int(pgid),
        "boot_id": _boot_identity(),
        "started": started,
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
    }


def inspect_process_identity(expected: dict) -> str:
    """Return match, missing, mismatch, or unknown for a recorded process."""
    _validate_process_identity(expected, "process")
    try:
        current = capture_process_identity(expected["pid"])
    except (PermissionError, TestSessionStateError):
        return "unknown"
    if current is None:
        return "missing"
    return "match" if current == expected else "mismatch"


def _configured_namespace():
    test_config = SETTINGS.test_config
    project = str(
        test_config.get("GOOGLE_CLOUD_PROJECT")
        or SETTINGS.GCLOUD_CONFIG.get("PROJECT")
        or ""
    ).strip()
    prefix = str(test_config.get("PREFIX") or "").strip()
    if not project or not prefix:
        raise TestSessionStateError(
            "Test-session ownership requires configured project and prefix values."
        )
    return {"project": project, "prefix": prefix}


def _configured_port():
    try:
        return int(SETTINGS.test_config["SERVER_PORT"])
    except (KeyError, TypeError, ValueError) as error:
        raise TestSessionStateError("Testing SERVER_PORT must be an integer.") from error


def _new_owned_data_lease(nonce):
    from lagniappe.core.tools.hosted_e2e.lease import E2ELease

    return E2ELease(run_id=nonce)


def _new_adopted_data_lease(nonce):
    from lagniappe.core.tools.hosted_e2e.lease import E2ELeaseHeartbeat

    return E2ELeaseHeartbeat(nonce)


def _busy_message(state):
    return (
        "Another local test session owns this checkout "
        f"(mode={state['mode']}, phase={state['phase']}, "
        f"pid={state['owner']['pid']}, command={state['command']!r}). "
        f"If it is stale, run `{state['recovery_hint']}`."
    )


@dataclass
class TestSessionAuthority:
    """Owned local state plus the matching cross-machine data lease."""

    nonce: str
    mode: str
    owner: dict
    data_lease: object
    _heartbeat_stop: threading.Event
    _heartbeat_lost: threading.Event
    _heartbeat_thread: threading.Thread | None
    _handed_off: bool = False

    def assert_local_active(self, *, phases=None):
        if self._heartbeat_lost.is_set():
            raise TestSessionStateError("The local test-session heartbeat was lost.")
        with session_transition_lock():
            state = load_session_state()
            if state is None or state["nonce"] != self.nonce:
                raise TestSessionStateError("Local test-session ownership was lost.")
            if state["mode"] != self.mode:
                raise TestSessionStateError("Local test-session mode changed.")
            if state["owner"] != self.owner:
                raise TestSessionStateError("Local test-session owner changed.")
            if phases and state["phase"] not in set(phases):
                raise TestSessionStateError(
                    f"Test session is {state['phase']!r}, not ready for this operation."
                )
        return state

    def assert_active(self, *, phases=None):
        state = self.assert_local_active(phases=phases)
        self.data_lease.assert_active()
        return state

    def update(self, **changes):
        with session_transition_lock():
            state = load_session_state()
            if state is None or state["nonce"] != self.nonce:
                raise TestSessionStateError("Local test-session ownership was lost.")
            if state["owner"] != self.owner:
                raise TestSessionStateError("Local test-session owner changed.")
            state.update(changes)
            state["heartbeat_at"] = utc_now()
            write_session_state(state)
            return state

    def mark_recovery_required(self):
        try:
            return self.update(phase="recovery-required")
        except TestSessionError:
            return None

    def handoff(self, owner):
        _validate_process_identity(owner, "handoff owner")
        self.assert_active()
        with session_transition_lock():
            state = load_session_state()
            if state is None or state["nonce"] != self.nonce:
                raise TestSessionStateError("Local test-session ownership was lost.")
            if state["owner"] != self.owner:
                raise TestSessionStateError("Local test-session owner changed.")
            state["owner"] = owner
            state["phase"] = "ready"
            state["heartbeat_at"] = utc_now()
            write_session_state(state)
        self._stop_local_heartbeat()
        self.data_lease.handoff()
        self._handed_off = True
        return state

    def complete(self):
        self.assert_active()
        self._stop_local_heartbeat()
        self.data_lease.__exit__(None, None, None)
        remove_session_state(self.nonce)

    def rollback_without_cleanup(self):
        """Release a session that has not crossed a destructive boundary."""
        self._stop_local_heartbeat()
        self.data_lease.__exit__(None, None, None)
        remove_session_state(self.nonce)

    def _stop_local_heartbeat(self):
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2)
        self._heartbeat_thread = None


def _heartbeat_owned_state(authority):
    while not authority._heartbeat_stop.wait(HEARTBEAT_SECONDS):
        try:
            authority.data_lease.assert_active()
            authority.update()
        except Exception:
            authority._heartbeat_lost.set()
            return


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_two_subprocess_starts_produce_one_owner
# @tests tests_tooling/test_005_test_session.py::test_busy_session_stops_before_mutation
# @matrix test-session : concurrency durable-state mutation-order ownership preflight subprocess
def acquire_test_session(
    mode: str,
    command,
    *,
    data_lease_factory: Callable[[str], object] = _new_owned_data_lease,
) -> TestSessionAuthority:
    """Publish a durable local owner, then acquire the shared data lease."""
    if mode not in SESSION_MODES:
        raise ValueError(f"Unsupported test-session mode {mode!r}.")
    owner = capture_process_identity(os.getpid())
    if owner is None:
        raise TestSessionStateError("Could not identify the test-session owner.")
    nonce = secrets.token_urlsafe(32)
    base_url = str(SETTINGS.test_config["BASE_URL"])
    command_text = (
        format_command(command) if isinstance(command, (list, tuple)) else str(command)
    )
    state = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "nonce": nonce,
        "mode": mode,
        "phase": "acquiring",
        "created_at": utc_now(),
        "heartbeat_at": utc_now(),
        "repository": str(APP_DIR),
        "base_url": base_url,
        "port": _configured_port(),
        "data_namespace": _configured_namespace(),
        "artifact_namespaces": [
            str(Directory.TEST_FAILURES.value),
            str(Directory.TEST_REPORTS.value),
        ],
        "command": command_text,
        "recovery_hint": RECOVERY_COMMAND,
        "owner": owner,
        "keeper": None,
        "server": None,
        "attachment": None,
    }
    with session_transition_lock():
        existing = load_session_state()
        if existing is not None:
            raise TestSessionBusy(_busy_message(existing))
        write_session_state(state)

    lease = data_lease_factory(nonce)
    try:
        lease.__enter__()
    except BaseException:
        remove_session_state(nonce)
        raise

    stop_event = threading.Event()
    lost_event = threading.Event()
    authority = TestSessionAuthority(
        nonce=nonce,
        mode=mode,
        owner=owner,
        data_lease=lease,
        _heartbeat_stop=stop_event,
        _heartbeat_lost=lost_event,
        _heartbeat_thread=None,
    )
    thread = threading.Thread(
        target=_heartbeat_owned_state,
        args=(authority,),
        name="lagniappe-test-session-state",
        daemon=True,
    )
    authority._heartbeat_thread = thread
    try:
        thread.start()
        authority.update(phase="starting")
        return authority
    except BaseException:
        authority._stop_local_heartbeat()
        lease.__exit__(None, None, None)
        remove_session_state(nonce)
        raise


def authority_from_environment(*, expected_mode="local-e2e"):
    nonce = str(os.environ.get(SESSION_NONCE_ENV) or "").strip()
    mode = str(os.environ.get(SESSION_MODE_ENV) or "").strip()
    if not nonce or mode != expected_mode:
        raise TestSessionStateError(
            "Local E2E requires runner-owned test-session authority. "
            "Use `venv/bin/python run.py test ...`."
        )
    with session_transition_lock():
        state = load_session_state()
        if state is None or state["nonce"] != nonce or state["mode"] != mode:
            raise TestSessionStateError("Inherited test-session authority is stale.")
        if state["phase"] != "ready" or state.get("server") is None:
            raise TestSessionStateError("Inherited test-session is not ready.")
        if inspect_process_identity(state["owner"]) != "match":
            raise TestSessionStateError("Inherited test-session owner is not live.")
        if inspect_process_identity(state["server"]) != "match":
            raise TestSessionStateError("Inherited Flask server identity is not live.")
    adopter = _new_adopted_data_lease(nonce)
    adopter.__enter__()
    return state, adopter


def update_state_for_nonce(nonce, **changes):
    with session_transition_lock():
        state = load_session_state()
        if state is None or state["nonce"] != nonce:
            raise TestSessionStateError("Test-session state no longer matches keeper.")
        state.update(changes)
        state["heartbeat_at"] = utc_now()
        write_session_state(state)
        return state


def _terminate_child(process, timeout=15):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_managed_keeper() -> int:
    """Own a detached managed-server process group and its lease heartbeat."""
    nonce = str(os.environ.get(SESSION_NONCE_ENV) or "").strip()
    mode = str(os.environ.get(SESSION_MODE_ENV) or "").strip()
    if not nonce or mode != "managed-server":
        print("Managed test-session keeper received invalid authority.", file=sys.stderr)
        return 2

    identity = None
    deadline = monotonic() + 10
    while monotonic() < deadline:
        try:
            state = load_session_state()
        except TestSessionError:
            state = None
        if state and state["nonce"] == nonce and state.get("keeper"):
            if state["keeper"]["pid"] == os.getpid():
                identity = state["keeper"]
                break
        sleep(0.05)
    if identity is None or inspect_process_identity(identity) != "match":
        print("Managed test-session keeper was not registered.", file=sys.stderr)
        return 2

    from runner.testing import (
        _launch_test_server,
        terminate_test_server_process,
        wait_for_session_server,
    )

    stop_event = threading.Event()

    def request_stop(_signum, _frame):
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)

    adopter = _new_adopted_data_lease(nonce)
    process = None
    try:
        adopter.__enter__()
        Directory.REPORTS.create()
        with File.MANAGED_TEST_SERVER_LOG.value.open(
            "a", encoding="utf-8", buffering=1
        ) as log_file:
            log_file.write("\n--- Starting managed test server ---\n")
            process = _launch_test_server(
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=False,
                session_nonce=nonce,
                session_mode=mode,
            )
        server = capture_process_identity(process.pid)
        if server is None:
            raise TestSessionStateError("Managed Flask process exited during launch.")
        update_state_for_nonce(nonce, server=server)
        if not wait_for_session_server(
            SETTINGS.test_config["BASE_URL"],
            nonce,
            expected_pid=process.pid,
            expected_mode=mode,
        ):
            raise TestSessionStateError("Managed Flask process failed nonce readiness.")
        update_state_for_nonce(nonce, server=server)

        next_heartbeat = monotonic()
        while not stop_event.is_set():
            exit_code = process.poll()
            if exit_code is not None:
                raise TestSessionStateError(
                    f"Managed Flask process exited unexpectedly ({exit_code})."
                )
            if monotonic() >= next_heartbeat:
                adopter.assert_active()
                state = update_state_for_nonce(nonce)
                if state.get("keeper") != identity:
                    raise TestSessionStateError("Managed keeper identity changed.")
                if state["phase"] == "ready" and state["owner"] != identity:
                    raise TestSessionStateError("Managed keeper lost local ownership.")
                if (
                    state["phase"] in {"starting", "seeding"}
                    and state["owner"] != identity
                    and inspect_process_identity(state["owner"]) != "match"
                ):
                    raise TestSessionStateError(
                        "Managed startup owner exited before ownership handoff."
                    )
                next_heartbeat = monotonic() + HEARTBEAT_SECONDS
            stop_event.wait(0.5)
        return 0
    except BaseException as error:
        try:
            state = load_session_state()
            if state and state["nonce"] == nonce and state["phase"] != "stopping":
                update_state_for_nonce(nonce, phase="recovery-required")
        except Exception:
            pass
        print(f"Managed test-session keeper stopped: {error}", file=sys.stderr)
        return 1
    finally:
        if process is not None:
            try:
                terminate_test_server_process(process)
            except Exception:
                _terminate_child(process, timeout=2)
        if adopter is not None:
            adopter.__exit__(None, None, None)


def main(arguments=None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments == ["keeper"]:
        return run_managed_keeper()
    print("Usage: python -m runner.test_session keeper", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RECOVERY_COMMAND",
    "SESSION_MODE_ENV",
    "SESSION_NONCE_ENV",
    "TestSessionAuthority",
    "TestSessionBusy",
    "TestSessionError",
    "TestSessionStateError",
    "acquire_test_session",
    "authority_from_environment",
    "capture_process_identity",
    "inspect_process_identity",
    "load_session_state",
    "remove_session_state",
    "session_transition_lock",
    "update_state_for_nonce",
    "validate_session_state",
]
