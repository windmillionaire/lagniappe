"""Bounded errors safe to expose through MCP or command diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from .limits import MAX_ERROR_BYTES


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/errors.py::AdapterError
def _bounded_text(value: object, limit: int = MAX_ERROR_BYTES) -> str:
    text = " ".join(str(value).split())
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text
    marker = "…"
    room = max(0, limit - len(marker.encode("utf-8")))
    return encoded[:room].decode("utf-8", errors="ignore") + marker


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/errors.py::AdapterError
def _safe_details(value: Any, *, depth: int = 0) -> Any:
    """Keep only bounded JSON values; never stringify arbitrary exceptions."""
    if depth > 8:
        return None
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _bounded_text(value, 1024)
    if isinstance(value, list):
        return [_safe_details(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, dict):
        return {
            _bounded_text(key, 80): _safe_details(item, depth=depth + 1)
            for key, item in list(value.items())[:20]
            if isinstance(key, str)
            and key.casefold()
            not in {
                "api_key",
                "authorization",
                "cookie",
                "download_url",
                "session_url",
                "token",
                "upload_id",
                "x-goog-signature",
            }
        }
    return None


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_api_errors_redact_credentials_and_duplicate_json_is_rejected
# @tests tests_unit/test_033_mcp_adapter.py::test_mcp_v2_results_use_direct_structured_values_and_complete_aliases
@dataclass(slots=True)
class AdapterError(Exception):
    """An expected failure with a stable, non-secret model-facing form."""

    code: str
    message: str
    retryable: bool = False
    status: int | None = None
    request_id: str | None = None
    details: Any = None

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/errors.py::AdapterError
    def __post_init__(self) -> None:
        self.message = _bounded_text(self.message, 2048)
        self.details = _safe_details(self.details)
        Exception.__init__(self, self.message)

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/errors.py::AdapterError
    def render(self) -> str:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.status is not None:
            payload["http_status"] = self.status
        if self.request_id:
            payload["request_id"] = _bounded_text(self.request_id, 80)
        if self.details is not None:
            payload["details"] = self.details

        def serialize(value: dict[str, Any]) -> str:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

        rendered = serialize(payload)
        if len(rendered.encode("utf-8")) <= MAX_ERROR_BYTES:
            return rendered

        # Never byte-truncate serialized JSON: that can split an escape or
        # string and turn a typed tool error into malformed text. Preserve the
        # actionable fields first, then replace oversized detail structurally.
        if "details" in payload:
            payload["details"] = {"truncated": True}
            rendered = serialize(payload)
            if len(rendered.encode("utf-8")) <= MAX_ERROR_BYTES:
                return rendered
            payload.pop("details")
            rendered = serialize(payload)
            if len(rendered.encode("utf-8")) <= MAX_ERROR_BYTES:
                return rendered

        # Pathological control-heavy internal strings can expand when JSON-
        # escaped even though their source text is bounded. This fixed ASCII
        # fallback is always valid JSON and remains below the public cap.
        fallback: dict[str, Any] = {
            "code": "adapter_error",
            "message": "The bounded error could not be rendered safely.",
            "retryable": bool(self.retryable),
        }
        if isinstance(self.status, int):
            fallback["http_status"] = self.status
        return serialize(fallback)


class ConfigurationError(AdapterError):
    """Local configuration is missing, invalid, or unsafe."""


class SchemaError(AdapterError):
    """An advertised or returned JSON Schema contract is incompatible."""


class TransportError(AdapterError):
    """A bounded network or upstream response failure."""


class FileBoundaryError(AdapterError):
    """A requested local file is outside the explicit safe boundary."""
