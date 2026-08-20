"""Persisted fields for the shared deferred-job envelope."""

from ..mixins import RelatedEntityMixin
from .base_db import DBProperty


class Actor(RelatedEntityMixin, DBProperty):
    _id = "actor"
    _kind = "user"


class Notification(RelatedEntityMixin, DBProperty):
    _id = "notification"
    _kind = "notification"


class JSONValue(DBProperty):
    json = True
    _blank_values = (None,)


class JobType(DBProperty):
    _id = "job_type"


class Status(DBProperty):
    _id = "status"


class Version(DBProperty):
    _id = "job_version"


class IdempotencyKey(DBProperty):
    _id = "idempotency_key"


class RequestFingerprint(DBProperty):
    _id = "request_fingerprint"


class DispatchState(DBProperty):
    _id = "dispatch_state"


class TaskIdentity(DBProperty):
    _id = "task_identity"


class DispatchedAt(DBProperty):
    _id = "dispatched_at"


class DeadlineAt(DBProperty):
    _id = "deadline_at"


class StatusRevision(DBProperty):
    _id = "status_revision"


class StartCompleted(DBProperty):
    _id = "start_completed"


class TelemetryId(DBProperty):
    _id = "telemetry_id"


class Authorization(JSONValue):
    _id = "authorization"


class Inputs(JSONValue):
    _id = "inputs"


class Parameters(JSONValue):
    _id = "parameters"


class Client(JSONValue):
    _id = "client"


class Attempt(DBProperty):
    _id = "attempt"


class LeaseToken(DBProperty):
    _id = "lease_token"


class LeaseExpires(DBProperty):
    _id = "lease_expires"


class NextAttemptAt(DBProperty):
    _id = "next_attempt_at"


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
