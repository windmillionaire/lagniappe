"""Shared outbound HTTP policy, pinning, bounds, and privacy contracts."""

from collections import deque
from dataclasses import replace
from io import BytesIO
import socket

from PIL import Image
import pytest
import requests

from lagniappe.core.tools.http import (
    BOOKMARK_IMAGE_POLICY,
    HTML_METADATA_POLICY,
    PROFILE_IMAGE_POLICY,
    OutboundResult,
    OutboundStatus,
    TrustedProviderPolicy,
    fetch_user_content,
    outbound_diagnostic,
    request_trusted_content,
)
from lagniappe.core.tools.http import client
from lagniappe.core.tools.links import metadata as link_metadata


pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=(), close_error=None):
        self.status_code = status
        self.headers = headers or {}
        self.chunks = list(chunks)
        self.closed = False
        self.close_error = close_error

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


class FakeSession:
    def __init__(self, responses=()):
        self.responses = deque(responses)
        self.trust_env = True
        self.mounts = []
        self.calls = []
        self.closed = False

    def mount(self, prefix, adapter):
        self.mounts.append((prefix, adapter))

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


def _record(address, port=443):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    endpoint = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", endpoint)


def _public_dns(monkeypatch, *addresses):
    monkeypatch.setattr(
        client.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [_record(address) for address in addresses],
    )


def _image_bytes(format="PNG"):
    output = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(output, format=format)
    return output.getvalue()


def _user_response(monkeypatch, responses, *, addresses=("93.184.216.34",)):
    _public_dns(monkeypatch, *addresses)
    pending = deque(responses)
    calls = []
    sessions = []

    def request(target, address, headers, timeout):
        calls.append((target, address, headers, timeout))
        response = pending.popleft()
        if isinstance(response, Exception):
            raise response
        session = FakeSession()
        sessions.append(session)
        return session, response

    monkeypatch.setattr(client, "_user_request", request)
    return calls, sessions


# @matrix link : fallback metadata relative-image
# @pairs bookmark:metadata outbound-http:privacy
def test_link_metadata_uses_typed_fetch_and_resolves_relative_images(monkeypatch):
    body = b"""
        <html><head>
          <meta property="og:title" content="Fetched title">
          <meta property="og:image" content="../images/card.png">
        </head></html>
    """
    result = OutboundResult(
        OutboundStatus.OK,
        body=body,
        media_type="text/html",
        http_status=200,
        size=len(body),
        final_url="https://final.example/articles/one",
    )
    monkeypatch.setattr(link_metadata, "fetch_user_content", lambda *args, **kwargs: result)

    metadata = link_metadata.get_link_attributes("https://start.example/original")

    assert metadata["name"] == "Fetched title"
    assert metadata["image"] == "https://final.example/images/card.png"

    monkeypatch.setattr(
        link_metadata,
        "fetch_user_content",
        lambda *args, **kwargs: OutboundResult(OutboundStatus.HTTP_ERROR),
    )
    fallback = link_metadata.get_link_attributes(
        "https://user:signed-secret@example.test/private?token=private"
    )
    assert fallback == {
        "name": "Broken link - example.test",
        "description": None,
        "image": None,
    }
    assert "signed-secret" not in repr(fallback)

    parser_response = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=[b"<html><title>Parser failure</title></html>"],
    )
    _user_response(monkeypatch, [parser_response])
    monkeypatch.setattr(link_metadata, "fetch_user_content", fetch_user_content)
    monkeypatch.setattr(
        link_metadata,
        "extract_link_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("parse failed")),
    )

    parser_fallback = link_metadata.get_link_attributes(
        "https://parser.example/page"
    )

    assert parser_fallback["name"] == "Broken link - parser.example"
    assert parser_response.closed


