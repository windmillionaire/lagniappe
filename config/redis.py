"""Shared Redis connection configuration for setup and application runtime."""

from collections.abc import Mapping
from pathlib import Path
import ssl


# @testable false
# @covered-by config/redis.py::validate_redis_ca_cert
# @covered-by config/redis.py::redis_tls_enabled
# @reason configuration-specific ValueError type exercised through its raisers
class RedisTLSConfigurationError(ValueError):
    """Raised when Redis TLS settings cannot produce a verified connection."""


# @testable false
# @covered-by config/redis.py::redis_client_kwargs
# @covered-by config/redis.py::redis_tls_enabled
# @reason mapping/object compatibility helper owned by public Redis config builders
def _setting(settings, name, default=None):
    if isinstance(settings, Mapping):
        return settings.get(name, default)
    return getattr(settings, name, default)


# @testable true
# @tests tests_tooling/test_003_config.py::test_redis_client_kwargs_support_verified_tls
# @matrix config : redis-tls settings
def redis_tls_enabled(settings):
    """Return the normalized Redis TLS flag from a mapping or config object."""
    value = _setting(settings, "REDIS_TLS", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    raise RedisTLSConfigurationError(
        "REDIS_TLS must be a boolean value (true or false)."
    )


# @testable true
# @tests tests_tooling/test_003_config.py::test_redis_client_kwargs_support_verified_tls
# @tests tests_tooling/test_003_config.py::test_redis_tls_requires_a_valid_ca_bundle
# @matrix config : certificate-validation failure redis-tls
def validate_redis_ca_cert(path, *, app_dir=None):
    """Resolve and validate a PEM CA bundle, returning its absolute path."""
    if not path:
        raise RedisTLSConfigurationError(
            "REDIS_TLS is enabled but REDIS_CA_CERT is not configured."
        )

    cert_path = Path(path).expanduser()
    if not cert_path.is_absolute():
        if app_dir is None:
            from config import APP_DIR

            app_dir = APP_DIR
        cert_path = Path(app_dir) / cert_path
    cert_path = cert_path.resolve()

    if not cert_path.is_file():
        raise RedisTLSConfigurationError(
            f"Redis CA certificate bundle was not found: {cert_path}"
        )

    try:
        ssl.create_default_context(cafile=str(cert_path))
    except (OSError, ValueError, ssl.SSLError) as error:
        raise RedisTLSConfigurationError(
            f"Redis CA certificate bundle is not a valid readable PEM file: {cert_path}"
        ) from error

    return cert_path


# @testable true
# @tests tests_tooling/test_003_config.py::test_redis_client_kwargs_support_verified_tls
# @tests tests_tooling/test_003_config.py::test_redis_tls_requires_a_valid_ca_bundle
# @matrix config : redis-connection redis-tls
def redis_client_kwargs(settings, *, app_dir=None, **connection_options):
    """Build redis-py client options shared by setup and runtime clients."""
    options = {
        "host": _setting(settings, "REDIS_HOST"),
        "port": _setting(settings, "REDIS_PORT"),
        "password": _setting(settings, "REDIS_PASSWORD"),
        **connection_options,
    }

    if redis_tls_enabled(settings):
        cert_path = validate_redis_ca_cert(
            _setting(settings, "REDIS_CA_CERT"), app_dir=app_dir
        )
        options.update(
            {
                "ssl": True,
                "ssl_ca_certs": str(cert_path),
                "ssl_cert_reqs": "required",
                "ssl_check_hostname": True,
            }
        )

    return options
