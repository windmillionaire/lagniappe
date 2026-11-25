"""Process locking and secret-free setup operation journaling."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from types import TracebackType
from typing import Self


from runner import presentation as ui
from runner.presentation import output as print

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from runner.context import REPOSITORY_ROOT, setup_command
from installer.errors import SetupError, SetupInterrupted


STATE_SCHEMA_VERSION = 1
_ACTIVE_JOURNAL = None


def _restrict_state_file(path):
    if os.name != "nt":
        os.chmod(path, 0o600)
        return True
    username = str(os.environ.get("USERNAME") or "").strip()
    if not username:
        print(
            ui.warning(f"Could not restrict the Windows ACL for {path}; "
            "USERNAME is unavailable.")
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
            ui.warning(f"Could not restrict the Windows ACL for {path}. "
            "Protect this setup state file manually.")
        )
        return False
    return True


def _state_dir():
    override = os.environ.get("LAGNIAPPE_SETUP_STATE_DIR")
    path = (
        Path(override)
        if override
        else REPOSITORY_ROOT / "config" / "files"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def _pid_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class SetupProcessLock:
    """Cross-platform single-process lock based on atomic file creation."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        wait_seconds: float = 0.0,
        poll_interval: float = 0.1,
    ) -> None:
        self.path = Path(path or (_state_dir() / ".lagniappe_setup.lock"))
        self.wait_seconds = max(0.0, float(wait_seconds))
        self.poll_interval = max(0.01, float(poll_interval))
        self.acquired = False

    def acquire(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_seconds
        stale_retries = 0
        while True:
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
                holder_pid = payload.get("pid")
                if _pid_running(holder_pid):
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(self.poll_interval, remaining))
                        continue
                    raise SetupError(
                        "Another Lagniappe setup process is already running "
                        f"(pid {holder_pid})."
                    ) from None
                if stale_retries >= 3:
                    raise SetupError(
                        "Could not acquire the Lagniappe setup process lock."
                    ) from None
                stale_retries += 1
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

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False

    def __enter__(self) -> Self:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class OperationJournal:
    """Persist the last safe setup boundary without settings or credentials."""

    def __init__(
        self, mode: str, argv: Sequence[str], path: str | Path | None = None
    ) -> None:
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

    def save(self) -> None:
        _write_json(self.path, self.payload)

    def step(self, name: str) -> None:
        self.payload["last_step"] = str(name)
        self.save()

    def mutation(
        self,
        step: str,
        *,
        action: str,
        resource: str,
        identifier: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.payload["last_step"] = str(step)
        mutation: dict[str, object] = {
            "step": str(step),
            "action": str(action),
            "resource": str(resource),
            "identifier": str(identifier),
        }
        if details:
            mutation["details"] = details
        self.payload["mutations"].append(mutation)
        self.save()

    def finish(self, status: str, error: BaseException | None = None) -> None:
        self.payload["status"] = status
        if error is not None:
            self.payload["error_category"] = getattr(error, "category", "setup")
        self.save()


def record_step(name: str) -> None:
    if _ACTIVE_JOURNAL is not None:
        _ACTIVE_JOURNAL.step(name)


def record_mutation(
    step: str,
    *,
    action: str,
    resource: str,
    identifier: str,
    details: Mapping[str, object] | None = None,
) -> None:
    if _ACTIVE_JOURNAL is not None:
        _ACTIVE_JOURNAL.mutation(
            step,
            action=action,
            resource=resource,
            identifier=identifier,
            details=details,
        )


@contextmanager
def _interrupt_handlers():
    previous = {}

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


def _print_recovery(journal, prefix):
    print(f"{prefix} after: {journal.payload['last_step'] or 'start'}")
    mutations = journal.payload["mutations"]
    if mutations:
        print(ui.heading("Completed remote mutations"))
        for mutation in mutations:
            print(
                "  - "
                f"{mutation['action']} {mutation['resource']} "
                f"{mutation['identifier']}"
            )
    else:
        print("Completed remote mutations: none")
    print(
        ui.value(
            "Resume with",
            journal.payload["resume_command"],
            action=True,
            verbatim=True,
            standalone=True,
        )
    )


@contextmanager
def setup_operation(
    mode: str,
    argv: Sequence[str],
    *,
    lock_path: str | Path | None = None,
    journal_path: str | Path | None = None,
) -> Iterator[OperationJournal]:
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
