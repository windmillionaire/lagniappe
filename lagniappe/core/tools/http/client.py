"""Bounded outbound HTTP clients for user URLs and fixed providers."""

from dataclasses import dataclass
from io import BytesIO
from ipaddress import ip_address
import re
import socket
import time
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

from PIL import Image
import requests
from requests.adapters import HTTPAdapter

from .models import (
    MAX_URL_BYTES,
    OutboundResult,
    OutboundStatus,
    TrustedProviderPolicy,
    UserFetchPolicy,
)


_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RASTER_MEDIA_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
}
_STREAM_CHUNK_BYTES = 64 * 1024
_HTTP_METHOD = re.compile(r"^[A-Z][A-Z0-9!#$%&'*+.^_`|~-]*$")


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @reason validated URL details are an internal connection-pinning contract
@dataclass(frozen=True)
class _ValidatedURL:
    url: str
    scheme: str
    host: str
    port: int
    explicit_port: bool
    path: str
    query: str

    @property
    def host_header(self) -> str:
        display_host = f"[{self.host}]" if ":" in self.host else self.host
        default_port = 443 if self.scheme == "https" else 80
        if self.explicit_port and self.port != default_port:
            return f"{display_host}:{self.port}"
        return display_host

    def address_url(self, address: str) -> str:
        display_address = f"[{address}]" if ":" in address else address
        default_port = 443 if self.scheme == "https" else 80
        netloc = display_address
        if self.explicit_port or self.port != default_port:
            netloc = f"{display_address}:{self.port}"
        return urlunsplit((self.scheme, netloc, self.path, self.query, ""))


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_pinned_adapter_connects_to_address_with_original_host_and_tls_identity
# @matrix outbound-http : certificate-hostname dns-pinning host-header sni
class _PinnedAddressAdapter(HTTPAdapter):
    """Requests adapter that verifies an IP connection as the original host."""

    def __init__(self, tls_hostname: str | None):
        self.tls_hostname = tls_hostname
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        if self.tls_hostname:
            pool_kwargs.update(
                {
                    "assert_hostname": self.tls_hostname,
                    "server_hostname": self.tls_hostname,
                }
            )
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @reason URL parsing and canonicalization are exercised through user fetch outcomes
def _validate_user_url(value: object, policy: UserFetchPolicy) -> _ValidatedURL:
    if not isinstance(value, str):
        raise ValueError("invalid URL")
    if (
        not value
        or value != value.strip()
        or len(value.encode("utf-8")) > MAX_URL_BYTES
        or _CONTROL_CHARACTER.search(value)
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)
        or "\\" in value
    ):
        raise ValueError("invalid URL")

    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.casefold()
        raw_host = parsed.hostname
        port_value = parsed.port
    except (TypeError, UnicodeError, ValueError) as error:
        raise ValueError("invalid URL") from error

    if (
        scheme not in policy.schemes
        or not parsed.netloc
        or raw_host is None
        or parsed.username is not None
        or parsed.password is not None
        or "%" in raw_host
    ):
        raise ValueError("invalid URL")

    try:
        host = raw_host.encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise ValueError("invalid URL") from error
    if (
        not host
        or host in _BLOCKED_HOSTS
        or host.endswith(".")
        or len(host) > 253
    ):
        raise ValueError("invalid URL")

    try:
        address = ip_address(host)
    except ValueError:
        if any(not _HOST_LABEL.fullmatch(label) for label in host.split(".")):
            raise ValueError("invalid URL")
    else:
        host = address.compressed

    port = port_value if port_value is not None else (443 if scheme == "https" else 80)
    if not 1 <= port <= 65_535:
        raise ValueError("invalid URL")

    explicit_port = port_value is not None
    display_host = f"[{host}]" if ":" in host else host
    netloc = display_host
    default_port = 443 if scheme == "https" else 80
    if explicit_port and port != default_port:
        netloc = f"{display_host}:{port}"
    path = parsed.path or "/"
    canonical = urlunsplit((scheme, netloc, path, parsed.query, ""))
    return _ValidatedURL(
        canonical,
        scheme,
        host,
        port,
        explicit_port,
        path,
        parsed.query,
    )


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @reason DNS classification is exercised through user fetch outcomes
def _resolve_public_addresses(target: _ValidatedURL) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(
            target.host,
            target.port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except (OSError, socket.gaierror) as error:
        raise ConnectionError("resolution failed") from error

    addresses = []
    for record in records:
        try:
            raw_address = record[4][0]
            if "%" in raw_address:
                raise ValueError("scoped resolved address")
            address = ip_address(raw_address)
        except (IndexError, ValueError) as error:
            raise ValueError("invalid resolved address") from error
        if (
            not address.is_global
            or address.is_multicast
            or address.is_unspecified
            or getattr(address, "is_site_local", False)
        ):
            raise ValueError("non-public resolved address")
        normalized = address.compressed
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise ConnectionError("resolution returned no addresses")
    return tuple(addresses)


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @covered-by lagniappe/core/tools/http/client.py::request_trusted_content
# @reason media parsing is exercised through both outbound response boundaries
def _media_type(headers) -> str | None:
    value = headers.get("Content-Type", "") if headers is not None else ""
    media_type = str(value).split(";", 1)[0].strip().casefold()
    return media_type or None


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @covered-by lagniappe/core/tools/http/client.py::request_trusted_content
# @reason media matching is exercised through both outbound response boundaries
def _accepted_media_type(media_type: str | None, accepted: frozenset[str]) -> bool:
    if not media_type:
        return False
    for pattern in accepted:
        if pattern == media_type:
            return True
        if pattern.endswith("/*") and media_type.startswith(pattern[:-1]):
            return True
        if (
            pattern == "application/*+json"
            and media_type.startswith("application/")
            and media_type.endswith("+json")
        ):
            return True
    return False


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @covered-by lagniappe/core/tools/http/client.py::request_trusted_content
# @reason declared-length handling is exercised through bounded response tests
def _declared_size(headers) -> int | None:
    value = headers.get("Content-Length") if headers is not None else None
    if value is None:
        return None
    try:
        size = int(str(value), 10)
    except (TypeError, ValueError):
        return None
    return size if size >= 0 else None


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @covered-by lagniappe/core/tools/http/client.py::request_trusted_content
# @reason streaming enforcement is exercised through bounded response tests
def _stream_body(response, max_bytes: int, deadline_at: float) -> tuple[bytes, int]:
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=_STREAM_CHUNK_BYTES):
        if time.monotonic() >= deadline_at:
            raise TimeoutError("operation deadline exceeded")
        if not chunk:
            continue
        remaining = max_bytes + 1 - size
        kept = bytes(chunk[:remaining])
        chunks.append(kept)
        size += len(kept)
        if size > max_bytes:
            break
    if time.monotonic() >= deadline_at:
        raise TimeoutError("operation deadline exceeded")
    return b"".join(chunks), size


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @reason raster verification is exercised through image policy outcomes
def _verified_raster_media_type(body: bytes) -> str | None:
    try:
        with Image.open(BytesIO(body)) as image:
            detected_format = str(image.format or "").upper()
            image.verify()
    except Exception:
        return None
    return _RASTER_MEDIA_TYPES.get(detected_format)


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @covered-by lagniappe/core/tools/http/client.py::request_trusted_content
# @reason result construction is owned by the two public clients
def _result(
    status: OutboundStatus,
    *,
    body: bytes = b"",
    media_type: str | None = None,
    http_status: int | None = None,
    size: int = 0,
    redirect_count: int = 0,
    final_url: str | None = None,
) -> OutboundResult:
    return OutboundResult(
        status=status,
        body=body,
        media_type=media_type,
        http_status=http_status,
        size=size,
        redirect_count=redirect_count,
        final_url=final_url,
    )


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @covered-by lagniappe/core/tools/http/client.py::request_trusted_content
# @reason cleanup failure handling is exercised through public-client closure tests
def _close_response_session(response, session) -> None:
    """Attempt both cleanup operations without leaking transport exceptions."""
    if response is not None:
        try:
            response.close()
        except Exception:
            pass
    if session is not None:
        try:
            session.close()
        except Exception:
            pass


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::fetch_user_content
# @reason per-address session ownership is exercised through user fetch closure tests
def _user_request(target, address, headers, timeout):
    session = requests.Session()
    session.trust_env = False
    adapter = _PinnedAddressAdapter(target.host if target.scheme == "https" else None)
    session.mount(f"{target.scheme}://", adapter)
    try:
        response = session.get(
            target.address_url(address),
            headers={**(headers or {}), "Host": target.host_header},
            allow_redirects=False,
            timeout=timeout,
            stream=True,
        )
    except Exception:
        _close_response_session(None, session)
        raise
    return session, response


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_pinned_adapter_connects_to_address_with_original_host_and_tls_identity
# @tests tests_unit/test_032_outbound_http.py::test_user_fetch_rejects_malformed_urls_before_resolution
# @tests tests_unit/test_032_outbound_http.py::test_user_fetch_rejects_every_non_public_address_category
# @tests tests_unit/test_032_outbound_http.py::test_user_fetch_rejects_mixed_dns_and_degrades_resolution_failure
# @tests tests_unit/test_032_outbound_http.py::test_user_fetch_pins_redirects_bounds_and_closes_every_response
# @tests tests_unit/test_032_outbound_http.py::test_user_fetch_redirect_and_address_attempt_limits
# @tests tests_unit/test_032_outbound_http.py::test_user_fetch_validates_media_deadline_and_raster_content
# @tests tests_unit/test_032_outbound_http.py::test_user_fetch_assigns_verified_raster_media_type
# @tests tests_unit/test_032_outbound_http.py::test_profile_image_policy_is_https_only
# @tests tests_e2e/004_projects/test_004e_document_forms.py::test_editor_preview_rejects_private_targets_without_disrupting_popover
# @matrix outbound-http : address-failover bounds closure deadline dns-pinning https-only media privacy proxy-isolation raster redirects streaming url-validation
def fetch_user_content(
    url: str,
    policy: UserFetchPolicy,
    *,
    headers: dict[str, str] | None = None,
) -> OutboundResult:
    """Fetch bounded content from a user-selected URL through validated IPs."""
    started_at = time.monotonic()
    deadline_at = started_at + policy.deadline
    current_url = url
    redirect_count = 0
    seen_urls: set[str] = set()

    while True:
        if time.monotonic() >= deadline_at:
            return _result(
                OutboundStatus.TIMEOUT,
                redirect_count=redirect_count,
                final_url=current_url,
            )
        try:
            target = _validate_user_url(current_url, policy)
        except (UnicodeError, ValueError):
            return _result(
                OutboundStatus.REJECTED,
                redirect_count=redirect_count,
                final_url=current_url if isinstance(current_url, str) else None,
            )
        if target.url in seen_urls:
            return _result(
                OutboundStatus.REJECTED,
                redirect_count=redirect_count,
                final_url=target.url,
            )
        seen_urls.add(target.url)

        try:
            addresses = _resolve_public_addresses(target)
        except ValueError:
            return _result(
                OutboundStatus.REJECTED,
                redirect_count=redirect_count,
                final_url=target.url,
            )
        except ConnectionError:
            return _result(
                OutboundStatus.HTTP_ERROR,
                redirect_count=redirect_count,
                final_url=target.url,
            )

        redirected = False
        saw_timeout = False
        for address in addresses[: policy.max_addresses]:
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                saw_timeout = True
                break
            timeout = (
                min(policy.connect_timeout, remaining),
                min(policy.read_timeout, remaining),
            )
            session = None
            response = None
            try:
                session, response = _user_request(target, address, headers, timeout)
                status = int(response.status_code)
                if status in _REDIRECT_STATUSES:
                    location = response.headers.get("Location")
                    if not location or redirect_count >= policy.max_redirects:
                        return _result(
                            OutboundStatus.REJECTED,
                            http_status=status,
                            redirect_count=redirect_count,
                            final_url=target.url,
                        )
                    try:
                        current_url = urljoin(target.url, str(location))
                    except (TypeError, UnicodeError, ValueError):
                        return _result(
                            OutboundStatus.REJECTED,
                            http_status=status,
                            redirect_count=redirect_count,
                            final_url=target.url,
                        )
                    redirect_count += 1
                    redirected = True
                    break
                if not 200 <= status < 300:
                    return _result(
                        OutboundStatus.HTTP_ERROR,
                        http_status=status,
                        redirect_count=redirect_count,
                        final_url=target.url,
                    )

                declared_size = _declared_size(response.headers)
                if declared_size is not None and declared_size > policy.max_bytes:
                    return _result(
                        OutboundStatus.TOO_LARGE,
                        http_status=status,
                        size=declared_size,
                        redirect_count=redirect_count,
                        final_url=target.url,
                    )
                media_type = _media_type(response.headers)
                if not _accepted_media_type(media_type, policy.accepted_media_types):
                    return _result(
                        OutboundStatus.WRONG_TYPE,
                        media_type=media_type,
                        http_status=status,
                        redirect_count=redirect_count,
                        final_url=target.url,
                    )

                body, size = _stream_body(response, policy.max_bytes, deadline_at)
                if size > policy.max_bytes:
                    return _result(
                        OutboundStatus.TOO_LARGE,
                        media_type=media_type,
                        http_status=status,
                        size=size,
                        redirect_count=redirect_count,
                        final_url=target.url,
                    )
                if policy.verify_raster:
                    detected_media_type = _verified_raster_media_type(body)
                    if not detected_media_type:
                        return _result(
                            OutboundStatus.WRONG_TYPE,
                            media_type=media_type,
                            http_status=status,
                            size=size,
                            redirect_count=redirect_count,
                            final_url=target.url,
                        )
                    media_type = detected_media_type
                return _result(
                    OutboundStatus.OK,
                    body=body,
                    media_type=media_type,
                    http_status=status,
                    size=size,
                    redirect_count=redirect_count,
                    final_url=target.url,
                )
            except (requests.Timeout, TimeoutError):
                saw_timeout = True
            except requests.RequestException:
                pass
            finally:
                _close_response_session(response, session)

        if redirected:
            continue
        outcome = (
            OutboundStatus.TIMEOUT
            if saw_timeout or time.monotonic() >= deadline_at
            else OutboundStatus.HTTP_ERROR
        )
        return _result(
            outcome,
            redirect_count=redirect_count,
            final_url=target.url,
        )


