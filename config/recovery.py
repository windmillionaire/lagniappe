"""Canonical settings export and recovery-file validation."""

from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse

from config.ai_settings import AI_SETTING_KEYS
from config.ai_email import AIEmailConfigurationError, normalize_ai_email_config
from config.constants import (
    DEFAULT_DEPLOYMENT_SETTINGS,
    REDIS_CA_CERT_RELATIVE_PATH,
    UNSUPPORTED_SETTING_KEYS,
)
from config.redis import redis_tls_enabled, validate_redis_ca_cert


CONFIG_KIND = "lagniappe-settings"
CONFIG_SCHEMA_VERSION = 3
REDIS_CA_PEM = "REDIS_CA_PEM"
REDACTED_VALUE = "[REDACTED]"
_SECRET_KEY_MARKERS = (
    "ACCESS_CODE",
    "API_KEY",
    "CREDENTIAL",
    "DSN",
    "GIBBERISH",
    "PASSWORD",
    "PRIVATE_KEY",
    "SECRET",
    "TOKEN",
)
_PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


# @testable false
# @covered-by config/recovery.py::validate_recovery_document
# @covered-by config/recovery.py::materialize_recovery_redis_ca
# @reason recovery-specific validation type exercised through its public raisers
class RecoveryConfigurationError(ValueError):
    """Raised when a recovery snapshot cannot be trusted or restored."""


# @testable false
# @covered-by config/recovery.py::validate_recovery_document
# @covered-by config/recovery.py::redact_settings_for_display
# @reason structured-value parser owned by public recovery validation and redaction
def _mapping(value, name):
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise RecoveryConfigurationError(
                f"{name} must contain a JSON object."
            ) from error
        if isinstance(decoded, Mapping):
            return dict(decoded)
    raise RecoveryConfigurationError(f"{name} must be a mapping.")


