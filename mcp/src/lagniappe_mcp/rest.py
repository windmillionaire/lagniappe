"""Bounded asynchronous REST and storage transports."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from typing import Any
import uuid

import httpx

from .configuration import ConnectionConfig
from .errors import AdapterError, TransportError
from .limits import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_CATALOG_BYTES,
    MAX_STRUCTURED_RESULT_BYTES,
    MEDIA_TIMEOUT_SECONDS,
    RESPONSE_TIMEOUT_SECONDS,
)
from .url_security import validate_api_url, validate_storage_url


# httpx/httpcore include complete request URLs in diagnostic records. Storage
# URLs carry resumable-session and signed-download credentials, so transport
# logging is disabled for the adapter before either client is used.
for _logger_name in ("httpx", "httpcore"):
    logging.getLogger(_logger_name).disabled = True

_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
_URL_PATTERN = re.compile(r"(?i)https?://[^\s\"'<>]+")
_SIGNED_PARAMETER_PATTERN = re.compile(
    r"(?i)\b(?:X-Goog-Signature|upload_id)=[^&\s\"'<>]+"
)
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_DETAIL_KEYS = frozenset(
    {
        "allowed_fields",
        "available",
        "code",
        "errors",
        "expected",
        "field",
        "fields",
        "file_index",
        "maximum",
        "maximum_length",
        "maximum_reported",
        "message",
        "minimum",
        "minimum_length",
        "path",
        "use_field",
        "validator",
    }
)


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient
def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _retryable_status(method: str, status: int) -> bool:
    if status == 429:
        return True
    return method.upper() == "GET" and status in {408, 425, 502, 503, 504}


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _finite_json_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _redact_upstream_text(value: str, *, api_key: str) -> str:
    result = _CONTROL_CHARACTER_PATTERN.sub(" ", value)
    result = result.replace(api_key, "[redacted]") if api_key else result
    result = _URL_PATTERN.sub("[redacted URL]", result)
    return _SIGNED_PARAMETER_PATTERN.sub("[redacted parameter]", result)


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _redact_upstream_value(value: Any, *, api_key: str, depth: int = 0) -> Any:
    if depth > 8:
        return None
    if isinstance(value, str):
        return _redact_upstream_text(value, api_key=api_key)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        return [
            _redact_upstream_value(item, api_key=api_key, depth=depth + 1)
            for item in value[:20]
        ]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:20]:
            if not isinstance(key, str):
                continue
            safe_key = key.casefold()
            if (
                safe_key not in _SAFE_DETAIL_KEYS
                or _CONTROL_CHARACTER_PATTERN.search(key)
            ):
                continue
            result[safe_key] = _redact_upstream_value(
                item, api_key=api_key, depth=depth + 1
            )
        return result
    return None


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
def _reject_content_encoding(response: httpx.Response, *, storage: bool) -> None:
    encoding = response.headers.get("content-encoding", "").strip().casefold()
    if encoding not in {"", "identity"}:
        raise TransportError(
            "invalid_download" if storage else "invalid_response",
            (
                "Original media response used an unsupported content encoding."
                if storage
                else "API response used an unsupported content encoding."
            ),
            status=response.status_code,
        )


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
async def _raw_chunks(response: httpx.Response):
    """Yield transport bytes, including already-buffered synthetic responses."""
    if response.is_stream_consumed:
        # Mock transports commonly construct an already-buffered Response.
        # Network responses sent with ``stream=True`` take the raw branch.
        yield response.content
        return
    async for chunk in response.aiter_raw():
        yield chunk


# @testable false
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
# @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
async def _raw_chunks_before(response: httpx.Response, *, deadline: float):
    """Yield response bytes within one wall-clock deadline."""
    iterator = _raw_chunks(response).__aiter__()
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        try:
            yield await asyncio.wait_for(anext(iterator), timeout=remaining)
        except StopAsyncIteration:
            return


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_api_request_uses_only_explicit_bearer_credentials
# @tests tests_unit/test_033_mcp_adapter.py::test_api_errors_redact_credentials_and_duplicate_json_is_rejected
# @tests tests_unit/test_033_mcp_adapter.py::test_failed_concurrent_startup_cancels_sibling_requests
# @tests tests_unit/test_033_mcp_adapter.py::test_media_download_does_not_inherit_client_credentials_or_cookies
class RESTClient:
    """A no-redirect client whose sole authenticated authority is configured."""

    def __init__(
        self,
        config: ConnectionConfig,
        *,
        client: httpx.AsyncClient | None = None,
        storage_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        timeout = httpx.Timeout(
            RESPONSE_TIMEOUT_SECONDS,
            connect=CONNECT_TIMEOUT_SECONDS,
        )
        self._owns_client = client is None
        self._owns_storage_client = storage_client is None
        self.client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json"},
        )
        self.storage_client = storage_client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                MEDIA_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
            ),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "*/*"},
        )

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient
    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()
        if self._owns_storage_client:
            await self.storage_client.aclose()

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient
    async def __aenter__(self) -> RESTClient:
        return self

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient
    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
    def _resolve_api_url(self, target: str) -> str:
        if target.startswith("http://") or target.startswith("https://"):
            return validate_api_url(self.config.authority, target)
        return self.config.authority.api_url(target)

    # @testable true
    # @pair mcp-adapter:product-contract
    # @tests tests_unit/test_033_mcp_adapter.py::test_api_request_uses_only_explicit_bearer_credentials
    # @tests tests_unit/test_033_mcp_adapter.py::test_api_errors_redact_credentials_and_duplicate_json_is_rejected
    async def request_json(
        self,
        method: str,
        target: str,
        *,
        body: Any = None,
        max_bytes: int = MAX_STRUCTURED_RESULT_BYTES,
    ) -> tuple[Any, str | None]:
        """Make one authenticated API request without retries or redirects."""
        url = self._resolve_api_url(target)
        content: bytes | None = None
        if body is not None:
            try:
                content = json.dumps(
                    body,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (RecursionError, TypeError, ValueError) as error:
                raise TransportError(
                    "invalid_request", "API request data is not valid JSON."
                ) from error
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "X-Request-ID": f"mcp-{uuid.uuid4().hex}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = httpx.Request(method, url, headers=headers, content=content)
        response: httpx.Response | None = None
        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT_SECONDS
        try:
            # Construct the request directly and explicitly disable client auth.
            # This prevents an injected/test client's cookies or authentication
            # defaults from widening the sole bearer-authenticated authority.
            response = await asyncio.wait_for(
                self.client.send(
                    request,
                    stream=True,
                    auth=None,
                    follow_redirects=False,
                ),
                timeout=RESPONSE_TIMEOUT_SECONDS,
            )
            if 300 <= response.status_code < 400:
                raise TransportError(
                    "redirect_rejected",
                    "Authenticated API redirects are not allowed.",
                    status=response.status_code,
                )
            _reject_content_encoding(response, storage=False)
            declared = response.headers.get("content-length")
            if declared:
                try:
                    declared_size = int(declared)
                    if declared_size < 0:
                        raise ValueError
                    if declared_size > max_bytes:
                        raise TransportError(
                            "response_too_large",
                            "API response exceeds the adapter limit.",
                        )
                except ValueError as error:
                    raise TransportError(
                        "invalid_response",
                        "API response has an invalid content length.",
                    ) from error
            chunks = bytearray()
            async for chunk in _raw_chunks_before(response, deadline=deadline):
                if len(chunk) > max_bytes - len(chunks):
                    raise TransportError(
                        "response_too_large",
                        "API response exceeds the adapter limit.",
                    )
                chunks.extend(chunk)
            raw_request_id = response.headers.get("x-request-id")
            request_id = (
                raw_request_id
                if isinstance(raw_request_id, str)
                and raw_request_id == headers["X-Request-ID"]
                and _REQUEST_ID_PATTERN.fullmatch(raw_request_id)
                else None
            )
            if _content_type(response) != "application/json":
                raise TransportError(
                    "invalid_response",
                    "API response was not JSON.",
                    request_id=request_id,
                    status=response.status_code,
                )
            try:
                value = json.loads(
                    chunks,
                    object_pairs_hook=_unique_json_object,
                    parse_constant=_reject_json_constant,
                    parse_float=_finite_json_float,
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                RecursionError,
                ValueError,
            ) as error:
                raise TransportError(
                    "invalid_response",
                    "API response contained invalid JSON.",
                    request_id=request_id,
                    status=response.status_code,
                ) from error
            if response.status_code >= 400:
                problem = value.get("error") if isinstance(value, dict) else None
                if not isinstance(problem, dict):
                    raise TransportError(
                        "api_error",
                        "The Lagniappe API request failed.",
                        retryable=_retryable_status(method, response.status_code),
                        request_id=request_id,
                        status=response.status_code,
                    )
                raw_code = problem.get("code")
                code = (
                    raw_code
                    if isinstance(raw_code, str)
                    and _ERROR_CODE_PATTERN.fullmatch(raw_code)
                    and raw_code != self.config.api_key
                    else "api_error"
                )
                raw_message = problem.get("message")
                message = (
                    _redact_upstream_text(raw_message, api_key=self.config.api_key)
                    if isinstance(raw_message, str) and raw_message
                    else "The Lagniappe API request failed."
                )
                body_request_id = value.get("request_id")
                safe_request_id = (
                    body_request_id
                    if isinstance(body_request_id, str)
                    and body_request_id == headers["X-Request-ID"]
                    and _REQUEST_ID_PATTERN.fullmatch(body_request_id)
                    else request_id
                    if isinstance(request_id, str)
                    and _REQUEST_ID_PATTERN.fullmatch(request_id)
                    else None
                )
                raise AdapterError(
                    code,
                    message,
                    retryable=_retryable_status(method, response.status_code),
                    request_id=safe_request_id,
                    details=_redact_upstream_value(
                        problem.get("details"), api_key=self.config.api_key
                    ),
                    status=response.status_code,
                )
            if not 200 <= response.status_code < 300:
                raise TransportError(
                    "invalid_response",
                    "API returned an unexpected status.",
                    status=response.status_code,
                )
            return value, request_id
        except (TimeoutError, httpx.TimeoutException) as error:
            raise TransportError(
                "api_timeout",
                "The Lagniappe API request timed out.",
                retryable=method.upper() == "GET",
            ) from error
        except httpx.RequestError as error:
            raise TransportError(
                "api_unavailable",
                "The Lagniappe API could not be reached.",
                retryable=method.upper() == "GET",
            ) from error
        finally:
            if response is not None:
                await response.aclose()

    # @testable true
    # @pair mcp-adapter:product-contract
    # @tests tests_unit/test_033_mcp_adapter.py::test_failed_concurrent_startup_cancels_sibling_requests
    # @tests tests_unit/test_033_mcp_adapter.py::test_adapter_executes_only_typed_lifecycle_and_catalog_routes
    async def startup(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Fetch only authenticated discovery, actor, and catalog concurrently."""
        tasks = (
            asyncio.create_task(self.request_json("GET", "", max_bytes=64 * 1024)),
            asyncio.create_task(self.request_json("GET", "me", max_bytes=128 * 1024)),
            asyncio.create_task(
                self.request_json("GET", "tools", max_bytes=MAX_CATALOG_BYTES)
            ),
        )
        try:
            discovery_result, actor_result, catalog_result = await asyncio.gather(
                *tasks
            )
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        discovery, _ = discovery_result
        actor, _ = actor_result
        catalog, _ = catalog_result
        if not all(isinstance(value, dict) for value in (discovery, actor, catalog)):
            raise TransportError(
                "invalid_response", "API startup resources must be JSON objects."
            )
        self._validate_discovery(discovery)
        return discovery, actor, catalog

    # @testable false
    # @covered-by mcp/src/lagniappe_mcp/rest.py::RESTClient.startup
    def _validate_discovery(self, discovery: dict[str, Any]) -> None:
        if discovery.get("version") != "v1":
            raise TransportError(
                "incompatible_api", "This adapter supports only Lagniappe API v1."
            )
        expected = {
            "base_url": "/api/v1",
            "openapi_url": "/api/v1/openapi.json",
            "actor_url": "/api/v1/me",
            "tools_url": "/api/v1/tools",
            "plans_url": "/api/v1/plans",
            "client_skill_url": "/api/v1/client-skill.md",
        }
        for field, path in expected.items():
            value = discovery.get(field)
            if not isinstance(value, str):
                raise TransportError(
                    "invalid_response", f"API discovery is missing {field}."
                )
            validate_api_url(self.config.authority, value, expected_path=path)

    # @testable true
    # @pair mcp-adapter:product-contract
    # @tests tests_unit/test_033_mcp_adapter.py::test_media_download_does_not_inherit_client_credentials_or_cookies
    async def download_media(self, url: str, *, cap: int) -> tuple[bytes, str]:
        """Consume a signed original without forwarding API authentication."""
        safe_url = validate_storage_url(url, upload=False)
        request = httpx.Request("GET", safe_url)
        response: httpx.Response | None = None
        deadline = asyncio.get_running_loop().time() + MEDIA_TIMEOUT_SECONDS
        try:
            response = await asyncio.wait_for(
                self.storage_client.send(
                    request,
                    stream=True,
                    auth=None,
                    follow_redirects=False,
                ),
                timeout=MEDIA_TIMEOUT_SECONDS,
            )
            if 300 <= response.status_code < 400:
                raise TransportError(
                    "redirect_rejected", "Storage redirects are not allowed."
                )
            _reject_content_encoding(response, storage=True)
            if not 200 <= response.status_code < 300:
                raise TransportError(
                    "download_failed",
                    "Original media download failed.",
                    status=response.status_code,
                )
            declared = response.headers.get("content-length")
            if declared is None:
                raise TransportError(
                    "invalid_download",
                    "Original media response omitted content length.",
                )
            try:
                expected = int(declared)
            except ValueError as error:
                raise TransportError(
                    "invalid_download", "Original media content length is invalid."
                ) from error
            if expected <= 0:
                raise TransportError(
                    "invalid_download", "Original media content length is invalid."
                )
            if expected > cap:
                raise TransportError(
                    "media_too_large", "Original media exceeds the MCP limit."
                )
            data = bytearray()
            async for chunk in _raw_chunks_before(response, deadline=deadline):
                if len(chunk) > cap - len(data):
                    raise TransportError(
                        "media_too_large", "Original media exceeds the MCP limit."
                    )
                data.extend(chunk)
            if len(data) != expected:
                raise TransportError(
                    "invalid_download",
                    "Original media byte count did not match its declaration.",
                )
            mime = _content_type(response)
            if not mime:
                raise TransportError(
                    "invalid_download", "Original media response omitted its MIME type."
                )
            return bytes(data), mime
        except (TimeoutError, httpx.TimeoutException) as error:
            raise TransportError(
                "download_timeout", "Original media download timed out.", retryable=True
            ) from error
        except httpx.RequestError as error:
            raise TransportError(
                "download_failed",
                "Original media could not be downloaded.",
                retryable=True,
            ) from error
        finally:
            if response is not None:
                await response.aclose()
