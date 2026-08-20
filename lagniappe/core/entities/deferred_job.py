"""Durable envelope for user-facing background work."""

from .entity import Entity
from ..definitions import DEFERRED_JOB_VERSION, DeferredJobStatus
from ..properties import deferred_job


# @testable infrastructure
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
                "actor": deferred_job.Actor,
                "notification": deferred_job.Notification,
                "job_type": deferred_job.JobType,
                "status": deferred_job.Status,
                "job_version": deferred_job.Version,
                "idempotency_key": deferred_job.IdempotencyKey,
                "request_fingerprint": deferred_job.RequestFingerprint,
                "dispatch_state": deferred_job.DispatchState,
                "task_identity": deferred_job.TaskIdentity,
                "dispatched_at": deferred_job.DispatchedAt,
                "deadline_at": deferred_job.DeadlineAt,
                "status_revision": deferred_job.StatusRevision,
                "start_completed": deferred_job.StartCompleted,
                "telemetry_id": deferred_job.TelemetryId,
                "authorization": deferred_job.Authorization,
                "inputs": deferred_job.Inputs,
                "parameters": deferred_job.Parameters,
                "client": deferred_job.Client,
                "attempt": deferred_job.Attempt,
                "lease_token": deferred_job.LeaseToken,
                "lease_expires": deferred_job.LeaseExpires,
                "next_attempt_at": deferred_job.NextAttemptAt,
                "progress": deferred_job.Progress,
                "checkpoint": deferred_job.Checkpoint,
                "result": deferred_job.Result,
                "error": deferred_job.Error,
                "delivery": deferred_job.Delivery,
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
