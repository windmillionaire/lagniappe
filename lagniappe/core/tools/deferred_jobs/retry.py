"""Deferred-job retry classification, backoff, and terminal errors."""

import random

from google.api_core import exceptions as google_exceptions

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    DEFERRED_JOB_QUOTA_RETRY_DELAYS,
    DEFERRED_JOB_QUOTA_RETRY_JITTER_SECONDS,
    DEFERRED_JOB_RETRY_DELAYS,
)

from .errors import DeferredJobDeadlineError


TRANSIENT_GOOGLE_ERRORS = (
    google_exceptions.BadGateway,
    google_exceptions.DeadlineExceeded,
    google_exceptions.GatewayTimeout,
    google_exceptions.InternalServerError,
    google_exceptions.ServiceUnavailable,
    google_exceptions.TooManyRequests,
)
MODEL_BUSY_MESSAGE = "The model is too busy right now. Try again later."




# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_retries_sdk_timeout
# @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_retries_sdk_5xx_and_persists_clean_terminal_message
# @matrix deferred-jobs : provider-errors provider-timeout retry
def _retryable(error):
    transient = (
        DeferredJobDeadlineError,
        exceptions.AIQuotaError,
        *TRANSIENT_GOOGLE_ERRORS,
        ConnectionError,
        TimeoutError,
    )
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        from lagniappe.core.tools.ai.core import is_provider_transient_error

        if isinstance(current, transient) or is_provider_transient_error(current):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False




# @testable infrastructure
def _quota_error(error):
    """Return a wrapped provider-quota error, when present."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        if isinstance(current, exceptions.AIQuotaError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None




# @testable infrastructure
def _retry_delays(error):
    """Choose stronger application backoff after provider quota exhaustion."""
    if _quota_error(error):
        return DEFERRED_JOB_QUOTA_RETRY_DELAYS
    return DEFERRED_JOB_RETRY_DELAYS




# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_waits_for_dependency_without_consuming_provider_retry
# @matrix deferred-jobs : dependency-wait provider-attempt-isolation
def _provider_retry_attempt(job):
    """Return the provider attempt number after excluding dependency-only runs."""
    parameters = getattr(job, "parameters", None) or {}
    dependency_waits = int(parameters.get("_dependency_waits", 0) or 0)
    return max(int(getattr(job, "attempt", 0) or 0) - dependency_waits, 1)




# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_retries_sdk_5xx_and_persists_clean_terminal_message
# @pair deferred-jobs:terminal-message
def _terminal_error(error, *, requires_ai=False):
    """Replace exhausted provider details with a concise user-facing message."""
    quota_error = _quota_error(error)
    if quota_error is not None:
        return exceptions.AIQuotaError(
            MODEL_BUSY_MESSAGE,
            context=dict(getattr(quota_error, "context", None) or {}),
        )
    if requires_ai and _retryable(error):
        return exceptions.AIException(
            MODEL_BUSY_MESSAGE,
            context=dict(getattr(error, "context", None) or {}),
        )
    return error




# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_increases_later_quota_backoff_without_adding_attempts
# @matrix deferred-jobs : backoff jitter quota
def _retry_delay(error, attempt):
    delays = _retry_delays(error)
    delay = delays[int(attempt) - 1]
    if delays is DEFERRED_JOB_QUOTA_RETRY_DELAYS:
        delay += random.randint(0, DEFERRED_JOB_QUOTA_RETRY_JITTER_SECONDS)
    return delay
