import copy
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlparse

from runner.context import GCLOUD_CLI, NPM_CLI
from config import APP_DIR, Directory, Environment, File, SETTINGS
from config.constants import DEFAULT_TEST_PREFIX
from runner.gcloud import activate_repository_gcloud
from runner.frontend_build import (
    FilesystemFrontendBuildReader,
    inspect_frontend_build,
)
from runner.process import run_command

# Cursor/agent sandboxes may set PLAYWRIGHT_BROWSERS_PATH to an empty cache.
# Prefer the normal user install when it exists.
_DEFAULT_PLAYWRIGHT_BROWSERS = Path.home() / ".cache/ms-playwright"
if _DEFAULT_PLAYWRIGHT_BROWSERS.is_dir():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_DEFAULT_PLAYWRIGHT_BROWSERS)


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_hosted_e2e_runner_skips_local_build_and_gcloud_activation
# @matrix hosted-e2e testing : frontend-build provider-auth
def hosted_e2e_enabled():
    """Return whether this process is the managed hosted-E2E runner."""
    return os.environ.get("LAGNIAPPE_HOSTED_E2E", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


# Patterns to filter from test server output (static files, etc.)
FILTERED_PATTERNS = re.compile(
    r'"GET /(?:'
    r"chunks/|"
    r"fonts/|"
    r"images/|"
    r"style\.css|"
    r"script\.js|"
    r"token|"
    r"update-session|"
    r"validate-user|"
    r"identity-config|"
    r"sw\.js|"
    r".*\.woff2|"
    r".*\.png|"
    r".*\.ico"
    r')[^"]*"'
)

_TEST_FRONTEND_BUNDLE_SCHEMA = 2
_TEST_FRONTEND_BUNDLE_STATE = Directory.REPORTS.value / "test-frontend-bundle.json"
_TEST_FRONTEND_INPUT_ROOTS = (
    Path("THIRD_PARTY_LICENSES"),
    Path("build"),
    Path("src/fonts"),
    Path("src/script"),
    Path("src/style"),
)
_TEST_FRONTEND_INPUT_FILES = (
    Path("config/browser_protocol.json"),
    Path("config/files/lagniappe_settings.yaml"),
    Path("package.json"),
    Path("package-lock.json"),
    Path("node_modules/.package-lock.json"),
)


# @testable false
# @covered-by runner/testing.py::ensure_test_frontend_bundle
# @reason private deterministic source/config fingerprint for the test-server build preflight
def _test_frontend_input_fingerprint():
    digest = hashlib.sha256(f"test-frontend-v{_TEST_FRONTEND_BUNDLE_SCHEMA}".encode())

    for relative_root in _TEST_FRONTEND_INPUT_ROOTS:
        root = APP_DIR / relative_root
        digest.update(f"root:{relative_root.as_posix()}\0".encode())
        if not root.is_dir():
            digest.update(b"missing\0")
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(APP_DIR).as_posix()
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")

    for relative in _TEST_FRONTEND_INPUT_FILES:
        path = APP_DIR / relative
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"missing")
        digest.update(b"\0")

    return digest.hexdigest()


