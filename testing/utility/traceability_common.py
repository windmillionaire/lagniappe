"""Report formatting and Git diff helpers for source and contract reports."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Iterable

from testing.utility.test_evidence import (
    LATEST_TEST_RUN as LATEST_TEST_RUN,
    TEST_RUN_SCHEMA_VERSION as TEST_RUN_SCHEMA_VERSION,
    _git,
    behavior_path_fingerprints as behavior_path_fingerprints,
    behavior_snapshot as behavior_snapshot,
    decode_test_run_snapshots as decode_test_run_snapshots,
    encode_test_run_snapshots as encode_test_run_snapshots,
    load_json as load_json,
    utc_now,
    write_json as write_json,
)

TRACEABILITY_SCHEMA_VERSION = 3


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
