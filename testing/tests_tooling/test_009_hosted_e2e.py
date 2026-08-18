"""Offline contracts for the hosted-E2E lifecycle and evidence bridge."""

import subprocess

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


# @features hosted-e2e
# @dimensions provider-errors deletion-safety
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


# @features hosted-e2e
# @dimensions first-setup api-propagation build-identity
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


# @features hosted-e2e
# @dimensions soft-routing deletion-safety production-preflight
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


# @features hosted-e2e
# @dimensions anchor soft-routing deletion-safety
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


# @features hosted-e2e
# @dimensions anchor reconciliation soft-routing deletion-safety
def test_hosted_anchor_redeploys_only_when_its_contract_is_stale(
    tmp_path,
    monkeypatch,
):
    calls = []
    descriptors = []

    def gcloud(*arguments, **options):
        calls.append((arguments, options))
        if arguments[:2] == ("app", "deploy"):
            descriptors.append(
                yaml.safe_load(arguments[2].read_text(encoding="utf-8"))
            )
        return subprocess.CompletedProcess(
            ["gcloud"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(hosted_e2e, "ANCHOR_ROOT", tmp_path)
    monkeypatch.setattr(hosted_e2e, "_gcloud", gcloud)
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

    calls.clear()
    descriptors.clear()
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


# @features hosted-e2e
# @dimensions lifecycle source-integrity generated-assets
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
        "suite": "pilot",
    }

    hosted_e2e_job._stamp_evidence(manifest)

    evidence = traceability_common.load_json(evidence_path)
    assert evidence["provenance"]["hosted_e2e"] == manifest


# @features hosted-e2e traceability
# @dimensions evidence merge provenance
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
    } <= ignore_lines


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


def test_hosted_workflow_is_manual_and_repository_read_only():
    """The dispatch workflow invokes only; evidence import stays local."""
    workflow_path = (
        hosted_e2e.APP_DIR / ".github/workflows/hosted-e2e.yml"
    )
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    assert workflow["on"] == {
        "workflow_dispatch": {
            "inputs": {
                "suite": {
                    "description": "E2E scope to run",
                    "required": "true",
                    "default": "pilot",
                    "type": "choice",
                    "options": ["pilot", "full"],
                }
            }
        }
    }
    assert workflow["permissions"] == {"id-token": "write"}
    assert workflow["jobs"]["execute"]["environment"] == "hosted-e2e"
    assert "google-github-actions/auth" in workflow_text
    assert "gcloud run jobs describe" in workflow_text
    assert "gcloud run jobs execute" in workflow_text
    assert "actions/checkout" not in workflow_text
    assert "contents:" not in workflow_text
    assert "git push" not in workflow_text
    assert "hosted-e2e results" not in workflow_text


# @features hosted-e2e
# @dimensions secrets redis-tls image-boundary
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


# @features hosted-e2e traceability
# @dimensions source-integrity build-metadata shared-build
def test_hosted_e2e_requires_a_committed_production_build(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Hosted E2E Test")
    _git(tmp_path, "config", "user.email", "hosted-e2e@example.test")
    files = {
        "config/constants.py": 'BUILD_ID = "b1234567"\n',
        "lagniappe/web/static/build.json": (
            '{"build_id": "b1234567", "mode": "production", '
            '"version": "1.2.3"}\n'
        ),
        "lagniappe/web/static/sw.js": 'const BUILD_ID = "b1234567";\n',
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
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

    metadata_path = tmp_path / "lagniappe/web/static/build.json"
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


# @features hosted-e2e
# @dimensions source-integrity generated-assets deployment-source
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


# @features hosted-e2e
# @dimensions image-boundary deployment-source
def test_runner_image_uses_the_exported_commit(tmp_path, monkeypatch):
    container_root = tmp_path / hosted_e2e.CONTAINER_RELATIVE_ROOT
    container_root.mkdir(parents=True)
    (container_root / "cloudbuild.yaml").write_text("steps: []\n", encoding="utf-8")
    (container_root / "gcloudignore").write_text("config/files/\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        hosted_e2e,
        "_gcloud",
        lambda *arguments, **options: calls.append((arguments, options)),
    )

    image = hosted_e2e._build_runner_image(
        _infrastructure(),
        "a" * 40,
        tmp_path,
    )

    assert image.endswith(":" + "a" * 40)
    arguments, options = calls[0]
    assert arguments[:3] == ("builds", "submit", tmp_path)
    assert f"--config={container_root / 'cloudbuild.yaml'}" in arguments
    assert f"--ignore-file={container_root / 'gcloudignore'}" in arguments
    assert options == {"timeout": 3600, "capture_output": False}


# @features hosted-e2e
# @dimensions authentication static-assets zero-traffic deployment-binding
def test_hosted_descriptor_routes_all_assets_through_the_cookie_gate():
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

    assert descriptor["handlers"] == [
        {"url": "/.*", "script": "auto", "secure": "always"}
    ]
    assert descriptor["automatic_scaling"]["min_idle_instances"] == 0
    assert descriptor["env_variables"]["LAGNIAPPE_HOSTED_E2E_ROLE"] == "server"
    assert descriptor["env_variables"][
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT"
    ] == "b" * 64
    assert descriptor["env_variables"]["LAGNIAPPE_HOSTED_E2E_BUILD_ID"] == (
        "b1234567"
    )
    assert descriptor["service_account"] == infrastructure.runtime_email


# @features hosted-e2e
# @dimensions identity least-privilege invocation-overrides
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
