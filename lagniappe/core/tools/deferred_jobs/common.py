"""Small shared helpers for deferred-job tool services."""

import json
from datetime import datetime, timezone

from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache




# @testable true
# @tests tests_unit/test_023b_deferred_job_service.py::test_cancel_deletes_tasks_and_persists_a_tombstone
# @tests tests_unit/test_023b_deferred_job_service.py::test_operation_projection_failure_is_nonfatal
# @matrix deferred-jobs : cache-failure-isolation redis-projection
# @pair deferred-jobs:deterministic-task-id
def _publish_operation_projection(job, *, operation):
    """Publish disposable polling state without changing a durable outcome."""
    try:
        cache.update_operation_projection(job)
    except Exception as error:
        exceptions.capture(
            error,
            context={
                "deferred_job": {
                    "id": getattr(job, "urlsafe_key", None),
                    "operation": operation,
                }
            },
            level="warning",
        )




# @testable infrastructure
def _load_reference(reference):
    if reference is None:
        return None
    if hasattr(reference, "db"):
        return reference
    if not isinstance(reference, dict) or not reference.get("id"):
        raise exceptions.ValidationError("Deferred job input reference is invalid.")
    entity = Entities.fetch_one(reference["id"], request=Fetch.direct())
    if entity is None or entity.entity_kind != reference.get("kind"):
        raise exceptions.ValidationError(
            f"Deferred job input {reference.get('kind')} is missing."
        )
    return entity




# @testable infrastructure
def _json_copy(value):
    return json.loads(json.dumps(value, default=str))




# @testable infrastructure
def _utc(value=None):
    return value or datetime.now(timezone.utc)




# @testable infrastructure
def _error_record(error, *, retryable, attempt):
    return {
        "type": type(error).__name__,
        "message": str(error),
        "retryable": bool(retryable),
        "attempt": int(attempt or 0),
        "context": _json_copy(getattr(error, "context", None) or {}),
    }