# @matrix outbound-http : diagnostics immutable privacy typed-outcome url-structure
def test_outbound_result_repr_and_diagnostic_never_expose_url_or_body():
    secret = "query-token-must-not-appear"
    fragment = "fragment-token-must-not-appear"
    body = b"private-response-body"
    result = OutboundResult(
        OutboundStatus.HTTP_ERROR,
        body=body,
        media_type="text/html",
        http_status=503,
        size=len(body),
        final_url=f"https://user:pass@example.test/private?sig={secret}#{fragment}",
    )

    representation = repr(result)
    diagnostic = outbound_diagnostic(result)
    rendered_diagnostic = repr(diagnostic)

    assert secret not in representation + rendered_diagnostic
    assert fragment not in representation + rendered_diagnostic
    assert body.decode() not in representation + rendered_diagnostic
    assert diagnostic == {
        "outcome": "http_error",
        "status": 503,
        "size": len(body),
        "has_path": True,
        "has_query": True,
        "has_fragment": True,
        "has_credentials": True,
        "scheme": "https",
        "host": "example.test",
    }
    with pytest.raises(Exception):
        result.size = 0


# @matrix outbound-http : user-policy validation
def test_user_policy_rejects_invalid_configuration():
    with pytest.raises(ValueError, match="Invalid user fetch policy"):
        replace(HTML_METADATA_POLICY, max_addresses=5)
    with pytest.raises(ValueError, match="Invalid user fetch policy"):
        replace(HTML_METADATA_POLICY, schemes=frozenset({"file"}))


# @matrix outbound-http : retry trusted-policy validation
def test_trusted_policy_requires_explicit_retry_contract():
    with pytest.raises(ValueError, match="Retries require"):
        TrustedProviderPolicy(
            name="incomplete-retry",
            host="provider.example",
            accepted_media_types=frozenset({"application/json"}),
            max_bytes=100,
            connect_timeout=1,
            read_timeout=1,
            deadline=3,
            attempts=2,
            retry_methods=frozenset({"GET"}),
        )
    with pytest.raises(ValueError, match="Single-attempt"):
        replace(
            TrustedProviderPolicy(
                name="single",
                host="provider.example",
                accepted_media_types=frozenset({"application/json"}),
                max_bytes=100,
                connect_timeout=1,
                read_timeout=1,
                deadline=3,
            ),
            retry_methods=frozenset({"GET"}),
        )
    with pytest.raises(ValueError, match="Invalid trusted provider policy"):
        replace(
            TrustedProviderPolicy(
                name="provider",
                host="provider.example",
                accepted_media_types=frozenset({"application/json"}),
                max_bytes=100,
                connect_timeout=1,
                read_timeout=1,
                deadline=3,
            ),
            host="provider.example@attacker.example",
        )
    with pytest.raises(ValueError, match="Invalid trusted provider policy"):
        TrustedProviderPolicy(
            name="invalid-retry-status",
            host="provider.example",
            accepted_media_types=frozenset({"application/json"}),
            max_bytes=100,
            connect_timeout=1,
            read_timeout=1,
            deadline=3,
            attempts=2,
            retry_methods=frozenset({"GET"}),
            retry_statuses=frozenset({404}),
            retry_backoff=(0,),
        )


# @matrix outbound-http : certificate-hostname dns-pinning host-header proxy-isolation sni
def test_pinned_adapter_connects_to_address_with_original_host_and_tls_identity(
    monkeypatch,
):
    response = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=[b"<title>Safe</title>"],
    )
    session = FakeSession([response])
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    _public_dns(monkeypatch, "2606:4700:4700::1111")

    result = fetch_user_content(
        "https://Example.COM:8443/private?signature=secret#not-on-wire",
        HTML_METADATA_POLICY,
    )

    assert result.ok
    assert session.trust_env is False
    assert session.calls[0][1] == (
        "https://[2606:4700:4700::1111]:8443/private?signature=secret"
    )
    assert session.calls[0][2]["headers"]["Host"] == "example.com:8443"
    assert session.calls[0][2]["allow_redirects"] is False
    assert session.calls[0][2]["stream"] is True
    prefix, adapter = session.mounts[0]
    assert prefix == "https://"
    pool = adapter.poolmanager.connection_from_url(session.calls[0][1])
    assert pool.host == "2606:4700:4700::1111"
    assert pool.conn_kw["server_hostname"] == "example.com"
    assert pool.assert_hostname == "example.com"
    assert response.closed and session.closed


