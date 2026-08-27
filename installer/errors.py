"""Typed setup failures and bounded provider retry helpers."""

import re
import subprocess
import time

GCLOUD_TIMEOUT = 600
GIT_TIMEOUT = 300
PIP_TIMEOUT = 900
NPM_TIMEOUT = 900
PLAYWRIGHT_TIMEOUT = 1200


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_error_classification_and_retry_contract
# @matrix setup : errors exit-status
class SetupError(RuntimeError):
    """Base failure mapped to a nonzero process status by ``python -m installer``."""

    exit_code = 1
    category = "setup"

    def __init__(self, message="Setup failed.", *, repair_action=None):
        super().__init__(message)
        self.repair_action = repair_action


class SetupCancelled(SetupError):
    category = "cancelled"


class SetupInterrupted(SetupError):
    category = "interrupted"
    exit_code = 130


class ProviderError(SetupError):
    category = "provider"


# @testable false
# @covered-by installer/errors.py::google_service_terms_error
# @reason typed provider detail container is exercised through terms-error normalization
class ProviderTermsNotAccepted(ProviderError):
    category = "terms-not-accepted"

    def __init__(
        self,
        message="Google service terms have not been accepted.",
        *,
        terms_id=None,
        terms_url=None,
        repair_action=None,
    ):
        super().__init__(message, repair_action=repair_action)
        self.terms_id = terms_id
        self.terms_url = terms_url


class ProviderNotFound(ProviderError):
    category = "not-found"


class ProviderPermissionDenied(ProviderError):
    category = "permission-denied"


class ProviderInvalidInput(ProviderError):
    category = "invalid-input"


class ProviderConflict(ProviderError):
    category = "conflict"


class ProviderTransientError(ProviderError):
    category = "transient"


class ProviderTimeout(ProviderTransientError):
    category = "timeout"


_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_GOOGLE_SERVICE_TERMS_NAMES = {
    "cloud": "Google Cloud service terms",
    "maps": "Google Maps Platform terms",
}


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_error_classification_and_retry_contract
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_enable_gcloud_apis_guides_maps_terms_then_retries_activation
# @matrix setup : error-guidance google-service-terms identity provider-errors
def google_service_terms_error(detail, *, account=None):
    """Return a concise actionable error for Google's per-service agreements."""
    detail = str(detail or "")
    normalized = detail.casefold()
    if "ureq_tos_not_accepted" not in normalized:
        return None
    match = re.search(r"tos_id=([a-z0-9_-]+)", normalized)
    if match is None:
        match = re.search(
            r"terms of service ['\"]([a-z0-9_-]+)['\"]",
            normalized,
        )
    terms_id = match.group(1) if match is not None else "cloud"
    terms_name = _GOOGLE_SERVICE_TERMS_NAMES.get(
        terms_id,
        f"Google service terms ({terms_id})",
    )
    terms_url = f"https://console.developers.google.com/terms/{terms_id}"
    selected_account = str(account or "").strip()
    account_clause = f" for '{selected_account}'" if selected_account else ""
    account_instruction = (
        f"Sign in as '{selected_account}'" if selected_account else "Sign in"
    )
    from runner.context import setup_command

    return ProviderTermsNotAccepted(
        f"{terms_name} have not been accepted{account_clause}.",
        terms_id=terms_id,
        terms_url=terms_url,
        repair_action=(
            f"{account_instruction} at {terms_url}, accept the {terms_name}, "
            f"then rerun {setup_command()}."
        ),
    )


# @testable false
# @covered-by installer/errors.py::classify_provider_error
# @reason provider status adapter exercised through public classification
def _status_code(error):
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "code", None)
    if callable(status):
        try:
            status = status()
        except Exception:
            status = None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_error_classification_and_retry_contract
# @matrix setup : classification provider-errors
def classify_provider_error(error, *, message=None, status_code=None):
    """Return one typed provider failure without confusing access with absence."""
    if isinstance(error, SetupError):
        return error
    detail = str(message or error or "Provider operation failed.").strip()
    status = status_code if status_code is not None else _status_code(error)
    name = type(error).__name__.casefold()
    text = f"{name} {error} {detail}".casefold()

    terms_error = google_service_terms_error(text)
    if terms_error is not None:
        return terms_error

    if isinstance(error, (subprocess.TimeoutExpired, TimeoutError)) or (
        "timeout" in name or "timed out" in text
    ):
        return ProviderTimeout(detail)
    if status in _TRANSIENT_STATUS_CODES or any(
        marker in text
        for marker in (
            "badgateway",
            "deadlineexceeded",
            "gatewaytimeout",
            "internalservererror",
            "serviceunavailable",
            "toomanyrequests",
            "connectionerror",
            "temporarily unavailable",
            "connection reset",
            "connectionreset",
            "connectionaborted",
            "forcibly closed",
            "service_disabled",
        )
    ):
        return ProviderTransientError(detail)
    if status in (401, 403) or any(
        marker in text
        for marker in ("forbidden", "permissiondenied", "permission denied")
    ):
        return ProviderPermissionDenied(detail)
    if (
        status == 404
        or "notfound" in name
        or "not found" in text
        or "not_found" in text
    ):
        return ProviderNotFound(detail)
    if status == 409 or "alreadyexists" in name or any(
        marker in text for marker in ("already_exists", "already exists", "conflict")
    ):
        return ProviderConflict(detail)
    if status in (400, 422) or any(
        marker in text for marker in ("badrequest", "invalidargument")
    ):
        return ProviderInvalidInput(detail)
    return ProviderError(detail)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_error_classification_and_retry_contract
# @matrix setup : provider-errors retry timeout
def retry_provider_call(
    operation,
    *,
    description,
    attempts=4,
    delays=(1, 2, 4),
    sleep=time.sleep,
):
    """Retry only typed transient provider failures with a bounded backoff."""
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as error:
            classified = classify_provider_error(
                error,
                message=f"{description}: {error}",
            )
            if (
                not isinstance(classified, ProviderTransientError)
                or attempt == attempts - 1
            ):
                raise classified from error
            sleep(delays[min(attempt, len(delays) - 1)])
    raise ProviderTimeout(f"{description} did not complete.")