# @testable true
# @tests tests_tooling/test_003_config.py::test_recovery_snapshot_is_complete_flat_and_merges_live_settings
# @matrix config : current-schema messaging-removal recovery-export
def build_recovery_snapshot(
    settings,
    *,
    deployment_settings=None,
    ai_settings=None,
    redis_ca_pem=None,
):
    """Return a complete flat recovery snapshot without redacting persisted values."""
    snapshot = dict(settings)
    snapshot.pop("BUILD_ID", None)
    snapshot.pop("FIREBASE_CONFIG", None)
    schema_version = snapshot.get("CONFIG_SCHEMA_VERSION")
    if (
        snapshot.get("CONFIG_KIND") != CONFIG_KIND
        or str(schema_version).strip() != str(CONFIG_SCHEMA_VERSION)
    ):
        raise RecoveryConfigurationError(
            "Recovery export requires current schema-3 application settings."
        )
    unsupported = sorted(UNSUPPORTED_SETTING_KEYS.intersection(snapshot))
    if unsupported:
        raise RecoveryConfigurationError(
            "Recovery export contains unsupported settings: "
            + ", ".join(unsupported)
        )
    runtime_email = str(
        snapshot.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    internal_caller_email = str(
        snapshot.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    if not runtime_email or not internal_caller_email:
        raise RecoveryConfigurationError(
            "Keyless recovery export requires RUNTIME_SERVICE_ACCOUNT_EMAIL "
            "and INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL."
        )
    if internal_caller_email != runtime_email:
        raise RecoveryConfigurationError(
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL must match "
            "RUNTIME_SERVICE_ACCOUNT_EMAIL for this release."
        )
    snapshot["RUNTIME_SERVICE_ACCOUNT_EMAIL"] = runtime_email
    snapshot["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] = internal_caller_email

    if deployment_settings:
        snapshot.update(
            {
                key: value
                for key, value in dict(deployment_settings).items()
                if key in DEFAULT_DEPLOYMENT_SETTINGS
            }
        )
    if ai_settings:
        snapshot.update(
            {
                key: value
                for key, value in dict(ai_settings).items()
                if key in AI_SETTING_KEYS
            }
        )

    snapshot["CONFIG_KIND"] = CONFIG_KIND
    snapshot["CONFIG_SCHEMA_VERSION"] = CONFIG_SCHEMA_VERSION
    snapshot.setdefault("GOOGLE_SIGNIN_ENABLED", True)
    snapshot.setdefault("BOOTSTRAP_ADMIN_EMAIL", "")
    if redis_tls_enabled(snapshot):
        if not redis_ca_pem:
            raise RecoveryConfigurationError(
                "Redis TLS is enabled, but its CA PEM is unavailable for export."
            )
        snapshot[REDIS_CA_PEM] = str(redis_ca_pem)
        snapshot["REDIS_CA_CERT"] = REDIS_CA_CERT_RELATIVE_PATH
    else:
        snapshot.pop(REDIS_CA_PEM, None)

    return snapshot


# @testable true
# @tests tests_tooling/test_003_config.py::test_recovery_display_redacts_nested_and_flat_secrets_without_mutation
# @matrix config : recovery-display secrets
def redact_settings_for_display(settings):
    """Return a redacted browser-display copy without mutating the source mapping."""

    # @testable false
    # @covered-by config/recovery.py::redact_settings_for_display
    # @reason nested key classifier exercised through the public redaction helper
    def secret_key(key):
        normalized = re.sub(r"[^A-Z0-9]+", "_", str(key).upper()).strip("_")
        compact = normalized.replace("_", "")
        return normalized == REDIS_CA_PEM or any(
            marker.replace("_", "") in compact for marker in _SECRET_KEY_MARKERS
        )

    # @testable false
    # @covered-by config/recovery.py::redact_settings_for_display
    # @reason recursive implementation exercised through the public redaction helper
    def redact(value, key=""):
        if secret_key(key):
            return REDACTED_VALUE
        if isinstance(value, Mapping):
            return {
                nested_key: redact(nested_value, nested_key)
                for nested_key, nested_value in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str) and value[:1] in ("{", "["):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return value
            redacted = redact(decoded)
            return json.dumps(redacted, sort_keys=True)
        return value

    return {key: redact(value, key) for key, value in dict(settings).items()}


# @testable false
# @covered-by config/recovery.py::validate_recovery_document
# @reason URL hostname extraction is exercised through recovery identity validation
def _hostname(value, name):
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        raise RecoveryConfigurationError(f"{name} must be a valid HTTPS URL.")
    return parsed.hostname.casefold()


# @testable false
# @covered-by config/recovery.py::validate_recovery_document
# @reason project-qualified resource comparison is owned by recovery validation
def _require_project_resource(value, name, project_id):
    if not value:
        return
    match = re.fullmatch(
        r"projects/([^/]+)/locations/([^/]+)/processors/([^/]+)",
        str(value),
    )
    resource_project = match.group(1) if match else ""
    if (
        not match
        or (
            resource_project != project_id
            and not (
                resource_project.isascii()
                and resource_project.isdecimal()
            )
        )
    ):
        raise RecoveryConfigurationError(
            f"{name} does not belong to recovered project '{project_id}'."
        )


# @testable true
# @tests tests_tooling/test_003_config.py::test_recovery_document_cross_checks_all_persisted_project_identities
# @tests tests_tooling/test_003_config.py::test_recovery_rejects_current_configuration_identity_mismatch
# @tests tests_tooling/test_003_config.py::test_recovery_requires_complete_current_configuration
# @tests tests_tooling/test_003_config.py::test_recovery_validates_and_normalizes_auth_email_smtp
# @tests tests_tooling/test_003_config.py::test_recovery_upgrades_schema_2_and_discards_legacy_messaging_config
# @tests tests_tooling/test_003_config.py::test_recovery_accepts_and_redacts_optional_ai_email_config
# @matrix config : ai-email authentication-email current-schema messaging-removal project-identity project-number recovery-validation required-settings schema-upgrade secrets
def validate_recovery_document(settings):
    """Validate and normalize a canonical recovery document before provider access."""
    from config.locations import (
        normalize_app_engine_location,
        normalize_resource_region,
    )

    recovered = dict(settings)
    if recovered.get("CONFIG_KIND") != CONFIG_KIND:
        raise RecoveryConfigurationError(
            f"CONFIG_KIND must be '{CONFIG_KIND}'."
        )
    schema_version = recovered.get("CONFIG_SCHEMA_VERSION")
    if schema_version not in {2, CONFIG_SCHEMA_VERSION}:
        raise RecoveryConfigurationError(
            "CONFIG_SCHEMA_VERSION must be 2 or 3."
        )
    recovered["CONFIG_SCHEMA_VERSION"] = CONFIG_SCHEMA_VERSION
    recovered.pop("FIREBASE_CONFIG", None)
    google_signin_value = recovered.get("GOOGLE_SIGNIN_ENABLED", True)
    if not isinstance(google_signin_value, bool):
        raise RecoveryConfigurationError(
            "GOOGLE_SIGNIN_ENABLED must be true or false."
        )
    recovered["GOOGLE_SIGNIN_ENABLED"] = google_signin_value
    recovered["BOOTSTRAP_ADMIN_EMAIL"] = str(
        recovered.get("BOOTSTRAP_ADMIN_EMAIL") or ""
    ).strip().casefold()
    unsupported = sorted(UNSUPPORTED_SETTING_KEYS.intersection(recovered))
    if unsupported:
        raise RecoveryConfigurationError(
            "Unsupported settings are present: " + ", ".join(unsupported)
        )

    app_name = str(recovered.get("APP_NAME") or "").strip()
    project_id = str(recovered.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    owner = str(recovered.get("ADMIN_EMAIL") or "").strip()
    if not app_name:
        raise RecoveryConfigurationError("APP_NAME is required for recovery.")
    if not _PROJECT_ID_PATTERN.fullmatch(project_id):
        raise RecoveryConfigurationError(
            "GOOGLE_CLOUD_PROJECT is missing or invalid."
        )
    if not owner:
        raise RecoveryConfigurationError("ADMIN_EMAIL is required for recovery.")
    app_engine_location = str(
        recovered.get("APP_ENGINE_LOCATION") or ""
    ).strip()
    resource_region = str(recovered.get("RESOURCE_REGION") or "").strip()
    if not app_engine_location or not resource_region:
        raise RecoveryConfigurationError(
            "APP_ENGINE_LOCATION and RESOURCE_REGION are required for recovery."
        )
    recovered["APP_ENGINE_LOCATION"] = normalize_app_engine_location(
        app_engine_location
    )
    recovered["RESOURCE_REGION"] = normalize_resource_region(resource_region)
    for name in (
        "APP_URL",
        "GOOGLE_LOGIN_URI",
        "GIBBERISH",
        "APP_ENGINE_LOCATION",
        "RESOURCE_REGION",
        "OCR_LOCATION",
    ):
        if recovered.get(name) in (None, ""):
            raise RecoveryConfigurationError(f"{name} is required for recovery.")

    runtime_email = str(
        recovered.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    expected_suffix = f"@{project_id}.iam.gserviceaccount.com"
    if not runtime_email.endswith(expected_suffix):
        raise RecoveryConfigurationError(
            "RUNTIME_SERVICE_ACCOUNT_EMAIL must identify a service account "
            "in GOOGLE_CLOUD_PROJECT."
        )
    recovered["RUNTIME_SERVICE_ACCOUNT_EMAIL"] = runtime_email
    internal_caller_email = str(
        recovered.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    if internal_caller_email != runtime_email:
        raise RecoveryConfigurationError(
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL must identify the "
            "recovered runtime service account for this release."
        )
    recovered["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] = internal_caller_email

    identity_value = recovered.get("IDENTITY_PLATFORM_CONFIG")
    if not identity_value:
        raise RecoveryConfigurationError(
            "IDENTITY_PLATFORM_CONFIG is required for authentication."
        )
    identity = _mapping(
        identity_value,
        "IDENTITY_PLATFORM_CONFIG",
    )
    if identity.get("projectId") != project_id:
        raise RecoveryConfigurationError(
            "IDENTITY_PLATFORM_CONFIG.projectId does not match "
            "GOOGLE_CLOUD_PROJECT."
        )
    if not str(identity.get("apiKey") or "").strip():
        raise RecoveryConfigurationError(
            "IDENTITY_PLATFORM_CONFIG.apiKey is required."
        )
    recovered["IDENTITY_PLATFORM_CONFIG"] = {
        "apiKey": str(identity["apiKey"]).strip(),
        "projectId": project_id,
    }

    auth_email_value = recovered.get("AUTH_EMAIL_CONFIG")
    if not auth_email_value:
        raise RecoveryConfigurationError(
            "AUTH_EMAIL_CONFIG is required for authentication email."
        )
    auth_email = _mapping(auth_email_value, "AUTH_EMAIL_CONFIG")
    try:
        auth_email_port = int(auth_email.get("port"))
    except (TypeError, ValueError):
        auth_email_port = 0
    normalized_auth_email = {
        "provider": auth_email.get("provider"),
        "service": str(auth_email.get("service") or "SMTP").strip(),
        "host": str(auth_email.get("host") or "").strip(),
        "port": auth_email_port,
        "security": str(auth_email.get("security") or "").strip().casefold(),
        "username": str(auth_email.get("username") or "").strip(),
        "password": str(auth_email.get("password") or ""),
        "senderEmail": str(auth_email.get("senderEmail") or "").strip(),
        "senderName": str(auth_email.get("senderName") or "").strip(),
    }
    if not (
        normalized_auth_email["provider"] == "smtp"
        and normalized_auth_email["service"]
        and normalized_auth_email["host"]
        and 1 <= normalized_auth_email["port"] <= 65535
        and normalized_auth_email["security"] in {"starttls", "ssl"}
        and normalized_auth_email["username"]
        and normalized_auth_email["password"]
        and re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            normalized_auth_email["senderEmail"],
        )
        and normalized_auth_email["senderName"]
    ):
        raise RecoveryConfigurationError(
            "AUTH_EMAIL_CONFIG must contain a complete encrypted SMTP "
            "configuration, verified sender address, and sender name."
        )
    recovered["AUTH_EMAIL_CONFIG"] = normalized_auth_email

    ai_email_value = recovered.get("AI_EMAIL_CONFIG")
    if ai_email_value not in (None, ""):
        try:
            recovered["AI_EMAIL_CONFIG"] = normalize_ai_email_config(
                _mapping(ai_email_value, "AI_EMAIL_CONFIG")
            )
        except AIEmailConfigurationError as error:
            raise RecoveryConfigurationError(
                f"AI_EMAIL_CONFIG is invalid: {error}"
            ) from error

    app_hostname = _hostname(recovered.get("APP_URL"), "APP_URL")
    if not (
        app_hostname == f"{project_id}.appspot.com"
        or (
            app_hostname.startswith(f"{project_id}.")
            and app_hostname.endswith(".r.appspot.com")
        )
    ):
        raise RecoveryConfigurationError(
            "APP_URL does not identify the recovered project's App Engine app."
        )

    login_hostname = _hostname(
        recovered.get("GOOGLE_LOGIN_URI"), "GOOGLE_LOGIN_URI"
    )
    allowed_login_hosts = {app_hostname}
    custom_domain = str(recovered.get("CUSTOM_DOMAIN") or "").strip().casefold()
    if custom_domain:
        allowed_login_hosts.add(custom_domain)
    if login_hostname not in allowed_login_hosts:
        raise RecoveryConfigurationError(
            "GOOGLE_LOGIN_URI does not match APP_URL or CUSTOM_DOMAIN."
        )

    _require_project_resource(
        recovered.get("OCR_PROCESSOR_ID"),
        "OCR_PROCESSOR_ID",
        project_id,
    )
    redis_values = {
        name: recovered.get(name)
        for name in ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD")
    }
    if any(value not in (None, "") for value in redis_values.values()) and not all(
        value not in (None, "") for value in redis_values.values()
    ):
        raise RecoveryConfigurationError(
            "REDIS_HOST, REDIS_PORT, and REDIS_PASSWORD must be recovered together."
        )
    return recovered


# @testable true
# @tests tests_tooling/test_003_config.py::test_recovery_redis_ca_round_trips_through_one_file
# @matrix config : recovery-export redis-tls
def read_recovery_redis_ca(settings, *, app_dir=None):
    """Read the validated Redis CA PEM for inclusion in a recovery snapshot."""
    if not redis_tls_enabled(settings):
        return None
    cert_path = validate_redis_ca_cert(
        dict(settings).get("REDIS_CA_CERT"),
        app_dir=app_dir,
    )
    return cert_path.read_text(encoding="utf-8")


# @testable true
# @tests tests_tooling/test_003_config.py::test_recovery_redis_ca_round_trips_through_one_file
# @matrix config : certificate-validation recovery-restore redis-tls
def materialize_recovery_redis_ca(settings, *, app_dir=None):
    """Atomically restore the managed Redis CA file before endpoint validation."""
    recovered = settings
    if not redis_tls_enabled(recovered):
        return None

    pem = recovered.get(REDIS_CA_PEM)
    if not isinstance(pem, str) or not pem.strip():
        raise RecoveryConfigurationError(
            f"{REDIS_CA_PEM} is required when REDIS_TLS is enabled."
        )

    if app_dir is None:
        from config import APP_DIR

        app_dir = APP_DIR
    target = Path(app_dir) / REDIS_CA_CERT_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=".redis_ca.",
            suffix=".pem",
            delete=False,
        ) as temporary:
            temporary.write(pem)
            temporary_path = Path(temporary.name)
        validate_redis_ca_cert(temporary_path, app_dir=app_dir)
        os.replace(temporary_path, target)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()

    recovered["REDIS_CA_CERT"] = REDIS_CA_CERT_RELATIVE_PATH
    return target