# @pair outbound-http:url-validation
@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.test/file",
        "https://user:password@example.test/",
        "https://example.test:99999/",
        "https://example.test:0/",
        "https://example..test/",
        "https://example.test./",
        "https://example.test/path\\segment",
        "https://example.test/line\nfeed",
        "https://example.test/zero\u200bwidth",
        "https://[fe80::1%25eth0]/",
        "https://[::1",
        "https://example.test/" + "x" * (8 * 1024),
    ],
)
def test_user_fetch_rejects_malformed_urls_before_resolution(monkeypatch, url):
    called = []
    monkeypatch.setattr(
        client.socket,
        "getaddrinfo",
        lambda *args, **kwargs: called.append(args),
    )
    result = fetch_user_content(url, HTML_METADATA_POLICY)

    assert result.status is OutboundStatus.REJECTED
    assert called == []


# @matrix outbound-http : dns-pinning url-validation
@pytest.mark.parametrize(
    "url,resolved",
    [
        ("http://127.0.0.1/", "127.0.0.1"),
        ("http://10.1.2.3/", "10.1.2.3"),
        ("http://100.64.0.1/", "100.64.0.1"),
        ("http://169.254.169.254/", "169.254.169.254"),
        ("http://192.0.2.1/", "192.0.2.1"),
        ("http://198.18.0.1/", "198.18.0.1"),
        ("http://224.0.0.1/", "224.0.0.1"),
        ("http://255.255.255.255/", "255.255.255.255"),
        ("http://0.0.0.0/", "0.0.0.0"),
        ("http://[::1]/", "::1"),
        ("http://[fc00::1]/", "fc00::1"),
        ("http://[fe80::1]/", "fe80::1"),
        ("http://[fec0::1]/", "fec0::1"),
        ("http://[ff00::1]/", "ff00::1"),
        ("http://[::]/", "::"),
        ("http://[2001:db8::1]/", "2001:db8::1"),
        ("http://2130706433/", "127.0.0.1"),
        ("http://0177.0.0.1/", "127.0.0.1"),
        ("http://0x7f000001/", "127.0.0.1"),
    ],
)
def test_user_fetch_rejects_every_non_public_address_category(
    monkeypatch, url, resolved
):
    _public_dns(monkeypatch, resolved)
    request = []
    monkeypatch.setattr(client, "_user_request", lambda *args: request.append(args))

    result = fetch_user_content(url, HTML_METADATA_POLICY)

    assert result.status is OutboundStatus.REJECTED
    assert request == []


# @pair outbound-http:dns-pinning
def test_user_fetch_rejects_mixed_dns_and_degrades_resolution_failure(monkeypatch):
    _public_dns(monkeypatch, "93.184.216.34", "127.0.0.1")
    assert (
        fetch_user_content("https://mixed.example/", HTML_METADATA_POLICY).status
        is OutboundStatus.REJECTED
    )

    monkeypatch.setattr(
        client.socket,
        "getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(socket.gaierror()),
    )
    assert (
        fetch_user_content("https://missing.example/", HTML_METADATA_POLICY).status
        is OutboundStatus.HTTP_ERROR
    )

    _public_dns(monkeypatch, "fe80::1%eth0")
    assert (
        fetch_user_content("https://scoped.example/", HTML_METADATA_POLICY).status
        is OutboundStatus.REJECTED
    )


