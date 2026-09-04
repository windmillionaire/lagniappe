"""Authority and path validation for API, browser, and storage URLs."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

from .errors import AdapterError, ConfigurationError, TransportError


_REPORT_PREVIEW_RE = re.compile(r"^/tools/api-plan/[A-Za-z0-9_-]{12}$")
_REPORT_REVIEW_RE = re.compile(r"^/tools/reports/[A-Za-z0-9_-]+$")
_GCS_UPLOAD_RE = re.compile(r"^/upload/storage/v1/b/[^/]+/o$")
_GCS_DOWNLOAD_RE = re.compile(r"^/[^/]+/.+$")
_SIGNED_QUERY_NAMES = frozenset(
    {
        "X-Goog-Algorithm",
        "X-Goog-Credential",
        "X-Goog-Date",
        "X-Goog-Expires",
        "X-Goog-SignedHeaders",
        "X-Goog-Signature",
        "generation",
        "response-content-disposition",
        "response-content-type",
    }
)
_REQUIRED_SIGNED_QUERY_NAMES = frozenset(
    {
        "X-Goog-Algorithm",
        "X-Goog-Credential",
        "X-Goog-Date",
        "X-Goog-Expires",
        "X-Goog-SignedHeaders",
        "X-Goog-Signature",
    }
)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/url_security.py::normalize_site_url
def _loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/url_security.py::normalize_site_url
def _canonical_host(host: str) -> str:
    value = host.casefold()
    if value.endswith(".") or len(value) > 253:
        raise ConfigurationError("invalid_url", "Lagniappe URL has an invalid host.")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        try:
            value.encode("ascii")
        except UnicodeEncodeError as error:
            raise ConfigurationError(
                "invalid_url", "Lagniappe URL host must use canonical ASCII."
            ) from error
        labels = value.split(".")
        if any(
            not label
            or len(label) > 63
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
            for label in labels
        ):
            raise ConfigurationError(
                "invalid_url", "Lagniappe URL has an invalid host."
            )
        return value
    normalized = address.compressed
    return f"[{normalized}]" if address.version == 6 else normalized


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_manual_environment_configuration_is_explicit_and_validated
# @tests tests_unit/test_033_mcp_adapter.py::test_site_url_normalizes_only_canonical_https_or_loopback_origins
@dataclass(frozen=True, slots=True)
class SiteAuthority:
    """One normalized site origin used for every authenticated request."""

    origin: str

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/url_security.py::SiteAuthority
    @property
    def api_base(self) -> str:
        return f"{self.origin}/api/v1"

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/url_security.py::SiteAuthority
    def api_url(self, path: str = "") -> str:
        clean = path.lstrip("/")
        return self.api_base if not clean else f"{self.api_base}/{clean}"


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_manual_environment_configuration_is_explicit_and_validated
# @tests tests_unit/test_033_mcp_adapter.py::test_api_request_uses_only_explicit_bearer_credentials
# @tests tests_unit/test_033_mcp_adapter.py::test_site_url_normalizes_only_canonical_https_or_loopback_origins
def normalize_site_url(value: str) -> SiteAuthority:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError(
            "invalid_url", "Lagniappe URL is malformed."
        ) from error
    if parsed.username or parsed.password:
        raise ConfigurationError(
            "invalid_url", "Lagniappe URL cannot contain user information."
        )
    if parsed.query or parsed.fragment:
        raise ConfigurationError(
            "invalid_url", "Lagniappe URL cannot contain a query or fragment."
        )
    if parsed.path not in {"", "/"}:
        raise ConfigurationError(
            "invalid_url", "Lagniappe URL must be an origin without a path."
        )
    if not parsed.hostname:
        raise ConfigurationError("invalid_url", "Lagniappe URL must include a host.")
    if parsed.scheme == "https":
        if port not in {None, 443}:
            raise ConfigurationError(
                "invalid_url", "HTTPS Lagniappe URL cannot use a nondefault port."
            )
    elif parsed.scheme == "http" and _loopback(parsed.hostname):
        pass
    else:
        raise ConfigurationError(
            "invalid_url",
            "Lagniappe URL must use HTTPS (loopback development may use HTTP).",
        )
    host = _canonical_host(parsed.hostname)
    include_port = port is not None and not (parsed.scheme == "https" and port == 443)
    if include_port and port == 0:
        raise ConfigurationError("invalid_url", "Lagniappe URL has an invalid port.")
    netloc = host if not include_port else f"{host}:{port}"
    return SiteAuthority(urlunsplit((parsed.scheme.casefold(), netloc, "", "", "")))


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
# @tests tests_unit/test_033_mcp_adapter.py::test_submit_refetches_contract_and_posts_only_a_valid_exact_wrapper
def validate_api_url(
    authority: SiteAuthority, value: str, *, expected_path: str | None = None
) -> str:
    """Require an exact configured origin and an allowed versioned API path."""
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError as error:
        raise TransportError(
            "incompatible_url", "Upstream API URL is malformed."
        ) from error
    candidate_origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    if parsed.username or parsed.password or candidate_origin != authority.origin:
        raise TransportError("incompatible_url", "Upstream API URL changed authority.")
    if parsed.query or parsed.fragment:
        raise TransportError(
            "incompatible_url", "Upstream API URL has an unexpected query or fragment."
        )
    if parsed.path != authority.api_base.removeprefix(
        authority.origin
    ) and not parsed.path.startswith("/api/v1/"):
        raise TransportError("incompatible_url", "Upstream API URL is outside /api/v1.")
    if expected_path is not None and parsed.path != expected_path:
        raise TransportError(
            "incompatible_url", "Upstream API URL does not match the expected resource."
        )
    return urlunsplit(parsed)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
# @tests tests_unit/test_033_mcp_adapter.py::test_submit_refetches_contract_and_posts_only_a_valid_exact_wrapper
def validate_human_url(authority: SiteAuthority, value: str) -> str:
    """Validate, but never fetch, an authenticated preview or review link."""
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError as error:
        raise TransportError(
            "incompatible_link", "Human review link is malformed."
        ) from error
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    if parsed.username or parsed.password or origin != authority.origin:
        raise TransportError(
            "incompatible_link", "Human review link changed authority."
        )
    if parsed.query or parsed.fragment:
        raise TransportError(
            "incompatible_link",
            "Human review link has an unexpected query or fragment.",
        )
    if not (
        _REPORT_PREVIEW_RE.fullmatch(parsed.path)
        or _REPORT_REVIEW_RE.fullmatch(parsed.path)
    ):
        raise TransportError(
            "incompatible_link", "Human review link has an unexpected path."
        )
    return urlunsplit(parsed)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
def quote_path_segment(value: str) -> str:
    text = str(value or "")
    if not text or len(text) > 2048:
        raise AdapterError(
            "invalid_plan_id", "plan_id must be a non-empty bounded string."
        )
    return quote(text, safe="")


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_storage_url_requires_exact_resumable_and_signed_parameters
# @tests tests_unit/test_033_mcp_adapter.py::test_media_download_does_not_inherit_client_credentials_or_cookies
def validate_storage_url(value: str, *, upload: bool) -> str:
    """Accept only the frozen path families on the exact GCS HTTPS origin."""
    try:
        parsed = urlsplit(str(value or ""))
        port = parsed.port
    except ValueError as error:
        raise TransportError(
            "unsafe_storage_url", "Storage URL is malformed."
        ) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "storage.googleapis.com"
        or port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise TransportError(
            "unsafe_storage_url", "Storage URL is outside the approved origin."
        )
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    names = [name for name, _ in pairs]
    values = dict(pairs)
    if len(names) != len(set(names)):
        raise TransportError(
            "unsafe_storage_url", "Storage URL contains duplicate parameters."
        )
    if upload:
        if not _GCS_UPLOAD_RE.fullmatch(parsed.path):
            raise TransportError(
                "unsafe_storage_url", "Storage upload URL has an unexpected path."
            )
        upload_names = set(names)
        if not {"uploadType", "upload_id"}.issubset(
            upload_names
        ) or not upload_names.issubset(
            {"ifGenerationMatch", "name", "uploadType", "upload_id"}
        ):
            raise TransportError(
                "unsafe_storage_url", "Storage upload URL has unexpected parameters."
            )
        if (
            values.get("uploadType") != "resumable"
            or not values.get("upload_id")
            or ("name" in values and not values["name"])
            or (
                "ifGenerationMatch" in values
                and values["ifGenerationMatch"] != "0"
            )
        ):
            raise TransportError(
                "unsafe_storage_url", "Storage upload URL is not resumable."
            )
    else:
        if not _GCS_DOWNLOAD_RE.fullmatch(parsed.path):
            raise TransportError(
                "unsafe_storage_url", "Storage download URL has an unexpected path."
            )
        if not pairs or any(name not in _SIGNED_QUERY_NAMES for name in names):
            raise TransportError(
                "unsafe_storage_url", "Storage download URL has unexpected parameters."
            )
        if not _REQUIRED_SIGNED_QUERY_NAMES.issubset(names) or any(
            not values[name] for name in _REQUIRED_SIGNED_QUERY_NAMES
        ):
            raise TransportError(
                "unsafe_storage_url", "Storage download URL is not signed."
            )
        if values["X-Goog-Algorithm"] != "GOOG4-RSA-SHA256":
            raise TransportError(
                "unsafe_storage_url",
                "Storage download URL uses an unexpected signature algorithm.",
            )
        expires = values["X-Goog-Expires"]
        if not expires.isdigit() or not 1 <= int(expires) <= 300:
            raise TransportError(
                "unsafe_storage_url", "Storage download URL has an unsafe expiry."
            )
        if not re.fullmatch(r"\d{8}T\d{6}Z", values["X-Goog-Date"]):
            raise TransportError(
                "unsafe_storage_url",
                "Storage download URL has an invalid signing date.",
            )
        if values["X-Goog-SignedHeaders"] != "host":
            raise TransportError(
                "unsafe_storage_url", "Storage download URL signs unexpected headers."
            )
        if not re.fullmatch(r"[0-9a-fA-F]{64,}", values["X-Goog-Signature"]):
            raise TransportError(
                "unsafe_storage_url", "Storage download URL has an invalid signature."
            )
    return urlunsplit(parsed)
