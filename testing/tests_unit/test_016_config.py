"""Unit tests for runtime application config behavior."""

from enum import Enum
import importlib.util
from pathlib import Path
import sys
import types

import pytest

pytestmark = pytest.mark.unit


class FakeEnvironment(Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


# @features config
# @dimensions build-id constants stale-settings
def test_config_prefers_tracked_build_id_over_app_settings(monkeypatch):
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
    }
    fake_config = types.SimpleNamespace(
        Environment=FakeEnvironment,
        SETTINGS=types.SimpleNamespace(app_config=app_settings),
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
    assert module.CONFIG.REDIS_TLS is False
    assert module.CONFIG.REDIS_CA_CERT is None
    assert module.CONFIG.SOURCE_URL == "https://example.test/default-source"
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


# @pair config:observability-setting
# @pair ai:observability
def test_config_honors_ai_observability_setting(monkeypatch):
    app_settings = {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "AI_OBSERVABILITY": True,
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
        SETTINGS=types.SimpleNamespace(app_config=app_settings),
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
    assert module.CONFIG.ANALYTICS is False
    assert module.CONFIG.REDIS_TLS is True
    assert module.CONFIG.REDIS_CA_CERT == "config/files/redis_ca.pem"


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
        SETTINGS=types.SimpleNamespace(app_config=app_settings),
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


# @features config
# @dimensions adc project-identity credential-cache
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


# @pairs config:adc config:project-identity config:credential-cache
# @pairs testing:adc testing:project-identity testing:credential-cache testing:runtime-impersonation
# @pairs development:adc development:project-identity development:credential-cache development:runtime-impersonation
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


# @features config
# @dimensions adc token-refresh
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
