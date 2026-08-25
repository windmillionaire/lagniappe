"""Offline contracts for the hosted-E2E lifecycle and evidence bridge."""

from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys

import pytest
import yaml

from runner import hosted_e2e
from runner.hosted_e2e_anchor import main as hosted_e2e_anchor
from runner.hosted_e2e import (
    HostedE2EError,
    HostedE2EInfrastructure,
    _describe,
    _hosted_app_descriptor,
    _verify_soft_routing_guard,
    merge_remote_evidence,
    require_clean_source,
)
from testing.utility.traceability_common import (
    TEST_RUN_SCHEMA_VERSION,
    behavior_snapshot,
    decode_test_run_snapshots,
    encode_test_run_snapshots,
)
from testing.utility import hosted_e2e_job, traceability_common


pytestmark = pytest.mark.tooling


def _infrastructure():
    return HostedE2EInfrastructure(
        project="project-1",
        project_number="1234",
        region="us-central1",
        service="e2e",
        job="lagniappe-e2e",
        runtime_email="runtime@project-1.iam.gserviceaccount.com",
        invoker_email="invoker@project-1.iam.gserviceaccount.com",
        artifact_repository="lagniappe-e2e",
        artifact_bucket="lagniappe-e2e-artifacts-example",
        settings_secret="lagniappe-e2e-settings",
        redis_ca_secret="lagniappe-e2e-redis-ca",
        workload_pool="lagniappe-e2e",
        workload_provider="github",
    )