# @testable false
# @covered-by lagniappe/core/tools/http/client.py::request_trusted_content
# @reason fixed provider URL construction is exercised through trusted-client tests
def _trusted_url(policy: TrustedProviderPolicy, path: str) -> str:
    try:
        parsed = urlsplit(path)
    except (AttributeError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError("Invalid provider path") from error
    if (
        not isinstance(path, str)
        or not path
        or _CONTROL_CHARACTER.search(path)
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in path)
        or "\\" in path
        or "#" in path
        or "?" in path
        or len(path.encode("utf-8")) > MAX_URL_BYTES
        or parsed.scheme
        or parsed.netloc
    ):
        raise ValueError("Invalid provider path")
    host = f"[{policy.host}]" if ":" in policy.host else policy.host
    default_port = 443 if policy.scheme == "https" else 80
    if policy.port is not None and policy.port != default_port:
        host = f"{host}:{policy.port}"
    return f"{policy.scheme}://{host}/{path.lstrip('/')}"


# @testable true
# @tests tests_unit/test_032_outbound_http.py::test_trusted_client_enforces_fixed_host_bounds_deadline_and_closure
# @tests tests_unit/test_032_outbound_http.py::test_trusted_client_media_acceptance_checks_every_pattern
# @tests tests_unit/test_032_outbound_http.py::test_trusted_client_retries_only_explicit_method_and_status
# @matrix outbound-http : bounds closure deadline fixed-host media privacy proxy-isolation redirects retry streaming trusted-provider
def request_trusted_content(
    method: str,
    path: str,
    policy: TrustedProviderPolicy,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, object] | None = None,
    json_body: object = None,
) -> OutboundResult:
    """Request bounded content from a policy-owned fixed provider origin."""
    method = str(method or "").upper()
    if not _HTTP_METHOD.fullmatch(method):
        return _result(OutboundStatus.REJECTED)
    try:
        url = _trusted_url(policy, path)
    except (UnicodeError, ValueError):
        return _result(OutboundStatus.REJECTED)
    deadline_at = time.monotonic() + policy.deadline
    final_status = OutboundStatus.HTTP_ERROR
    final_http_status = None

    for attempt in range(policy.attempts):
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            final_status = OutboundStatus.TIMEOUT
            break
        timeout = (
            min(policy.connect_timeout, remaining),
            min(policy.read_timeout, remaining),
        )
        session = requests.Session()
        session.trust_env = False
        response = None
        retry = False
        try:
            response = session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                allow_redirects=False,
                timeout=timeout,
                stream=True,
            )
            status = int(response.status_code)
            final_http_status = status
            if status in _REDIRECT_STATUSES:
                return _result(
                    OutboundStatus.HTTP_ERROR,
                    http_status=status,
                    final_url=url,
                )
            if not 200 <= status < 300:
                retry = (
                    attempt + 1 < policy.attempts
                    and method in policy.retry_methods
                    and status in policy.retry_statuses
                )
                if not retry:
                    return _result(
                        OutboundStatus.HTTP_ERROR,
                        http_status=status,
                        final_url=url,
                    )
            else:
                declared_size = _declared_size(response.headers)
                if declared_size is not None and declared_size > policy.max_bytes:
                    return _result(
                        OutboundStatus.TOO_LARGE,
                        http_status=status,
                        size=declared_size,
                        final_url=url,
                    )
                media_type = _media_type(response.headers)
                if not _accepted_media_type(media_type, policy.accepted_media_types):
                    return _result(
                        OutboundStatus.WRONG_TYPE,
                        media_type=media_type,
                        http_status=status,
                        final_url=url,
                    )
                body, size = _stream_body(response, policy.max_bytes, deadline_at)
                if size > policy.max_bytes:
                    return _result(
                        OutboundStatus.TOO_LARGE,
                        media_type=media_type,
                        http_status=status,
                        size=size,
                        final_url=url,
                    )
                return _result(
                    OutboundStatus.OK,
                    body=body,
                    media_type=media_type,
                    http_status=status,
                    size=size,
                    final_url=url,
                )
        except (requests.Timeout, TimeoutError):
            final_status = OutboundStatus.TIMEOUT
            retry = attempt + 1 < policy.attempts and method in policy.retry_methods
        except requests.RequestException:
            final_status = OutboundStatus.HTTP_ERROR
            retry = attempt + 1 < policy.attempts and method in policy.retry_methods
        finally:
            _close_response_session(response, session)

        if not retry:
            break
        delay = policy.retry_backoff[attempt]
        if delay >= deadline_at - time.monotonic():
            final_status = OutboundStatus.TIMEOUT
            break
        if delay:
            time.sleep(delay)

    return _result(
        final_status,
        http_status=final_http_status,
        final_url=url,
    )
