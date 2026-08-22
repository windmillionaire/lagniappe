"""Deferred-job lifecycle state and privacy-bounded projections."""

from datetime import datetime, timezone

from lagniappe.core.definitions import (
    DEFERRED_JOB_HEARTBEAT_SECONDS,
    DeferredJobPhase,
    DeferredJobStatus,
)

from .deferred_job_request import JSONValue
from .base_db import DBProperty


TERMINAL_STATUSES = frozenset(
    {
        DeferredJobStatus.SUCCEEDED.value,
        DeferredJobStatus.FAILED.value,
        DeferredJobStatus.CANCELLED.value,
        DeferredJobStatus.SUPERSEDED.value,
    }
)
ACTIVE_STATUSES = frozenset(
    {
        DeferredJobStatus.QUEUED.value,
        DeferredJobStatus.RUNNING.value,
        DeferredJobStatus.RETRY_WAIT.value,
    }
)
PHASE_LABELS = {
    DeferredJobPhase.QUEUED.value: "Waiting to start",
    DeferredJobPhase.PREPARING_INPUTS.value: "Preparing inputs",
    DeferredJobPhase.SUMMARIZING.value: "Summarizing files",
    DeferredJobPhase.GENERATING.value: "Generating",
    DeferredJobPhase.USING_TOOLS.value: "Checking context",
    DeferredJobPhase.FINALIZING.value: "Finishing up",
    DeferredJobPhase.VALIDATING.value: "Validating",
    DeferredJobPhase.PREPARED.value: "Ready to save",
    DeferredJobPhase.APPLYING.value: "Saving",
    DeferredJobPhase.RETRY_WAIT.value: "Waiting to retry",
    DeferredJobPhase.COMPLETE.value: "Complete",
    DeferredJobPhase.FAILED.value: "Failed",
    DeferredJobPhase.CANCELLED.value: "Cancelled",
    DeferredJobPhase.SUPERSEDED.value: "Replaced",
}


class Status(DBProperty):
    _id = "status"


class StatusRevision(DBProperty):
    _id = "status_revision"


class Progress(JSONValue):
    _id = "progress"


class Checkpoint(JSONValue):
    _id = "checkpoint"


class Result(JSONValue):
    _id = "result"


class Error(JSONValue):
    _id = "error"


class Delivery(JSONValue):
    _id = "delivery"


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lifecycle_normalizes_timestamps_and_elapsed_time
# @pair deferred-jobs:timestamp-normalization
def datetime_value(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lifecycle_normalizes_timestamps_and_elapsed_time
# @pair deferred-jobs:elapsed-time
def elapsed_seconds(start, now):
    start = datetime_value(start)
    return max(int((now - start).total_seconds()), 0) if start else 0


# @testable true
# @tests tests_e2e/002_home/test_002o_deferred_jobs.py::test_poll_operation_is_owner_safe
# @tests tests_unit/test_023a_deferred_job_properties.py::test_status_projection_is_bounded_and_marks_stale_work
# @features deferred-jobs
# @dimensions status progress timing stale-state privacy
def status_projection(job, *, now):
    progress = dict(getattr(job, "progress", None) or {})
    client = dict(getattr(job, "client", None) or {})
    phase = progress.get("phase") or getattr(job, "status", None) or "queued"
    modified = datetime_value(getattr(job, "modified", None))
    stale = bool(
        getattr(job, "status", None) in ACTIVE_STATUSES
        and modified
        and (now - modified).total_seconds() >= DEFERRED_JOB_HEARTBEAT_SECONDS * 2
    )
    error = getattr(job, "error", None) or {}
    next_attempt = datetime_value(getattr(job, "next_attempt_at", None))
    result = {
        "key": job.urlsafe_key,
        "type": getattr(job, "job_type", None),
        "status": getattr(job, "status", None),
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, "Working"),
        "attempt": int(getattr(job, "attempt", 0) or 0),
        "elapsed_seconds": elapsed_seconds(getattr(job, "created", None), now),
        "phase_elapsed_seconds": elapsed_seconds(progress.get("updated_at"), now),
        "updated_at": modified.isoformat() if modified else None,
        "next_attempt_at": next_attempt.isoformat() if next_attempt else None,
        "revision": int(getattr(job, "status_revision", 0) or 0),
        "terminal": getattr(job, "status", None) in TERMINAL_STATUSES,
        "stale": stale,
        "recovering": bool(
            stale
            or getattr(job, "dispatch_state", None) == "pending"
            or getattr(job, "status", None) == DeferredJobStatus.RETRY_WAIT.value
        ),
        "source_widget": client.get("source_widget"),
        "destination": client.get("destination"),
        "entity_key": client.get("key"),
    }
    if result["terminal"] and error.get("message"):
        result["error"] = str(error["message"])[:500]
    return result


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_admin_projection_exposes_diagnostics_without_payload_content
# @pair deferred-jobs:diagnostics
# @pair deferred-jobs:privacy
def admin_projection(job, *, now):
    """Extend owner-visible status with bounded operational diagnostics."""
    projection = status_projection(job, now=now)
    actor = getattr(job, "actor", None)
    inputs = getattr(job, "inputs", None) or {}
    input_refs = {
        str(name): {"kind": value.get("kind"), "id": value.get("id")}
        for name, value in inputs.items()
        if isinstance(value, dict) and value.get("kind") and value.get("id")
    }
    progress = getattr(job, "progress", None) or {}
    checkpoint = getattr(job, "checkpoint", None) or {}
    delivery = getattr(job, "delivery", None) or {}
    error = getattr(job, "error", None) or {}

    timestamps = {}
    for output_name, attribute_name in (
        ("modified_at", "modified"),
        ("dispatched_at", "dispatched_at"),
        ("deadline_at", "deadline_at"),
        ("lease_expires_at", "lease_expires"),
    ):
        value = datetime_value(getattr(job, attribute_name, None))
        timestamps[output_name] = value.isoformat() if value else None

    created = datetime_value(getattr(job, "created", None))
    projection.update(
        {
            "actor": (
                getattr(actor, "name", None)
                or getattr(actor, "email", None)
                or "Unknown user"
            ),
            "dispatch_state": getattr(job, "dispatch_state", None),
            "job_version": int(getattr(job, "job_version", 0) or 0),
            "start_completed": bool(getattr(job, "start_completed", False)),
            "created_at": created.isoformat() if created else None,
            "telemetry_id": getattr(job, "telemetry_id", None),
            "input_refs": input_refs,
            "progress": {
                key: progress[key]
                for key in ("phase", "updated_at", "delay_seconds")
                if progress.get(key) is not None
            },
            "checkpoint_state": {
                key: checkpoint[key]
                for key in ("schema_version", "stage", "phase")
                if checkpoint.get(key) is not None
            },
            "delivery_state": {
                key: bool(delivery[key])
                for key in ("failure", "cleanup", "notification", "input_missing")
                if key in delivery
            },
            "last_error": (
                {
                    key: error[key]
                    for key in ("type", "retryable", "attempt")
                    if error.get(key) is not None
                }
                if isinstance(error, dict) and error
                else None
            ),
            **timestamps,
        }
    )
    return projection
