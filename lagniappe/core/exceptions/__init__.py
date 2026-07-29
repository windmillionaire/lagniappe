"""Custom exceptions and error capture (Sentry in prod, console in dev)."""

from datetime import datetime
from pprint import pformat
import traceback
import sys

from lagniappe import CONFIG

from .request import (
    extract_request_info,
    sanitize_error_context,
    sanitize_sentry_event,
)
from .frames import extract_local_variables, extract_entity_from_frames
from .utility import format_debug_context_for_template


class DeploymentSettingsError(ValueError):
    """Raised when saved deployment settings cannot be applied safely."""


class AISettingsError(ValueError):
    """Raised when saved AI model settings cannot be applied safely."""


class ValidationError(Exception):
    """Raised when entity data fails validation (import, form submission)."""


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_exception_context_survives_autofill_wrapper_without_duplicate_capture
# @features ai
# @dimensions error-context
class AIException(Exception):
    """Raised when AI generation fails or returns invalid output."""

    def __init__(self, message, context=None):
        super().__init__(message)
        self.context = context or {}


class AIQuotaError(AIException):
    """Raised when the AI provider reports retryable quota exhaustion."""


class TaskCompletionError(Exception):
    """Raised when a task can't be completed (required fields missing)."""


class NetworkError(Exception):
    """Raised when an external API call fails."""


class SiteImageError(Exception):
    """Raised when site image processing fails."""


# @testable infrastructure
class PropertyError(Exception):
    """Raised when a property fails to instantiate or is used incorrectly.

    The ``property_name`` and optional ``entity`` are set as attributes
    for debugging. The original exception is chained (__cause__).
    """

    def __init__(self, message, entity=None):
        super().__init__(message)
        self.entity = entity


class UnloadedRelationError(Exception):
    """Raised or captured when code asks an entity relation to lazy-load."""


# @testable false
# @covered-by lagniappe/web/start/errors.py::_handle_error_with_context
# @reason debug context is rendered and captured through the Flask error handler
def get_debug_context(error):
    """
    Extract comprehensive debug context from an exception.
    Returns a dict with all available debug information.
    """
    context = {
        "timestamp": datetime.now().isoformat(),
        "error_type": type(error).__name__,
        "error_message": str(error),
    }

    # Get the traceback
    exc_tb = sys.exc_info()[2]

    # Entity data (from frame locals; we don't expose the full frames)
    if exc_tb:
        frames_info = extract_local_variables(exc_tb)
        context["entity"] = extract_entity_from_frames(frames_info)

    # Request info
    try:
        context["request"] = extract_request_info()
    except Exception:
        context["request"] = None

    # Full traceback string
    context["traceback"] = traceback.format_exc()

    return context


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_error_capture_can_wait_for_sentry_delivery
# @tests tests_unit/test_001_test_general_and_utilities.py::test_error_capture_sanitizes_context_without_duplicate_request
# @pairs error-handling:sentry error-handling:terminal-delivery
# @pairs deferred-jobs:sentry deferred-jobs:terminal-delivery
# @pairs error-handling:privacy error-handling:request-context error-handling:redaction
def capture(error, context=None, level="error", *, wait_for_delivery=False):
    """Capture an error, sending to Sentry in production or printing in dev."""
    if CONFIG.capture_errors:
        import sentry_sdk

        # Merge in debug context for richer Sentry reports
        full_context = {}
        exception_context = getattr(error, "context", None)
        if isinstance(exception_context, dict):
            full_context.update(exception_context)
        if context:
            full_context.update(context)

        # Add the request once. Flask error handlers already pass one as part
        # of get_debug_context().
        if "request" not in full_context:
            try:
                request_info = extract_request_info()
                if request_info:
                    full_context["request"] = request_info
            except Exception:
                pass

        full_context = sanitize_error_context(full_context)

        if full_context:
            with sentry_sdk.push_scope() as scope:
                for key, value in full_context.items():
                    if isinstance(value, dict):
                        scope.set_context(key, value)
                    else:
                        scope.set_extra(key, value)

                if isinstance(error, Exception):
                    sentry_sdk.capture_exception(error)
                else:
                    sentry_sdk.capture_message(str(error), level)
        else:
            if isinstance(error, Exception):
                sentry_sdk.capture_exception(error)
            else:
                sentry_sdk.capture_message(str(error), level)
        if wait_for_delivery:
            # App Engine may suspend an instance as soon as a caught task
            # request returns, before Sentry's background transport drains.
            sentry_sdk.flush(timeout=2.0)
    else:
        print(f"Error: {error}")
        if context:
            print(f"Context: {pformat(context)}")


from .entity_load import record_entity_load_trace
from .unloaded_relations import capture_unloaded_relation

__all__ = [
    "AISettingsError",
    "AIException",
    "AIQuotaError",
    "DeploymentSettingsError",
    "NetworkError",
    "PropertyError",
    "SiteImageError",
    "TaskCompletionError",
    "UnloadedRelationError",
    "ValidationError",
    "capture",
    "capture_unloaded_relation",
    "extract_request_info",
    "format_debug_context_for_template",
    "get_debug_context",
    "record_entity_load_trace",
    "sanitize_error_context",
    "sanitize_sentry_event",
]
