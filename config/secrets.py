"""Runtime-safe secret boundary and GCP Secret Manager client.

This module belongs to ``config/`` and is uploaded with the App Engine
application. It never imports ``installer/`` or ``runner/``.
"""

from __future__ import annotations

import base64
import copy
import json
import re
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import requests

SECRETS_BACKEND_LOCAL = "local_yaml"
SECRETS_BACKEND_SECRET_MANAGER = "secret_manager"
VALID_SECRETS_BACKENDS = frozenset(
    {SECRETS_BACKEND_LOCAL, SECRETS_BACKEND_SECRET_MANAGER}
)
DEFAULT_RUNTIME_SECRET_NAME = "lagniappe-runtime-secrets"
DEFAULT_RUNTIME_SECRET_VERSION = "current"
RUNTIME_SECRETS_SCHEMA_VERSION = 1
SECRET_PAYLOAD_LIMIT_BYTES = 65536
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

_PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_SECRET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_VERSION_NUMBER_PATTERN = re.compile(r"^[1-9][0-9]*$")

# Complete inventory of persisted runtime secrets (Stage 0 audit).
# Whole-key secrets moved out of lagniappe_settings.yaml when
# SECRETS_BACKEND == "secret_manager".
SECRET_TOP_LEVEL_KEYS = frozenset(
    {
        "SECRET_KEY",
        "GIBBERISH",
        "AGENT_ACCESS_CODE",
        "REDIS_PASSWORD",
        "SENTRY_DSN",
    }
)

# Nested secret subfields inside structured settings dicts. Non-secret sibling
# metadata (provider, host, senderEmail, domainId, etc.) stays on disk so
# diagnostics, handoff views, and non-secret validation remain readable.
SECRET_NESTED_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AUTH_EMAIL_CONFIG", ("password",)),
    ("AI_EMAIL_CONFIG", ("resend", "webhookSecret")),
    ("AI_EMAIL_CONFIG", ("resend", "inboundApiKey")),
    ("AI_EMAIL_CONFIG", ("resend", "sendingApiKey")),
)

_ALLOWED_SECRET_ROOTS = SECRET_TOP_LEVEL_KEYS | frozenset(
    top for top, _ in SECRET_NESTED_PATHS
)


