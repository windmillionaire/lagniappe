"""Versioned contracts for durable user-facing deferred jobs."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


DEFERRED_JOB_VERSION = 2
SUPPORTED_DEFERRED_JOB_VERSIONS = frozenset({1, DEFERRED_JOB_VERSION})
DEFERRED_JOB_PAYLOAD_LIMIT_BYTES = 750 * 1024
DEFERRED_JOB_LEASE_SECONDS = 5 * 60
DEFERRED_JOB_DISPATCH_DEADLINE_SECONDS = 30 * 60
DEFERRED_JOB_ATTEMPT_DEADLINE_SECONDS = 24 * 60
DEFERRED_JOB_HEARTBEAT_SECONDS = 60
DEFERRED_JOB_RECONCILE_GRACE_SECONDS = 2 * 60
DEFERRED_JOB_MAX_AGE_SECONDS = 3 * 60 * 60
DEFERRED_JOB_FEEDBACK_DELAY_SECONDS = 2 * 60
DEFERRED_JOB_RETRY_DELAYS = (60, 180, 600)
DEFERRED_JOB_QUOTA_RETRY_DELAYS = (60, 300)
DEFERRED_JOB_QUOTA_RETRY_JITTER_SECONDS = 30


class DeferredJobType(Enum):
    """Domain executors supported by the shared deferred-job runner."""

    REPORT_ORGANIZE = "report-organize"
    REPORT_ASK = "report-ask"
    REPORT_CREATE = "report-create"
    EMAIL_INGEST = "email-ingest"
    REPORT_EXECUTION = "report-execution"
    AUTOFILL = "autofill"
    PAGE_GENERATION = "page-generation"
    FILE_EXTRACT = "file-extract"
    FILE_SUMMARIZE = "file-summarize"


class DeferredJobStatus(Enum):
    """Persisted lifecycle states for a deferred job."""

    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class DeferredJobPhase(Enum):
    """Bounded progress phases safe to expose to the submitting actor."""

    QUEUED = "queued"
    PREPARING_INPUTS = "preparing_inputs"
    SUMMARIZING = "summarizing"
    GENERATING = "generating"
    USING_TOOLS = "using_tools"
    FINALIZING = "finalizing"
    VALIDATING = "validating"
    PREPARED = "prepared"
    APPLYING = "applying"
    RETRY_WAIT = "retry_wait"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class DeferredJobInspection(Enum):
    """Adapter observation of a prepared domain mutation."""

    APPLIED = "applied"
    NOT_APPLIED = "not-applied"
    DRIFTED = "drifted"


class DeferredJobRunState(Enum):
    """Delivery-facing outcome returned by the runner."""

    COMPLETE = "complete"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry-scheduled"
    ACTIVE = "active"


@dataclass(frozen=True)
class DeferredJobSpec:
    """Immutable input contract used to create one durable job."""

    job_type: DeferredJobType
    actor: Any
    inputs: dict[str, Any]
    parameters: dict[str, Any] = field(default_factory=dict)
    notification_body: str | None = "Working..."
    notification_target: Any = None
    client: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    delay_seconds: int = 0


# @testable infrastructure
@dataclass(frozen=True)
class DeferredJobResult:
    """Stable result returned to process routes and local dispatchers."""

    state: DeferredJobRunState
    job: Any = field(default=None, repr=False, compare=False)
    error: str | None = None

    @property
    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_checkpoints_before_apply_and_resumes_without_prepare
    # @pair deferred-jobs:delivery-result
    def success(self):
        return self.state in {
            DeferredJobRunState.COMPLETE,
            DeferredJobRunState.ACTIVE,
            DeferredJobRunState.RETRY_SCHEDULED,
        }
