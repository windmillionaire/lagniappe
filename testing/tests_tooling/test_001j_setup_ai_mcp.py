"""AI policy and MCP lifecycle contracts at the installer/provider boundary."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from installer import mcp
from installer.errors import SetupError

pytestmark = pytest.mark.tooling


def settings():
    return {
        "AI_ENABLED": True, "EXTERNAL_AI_ENABLED": True,
        "GOOGLE_CLOUD_PROJECT": "demo-project", "RESOURCE_REGION": "us-central1",
        "APP_URL": "https://demo-project.uc.r.appspot.com", "DEPLOYER_EMAIL": "owner@example.test",
    }


def service(target, resource="https://lagniappe-demo.run.app/mcp", *, enabled=True):
    return {
        "metadata": {"labels": {mcp.VERSION_LABEL: target.version, "managed-by": "lagniappe"}},
        "spec": {"template": {"spec": {
            "serviceAccountName": target.runtime,
            "containers": [{"image": target.image, "env": [
                {"name": "LAGNIAPPE_MCP_ENABLED", "value": "true" if enabled else "false"},
                {"name": "LAGNIAPPE_MCP_ISSUER", "value": target.issuer},
                {"name": "LAGNIAPPE_MCP_RESOURCE", "value": resource},
            ]}],
        }}},
        "status": {"url": resource.removesuffix("/mcp"),
                   "latestReadyRevisionName": "revision-1", "latestCreatedRevisionName": "revision-1",
                   "conditions": [{"type": "Ready", "status": "True"}],
                   "traffic": [{"revisionName": "revision-1", "percent": 100}]},
    }


class Cloud:
    """Small provider state machine; unknown commands fail instead of succeeding."""
    def __init__(self, target):
        self.target = target
        self.calls = []
        self.accounts = {}
        self.repository = None
        self.bucket = None
        self.policies = {}
        self.fields = []
        self.sink = {"exclusions": [{"name": "unrelated", "filter": "severity=DEBUG"}]}
        self.image = None
        self.service = None
        self.fail_activation = False

    def run(self, target, arguments, **kwargs):
        assert target.project == "demo-project"
        self.calls.append(list(arguments))
        args = [arg for arg in arguments if not arg.startswith("--")]
        output = {}
        missing = False
        if "get-iam-policy" in args:
            index = args.index("get-iam-policy")
            key = tuple(args[:index] + [args[index+1]])
            output = self.policies.setdefault(key, {"etag": "version-1", "bindings": []})
        elif "set-iam-policy" in args:
            index = args.index("set-iam-policy")
            key = tuple(args[:index] + [args[index+1]])
            self.policies[key] = json.loads(Path(args[index+2]).read_text())
        elif args[:2] == ["services", "enable"]:
            pass
        elif args[:2] == ["iam", "service-accounts"]:
            if args[2] == "create":
                email = f"{args[3]}@demo-project.iam.gserviceaccount.com"
                self.accounts[email] = {"email": email}
            else:
                output = self.accounts.get(args[3])
                missing = output is None
        elif args[:2] == ["artifacts", "repositories"]:
            if args[2] == "create":
                self.repository = {"format": "DOCKER"}
            else:
                output = self.repository
                missing = output is None
        elif args[:3] == ["storage", "buckets", "create"]:
            self.bucket = {"project_number": "123", "location": "US-CENTRAL1"}
        elif args[:3] == ["storage", "buckets", "describe"]:
            output = self.bucket
            missing = output is None
        elif args[:2] == ["projects", "describe"]:
            output = {"projectNumber": "123"}
        elif args[:3] == ["firestore", "fields", "ttls"]:
            if args[3] == "list":
                output = self.fields
            else:
                self.fields = [{"name": "projects/demo-project/databases/(default)/collectionGroups/mcp_oauth/fields/expires_at", "ttlConfig": {"state": "CREATING"}}]
        elif args[:2] == ["logging", "sinks"]:
            if args[2] == "update":
                self.sink["exclusions"].append({"name": mcp.AUTH_LOG_EXCLUSION, "filter": mcp.AUTH_LOG_FILTER})
            output = self.sink
        elif args[:3] == ["artifacts", "docker", "images"]:
            output = self.image
            missing = output is None
        elif args[:2] == ["builds", "submit"]:
            self.image = {"image_summary": {"digest": "sha256:abc"}}
        elif args[:3] == ["run", "services", "describe"]:
            output = self.service
            missing = output is None
        elif args[:2] == ["run", "deploy"]:
            enabled = any("LAGNIAPPE_MCP_ENABLED=true" in arg for arg in arguments)
            self.service = service(target, enabled=enabled and not self.fail_activation)
        elif args[:3] == ["run", "services", "update"]:
            self.service = service(target, enabled=False)
        elif args[:3] == ["run", "services", "update-traffic"]:
            assert "--to-latest" in arguments
            self.service["status"]["traffic"] = [{"revisionName": "revision-1", "percent": 100}]
        else:
            raise AssertionError(f"Unexpected provider command: {arguments}")
        return SimpleNamespace(returncode=1 if missing else 0, stdout=json.dumps(output), stderr="NOT_FOUND" if missing else "")


@pytest.fixture
def cloud(monkeypatch):
    target = mcp._deployment(settings())
    cloud = Cloud(target)
    monkeypatch.setattr(mcp, "_run", cloud.run)
    monkeypatch.setattr(mcp, "require_permissions", lambda target: None)
    monkeypatch.setattr(mcp, "record_step", lambda step: None)
    return cloud


# @matrix mcp-install : source-version upload-boundary
def test_mcp_version_tracks_only_build_inputs_and_rejects_symlinks(tmp_path, monkeypatch):
    source = tmp_path / "mcp/src/lagniappe_mcp/server.py"
    source.parent.mkdir(parents=True)
    source.write_text("initial")
    for name in ("pyproject.toml", "uv.lock", "README.md", "Dockerfile", "cloudbuild.yaml", "gcloudignore"):
        (tmp_path / "mcp" / name).write_text(name)
    first = mcp.source_version(tmp_path)
    (tmp_path / "app.py").write_text("app-only edit")
    (tmp_path / "mcp/.venv").mkdir()
    (tmp_path / "mcp/.venv/local").write_text("environment")
    assert mcp.source_version(tmp_path) == first
    with monkeypatch.context() as runtime:
        runtime.setattr(mcp, "RUNTIME_ARGUMENTS", (*mcp.RUNTIME_ARGUMENTS, "--new-runtime-setting"))
        assert mcp.source_version(tmp_path) != first
    source.write_text("new service behavior")
    assert mcp.source_version(tmp_path) != first
    (source.parent / "secret.py").symlink_to(tmp_path / "app.py")
    with pytest.raises(SetupError, match="symlink"):
        mcp.source_version(tmp_path)


# @matrix mcp-install : configuration opt-in legacy-settings
def test_mcp_policy_preserves_legacy_api_without_implicitly_installing_service():
    from config.ai_settings import normalize_ai_features
    assert normalize_ai_features({})["EXTERNAL_AI_ENABLED"]
    assert not mcp.requested({})
    assert mcp.requested({"REMOTE_MCP": {"enabled": True}})
    assert mcp.requested({"EXTERNAL_AI_ENABLED": True})
    assert not mcp.requested({"AI_ENABLED": False, "EXTERNAL_AI_ENABLED": True})
    assert not mcp.requested({"EXTERNAL_AI_ENABLED": False, "REMOTE_MCP": {"enabled": True}})


# @matrix mcp-install : fail-closed provider-discovery
def test_mcp_discovery_distinguishes_absence_from_unavailable_state(monkeypatch):
    target = mcp._deployment(settings())
    for error in ("PERMISSION_DENIED", "PERMISSION_DENIED: resource NOT_FOUND or inaccessible", "network timeout", "service API disabled"):
        monkeypatch.setattr(mcp, "_run", lambda *a, **k: SimpleNamespace(returncode=1, stderr=error))
        with pytest.raises(SetupError, match="discovery failed"):
            mcp.describe(target, ["run", "services", "describe"], optional=True)
    monkeypatch.setattr(mcp, "_run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="NOT_FOUND"))
    assert mcp.describe(target, ["run", "services", "describe"], optional=True) is None
    monkeypatch.setattr(mcp, "_run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="[]"))
    with pytest.raises(SetupError, match="unexpected resource"):
        mcp.describe(target, ["run", "services", "describe"])


# @matrix mcp-install : iam preflight
def test_mcp_permissions_are_checked_before_resource_mutation(monkeypatch):
    target = mcp._deployment(settings())
    client = SimpleNamespace(test_iam_permissions=lambda **kwargs: SimpleNamespace(permissions=[]))
    with pytest.raises(SetupError, match="provisioning permissions"):
        mcp.require_permissions(target, client=client)
    monkeypatch.setattr(mcp, "require_permissions", lambda target: (_ for _ in ()).throw(SetupError("denied")))
    monkeypatch.setattr(mcp, "_run", lambda *a, **k: pytest.fail("mutated before checking permissions"))
    with pytest.raises(SetupError, match="denied"):
        mcp.reconcile_resources(target, "owner@example.test")


# @matrix mcp-install : iam idempotence handoff
def test_mcp_iam_preserves_conditions_etags_and_skips_noop_writes(cloud):
    key = ("run", "services", mcp.SERVICE)
    original = {"role": "roles/run.admin", "members": ["user:owner@example.test"], "condition": {"expression": "true", "title": "conditional"}}
    cloud.policies[key] = {"etag": "etag-to-preserve", "bindings": [deepcopy(original)]}
    grants = [("user:owner@example.test", ["roles/run.admin"])]
    mcp.reconcile_access(cloud.target, ["run", "services"], mcp.SERVICE, grants)
    policy = cloud.policies[key]
    assert policy["etag"] == "etag-to-preserve"
    assert original in policy["bindings"]
    assert any(row.get("condition") is None for row in policy["bindings"])
    cloud.calls.clear()
    mcp.reconcile_access(cloud.target, ["run", "services"], mcp.SERVICE, grants)
    assert not any("set-iam-policy" in call for call in cloud.calls)
    mcp.reconcile_access(cloud.target, ["run", "services"], mcp.SERVICE, remove_member="user:owner@example.test")
    assert not cloud.policies[key]["bindings"]


# @matrix mcp-install : iam resources keyless
def test_mcp_resources_use_separate_build_identity_and_scoped_roles(cloud):
    mcp.reconcile_resources(cloud.target, "owner@example.test")
    assert set(cloud.accounts) == {cloud.target.runtime, cloud.target.build_account}
    project_roles = cloud.policies[("projects", "demo-project")]["bindings"]
    assert project_roles == [{"role": "roles/logging.logWriter", "members": [f"serviceAccount:{cloud.target.build_account}"]}]
    bucket_roles = cloud.policies[("storage", "buckets", f"gs://{cloud.target.bucket}")]["bindings"]
    assert {"role": "roles/storage.objectViewer", "members": [f"serviceAccount:{cloud.target.build_account}"]} in bucket_roles
    assert all(cloud.target.runtime not in json.dumps(policy) for policy in cloud.policies.values())
    assert cloud.sink["exclusions"][0]["name"] == "unrelated"
    assert cloud.sink["exclusions"][1]["filter"] == mcp.AUTH_LOG_FILTER
    cloud.calls.clear()
    mcp.reconcile_resources(cloud.target, "owner@example.test")
    assert not any("create" in call or "set-iam-policy" in call or "update" in call for call in cloud.calls)


# @matrix mcp-install : bootstrap configuration source-version update-order
def test_mcp_prepare_bootstraps_disabled_and_saves_exact_resource_before_app(cloud):
    config = settings()
    prepared = mcp.prepare_deployment(config)
    assert prepared.version == config["MCP_VERSION"]
    assert config["REMOTE_MCP"]["resource"] == "https://lagniappe-demo.run.app/mcp"
    assert config["REMOTE_MCP"]["actors"] is None
    assert config["REMOTE_MCP"]["codex_enabled"] is True
    assert not mcp._matches(cloud.service, prepared, config["REMOTE_MCP"]["resource"])
    assert any("--gcs-source-staging-dir=gs://demo-project-mcp-builds/source" in call for call in cloud.calls)
    assert all("LAGNIAPPE_MCP_ENABLED=true" not in " ".join(call) for call in cloud.calls)
    mcp.finish_deployment(prepared, config)
    assert mcp._matches(cloud.service, prepared, config["REMOTE_MCP"]["resource"])


# @matrix mcp-install : source-version update-order verification
def test_mcp_unchanged_update_skips_build_and_revision(cloud):
    config = settings()
    prepared = mcp.prepare_deployment(config)
    mcp.finish_deployment(prepared, config)
    cloud.calls.clear()
    prepared = mcp.prepare_deployment(config)
    mcp.finish_deployment(prepared, config)
    assert not any(call[:2] in (["builds", "submit"], ["run", "deploy"]) for call in cloud.calls)
    cloud.service["status"]["traffic"][0]["percent"] = 50
    assert not mcp._matches(cloud.service, prepared, config["REMOTE_MCP"]["resource"])


# @matrix mcp-install : disable failure-recovery update-order verification
def test_mcp_disable_and_failed_activation_do_not_claim_success(cloud, capsys):
    config = settings()
    prepared = mcp.prepare_deployment(config)
    cloud.fail_activation = True
    with pytest.raises(SetupError, match="Retry with ./setup.sh mcp"):
        mcp.finish_deployment(prepared, config)
    assert "MCP is ready" not in capsys.readouterr().out
    cloud.fail_activation = False
    mcp.finish_deployment(mcp.prepare_deployment(config), config)
    config["EXTERNAL_AI_ENABLED"] = False
    assert mcp.prepare_deployment(config) is None
    assert config["REMOTE_MCP"]["enabled"] is False
    mcp.finish_deployment(None, config)
    assert not mcp._matches(cloud.service, prepared, config["REMOTE_MCP"]["resource"])
    assert not any("delete" in call for call in cloud.calls)


# @matrix mcp-install : doctor recovery source-version
def test_mcp_inspection_is_read_only_and_detects_version_drift(cloud):
    config = settings()
    prepared = mcp.prepare_deployment(config)
    mcp.finish_deployment(prepared, config)
    cloud.calls.clear()
    assert mcp.inspect_deployment(config)["state"] == "AVAILABLE"
    cloud.service["metadata"]["labels"][mcp.VERSION_LABEL] = "old"
    assert mcp.inspect_deployment(config)["state"] == "UNAVAILABLE"
    assert all(call[:3] == ["run", "services", "describe"] for call in cloud.calls)


# @matrix mcp-install : handoff iam
def test_mcp_handoff_covers_both_accounts_bucket_repository_and_service(cloud):
    config = settings()
    config["DEPLOYER_EMAIL"] = "installer@example.test"
    mcp.prepare_deployment(config)
    mcp.handoff_access(config, owner="owner@example.test")
    mcp.handoff_access(config, remove_installer="installer@example.test")
    scoped = [policy for key, policy in cloud.policies.items() if key[0] != "projects"]
    assert len(scoped) == 5
    assert all("user:owner@example.test" in json.dumps(policy) for policy in scoped)
    assert all("user:installer@example.test" not in json.dumps(policy) for policy in scoped)
    assert "serviceAccount:lagniappe-mcp-build@demo-project.iam.gserviceaccount.com" in json.dumps(list(cloud.policies.values()))


# @matrix mcp-install : cli-routing retry
def test_focused_mcp_command_uses_normal_deployment_path(monkeypatch):
    from installer import verify, utils
    events = []
    monkeypatch.setattr(mcp.SETTINGS, "APP", settings())
    monkeypatch.setattr(verify, "prepare_existing_installation", lambda: events.append("prepare"))
    monkeypatch.setattr(utils, "deploy_to_app_engine", lambda: events.append("deploy"))
    assert mcp.configure_mcp() == 0
    assert events == ["prepare", "deploy"]


# @matrix deploy : app-failure update-order
# @source runner/deploy.py::deploy
def test_app_failure_never_activates_mcp(monkeypatch):
    from runner import deploy
    events = []
    monkeypatch.setattr(deploy, "verify_runtime_deploy_surface", lambda: None)
    monkeypatch.setattr(deploy, "verify_frontend_build", lambda **k: None)
    monkeypatch.setattr(deploy, "verify_generation_manifest", lambda: None)
    monkeypatch.setattr(deploy.SETTINGS, "APP", {"VERSION": "test"})
    monkeypatch.setattr(deploy.SETTINGS, "save", lambda: events.append("save"))
    monkeypatch.setattr(mcp, "prepare_deployment", lambda settings: events.append("prepare") or "target")
    monkeypatch.setattr(mcp, "finish_deployment", lambda target, settings: events.append("activate"))
    monkeypatch.setattr(deploy, "_deploy_app_yaml", lambda *a, **k: (_ for _ in ()).throw(SetupError("app failed")))
    with pytest.raises(SetupError, match="app failed"):
        deploy.deploy(build_assets=False)
    assert events == ["prepare", "save"]
    monkeypatch.setattr(deploy, "_deploy_app_yaml", lambda *a, **k: events.append("app"))
    events.clear()
    deploy.deploy(build_assets=False)
    assert events == ["prepare", "save", "app", "activate"]


# @matrix setup : optional site-policy settings-save
# @source installer/optional.py::configure_ai_features
def test_disabling_ai_skips_model_and_external_prompts(monkeypatch, capsys):
    import config
    from installer import optional
    saves, prompts = [], []
    saved = SimpleNamespace(APP={"AI_MODEL": "custom-model"}, save=lambda: saves.append(True))
    monkeypatch.setattr(config, "SETTINGS", saved)
    formatter = SimpleNamespace(info=lambda value: value, success=lambda value: value)
    monkeypatch.setattr(optional, "FORMATTER", SimpleNamespace(initialize=lambda: formatter))
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "n")
    assert optional.configure_ai_features() is False
    assert saved.APP["AI_ENABLED"] is False
    assert saved.APP["EXTERNAL_AI_ENABLED"] is False
    assert saved.APP["AI_OBSERVABILITY"] is False
    assert saved.APP["AI_MODEL"] == "custom-model"
    assert len(prompts) == len(saves) == 1
    assert "AI models:" not in capsys.readouterr().out
