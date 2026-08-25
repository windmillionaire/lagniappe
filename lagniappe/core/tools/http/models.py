"""Typed policy and result models for runtime outbound HTTP."""

from dataclasses import dataclass, field
from enum import Enum
import re
from urllib.parse import urlsplit


MAX_URL_BYTES = 8 * 1024
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_HTTP_METHOD = re.compile(r"^[A-Z][A-Z0-9!#$%&'*+.^_`|~-]*$")
_TRANSIENT_RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_outbound_result_repr_and_diagnostic_never_expose_url_or_body
# @features outbound-http
# @dimensions typed-outcome privacy
class OutboundStatus(str, Enum):
    """Privacy-safe outcomes shared by outbound HTTP callers."""

    OK = "ok"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    TOO_LARGE = "too_large"
    WRONG_TYPE = "wrong_type"


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_outbound_result_repr_and_diagnostic_never_expose_url_or_body
# @features outbound-http
# @dimensions typed-outcome privacy immutable
@dataclass(frozen=True)
class OutboundResult:
    """Bounded response data without transport exception text.

    Body bytes and the final URL are deliberately excluded from ``repr`` so a
    logged result cannot disclose response content or signed URL components.
    """

    status: OutboundStatus
    body: bytes = field(default=b"", repr=False)
    media_type: str | None = None
    http_status: int | None = None
    size: int = 0
    redirect_count: int = 0
    final_url: str | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        """Whether the request produced accepted, verified content."""
        return self.status is OutboundStatus.OK


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_user_policy_rejects_invalid_configuration
# @features outbound-http
# @dimensions user-policy validation
@dataclass(frozen=True)
class UserFetchPolicy:
    """Limits for one class of user-directed GET request."""

    name: str
    schemes: frozenset[str]
    accepted_media_types: frozenset[str]
    max_bytes: int
    max_redirects: int
    connect_timeout: float
    read_timeout: float
    deadline: float
    verify_raster: bool = False
    max_addresses: int = 4

    def __post_init__(self) -> None:
        if (
            not self.name
            or not self.schemes
            or not self.schemes <= {"http", "https"}
            or not self.accepted_media_types
            or self.max_bytes < 1
            or self.max_redirects < 0
            or self.connect_timeout <= 0
            or self.read_timeout <= 0
            or self.deadline <= 0
            or not 1 <= self.max_addresses <= 4
        ):
            raise ValueError("Invalid user fetch policy")


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_trusted_policy_requires_explicit_retry_contract
# @features outbound-http
# @dimensions trusted-policy validation retry
@dataclass(frozen=True)
class TrustedProviderPolicy:
    """Fixed-origin limits for a provider adapter."""

    name: str
    host: str
    accepted_media_types: frozenset[str]
    max_bytes: int
    connect_timeout: float
    read_timeout: float
    deadline: float
    scheme: str = "https"
    port: int | None = None
    max_redirects: int = 0
    attempts: int = 1
    retry_methods: frozenset[str] = frozenset()
    retry_statuses: frozenset[int] = frozenset()
    retry_backoff: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        try:
            if not isinstance(self.host, str) or self.host.endswith("."):
                raise ValueError("Invalid trusted provider policy")
            host = self.host.encode("idna").decode("ascii").casefold()
            methods = frozenset(method.upper() for method in self.retry_methods)
        except (AttributeError, TypeError, UnicodeError) as error:
            raise ValueError("Invalid trusted provider policy") from error
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "retry_methods", methods)
        if (
            not self.name
            or not host
            or len(host) > 253
            or any(not _HOST_LABEL.fullmatch(label) for label in host.split("."))
            or self.scheme not in {"http", "https"}
            or not self.accepted_media_types
            or self.max_bytes < 1
            or self.connect_timeout <= 0
            or self.read_timeout <= 0
            or self.deadline <= 0
            or self.max_redirects != 0
            or self.attempts < 1
            or (self.port is not None and not 1 <= self.port <= 65_535)
            or any(not _HTTP_METHOD.fullmatch(method) for method in methods)
            or any(
                not isinstance(status, int)
                or status not in _TRANSIENT_RETRY_STATUSES
                for status in self.retry_statuses
            )
        ):
            raise ValueError("Invalid trusted provider policy")
        if self.attempts == 1:
            if methods or self.retry_statuses or self.retry_backoff:
                raise ValueError("Single-attempt policies cannot configure retries")
        elif (
            not methods
            or not self.retry_statuses
            or len(self.retry_backoff) != self.attempts - 1
            or any(delay < 0 for delay in self.retry_backoff)
        ):
            raise ValueError("Retries require methods, statuses, attempts, and backoff")


HTML_METADATA_POLICY = UserFetchPolicy(
    name="html_metadata",
    schemes=frozenset({"http", "https"}),
    accepted_media_types=frozenset({"text/html", "application/xhtml+xml"}),
    max_bytes=256 * 1024,
    max_redirects=5,
    connect_timeout=0.5,
    read_timeout=1.0,
    deadline=2.0,
)

BOOKMARK_IMAGE_POLICY = UserFetchPolicy(
    name="bookmark_image",
    schemes=frozenset({"http", "https"}),
    accepted_media_types=frozenset({"image/*"}),
    max_bytes=10 * 1024 * 1024,
    max_redirects=5,
    connect_timeout=1.0,
    read_timeout=2.0,
    deadline=6.0,
    verify_raster=True,
)

PROFILE_IMAGE_POLICY = UserFetchPolicy(
    name="profile_image",
    schemes=frozenset({"https"}),
    accepted_media_types=frozenset({"image/*"}),
    max_bytes=10 * 1024 * 1024,
    max_redirects=5,
    connect_timeout=1.0,
    read_timeout=2.0,
    deadline=4.0,
    verify_raster=True,
)

PLACES_AUTOCOMPLETE_POLICY = TrustedProviderPolicy(
    name="places_autocomplete",
    host="places.googleapis.com",
    accepted_media_types=frozenset({"application/json", "application/*+json"}),
    max_bytes=1024 * 1024,
    connect_timeout=2.0,
    read_timeout=4.0,
    deadline=6.0,
)

PLACES_DETAILS_POLICY = TrustedProviderPolicy(
    name="places_details",
    host="places.googleapis.com",
    accepted_media_types=frozenset({"application/json", "application/*+json"}),
    max_bytes=1024 * 1024,
    connect_timeout=3.0,
    read_timeout=7.0,
    deadline=10.0,
)


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_outbound_result_repr_and_diagnostic_never_expose_url_or_body
# @features outbound-http
# @dimensions diagnostics privacy url-structure
def outbound_diagnostic(result: OutboundResult) -> dict[str, object]:
    """Return a bounded diagnostic projection without URL values or content."""
    diagnostic: dict[str, object] = {
        "outcome": result.status.value,
        "status": result.http_status,
        "size": result.size,
        "has_path": False,
        "has_query": False,
        "has_fragment": False,
        "has_credentials": False,
    }
    try:
        parsed = urlsplit(result.final_url or "")
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return diagnostic

    if parsed.scheme:
        diagnostic["scheme"] = parsed.scheme.casefold()[:16]
    if host:
        diagnostic["host"] = host.casefold()[:253]
    if port is not None:
        diagnostic["port"] = port
    diagnostic.update(
        {
            "has_path": bool(parsed.path and parsed.path != "/"),
            "has_query": bool(parsed.query),
            "has_fragment": bool(parsed.fragment),
            "has_credentials": parsed.username is not None
            or parsed.password is not None,
        }
    )
    return diagnostic
