"""Strong, test-only Playwright response waits for browser workflows."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit


# @testable true
# @tests tests_tooling/test_004_network_waits.py::test_lagniappe_error_response_contract
# @matrix e2e : error-contract manual-http side-effect-free
def assert_lagniappe_error_response(response: Any, *, status: int) -> None:
    """Assert the common response envelope for a direct Lagniappe HTTP error."""

    response_status = getattr(response, "status_code", None)
    if response_status is None:
        response_status = response.status
    assert response_status == status
    content_type = response.headers.get("content-type", "")
    assert content_type.lower().startswith("text/html"), (
        f"Expected an HTML error response; received {content_type!r}"
    )
    assert response.headers.get("x-lagniappe-error") == f"Error {status}"
    response_text = response.text
    if callable(response_text):
        response_text = response_text()
    assert f"Error {status}" in response_text
    assert "x-lagniappe-entity-revisions" not in response.headers


# @testable true
# @tests tests_tooling/test_004_network_waits.py::test_manual_mutation_headers_use_the_browser_origin
# @matrix e2e : csrf manual-http same-origin
def manual_mutation_headers(page_url: str, csrf_token: str) -> dict[str, str]:
    """Return browser-equivalent same-origin headers for a direct mutation."""

    parsed = urlsplit(page_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Manual mutation headers require an HTTP(S) page URL.")
    if not csrf_token:
        raise ValueError("Manual mutation headers require a CSRF token.")
    return {
        "Origin": f"{parsed.scheme}://{parsed.netloc}",
        "Referer": urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, "")
        ),
        "X-CSRFToken": csrf_token,
        "X-Lagniappe-Request": "true",
    }


# @testable true
# @tests tests_tooling/test_004_network_waits.py::test_semantically_equal_etags_allow_proxy_weakening
# @matrix e2e : etag manual-http proxy-normalization
def assert_same_etag(actual: str | None, expected: str | None) -> None:
    """Assert equal opaque ETag values while allowing proxy-valid weakening."""

    def normalize(value: str | None) -> str:
        assert isinstance(value, str) and value, "Expected a nonempty ETag header"
        normalized = value.removeprefix("W/")
        assert normalized.startswith('"') and normalized.endswith('"'), (
            f"Expected a quoted ETag; received {value!r}"
        )
        return normalized

    assert normalize(actual) == normalize(expected)


# @testable true
# @tests tests_tooling/test_004_network_waits.py::test_scoped_browser_route_always_removes_handler
# @matrix e2e : cleanup request-routing
@contextmanager
def scoped_browser_route(
    target: Any,
    pattern: Any,
    handler: Callable[[Any], None],
) -> Iterator[None]:
    """Install one Playwright route for a bounded scope and always remove it."""

    target.route(pattern, handler)
    try:
        yield
    finally:
        target.unroute(pattern, handler)


# @testable true
# @tests tests_tooling/test_004_network_waits.py::test_multipart_form_fields_preserves_values_and_filenames
# @matrix e2e : multipart request-routing
def multipart_form_fields(request: Any) -> list[tuple[str, str]]:
    """Return ordered text values and filenames from a Playwright multipart request."""

    content_type = request.header_value("content-type")
    assert content_type and content_type.lower().startswith("multipart/form-data;"), (
        "Expected a multipart/form-data browser request; received "
        f"{content_type!r}"
    )
    body = request.post_data_buffer
    assert body is not None, "Expected the multipart browser request to have a body"

    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: "
        + content_type.encode("latin-1")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    assert message.is_multipart(), "Browser request body was not valid multipart data"

    fields = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        if filename is not None:
            fields.append((name, filename))
            continue
        payload = part.get_payload(decode=True) or b""
        fields.append((name, payload.decode(part.get_content_charset() or "utf-8")))
    return fields


# @testable true
# @tests tests_tooling/test_004_network_waits.py
# @pair e2e:network-wait
@contextmanager
def expect_successful_response(
    page: Any,
    *,
    method: str,
    path: str,
    query: Mapping[str, str] | None = None,
    entity_key: str | None = None,
    request_payload_contains: str | Sequence[str] | None = None,
    response_check: Callable[[Any], None] | None = None,
    expected_status: int | None = None,
    timeout: float | None = None,
) -> Iterator[Any]:
    """Wait for one intended successful response and retain it for assertions.

    The response is selected by its request method, parsed URL path, optional
    query fields, and optional raw request-body markers.  Status and response
    validation happen after it is captured so a matching 4xx/5xx response
    reports its actual transport failure instead of timing out.
    """

    method = method.upper()
    payload_markers = _payload_markers(request_payload_contains)

    def matches(response: Any) -> bool:
        request = response.request
        parsed = urlsplit(response.url)
        if request.method.upper() != method or parsed.path != path:
            return False
        if query and any(
            parse_qs(parsed.query, keep_blank_values=True).get(name) != [value]
            for name, value in query.items()
        ):
            return False
        request_body = request.post_data or ""
        return all(marker in request_body for marker in payload_markers)

    options = {} if timeout is None else {"timeout": timeout}
    with page.expect_response(matches, **options) as response_info:
        yield response_info

    response = response_info.value
    if expected_status is None:
        assert response.ok, _failure_message(response, method, path, "a 2xx response")
    else:
        assert response.status == expected_status, _failure_message(
            response,
            method,
            path,
            f"HTTP {expected_status}",
        )

    if entity_key is not None:
        _assert_entity_revision(response, entity_key, method, path)
    if response_check is not None:
        response_check(response)


def _payload_markers(
    request_payload_contains: str | Sequence[str] | None,
) -> tuple[str, ...]:
    if request_payload_contains is None:
        return ()
    if isinstance(request_payload_contains, str):
        return (request_payload_contains,)
    return tuple(request_payload_contains)


def _assert_entity_revision(response: Any, entity_key: str, method: str, path: str) -> None:
    raw_revisions = response.headers.get("x-lagniappe-entity-revisions")
    assert raw_revisions, (
        f"{method} {path} did not return X-Lagniappe-Entity-Revisions for "
        f"entity {entity_key!r}"
    )
    try:
        revisions = json.loads(raw_revisions)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"{method} {path} returned invalid entity revisions: {raw_revisions!r}"
        ) from error

    revision_keys = {revision.get("key") for revision in revisions if isinstance(revision, dict)}
    assert entity_key in revision_keys, (
        f"{method} {path} did not acknowledge entity {entity_key!r}; "
        f"received revisions for {sorted(key for key in revision_keys if key)}"
    )


def _failure_message(response: Any, method: str, path: str, expected: str) -> str:
    try:
        body = response.text()
    except Exception as error:  # pragma: no cover - diagnostic fallback
        body = f"<unavailable response body: {error}>"
    return (
        f"Expected {method} {path} to return {expected}; received HTTP "
        f"{response.status} from {response.url}. Response body: {body[:1000]!r}"
    )
