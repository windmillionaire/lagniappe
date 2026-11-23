"""Discover template and style contracts on tests without importing application code."""

from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from testing.utility import native_js
from testing.utility.test_evidence import (
    git_query,
    utc_now,
    LATEST_TEST_RUN,
    behavior_path_fingerprints,
    decode_test_run_snapshots,
    load_json,
)

CONTRACT_REPORT_SCHEMA_VERSION = 3

_TAG = re.compile(r"^@([\w-]+)(?:\s*[:=]\s*|\s+)?(.*)$")
_TAG_NAMES = {
    "template": "templates",
    "templates": "templates",
    "template-partial": "templates",
    "template-partials": "templates",
    "style": "styles",
    "styles": "styles",
    "todo": "todos",
    "todos": "todos",
    "node-program": "programs",
}


def base_nodeid(nodeid: str) -> str:
    return re.sub(r"\[.*\]$", "", nodeid)


@dataclass
class ContractTest:
    path: str
    qualname: str
    lineno: int
    templates: list[str]
    styles: list[str]
    todos: list[str]
    programs: list[str]
    execution: str = "not_run"
    execution_current: bool = False
    snapshots: list[dict[str, str]] = field(default_factory=list)

    @property
    def nodeid(self) -> str:
        return f"{self.path}::{self.qualname}"

    @property
    def location(self) -> str:
        return f"{self.nodeid}:{self.lineno}"

    def matches(self, dependencies: Iterable[str], current: dict[str, str]) -> bool:
        return bool(self.snapshots) and all(
            path in current and snapshot.get(path) == current[path]
            for path in dependencies
            for snapshot in self.snapshots
        )


def _python_cases(path: Path) -> Iterator[tuple[str, int, str]]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()

    def visit(body: Sequence[ast.stmt], parents: tuple[str, ...]) -> Iterator[tuple[str, int, str]]:
        for node in body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = (*parents, node.name)
            if not isinstance(node, ast.ClassDef) and node.name.startswith("test_"):
                start = min((d.lineno for d in node.decorator_list), default=node.lineno) - 1
                preceding = start
                while preceding > 0 and lines[preceding - 1].lstrip().startswith("#"):
                    preceding -= 1
                comments = "\n".join(lines[preceding:start])
                docstring = ast.get_docstring(node) or ""
                yield "::".join(names), node.lineno, f"{comments}\n{docstring}"
            yield from visit(node.body, names)

    yield from visit(ast.parse(source, filename=str(path)).body, ())


def collect_contract_tests(repo_root: Path) -> dict[str, ContractTest]:
    tests_root = repo_root / "testing"
    js_paths = sorted(tests_root.rglob("test_*.mjs"))
    inventories = native_js.inventories(js_paths) if js_paths else {}
    tests = {}
    for path in sorted([*tests_root.rglob("test_*.py"), *js_paths]):
        cases: Iterable[tuple[str, int, str]]
        if path.suffix == ".mjs":
            cases = (
                (row["name"], row["lineno"], row["metadata_text"])
                for row in inventories[str(path.resolve())]["cases"]
            )
        else:
            cases = _python_cases(path)
        for name, lineno, text in cases:
            tags: dict[str, list[str]] = defaultdict(list)
            for line in text.splitlines():
                match = _TAG.match(line.strip().lstrip("#*").strip())
                if match is None:
                    continue
                tag = _TAG_NAMES.get(match[1].lower().replace("_", "-"))
                if tag is None:
                    continue
                value = match[2].strip()
                for part in [value] if tag == "todos" else re.split(r"[\s,]+", value):
                    if part and part not in tags[tag]:
                        tags[tag].append(part)
            if tags["templates"] or tags["styles"]:
                test = ContractTest(
                    path=path.relative_to(tests_root).as_posix(),
                    qualname=name,
                    lineno=lineno,
                    templates=tags["templates"],
                    styles=tags["styles"],
                    todos=tags["todos"],
                    programs=tags["programs"],
                )
                tests[test.nodeid] = test
    return tests


