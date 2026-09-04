"""Tooling tests for setup runtime, package, and resource helpers."""

import ast
import builtins
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import runpy
import subprocess
import sys
import types

import pytest

from installer.errors import (
    ProviderError,
    ProviderConflict,
    ProviderInvalidInput,
    ProviderNotFound,
    ProviderPermissionDenied,
    ProviderTermsNotAccepted,
    ProviderTimeout,
    ProviderTransientError,
    SetupCancelled,
    SetupError,
    classify_provider_error,
    google_service_terms_error,
    retry_provider_call,
)
from testing.utility.setup_fakes import (
    SpinnerRecorder,
    completed_process,
    spinner_factory,
)

pytestmark = pytest.mark.tooling


# @matrix setup : classification errors exit-status provider-errors retry timeout
def test_setup_error_classification_and_retry_contract():
    class StatusError(RuntimeError):
        def __init__(self, status):
            self.status_code = status
            super().__init__(f"status {status}")

    assert isinstance(classify_provider_error(StatusError(404)), ProviderNotFound)
    assert isinstance(
        classify_provider_error(StatusError(403)),
        ProviderPermissionDenied,
    )
    assert isinstance(
        classify_provider_error(StatusError(400)),
        ProviderInvalidInput,
    )
    assert isinstance(classify_provider_error(StatusError(409)), ProviderConflict)
    assert isinstance(
        classify_provider_error(StatusError(503)),
        ProviderTransientError,
    )
    service_disabled = StatusError(403)
    service_disabled.args = ("SERVICE_DISABLED",)
    assert isinstance(
        classify_provider_error(service_disabled),
        ProviderTransientError,
    )
    assert isinstance(
        classify_provider_error(subprocess.TimeoutExpired(["gcloud"], 1)),
        ProviderTimeout,
    )
    cancelled = SetupCancelled("operator cancelled")
    assert classify_provider_error(cancelled) is cancelled
    stderr_only = subprocess.CalledProcessError(1, ["gcloud", "describe"])
    assert isinstance(
        classify_provider_error(
            stderr_only,
            message="gcloud describe failed: NOT_FOUND: database does not exist",
        ),
        ProviderNotFound,
    )
    assert isinstance(
        classify_provider_error(
            stderr_only,
            message="gcloud create failed: ALREADY_EXISTS: database is being created",
        ),
        ProviderConflict,
    )
    maps_terms_detail = (
        "FAILED_PRECONDITION: The terms of service 'maps' must be accepted. "
        "tos_id=maps reason: UREQ_TOS_NOT_ACCEPTED Help Token: secret-token"
    )
    maps_terms = google_service_terms_error(
        maps_terms_detail,
        account="installer@example.com",
    )
    assert isinstance(maps_terms, ProviderTermsNotAccepted)
    assert str(maps_terms) == (
        "Google Maps Platform terms have not been accepted for 'installer@example.com'."
    )
    assert "https://console.developers.google.com/terms/maps" in (
        maps_terms.repair_action
    )
    assert "secret-token" not in str(maps_terms)
    assert isinstance(
        classify_provider_error(RuntimeError(maps_terms_detail)),
        ProviderTermsNotAccepted,
    )

    calls = []
    delays = []

    def eventually_available():
        calls.append(True)
        if len(calls) < 3:
            raise StatusError(503)
        return "ready"

    assert (
        retry_provider_call(
            eventually_available,
            description="probe",
            attempts=3,
            delays=(1, 2),
            sleep=delays.append,
        )
        == "ready"
    )
    assert delays == [1, 2]

    with pytest.raises(ProviderPermissionDenied):
        retry_provider_call(
            lambda: (_ for _ in ()).throw(StatusError(403)),
            description="permission probe",
            sleep=lambda delay: pytest.fail("permission errors must not retry"),
        )


def _fake_formatter(spinner=None):
    recorder = spinner or SpinnerRecorder()
    return types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            success=lambda message: message,
            info=lambda message: message,
            warning=lambda message: message,
            error=lambda message, error=None: message,
            ok_glyph="[OK]",
            fail_glyph="[X]",
            yaspin=spinner_factory(recorder),
        )
    )


def _fake_settings(app=None, gcloud=None, deploy=None, node=None):
    saves = []
    settings = types.SimpleNamespace(
        APP=app or {},
        DEPLOY=deploy or {},
        DEV={},
        GCLOUD_CONFIG=gcloud or {},
        MANIFEST={},
        NODE=node or {},
        save=lambda: saves.append(True),
    )
    settings._saves = saves
    return settings


def _load_config_constants():
    constants_path = Path(__file__).resolve().parents[2] / "config" / "constants.py"
    spec = importlib.util.spec_from_file_location(
        "_lagniappe_test_config_constants", constants_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _isolate_cli_routing_prerequisites(monkeypatch):
    """Keep command-routing tests independent of the host setup envelope."""
    import installer as setup_pkg
    from installer import package_install, state

    monkeypatch.setattr(setup_pkg, "verify_setup_runtime", lambda: None)
    monkeypatch.setattr(package_install, "ensure_pip_is_available", lambda: None)
    monkeypatch.setattr(package_install, "ensure_setup_dependencies", lambda: None)
    monkeypatch.setattr(
        state,
        "setup_operation",
        lambda *_args, **_kwargs: nullcontext(),
    )


def test_deferred_jobs_cli_verifies_installation_before_provisioning(monkeypatch):
    from runner import gcloud as runner_gcloud

    _isolate_cli_routing_prerequisites(monkeypatch)
    events = []
    verify_module = types.ModuleType("installer.verify")
    verify_module.prepare_existing_installation = lambda: events.append("verify")
    gcloud_module = types.ModuleType("installer.gcloud")
    gcloud_module.create_deferred_job_reconciler = lambda: (
        events.append("provision") or True
    )
    monkeypatch.setitem(sys.modules, "installer.verify", verify_module)
    monkeypatch.setitem(sys.modules, "installer.gcloud", gcloud_module)
    monkeypatch.setattr(
        runner_gcloud,
        "activate_repository_gcloud",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(sys, "argv", ["-m installer", "jobs"])

    setup_path = Path(__file__).resolve().parents[2] / "installer" / "__main__.py"
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(setup_path, run_name="__main__")

    assert exit_info.value.code == 0
    assert events == ["verify", "provision"]


def test_security_cli_routes_to_security_configuration(monkeypatch):
    from runner import gcloud as runner_gcloud

    _isolate_cli_routing_prerequisites(monkeypatch)
    events = []
    security_module = types.ModuleType("installer.security")
    security_module.configure_security = lambda: events.append("security") or 0
    monkeypatch.setitem(sys.modules, "installer.security", security_module)
    monkeypatch.setattr(
        runner_gcloud,
        "activate_repository_gcloud",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(sys, "argv", ["-m installer", "security"])

    setup_path = Path(__file__).resolve().parents[2] / "installer" / "__main__.py"
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(setup_path, run_name="__main__")

    assert exit_info.value.code == 0
    assert events == ["security"]


def test_development_cli_routes_to_development_setup(monkeypatch):
    from runner import gcloud as runner_gcloud

    _isolate_cli_routing_prerequisites(monkeypatch)
    events = []
    development_module = types.ModuleType("installer.development")
    development_module.setup_development = lambda: events.append("development") or 0
    monkeypatch.setitem(sys.modules, "installer.development", development_module)
    monkeypatch.setattr(
        runner_gcloud,
        "activate_repository_gcloud",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(sys, "argv", ["-m installer", "development"])

    setup_path = Path(__file__).resolve().parents[2] / "installer" / "__main__.py"
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(setup_path, run_name="__main__")

    assert exit_info.value.code == 0
    assert events == ["development"]


# @matrix setup : authentication-email cli deploy gmail replacement smtp
def test_email_cli_replaces_gmail_without_custom_domain(monkeypatch):
    import config
    import installer as setup_pkg
    from installer import auth_email, utils, verify

    events = []
    settings = _fake_settings(
        app={
            "AUTH_EMAIL_CONFIG": {
                "provider": "smtp",
                "service": "Gmail",
            },
            "CUSTOM_DOMAIN": "",
        }
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        verify,
        "prepare_existing_installation",
        lambda: events.append("verify"),
    )
    monkeypatch.setattr(
        auth_email,
        "setup_auth_email",
        lambda *, replace=False: events.append(("gmail", replace)) or True,
    )
    monkeypatch.setattr(utils, "deploy_to_app_engine", lambda: events.append("deploy"))
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert auth_email.configure_auth_email() == 0
    assert events == ["verify", ("gmail", True), "deploy"]


# @matrix setup : authentication-email cli custom-domain deploy smtp
def test_email_cli_configures_and_optionally_deploys(monkeypatch):
    import config
    import installer as setup_pkg
    from installer import auth_email, utils, verify

    events = []
    settings = _fake_settings(
        app={
            "CUSTOM_DOMAIN": "app.example.test",
        }
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        verify,
        "prepare_existing_installation",
        lambda: events.append("verify"),
    )
    monkeypatch.setattr(
        auth_email,
        "_setup_provider_auth_email",
        lambda: events.append("configure") or True,
    )
    monkeypatch.setattr(
        utils,
        "deploy_to_app_engine",
        lambda: events.append("deploy"),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert auth_email.configure_auth_email() == 0
    assert events == ["verify", "configure", "deploy"]


# @matrix setup : cli deploy redis-tls
def test_security_cli_configures_and_optionally_deploys_redis_tls(monkeypatch):
    import config
    import installer as setup_pkg
    from installer import redis as redis_setup
    from installer import security
    from installer import utils

    events = []
    settings = _fake_settings(
        app={
            "REDIS_HOST": "redis-123.redislabs.com",
            "REDIS_PORT": 12345,
            "REDIS_PASSWORD": "secret",
            "REDIS_TLS": False,
        }
    )
    answers = iter(["", ""])

    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        security,
        "prepare_existing_installation",
        lambda: events.append("verify"),
    )
    monkeypatch.setattr(
        redis_setup, "_enable_redis_tls", lambda: events.append("enable") or True
    )
    monkeypatch.setattr(utils, "deploy_to_app_engine", lambda: events.append("deploy"))
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert security.configure_security() == 0
    assert events == ["verify", "enable", "deploy"]


@pytest.fixture(autouse=True)
def fake_yaspin_module(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "yaspin", types.SimpleNamespace(yaspin=spinner_factory())
    )


def _install_cloud_module(monkeypatch, name, module):
    google = sys.modules.get("google") or types.ModuleType("google")
    cloud = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    setattr(google, "cloud", cloud)
    setattr(cloud, name, module)
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, f"google.cloud.{name}", module)


def _install_api_core_exceptions(monkeypatch, not_found):
    api_core = sys.modules.get("google.api_core") or types.ModuleType("google.api_core")
    exceptions = types.SimpleNamespace(NotFound=not_found)
    api_core.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "google.api_core", api_core)
    monkeypatch.setitem(sys.modules, "google.api_core.exceptions", exceptions)


def _install_config_package(monkeypatch, constants, settings=None):
    config_module = types.ModuleType("config")
    config_module.__path__ = ["config"]
    config_module.constants = constants
    if settings is not None:
        config_module.SETTINGS = settings
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.delitem(sys.modules, "config.deployment", raising=False)
    monkeypatch.delitem(sys.modules, "config.ai_settings", raising=False)
    monkeypatch.delitem(sys.modules, "config.ai_models", raising=False)
    return config_module


@pytest.fixture(autouse=True)
def isolated_config_package(monkeypatch):
    """Keep this setup test module independent from real local settings."""
    return _install_config_package(
        monkeypatch,
        _load_config_constants(),
        settings=_fake_settings(),
    )


# @matrix setup : development prerequisites
def test_development_setup_requires_existing_installation(monkeypatch, capsys):
    from installer import development

    monkeypatch.setattr(development, "_in_virtualenv", lambda: True)
    monkeypatch.setattr(
        development,
        "_missing_installation_files",
        lambda: ["DEV_YAML", "APP_SETTINGS_YAML"],
    )

    assert development.setup_development() == 1
    output = capsys.readouterr().out
    assert "./setup.sh" in output
    assert " first." in output
    assert "DEV_YAML, APP_SETTINGS_YAML" in output


# @matrix setup : development frontend-build idempotence package-install
def test_development_setup_is_additive_and_idempotent(monkeypatch):
    from installer import development

    calls = []
    monitoring = []
    cloud_events = []
    optional_module = types.ModuleType("installer.optional")
    optional_module.configure_development_error_monitoring = lambda: (
        monitoring.append(True) or True
    )
    monkeypatch.setitem(sys.modules, "installer.optional", optional_module)
    verify_module = types.ModuleType("installer.verify")
    verify_module.prepare_existing_installation = lambda: cloud_events.append(
        ("verify", {})
    )
    monkeypatch.setitem(sys.modules, "installer.verify", verify_module)
    gcloud_module = types.ModuleType("installer.gcloud")
    gcloud_module.configure_storage_buckets = lambda **kwargs: cloud_events.append(
        ("buckets", kwargs)
    )
    monkeypatch.setitem(sys.modules, "installer.gcloud", gcloud_module)
    monkeypatch.setattr(development, "_in_virtualenv", lambda: True)
    monkeypatch.setattr(development, "_missing_installation_files", lambda: [])
    monkeypatch.setattr(development, "NODE_CLI", "/tools/node")
    monkeypatch.setattr(development, "NPM_CLI", "/tools/npm")
    monkeypatch.setattr(development, "_installed_node_version", lambda: "v26.5.0")
    monkeypatch.setattr(
        development,
        "_run_command",
        lambda label, command: calls.append((label, command)) or True,
    )

    assert development.setup_development() == 0
    assert development.setup_development() == 0

    expected_commands = [
        [
            sys.executable,
            "-m",
            "runner.uv_bootstrap",
            "install",
            "--non-interactive",
        ],
        [sys.executable, "-m", "runner.uv_bootstrap", "check"],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            "requirements-dev.txt",
        ],
        ["/tools/npm", "ci"],
        [sys.executable, "-m", "playwright", "install", "chromium"],
        ["/tools/npm", "run", "dev"],
    ]
    assert [command for _, command in calls] == expected_commands * 2
    assert monitoring == [True, True]
    assert cloud_events == [
        ("verify", {}),
        (
            "buckets",
            {"include_production": False, "include_test": True},
        ),
        ("verify", {}),
        (
            "buckets",
            {"include_production": False, "include_test": True},
        ),
    ]


# @matrix setup : development portability windows
def test_development_setup_directs_native_windows_to_wsl(monkeypatch, capsys):
    from installer import development

    monkeypatch.setattr(development, "_native_windows", lambda: True)

    assert development.setup_development() == 1
    output = " ".join(capsys.readouterr().out.split())
    assert "Native Windows development is not supported" in output
    assert "WSL2" in output
    assert "installation, recovery, update, and deployment only" in output


# @matrix setup : development node-version
def test_development_setup_validates_node_range():
    from installer.development import (
        APP_ROOT,
        NODE_ENGINE_RANGE,
        node_version_supported,
    )

    for supported in ("v22.18.0", "22.20.1", "24.11.0", "v26.5.0"):
        assert node_version_supported(supported)
    for unsupported in (
        "22.17.9",
        "v23.0.0",
        "24.10.9",
        "24.11.0junk",
        "not-a-version",
    ):
        assert not node_version_supported(unsupported)

    package = json.loads((APP_ROOT / "package.json").read_text(encoding="utf-8"))
    pinned = (APP_ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
    assert package["engines"]["node"] == NODE_ENGINE_RANGE
    assert node_version_supported(pinned)


# @matrix setup : privacy-consent rerun sentry-destination
def test_error_monitoring_supports_maintainer_or_operator_sentry(monkeypatch, capsys):
    import config
    from installer import optional

    constants = types.SimpleNamespace(
        SENTRY_DSN="https://maintainer@errors.example.test/1",
        SENTRY_JS_DSN="https://maintainer-js@errors.example.test/2",
    )
    settings = _fake_settings()

    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(optional, "constants", constants)
    monkeypatch.setattr(optional, "FORMATTER", _fake_formatter())
    answers = iter(["y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    optional.setup_error_monitoring()

    assert settings.APP["CAPTURE_ERRORS"] == "True"
    assert settings.APP["SENTRY_DSN"] == constants.SENTRY_DSN
    assert settings.APP["SENTRY_JS_DSN"] == constants.SENTRY_JS_DSN
    assert "https://lagniappe.site/reporting_privacy" in capsys.readouterr().out

    settings.APP.pop("SENTRY_JS_DSN")
    saves_before = len(settings._saves)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    optional.setup_error_monitoring()

    assert settings.APP["SENTRY_JS_DSN"] == constants.SENTRY_JS_DSN
    assert len(settings._saves) == saves_before + 1

    settings.APP.clear()
    operator_dsn = "https://operator@errors.example.test/42"
    answers = iter(["n", "y", operator_dsn])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    optional.setup_error_monitoring()

    assert settings.APP["CAPTURE_ERRORS"] == "True"
    assert settings.APP["SENTRY_DSN"] == operator_dsn
    assert settings.APP["SENTRY_JS_DSN"] == operator_dsn

    saves_before = len(settings._saves)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    optional.setup_error_monitoring()
    assert settings.APP["CAPTURE_ERRORS"] == "True"
    assert settings.APP["SENTRY_DSN"] == operator_dsn
    assert settings.APP["SENTRY_JS_DSN"] == operator_dsn
    assert len(settings._saves) == saves_before


# @matrix setup : default-disabled privacy-consent sentry-destination
def test_disabled_error_monitoring_offers_to_enable(monkeypatch, capsys):
    import config
    from installer import optional

    constants = types.SimpleNamespace(
        SENTRY_DSN="https://maintainer@errors.example.test/1",
        SENTRY_JS_DSN="https://maintainer-js@errors.example.test/2",
    )
    settings = _fake_settings(app={"CAPTURE_ERRORS": "False"})
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(optional, "constants", constants)
    monkeypatch.setattr(optional, "FORMATTER", _fake_formatter())
    prompts = []
    answers = iter(["y", "y"])
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or next(answers),
    )

    optional.setup_error_monitoring()

    assert prompts[0] == "Would you like to enable error monitoring? [y/N]: "
    assert settings.APP == {
        "CAPTURE_ERRORS": "True",
        "SENTRY_DSN": constants.SENTRY_DSN,
        "SENTRY_JS_DSN": constants.SENTRY_JS_DSN,
    }
    assert "Error Monitoring & Crash Reporting" in capsys.readouterr().out


# @matrix ai-observability setup : privacy-consent rerun settings-save
def test_ai_observability_is_an_explicit_preserved_setup_choice(
    monkeypatch,
    capsys,
):
    import config
    import installer as setup_pkg
    from installer import optional

    settings = _fake_settings()
    monkeypatch.setattr(config, "SETTINGS", settings)
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            info=lambda message: f"<info>{message}</info>",
            success=lambda message: f"<success>{message}</success>",
        )
    )
    monkeypatch.setattr(optional, "FORMATTER", formatter)
    monkeypatch.setattr(
        optional,
        "wrap_text",
        lambda message: setup_pkg.wrap_text(message, width=53),
    )
    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "y",
    )

    assert optional.configure_ai_observability()
    assert settings.APP["AI_OBSERVABILITY"] is True
    first_output = capsys.readouterr().out
    visible_output = (
        first_output.replace("<info>", "")
        .replace("</info>", "")
        .replace("<success>", "")
        .replace("</success>", "")
    )
    output_lines = visible_output.splitlines()
    assert all(len(line) <= 53 for line in output_lines)
    assert any("token totals," in line for line in output_lines)
    assert "<info>Optional AI Generation Observability</info>" in first_output
    assert "<success>AI generation observability enabled.</success>" in first_output
    assert prompts == ["\n<info>Enable AI generation observability? [y/N]: </info>"]

    prompts.clear()
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "",
    )
    assert optional.configure_ai_observability()
    assert settings.APP["AI_OBSERVABILITY"] is True
    preserved_output = capsys.readouterr().out
    assert (
        "<info>AI generation observability is currently enabled.</info>"
        in preserved_output
    )
    assert "<success>Existing AI observability choice preserved.</success>" in (
        preserved_output
    )
    assert prompts == ["<info>Keep this AI observability choice? [Y/n]: </info>"]


# @matrix setup : google-oauth optional rerun settings-save
def test_google_signin_is_an_explicit_preserved_setup_choice(monkeypatch, capsys):
    import config
    from installer import admin

    settings = _fake_settings()
    monkeypatch.setattr(config, "SETTINGS", settings)
    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "n",
    )

    assert admin.configure_google_signin_choice() is False
    assert settings.APP["GOOGLE_SIGNIN_ENABLED"] is False
    assert prompts == ["Enable Google sign-in? [Y/n]: "]

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: pytest.fail("saved choice must not be prompted again"),
    )
    assert admin.configure_google_signin_choice() is False
    assert "Google sign-in is disabled" in capsys.readouterr().out


# @matrix ai-observability setup : ai-cache privacy-consent settings-save
def test_ai_setup_mode_configures_observability(monkeypatch):
    import config
    from installer import ai

    settings = _fake_settings()
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(ai, "prepare_existing_installation", lambda: None)
    monkeypatch.setattr(ai, "FORMATTER", _fake_formatter())
    answers = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert ai.configure_ai() == 0
    assert settings.APP["AI_OBSERVABILITY"] is True
    assert len(settings._saves) == 1


# @matrix setup : credential-parsing redis validation
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "redis-cli -u "
            "'redis://default:p%40ss%3Aword@"
            "redis-11826.c238.us-central1-2.gce.redns.redis-cloud.com:11826'",
            {
                "host": ("redis-11826.c238.us-central1-2.gce.redns.redis-cloud.com"),
                "port": 11826,
                "password": "p@ss:word",
            },
        ),
        (
            "Copied connection: redis-cli --uri "
            "rediss://named-user:secret@cache.example.test:6380/7",
            {
                "host": "cache.example.test",
                "port": 6380,
                "password": "secret",
            },
        ),
        (
            "redis-cli -h cache.example.test -p 6381 -a secret",
            {
                "host": "cache.example.test",
                "port": 6381,
                "password": "secret",
            },
        ),
        (
            "redis://default:secret@cache.example.test:6379",
            {
                "host": "cache.example.test",
                "port": 6379,
                "password": "secret",
            },
        ),
    ],
)
def test_redis_cli_command_parser_extracts_connection_details(command, expected):
    from installer import redis as redis_setup

    assert redis_setup._parse_redis_cli_command(command) == expected
    assert redis_setup._is_redis_cli_command(command)


# @matrix setup : credential-parsing redis validation
@pytest.mark.parametrize(
    "command",
    [
        "redis-cli PING",
        "redis-cli -u redis://default:secret@redis-123.redislabs.com",
        "redis-cli -u https://default:secret@redis.example.com:12345",
        "redis-cli -u redis://default:secret@:12345",
        "redis-cli -u redis://default:******@redis-123.redislabs.com:12345",
    ],
)
def test_redis_cli_command_parser_rejects_invalid_commands(command):
    from installer import redis as redis_setup

    with pytest.raises(ValueError):
        redis_setup._parse_redis_cli_command(command)
    assert not redis_setup._is_redis_cli_command(command)


# @matrix setup : cancellation credential-parsing interactive-input redis
def test_redis_cli_command_uses_visible_standard_input(monkeypatch, capsys):
    import installer as setup_pkg
    from installer import redis as redis_setup

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    prompts = []
    command = "redis-cli -u redis://default:redis-secret@redis-123.redislabs.com:12345"
    answers = iter(["not a Redis connection", command])
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or next(answers),
    )

    assert redis_setup._get_redis_connection_details() == {
        "host": "redis-123.redislabs.com",
        "port": 12345,
        "password": "redis-secret",
    }
    assert prompts == ["Paste copied Redis CLI command (x to exit): "] * 2
    output = capsys.readouterr().out
    assert "find Access, click Connect, expand Redis CLI, click Copy" in output
    assert "begin with 'redis-cli' or 'redis:'" in output


# @matrix setup : browser operator-guidance plan-selection provider-region redis redis-tls
def test_redis_cloud_instructions_open_console_and_locate_credentials(
    monkeypatch,
    capsys,
):
    from config import SETTINGS
    import installer as setup_pkg
    from installer import redis as redis_setup

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(redis_setup, "FORMATTER", _fake_formatter())
    monkeypatch.setitem(SETTINGS.APP, "RESOURCE_REGION", "us-central1")
    opened = []
    monkeypatch.setattr(
        redis_setup.webbrowser,
        "open_new_tab",
        lambda url: opened.append(url) or True,
    )

    redis_setup.redis_cloud_instructions()

    assert opened == [redis_setup.REDIS_CLOUD_CONSOLE_URL]
    output = " ".join(capsys.readouterr().out.split())
    assert "Try 30 MB for free" in output
    assert "sufficient for the rehearsal" in output
    assert "TLS option is unavailable on the free plan" in output
    assert "paid Essentials or Pro plan" in output
    assert "Cloud vendor 'Google Cloud'" in output
    assert "Region 'us-central1'" in output
    assert "existing database is suitable only when" in output
    assert "find Access on that same database details page" in output
    assert "connection panel, expand Redis CLI" in output
    assert "blue Copy button beneath the redis-cli command" in output
    assert "Return to setup and paste the complete copied command" in output
    assert "Keep the database details page open" in output


