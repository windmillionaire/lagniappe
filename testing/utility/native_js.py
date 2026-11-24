"""Static JavaScript discovery and execution shared by pytest and reporters."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_HELPERS = Path("testing/utility/js")
DEFAULT_MAX_WORKERS = 8
_FILE_INVENTORIES: dict[tuple, dict] = {}


def worker_count() -> int:
    """Return bounded parallel Node worker count for pytest execution."""
    raw = os.environ.get("LAGNIAPPE_JS_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError as error:
            raise ValueError(
                f"LAGNIAPPE_JS_WORKERS must be a positive integer, got {raw!r}"
            ) from error
    return max(1, min(DEFAULT_MAX_WORKERS, os.cpu_count() or 4))


def batch_enabled() -> bool:
    """Return whether multi-case files run batched before per-case fallback."""
    raw = os.environ.get("LAGNIAPPE_JS_BATCH", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def node_binary() -> str:
    node = shutil.which("node")
    if not node:
        raise ValueError(
            "Native JavaScript tests require Node; install the version in .nvmrc and run npm ci"
        )
    return node


def _read_inventories(files: list[tuple[str, int, int]]) -> dict:
    result = subprocess.run(
        [node_binary(), str(REPO_ROOT / JS_HELPERS / "inventory.mjs")],
        input=json.dumps([file for file, _, _ in files]),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"JavaScript discovery failed (check Node and npm ci):\n{result.stderr}"
        )
    return json.loads(result.stdout)


def inventories(paths) -> dict[str, dict]:
    files = []
    for path in sorted(set(Path(path).resolve() for path in paths)):
        stat = path.stat()
        files.append((str(path), stat.st_mtime_ns, stat.st_size))
    parser_version = (REPO_ROOT / JS_HELPERS / "inventory.mjs").stat().st_mtime_ns
    missing = [
        file for file in files if (*file, parser_version) not in _FILE_INVENTORIES
    ]
    if missing:
        parsed = _read_inventories(missing)
        for file in missing:
            _FILE_INVENTORIES[(*file, parser_version)] = parsed[file[0]]
    return {file[0]: _FILE_INVENTORIES[(*file, parser_version)] for file in files}


def inventory(path: Path) -> dict:
    return inventories([path])[str(path.resolve())]


def execution_dependencies(path: Path, repo_root: Path) -> set[str]:
    """Execution inputs are not claims of application coverage ownership."""
    dependencies = {
        ".nvmrc",
        "package.json",
        "package-lock.json",
        "testing/tests_js/conftest.py",
        "testing/utility/native_js.py",
        "testing/utility/native_js_pytest.py",
        "build/generate-registries.mjs",
        "build/utility.mjs",
        "src/style/pipeline.json",
        "src/style/styles.yaml",
        "src/style/icons.yaml",
        "src/style/registry.schema.json",
        "src/style/icons.schema.json",
    }
    dependencies.update(
        str(file.relative_to(repo_root))
        for file in (repo_root / JS_HELPERS).glob("*.mjs")
    )
    pending = [path.resolve()]
    visited = set()
    while pending:
        current = pending.pop()
        if current in visited or not current.is_file():
            continue
        visited.add(current)
        dependencies.add(current.relative_to(repo_root).as_posix())
        for specifier in inventory(current)["imports"]:
            if not specifier.startswith("."):
                continue
            imported = (current.parent / specifier).resolve()
            if (
                imported.is_relative_to(repo_root / "testing")
                and imported.suffix == ".mjs"
            ):
                dependencies.add(imported.relative_to(repo_root).as_posix())
                pending.append(imported)
    return dependencies


class JavaScriptFailure(Exception):
    """Native assertion, process, or reporter-protocol failure."""


def _parse_reporter_events(output: str, stderr: str) -> list[dict]:
    try:
        events = [json.loads(line) for line in output.splitlines() if line.strip()]
        if any(not isinstance(event, dict) or "type" not in event for event in events):
            raise ValueError("invalid event")
    except (ValueError, TypeError) as error:
        raise JavaScriptFailure(
            f"Invalid Node reporter output: {error}\n{output}\n{stderr}"
        ) from error
    return events


def interpret_result(output: str, stderr: str, returncode: int, name: str) -> dict:
    events = _parse_reporter_events(output, stderr)
    results = [
        event
        for event in events
        if event["type"] in {"test:pass", "test:fail"}
        and event.get("name") == name
        and event.get("nesting", 0) == 0
    ]
    failures = [
        event
        for event in events
        if event["type"] == "test:fail"
        and not event.get("skip")
        and not event.get("todo")
    ]
    if returncode or failures or len(results) != 1:
        details = "\n".join(
            str(event.get("error") or event.get("message") or "") for event in events
        )
        raise JavaScriptFailure(
            f"Node case {name} failed (exit {returncode}; matching results {len(results)}).\n{details}\n{stderr}"
        )
    return results[0]


def interpret_file_results(
    output: str, stderr: str, returncode: int, names: Sequence[str]
) -> tuple[dict[str, dict], set[str]]:
    """Parse one batched Node file run into verified passes and fallback cases.

    Any case that passes cleanly in a file with no hook/process/unhandled errors
    is trusted immediately. Any failed, missing, duplicate, or hook-tainted case
    is flagged for isolated single-case execution via ``run_case()`` so cross-case
    isolation and error attribution remain identical to per-case execution.
    """
    requested = list(names)
    requested_set = set(requested)
    try:
        events = _parse_reporter_events(output, stderr)
    except JavaScriptFailure:
        return {}, set(requested)

    by_name: dict[str, list[dict]] = {name: [] for name in requested}
    unattributed_failure = False
    for event in events:
        event_type = event["type"]
        if event_type not in {"test:pass", "test:fail"}:
            continue
        name = event.get("name")
        nesting = event.get("nesting", 0)
        if nesting == 0 and isinstance(name, str) and name in requested_set:
            by_name[name].append(event)
            continue
        if (
            event_type == "test:fail"
            and not event.get("skip")
            and not event.get("todo")
        ):
            unattributed_failure = True

    if unattributed_failure:
        return {}, set(requested)

    verified: dict[str, dict] = {}
    fallback: set[str] = set()
    for name in requested:
        matches = by_name[name]
        if len(matches) != 1:
            fallback.add(name)
            continue
        event = matches[0]
        if event["type"] == "test:pass" or event.get("skip") or event.get("todo"):
            verified[name] = event
        else:
            fallback.add(name)

    if returncode and not fallback:
        # Process exited non-zero without attributing the failure to a case
        # (e.g. unhandled rejection or late exception after test completion).
        return {}, set(requested)

    return verified, fallback


def _run_node_command(
    path: Path,
    pattern: str,
    *,
    timeout: float,
    case_timeout_ms: int | None = None,
    repo_root: Path = REPO_ROOT,
) -> tuple[str, str, int]:
    command = [
        node_binary(),
        "--test",
        "--test-concurrency=1",
        f"--test-name-pattern={pattern}",
    ]
    if case_timeout_ms is not None:
        command.append(f"--test-timeout={case_timeout_ms}")
    command.extend(
        [
            "--import",
            str(REPO_ROOT / JS_HELPERS / "bootstrap.mjs"),
            "--test-reporter",
            str(REPO_ROOT / JS_HELPERS / "reporter.mjs"),
            str(path.resolve()),
        ]
    )
    options = (
        {"start_new_session": True}
        if os.name != "nt"
        else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    )
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **options,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    return stdout, stderr, process.returncode


def run_case(
    path: Path, name: str, *, timeout: float = 30, repo_root: Path = REPO_ROOT
) -> dict:
    try:
        stdout, stderr, returncode = _run_node_command(
            path,
            f"^{re.escape(name)}$",
            timeout=timeout,
            repo_root=repo_root,
        )
    except subprocess.TimeoutExpired as error:
        out = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
        err = error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
        raise JavaScriptFailure(
            f"Node case {name} exceeded {timeout}s\n{out}\n{err}"
        ) from error
    return interpret_result(stdout, stderr, returncode, name)


def run_file_cases(
    path: Path,
    names: Sequence[str],
    *,
    timeout: float | None = None,
    case_timeout: float = 30,
    repo_root: Path = REPO_ROOT,
) -> dict[str, dict | JavaScriptFailure]:
    """Run selected cases from one file in a single Node process with isolated fallback."""
    ordered = list(dict.fromkeys(names))
    if not ordered:
        return {}

    outcomes: dict[str, dict | JavaScriptFailure] = {}
    if len(ordered) == 1 or not batch_enabled():
        fallback = ordered
    else:
        batch_timeout = (
            timeout
            if timeout is not None
            else max(case_timeout, min(120.0, 15.0 + 5.0 * len(ordered)))
        )
        pattern = "^(?:" + "|".join(re.escape(name) for name in ordered) + ")$"
        try:
            stdout, stderr, returncode = _run_node_command(
                path,
                pattern,
                timeout=batch_timeout,
                case_timeout_ms=int(case_timeout * 1000),
                repo_root=repo_root,
            )
        except subprocess.TimeoutExpired:
            verified: dict[str, dict] = {}
            fallback_set = set(ordered)
        else:
            verified, fallback_set = interpret_file_results(
                stdout, stderr, returncode, ordered
            )
        outcomes.update(verified)
        fallback = [name for name in ordered if name in fallback_set]

    for name in fallback:
        try:
            outcomes[name] = run_case(
                path, name, timeout=case_timeout, repo_root=repo_root
            )
        except JavaScriptFailure as failure:
            outcomes[name] = failure

    return outcomes
