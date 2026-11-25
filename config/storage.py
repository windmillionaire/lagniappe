"""Shared Cloud Storage naming and metadata contract."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, SupportsIndex, SupportsInt, TypedDict
from urllib.parse import urlparse

if TYPE_CHECKING:
    from google.cloud.storage import Bucket


class _CorsRule(TypedDict):
    origin: list[str]
    method: list[str]
    responseHeader: list[str]
    maxAgeSeconds: int


LOGGER = logging.getLogger(__name__)
BUCKET_KINDS = ("history", "private", "public")
RECOVERY_BUCKET_KIND = "recovery"
BUCKET_CREATE_LOCATION = "US"
BUCKET_DEFAULT_STORAGE_CLASS = "STANDARD"
BUCKET_CORS_METHODS = ["GET", "HEAD", "POST", "PUT"]
BUCKET_CORS_HEADERS = [
    "Content-Type",
    "Content-Range",
    "Range",
    "X-Goog-Resumable",
    "X-Goog-Meta-*",
]
BUCKET_CORS_MAX_AGE_SECONDS = 3600
BUCKET_CONFIG_RETRY_DELAYS = (0.25, 1.0)
RUNTIME_NONCURRENT_RETENTION_DAYS = 14 * 7
RUNTIME_TEMP_UPLOAD_RETENTION_DAYS = 30


def _is_storage_transient_error(error: Exception) -> bool:
    """Return whether a provider error is safe to retry."""
    if type(error).__name__ in {
        "BadGateway",
        "DeadlineExceeded",
        "GatewayTimeout",
        "InternalServerError",
        "ServiceUnavailable",
        "TooManyRequests",
    }:
        return True

    status = getattr(error, "code", None)
    if callable(status):
        status = status()
    status = getattr(status, "value", status)
    if status is None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)

    if not isinstance(status, (str, bytes, bytearray, SupportsInt, SupportsIndex)):
        return False
    try:
        status = int(status)
    except (TypeError, ValueError):
        return False

    return status in {408, 429} or 500 <= status < 600


def _bucket_name(settings: Mapping[str, object], kind: str) -> str:
    """Return one deterministic full bucket name for an app-settings mapping."""
    digest = hashlib.sha256(str(settings["GIBBERISH"]).encode()).hexdigest()
    prefix = str(settings.get("PREFIX") or "")
    return f"{prefix}{kind}-{digest}"[: len(prefix) + 32].lower()


def storage_bucket_names(settings: Mapping[str, object]) -> dict[str, str]:
    """Return Lagniappe's three runtime bucket names for app settings."""
    return {kind: _bucket_name(settings, kind) for kind in BUCKET_KINDS}


def recovery_bucket_name(settings: Mapping[str, object]) -> str:
    """Return the operator-only disaster-recovery bucket name."""
    return _bucket_name(settings, RECOVERY_BUCKET_KIND)


def _origin(value: object) -> str | None:
    """Return a scheme://host[:port] origin for a configured URL."""
    if not value:
        return None

    parsed = urlparse(str(value))
    if not parsed.scheme or not parsed.netloc:
        return None

    return f"{parsed.scheme}://{parsed.netloc}"


def expected_storage_cors_origins(config: object) -> list[str]:
    """Return the browser origins allowed to upload/download bucket objects."""
    origins = []

    app_origin = _origin(getattr(config, "APP_URL", None))
    if app_origin:
        origins.append(app_origin)

    custom_domain = getattr(config, "CUSTOM_DOMAIN", None)
    if custom_domain and (custom_origin := _origin(f"https://{custom_domain}")):
        origins.append(custom_origin)

    if getattr(config, "local", False):
        base_url = getattr(config, "BASE_URL", None)
        if not base_url:
            server_name = getattr(config, "SERVER_NAME", None)
            server_port = getattr(config, "SERVER_PORT", None)
            if server_name and server_port:
                base_url = f"http://{server_name}:{server_port}"
        local_origin = _origin(base_url)
        if local_origin:
            origins.append(local_origin)

    return sorted(set(origins))


def expected_storage_cors(config: object) -> list[_CorsRule]:
    """Return the expected Cloud Storage CORS rule for Lagniappe buckets."""
    origins = expected_storage_cors_origins(config)
    if not origins:
        return []

    return [
        {
            "origin": origins,
            "method": BUCKET_CORS_METHODS,
            "responseHeader": BUCKET_CORS_HEADERS,
            "maxAgeSeconds": BUCKET_CORS_MAX_AGE_SECONDS,
        }
    ]


def has_browser_cors_origin(rules: list[_CorsRule] | None, origin: str | None) -> bool:
    """Check for the explicit origin with all methods and headers used by the app."""
    if not origin:
        return False
    required_headers = {header.lower() for header in BUCKET_CORS_HEADERS}
    return any(
        origin in (rule.get("origin") or [])
        and set(BUCKET_CORS_METHODS).issubset(rule.get("method") or [])
        and required_headers.issubset(
            header.lower() for header in (rule.get("responseHeader") or [])
        )
        for rule in rules or []
    )