# @matrix setup : interactive-input operator-guidance redis
def test_redis_eviction_policy_instructions_require_confirmation(
    monkeypatch,
    capsys,
):
    import installer as setup_pkg
    from installer import redis as redis_setup

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(redis_setup, "FORMATTER", _fake_formatter())
    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "",
    )

    redis_setup.eviction_policy_instructions()

    output = " ".join(capsys.readouterr().out.split())
    assert "Performance & Availability → Data eviction policy" in output
    assert "select volatile-ttl" in output
    assert "only pending until you click 'Review changes'" in output
    assert "confirmation modal" in output
    assert "'Confirm' or 'Confirm & pay'" in output
    assert "Wait for the pending-change indicator to clear" in output
    assert "displayed Data eviction policy is still volatile-ttl" in output
    assert prompts == [
        "\nPress Enter only after Redis Cloud confirms the eviction policy..."
    ]


# @matrix setup : failure-isolation redis retry rollback settings-save
def test_setup_redis_clears_failed_credentials_and_retries(
    monkeypatch,
    capsys,
):
    import installer as setup_pkg
    from installer import redis as redis_setup

    settings = _fake_settings()
    _install_config_package(
        monkeypatch,
        _load_config_constants(),
        settings=settings,
    )
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(redis_setup, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(redis_setup, "redis_cloud_instructions", lambda: None)
    monkeypatch.setattr(redis_setup, "eviction_policy_instructions", lambda: None)
    monkeypatch.setattr(
        redis_setup,
        "_offer_redis_tls_for_fresh_install",
        lambda: None,
    )

    connections = iter(
        [
            {
                "host": "redis-111.redislabs.com",
                "port": 1111,
                "password": "wrong-password",
            },
            {
                "host": "redis-222.redislabs.com",
                "port": 2222,
                "password": "correct-password",
            },
        ]
    )
    connection_calls = []

    def get_connection():
        if connection_calls:
            assert not any(
                key in settings.APP
                for key in ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD")
            )
        connection_calls.append(True)
        return next(connections)

    monkeypatch.setattr(
        redis_setup,
        "_get_redis_connection_details",
        get_connection,
    )

    attempts = []

    def probe_connection():
        attempts.append(
            (
                settings.APP["REDIS_HOST"],
                settings.APP["REDIS_PORT"],
                settings.APP["REDIS_PASSWORD"],
            )
        )
        if len(attempts) == 1:
            raise ProviderError("Redis connection validation failed.")
        return True

    monkeypatch.setattr(redis_setup, "test_redis_connection", probe_connection)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert redis_setup.setup_redis()
    assert attempts == [
        ("redis-111.redislabs.com", 1111, "wrong-password"),
        ("redis-222.redislabs.com", 2222, "correct-password"),
    ]
    assert settings.APP == {
        "REDIS_HOST": "redis-222.redislabs.com",
        "REDIS_PORT": 2222,
        "REDIS_PASSWORD": "correct-password",
        "REDIS_TLS": False,
    }
    assert len(settings._saves) == 2
    output = capsys.readouterr().out
    assert "failed Redis connection details were cleared" in output


# @matrix setup : development privacy sentry-destination
def test_development_monitoring_rejects_maintainer_sentry(monkeypatch, capsys):
    import config
    from installer import optional

    constants = types.SimpleNamespace(
        SENTRY_DSN="https://maintainer@errors.example.test/1",
        SENTRY_JS_DSN="https://maintainer-js@errors.example.test/2",
    )
    settings = _fake_settings(
        app={"CAPTURE_ERRORS": "True", "SENTRY_DSN": constants.SENTRY_DSN}
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(optional, "constants", constants)
    operator_dsn = "https://operator@errors.example.test/42"
    answers = iter([constants.SENTRY_DSN, operator_dsn])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert optional.configure_development_error_monitoring()
    assert settings.APP == {
        "CAPTURE_ERRORS": "True",
        "SENTRY_DSN": operator_dsn,
        "SENTRY_JS_DSN": operator_dsn,
    }
    assert "That is the maintainer DSN" in capsys.readouterr().out

    settings.APP.update({"CAPTURE_ERRORS": "True", "SENTRY_DSN": constants.SENTRY_DSN})
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert optional.configure_development_error_monitoring()
    assert settings.APP == {"CAPTURE_ERRORS": "False"}


# @matrix setup : redis-connection redis-tls
def test_redis_connection_uses_shared_tls_settings_and_exits_on_failure(
    monkeypatch, tmp_path
):
    import config
    from config import redis as redis_config
    from installer import redis as redis_setup
    import redis as redis_pkg

    created_clients = []
    closed_clients = []
    install_requests = []

    class FakeRedis:
        def __init__(self, **kwargs):
            created_clients.append(kwargs)

        def ping(self):
            return True

        def close(self):
            closed_clients.append(self)

    import installer as setup_pkg

    monkeypatch.setattr(
        redis_setup,
        "install_if_missing",
        lambda *args, **kwargs: install_requests.append((args, kwargs)),
    )
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    settings = _fake_settings(
        app={
            "REDIS_HOST": "redis-123.redislabs.com",
            "REDIS_PORT": 12345,
            "REDIS_PASSWORD": "secret",
            "REDIS_TLS": False,
        }
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(redis_pkg, "Redis", FakeRedis)

    assert redis_setup.test_redis_connection()
    assert install_requests[-1] == (
        (
            "redis",
            "Python client library used to test the same TLS and authenticated "
            "connection as Lagniappe; this does not install a Redis server",
        ),
        {},
    )
    assert created_clients == [
        {
            "host": "redis-123.redislabs.com",
            "port": 12345,
            "password": "secret",
            "socket_timeout": 5,
        }
    ]
    assert len(closed_clients) == 1

    ca_bundle = tmp_path / "redis_ca.pem"
    ca_bundle.write_text("test CA bundle")
    monkeypatch.setattr(
        redis_config.ssl,
        "create_default_context",
        lambda **kwargs: types.SimpleNamespace(),
    )
    settings.APP.update(
        {
            "REDIS_TLS": True,
            "REDIS_CA_CERT": str(ca_bundle),
        }
    )

    assert redis_setup.test_redis_connection()
    assert created_clients[-1] == {
        "host": "redis-123.redislabs.com",
        "port": 12345,
        "password": "secret",
        "socket_timeout": 5,
        "ssl": True,
        "ssl_ca_certs": str(ca_bundle),
        "ssl_cert_reqs": "required",
        "ssl_check_hostname": True,
    }
    assert len(closed_clients) == 2

    class FailingRedis(FakeRedis):
        def ping(self):
            raise Exception("nope")

    monkeypatch.setattr(redis_pkg, "Redis", FailingRedis)
    with pytest.raises(ProviderError):
        redis_setup.test_redis_connection()


# @matrix setup : certificate-validation failure-isolation redis-tls settings-save
def test_redis_tls_enablement_uses_managed_ca(monkeypatch, tmp_path):
    import config
    from config import redis as redis_config
    import installer as setup_pkg
    from installer import redis as redis_setup

    target = tmp_path / "config" / "files" / "redis_ca.pem"
    target.parent.mkdir(parents=True)
    target.write_text("managed CA")
    settings = _fake_settings(
        app={
            "REDIS_HOST": "redis-123.redislabs.com",
            "REDIS_PORT": 12345,
            "REDIS_PASSWORD": "secret",
            "REDIS_TLS": False,
        }
    )

    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(redis_setup, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(redis_setup, "_managed_redis_ca_path", lambda: target)
    monkeypatch.setattr(
        redis_config.ssl,
        "create_default_context",
        lambda **kwargs: types.SimpleNamespace(),
    )
    monkeypatch.setattr(redis_setup, "test_redis_connection", lambda *a, **k: False)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert redis_setup._enable_redis_tls() is False
    assert settings.APP["REDIS_TLS"] is False
    assert "REDIS_CA_CERT" not in settings.APP
    assert settings._saves == []

    candidates = []
    monkeypatch.setattr(
        redis_setup,
        "test_redis_connection",
        lambda candidate, **kwargs: candidates.append(candidate) or True,
    )

    assert redis_setup._enable_redis_tls() is True
    assert candidates[-1]["REDIS_TLS"] is True
    assert candidates[-1]["REDIS_CA_CERT"] == str(target)
    assert settings.APP["REDIS_TLS"] is True
    assert settings.APP["REDIS_CA_CERT"] == "config/files/redis_ca.pem"
    assert len(settings._saves) == 1


# @matrix setup : certificate-validation missing-file operator-guidance redis-tls
def test_redis_tls_enablement_requires_managed_ca(monkeypatch, tmp_path, capsys):
    import config
    import installer as setup_pkg
    from installer import redis as redis_setup

    settings = _fake_settings(
        app={
            "REDIS_HOST": "redis-123.redislabs.com",
            "REDIS_PORT": 12345,
            "REDIS_PASSWORD": "secret",
            "REDIS_TLS": False,
        }
    )
    missing_ca = tmp_path / "config" / "files" / "redis_ca.pem"

    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(redis_setup, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(redis_setup, "_managed_redis_ca_path", lambda: missing_ca)
    monkeypatch.setattr(
        redis_setup,
        "test_redis_connection",
        lambda *args, **kwargs: pytest.fail("connection should not be attempted"),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert redis_setup._enable_redis_tls() is False
    assert settings.APP["REDIS_TLS"] is False
    assert "REDIS_CA_CERT" not in settings.APP
    assert settings._saves == []
    output = capsys.readouterr().out
    assert "HTTPS for the server-to-server connection" in output
    assert "password is still required for authentication" in output
    assert "Unzip the downloaded archive" in output
    assert "config/files/redis_ca.pem" in output


# @matrix setup : failure-isolation redis-tls rollback settings-save
def test_redis_tls_disablement_is_transactional(monkeypatch, tmp_path):
    import config
    from installer import redis as redis_setup

    target = tmp_path / "redis_ca.pem"
    target.write_text("retained CA")
    settings = _fake_settings(
        app={
            "REDIS_HOST": "redis-123.redislabs.com",
            "REDIS_PORT": 12345,
            "REDIS_PASSWORD": "secret",
            "REDIS_TLS": True,
            "REDIS_CA_CERT": "config/files/redis_ca.pem",
        }
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(redis_setup, "FORMATTER", _fake_formatter())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.setattr(redis_setup, "test_redis_connection", lambda *a, **k: False)

    assert redis_setup._disable_redis_tls() is False
    assert settings.APP["REDIS_TLS"] is True
    assert settings.APP["REDIS_CA_CERT"] == "config/files/redis_ca.pem"
    assert settings._saves == []

    candidates = []
    monkeypatch.setattr(
        redis_setup,
        "test_redis_connection",
        lambda candidate, **kwargs: candidates.append(candidate) or True,
    )
    assert redis_setup._disable_redis_tls() is True
    assert candidates[-1]["REDIS_TLS"] is False
    assert "REDIS_CA_CERT" not in candidates[-1]
    assert settings.APP["REDIS_TLS"] is False
    assert "REDIS_CA_CERT" not in settings.APP
    assert target.read_text() == "retained CA"
    assert len(settings._saves) == 1


# @matrix setup : deploy gcp-domain https managed-certificate provider-status retry success
def test_managed_certificate_waits_for_provider_then_reports_active(
    monkeypatch,
    capsys,
):
    from installer.domain import gcp as domain_gcp

    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(
            SETTINGS=_fake_settings(
                gcloud={
                    "PROJECT": "project-1",
                    "ACCOUNT": "owner@example.com",
                }
            )
        ),
    )
    pending_mapping = {
        "id": "app.example.com",
        "name": "apps/project-1/domainMappings/app.example.com",
        "sslSettings": {"pendingManagedCertificateId": "cert-pending"},
    }
    active_mapping = {
        "id": "app.example.com",
        "name": "apps/project-1/domainMappings/app.example.com",
        "sslSettings": {"certificateId": "cert-active"},
    }
    mapping_states = iter(
        [
            pending_mapping,
            pending_mapping,
            active_mapping,
            active_mapping,
        ]
    )
    gcloud_calls = []

    def fake_gcloud(arguments, **kwargs):
        gcloud_calls.append((arguments, kwargs))
        if "domain-mappings" in arguments:
            mapping = next(mapping_states)
            return [mapping] if "list" in arguments else mapping
        assert "ssl-certificates" in arguments
        return {"managedCertificate": {"status": "PENDING"}}

    delays = []
    monkeypatch.setattr(domain_gcp, "_run_gcloud_json", fake_gcloud)

    assert domain_gcp.wait_for_managed_certificate(
        "app.example.com",
        poll_delays=(0, 2, 3),
        sleep=delays.append,
    )

    assert delays == [2]
    assert gcloud_calls[0][0][:3] == ["app", "domain-mappings", "list"]
    assert "--project=project-1" in gcloud_calls[0][0]
    assert "--account=owner@example.com" in gcloud_calls[0][0]
    assert gcloud_calls[1][0][:3] == ["app", "domain-mappings", "describe"]
    assert gcloud_calls[2][0][:3] == ["app", "ssl-certificates", "describe"]
    assert "--project=project-1" in gcloud_calls[2][0]
    assert "--account=owner@example.com" in gcloud_calls[2][0]
    output = capsys.readouterr().out
    assert (
        "Managed TLS certificate cert-pending for https://app.example.com "
        "in Google Cloud project project-1 using owner@example.com: PENDING"
    ) in output
    assert "Managed TLS certificate active for https://app.example.com." in output
    assert "It may take up to an hour before the domain opens over HTTPS." in output
    assert "Checking the App Engine managed TLS certificate" not in output
    assert "Google's HTTPS frontend" not in output
    assert "Retrying in 3 seconds" not in output


# @matrix setup : managed-certificate retry timeout
def test_managed_certificate_default_polling_backs_off_without_extending_timeout():
    from installer.domain import gcp as domain_gcp

    assert domain_gcp.MANAGED_CERTIFICATE_POLL_DELAYS[:3] == (0, 30, 30)
    assert domain_gcp.MANAGED_CERTIFICATE_POLL_DELAYS[3:] == (60,) * 9
    assert sum(domain_gcp.MANAGED_CERTIFICATE_POLL_DELAYS) == 600


# @matrix setup : gcp-domain managed-certificate operator-guidance provider-failure
def test_managed_certificate_reports_permanent_provider_failure(monkeypatch):
    from installer.domain import gcp as domain_gcp

    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=_fake_settings(gcloud={"PROJECT": "project-1"})),
    )
    monkeypatch.setattr(
        domain_gcp,
        "_list_domain_mappings",
        lambda project, account=None: [
            {
                "id": "app.example.com",
                "name": "apps/project-1/domainMappings/app.example.com",
            }
        ],
    )
    monkeypatch.setattr(
        domain_gcp,
        "_get_domain_mapping",
        lambda project, domain, account=None: {
            "id": domain,
            "name": f"apps/{project}/domainMappings/{domain}",
            "sslSettings": {"pendingManagedCertificateId": "cert-failed"},
        },
    )
    monkeypatch.setattr(
        domain_gcp,
        "_get_ssl_certificate",
        lambda project, certificate, account=None: {
            "managedCertificate": {"status": "FAILED_PERMANENT"}
        },
    )

    with pytest.raises(ProviderError, match="permanently failed") as raised:
        domain_gcp.wait_for_managed_certificate(
            "app.example.com",
            poll_delays=(0,),
            sleep=lambda delay: pytest.fail("permanent failure must not retry"),
        )

    assert "DNS records and CAA" in raised.value.repair_action


# @matrix setup : gcp-domain incomplete-deployment managed-certificate timeout
def test_managed_certificate_timeout_keeps_deployment_incomplete(monkeypatch):
    from installer.domain import gcp as domain_gcp

    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=_fake_settings(gcloud={"PROJECT": "project-1"})),
    )
    monkeypatch.setattr(
        domain_gcp,
        "_list_domain_mappings",
        lambda project, account=None: [
            {
                "id": "app.example.com",
                "name": "apps/project-1/domainMappings/app.example.com",
            }
        ],
    )
    monkeypatch.setattr(
        domain_gcp,
        "_get_domain_mapping",
        lambda project, domain, account=None: {
            "id": domain,
            "name": f"apps/{project}/domainMappings/{domain}",
            "sslSettings": {"pendingManagedCertificateId": "cert-pending"},
        },
    )
    monkeypatch.setattr(
        domain_gcp,
        "_get_ssl_certificate",
        lambda project, certificate, account=None: {
            "managedCertificate": {"status": "FAILED_RETRYING_NOT_VISIBLE"}
        },
    )
    delays = []

    with pytest.raises(ProviderTimeout, match="Deployment succeeded") as raised:
        domain_gcp.wait_for_managed_certificate(
            "app.example.com",
            poll_delays=(0, 1),
            sleep=delays.append,
        )

    assert delays == [1]
    assert "FAILED_RETRYING_NOT_VISIBLE" in str(raised.value)
    assert "rerun setup" in raised.value.repair_action


# @matrix setup : account-project gcp-domain managed-certificate missing-resource
def test_managed_certificate_reports_missing_domain_mapping(monkeypatch):
    from installer.domain import gcp as domain_gcp

    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=_fake_settings(gcloud={"PROJECT": "project-1"})),
    )
    monkeypatch.setattr(
        domain_gcp,
        "_list_domain_mappings",
        lambda project, account=None: [],
    )

    with pytest.raises(ProviderNotFound, match="project project-1") as raised:
        domain_gcp.wait_for_managed_certificate(
            "app.example.com",
            poll_delays=(0,),
        )

    assert "Confirm account" in raised.value.repair_action
    assert "project project-1" in raised.value.repair_action


# @matrix setup : gcp-domain managed-certificate missing-resource reconciliation
def test_empty_mapping_list_creates_managed_mapping(monkeypatch):
    from installer.domain import gcp as domain_gcp

    sp = SpinnerRecorder()
    mapping = {
        "id": "app.example.com",
        "name": "apps/project-1/domainMappings/app.example.com",
        "sslSettings": {
            "sslManagementType": "AUTOMATIC",
            "pendingManagedCertificateId": "cert-pending",
        },
        "resourceRecords": [
            {
                "type": "CNAME",
                "name": "app",
                "rrdata": "ghs.googlehosted.com.",
            }
        ],
    }
    listed = iter([[], [mapping]])
    mutations = []
    monkeypatch.setattr(
        domain_gcp,
        "_list_domain_mappings",
        lambda project, account=None: next(listed),
    )
    monkeypatch.setattr(
        domain_gcp,
        "_get_domain_mapping",
        lambda project, domain, account=None: mapping,
    )
    monkeypatch.setattr(
        domain_gcp,
        "_run_gcloud_json",
        lambda arguments, **kwargs: mutations.append(arguments) or {},
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(
            SETTINGS=_fake_settings(
                gcloud={
                    "PROJECT": "project-1",
                    "ACCOUNT": "owner@example.com",
                }
            )
        ),
    )

    assert domain_gcp.create_gcp_domain_mapping("app.example.com", sp) == mapping
    assert mutations[0][:4] == [
        "app",
        "domain-mappings",
        "create",
        "app.example.com",
    ]
    assert "--certificate-management=automatic" in mutations[0]
    assert any("domain mapping created" in message for message in sp.messages)
    assert not any("domain mapping existing" in message for message in sp.messages)


# @matrix setup : gcp-domain idempotence managed-certificate reconciliation
def test_existing_domain_mapping_enables_managed_tls(monkeypatch):
    from installer.domain import gcp as domain_gcp

    sp = SpinnerRecorder()
    mapping_without_ssl = {
        "id": "app.example.com",
        "name": "apps/project-1/domainMappings/app.example.com",
        "resourceRecords": [
            {
                "type": "CNAME",
                "name": "app",
                "rrdata": "ghs.googlehosted.com.",
            }
        ],
    }
    managed_mapping = {
        **mapping_without_ssl,
        "sslSettings": {
            "sslManagementType": "AUTOMATIC",
            "pendingManagedCertificateId": "cert-pending",
        },
    }
    responses = iter(
        [
            [mapping_without_ssl],
            mapping_without_ssl,
            {},
            [managed_mapping],
            managed_mapping,
        ]
    )
    calls = []

    def fake_gcloud(arguments, **kwargs):
        calls.append(arguments)
        return next(responses)

    monkeypatch.setattr(domain_gcp, "_run_gcloud_json", fake_gcloud)
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(
            SETTINGS=_fake_settings(
                gcloud={
                    "PROJECT": "project-1",
                    "ACCOUNT": "owner@example.com",
                }
            )
        ),
    )

    assert (
        domain_gcp.create_gcp_domain_mapping("app.example.com", sp) == managed_mapping
    )
    assert calls[2][:4] == ["app", "domain-mappings", "update", "app.example.com"]
    assert "--certificate-management=automatic" in calls[2]
    assert "--project=project-1" in calls[2]
    assert "--account=owner@example.com" in calls[2]
    assert any("domain mapping updated" in message for message in sp.messages)
    assert any(
        "apps/project-1/domainMappings/app.example.com" in message
        for message in sp.messages
    )
    assert any("managed TLS AUTOMATIC" in message for message in sp.messages)
    assert any("certificate cert-pending" in message for message in sp.messages)


