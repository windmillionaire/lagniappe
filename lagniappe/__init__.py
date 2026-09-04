import ipaddress
import math
import os
import re
from urllib.parse import urlsplit

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


# @testable false
# @covered-by lagniappe/__init__.py::Config
# @reason Sentry sampling normalization is exercised through runtime Config construction
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


# @testable false
# @covered-by lagniappe/__init__.py::normalize_mcp_evaluation_config
# @reason strict origin parsing is exercised through the complete evaluation configuration
def _mcp_origin(value, name, *, hostname=False):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Invalid {name}: expected one HTTPS origin")
    value = value.strip()
    if not value:
        return None
    if hostname:
        if ":" in value or any(character in value for character in "/?#@"):
            raise RuntimeError(f"Invalid {name}: expected one HTTPS hostname")
        value = f"https://{value}"
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise RuntimeError(f"Invalid {name}: expected one HTTPS origin") from error
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.hostname.endswith(".")
    ):
        raise RuntimeError(f"Invalid {name}: expected one HTTPS origin")
    hostname_value = parsed.hostname.casefold()
    if hostname_value.endswith(".") or len(hostname_value) > 253:
        raise RuntimeError(f"Invalid {name}: expected one HTTPS origin")
    try:
        address = ipaddress.ip_address(hostname_value)
    except ValueError:
        try:
            hostname_value.encode("ascii")
        except UnicodeEncodeError as error:
            raise RuntimeError(
                f"Invalid {name}: expected a canonical ASCII DNS or IP host"
            ) from error
        labels = hostname_value.split(".")
        if any(
            not label
            or len(label) > 63
            or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
            for label in labels
        ):
            raise RuntimeError(
                f"Invalid {name}: expected a canonical ASCII DNS or IP host"
            )
    else:
        hostname_value = address.compressed
        if address.version == 6:
            hostname_value = f"[{hostname_value}]"
    return f"https://{hostname_value}"


# @testable true
# @tests tests_unit/test_016_config.py::test_mcp_evaluation_config_requires_actor_allowlist_and_strict_origins
# @matrix config mcp-package : actor-allowlist feature-flag mcp-evaluation origin-validation trial-gate
def normalize_mcp_evaluation_config(settings, constants_module):
    """Normalize the closed actor/origin gate for the MCP evaluation panel."""
    enabled = getattr(
        settings,
        "MCP_EVALUATION_ENABLED",
        getattr(constants_module, "DEFAULT_MCP_EVALUATION_ENABLED", False),
    )
    if not isinstance(enabled, bool):
        raise RuntimeError("Invalid MCP_EVALUATION_ENABLED: expected true or false")
    if not enabled:
        return False, frozenset(), ()

    actors = getattr(
        settings,
        "MCP_EVALUATION_ACTORS",
        getattr(constants_module, "DEFAULT_MCP_EVALUATION_ACTORS", ()),
    )
    if (
        not isinstance(actors, (list, tuple))
        or not actors
        or any(not isinstance(actor, str) or not actor.strip() for actor in actors)
    ):
        raise RuntimeError(
            "Invalid MCP_EVALUATION_ACTORS: expected a nonempty email list"
        )
    normalized_actors = tuple(actor.strip().casefold() for actor in actors)
    if len(set(normalized_actors)) != len(normalized_actors) or any(
        re.fullmatch(r"[^@\s]+@[^@\s]+", actor) is None
        for actor in normalized_actors
    ):
        raise RuntimeError("Invalid MCP_EVALUATION_ACTORS: invalid or duplicate actor")

    origins = [
        _mcp_origin(getattr(settings, "APP_URL", None), "APP_URL"),
        _mcp_origin(
            getattr(settings, "CUSTOM_DOMAIN", None),
            "CUSTOM_DOMAIN",
            hostname=True,
        ),
        _mcp_origin(
            getattr(
                settings,
                "MCP_EVALUATION_ORIGIN",
                getattr(constants_module, "DEFAULT_MCP_EVALUATION_ORIGIN", ""),
            ),
            "MCP_EVALUATION_ORIGIN",
        ),
    ]
    normalized_origins = tuple(dict.fromkeys(origin for origin in origins if origin))
    if not normalized_origins:
        raise RuntimeError("MCP evaluation requires at least one configured HTTPS origin")
    return True, frozenset(normalized_actors), normalized_origins


# @testable true
# @tests tests_unit/test_016_config.py::test_config_prefers_tracked_build_id_over_app_settings
# @tests tests_unit/test_016_config.py::test_config_requires_hosted_build_id_to_match_built_source
# @tests tests_unit/test_016_config.py::test_config_honors_ai_observability_setting
# @tests tests_unit/test_016_config.py::test_config_honors_configured_source_url
# @tests tests_unit/test_016_config.py::test_mcp_evaluation_config_requires_actor_allowlist_and_strict_origins
# @tests tests_unit/test_016_config.py::test_config_normalizes_and_validates_sentry_sample_rates
# @matrix config : actor-allowlist ai-email build-id constants error-reporting google-signin mcp-evaluation observability-setting optional-providers origin-validation public-projection secrets source-link stale-settings trial-gate
# @pairs ai:observability error-reporting:sampling
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
        (
            self.MCP_EVALUATION_ENABLED,
            self.MCP_EVALUATION_ACTORS,
            self.MCP_EVALUATION_ORIGINS,
        ) = normalize_mcp_evaluation_config(self, constants)
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
    # @testable true
    # @tests tests_unit/test_016_config.py::test_hosted_e2e_overrides_require_exact_runtime_identity
    # @matrix hosted-e2e : configuration role
    def hosted_e2e(self):
        """Return whether this is a validated Google-hosted test process."""
        return self.testing and bool(getattr(self, "HOSTED_E2E", False))

    @property
    # @testable true
    # @tests tests_unit/test_016_config.py::test_hosted_e2e_server_rejects_wrong_app_engine_version
    # @matrix hosted-e2e : configuration role
    def hosted_e2e_server(self):
        return self.hosted_e2e and getattr(self, "HOSTED_E2E_ROLE", None) == "server"

    @property
    # @testable true
    # @tests tests_unit/test_016_config.py::test_hosted_e2e_overrides_require_exact_runtime_identity
    # @matrix hosted-e2e : configuration role
    def hosted_e2e_runner(self):
        return self.hosted_e2e and getattr(self, "HOSTED_E2E_ROLE", None) == "runner"

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
    # @matrix config : adc credential-cache project-identity
    # @matrix development testing : adc credential-cache project-identity runtime-impersonation
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
    # @matrix config : adc token-refresh
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