# @matrix outbound-http : closure dns-pinning redirects
def test_user_fetch_pins_redirects_bounds_and_closes_every_response(monkeypatch):
    first = FakeResponse(302, {"Location": "/next"})
    second = FakeResponse(302, {"Location": "https://other.example/final"})
    final = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=[b"<title>Done</title>"],
    )
    calls, sessions = _user_response(monkeypatch, [first, second, final])

    result = fetch_user_content("https://start.example/root", HTML_METADATA_POLICY)

    assert result.status is OutboundStatus.OK
    assert result.redirect_count == 2
    assert result.final_url == "https://other.example/final"
    assert [call[0].host for call in calls] == [
        "start.example",
        "start.example",
        "other.example",
    ]
    assert all(response.closed for response in [first, second, final])
    assert all(session.closed for session in sessions)

    private_redirect = FakeResponse(302, {"Location": "http://127.0.0.1/latest"})
    _user_response(monkeypatch, [private_redirect])
    monkeypatch.setattr(
        client.socket,
        "getaddrinfo",
        lambda host, *args, **kwargs: [
            _record("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34")
        ],
    )
    rejected = fetch_user_content("https://start.example/", HTML_METADATA_POLICY)
    assert rejected.status is OutboundStatus.REJECTED
    assert private_redirect.closed

    loop = FakeResponse(302, {"Location": "/"})
    _user_response(monkeypatch, [loop])
    looped = fetch_user_content("https://start.example/", HTML_METADATA_POLICY)
    assert looped.status is OutboundStatus.REJECTED
    assert loop.closed

    malformed = FakeResponse(302, {"Location": "http://[::1"})
    _user_response(monkeypatch, [malformed])
    malformed_result = fetch_user_content(
        "https://start.example/",
        HTML_METADATA_POLICY,
    )
    assert malformed_result.status is OutboundStatus.REJECTED
    assert malformed.closed


# @matrix outbound-http : address-failover closure privacy redirects
def test_user_fetch_redirect_and_address_attempt_limits(monkeypatch):
    overflow_policy = replace(HTML_METADATA_POLICY, max_redirects=1)
    first = FakeResponse(302, {"Location": "/one"})
    overflow = FakeResponse(302, {"Location": "/two"})
    _user_response(monkeypatch, [first, overflow])
    result = fetch_user_content("https://start.example/", overflow_policy)
    assert result.status is OutboundStatus.REJECTED
    assert result.redirect_count == 1
    assert first.closed and overflow.closed

    _public_dns(
        monkeypatch,
        "1.1.1.1",
        "8.8.8.8",
        "9.9.9.9",
        "93.184.216.34",
        "142.250.72.14",
    )
    attempted = []

    def fail(target, address, headers, timeout):
        attempted.append(address)
        raise requests.ConnectionError("signed-url-must-not-escape")

    monkeypatch.setattr(client, "_user_request", fail)
    result = fetch_user_content("https://many.example/?sig=private", HTML_METADATA_POLICY)
    assert result.status is OutboundStatus.HTTP_ERROR
    assert attempted == ["1.1.1.1", "8.8.8.8", "9.9.9.9", "93.184.216.34"]
    assert "private" not in repr(result)


