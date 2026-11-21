"""Offline contracts for restoring installations, resuming work and publishing releases."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from google.api_core.exceptions import PreconditionFailed
import pytest
import yaml

from runner import cloud_checkpoints as checkpoints
from runner import cloud_settings as settings
from runner import cloud_task
from runner import publish_release as release
from testing.tests_tooling.test_003_config import _valid_recovery_document

PROJECT = "recovered-project-1"
ACCOUNT = f"lagniappe-codex@{PROJECT}.iam.gserviceaccount.com"
SOURCE = "a" * 40


@pytest.fixture
def bundle():
    app = dict(_valid_recovery_document(), SECRET_KEY="test-only", REDIS_TLS=False)
    target = {
        "NAME": "installation",
        "ACCOUNT": "owner@example.com",
        "PROJECT": PROJECT,
    }
    dev = {"gcloud_config": target, "test_settings": {}, "dev_settings": {}}
    return {
        "schema": 1,
        "project": PROJECT,
        "ca": None,
        "app": yaml.safe_dump(app),
        "dev": yaml.safe_dump(dev),
    }


def save_installation(root, bundle):
    (root / settings.FILES).mkdir(parents=True, exist_ok=True)
    for path, value in ((settings.APP, bundle["app"]), (settings.DEV, bundle["dev"])):
        (root / path).write_text(value)


# @matrix config setup : secrets project-identity redis-tls
def test_bundle_round_trip(bundle, tmp_path):
    save_installation(tmp_path, bundle)
    assert settings._local_bundle(tmp_path, PROJECT, {}) == bundle
    with pytest.raises(settings.CloudSettingsError):
        settings.validate_bundle(bundle, "another-project")
    wrong = yaml.safe_load(bundle["dev"])
    wrong["gcloud_config"]["PROJECT"] = "another-project"
    with pytest.raises(settings.CloudSettingsError):
        settings.validate_bundle(dict(bundle, dev=yaml.safe_dump(wrong)), PROJECT)
    app = dict(
        yaml.safe_load(bundle["app"]),
        REDIS_TLS=True,
        REDIS_CA_CERT=settings.CA.as_posix(),
    )
    for ca in (None, "invalid pem"):
        with pytest.raises(settings.CloudSettingsError):
            settings.validate_bundle(
                dict(bundle, app=yaml.safe_dump(app), ca=ca), PROJECT
            )


class Store:
    def __init__(self):
        self.current = ""
        self.versions = {}
        self.etag = 0

    def request(self, method, suffix="", **kwargs):
        import base64

        if method == "GET":
            return {
                "etag": str(self.etag),
                "versionAliases": {"current": self.current} if self.current else {},
            }
        if method == "POST":
            n = str(len(self.versions) + 1)
            self.versions[n] = json.loads(
                base64.b64decode(kwargs["json"]["payload"]["data"])
            )
            return {"name": "versions/" + n}
        assert method == "PATCH" and kwargs["json"]["etag"] == str(self.etag)
        self.current = kwargs["json"]["versionAliases"]["current"]
        self.etag += 1

    def access(self, n):
        return n, self.versions[n]


# @matrix config setup : secrets transactional-state
def test_publish_rejects_stale_writers(bundle, tmp_path, monkeypatch):
    save_installation(tmp_path, bundle)
    store = Store()
    first = settings.publish(tmp_path, PROJECT, store, {}, SOURCE)
    assert first["version"] == "1"
    assert settings.publish(tmp_path, PROJECT, store, {}, SOURCE)["version"] == "1"
    changed = dict(bundle, app=bundle["app"].replace("test-only", "changed"))
    save_installation(tmp_path, changed)
    with pytest.raises(settings.CloudSettingsError, match="newer bundle"):
        settings.publish(tmp_path, PROJECT, store, {}, SOURCE)
    assert store.current == "1" and len(store.versions) == 1
    assert settings.publish(tmp_path, PROJECT, store, first, SOURCE)["version"] == "2"
    save_installation(tmp_path, bundle)
    original = store.request

    def race(method, *args, **kwargs):
        if method == "PATCH":
            raise settings.CloudSettingsError("HTTP 412")
        return original(method, *args, **kwargs)

    monkeypatch.setattr(store, "request", race)
    with pytest.raises(settings.CloudSettingsError, match="412"):
        settings.publish(tmp_path, PROJECT, store, settings._receipt(tmp_path), SOURCE)
    assert store.current == "2" and settings._receipt(tmp_path)["version"] == "2"


@pytest.fixture
def generation(tmp_path, monkeypatch):
    # Bind the installer's normal YAML/JSON serializer to an isolated installation.
    import config
    from enum import Enum

    class Files(Enum):
        APP_YAML = tmp_path / "lagniappe.yaml"
        INDEX_YAML = tmp_path / "index.yaml"
        MANIFEST_JSON = tmp_path / "manifest.json"
        GENERATION_JSON = tmp_path / "config/files/lagniappe_generation.json"

        def load(self):
            return yaml.safe_load(self.value.read_text()) if self.value.exists() else {}

        def save(self, value):
            actual = config.File[self.name]
            text = (
                actual._serialize_yaml(value)
                if self.name.endswith("YAML")
                else actual._serialize_json(value)
            )
            settings._atomic_write_text(
                self.value, text, owner_only=self.name == "GENERATION_JSON"
            )

    monkeypatch.setattr(settings, "File", Files)
    monkeypatch.setattr(settings, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        settings,
        "write_generation_manifest",
        lambda: Files.GENERATION_JSON.save({"schema": 2}),
    )
    return Files


# @matrix config deploy : config-files transactional-state recovery
def test_restore_preserves_previous_installation(
    bundle, tmp_path, generation, monkeypatch
):
    operator = {"NAME": "cloud", "ACCOUNT": ACCOUNT}
    (tmp_path / "package.json").write_text('{"version":"3.1.4"}')
    receipt = settings.restore(tmp_path, PROJECT, "1", bundle, {}, SOURCE, operator)
    assert yaml.safe_load((tmp_path / settings.APP).read_text()) == dict(
        yaml.safe_load(bundle["app"]), VERSION="3.1.4"
    )
    assert (
        yaml.safe_load((tmp_path / settings.DEV).read_text())["gcloud_config"][
            "ACCOUNT"
        ]
        == ACCOUNT
    )
    assert settings._local_bundle(tmp_path, PROJECT, receipt) == bundle
    assert generation.APP_YAML.load()["service_account"].startswith("runtime@")
    for path in (settings.APP, settings.DEV, settings.RECEIPT):
        assert (tmp_path / path).stat().st_mode & 0o777 == 0o600
    before = {p: settings._read(tmp_path, p) for p in settings._restore_paths()}

    def interrupt():
        raise InterruptedError

    monkeypatch.setattr(settings, "write_generation_manifest", interrupt)
    changed = dict(bundle, app=bundle["app"].replace("test-only", "changed"))
    with pytest.raises(InterruptedError):
        settings.restore(tmp_path, PROJECT, "2", changed, receipt, SOURCE, operator)
    assert before == {p: settings._read(tmp_path, p) for p in before}
    assert not (tmp_path / settings.JOURNAL).exists()
    # Simulate a hard kill after file replacement, then a new process's recovery.
    (tmp_path / settings.JOURNAL).write_text(
        json.dumps({str(p): v for p, v in before.items()})
    )
    (tmp_path / settings.APP).write_text("interrupted")
    settings._recover(tmp_path)
    assert (tmp_path / settings.APP).read_text() == before[settings.APP]
    app = dict(yaml.safe_load(bundle["app"]), GOOGLE_CLOUD_PROJECT="other-project")
    (tmp_path / settings.APP).write_text(yaml.safe_dump(app))
    with pytest.raises(settings.CloudSettingsError, match="another project"):
        settings.restore(
            tmp_path, PROJECT, "2", changed, receipt, SOURCE, operator, replace=True
        )


# @matrix config setup : cli-routing project-identity
def test_cloud_settings_cli(bundle, tmp_path, monkeypatch, capsys):
    store = Store()
    monkeypatch.setattr(settings, "SecretManager", lambda *args: store)
    monkeypatch.setattr(settings, "APP_DIR", tmp_path)
    monkeypatch.setattr(settings, "_source", lambda root: SOURCE)
    (tmp_path / "package.json").write_text("{}")
    save_installation(tmp_path, bundle)
    assert settings.main(["publish", "--project", PROJECT]) == 0
    assert settings.main(["check", "--project", PROJECT, "--version", "1"]) == 0
    (tmp_path / settings.APP).write_text(
        bundle["app"].replace("test-only", "sensitive-test-password")
    )
    assert settings.main(["check", "--project", PROJECT, "--version", "1"]) == 1
    output = capsys.readouterr()
    assert "sensitive-test-password" not in output.err + output.out


class Bucket:
    def __init__(self):
        self.generation = 0
        self.raw = None

    def blob(self, name):
        assert name == checkpoints.OBJECT
        return self

    def get_blob(self, name):
        return self.blob(name) if self.generation else None

    def upload_from_string(self, raw, *, if_generation_match, content_type):
        if self.generation != if_generation_match:
            raise PreconditionFailed("changed")
        self.raw = raw
        self.generation += 1

    def download_as_bytes(self, *, if_generation_match):
        assert self.generation == if_generation_match
        return self.raw.encode()


# @matrix hosted-e2e : lifecycle recovery transactional-state
def test_checkpoint_resumes_and_excludes_competing_writers():
    bucket = Bucket()
    a = checkpoints.Checkpoint(bucket, PROJECT)
    a.save()
    b = checkpoints.Checkpoint(bucket, PROJECT)
    receipt = {"version": "7", "source": SOURCE}
    a.paths = {Path("state.json"): "state"}
    with a.operation("create", receipt):
        with pytest.raises(RuntimeError, match="holds checkpoint"):
            with b.operation("teardown", receipt):
                pytest.fail("concurrent teardown entered")
        a.write(
            Path("state.json"),
            {
                "schema_version": 1,
                "project": PROJECT,
                "source": SOURCE,
                "status": "ready",
            },
        )
    with pytest.raises(RuntimeError, match="numeric settings version"):
        with b.operation("teardown", dict(receipt, version="6")):
            pytest.fail("wrong settings version")
    with b.operation("teardown", receipt):
        assert (
            b.doc["state"]["source"] == SOURCE
            and b.doc["state"]["cloud_settings_version"] == "7"
        )
    # Abandoned lock: only the precise generation may take over.
    a.load()
    a.doc["operation"] = {"action": "execute"}
    a.save()
    with pytest.raises(RuntimeError):
        with b.operation("teardown", receipt, a.generation - 1):
            pytest.fail("stale generation")
    with b.operation("teardown", receipt, a.generation):
        assert b.doc["operation"]["action"] == "teardown"


# @matrix hosted-e2e setup : project-identity transactional-state
def test_checkpoint_seed_is_create_only(tmp_path, bundle, monkeypatch):
    save_installation(tmp_path, bundle)
    settings._record(tmp_path, PROJECT, "1", SOURCE)
    root = tmp_path / "reports/hosted-e2e"
    root.mkdir(parents=True)
    fields = {"schema_version": 1, "project": PROJECT, "service": "e2e"}
    (root / "setup.json").write_text(json.dumps(dict(fields, project_number="123")))
    (root / "state.json").write_text(json.dumps(dict(fields, status="ready")))
    bucket = Bucket()
    monkeypatch.setattr(settings, "cli_token", lambda *args: "test-token")
    monkeypatch.setattr(checkpoints, "_bucket", lambda *args, **kwargs: bucket)
    with pytest.raises(RuntimeError, match="active lifecycle"):
        checkpoints.seed(tmp_path, PROJECT)
    (root / "state.json").write_text(json.dumps(dict(fields, status="torn-down")))
    checkpoints.seed(tmp_path, PROJECT)
    with pytest.raises(RuntimeError, match="Another task changed"):
        checkpoints.seed(tmp_path, PROJECT)
    assert bucket.generation == 1


# @matrix hosted-e2e : isolation project-identity
def test_checkpoint_is_opt_in(monkeypatch, tmp_path):
    args = SimpleNamespace(action="status", recover_generation=None)
    monkeypatch.delenv("LAGNIAPPE_CLOUD_CHECKPOINT_PROJECT", raising=False)
    with checkpoints.lifecycle(None, args):
        assert checkpoints.ACTIVE.get() is None
    monkeypatch.setenv("LAGNIAPPE_CLOUD_CHECKPOINT_PROJECT", PROJECT)
    with pytest.raises(RuntimeError, match="Restore"):
        with checkpoints.lifecycle(SimpleNamespace(APP_DIR=tmp_path), args):
            pytest.fail("unconfigured checkout took remote lock")
    args.action = "validate-release-evidence"
    with checkpoints.lifecycle(None, args):
        assert checkpoints.ACTIVE.get() is None


# @matrix auth setup : adc project-identity
def test_cloud_connection_requires_target_identity(tmp_path, monkeypatch):
    path = tmp_path / "native.json"
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))
    monkeypatch.delenv("OIC_MANIFEST_PATH", raising=False)
    credentials = {
        "type": "service_account",
        "service_account_impersonation_url": f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{ACCOUNT}:generateAccessToken",
    }
    path.write_text(json.dumps(credentials))
    with pytest.raises(RuntimeError, match="federate"):
        cloud_task.connection_file(ACCOUNT)
    credentials["type"] = "external_account"
    path.write_text(json.dumps(credentials))
    assert cloud_task.connection_file(ACCOUNT) == str(path)
    with pytest.raises(RuntimeError, match="federate"):
        cloud_task.connection_file("wrong@" + PROJECT + ".iam.gserviceaccount.com")


# @matrix auth setup : adc project-identity
def test_cloud_connection_accepts_only_the_configured_relay(tmp_path, monkeypatch):
    native = tmp_path / "connection.json"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"connections": [{"is_default": True, "credentials_file": str(native)}]}
        )
    )
    monkeypatch.setenv("OIC_MANIFEST_PATH", str(manifest))
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("https_proxy", "http://proxy:8080")
    account = ACCOUNT.replace("@", "%40")
    route = f"/identity/gcp/v1/projects/-/serviceAccounts/{account}:generateAccessToken"
    relay = "https://proxy" + route
    credentials = {
        "type": "external_account",
        "service_account_impersonation_url": relay,
    }
    original = json.dumps(credentials)
    native.write_text(original)
    assert cloud_task.connection_file(ACCOUNT) == str(native)
    assert native.read_text() == original
    with pytest.raises(RuntimeError, match="federate"):
        cloud_task.connection_file(f"other@{PROJECT}.iam.gserviceaccount.com")

    for url in (
        "https://proxy.example.org" + route,
        "https://iamcredentials.googleapis.com" + route,
        "http://proxy" + route,
        "https://someone@proxy" + route,
        relay + "?alternate=route",
        relay + "#fragment",
        relay.replace(":generateAccessToken", ":signBlob"),
    ):
        native.write_text(
            json.dumps(dict(credentials, service_account_impersonation_url=url))
        )
        with pytest.raises(RuntimeError, match="federate"):
            cloud_task.connection_file(ACCOUNT)
    native.write_text(original)
    monkeypatch.delenv("https_proxy")
    with pytest.raises(RuntimeError, match="federate"):
        cloud_task.connection_file(ACCOUNT)


# @matrix setup : cli-routing project-identity
@pytest.mark.parametrize("active_account", [ACCOUNT, "other@example.com"])
def test_check_connection_uses_task_identity_before_restore(
    tmp_path, monkeypatch, capsys, active_account
):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path)
    monkeypatch.setattr(settings, "GCLOUD_CLI", "gcloud")
    monkeypatch.setattr(cloud_task, "GCLOUD_CLI", "gcloud")
    monkeypatch.setattr(cloud_task, "connection_file", lambda account: "/native.json")
    token_requests = []
    configs = set()

    def gcloud(args, *, env, capture_output, text=False):
        assert args[0] == "gcloud" and capture_output
        assert env["GOOGLE_APPLICATION_CREDENTIALS"] == "/native.json"
        configs.add(Path(env["CLOUDSDK_CONFIG"]))
        assert Path(env["CLOUDSDK_CONFIG"]).is_dir()
        output = ""
        if "describe" in args:
            output = json.dumps(
                {
                    "properties": {
                        "core": {"project": PROJECT, "account": active_account}
                    }
                }
            )
        if "print-access-token" in args:
            token_requests.append(args)
            output = "private-test-token"
        return subprocess.CompletedProcess(
            args, 0, output if text else output.encode(), b""
        )

    monkeypatch.setattr(subprocess, "run", gcloud)
    status = cloud_task.main(["--project", PROJECT, "--check-connection"])
    output = capsys.readouterr()
    if active_account == ACCOUNT:
        assert status == 0 and ACCOUNT in output.out
        assert len(token_requests) == 1 and f"--account={ACCOUNT}" in token_requests[0]
    else:
        assert status == 1 and "different account or project" in output.err
        assert not token_requests
    assert "private-test-token" not in output.out + output.err
    assert len(configs) == 1 and not configs.pop().exists()
    assert not list(tmp_path.iterdir())


# @matrix setup : cli-routing project-identity
def test_task_reuses_pinned_version(monkeypatch):
    calls = []
    monkeypatch.setattr(cloud_task, "connection_file", lambda account: "/native")
    monkeypatch.setattr(cloud_task, "_gcloud", lambda *args, **kw: None)
    monkeypatch.setattr(settings, "_receipt", lambda root: {"version": "9"})

    def run(args, **kw):
        calls.append((args, kw))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert cloud_task.main(["--project", PROJECT, "--", "example-command"]) == 0
    assert calls[0][0][-2:] == ["--version", "9"]
    assert calls[1][0] == ["example-command"]
    assert calls[1][1]["env"]["LAGNIAPPE_CLOUD_CHECKPOINT_PROJECT"] == PROJECT


# @matrix auth setup : adc project-identity
def test_startup_checks_identity_and_optional_redis(monkeypatch):
    app = {
        "EXPERIMENTS_ENABLED": True,
        "EXPERIMENTS_PROJECT": PROJECT,
        "GOOGLE_CLOUD_PROJECT": PROJECT,
        "ADMIN_EMAIL": "owner@example.com",
        "AGENT_ACCESS_EMAIL": "agent@example.com",
    }
    monkeypatch.setattr("config.SETTINGS", SimpleNamespace(APP=app))
    activate = Mock()
    monkeypatch.setattr("runner.gcloud.activate_repository_gcloud", activate)
    redis = Mock()
    monkeypatch.setattr("redis.Redis", redis)

    cloud_task.probe(PROJECT)
    activate.assert_called_once_with(
        ensure_adc=True, ensure_cli_token=True, allow_adc_login=False
    )
    redis.assert_not_called()
    with pytest.raises(RuntimeError, match="selected experiments installation"):
        cloud_task.probe("other-project")
    redis.return_value.ping.return_value = False
    with pytest.raises(RuntimeError, match="PING"):
        cloud_task.probe(PROJECT, check_redis=True)
    redis.return_value.ping.assert_called_once_with()
    redis.return_value.close.assert_called_once_with()


# @matrix setup : cli-routing project-identity
@pytest.mark.parametrize("options", [[], ["--check-redis"]])
def test_default_startup_reads_hosted_status(monkeypatch, options):
    monkeypatch.setattr(cloud_task, "connection_file", lambda account: "/native")
    monkeypatch.setattr(cloud_task, "_gcloud", lambda *args, **kwargs: None)
    monkeypatch.setattr(settings, "_receipt", lambda root: {})
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", run)
    assert cloud_task.main(["--project", PROJECT, *options]) == 0
    restore, probe, status = [call.args[0] for call in run.call_args_list]
    assert restore[-5:] == [
        "cloud-settings",
        "restore",
        "--operator",
        "--version",
        "current",
    ]
    assert probe[1] == "-c" and probe[3:] == [PROJECT, *options]
    assert status[-2:] == ["hosted-e2e", "status"]


# @matrix release : protected-branch source-integrity
def test_release_rejects_unverified_heads():
    repo = "owner/lagniappe"
    identity = {"repo": {"full_name": repo}}
    head = "b" * 40
    pr = {
        "merged": True,
        "merge_commit_sha": SOURCE,
        "base": dict(identity, ref="main"),
        "head": dict(identity, ref="hotfix/3.0.1", sha=head),
    }
    status = {
        "context": "Source quality and traceability",
        "state": "success",
        "creator": {"login": "github-actions[bot]"},
        "target_url": "https://github.com/owner/lagniappe/actions/runs/42",
    }
    run = {
        "path": ".github/workflows/hosted-e2e.yml",
        "head_sha": head,
        "conclusion": "success",
        "head_repository": identity["repo"],
    }

    def api(path):
        if path.endswith(f"/{head}/statuses?per_page=100"):
            return [status]
        assert path.endswith("/runs/42")
        return run

    assert release.verified_version(repo, SOURCE, pr, api) == "3.0.1"
    for obj, key, bad in (
        (pr, "merge_commit_sha", head),
        (run, "head_sha", SOURCE),
        (run, "path", "other.yml"),
        (status, "state", "failure"),
        (pr["head"], "ref", "main"),
    ):
        old = obj[key]
        obj[key] = bad
        with pytest.raises(ValueError):
            release.verified_version(repo, SOURCE, pr, api)
        obj[key] = old


# @matrix release : git-upgrade source-integrity
def test_publication_retries_with_annotated_tag(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    local = tmp_path / "work"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    subprocess.run(["git", "init", str(local)], check=True, capture_output=True)
    monkeypatch.chdir(local)
    for command in (
        ["config", "user.name", "Test"],
        ["config", "user.email", "test@example.com"],
        ["commit", "--allow-empty", "-m", "Release"],
        ["remote", "add", "origin", str(remote)],
    ):
        release._run("git", *command)
    sha = release._run("git", "rev-parse", "HEAD")
    run = subprocess.run
    releases = []

    def gh_or_git(args, **kwargs):
        if args[0] == "git":
            return run(args, **kwargs)
        if args[2] == "view":
            return SimpleNamespace(
                returncode=0 if releases else 1,
                stdout=json.dumps(
                    {"tagName": "v1.0.1", "isDraft": False, "isPrerelease": False}
                ),
            )
        assert args[2:4] == ("create", "v1.0.1") and "--verify-tag" in args
        releases.append(args[3])
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(subprocess, "run", gh_or_git)
    for _ in range(2):
        release.publish_tag("owner/repo", sha, "1.0.1", Path("notes"))
    assert release._run("git", "cat-file", "-t", "v1.0.1") == "tag" and releases == [
        "v1.0.1"
    ]
    release._run("git", "tag", "v1.0.2")
    release._run("git", "push", "origin", "v1.0.2")
    with pytest.raises(ValueError, match="lightweight"):
        release.publish_tag("owner/repo", sha, "1.0.2", Path("notes"))


# @matrix hosted-e2e setup : iam project-identity
def test_operator_grants_stay_in_experiments(bundle):
    from runner.cloud_operator_iam import CUSTOM, bindings

    app = dict(
        yaml.safe_load(bundle["app"]),
        EXPERIMENTS_ENABLED=True,
        EXPERIMENTS_PROJECT=PROJECT,
        AGENT_ACCESS_EMAIL="agent@example.com",
    )
    setup = dict(
        project=PROJECT,
        project_number="123",
        region="us-central1",
        job="lagniappe-e2e",
        runtime_email=f"e2e@{PROJECT}.iam.gserviceaccount.com",
        settings_secret="e2e-settings",
        redis_ca_secret="e2e-ca",
        artifact_bucket="results",
        artifact_repository="e2e",
    )
    app_engine = f"{PROJECT}@appspot.gserviceaccount.com"
    grants = bindings(
        PROJECT, app, setup, "build@example.com", app_engine_account=app_engine, hosted_job_exists=True
    )
    assert [
        role for command, role in grants
        if command == ["iam", "service-accounts", "add-iam-policy-binding", app_engine]
    ] == ["roles/iam.serviceAccountUser"]
    job_policy = f"projects/{PROJECT}/roles/lagniappeHostedJobPolicy"
    assert [command for command, role in grants if role == job_policy] == [
        ["run", "jobs", "add-iam-policy-binding", "lagniappe-e2e", "--region=us-central1"]
    ]
    assert all(role != job_policy for _, role in bindings(PROJECT, app, setup, "build@example.com"))
    assert set(CUSTOM["lagniappeHostedJobPolicy"][1]) == {
        "run.jobs.getIamPolicy", "run.jobs.setIamPolicy",
    }
    for exists in (False, True):
        standing = bindings(
            PROJECT, app, setup, "build@example.com",
            hosted_job_exists=exists, project_job_policy=True,
        )
        assert [command for command, role in standing if role == job_policy] == [
            ["projects", "add-iam-policy-binding", PROJECT]
        ]
    for command, role in grants:
        if role.endswith("lagniappeTestBucketCors"):
            assert command[-1].startswith("gs://test-")
        if role.endswith("lagniappeSettingsPublisher"):
            assert command == ["secrets", "add-iam-policy-binding", settings.SECRET]
        assert role not in {"roles/owner", "roles/editor", "roles/secretmanager.admin"}
    with pytest.raises(ValueError):
        bindings("other-project", app, setup, "build@example.com")
    with pytest.raises(ValueError):
        bindings("other-project", app, setup, "build@example.com", project_job_policy=True)
    with pytest.raises(ValueError):
        bindings(PROJECT, app, dict(setup, job="unrelated-job"), "build@example.com", hosted_job_exists=True)


# @matrix hosted-e2e setup : iam project-identity
def test_operator_checks_both_build_accounts_before_granting_access(monkeypatch, capsys):
    from runner.cloud_operator_iam import _build_accounts

    compute = "123-compute@developer.gserviceaccount.com"
    app_engine = f"app-build@{PROJECT}.iam.gserviceaccount.com"
    app = {"id": PROJECT, "serviceAccount": app_engine}
    policy = {"bindings": []}
    base = ["gcloud", f"--project={PROJECT}"]

    def discover(argv, *, text):
        assert argv[:len(base)] == base
        command = argv[len(base):-1]
        if command == ["builds", "get-default-service-account"]:
            return f"projects/{PROJECT}/serviceAccounts/{compute}\n"
        if command == ["app", "describe"]:
            return json.dumps(app)
        assert command == ["projects", "get-iam-policy", PROJECT]
        return json.dumps(policy)

    monkeypatch.setattr(subprocess, "check_output", discover)
    for account, role in ((compute, "roles/editor"), (app_engine, "roles/owner")):
        policy["bindings"] = [{"role": role, "members": [f"serviceAccount:{account}"]}]
        assert _build_accounts(base, PROJECT, apply=False) == (compute, app_engine)
        assert account in capsys.readouterr().out
        with pytest.raises(SystemExit, match=role):
            _build_accounts(base, PROJECT, apply=True)
    policy["bindings"] = [{"role": "roles/editor", "members": ["user:owner@example.com"]}]
    assert _build_accounts(base, PROJECT, apply=True) == (compute, app_engine)
    app["id"] = "different-project"
    with pytest.raises(SystemExit, match="selected project"):
        _build_accounts(base, PROJECT, apply=True)


# @matrix deploy setup : project-identity
def test_deploy_requires_pinned_experiments_target(bundle, tmp_path, monkeypatch):
    save_installation(tmp_path, bundle)
    app = dict(
        yaml.safe_load(bundle["app"]),
        EXPERIMENTS_ENABLED=True,
        EXPERIMENTS_PROJECT=PROJECT,
        AGENT_ACCESS_EMAIL="agent@example.com",
    )
    operator = {"NAME": "cloud", "ACCOUNT": ACCOUNT}
    draft = SimpleNamespace(APP=app, GCLOUD_CONFIG=dict(operator, PROJECT=PROJECT))
    monkeypatch.setattr(settings, "_source", lambda root: SOURCE)
    settings._record(tmp_path, PROJECT, "7", SOURCE, operator_target=operator)
    settings.verify_operator_target(tmp_path, PROJECT, draft)
    (tmp_path / settings.DEV).write_text("edited")
    from runner import deploy

    monkeypatch.setenv("LAGNIAPPE_CLOUD_CHECKPOINT_PROJECT", PROJECT)
    monkeypatch.setattr(deploy, "SETTINGS", draft)
    monkeypatch.setattr(
        deploy, "Directory", SimpleNamespace(APP=SimpleNamespace(value=tmp_path))
    )
    with pytest.raises(settings.CloudSettingsError, match="pinned experiments"):
        deploy.deploy()
