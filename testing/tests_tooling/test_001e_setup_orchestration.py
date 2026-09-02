"""Characterization tests for setup orchestration, CLI status, and failures."""

from contextlib import nullcontext
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

from installer.errors import SetupError
from installer.state import (
    SetupProcessLock,
    record_mutation,
    record_step,
    setup_operation,
)
from testing.utility.setup_fakes import (
    SpinnerRecorder,
    completed_process,
    spinner_factory,
)

pytestmark = pytest.mark.tooling

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CLI_PROBE = REPOSITORY_ROOT / "testing" / "utility" / "setup_cli_probe.py"

CLI_MODES = (
    pytest.param([], "install", id="install"),
    pytest.param(["auth"], "auth", id="auth"),
    pytest.param(["url"], "url", id="url"),
    pytest.param(["email"], "email", id="email"),
    pytest.param(["oauth"], "oauth", id="oauth"),
    pytest.param(["ai"], "ai", id="ai"),
    pytest.param(["ai-email"], "ai-email", id="ai-email"),
    pytest.param(["security"], "security", id="security"),
    pytest.param(["jobs"], "jobs", id="jobs"),
    pytest.param(["monitoring"], "monitoring", id="monitoring"),
    pytest.param(["handoff"], "handoff", id="handoff"),
    pytest.param(["update"], "update", id="update"),
    pytest.param(["upgrade"], "upgrade", id="upgrade"),
    pytest.param(["development"], "development", id="development"),
    pytest.param(["repair"], "repair", id="repair"),
    pytest.param(["doctor"], "doctor", id="doctor"),
)


def _fake_formatter():
    return types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            success=lambda message: message,
            info=lambda message: message,
            warning=lambda message: message,
            error=lambda message, error=None: message,
            ok_glyph="[OK]",
            fail_glyph="[X]",
            yaspin=spinner_factory(SpinnerRecorder()),
        )
    )


