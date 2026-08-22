"""Shared retry behavior for short Datastore transactions."""

from functools import wraps
import time

from google.api_core import exceptions as google_exceptions


TRANSACTION_RETRY_DELAYS = (0.05, 0.1, 0.2)


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @pair notifications:transaction-retry
def retry_aborted(operation):
    """Retry a complete transaction after transient Datastore contention."""

    # @testable false
    # @covered-by lagniappe/core/tools/database/transactions.py::retry_aborted
    # @reason generated wrapper is exercised through the public retry decorator
    @wraps(operation)
    def retried(*args, **kwargs):
        for attempt in range(len(TRANSACTION_RETRY_DELAYS) + 1):
            try:
                return operation(*args, **kwargs)
            except google_exceptions.Aborted:
                if attempt >= len(TRANSACTION_RETRY_DELAYS):
                    raise
                time.sleep(TRANSACTION_RETRY_DELAYS[attempt])

    return retried
