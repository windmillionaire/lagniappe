"""Deferred-job lifecycle state and privacy-bounded projections."""

from __future__ import annotations

from typing import NotRequired, TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from lagniappe.core.entities import types as models


from datetime import datetime, UTC

from lagniappe.core.definitions import (
    DEFERRED_JOB_HEARTBEAT_SECONDS,
    DeferredJobPhase,
    DeferredJobStatus,
    DeferredJobType,
)

from .deferred_job_request import JSONValue
from .base_db import DBProperty


class JobStatus(TypedDict):
    key: str
    type: str | None
    status: str | None
    phase: str
    phase_label: str
    attempt: int
    remaining_seconds: int | None
    last_progress_at: str | None
    retry_reason: str | None
    elapsed_seconds: int
    phase_elapsed_seconds: int
    updated_at: str | None
    next_attempt_at: str | None
    revision: int
    terminal: bool
    stale: bool
    recovering: bool
    source_widget: str | None
    destination: str | None
    entity_key: str | None
    can_cancel: NotRequired[bool]
    target_key: NotRequired[str | None]
    operation_id: NotRequired[str | None]
    snapshot_revision: NotRequired[str | None]
    error: NotRequired[str]


class AdminJobStatus(JobStatus):
    actor: str
    dispatch_state: str | None
    job_version: int
    start_completed: bool
    created_at: str | None
    telemetry_id: str | None
    input_refs: dict[str, dict[str, str]]
    progress: dict[str, object]
    checkpoint_state: dict[str, object]
    delivery_state: dict[str, bool]
    last_error: dict[str, object] | None
    modified_at: str | None
    dispatched_at: str | None
    deadline_at: str | None
    lease_expires_at: str | None


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
    DeferredJobPhase.WAITING_DEPENDENCY.value: "Waiting for related work",
    DeferredJobPhase.RETRY_WAIT.value: "Waiting to retry",
    DeferredJobPhase.COMPLETE.value: "Complete",
    DeferredJobPhase.FAILED.value: "Failed",
    DeferredJobPhase.CANCELLED.value: "Cancelled",
    DeferredJobPhase.SUPERSEDED.value: "Replaced",
}


class Status(DBProperty[str]):
    _id = "status"


