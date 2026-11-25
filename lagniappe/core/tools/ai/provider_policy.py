"""Shared provider retry options and error classification."""

from collections.abc import Mapping
from typing import TypedDict

from google.genai import types
import httpx

from config.ai_models import (
    AI_REQUEST_TIMEOUT_MS,
    AI_RETRY_ATTEMPTS,
    AI_RETRY_EXP_BASE,
    AI_RETRY_INITIAL_DELAY,
    AI_RETRY_JITTER,
    AI_RETRY_MAX_DELAY,
    AI_RETRY_STATUS_CODES,
)


class ProviderErrorDetails(TypedDict):
    code: object
    status: object
    message: str | None
    raw: str


class ReportOriginalsRejected(Exception):
    """The provider rejected the uploaded media on the initial planner request."""

    @staticmethod
    def matches(error: Exception) -> bool:
        details = provider_error_details(error)
        message = (details["message"] or details["raw"]).casefold()
        return str(details["code"]) == "400" and any(marker in message for marker in (
            "document has no pages", "exceeds the supported page limit", "unsupported mime type",
            "unable to process input image", "input token count", "too many input tokens",
        ))


def retry_http_options(
    api_version: str | None = None,
    attempts: int | None = None,
    headers: Mapping[str, str] | None = None,
) -> types.HttpOptions:
    """Build request-level retry settings and optional routing headers."""
    retry_options = types.HttpRetryOptions(
        attempts=attempts or AI_RETRY_ATTEMPTS,
        initial_delay=AI_RETRY_INITIAL_DELAY,
        max_delay=AI_RETRY_MAX_DELAY,
        exp_base=AI_RETRY_EXP_BASE,
        jitter=AI_RETRY_JITTER,
        http_status_codes=AI_RETRY_STATUS_CODES,
    )
    options: dict[str, object] = {
        "retry_options": retry_options,
        "timeout": AI_REQUEST_TIMEOUT_MS,
    }
    if api_version:
        options["api_version"] = api_version
    if headers:
        options["headers"] = dict(headers)
    return types.HttpOptions.model_validate(options)


def provider_error_message(error: BaseException) -> str:
    """Extract the concise provider message from a GenAI exception."""
    details = provider_error_details(error)
    if details["message"]:
        return details["message"]

    return str(error).strip() or "The image provider did not return details."


def provider_error_details(error: BaseException) -> ProviderErrorDetails:
    """Extract structured details from a GenAI provider exception."""
    message = getattr(error, "message", None)
    code = getattr(error, "code", None)
    status = getattr(error, "status", None)

    details = getattr(error, "details", None)
    if isinstance(details, dict):
        nested = details.get("error", {})
        if isinstance(nested, dict):
            message = message or nested.get("message")
            code = code or nested.get("code")
            status = status or nested.get("status")

    return {
        "code": code,
        "status": status,
        "message": str(message).strip() if message else None,
        "raw": str(error).strip(),
    }


def is_provider_quota_error(error: BaseException) -> bool:
    """Return whether a provider exception represents retryable quota pressure."""
    details = provider_error_details(error)
    code = details.get("code")
    status = str(details.get("status") or "")
    raw = str(details.get("raw") or "")
    return (
        str(code) == "429"
        or status == "RESOURCE_EXHAUSTED"
        or "RESOURCE_EXHAUSTED" in raw
    )


def is_provider_transient_error(error: BaseException) -> bool:
    """Return whether a provider error is safe for a deferred retry."""
    if isinstance(error, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    code = provider_error_details(error).get("code")
    return str(code) in {str(value) for value in AI_RETRY_STATUS_CODES}