class SecretsBackendError(RuntimeError):
    """Secret-free error raised when Secret Manager runtime config fails."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode_mapping(value: object) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(decoded, dict):
            return decoded
    return None


def _pop_nested(container: dict[str, Any], path: tuple[str, ...]) -> object | None:
    cursor: Any = container
    parents: list[tuple[dict[str, Any], str]] = []
    for segment in path[:-1]:
        if not isinstance(cursor, dict) or segment not in cursor:
            return None
        parents.append((cursor, segment))
        cursor = cursor[segment]
    leaf = path[-1]
    if not isinstance(cursor, dict) or leaf not in cursor:
        return None
    value = cursor.pop(leaf)
    for parent, segment in reversed(parents):
        child = parent.get(segment)
        if isinstance(child, dict) and not child:
            parent.pop(segment, None)
    return value


def _get_nested(container: Mapping[str, Any], path: tuple[str, ...]) -> object | None:
    cursor: Any = container
    for segment in path:
        if not isinstance(cursor, Mapping) or segment not in cursor:
            return None
        cursor = cursor[segment]
    return cursor


def _set_nested(
    container: dict[str, Any], path: tuple[str, ...], value: object
) -> None:
    cursor = container
    for segment in path[:-1]:
        existing = cursor.get(segment)
        if not isinstance(existing, dict):
            existing = {}
            cursor[segment] = existing
        cursor = existing
    cursor[path[-1]] = copy.deepcopy(value)


def normalize_secrets_config(settings: Mapping[str, object]) -> dict[str, str]:
    """Validate and normalize SECRETS_BACKEND settings."""
    raw_backend = settings.get("SECRETS_BACKEND")
    backend = (
        SECRETS_BACKEND_LOCAL
        if raw_backend in (None, "")
        else str(raw_backend).strip().casefold()
    )
    if backend not in VALID_SECRETS_BACKENDS:
        raise SecretsBackendError(
            "SECRETS_BACKEND must be 'local_yaml' or 'secret_manager'."
        )
    raw_name = settings.get("SECRETS_SECRET_NAME")
    secret_name = (
        DEFAULT_RUNTIME_SECRET_NAME
        if raw_name in (None, "")
        else str(raw_name).strip()
    )
    if not _SECRET_NAME_PATTERN.fullmatch(secret_name):
        raise SecretsBackendError("SECRETS_SECRET_NAME is invalid.")

    raw_version = settings.get("SECRETS_VERSION")
    version = (
        DEFAULT_RUNTIME_SECRET_VERSION
        if raw_version in (None, "")
        else str(raw_version).strip()
    )
    if version != DEFAULT_RUNTIME_SECRET_VERSION and not _VERSION_NUMBER_PATTERN.fullmatch(
        version
    ):
        raise SecretsBackendError(
            "SECRETS_VERSION must be 'current' or a positive integer version."
        )
    return {
        "SECRETS_BACKEND": backend,
        "SECRETS_SECRET_NAME": secret_name,
        "SECRETS_VERSION": version,
    }


def uses_secret_manager(settings: Mapping[str, object]) -> bool:
    """Return True when the settings mapping selects GCP Secret Manager."""
    raw = settings.get("SECRETS_BACKEND")
    return isinstance(raw, str) and raw.strip().casefold() == SECRETS_BACKEND_SECRET_MANAGER


def extract_secret_settings(settings: Mapping[str, object]) -> dict[str, object]:
    """Extract only defined runtime secret keys and nested secret subfields."""
    extracted: dict[str, object] = {}
    for key in sorted(SECRET_TOP_LEVEL_KEYS):
        value = settings.get(key)
        if value not in (None, ""):
            extracted[key] = copy.deepcopy(value)

    for top_key, nested_path in SECRET_NESTED_PATHS:
        decoded = _decode_mapping(settings.get(top_key))
        if not decoded:
            continue
        value = _get_nested(decoded, nested_path)
        if value not in (None, ""):
            target = extracted.setdefault(top_key, {})
            if isinstance(target, dict):
                _set_nested(target, nested_path, value)
    return extracted


def strip_secret_settings(settings: Mapping[str, object]) -> dict[str, object]:
    """Return a copy of settings with all runtime secret values removed."""
    stripped: dict[str, Any] = copy.deepcopy(dict(settings))
    for key in SECRET_TOP_LEVEL_KEYS:
        stripped.pop(key, None)

    for top_key, nested_path in SECRET_NESTED_PATHS:
        if top_key not in stripped:
            continue
        was_json_string = isinstance(stripped[top_key], str)
        decoded = _decode_mapping(stripped[top_key])
        if decoded is None:
            continue
        _pop_nested(decoded, nested_path)
        if decoded:
            stripped[top_key] = (
                json.dumps(decoded, sort_keys=True) if was_json_string else decoded
            )
        else:
            stripped.pop(top_key, None)
    return stripped


def merge_secret_settings(
    non_secret: Mapping[str, object], secrets_map: Mapping[str, object]
) -> dict[str, object]:
    """Merge hydrated secret values into a fresh copy of non-secret settings."""
    merged: dict[str, Any] = copy.deepcopy(dict(non_secret))
    for key in sorted(SECRET_TOP_LEVEL_KEYS):
        if key in secrets_map and secrets_map[key] not in (None, ""):
            merged[key] = copy.deepcopy(secrets_map[key])

    for top_key, nested_path in SECRET_NESTED_PATHS:
        secret_container = secrets_map.get(top_key)
        if not isinstance(secret_container, Mapping):
            continue
        secret_value = _get_nested(secret_container, nested_path)
        if secret_value in (None, ""):
            continue
        existing_raw = merged.get(top_key)
        was_json_string = isinstance(existing_raw, str)
        existing = _decode_mapping(existing_raw) or {}
        _set_nested(existing, nested_path, secret_value)
        merged[top_key] = (
            json.dumps(existing, sort_keys=True) if was_json_string else existing
        )
    return merged


def find_leaked_secret_keys(disk_settings: Mapping[str, object]) -> list[str]:
    """Return dotted paths for any runtime secret still present in disk settings."""
    leaked: list[str] = []
    for key in sorted(SECRET_TOP_LEVEL_KEYS):
        if disk_settings.get(key) not in (None, ""):
            leaked.append(key)
    for top_key, nested_path in SECRET_NESTED_PATHS:
        decoded = _decode_mapping(disk_settings.get(top_key))
        if not decoded:
            continue
        if _get_nested(decoded, nested_path) not in (None, ""):
            leaked.append(".".join((top_key, *nested_path)))
    return sorted(leaked)


def validate_secret_envelope(
    envelope: object, *, project_id: str
) -> dict[str, object]:
    """Validate the Secret Manager JSON envelope and return its secrets mapping."""
    if not _PROJECT_PATTERN.fullmatch(project_id):
        raise SecretsBackendError("GOOGLE_CLOUD_PROJECT is missing or invalid.")
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"schema", "project", "secrets"}
        or envelope["schema"] != RUNTIME_SECRETS_SCHEMA_VERSION
        or envelope["project"] != project_id
        or not isinstance(envelope["secrets"], dict)
    ):
        raise SecretsBackendError(
            "Runtime secrets envelope schema or project does not match."
        )
    secrets_map: dict[str, object] = envelope["secrets"]
    unknown = sorted(set(secrets_map) - _ALLOWED_SECRET_ROOTS)
    if unknown:
        raise SecretsBackendError(
            "Runtime secrets envelope contains unsupported keys: "
            + ", ".join(unknown)
        )
    return copy.deepcopy(secrets_map)


def _build_crc32c_table() -> tuple[int, ...]:
    table: list[int] = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F63B78 if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


_CRC32C_TABLE = _build_crc32c_table()


def _crc32c_value(raw: bytes) -> int:
    """Compute IEEE Castagnoli CRC32C without extra runtime dependencies."""
    crc = 0xFFFFFFFF
    for byte in raw:
        crc = _CRC32C_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def _adc_access_token() -> str:
    try:
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
        credentials.refresh(Request())
        token = getattr(credentials, "token", None)
    except Exception as error:
        raise SecretsBackendError(
            "Could not obtain Google Cloud credentials for Secret Manager."
        ) from error
    if not isinstance(token, str) or not token:
        raise SecretsBackendError(
            "Google Cloud credentials did not return an access token."
        )
    return token


class SecretManagerRuntimeStore:
    """Bounded, secret-free REST client for ``lagniappe-runtime-secrets``."""

    def __init__(
        self,
        project_id: str,
        secret_name: str = DEFAULT_RUNTIME_SECRET_NAME,
        *,
        access_token: str | None = None,
        session: requests.Session | None = None,
        propagation_retry_delays: tuple[float, ...] | None = None,
    ) -> None:
        if not _PROJECT_PATTERN.fullmatch(project_id):
            raise SecretsBackendError("GOOGLE_CLOUD_PROJECT is missing or invalid.")
        if not _SECRET_NAME_PATTERN.fullmatch(secret_name):
            raise SecretsBackendError("SECRETS_SECRET_NAME is invalid.")
        self.project_id = project_id
        self.secret_name = secret_name
        self.url = (
            f"https://secretmanager.googleapis.com/v1/"
            f"projects/{project_id}/secrets/{secret_name}"
        )
        if session is None:
            import requests

            self.session = requests.Session()
            self._propagation_retry_delays = (
                (3.0, 6.0, 12.0)
                if propagation_retry_delays is None
                else propagation_retry_delays
            )
        else:
            self.session = session
            self._propagation_retry_delays = (
                () if propagation_retry_delays is None else propagation_retry_delays
            )
        token = access_token if access_token is not None else _adc_access_token()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _request(
        self,
        method: str,
        suffix: str = "",
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        retry_propagation: bool = False,
    ) -> dict[str, Any]:
        import requests

        delays = self._propagation_retry_delays if retry_propagation else ()
        response = None
        for attempt in range(len(delays) + 1):
            try:
                response = self.session.request(
                    method,
                    self.url + suffix,
                    json=json_body,
                    params=params,
                    timeout=15,
                    allow_redirects=False,
                )
            except requests.RequestException as error:
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                raise SecretsBackendError(
                    "Secret Manager request failed. Check network access and project."
                ) from error
            if response.ok:
                break
            if (
                attempt < len(delays)
                and response.status_code in {403, 429, 500, 502, 503, 504}
            ):
                time.sleep(delays[attempt])
                continue
            raise SecretsBackendError(
                f"Secret Manager returned HTTP {response.status_code} for "
                f"{self.secret_name}. Check Secret Manager API, IAM secretAccessor "
                "binding, and current version."
            )
        assert response is not None
        try:
            data = response.json()
        except ValueError as error:
            raise SecretsBackendError(
                "Secret Manager returned invalid JSON metadata."
            ) from error
        if not isinstance(data, dict):
            raise SecretsBackendError("Secret Manager returned an unexpected payload.")
        return data

    def access(
        self, version: str = DEFAULT_RUNTIME_SECRET_VERSION
    ) -> tuple[str, dict[str, object]]:
        """Read and verify one version of the runtime secrets JSON envelope."""
        if version != DEFAULT_RUNTIME_SECRET_VERSION and not _VERSION_NUMBER_PATTERN.fullmatch(
            version
        ):
            raise SecretsBackendError(
                "SECRETS_VERSION must be 'current' or a positive integer version."
            )
        data = self._request("GET", f"/versions/{version}:access")
        name = data.get("name")
        payload = data.get("payload")
        if not isinstance(name, str) or not isinstance(payload, dict):
            raise SecretsBackendError("Secret Manager returned an incomplete version.")
        number = name.rsplit("/", 1)[-1]
        encoded = payload.get("data")
        if not isinstance(encoded, str):
            raise SecretsBackendError("Secret Manager version payload is missing.")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise SecretsBackendError(
                "Secret Manager version payload could not be decoded."
            ) from error
        expected_crc = payload.get("dataCrc32c")
        actual_crc = _crc32c_value(raw)
        if (
            not _VERSION_NUMBER_PATTERN.fullmatch(number)
            or version not in {DEFAULT_RUNTIME_SECRET_VERSION, number}
            or len(raw) > SECRET_PAYLOAD_LIMIT_BYTES
            or (
                actual_crc is not None
                and expected_crc is not None
                and actual_crc != int(str(expected_crc))
            )
        ):
            raise SecretsBackendError(
                "Secret Manager version or checksum verification failed."
            )
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SecretsBackendError(
                "Runtime secrets payload is not valid JSON."
            ) from error
        return number, validate_secret_envelope(envelope, project_id=self.project_id)

    def publish(self, secrets_map: Mapping[str, object]) -> str:
        """Idempotently publish a verified runtime-secrets JSON version and update 'current'."""
        envelope: dict[str, object] = {
            "schema": RUNTIME_SECRETS_SCHEMA_VERSION,
            "project": self.project_id,
            "secrets": extract_secret_settings(secrets_map),
        }
        validated_secrets = validate_secret_envelope(
            envelope, project_id=self.project_id
        )
        envelope["secrets"] = validated_secrets
        metadata = self._request("GET", retry_propagation=True)
        aliases = metadata.get("versionAliases") or {}
        if not isinstance(aliases, dict):
            aliases = {}
        current = str(aliases.get(DEFAULT_RUNTIME_SECRET_VERSION) or "")
        if current:
            try:
                _, existing_secrets = self.access(current)
            except SecretsBackendError:
                existing_secrets = None
            if existing_secrets == validated_secrets:
                return current

        raw = _canonical_json(envelope).encode("utf-8")
        if len(raw) > SECRET_PAYLOAD_LIMIT_BYTES:
            raise SecretsBackendError(
                "Runtime secrets exceed the 64 KiB Secret Manager payload limit."
            )
        payload: dict[str, object] = {"data": base64.b64encode(raw).decode("ascii")}
        crc = _crc32c_value(raw)
        if crc is not None:
            payload["dataCrc32c"] = str(crc)
        added = self._request(
            "POST",
            ":addVersion",
            json_body={"payload": payload},
            retry_propagation=True,
        )
        added_name = added.get("name")
        etag = metadata.get("etag")
        if not isinstance(added_name, str) or not isinstance(etag, str):
            raise SecretsBackendError(
                "Secret Manager returned incomplete version metadata."
            )
        version = added_name.rsplit("/", 1)[-1]
        if not _VERSION_NUMBER_PATTERN.fullmatch(version):
            raise SecretsBackendError("Secret Manager returned an invalid version ID.")
        if self.access(version)[1] != validated_secrets:
            raise SecretsBackendError(
                "The new runtime secrets version failed read-back verification."
            )
        self._request(
            "PATCH",
            params={"updateMask": "version_aliases"},
            json_body={
                "etag": etag,
                "versionAliases": {**aliases, DEFAULT_RUNTIME_SECRET_VERSION: version},
            },
            retry_propagation=True,
        )
        return version


def load_runtime_secrets(
    settings: Mapping[str, object],
    *,
    store: SecretManagerRuntimeStore | None = None,
) -> dict[str, object]:
    """Hydrate runtime secrets from GCP Secret Manager for the configured project."""
    normalized = normalize_secrets_config(settings)
    if normalized["SECRETS_BACKEND"] != SECRETS_BACKEND_SECRET_MANAGER:
        return {}
    project_id = str(settings.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not _PROJECT_PATTERN.fullmatch(project_id):
        raise SecretsBackendError(
            "GOOGLE_CLOUD_PROJECT is required when SECRETS_BACKEND is 'secret_manager'."
        )
    client = store or SecretManagerRuntimeStore(
        project_id, normalized["SECRETS_SECRET_NAME"]
    )
    _, secrets_map = client.access(normalized["SECRETS_VERSION"])
    return secrets_map


def save_runtime_secrets(
    settings: Mapping[str, object],
    secrets_map: Mapping[str, object],
    *,
    store: SecretManagerRuntimeStore | None = None,
) -> str:
    """Persist runtime secrets to GCP Secret Manager and return the active version."""
    normalized = normalize_secrets_config(settings)
    if normalized["SECRETS_BACKEND"] != SECRETS_BACKEND_SECRET_MANAGER:
        raise SecretsBackendError(
            "save_runtime_secrets requires SECRETS_BACKEND='secret_manager'."
        )
    project_id = str(settings.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not _PROJECT_PATTERN.fullmatch(project_id):
        raise SecretsBackendError(
            "GOOGLE_CLOUD_PROJECT is required when SECRETS_BACKEND is 'secret_manager'."
        )
    client = store or SecretManagerRuntimeStore(
        project_id, normalized["SECRETS_SECRET_NAME"]
    )
    return client.publish(secrets_map)