# @testable false
# @covered-by runner/testing.py::ensure_test_frontend_bundle
# @reason private tolerant state reader treats missing or malformed local metadata as stale
def _read_test_frontend_bundle_state():
    try:
        state = json.loads(
            _TEST_FRONTEND_BUNDLE_STATE.read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return state if isinstance(state, dict) else None


# @testable false
# @covered-by runner/testing.py::ensure_test_frontend_bundle
# @reason shared validator adapter for the managed test-server preflight
def _inspect_test_frontend_bundle(*, expected_mode=None):
    return inspect_frontend_build(
        FilesystemFrontendBuildReader(APP_DIR),
        expected_mode=expected_mode,
        expected_version=str(SETTINGS.APP["VERSION"]),
    )


# @testable true
# @tests tests_tooling/test_005_test_server_command.py::test_test_frontend_bundle_skips_current_build
# @tests tests_tooling/test_005_test_server_command.py::test_test_frontend_bundle_rebuilds_stale_build
# @tests tests_tooling/test_005_test_server_command.py::test_test_frontend_bundle_preserves_current_production_build
# @tests tests_tooling/test_005_test_server_command.py::test_test_frontend_bundle_replaces_stale_production_build
# @matrix frontend-build : freshness no-op output-validation production-preservation rebuild
# @pair test-server:freshness
def ensure_test_frontend_bundle(authority):
    """Build development assets when test-server inputs or outputs changed."""
    authority.assert_active()
    validation, issues = _inspect_test_frontend_bundle()
    output_fingerprint = (
        validation.output_fingerprint if validation is not None else None
    )
    if validation is not None and validation.metadata["mode"] == "production":
        print(
            "Current production frontend bundle detected; preserving it.",
            flush=True,
        )
        return False

    input_fingerprint = _test_frontend_input_fingerprint()
    state = _read_test_frontend_bundle_state()
    if output_fingerprint is not None and state == {
        "schema": _TEST_FRONTEND_BUNDLE_SCHEMA,
        "inputs": input_fingerprint,
        "outputs": output_fingerprint,
    }:
        return False

    if issues:
        print(
            f"Frontend test bundle is stale ({issues[0]}); running npm run dev.",
            flush=True,
        )
    else:
        print("Frontend test bundle is stale; running npm run dev.", flush=True)
    authority.assert_active()
    try:
        result = subprocess.run(
            [NPM_CLI, "run", "dev"],
            cwd=APP_DIR,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "npm is required to build the frontend test bundle."
        ) from error
    if result.returncode != 0:
        raise RuntimeError(
            f"Frontend test bundle build failed with exit code {result.returncode}."
        )
    authority.assert_active()

    validation, issues = _inspect_test_frontend_bundle(expected_mode="development")
    if validation is None:
        detail = issues[0] if issues else "unknown publication error"
        raise RuntimeError(
            "Frontend test bundle build completed without a valid development "
            f"publication: {detail}"
        )
    output_fingerprint = validation.output_fingerprint

    Directory.REPORTS.create()
    state = {
        "schema": _TEST_FRONTEND_BUNDLE_SCHEMA,
        "inputs": input_fingerprint,
        "outputs": output_fingerprint,
    }
    temporary = _TEST_FRONTEND_BUNDLE_STATE.with_suffix(".tmp")
    temporary.write_text(
        f"{json.dumps(state, indent=2)}\n",
        encoding="utf-8",
    )
    temporary.replace(_TEST_FRONTEND_BUNDLE_STATE)
    authority.assert_active()
    return True


def prepare_test_artifacts(authority):
    """Reset generated E2E artifact directories before a test-server run."""
    authority.assert_active()
    for artifact_dir in [Directory.TEST_FAILURES, Directory.TEST_REPORTS]:
        artifact_dir.clean()
        artifact_dir.get_or_create()
    authority.assert_active()


# @testable infrastructure
# @reason live test-index deployment is an operator-only provider boundary
def update_test_indexes():
    index_data = File.INDEX_YAML.load()
    indexes = index_data["indexes"]

    try:
        test_indexes = []
        for index in indexes:
            test_index = copy.deepcopy(index)
            if "kind" in test_index:
                test_index["kind"] = f"test-{test_index['kind']}"
            test_indexes.append(test_index)

        combined = {"indexes": indexes + test_indexes}

        File.INDEX_YAML.save(combined)

        run_command(
            [GCLOUD_CLI, "app", "deploy", File.INDEX_YAML.value, "--quiet"],
            check=True,
        )

    finally:
        File.INDEX_YAML.save(index_data)


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_wait_for_session_server_requires_exact_nonce_and_pid
# @tests tests_tooling/test_005_test_server_command.py::test_wait_for_session_server_allows_slow_local_startup
# @tests tests_tooling/test_005_test_server_command.py::test_wait_for_session_server_bounds_stalled_requests_by_one_deadline
# @tests tests_tooling/test_005_test_server_command.py::test_wait_for_session_server_reports_last_http_state
# @matrix test-session : deadline diagnostics health-nonce http-state process-identity readiness slow-start stalled-response
def wait_for_session_server(
    base_url,
    nonce,
    *,
    expected_pid,
    expected_mode,
    timeout_seconds=20.0,
    report_timeout=True,
):
    """Wait for the exact Flask process owned by a test session."""
    import requests

    deadline = monotonic() + timeout_seconds
    last_state = "no response"
    expected = {
        "ready": True,
        "mode": expected_mode,
        "session_nonce": nonce,
        "pid": expected_pid,
    }
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0.01:
            break
        connect_timeout = min(0.5, remaining / 2)
        read_timeout = min(2.0, remaining - connect_timeout)
        try:
            response = requests.get(
                f"{base_url}/testing/health",
                timeout=(connect_timeout, read_timeout),
            )
            if response.status_code != 200:
                last_state = f"HTTP {response.status_code}"
            else:
                try:
                    actual = response.json()
                except ValueError:
                    last_state = "invalid JSON"
                else:
                    if actual == expected:
                        return True
                    last_state = f"identity mismatch ({actual!r})"
        except requests.RequestException as error:
            last_state = type(error).__name__

        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(0.5, remaining))

    if report_timeout:
        print(
            f"Server readiness timed out after {timeout_seconds:g}s "
            f"(last state: {last_state})."
        )
    return False