def _git(repo, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


# @matrix hosted-e2e : deletion-safety provider-errors
def test_provider_describe_distinguishes_absence_from_operational_errors(monkeypatch):
    missing = subprocess.CompletedProcess(
        ["gcloud"],
        returncode=1,
        stdout="",
        stderr="NOT_FOUND: the resource does not exist",
    )
    monkeypatch.setattr(hosted_e2e, "_gcloud", lambda *_args, **_kwargs: missing)
    assert _describe(["run", "jobs", "describe", "missing"]) is None

    denied = subprocess.CompletedProcess(
        ["gcloud"],
        returncode=1,
        stdout="",
        stderr="PERMISSION_DENIED: caller cannot inspect the job",
    )
    monkeypatch.setattr(hosted_e2e, "_gcloud", lambda *_args, **_kwargs: denied)
    with pytest.raises(HostedE2EError, match="PERMISSION_DENIED"):
        _describe(["run", "jobs", "describe", "protected"])


# @matrix hosted-e2e : api-propagation build-identity first-setup
def test_cloud_build_identity_waits_for_first_setup_propagation(monkeypatch):
    results = iter(
        (
            subprocess.CompletedProcess(
                ["gcloud"], returncode=0, stdout="", stderr=""
            ),
            subprocess.CompletedProcess(
                ["gcloud"],
                returncode=0,
                stdout=(
                    "projects/1234/serviceAccounts/"
                    "1234-compute@developer.gserviceaccount.com\n"
                ),
                stderr="",
            ),
        )
    )
    calls = []
    delays = []

    def gcloud(*arguments, **options):
        calls.append((arguments, options))
        return next(results)

    monkeypatch.setattr(hosted_e2e, "_gcloud", gcloud)
    monkeypatch.setattr(hosted_e2e.time, "sleep", delays.append)

    assert hosted_e2e._cloud_build_service_account(_infrastructure()) == (
        "1234-compute@developer.gserviceaccount.com"
    )
    assert delays == [2]
    assert len(calls) == 2
    assert calls[0][0][-1] == "--format=value(serviceAccountEmail)"
    assert calls[0][1] == {"check": False}


# @matrix hosted-e2e : api-propagation build-identity first-setup
def test_cloud_build_identity_rejects_legacy_cloud_build_account(monkeypatch):
    legacy = subprocess.CompletedProcess(
        ["gcloud"],
        returncode=0,
        stdout="1234@cloudbuild.gserviceaccount.com\n",
        stderr="",
    )
    monkeypatch.setattr(hosted_e2e, "_gcloud", lambda *_args, **_options: legacy)
    monkeypatch.setattr(hosted_e2e.time, "sleep", lambda _delay: None)

    with pytest.raises(HostedE2EError, match="Compute Engine default"):
        hosted_e2e._cloud_build_service_account(_infrastructure())


# @matrix hosted-e2e : deletion-safety production-preflight soft-routing
def test_soft_routing_guard_preflight_requires_marker(monkeypatch):
    class Response:
        status_code = 404
        headers = {"X-Lagniappe-Hosted-E2E-Guard": "active"}

    calls = []
    monkeypatch.setattr(
        "requests.get",
        lambda url, **options: calls.append((url, options)) or Response(),
    )
    monkeypatch.setattr(
        hosted_e2e,
        "_app_default_hostname",
        lambda _infrastructure: "project-1.uc.r.appspot.com",
    )

    _verify_soft_routing_guard(_infrastructure())

    assert calls[0][0].startswith("https://e2e-")
    assert calls[0][0].endswith(
        "-dot-e2e-dot-project-1.uc.r.appspot.com/users/login"
    )
    assert calls[0][1] == {"allow_redirects": False, "timeout": 30}

    Response.headers = {}
    with pytest.raises(HostedE2EError, match="rerun hosted-E2E setup"):
        _verify_soft_routing_guard(_infrastructure())


# @matrix hosted-e2e : anchor deletion-safety soft-routing
def test_hosted_anchor_marks_every_rejection():
    response = {}

    def start_response(status, headers):
        response["status"] = status
        response["headers"] = dict(headers)

    body = b"".join(hosted_e2e_anchor.app({}, start_response))

    assert response["status"] == "404 Not Found"
    assert response["headers"]["X-Lagniappe-Hosted-E2E-Guard"] == "active"
    assert response["headers"]["X-Lagniappe-Hosted-E2E-Anchor"] == "active"
    assert body == b"Not Found\n"


# @matrix hosted-e2e : anchor deletion-safety reconciliation soft-routing
def test_hosted_anchor_redeploys_only_when_its_contract_is_stale(
    tmp_path,
    monkeypatch,
):
    calls = []
    descriptors = []
    events = []

    def gcloud(*arguments, **options):
        calls.append((arguments, options))
        if arguments[:2] == ("app", "deploy"):
            events.append("deploy")
            descriptors.append(
                yaml.safe_load(arguments[2].read_text(encoding="utf-8"))
            )
        elif arguments[:3] == ("app", "services", "set-traffic"):
            events.append("traffic")
        return subprocess.CompletedProcess(
            ["gcloud"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(hosted_e2e, "ANCHOR_ROOT", tmp_path)
    monkeypatch.setattr(hosted_e2e, "_gcloud", gcloud)
    monkeypatch.setattr(
        hosted_e2e,
        "_verify_soft_routing_guard",
        lambda _infrastructure: events.append("guard"),
    )
    monkeypatch.setattr(
        hosted_e2e,
        "_describe",
        lambda _arguments: {"envVariables": {}},
    )

    hosted_e2e._ensure_anchor(_infrastructure())

    assert descriptors[0]["env_variables"] == {
        "HOSTED_E2E_ANCHOR_REVISION": hosted_e2e.ANCHOR_REVISION
    }
    assert calls[-1][0][:4] == ("app", "services", "set-traffic", "e2e")
    assert events == ["deploy", "traffic", "guard"]

    calls.clear()
    descriptors.clear()
    events.clear()
    monkeypatch.setattr(
        hosted_e2e,
        "_describe",
        lambda _arguments: {
            "envVariables": {
                "HOSTED_E2E_ANCHOR_REVISION": hosted_e2e.ANCHOR_REVISION
            }
        },
    )

    hosted_e2e._ensure_anchor(_infrastructure())

    assert descriptors == []
    assert calls[-1][0][:4] == ("app", "services", "set-traffic", "e2e")
    assert events == ["traffic", "guard"]

    calls.clear()
    events.clear()
    monkeypatch.setattr(hosted_e2e, "_describe", lambda _arguments: None)

    hosted_e2e._ensure_anchor(_infrastructure())

    assert events == ["guard", "deploy", "traffic", "guard"]


# @matrix hosted-e2e : generated-assets lifecycle source-integrity
def test_hosted_e2e_requires_a_clean_committed_source(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Hosted E2E Test")
    _git(tmp_path, "config", "user.email", "hosted-e2e@example.test")
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "source.py")
    _git(tmp_path, "commit", "-m", "initial")

    head = require_clean_source(tmp_path)

    assert len(head) == 40
    generated = tmp_path / "lagniappe/web/static/generated.js"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated\n", encoding="utf-8")
    assert require_clean_source(tmp_path) == head

    source.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(HostedE2EError, match="clean working tree"):
        require_clean_source(tmp_path)


# @matrix hosted-e2e release traceability : provider-mutation release-base source-quality
def test_hosted_create_preflight_runs_before_provider_activation(monkeypatch):
    revision = "a" * 40
    commands = []

    monkeypatch.setattr(hosted_e2e, "NPM_CLI", "npm")
    monkeypatch.setattr(
        hosted_e2e,
        "_git",
        lambda *arguments, **options: subprocess.CompletedProcess(
            arguments,
            returncode=0,
            stdout=f"{revision}\n",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        hosted_e2e,
        "run_command",
        lambda command, **options: commands.append((command, options))
        or subprocess.CompletedProcess(command, returncode=0),
    )

    assert (
        hosted_e2e._run_create_preflight(revision, base_ref="release-base")
        == revision
    )

    command_arguments = [list(map(str, command)) for command, _options in commands]
    assert command_arguments[0] == ["npm", "run", "check"]
    assert command_arguments[1][1:] == ["-m", "ruff", "check", "."]
    assert command_arguments[2][2:] == ["test", "tooling"]
    assert command_arguments[3][2:4] == ["traceability", "--check"]
    assert "--changed" not in command_arguments[3]
    assert command_arguments[4][2:] == [
        "release-check",
        "--base",
        revision,
    ]
    assert all(
        options
        == {
            "check": False,
            "capture_output": False,
            "timeout": 1800,
            "cwd": hosted_e2e.APP_DIR,
        }
        for _command, options in commands
    )

    events = []
    monkeypatch.setattr(
        hosted_e2e,
        "require_clean_source",
        lambda: events.append("source") or revision,
    )
    monkeypatch.setattr(
        hosted_e2e,
        "_require_committed_production_build",
        lambda _source: events.append("build") or "b1234567",
    )

    def stop_preflight(source, *, base_ref):
        events.append(("preflight", source, base_ref))
        raise HostedE2EError("preflight stopped")

    monkeypatch.setattr(hosted_e2e, "_run_create_preflight", stop_preflight)
    monkeypatch.setattr(
        hosted_e2e,
        "_activate",
        lambda **_options: events.append("provider"),
    )

    with pytest.raises(HostedE2EError, match="preflight stopped"):
        hosted_e2e.create(base_ref="release-base")

    assert events == [
        "source",
        "build",
        ("preflight", revision, "release-base"),
    ]


def _evidence(snapshot, paths, test_name, outcome="passed"):
    pairs, snapshots = encode_test_run_snapshots({snapshot: paths})
    return {
        "schema_version": TEST_RUN_SCHEMA_VERSION,
        "kind": "test-run",
        "provenance": {"behavior_snapshot": snapshot},
        "exit_status": 0 if outcome == "passed" else 1,
        "sessions": [{"snapshot": snapshot, "tests": 1}],
        "fingerprint_pairs": pairs,
        "snapshots": snapshots,
        "tests": {
            test_name: {
                "outcome": outcome,
                "duration": 0.1,
                "snapshot": snapshot,
            }
        },
    }


def _release_evidence_repository(
    repo,
    *,
    exit_status=0,
    suite="all",
    targets=None,
    extra_change=False,
):
    _git(repo, "init")
    _git(repo, "config", "user.name", "Hosted Release Test")
    _git(repo, "config", "user.email", "hosted-release@example.test")
    source = repo / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    evidence_path = repo / traceability_common.LATEST_TEST_RUN
    traceability_common.write_json(evidence_path, {})
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()

    source.write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Candidate")
    candidate = _git(repo, "rev-parse", "HEAD").stdout.strip()
    snapshot, paths = behavior_snapshot(repo)
    payload = _evidence(
        snapshot,
        paths,
        "testing/tests_unit/test_release.py::test_release",
    )
    payload["exit_status"] = exit_status
    payload["provenance"]["hosted_e2e"] = {
        "execution": "lagniappe-e2e-release1",
        "job": "lagniappe-e2e",
        "service": "e2e",
        "source": candidate,
        "source_snapshot": snapshot,
        "build_id": "b1234567",
        "version": "e2e-abcdef1234567890",
        "suite": suite,
    }
    if targets is not None:
        payload["provenance"]["hosted_e2e"]["targets"] = targets
    traceability_common.write_json(evidence_path, payload)
    if extra_change:
        (repo / "unexpected.txt").write_text("changed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Evidence")
    evidence = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return base, candidate, evidence


# @matrix hosted-e2e : branch-movement source-integrity
# @pairs release:continuation traceability:evidence
def test_release_evidence_validation_requires_exact_candidate_parent_and_snapshot(
    tmp_path,
):
    repo = tmp_path / "valid"
    repo.mkdir()
    base, candidate, evidence = _release_evidence_repository(repo)

    result = hosted_e2e.validate_release_evidence(
        candidate,
        evidence,
        base=base,
        repo_root=repo,
    )

    assert result["mode"] == "continuation"
    assert result["candidate"] == candidate
    assert result["evidence"] == evidence

    _git(repo, "switch", "--detach", base)
    (repo / "base-moved.txt").write_text("advanced base\n", encoding="utf-8")
    _git(repo, "add", "base-moved.txt")
    _git(repo, "commit", "-m", "Advance base elsewhere")
    advanced_base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "switch", "--detach", evidence)
    with pytest.raises(HostedE2EError, match="not descended"):
        hosted_e2e.validate_release_evidence(
            candidate,
            evidence,
            base=advanced_base,
            repo_root=repo,
        )

    with pytest.raises(HostedE2EError, match="exact candidate as its only parent"):
        hosted_e2e.validate_release_evidence(
            base,
            evidence,
            base=base,
            repo_root=repo,
        )

    source = repo / "source.py"
    source.write_text("VALUE = 3\n", encoding="utf-8")
    with pytest.raises(HostedE2EError, match="semantic source tree"):
        hosted_e2e.validate_release_evidence(
            candidate,
            evidence,
            base=base,
            repo_root=repo,
        )
    source.write_text("VALUE = 2\n", encoding="utf-8")

    (repo / "moved.txt").write_text("new head\n", encoding="utf-8")
    _git(repo, "add", "moved.txt")
    _git(repo, "commit", "-m", "Move branch")
    with pytest.raises(HostedE2EError, match="checked-out release head"):
        hosted_e2e.validate_release_evidence(
            candidate,
            evidence,
            base=base,
            repo_root=repo,
        )

    extra_repo = tmp_path / "extra"
    extra_repo.mkdir()
    extra_base, extra_candidate, extra_evidence = _release_evidence_repository(
        extra_repo,
        extra_change=True,
    )
    with pytest.raises(HostedE2EError, match="modify only"):
        hosted_e2e.validate_release_evidence(
            extra_candidate,
            extra_evidence,
            base=extra_base,
            repo_root=extra_repo,
        )


# @matrix hosted-e2e : failure-retention suite-scope target-validation
def test_release_evidence_validation_rejects_failed_or_focused_results(tmp_path):
    failed_repo = tmp_path / "failed"
    failed_repo.mkdir()
    base, candidate, evidence = _release_evidence_repository(
        failed_repo,
        exit_status=1,
    )
    with pytest.raises(HostedE2EError, match="did not pass"):
        hosted_e2e.validate_release_evidence(
            candidate,
            evidence,
            base=base,
            repo_root=failed_repo,
        )

    focused_repo = tmp_path / "focused"
    focused_repo.mkdir()
    base, candidate, evidence = _release_evidence_repository(
        focused_repo,
        suite="focused",
        targets=["testing/tests_e2e/test_example.py::test_example"],
    )
    with pytest.raises(HostedE2EError, match="complete hosted all suite"):
        hosted_e2e.validate_release_evidence(
            candidate,
            evidence,
            base=base,
            repo_root=focused_repo,
        )


def test_hosted_result_stamps_remote_provenance(tmp_path, monkeypatch):
    evidence_path = tmp_path / "latest.json"
    traceability_common.write_json(
        evidence_path,
        _evidence(
            "snapshot",
            {"source.py": "fingerprint"},
            "tests_e2e/test_remote.py::test_remote",
        ),
    )
    monkeypatch.setattr(hosted_e2e_job, "EVIDENCE_PATH", evidence_path)
    manifest = {
        "execution": "lagniappe-e2e-example",
        "job": "lagniappe-e2e",
        "service": "e2e",
        "source": "a" * 40,
        "source_snapshot": "b" * 64,
        "build_id": "b1234567",
        "version": "e2e-abcdef1234567890",
        "suite": "all",
        "suite_started_at": "2026-08-20T01:00:00+00:00",
        "suite_finished_at": "2026-08-20T01:30:00+00:00",
    }

    hosted_e2e_job._stamp_evidence(manifest)

    evidence = traceability_common.load_json(evidence_path)
    assert evidence["provenance"]["hosted_e2e"] == manifest


def test_hosted_manifest_records_exact_suite_window(monkeypatch):
    environment = {
        "CLOUD_RUN_JOB": "lagniappe-e2e",
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "LAGNIAPPE_HOSTED_E2E_SERVICE": "e2e",
        "LAGNIAPPE_HOSTED_E2E_VERSION": "e2e-abcdef1234567890",
        "LAGNIAPPE_HOSTED_E2E_SOURCE": "a" * 40,
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT": "b" * 64,
        "LAGNIAPPE_HOSTED_E2E_BUILD_ID": "b1234567",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    started_at = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 8, 20, 1, 30, tzinfo=timezone.utc)

    manifest = hosted_e2e_job._artifact_manifest(
        suite="all",
        exit_status=1,
        execution="lagniappe-e2e-example",
        started_at=started_at,
        finished_at=finished_at,
    )

    assert manifest["suite_started_at"] == "2026-08-20T01:00:00+00:00"
    assert manifest["suite_finished_at"] == "2026-08-20T01:30:00+00:00"


# @matrix hosted-e2e : argument-injection focused-execution target-validation
def test_hosted_focused_targets_require_existing_e2e_nodeids():
    target = (
        "testing/tests_e2e/001_site/test_001a_environment.py::"
        "test_database_setup"
    )

    assert hosted_e2e_job.validate_focused_targets([target]) == (target,)
    assert target in hosted_e2e_job._pytest_command("focused", [target])
    with pytest.raises(RuntimeError):
        hosted_e2e_job.validate_focused_targets([target, target])

    invalid_targets = (
        "--collect-only",
        "testing/tests_unit/test_001_entities.py",
        "testing/tests_e2e/../tests_unit/test_001_entities.py",
        "testing/tests_e2e/001_site/missing.py::test_missing",
        f"{target},--collect-only",
        "testing/tests_e2e/001_site/test_001a_environment.py::",
    )
    for invalid in invalid_targets:
        with pytest.raises(RuntimeError):
            hosted_e2e_job.validate_focused_targets([invalid])


def test_hosted_all_scope_runs_every_complete_suite_and_opt_in_contract():
    command = hosted_e2e_job._pytest_command("all")

    assert command[command.index("--strict") + 1 : -1] == [
        "unit",
        "js",
        "tooling",
        "e2e",
        "-m",
        "not unfinished",
    ]
    with pytest.raises(RuntimeError):
        hosted_e2e_job._pytest_command("all", ["testing/tests_unit/"])


# @matrix hosted-e2e : cloud-run focused-execution local-dispatch override
def test_hosted_execute_dispatches_validated_focused_targets(monkeypatch):
    target = (
        "testing/tests_e2e/001_site/test_001a_environment.py::"
        "test_database_setup"
    )
    second_target = (
        "testing/tests_e2e/001_site/test_001a_environment.py::"
        "test_cache_setup"
    )
    calls = []
    writes = []
    monkeypatch.setattr(hosted_e2e, "_activate", lambda **_options: None)
    monkeypatch.setattr(hosted_e2e, "_infrastructure", _infrastructure)
    monkeypatch.setattr(
        hosted_e2e,
        "_state_ready",
        lambda _infrastructure: {"status": "ready"},
    )
    monkeypatch.setattr(
        hosted_e2e,
        "_write_json",
        lambda path, payload, **options: writes.append((path, payload, options)),
    )

    def gcloud(*arguments, **options):
        calls.append((arguments, options))
        return subprocess.CompletedProcess(
            ["gcloud"],
            returncode=0,
            stdout='{"metadata": {"name": "lagniappe-e2e-focus1"}}',
            stderr="",
        )

    monkeypatch.setattr(hosted_e2e, "_gcloud", gcloud)
    monkeypatch.setattr(
        hosted_e2e,
        "_wait_for_execution",
        lambda *_arguments, **_options: ({"status": {}}, 0),
    )

    result = hosted_e2e.execute(
        suite="focused",
        targets=[target, second_target],
        import_results=False,
    )

    assert result == {
        "execution": "lagniappe-e2e-focus1",
        "exit_status": 0,
        "suite": "focused",
    }
    assert (
        f"--args=--suite=focused,--target={target},--target={second_target}"
        in calls[0][0]
    )
    assert "--async" in calls[0][0]
    assert "--wait" not in calls[0][0]
    assert writes[0][1]["last_targets"] == [target, second_target]


# @matrix hosted-e2e : execution-name failure-recovery
def test_hosted_execute_recovers_failed_execution_name_from_gcloud_stderr(
    monkeypatch,
):
    writes = []
    monkeypatch.setattr(hosted_e2e, "_activate", lambda **_options: None)
    monkeypatch.setattr(hosted_e2e, "_infrastructure", _infrastructure)
    monkeypatch.setattr(
        hosted_e2e,
        "_state_ready",
        lambda _infrastructure: {"status": "ready"},
    )
    monkeypatch.setattr(
        hosted_e2e,
        "_write_json",
        lambda path, payload, **options: writes.append((path, payload, options)),
    )
    monkeypatch.setattr(
        hosted_e2e,
        "_gcloud",
        lambda *_arguments, **_options: subprocess.CompletedProcess(
            ["gcloud"],
            returncode=1,
            stdout="",
            stderr=(
                "This command is authenticated as lagniappe-e2e-invoker@"
                "example.test.\n"
                "Execution lagniappe-e2e-failed1 finished with a failed task.\n"
                "Run gcloud run jobs executions describe lagniappe-e2e-failed1.\n"
            ),
        ),
    )
    monkeypatch.setattr(
        hosted_e2e,
        "_wait_for_execution",
        lambda *_arguments, **_options: (
            {
                "status": {
                    "completionTime": "2026-08-21T17:50:24Z",
                    "failedCount": 1,
                }
            },
            1,
        ),
    )

    result = hosted_e2e.execute(suite="all", import_results=False)

    assert result == {
        "execution": "lagniappe-e2e-failed1",
        "exit_status": 1,
        "suite": "all",
    }
    assert writes[0][1]["last_execution"] == "lagniappe-e2e-failed1"
    assert writes[0][1]["last_suite"] == "all"


# @matrix hosted-e2e : execution-status failure-reporting progress
def test_hosted_execution_wait_reports_progress_and_failure(monkeypatch, capsys):
    clock = [0]
    running = {
        "spec": {"taskCount": 1},
        "status": {
            "runningCount": 1,
            "conditions": [{"type": "Started", "status": "True"}],
        },
    }
    payloads = iter(
        [
            {"spec": {"taskCount": 1}, "status": {"conditions": []}},
            running,
            running,
            running,
            running,
            running,
            {
                "spec": {"taskCount": 1},
                "status": {
                    "completionTime": "2026-08-21T17:50:24Z",
                    "failedCount": 1,
                    "conditions": [
                        {
                            "type": "Completed",
                            "status": "False",
                            "message": "The test container exited with code 1.",
                        }
                    ],
                },
            },
        ]
    )
    calls = []

    def describe(arguments):
        calls.append(arguments)
        return next(payloads)

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(hosted_e2e, "_describe", describe)

    payload, exit_status = hosted_e2e._wait_for_execution(
        _infrastructure(),
        "lagniappe-e2e-progress1",
        poll_interval=60,
        monotonic=lambda: clock[0],
        sleep=sleep,
    )

    assert exit_status == 1
    assert payload["status"]["failedCount"] == 1
    assert calls[0][:5] == [
        "run",
        "jobs",
        "executions",
        "describe",
        "lagniappe-e2e-progress1",
    ]
    output = capsys.readouterr().out
    assert "[00:00:00] STARTING: 0s elapsed" in output
    assert "[00:01:00] RUNNING: 1m 0s elapsed" in output
    assert "[00:05:00] RUNNING: 5m 0s elapsed" in output
    assert "[00:06:00] FAILED: completed after 6m 0s" in output
    assert "exited with code 1" in output


# @matrix hosted-e2e : execution-status success
def test_hosted_execution_wait_recognizes_success(monkeypatch):
    monkeypatch.setattr(
        hosted_e2e,
        "_describe",
        lambda _arguments: {
            "spec": {"taskCount": 1},
            "status": {
                "completionTime": "2026-08-21T17:50:24Z",
                "succeededCount": 1,
                "conditions": [{"type": "Completed", "status": "True"}],
            },
        },
    )

    payload, exit_status = hosted_e2e._wait_for_execution(
        _infrastructure(),
        "lagniappe-e2e-success1",
        report=False,
        monotonic=lambda: 0,
        sleep=lambda _seconds: pytest.fail("completed execution should not sleep"),
    )

    assert exit_status == 0
    assert payload["status"]["succeededCount"] == 1


# @matrix hosted-e2e : artifact-location duration junit result-summary
def test_hosted_execute_summary_reports_unique_junit_failures(tmp_path):
    execution = "lagniappe-e2e-summary1"
    destination = tmp_path / "results" / execution
    destination.mkdir(parents=True)
    (destination / "junit.xml").write_text(
        """\
<testsuites>
  <testsuite>
    <testcase classname="tests_unit.test_example" name="test_passes" />
    <testcase classname="tests_e2e.test_example" name="test_fails">
      <failure message="assert 500 == 200" />
    </testcase>
    <testcase classname="tests_e2e.test_example" name="test_fails">
      <error message="failed during teardown" />
    </testcase>
    <testcase classname="tests_unit.test_example" name="test_skips">
      <skipped />
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    summary = hosted_e2e.format_execute_summary(
        {
            "execution": execution,
            "exit_status": 1,
            "suite": "all",
            "source": "a" * 40,
            "version": "e2e-1234567890abcdef",
            "build_id": "b1234567",
            "suite_started_at": "2026-08-21T17:00:00+00:00",
            "suite_finished_at": "2026-08-21T17:01:30+00:00",
        },
        state_root=tmp_path,
    )

    assert "Hosted E2E FAILED" in summary
    assert f"Source: {'a' * 40}" in summary
    assert "Deployment: e2e-1234567890abcdef (build b1234567)" in summary
    assert "Duration: 1m 30s" in summary
    assert "Tests: 3 total — 1 passed, 1 failed, 1 skipped" in summary
    assert "Additional error records: 1" in summary
    assert "testing/tests_e2e/test_example.py::test_fails" in summary
    assert "assert 500 == 200" in summary
    assert str(destination.resolve()) in summary


# @matrix hosted-e2e : cli-routing evidence-import suite-scope
def test_hosted_execute_command_defaults_to_all_and_imports(
    monkeypatch,
    capsys,
):
    calls = []
    monkeypatch.setattr(
        hosted_e2e,
        "execute",
        lambda **options: calls.append(options)
        or {
            "execution": "lagniappe-e2e-alltest",
            "exit_status": 0,
            "suite": "all",
        },
    )

    assert hosted_e2e.run_hosted_e2e_command(["execute"]) == 0
    assert hosted_e2e.run_hosted_e2e_command(
        ["execute", "--no-import-results"]
    ) == 0
    assert calls == [
        {"suite": "all", "targets": (), "import_results": True},
        {"suite": "all", "targets": (), "import_results": False},
    ]
    output = capsys.readouterr().out
    assert output.count("Hosted E2E PASSED") == 2
    assert "Results were left in Cloud Storage" in output
    assert not output.lstrip().startswith("{")


# @pair hosted-e2e:cli-routing
def test_hosted_create_command_routes_preflight_base(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        hosted_e2e,
        "create",
        lambda **options: calls.append(options)
        or {"base_url": "https://e2e.example.test"},
    )

    assert hosted_e2e.run_hosted_e2e_command(
        ["create", "--base", "release-base"]
    ) == 0

    assert calls == [{"base_ref": "release-base"}]
    assert "Hosted E2E version ready" in capsys.readouterr().out


# @pair hosted-e2e:cli-routing
def test_hosted_release_evidence_command_routes_validation(monkeypatch, capsys):
    candidate = "a" * 40
    evidence = "b" * 40
    base = "c" * 40
    calls = []
    monkeypatch.setattr(
        hosted_e2e,
        "validate_release_evidence",
        lambda *arguments, **options: calls.append((arguments, options))
        or {
            "base": base,
            "candidate": candidate,
            "evidence": evidence,
            "mode": "continuation",
        },
    )

    assert hosted_e2e.run_hosted_e2e_command(
        [
            "validate-release-evidence",
            "--base",
            base,
            "--candidate",
            candidate,
            "--evidence",
            evidence,
        ]
    ) == 0

    assert calls == [((candidate, evidence), {"base": base})]
    assert json.loads(capsys.readouterr().out)["mode"] == "continuation"


# @matrix hosted-e2e traceability : artifact-download progress selective-download
def test_hosted_results_can_skip_large_report_archive(tmp_path, monkeypatch, capsys):
    execution = "lagniappe-e2e-result1"
    requested = []
    files = {
        "manifest.json": json.dumps(
            {"execution": execution, "exit_status": 0, "suite": "all"}
        ).encode(),
        "evidence.json": b"{}\n",
        "junit.xml": b"<testsuites/>\n",
        "reports.tar.gz": b"large report archive",
    }

    class Blob:
        def __init__(self, name):
            self.name = name

        def exists(self, *, client):
            return self.name.rsplit("/", 1)[-1] in files

        def download_to_filename(self, path):
            name = self.name.rsplit("/", 1)[-1]
            requested.append(name)
            path.write_bytes(files[name])

    class Bucket:
        def blob(self, name):
            return Blob(name)

    class Client:
        def __init__(self, *, project):
            assert project == "project-1"

        def bucket(self, name):
            assert name == "lagniappe-e2e-artifacts-example"
            return Bucket()

    monkeypatch.setattr(hosted_e2e, "_activate", lambda **_options: None)
    monkeypatch.setattr(hosted_e2e, "_infrastructure", _infrastructure)
    monkeypatch.setattr(hosted_e2e, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(hosted_e2e, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr("google.cloud.storage.Client", Client)

    manifest = hosted_e2e.results(
        execution=execution,
        merge=False,
        include_report_archive=False,
    )

    assert manifest["suite"] == "all"
    assert requested == ["manifest.json", "evidence.json", "junit.xml"]
    assert not (tmp_path / "results" / execution / "reports.tar.gz").exists()
    output = capsys.readouterr().out
    assert str(tmp_path / "results" / execution) in output
    assert "downloading manifest.json" in output


# @matrix hosted-e2e : deletion-safety evidence-retention local-artifacts teardown
def test_hosted_teardown_removes_downloaded_results_after_success(
    tmp_path,
    monkeypatch,
    capsys,
):
    infrastructure = _infrastructure()
    state_root = tmp_path / "reports/hosted-e2e"
    state_path = state_root / "state.json"
    result_root = state_root / "results"
    result_root.mkdir(parents=True)
    (result_root / "execution-1").mkdir()
    (result_root / "execution-1/junit.xml").write_text(
        "<testsuites/>\n",
        encoding="utf-8",
    )
    setup_path = state_root / "setup.json"
    setup_path.write_text("{}\n", encoding="utf-8")
    version = "e2e-1234567890abcdef"
    state = {
        "project": infrastructure.project,
        "region": infrastructure.region,
        "service": hosted_e2e.SERVICE,
        "job": infrastructure.job,
        "artifact_bucket": infrastructure.artifact_bucket,
        "version": version,
        "base_url": "https://hosted-e2e.example.test",
        "status": "ready",
    }
    hosted_e2e._write_json(state_path, state)

    class CleanupLease:
        def __exit__(self, *_arguments):
            return None

    monkeypatch.setattr(hosted_e2e, "APP_DIR", tmp_path)
    monkeypatch.setattr(hosted_e2e, "STATE_ROOT", state_root)
    monkeypatch.setattr(hosted_e2e, "STATE_PATH", state_path)
    monkeypatch.setattr(hosted_e2e, "_activate", lambda **_options: None)
    monkeypatch.setattr(hosted_e2e, "_infrastructure", lambda: infrastructure)
    monkeypatch.setattr(hosted_e2e, "_verify_soft_routing_guard", lambda _value: None)
    monkeypatch.setattr(hosted_e2e, "_describe", lambda _arguments: None)
    monkeypatch.setattr(hosted_e2e, "_acquire_cleanup_lease", CleanupLease)
    monkeypatch.setattr(
        hosted_e2e,
        "_version_url",
        lambda _infrastructure, _version: state["base_url"],
    )
    cors_changes = []
    monkeypatch.setattr(
        hosted_e2e,
        "_change_test_bucket_cors",
        lambda *arguments, **options: cors_changes.append((arguments, options)),
    )

    result = hosted_e2e.teardown()

    assert result["status"] == "torn-down"
    assert hosted_e2e._load_json(state_path)["status"] == "torn-down"
    assert not result_root.exists()
    assert setup_path.exists()
    assert cors_changes == [
        ((infrastructure, state["base_url"]), {"present": False})
    ]
    assert f"Removed local hosted E2E artifacts: {result_root}" in capsys.readouterr().out


# @matrix hosted-e2e traceability : evidence merge provenance
def test_remote_evidence_merges_tests_and_snapshot_provenance():
    local = _evidence(
        "local-snapshot",
        {"source/local.py": "local-fingerprint"},
        "tests_unit/test_local.py::test_local",
    )
    remote = _evidence(
        "remote-snapshot",
        {"source/remote.py": "remote-fingerprint"},
        "tests_e2e/test_remote.py::test_remote",
    )

    merged = merge_remote_evidence(local, remote)

    assert set(merged["tests"]) == {
        "tests_unit/test_local.py::test_local",
        "tests_e2e/test_remote.py::test_remote",
    }
    assert decode_test_run_snapshots(merged) == {
        "local-snapshot": {"source/local.py": "local-fingerprint"},
        "remote-snapshot": {"source/remote.py": "remote-fingerprint"},
    }
    assert merged["sessions"] == [
        {"snapshot": "local-snapshot", "tests": 1},
        {"snapshot": "remote-snapshot", "tests": 1},
    ]


# @pair hosted-e2e:ci-import
def test_traceability_common_import_does_not_require_playwright():
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "playwright" or name.startswith("playwright."):
        raise ModuleNotFoundError("playwright is intentionally unavailable")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
from testing.utility.traceability_common import TEST_RUN_SCHEMA_VERSION
print(TEST_RUN_SCHEMA_VERSION)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=hosted_e2e.APP_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(TEST_RUN_SCHEMA_VERSION)


# @matrix hosted-e2e traceability : ci-import evidence merge provenance source-integrity
def test_hosted_result_directory_import_requires_the_exact_source(
    tmp_path,
    monkeypatch,
):
    source = "a" * 40
    source_file = tmp_path / "source.py"
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    snapshot, paths = behavior_snapshot(tmp_path)
    result_dir = tmp_path / "reports/result"
    result_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "kind": "hosted-e2e-result",
        "execution": "lagniappe-e2e-result1",
        "exit_status": 1,
        "source": source,
        "source_snapshot": snapshot,
        "suite": "all",
    }
    traceability_common.write_json(result_dir / "manifest.json", manifest)
    traceability_common.write_json(
        result_dir / "evidence.json",
        _evidence(
            snapshot,
            paths,
            "tests_e2e/test_remote.py::test_remote",
            outcome="failed",
        ),
    )
    monkeypatch.setattr(hosted_e2e, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        hosted_e2e,
        "_git",
        lambda *_arguments, **_options: subprocess.CompletedProcess(
            ["git"], 0, stdout=f"{source}\n", stderr=""
        ),
    )

    imported = hosted_e2e.import_result_directory(
        result_dir,
        expected_execution="lagniappe-e2e-result1",
    )

    assert imported == manifest
    evidence = traceability_common.load_json(
        tmp_path / traceability_common.LATEST_TEST_RUN
    )
    assert evidence["tests"]["tests_e2e/test_remote.py::test_remote"][
        "outcome"
    ] == "failed"

    manifest["source"] = "b" * 40
    traceability_common.write_json(result_dir / "manifest.json", manifest)
    with pytest.raises(HostedE2EError, match="does not match"):
        hosted_e2e.import_result_directory(result_dir)


def test_source_archive_snapshot_falls_back_when_git_is_not_installed(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    def missing_git(*_arguments, **_options):
        raise FileNotFoundError("git is not installed")

    monkeypatch.setattr(traceability_common.subprocess, "run", missing_git)

    snapshot, paths = behavior_snapshot(tmp_path)

    assert len(snapshot) == 64
    assert paths == {"source.py": traceability_common.behavior_file_fingerprint(source)}


def test_hosted_image_upload_boundary_excludes_local_credentials_and_results():
    all_lines = {
        line.strip()
        for line in (hosted_e2e.CONTAINER_ROOT / "gcloudignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    ignore_lines = {line for line in all_lines if not line.startswith("#")}

    assert not any(line.startswith("#!include:") for line in all_lines)
    assert ".gcloudignore" not in ignore_lines
    assert "testing/" not in ignore_lines
    assert "/testing/" not in ignore_lines
    assert {
        ".git",
        ".env",
        ".env.*",
        "config/files/",
        "reports/",
        "testing/evidence/",
        "venv/",
        "*credentials*.json",
        "*service-account*.json",
        "gha-creds-*.json",
    } <= ignore_lines


def test_hosted_runner_installs_complete_test_collection_dependencies():
    development_requirements = {
        line.strip()
        for line in (hosted_e2e.APP_DIR / "requirements-dev.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip().startswith("-r ")
    }
    dockerfile = " ".join(
        (hosted_e2e.CONTAINER_ROOT / "Dockerfile")
        .read_text(encoding="utf-8")
        .split()
    )

    assert {
        "-r requirements.txt",
        "-r requirements-installer.txt",
    } <= development_requirements
    assert (
        "COPY requirements.txt requirements-dev.txt requirements-installer.txt ./"
        in dockerfile
    )
    assert "FROM node:24-bookworm-slim AS node-runtime" in dockerfile
    assert "apt-get install --yes --no-install-recommends git" in dockerfile
    assert "ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm" in (
        dockerfile
    )
    assert "COPY package.json package-lock.json ./" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert (
        "COPY runner/hosted_e2e_container/root.gcloudignore .gcloudignore"
        in dockerfile
    )


def test_hosted_anchor_declares_its_upload_boundary():
    ignore_lines = {
        line.strip()
        for line in (hosted_e2e.ANCHOR_ROOT / ".gcloudignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert {".gcloudignore", ".git", ".gitignore", "__pycache__/", "*.py[cod]"} <= (
        ignore_lines
    )


def test_hosted_workflow_consolidates_candidate_and_continuation_validation():
    """One workflow owns hosted candidates and the current-head release gate."""
    workflow_path = hosted_e2e.APP_DIR / ".github/workflows/hosted-e2e.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    assert workflow["on"]["pull_request"] == {
        "branches": ["main"],
        "types": ["opened", "reopened"],
    }
    assert workflow["on"]["push"] == {
        "branches": ["next/**", "hotfix/**"],
    }
    dispatch = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch["mode"]["options"] == ["manual", "continuation"]
    assert dispatch["suite"]["options"] == ["all", "full"]
    assert {"pull_request", "candidate_sha", "evidence_sha"} <= set(dispatch)
    request = workflow["jobs"]["request"]
    execute = workflow["jobs"]["execute"]
    quality = workflow["jobs"]["quality"]
    attest = workflow["jobs"]["attest"]
    assert workflow["permissions"] == {}
    assert request["permissions"] == {"pull-requests": "read"}
    assert execute["permissions"] == {
        "contents": "write",
        "actions": "write",
        "id-token": "write",
    }
    assert quality["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert attest["permissions"] == {"statuses": "write"}
    assert request["name"] == "Resolve hosted release request"
    assert "preflight" not in workflow["jobs"]
    assert execute["needs"] == "request"
    assert "needs.request.outputs.execute == 'true'" in execute["if"]
    assert execute["environment"] == "hosted-e2e"
    assert "environment" not in quality
    assert "Prepare hosted release evidence" in execute["name"]
    assert "Execute hosted suite" in execute["name"]
    assert "Source quality and traceability" in quality["name"]
    assert "Manual dispatch guard" in quality["name"]
    assert quality["needs"] == ["request", "execute"]
    assert "github.event_name == 'push'" in quality["if"]
    assert "needs.request.outputs.execute == 'true'" in quality["if"]
    assert "evidence_changed != 'true'" in quality["if"]
    assert "inputs.mode == 'continuation'" in quality["if"]
    assert attest["needs"] == "quality"
    assert "needs.quality.result == 'success'" in attest["if"]
    assert "Publish current-head release status" in attest["name"]
    assert "ref: ${{ needs.request.outputs.candidate_sha }}" in workflow_text
    assert "ref: ${{ steps.context.outputs.evidence_sha }}" in workflow_text
    assert "PR_HEAD_SHA" in workflow_text
    assert "next/*|hotfix/*" in workflow_text
    assert '"head=$owner:$branch"' in workflow_text
    assert "No open pull request to main" in workflow_text
    assert "synchronize" not in workflow["on"]["pull_request"]["types"]
    assert "google-github-actions/auth" in workflow_text
    assert "gcloud run jobs describe" in workflow_text
    assert "gcloud run jobs execute" in workflow_text
    assert "--async" in workflow_text
    assert "--wait" not in workflow_text
    assert "gcloud storage cp" in workflow_text
    assert "attempt<=720" in workflow_text
    assert "completion manifest" in workflow_text
    assert "hosted-e2e import-results" in workflow_text
    assert "--execution \"$EXECUTION\"" in workflow_text
    assert 'rm -f -- "$credentials_file"' in workflow_text
    assert 'statuses/$EVIDENCE_SHA' in workflow_text
    assert "Exact hosted evidence and release gates passed" in workflow_text
    assert "EVIDENCE_SHA: ${{ needs.quality.outputs.evidence_sha }}" in workflow_text

    quality_text = yaml.dump(quality, sort_keys=False)
    assert "gh api" in quality_text
    assert "validate-release-evidence" in quality_text
    assert "npm run check" in quality_text
    assert "ruff check ." in quality_text
    assert "run.py traceability" not in quality_text
    assert "release-check --base" in quality_text
    assert "gcloud" not in quality_text
    assert "run.py test" not in quality_text


def test_hosted_workflow_retains_results_before_reporting_and_guards_movement():
    """Failed evidence is returned before red, without overwriting a moved ref."""
    workflow_path = hosted_e2e.APP_DIR / ".github/workflows/hosted-e2e.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["execute"]["steps"]
    positions = {step["name"]: index for index, step in enumerate(steps)}

    assert positions["Merge hosted evidence"] < positions[
        "Commit evidence to the tested branch"
    ]
    assert positions["Commit evidence to the tested branch"] < positions[
        "Dispatch validation on the evidence child"
    ]
    assert positions["Dispatch validation on the evidence child"] < positions[
        "Report the hosted suite result"
    ]
    report = steps[positions["Report the hosted suite result"]]
    assert "always()" in report["if"]
    assert "manifest.json" in report["run"]
    assert "gh workflow run hosted-e2e.yml" in workflow_text
    assert "-f mode=continuation" in workflow_text
    assert 'remote_head="$(git rev-parse FETCH_HEAD)"' in workflow_text
    assert '"$remote_head" != "$EXPECTED_SOURCE"' in workflow_text
    assert '"$remote_head" != "$EVIDENCE_SHA"' in workflow_text
    assert 'git commit -am "Updated hosted test evidence"' in workflow_text
    assert 'git push origin "HEAD:refs/heads/$BRANCH"' in workflow_text
    assert "git push --force" not in workflow_text
    assert '"$head_sha" != "$DISPATCH_EVIDENCE"' in workflow_text


# @matrix hosted-e2e : artifact-download identity least-privilege
def test_ci_invoker_can_only_read_the_result_bucket(monkeypatch):
    calls = []
    monkeypatch.setattr(
        hosted_e2e,
        "_gcloud",
        lambda *arguments, **options: calls.append((arguments, options)),
    )
    infrastructure = _infrastructure()
    invoker = f"serviceAccount:{infrastructure.invoker_email}"

    hosted_e2e._grant_ci_result_access(infrastructure, invoker)

    assert calls == [
        (
            (
                "storage",
                "buckets",
                "add-iam-policy-binding",
                f"gs://{infrastructure.artifact_bucket}",
                f"--member={invoker}",
                "--role=roles/storage.objectViewer",
                "--quiet",
            ),
            {},
        )
    ]


# @matrix hosted-e2e : image-boundary redis-tls secrets
def test_settings_and_redis_ca_use_separate_secret_versions(tmp_path, monkeypatch):
    redis_ca = tmp_path / "config/files/redis_ca.pem"
    redis_ca.parent.mkdir(parents=True)
    redis_ca.write_text("public trust certificate\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(hosted_e2e, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        hosted_e2e.SETTINGS,
        "APP",
        {
            "REDIS_TLS": True,
            "REDIS_CA_CERT": "config/files/redis_ca.pem",
        },
    )
    monkeypatch.setattr(
        hosted_e2e,
        "_gcloud",
        lambda *arguments, **_options: calls.append(arguments),
    )

    hosted_e2e._sync_settings_secret(_infrastructure())

    additions = [
        arguments
        for arguments in calls
        if arguments[1:3] == ("versions", "add")
    ]
    assert len(additions) == 2
    assert additions[0][3] == "lagniappe-e2e-settings"
    assert additions[1][3] == "lagniappe-e2e-redis-ca"
    assert f"--data-file={redis_ca}" in additions[1]


# @matrix hosted-e2e traceability : build-metadata shared-build source-integrity
def test_hosted_e2e_requires_a_committed_production_build(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Hosted E2E Test")
    _git(tmp_path, "config", "user.email", "hosted-e2e@example.test")
    files = {
        "build/publication.json": f"{
            json.dumps(
                {
                    'schema': 1,
                    'source_roots': ['src/script'],
                    'source_files': ['build/publication.json', 'package.json'],
                    'exclusive_artifact_roots': ['lagniappe/web/static/chunks'],
                    'required_artifacts': [
                        'lagniappe/web/static/chunks/views/home.js',
                        'lagniappe/web/static/script.js',
                        'lagniappe/web/static/sw.js',
                    ],
                    'required_artifact_prefixes': [
                        'lagniappe/web/static/chunks/',
                        'lagniappe/web/static/chunks/views/',
                    ],
                },
                sort_keys=True,
            )
        }\n",
        "config/constants.py": 'BUILD_ID = "b1234567"\n',
        "lagniappe/web/static/chunks/views/home.js": "export const home = true;\n",
        "lagniappe/web/static/script.js": "export const main = true;\n",
        "lagniappe/web/static/sw.js": 'const BUILD_ID = "b1234567";\n',
        "package.json": '{"version": "1.2.3"}\n',
        "src/script/main.mjs": "export const main = true;\n",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    source_paths = [
        "build/publication.json",
        "package.json",
        "src/script/main.mjs",
    ]
    source_digest = hashlib.sha256(b"frontend-source-v1\0")
    for relative in source_paths:
        source_digest.update(relative.encode())
        source_digest.update(b"\0")
        source_digest.update((tmp_path / relative).read_bytes())
        source_digest.update(b"\0")
    artifact_paths = [
        "lagniappe/web/static/chunks/views/home.js",
        "lagniappe/web/static/script.js",
        "lagniappe/web/static/sw.js",
    ]
    metadata = {
        "schema": 1,
        "build_id": "b1234567",
        "mode": "production",
        "version": "1.2.3",
        "source": {"sha256": source_digest.hexdigest()},
        "artifacts": [],
    }
    for relative in artifact_paths:
        content = (tmp_path / relative).read_bytes()
        metadata["artifacts"].append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )
    metadata_path = tmp_path / "lagniappe/web/static/build.json"
    metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "production build")
    source = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    assert (
        hosted_e2e._require_committed_production_build(
            source,
            repo_root=tmp_path,
            expected_version="1.2.3",
        )
        == "b1234567"
    )

    metadata_path.write_text(
        '{"build_id": "local", "mode": "development", "version": "local"}\n',
        encoding="utf-8",
    )
    assert (
        hosted_e2e._require_committed_production_build(
            source,
            repo_root=tmp_path,
            expected_version="1.2.3",
        )
        == "b1234567"
    )

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "development build")
    development_source = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(HostedE2EError, match="committed production"):
        hosted_e2e._require_committed_production_build(
            development_source,
            repo_root=tmp_path,
            expected_version="1.2.3",
        )


# @matrix hosted-e2e : deployment-source generated-assets source-integrity
def test_committed_source_export_ignores_generated_worktree_churn(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Hosted E2E Test")
    _git(tmp_path, "config", "user.email", "hosted-e2e@example.test")
    generated = tmp_path / "lagniappe/web/static/script.js"
    generated.parent.mkdir(parents=True)
    generated.write_text("committed production bundle\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "production bundle")
    source = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    generated.write_text("local development bundle\n", encoding="utf-8")

    with hosted_e2e._committed_source_tree(
        source,
        repo_root=tmp_path,
    ) as source_root:
        assert (source_root / generated.relative_to(tmp_path)).read_text(
            encoding="utf-8"
        ) == "committed production bundle\n"


# @matrix hosted-e2e : deployment-source image-boundary
def test_runner_image_uses_the_exported_commit(tmp_path, monkeypatch):
    container_root = tmp_path / hosted_e2e.CONTAINER_RELATIVE_ROOT
    container_root.mkdir(parents=True)
    (tmp_path / ".gcloudignore").write_text(
        "/testing/\n!/config/files/lagniappe_settings.yaml\n",
        encoding="utf-8",
    )
    (container_root / "cloudbuild.yaml").write_text("steps: []\n", encoding="utf-8")
    (container_root / "gcloudignore").write_text("config/files/\n", encoding="utf-8")
    calls = []
    cloud_build_id = "12345678-1234-1234-1234-123456789abc"

    def gcloud(*arguments, **options):
        calls.append((arguments, options))
        return subprocess.CompletedProcess(
            ["gcloud"],
            returncode=0,
            stdout=f'{{"id": "{cloud_build_id}"}}',
            stderr="",
        )

    monkeypatch.setattr(
        hosted_e2e,
        "_gcloud",
        gcloud,
    )

    image, returned_build_id = hosted_e2e._build_runner_image(
        _infrastructure(),
        "a" * 40,
        tmp_path,
    )

    assert image.endswith(":" + "a" * 40)
    assert returned_build_id == cloud_build_id
    arguments, options = calls[0]
    assert arguments[:3] == ("builds", "submit", tmp_path)
    assert f"--config={container_root / 'cloudbuild.yaml'}" in arguments
    assert f"--ignore-file={container_root / 'gcloudignore'}" in arguments
    assert "--async" in arguments
    assert "--format=json" in arguments
    assert options == {"timeout": 600}
    assert (
        container_root / hosted_e2e.RUNNER_GCLOUDIGNORE_COPY
    ).read_text(encoding="utf-8") == (
        tmp_path / ".gcloudignore"
    ).read_text(encoding="utf-8")


# @matrix hosted-e2e : build-resume failure-recovery provider-status
def test_runner_image_build_waits_for_recorded_cloud_build(monkeypatch):
    cloud_build_id = "12345678-1234-1234-1234-123456789abc"
    descriptions = iter(({"status": "QUEUED"}, {"status": "SUCCESS"}))
    calls = []
    delays = []

    def describe(arguments):
        calls.append(arguments)
        return next(descriptions)

    monkeypatch.setattr(hosted_e2e, "_describe", describe)
    monkeypatch.setattr(hosted_e2e.time, "monotonic", lambda: 0)
    monkeypatch.setattr(hosted_e2e.time, "sleep", delays.append)

    result = hosted_e2e._wait_runner_image_build(
        _infrastructure(),
        cloud_build_id,
        poll_interval=0.01,
    )

    assert result == {"status": "SUCCESS"}
    assert calls[0][:3] == ["builds", "describe", cloud_build_id]
    assert delays == [0.01]

    monkeypatch.setattr(
        hosted_e2e,
        "_describe",
        lambda _arguments: {
            "status": "FAILURE",
            "failureInfo": {"detail": "Docker step failed"},
            "logUrl": "https://console.example.test/build",
        },
    )
    with pytest.raises(HostedE2EError, match="Docker step failed.*Logs: https"):
        hosted_e2e._wait_runner_image_build(_infrastructure(), cloud_build_id)


# @matrix hosted-e2e : failure-recovery lifecycle resume source-integrity
def test_hosted_create_resumes_only_the_same_committed_lifecycle(monkeypatch):
    infrastructure = _infrastructure()
    source = "a" * 40
    snapshot = "b" * 64
    version = "e2e-abcdef1234567890"
    base_url = "https://version.example.test"
    state = {
        "schema_version": hosted_e2e.STATE_SCHEMA_VERSION,
        "status": "failed",
        "project": infrastructure.project,
        "region": infrastructure.region,
        "service": infrastructure.service,
        "job": infrastructure.job,
        "artifact_bucket": infrastructure.artifact_bucket,
        "version": version,
        "base_url": base_url,
        "source": source,
        "source_snapshot": snapshot,
        "build_id": "b1234567",
        "image": f"{infrastructure.image_base}:{source}",
        "cloud_build_id": "12345678-1234-1234-1234-123456789abc",
    }
    monkeypatch.setattr(
        hosted_e2e,
        "_version_url",
        lambda _infrastructure, _version: base_url,
    )

    resumed = hosted_e2e._resumable_create_state(
        state,
        infrastructure,
        source=source,
        source_snapshot=snapshot,
        build_id="b1234567",
    )

    assert resumed == state
    assert resumed is not state

    mismatched = dict(state, source="c" * 40)
    with pytest.raises(HostedE2EError, match="different committed build"):
        hosted_e2e._resumable_create_state(
            mismatched,
            infrastructure,
            source=source,
            source_snapshot=snapshot,
            build_id="b1234567",
        )
    with pytest.raises(HostedE2EError, match="has not been torn down"):
        hosted_e2e._resumable_create_state(
            dict(state, status="ready"),
            infrastructure,
            source=source,
            source_snapshot=snapshot,
            build_id="b1234567",
        )
    missing_build_id = dict(state, image_ready=True)
    missing_build_id.pop("cloud_build_id")
    with pytest.raises(HostedE2EError, match="without recording"):
        hosted_e2e._resumable_create_state(
            missing_build_id,
            infrastructure,
            source=source,
            source_snapshot=snapshot,
            build_id="b1234567",
        )


# @matrix hosted-e2e : deployment-source failure-recovery lifecycle resume
def test_hosted_app_resume_requires_exact_deployment_metadata(monkeypatch):
    infrastructure = _infrastructure()
    state = {
        "version": "e2e-abcdef1234567890",
        "source": "a" * 40,
        "source_snapshot": "b" * 64,
        "build_id": "b1234567",
    }
    variables = {
        "LAGNIAPPE_HOSTED_E2E_VERSION": state["version"],
        "LAGNIAPPE_HOSTED_E2E_SOURCE": state["source"],
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT": state["source_snapshot"],
        "LAGNIAPPE_HOSTED_E2E_BUILD_ID": state["build_id"],
    }

    monkeypatch.setattr(hosted_e2e, "_describe", lambda _arguments: None)
    assert not hosted_e2e._hosted_app_version_present(infrastructure, state)

    monkeypatch.setattr(
        hosted_e2e,
        "_describe",
        lambda _arguments: {"envVariables": variables},
    )
    assert hosted_e2e._hosted_app_version_present(infrastructure, state)

    monkeypatch.setattr(
        hosted_e2e,
        "_describe",
        lambda _arguments: {
            "envVariables": dict(variables, LAGNIAPPE_HOSTED_E2E_SOURCE="c" * 40)
        },
    )
    with pytest.raises(HostedE2EError, match="unexpected deployment metadata"):
        hosted_e2e._hosted_app_version_present(infrastructure, state)


# @matrix hosted-e2e : authentication deployment-binding deterministic-topology performance static-assets zero-traffic
def test_hosted_descriptor_preserves_native_static_handlers():
    infrastructure = _infrastructure()

    descriptor = _hosted_app_descriptor(
        infrastructure,
        version="e2e-abcdef1234567890",
        source="a" * 40,
        source_snapshot="b" * 64,
        build_id="b1234567",
        base_url=(
            "https://e2e-abcdef1234567890-dot-e2e-dot-"
            "project-1.uc.r.appspot.com"
        ),
        session_key="s" * 48,
    )

    assert descriptor["handlers"][:-1] == hosted_e2e.APP_HANDLERS[:-1]
    assert descriptor["handlers"] is not hosted_e2e.APP_HANDLERS

    chunk_handler = next(
        handler
        for handler in descriptor["handlers"]
        if handler["url"] == "/chunks/(.*\\.js)$"
    )
    assert chunk_handler["static_files"] == "lagniappe/web/static/chunks/\\1"

    testing_handler = next(
        handler
        for handler in descriptor["handlers"]
        if handler["url"] == "/testing(/.*)?$"
    )
    assert testing_handler["script"] == "auto"
    assert descriptor["handlers"][-2]["url"] == "/$"
    assert descriptor["handlers"][-2]["script"] == "auto"
    assert descriptor["handlers"][-1] == {
        "url": "/(.*)$",
        "script": "auto",
        "secure": "always",
        "redirect_http_response_code": 301,
    }
    assert descriptor["entrypoint"] == "gunicorn -t 3600 -w 4 -b :$PORT main:app"
    assert descriptor["instance_class"] == "B2"
    assert descriptor["basic_scaling"] == {
        "max_instances": 1,
        "idle_timeout": "15m",
    }
    assert "automatic_scaling" not in descriptor
    assert descriptor["env_variables"]["LAGNIAPPE_HOSTED_E2E_ROLE"] == "server"
    assert descriptor["env_variables"][
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT"
    ] == "b" * 64
    assert descriptor["env_variables"]["LAGNIAPPE_HOSTED_E2E_BUILD_ID"] == (
        "b1234567"
    )
    assert descriptor["service_account"] == infrastructure.runtime_email


# @matrix hosted-e2e : identity runtime-impersonation
def test_hosted_runtime_identity_roles_include_deployer_signing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        hosted_e2e,
        "_service_account_role",
        lambda account, member, role: calls.append((account, member, role)),
    )
    infrastructure = _infrastructure()
    runtime_member = f"serviceAccount:{infrastructure.runtime_email}"
    deployer_member = "user:operator@example.test"

    hosted_e2e._grant_runtime_identity_roles(
        infrastructure,
        runtime_member,
        deployer_member,
    )

    cloud_run_agent = (
        f"serviceAccount:service-{infrastructure.project_number}"
        "@serverless-robot-prod.iam.gserviceaccount.com"
    )
    assert calls == [
        (
            infrastructure.runtime_email,
            runtime_member,
            "roles/iam.serviceAccountTokenCreator",
        ),
        (
            infrastructure.runtime_email,
            deployer_member,
            "roles/iam.serviceAccountTokenCreator",
        ),
        (
            infrastructure.runtime_email,
            runtime_member,
            "roles/iam.serviceAccountUser",
        ),
        (
            infrastructure.runtime_email,
            deployer_member,
            "roles/iam.serviceAccountUser",
        ),
        (
            infrastructure.runtime_email,
            cloud_run_agent,
            "roles/iam.serviceAccountTokenCreator",
        ),
    ]


# @matrix hosted-e2e : identity invocation-overrides least-privilege
def test_hosted_job_grants_only_job_scoped_ci_permissions(monkeypatch):
    calls = []
    monkeypatch.setattr(hosted_e2e, "_describe", lambda _arguments: None)
    monkeypatch.setattr(
        hosted_e2e,
        "_deployer_member",
        lambda: "user:operator@example.test",
    )
    monkeypatch.setattr(hosted_e2e.SETTINGS, "APP", {"REDIS_TLS": True})
    monkeypatch.setattr(
        hosted_e2e,
        "_gcloud",
        lambda *arguments, **options: calls.append((arguments, options)),
    )
    infrastructure = _infrastructure()
    state = {
        "base_url": "https://version.example.test",
        "version": "e2e-abcdef1234567890",
        "source": "a" * 40,
        "source_snapshot": "b" * 64,
        "build_id": "b1234567",
        "image": "us-central1-docker.pkg.dev/project-1/lagniappe-e2e/runner:source",
    }

    hosted_e2e._update_job(infrastructure, state)

    bindings = {
        (
            next(value for value in arguments if value.startswith("--member=")),
            next(value for value in arguments if value.startswith("--role=")),
        )
        for arguments, _options in calls
        if "add-iam-policy-binding" in arguments
    }
    assert bindings == {
        (
            f"--member=serviceAccount:{infrastructure.invoker_email}",
            "--role=roles/run.viewer",
        ),
        (
            f"--member=serviceAccount:{infrastructure.invoker_email}",
            "--role=roles/run.jobsExecutorWithOverrides",
        ),
        (
            "--member=user:operator@example.test",
            "--role=roles/run.jobsExecutorWithOverrides",
        ),
    }
    assert all(role != "--role=roles/run.invoker" for _member, role in bindings)
    job_update = next(
        arguments
        for arguments, _options in calls
        if arguments[:3] == ("run", "jobs", "create")
    )
    secret_argument = next(
        argument for argument in job_update if argument.startswith("--set-secrets=")
    )
    assert "lagniappe_settings.yaml=lagniappe-e2e-settings:latest" in secret_argument
    assert "redis_ca.pem=lagniappe-e2e-redis-ca:latest" in secret_argument