# @matrix setup : ai-cache gcp-domain idempotence provider-records
def test_gcp_domain_mapping_and_ai_cache_commands(monkeypatch):
    from installer import ai
    from installer.domain import gcp as domain_gcp

    sp = SpinnerRecorder()
    domain_calls = []
    mapping = {
        "id": "app.example.com",
        "name": "apps/project-1/domainMappings/app.example.com",
        "sslSettings": {
            "sslManagementType": "AUTOMATIC",
            "pendingManagedCertificateId": "cert-pending",
        },
        "resourceRecords": [
            {
                "type": "CNAME",
                "name": "app",
                "rrdata": "ghs.googlehosted.com.",
            }
        ],
    }

    def fake_domain_run(command, **kwargs):
        domain_calls.append(command)
        if "list" in command:
            prior_lists = sum("list" in call for call in domain_calls[:-1])
            payload = [] if prior_lists == 0 else [mapping]
            return completed_process(command, stdout=json.dumps(payload))
        if "create" in command:
            return completed_process(command, stdout="{}")
        return completed_process(command, stdout=json.dumps(mapping))

    monkeypatch.setattr(domain_gcp, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(domain_gcp.subprocess, "run", fake_domain_run)
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=_fake_settings(gcloud={"PROJECT": "project-1"})),
    )

    assert domain_gcp.create_gcp_domain_mapping("app.example.com", sp) == mapping
    assert domain_calls[0][:4] == [
        "/usr/bin/gcloud",
        "app",
        "domain-mappings",
        "list",
    ]
    assert domain_calls[1][:4] == [
        "/usr/bin/gcloud",
        "app",
        "domain-mappings",
        "create",
    ]
    assert "--certificate-management=automatic" in domain_calls[1]
    assert domain_calls[2][:4] == [
        "/usr/bin/gcloud",
        "app",
        "domain-mappings",
        "list",
    ]
    assert domain_calls[3][:4] == [
        "/usr/bin/gcloud",
        "app",
        "domain-mappings",
        "describe",
    ]
    first_run_call_count = len(domain_calls)
    assert domain_gcp.create_gcp_domain_mapping("app.example.com", sp) == mapping
    assert len(domain_calls) == first_run_call_count + 4
    assert not any(
        "create" in command for command in domain_calls[first_run_call_count:]
    )

    import requests

    ai_patch_calls = []

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    class FakeSession:
        def patch(self, url, headers=None, json=None, timeout=None):
            ai_patch_calls.append({"url": url, "json": json})
            return FakeResponse()

    monkeypatch.setattr(
        "installer.package_install.install_if_missing", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(ai, "_get_access_token", lambda: "token")
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    assert ai._configure_ai_cache(sp)
    assert ai_patch_calls == [
        {
            "url": "https://us-central1-aiplatform.googleapis.com/v1/projects/project-1/cacheConfig",
            "json": {
                "name": "projects/project-1/cacheConfig",
                "disableCache": True,
            },
        }
    ]


# @matrix setup : account-identity custom-domain interactive-input ownership
def test_domain_ownership_instructions_name_selected_gcloud_account(
    monkeypatch,
    capsys,
):
    import installer as setup_package
    from installer.domain import manual as domain_manual

    settings = _fake_settings(
        gcloud={"ACCOUNT": "installer@example.com"},
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    monkeypatch.setattr(setup_package, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(domain_manual, "FORMATTER", _fake_formatter())
    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "y",
    )

    assert domain_manual.confirm_domain_ownership("app.example.com")

    output = capsys.readouterr().out
    assert "installer@example.com" in output
    assert "signed in to that exact account" in output
    assert "confirm that account is an Owner" in output
    assert prompts == [
        "Has Google confirmed that installer@example.com owns app.example.com? [y/N]: "
    ]


# @matrix setup : cloudflare-api interactive-input least-privilege
def test_cloudflare_token_prompt_explains_dashboard_steps_and_scope(
    monkeypatch,
    capsys,
):
    from installer.domain import cloudflare

    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "scoped-token-" + ("a" * 20),
    )

    assert cloudflare.get_cloudflare_api_token() == ("scoped-token-" + ("a" * 20))

    output = " ".join(capsys.readouterr().out.split())
    assert cloudflare.CLOUDFLARE_API_TOKEN_URL in output
    assert "My Profile > API Tokens" in output
    assert "Select Create Token" in output
    assert "'Edit zone DNS' template" in output
    assert "Under Zone Resources" in output
    assert "Include > Specific zone" in output
    assert "Under Permissions" in output
    assert "Zone > DNS > Edit" in output
    assert "Select + Add more" in output
    assert "Zone > Zone > Read" in output
    assert "Do not select Edit for Zone" in output
    assert "both DNS:Edit and Zone:Read" in output
    assert "does not save it" in output
    assert "delete it from Cloudflare after setup" in output
    assert prompts == ["Cloudflare API token (x to cancel): "]

    monkeypatch.setattr("builtins.input", lambda prompt: "x")
    with pytest.raises(
        SetupCancelled,
        match="Cloudflare DNS setup cancelled",
    ):
        cloudflare.get_cloudflare_api_token()


# @matrix setup : cloudflare-dns custom-domain disabled-provider dns-only idempotence provider-records
def test_custom_domain_uses_provider_records_and_dns_only_cloudflare(monkeypatch):
    import installer as setup_package
    from installer import custom_domain
    from installer import domain
    from installer import identity

    mapping = {
        "id": "app.example.com",
        "resourceRecords": [
            {
                "type": "CNAME",
                "name": "app",
                "rrdata": "ghs.googlehosted.com.",
            }
        ],
    }
    zone = {
        "id": "zone-1",
        "name": "example.com",
        "account": {"id": "account-1"},
    }
    settings = _fake_settings()
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    monkeypatch.setattr(setup_package, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        domain,
        "explain_domain_setup",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(domain, "confirm_domain_ownership", lambda value: True)
    monkeypatch.setattr(
        domain,
        "create_gcp_domain_mapping",
        lambda value, spinner: mapping,
    )
    monkeypatch.setattr(
        domain,
        "get_cloudflare_api_token",
        lambda: "scoped-token-" + ("a" * 20),
    )
    monkeypatch.setattr(
        domain,
        "get_cloudflare_zone",
        lambda value, token: zone,
    )
    reconciled = []
    monkeypatch.setattr(
        domain,
        "reconcile_cloudflare_dns_records",
        lambda value, selected_zone, token, records: (
            reconciled.append((value, selected_zone, token, records)) or ["record-1"]
        ),
    )
    oauth_domains = []
    monkeypatch.setattr(
        domain,
        "update_oauth_redirect_uris",
        oauth_domains.append,
    )
    identity_urls = []
    monkeypatch.setattr(
        identity,
        "setup_identity_platform",
        lambda app_url=None: identity_urls.append(app_url) or True,
    )
    answers = iter(["app.example.com", "y", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert custom_domain._setup_custom_domain()
    assert reconciled == [
        (
            "app.example.com",
            zone,
            "scoped-token-" + ("a" * 20),
            mapping["resourceRecords"],
        )
    ]
    assert settings.APP["CUSTOM_DOMAIN"] == "app.example.com"
    assert settings.APP["CLOUDFLARE_ZONE_ID"] == "zone-1"
    assert settings.APP["CLOUDFLARE_ACCOUNT_ID"] == "account-1"
    assert identity_urls == ["https://app.example.com"]
    assert oauth_domains == ["app.example.com"]

    settings.APP["GOOGLE_SIGNIN_ENABLED"] = False
    identity_urls.clear()
    answers = iter(["no-google.example.com", "y"])

    assert custom_domain._setup_custom_domain()
    assert oauth_domains == ["app.example.com"]
    assert identity_urls == ["https://no-google.example.com"]


# @matrix setup : custom-domain idempotence manual-dns provider-records
def test_custom_domain_supports_manual_dns(monkeypatch, capsys):
    import installer as setup_package
    from installer import custom_domain
    from installer import domain
    from installer import identity
    from installer.domain import manual as domain_manual

    mapping = {
        "id": "app.example.com",
        "resourceRecords": [
            {
                "type": "CNAME",
                "name": "app",
                "rrdata": "ghs.googlehosted.com.",
            }
        ],
    }
    settings = _fake_settings(
        app={
            "CLOUDFLARE_ZONE_ID": "old-zone",
            "CLOUDFLARE_ACCOUNT_ID": "old-account",
        }
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    monkeypatch.setattr(setup_package, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(domain_manual, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        domain,
        "explain_domain_setup",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(domain, "confirm_domain_ownership", lambda value: True)
    monkeypatch.setattr(
        domain,
        "create_gcp_domain_mapping",
        lambda value, spinner: mapping,
    )
    monkeypatch.setattr(
        domain,
        "get_cloudflare_api_token",
        lambda: pytest.fail("Cloudflare must remain optional"),
    )
    monkeypatch.setattr(
        domain,
        "update_oauth_redirect_uris",
        lambda value: pytest.fail("Fresh installation must defer OAuth configuration"),
    )
    identity_urls = []
    monkeypatch.setattr(
        identity,
        "setup_identity_platform",
        lambda app_url=None: identity_urls.append(app_url) or True,
    )
    answers = iter(["app.example.com", "n", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert custom_domain._setup_custom_domain(configure_auth=False)
    output = capsys.readouterr().out
    assert "CNAME" in output
    assert "app" in output
    assert "ghs.googlehosted.com." in output
    assert settings.APP["CUSTOM_DOMAIN"] == "app.example.com"
    assert settings.APP["GOOGLE_LOGIN_URI"] == (
        "https://app.example.com/users/google-signin"
    )
    assert "CLOUDFLARE_ZONE_ID" not in settings.APP
    assert "CLOUDFLARE_ACCOUNT_ID" not in settings.APP
    assert identity_urls == []


# @matrix setup : branch git-upgrade local-change-report
def test_upgrade_repository_preserves_report_before_branch_reset(
    monkeypatch,
    tmp_path,
):
    import installer as setup_pkg
    from installer import upgrade

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(upgrade, "GIT_CLI", "git")
    monkeypatch.setattr(upgrade, "REPOSITORY_ROOT", tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command == ["git", "status", "--porcelain"]:
            return completed_process(
                command,
                stdout=" M installer/ai.py\n?? notes.txt\n",
            )
        if command == ["git", "diff", "--stat"]:
            return completed_process(
                command,
                stdout=" installer/ai.py | 2 +-\n",
            )
        if command == ["git", "diff"]:
            return completed_process(
                command,
                stdout="diff --git a/installer/ai.py\n",
            )
        if command == ["git", "diff", "--cached"]:
            return completed_process(command, stdout="")
        if command in (
            ["git", "fetch", "--all"],
            ["git", "reset", "--hard", "origin/release/candidate"],
        ):
            return completed_process(command)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(upgrade.subprocess, "run", fake_run)
    spinner = SpinnerRecorder()

    assert upgrade._update_repository(spinner, branch="release/candidate")
    assert [command for command, _kwargs in calls] == [
        ["git", "status", "--porcelain"],
        ["git", "diff", "--stat"],
        ["git", "diff"],
        ["git", "diff", "--cached"],
        ["git", "fetch", "--all"],
        ["git", "reset", "--hard", "origin/release/candidate"],
    ]
    assert all(kwargs["cwd"] == tmp_path for _command, kwargs in calls)
    report_path = next((tmp_path / "reports").glob("upgrade-local-changes-*.md"))
    report = report_path.read_text(encoding="utf-8")
    assert " M installer/ai.py" in report
    assert "?? notes.txt" in report
    assert "git reset --hard origin/release/candidate" in report
    assert spinner.oks == ["[OK]"]


# @matrix setup : branch failure-propagation git-upgrade
def test_upgrade_repository_handles_clean_status_and_status_failure(monkeypatch):
    import installer as setup_pkg
    from installer import upgrade

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(upgrade, "GIT_CLI", "git")
    calls = []

    def clean_run(command, **_kwargs):
        calls.append(command)
        return completed_process(command, stdout="")

    monkeypatch.setattr(upgrade.subprocess, "run", clean_run)
    clean_spinner = SpinnerRecorder()

    assert upgrade._update_repository(clean_spinner)
    assert calls == [
        ["git", "status", "--porcelain"],
        ["git", "fetch", "--all"],
        ["git", "reset", "--hard", "origin/main"],
    ]
    assert clean_spinner.oks == ["[OK]"]

    def failing_status(command, **_kwargs):
        assert command == ["git", "status", "--porcelain"]
        return completed_process(command, returncode=1, stderr="not a repo")

    monkeypatch.setattr(upgrade.subprocess, "run", failing_status)
    failure_spinner = SpinnerRecorder()

    assert not upgrade._update_repository(failure_spinner)
    assert failure_spinner.fails == ["[X]"]
    assert any("Git status failed" in message for message in failure_spinner.messages)


# @matrix setup : branch git-upgrade version-validation
def test_upgrade_target_fetches_and_reads_exact_remote_version(monkeypatch, tmp_path):
    import installer as setup_pkg
    from installer import upgrade

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(upgrade, "GIT_CLI", "git")
    monkeypatch.setattr(upgrade, "REPOSITORY_ROOT", tmp_path)
    commit = "a" * 40
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command == ["git", "fetch", "--all"]:
            return completed_process(command)
        if command == [
            "git",
            "rev-parse",
            "--verify",
            "origin/release/candidate^{commit}",
        ]:
            return completed_process(command, stdout=f"{commit}\n")
        if command == ["git", "show", f"{commit}:package.json"]:
            return completed_process(command, stdout='{"version": "2.0.0"}\n')
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(upgrade.subprocess, "run", fake_run)
    spinner = SpinnerRecorder()

    assert upgrade._fetch_upgrade_target(
        spinner,
        branch="release/candidate",
    ) == {
        "branch": "release/candidate",
        "ref": "origin/release/candidate",
        "commit": commit,
        "version": "2.0.0",
    }
    assert [command for command, _kwargs in calls] == [
        ["git", "fetch", "--all"],
        [
            "git",
            "rev-parse",
            "--verify",
            "origin/release/candidate^{commit}",
        ],
        ["git", "show", f"{commit}:package.json"],
    ]
    assert all(kwargs["cwd"] == tmp_path for _command, kwargs in calls)
    assert spinner.oks == ["[OK]"]


# @matrix setup : branch failure-propagation git-upgrade version-validation
@pytest.mark.parametrize(
    ("resolved", "package", "expected_message"),
    [
        (None, None, "Could not resolve origin/main"),
        ("b" * 40, '{"version": "2.0"}', "stable X.Y.Z version"),
    ],
    ids=["missing-ref", "invalid-version"],
)
def test_upgrade_target_rejects_missing_ref_and_invalid_version(
    monkeypatch,
    resolved,
    package,
    expected_message,
):
    import installer as setup_pkg
    from installer import upgrade

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(upgrade, "GIT_CLI", "git")

    def fake_run(command, **_kwargs):
        if command == ["git", "fetch", "--all"]:
            return completed_process(command)
        if command == [
            "git",
            "rev-parse",
            "--verify",
            "origin/main^{commit}",
        ]:
            return completed_process(
                command,
                returncode=0 if resolved else 1,
                stdout=f"{resolved}\n" if resolved else "",
                stderr="missing" if not resolved else "",
            )
        if resolved and command == ["git", "show", f"{resolved}:package.json"]:
            return completed_process(command, stdout=package)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(upgrade.subprocess, "run", fake_run)
    spinner = SpinnerRecorder()

    assert upgrade._fetch_upgrade_target(spinner) is None
    assert spinner.fails == ["[X]"]
    assert any(expected_message in message for message in spinner.messages)


# @matrix setup : branch config-files git-upgrade post-deploy
# @pairs migrations:major-version setup:major-version
def test_upgrade_replaces_source_then_applies_update(monkeypatch):
    import installer as setup_pkg
    from installer import upgrade

    events = []
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        upgrade,
        "activate_installation",
        lambda: events.append("activate"),
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(
            SETTINGS=_fake_settings(
                app={"VERSION": "1.4.0"},
                node={"version": "1.4.0"},
            )
        ),
    )
    target_commit = "c" * 40
    monkeypatch.setattr(
        upgrade,
        "_fetch_upgrade_target",
        lambda spinner, branch: (
            events.append(("inspect", branch))
            or {
                "branch": branch,
                "ref": f"origin/{branch}",
                "commit": target_commit,
                "version": "2.0.0",
            }
        ),
    )
    monkeypatch.setattr(
        upgrade,
        "_update_repository",
        lambda spinner, branch, target_commit: (
            events.append(("replace", branch, target_commit)) or True
        ),
    )
    monkeypatch.setattr(
        upgrade,
        "_refresh_setup_dependencies",
        lambda: events.append("dependencies"),
    )
    monkeypatch.setattr(
        upgrade,
        "_apply_update",
        lambda **kwargs: events.append(("apply", kwargs)) or 0,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    assert upgrade.upgrade(branch="release/candidate") == 0
    assert events == [
        "activate",
        ("inspect", "release/candidate"),
        ("replace", "release/candidate", target_commit),
        "dependencies",
        (
            "apply",
            {
                "upgrade": True,
                "installed_version": "1.4.0",
                "target_version": "2.0.0",
                "maintenance_required": True,
            },
        ),
    ]


# @matrix migrations setup : major-version unknown-source version-validation
def test_upgrade_maintenance_notice_version_policy():
    from installer.upgrade_notice import (
        parse_release_version,
        post_upgrade_maintenance_required,
    )

    assert parse_release_version("2.3.4") == (2, 3, 4)
    assert parse_release_version("2.3") is None
    assert post_upgrade_maintenance_required("1.9.0", "2.0.0")
    assert post_upgrade_maintenance_required("unknown", "2.0.0")
    assert not post_upgrade_maintenance_required("2.0.0", "2.1.0")
    with pytest.raises(ValueError, match="stable X.Y.Z"):
        post_upgrade_maintenance_required("1.0.0", "next")


# @matrix migrations setup : legacy-upgrade major-version
def test_legacy_upgrade_deploy_notice_uses_active_operation(monkeypatch):
    from installer import state
    from installer.upgrade_notice import legacy_upgrade_deploy_notice_required

    settings = _fake_settings(
        app={"VERSION": "1.0.0"},
        node={"version": "1.0.0"},
    )
    monkeypatch.setattr(
        state,
        "_ACTIVE_JOURNAL",
        types.SimpleNamespace(payload={"mode": "upgrade"}),
    )

    assert legacy_upgrade_deploy_notice_required(settings)
    settings.APP["VERSION"] = "1.1.0"
    assert not legacy_upgrade_deploy_notice_required(settings)
    settings.APP["VERSION"] = "2.0.0"
    state._ACTIVE_JOURNAL.payload["mode"] = "install"
    assert not legacy_upgrade_deploy_notice_required(settings)


# @matrix setup : dependency-bootstrap git-upgrade
def test_upgrade_refreshes_setup_dependencies_from_replaced_checkout(monkeypatch):
    import installer as setup_pkg
    from installer import upgrade

    events = []
    package_install = types.ModuleType("installer.package_install")
    refreshed = types.SimpleNamespace(
        ensure_pip_is_available=lambda: events.append("pip"),
        ensure_setup_dependencies=lambda: events.append("dependencies"),
    )
    monkeypatch.setattr(
        setup_pkg,
        "package_install",
        package_install,
        raising=False,
    )
    monkeypatch.setattr(
        upgrade,
        "reload",
        lambda module: events.append(("reload", module.__name__)) or refreshed,
    )

    upgrade._refresh_setup_dependencies()

    assert events == [
        ("reload", "installer.package_install"),
        "pip",
        "dependencies",
    ]


# @matrix setup : config-files deferred-jobs post-deploy provider-apis public-page-settings storage-buckets
# @pairs migrations:major-version setup:major-version
def test_update_reloads_config_and_setup_helpers(monkeypatch, capsys):
    import installer as setup_pkg
    from installer import upgrade

    events = []
    settings = _fake_settings(
        app={"VERSION": "1.5.0"},
        node={"version": "2.0.0"},
    )
    config_module = types.ModuleType("config")
    constants_module = types.ModuleType("config.constants")
    create_config_module = types.ModuleType("installer.create_config")
    gcloud_module = types.ModuleType("installer.gcloud")
    utils_module = types.ModuleType("installer.utils")
    deploy_module = types.ModuleType("runner.deploy")

    create_config_module.update_config = lambda: (
        events.append("update_config") or "2.0.0"
    )
    create_config_module.verify_application_config = lambda upgrade=False: (
        events.append(("verify_application_config", upgrade))
    )
    gcloud_module.create_deferred_job_reconciler = lambda: events.append(
        "deferred-job-reconciler"
    )
    gcloud_module.enable_gcloud_apis = lambda: events.append("provider-apis")
    gcloud_module.setup_app_engine = lambda: events.append("app-engine-and-runtime-iam")
    gcloud_module.configure_storage_buckets = lambda: events.append("storage-buckets")
    gcloud_module.configure_data_protection = lambda: events.append("data-protection")
    utils_module.deploy_to_app_engine = lambda **kwargs: events.append("deploy")
    deploy_module.verify_runtime_deploy_surface = lambda: events.append(
        "verify-runtime-deploy-surface"
    )
    config_module.SETTINGS = settings
    config_module.constants = constants_module
    config_module.verify_generation_manifest = lambda: events.append(
        "verify_generation"
    )

    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setattr(setup_pkg, "create_config", create_config_module, raising=False)
    monkeypatch.setitem(sys.modules, "installer.gcloud", gcloud_module)
    monkeypatch.setattr(setup_pkg, "gcloud", gcloud_module, raising=False)
    monkeypatch.setattr(setup_pkg, "utils", utils_module, raising=False)
    monkeypatch.setitem(sys.modules, "runner.deploy", deploy_module)

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        upgrade,
        "activate_installation",
        lambda: events.append("activate_installation"),
    )
    monkeypatch.setattr(
        upgrade, "_update_custom_images", lambda f: events.append("images")
    )
    monkeypatch.setattr(
        upgrade, "_update_deployment_settings", lambda f: events.append("deployment")
    )
    monkeypatch.setattr(
        upgrade, "_update_ai_settings", lambda f: events.append("ai-settings")
    )
    monkeypatch.setattr(
        upgrade,
        "_update_public_page_settings",
        lambda f: events.append("public-page-settings"),
    )
    storage_module = types.ModuleType("installer.storage")
    storage_module.configure_storage = lambda: events.append("storage-config")
    monkeypatch.setitem(sys.modules, "installer.storage", storage_module)
    monkeypatch.setattr(setup_pkg, "storage", storage_module, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    def fake_reload(module):
        events.append(("reload", module.__name__))
        return module

    monkeypatch.setattr(upgrade, "reload", fake_reload)

    assert upgrade.update() == 0
    output = capsys.readouterr().out
    assert "Required post-upgrade maintenance" in output
    assert "Apply Updates" in output
    assert "Refresh Cache" in output
    assert "Required next steps" in output

    assert events == [
        "activate_installation",
        ("reload", "installer"),
        ("reload", "config"),
        ("reload", "config.constants"),
        ("reload", "installer.create_config"),
        ("reload", "installer.gcloud"),
        ("reload", "installer.utils"),
        "update_config",
        ("verify_application_config", False),
        "verify-runtime-deploy-surface",
        "provider-apis",
        "app-engine-and-runtime-iam",
        "storage-buckets",
        "data-protection",
        "images",
        "deployment",
        "ai-settings",
        "public-page-settings",
        "verify_generation",
        "deploy",
        "deferred-job-reconciler",
    ]

    events.clear()
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.setattr(
        upgrade,
        "_configure_deferred_job_recovery",
        lambda f, gcloud: events.append("scheduler-repair-warning") or False,
    )

    assert upgrade.update() == 1
    assert "deploy" in events
    assert "scheduler-repair-warning" in events


# @matrix deferred-jobs setup : failure-isolation post-deploy recovery
@pytest.mark.parametrize(
    "failure",
    [RuntimeError("scheduler unavailable"), SystemExit(1)],
    ids=["runtime-error", "gcloud-system-exit"],
)
def test_post_deploy_deferred_job_recovery_failure_is_nonfatal(capsys, failure):
    from installer import upgrade

    formatter = _fake_formatter().initialize()
    gcloud = types.SimpleNamespace(
        create_deferred_job_reconciler=lambda: (_ for _ in ()).throw(failure)
    )

    assert not upgrade._configure_deferred_job_recovery(formatter, gcloud)

    output = capsys.readouterr().out
    assert "Deployment succeeded" in output
    assert "does not invalidate the completed update" in output
    assert "active deferred jobs may fail" in output
    assert "Retry with: ./setup.sh jobs" in output


# @pair setup:image-restore
def test_image_restore_uses_loaded_metadata_and_timeouts(monkeypatch, tmp_path):
    from installer import image

    datastore_calls = []

    class FakeDatastore:
        def key(self, *parts):
            return parts

        def get(self, key, **kwargs):
            datastore_calls.append({"key": key, **kwargs})
            return {
                "version": 3,
                "logo.png": "stored/logo.png",
                "asset_generations": {"logo.png": "41"},
            }

    monkeypatch.setattr(image, "get_datastore_client", lambda: FakeDatastore())

    assert image.get_images() == {
        "version": 3,
        "logo.png": "stored/logo.png",
        "asset_generations": {"logo.png": "41"},
    }
    assert datastore_calls == [
        {"key": ("site", "image"), "timeout": image.DATASTORE_TIMEOUT}
    ]

    monkeypatch.chdir(tmp_path)
    downloads = []
    site_images_dir = tmp_path / "site-images"
    Directory = types.SimpleNamespace(
        SITE_IMAGES=types.SimpleNamespace(
            value=site_images_dir,
            get_or_create=lambda: site_images_dir,
        )
    )
    monkeypatch.setitem(
        sys.modules, "config", types.SimpleNamespace(Directory=Directory)
    )

    class FakeBlob:
        def __init__(self, key):
            self.key = key

        def download_to_filename(self, path, **kwargs):
            downloads.append({"key": self.key, "path": path, **kwargs})
            Path(path).write_bytes(f"image:{self.key}".encode())

    class FakeBucket:
        def blob(self, key):
            return FakeBlob(key)

    monkeypatch.setattr(image, "get_storage_bucket", lambda: FakeBucket())

    sp = SpinnerRecorder()
    assert image.save_images(
        sp,
        {
            "version": 4,
            "logo.png": "stored/logo.png",
            "nested/splash.png": "nested/splash.png",
            "asset_generations": {
                "logo.png": "41",
                "nested/splash.png": "42",
            },
            "ENTITY": '{"legacy_generation_metadata": true}',
        },
    )

    assert [download["key"] for download in downloads] == [
        "stored/logo.png",
        "nested/splash.png",
    ]
    assert all(
        download["timeout"] == image.IMAGE_DOWNLOAD_TIMEOUT for download in downloads
    )
    assert site_images_dir.joinpath("logo.png").read_bytes() == (
        b"image:stored/logo.png"
    )
    assert site_images_dir.joinpath("nested/splash.png").read_bytes() == (
        b"image:nested/splash.png"
    )
    assert sp.oks == []

    class FailingBlob(FakeBlob):
        def download_to_filename(self, path, **kwargs):
            raise RuntimeError("storage unavailable")

    class FailingBucket:
        def blob(self, key):
            return FailingBlob(key)

    monkeypatch.setattr(image, "get_storage_bucket", lambda: FailingBucket())
    failed_sp = SpinnerRecorder()
    assert not image.save_images(failed_sp, {"logo.png": "logo.png"})
    assert failed_sp.fails == []
    assert any("continuing without it" in message for message in failed_sp.messages)


# @matrix setup : image-restore path-validation transactional-state partial-failure
def test_image_restore_skips_invalid_entries_and_keeps_successful_downloads(
    monkeypatch,
    tmp_path,
):
    from installer import image

    images_dir = tmp_path / "site-images"
    images_dir.mkdir()
    (images_dir / "live.png").write_bytes(b"live")
    directory = types.SimpleNamespace(
        SITE_IMAGES=types.SimpleNamespace(value=images_dir)
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(Directory=directory),
    )

    assert not image.save_images(
        SpinnerRecorder(),
        {"../escape.png": "../escape.png"},
    )
    assert (images_dir / "live.png").read_bytes() == b"live"
    assert not (tmp_path / "escape.png").exists()

    class Blob:
        def __init__(self, key):
            self.key = key

        def download_to_filename(self, path, **kwargs):
            if self.key == "second.png":
                raise RuntimeError("forced download failure")
            Path(path).write_bytes(b"staged")

    monkeypatch.setattr(
        image,
        "get_storage_bucket",
        lambda: types.SimpleNamespace(blob=lambda key: Blob(key)),
    )
    assert image.save_images(
        SpinnerRecorder(),
        {"first.png": "first.png", "second.png": "second.png"},
    )
    assert (images_dir / "live.png").read_bytes() == b"live"
    assert (images_dir / "first.png").read_bytes() == b"staged"
    assert not (images_dir / "second.png").exists()


# @matrix setup : image-restore site-image
def test_upgrade_restore_images_installs_storage_before_restore_spinner(monkeypatch):
    from installer import upgrade

    events = []
    site_images = {"version": 11, "logo.png": True}

    monkeypatch.setattr(
        upgrade, "ensure_datastore_dependency", lambda: events.append("datastore")
    )
    monkeypatch.setattr(upgrade, "get_images", lambda: site_images)
    monkeypatch.setattr(
        upgrade, "ensure_storage_dependency", lambda: events.append("storage")
    )

    def fake_save_images(sp, images):
        events.append(("save", images))
        return True

    monkeypatch.setattr(upgrade, "save_images", fake_save_images)

    def fake_yaspin(text):
        class Context:
            def __enter__(self):
                events.append(("spinner", text))
                return SpinnerRecorder()

            def __exit__(self, exc_type, exc, tb):
                return False

        return Context()

    formatter = types.SimpleNamespace(
        success=lambda message: message,
        warning=lambda message: message,
        ok_glyph="[OK]",
        fail_glyph="[X]",
        yaspin=fake_yaspin,
    )
    settings = _fake_settings()

    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )

    upgrade._update_custom_images(formatter)

    assert events == [
        "datastore",
        ("spinner", "Checking for custom images"),
        "storage",
        ("spinner", "Restoring custom images"),
        ("save", site_images),
    ]
    assert settings.APP["SITE_IMAGE_VERSION"] == 11


# @matrix setup : image-restore site-image partial-failure
def test_upgrade_restore_images_continues_when_no_remote_image_is_available(
    monkeypatch,
):
    from installer import upgrade

    spinner = SpinnerRecorder()
    formatter = _fake_formatter(spinner).initialize()
    settings = _fake_settings(app={"SITE_IMAGE_VERSION": 7})

    monkeypatch.setattr(upgrade, "ensure_datastore_dependency", lambda: None)
    monkeypatch.setattr(
        upgrade, "get_images", lambda: {"version": 11, "logo.png": "logo.png"}
    )
    monkeypatch.setattr(upgrade, "ensure_storage_dependency", lambda: None)
    monkeypatch.setattr(upgrade, "save_images", lambda sp, images: False)
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )

    upgrade._update_custom_images(formatter)

    assert settings.APP["SITE_IMAGE_VERSION"] == 7
    assert spinner.fails == []
    assert spinner.oks == ["[OK]", "[OK]"]


# @source config/deployment.py::normalize_deployment_settings
# @matrix config : app-yaml deployment-settings memory-pressure
def test_default_deployment_uses_three_memory_safe_workers():
    constants = _load_config_constants()
    assert constants.DEFAULT_DEPLOYMENT_SETTINGS["DEPLOY_WORKER_COUNT"] == "3"


# @matrix config user-settings : app-yaml deployment-settings validation
def test_deployment_settings_normalize_validation(monkeypatch):
    class DeploymentSettingsError(Exception):
        pass

    constants = types.SimpleNamespace(
        DEFAULT_DEPLOYMENT_SETTINGS={
            "DEPLOY_SCALING_TYPE": "basic",
            "DEPLOY_MAX_INSTANCES": "1",
            "DEPLOY_IDLE_TIMEOUT": "15m",
            "DEPLOY_WORKER_COUNT": "3",
            "DEPLOY_INSTANCE_CLASS": "B2",
            "DEPLOY_MIN_IDLE_INSTANCES": "1",
        },
        SCALING_TYPES=("automatic", "basic"),
        AUTOMATIC_INSTANCE_CLASSES=("F1", "F2", "F4", "F4_1G"),
        BASIC_INSTANCE_CLASSES=("B1", "B2", "B4", "B4_1G", "B8"),
    )
    monkeypatch.setitem(
        sys.modules,
        "lagniappe.core.exceptions",
        types.SimpleNamespace(DeploymentSettingsError=DeploymentSettingsError),
    )
    _install_config_package(monkeypatch, constants)

    from config.deployment import normalize_deployment_settings

    assert normalize_deployment_settings(
        {
            "DEPLOY_SCALING_TYPE": "automatic",
            "DEPLOY_WORKER_COUNT": "3",
            "DEPLOY_INSTANCE_CLASS": "F2",
            "DEPLOY_MAX_INSTANCES": "2",
            "DEPLOY_MIN_IDLE_INSTANCES": "2",
        }
    ) == {
        "DEPLOY_SCALING_TYPE": "automatic",
        "DEPLOY_WORKER_COUNT": "3",
        "DEPLOY_INSTANCE_CLASS": "F2",
        "DEPLOY_MAX_INSTANCES": "2",
        "DEPLOY_MIN_IDLE_INSTANCES": "2",
        "DEPLOY_IDLE_TIMEOUT": "15m",
    }

    with pytest.raises(DeploymentSettingsError):
        normalize_deployment_settings({"DEPLOY_SCALING_TYPE": "manual"})

    with pytest.raises(DeploymentSettingsError):
        normalize_deployment_settings(
            {"DEPLOY_SCALING_TYPE": "automatic", "DEPLOY_INSTANCE_CLASS": "B2"}
        )

    with pytest.raises(DeploymentSettingsError):
        normalize_deployment_settings({"DEPLOY_WORKER_COUNT": "0"})

    for instance_class in ("F2", "B2"):
        with pytest.raises(DeploymentSettingsError, match="at most 3 .*workers"):
            normalize_deployment_settings(
                {
                    "DEPLOY_SCALING_TYPE": (
                        "automatic" if instance_class.startswith("F") else "basic"
                    ),
                    "DEPLOY_INSTANCE_CLASS": instance_class,
                    "DEPLOY_WORKER_COUNT": "4",
                }
            )

        assert (
            normalize_deployment_settings(
                {
                    "DEPLOY_SCALING_TYPE": (
                        "automatic" if instance_class.startswith("F") else "basic"
                    ),
                    "DEPLOY_INSTANCE_CLASS": instance_class,
                    "DEPLOY_WORKER_COUNT": "4",
                },
                enforce_worker_limit=False,
            )["DEPLOY_WORKER_COUNT"]
            == "4"
        )

    for scaling_type, instance_class in (("automatic", "F4"), ("basic", "B4")):
        assert (
            normalize_deployment_settings(
                {
                    "DEPLOY_SCALING_TYPE": scaling_type,
                    "DEPLOY_INSTANCE_CLASS": instance_class,
                    "DEPLOY_WORKER_COUNT": "20",
                }
            )["DEPLOY_WORKER_COUNT"]
            == "20"
        )

    with pytest.raises(DeploymentSettingsError):
        normalize_deployment_settings({"DEPLOY_MAX_INSTANCES": "0"})

    with pytest.raises(DeploymentSettingsError):
        normalize_deployment_settings(
            {
                "DEPLOY_SCALING_TYPE": "automatic",
                "DEPLOY_INSTANCE_CLASS": "F2",
                "DEPLOY_MAX_INSTANCES": "1",
                "DEPLOY_MIN_IDLE_INSTANCES": "2",
            }
        )


# @matrix config : app-yaml deployment-settings
def test_deployment_settings_apply_automatic_scaling_preserves_unowned_app_config(
    monkeypatch,
):
    constants = types.SimpleNamespace(
        RUNTIME="python314",
        GUNICORN_TIMEOUT_SECONDS=3600,
        AUTOMATIC_INBOUND_SERVICES=("warmup",),
        DEFAULT_DEPLOYMENT_SETTINGS={
            "DEPLOY_SCALING_TYPE": "basic",
            "DEPLOY_MAX_INSTANCES": "1",
            "DEPLOY_IDLE_TIMEOUT": "15m",
            "DEPLOY_WORKER_COUNT": "3",
            "DEPLOY_INSTANCE_CLASS": "B2",
            "DEPLOY_MIN_IDLE_INSTANCES": "1",
        },
        SCALING_TYPES=("automatic", "basic"),
        AUTOMATIC_INSTANCE_CLASSES=("F1", "F2", "F4", "F4_1G"),
        BASIC_INSTANCE_CLASSES=("B1", "B2", "B4", "B4_1G", "B8"),
    )
    monkeypatch.setitem(
        sys.modules,
        "lagniappe.core.exceptions",
        types.SimpleNamespace(DeploymentSettingsError=Exception),
    )
    _install_config_package(monkeypatch, constants)

    from config.deployment import apply_deployment_settings

    handlers = [{"url": "/.*", "script": "auto"}]
    app_yaml = {
        "runtime": "python312",
        "entrypoint": "old",
        "instance_class": "B2",
        "basic_scaling": {"max_instances": 1, "idle_timeout": "15m"},
        "inbound_services": ["mail"],
        "handlers": handlers,
        "service_account": "service@example.com",
        "default_expiration": "31536000s",
    }
    app_settings = {}

    apply_deployment_settings(
        app_yaml,
        app_settings,
        {
            "DEPLOY_SCALING_TYPE": "automatic",
            "DEPLOY_WORKER_COUNT": "3",
            "DEPLOY_INSTANCE_CLASS": "F2",
            "DEPLOY_MAX_INSTANCES": "2",
            "DEPLOY_MIN_IDLE_INSTANCES": "2",
        },
    )

    assert app_yaml["entrypoint"] == "gunicorn -t 3600 -w 3 -b :$PORT main:app"
    assert app_yaml["instance_class"] == "F2"
    assert app_yaml["automatic_scaling"] == {
        "min_idle_instances": "2",
        "max_instances": "2",
    }
    assert app_yaml["inbound_services"] == ["mail", "warmup"]

    apply_deployment_settings(
        app_yaml,
        app_settings,
        {
            "DEPLOY_SCALING_TYPE": "automatic",
            "DEPLOY_WORKER_COUNT": "3",
            "DEPLOY_INSTANCE_CLASS": "F2",
            "DEPLOY_MAX_INSTANCES": "2",
            "DEPLOY_MIN_IDLE_INSTANCES": "2",
        },
    )

    assert app_yaml["inbound_services"] == ["mail", "warmup"]
    assert "basic_scaling" not in app_yaml
    assert app_yaml["handlers"] is handlers
    assert app_yaml["service_account"] == "service@example.com"
    assert app_yaml["default_expiration"] == "31536000s"


# @matrix config : app-yaml deployment-settings
def test_deployment_settings_apply_basic_scaling_preserves_unowned_app_config(
    monkeypatch,
):
    constants = types.SimpleNamespace(
        RUNTIME="python314",
        GUNICORN_TIMEOUT_SECONDS=3600,
        AUTOMATIC_INBOUND_SERVICES=("warmup",),
        DEFAULT_DEPLOYMENT_SETTINGS={
            "DEPLOY_SCALING_TYPE": "basic",
            "DEPLOY_MAX_INSTANCES": "1",
            "DEPLOY_IDLE_TIMEOUT": "15m",
            "DEPLOY_WORKER_COUNT": "3",
            "DEPLOY_INSTANCE_CLASS": "B2",
            "DEPLOY_MIN_IDLE_INSTANCES": "1",
        },
        SCALING_TYPES=("automatic", "basic"),
        AUTOMATIC_INSTANCE_CLASSES=("F1", "F2", "F4", "F4_1G"),
        BASIC_INSTANCE_CLASSES=("B1", "B2", "B4", "B4_1G", "B8"),
    )
    monkeypatch.setitem(
        sys.modules,
        "lagniappe.core.exceptions",
        types.SimpleNamespace(DeploymentSettingsError=Exception),
    )
    _install_config_package(monkeypatch, constants)

    from config.deployment import apply_deployment_settings

    app_yaml = {
        "runtime": "python312",
        "entrypoint": "old",
        "instance_class": "F2",
        "automatic_scaling": {"min_idle_instances": 1, "max_instances": 4},
        "inbound_services": ["mail", "warmup"],
        "handlers": [{"url": "/.*", "script": "auto"}],
        "unknown": "preserved",
    }
    app_settings = {}

    apply_deployment_settings(
        app_yaml,
        app_settings,
        {
            "DEPLOY_SCALING_TYPE": "basic",
            "DEPLOY_WORKER_COUNT": "2",
            "DEPLOY_INSTANCE_CLASS": "B2",
            "DEPLOY_MAX_INSTANCES": "1",
        },
    )

    assert app_yaml["entrypoint"] == "gunicorn -t 3600 -w 2 -b :$PORT main:app"
    assert app_yaml["instance_class"] == "B2"
    assert app_yaml["basic_scaling"] == {
        "max_instances": "1",
        "idle_timeout": "15m",
    }
    assert "automatic_scaling" not in app_yaml
    assert app_yaml["inbound_services"] == ["mail"]
    assert app_yaml["unknown"] == "preserved"

    app_yaml["inbound_services"] = ["warmup"]
    apply_deployment_settings(
        app_yaml,
        app_settings,
        {
            "DEPLOY_SCALING_TYPE": "basic",
            "DEPLOY_WORKER_COUNT": "2",
            "DEPLOY_INSTANCE_CLASS": "B2",
            "DEPLOY_MAX_INSTANCES": "1",
        },
    )

    assert "inbound_services" not in app_yaml


# @matrix config : ai-settings app-yaml
def test_ai_settings_apply_preserves_unowned_app_config(monkeypatch):
    constants = types.SimpleNamespace(
        DEFAULT_AI_MODEL="gemini-3.5-flash",
        DEFAULT_UTILITY_AI_MODEL="gemini-3.1-flash-lite",
        DEFAULT_AI_IMAGE_MODEL="gemini-3.1-flash-image",
        DEFAULT_AI_LOCATION="global",
    )
    monkeypatch.setitem(
        sys.modules,
        "lagniappe.core.exceptions",
        types.SimpleNamespace(AISettingsError=Exception),
    )
    _install_config_package(monkeypatch, constants)

    from config.ai_settings import apply_ai_settings

    app_settings = {
        "APP_NAME": "Lagniappe",
        "AI_MODEL": "old-primary",
        "AI_UTILITY_MODEL": "old-utility",
        "AI_IMAGE_MODEL": "old-image",
        "AI_LOCATION": "global",
    }

    apply_ai_settings(
        app_settings,
        {
            "AI_MODEL": "custom-primary",
            "AI_UTILITY_MODEL": "custom-utility",
            "AI_IMAGE_MODEL": "custom-image",
            "AI_LOCATION": "global",
        },
    )

    assert app_settings == {
        "APP_NAME": "Lagniappe",
        "AI_MODEL": "custom-primary",
        "AI_UTILITY_MODEL": "custom-utility",
        "AI_IMAGE_MODEL": "custom-image",
        "AI_LOCATION": "global",
    }


# @matrix config : app-yaml public-page-indexing
def test_public_page_settings_apply_preserves_unowned_app_config(monkeypatch):
    constants = types.SimpleNamespace(DEFAULT_PUBLIC_PAGE_INDEXING=False)
    _install_config_package(monkeypatch, constants)

    from config.public_pages import apply_public_page_settings

    app_settings = {"APP_NAME": "Lagniappe", "PUBLIC_PAGE_INDEXING": False}
    apply_public_page_settings(
        app_settings,
        {"PUBLIC_PAGE_INDEXING": "true", "ignored": "value"},
    )

    assert app_settings == {
        "APP_NAME": "Lagniappe",
        "PUBLIC_PAGE_INDEXING": True,
    }


# @matrix setup : app-yaml datastore deployment-settings
def test_upgrade_restore_deployment_settings_applies_saved_app_config(monkeypatch):
    from installer import upgrade

    events = []
    deployment_settings = {
        "version": 4,
        "DEPLOY_SCALING_TYPE": "automatic",
        "DEPLOY_WORKER_COUNT": "4",
        "DEPLOY_INSTANCE_CLASS": "F2",
        "DEPLOY_MAX_INSTANCES": "2",
        "DEPLOY_MIN_IDLE_INSTANCES": "2",
    }
    settings = _fake_settings(
        deploy={
            "runtime": "python312",
            "basic_scaling": {"max_instances": 1, "idle_timeout": "15m"},
            "handlers": [{"url": "/.*", "script": "auto"}],
        }
    )

    monkeypatch.setattr(
        upgrade, "ensure_datastore_dependency", lambda: events.append("datastore")
    )
    import installer.deployment as deployment_module

    monkeypatch.setattr(
        deployment_module, "get_deployment_settings", lambda: deployment_settings
    )

    def fake_yaspin(text):
        class Context:
            def __enter__(self):
                events.append(("spinner", text))
                return SpinnerRecorder()

            def __exit__(self, exc_type, exc, tb):
                return False

        return Context()

    formatter = types.SimpleNamespace(
        success=lambda message: message,
        warning=lambda message: message,
        ok_glyph="[OK]",
        fail_glyph="[X]",
        yaspin=fake_yaspin,
    )

    constants = types.SimpleNamespace(
        RUNTIME="python314",
        GUNICORN_TIMEOUT_SECONDS=3600,
        AUTOMATIC_INBOUND_SERVICES=("warmup",),
        DEFAULT_DEPLOYMENT_SETTINGS={
            "DEPLOY_SCALING_TYPE": "basic",
            "DEPLOY_MAX_INSTANCES": "1",
            "DEPLOY_IDLE_TIMEOUT": "15m",
            "DEPLOY_WORKER_COUNT": "3",
            "DEPLOY_INSTANCE_CLASS": "B2",
            "DEPLOY_MIN_IDLE_INSTANCES": "1",
        },
        SCALING_TYPES=("automatic", "basic"),
        AUTOMATIC_INSTANCE_CLASSES=("F1", "F2", "F4", "F4_1G"),
        BASIC_INSTANCE_CLASSES=("B1", "B2", "B4", "B4_1G", "B8"),
    )
    monkeypatch.setitem(
        sys.modules,
        "lagniappe.core.exceptions",
        types.SimpleNamespace(DeploymentSettingsError=Exception),
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    upgrade._update_deployment_settings(formatter)

    assert events == [
        "datastore",
        ("spinner", "Checking for deployment settings"),
        ("spinner", "Applying deployment settings"),
    ]
    assert settings.DEPLOY["entrypoint"] == "gunicorn -t 3600 -w 4 -b :$PORT main:app"
    assert settings.DEPLOY["instance_class"] == "F2"
    assert settings.DEPLOY["automatic_scaling"] == {
        "min_idle_instances": "2",
        "max_instances": "2",
    }
    assert settings.DEPLOY["inbound_services"] == ["warmup"]
    assert "basic_scaling" not in settings.DEPLOY


# @matrix setup : app-yaml deployment-settings
def test_upgrade_restore_deployment_settings_continues_when_unavailable(monkeypatch):
    import config
    from installer import upgrade

    def unavailable():
        raise RuntimeError("datastore unavailable")

    monkeypatch.setattr(upgrade, "ensure_datastore_dependency", unavailable)

    settings = _fake_settings(deploy={"entrypoint": "existing"})
    formatter = types.SimpleNamespace(
        success=lambda message: message,
        warning=lambda message: message,
        yaspin=spinner_factory(),
    )

    monkeypatch.setattr(config, "SETTINGS", settings)

    upgrade._update_deployment_settings(formatter)

    assert settings.DEPLOY == {"entrypoint": "existing"}


# @matrix setup : ai-settings app-yaml datastore
def test_upgrade_restore_ai_settings_applies_saved_app_config(monkeypatch):
    from installer import upgrade

    events = []
    ai_settings = {
        "version": 3,
        "AI_MODEL": "custom-primary",
        "AI_UTILITY_MODEL": "custom-utility",
        "AI_IMAGE_MODEL": "custom-image",
        "AI_LOCATION": "global",
    }
    settings = _fake_settings(
        app={
            "APP_NAME": "Lagniappe",
            "AI_MODEL": "old-primary",
            "AI_UTILITY_MODEL": "old-utility",
            "AI_IMAGE_MODEL": "old-image",
            "AI_LOCATION": "global",
        }
    )

    monkeypatch.setattr(
        upgrade, "ensure_datastore_dependency", lambda: events.append("datastore")
    )
    import installer.ai_settings as ai_settings_module

    monkeypatch.setattr(ai_settings_module, "get_ai_settings", lambda: ai_settings)

    def fake_yaspin(text):
        class Context:
            def __enter__(self):
                events.append(("spinner", text))
                return SpinnerRecorder()

            def __exit__(self, exc_type, exc, tb):
                return False

        return Context()

    formatter = types.SimpleNamespace(
        success=lambda message: message,
        warning=lambda message: message,
        ok_glyph="[OK]",
        fail_glyph="[X]",
        yaspin=fake_yaspin,
    )

    constants = types.SimpleNamespace(
        DEFAULT_AI_MODEL="gemini-3.5-flash",
        DEFAULT_UTILITY_AI_MODEL="gemini-3.1-flash-lite",
        DEFAULT_AI_IMAGE_MODEL="gemini-3.1-flash-image",
        DEFAULT_AI_LOCATION="global",
    )
    monkeypatch.setitem(
        sys.modules,
        "lagniappe.core.exceptions",
        types.SimpleNamespace(AISettingsError=Exception),
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    upgrade._update_ai_settings(formatter)

    assert events == [
        "datastore",
        ("spinner", "Checking for AI settings"),
        ("spinner", "Applying AI settings"),
    ]
    assert settings.APP == {
        "APP_NAME": "Lagniappe",
        "AI_MODEL": "custom-primary",
        "AI_UTILITY_MODEL": "custom-utility",
        "AI_IMAGE_MODEL": "custom-image",
        "AI_LOCATION": "global",
    }


# @matrix setup : ai-settings app-yaml
def test_upgrade_restore_ai_settings_continues_when_unavailable(monkeypatch):
    import config
    from installer import upgrade

    def unavailable():
        raise RuntimeError("datastore unavailable")

    monkeypatch.setattr(upgrade, "ensure_datastore_dependency", unavailable)

    settings = _fake_settings(app={"AI_MODEL": "existing"})
    formatter = types.SimpleNamespace(
        success=lambda message: message,
        warning=lambda message: message,
        yaspin=spinner_factory(),
    )

    monkeypatch.setattr(config, "SETTINGS", settings)

    upgrade._update_ai_settings(formatter)

    assert settings.APP == {"AI_MODEL": "existing"}


# @matrix setup : app-yaml datastore public-page-indexing
def test_upgrade_restore_public_page_settings_applies_saved_app_config(monkeypatch):
    from installer import upgrade
    import installer.public_pages as public_pages_module

    events = []
    settings = _fake_settings(
        app={"APP_NAME": "Lagniappe", "PUBLIC_PAGE_INDEXING": False}
    )
    monkeypatch.setattr(
        upgrade, "ensure_datastore_dependency", lambda: events.append("datastore")
    )
    monkeypatch.setattr(
        public_pages_module,
        "get_public_page_settings",
        lambda: {"PUBLIC_PAGE_INDEXING": True, "version": 2},
    )
    formatter = types.SimpleNamespace(
        success=lambda message: message,
        warning=lambda message: message,
        ok_glyph="[OK]",
        fail_glyph="[X]",
        yaspin=spinner_factory(),
    )
    constants = types.SimpleNamespace(DEFAULT_PUBLIC_PAGE_INDEXING=False)
    _install_config_package(monkeypatch, constants, settings=settings)

    upgrade._update_public_page_settings(formatter)

    assert events == ["datastore"]
    assert settings.APP["PUBLIC_PAGE_INDEXING"] is True
    assert settings.APP["APP_NAME"] == "Lagniappe"


# @matrix setup : app-yaml public-page-indexing
def test_upgrade_restore_public_page_settings_continues_when_unavailable(monkeypatch):
    import config
    from installer import upgrade

    monkeypatch.setattr(
        upgrade,
        "ensure_datastore_dependency",
        lambda: (_ for _ in ()).throw(RuntimeError("datastore unavailable")),
    )
    settings = _fake_settings(app={"PUBLIC_PAGE_INDEXING": False})
    formatter = types.SimpleNamespace(
        success=lambda message: message,
        warning=lambda message: message,
        yaspin=spinner_factory(),
    )
    monkeypatch.setattr(config, "SETTINGS", settings)

    upgrade._update_public_page_settings(formatter)

    assert settings.APP == {"PUBLIC_PAGE_INDEXING": False}


# @matrix setup : dependency-pins package-install
# @source installer/package_install.py::_pinned_requirement
def test_setup_third_party_imports_are_bootstrapped_or_jit_guarded():
    from installer import package_install

    repository_root = Path(__file__).parents[2]
    local_roots = {
        path.stem
        for path in repository_root.iterdir()
        if path.is_file() and path.suffix == ".py"
    } | {
        path.name
        for path in repository_root.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }
    baseline_imports = {
        import_name
        for import_name, _package_name, _explanation in package_install._SETUP_DEPENDENCIES
    }

    def covers(imported_name, dependency_name):
        return imported_name == dependency_name or imported_name.startswith(
            f"{dependency_name}."
        )

    violations = []
    for path in sorted((repository_root / "installer").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }

        def scope(node):
            current = node
            while current is not None and not isinstance(
                current, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                current = parents.get(current)
            return current

        guards = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if not (
                (isinstance(target, ast.Name) and target.id == "install_if_missing")
                or (
                    isinstance(target, ast.Attribute)
                    and target.attr == "install_if_missing"
                )
            ):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                violations.append(
                    f"{path.relative_to(repository_root)}:{node.lineno}: dynamic JIT import"
                )
                continue
            import_name = node.args[0].value
            package_name = import_name
            if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
                package_name = node.args[2].value
            for keyword in node.keywords:
                if keyword.arg == "package_name" and isinstance(
                    keyword.value, ast.Constant
                ):
                    package_name = keyword.value.value
            try:
                package_install._pinned_requirement(package_name)
            except RuntimeError as error:
                violations.append(
                    f"{path.relative_to(repository_root)}:{node.lineno}: {error}"
                )
            guards.append((str(import_name), scope(node), node.lineno))

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend((alias.name, node) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.extend(
                    (
                        node.module
                        if alias.name == "*"
                        else f"{node.module}.{alias.name}",
                        node,
                    )
                    for alias in node.names
                )

        for imported_name, node in imports:
            root = imported_name.split(".", 1)[0]
            if root in sys.stdlib_module_names or root in local_roots:
                continue
            if any(
                covers(imported_name, dependency) for dependency in baseline_imports
            ):
                continue
            if any(
                covers(imported_name, dependency)
                and guard_scope is scope(node)
                and guard_line < node.lineno
                for dependency, guard_scope, guard_line in guards
            ):
                continue
            violations.append(
                f"{path.relative_to(repository_root)}:{node.lineno}: "
                f"{imported_name} is neither bootstrapped nor JIT guarded"
            )

    assert violations == []


# @matrix setup : dependency-pins package-install
def test_setup_package_install_helpers(monkeypatch):
    from installer import package_install

    check_calls = []

    def available_check_call(command, **kwargs):
        check_calls.append(command)

    monkeypatch.setattr(package_install.subprocess, "check_call", available_check_call)
    package_install.ensure_pip_is_available()

    assert check_calls == [[sys.executable, "-m", "pip", "--version"]]

    check_calls.clear()

    def install_then_verify(command, **kwargs):
        check_calls.append(command)
        if len(check_calls) == 1:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(package_install.subprocess, "check_call", install_then_verify)
    package_install.ensure_pip_is_available()

    assert check_calls == [
        [sys.executable, "-m", "pip", "--version"],
        [sys.executable, "-m", "ensurepip", "--upgrade", "--default-pip"],
        [sys.executable, "-m", "pip", "--version"],
    ]

    monkeypatch.setattr(
        package_install.subprocess,
        "check_call",
        lambda command, **kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, command)
        ),
    )

    with pytest.raises(SetupError):
        package_install.ensure_pip_is_available()

    run_calls = []
    imported = []
    invalidated = []

    monkeypatch.setattr(
        package_install.subprocess,
        "run",
        lambda command, **kwargs: (
            run_calls.append((command, kwargs))
            or completed_process(command, stdout="installed")
        ),
    )
    monkeypatch.setattr(
        package_install.importlib, "invalidate_caches", lambda: invalidated.append(True)
    )
    monkeypatch.setattr(
        package_install.importlib, "import_module", lambda name: imported.append(name)
    )

    package_install._install("PyYAML", "yaml")

    assert run_calls[0][0] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "PyYAML==6.0.3",
    ]
    assert package_install._pinned_requirement("redis") == "redis[hiredis]==8.1.0"
    assert package_install._pinned_requirement("yaspin") == "yaspin==3.4.0"
    assert package_install._pinned_requirement("certifi") == "certifi==2026.7.22"
    assert run_calls[1][0] == [sys.executable, "-m", "pip", "check"]
    assert invalidated == [True]
    assert imported == ["yaml"]

    with pytest.raises(RuntimeError, match="has no exact pin"):
        package_install._install("badpkg", "badpkg")

    monkeypatch.setattr(
        package_install.subprocess,
        "run",
        lambda command, **kwargs: completed_process(
            command, returncode=2, stdout="out", stderr="err"
        ),
    )

    with pytest.raises(RuntimeError, match="pip install exited with 2"):
        package_install._install("PyYAML", "yaml")

    installs = []
    monkeypatch.setenv("LAGNIAPPE_NONINTERACTIVE", "1")
    monkeypatch.setattr(
        package_install.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError(name)),
    )
    monkeypatch.setattr(
        package_install,
        "_install",
        lambda package, name: installs.append((package, name)),
    )

    package_install.install_if_missing("yaml", "YAML parser", package_name="PyYAML")

    assert installs == [("PyYAML", "yaml")]

    monkeypatch.setattr(
        package_install,
        "_install",
        lambda package, name: (_ for _ in ()).throw(RuntimeError("install failed")),
    )

    with pytest.raises(SetupError):
        package_install.install_if_missing(
            "yaml",
            "YAML parser",
            package_name="PyYAML",
        )

    class Tty:
        def isatty(self):
            return True

    monkeypatch.delenv("LAGNIAPPE_NONINTERACTIVE", raising=False)
    monkeypatch.setattr(package_install.sys, "stdin", Tty())
    monkeypatch.setattr(builtins, "input", lambda: "n")

    with pytest.raises(SetupCancelled):
        package_install.install_if_missing(
            "yaml",
            "YAML parser",
            package_name="PyYAML",
        )


# @matrix setup : dependency-pins package-install
def test_setup_dependency_transaction_validates_versions_and_pip_check(monkeypatch):
    from installer import package_install

    preflight_imports = []
    monkeypatch.setattr(
        package_install.metadata,
        "version",
        lambda _distribution_name: "6.0.3",
    )
    monkeypatch.setattr(
        package_install.importlib,
        "import_module",
        lambda import_name: preflight_imports.append(import_name),
    )
    assert package_install._dependency_status(
        "yaml",
        "PyYAML",
        check_import=False,
    ) == ("PyYAML==6.0.3", True, "6.0.3")
    assert preflight_imports == []

    dependencies = (
        ("yaml", "PyYAML", "YAML configuration"),
        ("requests", "requests", "provider HTTP requests"),
    )
    status_calls = {"yaml": 0, "requests": 0}
    requirements = {
        "yaml": "PyYAML==6.0.3",
        "requests": "requests==2.34.2",
    }

    check_import_calls = []

    def dependency_status(import_name, package_name, *, check_import=True):
        check_import_calls.append((import_name, check_import))
        status_calls[import_name] += 1
        ready = status_calls[import_name] > 1
        return (
            requirements[import_name],
            ready,
            "6.0.3" if ready else "version mismatch",
        )

    run_calls = []
    invalidated = []
    metadata_invalidated = []
    monkeypatch.setattr(package_install, "_SETUP_DEPENDENCIES", dependencies)
    monkeypatch.setattr(package_install, "_dependency_status", dependency_status)
    monkeypatch.setattr(
        package_install.subprocess,
        "run",
        lambda command, **kwargs: (
            run_calls.append(command) or completed_process(command)
        ),
    )
    monkeypatch.setattr(
        package_install.importlib,
        "invalidate_caches",
        lambda: invalidated.append(True),
    )
    monkeypatch.setattr(
        package_install.metadata.MetadataPathFinder,
        "invalidate_caches",
        classmethod(lambda _cls: metadata_invalidated.append(True)),
    )
    monkeypatch.setenv("LAGNIAPPE_NONINTERACTIVE", "1")

    assert package_install._requirement_version("redis[hiredis]==8.0.1") == (
        "redis",
        "8.0.1",
    )
    assert package_install.ensure_setup_dependencies()
    assert run_calls == [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--upgrade-strategy",
            "eager",
            "PyYAML==6.0.3",
            "requests==2.34.2",
        ],
        [sys.executable, "-m", "pip", "check"],
    ]
    assert invalidated == [True]
    assert metadata_invalidated == [True]
    assert status_calls == {"yaml": 2, "requests": 2}
    assert check_import_calls == [
        ("yaml", False),
        ("requests", False),
        ("yaml", True),
        ("requests", True),
    ]

    monkeypatch.setattr(
        package_install.subprocess,
        "run",
        lambda command, **kwargs: completed_process(
            command,
            returncode=1,
            stdout="broken dependency",
        ),
    )
    with pytest.raises(RuntimeError, match="broken dependency"):
        package_install._run_pip_check()


# @matrix setup : dependency-pins package-install
def test_setup_dependency_transaction_repairs_transitive_conflicts(monkeypatch):
    from installer import package_install

    dependencies = (("requests", "requests", "provider HTTP requests"),)
    status_calls = []
    check_calls = []
    install_calls = []

    monkeypatch.setattr(package_install, "_SETUP_DEPENDENCIES", dependencies)
    monkeypatch.setattr(
        package_install,
        "_dependency_status",
        lambda import_name, _package_name, *, check_import=True: (
            status_calls.append((import_name, check_import))
            or ("requests==2.34.2", True, "2.34.2")
        ),
    )

    def pip_check():
        check_calls.append(True)
        if len(check_calls) == 1:
            raise RuntimeError(
                "The Python environment has incompatible dependencies: "
                "downstream-package requires a newer transport"
            )

    monkeypatch.setattr(package_install, "_run_pip_check", pip_check)
    monkeypatch.setattr(
        package_install.subprocess,
        "run",
        lambda command, **_kwargs: (
            install_calls.append(command) or completed_process(command)
        ),
    )
    monkeypatch.setenv("LAGNIAPPE_NONINTERACTIVE", "1")

    assert package_install.ensure_setup_dependencies()
    assert install_calls == [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--upgrade-strategy",
            "eager",
            "requests==2.34.2",
        ]
    ]
    assert status_calls == [("requests", False), ("requests", True)]
    assert check_calls == [True, True]


# @matrix setup : encoding package-install portability spinner terminal-wrapping
def test_setup_formatter_tracks_active_spinners(monkeypatch):
    import installer as setup_pkg
    from installer import package_install

    package_install._ACTIVE_SPINNERS.clear()
    installs = []
    spinner = object()
    spinner_calls = []

    class Output:
        encoding = "ascii"

        def __init__(self):
            self.tty = True
            self.messages = []

        def isatty(self):
            return self.tty

        def write(self, message):
            self.messages.append(message)

        def flush(self):
            return None

    output = Output()

    class SpinnerContext:
        def __enter__(self):
            return spinner

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        package_install,
        "install_if_missing",
        lambda *args, **kwargs: installs.append((args, kwargs)),
    )
    monkeypatch.setitem(
        sys.modules,
        "colorama",
        types.SimpleNamespace(
            Fore=types.SimpleNamespace(RED="", YELLOW="", GREEN="", CYAN=""),
            Style=types.SimpleNamespace(RESET_ALL=""),
            just_fix_windows_console=lambda: None,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "yaspin",
        types.SimpleNamespace(
            yaspin=lambda **kwargs: spinner_calls.append(kwargs) or SpinnerContext()
        ),
    )
    monkeypatch.setattr(
        setup_pkg.sys,
        "stdout",
        output,
    )

    formatter = setup_pkg.Formatter().initialize()

    with formatter.yaspin(text="Configuring service account") as active_spinner:
        assert active_spinner is spinner
        assert package_install._ACTIVE_SPINNERS == [spinner]

    assert package_install._ACTIVE_SPINNERS == []
    assert formatter.ok_glyph == "[OK]"
    assert formatter.fail_glyph == "[X]"
    assert spinner_calls
    assert "disable" not in spinner_calls[0]
    animated_spinner_calls = len(spinner_calls)
    monkeypatch.setattr(setup_pkg, "_use_plain_progress", lambda stream=None: True)
    with formatter.yaspin(text="Windows progress") as windows_spinner:
        windows_spinner.ok(formatter.ok_glyph)
    assert len(spinner_calls) == animated_spinner_calls
    assert "Windows progress" in "".join(output.messages)
    output.tty = False
    with formatter.yaspin(text="Plain progress") as plain_spinner:
        plain_spinner.ok(formatter.ok_glyph)
    assert "Plain progress" in "".join(output.messages)
    assert "[OK]" in "".join(output.messages)
    wrapped = setup_pkg.wrap_text(
        "Operational summaries include model, token totals, duration, "
        "retry categories, and tool names.",
        width=42,
    )
    assert all(len(line) <= 42 for line in wrapped.splitlines())
    assert "totals," in wrapped
    assert "\n," not in wrapped
    assert setup_pkg.wrap_text(
        "First paragraph.\n\n  Indented paragraph with several words.\n"
        "• Bullet paragraph with several words.",
        width=24,
    ).splitlines() == [
        "First paragraph.",
        "",
        "  Indented paragraph",
        "  with several words.",
        "• Bullet paragraph with",
        "  several words.",
    ]
    assert installs == [
        (("yaspin", "progress indicator for the setup script"), {}),
        (("colorama", "colorizes setup script output"), {}),
    ]


# @matrix setup : package-install spinner
def test_install_if_missing_pauses_active_spinner_for_prompt(monkeypatch):
    from installer import package_install

    package_install._ACTIVE_SPINNERS.clear()
    events = []

    class PromptSpinner:
        def stop(self):
            events.append("stop")

        def start(self):
            events.append("start")

    spinner = PromptSpinner()

    class SpinnerContext:
        def __enter__(self):
            events.append("enter")
            return spinner

        def __exit__(self, exc_type, exc, tb):
            events.append("exit")
            return False

    def fake_yaspin(*args, **kwargs):
        events.append(("factory", args, kwargs))
        return SpinnerContext()

    class Tty:
        def isatty(self):
            return True

    def missing_import(name):
        raise ImportError(name)

    monkeypatch.delenv("LAGNIAPPE_NONINTERACTIVE", raising=False)
    monkeypatch.setattr(package_install.sys, "stdin", Tty())
    monkeypatch.setattr(package_install.importlib, "import_module", missing_import)
    monkeypatch.setattr(builtins, "input", lambda: events.append("input") or "y")
    monkeypatch.setattr(
        package_install,
        "_install",
        lambda package, name: events.append(("install", package, name)),
    )

    tracked_yaspin = package_install.track_spinner_factory(fake_yaspin)
    with tracked_yaspin(text="Configuring service account") as active_spinner:
        assert active_spinner is spinner
        assert package_install._ACTIVE_SPINNERS == [spinner]
        package_install.install_if_missing(
            "google.cloud.iam_admin_v1",
            "Google IAM Admin API",
            package_name="google-cloud-iam",
        )
        assert package_install._ACTIVE_SPINNERS == [spinner]

    assert package_install._ACTIVE_SPINNERS == []
    assert events == [
        ("factory", (), {"text": "Configuring service account"}),
        "enter",
        "stop",
        "input",
        ("install", "google-cloud-iam", "google.cloud.iam_admin_v1"),
        "start",
        "exit",
    ]


# @matrix setup : gcloud-command preflight provider-apis timeout
def test_enable_gcloud_apis_reuses_confirmed_preflight(monkeypatch):
    import installer as setup_pkg
    from installer import gcloud

    constants = _load_config_constants()
    settings = _fake_settings(gcloud={"PROJECT": "project-1"})
    settings._SETUP_ENABLED_GOOGLE_CLOUD_APIS = set(
        constants.REQUIRED_GOOGLE_CLOUD_APIS
    )
    _install_config_package(monkeypatch, constants, settings=settings)
    spinner = SpinnerRecorder()
    formatter = _fake_formatter(spinner)
    monkeypatch.setattr(setup_pkg, "FORMATTER", formatter)
    monkeypatch.setattr(gcloud, "FORMATTER", formatter)
    monkeypatch.setattr(gcloud, "constants", constants)

    calls = []
    mutations = []
    propagation_delays = []
    monkeypatch.setattr(
        gcloud.time,
        "sleep",
        lambda delay: propagation_delays.append(delay),
    )

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ["services", "list", "--enabled"]:
            return completed_process(
                command,
                stdout="\n".join(constants.REQUIRED_GOOGLE_CLOUD_APIS),
            )
        return completed_process(command)

    monkeypatch.setattr(gcloud, "run_gcloud_command", run)
    monkeypatch.setattr(
        gcloud,
        "record_mutation",
        lambda *args, **kwargs: mutations.append((args, kwargs)),
    )

    assert gcloud.enable_gcloud_apis()
    assert calls == []

    missing = "identitytoolkit.googleapis.com"
    settings._SETUP_ENABLED_GOOGLE_CLOUD_APIS.remove(missing)
    discovered = iter(
        [
            set(constants.REQUIRED_GOOGLE_CLOUD_APIS) - {missing},
            set(constants.REQUIRED_GOOGLE_CLOUD_APIS),
        ]
    )

    def run_with_propagation(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ["services", "list", "--enabled"]:
            return completed_process(
                command,
                stdout="\n".join(next(discovered)),
            )
        return completed_process(command)

    monkeypatch.setattr(gcloud, "run_gcloud_command", run_with_propagation)
    assert gcloud.enable_gcloud_apis()
    assert calls == [
        (
            [
                "services",
                "enable",
                missing,
                "--project=project-1",
            ],
            {
                "check": False,
                "timeout": gcloud.GCLOUD_SERVICE_ENABLE_TIMEOUT,
            },
        ),
        (
            [
                "services",
                "list",
                "--enabled",
                "--project=project-1",
                "--format=value(config.name)",
            ],
            {"timeout": gcloud.GCLOUD_SERVICE_DISCOVERY_TIMEOUT},
        ),
        (
            [
                "services",
                "list",
                "--enabled",
                "--project=project-1",
                "--format=value(config.name)",
            ],
            {"timeout": gcloud.GCLOUD_SERVICE_DISCOVERY_TIMEOUT},
        ),
    ]
    assert propagation_delays == [2]
    assert mutations[-1][1]["identifier"] == missing
    assert any("may take up to 5 minutes" in message for message in spinner.messages)

    del settings._SETUP_ENABLED_GOOGLE_CLOUD_APIS
    calls.clear()

    def list_enabled(command, **kwargs):
        calls.append((command, kwargs))
        return completed_process(
            command,
            stdout="\n".join(constants.REQUIRED_GOOGLE_CLOUD_APIS),
        )

    monkeypatch.setattr(gcloud, "run_gcloud_command", list_enabled)
    assert gcloud.enable_gcloud_apis()
    assert calls == [
        (
            [
                "services",
                "list",
                "--enabled",
                "--project=project-1",
                "--format=value(config.name)",
            ],
            {"timeout": gcloud.GCLOUD_SERVICE_DISCOVERY_TIMEOUT},
        )
    ]


# @matrix setup : browser error-guidance google-service-terms identity interactive-input provider-apis
def test_enable_gcloud_apis_guides_maps_terms_then_retries_activation(
    monkeypatch,
    capsys,
):
    import installer as setup_pkg
    from installer import gcloud

    constants = _load_config_constants()
    settings = _fake_settings(
        app={"ADMIN_EMAIL": "owner@business.example"},
        gcloud={
            "ACCOUNT": "installer@business.example",
            "PROJECT": "project-1",
        },
    )
    settings._SETUP_ENABLED_GOOGLE_CLOUD_APIS = set(
        constants.REQUIRED_GOOGLE_CLOUD_APIS
    ) - {"places.googleapis.com"}
    _install_config_package(monkeypatch, constants, settings=settings)
    spinner = SpinnerRecorder()
    formatter = _fake_formatter(spinner)
    monkeypatch.setattr(setup_pkg, "FORMATTER", formatter)
    monkeypatch.setattr(gcloud, "FORMATTER", formatter)
    monkeypatch.setattr(gcloud, "constants", constants)
    provider_detail = (
        "ERROR: FAILED_PRECONDITION: The terms of service 'maps' for "
        "places.googleapis.com must be accepted. tos_id=maps "
        "reason: UREQ_TOS_NOT_ACCEPTED Help Token: do-not-print"
    )
    calls = []
    enabled_attempts = 0

    def run(command, **kwargs):
        nonlocal enabled_attempts
        calls.append((command, kwargs))
        if command[:2] == ["services", "enable"]:
            enabled_attempts += 1
            if enabled_attempts == 1:
                return completed_process(
                    command,
                    returncode=1,
                    stderr=provider_detail,
                )
            return completed_process(command)
        return completed_process(
            command,
            stdout="\n".join(constants.REQUIRED_GOOGLE_CLOUD_APIS),
        )

    monkeypatch.setattr(
        gcloud,
        "run_gcloud_command",
        run,
    )
    opened = []
    monkeypatch.setattr(
        gcloud.webbrowser,
        "open_new_tab",
        lambda url: opened.append(url) or True,
    )
    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "",
    )
    mutations = []
    monkeypatch.setattr(
        gcloud,
        "record_mutation",
        lambda *args, **kwargs: mutations.append((args, kwargs)),
    )

    assert gcloud.enable_gcloud_apis()
    output = " ".join(capsys.readouterr().out.split())
    assert "installer@business.example" in output
    assert "owner@business.example" in output
    assert "Owner does not need to enable Places API manually" in output
    assert "Help Token" not in output
    assert opened == ["https://console.developers.google.com/terms/maps"]
    assert len(prompts) == 1
    assert "retry API activation" in prompts[0]
    assert spinner.stops == 1
    assert spinner.starts == 1
    assert mutations[-1][1]["identifier"] == "places.googleapis.com"
    assert calls == [
        (
            [
                "services",
                "enable",
                "places.googleapis.com",
                "--project=project-1",
            ],
            {
                "check": False,
                "timeout": gcloud.GCLOUD_SERVICE_ENABLE_TIMEOUT,
            },
        ),
        (
            [
                "services",
                "enable",
                "places.googleapis.com",
                "--project=project-1",
            ],
            {
                "check": False,
                "timeout": gcloud.GCLOUD_SERVICE_ENABLE_TIMEOUT,
            },
        ),
        (
            [
                "services",
                "list",
                "--enabled",
                "--project=project-1",
                "--format=value(config.name)",
            ],
            {"timeout": gcloud.GCLOUD_SERVICE_DISCOVERY_TIMEOUT},
        ),
    ]


# @matrix setup : deploy failure gcloud-command progress
def test_setup_prerequisite_gcloud_and_deploy_helpers(monkeypatch, capsys):
    import installer as setup_pkg
    from installer import utils
    from installer.domain import gcp as domain_gcp

    monkeypatch.setattr(utils, "GCLOUD_CLI", None)
    with pytest.raises(SetupError):
        utils.check_gcloud_cli()

    monkeypatch.setattr(utils, "GCLOUD_CLI", "gcloud")
    utils.check_gcloud_cli()

    run_calls = []

    def successful_run(command, **kwargs):
        run_calls.append((command, kwargs))
        return completed_process(command, stdout="ok")

    monkeypatch.setattr(utils.subprocess, "run", successful_run)

    assert utils.run_gcloud_command(["config", "list"]).stdout == "ok"
    assert run_calls == [
        (
            ["gcloud", "config", "list"],
            {
                "capture_output": True,
                "stdin": subprocess.DEVNULL,
                "text": True,
                "check": True,
                "timeout": utils.GCLOUD_TIMEOUT,
            },
        )
    ]

    error = subprocess.CalledProcessError(
        2, ["gcloud", "bad"], output="", stderr="bad command"
    )
    monkeypatch.setattr(
        utils.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    assert utils.run_gcloud_command(["bad"], check=False) is error
    with pytest.raises(ProviderError):
        utils.run_gcloud_command(["bad"], check=True)

    deploy_commands = []
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(
            SETTINGS=_fake_settings(
                app={"CUSTOM_DOMAIN": "app.example.com"},
                gcloud={"PROJECT": "project-1"},
            )
        ),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (_ for _ in ()).throw(
            AssertionError("deploy helper should not prompt")
        ),
    )
    monkeypatch.setattr(
        utils,
        "run_gcloud_command",
        lambda command, check=True: (
            deploy_commands.append((command, check)) or completed_process(command)
        ),
    )
    deployment_spinner = SpinnerRecorder()
    deployment_progress = []
    initialized_formatter = _fake_formatter(deployment_spinner).initialize()
    initialized_formatter.yaspin = lambda **kwargs: (
        deployment_progress.append(kwargs["text"]) or nullcontext(deployment_spinner)
    )
    monkeypatch.setattr(
        setup_pkg,
        "FORMATTER",
        types.SimpleNamespace(initialize=lambda: initialized_formatter),
    )
    monkeypatch.setattr(
        utils,
        "print_summary",
        lambda: deploy_commands.append("summary"),
    )
    monkeypatch.setattr(
        domain_gcp,
        "wait_for_managed_certificate",
        lambda domain: deploy_commands.append(("certificate", domain)),
    )
    deploy_module = types.ModuleType("runner.deploy")
    deploy_module.deploy = lambda **kwargs: deploy_commands.append(("deploy", kwargs))
    monkeypatch.setitem(sys.modules, "runner.deploy", deploy_module)

    capsys.readouterr()
    utils.deploy_to_app_engine()

    assert capsys.readouterr().out == "Deployment complete!\n"
    assert deployment_progress == [
        "Deploy App Engine indexes and application (may take up to 10 minutes)"
    ]
    assert deployment_spinner.oks == ["[OK]"]
    assert deployment_spinner.fails == []
    assert deploy_commands == [
        (
            "deploy",
            {
                "build_assets": False,
                "deploy_indexes": True,
                "quiet": True,
                "capture_output": True,
                "announce_progress": False,
                "announce_completion": False,
            },
        ),
        ("certificate", "app.example.com"),
        "summary",
    ]

    deploy_module.deploy = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("provider deployment failed")
    )
    with pytest.raises(RuntimeError, match="provider deployment failed"):
        utils.deploy_to_app_engine(print_final_summary=False)
    assert deployment_spinner.oks == ["[OK]"]
    assert deployment_spinner.fails == ["[X]"]


# @pairs migrations:deploy setup:legacy-upgrade setup:major-version
def test_legacy_upgrade_warning_can_cancel_before_provider_deploy(
    monkeypatch,
    capsys,
):
    import installer as setup_pkg
    from installer import state, utils

    settings = _fake_settings(
        app={"VERSION": "1.0.0"},
        node={"version": "1.0.0"},
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    monkeypatch.setattr(
        state,
        "_ACTIVE_JOURNAL",
        types.SimpleNamespace(payload={"mode": "upgrade"}),
    )
    formatter = _fake_formatter().initialize()
    monkeypatch.setattr(
        setup_pkg,
        "FORMATTER",
        types.SimpleNamespace(initialize=lambda: formatter),
    )
    deploy_calls = []
    deploy_module = types.ModuleType("runner.deploy")
    deploy_module.deploy = lambda **kwargs: deploy_calls.append(kwargs)
    monkeypatch.setitem(sys.modules, "runner.deploy", deploy_module)

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    with pytest.raises(SetupCancelled, match="currently deployed application"):
        utils.deploy_to_app_engine(print_final_summary=False)
    assert deploy_calls == []
    output = capsys.readouterr().out
    assert "Required post-upgrade maintenance" in output
    assert "Apply Updates" in output
    assert "Refresh Cache" in output

    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    utils.deploy_to_app_engine(print_final_summary=False)
    output = capsys.readouterr().out
    assert len(deploy_calls) == 1
    assert "Required next steps" in output
    assert "  4. Select Refresh Cache." in output


# @matrix deferred-jobs setup : cloud-scheduler iam oidc recovery runtime-isolation
def test_setup_deferred_job_reconciler_contract(monkeypatch):
    import installer as setup_pkg
    from installer import gcloud

    constants = _load_config_constants()
    settings = _fake_settings(
        app={
            "APP_URL": "https://project-1.appspot.com/",
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
                "app-runtime@project-1.iam.gserviceaccount.com"
            ),
            "RESOURCE_REGION": "us-central1",
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
                "app-runtime@project-1.iam.gserviceaccount.com"
            ),
        },
        gcloud={"PROJECT": "project-1", "ACCOUNT": "deployer@example.com"},
    )
    _install_config_package(monkeypatch, constants, settings=settings)
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(gcloud, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(gcloud, "constants", constants)

    commands = []
    iam_calls = []
    existing_returncode = 1

    def fake_run(command, check=True):
        commands.append((command, check))
        if command[:2] == ["projects", "describe"]:
            return completed_process(command, stdout="123456789\n")
        if command[:3] == ["scheduler", "jobs", "describe"]:
            return completed_process(
                command,
                returncode=existing_returncode,
                stderr="not found" if existing_returncode else "",
            )
        return completed_process(command)

    monkeypatch.setattr(gcloud, "run_gcloud_command", fake_run)
    monkeypatch.setattr(
        gcloud,
        "configure_data_protection",
        lambda: (_ for _ in ()).throw(
            AssertionError("deferred-job setup must not configure data protection")
        ),
    )
    monkeypatch.setattr(
        gcloud.iam_access,
        "reconcile_project_service_agent",
        lambda *args: iam_calls.append(("project", args)),
    )
    monkeypatch.setattr(
        gcloud.iam_access,
        "reconcile_runtime_service_account_policy",
        lambda *args: iam_calls.append(("service-account", args)),
    )

    assert gcloud.create_deferred_job_reconciler()
    assert commands[0][0] == [
        "services",
        "enable",
        "cloudscheduler.googleapis.com",
        "--project=project-1",
    ]
    assert not any(command[:1] == ["beta"] for command, _check in commands)
    assert iam_calls[:2] == [
        (
            "project",
            (
                "project-1",
                "serviceAccount:service-123456789"
                "@gcp-sa-cloudscheduler.iam.gserviceaccount.com",
                "roles/cloudscheduler.serviceAgent",
            ),
        ),
        (
            "service-account",
            (
                "project-1",
                "app-runtime@project-1.iam.gserviceaccount.com",
                "deployer@example.com",
            ),
        ),
    ]
    assert not any(
        command[:2] == ["projects", "add-iam-policy-binding"]
        or command[:3] == ["iam", "service-accounts", "add-iam-policy-binding"]
        for command, _check in commands
    )
    scheduler = next(
        command
        for command, _check in commands
        if command[:4] == ["scheduler", "jobs", "create", "http"]
    )
    assert scheduler[:6] == [
        "scheduler",
        "jobs",
        "create",
        "http",
        "lagniappe-deferred-jobs-reconciler",
        "--location=us-central1",
    ]
    assert "--schedule=*/5 * * * *" in scheduler
    assert "--uri=https://project-1.appspot.com/process/jobs/reconcile" in scheduler
    assert "--headers=Content-Type=application/json" in scheduler
    assert '--message-body={"reconcile":true}' in scheduler
    assert (
        "--oidc-service-account-email=app-runtime@project-1.iam.gserviceaccount.com"
    ) in scheduler
    assert not any(
        "roles/cloudscheduler.admin" in part
        for command, _check in commands
        for part in command
    )

    commands.clear()
    existing_returncode = 0
    assert gcloud.create_deferred_job_reconciler()
    scheduler = next(
        command
        for command, _check in commands
        if command[:4] == ["scheduler", "jobs", "update", "http"]
    )
    assert scheduler[:5] == [
        "scheduler",
        "jobs",
        "update",
        "http",
        "lagniappe-deferred-jobs-reconciler",
    ]
    assert "--update-headers=Content-Type=application/json" in scheduler
    assert not any(part.startswith("--headers=") for part in scheduler)
    assert not any(command[:1] == ["firestore"] for command, _check in commands)


# @matrix disaster-recovery setup : idempotent native-backups pitr retention runtime-isolation
def test_setup_data_protection_contract(monkeypatch):
    from installer import gcloud

    constants = _load_config_constants()
    assert "firestore.googleapis.com" in constants.REQUIRED_GOOGLE_CLOUD_APIS
    settings = _fake_settings(gcloud={"PROJECT": "project-1"})
    _install_config_package(monkeypatch, constants, settings=settings)

    commands = []
    mutations = []
    schedules = []
    pitr_attempts = 0
    propagation_delays = []
    monkeypatch.setattr(
        gcloud.time,
        "sleep",
        lambda delay: propagation_delays.append(delay),
    )

    def fake_run(command, check=True):
        nonlocal pitr_attempts
        commands.append((command, check))
        if command[:3] == ["firestore", "databases", "update"]:
            pitr_attempts += 1
            if pitr_attempts == 1:
                raise RuntimeError("SERVICE_DISABLED: Firestore is propagating")
        if command[:4] == ["firestore", "backups", "schedules", "list"]:
            return completed_process(command, stdout=json.dumps(schedules))
        return completed_process(command)

    monkeypatch.setattr(gcloud, "run_gcloud_command", fake_run)
    monkeypatch.setattr(
        gcloud,
        "record_mutation",
        lambda *args, **kwargs: mutations.append((args, kwargs)),
    )

    assert gcloud.configure_data_protection()
    assert pitr_attempts == 2
    assert propagation_delays == [2]
    assert any(
        command[:3] == ["firestore", "databases", "update"]
        and "--enable-pitr" in command
        for command, _check in commands
    )
    backup_schedules = [
        command
        for command, _check in commands
        if command[:4] == ["firestore", "backups", "schedules", "create"]
    ]
    assert any(
        "--recurrence=daily" in command and "--retention=14d" in command
        for command in backup_schedules
    )
    assert any(
        "--recurrence=weekly" in command
        and "--day-of-week=SUN" in command
        and "--retention=98d" in command
        for command in backup_schedules
    )
    assert mutations[-1][1]["identifier"] == "project-1/(default)"

    commands.clear()
    schedules.extend(
        [
            {
                "name": "projects/project-1/databases/(default)/backupSchedules/daily-1",
                "dailyRecurrence": {},
            },
            {
                "name": "projects/project-1/databases/(default)/backupSchedules/weekly-1",
                "weeklyRecurrence": {},
            },
        ]
    )

    assert gcloud.configure_data_protection()
    updates = [
        command
        for command, _check in commands
        if command[:4] == ["firestore", "backups", "schedules", "update"]
    ]
    assert any(
        "--backup-schedule=daily-1" in command and "--retention=14d" in command
        for command in updates
    )
    assert any(
        "--backup-schedule=weekly-1" in command and "--retention=98d" in command
        for command in updates
    )


# @matrix setup : admin ai-model ai-observability identity-platform oauth optional privacy-consent redis redis-tls settings-save
def test_setup_settings_mutation_flows(monkeypatch, capsys):
    constants = _load_config_constants()
    settings = _fake_settings(
        app={
            "GOOGLE_LOGIN_URI": ("https://project-1.appspot.com/users/google-signin"),
        }
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    from installer import admin
    from installer import identity
    from installer import optional
    from installer import redis as redis_setup

    monkeypatch.setattr(optional, "FORMATTER", _fake_formatter())

    monkeypatch.setattr(admin, "_get_admin_name", lambda: "Owner")
    monkeypatch.setattr(admin, "_get_admin_email", lambda: "owner@example.com")
    monkeypatch.setattr(admin, "print_oauth_instructions", lambda: None)
    monkeypatch.setattr(
        admin,
        "_get_verified_oauth_credentials",
        lambda _settings: (
            "1234-demo.apps.googleusercontent.com",
            "oauth-secret",
        ),
    )
    provider_calls = []
    monkeypatch.setattr(
        identity,
        "setup_google_provider",
        lambda client_id, client_secret=None: (
            provider_calls.append((client_id, client_secret)) or True
        ),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    admin.setup_admin_and_oauth()

    assert settings.APP == {
        "GOOGLE_LOGIN_URI": ("https://project-1.appspot.com/users/google-signin"),
        "ADMIN_NAME": "Owner",
        "ADMIN_EMAIL": "owner@example.com",
        "GOOGLE_SIGNIN_ENABLED": True,
        "GOOGLE_CLIENT_ID": "1234-demo.apps.googleusercontent.com",
    }
    assert len(settings._saves) == 2
    assert provider_calls == [("1234-demo.apps.googleusercontent.com", "oauth-secret")]
    admin_output = " ".join(capsys.readouterr().out.split())
    assert "Lagniappe runtime does" in admin_output
    assert "not need" in admin_output
    assert "delete the local JSON or move it to secure storage" in admin_output
    assert "./setup.sh oauth" in admin_output

    settings.APP.clear()
    settings._saves.clear()
    monkeypatch.setattr(
        redis_setup,
        "_get_redis_connection_details",
        lambda: {
            "host": "redis-123.redislabs.com",
            "port": 12345,
            "password": "secret",
        },
    )
    monkeypatch.setattr(redis_setup, "redis_cloud_instructions", lambda: None)
    monkeypatch.setattr(redis_setup, "eviction_policy_instructions", lambda: None)
    monkeypatch.setattr(redis_setup, "_offer_redis_tls_for_fresh_install", lambda: None)
    monkeypatch.setattr(redis_setup, "test_redis_connection", lambda: True)

    redis_setup.setup_redis()

    assert settings.APP == {
        "REDIS_HOST": "redis-123.redislabs.com",
        "REDIS_PORT": 12345,
        "REDIS_PASSWORD": "secret",
        "REDIS_TLS": False,
    }
    assert len(settings._saves) == 1

    settings.APP.clear()
    settings._saves.clear()

    settings.GCLOUD_CONFIG["PROJECT"] = "project-1"
    settings.APP["APP_URL"] = "https://project-1.example"
    monkeypatch.setattr(identity, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(identity, "_get_access_token", lambda: "token")
    reconciled_auth = {
        "subtype": "IDENTITY_PLATFORM",
        "client": {"apiKey": "identity-key"},
        "signIn": {"email": {"enabled": True, "passwordRequired": True}},
        "authorizedDomains": ["project-1.example"],
        "notification": {
            "sendEmail": {
                "callbackUri": "https://project-1.example/users/login",
            }
        },
    }
    auth_reconciliations = []
    monkeypatch.setattr(
        identity,
        "reconcile_identity_platform",
        lambda session, project_id, headers, app_url: (
            auth_reconciliations.append((project_id, headers, app_url))
            or reconciled_auth
        ),
    )

    assert identity.setup_identity_platform()
    assert settings.APP["IDENTITY_PLATFORM_CONFIG"] == {
        "apiKey": "identity-key",
        "projectId": "project-1",
    }
    assert auth_reconciliations == [
        (
            "project-1",
            {
                "Authorization": "Bearer token",
                "x-goog-user-project": "project-1",
            },
            "https://project-1.example",
        )
    ]

    settings.APP.update(
        {
            "SENTRY_DSN": "old",
            "SENTRY_JS_DSN": "old-js",
            "AI_MODEL": "gemini-old",
            "AI_UTILITY_MODEL": "gemini-utility-old",
            "AI_IMAGE_MODEL": "imagen-old",
        }
    )
    settings._saves.clear()
    answers = iter(
        [
            "n",
            "n",
            "y",
            "gemini-new",
            "y",
            "gemini-utility-new",
            "y",
            "imagen-new",
            "y",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    optional.setup_error_monitoring()
    optional.change_ai_model()
    setup_output = capsys.readouterr().out

    assert settings.APP["CAPTURE_ERRORS"] == "False"
    assert "SENTRY_DSN" not in settings.APP
    assert "SENTRY_JS_DSN" not in settings.APP
    assert "Form and JSON values, request/response bodies" in setup_output
    assert "Recognized password, token, API-key, and private-key values" in setup_output
    assert "Reports are privacy-reduced, not guaranteed to be anonymous" in setup_output
    assert "the submitted fields may be included" not in setup_output
    assert settings.APP["AI_MODEL"] == "gemini-new"
    assert settings.APP["AI_UTILITY_MODEL"] == "gemini-utility-new"
    assert settings.APP["AI_LOCATION"] == "global"
    assert settings.APP["AI_IMAGE_MODEL"] == "imagen-new"
    assert settings.APP["AI_OBSERVABILITY"] is True
    assert len(settings._saves) == 2


# @matrix setup : admin disabled-provider oauth optional settings-save
def test_disabled_google_signin_skips_oauth_setup(monkeypatch, capsys):
    constants = _load_config_constants()
    settings = _fake_settings(
        app={
            "ADMIN_NAME": "Owner",
            "ADMIN_EMAIL": "owner@example.com",
            "GOOGLE_SIGNIN_ENABLED": False,
            "GOOGLE_CLIENT_ID": "retained-client.apps.googleusercontent.com",
        }
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    from installer import admin, identity

    monkeypatch.setattr(
        admin,
        "print_oauth_instructions",
        lambda: pytest.fail("disabled Google sign-in must skip OAuth instructions"),
    )
    monkeypatch.setattr(
        identity,
        "setup_google_provider",
        lambda *_args, **_kwargs: pytest.fail(
            "disabled Google sign-in must skip provider reconciliation"
        ),
    )

    assert admin.setup_admin_and_oauth()
    assert settings.APP["GOOGLE_CLIENT_ID"].startswith("retained-client")
    assert settings._saves == []
    assert "Skipping Google OAuth" in capsys.readouterr().out


# @matrix setup : browser oauth provider-apis
def test_oauth_instructions_open_current_project_clients_page(
    monkeypatch,
    capsys,
):
    constants = _load_config_constants()
    settings = _fake_settings(
        app={
            "APP_NAME": "Demo Lagniappe",
            "APP_URL": "https://demo.uc.r.appspot.com",
            "CUSTOM_DOMAIN": "app.example.com",
            "GOOGLE_LOGIN_URI": ("https://app.example.com/users/google-signin"),
        },
        gcloud={
            "PROJECT": "demo-project",
            "ACCOUNT": "operator@example.com",
        },
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    from installer import admin

    opened = []
    monkeypatch.setattr(
        admin.webbrowser,
        "open_new_tab",
        lambda url: opened.append(url) or True,
    )

    admin.print_oauth_instructions()

    assert opened == [
        "https://console.cloud.google.com/auth/clients?project=demo-project"
    ]
    output = capsys.readouterr().out
    assert "Identity Platform is ready" in output
    assert "Required browser account: operator@example.com" in output
    assert "switch the" in output
    assert "browser to this account and reload the page" in output
    assert "setup already verified this" in output
    assert "account's project permissions" in output
    assert "secret will not be saved" in output
    assert "in Lagniappe settings" in output
    assert "click 'Get started'" in output
    assert "Audience: choose 'External'" in output
    assert "For a new or replacement client, click 'Create client'" in output
    assert "For secret rotation" in output
    assert "Authorized JavaScript origin: https://app.example.com" in output
    assert (
        "Authorized redirect URI: https://app.example.com/users/google-signin"
    ) in output
    assert "client type must" in output
    assert "say 'Web application'; a 'Desktop app' client will not" in output
    assert "work" in output
    assert "click 'Download JSON'" in output
    assert "google_oauth_credentials.json" in output
    assert str(admin.OAUTH_CLIENT_FILE) in output


# @matrix setup : credential-file oauth retention rotation secrets
def test_oauth_credential_retention_message(tmp_path, capsys):
    from installer import admin

    credential_path = tmp_path / "google_oauth_credentials.json"
    admin._print_oauth_file_retention_message(credential_path)

    output = capsys.readouterr().out
    assert str(credential_path) in output
    assert "Lagniappe runtime does" in output
    assert "not need" in output
    assert "delete the local JSON or move it to secure storage" in output
    assert "excluded from Git and App Engine uploads" in output
    assert "./setup.sh oauth" in output


# @matrix setup : client-type oauth provider-apis redirect-uri validation
def test_oauth_web_client_probe_accepts_exact_callback():
    from installer import admin

    calls = []

    def request_get(url, **kwargs):
        calls.append((url, kwargs))
        return types.SimpleNamespace(
            status_code=302,
            text="",
            headers={"Location": "https://accounts.google.com/v3/signin"},
        )

    redirect_uri = "https://project-1.appspot.com/users/google-signin"
    assert admin.verify_oauth_web_client(
        "1234-demo.apps.googleusercontent.com",
        redirect_uri,
        request_get=request_get,
    )

    assert calls[0][0] == admin.GOOGLE_OAUTH_AUTHORIZE_URL
    assert calls[0][1]["params"]["redirect_uri"] == redirect_uri
    assert calls[0][1]["params"]["response_type"] == "code"
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["timeout"] == admin.OAUTH_CLIENT_PROBE_TIMEOUT


# @matrix setup : client-type failure-isolation oauth redirect-uri validation
def test_oauth_web_client_probe_rejects_redirect_mismatch():
    from installer import admin

    def request_get(_url, **_kwargs):
        return types.SimpleNamespace(
            status_code=302,
            text="",
            headers={
                "Location": (
                    "https://accounts.google.com/signin/oauth/error"
                    "?authError=encoded-provider-detail"
                )
            },
        )

    redirect_uri = "https://project-1.appspot.com/users/google-signin"
    with pytest.raises(
        ProviderInvalidInput,
        match="may not be a Web application client",
    ) as failure:
        admin.verify_oauth_web_client(
            "1234-desktop.apps.googleusercontent.com",
            redirect_uri,
            request_get=request_get,
        )

    assert redirect_uri in str(failure.value)
    assert "./setup.sh oauth" in failure.value.repair_action
    assert "google_oauth_credentials.json" in failure.value.repair_action


# @matrix setup : client-type credential-file javascript-origin oauth project-isolation redirect-uri secrets validation
def test_oauth_credentials_file_requires_web_project_and_exact_urls(tmp_path):
    from installer import admin

    credential_path = tmp_path / "google_oauth_credentials.json"
    expected = {
        "project_id": "project-1",
        "javascript_origin": "https://project-1.appspot.com",
        "redirect_uri": "https://project-1.appspot.com/users/google-signin",
    }
    web = {
        "client_id": "1234-web.apps.googleusercontent.com",
        "client_secret": "oauth-secret",
        "project_id": expected["project_id"],
        "javascript_origins": [expected["javascript_origin"]],
        "redirect_uris": [expected["redirect_uri"]],
    }
    credential_path.write_text(json.dumps({"web": web}), encoding="utf-8")

    assert admin.load_oauth_client_credentials(
        credential_path,
        **expected,
    ) == ("1234-web.apps.googleusercontent.com", "oauth-secret")

    invalid_payloads = (
        (
            {"installed": web},
            "not for a Web application client.*Desktop app",
        ),
        (
            {"web": {**web, "project_id": "other-project"}},
            "belongs to project 'other-project'",
        ),
        (
            {"web": {**web, "javascript_origins": ["https://wrong.example"]}},
            "required Authorized JavaScript origin",
        ),
        (
            {"web": {**web, "redirect_uris": ["https://wrong.example/login"]}},
            "required Authorized redirect URI",
        ),
    )
    for payload, message in invalid_payloads:
        credential_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ProviderInvalidInput, match=message):
            admin.load_oauth_client_credentials(
                credential_path,
                **expected,
            )


# @matrix setup : credential-file interactive-retry oauth propagation secrets
def test_oauth_credentials_file_retry_reloads_or_waits_for_propagation(
    monkeypatch,
    tmp_path,
    capsys,
):
    import installer as setup_package
    from installer import admin

    monkeypatch.setattr(setup_package, "FORMATTER", _fake_formatter())
    credential_path = tmp_path / "google_oauth_credentials.json"
    settings = _fake_settings(
        app={
            "APP_URL": "https://project-1.appspot.com",
            "GOOGLE_LOGIN_URI": ("https://project-1.appspot.com/users/google-signin"),
        },
        gcloud={
            "PROJECT": "project-1",
            "ACCOUNT": "operator@example.com",
        },
    )
    first_credentials = (
        "1234-first.apps.googleusercontent.com",
        "first-secret",
    )
    second_credentials = (
        "1234-second.apps.googleusercontent.com",
        "second-secret",
    )
    load_results = iter(
        (
            ProviderInvalidInput("JSON file is not present."),
            first_credentials,
            second_credentials,
        )
    )
    load_calls = []

    def load(path, **requirements):
        load_calls.append((path, requirements))
        result = next(load_results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(admin, "load_oauth_client_credentials", load)
    verification_calls = []

    def verify(client_id, redirect_uri):
        verification_calls.append((client_id, redirect_uri))
        if len(verification_calls) == 1:
            raise ProviderInvalidInput("Google rejected the callback.")
        return True

    monkeypatch.setattr(admin, "verify_oauth_web_client", verify)
    choices = iter(("", "", "r"))
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(choices)

    monkeypatch.setattr("builtins.input", answer)

    assert (
        admin._get_verified_oauth_credentials(
            settings,
            credential_path,
        )
        == second_credentials
    )
    assert len(load_calls) == 3
    assert all(call[0] == credential_path for call in load_calls)
    assert load_calls[-1][1] == {
        "project_id": "project-1",
        "javascript_origin": "https://project-1.appspot.com",
        "redirect_uri": "https://project-1.appspot.com/users/google-signin",
    }
    assert verification_calls == [
        (
            "1234-first.apps.googleusercontent.com",
            "https://project-1.appspot.com/users/google-signin",
        ),
        (
            "1234-second.apps.googleusercontent.com",
            "https://project-1.appspot.com/users/google-signin",
        ),
    ]
    output = capsys.readouterr().out
    assert str(credential_path) in output
    assert "Complete the Google Auth Platform browser steps" in prompts[0]
    assert "signed in as 'operator@example.com'" in prompts[0]
    assert "press Enter to verify it" in prompts[0]
    assert "already matches" in output
    assert "Google may still be applying" in output


# @matrix setup : client-type failure-isolation identity-platform oauth redirect-uri
def test_admin_oauth_rejection_precedes_provider_update(monkeypatch):
    constants = _load_config_constants()
    settings = _fake_settings(
        app={
            "ADMIN_NAME": "Owner",
            "ADMIN_EMAIL": "owner@example.com",
            "GOOGLE_SIGNIN_ENABLED": True,
            "GOOGLE_LOGIN_URI": ("https://project-1.appspot.com/users/google-signin"),
        }
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    from installer import admin, identity

    monkeypatch.setattr(admin, "print_oauth_instructions", lambda: None)
    monkeypatch.setattr(
        admin,
        "_get_verified_oauth_credentials",
        lambda _settings: (_ for _ in ()).throw(
            ProviderInvalidInput("Desktop client rejected.")
        ),
    )
    provider_calls = []
    monkeypatch.setattr(
        identity,
        "setup_google_provider",
        lambda *args: provider_calls.append(args),
    )

    with pytest.raises(ProviderInvalidInput, match="Desktop client rejected"):
        admin.setup_admin_and_oauth()

    assert provider_calls == []
    assert "GOOGLE_CLIENT_ID" not in settings.APP
    assert settings._saves == []


# @matrix setup : client-type identity-platform interactive-retry oauth settings-save
def test_existing_admin_oauth_can_replace_rejected_saved_client(monkeypatch):
    constants = _load_config_constants()
    settings = _fake_settings(
        app={
            "ADMIN_NAME": "Owner",
            "ADMIN_EMAIL": "owner@example.com",
            "GOOGLE_LOGIN_URI": ("https://project-1.appspot.com/users/google-signin"),
            "GOOGLE_CLIENT_ID": "1234-old.apps.googleusercontent.com",
        }
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    from installer import admin, identity

    monkeypatch.setattr(admin, "verify_oauth_web_client", lambda *_args: True)
    monkeypatch.setattr(admin, "print_oauth_instructions", lambda: None)
    monkeypatch.setattr(
        admin,
        "_get_verified_oauth_credentials",
        lambda _settings: (
            "1234-new.apps.googleusercontent.com",
            "new-secret",
        ),
    )
    monkeypatch.setattr(admin, "_print_oauth_file_retention_message", lambda: None)
    provider_calls = []

    def setup_provider(client_id, secret=None):
        provider_calls.append((client_id, secret))
        if secret is None:
            raise ProviderInvalidInput("The replacement secret is required.")
        return True

    monkeypatch.setattr(identity, "setup_google_provider", setup_provider)

    admin.setup_admin_and_oauth()

    assert provider_calls == [
        ("1234-old.apps.googleusercontent.com", None),
        ("1234-new.apps.googleusercontent.com", "new-secret"),
    ]
    assert settings.APP["GOOGLE_CLIENT_ID"] == ("1234-new.apps.googleusercontent.com")
    assert settings.APP["GOOGLE_SIGNIN_ENABLED"] is True
    assert settings._saves == [True, True]


# @matrix setup : cli client-type deploy identity-platform oauth redirect-uri settings-save
def test_oauth_cli_replaces_settings_and_deploys(monkeypatch):
    import config
    import installer as setup_package
    from installer import admin, identity, utils, verify

    settings = _fake_settings(
        app={
            "APP_NAME": "Demo Lagniappe",
            "APP_URL": "https://project-1.appspot.com",
            "GOOGLE_LOGIN_URI": ("https://project-1.appspot.com/users/google-signin"),
            "GOOGLE_CLIENT_ID": "1234-old.apps.googleusercontent.com",
        },
        gcloud={"PROJECT": "project-1"},
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(setup_package, "FORMATTER", _fake_formatter())

    events = []
    monkeypatch.setattr(
        verify,
        "prepare_existing_installation",
        lambda: events.append("verify-installation"),
    )
    monkeypatch.setattr(admin, "print_oauth_instructions", lambda: None)
    monkeypatch.setattr(
        admin,
        "_get_verified_oauth_credentials",
        lambda _settings: (
            "1234-web.apps.googleusercontent.com",
            "new-secret",
        ),
    )
    monkeypatch.setattr(admin, "_print_oauth_file_retention_message", lambda: None)
    monkeypatch.setattr(
        identity,
        "setup_google_provider",
        lambda client_id, secret: (
            events.append(("provider", client_id, secret)) or True
        ),
    )
    monkeypatch.setattr(
        utils,
        "deploy_to_app_engine",
        lambda: events.append("deploy"),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    assert admin.configure_oauth() == 0
    assert settings.APP["GOOGLE_CLIENT_ID"] == ("1234-web.apps.googleusercontent.com")
    assert settings.APP["GOOGLE_SIGNIN_ENABLED"] is True
    assert settings._saves == [True]
    assert events == [
        "verify-installation",
        (
            "provider",
            "1234-web.apps.googleusercontent.com",
            "new-secret",
        ),
        "deploy",
    ]


# @matrix iam setup : identity
def test_iam_principal_member_classifies_google_identities():
    from installer import iam

    assert iam.principal_member("deployer@example.com") == "user:deployer@example.com"
    assert (
        iam.principal_member("runtime@project-1.iam.gserviceaccount.com")
        == "serviceAccount:runtime@project-1.iam.gserviceaccount.com"
    )


# @matrix iam setup : conditions etag idempotence unrelated-members
def test_iam_reconciliation_is_idempotent_and_preserves_conditions_and_etag():
    from google.api_core.iam import Policy
    from installer import iam

    runtime = "serviceAccount:runtime@project-1.iam.gserviceaccount.com"
    conditional = {
        "title": "temporary",
        "description": "operator-owned",
        "expression": "request.time < timestamp('2030-01-01T00:00:00Z')",
    }
    policy = Policy(etag=b"provider-etag", version=3)
    policy.bindings = [
        {
            "role": "roles/legacy",
            "members": {runtime, "user:other@example.com"},
        },
        {
            "role": "roles/runtime",
            "members": {"group:operators@example.com", runtime},
        },
        {
            "role": "roles/runtime",
            "members": {"serviceAccount:other@project-1.iam.gserviceaccount.com"},
        },
        {
            "role": "roles/legacy",
            "members": {runtime},
            "condition": conditional,
        },
        {
            "role": "roles/unrelated",
            "members": {runtime},
        },
    ]

    assert iam.reconcile_member_roles(
        policy,
        runtime,
        desired_roles={"roles/runtime", "roles/new"},
        managed_roles={"roles/legacy", "roles/runtime", "roles/new"},
        binding_factory=lambda role, members: {
            "role": role,
            "members": set(members),
        },
    )

    assert policy.etag == b"provider-etag"
    assert policy.version == 3
    unconditional_runtime = [
        binding
        for binding in policy.bindings
        if binding["role"] == "roles/runtime" and not binding.get("condition")
    ]
    assert len(unconditional_runtime) == 1
    assert set(unconditional_runtime[0]["members"]) == {
        runtime,
        "group:operators@example.com",
        "serviceAccount:other@project-1.iam.gserviceaccount.com",
    }
    assert {
        binding["role"]: set(binding["members"])
        for binding in policy.bindings
        if not binding.get("condition")
    }["roles/legacy"] == {"user:other@example.com"}
    assert any(
        binding.get("condition") is conditional and runtime in binding["members"]
        for binding in policy.bindings
    )
    assert any(
        binding["role"] == "roles/unrelated" and runtime in binding["members"]
        for binding in policy.bindings
    )

    assert not iam.reconcile_member_roles(
        policy,
        runtime,
        desired_roles={"roles/runtime", "roles/new"},
        managed_roles={"roles/legacy", "roles/runtime", "roles/new"},
        binding_factory=lambda role, members: {
            "role": role,
            "members": set(members),
        },
    )

    operator = "user:operator@example.com"
    shared_policy = Policy(etag=b"shared-etag", version=3)
    shared_policy.bindings = []
    assert iam.reconcile_member_roles(
        shared_policy,
        operator,
        desired_roles={"roles/shared"},
        managed_roles={"roles/shared"},
        binding_factory=lambda role, members: {
            "role": role,
            "members": set(members),
        },
    )
    assert iam.reconcile_member_roles(
        shared_policy,
        runtime,
        desired_roles={"roles/shared"},
        managed_roles={"roles/shared"},
        binding_factory=lambda role, members: {
            "role": role,
            "members": set(members),
        },
    )
    assert not iam.reconcile_member_roles(
        shared_policy,
        operator,
        desired_roles={"roles/shared"},
        managed_roles={"roles/shared"},
        binding_factory=lambda role, members: {
            "role": role,
            "members": set(members),
        },
    )
    assert not iam.reconcile_member_roles(
        shared_policy,
        runtime,
        desired_roles={"roles/shared"},
        managed_roles={"roles/shared"},
        binding_factory=lambda role, members: {
            "role": role,
            "members": set(members),
        },
    )


# @matrix iam setup : deployer failure-reporting installer preflight
def test_operator_permission_preflight_reports_missing_boundaries(monkeypatch):
    from installer import iam

    constants = _load_config_constants()
    missing_installer = constants.INSTALLER_PROJECT_PERMISSIONS[0]
    missing_deployer = next(
        permission
        for permission in constants.DEPLOYER_PROJECT_PERMISSIONS
        if permission not in constants.INSTALLER_PROJECT_PERMISSIONS
    )
    granted = (
        set(constants.INSTALLER_PROJECT_PERMISSIONS)
        | set(constants.DEPLOYER_PROJECT_PERMISSIONS)
    ) - {missing_installer, missing_deployer}
    requests = []

    def project_permissions(request, timeout=None):
        requests.append((request, timeout))
        return types.SimpleNamespace(permissions=sorted(granted))

    billing_requests = []

    def billing_permissions(request, timeout=None):
        billing_requests.append((request, timeout))
        return types.SimpleNamespace(permissions=[])

    client = types.SimpleNamespace(test_iam_permissions=project_permissions)
    billing_client = types.SimpleNamespace(test_iam_permissions=billing_permissions)

    monkeypatch.setattr(iam, "constants", constants)
    monkeypatch.setattr(iam, "install_if_missing", lambda *args, **kwargs: None)

    assert iam.inspect_operator_permissions(
        "project-1",
        billing_account="billing-1",
        require_billing_link=True,
        client=client,
        billing_client=billing_client,
    ) == {
        "installer": [missing_installer],
        "billing": constants.INSTALLER_BILLING_ACCOUNT_PERMISSIONS,
        "deployer": [missing_deployer],
    }
    assert requests[-1][0]["resource"] == "projects/project-1"
    assert set(requests[-1][0]["permissions"]) == (
        set(constants.INSTALLER_PROJECT_PERMISSIONS)
        | set(constants.DEPLOYER_PROJECT_PERMISSIONS)
    )
    assert set(requests[-1][0]["permissions"]).isdisjoint(
        set(constants.INSTALLER_BUCKET_PERMISSIONS)
    )
    assert requests[-1][1] == 30
    assert billing_requests == [
        (
            {
                "resource": "billingAccounts/billing-1",
                "permissions": constants.INSTALLER_BILLING_ACCOUNT_PERMISSIONS,
            },
            30,
        )
    ]

    with pytest.raises(RuntimeError) as error:
        iam.require_operator_permissions(
            "project-1",
            billing_account="billing-1",
            require_billing_link=True,
            client=client,
            billing_client=billing_client,
        )
    message = str(error.value)
    assert f"Installer: {missing_installer}" in message
    assert "Billing: billing.resourceAssociations.create" in message
    assert f"Deployer: {missing_deployer}" in message
    assert "active installer/deployer account" in message


# @matrix setup : delegated-install owner preflight project-iam
def test_permanent_owner_preflight_requires_direct_project_owner_binding(
    monkeypatch,
):
    from installer import iam

    requests = []
    policy = types.SimpleNamespace(
        bindings=[
            {
                "role": "roles/owner",
                "members": ["user:owner@example.test"],
            }
        ]
    )

    def get_policy(request, timeout=None):
        requests.append((request, timeout))
        return policy

    monkeypatch.setattr(iam, "install_if_missing", lambda *args, **kwargs: None)
    client = types.SimpleNamespace(get_iam_policy=get_policy)

    assert iam.require_permanent_owner_binding(
        "project-1",
        "OWNER@example.test",
        client=client,
    )
    assert requests == [
        (
            {
                "resource": "projects/project-1",
                "options": {"requested_policy_version": 3},
            },
            30,
        )
    ]

    with pytest.raises(RuntimeError, match="not a forwarding alias") as error:
        iam.require_permanent_owner_binding(
            "project-1",
            "alias@example.test",
            client=client,
        )
    assert "direct roles/owner binding" in str(error.value)


# @matrix iam setup storage : bucket-scope failure-reporting installer preflight
def test_installer_bucket_permission_preflight_uses_bucket_resource(monkeypatch):
    from installer import iam

    constants = _load_config_constants()
    missing_installer = constants.INSTALLER_BUCKET_PERMISSIONS[0]
    required = set(constants.INSTALLER_BUCKET_PERMISSIONS)
    requests = []

    class Bucket:
        name = "project-1-private"

        def permission_check(self, permissions):
            requests.append(permissions)
            return sorted(required - {missing_installer})

        test_iam_permissions = permission_check

    monkeypatch.setattr(iam, "constants", constants)

    with pytest.raises(RuntimeError) as error:
        iam.require_installer_bucket_permissions(Bucket())

    assert requests == [sorted(required)]
    message = str(error.value)
    assert "Cloud Storage bucket 'project-1-private'" in message
    assert f"Installer: {missing_installer}" in message
    assert "active installer account" in message


def test_runtime_role_plan_limits_administration_to_owned_scheduler_lifecycle():
    constants = _load_config_constants()

    assert {
        "cloudscheduler.jobs.enable",
        "cloudscheduler.jobs.pause",
        "cloudtasks.queues.pause",
        "cloudtasks.queues.purge",
        "cloudtasks.queues.resume",
        "cloudtasks.tasks.fullView",
        "cloudtasks.tasks.list",
    }.issubset(constants.INSTALLER_PROJECT_PERMISSIONS)
    assert "appengine.services.update" not in (constants.DEPLOYER_PROJECT_PERMISSIONS)
    assert "appengine.services.updateTraffic" not in (
        constants.DEPLOYER_PROJECT_PERMISSIONS
    )
    assert "serviceusage.services.use" in (constants.INSTALLER_PROJECT_PERMISSIONS)
    assert "iam.serviceAccountKeys.create" not in (
        constants.INSTALLER_PROJECT_PERMISSIONS
    )
    assert "iamcredentials.googleapis.com" in (constants.REQUIRED_GOOGLE_CLOUD_APIS)
    runtime_roles = set(constants.RUNTIME_PROJECT_ROLES)
    assert runtime_roles.isdisjoint(constants.REMOVED_RUNTIME_PROJECT_ROLES)
    assert {
        "roles/cloudscheduler.admin",
        "roles/cloudtasks.enqueuer",
        "roles/cloudtasks.taskDeleter",
        "roles/firebaseauth.editor",
    }.issubset(runtime_roles)
    assert {
        "roles/cloudtasks.admin",
        "roles/firebase.admin",
        "roles/firebaseauth.admin",
        "roles/firebasemessagingcampaigns.admin",
        "roles/serviceusage.serviceUsageConsumer",
        "roles/serviceusage.serviceUsageAdmin",
        "roles/storage.admin",
        "roles/appengine.deployer",
        "roles/cloudbuild.builds.editor",
        "roles/iam.serviceAccountUser",
    }.isdisjoint(runtime_roles)
    assert "roles/firebasecloudmessaging.admin" in (
        constants.REMOVED_RUNTIME_PROJECT_ROLES
    )
    assert set(constants.RUNTIME_BUCKET_ROLES) == {
        "roles/storage.legacyBucketReader",
        "roles/storage.objectAdmin",
    }
    assert constants.OPERATOR_BUCKET_ROLES == ["roles/storage.objectAdmin"]
    assert constants.RUNTIME_SERVICE_ACCOUNT_ROLES == [
        "roles/iam.serviceAccountUser",
        "roles/iam.serviceAccountTokenCreator",
    ]


# @matrix iam setup storage : bucket-location bucket-scope idempotence provisioning storage-class
def test_setup_storage_provisioning_is_bucket_scoped_and_idempotent(monkeypatch):
    import installer as setup_pkg
    from config.storage import recovery_bucket_name, storage_bucket_names
    from google.api_core import exceptions as api_exceptions
    from google.api_core.iam import Policy
    from installer import gcloud

    constants = _load_config_constants()
    runtime_email = "runtime@project-1.iam.gserviceaccount.com"
    operator_email = "operator@example.com"
    settings = _fake_settings(
        app={
            "APP_URL": "https://project-1.appspot.com",
            "CUSTOM_DOMAIN": None,
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": runtime_email,
            "DEPLOYER_EMAIL": operator_email,
            "GIBBERISH": "stable-bucket-secret",
        },
        gcloud={"PROJECT": "project-1", "ACCOUNT": operator_email},
    )
    settings.TEST_CONFIG = {"PREFIX": "test-"}
    _install_config_package(monkeypatch, constants, settings=settings)
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(gcloud, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(gcloud, "constants", constants)
    monkeypatch.setattr(gcloud, "install_if_missing", lambda *args, **kwargs: None)
    project_reconciliations = []
    monkeypatch.setattr(
        gcloud.iam_access,
        "reconcile_runtime_project_policy",
        lambda *args: project_reconciliations.append(args),
    )

    buckets = {}

    class Bucket:
        def __init__(self, name):
            self.name = name
            self.location = None
            self.storage_class = None
            self.cors = []
            self.iam_configuration = types.SimpleNamespace(
                uniform_bucket_level_access_enabled=False
            )
            self.patches = 0
            self.policy_sets = 0
            self.permission_checks = []
            self.policy = Policy(etag=f"etag-{name}".encode(), version=3)
            self.policy.bindings = [
                {
                    "role": "roles/viewer",
                    "members": {"user:unrelated@example.com"},
                    "condition": {
                        "title": "operator-owned",
                        "expression": "request.time < timestamp('2030-01-01T00:00:00Z')",
                    },
                }
            ]

        def patch(self):
            self.patches += 1

        def permission_check(self, permissions):
            self.permission_checks.append(permissions)
            return permissions

        test_iam_permissions = permission_check

        def get_iam_policy(self, requested_policy_version):
            assert requested_policy_version == 3
            return self.policy

        def set_iam_policy(self, policy):
            assert policy is self.policy
            self.policy_sets += 1

    class Client:
        def __init__(self, project):
            assert project == "project-1"

        def get_bucket(self, name):
            if name not in buckets:
                raise api_exceptions.NotFound("missing")
            return buckets[name]

        def bucket(self, name):
            return Bucket(name)

        def create_bucket(self, bucket, location):
            assert location == "US"
            bucket.location = location
            buckets[bucket.name] = bucket
            return bucket

    storage_module = types.ModuleType("storage")
    storage_module.Client = Client
    _install_cloud_module(monkeypatch, "storage", storage_module)

    assert gcloud.configure_storage_buckets()
    expected_bucket_names = {
        *storage_bucket_names(settings.APP).values(),
        recovery_bucket_name(settings.APP),
    }
    assert set(buckets) == expected_bucket_names
    runtime_member = f"serviceAccount:{runtime_email}"
    operator_member = f"user:{operator_email}"
    recovery_name = recovery_bucket_name(settings.APP)
    public_names = {
        storage_bucket_names(settings.APP)["public"],
    }
    for bucket in buckets.values():
        assert bucket.location == "US"
        assert bucket.storage_class == "STANDARD"
        assert bucket.patches == 1
        assert bucket.policy_sets == 1
        assert bucket.policy.etag == f"etag-{bucket.name}".encode()
        bindings = {
            binding["role"]: set(binding["members"])
            for binding in bucket.policy.bindings
            if not binding.get("condition")
        }
        expected_bindings = {
            "roles/storage.objectAdmin": {operator_member},
        }
        if bucket.name != recovery_name:
            for role in constants.RUNTIME_BUCKET_ROLES:
                expected_bindings.setdefault(role, set()).add(runtime_member)
            if bucket.name in public_names:
                expected_bindings["roles/storage.objectViewer"] = {"allUsers"}
        assert bindings == expected_bindings
        assert any(
            binding.get("condition", {}).get("title") == "operator-owned"
            for binding in bucket.policy.bindings
        )

    assert gcloud.configure_storage_buckets()
    assert all(bucket.patches == 1 for bucket in buckets.values())
    assert all(bucket.policy_sets == 1 for bucket in buckets.values())
    expected_permissions = sorted(set(constants.INSTALLER_BUCKET_PERMISSIONS))
    assert all(
        bucket.permission_checks == [expected_permissions, expected_permissions]
        for bucket in buckets.values()
    )

    assert gcloud.configure_storage_buckets(
        include_production=False,
        include_test=True,
    )
    test_bucket_settings = {**settings.APP, "PREFIX": "test-"}
    test_bucket_names = set(storage_bucket_names(test_bucket_settings).values())
    assert set(buckets) == expected_bucket_names | test_bucket_names
    for bucket_name in test_bucket_names:
        bucket = buckets[bucket_name]
        assert bucket.policy_sets == 1
        assert bucket.permission_checks == [expected_permissions]
        bindings = {
            binding["role"]: set(binding["members"])
            for binding in bucket.policy.bindings
            if not binding.get("condition")
        }
        assert bindings["roles/storage.objectAdmin"] == {
            operator_member,
            runtime_member,
        }
        assert bindings["roles/storage.legacyBucketReader"] == {runtime_member}
    assert "roles/storage.objectViewer" in {
        binding["role"]
        for binding in buckets[
            storage_bucket_names(test_bucket_settings)["public"]
        ].policy.bindings
        if not binding.get("condition")
    }
    assert project_reconciliations == [
        ("project-1", runtime_email),
        ("project-1", runtime_email),
        ("project-1", runtime_email),
    ]


# @matrix setup : app-engine immutable-location keyless-config oidc provider-state
def test_setup_app_engine_persists_provider_location_hostname_and_oidc_subject(
    monkeypatch,
):
    import installer as setup_pkg
    from installer import gcloud

    constants = _load_config_constants()
    runtime_email = "runtime@project-1.iam.gserviceaccount.com"
    settings = _fake_settings(
        app={
            "APP_ENGINE_LOCATION": "us-central1",
            "CUSTOM_DOMAIN": None,
        },
        gcloud={"PROJECT": "project-1"},
    )
    _install_config_package(monkeypatch, constants, settings=settings)
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(
        gcloud,
        "configure_service_account",
        lambda: {"client_email": runtime_email},
    )
    monkeypatch.setattr(
        gcloud,
        "create_app_engine_app",
        lambda: types.SimpleNamespace(
            location_id="us-central",
            default_hostname="project-1.uc.r.appspot.com",
        ),
    )

    gcloud.setup_app_engine()

    assert settings.APP["APP_ENGINE_LOCATION"] == "us-central"
    assert settings.APP["APP_URL"] == "https://project-1.uc.r.appspot.com"
    assert settings.APP["GOOGLE_LOGIN_URI"] == (
        "https://project-1.uc.r.appspot.com/users/google-signin"
    )
    assert settings.APP["RUNTIME_SERVICE_ACCOUNT_EMAIL"] == runtime_email
    assert settings.APP["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] == runtime_email
    assert settings.DEPLOY["service_account"] == runtime_email
    assert len(settings._saves) == 2


# @matrix setup : provider-convergence service-account
def test_service_account_waits_for_newly_enabled_iam(monkeypatch):
    import installer as setup_pkg

    constants = _load_config_constants()
    runtime_email = "svc@project-1.iam.gserviceaccount.com"
    settings = _fake_settings(
        app={
            "APP_NAME": "Lagniappe",
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": runtime_email,
        },
        gcloud={"PROJECT": "project-1", "ACCOUNT": "deployer@example.com"},
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    from installer import gcloud

    spinner = SpinnerRecorder()
    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter(spinner))
    monkeypatch.setattr(gcloud, "FORMATTER", _fake_formatter(spinner))
    monkeypatch.setattr(gcloud, "install_if_missing", lambda *args, **kwargs: None)
    delays = []
    monkeypatch.setattr(gcloud.time, "sleep", delays.append)

    class ServiceDisabled(RuntimeError):
        status_code = 403

        def __init__(self):
            super().__init__(
                "SERVICE_DISABLED: IAM has not been used in this project yet."
            )

    account = types.SimpleNamespace(
        email=runtime_email,
        name=f"projects/project-1/serviceAccounts/{runtime_email}",
    )

    class IAMClient:
        create_attempts = 0
        created = False

        def get_service_account(self, request):
            if self.created:
                return account
            raise ProviderNotFound("service account does not exist")

        def create_service_account(self, request):
            self.create_attempts += 1
            if self.create_attempts < 3:
                raise ServiceDisabled()
            self.created = True
            return account

    class ServiceAccount:
        display_name = None

    iam_admin_v1 = types.ModuleType("iam_admin_v1")
    iam_admin_v1.IAMClient = IAMClient
    iam_admin_v1.types = types.SimpleNamespace(
        GetServiceAccountRequest=lambda name: types.SimpleNamespace(name=name),
        CreateServiceAccountRequest=lambda: types.SimpleNamespace(
            account_id=None,
            name=None,
            service_account=None,
        ),
        ServiceAccount=ServiceAccount,
    )
    _install_cloud_module(monkeypatch, "iam_admin_v1", iam_admin_v1)
    monkeypatch.setattr(
        gcloud.iam_access,
        "reconcile_runtime_project_policy",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        gcloud.iam_access,
        "reconcile_runtime_service_account_policy",
        lambda *args: None,
    )

    assert gcloud.configure_service_account() == {"client_email": runtime_email}
    assert delays == [2, 4]
    assert any(
        "Google IAM is still becoming available" in message
        for message in spinner.messages
    )
    assert not any("SERVICE_DISABLED" in message for message in spinner.messages)


# @matrix setup : app-engine cloud-tasks ocr service-account
def test_setup_gcloud_resource_client_contracts(monkeypatch):
    import installer as setup_pkg

    constants = _load_config_constants()
    runtime_email = "svc@project-1.iam.gserviceaccount.com"
    settings = _fake_settings(
        app={
            "APP_NAME": "Lagniappe",
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": runtime_email,
            "APP_ENGINE_LOCATION": "us-central",
            "RESOURCE_REGION": "us-central1",
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": runtime_email,
            "OCR_LOCATION": "us",
        },
        gcloud={"PROJECT": "project-1", "ACCOUNT": "deployer@example.com"},
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    from installer import gcloud

    monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(gcloud, "FORMATTER", _fake_formatter())
    monkeypatch.setattr(gcloud, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(gcloud.time, "sleep", lambda seconds: None)

    account = types.SimpleNamespace(
        email=runtime_email,
        name=f"projects/project-1/serviceAccounts/{runtime_email}",
    )

    class IAMClient:
        def get_service_account(self, request):
            return account

    iam_admin_v1 = types.ModuleType("iam_admin_v1")
    iam_admin_v1.IAMClient = IAMClient
    iam_admin_v1.types = types.SimpleNamespace(
        GetServiceAccountRequest=lambda name: types.SimpleNamespace(name=name)
    )
    _install_cloud_module(monkeypatch, "iam_admin_v1", iam_admin_v1)
    iam_calls = []
    monkeypatch.setattr(
        gcloud.iam_access,
        "reconcile_runtime_project_policy",
        lambda *args, **kwargs: iam_calls.append(("project", args, kwargs)),
    )
    monkeypatch.setattr(
        gcloud.iam_access,
        "reconcile_runtime_service_account_policy",
        lambda *args: iam_calls.append(("service-account", args)),
    )
    assert gcloud.configure_service_account() == {"client_email": runtime_email}
    assert iam_calls == [
        (
            "project",
            ("project-1", runtime_email),
            {
                "removed_roles": (
                    set(constants.REMOVED_RUNTIME_PROJECT_ROLES)
                    - set(constants.REMOVED_RUNTIME_PROJECT_STORAGE_ROLES)
                )
            },
        ),
        (
            "service-account",
            (
                "project-1",
                runtime_email,
                "deployer@example.com",
            ),
        ),
    ]

    class AppNotFound(Exception):
        pass

    class Application:
        def __init__(self):
            self.id = None
            self.location_id = None
            self.default_hostname = None

    app_requests = []
    app_engine_events = []

    class AppEngineSpinner:
        def __init__(self, text):
            self.text = text

        def __enter__(self):
            app_engine_events.append(("spinner-enter", self.text))
            return self

        def __exit__(self, exc_type, exc, tb):
            app_engine_events.append(("spinner-exit", self.text))
            return False

        def write(self, message):
            app_engine_events.append(("spinner-write", message))

        def ok(self, mark):
            app_engine_events.append(("spinner-ok", mark))

        def fail(self, mark):
            app_engine_events.append(("spinner-fail", mark))

    app_engine_formatter = types.SimpleNamespace(
        success=lambda message: message,
        info=lambda message: message,
        warning=lambda message: message,
        error=lambda message, error=None: message,
        ok_glyph="[OK]",
        fail_glyph="[X]",
        yaspin=lambda **kwargs: AppEngineSpinner(kwargs["text"]),
    )
    monkeypatch.setattr(
        gcloud,
        "FORMATTER",
        types.SimpleNamespace(initialize=lambda: app_engine_formatter),
    )

    class ApplicationsClient:
        def get_application(self, request, timeout):
            assert timeout == gcloud.APP_ENGINE_RPC_TIMEOUT
            raise AppNotFound()

        def create_application(self, request, timeout):
            assert timeout == gcloud.APP_ENGINE_RPC_TIMEOUT
            app_engine_events.append(("create", request))
            app_requests.append(request)

            def result(timeout):
                app_engine_events.append(("result", timeout))
                return types.SimpleNamespace(
                    default_hostname="project-1.appspot.com",
                    location_id=request["application"].location_id,
                )

            return types.SimpleNamespace(result=result)

    appengine_admin_v1 = types.ModuleType("appengine_admin_v1")
    appengine_admin_v1.ApplicationsClient = ApplicationsClient
    appengine_admin_v1.Application = Application
    _install_cloud_module(monkeypatch, "appengine_admin_v1", appengine_admin_v1)
    _install_api_core_exceptions(monkeypatch, AppNotFound)
    location_prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (
            location_prompts.append(prompt)
            or app_engine_events.append(("input", prompt))
            or "y"
        ),
    )

    created_app = gcloud.create_app_engine_app()

    assert created_app.default_hostname == "project-1.appspot.com"
    assert app_requests[0]["application"].id == "project-1"
    assert app_requests[0]["application"].location_id == "us-central"
    assert location_prompts == [
        "Create the App Engine application in 'us-central'? [y/N]: "
    ]
    discovery_exit = app_engine_events.index(
        ("spinner-exit", "Discover App Engine application")
    )
    prompt_event = app_engine_events.index(
        (
            "input",
            "Create the App Engine application in 'us-central'? [y/N]: ",
        )
    )
    creation_enter = app_engine_events.index(
        (
            "spinner-enter",
            "Create App Engine application (may take up to 5 minutes)",
        )
    )
    assert discovery_exit < prompt_event < creation_enter
    assert ("result", gcloud.APP_ENGINE_CREATE_TIMEOUT) in app_engine_events

    provider_app = types.SimpleNamespace(
        id="project-1",
        location_id="us-central",
        default_hostname="project-1.uc.r.appspot.com",
    )

    class ExistingApplicationsClient:
        def get_application(self, request, timeout):
            assert request == {"name": "apps/project-1"}
            assert timeout == gcloud.APP_ENGINE_RPC_TIMEOUT
            return provider_app

        def create_application(self, request, timeout):
            raise AssertionError("existing App Engine app must not be recreated")

    appengine_admin_v1.ApplicationsClient = ExistingApplicationsClient
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (_ for _ in ()).throw(
            AssertionError("existing immutable location must not be reconfirmed")
        ),
    )
    assert gcloud.create_app_engine_app() is provider_app

    class QueueNotFound(Exception):
        pass

    queue_requests = []

    class Queue:
        def __init__(self, name):
            self.name = name

    class CloudTasksClient:
        created = set()

        def get_queue(self, name):
            if name not in self.created:
                raise QueueNotFound()
            return types.SimpleNamespace(name=name)

        def create_queue(self, parent, queue):
            queue_requests.append((parent, queue.name))
            self.created.add(queue.name)
            return queue

    tasks_v2 = types.ModuleType("tasks_v2")
    tasks_v2.CloudTasksClient = CloudTasksClient
    tasks_v2.types = types.SimpleNamespace(Queue=Queue)
    _install_cloud_module(monkeypatch, "tasks_v2", tasks_v2)
    _install_api_core_exceptions(monkeypatch, QueueNotFound)
    settings._saves.clear()

    assert gcloud.create_task_queue()
    assert settings.APP["TASK_QUEUE_NAME"] == "lagniappe-tasks"
    assert queue_requests == [
        (
            "projects/project-1/locations/us-central1",
            "projects/project-1/locations/us-central1/queues/lagniappe-tasks",
        )
    ]
    assert settings._saves

    client_options_module = types.ModuleType("google.api_core.client_options")
    client_options_module.ClientOptions = lambda api_endpoint: types.SimpleNamespace(
        api_endpoint=api_endpoint
    )
    monkeypatch.setitem(
        sys.modules, "google.api_core.client_options", client_options_module
    )

    ocr_requests = []

    class Processor:
        def __init__(self, display_name, type_):
            self.display_name = display_name
            self.type_ = type_

    class DocumentProcessorServiceClient:
        processors = {}

        def __init__(self, client_options):
            ocr_requests.append(("options", client_options.api_endpoint))

        def common_location_path(self, project_id, location):
            return f"projects/{project_id}/locations/{location}"

        def list_processors(self, parent):
            ocr_requests.append(("list", parent))
            return types.SimpleNamespace(processors=[])

        def create_processor(self, parent, processor):
            ocr_requests.append((parent, processor.display_name, processor.type_))
            created = types.SimpleNamespace(
                name=f"{parent}/processors/processor-1",
                display_name=processor.display_name,
            )
            self.processors[created.name] = created
            return created

        def get_processor(self, name):
            if name not in self.processors:
                raise KeyError(name)
            return self.processors[name]

    documentai = types.ModuleType("documentai")
    documentai.DocumentProcessorServiceClient = DocumentProcessorServiceClient
    documentai.Processor = Processor
    _install_cloud_module(monkeypatch, "documentai", documentai)
    settings._saves.clear()

    gcloud.create_ocr_processor()

    assert settings.APP == {
        "APP_NAME": "Lagniappe",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": runtime_email,
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": runtime_email,
        "OCR_LOCATION": "us",
        "TASK_QUEUE_NAME": "lagniappe-tasks",
        "OCR_PROCESSOR_ID": "projects/project-1/locations/us/processors/processor-1",
        "OCR_PROCESSOR": "lagniappe-document-processor",
    }
    assert ocr_requests == [
        ("options", "us-documentai.googleapis.com"),
        ("list", "projects/project-1/locations/us"),
        (
            "projects/project-1/locations/us",
            "lagniappe-document-processor",
            "OCR_PROCESSOR",
        ),
    ]


# @matrix setup : app-engine failure-isolation interactive-input timeout
def test_app_engine_creation_prompt_and_bounded_failures(monkeypatch, capsys):
    import installer as setup_pkg

    constants = _load_config_constants()
    settings = _fake_settings(
        app={"APP_ENGINE_LOCATION": "us-central"},
        gcloud={"PROJECT": "project-1"},
    )
    _install_config_package(monkeypatch, constants, settings=settings)

    from installer import gcloud

    spinner = SpinnerRecorder()
    formatter = _fake_formatter(spinner)
    monkeypatch.setattr(setup_pkg, "FORMATTER", formatter)
    monkeypatch.setattr(gcloud, "FORMATTER", formatter)
    monkeypatch.setattr(gcloud, "install_if_missing", lambda *args, **kwargs: None)

    class AppNotFound(Exception):
        pass

    class Application:
        def __init__(self):
            self.id = None
            self.location_id = None

    create_requests = []
    operation_timeouts = []

    class ApplicationsClient:
        def get_application(self, request, timeout):
            assert timeout == gcloud.APP_ENGINE_RPC_TIMEOUT
            raise AppNotFound()

        def create_application(self, request, timeout):
            assert timeout == gcloud.APP_ENGINE_RPC_TIMEOUT
            create_requests.append(request)

            def result(timeout):
                operation_timeouts.append(timeout)
                raise TimeoutError("provider operation remained pending")

            return types.SimpleNamespace(result=result)

    appengine_admin_v1 = types.ModuleType("appengine_admin_v1")
    appengine_admin_v1.ApplicationsClient = ApplicationsClient
    appengine_admin_v1.Application = Application
    _install_cloud_module(monkeypatch, "appengine_admin_v1", appengine_admin_v1)
    _install_api_core_exceptions(monkeypatch, AppNotFound)

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (_ for _ in ()).throw(EOFError()),
    )
    with pytest.raises(
        SetupCancelled,
        match="could not read from this terminal",
    ):
        gcloud.create_app_engine_app()
    assert create_requests == []
    assert "Run setup again in an interactive terminal" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    with pytest.raises(
        ProviderTimeout,
        match="Run setup again",
    ):
        gcloud.create_app_engine_app()
    assert len(create_requests) == 1
    assert operation_timeouts == [gcloud.APP_ENGINE_CREATE_TIMEOUT]
    output = capsys.readouterr().out
    assert "may take up to 5 minutes" in output
    assert any(
        "Google may still be completing it" in message for message in spinner.messages
    )


# @matrix iam : conditions empty-bindings member-removal policy-inspection unrelated-members
def test_handoff_policy_helpers_remove_only_the_target_member():
    from installer import iam

    installer = "user:installer@example.test"
    other = "user:other@example.test"
    policy = types.SimpleNamespace(
        bindings=[
            {"role": "roles/owner", "members": [installer, other]},
            {
                "role": "roles/viewer",
                "members": [installer],
                "condition": {"title": "temporary", "expression": "true"},
            },
            {"role": "roles/editor", "members": [other]},
        ]
    )

    assert iam.policy_member_roles(policy, installer) == {
        "roles/owner",
        "roles/viewer",
    }
    assert iam.policy_member_roles(policy, installer, include_conditions=False) == {
        "roles/owner"
    }
    assert iam.remove_member_bindings(policy, installer)
    assert iam.policy_member_roles(policy, installer) == set()
    assert iam.policy_member_roles(policy, other) == {
        "roles/owner",
        "roles/editor",
    }
    assert not iam.remove_member_bindings(policy, installer)


class _HandoffBucket:
    def __init__(self, name, policy, events):
        self.name = name
        self.policy = policy
        self.events = events

    def get_iam_policy(self, requested_policy_version=3):
        assert requested_policy_version == 3
        return self.policy

    def set_iam_policy(self, policy):
        assert policy is self.policy
        self.events.append(f"bucket:{self.name}")


class _HandoffPolicyClient:
    def __init__(self, policy, events, label):
        self.policy = policy
        self.events = events
        self.label = label

    def get_iam_policy(self, request):
        assert request["options"]["requested_policy_version"] == 3
        return self.policy

    def set_iam_policy(self, request):
        assert request["policy"] is self.policy
        self.events.append(self.label)


def _handoff_policy(*bindings):
    return types.SimpleNamespace(
        bindings=[
            {"role": role, "members": list(members)} for role, members in bindings
        ]
    )


# @matrix handoff : active-account adc gcloud installer operator owner preconditions
def test_handoff_operator_preparation_accepts_installer_or_owner(monkeypatch, capsys):
    import config
    from installer import handoff as handoff_module
    from runner import gcloud as runner_gcloud

    installer = "installer@example.test"
    owner = "owner@example.test"
    settings = _fake_settings(
        app={"INSTALLER_EMAIL": installer, "ADMIN_EMAIL": owner},
        gcloud={
            "NAME": "handoff",
            "ACCOUNT": installer,
            "PROJECT": "handoff-project",
        },
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    active = {"email": installer}
    activations = []
    monkeypatch.setattr(
        runner_gcloud,
        "get_configuration_value",
        lambda key: active["email"] if key == "account" else "",
    )
    monkeypatch.setattr(
        runner_gcloud,
        "activate_repository_gcloud",
        lambda **kwargs: (
            activations.append((settings.GCLOUD_CONFIG["ACCOUNT"], kwargs)) or True
        ),
    )

    assert handoff_module.prepare_handoff_operator() == installer
    active["email"] = owner
    assert handoff_module.prepare_handoff_operator() == owner
    assert activations == [
        (installer, {"ensure_adc": True, "ensure_cli_token": True}),
        (owner, {"ensure_adc": True, "ensure_cli_token": True}),
    ]
    assert settings.GCLOUD_CONFIG["ACCOUNT"] == installer
    assert "(installer)" in capsys.readouterr().out

    active["email"] = "unrelated@example.test"
    with pytest.raises(RuntimeError, match="saved installer or permanent Owner"):
        handoff_module.prepare_handoff_operator()
    assert len(activations) == 2


# @matrix handoff : all-bindings bucket cleanup deploy final-mutation idempotence installer-removal ordering owner-add owner-lockout preview project-role resumable service-account settings unrelated-members verification
def test_delegated_handoff_orders_mutations_preserves_unrelated_members_and_is_idempotent(
    monkeypatch, capsys
):
    import config
    from installer import handoff as handoff_module, iam

    events = []
    installer = "installer@example.test"
    owner = "owner@example.test"
    unrelated = "user:unrelated@example.test"
    installer_member = iam.principal_member(installer)
    owner_member = iam.principal_member(owner)
    app = {
        "GOOGLE_CLOUD_PROJECT": "handoff-project",
        "INSTALLER_EMAIL": installer,
        "DEPLOYER_EMAIL": installer,
        "ADMIN_EMAIL": owner,
        "BOOTSTRAP_ADMIN_EMAIL": installer,
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@handoff-project.iam.gserviceaccount.com"
        ),
        "GIBBERISH": "handoff-secret",
        "PREFIX": "",
    }
    runtime_member = iam.principal_member(app["RUNTIME_SERVICE_ACCOUNT_EMAIL"])
    settings = _fake_settings(
        app=app,
        gcloud={
            "NAME": "handoff",
            "ACCOUNT": installer,
            "PROJECT": "handoff-project",
        },
    )
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(
        config,
        "File",
        types.SimpleNamespace(
            APP_SETTINGS_YAML=types.SimpleNamespace(exists=lambda: True)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        handoff_module, "record_step", lambda step: events.append(f"step:{step}")
    )
    monkeypatch.setattr(
        iam, "require_installer_bucket_permissions", lambda bucket: None
    )

    bucket_names = [
        *handoff_module.storage_bucket_names(app).values(),
        handoff_module.recovery_bucket_name(app),
    ]
    buckets = {
        name: _HandoffBucket(
            name,
            _handoff_policy(
                ("roles/storage.objectAdmin", [installer_member, unrelated]),
                ("roles/storage.objectViewer", [unrelated]),
            ),
            events,
        )
        for name in bucket_names
    }
    service_policy = _handoff_policy(
        (
            "roles/iam.serviceAccountUser",
            [installer_member, unrelated, runtime_member],
        ),
        (
            "roles/iam.serviceAccountTokenCreator",
            [installer_member, runtime_member],
        ),
        ("roles/iam.serviceAccountViewer", [unrelated]),
    )
    project_policy = _handoff_policy(
        ("roles/owner", [owner_member, installer_member]),
        ("roles/viewer", [installer_member, unrelated]),
        ("roles/editor", [unrelated]),
    )
    context = {
        "buckets": buckets,
        "service_accounts": _HandoffPolicyClient(
            service_policy, events, "service-account"
        ),
        "projects": _HandoffPolicyClient(project_policy, events, "project"),
    }

    def deploy(**kwargs):
        assert kwargs == {"print_final_summary": False}
        events.append("deploy")

    result = handoff_module.handoff(
        context=context,
        deploy=deploy,
        confirm=lambda prompt: "y",
        permission_check=lambda project: events.append(f"preflight:{project}"),
    )

    assert result == 0
    assert settings.APP["INSTALLER_EMAIL"] == installer
    assert settings.APP["DEPLOYER_EMAIL"] == owner
    assert settings.APP["BOOTSTRAP_ADMIN_EMAIL"] == ""
    assert settings.GCLOUD_CONFIG["ACCOUNT"] == owner
    assert settings._saves == [True]
    preview = capsys.readouterr().out
    assert "Installer/source: installer@example.test" in preview
    assert "Permanent Owner/deployer: owner@example.test" in preview
    assert "roles/storage.objectAdmin" in preview
    assert "roles/iam.serviceAccountTokenCreator" in preview
    assert "Project handoff-project (final cloud mutation)" in preview
    assert events.index("deploy") < events.index(
        "step:remove installer managed-resource access"
    )
    assert events[-1] == "project"

    for bucket in buckets.values():
        assert iam.policy_member_roles(bucket.policy, installer_member) == set()
        assert "roles/storage.objectAdmin" in iam.policy_member_roles(
            bucket.policy, owner_member
        )
        assert iam.policy_member_roles(bucket.policy, unrelated) == {
            "roles/storage.objectAdmin",
            "roles/storage.objectViewer",
        }
    assert iam.policy_member_roles(service_policy, installer_member) == set()
    assert set(iam.constants.RUNTIME_SERVICE_ACCOUNT_ROLES).issubset(
        iam.policy_member_roles(service_policy, owner_member)
    )
    assert set(iam.constants.RUNTIME_SERVICE_ACCOUNT_ROLES).issubset(
        iam.policy_member_roles(service_policy, runtime_member)
    )
    assert "roles/iam.serviceAccountUser" in iam.policy_member_roles(
        service_policy, unrelated
    )
    assert iam.policy_member_roles(project_policy, installer_member) == set()
    assert iam.policy_member_roles(project_policy, owner_member) == {"roles/owner"}
    assert iam.policy_member_roles(project_policy, unrelated) == {
        "roles/viewer",
        "roles/editor",
    }

    events.clear()
    assert (
        handoff_module.handoff(
            context=context,
            deploy=deploy,
            confirm=lambda prompt: "yes",
            permission_check=lambda project: None,
        )
        == 0
    )
    assert "project" not in events
    assert "service-account" not in events
    assert not any(event.startswith("bucket:") for event in events)


# @matrix handoff : confirmation default-no no-mutation owner-lockout preconditions
def test_delegated_handoff_rejects_owner_lockout_and_default_no_confirmation(
    monkeypatch,
):
    import config
    from installer import handoff as handoff_module, iam

    installer = "installer@example.test"
    owner = "owner@example.test"
    app = {
        "GOOGLE_CLOUD_PROJECT": "handoff-project",
        "INSTALLER_EMAIL": installer,
        "DEPLOYER_EMAIL": installer,
        "ADMIN_EMAIL": owner,
        "BOOTSTRAP_ADMIN_EMAIL": installer,
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@handoff-project.iam.gserviceaccount.com"
        ),
        "GIBBERISH": "handoff-secret",
    }
    settings = _fake_settings(app=app)
    monkeypatch.setattr(config, "SETTINGS", settings)
    monkeypatch.setattr(
        config,
        "File",
        types.SimpleNamespace(
            APP_SETTINGS_YAML=types.SimpleNamespace(exists=lambda: True)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        iam, "require_installer_bucket_permissions", lambda bucket: None
    )
    names = [
        *handoff_module.storage_bucket_names(app).values(),
        handoff_module.recovery_bucket_name(app),
    ]
    events = []
    context = {
        "buckets": {
            name: _HandoffBucket(name, _handoff_policy(), events) for name in names
        },
        "service_accounts": _HandoffPolicyClient(
            _handoff_policy(), events, "service-account"
        ),
        "projects": _HandoffPolicyClient(
            _handoff_policy(("roles/owner", [iam.principal_member(installer)])),
            events,
            "project",
        ),
    }

    with pytest.raises(RuntimeError, match="must already hold roles/owner"):
        handoff_module.handoff(
            context=context,
            deploy=lambda **kwargs: pytest.fail("must not deploy"),
            confirm=lambda prompt: "y",
            permission_check=lambda project: None,
        )

    context["projects"].policy.bindings[0]["members"].append(
        iam.principal_member(owner)
    )
    assert (
        handoff_module.handoff(
            context=context,
            deploy=lambda **kwargs: pytest.fail("must not deploy"),
            confirm=lambda prompt: "",
            permission_check=lambda project: None,
        )
        == 1
    )
    assert settings._saves == []
    assert events == []


# @matrix setup : image-restore site-image storage-bucket
# def test_setup_image_client_and_site_image_restore_helpers(monkeypatch):
#     import installer as setup_pkg
#     from installer import image
#     from installer import utils

#     settings = _fake_settings(app={"GIBBERISH": "secret"}, deploy={})
#     bucket_names = []

#     class StorageClient:
#         def bucket(self, name):
#             bucket_names.append(name)
#             return {"bucket": name}

#     storage = types.ModuleType("storage")
#     storage.Client = StorageClient
#     _install_cloud_module(monkeypatch, "storage", storage)
#     monkeypatch.setattr(image, "ensure_storage_dependency", lambda: None)
#     monkeypatch.setitem(
#         sys.modules,
#         "config",
#         types.SimpleNamespace(
#             SETTINGS=settings,
#             File=types.SimpleNamespace(
#                 INDEX_YAML=types.SimpleNamespace(value="index.yaml"),
#                 APP_YAML=types.SimpleNamespace(value="app.yaml"),
#             ),
#         ),
#     )

#     assert image.get_storage_bucket() == {"bucket": bucket_names[0]}
#     assert bucket_names == [
#         f"public-{hashlib.sha256(b'secret').hexdigest()}"[:32].lower()
#     ]

#     deploy_calls = []
#     monkeypatch.setattr(setup_pkg, "FORMATTER", _fake_formatter())
#     monkeypatch.setattr(image, "verify_installation", lambda: None)
#     monkeypatch.setattr(image, "ensure_datastore_dependency", lambda: None)
#     monkeypatch.setattr(image, "get_images", lambda: {"version": 5, "logo.png": True})
#     monkeypatch.setattr(image, "ensure_storage_dependency", lambda: None)
#     monkeypatch.setattr(image, "save_images", lambda sp, entity: True)
#     monkeypatch.setattr(
#         utils, "deploy_to_app_engine", lambda: deploy_calls.append(True)
#     )
#     monkeypatch.setattr("builtins.input", lambda prompt: "n")

#     image.add_site_image()

#     assert settings.APP["SITE_IMAGE_VERSION"] == 5
#     assert settings.MANIFEST == {"name": "Demo"}
#     assert settings._saves
#     assert deploy_calls == []
