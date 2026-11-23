"""Shared retry behavior for short Datastore transactions."""

import time
from collections.abc import Callable
from functools import wraps

from google.api_core import exceptions as google_exceptions


TRANSACTION_RETRY_DELAYS = (0.05, 0.1, 0.2)


def retry_aborted[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    """Retry a complete transaction after transient Datastore contention."""

    @wraps(operation)
    def retried(*args: P.args, **kwargs: P.kwargs) -> R:
        for delay in TRANSACTION_RETRY_DELAYS:
            try:
                return operation(*args, **kwargs)
            except google_exceptions.Aborted:
                time.sleep(delay)
        return operation(*args, **kwargs)

    return retried