def _server_port_in_use(base_url):
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port

    if not port:
        return False

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            return sock.connect_ex((host, port)) == 0
    except OSError as error:
        raise RuntimeError(
            f"Could not inspect configured test-server port {port}: {error}."
        ) from error


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_occupied_port_is_refused_without_signaling
# @matrix test-session : cross-platform fail-closed port-ownership
def require_server_port_available(base_url):
    """Refuse an occupied port; a listener is never ownership evidence."""
    if _server_port_in_use(base_url):
        parsed = urlparse(base_url)
        raise RuntimeError(
            f"Test server port {parsed.port} is occupied by an unverified process. "
            "No process was signaled."
        )


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_live_legacy_pid_is_refused_without_signaling
# @matrix test-session : legacy-migration pid-reuse signal-safety
def require_legacy_test_server_clear():
    """Retire only a dead legacy PID file; never trust it for signaling."""
    from runner.test_session import RECOVERY_COMMAND, capture_process_identity

    path = File.MANAGED_TEST_SERVER_PID.value
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return False
    except ValueError as error:
        raise RuntimeError(
            f"Legacy test-server PID file is malformed. Run `{RECOVERY_COMMAND}`."
        ) from error

    if capture_process_identity(pid) is not None:
        raise RuntimeError(
            "A live process matches the legacy test-server PID, but legacy state "
            "cannot prove ownership. No process was signaled; run "
            f"`{RECOVERY_COMMAND}` after it exits."
        )
    require_server_port_available(SETTINGS.test_config["BASE_URL"])
    path.unlink(missing_ok=True)
    return True


def _filter_server_output(pipe, stream):
    """Filter and forward server output, hiding static file requests."""
    for line in iter(pipe.readline, b""):
        try:
            decoded = line.decode("utf-8", errors="replace")
            if not FILTERED_PATTERNS.search(decoded):
                stream.write(decoded)
                stream.flush()
        except Exception:
            pass
    pipe.close()


def _configure_test_gcloud():
    os.environ["FLASK_ENV"] = Environment.TESTING.value
    if hosted_e2e_enabled():
        return
    activate_repository_gcloud(
        ensure_adc=True,
        allow_runtime_adc=True,
        allow_adc_login=False,
    )


def _test_server_command():
    return [
        sys.executable,
        "-m",
        "flask",
        "--app",
        "main.py",
        "run",
        "--port",
        SETTINGS.test_config["SERVER_PORT"],
    ]


def _test_server_env(session_nonce, session_mode):
    from runner.test_session import SESSION_MODE_ENV, SESSION_NONCE_ENV

    return {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "FLASK_ENV": Environment.TESTING.value,
        SESSION_NONCE_ENV: session_nonce,
        SESSION_MODE_ENV: session_mode,
    }


def _launch_test_server(
    stdout,
    stderr,
    *,
    session_nonce,
    session_mode,
    start_new_session=False,
):
    return subprocess.Popen(
        _test_server_command(),
        cwd=APP_DIR,
        stdout=stdout,
        stderr=stderr,
        env=_test_server_env(session_nonce, session_mode),
        start_new_session=start_new_session,
    )


