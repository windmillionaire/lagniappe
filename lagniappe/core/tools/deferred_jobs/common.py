"""Small shared helpers for deferred-job tool services."""

import json
from datetime import datetime, UTC

from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache




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




def _load_reference(reference):
    if reference is None:
        return None
    if hasattr(reference, "db"):
        return reference
    if not isinstance(reference, dict) or not reference.get("id"):
        raise exceptions.ValidationError("Deferred job input reference is invalid.")
    request = (
        Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION)
        if reference.get("kind") in {"file", "task", "task_history"}
        else Fetch.direct()
    )
    entity = Entities.fetch_one(reference["id"], request=request)
    if entity is None or entity.entity_kind != reference.get("kind"):
        raise exceptions.ValidationError(
            f"Deferred job input {reference.get('kind')} is missing."
        )
    return entity




def _json_copy(value):
    return json.loads(json.dumps(value, default=str))




def _utc(value: datetime | None = None) -> datetime:
    return value or datetime.now(UTC)




def _error_record(error, *, retryable, attempt):
    return {
        "type": type(error).__name__,
        "message": str(error),
        "retryable": bool(retryable),
        "attempt": int(attempt or 0),
        "context": _json_copy(getattr(error, "context", None) or {}),
    }
