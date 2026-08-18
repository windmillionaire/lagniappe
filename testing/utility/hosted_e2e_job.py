"""Cloud Run job entry point for the existing E2E pytest suite."""

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
PILOT_TARGETS = (
    "testing/tests_e2e/001_site/test_001a_environment.py::test_database_setup",
    "testing/tests_e2e/001_site/test_001a_environment.py::test_cache_setup",
    "testing/tests_e2e/001_site/test_001a_environment.py::test_storage_setup",
    "testing/tests_e2e/001_site/test_001b_login.py::test_user_login_success",
)


def _required_environment(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Hosted E2E job requires {name}.")
    return value


def _pytest_command(suite: str) -> list[str]:
    targets = ["e2e"] if suite == "full" else list(PILOT_TARGETS)
    return [
        sys.executable,
        str(REPOSITORY_ROOT / "run.py"),
        "test",
        "--strict",
        *targets,
        f"--junitxml={HOSTED_REPORT_ROOT / 'junit.xml'}",
    ]


def _artifact_manifest(*, suite: str, exit_status: int, execution: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "hosted-e2e-result",
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
        )
    }
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
    parser.add_argument("--suite", choices=("pilot", "full"), default="pilot")
    args = parser.parse_args(arguments)

    execution = _required_environment("CLOUD_RUN_EXECUTION")
    HOSTED_REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(_pytest_command(args.suite), cwd=REPOSITORY_ROOT)
    manifest = _artifact_manifest(
        suite=args.suite,
        exit_status=result.returncode,
        execution=execution,
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
