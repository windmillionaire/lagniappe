"""Pytest plugin that records the latest test outcomes for traceability."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import sys

from testing.utility.traceability_common import (
    LATEST_TEST_RUN,
    TEST_RUN_SCHEMA_VERSION,
    behavior_snapshot,
    decode_test_run_snapshots,
    encode_test_run_snapshots,
    load_json,
    utc_now,
    write_json,
)


_OUTCOMES: dict[str, dict[str, object]] = {}
MAX_TRACEBACK_CHARS = 100_000
TRACEBACK_TRUNCATION_MARKER = "\n... traceback truncated ...\n"
PARAMETER_SUFFIX_RE = re.compile(r"\[.*\]$")


def _repo_root(config) -> Path:
    configured = Path(str(config.rootpath)).resolve()
    if configured.name == "testing":
        return configured.parent
    return Path.cwd().resolve()


def pytest_sessionstart(session) -> None:
    _OUTCOMES.clear()


def _failure_traceback(report) -> tuple[str, bool]:
    text = getattr(report, "longreprtext", "")
    if not text:
        text = str(getattr(report, "longrepr", "") or "")
    text = str(text).strip()
    if len(text) <= MAX_TRACEBACK_CHARS:
        return text, False

    available = MAX_TRACEBACK_CHARS - len(TRACEBACK_TRUNCATION_MARKER)
    head = available // 2
    tail = available - head
    return (
        f"{text[:head]}{TRACEBACK_TRUNCATION_MARKER}{text[-tail:]}",
        True,
    )


def pytest_runtest_logreport(report) -> None:
    row = _OUTCOMES.setdefault(
        report.nodeid,
        {
            "outcome": "not_run",
            "duration": 0.0,
        },
    )
    row["duration"] = float(row["duration"]) + float(report.duration)

    if report.failed:
        row["outcome"] = "failed"
        row["failed_phase"] = report.when
        traceback, truncated = _failure_traceback(report)
        if traceback:
            row["traceback"] = traceback
        else:
            row.pop("traceback", None)
        if truncated:
            row["traceback_truncated"] = True
        else:
            row.pop("traceback_truncated", None)
    elif report.when == "call":
        row["outcome"] = "skipped" if report.skipped else "passed"
    elif report.when == "setup" and report.skipped:
        row["outcome"] = "skipped"


def pytest_sessionfinish(session, exitstatus: int) -> None:
    repo_root = _repo_root(session.config)
    command = os.environ.get("LAGNIAPPE_TEST_COMMAND")
    recorded_command = json.loads(command) if command else [sys.executable, *sys.argv]
    _write_manifest(repo_root, recorded_command, _OUTCOMES, exitstatus)


def _base_nodeid(nodeid: str) -> str:
    parts = nodeid.split("::")
    if parts:
        parts[-1] = PARAMETER_SUFFIX_RE.sub("", parts[-1])
    return "::".join(parts)


def _test_module_path(repo_root: Path, nodeid: str) -> Path:
    """Resolve the test module path for a recorded node ID."""
    raw_path = nodeid.partition("::")[0]
    path = Path(raw_path)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "testing":
        return repo_root / path
    testing_path = repo_root / "testing" / path
    return testing_path if testing_path.is_file() else repo_root / path


def _test_node_exists(
    repo_root: Path,
    nodeid: str,
    parsed_modules: dict[Path, ast.Module | None],
) -> bool:
    """Return whether a recorded node ID still has a source test definition."""
    path = _test_module_path(repo_root, nodeid)
    if not path.is_file():
        return False

    base_nodeid = PARAMETER_SUFFIX_RE.sub("", nodeid)
    symbols = base_nodeid.split("::")[1:]
    if not symbols or path.suffix != ".py":
        return True

    if path not in parsed_modules:
        try:
            parsed_modules[path] = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError):
            # Evidence cleanup must not hide the original filesystem or
            # collection problem. Keep the record until the module is readable.
            parsed_modules[path] = None

    module = parsed_modules[path]
    if module is None:
        return True

    body = module.body
    definitions = (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)
    for index, symbol in enumerate(symbols):
        definition = next(
            (
                statement
                for statement in body
                if isinstance(statement, definitions) and statement.name == symbol
            ),
            None,
        )
        if definition is None:
            return False
        if index < len(symbols) - 1:
            if not isinstance(definition, ast.ClassDef):
                return False
            body = definition.body
    return True


def _completed_parameter_sets(
    recorded_command: list[str],
    outcomes: dict[str, dict[str, object]],
    exitstatus: int,
) -> set[str]:
    """Find whole parametrized functions explicitly completed by this command."""
    if exitstatus != 0:
        return set()

    selection_options = {"-k", "--lf", "--ff", "--nf", "--sw", "--stepwise"}
    if any(
        argument in selection_options
        or argument.startswith("--maxfail")
        or argument == "-x"
        for argument in recorded_command
    ):
        return set()

    selected_bases = set()
    for argument in recorded_command:
        normalized = str(argument).removeprefix("testing/")
        if "::" not in normalized or PARAMETER_SUFFIX_RE.search(normalized):
            continue
        selected_bases.add(normalized)

    outcome_bases = {_base_nodeid(nodeid) for nodeid in outcomes}
    return selected_bases & outcome_bases


def _write_manifest(
    repo_root: Path,
    recorded_command: list[str],
    outcomes: dict[str, dict[str, object]],
    exitstatus: int,
) -> None:
    """Merge one pytest session into the result manifest."""
    snapshot_id, path_fingerprints = behavior_snapshot(repo_root)
    metadata = {
        "generated_at": utc_now(),
        "command": recorded_command,
        "behavior_snapshot": snapshot_id,
    }
    destination = repo_root / LATEST_TEST_RUN
    previous = load_json(destination)
    tests: dict[str, object] = {}
    snapshots: dict[str, dict[str, str]] = {}
    previous_schema = previous.get("schema_version") if previous else None
    if isinstance(previous_schema, int) and previous_schema in {
        2,
        TEST_RUN_SCHEMA_VERSION,
    }:
        previous_tests = previous.get("tests")
        if isinstance(previous_tests, dict):
            tests.update(previous_tests)
        snapshots.update(decode_test_run_snapshots(previous))

    parsed_modules: dict[Path, ast.Module | None] = {}
    tests = {
        nodeid: row
        for nodeid, row in tests.items()
        if nodeid in outcomes
        or _test_node_exists(repo_root, nodeid, parsed_modules)
    }

    snapshots[snapshot_id] = path_fingerprints
    recorded_outcomes = {
        nodeid: {**row, "snapshot": snapshot_id}
        for nodeid, row in outcomes.items()
    }
    completed_parameter_sets = _completed_parameter_sets(
        recorded_command, outcomes, exitstatus
    )
    if completed_parameter_sets:
        tests = {
            nodeid: row
            for nodeid, row in tests.items()
            if _base_nodeid(nodeid) not in completed_parameter_sets
        }
    tests.update(recorded_outcomes)
    latest_session = {
        "generated_at": metadata["generated_at"],
        "command": recorded_command,
        "exit_status": int(exitstatus),
        "tests": len(outcomes),
        "snapshot": snapshot_id,
    }
    used_snapshots = {
        row.get("snapshot")
        for row in tests.values()
        if isinstance(row, dict) and isinstance(row.get("snapshot"), str)
    }
    snapshots = {
        key: value for key, value in snapshots.items() if key in used_snapshots
    }
    fingerprint_pairs, encoded_snapshots = encode_test_run_snapshots(snapshots)
    payload = {
        "schema_version": TEST_RUN_SCHEMA_VERSION,
        "kind": "test-run",
        "provenance": metadata,
        "exit_status": int(exitstatus),
        "sessions": [latest_session],
        "fingerprint_pairs": fingerprint_pairs,
        "snapshots": encoded_snapshots,
        "tests": dict(sorted(tests.items())),
    }
    write_json(destination, payload)
