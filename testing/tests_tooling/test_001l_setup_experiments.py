"""Experiments installation settings, local setup and deployment evidence."""

from types import SimpleNamespace

import pytest

from config.experiments import normalize_experiments_config
from installer import experiments
from installer.errors import SetupError
from runner.experiments import source_identity

pytestmark = pytest.mark.tooling


def _app():
    return {
        "GOOGLE_CLOUD_PROJECT": "experiments-project",
        "ADMIN_EMAIL": "owner@example.test",
        "AGENT_ACCESS_EMAIL": "agent@example.test",
        "AGENT_ACCESS_CODE": "private-test-code",
        "APP_URL": "https://experiments-project.uc.r.appspot.com",
    }


# @matrix experiments : configuration
def test_experiments_settings_are_opt_in_and_project_bound():
    assert normalize_experiments_config({})["EXPERIMENTS_ENABLED"] is False
    app = {
        **_app(),
        "EXPERIMENTS_ENABLED": True,
        "EXPERIMENTS_PROJECT": "experiments-project",
        "EXPERIMENTS_DIAGNOSTICS": "trace",
        "EXPERIMENTS_EXECUTION_ENABLED": True,
    }
    assert normalize_experiments_config(app)["EXPERIMENTS_DIAGNOSTICS"] == "trace"
    # Turning off ordinary AI/access policy remains a valid deployment and
    # revokes the effective capability instead of preventing app startup.
    assert normalize_experiments_config({**app, "AI_ENABLED": False})
    for overrides in (
        {"EXPERIMENTS_ENABLED": "true"},
        {"EXPERIMENTS_EXECUTION_ENABLED": 1},
        {"EXPERIMENTS_PROJECT": "production"},
        {"EXPERIMENTS_DIAGNOSTICS": {}},
        {"EXPERIMENTS_DIAGNOSTICS": "verbose"},
        {"EXPERIMENTS_SOURCE_ID": "branch-name"},
        {"ADMIN_EMAIL": "agent@example.test"},
        {"AGENT_ACCESS_EMAIL": ""},
        {"EXPERIMENTS_ENABLED": False},
    ):
        with pytest.raises(ValueError):
            normalize_experiments_config({**app, **overrides})


