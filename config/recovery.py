"""Canonical settings export and recovery-file validation."""

import json
import os
import re
import tempfile
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from urllib.parse import urlparse

from config.ai_email import AIEmailConfigurationError, normalize_ai_email_config
from config.ai_settings import AI_PERSISTED_SETTING_KEYS
from config.constants import (
    DEFAULT_DEPLOYMENT_SETTINGS,
    REDIS_CA_CERT_RELATIVE_PATH,
    UNSUPPORTED_SETTING_KEYS,
)
from config.public_pages import PUBLIC_PAGE_SETTING_KEYS
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


class RecoveryConfigurationError(ValueError):
    """Raised when a recovery snapshot cannot be trusted or restored."""


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


def build_recovery_snapshot(
    settings: Mapping[str, object],
    *,
    deployment_settings: Mapping[str, object] | None = None,
    ai_settings: Mapping[str, object] | None = None,
    public_page_settings: Mapping[str, object] | None = None,
    redis_ca_pem: str | None = None,
) -> dict[str, object]:
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
                if key in AI_PERSISTED_SETTING_KEYS
            }
        )
    if public_page_settings:
        snapshot.update(
            {
                key: value
                for key, value in dict(public_page_settings).items()
                if key in PUBLIC_PAGE_SETTING_KEYS
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


def redact_settings_for_display(settings: Mapping[str, object]) -> dict[str, object]:
    """Return a redacted browser-display copy without mutating the source mapping."""

    def secret_key(key: object) -> bool:
        normalized = re.sub(r"[^A-Z0-9]+", "_", str(key).upper()).strip("_")
        compact = normalized.replace("_", "")
        return normalized == REDIS_CA_PEM or any(
            marker.replace("_", "") in compact for marker in _SECRET_KEY_MARKERS
        )

    def redact(value: object, key: object = "") -> object:
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


def _hostname(value, name):
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        raise RecoveryConfigurationError(f"{name} must be a valid HTTPS URL.")
    return parsed.hostname.casefold()


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


def validate_recovery_document(settings: Mapping[str, object]) -> dict[str, object]:
    """Validate and normalize a canonical recovery document before provider access."""
    from config.locations import (
        normalize_app_engine_location,
        normalize_resource_region,
    )
    from config.secrets import (
        SecretsBackendError,
        normalize_secrets_config,
        uses_secret_manager,
    )

    recovered = dict(settings)
    try:
        secrets_config = normalize_secrets_config(recovered)
    except SecretsBackendError as error:
        raise RecoveryConfigurationError(str(error)) from error
    secret_manager_backend = uses_secret_manager(secrets_config)
    if secret_manager_backend:
        recovered.update(secrets_config)
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
    required_fields = [
        "APP_URL",
        "GOOGLE_LOGIN_URI",
        "APP_ENGINE_LOCATION",
        "RESOURCE_REGION",
        "OCR_LOCATION",
    ]
    if not secret_manager_backend:
        required_fields.append("GIBBERISH")
    for name in required_fields:
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
        port = auth_email.get("port")
        auth_email_port = int(port) if port is not None else 0
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
        and (secret_manager_backend or normalized_auth_email["password"])
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
    if secret_manager_backend and not normalized_auth_email["password"]:
        normalized_auth_email.pop("password", None)
    recovered["AUTH_EMAIL_CONFIG"] = normalized_auth_email

    from config.experiments import normalize_experiments_config
    try:
        normalize_experiments_config(recovered)
    except ValueError as error:
        raise RecoveryConfigurationError(f"Experiments configuration is invalid: {error}") from error

    from config.ai_settings import normalize_ai_features
    from config.remote_mcp import normalize_mcp_config
    try:
        normalize_ai_features(recovered)
        normalize_mcp_config(recovered)
        if recovered.get("MCP_VERSION") is not None and not re.fullmatch(r"[a-f0-9]{32}", str(recovered["MCP_VERSION"])):
            raise ValueError("MCP_VERSION must be a source fingerprint")
    except ValueError as error:
        raise RecoveryConfigurationError(f"AI configuration is invalid: {error}") from error

    ai_email_value = recovered.get("AI_EMAIL_CONFIG")
    if ai_email_value not in (None, ""):
        ai_email_mapping = _mapping(ai_email_value, "AI_EMAIL_CONFIG")
        if secret_manager_backend and ai_email_mapping.get("enabled"):
            # Secret Resend keys live in Secret Manager rather than disk YAML.
            resend_raw = ai_email_mapping.get("resend")
            if isinstance(resend_raw, Mapping):
                validation_copy = dict(ai_email_mapping)
                validation_resend = dict(resend_raw)
                for key in ("webhookSecret", "inboundApiKey", "sendingApiKey"):
                    validation_resend.setdefault(key, f"secret-manager-managed-{key}")
                validation_copy["resend"] = validation_resend
                try:
                    normalize_ai_email_config(validation_copy)
                except AIEmailConfigurationError as error:
                    raise RecoveryConfigurationError(
                        f"AI_EMAIL_CONFIG is invalid: {error}"
                    ) from error
                recovered["AI_EMAIL_CONFIG"] = ai_email_mapping
            else:
                raise RecoveryConfigurationError(
                    "AI_EMAIL_CONFIG is invalid: AI_EMAIL_CONFIG.resend must be a mapping."
                )
        else:
            try:
                recovered["AI_EMAIL_CONFIG"] = normalize_ai_email_config(
                    ai_email_mapping
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
    redis_required = (
        ("REDIS_HOST", "REDIS_PORT")
        if secret_manager_backend
        else ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD")
    )
    redis_values = {name: recovered.get(name) for name in redis_required}
    if any(value not in (None, "") for value in redis_values.values()) and not all(
        value not in (None, "") for value in redis_values.values()
    ):
        raise RecoveryConfigurationError(
            "REDIS_HOST, REDIS_PORT, and REDIS_PASSWORD must be recovered together."
        )
    return recovered


def read_recovery_redis_ca(
    settings: Mapping[str, object], *, app_dir: str | Path | None = None
) -> str | None:
    """Read the validated Redis CA PEM for inclusion in a recovery snapshot."""
    if not redis_tls_enabled(settings):
        return None
    cert_path = validate_redis_ca_cert(
        dict(settings).get("REDIS_CA_CERT"),
        app_dir=app_dir,
    )
    return cert_path.read_text(encoding="utf-8")


def materialize_recovery_redis_ca(
    settings: MutableMapping[str, object], *, app_dir: str | Path | None = None
) -> Path | None:
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
