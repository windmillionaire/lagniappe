"""Shared Cloud Storage naming and metadata contract."""

import hashlib
import logging
import time
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
BUCKET_KINDS = ("history", "private", "public", "export")
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


# @testable false
# @covered-by config/storage.py::_patch_bucket_metadata
# @reason provider-neutral classifier is owned by bucket metadata retry behavior
def _is_storage_transient_error(error):
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

    try:
        status = int(status)
    except (TypeError, ValueError):
        return False

    return status in {408, 429} or 500 <= status < 600


# @testable false
# @covered-by config/storage.py::storage_bucket_names
# @covered-by config/storage.py::recovery_bucket_name
# @reason shared deterministic name construction is exercised through public naming contracts
def _bucket_name(settings, kind):
    """Return one deterministic full bucket name for an app-settings mapping."""
    digest = hashlib.sha256(str(settings["GIBBERISH"]).encode()).hexdigest()
    prefix = str(settings.get("PREFIX") or "")
    return f"{prefix}{kind}-{digest}"[: len(prefix) + 32].lower()


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_storage_bucket_names_match_runtime_contract
# @features storage setup
# @dimensions naming
def storage_bucket_names(settings):
    """Return Lagniappe's four full bucket names for an app-settings mapping."""
    return {kind: _bucket_name(settings, kind) for kind in BUCKET_KINDS}


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_storage_bucket_names_match_runtime_contract
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_storage_provisioning_is_bucket_scoped_and_idempotent
# @features disaster-recovery
# @dimensions naming
def recovery_bucket_name(settings):
    """Return the operator-only disaster-recovery bucket name."""
    return _bucket_name(settings, RECOVERY_BUCKET_KIND)


# @testable false
# @covered-by config/storage.py::expected_storage_cors_origins
# @reason URL parsing helper owned by the public CORS contract
def _origin(value):
    """Return a scheme://host[:port] origin for a configured URL."""
    if not value:
        return None

    parsed = urlparse(str(value))
    if not parsed.scheme or not parsed.netloc:
        return None

    return f"{parsed.scheme}://{parsed.netloc}"


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_storage_cors_origins_include_configured_urls
# @features storage
# @dimensions cors origins
def expected_storage_cors_origins(config):
    """Return the browser origins allowed to upload/download bucket objects."""
    origins = []

    app_origin = _origin(getattr(config, "APP_URL", None))
    if app_origin:
        origins.append(app_origin)

    custom_domain = getattr(config, "CUSTOM_DOMAIN", None)
    if custom_domain:
        origins.append(_origin(f"https://{custom_domain}"))

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


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_expected_storage_cors_shape
# @features storage
# @dimensions cors
def expected_storage_cors(config):
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


# @testable false
# @covered-by config/storage.py::configure_storage_bucket
# @reason normalization helper owned by idempotent metadata reconciliation
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


# @testable false
# @covered-by config/storage.py::configure_storage_bucket
# @reason retry helper owned by bucket metadata reconciliation
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


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_configure_bucket_is_idempotent
# @tests tests_unit/test_018_database_assets.py::test_configure_bucket_repairs_cors_drift
# @tests tests_unit/test_018_database_assets.py::test_configure_bucket_repairs_storage_class_without_touching_lifecycle
# @tests tests_unit/test_018_database_assets.py::test_configure_bucket_retries_transient_patch_failure
# @features storage
# @dimensions cors idempotent bucket-metadata transient-retry storage-class lifecycle-preservation
def configure_storage_bucket(bucket, config):
    """Reconcile setup-owned metadata while preserving retention/lifecycle."""
    changed = False

    iam_configuration = getattr(bucket, "iam_configuration", None)
    if (
        iam_configuration
        and not iam_configuration.uniform_bucket_level_access_enabled
    ):
        iam_configuration.uniform_bucket_level_access_enabled = True
        changed = True

    expected_cors = expected_storage_cors(config)
    if _normalized_cors(getattr(bucket, "cors", None)) != _normalized_cors(
        expected_cors
    ):
        bucket.cors = expected_cors
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


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_configure_recovery_bucket_removes_cors_and_is_idempotent
# @features disaster-recovery
# @dimensions bucket-metadata lifecycle-preservation
def configure_recovery_bucket(bucket):
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
