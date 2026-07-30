"""Shared authenticated HTTP helpers for Google provider setup."""

import time

from installer import FORMATTER

from .errors import ProviderTimeout, classify_provider_error, retry_provider_call
from .package_install import install_if_missing

PROVIDER_API_TIMEOUT = 10
PROVIDER_OPERATION_TIMEOUT_SECONDS = 120
PROVIDER_OPERATION_POLL_DELAYS = (1, 2, 4, 5)
PROVIDER_REQUEST_ATTEMPTS = 4


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_google_provider_access_token_refresh_retries_connection_resets
# @features setup
# @dimensions google-provider authentication retry
def _get_access_token():
    """Get an OAuth2 access token for Google provider management APIs."""
    f = FORMATTER.initialize()
    install_if_missing(
        "google.auth", "Google authentication library", package_name="google-auth"
    )
    import google.auth
    import google.auth.transport.requests

    credentials, _project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if not credentials:
        print(f.error("Failed to get Google provider credentials."))
        return None
    request = google.auth.transport.requests.Request()
    retry_provider_call(
        lambda: credentials.refresh(request),
        description="Google provider access-token refresh",
        attempts=PROVIDER_REQUEST_ATTEMPTS,
        delays=PROVIDER_OPERATION_POLL_DELAYS,
        sleep=time.sleep,
    )
    return credentials.token


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_google_provider_helpers_use_timeouts_and_report_errors
# @pair setup:google-provider-api
# @pair google-provider-api:quota-project
def _google_request_headers(access_token, project_id, *, json_content=False):
    """Build quota-project-bound Google provider REST headers."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-goog-user-project": project_id,
    }
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_google_provider_helpers_use_timeouts_and_report_errors
# @tests tests_tooling/test_001b_setup_providers.py::test_google_provider_api_request_reports_reason_and_retries_service_activation
# @features setup
# @dimensions google-provider-api diagnostics retry
def _api_request(
    session,
    method,
    url,
    headers,
    json_data=None,
    allow_codes=None,
    *,
    attempts=None,
    delays=None,
    retry_label=None,
):
    """Make a bounded retrying Google provider request."""
    allow_codes = allow_codes or []
    attempts = attempts or PROVIDER_REQUEST_ATTEMPTS
    delays = delays or PROVIDER_OPERATION_POLL_DELAYS

    # @testable false
    # @covered-by installer/google_provider.py::_api_request
    # @reason retry-delay selection is exercised through the bounded provider request
    def wait_for_retry(attempt):
        delay = delays[min(attempt, len(delays) - 1)]
        if retry_label:
            print(
                FORMATTER.initialize().info(
                    f"{retry_label} is still becoming available; "
                    f"retrying in {delay} seconds..."
                )
            )
        time.sleep(delay)

    for attempt in range(attempts):
        try:
            callback = getattr(session, method.casefold(), None)
            if callback is None or method not in {"GET", "POST", "PATCH"}:
                raise ValueError(f"Unsupported provider request method: {method}")
            kwargs = {"headers": headers, "timeout": PROVIDER_API_TIMEOUT}
            if method != "GET":
                kwargs["json"] = json_data or {}
            response = callback(url, **kwargs)
        except Exception as error:
            classified = classify_provider_error(
                error,
                message=f"Google provider {method} request failed: {error}",
            )
            if classified.category != "transient" or attempt == attempts - 1:
                raise classified from error
            wait_for_retry(attempt)
            continue

        if response.status_code == 200 or response.status_code in allow_codes:
            return response, response.json() if response.text else {}
        try:
            response_data = response.json()
        except (AttributeError, ValueError):
            response_data = {}
        error_data = (
            response_data.get("error") or {}
            if isinstance(response_data, dict)
            else {}
        )
        if not isinstance(error_data, dict):
            error_data = {}
        provider_status = str(error_data.get("status") or "").strip()
        provider_message = " ".join(
            str(error_data.get("message") or response.text or "").split()
        )[:1000]
        provider_reasons = []
        for detail in error_data.get("details") or ():
            if not isinstance(detail, dict):
                continue
            reason = str(detail.get("reason") or "").strip()
            if reason and reason not in provider_reasons:
                provider_reasons.append(reason)
        status_detail = f"HTTP {response.status_code}"
        if provider_status:
            status_detail += f" {provider_status}"
        if provider_reasons:
            status_detail += f" ({', '.join(provider_reasons)})"
        if provider_message:
            status_detail += f": {provider_message}"
        classified = classify_provider_error(
            RuntimeError(status_detail),
            message=f"Google provider {method} request failed: {status_detail}",
            status_code=response.status_code,
        )
        if classified.category != "transient" or attempt == attempts - 1:
            raise classified
        wait_for_retry(attempt)
    raise ProviderTimeout(f"Google provider request timed out: {method} {url}")
