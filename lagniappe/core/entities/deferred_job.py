"""Durable envelope for user-facing background work."""

from .entity import Entity
from ..definitions import DEFERRED_JOB_VERSION, DeferredJobStatus
from ..properties import (
    deferred_job_dispatch,
    deferred_job_lifecycle,
    deferred_job_request,
)


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_property_split_preserves_persisted_schema
# @features deferred-jobs
# @dimensions persisted-schema property-ownership json-encoding index-exclusion
class DeferredJob(Entity):
    """Internal versioned job record; domain entities remain the UI contract."""

    entity_kind = "job"

    @property
    # @testable infrastructure
    def exclude_from_index(self):
        return frozenset(
            {
                "authorization",
                "inputs",
                "parameters",
                "client",
                "progress",
                "checkpoint",
                "result",
                "error",
                "delivery",
                "idempotency_key",
                "request_fingerprint",
                "lease_token",
                "task_identity",
                "telemetry_id",
                "start_completed",
            }
        )

    @property
    # @testable infrastructure
    def to_cache(self):
        return {}

    @property
    # @testable infrastructure
    def required(self):
        return [self.actor.hash] if self.actor else []

    # @testable infrastructure
    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "actor": deferred_job_request.Actor,
                "notification": deferred_job_request.Notification,
                "job_type": deferred_job_request.JobType,
                "status": deferred_job_lifecycle.Status,
                "job_version": deferred_job_request.Version,
                "idempotency_key": deferred_job_request.IdempotencyKey,
                "request_fingerprint": deferred_job_request.RequestFingerprint,
                "dispatch_state": deferred_job_dispatch.DispatchState,
                "task_identity": deferred_job_dispatch.TaskIdentity,
                "dispatched_at": deferred_job_dispatch.DispatchedAt,
                "deadline_at": deferred_job_dispatch.DeadlineAt,
                "status_revision": deferred_job_lifecycle.StatusRevision,
                "start_completed": deferred_job_request.StartCompleted,
                "telemetry_id": deferred_job_request.TelemetryId,
                "authorization": deferred_job_request.Authorization,
                "inputs": deferred_job_request.Inputs,
                "parameters": deferred_job_request.Parameters,
                "client": deferred_job_request.Client,
                "attempt": deferred_job_dispatch.Attempt,
                "lease_token": deferred_job_dispatch.LeaseToken,
                "lease_expires": deferred_job_dispatch.LeaseExpires,
                "next_attempt_at": deferred_job_dispatch.NextAttemptAt,
                "progress": deferred_job_lifecycle.Progress,
                "checkpoint": deferred_job_lifecycle.Checkpoint,
                "result": deferred_job_lifecycle.Result,
                "error": deferred_job_lifecycle.Error,
                "delivery": deferred_job_lifecycle.Delivery,
            }
        )
        return properties

    @classmethod
    # @testable infrastructure
    def create(cls, data):
        actor = data["actor"]
        job = cls(data.get("key")) if data.get("key") else cls(parent=actor)
        job.kind = cls.entity_kind
        job.name = data.get("name") or data["job_type"]
        job.actor = actor
        job.notification = data.get("notification")
        job.job_type = data["job_type"]
        job.status = data.get("status") or DeferredJobStatus.QUEUED.value
        job.job_version = data.get("job_version") or DEFERRED_JOB_VERSION
        job.idempotency_key = data["idempotency_key"]
        job.request_fingerprint = data.get("request_fingerprint")
        job.dispatch_state = data.get("dispatch_state") or "pending"
        job.task_identity = data.get("task_identity")
        job.dispatched_at = data.get("dispatched_at")
        job.deadline_at = data.get("deadline_at")
        job.status_revision = int(data.get("status_revision") or 0)
        job.start_completed = bool(data.get("start_completed", True))
        job.telemetry_id = data.get("telemetry_id")
        job.authorization = data.get("authorization") or {}
        job.inputs = data.get("inputs") or {}
        job.parameters = data.get("parameters") or {}
        job.client = data.get("client") or {}
        job.attempt = int(data.get("attempt") or 0)
        job.progress = data.get("progress") or {}
        job.checkpoint = data.get("checkpoint") or {}
        job.result = data.get("result") or {}
        job.error = data.get("error") or {}
        job.delivery = data.get("delivery") or {}
        return job
