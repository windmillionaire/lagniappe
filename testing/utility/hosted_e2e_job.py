"""Cloud Run job entry point for the repository test suites."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from google.cloud import storage


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = REPOSITORY_ROOT / "reports"
HOSTED_REPORT_ROOT = REPORT_ROOT / "hosted-e2e"
EVIDENCE_PATH = REPOSITORY_ROOT / "testing/evidence/latest.json"
MAX_FOCUSED_TARGETS = 50


def _required_environment(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Hosted E2E job requires {name}.")
    return value


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_focused_targets_require_existing_e2e_nodeids
# @matrix hosted-e2e : argument-injection focused-execution target-validation
def validate_focused_targets(targets) -> tuple[str, ...]:
    """Return bounded existing E2E paths/nodeids safe for job arg overrides."""
    normalized = tuple(str(target).strip() for target in targets or ())
    if not normalized:
        raise RuntimeError("Focused hosted E2E requires at least one --target.")
    if len(normalized) > MAX_FOCUSED_TARGETS:
        raise RuntimeError(
            f"Focused hosted E2E accepts at most {MAX_FOCUSED_TARGETS} targets."
        )
    if len(set(normalized)) != len(normalized):
        raise RuntimeError("Focused hosted E2E targets must be unique.")

    e2e_root = (REPOSITORY_ROOT / "testing/tests_e2e").resolve()
    for target in normalized:
        if not target or len(target) > 512:
            raise RuntimeError("Focused hosted E2E received an invalid target.")
        if any(character in target for character in (",", "\x00", "\r", "\n")):
            raise RuntimeError(
                "Focused hosted E2E targets cannot contain commas or control characters."
            )
        path_text, separator, selector = target.partition("::")
        if not path_text.startswith("testing/tests_e2e/"):
            raise RuntimeError(
                "Focused hosted E2E targets must be real testing/tests_e2e paths."
            )
        relative_path = Path(path_text)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError("Focused hosted E2E targets cannot traverse directories.")
        target_path = (REPOSITORY_ROOT / relative_path).resolve()
        if (
            not target_path.is_relative_to(e2e_root)
            or target_path.suffix != ".py"
            or not target_path.is_file()
        ):
            raise RuntimeError(
                "Focused hosted E2E targets must name existing E2E Python files."
            )
        if separator and (
            not selector
            or any(not component for component in selector.split("::"))
        ):
            raise RuntimeError("Focused hosted E2E received an invalid nodeid selector.")
    return normalized


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_focused_targets_require_existing_e2e_nodeids
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_all_scope_runs_every_complete_suite_and_opt_in_contract
# @matrix hosted-e2e : argument-injection focused-execution target-validation
def _pytest_command(suite: str, targets=()) -> list[str]:
    if suite == "all":
        if targets:
            raise RuntimeError("All hosted tests do not accept focused targets.")
        pytest_targets = [
            "unit",
            "js",
            "tooling",
            "e2e",
            "-m",
            "not unfinished",
        ]
    elif suite == "full":
        if targets:
            raise RuntimeError("Full hosted E2E does not accept focused targets.")
        pytest_targets = ["e2e"]
    elif suite == "focused":
        pytest_targets = list(validate_focused_targets(targets))
    else:
        raise RuntimeError(f"Unsupported hosted E2E suite {suite!r}.")
    return [
        sys.executable,
        str(REPOSITORY_ROOT / "run.py"),
        "test",
        "--strict",
        *pytest_targets,
        f"--junitxml={HOSTED_REPORT_ROOT / 'junit.xml'}",
    ]


def _artifact_manifest(
    *,
    suite: str,
    exit_status: int,
    execution: str,
    started_at: datetime,
    finished_at: datetime,
    targets=(),
) -> dict:
    manifest = {
        "schema_version": 1,
        "kind": "hosted-e2e-result",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite_started_at": started_at.astimezone(timezone.utc).isoformat(),
        "suite_finished_at": finished_at.astimezone(timezone.utc).isoformat(),
        "execution": execution,
        "job": _required_environment("CLOUD_RUN_JOB"),
        "project": _required_environment("GOOGLE_CLOUD_PROJECT"),
        "service": _required_environment("LAGNIAPPE_HOSTED_E2E_SERVICE"),
        "version": _required_environment("LAGNIAPPE_HOSTED_E2E_VERSION"),
        "source": _required_environment("LAGNIAPPE_HOSTED_E2E_SOURCE"),
        "source_snapshot": _required_environment(
            "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT"
        ),
        "build_id": _required_environment("LAGNIAPPE_HOSTED_E2E_BUILD_ID"),
        "suite": suite,
        "exit_status": int(exit_status),
    }
    if targets:
        manifest["targets"] = list(targets)
    return manifest


def _archive_reports(destination: Path) -> None:
    with tarfile.open(destination, "w:gz", encoding="utf-8") as archive:
        if REPORT_ROOT.is_dir():
            for path in sorted(REPORT_ROOT.rglob("*")):
                if path.is_file() and not path.is_symlink() and path != destination:
                    archive.add(path, arcname=path.relative_to(REPOSITORY_ROOT))


def _stamp_evidence(manifest: dict) -> None:
    from testing.utility.traceability_common import load_json, write_json

    evidence = load_json(EVIDENCE_PATH)
    if not evidence or evidence.get("kind") != "test-run":
        raise RuntimeError("pytest did not produce valid traceability evidence")
    provenance = dict(evidence.get("provenance") or {})
    provenance["hosted_e2e"] = {
        key: manifest[key]
        for key in (
            "execution",
            "job",
            "service",
            "source",
            "source_snapshot",
            "build_id",
            "version",
            "suite",
            "suite_started_at",
            "suite_finished_at",
        )
    }
    if manifest.get("targets"):
        provenance["hosted_e2e"]["targets"] = list(manifest["targets"])
    evidence["provenance"] = provenance
    write_json(EVIDENCE_PATH, evidence)


def _upload_artifacts(manifest: dict) -> None:
    bucket_name = _required_environment("LAGNIAPPE_HOSTED_E2E_ARTIFACT_BUCKET")
    execution = manifest["execution"]
    prefix = f"executions/{execution}"
    client = storage.Client(project=manifest["project"])
    bucket = client.bucket(bucket_name)

    with tempfile.TemporaryDirectory(prefix="lagniappe-e2e-artifacts-") as temp_dir:
        temp_root = Path(temp_dir)
        manifest_path = temp_root / "manifest.json"
        archive_path = temp_root / "reports.tar.gz"
        manifest_path.write_text(
            f"{json.dumps(manifest, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
        _archive_reports(archive_path)
        if not EVIDENCE_PATH.is_file():
            raise RuntimeError("pytest did not produce traceability evidence")
        uploads = (
            ("evidence.json", EVIDENCE_PATH),
            ("junit.xml", HOSTED_REPORT_ROOT / "junit.xml"),
            ("reports.tar.gz", archive_path),
            # The manifest is the completion marker consumed by --latest.
            ("manifest.json", manifest_path),
        )
        for name, path in uploads:
            if path.is_file():
                bucket.blob(f"{prefix}/{name}").upload_from_filename(path)


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("all", "full", "focused"),
        default="all",
    )
    parser.add_argument("--target", action="append", default=[])
    args = parser.parse_args(arguments)

    targets = (
        validate_focused_targets(args.target)
        if args.suite == "focused"
        else tuple(args.target)
    )

    execution = _required_environment("CLOUD_RUN_EXECUTION")
    HOSTED_REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    result = subprocess.run(
        _pytest_command(args.suite, targets),
        cwd=REPOSITORY_ROOT,
    )
    finished_at = datetime.now(timezone.utc)
    manifest = _artifact_manifest(
        suite=args.suite,
        exit_status=result.returncode,
        execution=execution,
        started_at=started_at,
        finished_at=finished_at,
        targets=targets,
    )
    try:
        _stamp_evidence(manifest)
        _upload_artifacts(manifest)
    except Exception as error:
        print(f"Hosted E2E artifact upload failed: {error}", file=sys.stderr)
        return result.returncode or 2
    print(
        "Hosted E2E artifacts uploaded to "
        f"gs://{os.environ['LAGNIAPPE_HOSTED_E2E_ARTIFACT_BUCKET']}/"
        f"executions/{execution}/"
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
