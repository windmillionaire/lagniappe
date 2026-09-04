"""Private, secret-free JSONL evaluation telemetry for the stdio adapter.

The records in this module are deliberately a small closed vocabulary.  They
never accept model arguments, MCP request identities, URLs, Plan identities,
paths, response bodies, or exception text.  A locally generated correlation
identity joins one MCP call (or startup) to its API and storage request events.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import re
import sys
import threading
import time
from typing import Iterator, Literal
import uuid

from .errors import AdapterError, FileBoundaryError, SchemaError, TransportError
from .limits import (
    MAX_STARTUP_DIAGNOSTIC_BYTES,
    MAX_STDERR_BYTES,
    MAX_TOOL_COUNT,
    MAX_UPLOAD_CHUNK_BYTES,
    MAX_UPLOAD_RECOVERY_ATTEMPTS,
    MAX_UPLOAD_STATUS_PROBES,
    UPLOAD_TIMEOUT_SECONDS,
)


ScopeKind = Literal["startup", "call"]
TransportKind = Literal["api", "storage"]

_CALL_OPERATIONS = frozenset(
    {
        "actor",
        "get_plan",
        "get_plan_contract",
        "protocol",
        "read",
        "start_ask",
        "start_create",
        "start_organize",
        "submit",
        "upload",
    }
)
_STARTUP_OPERATIONS = frozenset({"bootstrap", "check"})
_API_OPERATIONS = frozenset(
    {
        "actor",
        "catalog",
        "contract",
        "discovery",
        "openapi",
        "plan_create",
        "plan_status",
        "read",
        "submit",
        "upload_finalize",
        "upload_session",
        "other",
    }
)
_STORAGE_OPERATIONS = frozenset({"download", "upload_chunk", "upload_status"})
_OUTCOMES = frozenset({"success", "error", "cancelled"})
_ERROR_KINDS = frozenset(
    {
        "adapter_failure",
        "adapter_timeout",
        "api_domain",
        "api_transport",
        "client_cancelled",
        "local_boundary",
        "local_validation",
        "protocol_error",
        "storage_response",
        "storage_transport",
        "upstream_response",
    }
)
_BUILD_ID_PATTERN = re.compile(r"^[a-f0-9]{8}$")
_STORAGE_ERROR_CODES = frozenset(
    {
        "download_failed",
        "download_timeout",
        "invalid_download",
        "invalid_upload_offset",
        "invalid_upload_response",
        "invalid_upload_session",
        "media_too_large",
        "mime_mismatch",
        "redirect_rejected",
        "unsupported_media",
        "upload_failed",
        "upload_no_progress",
        "upload_not_complete",
        "upload_probe_failed",
        "upload_recovery_exhausted",
    }
)
_UPSTREAM_RESPONSE_CODES = frozenset(
    {
        "incompatible_api",
        "incompatible_contract",
        "invalid_catalog",
        "invalid_response",
        "response_too_large",
        "result_too_large",
        "unsafe_transport_extension",
    }
)

# Saturation makes every numeric field fixed-width even if a hostile future
# contract attempts to inflate a call.  Current product limits are far below
# these derived ceilings.
_MAX_REQUEST_COUNT = MAX_TOOL_COUNT * (
    MAX_UPLOAD_RECOVERY_ATTEMPTS + MAX_UPLOAD_STATUS_PROBES + 2
)
_MAX_METRIC_BYTES = MAX_UPLOAD_CHUNK_BYTES * MAX_TOOL_COUNT
_MAX_ELAPSED_MS = int(UPLOAD_TIMEOUT_SECONDS * 1000 * _MAX_REQUEST_COUNT)
_MAX_UNIX_MS = 9_999_999_999_999

_CURRENT_SCOPE: ContextVar[TelemetryScope | None] = ContextVar(
    "lagniappe_mcp_telemetry_scope", default=None
)
_STDERR_LOCK = threading.Lock()
_STDERR_STREAM: object | None = None
_STARTUP_STDERR_BYTES_WRITTEN = 0


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/_telemetry.py::TelemetryScope
def _bounded_integer(value: object, *, maximum: int) -> tuple[int, bool]:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0, False
    if value < 0:
        return 0, True
    if value > maximum:
        return maximum, True
    return value, False


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/_telemetry.py::TelemetryScope
def _elapsed_ms(start_ns: int) -> tuple[int, bool]:
    elapsed = max(0, (time.monotonic_ns() - start_ns) // 1_000_000)
    return _bounded_integer(elapsed, maximum=_MAX_ELAPSED_MS)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/_telemetry.py::TelemetryScope
def _unix_ms() -> int:
    value, _saturated = _bounded_integer(
        time.time_ns() // 1_000_000, maximum=_MAX_UNIX_MS
    )
    return value


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/_telemetry.py::TelemetryScope
def _write_event(value: dict[str, object]) -> None:
    """Write one bounded event and cap aggregate startup diagnostics."""
    global _STARTUP_STDERR_BYTES_WRITTEN, _STDERR_STREAM
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        if len(encoded) + 1 > MAX_STDERR_BYTES:
            encoded = b'{"event":"lagniappe_mcp_telemetry","outcome":"dropped"}'
        line = encoded.decode("ascii") + "\n"
        with _STDERR_LOCK:
            stream = sys.stderr
            if stream is not _STDERR_STREAM:
                _STDERR_STREAM = stream
                _STARTUP_STDERR_BYTES_WRITTEN = 0
            line_bytes = len(encoded) + 1
            if value.get("scope") == "startup":
                if (
                    _STARTUP_STDERR_BYTES_WRITTEN + line_bytes
                    > MAX_STARTUP_DIAGNOSTIC_BYTES
                ):
                    return
                _STARTUP_STDERR_BYTES_WRITTEN += line_bytes
            stream.write(line)
            stream.flush()
    except BaseException:
        # Diagnostics must never corrupt stdout, replace a tool result, or keep
        # the stdio process alive after its client disconnects.
        return


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/_telemetry.py::TelemetryScope
def _safe_operation(scope: ScopeKind, operation: str) -> str:
    allowed = _STARTUP_OPERATIONS if scope == "startup" else _CALL_OPERATIONS
    return operation if operation in allowed else "protocol"


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_telemetry_correlates_concurrent_calls_without_sensitive_values
# @tests tests_unit/test_033_mcp_adapter.py::test_telemetry_records_safe_api_error_status_and_retry
@dataclass(slots=True)
class UpstreamRequestTelemetry:
    """One API or storage request associated with the active safe scope."""

    owner: TelemetryScope
    transport: TransportKind
    operation: str
    request_index: int
    started_ns: int = field(default_factory=time.monotonic_ns)
    started_unix_ms: int = field(default_factory=_unix_ms)
    finished: bool = False

    @property
    def api_request_id(self) -> str:
        """A safe outbound API ID that also joins server-side request logs."""
        return f"mcp-{self.owner.correlation_id[:20]}-{self.request_index}"

    def complete(
        self,
        outcome: str,
        *,
        error_kind: str | None = None,
        status: int | None = None,
        request_bytes: int = 0,
        response_bytes: int = 0,
        retry_after_seconds: int | None = None,
        response_build_id: str | None = None,
    ) -> None:
        if self.finished:
            return
        self.finished = True
        self.owner._record_request(
            self,
            outcome=outcome,
            error_kind=error_kind,
            status=status,
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            retry_after_seconds=retry_after_seconds,
            response_build_id=response_build_id,
        )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_telemetry_correlates_concurrent_calls_without_sensitive_values
# @tests tests_unit/test_033_mcp_adapter.py::test_telemetry_separates_startup_and_records_storage_bytes
# @tests tests_unit/test_033_mcp_adapter.py::test_telemetry_records_safe_api_error_status_and_retry
@dataclass(slots=True)
class TelemetryScope:
    """Bounded aggregate and correlation identity for startup or one MCP call."""

    scope: ScopeKind
    operation: str
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_ns: int = field(default_factory=time.monotonic_ns)
    started_unix_ms: int = field(default_factory=_unix_ms)
    upstream_requests: int = 0
    api_requests: int = 0
    storage_requests: int = 0
    request_bytes: int = 0
    response_bytes: int = 0
    saturated: bool = False
    finished: bool = False

    def begin_request(
        self, transport: TransportKind, operation: str
    ) -> UpstreamRequestTelemetry:
        self.upstream_requests, overflow = _bounded_integer(
            self.upstream_requests + 1, maximum=_MAX_REQUEST_COUNT
        )
        self.saturated = self.saturated or overflow
        if transport == "api":
            self.api_requests, overflow = _bounded_integer(
                self.api_requests + 1, maximum=_MAX_REQUEST_COUNT
            )
            safe_operation = operation if operation in _API_OPERATIONS else "other"
        else:
            self.storage_requests, overflow = _bounded_integer(
                self.storage_requests + 1, maximum=_MAX_REQUEST_COUNT
            )
            safe_operation = (
                operation if operation in _STORAGE_OPERATIONS else "upload_chunk"
            )
        self.saturated = self.saturated or overflow
        return UpstreamRequestTelemetry(
            owner=self,
            transport=transport,
            operation=safe_operation,
            request_index=self.upstream_requests,
        )

    def _record_request(
        self,
        request: UpstreamRequestTelemetry,
        *,
        outcome: str,
        error_kind: str | None,
        status: int | None,
        request_bytes: int,
        response_bytes: int,
        retry_after_seconds: int | None,
        response_build_id: str | None,
    ) -> None:
        bounded_request, request_saturated = _bounded_integer(
            request_bytes, maximum=_MAX_METRIC_BYTES
        )
        bounded_response, response_saturated = _bounded_integer(
            response_bytes, maximum=_MAX_METRIC_BYTES
        )
        self.request_bytes, aggregate_request_saturated = _bounded_integer(
            self.request_bytes + bounded_request, maximum=_MAX_METRIC_BYTES
        )
        self.response_bytes, aggregate_response_saturated = _bounded_integer(
            self.response_bytes + bounded_response, maximum=_MAX_METRIC_BYTES
        )
        elapsed, elapsed_saturated = _elapsed_ms(request.started_ns)
        saturated = any(
            (
                request_saturated,
                response_saturated,
                aggregate_request_saturated,
                aggregate_response_saturated,
                elapsed_saturated,
            )
        )
        self.saturated = self.saturated or saturated
        safe_status = status if isinstance(status, int) and 100 <= status <= 599 else None
        safe_outcome = outcome if outcome in _OUTCOMES else "error"
        safe_error = error_kind if error_kind in _ERROR_KINDS else None
        event: dict[str, object] = {
            "api_request_id": (
                request.api_request_id if request.transport == "api" else None
            ),
            "correlation_id": self.correlation_id,
            "elapsed_ms": elapsed,
            "event": "lagniappe_mcp_upstream",
            "operation": request.operation,
            "outcome": safe_outcome,
            "request_bytes": bounded_request,
            "request_index": request.request_index,
            "response_bytes": bounded_response,
            "schema_version": 1,
            "scope": self.scope,
            "started_unix_ms": request.started_unix_ms,
            "status": safe_status,
            "transport": request.transport,
        }
        if safe_error is not None:
            event["error_kind"] = safe_error
        if (
            safe_status == 429
            and isinstance(retry_after_seconds, int)
            and not isinstance(retry_after_seconds, bool)
            and 1 <= retry_after_seconds <= 86_400
        ):
            event["retry_after_seconds"] = retry_after_seconds
        if isinstance(response_build_id, str) and _BUILD_ID_PATTERN.fullmatch(
            response_build_id
        ):
            event["response_build_id"] = response_build_id
        if saturated:
            event["saturated"] = True
        _write_event(event)

    def complete(self, outcome: str, *, error_kind: str | None = None) -> None:
        if self.finished:
            return
        self.finished = True
        elapsed, elapsed_saturated = _elapsed_ms(self.started_ns)
        self.saturated = self.saturated or elapsed_saturated
        safe_outcome = outcome if outcome in _OUTCOMES else "error"
        safe_error = error_kind if error_kind in _ERROR_KINDS else None
        event: dict[str, object] = {
            "api_requests": self.api_requests,
            "correlation_id": self.correlation_id,
            "elapsed_ms": elapsed,
            "event": "lagniappe_mcp_scope",
            "operation": self.operation,
            "outcome": safe_outcome,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "schema_version": 1,
            "scope": self.scope,
            "started_unix_ms": self.started_unix_ms,
            "storage_requests": self.storage_requests,
            "upstream_requests": self.upstream_requests,
        }
        if safe_error is not None:
            event["error_kind"] = safe_error
        if self.saturated:
            event["saturated"] = True
        _write_event(event)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/_telemetry.py::telemetry_scope
def classify_error(error: BaseException) -> str:
    """Map expected failures to a closed, argument-free evaluation class."""
    if isinstance(error, asyncio.CancelledError):
        return "client_cancelled"
    if isinstance(error, FileBoundaryError):
        return "local_boundary"
    if isinstance(error, SchemaError):
        if error.code in {
            "input_validation_failed",
            "proposal_validation_failed",
            "stale_contract_version",
        }:
            return "local_validation"
        return "upstream_response"
    if isinstance(error, TransportError):
        if error.code.endswith("_timeout"):
            return "adapter_timeout"
        if error.code in _STORAGE_ERROR_CODES:
            return (
                "storage_response"
                if error.status is not None
                or error.code
                in {
                    "invalid_download",
                    "invalid_upload_offset",
                    "invalid_upload_response",
                    "invalid_upload_session",
                    "media_too_large",
                    "mime_mismatch",
                    "redirect_rejected",
                    "unsupported_media",
                }
                else "storage_transport"
            )
        if error.code in _UPSTREAM_RESPONSE_CODES:
            return "upstream_response"
        return "api_transport"
    if isinstance(error, AdapterError):
        return "api_domain"
    return "adapter_failure"


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_telemetry_correlates_concurrent_calls_without_sensitive_values
# @tests tests_unit/test_033_mcp_adapter.py::test_telemetry_separates_startup_and_records_storage_bytes
@contextmanager
def telemetry_scope(scope: ScopeKind, operation: str) -> Iterator[TelemetryScope]:
    """Install one task-local correlation scope and always emit its summary."""
    measurement = TelemetryScope(scope, _safe_operation(scope, operation))
    token = _CURRENT_SCOPE.set(measurement)
    try:
        yield measurement
    except asyncio.CancelledError:
        measurement.complete("cancelled", error_kind="client_cancelled")
        raise
    except BaseException as error:
        measurement.complete("error", error_kind=classify_error(error))
        raise
    else:
        measurement.complete("success")
    finally:
        _CURRENT_SCOPE.reset(token)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/_telemetry.py::TelemetryScope
def begin_upstream_request(
    transport: TransportKind, operation: str
) -> UpstreamRequestTelemetry | None:
    """Begin a request only when serving a measured startup or MCP call."""
    scope = _CURRENT_SCOPE.get()
    if scope is None:
        return None
    return scope.begin_request(transport, operation)
