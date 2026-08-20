"""Process locking and secret-free setup operation journaling."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

from runner.context import REPOSITORY_ROOT, setup_command
from installer.errors import SetupError, SetupInterrupted


STATE_SCHEMA_VERSION = 1
_ACTIVE_JOURNAL = None


# @testable false
# @covered-by installer/state.py::SetupProcessLock
# @covered-by installer/state.py::OperationJournal
# @reason platform permission adapter is owned by setup state persistence
def _restrict_state_file(path):
    if os.name != "nt":
        os.chmod(path, 0o600)
        return True
    username = str(os.environ.get("USERNAME") or "").strip()
    if not username:
        print(
            f"WARNING: Could not restrict the Windows ACL for {path}; "
            "USERNAME is unavailable."
        )
        return False
    try:
        result = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{username}:(R,W)",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is None or result.returncode != 0:
        print(
            f"WARNING: Could not restrict the Windows ACL for {path}. "
            "Protect this setup state file manually."
        )
        return False
    return True


# @testable false
# @covered-by installer/state.py::setup_operation
# @reason state-path selection is exercised through setup operation journaling
def _state_dir():
    override = os.environ.get("LAGNIAPPE_SETUP_STATE_DIR")
    path = (
        Path(override)
        if override
        else REPOSITORY_ROOT / "config" / "files"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


# @testable false
# @covered-by installer/state.py::OperationJournal
# @reason atomic journal serialization is exercised through the journal contract
def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"{json.dumps(payload, indent=2, sort_keys=True)}\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        if os.name != "nt" and hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as output:
            descriptor = None
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _restrict_state_file(path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


# @testable false
# @covered-by installer/state.py::SetupProcessLock
# @reason process probe is owned by the setup lock contract
def _pid_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_process_lock_and_operation_journal
# @features setup
# @dimensions process-lock
class SetupProcessLock:
    """Cross-platform single-process lock based on atomic file creation."""

    def __init__(self, path=None):
        self.path = Path(path or (_state_dir() / ".lagniappe_setup.lock"))
        self.acquired = False

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                try:
                    payload = json.loads(
                        self.path.read_text(encoding="utf-8") or "{}"
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    payload = {}
                if _pid_running(payload.get("pid")):
                    raise SetupError(
                        "Another Lagniappe setup process is already running "
                        f"(pid {payload['pid']})."
                    )
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            ) as lock_file:
                lock_file.write(
                    json.dumps(
                        {
                            "schema": STATE_SCHEMA_VERSION,
                            "pid": os.getpid(),
                        }
                    )
                    + "\n"
                )
                lock_file.flush()
                os.fsync(lock_file.fileno())
            _restrict_state_file(self.path)
            self.acquired = True
            return self
        raise SetupError("Could not acquire the Lagniappe setup process lock.")

    def release(self):
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_process_lock_and_operation_journal
# @features setup
# @dimensions operation-journal recovery
class OperationJournal:
    """Persist the last safe setup boundary without settings or credentials."""

    def __init__(self, mode, argv, path=None):
        self.path = Path(
            path or (_state_dir() / "lagniappe_setup_operation.json")
        )
        self.payload = {
            "schema": STATE_SCHEMA_VERSION,
            "mode": mode,
            "status": "running",
            "resume_command": setup_command(*argv),
            "last_step": None,
            "mutations": [],
        }

    def save(self):
        _write_json(self.path, self.payload)

    def step(self, name):
        self.payload["last_step"] = str(name)
        self.save()

    def mutation(self, step, *, action, resource, identifier, details=None):
        self.payload["last_step"] = str(step)
        mutation = {
            "step": str(step),
            "action": str(action),
            "resource": str(resource),
            "identifier": str(identifier),
        }
        if details:
            mutation["details"] = details
        self.payload["mutations"].append(mutation)
        self.save()

    def finish(self, status, error=None):
        self.payload["status"] = status
        if error is not None:
            self.payload["error_category"] = getattr(error, "category", "setup")
        self.save()


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_process_lock_and_operation_journal
# @features setup
# @dimensions operation-journal
def record_step(name):
    if _ACTIVE_JOURNAL is not None:
        _ACTIVE_JOURNAL.step(name)


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_process_lock_and_operation_journal
# @features setup
# @dimensions operation-journal recovery
def record_mutation(step, *, action, resource, identifier, details=None):
    if _ACTIVE_JOURNAL is not None:
        _ACTIVE_JOURNAL.mutation(
            step,
            action=action,
            resource=resource,
            identifier=identifier,
            details=details,
        )


# @testable false
# @covered-by installer/state.py::setup_operation
# @reason platform signal adapter exercised through the setup operation boundary
@contextmanager
def _interrupt_handlers():
    previous = {}

    # @testable false
    # @covered-by installer/state.py::setup_operation
    # @reason signal callback raises the typed interruption owned by its context
    def interrupt(signum, _frame):
        raise SetupInterrupted(f"Setup interrupted by signal {signum}.")

    for signum in tuple(
        value
        for value in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None))
        if value is not None
    ):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupt)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


# @testable false
# @covered-by installer/state.py::setup_operation
# @reason console rendering is exercised through interrupted operation recovery
def _print_recovery(journal, prefix):
    print(f"{prefix} after: {journal.payload['last_step'] or 'start'}")
    mutations = journal.payload["mutations"]
    if mutations:
        print("Completed remote mutations:")
        for mutation in mutations:
            print(
                "  - "
                f"{mutation['action']} {mutation['resource']} "
                f"{mutation['identifier']}"
            )
    else:
        print("Completed remote mutations: none")
    print(f"Run {journal.payload['resume_command']} again to resume.")


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_process_lock_and_operation_journal
# @features setup
# @dimensions process-lock operation-journal recovery
@contextmanager
def setup_operation(mode, argv, *, lock_path=None, journal_path=None):
    """Lock setup and report a secret-free exact resume command on failure."""
    global _ACTIVE_JOURNAL

    with SetupProcessLock(lock_path):
        journal = OperationJournal(mode, argv, path=journal_path)
        journal.save()
        _ACTIVE_JOURNAL = journal
        try:
            with _interrupt_handlers():
                yield journal
        except SetupInterrupted as error:
            journal.finish("interrupted", error)
            _print_recovery(journal, "Setup interrupted")
            raise
        except KeyboardInterrupt as error:
            interrupted = SetupInterrupted("Setup interrupted from the terminal.")
            journal.finish("interrupted", interrupted)
            _print_recovery(journal, "Setup interrupted")
            raise interrupted from error
        except BaseException as error:
            journal.finish("failed", error)
            _print_recovery(journal, "Setup stopped")
            raise
        else:
            journal.finish("complete")
        finally:
            _ACTIVE_JOURNAL = None