# @matrix experiments : configuration
def test_experiments_preset_preserves_existing_choices_and_rejects_conversion(
    monkeypatch, capsys
):
    import config

    saved = []
    settings = SimpleNamespace(
        APP=_app(),
        GCLOUD_CONFIG={"NAME": "experiments"},
        save=lambda: saved.append(True),
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    assert experiments.configure() is False
    assert saved == []
    with pytest.raises(SetupError, match="not converted"):
        experiments.configure(requested=True)
    assert experiments.configure(requested=True, first_install=True)
    assert settings.APP["EXPERIMENTS_PROJECT"] == "experiments-project"
    assert settings.APP["GOOGLE_SIGNIN_ENABLED"] is True
    assert settings.APP["MCP_NAME"] == "experiments-mcp"
    assert settings.APP["EXPERIMENTS_EXECUTION_ENABLED"] is True
    settings.APP.update(
        EXPERIMENTS_EXECUTION_ENABLED=False,
        EXPERIMENTS_DIAGNOSTICS="off",
        AGENT_ACCESS_ENABLED=False,
    )
    assert experiments.configure(requested=True)
    assert settings.APP["EXPERIMENTS_EXECUTION_ENABLED"] is False
    assert settings.APP["AGENT_ACCESS_ENABLED"] is False
    assert "private-test-code" not in capsys.readouterr().out


# @matrix experiments : toolchain
def test_experiments_toolchain_builds_production_without_provisioning_test_resources(
    monkeypatch,
):
    from installer import development
    from runner import context

    monkeypatch.setattr(context, "NPM_CLI", "/local/npm")
    monkeypatch.setattr(development, "_installed_node_version", lambda: "22.14.0")
    monkeypatch.setattr(development, "node_version_supported", lambda version: True)
    commands = []
    monkeypatch.setattr(
        development,
        "_run_command",
        lambda label, command: commands.append(command) or True,
    )
    experiments.prepare_toolchain()
    assert ["/local/npm", "ci"] in commands
    assert any(
        command[-3:] == ["playwright", "install", "chromium"] for command in commands
    )
    assert any("runner.uv_bootstrap" in command for command in commands)
    assert all(
        "gcloud" not in command and "development" not in command for command in commands
    )
    monkeypatch.setattr(development, "_run_command", lambda *args: False)
    with pytest.raises(SetupError, match="failed"):
        experiments.prepare_toolchain()


# @matrix experiments : bootstrap
def test_experiments_bootstrap_verification_requires_saved_accounts(monkeypatch):
    import config
    import requests
    from google.cloud import datastore

    app = {
        **_app(),
        "EXPERIMENTS_ENABLED": True,
        "EXPERIMENTS_PROJECT": "experiments-project",
    }
    monkeypatch.setattr(config, "SETTINGS", SimpleNamespace(APP=app))
    monkeypatch.setattr(
        requests, "get", lambda *args, **kwargs: SimpleNamespace(status_code=200)
    )
    rows = {
        ("site", "experiments-bootstrap"): {
            "version": 1,
            "owner": "owner-key",
            "agent": "agent-key",
        },
        "owner-key": {"email": app["ADMIN_EMAIL"], "owner": True},
        "agent-key": {"email": app["AGENT_ACCESS_EMAIL"], "admin": True},
    }
    monkeypatch.setattr(
        datastore,
        "Client",
        lambda *, project: SimpleNamespace(key=lambda *parts: parts, get=rows.get),
    )
    experiments.verify_bootstrap(require_admin=True)
    rows["agent-key"]["admin"] = False
    experiments.verify_bootstrap()  # a later intentional demotion is preserved
    with pytest.raises(SetupError, match="Administrator"):
        experiments.verify_bootstrap(require_admin=True)
    rows.pop("owner-key")
    with pytest.raises(SetupError, match="owner account"):
        experiments.verify_bootstrap()


# @matrix experiments : source-identity
def test_source_identity_includes_dirty_code_and_excludes_credentials(tmp_path):
    source = tmp_path / "lagniappe/core/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("original")
    secret = tmp_path / "config/files/settings.yaml"
    secret.parent.mkdir(parents=True)
    secret.write_text("secret-one")
    first = source_identity(tmp_path)
    secret.write_text("secret-two")
    assert source_identity(tmp_path) == first
    source.write_text("uncommitted change")
    second = source_identity(tmp_path)
    assert second != first
    (source.parent / "untracked.py").write_text("new source")
    assert source_identity(tmp_path) != second


# @source installer/__main__.py::_parser
# @source installer/__main__.py::_dispatch
# @matrix setup : cli-routing
def test_experiments_cli_is_an_install_option(monkeypatch):
    from installer import __main__ as cli
    from installer import install

    calls = []
    monkeypatch.setattr(install, "install", lambda **kwargs: calls.append(kwargs))
    args = cli._parser().parse_args(["--experiments"])
    cli._dispatch(args)
    assert calls == [{"experiments": True}]


# @source installer/deploy.py::deploy_to_app_engine
# @matrix setup : deploy
def test_experiments_deploy_rebuilds_assets_and_verifies_bootstrap(monkeypatch):
    import config
    from installer import deploy, mcp, monitoring, upgrade_notice
    from runner import deploy as runner_deploy

    app = {"EXPERIMENTS_ENABLED": True}
    monkeypatch.setattr(config, "SETTINGS", SimpleNamespace(APP=app))
    monkeypatch.setattr(upgrade_notice, "legacy_upgrade_deploy_notice_required", lambda settings: False)
    monkeypatch.setattr(mcp, "requested", lambda app: False)
    monkeypatch.setattr(monitoring, "reconcile_memory_alert_after_deploy", lambda: None)
    calls = []
    monkeypatch.setattr(runner_deploy, "deploy", lambda **kwargs: calls.append(("deploy", kwargs)))
    monkeypatch.setattr(experiments, "verify_bootstrap", lambda **kwargs: calls.append(("verify", kwargs)))
    deploy.deploy_to_app_engine(print_final_summary=False, first_install=True)
    assert calls[0][0] == "deploy" and calls[0][1]["build_assets"] is True
    assert calls[1] == ("verify", {"require_admin": True})
    app["EXPERIMENTS_ENABLED"] = False
    deploy.deploy_to_app_engine(print_final_summary=False)
    assert calls[2][1]["build_assets"] is False
