import os

from config import SETTINGS, Environment, constants
from config.locations import (
    normalize_app_engine_location,
    normalize_resource_region,
)
from config.storage import storage_bucket_names


GOOGLE_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
IAM_CREDENTIALS_SIGNING_URL = "https://iamcredentials.googleapis.com/"


# @testable false
# @covered-by lagniappe/__init__.py::Config
# @reason helper for environment-derived config flags
def _env_flag(name, default=False):
    """Return a boolean from a local debugging environment variable."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# @testable true
# @tests tests_unit/test_016_config.py::test_config_prefers_tracked_build_id_over_app_settings
# @tests tests_unit/test_016_config.py::test_config_honors_ai_observability_setting
# @tests tests_unit/test_016_config.py::test_config_honors_configured_source_url
# @pair config:build-id
# @pair config:constants
# @pair config:stale-settings
# @pair config:observability-setting
# @pair config:source-link
# @pair ai:observability
class Config:
    """Application configuration."""

    def __init__(self):
        self.ENV = Environment(os.environ.get("FLASK_ENV", "production"))
        if self.ENV in [Environment.PRODUCTION]:
            app_settings = SETTINGS.app_config
        elif self.ENV == Environment.DEVELOPMENT:
            app_settings = SETTINGS.dev_config
        elif self.ENV == Environment.TESTING:
            app_settings = SETTINGS.test_config
        else:
            raise ValueError(f"Invalid environment: {self.ENV}")

        unsupported = sorted(
            constants.UNSUPPORTED_SETTING_KEYS.intersection(app_settings)
        )
        if unsupported:
            raise RuntimeError(
                "Application settings contain unsupported keys: "
                + ", ".join(unsupported)
            )
        self.PREFIX = app_settings.get("PREFIX", "")
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
        self._google_credentials = None
        self.BUILD_ID = getattr(constants, "BUILD_ID", None) or self.VERSION

        self.AI_DEBUG = _env_flag("AI_DEBUG", False)
        self.AI_DEBUG_LOG = (os.environ.get("AI_DEBUG_LOG") or "").strip() or None
        self.DEBUG_TRACING = _env_flag("DEBUG_TRACING", False)
        self.STRICT_RELATION_LOADS = _env_flag("STRICT_RELATION_LOADS", False)
        self.CAPTURE_UNLOADED_RELATIONS = _env_flag("CAPTURE_UNLOADED_RELATIONS", False)
        self.TASK_QUEUE_ENABLED = _env_flag("TASK_QUEUE_ENABLED", self.production)
        self.TEST_CURRENT_USER = None
        self.ANALYTICS = getattr(self, "ANALYTICS", False)
        self.AI_OBSERVABILITY = getattr(
            self,
            "AI_OBSERVABILITY",
            getattr(constants, "DEFAULT_AI_OBSERVABILITY_ENABLED", False),
        )
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
        sentry_dsn = getattr(app_settings, "SENTRY_DSN", None)
        if sentry_dsn and not getattr(self, "SENTRY_JS_DSN", None):
            self.SENTRY_JS_DSN = sentry_dsn

        self._set_bucket_names()

    def _set_bucket_names(self):
        for bucket, bucket_name in storage_bucket_names(
            {
                "GIBBERISH": self.GIBBERISH,
                "PREFIX": self.PREFIX,
            }
        ).items():
            attr_name = f"{bucket.upper()}_BUCKET"
            setattr(self, attr_name, bucket_name.removeprefix(self.PREFIX))

    @property
    def capture_errors(self):
        return self.ENV == Environment.PRODUCTION and self.CAPTURE_ERRORS

    @property
    def testing(self):
        return self.ENV == Environment.TESTING

    @property
    def production(self):
        return self.ENV == Environment.PRODUCTION

    @property
    def development(self):
        return self.ENV == Environment.DEVELOPMENT

    @property
    def local(self):
        return not self.production

    # @testable true
    # @tests tests_unit/test_016_config.py::test_google_credentials_are_shared_and_project_bound
    # @tests tests_unit/test_016_config.py::test_local_google_credentials_impersonate_runtime_identity
    # @pairs config:adc config:project-identity config:credential-cache
    # @pairs testing:adc testing:project-identity testing:credential-cache testing:runtime-impersonation
    # @pairs development:adc development:project-identity development:credential-cache development:runtime-impersonation
    @property
    def google_credentials(self):
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

    # @testable true
    # @tests tests_unit/test_016_config.py::test_google_access_token_refreshes_adc_when_stale
    # @features config
    # @dimensions adc token-refresh
    def google_access_token(self):
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