def _normalized_cors(cors):
    """Return a comparable CORS shape with order-only differences removed."""
    normalized = []
    for rule in cors or []:
        normalized.append(
            {
                "origin": sorted(rule.get("origin") or []),
                "method": sorted(rule.get("method") or []),
                "responseHeader": sorted(rule.get("responseHeader") or []),
                "maxAgeSeconds": int(rule.get("maxAgeSeconds") or 0),
            }
        )

    return sorted(
        normalized,
        key=lambda rule: (
            tuple(rule["origin"]),
            tuple(rule["method"]),
            tuple(rule["responseHeader"]),
            rule["maxAgeSeconds"],
        ),
    )


def _runtime_lifecycle_rules(rules):
    """Replace only version and temporary-upload deletion rules owned by setup."""
    preserved = []
    for rule in rules or []:
        condition = dict(rule.get("condition") or {})
        action = dict(rule.get("action") or {})
        normalized_keys = {
            {
                "days_since_noncurrent_time": "daysSinceNoncurrentTime",
                "is_live": "isLive",
            }.get(key, key)
            for key in condition
        }
        if (
            str(action.get("type") or "").casefold() == "delete"
            and "daysSinceNoncurrentTime" in normalized_keys
            and normalized_keys.issubset({"daysSinceNoncurrentTime", "isLive"})
            and condition.get("isLive", condition.get("is_live", False)) is False
        ):
            continue
        if (
            str(action.get("type") or "").casefold() == "delete"
            and condition.get("matchesPrefix") == ["tmp/uploads/"]
            and normalized_keys.issubset({"age", "matchesPrefix"})
        ):
            continue
        preserved.append(rule)
    preserved.append(
        {
            "action": {"type": "Delete"},
            "condition": {
                "daysSinceNoncurrentTime": RUNTIME_NONCURRENT_RETENTION_DAYS
            },
        }
    )
    preserved.append(
        {
            "action": {"type": "Delete"},
            "condition": {
                "age": RUNTIME_TEMP_UPLOAD_RETENTION_DAYS,
                "matchesPrefix": ["tmp/uploads/"],
            },
        }
    )
    return preserved


def _patch_bucket_metadata(bucket):
    """Patch bucket metadata, retrying transient Cloud Storage failures."""
    for attempt in range(len(BUCKET_CONFIG_RETRY_DELAYS) + 1):
        try:
            bucket.patch()
            return
        except Exception as error:
            if (
                not _is_storage_transient_error(error)
                or attempt == len(BUCKET_CONFIG_RETRY_DELAYS)
            ):
                raise

            LOGGER.warning(
                "Retrying Cloud Storage bucket metadata patch after "
                "a transient error.",
                exc_info=True,
            )
            time.sleep(BUCKET_CONFIG_RETRY_DELAYS[attempt])


def configure_storage_bucket(
    bucket: Bucket, config: object, *, preserve_cors_origin: str | None = None
) -> bool:
    """Reconcile runtime metadata and the setup-owned version-retention rule."""
    changed = False

    iam_configuration = getattr(bucket, "iam_configuration", None)
    if (
        iam_configuration
        and not iam_configuration.uniform_bucket_level_access_enabled
    ):
        iam_configuration.uniform_bucket_level_access_enabled = True
        changed = True

    expected_cors = expected_storage_cors(config)
    existing_cors = getattr(bucket, "cors", None)
    if expected_cors and preserve_cors_origin and has_browser_cors_origin(existing_cors, preserve_cors_origin):
        expected_cors[0]["origin"] = sorted(
            {*expected_cors[0]["origin"], preserve_cors_origin}
        )
    if _normalized_cors(existing_cors) != _normalized_cors(expected_cors):
        bucket.cors = expected_cors
        changed = True

    if (
        str(getattr(bucket, "storage_class", "") or "").upper()
        != BUCKET_DEFAULT_STORAGE_CLASS
    ):
        bucket.storage_class = BUCKET_DEFAULT_STORAGE_CLASS
        changed = True

    if not bool(getattr(bucket, "versioning_enabled", False)):
        bucket.versioning_enabled = True
        changed = True

    current_lifecycle = list(getattr(bucket, "lifecycle_rules", None) or [])
    expected_lifecycle = _runtime_lifecycle_rules(current_lifecycle)
    if current_lifecycle != expected_lifecycle:
        bucket.lifecycle_rules = expected_lifecycle
        changed = True

    if changed:
        _patch_bucket_metadata(bucket)

    return changed


def configure_recovery_bucket(bucket: Bucket) -> bool:
    """Reconcile recovery-bucket metadata without browser-facing CORS."""
    changed = False

    iam_configuration = getattr(bucket, "iam_configuration", None)
    if (
        iam_configuration
        and not iam_configuration.uniform_bucket_level_access_enabled
    ):
        iam_configuration.uniform_bucket_level_access_enabled = True
        changed = True

    if getattr(bucket, "cors", None):
        bucket.cors = []
        changed = True

    if (
        str(getattr(bucket, "storage_class", "") or "").upper()
        != BUCKET_DEFAULT_STORAGE_CLASS
    ):
        bucket.storage_class = BUCKET_DEFAULT_STORAGE_CLASS
        changed = True

    if changed:
        _patch_bucket_metadata(bucket)

    return changed