def attach_contract_results(repo_root: Path, tests: dict[str, ContractTest]) -> dict[str, str]:
    """Check the test itself and native runner inputs before selecting style evidence."""
    manifest = load_json(repo_root / LATEST_TEST_RUN) or {}
    snapshots = decode_test_run_snapshots(manifest)
    records = manifest.get("tests")
    if not isinstance(records, dict) or not records:
        return {}
    by_test: dict[str, list[dict[str, object]]] = defaultdict(list)
    for nodeid, row in records.items():
        if isinstance(nodeid, str) and isinstance(row, dict):
            by_test[base_nodeid(nodeid)].append(row)

    current = behavior_path_fingerprints(repo_root)
    for test in tests.values():
        rows = by_test.get(test.nodeid, [])
        if not rows:
            continue
        outcomes = [str(row.get("outcome", "not_run")) for row in rows]
        if "failed" in outcomes:
            test.execution = "failed"
        elif "passed" in outcomes:
            test.execution = "passed"
        else:
            test.execution = outcomes[0]
        test.snapshots = [snapshots.get(str(row.get("snapshot")), {}) for row in rows]
        path = repo_root / "testing" / test.path
        dependencies = {f"testing/{test.path}"}
        if path.suffix == ".mjs":
            dependencies.update(native_js.execution_dependencies(path, repo_root))
        for program in test.programs:
            program_path = (repo_root / program).resolve()
            if not program_path.is_relative_to(repo_root.resolve()) or program_path.suffix != ".mjs":
                raise ValueError(f"Invalid @node-program in {test.nodeid}: {program}")
            dependencies.add(program)
            if program_path.is_file():
                dependencies.update(native_js.execution_dependencies(program_path, repo_root))
        test.execution_current = test.execution != "not_run" and test.matches(dependencies, current)
    return current


def git_head(repo_root: Path) -> str | None:
    result = git_query(repo_root, "rev-parse", "HEAD", text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def git_changed_paths(repo_root: Path, base: str = "HEAD") -> list[str]:
    """Return tracked, staged, and untracked paths changed from ``base``."""
    paths: set[str] = set()
    commands = [
        ("diff", "--name-only", "-z", base),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ]
    for command in commands:
        result = git_query(repo_root, *command)
        if result.returncode != 0:
            message = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(message or f"git {' '.join(command)} failed")
        paths.update(
            value.decode(errors="surrogateescape")
            for value in result.stdout.split(b"\0")
            if value
        )
    return sorted(paths)


def working_tree_fingerprint(repo_root: Path) -> str:
    """Hash HEAD plus the content and identity of every dirty path."""
    digest = hashlib.sha256()
    digest.update((git_head(repo_root) or "no-head").encode())
    try:
        paths = git_changed_paths(repo_root)
    except RuntimeError:
        paths = []

    for relative in paths:
        digest.update(b"\0path\0")
        digest.update(relative.encode(errors="surrogateescape"))
        path = repo_root / relative
        if path.is_file():
            digest.update(b"\0file\0")
            try:
                digest.update(path.read_bytes())
            except OSError:
                digest.update(b"unreadable")
        elif path.exists():
            digest.update(b"\0other\0")
        else:
            digest.update(b"\0deleted\0")
    return digest.hexdigest()


def provenance(repo_root: Path, *, command: Iterable[str] = ()) -> dict[str, object]:
    return {
        "generated_at": utc_now(),
        "git_head": git_head(repo_root),
        "working_tree_fingerprint": working_tree_fingerprint(repo_root),
        "command": list(command),
    }


def stable_finding_id(kind: str, location: str, message: str) -> str:
    """Return the shared content-derived identifier for a report finding."""
    digest = hashlib.sha256(f"{kind}\0{location}\0{message}".encode()).hexdigest()[:16]
    return f"{kind}:{digest}"


def structured_report_payload(
    *,
    kind: str,
    report: object,
    report_provenance: dict[str, object],
    findings: list[dict[str, str]],
) -> dict[str, object]:
    """Wrap a contract report in the repository's versioned JSON envelope."""
    return {
        "schema_version": CONTRACT_REPORT_SCHEMA_VERSION,
        "kind": kind,
        "provenance": report_provenance,
        "findings": findings,
        "finding_ids": [finding["id"] for finding in findings],
        "report": report,
    }