# @matrix outbound-http : bounds closure deadline media raster streaming
def test_user_fetch_validates_media_deadline_and_raster_content(monkeypatch):
    small_policy = replace(HTML_METADATA_POLICY, max_bytes=4)
    declared = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Length": "5"},
        chunks=[b"never-read"],
    )
    _user_response(monkeypatch, [declared])
    assert fetch_user_content("https://example.test/", small_policy).status is OutboundStatus.TOO_LARGE
    assert declared.closed

    lying = FakeResponse(
        headers={
            "Content-Type": "text/html",
            "Content-Length": "1",
            "Content-Encoding": "gzip",
        },
        chunks=[b"1234", b"5"],
    )
    _user_response(monkeypatch, [lying])
    lying_result = fetch_user_content("https://example.test/", small_policy)
    assert lying_result.status is OutboundStatus.TOO_LARGE
    assert lying_result.size == 5
    assert lying.closed

    http_failure = FakeResponse(status=503)
    _user_response(monkeypatch, [http_failure])
    assert (
        fetch_user_content("https://example.test/", small_policy).status
        is OutboundStatus.HTTP_ERROR
    )
    assert http_failure.closed

    wrong_type = FakeResponse(headers={}, chunks=[b"1234"])
    _user_response(monkeypatch, [wrong_type])
    assert fetch_user_content("https://example.test/", small_policy).status is OutboundStatus.WRONG_TYPE
    assert wrong_type.closed

    timed_out = FakeResponse(headers={"Content-Type": "text/html"}, chunks=[b"ok"])
    _user_response(monkeypatch, [timed_out])
    monkeypatch.setattr(
        client,
        "_stream_body",
        lambda *args: (_ for _ in ()).throw(TimeoutError()),
    )
    assert fetch_user_content("https://example.test/", small_policy).status is OutboundStatus.TIMEOUT
    assert timed_out.closed

    monkeypatch.undo()
    valid_image = _image_bytes()
    exact_body = valid_image + b"\0" * (BOOKMARK_IMAGE_POLICY.max_bytes - len(valid_image))
    exact = FakeResponse(
        headers={"Content-Type": "image/png"},
        chunks=[exact_body],
    )
    _user_response(monkeypatch, [exact])
    exact_result = fetch_user_content(
        "https://images.example/exact",
        BOOKMARK_IMAGE_POLICY,
    )
    assert exact_result.status is OutboundStatus.OK
    assert exact_result.size == 10 * 1024 * 1024
    assert exact_result.media_type == "image/png"
    assert exact.closed

    overflow_image = FakeResponse(
        headers={"Content-Type": "image/png"},
        chunks=[exact_body, b"x"],
    )
    _user_response(monkeypatch, [overflow_image])
    assert fetch_user_content(
        "https://images.example/overflow",
        BOOKMARK_IMAGE_POLICY,
    ).status is OutboundStatus.TOO_LARGE
    assert overflow_image.closed

    invalid_image = FakeResponse(
        headers={"Content-Type": "image/jpeg"},
        chunks=[b"not-a-real-image"],
    )
    _user_response(monkeypatch, [invalid_image])
    invalid_result = fetch_user_content(
        "https://images.example/invalid",
        BOOKMARK_IMAGE_POLICY,
    )
    assert invalid_result.status is OutboundStatus.WRONG_TYPE
    assert invalid_image.closed


# @pair outbound-http:raster
@pytest.mark.parametrize(
    "image_format,expected_media_type",
    [
        ("JPEG", "image/jpeg"),
        ("PNG", "image/png"),
        ("GIF", "image/gif"),
        ("WEBP", "image/webp"),
        ("BMP", "image/bmp"),
    ],
)
def test_user_fetch_assigns_verified_raster_media_type(
    monkeypatch,
    image_format,
    expected_media_type,
):
    response = FakeResponse(
        headers={"Content-Type": "image/jpeg"},
        chunks=[_image_bytes(image_format)],
    )
    _user_response(monkeypatch, [response])

    result = fetch_user_content(
        "https://images.example/photo",
        BOOKMARK_IMAGE_POLICY,
    )

    assert result.status is OutboundStatus.OK
    assert result.media_type == expected_media_type
    assert response.closed


# @pair outbound-http:https-only
def test_profile_image_policy_is_https_only(monkeypatch):
    request = []
    monkeypatch.setattr(client, "_user_request", lambda *args: request.append(args))

    result = fetch_user_content("http://images.example/photo", PROFILE_IMAGE_POLICY)

    assert result.status is OutboundStatus.REJECTED
    assert request == []


