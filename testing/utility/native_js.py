"""Static JavaScript discovery and execution shared by pytest and reporters."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_HELPERS = Path("testing/utility/js")
_FILE_INVENTORIES: dict[tuple, dict] = {}


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


def interpret_result(output: str, stderr: str, returncode: int, name: str) -> dict:
    try:
        events = [json.loads(line) for line in output.splitlines() if line.strip()]
        if any(not isinstance(event, dict) or "type" not in event for event in events):
            raise ValueError("invalid event")
    except (ValueError, TypeError) as error:
        raise JavaScriptFailure(
            f"Invalid Node reporter output: {error}\n{output}\n{stderr}"
        ) from error
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


def run_case(
    path: Path, name: str, *, timeout: float = 30, repo_root: Path = REPO_ROOT
) -> dict:
    command = [
        node_binary(),
        "--test",
        "--test-concurrency=1",
        f"--test-name-pattern=^{re.escape(name)}$",
        "--import",
        str(REPO_ROOT / JS_HELPERS / "bootstrap.mjs"),
        "--test-reporter",
        str(REPO_ROOT / JS_HELPERS / "reporter.mjs"),
        str(path.resolve()),
    ]
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
    except BaseException as error:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stdout, stderr = process.communicate()
        if isinstance(error, subprocess.TimeoutExpired):
            raise JavaScriptFailure(
                f"Node case {name} exceeded {timeout}s\n{stdout}\n{stderr}"
            ) from error
        raise
    return interpret_result(stdout, stderr, process.returncode, name)
