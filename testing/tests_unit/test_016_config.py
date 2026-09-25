"""Unit tests for runtime application config behavior."""

import copy
import importlib.util
from pathlib import Path
import sys
import types

import pytest

from config import Environment as FakeEnvironment, RuntimeSettings


pytestmark = pytest.mark.unit


def _disabled_ai_email_config():
    return {
        "provider": "resend",
        "enabled": False,
        "domain": "INBOUND.Example.COM.",
        "resend": {
            "domainId": "domain-1",
            "webhookId": "webhook-1",
            "webhookSecret": "whsec_dGVzdA==",
            "inboundApiKey": "re_full",
            "sendingApiKey": "re_send",
            "senderEmail": "noreply@example.com",
            "senderName": "Lagniappe",
        },
    }


# @matrix config : configuration transactional-state
def test_config_owns_values_from_an_explicit_runtime_snapshot(monkeypatch):
    import lagniappe

    app_settings = {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "VERSION": "1.0",
        "GIBBERISH": "bucket-seed",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": "runtime@project-1.iam.gserviceaccount.com",
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": "runtime@project-1.iam.gserviceaccount.com",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "IDENTITY_PLATFORM_CONFIG": {"providers": [{"enabled": True}]},
        "AI_EMAIL_CONFIG": _disabled_ai_email_config(),
    }
    snapshot = RuntimeSettings(FakeEnvironment.PRODUCTION, app_settings)
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setattr(
        lagniappe,
        "load_runtime_settings",
        lambda *args: pytest.fail("explicit snapshot caused a settings file read"),
    )
    first, second = lagniappe.Config(snapshot), lagniappe.Config(snapshot)
    assert first.ENV is FakeEnvironment.PRODUCTION
    assert first.AI_EMAIL_CONFIG["domain"] == "inbound.example.com"
    assert snapshot.as_dict()["AI_EMAIL_CONFIG"]["domain"] == "INBOUND.Example.COM."
    first.IDENTITY_PLATFORM_CONFIG["providers"][0]["enabled"] = False
    first.AI_EMAIL_CONFIG["resend"]["senderName"] = "Changed"
    assert second.IDENTITY_PLATFORM_CONFIG["providers"] == [{"enabled": True}]
    assert second.AI_EMAIL_CONFIG["resend"]["senderName"] == "Lagniappe"
    assert snapshot.as_dict() == app_settings


