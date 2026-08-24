import copy
from contextlib import contextmanager
import fcntl
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
from runner.process import run_command

# Cursor/agent sandboxes may set PLAYWRIGHT_BROWSERS_PATH to an empty cache.
# Prefer the normal user install when it exists.
_DEFAULT_PLAYWRIGHT_BROWSERS = Path.home() / ".cache/ms-playwright"
if _DEFAULT_PLAYWRIGHT_BROWSERS.is_dir():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_DEFAULT_PLAYWRIGHT_BROWSERS)


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_hosted_e2e_runner_skips_local_build_and_gcloud_activation
# @features testing hosted-e2e
# @dimensions provider-auth frontend-build
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

_TEST_FRONTEND_BUNDLE_SCHEMA = 1
_TEST_FRONTEND_BUNDLE_STATE = Directory.REPORTS.value / "test-frontend-bundle.json"
_TEST_FRONTEND_BUILD_METADATA = APP_DIR / "lagniappe/web/static/build.json"
_TEST_FRONTEND_INPUT_ROOTS = (
    Path("build"),
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
_TEST_FRONTEND_OUTPUT_FILES = (
    Path("lagniappe/web/static/build.json"),
    Path("lagniappe/web/static/login.js"),
    Path("lagniappe/web/static/script.js"),
    Path("lagniappe/web/static/style.css"),
    Path("lagniappe/web/static/sw.js"),
)


# @testable false
# @covered-by runner/testing.py::ensure_test_frontend_bundle
# @reason shared path contract with the E2E session fixture
def _e2e_session_lock_path():
    port = SETTINGS.test_config["SERVER_PORT"]
    return Path("/tmp") / f"lagniappe-e2e-{port}.lock"


# @testable false
# @covered-by runner/testing.py::ensure_test_frontend_bundle
# @reason prevents a preflight build from deleting chunks used by a live browser session
@contextmanager
def _test_frontend_bundle_session_guard():
    lock_path = _e2e_session_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        acquired = False
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            lock_file.seek(0)
            owner = lock_file.read().strip()
            if owner != f"pid={os.getpid()}":
                print(
                    "Frontend test bundle preflight deferred while the E2E "
                    f"session lock is held ({owner or 'unknown owner'}).",
                    flush=True,
                )
                yield False
                return

        if acquired:
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(f"pid={os.getpid()}")
            lock_file.flush()

        try:
            yield True
        finally:
            if acquired:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


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
# @reason private generated-output fingerprint detects missing, partial, or restored bundles
def _test_frontend_output_fingerprint():
    paths = [APP_DIR / relative for relative in _TEST_FRONTEND_OUTPUT_FILES]
    chunks = Directory.JS_CHUNKS.value
    chunk_paths = sorted(chunks.glob("*.js")) if chunks.is_dir() else []
    if any(not path.is_file() for path in paths) or not chunk_paths:
        return None

    digest = hashlib.sha256()
    for path in [*paths, *chunk_paths]:
        relative = path.relative_to(APP_DIR).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
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
# @reason tolerant metadata read preserves intentional production builds without trusting malformed output
def _test_frontend_bundle_mode():
    try:
        metadata = json.loads(
            _TEST_FRONTEND_BUILD_METADATA.read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(metadata, dict):
        return None
    mode = metadata.get("mode")
    return mode if isinstance(mode, str) else None


# @testable true
# @tests tests_tooling/test_005_test_server_command.py::test_test_frontend_bundle_skips_current_build
# @tests tests_tooling/test_005_test_server_command.py::test_test_frontend_bundle_rebuilds_stale_build
# @tests tests_tooling/test_005_test_server_command.py::test_test_frontend_bundle_defers_build_during_active_e2e_session
# @tests tests_tooling/test_005_test_server_command.py::test_test_frontend_bundle_preserves_production_build
# @pair test-server:freshness
# @pair frontend-build:freshness
# @pair frontend-build:no-op
# @pair frontend-build:rebuild
# @pair frontend-build:output-validation
# @pair frontend-build:e2e-session-isolation
# @pair frontend-build:production-preservation
def ensure_test_frontend_bundle():
    """Build development assets when test-server inputs or outputs changed."""
    if _test_frontend_bundle_mode() == "production":
        print("Production frontend bundle detected; preserving it.", flush=True)
        return False

    with _test_frontend_bundle_session_guard() as may_build:
        if not may_build:
            return False

        input_fingerprint = _test_frontend_input_fingerprint()
        output_fingerprint = _test_frontend_output_fingerprint()
        state = _read_test_frontend_bundle_state()
        if output_fingerprint is not None and state == {
            "schema": _TEST_FRONTEND_BUNDLE_SCHEMA,
            "inputs": input_fingerprint,
            "outputs": output_fingerprint,
        }:
            return False

        print("Frontend test bundle is stale; running npm run dev.", flush=True)
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

        output_fingerprint = _test_frontend_output_fingerprint()
        if output_fingerprint is None:
            raise RuntimeError(
                "Frontend test bundle build completed without required outputs."
            )

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
        return True


def prepare_test_artifacts():
    """Reset generated E2E artifact directories before a test-server run."""
    for artifact_dir in [Directory.TEST_FAILURES, Directory.TEST_REPORTS]:
        artifact_dir.clean()
        artifact_dir.get_or_create()


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
# @tests tests_tooling/test_005_test_server_command.py::test_wait_for_server_allows_slow_local_startup
# @tests tests_tooling/test_005_test_server_command.py::test_wait_for_server_bounds_stalled_requests_by_one_deadline
# @tests tests_tooling/test_005_test_server_command.py::test_wait_for_server_reports_last_http_state
# @features test-server
# @dimensions readiness slow-start deadline stalled-response diagnostics http-state
def wait_for_server(base_url, timeout_seconds=20.0):
    import requests

    deadline = monotonic() + timeout_seconds
    last_state = "no response"
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0.01:
            break
        connect_timeout = min(0.5, remaining / 2)
        read_timeout = min(2.0, remaining - connect_timeout)
        try:
            response = requests.get(
                f"{base_url}/l/ping",
                timeout=(connect_timeout, read_timeout),
            )
            if response.status_code == 200:
                return True
            last_state = f"HTTP {response.status_code}"
        except requests.RequestException as error:
            last_state = type(error).__name__

        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(0.5, remaining))

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

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _port_listener_pids(port):
    result = subprocess.run(
        ["ss", "-ltnp", f"( sport = :{port} )"],
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted({int(pid) for pid in re.findall(r"pid=(\d+)", result.stdout)})


def _kill_existing_test_server(base_url):
    parsed = urlparse(base_url)
    port = parsed.port

    if not port:
        return

    pids = _port_listener_pids(port)
    if not pids:
        return

    print(
        f"Abandoned test server process killed on port {port}: {', '.join(map(str, pids))}"
    )

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue

    for _ in range(10):
        if not _server_port_in_use(base_url):
            return
        sleep(0.2)

    remaining_pids = _port_listener_pids(port)
    for pid in remaining_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue

    for _ in range(10):
        if not _server_port_in_use(base_url):
            return
        sleep(0.2)

    raise RuntimeError(f"Could not free test server port {port} before startup.")


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


def _test_server_env():
    return {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "FLASK_ENV": Environment.TESTING.value,
    }


def _launch_test_server(stdout, stderr, start_new_session=False):
    return subprocess.Popen(
        _test_server_command(),
        cwd=APP_DIR,
        stdout=stdout,
        stderr=stderr,
        env=_test_server_env(),
        start_new_session=start_new_session,
    )


# @testable infrastructure
def run_test_server():
    ensure_test_frontend_bundle()
    _configure_test_gcloud()
    base_url = SETTINGS.test_config["BASE_URL"]
    _kill_existing_test_server(base_url)

    process = _launch_test_server(stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    stdout_thread = threading.Thread(
        target=_filter_server_output, args=(process.stdout, sys.stdout), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_filter_server_output, args=(process.stderr, sys.stderr), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    if not wait_for_server(base_url):
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"Test server exited before becoming healthy (exit code {exit_code})."
            )
        raise RuntimeError("Test server failed to start")

    return process


def terminate_test_server_process(process, timeout=15):
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_cleanup_scope_requires_the_reserved_test_prefix
# @features testing hosted-e2e
# @dimensions cleanup prefix fail-closed
def _require_test_cleanup_scope(config):
    if not config.testing or config.PREFIX != DEFAULT_TEST_PREFIX:
        raise RuntimeError(
            "Refusing test cleanup outside the reserved test- data prefix."
        )


# @testable infrastructure
def cleanup_test_data():
    os.environ["FLASK_ENV"] = Environment.TESTING.value
    _configure_test_gcloud()

    from lagniappe import CONFIG

    _require_test_cleanup_scope(CONFIG)
    from lagniappe.core.tools import database, cache

    database.cleanup_test_data()
    cache.cleanup_test_data()


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_initialize_test_services_replays_server_persistence_startup
# @features testing hosted-e2e
# @dimensions initialization database cache migrations
def _initialize_test_services(database, cache, migrations):
    """Replay the persistence portion of application startup after cleanup."""
    cache.initialize()
    fresh_install = database.initialize()
    migrations.initialize_fresh_install(fresh_install)
    return fresh_install


# @testable infrastructure
# @features testing hosted-e2e
# @dimensions initialization cleanup
def initialize_test_data():
    """Seed clean test persistence without starting another Flask process."""
    os.environ["FLASK_ENV"] = Environment.TESTING.value
    _configure_test_gcloud()

    from lagniappe import CONFIG

    _require_test_cleanup_scope(CONFIG)
    from lagniappe.core.tools import cache, database
    from lagniappe.core.tools.database import migrations

    return _initialize_test_services(database, cache, migrations)


# @testable false
# @covered-by runner/testing.py::teardown_managed_test_server
# @reason tolerant PID parsing is exercised through managed-server teardown
def _read_managed_test_server_pid():
    try:
        return int(
            File.MANAGED_TEST_SERVER_PID.value.read_text(encoding="utf-8").strip()
        )
    except (FileNotFoundError, ValueError):
        return None


def _process_is_running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _send_process_signal(pid, sig):
    try:
        os.killpg(pid, sig)
        return True
    except (PermissionError, ProcessLookupError):
        pass

    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False


def _terminate_managed_test_server_pid(pid, timeout=15):
    if not _process_is_running(pid):
        return False

    _send_process_signal(pid, signal.SIGTERM)
    for _ in range(timeout * 5):
        if not _process_is_running(pid):
            return True
        sleep(0.2)

    _send_process_signal(pid, signal.SIGKILL)
    for _ in range(10):
        if not _process_is_running(pid):
            return True
        sleep(0.2)

    raise RuntimeError(f"Could not stop managed test server process {pid}.")


# @testable infrastructure
def start_managed_test_server():
    """Start a detached Flask test server for manual or agent browser review."""
    prepare_test_artifacts()
    ensure_test_frontend_bundle()
    _configure_test_gcloud()
    base_url = SETTINGS.test_config["BASE_URL"]
    _kill_existing_test_server(base_url)
    Directory.REPORTS.create()

    with File.MANAGED_TEST_SERVER_LOG.value.open(
        "a",
        encoding="utf-8",
        buffering=1,
    ) as log_file:
        log_file.write("\n--- Starting managed test server ---\n")
        process = _launch_test_server(
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    if not wait_for_server(base_url):
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"Test server exited before becoming healthy (exit code {exit_code}). "
                f"See {File.MANAGED_TEST_SERVER_LOG.value}."
            )
        _terminate_managed_test_server_pid(process.pid, timeout=5)
        raise RuntimeError(
            f"Test server failed to start. See {File.MANAGED_TEST_SERVER_LOG.value}."
        )

    File.MANAGED_TEST_SERVER_PID.value.write_text(
        f"{process.pid}\n",
        encoding="utf-8",
    )
    return process.pid


# @testable true
# @tests tests_tooling/test_005_test_server_command.py::test_teardown_managed_test_server_stops_before_cleaning
# @features test-server
# @dimensions teardown process-management
def teardown_managed_test_server():
    """Stop the detached test server and clean test data."""
    os.environ["FLASK_ENV"] = Environment.TESTING.value
    pid = _read_managed_test_server_pid()

    if pid:
        _terminate_managed_test_server_pid(pid)

    base_url = SETTINGS.test_config["BASE_URL"]
    if _server_port_in_use(base_url):
        _kill_existing_test_server(base_url)

    try:
        File.MANAGED_TEST_SERVER_PID.value.unlink()
    except FileNotFoundError:
        pass

    cleanup_test_data()

    return pid