def _load_config_constants():
    path = REPOSITORY_ROOT / "config" / "constants.py"
    spec = importlib.util.spec_from_file_location(
        "_setup_orchestration_constants",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cli(arguments, *, behavior="return", status=0):
    return subprocess.run(
        [
            sys.executable,
            str(CLI_PROBE),
            behavior,
            str(status),
            *arguments,
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _module(monkeypatch, setup_package, name, **members):
    module_name = f"installer.{name}"
    module = types.ModuleType(module_name)
    for member_name, value in members.items():
        setattr(module, member_name, value)
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setattr(setup_package, name, module, raising=False)
    return module


def _install_harness(
    monkeypatch,
    *,
    fail_at=None,
    deploy=False,
    with_ai_email=False,
):
    import installer as setup_package
    from installer import install as install_module

    events = []
    settings = types.SimpleNamespace(
        APP={},
        DEPLOY={"runtime": "python314"},
        NODE={"version": "0.1"},
        GCLOUD_CONFIG={},
        save=lambda: events.append("settings.save"),
    )
    config_module = types.ModuleType("config")
    config_module.SETTINGS = settings
    config_module.File = types.SimpleNamespace(
        INDEX_YAML=types.SimpleNamespace(value="index.yaml"),
        APP_YAML=types.SimpleNamespace(value="lagniappe.yaml"),
    )
    monkeypatch.setitem(sys.modules, "config", config_module)

    def step(name, result=None):
        def invoke(*args, **kwargs):
            events.append(name)
            if name == fail_at:
                raise RuntimeError(f"injected failure at {name}")
            return result

        return invoke

    def set_application_defaults():
        events.append("set_application_defaults")
        assert settings.APP == {}
        if fail_at == "set_application_defaults":
            raise RuntimeError("injected failure at set_application_defaults")
        settings.APP["APP_NAME"] = "Lagniappe"
        settings.GCLOUD_CONFIG.update(
            {"ACCOUNT": "owner@example.test", "PROJECT": "project-1"}
        )
        return True

    _module(
        monkeypatch,
        setup_package,
        "create_config",
        set_application_defaults=set_application_defaults,
    )
    _module(
        monkeypatch,
        setup_package,
        "utils",
        check_gcloud_cli=step("check_gcloud_cli"),
        deploy_to_app_engine=step("deploy_to_app_engine"),
    )
    gcloud_module = _module(
        monkeypatch,
        setup_package,
        "gcloud",
        enable_gcloud_apis=step("enable_gcloud_apis"),
        setup_app_engine=step("setup_app_engine"),
        configure_storage_buckets=step("configure_storage_buckets"),
        create_task_queue=step("create_task_queue"),
        configure_data_protection=step("configure_data_protection"),
        create_ocr_processor=step("create_ocr_processor"),
        create_deferred_job_reconciler=step("create_deferred_job_reconciler", True),
    )

    def configure_deferred_job_recovery(f, gcloud):
        try:
            gcloud.create_deferred_job_reconciler()
        except Exception:
            return False
        return True

    _module(
        monkeypatch,
        setup_package,
        "upgrade",
        _configure_deferred_job_recovery=configure_deferred_job_recovery,
    )
    assert gcloud_module is setup_package.gcloud
    _module(
        monkeypatch,
        setup_package,
        "auth_email",
        setup_auth_email=step("setup_auth_email", True),
    )
    _module(
        monkeypatch,
        setup_package,
        "identity",
        setup_identity_platform=step("setup_identity_platform", True),
    )
    _module(
        monkeypatch,
        setup_package,
        "admin",
        setup_admin_and_oauth=step("setup_admin_and_oauth"),
    )
    _module(
        monkeypatch,
        setup_package,
        "redis",
        setup_redis=step("setup_redis"),
    )
    _module(
        monkeypatch,
        setup_package,
        "optional",
        setup_error_monitoring=step("setup_error_monitoring"),
        change_ai_model=step("change_ai_model"),
    )
    ai_email_candidate = {"enabled": True} if with_ai_email else None

    def activate_ai_email(candidate):
        assert candidate is ai_email_candidate
        events.append("activate_ai_email")
        if fail_at == "activate_ai_email":
            raise RuntimeError("injected failure at activate_ai_email")
        return True

    _module(
        monkeypatch,
        setup_package,
        "ai_email",
        setup_ai_email=step("setup_ai_email", ai_email_candidate),
        activate_ai_email=activate_ai_email,
    )

    monkeypatch.setattr(
        install_module,
        "ensure_pip_is_available",
        step("ensure_pip_is_available"),
    )
    monkeypatch.setattr(
        install_module,
        "ensure_setup_dependencies",
        step("ensure_setup_dependencies"),
    )
    answers = iter(["", "y" if deploy else "n"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    return install_module, settings, events


# @matrix setup : prerequisites virtualenv
def test_default_install_characterization_starts_empty_and_reaches_all_boundaries(
    monkeypatch,
    capsys,
):
    install_module, settings, events = _install_harness(monkeypatch, deploy=True)

    assert install_module.install() == 0
    assert settings.APP["APP_NAME"] == "Lagniappe"
    assert events == [
        "ensure_pip_is_available",
        "check_gcloud_cli",
        "ensure_setup_dependencies",
        "set_application_defaults",
        "enable_gcloud_apis",
        "setup_app_engine",
        "configure_storage_buckets",
        "create_task_queue",
        "configure_data_protection",
        "create_ocr_processor",
        "setup_auth_email",
        "setup_identity_platform",
        "setup_admin_and_oauth",
        "setup_redis",
        "setup_error_monitoring",
        "change_ai_model",
        "setup_ai_email",
        "settings.save",
        "deploy_to_app_engine",
        "create_deferred_job_reconciler",
    ]
    output = capsys.readouterr().out
    assert "Wrapping up installation..." in output
    assert "Deployment complete!" in output
    assert "every Gunicorn worker adds application memory use" in output
    assert "limits F2 and B2 to three workers" in output
    assert output.index("Deployment complete!") < output.index("Setup complete!")
    assert "Manual deployment steps:" not in output


# @matrix setup : explicit-project manual-deploy
def test_default_install_only_prints_manual_deployment_steps_when_declined(
    monkeypatch,
    capsys,
):
    install_module, _settings, events = _install_harness(
        monkeypatch,
        deploy=False,
    )

    assert install_module.install() == 0
    output = capsys.readouterr().out
    assert "Manual deployment steps:" in output
    assert "Review the generated YAML files" in output
    assert "index.yaml --project project-1" in output
    assert "lagniappe.yaml --project project-1" in output
    assert "Then reconcile memory monitoring: ./setup.sh monitoring" in output
    assert "Wrapping up installation..." not in output
    assert "deploy_to_app_engine" not in events


# @pairs ai-email:activation setup:main-install
def test_default_install_activates_ai_email_after_deploy_and_jobs(
    monkeypatch,
):
    install_module, _settings, events = _install_harness(
        monkeypatch,
        deploy=True,
        with_ai_email=True,
    )

    assert install_module.install() == 0
    assert events.index("setup_ai_email") < events.index("settings.save")
    assert events.index("deploy_to_app_engine") < events.index(
        "create_deferred_job_reconciler"
    )
    assert events.index("create_deferred_job_reconciler") < events.index(
        "activate_ai_email"
    )


def test_recovery_install_skips_optional_reconfiguration(monkeypatch):
    install_module, settings, events = _install_harness(monkeypatch)
    settings.RECOVERY_MODE = True

    assert install_module.install() == 0
    assert "setup_error_monitoring" not in events
    assert "change_ai_model" not in events
    assert "setup_ai_email" not in events
    assert "setup_redis" in events
    assert "settings.save" in events


# @matrix setup : failure-isolation recovery
def test_recovery_is_announced_before_dependency_or_provider_mutation(
    monkeypatch,
    tmp_path,
    capsys,
):
    from installer import install as install_module

    config_dir = tmp_path / "config" / "files"
    config_dir.mkdir(parents=True)
    (config_dir / "lagniappe_settings.yaml").write_text("APP_NAME: Demo\n")
    assert install_module._recovery_file_present(tmp_path)

    events = []
    monkeypatch.setattr(
        install_module,
        "_recovery_file_present",
        lambda: True,
    )
    monkeypatch.setattr(
        install_module,
        "ensure_pip_is_available",
        lambda: events.append(("pip", capsys.readouterr().out)),
    )
    monkeypatch.setattr(
        "installer.utils.check_gcloud_cli",
        lambda: (_ for _ in ()).throw(RuntimeError("stop after announcement")),
    )

    with pytest.raises(RuntimeError, match="stop after announcement"):
        install_module.install()

    assert events
    assert "Recovery mode detected" in events[0][1]


# @matrix setup : dependency-bootstrap focused-mode gcloud-token operation-journal portability prerequisites python-version virtualenv
def test_setup_python_runtime_gate_precedes_every_cli_mode(monkeypatch):
    from runner import gcloud as runner_gcloud
    import installer as setup_package
    from installer import handoff as handoff_module
    from installer import package_install
    from installer import state

    setup_path = REPOSITORY_ROOT / "installer" / "__main__.py"
    spec = importlib.util.spec_from_file_location("_portable_setup_cli", setup_path)
    assert spec is not None
    assert spec.loader is not None
    setup_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup_cli)
    verify_runtime = setup_package.verify_setup_runtime

    for parameters in CLI_MODES:
        arguments = list(parameters.values[0])
        events = []
        monkeypatch.setattr(
            setup_package,
            "verify_setup_runtime",
            lambda: events.append("runtime"),
        )
        monkeypatch.setattr(
            package_install,
            "ensure_pip_is_available",
            lambda: events.append("pip"),
        )
        monkeypatch.setattr(
            package_install,
            "ensure_setup_dependencies",
            lambda: events.append("dependencies"),
        )
        monkeypatch.setattr(
            runner_gcloud,
            "activate_repository_gcloud",
            lambda **kwargs: events.append(("activate-gcloud", kwargs)),
        )
        monkeypatch.setattr(
            handoff_module,
            "prepare_handoff_operator",
            lambda: events.append("prepare-handoff"),
        )
        monkeypatch.setattr(
            setup_cli,
            "_dispatch",
            lambda args: events.append("dispatch") or 0,
        )
        monkeypatch.setattr(
            state,
            "setup_operation",
            lambda mode, argv: nullcontext(),
        )

        assert setup_cli.main(arguments) == 0
        expected = ["runtime"]
        if arguments:
            expected.extend(("pip", "dependencies"))
            if arguments != ["auth"]:
                if arguments == ["handoff"]:
                    expected.append("prepare-handoff")
                else:
                    expected.append(
                        (
                            "activate-gcloud",
                            {
                                "ensure_adc": arguments != ["doctor"],
                                "ensure_cli_token": arguments != ["doctor"],
                            },
                        )
                    )
        expected.append("dispatch")
        assert events == expected

    monkeypatch.setattr(setup_package, "verify_setup_runtime", verify_runtime)
    monkeypatch.setattr(setup_package.sys, "version_info", (3, 11))
    with pytest.raises(SetupError):
        setup_package.verify_setup_runtime()

    monkeypatch.setattr(setup_package.sys, "version_info", (3, 12))
    monkeypatch.setattr(setup_package, "project_virtualenv_active", lambda: False)
    with pytest.raises(SetupError):
        setup_package.verify_setup_runtime()

    monkeypatch.setattr(setup_package, "project_virtualenv_active", lambda: True)
    assert setup_package.verify_setup_runtime() is None


# @matrix auth setup : adc explicit-command gcloud-token interactive
def test_setup_auth_uses_explicit_browser_flow(monkeypatch, capsys):
    from installer import auth
    from runner import gcloud as runner_gcloud

    calls = []
    monkeypatch.setattr(
        runner_gcloud,
        "activate_repository_gcloud",
        lambda **kwargs: calls.append(kwargs),
    )

    assert auth.authenticate() == 0
    assert calls == [
        {
            "ensure_adc": True,
            "ensure_cli_token": True,
            "allow_cli_login": True,
            "allow_runtime_adc": False,
            "allow_adc_login": True,
            "select_adc_target": True,
        }
    ]
    assert "Google Cloud CLI and Application Default Credentials are ready" in (
        capsys.readouterr().out
    )


# @matrix setup : gcloud-token safe-failure
def test_stale_gcloud_token_stops_with_setup_auth_instruction(
    monkeypatch,
    capsys,
):
    import installer as setup_package
    from installer import __main__ as setup_cli
    from installer import package_install
    from runner import gcloud as runner_gcloud

    monkeypatch.setattr(setup_package, "verify_setup_runtime", lambda: None)
    monkeypatch.setattr(package_install, "ensure_pip_is_available", lambda: None)
    monkeypatch.setattr(package_install, "ensure_setup_dependencies", lambda: None)
    monkeypatch.setattr(
        runner_gcloud,
        "activate_repository_gcloud",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "The saved gcloud login needs to be refreshed. "
                "Run ./setup.sh auth, then retry this setup command."
            )
        ),
    )

    assert setup_cli.cli(["upgrade"]) == 1
    output = capsys.readouterr().out
    assert "Setup failed [setup]" in output
    assert "Run ./setup.sh auth" in output
    assert "gcloud auth login" not in output


# @matrix setup : generated-command instructions portability repository-root virtualenv
def test_portable_runtime_paths_commands_and_virtualenv_instructions():
    from runner import context as runner_context

    assert runner_context.REPOSITORY_ROOT == REPOSITORY_ROOT
    config_source = (REPOSITORY_ROOT / "config" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "Path(__file__).resolve().parent.parent" in config_source
    assert "from runner" not in config_source
    assert "from installer" not in config_source
    assert runner_context.project_virtualenv_active(
        prefix=runner_context.PROJECT_VIRTUALENV,
        base_prefix=runner_context.PROJECT_VIRTUALENV.parent / "system-python",
    )
    assert not runner_context.project_virtualenv_active(
        prefix=runner_context.PROJECT_VIRTUALENV.parent / "other-venv",
        base_prefix=runner_context.PROJECT_VIRTUALENV.parent / "system-python",
    )

    windows_command = runner_context.setup_command("jobs", windows=True)
    posix_command = runner_context.setup_command("jobs", windows=False)
    assert windows_command == r".\setup.cmd jobs"
    assert posix_command == "./setup.sh jobs"

    instructions = runner_context.virtualenv_instructions()
    assert "./setup.sh" in instructions
    assert ".\\setup.cmd" in instructions
    assert "Windows PowerShell" in instructions

    posix_launcher = (REPOSITORY_ROOT / "setup.sh").read_text(encoding="utf-8")
    windows_launcher = (REPOSITORY_ROOT / "setup.cmd").read_text(
        encoding="utf-8"
    )
    assert (
        "gcloud info --format=value\\(basic.python_location\\)"
        in posix_launcher
    )
    assert '"$LAGNIAPPE_BOOTSTRAP_PYTHON" -E -m venv' in posix_launcher
    assert '"$LAGNIAPPE_VENV_PYTHON" -E -m installer "$@"' in posix_launcher
    assert '"$@"' in posix_launcher
    assert "gcloud info" not in windows_launcher
    assert "Python.Python.3.14" in windows_launcher
    assert "winget install" in windows_launcher
    assert "bundledpython" in windows_launcher
    assert 'rmdir /s /q "%LAGNIAPPE_VENV_DIR%"' in windows_launcher
    assert '"%LAGNIAPPE_BOOTSTRAP_PYTHON%" -E -m venv' in windows_launcher
    assert (
        '"%LAGNIAPPE_VENV_PYTHON%" -E -m installer %*'
        in windows_launcher
    )
    assert "%*" in windows_launcher


# @pair setup:recovery
def test_recovery_uses_saved_project_preserves_owner_and_verifies_before_dev_write(
    monkeypatch,
    tmp_path,
    capsys,
):
    import installer as setup_package
    from config import recovery as config_recovery
    from installer import create_config
    from installer import recovery as setup_recovery
    from runner import gcloud as runner_gcloud

    recovered_project = "recovered-project-1"
    ambient_project = "wrong-ambient-project"
    owner = "owner@example.test"
    deployer = "deployer@example.test"
    recovered_settings = {
        "CONFIG_KIND": config_recovery.CONFIG_KIND,
        "CONFIG_SCHEMA_VERSION": config_recovery.CONFIG_SCHEMA_VERSION,
        "APP_NAME": "Recovered App",
        "GOOGLE_CLOUD_PROJECT": recovered_project,
        "ADMIN_EMAIL": owner,
        "APP_URL": (
            "https://recovered-project-1.us-central1.r.appspot.com"
        ),
        "GOOGLE_LOGIN_URI": (
            "https://recovered-project-1.us-central1.r.appspot.com/"
            "users/google-signin"
        ),
        "GIBBERISH": "recovery-secret",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "OCR_LOCATION": "us",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            f"runtime@{recovered_project}.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            f"runtime@{recovered_project}.iam.gserviceaccount.com"
        ),
        "IDENTITY_PLATFORM_CONFIG": {
            "apiKey": "identity-key",
            "projectId": recovered_project,
        },
        "AUTH_EMAIL_CONFIG": {
            "provider": "smtp",
            "service": "Resend",
            "host": "smtp.resend.com",
            "port": 465,
            "security": "ssl",
            "username": "resend",
            "password": "provider-key",
            "senderEmail": "noreply@example.test",
            "senderName": "Recovered App",
        },
        "VERSION": "1.0.0",
        "REDIS_TLS": False,
    }
    config_directory = tmp_path / "config" / "files"
    config_directory.mkdir(parents=True)
    canonical_file = config_directory / "lagniappe_settings.yaml"
    canonical_file.write_text(
        yaml.safe_dump(recovered_settings),
        encoding="utf-8",
    )
    assert list(config_directory.iterdir()) == [canonical_file]

    settings = types.SimpleNamespace(
        APP=yaml.safe_load(canonical_file.read_text(encoding="utf-8")),
        GCLOUD_CONFIG={},
        NODE={"version": "1.0.0"},
    )
    constants = _load_config_constants()
    config_module = types.ModuleType("config")
    config_module.__path__ = [str(REPOSITORY_ROOT / "config")]
    config_module.SETTINGS = settings
    config_module.constants = constants
    config_module.File = types.SimpleNamespace(
        APP_SETTINGS_YAML=types.SimpleNamespace(
            exists=lambda: True,
            save=lambda data: canonical_file.write_text(
                yaml.safe_dump(data),
                encoding="utf-8",
            )
        ),
        DEV_YAML=types.SimpleNamespace(exists=lambda: False),
    )
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setattr(runner_gcloud, "config_gcloud", lambda: None)
    monkeypatch.setattr(setup_package, "FORMATTER", _fake_formatter())

    events = []
    selections = []

    def select_project(project_id, sanitized_name):
        selections.append((project_id, sanitized_name))
        return project_id

    monkeypatch.setattr(
        create_config,
        "_get_gcloud_account",
        lambda account: deployer,
    )
    monkeypatch.setattr(create_config, "_get_gcloud_project", select_project)
    monkeypatch.setattr(
        create_config,
        "_set_adc_quota_project",
        lambda project_id, spinner: events.append(("adc", project_id))
        or {
            "state": "success",
            "principal": deployer,
            "project": recovered_project,
            "quota_project": recovered_project,
            "error": None,
        },
    )
    monkeypatch.setattr(
        create_config,
        "_require_operator_permissions",
        lambda project_id, **kwargs: events.append(
            (
                "permissions",
                project_id,
                "cli" if kwargs.get("client") is project_client else "adc",
            )
        ),
    )
    project_client = object()
    monkeypatch.setattr(
        create_config,
        "_gcloud_project_client",
        lambda account: events.append(("cli-token", account)) or project_client,
    )
    monkeypatch.setattr(
        create_config,
        "_active_cli_identity",
        lambda: {
            "configuration": "recovered-app",
            "account": deployer,
            "project": recovered_project,
        },
    )
    preflight = {
        "project": {
            "state": "available",
            "details": {"projectNumber": "123456"},
            "error": None,
        },
        "billing_account": "billing-1",
        "billing_enabled": True,
        "enabled_apis": set(),
        "missing_apis": [],
    }
    monkeypatch.setattr(
        create_config,
        "_target_preflight",
        lambda project_id: events.append(("preflight", project_id)) or preflight,
    )
    def ensure_adc(account, project_id=None):
        events.append(("adc-auth", account, project_id))
        return {
            "state": "success",
            "principal": deployer,
            "project": recovered_project,
            "quota_project": recovered_project,
            "error": None,
        }

    monkeypatch.setattr(create_config, "_ensure_adc_principal", ensure_adc)
    monkeypatch.setattr(
        create_config,
        "_display_install_identity_summary",
        lambda target_preflight, adc_identity: None,
    )
    monkeypatch.setattr(
        create_config,
        "_apply_target_preflight",
        lambda project_id, target_preflight, project_ready=None: None,
    )
    monkeypatch.setattr(
        config_recovery,
        "materialize_recovery_redis_ca",
        lambda settings: events.append(("materialize-ca", settings["REDIS_TLS"])),
    )

    def verify_resources(app_settings, project_id, project_details=None):
        events.append(("verify", project_id, project_details))
        assert not config_module.File.DEV_YAML.exists()
        return {
            "service-account": {
                "state": setup_recovery.AVAILABLE,
                "details": {},
                "error": None,
            }
        }

    monkeypatch.setattr(
        setup_recovery,
        "verify_recovery_resources",
        verify_resources,
    )

    def write_defaults():
        events.append(("write-dev", recovered_project))
        create_config._build_app_settings()

    monkeypatch.setattr(create_config, "_set_default_config", write_defaults)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert create_config.set_application_defaults()
    assert selections == [(recovered_project, "recovered-app")]
    assert settings.GCLOUD_CONFIG == {
        "NAME": "recovered-app",
        "ACCOUNT": deployer,
        "PROJECT": recovered_project,
        "BILLING_ACCOUNT": "billing-1",
    }
    assert settings.APP["GOOGLE_CLOUD_PROJECT"] == recovered_project
    assert settings.APP["ADMIN_EMAIL"] == owner
    assert settings.APP["INSTALLER_EMAIL"] == deployer
    assert settings.APP["DEPLOYER_EMAIL"] == deployer
    assert settings.APP["RUNTIME_SERVICE_ACCOUNT_EMAIL"] == (
        f"runtime@{recovered_project}.iam.gserviceaccount.com"
    )
    assert settings.APP["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] == (
        f"runtime@{recovered_project}.iam.gserviceaccount.com"
    )
    assert ("preflight", recovered_project) in events
    assert ("permissions", recovered_project, "cli") in events
    assert ("permissions", recovered_project, "adc") in events
    assert ("verify", recovered_project, {"projectNumber": "123456"}) in events
    assert events.index(
        ("permissions", recovered_project, "cli")
    ) < events.index(("adc-auth", deployer, recovered_project))
    assert events.index(("permissions", recovered_project, "adc")) < events.index(
        ("verify", recovered_project, {"projectNumber": "123456"})
    )
    assert events.index(
        ("verify", recovered_project, {"projectNumber": "123456"})
    ) < events.index(
        ("write-dev", recovered_project)
    )
    assert ambient_project not in repr(events)
    assert "Recovery mode" in capsys.readouterr().out


def _recovery_provider_settings():
    return {
        "APP_URL": "https://recovered-project-1.appspot.com",
        "GIBBERISH": "bucket-secret",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "OCR_LOCATION": "us",
        "OCR_PROCESSOR": "lagniappe-document-processor",
        "OCR_PROCESSOR_ID": (
            "projects/123456/locations/us/processors/processor-1"
        ),
        "TASK_QUEUE_NAME": "lagniappe-tasks",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@recovered-project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@recovered-project-1.iam.gserviceaccount.com"
        ),
        "DEPLOYER_EMAIL": "deployer@example.com",
        "IDENTITY_PLATFORM_CONFIG": {
            "apiKey": "identity-api-key",
            "projectId": "recovered-project-1",
        },
        "REDIS_HOST": "redis.example.test",
        "REDIS_PORT": 12345,
        "REDIS_PASSWORD": "secret",
    }


# @matrix setup : failure-isolation provider-discovery recovery
def test_recovery_provider_states_distinguish_absent_from_unavailable(monkeypatch):
    from installer import recovery

    results = iter(
        [
            completed_process(["gcloud"], returncode=1, stderr="NOT_FOUND"),
            completed_process(
                ["gcloud"],
                returncode=1,
                stderr="PERMISSION_DENIED",
            ),
            completed_process(["gcloud"], stdout="{broken"),
        ]
    )
    monkeypatch.setattr(
        recovery,
        "run_gcloud_command",
        lambda command, check=False: next(results),
    )

    assert recovery._probe_gcloud_json(["one"])["state"] == recovery.ABSENT
    assert recovery._probe_gcloud_json(["two"])["state"] == recovery.UNAVAILABLE
    assert recovery._probe_gcloud_json(["three"])["state"] == recovery.UNAVAILABLE


# @matrix setup : project-identity project-number provider-discovery recovery
def test_recovery_provider_discovery_targets_only_recovered_project(monkeypatch):
    from installer import recovery

    project_id = "recovered-project-1"
    settings = _recovery_provider_settings()
    commands = []

    def gcloud(command, check=False):
        commands.append(command)
        if command[:3] == ["iam", "service-accounts", "describe"]:
            details = {
                "email": settings["RUNTIME_SERVICE_ACCOUNT_EMAIL"]
            }
        elif command[:3] == ["iam", "service-accounts", "get-iam-policy"]:
            details = {
                "bindings": [
                    {
                        "role": "roles/iam.serviceAccountTokenCreator",
                        "members": [
                            "serviceAccount:"
                            + settings["RUNTIME_SERVICE_ACCOUNT_EMAIL"],
                            "user:deployer@example.com",
                        ],
                    }
                ]
            }
        elif command[:3] == ["services", "list", "--enabled"]:
            return completed_process(
                command,
                stdout="iamcredentials.googleapis.com\n",
            )
        elif command[:2] == ["app", "describe"]:
            details = {
                "defaultHostname": "recovered-project-1.appspot.com",
                "locationId": "us-central",
            }
        elif command[:3] == ["app", "versions", "list"]:
            details = [
                {
                    "serviceAccount": settings[
                        "RUNTIME_SERVICE_ACCOUNT_EMAIL"
                    ]
                }
            ]
        elif command[:3] == ["tasks", "queues", "describe"]:
            details = {
                "name": (
                    "projects/recovered-project-1/locations/us-central1/"
                    "queues/lagniappe-tasks"
                )
            }
        else:
            details = {"projectNumber": "123456"}
        return completed_process(command, stdout=json.dumps(details))

    monkeypatch.setattr(recovery, "run_gcloud_command", gcloud)
    monkeypatch.setattr(
        recovery,
        "_probe_ocr",
        lambda project, location, name: {
            "state": recovery.AVAILABLE,
            "details": {
                "name": name,
                "display_name": settings["OCR_PROCESSOR"],
            },
            "error": None,
        },
    )
    monkeypatch.setattr(
        recovery,
        "_probe_identity_platform",
        lambda project: {
            "state": recovery.AVAILABLE,
            "details": {
                "emailPasswordEnabled": True,
                "subtype": "IDENTITY_PLATFORM",
                "standalone": True,
            },
            "error": None,
        },
    )
    monkeypatch.setattr(
        recovery,
        "_probe_redis",
        lambda recovered: {
            "state": recovery.AVAILABLE,
            "details": None,
            "error": None,
        },
    )

    report = recovery.verify_recovery_resources(
        settings,
        project_id,
        project_details={"projectNumber": "123456"},
    )

    assert set(observation["state"] for observation in report.values()) == {
        recovery.AVAILABLE
    }
    assert commands
    assert all(
        f"--project={project_id}" in command
        for command in commands
    )
    assert [
        command
        for command in commands
        if command[:3] == ["services", "list", "--enabled"]
    ] == [
        [
            "services",
            "list",
            "--enabled",
            f"--project={project_id}",
            "--filter=config.name=iamcredentials.googleapis.com",
            "--format=value(config.name)",
        ]
    ]
    assert "wrong-ambient-project" not in repr(commands)

    monkeypatch.setattr(
        recovery,
        "_probe_identity_platform",
        lambda project: {
            "state": recovery.AVAILABLE,
            "details": {
                "emailPasswordEnabled": False,
                "subtype": "IDENTITY_PLATFORM",
                "standalone": True,
            },
            "error": None,
        },
    )
    with pytest.raises(
        recovery.RecoveryResourceError,
        match="email/password authentication is disabled",
    ):
        recovery.verify_recovery_resources(
            settings,
            project_id,
            project_details={"projectNumber": "123456"},
        )

    foreign_ocr = {
        **settings,
        "OCR_PROCESSOR_ID": (
            "projects/654321/locations/us/processors/processor-1"
        ),
    }
    ocr_calls = []
    monkeypatch.setattr(
        recovery,
        "_probe_ocr",
        lambda *args: ocr_calls.append(args)
        or {
            "state": recovery.AVAILABLE,
            "details": {},
            "error": None,
        },
    )
    with pytest.raises(
        recovery.RecoveryResourceError,
        match="project ID or project number",
    ):
        recovery.verify_recovery_resources(
            foreign_ocr,
            project_id,
            project_details={"projectNumber": "123456"},
        )
    assert ocr_calls == []


# @matrix setup : keyless-config provider-discovery recovery repair
def test_recovery_reports_missing_signing_setup_as_repairable_drift(monkeypatch):
    from installer import recovery

    settings = _recovery_provider_settings()

    def available(details=None):
        return {
            "state": recovery.AVAILABLE,
            "details": details or {},
            "error": None,
        }

    monkeypatch.setattr(
        recovery,
        "_probe_service_account",
        lambda project, email: available({"email": email}),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_enabled_api",
        lambda project, service: {
            "state": recovery.ABSENT,
            "details": {"state": "DISABLED"},
            "error": None,
        },
    )
    monkeypatch.setattr(
        recovery,
        "_probe_service_account_policy",
        lambda project, email: available({"bindings": []}),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_app_engine",
        lambda project: available(
            {
                "defaultHostname": "recovered-project-1.appspot.com",
                "locationId": "us-central",
            }
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_runtime_version",
        lambda project: available(
            [{"serviceAccount": settings["RUNTIME_SERVICE_ACCOUNT_EMAIL"]}]
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_task_queue",
        lambda project, location, queue: available(
            {
                "name": (
                    f"projects/{project}/locations/{location}/queues/{queue}"
                )
            }
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_ocr",
        lambda project, location, name: available(
            {
                "name": name,
                "display_name": settings["OCR_PROCESSOR"],
            }
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_identity_platform",
        lambda project: available(
            {
                "emailPasswordEnabled": True,
                "subtype": "IDENTITY_PLATFORM",
                "standalone": True,
            }
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_bucket",
        lambda project, name: available({"projectNumber": "123456"}),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_redis",
        lambda recovered: available(),
    )

    report = recovery.verify_recovery_resources(
        settings,
        "recovered-project-1",
        project_details={"projectNumber": "123456"},
    )

    assert report["iam-credentials-api"]["state"] == recovery.ABSENT
    assert report["signing-iam"]["state"] == recovery.ABSENT
    assert set(report["signing-iam"]["missing_members"]) == {
        "serviceAccount:"
        + settings["RUNTIME_SERVICE_ACCOUNT_EMAIL"],
        "user:deployer@example.com",
    }


# @matrix setup : failure-isolation project-identity provider-discovery recovery
def test_recovery_provider_mismatch_or_unavailable_stops_before_mutation(
    monkeypatch,
):
    from installer import recovery

    settings = _recovery_provider_settings()

    def available(details=None):
        return {
            "state": recovery.AVAILABLE,
            "details": details or {},
            "error": None,
        }

    monkeypatch.setattr(
        recovery,
        "_probe_service_account",
        lambda project, email: available({"email": email}),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_enabled_api",
        lambda project, service: available({"state": "ENABLED"}),
    )
    runtime_email = settings["RUNTIME_SERVICE_ACCOUNT_EMAIL"]
    monkeypatch.setattr(
        recovery,
        "_probe_service_account_policy",
        lambda project, email: available(
            {
                "bindings": [
                    {
                        "role": "roles/iam.serviceAccountTokenCreator",
                        "members": [
                            f"serviceAccount:{runtime_email}",
                            "user:deployer@example.com",
                        ],
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_probe_app_engine",
        lambda project: available({"defaultHostname": "wrong.appspot.com"}),
    )

    with pytest.raises(
        recovery.RecoveryResourceError,
        match="App Engine hostname",
    ):
        recovery.verify_recovery_resources(settings, "recovered-project-1")

    monkeypatch.setattr(
        recovery,
        "_probe_app_engine",
        lambda project: available(
            {
                "defaultHostname": "recovered-project-1.appspot.com",
                "locationId": "europe-west",
            }
        ),
    )
    with pytest.raises(
        recovery.RecoveryResourceError,
        match="App Engine location",
    ):
        recovery.verify_recovery_resources(settings, "recovered-project-1")

    monkeypatch.setattr(
        recovery,
        "_probe_app_engine",
        lambda project: {
            "state": recovery.UNAVAILABLE,
            "details": None,
            "error": "permission denied",
        },
    )
    with pytest.raises(
        recovery.RecoveryResourceError,
        match="unavailable",
    ):
        recovery.verify_recovery_resources(settings, "recovered-project-1")


# @matrix setup : cli-routing cli-status lazy-imports
@pytest.mark.parametrize(("arguments", "entry_point"), CLI_MODES)
def test_cli_subprocess_routes_every_mode_and_returns_status(arguments, entry_point):
    status = 7
    result = _run_cli(arguments, status=status)

    expected_status = (
        1 if entry_point == "jobs" else 0 if entry_point == "monitoring" else status
    )
    assert result.returncode == expected_status
    assert f"CALL {entry_point}" in result.stdout
    if entry_point in {"jobs", "monitoring"}:
        assert "CALL verify" in result.stdout


# @matrix setup : failure-propagation unexpected-errors
@pytest.mark.parametrize(("arguments", "entry_point"), CLI_MODES)
def test_cli_subprocess_provider_failures_are_nonzero(arguments, entry_point):
    result = _run_cli(arguments, behavior="raise")

    assert result.returncode != 0
    assert f"CALL {entry_point}" in result.stdout
    assert "provider failure" in result.stdout


# @matrix setup : cli-status failure-propagation
def test_cli_subprocess_treats_none_cancellation_as_failure():
    result = _run_cli([], behavior="cancel")

    assert result.returncode != 0
    assert "CALL install" in result.stdout


# @matrix setup : argument-validation cli-routing
def test_cli_subprocess_rejects_multiple_or_dashed_commands():
    result = _run_cli(["url", "ai"], status=0)

    assert result.returncode == 2
    assert "CALL url" not in result.stdout
    assert "CALL ai" not in result.stdout

    result = _run_cli(["doctor", "ai"], status=0)
    assert result.returncode == 2
    assert "CALL doctor" not in result.stdout
    assert "CALL ai" not in result.stdout

    result = _run_cli(["-update"], status=0)
    assert result.returncode == 2
    assert "CALL update" not in result.stdout


def test_cli_subprocess_routes_upgrade_branch():
    result = _run_cli(["upgrade", "--branch", "release/candidate"], status=0)

    assert result.returncode == 0
    assert "CALL upgrade" in result.stdout
    assert "kwargs={'branch': 'release/candidate'}" in result.stdout


def test_cli_subprocess_rejects_branch_without_upgrade():
    result = _run_cli(["--branch", "main"], status=0)

    assert result.returncode == 2
    assert "CALL " not in result.stdout

    result = _run_cli(["upgrade", "--branch", " "], status=0)
    assert result.returncode == 2
    assert "CALL " not in result.stdout


REMOTE_MUTATION_BOUNDARIES = (
    "set_application_defaults",
    "enable_gcloud_apis",
    "setup_app_engine",
    "configure_storage_buckets",
    "create_task_queue",
    "configure_data_protection",
    "create_ocr_processor",
    "setup_auth_email",
    "setup_identity_platform",
    "setup_admin_and_oauth",
    "setup_redis",
    "setup_error_monitoring",
    "change_ai_model",
    "setup_ai_email",
    "deploy_to_app_engine",
    "create_deferred_job_reconciler",
    "activate_ai_email",
)


@pytest.mark.parametrize("failure_boundary", REMOTE_MUTATION_BOUNDARIES)
def test_default_install_stops_after_each_injected_remote_failure(
    monkeypatch,
    failure_boundary,
):
    install_module, _settings, events = _install_harness(
        monkeypatch,
        fail_at=failure_boundary,
        deploy=True,
        with_ai_email=failure_boundary == "activate_ai_email",
    )

    if failure_boundary == "create_deferred_job_reconciler":
        assert install_module.install() == 1
    else:
        with pytest.raises(RuntimeError, match=failure_boundary):
            install_module.install()

    assert failure_boundary in events
    assert not set(REMOTE_MUTATION_BOUNDARIES[
        REMOTE_MUTATION_BOUNDARIES.index(failure_boundary) + 1 :
    ]).intersection(events)


LOCAL_SETTING_WRITES = (
    "APP_YAML",
    "APP_SETTINGS_YAML",
    "DEV_YAML",
    "PACKAGE_JSON",
    "INDEX_YAML",
    "MANIFEST_JSON",
)


@pytest.mark.parametrize("failure_file", LOCAL_SETTING_WRITES)
def test_settings_save_characterizes_each_local_write_failure(
    monkeypatch,
    failure_file,
):
    import config

    writes = []

    def save(file_ref, data):
        writes.append(file_ref.name)
        if file_ref.name == failure_file:
            raise OSError(f"injected write failure: {file_ref.name}")
        return True

    monkeypatch.setattr(config.File, "save", save)
    monkeypatch.setattr(config.File, "exists", lambda file_ref: True)
    monkeypatch.setattr(config, "write_generation_manifest", lambda: None)

    settings = object.__new__(config.Settings)
    settings.DEPLOY = {"runtime": "python314"}
    settings.APP = {"APP_NAME": "Fault Probe"}
    settings.DEV = {}
    settings.NODE = {"version": "1.0.0"}
    settings.INDEX = {"indexes": []}
    settings.MANIFEST = {"name": "Fault Probe"}
    settings.GCLOUD_CONFIG = {"PROJECT": "project-1"}
    settings.DEV_CONFIG = {"SERVER_PORT": "5050"}
    settings.TEST_CONFIG = {"SERVER_PORT": "5000"}

    with pytest.raises(OSError, match=failure_file):
        settings.save()

    failure_index = LOCAL_SETTING_WRITES.index(failure_file)
    assert writes == list(LOCAL_SETTING_WRITES[: failure_index + 1])


def test_settings_save_targets_only_requested_file(monkeypatch):
    import config

    writes = []
    monkeypatch.setattr(
        config.File,
        "save",
        lambda file_ref, data: writes.append(file_ref.name) or True,
    )
    monkeypatch.setattr(config.File, "exists", lambda file_ref: True)
    monkeypatch.setattr(config, "write_generation_manifest", lambda: None)

    settings = object.__new__(config.Settings)
    settings.DEPLOY = {"runtime": "python314"}
    settings.APP = {"APP_NAME": "Targeted Save"}
    settings.DEV = {}
    settings.NODE = {"version": "1.0.0"}
    settings.INDEX = {"indexes": []}
    settings.MANIFEST = {"name": "Targeted Save"}
    settings.GCLOUD_CONFIG = {"PROJECT": "project-1"}
    settings.DEV_CONFIG = {"SERVER_PORT": "5050"}
    settings.TEST_CONFIG = {"SERVER_PORT": "5000"}

    assert settings.save(config.File.APP_SETTINGS_YAML) == (
        "APP_SETTINGS_YAML",
    )
    assert writes == ["APP_SETTINGS_YAML"]


# @matrix setup : operation-journal process-lock recovery
def test_setup_process_lock_and_operation_journal(tmp_path, capsys):
    lock_path = tmp_path / "installer.lock"
    journal_path = tmp_path / "operation.json"

    with SetupProcessLock(lock_path):
        with pytest.raises(SetupError, match="already running"):
            SetupProcessLock(lock_path).acquire()

    with pytest.raises(SetupError, match="interrupted"):
        with setup_operation(
            "install",
            ["jobs"],
            lock_path=lock_path,
            journal_path=journal_path,
        ):
            record_step("enable API")
            record_mutation(
                "enable API",
                action="enabled",
                resource="provider-api",
                identifier="tasks.googleapis.com",
            )
            raise KeyboardInterrupt

    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["status"] == "interrupted"
    assert journal["last_step"] == "enable API"
    assert journal["mutations"] == [
        {
            "action": "enabled",
            "identifier": "tasks.googleapis.com",
            "resource": "provider-api",
            "step": "enable API",
        }
    ]
    assert "secret" not in json.dumps(journal).casefold()
    output = capsys.readouterr().out
    assert "Completed remote mutations:" in output
    assert "tasks.googleapis.com" in output
    assert "Run ./setup.sh jobs again to resume." in output
