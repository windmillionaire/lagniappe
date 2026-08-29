"""Shared provenance and Git-scope helpers for traceability tooling."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Iterable


TRACEABILITY_SCHEMA_VERSION = 3
TEST_RUN_SCHEMA_VERSION = 3
TEST_EVIDENCE_DIR = Path("testing/evidence")
LATEST_TEST_RUN = TEST_EVIDENCE_DIR / "latest.json"
BEHAVIOR_SUFFIXES = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".jinja",
    ".jinja2",
    ".json",
    ".mjs",
    ".py",
    ".scss",
    ".toml",
    ".yaml",
    ".yml",
}
BEHAVIOR_EXCLUDED_PREFIXES = (
    ".git/",
    ".github/",
    "config/files/",
    "documentation/",
    "lagniappe/web/static/",
    "node_modules/",
    "reports/",
    "testing/evidence/",
    "venv/",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(
    repo_root: Path, *args: str, check: bool = False, text: bool = False
) -> subprocess.CompletedProcess:
    command = ["git", *args]
    try:
        return subprocess.run(
            command,
            cwd=repo_root,
            check=check,
            capture_output=True,
            text=text,
        )
    except OSError as error:
        if check:
            raise
        empty = "" if text else b""
        detail = str(error) if text else str(error).encode()
        return subprocess.CompletedProcess(command, 127, empty, detail)


def git_head(repo_root: Path) -> str | None:
    result = _git(repo_root, "rev-parse", "HEAD", text=True)
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
        result = _git(repo_root, *command)
        if result.returncode != 0:
            message = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(message or f"git {' '.join(command)} failed")
        paths.update(
            value.decode(errors="surrogateescape")
            for value in result.stdout.split(b"\0")
            if value
        )
    return sorted(paths)


def git_changed_line_ranges(
    repo_root: Path,
    paths: Iterable[str],
    base: str = "HEAD",
) -> dict[str, list[tuple[int, int]] | None]:
    """Return changed new-file line ranges, using ``None`` for untracked files."""
    existing_paths = [path for path in paths if (repo_root / path).is_file()]
    ranges: dict[str, list[tuple[int, int]] | None] = {
        path: None for path in existing_paths
    }
    if not existing_paths:
        return ranges

    result = _git(
        repo_root,
        "diff",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        base,
        "--",
        *existing_paths,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff line scan failed")

    current_path: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("+++ "):
            value = line[4:]
            current_path = (
                value.removeprefix("b/") if value != "/dev/null" else None
            )
            if current_path in ranges:
                ranges[current_path] = []
            continue
        if current_path is None or not line.startswith("@@"):
            continue
        match = re.search(r"\+(\d+)(?:,(\d+))?", line)
        if match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or 1)
        changed = ranges.get(current_path)
        if not isinstance(changed, list):
            continue
        if count:
            changed.append((start, start + count - 1))
        else:
            changed.append((max(1, start - 1), start))
    return ranges


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


class _WithoutDocstrings(ast.NodeTransformer):
    """Remove documentation-only strings from a Python syntax tree."""

    def _without_docstring(self, node):
        self.generic_visit(node)
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body = node.body[1:]
        return node

    visit_Module = _without_docstring
    visit_ClassDef = _without_docstring
    visit_FunctionDef = _without_docstring
    visit_AsyncFunctionDef = _without_docstring


def _python_behavior_bytes(content: bytes) -> bytes:
    try:
        tree = ast.parse(content.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return content
    tree = _WithoutDocstrings().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.dump(tree, annotate_fields=True, include_attributes=False).encode()


def _javascript_without_comments(content: str) -> str:
    """Strip JavaScript comments while preserving quoted and template strings."""
    result: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(content):
        char = content[index]
        following = content[index + 1] if index + 1 < len(content) else ""

        if state == "line-comment":
            if char == "\n":
                result.append(char)
                state = "code"
            index += 1
            continue
        if state == "block-comment":
            if char == "*" and following == "/":
                state = "code"
                index += 2
            else:
                if char == "\n":
                    result.append(char)
                index += 1
            continue
        if state == "string":
            result.append(char)
            if char == "\\" and following:
                result.append(following)
                index += 2
                continue
            if char == quote:
                state = "code"
            index += 1
            continue

        if char == "/" and following == "/":
            state = "line-comment"
            index += 2
            continue
        if char == "/" and following == "*":
            state = "block-comment"
            index += 2
            continue
        if char in {"'", '"', "`"}:
            state = "string"
            quote = char
        result.append(char)
        index += 1
    return "".join(result)


def behavior_file_fingerprint(path: Path) -> str:
    """Hash behavior-bearing content while ignoring annotation-only comments."""
    content = path.read_bytes()
    if path.suffix == ".py":
        if path.name == "constants.py" and path.parent.name == "config":
            # BUILD_ID is random output from the production asset build. It is
            # recorded in hosted provenance but is not a source-tree change.
            content = re.sub(
                rb"(?m)^BUILD_ID\s*=.*(?:\r?\n|$)",
                b"",
                content,
            )
        content = _python_behavior_bytes(content)
    elif path.suffix in {".js", ".mjs"}:
        try:
            content = _javascript_without_comments(content.decode("utf-8")).encode()
        except UnicodeDecodeError:
            pass
    return hashlib.sha256(content).hexdigest()


def behavior_path_fingerprints(repo_root: Path) -> dict[str, str]:
    """Return semantic fingerprints for behavior files and virtual records."""
    paths: set[str] = set()
    tracked = _git(repo_root, "ls-files", "-z")
    if tracked.returncode == 0:
        paths.update(
            value.decode(errors="surrogateescape")
            for value in tracked.stdout.split(b"\0")
            if value
        )
    untracked = _git(repo_root, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked.returncode == 0:
        paths.update(
            value.decode(errors="surrogateescape")
            for value in untracked.stdout.split(b"\0")
            if value
        )

    # Source archives and test-runner images intentionally omit .git. Fall back
    # to the uploaded tree so hosted evidence has the same provenance contract.
    if not paths:
        paths.update(
            path.relative_to(repo_root).as_posix()
            for path in repo_root.rglob("*")
            if path.is_file()
        )

    fingerprints: dict[str, str] = {}
    for relative in sorted(paths):
        if relative.startswith(BEHAVIOR_EXCLUDED_PREFIXES):
            continue
        path = repo_root / relative
        if path.is_file() and path.suffix.lower() in BEHAVIOR_SUFFIXES:
            try:
                fingerprints[relative] = behavior_file_fingerprint(path)
            except OSError:
                continue
    try:
        from testing.utility.style_registry import style_record_fingerprints

        fingerprints.update(
            {
                f"@style/{name}": fingerprint
                for name, fingerprint in style_record_fingerprints(repo_root).items()
            }
        )
    except (OSError, TypeError, ValueError):
        # Style validation reports malformed registries directly; result capture
        # must remain available for unrelated suites.
        pass
    return fingerprints


def behavior_snapshot(repo_root: Path) -> tuple[str, dict[str, str]]:
    """Return a stable ID and path map for the current behavioral tree."""
    paths = behavior_path_fingerprints(repo_root)
    digest = hashlib.sha256()
    for path, fingerprint in paths.items():
        digest.update(path.encode(errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(fingerprint.encode())
        digest.update(b"\0")
    return digest.hexdigest(), paths


def decode_test_run_snapshots(
    manifest: dict[str, object],
) -> dict[str, dict[str, str]]:
    """Return snapshot path maps from current or legacy test-run manifests."""
    raw_snapshots = manifest.get("snapshots")
    if not isinstance(raw_snapshots, dict):
        return {}

    if manifest.get("schema_version") == 2:
        decoded: dict[str, dict[str, str]] = {}
        for snapshot_id, raw_snapshot in raw_snapshots.items():
            if not isinstance(snapshot_id, str) or not isinstance(raw_snapshot, dict):
                continue
            raw_paths = raw_snapshot.get("paths")
            if not isinstance(raw_paths, dict):
                continue
            decoded[snapshot_id] = {
                str(path): str(fingerprint)
                for path, fingerprint in raw_paths.items()
                if isinstance(path, str) and isinstance(fingerprint, str)
            }
        return decoded

    if manifest.get("schema_version") != TEST_RUN_SCHEMA_VERSION:
        return {}

    raw_pairs = manifest.get("fingerprint_pairs")
    if not isinstance(raw_pairs, list):
        return {}
    pairs: list[tuple[str, str] | None] = []
    for raw_pair in raw_pairs:
        if (
            isinstance(raw_pair, list)
            and len(raw_pair) == 2
            and isinstance(raw_pair[0], str)
            and isinstance(raw_pair[1], str)
        ):
            pairs.append((raw_pair[0], raw_pair[1]))
        else:
            pairs.append(None)

    decoded = {}
    for snapshot_id, raw_snapshot in raw_snapshots.items():
        if not isinstance(snapshot_id, str) or not isinstance(raw_snapshot, dict):
            continue
        raw_pair_ids = raw_snapshot.get("fingerprints")
        if not isinstance(raw_pair_ids, list):
            continue
        paths: dict[str, str] = {}
        for pair_id in raw_pair_ids:
            if not isinstance(pair_id, int) or isinstance(pair_id, bool):
                continue
            if pair_id < 0 or pair_id >= len(pairs):
                continue
            pair = pairs[pair_id]
            if pair is not None:
                paths[pair[0]] = pair[1]
        decoded[snapshot_id] = paths
    return decoded


def encode_test_run_snapshots(
    snapshots: dict[str, dict[str, str]],
) -> tuple[list[list[str]], dict[str, dict[str, list[int]]]]:
    """Intern snapshot path/fingerprint pairs for compact test-run storage."""
    pairs = sorted(
        {
            (path, fingerprint)
            for paths in snapshots.values()
            for path, fingerprint in paths.items()
        }
    )
    pair_ids = {pair: index for index, pair in enumerate(pairs)}
    encoded = {
        snapshot_id: {
            "fingerprints": sorted(
                pair_ids[(path, fingerprint)]
                for path, fingerprint in paths.items()
            )
        }
        for snapshot_id, paths in snapshots.items()
    }
    return [list(pair) for pair in pairs], encoded


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
    """Wrap a traceability report in the repository's versioned JSON envelope."""
    return {
        "schema_version": TRACEABILITY_SCHEMA_VERSION,
        "kind": kind,
        "provenance": report_provenance,
        "findings": findings,
        "finding_ids": [finding["id"] for finding in findings],
        "report": report,
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None