# @matrix outbound-http : bounds closure deadline fixed-host privacy proxy-isolation redirects streaming trusted-provider
def test_trusted_client_enforces_fixed_host_bounds_deadline_and_closure(monkeypatch):
    response = FakeResponse(
        headers={"Content-Type": "application/json"},
        chunks=[b'{"ok":true}'],
    )
    session = FakeSession([response])
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    policy = TrustedProviderPolicy(
        name="provider",
        host="provider.example",
        accepted_media_types=frozenset({"application/json"}),
        max_bytes=20,
        connect_timeout=2,
        read_timeout=3,
        deadline=4,
    )

    result = request_trusted_content(
        "POST",
        "/v1/items",
        policy,
        params={"view": "small"},
        json_body={"input": "value"},
    )

    assert result.ok and result.body == b'{"ok":true}'
    assert session.calls == [
        (
            "POST",
            "https://provider.example/v1/items",
            {
                "headers": None,
                "params": {"view": "small"},
                "json": {"input": "value"},
                "allow_redirects": False,
                "timeout": pytest.approx((2, 3)),
                "stream": True,
            },
        )
    ]
    assert session.trust_env is False
    assert response.closed and session.closed

    sessions = []

    def forbidden_session():
        sessions.append(True)
        return FakeSession()

    monkeypatch.setattr(client.requests, "Session", forbidden_session)
    rejected = request_trusted_content(
        "GET", "https://attacker.example/data", policy
    )
    assert rejected.status is OutboundStatus.REJECTED
    assert sessions == []

    redirect = FakeResponse(302, {"Location": "https://attacker.example/"})
    redirect_session = FakeSession([redirect])
    monkeypatch.setattr(client.requests, "Session", lambda: redirect_session)
    redirect_result = request_trusted_content("GET", "v1/data", policy)
    assert redirect_result.status is OutboundStatus.HTTP_ERROR
    assert redirect.closed and redirect_session.closed

    oversized = FakeResponse(
        headers={"Content-Type": "application/json", "Content-Length": "21"}
    )
    oversized_session = FakeSession([oversized])
    monkeypatch.setattr(client.requests, "Session", lambda: oversized_session)
    too_large = request_trusted_content("GET", "v1/data", policy)
    assert too_large.status is OutboundStatus.TOO_LARGE
    assert oversized.closed and oversized_session.closed

    timeout_session = FakeSession([requests.ReadTimeout("private transport text")])
    monkeypatch.setattr(client.requests, "Session", lambda: timeout_session)
    timed_out = request_trusted_content("GET", "v1/data", policy)
    assert timed_out.status is OutboundStatus.TIMEOUT
    assert timeout_session.closed
    assert "private transport text" not in repr(timed_out)

    close_failure = FakeResponse(
        headers={"Content-Type": "application/json"},
        chunks=[b"{}"],
        close_error=RuntimeError("private cleanup text"),
    )
    close_failure_session = FakeSession([close_failure])
    monkeypatch.setattr(
        client.requests,
        "Session",
        lambda: close_failure_session,
    )
    cleanup_result = request_trusted_content("GET", "v1/data", policy)
    assert cleanup_result.status is OutboundStatus.OK
    assert close_failure.closed and close_failure_session.closed
    assert "private cleanup text" not in repr(cleanup_result)


# @matrix outbound-http : closure retry trusted-provider
def test_trusted_client_retries_only_explicit_method_and_status(monkeypatch):
    first = FakeResponse(503, {"Content-Type": "application/json"})
    second = FakeResponse(
        headers={"Content-Type": "application/problem+json"},
        chunks=[b"{}"],
    )
    sessions = deque([FakeSession([first]), FakeSession([second])])
    created = list(sessions)
    monkeypatch.setattr(client.requests, "Session", lambda: sessions.popleft())
    policy = TrustedProviderPolicy(
        name="retrying-provider",
        host="provider.example",
        accepted_media_types=frozenset({"application/*+json"}),
        max_bytes=20,
        connect_timeout=1,
        read_timeout=1,
        deadline=4,
        attempts=2,
        retry_methods=frozenset({"GET"}),
        retry_statuses=frozenset({503}),
        retry_backoff=(0,),
    )

    result = request_trusted_content("GET", "v1/data", policy)

    assert result.status is OutboundStatus.OK
    assert first.closed and second.closed
    assert all(session.closed for session in created)

    post_response = FakeResponse(503, {"Content-Type": "application/json"})
    post_session = FakeSession([post_response])
    monkeypatch.setattr(client.requests, "Session", lambda: post_session)
    result = request_trusted_content("POST", "v1/data", policy)
    assert result.status is OutboundStatus.HTTP_ERROR
    assert post_response.closed and post_session.closed
