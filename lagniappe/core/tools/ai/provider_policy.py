"""Shared provider retry options and error classification."""

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


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_config_combines_search_tools_json_and_thinking_settings
# @pair ai:retry-config
def retry_http_options(api_version=None, attempts=None, headers=None):
    """Build request-level retry settings and optional routing headers."""
    retry_options = types.HttpRetryOptions(
        attempts=attempts or AI_RETRY_ATTEMPTS,
        initial_delay=AI_RETRY_INITIAL_DELAY,
        max_delay=AI_RETRY_MAX_DELAY,
        exp_base=AI_RETRY_EXP_BASE,
        jitter=AI_RETRY_JITTER,
        http_status_codes=AI_RETRY_STATUS_CODES,
    )
    options = {
        "retry_options": retry_options,
        "timeout": AI_REQUEST_TIMEOUT_MS,
    }
    if api_version:
        options["api_version"] = api_version
    if headers:
        options["headers"] = dict(headers)
    return types.HttpOptions(**options)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_image_generation_config_and_provider_error
# @tests tests_unit/test_015_ai_tools.py::test_generate_ai_image_returns_clean_provider_message
# @matrix ai : config image-generate provider-errors user-message
def provider_error_message(error):
    """Extract the concise provider message from a GenAI exception."""
    details = provider_error_details(error)
    if details.get("message"):
        return details["message"]

    return str(error).strip() or "The image provider did not return details."


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_provider_quota_error_is_wrapped_for_text_generation
# @matrix ai : provider-errors quota
def provider_error_details(error):
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


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_provider_quota_error_is_wrapped_for_text_generation
# @matrix ai : provider-errors quota
def is_provider_quota_error(error):
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


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_provider_transient_error_classification
# @matrix ai deferred-jobs : provider-errors retry-classification
def is_provider_transient_error(error):
    """Return whether a provider error is safe for a deferred retry."""
    if isinstance(error, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    code = provider_error_details(error).get("code")
    return str(code) in {str(value) for value in AI_RETRY_STATUS_CODES}
