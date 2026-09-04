"""Fail-closed configuration for Google-hosted E2E execution."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse


HOSTED_E2E_FLAG = "LAGNIAPPE_HOSTED_E2E"
HOSTED_E2E_ROLE = "LAGNIAPPE_HOSTED_E2E_ROLE"
HOSTED_E2E_BASE_URL = "LAGNIAPPE_HOSTED_E2E_BASE_URL"
HOSTED_E2E_PREFIX = "LAGNIAPPE_HOSTED_E2E_PREFIX"
HOSTED_E2E_RUNTIME_EMAIL = "LAGNIAPPE_HOSTED_E2E_RUNTIME_SERVICE_ACCOUNT_EMAIL"
HOSTED_E2E_VERSION = "LAGNIAPPE_HOSTED_E2E_VERSION"
HOSTED_E2E_SOURCE = "LAGNIAPPE_HOSTED_E2E_SOURCE"
HOSTED_E2E_SOURCE_SNAPSHOT = "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT"
HOSTED_E2E_BUILD_ID = "LAGNIAPPE_HOSTED_E2E_BUILD_ID"
HOSTED_E2E_SERVICE = "LAGNIAPPE_HOSTED_E2E_SERVICE"
HOSTED_E2E_JOB = "LAGNIAPPE_HOSTED_E2E_JOB"
HOSTED_E2E_CALLER_EMAIL = "LAGNIAPPE_HOSTED_E2E_CALLER_EMAIL"
HOSTED_E2E_SESSION_KEY = "LAGNIAPPE_HOSTED_E2E_SESSION_KEY"

HOSTED_E2E_ROLES = frozenset({"runner", "server"})
HOSTED_E2E_SERVICE_NAME = "e2e"
HOSTED_E2E_SOURCE_RE = re.compile(r"^[0-9a-f]{7,64}$")
HOSTED_E2E_VERSION_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
HOSTED_E2E_RESERVED_HOST_RE = re.compile(
    r"^e2e-[0-9a-f]{16}-dot-e2e-dot-[a-z0-9.-]+\.appspot\.com$"
)


# @testable false
# @covered-by config/hosted_e2e.py::hosted_e2e_settings_overrides
# @reason normalization helper owned by the fail-closed hosted configuration contract
def _enabled(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


# @testable false
# @covered-by config/hosted_e2e.py::hosted_e2e_settings_overrides
# @reason required-value helper owned by the fail-closed hosted configuration contract
def _required(environ: dict[str, str], name: str) -> str:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Hosted E2E configuration requires {name}.")
    return value


# @testable true
# @tests tests_unit/test_016_config.py::test_reserved_hosted_e2e_hostname_is_exact
# @matrix hosted-e2e testing : authentication deletion-safety soft-routing
def is_reserved_hosted_e2e_hostname(hostname: str) -> bool:
    """Return whether an App Engine hostname is reserved for ephemeral E2E."""
    normalized = str(hostname or "").strip().rstrip(".").casefold()
    return HOSTED_E2E_RESERVED_HOST_RE.fullmatch(normalized) is not None


# @testable true
# @tests tests_unit/test_016_config.py::test_hosted_e2e_overrides_require_exact_runtime_identity
# @tests tests_unit/test_016_config.py::test_hosted_e2e_server_rejects_wrong_app_engine_version
# @matrix hosted-e2e mcp-package testing : actor-allowlist configuration deployment-binding fail-closed identity mcp-evaluation origin-validation prefix trial-gate
def hosted_e2e_settings_overrides(
    app_settings: dict[str, object],
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    """Return validated non-secret test overrides for a hosted E2E process."""
    environ = os.environ if environ is None else environ
    if not _enabled(environ.get(HOSTED_E2E_FLAG)):
        return {}

    from .constants import (
        DEFAULT_ADMIN_EMAIL,
        DEFAULT_ADMIN_NAME,
        DEFAULT_TEST_PREFIX,
    )

    role = _required(environ, HOSTED_E2E_ROLE).casefold()
    if role not in HOSTED_E2E_ROLES:
        raise RuntimeError("Hosted E2E role must be 'runner' or 'server'.")

    prefix = _required(environ, HOSTED_E2E_PREFIX)
    if prefix != DEFAULT_TEST_PREFIX:
        raise RuntimeError(
            f"Hosted E2E prefix must be the reserved value {DEFAULT_TEST_PREFIX!r}."
        )
    production_prefix = str(app_settings.get("PREFIX") or "")
    if prefix == production_prefix:
        raise RuntimeError("Hosted E2E prefix must differ from production.")

    base_url = _required(environ, HOSTED_E2E_BASE_URL).rstrip("/")
    parsed = urlparse(base_url)
    try:
        parsed_port = parsed.port
    except ValueError as error:
        raise RuntimeError(
            "Hosted E2E base URL must be one exact HTTPS origin."
        ) from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed_port is not None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeError("Hosted E2E base URL must be one exact HTTPS origin.")

    project_id = str(app_settings.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    runtime_email = _required(environ, HOSTED_E2E_RUNTIME_EMAIL).casefold()
    if not project_id or not runtime_email.endswith(
        f"@{project_id}.iam.gserviceaccount.com"
    ):
        raise RuntimeError(
            "Hosted E2E runtime identity must be a service account in the "
            "configured project."
        )

    version = _required(environ, HOSTED_E2E_VERSION)
    source = _required(environ, HOSTED_E2E_SOURCE).casefold()
    source_snapshot = _required(environ, HOSTED_E2E_SOURCE_SNAPSHOT).casefold()
    build_id = _required(environ, HOSTED_E2E_BUILD_ID).casefold()
    if not HOSTED_E2E_VERSION_RE.fullmatch(version):
        raise RuntimeError("Hosted E2E version has an invalid App Engine ID.")
    if not HOSTED_E2E_SOURCE_RE.fullmatch(source):
        raise RuntimeError("Hosted E2E source must be a hexadecimal fingerprint.")
    if not re.fullmatch(r"[0-9a-f]{64}", source_snapshot):
        raise RuntimeError(
            "Hosted E2E source snapshot must be a semantic SHA-256 fingerprint."
        )
    if not re.fullmatch(r"b[0-9a-f]{7}", build_id):
        raise RuntimeError("Hosted E2E build ID is invalid.")

    service = _required(environ, HOSTED_E2E_SERVICE)
    if service != HOSTED_E2E_SERVICE_NAME:
        raise RuntimeError(
            f"Hosted E2E service must be {HOSTED_E2E_SERVICE_NAME!r}."
        )
    expected_host_prefix = f"{version}-dot-{service}-dot-"
    app_hostname = parsed.hostname.removeprefix(expected_host_prefix)
    project_host = app_hostname == f"{project_id}.appspot.com"
    regional_project_host = app_hostname.startswith(
        f"{project_id}."
    ) and app_hostname.endswith(".r.appspot.com")
    if (
        not parsed.hostname.startswith(expected_host_prefix)
        or not (project_host or regional_project_host)
    ):
        raise RuntimeError(
            "Hosted E2E base URL must be the exact App Engine version hostname."
        )

    caller_email = _required(environ, HOSTED_E2E_CALLER_EMAIL).casefold()
    if not caller_email.endswith(f"@{project_id}.iam.gserviceaccount.com"):
        raise RuntimeError(
            "Hosted E2E caller identity must be a service account in the "
            "configured project."
        )
    if caller_email != runtime_email:
        raise RuntimeError(
            "Hosted E2E caller identity must match the attached runtime identity."
        )

    if role == "server":
        if environ.get("GAE_SERVICE") != service:
            raise RuntimeError("Hosted E2E server is not running in the E2E service.")
        if environ.get("GAE_VERSION") != version:
            raise RuntimeError(
                "Hosted E2E server version does not match its configured version."
            )
        session_key = _required(environ, HOSTED_E2E_SESSION_KEY)
        if len(session_key) < 32:
            raise RuntimeError("Hosted E2E session key is too short.")
    else:
        expected_job = _required(environ, HOSTED_E2E_JOB)
        if environ.get("CLOUD_RUN_JOB") != expected_job:
            raise RuntimeError(
                "Hosted E2E runner is not running in its configured Cloud Run job."
            )
        session_key = ""

    return {
        "ADMIN_EMAIL": DEFAULT_ADMIN_EMAIL,
        "ADMIN_NAME": DEFAULT_ADMIN_NAME,
        "PREFIX": prefix,
        "BASE_URL": base_url,
        "APP_URL": base_url,
        "MCP_EVALUATION_ENABLED": True,
        "MCP_EVALUATION_ACTORS": [DEFAULT_ADMIN_EMAIL],
        "MCP_EVALUATION_ORIGIN": base_url,
        "SERVER_NAME": parsed.hostname,
        "SERVER_PORT": "443",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": runtime_email,
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": runtime_email,
        "HOSTED_E2E": True,
        "HOSTED_E2E_ROLE": role,
        "HOSTED_E2E_VERSION": version,
        "HOSTED_E2E_SOURCE": source,
        "HOSTED_E2E_SOURCE_SNAPSHOT": source_snapshot,
        "HOSTED_E2E_BUILD_ID": build_id,
        "HOSTED_E2E_SERVICE": service,
        "HOSTED_E2E_CALLER_EMAIL": caller_email,
        "HOSTED_E2E_SESSION_KEY": session_key,
        "HOSTED_E2E_JOB": str(environ.get(HOSTED_E2E_JOB) or "").strip(),
    }


__all__ = [
    "HOSTED_E2E_BASE_URL",
    "HOSTED_E2E_BUILD_ID",
    "HOSTED_E2E_CALLER_EMAIL",
    "HOSTED_E2E_FLAG",
    "HOSTED_E2E_JOB",
    "HOSTED_E2E_PREFIX",
    "HOSTED_E2E_ROLE",
    "HOSTED_E2E_RUNTIME_EMAIL",
    "HOSTED_E2E_SERVICE",
    "HOSTED_E2E_SERVICE_NAME",
    "HOSTED_E2E_SESSION_KEY",
    "HOSTED_E2E_SOURCE",
    "HOSTED_E2E_SOURCE_SNAPSHOT",
    "HOSTED_E2E_VERSION",
    "hosted_e2e_settings_overrides",
    "is_reserved_hosted_e2e_hostname",
]