class StatusRevision(DBProperty[int]):
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
def datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lifecycle_normalizes_timestamps_and_elapsed_time
# @pair deferred-jobs:elapsed-time
def elapsed_seconds(start: object, now: datetime) -> int:
    start = datetime_value(start)
    return max(int((now - start).total_seconds()), 0) if start else 0


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_status_projection_is_bounded_and_marks_stale_work
# @tests tests_unit/test_023a_deferred_job_properties.py::test_dependency_status_distinguishes_form_waits_from_recovery
# @tests tests_unit/test_023a_deferred_job_properties.py::test_terminal_job_elapsed_time_stays_fixed_after_completion
# @tests tests_unit/test_023a_deferred_job_properties.py::test_active_job_elapsed_time_advances_with_the_clock
# @tests tests_unit/test_023a_deferred_job_properties.py::test_terminal_job_elapsed_time_uses_stored_fallbacks
# @matrix deferred-jobs : privacy progress stale-state status timing dependency-wait recovery
def status_projection(job: models.DeferredJob, *, now: datetime) -> JobStatus:
    progress = dict(getattr(job, "progress", None) or {})
    client = dict(getattr(job, "client", None) or {})
    phase = progress.get("phase") or getattr(job, "status", None) or "queued"
    modified = datetime_value(getattr(job, "modified", None))
    terminal = getattr(job, "status", None) in TERMINAL_STATUSES
    # Terminal progress records when execution ended; later delivery bookkeeping
    # can still advance modified. Legacy jobs fall back to their stored modified.
    elapsed_until = (
        datetime_value(progress.get("updated_at")) or modified
        if terminal
        else now
    )
    stale = bool(
        getattr(job, "status", None) in ACTIVE_STATUSES
        and modified
        and (now - modified).total_seconds() >= DEFERRED_JOB_HEARTBEAT_SECONDS * 2
    )
    error = getattr(job, "error", None) or {}
    dependency_wait = bool(
        getattr(job, "status", None) == DeferredJobStatus.RETRY_WAIT.value
        and (
            phase == DeferredJobPhase.WAITING_DEPENDENCY.value
            or error.get("type") == "DeferredJobDependencyPendingError"
        )
    )
    if dependency_wait:
        # Older jobs recorded all dependency waits as file summarization.
        phase = DeferredJobPhase.WAITING_DEPENDENCY.value
    phase_label = PHASE_LABELS.get(phase, "Working")
    if dependency_wait and getattr(job, "job_type", None) == DeferredJobType.REPORT_EXECUTION.value:
        phase_label = "Waiting for form update"
    next_attempt = datetime_value(getattr(job, "next_attempt_at", None))
    result: JobStatus = {
        "key": job.urlsafe_key,
        "type": getattr(job, "job_type", None),
        "status": getattr(job, "status", None),
        "phase": phase,
        "phase_label": phase_label,
        "attempt": int(getattr(job, "attempt", 0) or 0),
        "remaining_seconds": (
            max((120 if getattr(job, "job_type", None) == "autofill" else 600)
                - elapsed_seconds(getattr(job, "created", None), now), 0)
            if getattr(job, "job_type", None) in {"autofill", DeferredJobType.REPORT_AI.value} and not terminal
            else None
        ),
        "last_progress_at": progress.get("updated_at"),
        "retry_reason": (getattr(job, "parameters", None) or {}).get("_provider_retry_reason"),
        "elapsed_seconds": (
            elapsed_seconds(getattr(job, "created", None), elapsed_until)
            if elapsed_until else 0
        ),
        "phase_elapsed_seconds": (
            elapsed_seconds(progress.get("updated_at"), elapsed_until)
            if elapsed_until else 0
        ),
        "updated_at": modified.isoformat() if modified else None,
        "next_attempt_at": next_attempt.isoformat() if next_attempt else None,
        "revision": int(getattr(job, "status_revision", 0) or 0),
        "terminal": terminal,
        "stale": stale,
        "recovering": bool(
            stale
            or getattr(job, "dispatch_state", None) == "pending"
            or (
                getattr(job, "status", None) == DeferredJobStatus.RETRY_WAIT.value
                and not dependency_wait
            )
        ),
        "source_widget": client.get("source_widget"),
        "destination": client.get("destination"),
        "entity_key": client.get("key"),
    }
    if getattr(job, "job_type", None) == "autofill":
        result.update({
            "target_key": ((getattr(job, "inputs", None) or {}).get("target") or {}).get("id"),
            "operation_id": getattr(job, "idempotency_key", None),
            "snapshot_revision": ((getattr(job, "parameters", None) or {}).get("snapshot") or {}).get("revision"),
        })
    if result["terminal"] and error.get("message"):
        result["error"] = str(error["message"])[:500]
    return result


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_admin_projection_exposes_diagnostics_without_payload_content
# @tests tests_unit/test_023a_deferred_job_properties.py::test_terminal_job_elapsed_time_stays_fixed_after_completion
# @matrix deferred-jobs : diagnostics privacy timing
def admin_projection(job: models.DeferredJob, *, now: datetime) -> AdminJobStatus:
    """Extend owner-visible status with bounded operational diagnostics."""
    projection = status_projection(job, now=now)
    actor = getattr(job, "actor", None)
    inputs = getattr(job, "inputs", None) or {}
    input_refs = {
        str(name): {"kind": kind, "id": identifier}
        for name, value in inputs.items()
        if isinstance(value, dict)
        and isinstance(kind := value.get("kind"), str) and kind
        and isinstance(identifier := value.get("id"), str) and identifier
    }
    progress = getattr(job, "progress", None) or {}
    checkpoint = getattr(job, "checkpoint", None) or {}
    delivery = getattr(job, "delivery", None) or {}
    error = getattr(job, "error", None) or {}

    def timestamp(attribute: str) -> str | None:
        value = datetime_value(getattr(job, attribute, None))
        return value.isoformat() if value else None

    created = datetime_value(getattr(job, "created", None))
    return {
        **projection,
        "actor": (
            getattr(actor, "name", None)
            or getattr(actor, "email", None)
            or "Unknown user"
        ),
        "operation_id": getattr(job, "idempotency_key", None),
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
        "modified_at": timestamp("modified"),
        "dispatched_at": timestamp("dispatched_at"),
        "deadline_at": timestamp("deadline_at"),
        "lease_expires_at": timestamp("lease_expires"),
    }
