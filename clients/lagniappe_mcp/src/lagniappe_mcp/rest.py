"""Bounded asynchronous REST and storage transports."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from typing import Any
import uuid
from urllib.parse import urlsplit

import httpx

from .configuration import ConnectionConfig
from ._telemetry import begin_upstream_request, classify_error
from .errors import AdapterError, TransportError
from .limits import (
    CONNECT_TIMEOUT_SECONDS,
    CONTRACT_VERSION_MAX,
    MAX_CATALOG_BYTES,
    MAX_OPENAPI_BYTES,
    MAX_STRUCTURED_RESULT_BYTES,
    MEDIA_TIMEOUT_SECONDS,
    RESPONSE_TIMEOUT_SECONDS,
)
from .url_security import validate_api_url, validate_storage_url


# httpx/httpcore include complete request URLs in diagnostic records. Storage
# URLs carry resumable-session and signed-download credentials, so transport
# logging is disabled for this standalone process before either client is used.
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
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient
def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _retryable_status(method: str, status: int) -> bool:
    if status == 429:
        return True
    return method.upper() == "GET" and status in {408, 425, 502, 503, 504}


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _finite_json_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _redact_upstream_text(value: str, *, api_key: str) -> str:
    result = _CONTROL_CHARACTER_PATTERN.sub(" ", value)
    result = result.replace(api_key, "[redacted]") if api_key else result
    result = _URL_PATTERN.sub("[redacted URL]", result)
    return _SIGNED_PARAMETER_PATTERN.sub("[redacted parameter]", result)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
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
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def _api_operation(url: str) -> str:
    """Map a validated URL to a closed metric label without retaining IDs."""
    path = urlsplit(url).path
    prefix = "/api/v1"
    if path == prefix:
        return "discovery"
    relative = path.removeprefix(f"{prefix}/")
    if relative == "me":
        return "actor"
    if relative == "tools":
        return "catalog"
    if relative == "openapi.json":
        return "openapi"
    if relative == "plans":
        return "plan_create"
    parts = relative.split("/")
    if len(parts) == 2 and parts[0] == "plans":
        return "plan_status"
    if len(parts) == 3 and parts[0] == "plans":
        return {
            "contract": "contract",
            "submit": "submit",
            "uploads": "upload_session",
        }.get(parts[2], "other")
    if (
        len(parts) == 4
        and parts[0] == "plans"
        and parts[2] == "uploads"
        and parts[3] == "finalize"
    ):
        return "upload_finalize"
    if len(parts) == 4 and parts[0] == "plans" and parts[2] == "tools":
        return "read"
    return "other"


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient
def _declared_bytes(headers: httpx.Headers) -> int:
    value = headers.get("content-length")
    if value is None or len(value) > 20 or not value.isascii() or not value.isdigit():
        return 0
    return int(value)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
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
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
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
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
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
# @tests tests_unit/test_033_mcp_adapter.py::test_telemetry_separates_startup_and_records_storage_bytes
class _TelemetryStorageClient:
    """Measure upload PUTs without adding headers to signed storage URLs."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def send(
        self,
        request: httpx.Request,
        *,
        stream: bool,
        auth: object,
        follow_redirects: bool,
    ) -> httpx.Response:
        if request.method != "PUT":
            return await self._client.send(
                request,
                stream=stream,
                auth=auth,
                follow_redirects=follow_redirects,
            )
        content_range = request.headers.get("content-range", "")
        operation = (
            "upload_status" if content_range.startswith("bytes */") else "upload_chunk"
        )
        metric = begin_upstream_request("storage", operation)
        if metric is None:
            return await self._client.send(
                request,
                stream=stream,
                auth=auth,
                follow_redirects=follow_redirects,
            )
        status: int | None = None
        response_bytes = 0
        outcome = "error"
        error_kind: str | None = "storage_transport"
        try:
            response = await self._client.send(
                request,
                stream=stream,
                auth=auth,
                follow_redirects=follow_redirects,
            )
            status = response.status_code
            response_bytes = _declared_bytes(response.headers)
            if 200 <= status < 300 or status == 308:
                outcome = "success"
                error_kind = None
            else:
                error_kind = "storage_response"
            return response
        except asyncio.CancelledError:
            outcome = "cancelled"
            error_kind = "client_cancelled"
            raise
        except httpx.TimeoutException:
            error_kind = "adapter_timeout"
            raise
        except BaseException as error:
            error_kind = classify_error(error)
            if error_kind not in {
                "adapter_timeout",
                "client_cancelled",
                "local_boundary",
                "storage_response",
                "storage_transport",
            }:
                error_kind = "storage_transport"
            raise
        finally:
            metric.complete(
                outcome,
                error_kind=error_kind,
                status=status,
                request_bytes=_declared_bytes(request.headers),
                response_bytes=response_bytes,
            )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_openapi_compatibility_check_is_exact_and_runs_only_for_check