# @testable infrastructure
def run_test_server(authority):
    """Launch and verify the local E2E Flask child for an active owner."""
    authority.assert_active(phases={"starting"})
    base_url = SETTINGS.test_config["BASE_URL"]
    require_server_port_available(base_url)

    process = _launch_test_server(
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        session_nonce=authority.nonce,
        session_mode=authority.mode,
        start_new_session=True,
    )
    try:
        from runner.test_session import capture_process_identity

        server = capture_process_identity(process.pid)
        if server is None:
            raise RuntimeError("Test server exited before its identity was recorded.")
        authority.update(server=server)

        stdout_thread = threading.Thread(
            target=_filter_server_output,
            args=(process.stdout, sys.stdout),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_filter_server_output,
            args=(process.stderr, sys.stderr),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        if not wait_for_session_server(
            base_url,
            authority.nonce,
            expected_pid=process.pid,
            expected_mode=authority.mode,
        ):
            exit_code = process.poll()
            if exit_code is not None:
                raise RuntimeError(
                    "Test server exited before becoming healthy "
                    f"(exit code {exit_code})."
                )
            raise RuntimeError("Test server failed nonce-bound readiness")

        return process
    except BaseException:
        if process.poll() is None:
            terminate_test_server_process(process, timeout=5)
        else:
            process.wait()
        raise


def terminate_test_server_process(process, timeout=15):
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_cleanup_scope_requires_the_reserved_test_prefix
# @matrix hosted-e2e testing : cleanup fail-closed prefix
def _require_test_cleanup_scope(config):
    if not config.testing or config.PREFIX != DEFAULT_TEST_PREFIX:
        raise RuntimeError(
            "Refusing test cleanup outside the reserved test- data prefix."
        )


# @testable infrastructure
def cleanup_test_data(authority):
    """Clear the reserved test namespace only for the active lease owner."""
    authority.assert_active()
    os.environ["FLASK_ENV"] = Environment.TESTING.value
    _configure_test_gcloud()

    from lagniappe import CONFIG

    _require_test_cleanup_scope(CONFIG)
    from lagniappe.core.tools import cache
    from lagniappe.core.tools.database import utility as database_utility

    database_utility.cleanup_test_data()
    cache.cleanup_test_data()
    authority.assert_active()


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_initialize_test_services_replays_server_persistence_startup
# @matrix hosted-e2e testing : cache database initialization migrations
def _initialize_test_services(database, cache, migrations):
    """Replay the persistence portion of application startup after cleanup."""
    cache.initialize()
    fresh_install = database.initialize()
    migrations.initialize_fresh_install(fresh_install)
    return fresh_install


# @testable infrastructure
# @matrix hosted-e2e testing : cleanup initialization
def initialize_test_data(authority):
    """Seed clean test persistence without starting another Flask process."""
    authority.assert_active()
    os.environ["FLASK_ENV"] = Environment.TESTING.value
    _configure_test_gcloud()

    from lagniappe import CONFIG

    _require_test_cleanup_scope(CONFIG)
    from lagniappe.core.tools import cache
    from lagniappe.core.tools.database import migrations, utility as database_utility

    result = _initialize_test_services(database_utility, cache, migrations)
    authority.assert_active()
    return result


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_reused_recorded_pid_is_never_signaled
# @matrix test-session : pid-reuse signal-safety
def _terminate_verified_process_group(identity, timeout=15):
    """Signal only a still-matching, session-leading recorded process."""
    from runner.test_session import inspect_process_identity

    status = inspect_process_identity(identity)
    if status == "missing" or status == "mismatch":
        return False
    if status != "match":
        raise RuntimeError("Recorded test-session process cannot be inspected safely.")
    if identity["pid"] != identity["pgid"]:
        raise RuntimeError("Recorded test-session owner is not a process-group leader.")
    os.killpg(identity["pgid"], signal.SIGTERM)
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        status = inspect_process_identity(identity)
        if status in {"missing", "mismatch"}:
            return True
        if status == "unknown":
            raise RuntimeError("Lost permission to inspect the test-session owner.")
        sleep(0.2)
    if inspect_process_identity(identity) != "match":
        return True
    os.killpg(identity["pgid"], signal.SIGKILL)
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if inspect_process_identity(identity) in {"missing", "mismatch"}:
            return True
        sleep(0.2)
    raise RuntimeError(
        f"Could not stop verified test-session process {identity['pid']}."
    )


def _session_matches_configuration(state):
    from runner.test_session import _configured_namespace, _configured_port

    return (
        state["repository"] == str(APP_DIR)
        and state["base_url"] == str(SETTINGS.test_config["BASE_URL"])
        and state["port"] == _configured_port()
        and state["data_namespace"] == _configured_namespace()
    )


def _wait_for_managed_keeper(authority, process, timeout=25):
    from runner.test_session import inspect_process_identity, load_session_state

    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "Managed test-session keeper exited during startup. "
                f"See {File.MANAGED_TEST_SERVER_LOG.value}."
            )
        state = load_session_state()
        if state and state["nonce"] == authority.nonce and state.get("server"):
            server = state["server"]
            if inspect_process_identity(server) == "match" and wait_for_session_server(
                state["base_url"],
                authority.nonce,
                expected_pid=server["pid"],
                expected_mode="managed-server",
                timeout_seconds=min(1, max(0.1, deadline - monotonic())),
                report_timeout=False,
            ):
                return state
        sleep(0.1)
    raise RuntimeError(
        "Managed test server failed nonce-bound readiness. "
        f"See {File.MANAGED_TEST_SERVER_LOG.value}."
    )


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_managed_start_conflict_stops_before_mutation
# @matrix test-session : managed-start mutation-order ownership
def start_managed_test_server(load_packs=()):
    """Start a detached keeper and explicitly hand it session ownership."""
    _configure_test_gcloud()
    from runner.test_session import (
        SESSION_MODE_ENV,
        SESSION_NONCE_ENV,
        acquire_test_session,
        capture_process_identity,
    )

    require_legacy_test_server_clear()
    authority = acquire_test_session(
        "managed-server",
        [sys.executable, str(APP_DIR / "run.py"), "test-server", "--start"],
    )
    base_url = SETTINGS.test_config["BASE_URL"]
    process = None
    keeper = None
    crossed_data_boundary = False
    try:
        require_server_port_available(base_url)
        ensure_test_frontend_bundle(authority)
        prepare_test_artifacts(authority)
        crossed_data_boundary = True
        cleanup_test_data(authority)
        Directory.REPORTS.create()
        environment = {
            **os.environ,
            SESSION_NONCE_ENV: authority.nonce,
            SESSION_MODE_ENV: authority.mode,
        }
        with File.MANAGED_TEST_SERVER_LOG.value.open(
            "a", encoding="utf-8", buffering=1
        ) as log_file:
            process = subprocess.Popen(
                [sys.executable, "-m", "runner.test_session", "keeper"],
                cwd=APP_DIR,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=environment,
                start_new_session=True,
            )
        keeper = capture_process_identity(process.pid)
        if keeper is None:
            raise RuntimeError("Managed test-session keeper exited during launch.")
        authority.update(keeper=keeper)
        state = _wait_for_managed_keeper(authority, process)

        summary = None
        if load_packs:
            authority.update(phase="seeding")
            from testing.utility import test_server_seed

            summary = test_server_seed.load_packs(load_packs, authority)
        authority.handoff(keeper)
        return {
            "pid": state["server"]["pid"],
            "keeper_pid": keeper["pid"],
            "nonce": authority.nonce,
            "seed_summary": summary,
        }
    except BaseException:
        try:
            authority.update(phase="stopping")
        except Exception:
            pass
        if process is not None:
            if keeper is None and process.poll() is None:
                authority.mark_recovery_required()
                raise
            try:
                if keeper is not None:
                    _terminate_verified_process_group(keeper, timeout=5)
            except Exception:
                authority.mark_recovery_required()
                raise
        try:
            if crossed_data_boundary:
                cleanup_test_data(authority)
            authority.complete()
        except Exception:
            authority.mark_recovery_required()
            raise
        raise


