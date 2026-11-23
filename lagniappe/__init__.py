from __future__ import annotations

import ipaddress
import math
import os
import re
import sys
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from config import Environment, constants, load_runtime_settings
from config.locations import (
    normalize_app_engine_location,
    normalize_resource_region,
)
from config.storage import storage_bucket_names


if TYPE_CHECKING:
    from config import RuntimeSettings
    from google.auth.credentials import Credentials


GOOGLE_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
IAM_CREDENTIALS_SIGNING_URL = "https://iamcredentials.googleapis.com/"


def _env_flag(name: str, default: bool = False) -> bool:
    """Return a boolean from a local debugging environment variable."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _sample_rate(value, name):
    if isinstance(value, bool):
        raise RuntimeError(f"Invalid {name}: expected a number from 0.0 through 1.0")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Invalid {name}: expected a number from 0.0 through 1.0"
        ) from error
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise RuntimeError(f"Invalid {name}: expected a number from 0.0 through 1.0")
    return normalized


class Config:
    """Application configuration."""

    # Installed settings are assigned with setattr; these names describe the
    # values available to callers without constructing provider clients or
    # turning optional installation settings into class-level defaults.
    ADMIN_EMAIL: str
    ADMIN_NAME: str
    AGENT_ACCESS_EMAIL: str
    AGENT_ACCESS_NAME: str
    AI_AUTO_EXECUTE: bool
    AI_ENABLED: bool
    AI_IMAGE_MODEL: str
    AI_LOCATION: str
    AI_MODEL: str
    AI_UTILITY_MODEL: str
    ANALYTICS: bool
    APP_ENGINE_LOCATION: str
    APP_NAME: str
    APP_URL: str
    AUTH_EMAIL_CONFIG: dict[str, object]
    BASE_URL: str
    CAPTURE_ERRORS: bool
    CONFIG_KIND: str
    CONFIG_SCHEMA_VERSION: int
    DEPLOYER_EMAIL: str
    DEPLOY_IDLE_TIMEOUT: str
    DEPLOY_INSTANCE_CLASS: str
    DEPLOY_MAX_INSTANCES: int | str
    DEPLOY_MIN_IDLE_INSTANCES: int | str
    DEPLOY_SCALING_TYPE: str
    DEPLOY_WORKER_COUNT: int | str
    EXPERIMENTS_DIAGNOSTICS: str
    EXPERIMENTS_ENABLED: bool
    EXPERIMENTS_EXECUTION_ENABLED: bool
    EXPERIMENTS_PROJECT: str
    EXPERIMENTS_SOURCE_ID: str
    EXTERNAL_AI_ENABLED: bool
    GIBBERISH: str
    GOOGLE_CLOUD_PROJECT: str
    GOOGLE_LOGIN_URI: str
    GOOGLE_SIGNIN_ENABLED: bool
    HISTORY_BUCKET: str
    HOSTED_E2E: bool
    HOSTED_E2E_BUILD_ID: str
    HOSTED_E2E_CALLER_EMAIL: str
    HOSTED_E2E_ROLE: str
    HOSTED_E2E_SERVICE: str
    HOSTED_E2E_SESSION_KEY: str
    HOSTED_E2E_SOURCE: str
    HOSTED_E2E_SOURCE_SNAPSHOT: str
    HOSTED_E2E_VERSION: str
    IDENTITY_PLATFORM_CONFIG: dict[str, str]
    INSTALLER_EMAIL: str
    INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL: str
    MCP_NAME: str
    MCP_RESOURCE: str
    MCP_SERVICE_ACCOUNT: str
    OCR_LOCATION: str
    OCR_PROCESSOR: str
    OCR_PROCESSOR_ID: str
    PRIVATE_BUCKET: str
    PUBLIC_BUCKET: str
    PUBLIC_MANUAL: bool
    PUBLIC_PAGE_INDEXING: bool
    REDIS_HOST: str
    REDIS_PASSWORD: str
    REDIS_PORT: int
    REDIS_TLS: bool
    RESOURCE_REGION: str
    RUNTIME_SERVICE_ACCOUNT_EMAIL: str
    SECRET_KEY: str
    SENTRY_DSN: str
    TASK_QUEUE_NAME: str
    VERSION: str

    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        if sys.version_info[:2] != (3, 14):
            raise RuntimeError("Lagniappe 2.5 requires Python 3.14.")
        if settings is None:
            settings = load_runtime_settings(
                Environment(os.environ.get("FLASK_ENV", "production"))
            )
        self.ENV = settings.environment
        app_settings = settings.as_dict()

        unsupported = sorted(
            constants.UNSUPPORTED_SETTING_KEYS.intersection(app_settings)
        )
        if unsupported:
            raise RuntimeError(
                "Application settings contain unsupported keys: "
                + ", ".join(unsupported)
            )
        self.PREFIX = ""
        for key, value in app_settings.items():
            setattr(self, key, value)
        if (
            getattr(self, "CONFIG_KIND", None) != "lagniappe-settings"
            or getattr(self, "CONFIG_SCHEMA_VERSION", None) != 3
        ):
            raise RuntimeError(
                "Lagniappe requires a current schema-3 settings file. "
                "Regenerate the installation configuration with setup."
            )
        app_engine_location = getattr(self, "APP_ENGINE_LOCATION", None)
        resource_region = getattr(self, "RESOURCE_REGION", None)
        if not app_engine_location or not resource_region:
            raise RuntimeError(
                "APP_ENGINE_LOCATION and RESOURCE_REGION are required. "
                "Regenerate the installation configuration with setup."
            )
        self.APP_ENGINE_LOCATION = normalize_app_engine_location(app_engine_location)
        self.RESOURCE_REGION = normalize_resource_region(resource_region)
        runtime_email = getattr(self, "RUNTIME_SERVICE_ACCOUNT_EMAIL", None)
        internal_caller_email = getattr(
            self, "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL", None
        )
        runtime_email = str(runtime_email or "").strip()
        internal_caller_email = str(internal_caller_email or "").strip()
        if not runtime_email or not internal_caller_email:
            raise RuntimeError(
                "RUNTIME_SERVICE_ACCOUNT_EMAIL and "
                "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL are required. "
                "Regenerate the installation configuration with setup."
            )
        if runtime_email.casefold() != internal_caller_email.casefold():
            raise RuntimeError(
                "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL must match "
                "RUNTIME_SERVICE_ACCOUNT_EMAIL for this release."
            )
        project_id = str(getattr(self, "GOOGLE_CLOUD_PROJECT", None) or "").strip()
        if not runtime_email.casefold().endswith(
            f"@{project_id}.iam.gserviceaccount.com"
        ):
            raise RuntimeError(
                "RUNTIME_SERVICE_ACCOUNT_EMAIL must identify a service "
                "account in GOOGLE_CLOUD_PROJECT."
            )
        self.RUNTIME_SERVICE_ACCOUNT_EMAIL = runtime_email.casefold()
        self.INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL = internal_caller_email.casefold()
        self._google_credentials: Credentials | None = None
        tracked_build_id = getattr(constants, "BUILD_ID", None) or self.VERSION
        hosted_build_id = (
            getattr(self, "HOSTED_E2E_BUILD_ID", None)
            if self.testing and getattr(self, "HOSTED_E2E", False)
            else None
        )
        if hosted_build_id and hosted_build_id != tracked_build_id:
            raise RuntimeError(
                "Hosted E2E build ID does not match the built source tree."
            )
        self.BUILD_ID = tracked_build_id

        self.AI_DEBUG = _env_flag("AI_DEBUG", False)
        self.AI_DEBUG_LOG = (os.environ.get("AI_DEBUG_LOG") or "").strip() or None
        self.DEBUG_TRACING = _env_flag("DEBUG_TRACING", False)
        self.STRICT_RELATION_LOADS = _env_flag("STRICT_RELATION_LOADS", False)
        self.CAPTURE_UNLOADED_RELATIONS = _env_flag("CAPTURE_UNLOADED_RELATIONS", False)
        self.TASK_QUEUE_ENABLED = _env_flag("TASK_QUEUE_ENABLED", self.production)
        self.TEST_CURRENT_USER = None
        self.ANALYTICS = getattr(self, "ANALYTICS", False)
        self.SENTRY_TRACES_SAMPLE_RATE = _sample_rate(
            getattr(
                self,
                "SENTRY_TRACES_SAMPLE_RATE",
                getattr(constants, "DEFAULT_SENTRY_TRACES_SAMPLE_RATE", 1.0),
            ),
            "SENTRY_TRACES_SAMPLE_RATE",
        )
        self.SENTRY_PROFILE_SESSION_SAMPLE_RATE = _sample_rate(
            getattr(
                self,
                "SENTRY_PROFILE_SESSION_SAMPLE_RATE",
                getattr(
                    constants,
                    "DEFAULT_SENTRY_PROFILE_SESSION_SAMPLE_RATE",
                    1.0,
                ),
            ),
            "SENTRY_PROFILE_SESSION_SAMPLE_RATE",
        )
        self.GOOGLE_SIGNIN_ENABLED = getattr(
            self,
            "GOOGLE_SIGNIN_ENABLED",
            getattr(constants, "DEFAULT_GOOGLE_SIGNIN_ENABLED", True),
        )
        self.BOOTSTRAP_ADMIN_EMAIL = str(
            getattr(
                self,
                "BOOTSTRAP_ADMIN_EMAIL",
                getattr(constants, "DEFAULT_BOOTSTRAP_ADMIN_EMAIL", ""),
            )
            or ""
        ).strip().casefold()
        self.GOOGLE_CLIENT_ID = str(
            getattr(self, "GOOGLE_CLIENT_ID", "") or ""
        ).strip()
        self.CUSTOM_DOMAIN = str(
            getattr(self, "CUSTOM_DOMAIN", "") or ""
        ).strip()
        from config.ai_settings import normalize_ai_features
        from config.remote_mcp import normalize_mcp_config

        for name, enabled in normalize_ai_features(vars(self)).items():
            setattr(self, name, enabled)

        for name, value in normalize_mcp_config(vars(self)).items():
            setattr(self, name, value)
        from config.experiments import normalize_experiments_config
        for name, value in normalize_experiments_config(vars(self)).items():
            setattr(self, name, value)
        self.CLOUDFLARE_ACCOUNT_ID = str(
            getattr(self, "CLOUDFLARE_ACCOUNT_ID", "") or ""
        ).strip()
        self.AI_OBSERVABILITY = getattr(
            self,
            "AI_OBSERVABILITY",
            getattr(constants, "DEFAULT_AI_OBSERVABILITY_ENABLED", False),
        )
        from config.ai_email import ai_email_public_config, normalize_ai_email_config

        try:
            self.AI_EMAIL_CONFIG = normalize_ai_email_config(
                getattr(self, "AI_EMAIL_CONFIG", None)
            )
        except ValueError as error:
            raise RuntimeError(f"Invalid AI_EMAIL_CONFIG: {error}") from error
        self.AI_EMAIL_PUBLIC = ai_email_public_config(self.AI_EMAIL_CONFIG)
        self.REDIS_TLS = getattr(
            self,
            "REDIS_TLS",
            getattr(constants, "DEFAULT_REDIS_TLS_ENABLED", False),
        )
        self.SOURCE_URL = str(
            getattr(
                self,
                "SOURCE_URL",
                getattr(constants, "DEFAULT_SOURCE_URL", ""),
            )
            or ""
        ).strip()
        self.REDIS_CA_CERT = getattr(self, "REDIS_CA_CERT", None)
        self.LOGIN_USER_KEY = "_lagniappe_user_key"
        self.LOGIN_USER_PAGE_KEY = "_lagniappe_user_page_key"
        self.LOGIN_INVALIDATE_CACHE_KEY = "_lagniappe_invalidate_cache"
        self.AUTH_SESSION_CACHE_KEYS = (
            self.LOGIN_USER_KEY,
            self.LOGIN_USER_PAGE_KEY,
            self.LOGIN_INVALIDATE_CACHE_KEY,
            "restrictions",
            "belongs_to",
            "assign",
            "create_pages",
        )
        self.SENTRY_JS_DSN = str(app_settings.get("SENTRY_JS_DSN") or "").strip()

        self._set_bucket_names()

    def _set_bucket_names(self) -> None:
        for bucket, bucket_name in storage_bucket_names(
            {
                "GIBBERISH": self.GIBBERISH,
                "PREFIX": self.PREFIX,
            }
        ).items():
            attr_name = f"{bucket.upper()}_BUCKET"
            setattr(self, attr_name, bucket_name.removeprefix(self.PREFIX))

    @property
    def capture_errors(self) -> bool:
        return self.ENV == Environment.PRODUCTION and self.CAPTURE_ERRORS

    @property
    def testing(self) -> bool:
        return self.ENV == Environment.TESTING

    @property
    def hosted_e2e(self) -> bool:
        """Return whether this is a validated Google-hosted test process."""
        return self.testing and bool(getattr(self, "HOSTED_E2E", False))

    @property
    def hosted_e2e_server(self) -> bool:
        return self.hosted_e2e and getattr(self, "HOSTED_E2E_ROLE", None) == "server"

    @property
    def hosted_e2e_runner(self) -> bool:
        return self.hosted_e2e and getattr(self, "HOSTED_E2E_ROLE", None) == "runner"

    @property
    def production(self) -> bool:
        return self.ENV == Environment.PRODUCTION

    @property
    def development(self) -> bool:
        return self.ENV == Environment.DEVELOPMENT

    @property
    def local(self) -> bool:
        return not self.production

    @property
    def google_credentials(self) -> Credentials:
        """Return one project- and runtime-bound credential for Google clients."""
        if self._google_credentials is not None:
            return self._google_credentials

        import google.auth

        try:
            credentials, adc_project = google.auth.default(
                scopes=[GOOGLE_CLOUD_PLATFORM_SCOPE]
            )
        except Exception as error:
            raise RuntimeError(
                "Google Application Default Credentials are unavailable. "
                "Authenticate ADC for the configured project or use "
                "short-lived service-account impersonation."
            ) from error

        configured_project = str(self.GOOGLE_CLOUD_PROJECT or "").strip()
        if not adc_project:
            raise RuntimeError(
                "Application Default Credentials did not identify a Google "
                "Cloud project. Reauthenticate ADC for the configured project."
            )
        if adc_project != configured_project:
            raise RuntimeError(
                "Application Default Credentials target project "
                f"'{adc_project}', but Lagniappe is configured for "
                f"'{configured_project}'."
            )

        environment = getattr(self, "ENV", None)
        environment_value = getattr(environment, "value", environment)
        if environment_value in {
            Environment.DEVELOPMENT.value,
            Environment.TESTING.value,
        }:
            source_principal = str(
                getattr(credentials, "service_account_email", None)
                or getattr(credentials, "signer_email", None)
                or ""
            ).strip()
            if (
                source_principal.casefold()
                != self.RUNTIME_SERVICE_ACCOUNT_EMAIL.casefold()
            ):
                from google.auth import impersonated_credentials

                credentials = impersonated_credentials.Credentials(
                    source_credentials=credentials,
                    target_principal=self.RUNTIME_SERVICE_ACCOUNT_EMAIL,
                    target_scopes=[GOOGLE_CLOUD_PLATFORM_SCOPE],
                    lifetime=3600,
                )
        self._google_credentials = credentials
        return credentials

    def google_access_token(self) -> str:
        """Return a fresh shared ADC token for direct Google REST operations."""
        from google.auth.transport.requests import Request

        credentials = self.google_credentials
        try:
            credentials.before_request(
                Request(),
                "POST",
                IAM_CREDENTIALS_SIGNING_URL,
                {},
            )
        except Exception as error:
            raise RuntimeError(
                "Application Default Credentials could not refresh a Google "
                "Cloud access token. Verify ADC scopes and IAM."
            ) from error
        if not credentials.token:
            raise RuntimeError(
                "Application Default Credentials did not provide an access token."
            )
        return credentials.token


CONFIG = Config()

__all__ = [
    "CONFIG",
]