def validate_openapi_compatibility(value: Any) -> None:
    """Validate the small frozen API surface that the adapter implements.

    The site-served manifest binds the complete OpenAPI document to a release.
    This runtime check deliberately inspects only the routes, methods, contract
    version, and closed upload declaration the installed adapter relies on.
    """
    if not isinstance(value, dict) or value.get("openapi") != "3.1.0":
        raise TransportError(
            "incompatible_openapi",
            "The Lagniappe OpenAPI document is not a supported 3.1 contract.",
        )

    paths = value.get("paths")
    expected_methods = {
        "/api/v1": "get",
        "/api/v1/client-skill.md": "get",
        "/api/v1/me": "get",
        "/api/v1/tools": "get",
        "/api/v1/plans": "post",
        "/api/v1/plans/{plan_id}": "get",
        "/api/v1/plans/{plan_id}/contract": "get",
        "/api/v1/plans/{plan_id}/submit": "post",
        "/api/v1/plans/{plan_id}/uploads": "post",
        "/api/v1/plans/{plan_id}/uploads/finalize": "post",
        "/api/v1/plans/{plan_id}/tools/{tool_name}": "post",
    }
    if (
        not isinstance(paths, dict)
        or set(paths) != set(expected_methods)
        or any(
            not isinstance(paths.get(path), dict)
            or set(paths[path]) != {method}
            for path, method in expected_methods.items()
        )
    ):
        raise TransportError(
            "incompatible_openapi",
            "The Lagniappe OpenAPI document is missing an adapter route or method.",
        )

    components = value.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        raise TransportError(
            "incompatible_openapi",
            "The Lagniappe OpenAPI document is missing component schemas.",
        )

    contract_paths = (
        ("Plan", "properties", "contract_version", "const"),
        ("PlanContract", "properties", "contract_version", "const"),
        ("PlanSubmissionFormat", "properties", "contract_version", "const"),
        (
            "PlanSubmissionFormat",
            "properties",
            "body",
            "properties",
            "contract_version",
            "const",
        ),
        ("SubmissionReceipt", "properties", "contract_version", "const"),
    )
    for location in contract_paths:
        current: Any = schemas
        for part in location:
            current = current.get(part) if isinstance(current, dict) else None
        if current != CONTRACT_VERSION_MAX:
            raise TransportError(
                "incompatible_contract",
                "The Lagniappe OpenAPI contract version is not supported by this adapter.",
            )

    upload = schemas.get("UploadFile")
    upload_properties = upload.get("properties") if isinstance(upload, dict) else None
    filename_schema = (
        upload_properties.get("filename")
        if isinstance(upload_properties, dict)
        else None
    )
    content_type_schema = (
        upload_properties.get("content_type")
        if isinstance(upload_properties, dict)
        else None
    )
    size_schema = (
        upload_properties.get("size")
        if isinstance(upload_properties, dict)
        else None
    )
    if (
        not isinstance(upload, dict)
        or upload.get("additionalProperties") is not False
        or upload.get("required") != ["filename", "size"]
        or not isinstance(filename_schema, dict)
        or filename_schema.get("type") != "string"
        or not isinstance(content_type_schema, dict)
        or content_type_schema.get("type") != "string"
        or not isinstance(size_schema, dict)
        or size_schema.get("type") != "integer"
    ):
        raise TransportError(
            "incompatible_openapi",
            "The Lagniappe upload declaration is not the closed contract this adapter supports.",
        )

    plan = schemas.get("Plan")
    plan_properties = plan.get("properties") if isinstance(plan, dict) else None
    plan_batch = (
        plan_properties.get("upload_batch_id")
        if isinstance(plan_properties, dict)
        else None
    )
    plan_batch_options = (
        plan_batch.get("oneOf") if isinstance(plan_batch, dict) else None
    )
    plan_required = plan.get("required") if isinstance(plan, dict) else None
    create_operation = paths["/api/v1/plans/{plan_id}/uploads"]["post"]
    create_responses = (
        create_operation.get("responses", {})
        if isinstance(create_operation, dict)
        else {}
    )
    create_response = (
        create_responses.get("201") if isinstance(create_responses, dict) else None
    )
    create_content = (
        create_response.get("content") if isinstance(create_response, dict) else None
    )
    create_json = (
        create_content.get("application/json")
        if isinstance(create_content, dict)
        else None
    )
    create_schema = (
        create_json.get("schema") if isinstance(create_json, dict) else None
    )
    create_properties = (
        create_schema.get("properties") if isinstance(create_schema, dict) else None
    )
    create_batch = (
        create_properties.get("upload_batch_id")
        if isinstance(create_properties, dict)
        else None
    )
    finalize_operation = paths["/api/v1/plans/{plan_id}/uploads/finalize"]["post"]
    finalize_body = (
        finalize_operation.get("requestBody")
        if isinstance(finalize_operation, dict)
        else None
    )
    finalize_content = (
        finalize_body.get("content") if isinstance(finalize_body, dict) else None
    )
    finalize_json = (
        finalize_content.get("application/json")
        if isinstance(finalize_content, dict)
        else None
    )
    finalize_schema = (
        finalize_json.get("schema") if isinstance(finalize_json, dict) else None
    )
    finalize_properties = (
        finalize_schema.get("properties")
        if isinstance(finalize_schema, dict)
        else None
    )
    finalize_batch = (
        finalize_properties.get("upload_batch_id")
        if isinstance(finalize_properties, dict)
        else None
    )
    if (
        not isinstance(plan_required, list)
        or "upload_batch_id" not in plan_required
        or not isinstance(plan_batch_options, list)
        or len(plan_batch_options) != 2
        or not all(isinstance(option, dict) for option in plan_batch_options)
        or not any(option.get("type") == "string" for option in plan_batch_options)
        or not any(option.get("type") == "null" for option in plan_batch_options)
        or not isinstance(create_schema, dict)
        or create_schema.get("additionalProperties") is not False
        or create_schema.get("required")
        != ["plan_id", "upload_batch_id", "uploads"]
        or not isinstance(create_batch, dict)
        or create_batch.get("type") != "string"
        or not isinstance(finalize_body, dict)
        or finalize_body.get("required") is not True
        or not isinstance(finalize_schema, dict)
        or finalize_schema.get("additionalProperties") is not False
        or finalize_schema.get("required") != ["upload_batch_id"]
        or not isinstance(finalize_properties, dict)
        or set(finalize_properties) != {"upload_batch_id"}
        or not isinstance(finalize_batch, dict)
        or finalize_batch.get("type") != "string"
    ):
        raise TransportError(
            "incompatible_openapi",
            "The Lagniappe upload batch identity contract is not supported by this adapter.",
        )


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
        raw_storage_client = storage_client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                MEDIA_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
            ),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "*/*"},
        )
        self._raw_storage_client = raw_storage_client
        self.storage_client = _TelemetryStorageClient(raw_storage_client)

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient
    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()
        if self._owns_storage_client:
            await self._raw_storage_client.aclose()

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient
    async def __aenter__(self) -> RESTClient:
        return self

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient
    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
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
        metric = begin_upstream_request("api", _api_operation(url))
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "X-Request-ID": (
                metric.api_request_id if metric is not None else f"mcp-{uuid.uuid4().hex}"
            ),
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = httpx.Request(method, url, headers=headers, content=content)
        response: httpx.Response | None = None
        response_bytes = 0
        status: int | None = None
        retry_after_seconds: int | None = None
        response_build_id: str | None = None
        outcome = "error"
        error_kind: str | None = "api_transport"
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
            status = response.status_code
            raw_retry_after = response.headers.get("retry-after")
            if (
                status == 429
                and raw_retry_after is not None
                and len(raw_retry_after) <= 5
                and raw_retry_after.isascii()
                and raw_retry_after.isdigit()
            ):
                retry_after_seconds = int(raw_retry_after)
            response_build_id = response.headers.get("x-lagniappe-build-id")
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
                response_bytes = len(chunks)
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
                    status=response.status_code,
                    request_id=request_id,
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
                    status=response.status_code,
                    request_id=request_id,
                ) from error
            if response.status_code >= 400:
                problem = value.get("error") if isinstance(value, dict) else None
                if not isinstance(problem, dict):
                    raise TransportError(
                        "api_error",
                        "The Lagniappe API request failed.",
                        retryable=_retryable_status(method, response.status_code),
                        status=response.status_code,
                        request_id=request_id,
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
                    status=response.status_code,
                    request_id=safe_request_id,
                    details=_redact_upstream_value(
                        problem.get("details"), api_key=self.config.api_key
                    ),
                )
            if not 200 <= response.status_code < 300:
                raise TransportError(
                    "invalid_response",
                    "API returned an unexpected status.",
                    status=response.status_code,
                )
            outcome = "success"
            error_kind = None
            return value, request_id
        except asyncio.CancelledError:
            outcome = "cancelled"
            error_kind = "client_cancelled"
            raise
        except AdapterError as error:
            error_kind = classify_error(error)
            raise
        except (TimeoutError, httpx.TimeoutException) as error:
            error_kind = "adapter_timeout"
            raise TransportError(
                "api_timeout",
                "The Lagniappe API request timed out.",
                retryable=method.upper() == "GET",
            ) from error
        except httpx.RequestError as error:
            error_kind = "api_transport"
            raise TransportError(
                "api_unavailable",
                "The Lagniappe API could not be reached.",
                retryable=method.upper() == "GET",
            ) from error
        finally:
            if metric is not None:
                metric.complete(
                    outcome,
                    error_kind=error_kind,
                    status=status,
                    request_bytes=len(content or b""),
                    response_bytes=response_bytes,
                    retry_after_seconds=retry_after_seconds,
                    response_build_id=response_build_id,
                )
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
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::validate_openapi_compatibility
    async def check_openapi_compatibility(self) -> None:
        """Fetch and validate compatibility without lengthening MCP startup."""
        value, _request_id = await self.request_json(
            "GET", "openapi.json", max_bytes=MAX_OPENAPI_BYTES
        )
        validate_openapi_compatibility(value)

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.startup
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
        metric = begin_upstream_request("storage", "download")
        request = httpx.Request("GET", safe_url)
        response: httpx.Response | None = None
        response_bytes = 0
        status: int | None = None
        outcome = "error"
        error_kind: str | None = "storage_transport"
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
            status = response.status_code
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
                response_bytes = len(data)
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
            outcome = "success"
            error_kind = None
            return bytes(data), mime
        except asyncio.CancelledError:
            outcome = "cancelled"
            error_kind = "client_cancelled"
            raise
        except AdapterError as error:
            error_kind = classify_error(error)
            raise
        except (TimeoutError, httpx.TimeoutException) as error:
            error_kind = "adapter_timeout"
            raise TransportError(
                "download_timeout", "Original media download timed out.", retryable=True
            ) from error
        except httpx.RequestError as error:
            error_kind = "storage_transport"
            raise TransportError(
                "download_failed",
                "Original media could not be downloaded.",
                retryable=True,
            ) from error
        finally:
            if metric is not None:
                metric.complete(
                    outcome,
                    error_kind=error_kind,
                    status=status,
                    response_bytes=response_bytes,
                )
            if response is not None:
                await response.aclose()