def _verified_managed_state(*, require_live=True):
    from runner.test_session import inspect_process_identity, load_session_state

    state = load_session_state()
    if state is None:
        return None
    if state["mode"] != "managed-server":
        raise RuntimeError(
            "The active local test session is not a managed server; refusing action."
        )
    if not _session_matches_configuration(state):
        raise RuntimeError("Test-session state does not match this checkout/configuration.")
    attachment = state.get("attachment")
    if attachment:
        attachment_status = inspect_process_identity(attachment["process"])
        if attachment_status in {"match", "unknown"}:
            raise RuntimeError(
                f"Browser review attachment {attachment['id']} is still active "
                "or cannot be inspected safely."
            )
    if state.get("keeper") != state["owner"]:
        raise RuntimeError("Managed test-session keeper is not the recorded owner.")
    if require_live:
        for field in ("owner", "server"):
            if not state.get(field) or inspect_process_identity(state[field]) != "match":
                raise RuntimeError(
                    f"Managed test-session {field} identity cannot be verified. "
                    f"Run `{state['recovery_hint']}` after it exits."
                )
        if not wait_for_session_server(
            state["base_url"],
            state["nonce"],
            expected_pid=state["server"]["pid"],
            expected_mode=state["mode"],
            timeout_seconds=2,
        ):
            raise RuntimeError("Managed server health does not prove session ownership.")
        from lagniappe.core.tools.hosted_e2e.lease import current_e2e_lease

        if current_e2e_lease() != state["nonce"]:
            raise RuntimeError("Managed server no longer owns the shared data lease.")
    return state


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_managed_teardown_cannot_touch_local_e2e_owner
# @tests tests_tooling/test_005_test_session.py::test_managed_teardown_refuses_live_browser_attachment
# @matrix test-session : browser-attachment mode-isolation teardown
def teardown_managed_test_server():
    """Stop and clean only a fully verified managed-server session."""
    _configure_test_gcloud()
    state = _verified_managed_state()
    if state is None:
        return None

    from lagniappe.core.tools.hosted_e2e.lease import (
        E2ELeaseHeartbeat,
        release_e2e_lease,
    )
    from runner.test_session import (
        inspect_process_identity,
        load_session_state,
        remove_session_state,
        session_transition_lock,
        update_state_for_nonce,
        utc_now,
        write_session_state,
    )

    adopter = E2ELeaseHeartbeat(state["nonce"])
    adopter.__enter__()
    try:
        with session_transition_lock():
            current = load_session_state()
            if current is None or current["nonce"] != state["nonce"]:
                raise RuntimeError("Managed test-session ownership changed.")
            if current["phase"] != "ready" or current["owner"] != state["owner"]:
                raise RuntimeError("Managed test-session changed before teardown.")
            attachment = current.get("attachment")
            if attachment:
                attachment_status = inspect_process_identity(attachment["process"])
                if attachment_status in {"match", "unknown"}:
                    raise RuntimeError("Browser review attached during teardown.")
                current["attachment"] = None
            current["phase"] = "stopping"
            current["heartbeat_at"] = utc_now()
            write_session_state(current)
        _terminate_verified_process_group(state["owner"])
        if _server_port_in_use(state["base_url"]):
            raise RuntimeError(
                "Test-server port remains occupied after its verified owner stopped; "
                "refusing cleanup."
            )
        cleanup_test_data(adopter)
        adopter.assert_active()
        if not release_e2e_lease(state["nonce"]):
            raise RuntimeError("Shared test-data lease changed during teardown.")
        remove_session_state(state["nonce"])
        return state["server"]["pid"]
    except BaseException:
        try:
            update_state_for_nonce(state["nonce"], phase="recovery-required")
        except Exception:
            pass
        raise
    finally:
        adopter.__exit__(None, None, None)