# @matrix config : site-policy configuration validation
# @source lagniappe/__init__.py::Config
@pytest.mark.parametrize("ai_enabled, external_enabled", [(True, True), (True, False), (False, True)])
def test_config_loads_flat_mcp_settings_and_ai_switches(monkeypatch, ai_enabled, external_enabled):
    app_settings = {
        "CONFIG_KIND": "lagniappe-settings", "CONFIG_SCHEMA_VERSION": 3,
        "GOOGLE_CLOUD_PROJECT": "project-1", "VERSION": "1.0",
        "GIBBERISH": "bucket-seed",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": "runtime@project-1.iam.gserviceaccount.com",
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": "runtime@project-1.iam.gserviceaccount.com",
        "APP_ENGINE_LOCATION": "us-central", "RESOURCE_REGION": "us-central1",
        "APP_URL": "https://project-1.uc.r.appspot.com",
        "CUSTOM_DOMAIN": "workspace.example.test",
        "AI_ENABLED": ai_enabled, "EXTERNAL_AI_ENABLED": external_enabled,
        "MCP_RESOURCE": "https://mcp.example.test/mcp",
        "MCP_SERVICE_ACCOUNT": "lagniappe-mcp@project-1.iam.gserviceaccount.com",
    }
    monkeypatch.setitem(sys.modules, "config", types.SimpleNamespace(
        Environment=FakeEnvironment,
        load_runtime_settings=lambda environment: RuntimeSettings(environment, app_settings),
        constants=types.SimpleNamespace(
            BUILD_ID="tracked-build", DEFAULT_SOURCE_URL="https://example.test/source",
            UNSUPPORTED_SETTING_KEYS=frozenset(),
        ),
    ))
    monkeypatch.setenv("FLASK_ENV", "production")
    spec = importlib.util.spec_from_file_location(
        "_lagniappe_mcp_config_test",
        Path(__file__).resolve().parents[2] / "lagniappe" / "__init__.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CONFIG.AI_ENABLED is ai_enabled
    assert module.CONFIG.EXTERNAL_AI_ENABLED is (ai_enabled and external_enabled)
    assert module.CONFIG.MCP_RESOURCE == app_settings["MCP_RESOURCE"]
    assert module.CONFIG.MCP_SERVICE_ACCOUNT == app_settings["MCP_SERVICE_ACCOUNT"]
    assert not hasattr(module.CONFIG, "REMOTE_MCP")


# @matrix config : ai-email build-id constants optional-providers public-projection secrets stale-settings
@pytest.mark.parametrize("email_policy_version", [None, 1, 2])
def test_config_prefers_tracked_build_id_over_app_settings(monkeypatch, email_policy_version):
    email_config = _disabled_ai_email_config()
    if email_policy_version is not None:
        email_config.update(
            version=email_policy_version,
            aliases={"ai": "ai", "ask": "ask", "create": "create", "organize": "organize"},
            limits={"maxFiles": 20},
        )
    app_settings = {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "BUILD_ID": "stale-local-build",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "GIBBERISH": "bucket-seed",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "VERSION": "1.0",
        "AI_EMAIL_CONFIG": email_config,
    }
    original_settings = copy.deepcopy(app_settings)
    fake_config = types.SimpleNamespace(
        Environment=FakeEnvironment,
        load_runtime_settings=lambda environment: RuntimeSettings(environment, app_settings),
        constants=types.SimpleNamespace(
            BUILD_ID="tracked-build",
            DEFAULT_SOURCE_URL="https://example.test/default-source",
            UNSUPPORTED_SETTING_KEYS=frozenset(),
        ),
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("AI_DEBUG", "true")

    module_path = Path(__file__).resolve().parents[2] / "lagniappe" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_lagniappe_config_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert app_settings == original_settings
    assert set(module.CONFIG.AI_EMAIL_CONFIG) == {"provider", "enabled", "domain", "resend"}
    assert module.CONFIG.BUILD_ID == "tracked-build"
    assert module.CONFIG.AI_DEBUG is True
    assert module.CONFIG.TASK_QUEUE_ENABLED is True
    assert module.CONFIG.APP_ENGINE_LOCATION == "us-central"
    assert module.CONFIG.RESOURCE_REGION == "us-central1"
    assert module.CONFIG.RUNTIME_SERVICE_ACCOUNT_EMAIL == (
        "runtime@project-1.iam.gserviceaccount.com"
    )
    assert (
        module.CONFIG.INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL
        == "runtime@project-1.iam.gserviceaccount.com"
    )
    assert module.CONFIG.AI_OBSERVABILITY is False
    assert module.CONFIG.GOOGLE_SIGNIN_ENABLED is True
    assert module.CONFIG.GOOGLE_CLIENT_ID == ""
    assert module.CONFIG.CUSTOM_DOMAIN == ""
    assert module.CONFIG.CLOUDFLARE_ACCOUNT_ID == ""
    assert module.CONFIG.REDIS_TLS is False
    assert module.CONFIG.REDIS_CA_CERT is None
    assert module.CONFIG.SOURCE_URL == "https://example.test/default-source"
    assert module.CONFIG.AI_EMAIL_CONFIG["domain"] == "inbound.example.com"
    assert module.CONFIG.AI_EMAIL_PUBLIC == {"enabled": False, "addresses": {}}
    assert module.CONFIG.LOGIN_USER_KEY == "_lagniappe_user_key"
    assert module.CONFIG.LOGIN_USER_PAGE_KEY == "_lagniappe_user_page_key"
    assert module.CONFIG.LOGIN_INVALIDATE_CACHE_KEY == "_lagniappe_invalidate_cache"
    assert module.CONFIG.AUTH_SESSION_CACHE_KEYS == (
        "_lagniappe_user_key",
        "_lagniappe_user_page_key",
        "_lagniappe_invalidate_cache",
        "restrictions",
        "belongs_to",
        "assign",
        "create_pages",
    )


# @pair config:build-id
def test_config_requires_hosted_build_id_to_match_built_source(monkeypatch):
    app_settings = {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "BUILD_ID": "b1234567",
        "HOSTED_E2E": True,
        "HOSTED_E2E_BUILD_ID": "b1234567",
        "HOSTED_E2E_ROLE": "runner",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "GIBBERISH": "bucket-seed",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "VERSION": "1.0",
        "AI_EMAIL_CONFIG": _disabled_ai_email_config(),
    }
    fake_config = types.SimpleNamespace(
        Environment=FakeEnvironment,
        load_runtime_settings=lambda environment: RuntimeSettings(environment, app_settings),
        constants=types.SimpleNamespace(
            BUILD_ID="b1234567",
            DEFAULT_SOURCE_URL="https://example.test/default-source",
            UNSUPPORTED_SETTING_KEYS=frozenset(),
        ),
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setenv("FLASK_ENV", "testing")

    module_path = Path(__file__).resolve().parents[2] / "lagniappe" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "_lagniappe_hosted_build_config_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.CONFIG.BUILD_ID == "b1234567"

    fake_config.constants.BUILD_ID = "b7654321"
    mismatch_spec = importlib.util.spec_from_file_location(
        "_lagniappe_hosted_build_mismatch_test",
        module_path,
    )
    mismatch_module = importlib.util.module_from_spec(mismatch_spec)
    with pytest.raises(RuntimeError, match="does not match the built source"):
        mismatch_spec.loader.exec_module(mismatch_module)


# @matrix config : google-signin observability-setting
# @pair ai:observability
def test_config_honors_ai_observability_setting(monkeypatch):
    app_settings = {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "AI_OBSERVABILITY": True,
        "GOOGLE_SIGNIN_ENABLED": False,
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "REDIS_TLS": True,
        "REDIS_CA_CERT": "config/files/redis_ca.pem",
        "GIBBERISH": "bucket-seed",
        "VERSION": "1.0",
    }
    fake_config = types.SimpleNamespace(
        Environment=FakeEnvironment,
        load_runtime_settings=lambda environment: RuntimeSettings(environment, app_settings),
        constants=types.SimpleNamespace(
            BUILD_ID="tracked-build",
            DEFAULT_SOURCE_URL="https://example.test/default-source",
            UNSUPPORTED_SETTING_KEYS=frozenset(),
        ),
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setenv("FLASK_ENV", "production")

    module_path = Path(__file__).resolve().parents[2] / "lagniappe" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "_lagniappe_ai_observability_config_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.CONFIG.AI_OBSERVABILITY is True
    assert module.CONFIG.GOOGLE_SIGNIN_ENABLED is False
    assert module.CONFIG.GOOGLE_CLIENT_ID == ""
    assert module.CONFIG.ANALYTICS is False
    assert module.CONFIG.SENTRY_TRACES_SAMPLE_RATE == 1.0
    assert module.CONFIG.SENTRY_PROFILE_SESSION_SAMPLE_RATE == 1.0
    assert module.CONFIG.REDIS_TLS is True
    assert module.CONFIG.REDIS_CA_CERT == "config/files/redis_ca.pem"


# @source lagniappe/__init__.py::Config
# @pair config:error-reporting
@pytest.mark.parametrize(
    "browser_settings, expected",
    [
        pytest.param({}, "", id="missing"),
        pytest.param({"SENTRY_JS_DSN": None}, "", id="null"),
        pytest.param({"SENTRY_JS_DSN": ""}, "", id="empty"),
        pytest.param({"SENTRY_JS_DSN": " \t "}, "", id="whitespace"),
        pytest.param(
            {"SENTRY_JS_DSN": "https://browser.example.test/2"},
            "https://browser.example.test/2",
            id="separate-destination",
        ),
        pytest.param(
            {"SENTRY_JS_DSN": " https://browser.example.test/2 "},
            "https://browser.example.test/2",
            id="padded-destination",
        ),
        pytest.param(
            {"SENTRY_JS_DSN": "https://backend.example.test/1"},
            "https://backend.example.test/1",
            id="explicitly-shared-destination",
        ),
    ],
)
def test_config_keeps_sentry_browser_destination_independent(
    monkeypatch, browser_settings, expected
):
    import lagniappe

    app_settings = {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": "runtime@project-1.iam.gserviceaccount.com",
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": "runtime@project-1.iam.gserviceaccount.com",
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "GIBBERISH": "bucket-seed",
        "VERSION": "1.0",
        "CAPTURE_ERRORS": True,
        "SENTRY_DSN": "https://backend.example.test/1",
        **browser_settings,
    }
    original_settings = copy.deepcopy(app_settings)
    config = lagniappe.Config(RuntimeSettings(FakeEnvironment.PRODUCTION, app_settings))

    assert config.SENTRY_JS_DSN == expected
    assert config.SENTRY_DSN == "https://backend.example.test/1"
    assert config.capture_errors is True
    assert app_settings == original_settings


# @pairs config:error-reporting error-reporting:sampling
def test_config_normalizes_and_validates_sentry_sample_rates(monkeypatch):
    app_settings = {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "GIBBERISH": "bucket-seed",
        "VERSION": "1.0",
        "SENTRY_TRACES_SAMPLE_RATE": "0.25",
        "SENTRY_PROFILE_SESSION_SAMPLE_RATE": 0.5,
    }
    settings = types.SimpleNamespace(app_config=app_settings)
    fake_config = types.SimpleNamespace(
        Environment=FakeEnvironment,
        load_runtime_settings=lambda environment: RuntimeSettings(
            environment, settings.app_config
        ),
        constants=types.SimpleNamespace(
            BUILD_ID="tracked-build",
            DEFAULT_SOURCE_URL="https://example.test/default-source",
            DEFAULT_SENTRY_TRACES_SAMPLE_RATE=1.0,
            DEFAULT_SENTRY_PROFILE_SESSION_SAMPLE_RATE=1.0,
            UNSUPPORTED_SETTING_KEYS=frozenset(),
        ),
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setenv("FLASK_ENV", "production")

    module_path = Path(__file__).resolve().parents[2] / "lagniappe" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "_lagniappe_sentry_sampling_config_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.CONFIG.SENTRY_TRACES_SAMPLE_RATE == 0.25
    assert module.CONFIG.SENTRY_PROFILE_SESSION_SAMPLE_RATE == 0.5

    invalid_values = (True, "invalid", float("nan"), float("inf"), -0.1, 1.1)
    for name in (
        "SENTRY_TRACES_SAMPLE_RATE",
        "SENTRY_PROFILE_SESSION_SAMPLE_RATE",
    ):
        for value in invalid_values:
            settings.app_config = {**app_settings, name: value}
            with pytest.raises(RuntimeError, match=name):
                module.Config()


# @pair config:source-link
def test_config_honors_configured_source_url(monkeypatch):
    app_settings = {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "GIBBERISH": "bucket-seed",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@project-1.iam.gserviceaccount.com"
        ),
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "SOURCE_URL": "  https://example.test/fork/tree/release  ",
        "VERSION": "1.0",
    }
    fake_config = types.SimpleNamespace(
        Environment=FakeEnvironment,
        load_runtime_settings=lambda environment: RuntimeSettings(environment, app_settings),
        constants=types.SimpleNamespace(
            BUILD_ID="tracked-build",
            DEFAULT_SOURCE_URL="https://example.test/default-source",
            UNSUPPORTED_SETTING_KEYS=frozenset(),
        ),
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setenv("FLASK_ENV", "production")

    module_path = Path(__file__).resolve().parents[2] / "lagniappe" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "_lagniappe_source_url_config_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.CONFIG.SOURCE_URL == "https://example.test/fork/tree/release"


# @matrix config : adc credential-cache project-identity
def test_google_credentials_are_shared_and_project_bound(monkeypatch):
    import google.auth
    from lagniappe import Config

    credentials = object()
    calls = []
    monkeypatch.setattr(
        google.auth,
        "default",
        lambda scopes: calls.append(scopes) or (credentials, "project-1"),
    )
    config = object.__new__(Config)
    config.GOOGLE_CLOUD_PROJECT = "project-1"
    config._google_credentials = None

    assert config.google_credentials is credentials
    assert config.google_credentials is credentials
    assert len(calls) == 1

    mismatched = object.__new__(Config)
    mismatched.GOOGLE_CLOUD_PROJECT = "project-1"
    mismatched._google_credentials = None
    monkeypatch.setattr(
        google.auth,
        "default",
        lambda scopes: (object(), "other-project"),
    )
    with pytest.raises(RuntimeError, match="other-project.*project-1"):
        _ = mismatched.google_credentials


# @matrix config : adc credential-cache project-identity
# @matrix development testing : adc credential-cache project-identity runtime-impersonation
@pytest.mark.parametrize("environment_name", ["development", "testing"])
def test_local_google_credentials_impersonate_runtime_identity(
    monkeypatch,
    environment_name,
):
    import google.auth
    from google.auth import impersonated_credentials

    from config import Environment
    from lagniappe import Config

    source_credentials = object()
    calls = []

    class RuntimeCredentials:
        service_account_email = (
            "runtime@project-1.iam.gserviceaccount.com"
        )

        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        google.auth,
        "default",
        lambda scopes: (source_credentials, "project-1"),
    )
    monkeypatch.setattr(
        impersonated_credentials,
        "Credentials",
        RuntimeCredentials,
    )
    config = object.__new__(Config)
    config.ENV = Environment(environment_name)
    config.GOOGLE_CLOUD_PROJECT = "project-1"
    config.RUNTIME_SERVICE_ACCOUNT_EMAIL = (
        "runtime@project-1.iam.gserviceaccount.com"
    )
    config._google_credentials = None

    credentials = config.google_credentials

    assert credentials.service_account_email == (
        "runtime@project-1.iam.gserviceaccount.com"
    )
    assert calls == [
        {
            "source_credentials": source_credentials,
            "target_principal": (
                "runtime@project-1.iam.gserviceaccount.com"
            ),
            "target_scopes": [
                "https://www.googleapis.com/auth/cloud-platform"
            ],
            "lifetime": 3600,
        }
    ]
    assert config.google_credentials is credentials

    existing_runtime_credentials = types.SimpleNamespace(
        service_account_email=(
            "runtime@project-1.iam.gserviceaccount.com"
        )
    )
    monkeypatch.setattr(
        google.auth,
        "default",
        lambda scopes: (existing_runtime_credentials, "project-1"),
    )
    already_impersonated = object.__new__(Config)
    already_impersonated.ENV = Environment(environment_name)
    already_impersonated.GOOGLE_CLOUD_PROJECT = "project-1"
    already_impersonated.RUNTIME_SERVICE_ACCOUNT_EMAIL = (
        "runtime@project-1.iam.gserviceaccount.com"
    )
    already_impersonated._google_credentials = None

    assert already_impersonated.google_credentials is existing_runtime_credentials
    assert len(calls) == 1


# @matrix config : adc token-refresh
def test_google_access_token_refreshes_adc_when_stale(monkeypatch):
    from lagniappe import Config

    calls = []

    class Credentials:
        token = None

        def before_request(self, request, method, url, headers):
            calls.append((request, method, url, headers))
            self.token = "fresh-token"

    config = object.__new__(Config)
    config._google_credentials = Credentials()

    assert config.google_access_token() == "fresh-token"
    assert calls[0][1:] == (
        "POST",
        "https://iamcredentials.googleapis.com/",
        {},
    )

    class DeniedCredentials:
        token = None

        def before_request(self, request, method, url, headers):
            raise PermissionError("missing scope")

    config._google_credentials = DeniedCredentials()
    with pytest.raises(RuntimeError, match="scopes and IAM") as failure:
        config.google_access_token()
    assert isinstance(failure.value.__cause__, PermissionError)

    class EmptyCredentials:
        token = None

        def before_request(self, request, method, url, headers):
            return None

    config._google_credentials = EmptyCredentials()
    with pytest.raises(RuntimeError, match="did not provide an access token"):
        config.google_access_token()


# @matrix hosted-e2e testing : configuration deployment-binding fail-closed identity prefix
def test_hosted_e2e_overrides_require_exact_runtime_identity():
    from config.hosted_e2e import hosted_e2e_settings_overrides
    from lagniappe import Config
    from config import Environment

    environment = {
        "LAGNIAPPE_HOSTED_E2E": "true",
        "LAGNIAPPE_HOSTED_E2E_ROLE": "runner",
        "LAGNIAPPE_HOSTED_E2E_BASE_URL": (
            "https://e2e-abcdef1234567890-dot-e2e-dot-"
            "project-1.uc.r.appspot.com"
        ),
        "LAGNIAPPE_HOSTED_E2E_PREFIX": "test-",
        "LAGNIAPPE_HOSTED_E2E_RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runner@wrong-project.iam.gserviceaccount.com"
        ),
        "LAGNIAPPE_HOSTED_E2E_VERSION": "e2e-abcdef1234567890",
        "LAGNIAPPE_HOSTED_E2E_SOURCE": "a" * 40,
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT": "b" * 64,
        "LAGNIAPPE_HOSTED_E2E_BUILD_ID": "b1234567",
        "LAGNIAPPE_HOSTED_E2E_SERVICE": "e2e",
        "LAGNIAPPE_HOSTED_E2E_CALLER_EMAIL": (
            "runner@project-1.iam.gserviceaccount.com"
        ),
        "LAGNIAPPE_HOSTED_E2E_JOB": "lagniappe-e2e",
        "CLOUD_RUN_JOB": "lagniappe-e2e",
    }

    with pytest.raises(RuntimeError, match="runtime identity"):
        hosted_e2e_settings_overrides(
            {"PREFIX": "", "GOOGLE_CLOUD_PROJECT": "project-1"},
            environ=environment,
        )

    environment["LAGNIAPPE_HOSTED_E2E_RUNTIME_SERVICE_ACCOUNT_EMAIL"] = (
        "runner@project-1.iam.gserviceaccount.com"
    )
    configured_base_url = environment["LAGNIAPPE_HOSTED_E2E_BASE_URL"]
    environment["LAGNIAPPE_HOSTED_E2E_BASE_URL"] = "https://version.example.test"
    with pytest.raises(RuntimeError, match="exact App Engine version hostname"):
        hosted_e2e_settings_overrides(
            {"PREFIX": "", "GOOGLE_CLOUD_PROJECT": "project-1"},
            environ=environment,
        )
    environment["LAGNIAPPE_HOSTED_E2E_BASE_URL"] = configured_base_url

    overrides = hosted_e2e_settings_overrides(
        {"PREFIX": "", "GOOGLE_CLOUD_PROJECT": "project-1"},
        environ=environment,
    )

    assert overrides["PREFIX"] == "test-"
    assert overrides["ADMIN_EMAIL"] == "admin@test.com"
    assert overrides["ADMIN_NAME"] == "admin"
    assert overrides["BASE_URL"] == (
        "https://e2e-abcdef1234567890-dot-e2e-dot-"
        "project-1.uc.r.appspot.com"
    )
    assert overrides["RUNTIME_SERVICE_ACCOUNT_EMAIL"] == (
        "runner@project-1.iam.gserviceaccount.com"
    )
    assert overrides["HOSTED_E2E_ROLE"] == "runner"
    assert overrides["HOSTED_E2E_BUILD_ID"] == "b1234567"

    config = object.__new__(Config)
    config.ENV = Environment.TESTING
    config.HOSTED_E2E = True
    config.HOSTED_E2E_ROLE = "runner"
    assert config.hosted_e2e is True
    assert config.hosted_e2e_runner is True
    assert config.hosted_e2e_server is False


# @matrix hosted-e2e testing : configuration deployment-binding fail-closed identity
def test_hosted_e2e_server_rejects_wrong_app_engine_version():
    from config.hosted_e2e import hosted_e2e_settings_overrides
    from lagniappe import Config
    from config import Environment

    environment = {
        "LAGNIAPPE_HOSTED_E2E": "true",
        "LAGNIAPPE_HOSTED_E2E_ROLE": "server",
        "LAGNIAPPE_HOSTED_E2E_BASE_URL": (
            "https://e2e-abcdef1234567890-dot-e2e-dot-"
            "project-1.uc.r.appspot.com"
        ),
        "LAGNIAPPE_HOSTED_E2E_PREFIX": "test-",
        "LAGNIAPPE_HOSTED_E2E_RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runner@project-1.iam.gserviceaccount.com"
        ),
        "LAGNIAPPE_HOSTED_E2E_VERSION": "e2e-abcdef1234567890",
        "LAGNIAPPE_HOSTED_E2E_SOURCE": "a" * 40,
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT": "b" * 64,
        "LAGNIAPPE_HOSTED_E2E_BUILD_ID": "b1234567",
        "LAGNIAPPE_HOSTED_E2E_SERVICE": "e2e",
        "LAGNIAPPE_HOSTED_E2E_CALLER_EMAIL": (
            "runner@project-1.iam.gserviceaccount.com"
        ),
        "LAGNIAPPE_HOSTED_E2E_SESSION_KEY": "s" * 48,
        "GAE_SERVICE": "e2e",
        "GAE_VERSION": "wrong-version",
    }

    with pytest.raises(RuntimeError, match="configured version"):
        hosted_e2e_settings_overrides(
            {"PREFIX": "", "GOOGLE_CLOUD_PROJECT": "project-1"},
            environ=environment,
        )

    config = object.__new__(Config)
    config.ENV = Environment.TESTING
    config.HOSTED_E2E = True
    config.HOSTED_E2E_ROLE = "server"
    assert config.hosted_e2e_server is True
    assert config.hosted_e2e_runner is False


# @matrix hosted-e2e testing : authentication deletion-safety soft-routing
def test_reserved_hosted_e2e_hostname_is_exact():
    from config.hosted_e2e import is_reserved_hosted_e2e_hostname

    assert is_reserved_hosted_e2e_hostname(
        "e2e-abcdef1234567890-dot-e2e-dot-project-1.uc.r.appspot.com"
    )
    assert is_reserved_hosted_e2e_hostname(
        "E2E-ABCDEF1234567890-DOT-E2E-DOT-PROJECT-1.APPSpot.COM."
    )
    assert not is_reserved_hosted_e2e_hostname(
        "e2e-anchor-dot-e2e-dot-project-1.uc.r.appspot.com"
    )
    assert not is_reserved_hosted_e2e_hostname(
        "e2e-abcdef1234567890-dot-default-dot-project-1.uc.r.appspot.com"
    )
    assert not is_reserved_hosted_e2e_hostname(
        "prefix-e2e-abcdef1234567890-dot-e2e-dot-project-1.appspot.com"
    )


# @pair data-lifecycle:named-scratch-database
def test_installer_database_id_validation():
    from config.datastore import validate_database_id

    assert validate_database_id("(default)") == "(default)"
    assert validate_database_id("current-db") == "current-db"
    with pytest.raises(ValueError):
        validate_database_id("UPPERCASE")
