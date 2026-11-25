"""Download hosted results, import test evidence, and verify release provenance."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from config import APP_DIR

from .preflight import _committed_build_id, _git
from .runtime import (
    EXECUTION_RE,
    HostedE2EError,
    STATE_ROOT,
    _activate,
    _environment,
    _infrastructure,
    _load_json,
)


class ReleaseEvidence(TypedDict):
    base: str
    candidate: str
    evidence: str
    mode: str
    source_snapshot: str


def _evidence_exit_status(document: object) -> int:
    status = document.get("exit_status") if isinstance(document, dict) else None
    if type(status) is not int:
        raise HostedE2EError("Hosted result evidence requires an integer exit status.")
    return status


def format_execute_summary(
    payload: dict[str, object],
    *,
    imported: bool = True,
    state_root: Path = STATE_ROOT,
    result_root: Path | None = None,
    environment: str = "standard",
) -> str:
    """Format an operator-facing summary for one hosted execution result."""
    execution = str(payload.get("execution") or "unknown")
    exit_status = _evidence_exit_status(payload)
    result = "PASSED" if exit_status == 0 else "FAILED"
    lines = [
        "",
        f"Hosted E2E {result}",
        f"Execution: {execution}",
        f"Suite: {payload.get('suite') or 'unknown'}",
    ]
    source = str(payload.get("source") or "").strip()
    if source:
        lines.append(f"Source: {source}")
    version = str(payload.get("version") or "").strip()
    build_id = str(payload.get("build_id") or "").strip()
    if version or build_id:
        deployment = version or "unknown version"
        if build_id:
            deployment = f"{deployment} (build {build_id})"
        lines.append(f"Deployment: {deployment}")

    started_at = payload.get("suite_started_at")
    finished_at = payload.get("suite_finished_at")
    if isinstance(started_at, str) and isinstance(finished_at, str):
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            elapsed = max(0, int((finished - started).total_seconds()))
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                duration = f"{hours}h {minutes}m {seconds}s"
            elif minutes:
                duration = f"{minutes}m {seconds}s"
            else:
                duration = f"{seconds}s"
            lines.append(f"Duration: {duration}")
        except ValueError:
            pass

    selected = _environment(environment)
    result_root = (
        Path(result_root)
        if result_root is not None
        else Path(state_root) / selected.result_directory
    )
    destination = result_root / execution
    junit_path = destination / "junit.xml"
    if imported and junit_path.is_file():
        try:
            testcases = ElementTree.parse(junit_path).getroot().findall(".//testcase")
        except (ElementTree.ParseError, OSError):
            testcases = []
        if testcases:
            outcomes = {}
            teardown_errors = 0
            for testcase in testcases:
                identity = (
                    testcase.get("classname") or "",
                    testcase.get("name") or "",
                )
                outcome = outcomes.setdefault(
                    identity,
                    {"failure": None, "error": None, "skipped": False},
                )
                failure = testcase.find("failure")
                error = testcase.find("error")
                skipped = testcase.find("skipped")
                if failure is not None and outcome["failure"] is None:
                    outcome["failure"] = failure
                if error is not None and outcome["error"] is None:
                    outcome["error"] = error
                if error is not None:
                    teardown_errors += 1
                if skipped is not None:
                    outcome["skipped"] = True

            failed = [
                (identity, outcome)
                for identity, outcome in outcomes.items()
                if outcome["failure"] is not None or outcome["error"] is not None
            ]
            skipped_count = sum(
                outcome["skipped"]
                and outcome["failure"] is None
                and outcome["error"] is None
                for outcome in outcomes.values()
            )
            passed = len(outcomes) - len(failed) - skipped_count
            lines.append(
                f"Tests: {len(outcomes):,} total — {passed:,} passed, "
                f"{len(failed):,} failed, {skipped_count:,} skipped"
            )
            if teardown_errors:
                lines.append(f"Additional error records: {teardown_errors:,}")
            if failed:
                lines.append("Failed tests:")
                for (classname, name), outcome in failed[:12]:
                    parts = classname.split(".") if classname else []
                    module_indexes = [
                        index
                        for index, part in enumerate(parts)
                        if part.startswith("test_")
                    ]
                    if parts and module_indexes and parts[0].startswith("tests_"):
                        module_index = module_indexes[-1]
                        test_path = Path(
                            "testing", *parts[: module_index + 1]
                        ).with_suffix(".py")
                        qualifiers = parts[module_index + 1 :]
                        nodeid_parts = [test_path.as_posix(), *qualifiers, name]
                        nodeid = "::".join(part for part in nodeid_parts if part)
                    else:
                        nodeid = f"{classname}::{name}" if classname else name
                    problem = (
                        outcome["failure"]
                        if outcome["failure"] is not None
                        else outcome["error"]
                    )
                    message = str(problem.get("message") or "").splitlines()[0].strip()
                    lines.append(f"  - {nodeid}")
                    if message:
                        lines.append(f"    {message}")
                remaining = len(failed) - 12
                if remaining > 0:
                    lines.append(f"  - …and {remaining} more; see JUnit XML below.")

    if imported:
        lines.append(f"Artifacts: {destination.resolve()}")
        if junit_path.is_file():
            lines.append(f"JUnit XML: {junit_path.resolve()}")
    else:
        lines.append("Results were left in Cloud Storage and were not imported.")
        environment_argument = (
            ""
        )
        lines.append(
            "Import later: venv/bin/python run.py hosted-e2e results "
            f"{environment_argument}--execution {execution}"
        )
    return "\n".join(lines)


def _latest_execution(infrastructure, *, environment="standard"):
    selected = _environment(environment)
    from google.cloud import storage

    client = storage.Client(project=infrastructure.project)
    bucket = client.bucket(infrastructure.artifact_bucket)
    manifests = [
        blob
        for blob in client.list_blobs(bucket, prefix="executions/")
        if blob.name.endswith("/manifest.json")
        and blob.name.split("/", 2)[1].startswith(f"{selected.job}-")
    ]
    if not manifests:
        raise HostedE2EError("No hosted E2E result artifacts exist.")
    newest = max(
        manifests,
        key=lambda blob: blob.updated or datetime.min.replace(tzinfo=UTC),
    )
    return newest.name.split("/", 2)[1]


def merge_remote_evidence(local: object, remote: object) -> dict[str, object]:
    """Merge a hosted pytest manifest into the normal latest evidence file."""
    from testing.utility.test_evidence import (
        TEST_RUN_SCHEMA_VERSION,
        decode_test_run_snapshots,
        encode_test_run_snapshots,
    )

    if (
        not isinstance(remote, dict)
        or remote.get("schema_version") != TEST_RUN_SCHEMA_VERSION
    ):
        raise HostedE2EError("Hosted result evidence has an unsupported schema.")
    if remote.get("kind") != "test-run" or not isinstance(remote.get("tests"), dict):
        raise HostedE2EError("Hosted result evidence is malformed.")
    local = (
        local
        if isinstance(local, dict)
        and local.get("schema_version") in {2, TEST_RUN_SCHEMA_VERSION}
        else {}
    )
    tests = dict(local.get("tests") or {})
    tests.update(remote["tests"])
    snapshots = decode_test_run_snapshots(local)
    for snapshot_id, paths in decode_test_run_snapshots(remote).items():
        if snapshot_id in snapshots and snapshots[snapshot_id] != paths:
            raise HostedE2EError("Evidence snapshot identity collision detected.")
        snapshots[snapshot_id] = paths
    used_snapshots = {
        row.get("snapshot")
        for row in tests.values()
        if isinstance(row, dict) and isinstance(row.get("snapshot"), str)
    }
    snapshots = {
        key: value for key, value in snapshots.items() if key in used_snapshots
    }
    pairs, encoded = encode_test_run_snapshots(snapshots)
    sessions = [
        *list(local.get("sessions") or []),
        *list(remote.get("sessions") or []),
    ][-50:]
    return {
        "schema_version": TEST_RUN_SCHEMA_VERSION,
        "kind": "test-run",
        "provenance": remote.get("provenance") or {},
        "exit_status": _evidence_exit_status(remote),
        "sessions": sessions,
        "fingerprint_pairs": pairs,
        "snapshots": encoded,
        "tests": dict(sorted(tests.items())),
    }


def import_result_directory(
    directory: Path, *, expected_execution: str | None = None
) -> dict[str, object]:
    """Validate and merge an already-downloaded hosted result directory."""
    from testing.utility.test_evidence import (
        LATEST_TEST_RUN,
        behavior_snapshot,
        load_json,
        write_json,
    )

    directory = Path(directory)
    manifest = load_json(directory / "manifest.json")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "hosted-e2e-result"
    ):
        raise HostedE2EError("Hosted result manifest has an unsupported schema.")
    execution = manifest.get("execution") if isinstance(manifest, dict) else None
    if not isinstance(execution, str) or not EXECUTION_RE.fullmatch(execution):
        raise HostedE2EError("Hosted result manifest has no valid execution name.")
    if expected_execution is not None and execution != expected_execution:
        raise HostedE2EError("Hosted result manifest does not match its execution.")

    source = _git("rev-parse", "HEAD").stdout.strip().casefold()
    source_snapshot, _source_paths = behavior_snapshot(APP_DIR)
    if (
        manifest.get("source") != source
        or manifest.get("source_snapshot") != source_snapshot
    ):
        raise HostedE2EError(
            "Hosted result source does not match the local semantic tree; "
            f"artifacts remain at {directory} but evidence was not merged."
        )

    remote = load_json(directory / "evidence.json")
    if not isinstance(remote, dict):
        raise HostedE2EError("Hosted result evidence is malformed.")
    status = _evidence_exit_status(manifest)
    if _evidence_exit_status(remote) != status:
        raise HostedE2EError("Hosted result manifest and evidence exit statuses disagree.")
    provenance = remote.get("provenance")
    hosted = provenance.get("hosted_e2e") if isinstance(provenance, dict) else None
    if (
        not isinstance(hosted, dict)
        or not isinstance(manifest.get("suite"), str)
        or not re.fullmatch(r"b[0-9a-f]{7}", str(manifest.get("build_id") or ""))
        or any(
            hosted.get(key) != manifest[key]
            for key in ("execution", "source", "source_snapshot", "suite", "build_id")
        )
        or any(
            (key in manifest) != (key in hosted) or manifest.get(key) != hosted.get(key)
            for key in ("targets", "environment")
        )
    ):
        raise HostedE2EError("Hosted result manifest and evidence provenance disagree.")
    if hosted["build_id"] != _committed_build_id(source, APP_DIR):
        raise HostedE2EError("Hosted result build ID does not match the committed frontend build.")
    evidence_path = APP_DIR / LATEST_TEST_RUN
    local = load_json(evidence_path)
    if (
        manifest.get("suite") == "all"
        and "targets" not in manifest
        and status == 0
    ):
        # A complete successful inventory supersedes retired test IDs, including
        # bare functions that now have parameters. Partial runs still merge.
        local = None
    merged = merge_remote_evidence(local, remote)
    write_json(evidence_path, merged)
    return manifest


def validate_release_evidence(
    candidate: str,
    evidence: str,
    *,
    base: str,
    repo_root: Path = APP_DIR,
) -> ReleaseEvidence:
    """Validate passing hosted evidence for an exact release commit chain."""
    from testing.utility.test_evidence import (
        LATEST_TEST_RUN,
        TEST_RUN_SCHEMA_VERSION,
        behavior_snapshot,
        load_json,
    )

    repo_root = Path(repo_root)
    revisions = {"base": base, "candidate": candidate, "evidence": evidence}
    for label, revision in revisions.items():
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise HostedE2EError(f"The release {label} is not an exact commit SHA.")

    head = _git("rev-parse", "HEAD", repo_root=repo_root).stdout.strip().casefold()
    if head != evidence:
        raise HostedE2EError(
            f"The checked-out release head is {head}, not evidence commit {evidence}."
        )

    ancestry = _git(
        "merge-base",
        "--is-ancestor",
        base,
        candidate,
        check=False,
        repo_root=repo_root,
    )
    if ancestry.returncode != 0:
        raise HostedE2EError(
            "The release candidate is not descended from the pull-request base."
        )

    mode = "candidate"
    if evidence != candidate:
        mode = "continuation"
        parents = (
            _git(
                "show",
                "--no-patch",
                "--format=%P",
                evidence,
                repo_root=repo_root,
            )
            .stdout.strip()
            .casefold()
            .split()
        )
        if parents != [candidate]:
            raise HostedE2EError(
                "The evidence continuation must have the exact candidate as its only parent."
            )
        changed = _git(
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            candidate,
            evidence,
            repo_root=repo_root,
        ).stdout.splitlines()
        if changed != [f"M\t{LATEST_TEST_RUN.as_posix()}"]:
            raise HostedE2EError(
                "The evidence continuation must modify only testing/evidence/latest.json."
            )

    payload = load_json(repo_root / LATEST_TEST_RUN)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != TEST_RUN_SCHEMA_VERSION
        or payload.get("kind") != "test-run"
    ):
        raise HostedE2EError("Release evidence has an unsupported schema.")
    provenance = payload.get("provenance")
    hosted = provenance.get("hosted_e2e") if isinstance(provenance, dict) else None
    if not isinstance(hosted, dict):
        raise HostedE2EError("Release evidence has no hosted-E2E provenance.")

    source_snapshot, _source_paths = behavior_snapshot(repo_root)
    if hosted.get("source") != candidate:
        raise HostedE2EError(
            "Release evidence does not name the exact candidate source."
        )
    if hosted.get("source_snapshot") != source_snapshot:
        raise HostedE2EError(
            "Release evidence does not match the current semantic source tree."
        )
    if hosted.get("build_id") != _committed_build_id(candidate, repo_root):
        raise HostedE2EError("Release evidence does not match the candidate frontend build ID.")
    if hosted.get("suite") != "all" or "targets" in hosted:
        raise HostedE2EError(
            "Release evidence must come from the complete hosted all suite."
        )
    if type(payload.get("exit_status")) is not int or payload["exit_status"] != 0:
        raise HostedE2EError("The hosted release suite did not pass.")

    return {
        "base": base,
        "candidate": candidate,
        "evidence": evidence,
        "mode": mode,
        "source_snapshot": source_snapshot,
    }


def results(
    *,
    execution: str | None = None,
    latest: bool = False,
    merge: bool = True,
    include_report_archive: bool = True,
    environment: str = "standard",
) -> dict[str, object]:
    """Download one result bundle and merge its outcomes into evidence.json."""
    selected = _environment(environment)
    _activate(adc=True)
    infrastructure = _infrastructure()
    state = _load_json(selected.state_path) or {}
    if latest:
        execution = _latest_execution(infrastructure, environment=selected.name)
    selected_execution = execution or state.get("last_execution")
    if (
        not isinstance(selected_execution, str)
        or not selected_execution.startswith(f"{selected.job}-")
        or not EXECUTION_RE.fullmatch(selected_execution)
    ):
        raise HostedE2EError("A valid Cloud Run execution name is required.")

    execution = selected_execution
    from google.cloud import storage

    destination = selected.result_root / execution
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading hosted test artifacts to {destination}", flush=True)
    client = storage.Client(project=infrastructure.project)
    bucket = client.bucket(infrastructure.artifact_bucket)
    downloaded = {}
    artifact_names = ["manifest.json", "evidence.json", "junit.xml"]
    if include_report_archive:
        artifact_names.append("reports.tar.gz")
    for name in artifact_names:
        blob = bucket.blob(f"executions/{execution}/{name}")
        if not blob.exists(client=client):
            if name in {"manifest.json", "evidence.json"}:
                raise HostedE2EError(f"Hosted result is missing required {name}.")
            continue
        path = destination / name
        print(f"  downloading {name}...", end="", flush=True)
        blob.download_to_filename(path)
        print(f" {path.stat().st_size:,} bytes", flush=True)
        downloaded[name] = path

    manifest = _load_json(downloaded["manifest.json"])
    if not manifest or manifest.get("execution") != execution:
        raise HostedE2EError("Hosted result manifest does not match its execution.")
    manifest_job = manifest.get("job")
    if (
        manifest_job not in {None, selected.job}
    ):
        raise HostedE2EError("Hosted result manifest belongs to another environment.")
    if merge:
        return import_result_directory(
            destination,
            expected_execution=execution,
        )
    return manifest