def test_server_status():
    """Return read-only diagnostics for the checkout-local test session."""
    from runner.test_session import inspect_process_identity, load_session_state

    state = load_session_state()
    if state is None:
        legacy_pid = None
        try:
            legacy_pid = int(
                File.MANAGED_TEST_SERVER_PID.value.read_text(encoding="utf-8").strip()
            )
        except (FileNotFoundError, ValueError):
            pass
        try:
            port_occupied = _server_port_in_use(SETTINGS.test_config["BASE_URL"])
            port_error = None
        except RuntimeError as error:
            port_occupied = None
            port_error = str(error)
        return {
            "active": False,
            "legacy_pid": legacy_pid,
            "port_occupied": port_occupied,
            "port_error": port_error,
        }

    owner_status = inspect_process_identity(state["owner"])
    server_status = (
        inspect_process_identity(state["server"]) if state.get("server") else "missing"
    )
    configuration_matches = _session_matches_configuration(state)
    health_verified = False
    if configuration_matches and server_status == "match":
        health_verified = wait_for_session_server(
            state["base_url"],
            state["nonce"],
            expected_pid=state["server"]["pid"],
            expected_mode=state["mode"],
            timeout_seconds=0.75,
            report_timeout=False,
        )
    return {
        "active": configuration_matches and owner_status == "match" and health_verified,
        "configuration_matches": configuration_matches,
        "mode": state["mode"],
        "phase": state["phase"],
        "nonce": state["nonce"],
        "owner_pid": state["owner"]["pid"],
        "owner_status": owner_status,
        "server_pid": state["server"]["pid"] if state.get("server") else None,
        "server_status": server_status,
        "health_verified": health_verified,
        "attachment": state.get("attachment"),
        "recovery_hint": state["recovery_hint"],
    }


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_recovery_rejects_wrong_health_nonce_without_signaling
# @matrix test-session : health-nonce recovery signal-safety
def _terminate_recoverable_server(state, timeout=15):
    """Stop an orphan only when process identity and health both prove ownership."""
    from runner.test_session import inspect_process_identity

    server = state.get("server")
    if not server:
        return False
    status = inspect_process_identity(server)
    if status in {"missing", "mismatch"}:
        return False
    if status != "match":
        raise RuntimeError("Orphaned server process cannot be inspected safely.")
    if not wait_for_session_server(
        state["base_url"],
        state["nonce"],
        expected_pid=server["pid"],
        expected_mode=state["mode"],
        timeout_seconds=2,
    ):
        raise RuntimeError(
            "Orphaned server health does not prove ownership; no process was signaled."
        )
    expected_pgid = (
        state["owner"]["pgid"]
        if state["mode"] == "managed-server"
        else server["pid"]
    )
    if server["pgid"] != expected_pgid:
        raise RuntimeError("Orphaned server process group does not match its owner.")

    os.killpg(server["pgid"], signal.SIGTERM)
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        status = inspect_process_identity(server)
        if status in {"missing", "mismatch"}:
            return True
        if status == "unknown":
            raise RuntimeError("Lost permission to inspect the orphaned server.")
        sleep(0.2)
    if inspect_process_identity(server) == "match":
        os.killpg(server["pgid"], signal.SIGKILL)
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if inspect_process_identity(server) in {"missing", "mismatch"}:
            return True
        sleep(0.2)
    raise RuntimeError(f"Could not stop orphaned server process {server['pid']}.")


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_recovery_refuses_while_owner_is_live
# @tests tests_tooling/test_005_test_session.py::test_recovery_is_idempotent_without_state
# @matrix test-session : idempotence live-owner recovery
def recover_managed_test_server():
    """Recover only after proving the recorded owner has exited."""
    from runner.test_session import (
        inspect_process_identity,
        load_session_state,
        remove_session_state,
        update_state_for_nonce,
    )

    state = load_session_state()
    base_url = SETTINGS.test_config["BASE_URL"]
    if state is None:
        legacy_pid = None
        try:
            legacy_pid = int(
                File.MANAGED_TEST_SERVER_PID.value.read_text(encoding="utf-8").strip()
            )
        except FileNotFoundError:
            pass
        except ValueError as error:
            raise RuntimeError(
                "Legacy test-server PID file is malformed; refusing recovery."
            ) from error
        if legacy_pid is not None:
            from runner.test_session import capture_process_identity

            if capture_process_identity(legacy_pid) is not None:
                raise RuntimeError(
                    "Legacy test-server PID is live but has no verifiable session "
                    "identity; no process was signaled."
                )
        if _server_port_in_use(base_url):
            raise RuntimeError(
                "Test-server port is occupied without verifiable session state; "
                "no process was signaled."
            )
        File.MANAGED_TEST_SERVER_PID.value.unlink(missing_ok=True)
        return {"recovered": False, "detail": "No recoverable session exists."}

    if not _session_matches_configuration(state):
        raise RuntimeError("Stale state does not match this checkout/configuration.")
    owner_status = inspect_process_identity(state["owner"])
    if owner_status == "match":
        raise RuntimeError(
            f"Test-session owner {state['owner']['pid']} is still live; recovery refused."
        )
    if owner_status == "unknown":
        raise RuntimeError(
            "Test-session owner cannot be inspected safely; recovery refused."
        )
    attachment = state.get("attachment")
    if attachment and inspect_process_identity(attachment["process"]) in {
        "match",
        "unknown",
    }:
        raise RuntimeError("Browser review attachment may still be active.")

    _terminate_recoverable_server(state)
    if _server_port_in_use(base_url):
        raise RuntimeError(
            "Test-server port is occupied by an unverified process; "
            "refusing recovery."
        )

    _configure_test_gcloud()
    from lagniappe.core.tools.hosted_e2e.lease import (
        E2ELease,
        E2ELeaseHeartbeat,
        current_e2e_lease,
        release_e2e_lease,
    )

    current = current_e2e_lease()
    if current not in {None, state["nonce"]}:
        # Another machine/session owns shared data. Removing the proven-dead
        # local record is safe; deleting shared data is not.
        remove_session_state(state["nonce"])
        File.MANAGED_TEST_SERVER_PID.value.unlink(missing_ok=True)
        return {
            "recovered": True,
            "cleaned": False,
            "detail": "Removed dead local state; shared data has a different owner.",
        }

    lease = (
        E2ELeaseHeartbeat(state["nonce"])
        if current == state["nonce"]
        else E2ELease(run_id=state["nonce"])
    )
    lease.__enter__()
    release_explicitly = current == state["nonce"]
    try:
        update_state_for_nonce(state["nonce"], phase="stopping")
        cleanup_test_data(lease)
        lease.assert_active()
        if release_explicitly and not release_e2e_lease(state["nonce"]):
            raise RuntimeError("Shared test-data lease changed during recovery.")
        remove_session_state(state["nonce"])
        File.MANAGED_TEST_SERVER_PID.value.unlink(missing_ok=True)
        return {"recovered": True, "cleaned": True, "detail": "Recovery complete."}
    except BaseException:
        try:
            update_state_for_nonce(state["nonce"], phase="recovery-required")
        except Exception:
            pass
        raise
    finally:
        lease.__exit__(None, None, None)


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_browser_attachment_is_exclusive_and_detaches
# @matrix test-session : browser-attachment exclusivity
def attach_browser_review(command):
    """Attach one browser capture to a verified managed-server session."""
    from runner.test_session import (
        capture_process_identity,
        inspect_process_identity,
        load_session_state,
        session_transition_lock,
        utc_now,
        write_session_state,
    )

    state = _verified_managed_state()
    if state is None or state["phase"] != "ready":
        raise RuntimeError("Browser review requires a ready managed test server.")
    process = capture_process_identity(os.getpid())
    if process is None:
        raise RuntimeError("Could not identify the browser-review process.")
    attachment_id = hashlib.sha256(
        f"{state['nonce']}\0{process['pid']}\0{monotonic()}".encode()
    ).hexdigest()[:24]
    with session_transition_lock():
        current = load_session_state()
        if current is None or current["nonce"] != state["nonce"]:
            raise RuntimeError("Managed test-session ownership changed before attach.")
        if current["phase"] != "ready" or current["owner"] != state["owner"]:
            raise RuntimeError("Managed test-session is no longer ready to attach.")
        existing = current.get("attachment")
        if existing and inspect_process_identity(existing["process"]) in {
            "match",
            "unknown",
        }:
            raise RuntimeError("Another browser review is already attached.")
        current["attachment"] = {
            "id": attachment_id,
            "command": " ".join(map(str, command)),
            "created_at": utc_now(),
            "process": process,
        }
        current["heartbeat_at"] = utc_now()
        write_session_state(current)
    return attachment_id


# @testable true
# @tests tests_tooling/test_005_test_session.py::test_browser_attachment_is_exclusive_and_detaches
# @matrix test-session : browser-attachment detach
def detach_browser_review(attachment_id):
    """Remove only the caller's matching browser-review attachment."""
    from runner.test_session import (
        load_session_state,
        session_transition_lock,
        utc_now,
        write_session_state,
    )

    with session_transition_lock():
        state = load_session_state()
        if state is None:
            return False
        attachment = state.get("attachment")
        if not attachment or attachment["id"] != attachment_id:
            return False
        state["attachment"] = None
        state["heartbeat_at"] = utc_now()
        write_session_state(state)
        return True
