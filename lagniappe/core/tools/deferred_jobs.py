"""Durable orchestration for user-facing deferred work."""

from collections.abc import Callable
import hashlib
import json
import random
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from flask import current_app, url_for
from google.api_core import exceptions as google_exceptions
from google.cloud.datastore import query as datastore_query

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    DEFERRED_JOB_ATTEMPT_DEADLINE_SECONDS,
    DEFERRED_JOB_DISPATCH_DEADLINE_SECONDS,
    DEFERRED_JOB_FEEDBACK_DELAY_SECONDS,
    DEFERRED_JOB_HEARTBEAT_SECONDS,
    DEFERRED_JOB_LEASE_SECONDS,
    DEFERRED_JOB_MAX_AGE_SECONDS,
    DEFERRED_JOB_PAYLOAD_LIMIT_BYTES,
    DEFERRED_JOB_QUOTA_RETRY_DELAYS,
    DEFERRED_JOB_QUOTA_RETRY_JITTER_SECONDS,
    DEFERRED_JOB_RETRY_DELAYS,
    DEFERRED_JOB_RECONCILE_GRACE_SECONDS,
    SUPPORTED_DEFERRED_JOB_VERSIONS,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobResult,
    DeferredJobRunState,
    DeferredJobSpec,
    DeferredJobStatus,
    DeferredJobType,
    Fetch,
    PushDeliveryOutcome,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database, task_queue
from lagniappe.core.tools.database.core import DATA, KINDS


TERMINAL_STATUSES = {
    DeferredJobStatus.SUCCEEDED.value,
    DeferredJobStatus.FAILED.value,
    DeferredJobStatus.CANCELLED.value,
    DeferredJobStatus.SUPERSEDED.value,
}
ACTIVE_STATUSES = {
    DeferredJobStatus.QUEUED.value,
    DeferredJobStatus.RUNNING.value,
    DeferredJobStatus.RETRY_WAIT.value,
}
AUTOFILL_FORM_LOCK_SCOPE = "form-autofill"
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
TRANSIENT_GOOGLE_ERRORS = (
    google_exceptions.BadGateway,
    google_exceptions.DeadlineExceeded,
    google_exceptions.GatewayTimeout,
    google_exceptions.InternalServerError,
    google_exceptions.ServiceUnavailable,
    google_exceptions.TooManyRequests,
)
MODEL_BUSY_MESSAGE = "The model is too busy right now. Try again later."
MISSING_INPUT_MESSAGE = (
    "This operation stopped because the item it was working on was deleted."
)


class DeferredJobInfrastructureError(RuntimeError):
    """The delivery should be retried because orchestration could not persist."""


class DeferredJobClaimLostError(DeferredJobInfrastructureError):
    """The current worker no longer owns an existing deferred job."""


class DeferredJobDeadlineError(RuntimeError):
    """One attempt reached its bounded execution deadline."""


class DeferredJobDriftError(exceptions.ValidationError):
    """Prepared job state no longer matches the durable domain state."""


# @testable infrastructure
class DeferredJobLockedError(exceptions.ValidationError):
    """A target-scoped operation already owns the requested mutation surface."""

    def __init__(self, job):
        super().__init__("Autofill is already running for this form.")
        self.job = job


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_lock_resolution_is_target_scoped
# @pairs deferred-jobs:form-lock deferred-jobs:deterministic-key
def deferred_job_lock_key(target, scope=AUTOFILL_FORM_LOCK_SCOPE):
    """Return the deterministic lock key for one target mutation surface."""
    target_key = getattr(target, "urlsafe_key", target)
    if not target_key:
        return None
    identifier = hashlib.sha256(f"{scope}:{target_key}".encode("utf-8")).hexdigest()
    return database.create_named_key("job_lock", identifier)


# @testable false
# @covered-by lagniappe/core/tools/deferred_jobs.py::deferred_job_lock_descriptor
# @reason single-target convenience wrapper delegates to the batch resolver
def active_deferred_job_lock(target, scope=AUTOFILL_FORM_LOCK_SCOPE):
    """Return ``(lock, job)`` while the target's referenced job is active."""
    target_key = getattr(target, "urlsafe_key", target)
    return deferred_job_lock_descriptors([target], scope=scope).get(
        target_key,
        None,
    )


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_lock_resolution_is_target_scoped
# @pairs deferred-jobs:form-lock deferred-jobs:stale-cleanup
def deferred_job_lock_descriptors(targets, scope=AUTOFILL_FORM_LOCK_SCOPE):
    """Batch-resolve active locks keyed by target urlsafe key."""
    targets = [target for target in targets or () if target]
    target_keys = [getattr(target, "urlsafe_key", target) for target in targets]
    lock_keys = [deferred_job_lock_key(target, scope) for target in targets]
    locks = {
        lock.target: lock
        for lock in Entities.fetch(*lock_keys, request=Fetch.direct())
        if isinstance(lock, Entities.DEFERRED_JOB_LOCK) and lock.operation
    }
    jobs = {
        job.urlsafe_key: job
        for job in Entities.fetch(
            *(lock.operation for lock in locks.values()),
            request=Fetch.direct(),
        )
        if isinstance(job, Entities.DEFERRED_JOB)
    }
    active = {}
    for target_key in target_keys:
        lock = locks.get(target_key)
        job = jobs.get(lock.operation) if lock else None
        if lock and job and job.status in ACTIVE_STATUSES:
            active[target_key] = (lock, job)
        elif lock:
            database.release_deferred_job_lock(lock.key, lock.operation)
    return active


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_lock_descriptor_is_browser_safe
# @pairs deferred-jobs:form-lock deferred-jobs:browser-projection
def deferred_job_lock_descriptor(target, scope=AUTOFILL_FORM_LOCK_SCOPE):
    """Return the browser-safe active-operation descriptor for ``target``."""
    active = active_deferred_job_lock(target, scope)
    if active is None:
        return None
    lock, job = active
    return {
        "locked": True,
        "scope": lock.scope,
        "operation": job.urlsafe_key,
        "revision": int(job.status_revision or 0),
    }


# @testable infrastructure
@dataclass
class DeferredJobContext:
    job: object
    actor: object
    notification: object | None
    inputs: dict
    parameters: dict
    checkpoint: dict
    active_check: Callable[[], bool] | None = None
    execution_control: object | None = None
    checkpoint_callback: Callable[..., None] | None = None

    # @testable infrastructure
    def input(self, name, default=None):
        return self.inputs.get(name, default)

    # @testable infrastructure
    def ensure_active(self):
        """Stop domain writes after cancellation or lease replacement."""
        if self.execution_control is not None:
            self.execution_control.ensure_active()
            return
        if self.active_check is not None and not self.active_check():
            raise DeferredJobClaimLostError("Deferred job was cancelled or superseded.")

    def set_phase(self, phase, **details):
        """Persist a bounded user-visible phase for this claimed job."""
        if self.execution_control is not None:
            self.execution_control.set_phase(phase, **details)

    def checkpoint_stage(self, stage, payload=None, **progress):
        """Persist a resumable adapter-owned preparation checkpoint."""
        self.ensure_active()
        checkpoint = {
            "schema_version": 1,
            "stage": str(getattr(stage, "value", stage)),
            **_json_copy(payload or {}),
        }
        if self.checkpoint_callback is not None:
            self.checkpoint_callback(checkpoint, progress=progress)
        self.checkpoint = checkpoint
        return checkpoint


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_execution_control_renews_and_observes_lost_claim
# @features deferred-jobs
# @dimensions heartbeat deadline cancellation progress provider-boundary tool-boundary
class DeferredExecutionControl:
    """Lease, deadline, cancellation, and coarse progress for one attempt."""

    _PROVIDER_PHASES = {
        "initial": DeferredJobPhase.GENERATING,
        "tool": DeferredJobPhase.USING_TOOLS,
        "structured_final": DeferredJobPhase.FINALIZING,
    }

    def __init__(self, *, deadline_at, active_check, progress_callback):
        self.deadline_at = deadline_at
        self._active_check = active_check
        self._progress_callback = progress_callback
        self._phase = None
        self._details = {}
        self._lost = False
        self._background_error = None

    @property
    def remaining_seconds(self):
        return max((self.deadline_at - _utc()).total_seconds(), 0)

    def mark_lost(self):
        self._lost = True

    def mark_background_error(self, error):
        self._background_error = error

    def ensure_active(self):
        if self._background_error is not None:
            raise DeferredJobInfrastructureError(
                "Deferred job heartbeat failed."
            ) from self._background_error
        if self._lost or not self._active_check():
            self._lost = True
            raise DeferredJobClaimLostError("Deferred job was cancelled or superseded.")
        if _utc() >= self.deadline_at:
            raise DeferredJobDeadlineError(
                "Deferred AI attempt reached its execution deadline."
            )

    def set_phase(self, phase, **details):
        phase = str(getattr(phase, "value", phase))
        bounded = {
            key: value
            for key, value in details.items()
            if key in {"completed", "total", "provider_stage"}
            and isinstance(value, (str, int))
        }
        if phase == self._phase and bounded == self._details:
            self.ensure_active()
            return
        self.ensure_active()
        self._progress_callback(
            {
                "phase": phase,
                **bounded,
                "updated_at": _utc().isoformat(),
            }
        )
        self._phase = phase
        self._details = bounded

    def before_provider(self, stage):
        self.set_phase(
            self._PROVIDER_PHASES.get(stage, DeferredJobPhase.GENERATING),
            provider_stage=stage,
        )

    def after_provider(self, _stage):
        self.ensure_active()

    def before_tool(self, _name):
        self.set_phase(DeferredJobPhase.USING_TOOLS)

    def after_tool(self, _name):
        self.ensure_active()


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_execution_control_renews_and_observes_lost_claim
# @features deferred-jobs
# @dimensions heartbeat blocking-provider lease-loss
class _DeferredLeaseGuard:
    """Renew a claim while a blocking provider request owns the worker."""

    def __init__(self, registry, job, lease_token, control):
        self.registry = registry
        self.job = job
        self.lease_token = lease_token
        self.control = control
        self.stop_event = threading.Event()
        self.thread = None

    def __enter__(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1)

    def _run(self):
        while not self.stop_event.wait(DEFERRED_JOB_HEARTBEAT_SECONDS):
            if _utc() >= self.control.deadline_at:
                return
            try:
                if not self.registry._renew_claim(self.job, self.lease_token):
                    self.control.mark_lost()
                    return
            except Exception as error:
                self.control.mark_background_error(error)
                return


# @testable infrastructure
class DeferredJobAdapter:
    """Domain boundary plugged into the shared job lifecycle."""

    job_type = None
    synchronous_testing = False
    requires_ai = False
    mutation_inputs = ()
    queued_message = "Working..."
    retry_message = "Work is temporarily delayed; retrying shortly..."
    active_message = (
        "Still working. This is taking longer than usual; we'll keep trying."
    )
    success_message = "Work is ready."
    failure_prefix = "Work failed."
    completion_notification_only = False

    # @testable infrastructure
    def authorization(self, spec):
        authorization = {
            "policy": self.job_type.value,
            "actor": spec.actor.urlsafe_key,
            "inputs": _serialize_inputs(spec.inputs),
        }
        fingerprints = {
            name: getattr(spec.inputs.get(name), "fingerprint", None)
            for name in self.mutation_inputs
            if spec.inputs.get(name) is not None
        }
        if fingerprints:
            authorization["fingerprints"] = fingerprints
        return authorization

    # @testable infrastructure
    def load(self, context):
        context.inputs = {
            name: _load_reference(reference)
            for name, reference in context.inputs.items()
        }
        return context

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_registered_ai_adapters_reject_restricted_actor_before_prepare
    # @pair deferred-jobs:authorization
    # @pair ai:authorization
    # @pair ai:restriction-gate
    # @pair ai:provider-boundary
    def authorize(self, context):
        if (
            self.requires_ai
            and not context.actor.properties.restrictions.can_use_ai_tools
        ):
            raise exceptions.ValidationError("This user cannot use AI tools.")

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_runner_rejects_changed_target_fingerprint_before_apply
    # @pair deferred-jobs:target-fingerprint
    # @pair deferred-jobs:no-apply
    def validate_apply(self, context):
        """Reject generated output when an apply target changed in the queue."""
        expected = (context.job.authorization or {}).get("fingerprints") or {}
        for name in self.mutation_inputs:
            target = context.input(name)
            if target is None:
                continue
            if expected.get(name) != getattr(target, "fingerprint", None):
                raise DeferredJobDriftError(
                    "The target changed while this operation was running."
                )

    # @testable infrastructure
    def prepare(self, context):
        return {}

    def checkpoint_ready(self, context):
        """Return whether preparation has produced its final apply checkpoint."""
        return bool(context.checkpoint)

    # @testable infrastructure
    def started(self, context):
        """Persist domain metadata after the job exists and before dispatch."""
        return None

    # @testable infrastructure
    def start_lock(self, spec, job):
        """Return an optional target-scoped lock created with the job."""
        return None

    # @testable infrastructure
    def can_view_status(self, job, actor):
        """Authorize a non-owner for the bounded browser status projection."""
        return False

    # @testable infrastructure
    def inspect(self, context):
        return DeferredJobInspection.NOT_APPLIED

    # @testable infrastructure
    def apply(self, context):
        raise NotImplementedError

    # @testable infrastructure
    def cleanup(self, context, *, terminal):
        return None

    # @testable infrastructure
    def failure(self, context, error):
        return None

    # @testable infrastructure
    def event(self, context):
        client = context.job.client or {}
        if not client.get("source_widget") and not client.get("destination"):
            return None
        event = {
            "type": "deferred-complete",
            "source_widget": client.get("source_widget"),
            "destination": client.get("destination"),
            "operation": context.job.urlsafe_key,
            "revision": int(getattr(context.job, "status_revision", 0) or 0),
        }
        if client.get("key"):
            event["key"] = client["key"]
        return event

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        if succeeded:
            return self.success_message
        message = str(error or "").strip()
        return f"{self.failure_prefix} {message}".strip()

    # @testable infrastructure
    def notification_target(self, context):
        return None


# @testable infrastructure
class DeferredJobRegistry:
    """Create, dispatch, claim, recover, and publish durable jobs."""

    def __init__(self):
        self._adapters = {}
        self._defaults_loaded = False

    # @testable infrastructure
    def register(self, adapter):
        if not isinstance(adapter, DeferredJobAdapter) or adapter.job_type is None:
            raise TypeError("Deferred job adapters require a job_type")
        self._adapters[adapter.job_type] = adapter
        return adapter

    # @testable infrastructure
    def adapter(self, job_type):
        self._load_default_adapters()
        if not isinstance(job_type, DeferredJobType):
            job_type = DeferredJobType(job_type)
        adapter = self._adapters.get(job_type)
        if adapter is None:
            raise exceptions.ValidationError(
                f"Unsupported deferred job type: {job_type.value}"
            )
        return adapter

    # @testable infrastructure
    def _load_default_adapters(self):
        if self._defaults_loaded:
            return
        self._defaults_loaded = True
        from .deferred_job_adapters import register_adapters

        register_adapters(self)

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_deferred_job_create_is_transactionally_idempotent
    # @tests tests_unit/test_023_deferred_jobs.py::test_start_rejects_operation_id_reuse_for_different_request
    # @tests tests_unit/test_023_deferred_jobs.py::test_start_retains_site_export_intent_after_provider_enqueue_failure
    # @tests tests_unit/test_023_deferred_jobs.py::test_start_dispatch_marker_does_not_overwrite_a_fast_worker
    # @pair deferred-jobs:transactional-start
    # @pair deferred-jobs:start
    # @pair deferred-jobs:operation-fingerprint
    # @pair deferred-jobs:mismatch
    # @pair deferred-jobs:transient-dispatch
    # @pair deferred-jobs:dispatch-worker-race
    # @pair deferred-jobs:compare-and-set
    # @pair deferred-jobs:no-apply
    # @pair export:intent-preservation
    # @pair notifications:pending-state
    def start(self, spec):
        if not isinstance(spec, DeferredJobSpec):
            raise TypeError("DeferredJobs.start requires a DeferredJobSpec")
        adapter = self.adapter(spec.job_type)
        inputs = _serialize_inputs(spec.inputs)
        parameters = _json_copy(spec.parameters)
        client = _json_copy(spec.client)
        if bool(client.get("source_widget")) != bool(client.get("destination")):
            raise exceptions.ValidationError(
                "Deferred completion routing requires both a source and destination."
            )
        authorization = adapter.authorization(spec)
        request_fingerprint = _request_fingerprint(
            job_type=spec.job_type.value,
            actor=spec.actor.urlsafe_key,
            authorization=authorization,
            inputs=inputs,
            parameters=parameters,
            client=client,
        )
        _validate_payload(
            authorization=authorization,
            inputs=inputs,
            parameters=parameters,
            client=client,
        )

        idempotency_key = str(
            spec.idempotency_key or _new_idempotency_key(spec)
        ).strip()
        if not idempotency_key or len(idempotency_key) > 200:
            raise exceptions.ValidationError(
                "Deferred operation identifier is invalid."
            )
        storage_id = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        job_key = database.create_named_key("job", storage_id, spec.actor)
        existing = Entities.fetch_one(job_key, request=Fetch.direct())
        if existing is not None:
            if (
                getattr(existing, "request_fingerprint", None)
                and getattr(existing, "request_fingerprint", None)
                != request_fingerprint
            ):
                raise exceptions.ValidationError(
                    "Deferred operation identifier was reused for a different request."
                )
            return existing, existing.notification

        notification = None
        if not adapter.completion_notification_only:
            notification = Entities.NOTIFICATION.create(
                {
                    "parent": spec.actor,
                    "target": spec.notification_target,
                    "body": spec.notification_body or adapter.queued_message,
                    "pending": True,
                }
            )
        job = Entities.DEFERRED_JOB.create(
            {
                "key": job_key,
                "actor": spec.actor,
                "notification": notification,
                "name": spec.job_type.value,
                "job_type": spec.job_type.value,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "dispatch_state": "pending",
                "status_revision": 1,
                "start_completed": False,
                "telemetry_id": str(uuid.uuid4()),
                "authorization": authorization,
                "inputs": inputs,
                "parameters": parameters,
                "client": client,
                "progress": {
                    "phase": DeferredJobPhase.QUEUED.value,
                    "updated_at": _utc().isoformat(),
                },
            }
        )
        lock = adapter.start_lock(spec, job)
        creation = database.create_deferred_job_if_absent(job, notification, lock)
        if not creation.get("created"):
            raw = creation.get("entity")
            existing = Entities.DEFERRED_JOB(raw) if raw is not None else None
            existing = (
                Entities.fetch_one(existing, request=Fetch.direct())
                if existing is not None
                else None
            )
            if existing is None:
                raise DeferredJobInfrastructureError(
                    "Deferred operation could not be created."
                )
            if creation.get("reason") == "locked":
                raise DeferredJobLockedError(existing)
            if (
                getattr(existing, "request_fingerprint", None)
                and getattr(existing, "request_fingerprint", None)
                != request_fingerprint
            ):
                raise exceptions.ValidationError(
                    "Deferred operation identifier was reused for a different request."
                )
            return existing, existing.notification
        Entities.save(*[entity for entity in (job, notification, spec.actor) if entity])

        context = DeferredJobContext(
            job=job,
            actor=spec.actor,
            notification=notification,
            inputs=spec.inputs,
            parameters=parameters,
            checkpoint={},
        )

        try:
            adapter.started(context)
            job.start_completed = True
            job.status_revision = int(job.status_revision or 0) + 1
            Entities.save(job)
        except Exception as error:
            adapter.failure(context, error)
            adapter.cleanup(context, terminal=True)
            job.status = DeferredJobStatus.FAILED.value
            job.dispatch_state = "failed"
            job.client = {
                key: value
                for key, value in (job.client or {}).items()
                if key != "token"
            }
            job.error = _error_record(error, retryable=False, attempt=0)
            job.progress = {
                "phase": DeferredJobPhase.FAILED.value,
                "updated_at": _utc().isoformat(),
            }
            if notification is not None:
                notification.body = adapter.terminal_message(
                    context,
                    succeeded=False,
                    error="The operation could not be initialized.",
                )
                notification.pending = False
            Entities.save(
                *[entity for entity in (job, notification, spec.actor) if entity]
            )
            raise

        dispatch_revision = int(job.status_revision or 0) + 1
        dispatch_started_at = _utc()
        job.dispatch_state = "dispatching"
        job.dispatched_at = dispatch_started_at
        job.status_revision = dispatch_revision
        Entities.save(job)

        dispatch_accepted = False
        try:
            task_identity = self.dispatch(
                job,
                attempt=1,
                delay_seconds=spec.delay_seconds,
            )
            if isinstance(task_identity, DeferredJobResult):
                current = Entities.fetch_one(job.key, request=Fetch.direct())
                job = current or task_identity.job or job
                notification = getattr(job, "notification", notification)
            else:
                updated = database.update_deferred_job_recovery_dispatch(
                    job.key,
                    dispatch_revision,
                    {
                        "dispatch_state": "dispatched",
                        "task_identity": task_identity,
                    },
                    _utc(),
                )
                if updated:
                    job.dispatch_state = "dispatched"
                    job.task_identity = task_identity
                else:
                    current = Entities.fetch_one(job.key, request=Fetch.direct())
                    if current is None:
                        raise DeferredJobInfrastructureError(
                            "Deferred operation disappeared during dispatch."
                        )
                    job = current
                    notification = getattr(job, "notification", notification)
            dispatch_accepted = True
        except Exception as error:
            error_record = _error_record(error, retryable=True, attempt=0)
            dispatch_pending = database.update_deferred_job_recovery_dispatch(
                job.key,
                dispatch_revision,
                {
                    "dispatch_state": "pending",
                    "dispatched_at": None,
                    "task_identity": None,
                    "error": json.dumps(error_record),
                },
                _utc(),
            )
            if dispatch_pending:
                job.dispatch_state = "pending"
                job.dispatched_at = None
                job.task_identity = None
                job.error = error_record
            else:
                current = Entities.fetch_one(job.key, request=Fetch.direct())
                if current is None:
                    raise
                job = current
                notification = getattr(job, "notification", notification)
                dispatch_accepted = True
            exceptions.capture(
                error,
                context={
                    "deferred_job": {
                        "id": job.urlsafe_key,
                        "type": job.job_type,
                        "operation": "initial_dispatch",
                    }
                },
                level="warning",
            )
            if (
                dispatch_pending
                and CONFIG.production
                and not getattr(
                    CONFIG,
                    "TASK_QUEUE_ENABLED",
                    CONFIG.production,
                )
            ):
                terminal_error = DeferredJobInfrastructureError(
                    "Background processing is unavailable."
                )
                adapter.failure(context, terminal_error)
                adapter.cleanup(context, terminal=True)
                job.status = DeferredJobStatus.FAILED.value
                job.dispatch_state = "failed"
                job.client = {
                    key: value
                    for key, value in (job.client or {}).items()
                    if key != "token"
                }
                job.error = _error_record(
                    terminal_error,
                    retryable=False,
                    attempt=0,
                )
                job.progress = {
                    "phase": DeferredJobPhase.FAILED.value,
                    "updated_at": _utc().isoformat(),
                }
                if notification is not None:
                    notification.body = adapter.terminal_message(
                        context,
                        succeeded=False,
                        error=terminal_error,
                    )
                    notification.pending = False
                Entities.save(
                    *[entity for entity in (job, notification, spec.actor) if entity]
                )
                raise

        try:
            self.dispatch_feedback(job)
        except Exception as error:
            exceptions.capture(
                error,
                context={
                    "deferred_job": {
                        "id": job.urlsafe_key,
                        "type": job.job_type,
                        "operation": "schedule_feedback",
                    }
                },
                level="warning",
            )

        if (
            dispatch_accepted
            and job.status in ACTIVE_STATUSES
            and notification is not None
            and notification.pending
        ):
            try:
                _send_notification(notification, client.get("token"))
            except DeferredJobInfrastructureError as error:
                exceptions.capture(
                    error,
                    context={
                        "deferred_job": {
                            "id": job.urlsafe_key,
                            "type": job.job_type,
                            "operation": "initial_notification",
                        }
                    },
                    level="warning",
                )
        return job, notification

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_cancel_deletes_tasks_and_persists_a_tombstone
    # @features deferred-jobs
    # @dimensions cancellation deterministic-task-id
    def cancel(
        self,
        job,
        *,
        status=DeferredJobStatus.CANCELLED,
        message="Operation cancelled.",
    ):
        """Tombstone work durably so an already-running delivery loses its lease."""
        if isinstance(job, dict):
            job = job.get("key")
        if isinstance(job, str):
            job = Entities.fetch_one(job, request=Fetch.direct())
        if job is None:
            return False

        if job.status in TERMINAL_STATUSES:
            return True
        if not isinstance(status, DeferredJobStatus):
            status = DeferredJobStatus(status)
        if status not in {
            DeferredJobStatus.CANCELLED,
            DeferredJobStatus.SUPERSEDED,
        }:
            raise ValueError("Active work can only be cancelled or superseded.")
        now = _utc()
        public_client = {
            key: value for key, value in (job.client or {}).items() if key != "token"
        }
        task_identity = getattr(job, "task_identity", None)
        if not task_identity and job.status in {
            DeferredJobStatus.QUEUED.value,
            DeferredJobStatus.RETRY_WAIT.value,
        }:
            attempt = (
                1
                if job.status == DeferredJobStatus.QUEUED.value
                else int(job.attempt or 0) + 1
            )
            task_identity = task_queue.task_name(_task_id(job, attempt))
        transition = database.transition_active_deferred_job(
            job.key,
            {
                "status": status.value,
                "dispatch_state": status.value,
                "lease_token": None,
                "lease_expires": None,
                "next_attempt_at": None,
                "deadline_at": None,
                "client": json.dumps(public_client),
                "progress": json.dumps(
                    {
                        "phase": status.value,
                        "updated_at": now.isoformat(),
                    }
                ),
            },
            now,
        )
        if not transition.get("transitioned"):
            return transition.get("reason") == "terminal"
        job = Entities.DEFERRED_JOB(transition["entity"])
        job = Entities.fetch_one(job, request=Fetch.direct()) or job
        if task_identity:
            task_queue.delete_task(task_identity)
        task_queue.delete_task(task_queue.task_name(_feedback_task_id(job)))
        adapter = self.adapter(job.job_type)
        context = self._context(job)
        try:
            context = adapter.load(context)
            adapter.cleanup(context, terminal=True)
        except Exception as error:
            exceptions.capture(
                error,
                context={
                    "deferred_job": {
                        "id": job.urlsafe_key,
                        "operation": "cancel_cleanup",
                    }
                },
                level="warning",
            )
        notification = getattr(job, "notification", None)
        if notification is not None:
            notification.body = message
            notification.pending = False
        Entities.save(*[entity for entity in (job, notification) if entity])
        return True

    def supersede(self, job):
        """Replace active work while retaining a terminal operation record."""
        return self.cancel(
            job,
            status=DeferredJobStatus.SUPERSEDED,
            message="Operation replaced by a newer request.",
        )

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_production_dispatch_rejects_disabled_task_queue
    # @pair deferred-jobs:dispatch
    # @pair deferred-jobs:disabled-queue
    # @pair deferred-jobs:task-identity
    def dispatch(self, job, *, attempt, delay_seconds=0, task_suffix=None):
        adapter = self.adapter(job.job_type)
        if CONFIG.production:
            endpoint = url_for("process.deferred_job_process", _external=True)
            task_identity = task_queue.create_task(
                endpoint,
                {"job_key": job.urlsafe_key},
                delay_seconds,
                task_id=_task_id(job, attempt, suffix=task_suffix),
                dispatch_deadline_seconds=DEFERRED_JOB_DISPATCH_DEADLINE_SECONDS,
            )
            if not task_identity:
                raise DeferredJobInfrastructureError(
                    "Deferred job dispatch did not return a task identity."
                )
            return task_identity
        if CONFIG.testing and adapter.synchronous_testing:
            return self.run(job.urlsafe_key)
        if CONFIG.development:
            app = current_app._get_current_object()

            def run_local():
                with app.app_context():
                    self.run(job.urlsafe_key)

            if delay_seconds:
                timer = threading.Timer(delay_seconds, run_local)
                timer.daemon = True
                timer.start()
                return None
            threading.Thread(target=run_local, daemon=True).start()
        return None

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_long_running_feedback_dispatch_is_delayed_and_deterministic
    # @features deferred-jobs notifications
    # @dimensions long-running feedback scheduling
    def dispatch_feedback(self, job):
        """Schedule a bounded user-facing update for unusually long work."""
        if (
            not CONFIG.production
            or job.notification is None
            or job.status not in ACTIVE_STATUSES
        ):
            return None
        endpoint = url_for("process.deferred_job_feedback", _external=True)
        return task_queue.create_task(
            endpoint,
            {"job_key": job.urlsafe_key},
            DEFERRED_JOB_FEEDBACK_DELAY_SECONDS,
            task_id=_feedback_task_id(job),
        )

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_long_running_feedback_updates_pending_notification
    # @features deferred-jobs notifications
    # @dimensions long-running feedback terminal-safety
    def feedback(self, job_key):
        """Publish a progress message when a job remains queued or running."""
        job = Entities.fetch_one(job_key, request=Fetch.direct())
        if (
            job is None
            or job.status
            not in {
                DeferredJobStatus.QUEUED.value,
                DeferredJobStatus.RUNNING.value,
            }
            or job.notification is None
        ):
            return False

        adapter = self.adapter(job.job_type)
        notification = job.notification
        notification.body = adapter.active_message
        notification.pending = True
        Entities.save(notification, job.actor)
        _send_notification(notification, (job.client or {}).get("token"))
        return True

    # @testable true
    # @tests tests_e2e/002_home/test_002o_deferred_jobs.py::test_deferred_status_is_owner_safe_and_batched
    # @features deferred-jobs
    # @dimensions status owner batch progress timing
    def statuses(self, job_keys, actor, *, now=None):
        """Project a bounded owner-safe status list for browser reconciliation."""
        actor_key = getattr(actor, "urlsafe_key", None)
        keys = list(dict.fromkeys(str(key) for key in (job_keys or ()) if key))
        if len(keys) > 50:
            raise exceptions.ValidationError(
                "At most 50 deferred operations can be checked at once."
            )
        statuses = []
        for job in Entities.fetch(*keys, request=Fetch.direct()):
            if not isinstance(job, Entities.DEFERRED_JOB):
                continue
            owner_key = getattr(getattr(job, "actor", None), "urlsafe_key", None)
            owner = bool(actor_key and owner_key == actor_key)
            if not owner and not self.adapter(job.job_type).can_view_status(job, actor):
                continue
            projection = _status_projection(job, now=_utc(now))
            if not owner:
                projection.pop("error", None)
            statuses.append(projection)
        return statuses

    # @testable infrastructure
    def recent(self, *, limit=100, now=None):
        """Return privacy-bounded operation rows for the owner dashboard."""
        query = DATA.datastore.query(kind=KINDS.jobs.value)
        query.order = ["-modified"]
        records = list(query.fetch(limit=min(max(int(limit), 1), 250)))
        jobs = [Entities.DEFERRED_JOB(record) for record in records]
        jobs = Entities.fetch(*jobs, request=Fetch.direct())
        return [_admin_projection(job, now=_utc(now)) for job in jobs]

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_delete_terminal_jobs_preserves_active_and_incomplete_delivery
    # @pair deferred-jobs:retention
    # @pair deferred-jobs:terminal-delivery
    def delete_terminal(self, *, before=None, batch_size=500):
        """Delete retained terminal jobs without interrupting unfinished work."""
        before = _utc(before) if before is not None else None
        batch_size = max(int(batch_size), 1)
        query = DATA.datastore.query(kind=KINDS.jobs.value)
        if before is not None:
            query.add_filter(
                filter=datastore_query.PropertyFilter("created", "<", before)
            )
            query.order = ["created"]

        deleted = 0
        keys = []
        for record in query.fetch():
            created = _datetime(record.get("created"))
            if before is not None and (created is None or created >= before):
                continue
            if record.get("status") not in TERMINAL_STATUSES:
                continue
            if record.get("dispatch_state") == "delivery_pending":
                continue

            keys.append(record.key)
            if len(keys) < batch_size:
                continue
            DATA.datastore.delete_multi(keys)
            deleted += len(keys)
            keys = []

        if keys:
            DATA.datastore.delete_multi(keys)
            deleted += len(keys)
        return deleted

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_reconciler_redispatches_one_cas_claimed_stale_job
    # @tests tests_unit/test_023_deferred_jobs.py::test_reconciler_resumes_stale_terminal_delivery_after_grace
    # @tests tests_unit/test_023_deferred_jobs.py::test_reconciler_completes_terminal_delivery_when_input_was_deleted
    # @pair deferred-jobs:reconciliation
    # @pair deferred-jobs:redispatch
    # @pair deferred-jobs:compare-and-set
    # @pair deferred-jobs:deterministic-task-id
    # @pair deferred-jobs:terminal-delivery
    # @pair deferred-jobs:grace
    # @pair deferred-jobs:orphaned-input
    # @pair notifications:terminal-delivery
    def reconcile(self, *, now=None, limit=250):
        """Redispatch stranded work and bound the age of every operation."""
        now = _utc(now)
        jobs = self._reconcile_candidates(limit=limit)
        result = {
            "examined": len(jobs),
            "redispatched": 0,
            "failed": 0,
            "delivered": 0,
            "errors": 0,
        }
        for job in jobs:
            try:
                if (
                    job.status in TERMINAL_STATUSES
                    and getattr(job, "dispatch_state", None) == "delivery_pending"
                ):
                    modified = _datetime(getattr(job, "modified", None))
                    if (
                        modified
                        and modified
                        + timedelta(seconds=DEFERRED_JOB_RECONCILE_GRACE_SECONDS)
                        > now
                    ):
                        continue
                    self._finish_stale_delivery(job)
                    result["delivered"] += 1
                    continue

                error = exceptions.AIException(
                    "This operation could not finish after automatic recovery. "
                    "Try again."
                )
                claim = database.claim_deferred_job_recovery(
                    job.key,
                    int(getattr(job, "status_revision", 0) or 0),
                    now,
                    grace_seconds=DEFERRED_JOB_RECONCILE_GRACE_SECONDS,
                    max_age_seconds=DEFERRED_JOB_MAX_AGE_SECONDS,
                    stale_updates={
                        "status": DeferredJobStatus.FAILED.value,
                        "dispatch_state": "delivery_pending",
                        "lease_token": None,
                        "lease_expires": None,
                        "deadline_at": None,
                        "next_attempt_at": None,
                        "error": json.dumps(
                            _error_record(
                                error,
                                retryable=False,
                                attempt=getattr(job, "attempt", 0),
                            )
                        ),
                        "progress": json.dumps(
                            {
                                "phase": DeferredJobPhase.FAILED.value,
                                "updated_at": now.isoformat(),
                            }
                        ),
                        "delivery": json.dumps(
                            {
                                "failure": False,
                                "cleanup": False,
                                "notification": False,
                                "event": False,
                            }
                        ),
                    },
                )
                if not claim.get("claimed"):
                    continue
                job = Entities.DEFERRED_JOB(claim["entity"])
                job = Entities.fetch_one(job, request=Fetch.direct()) or job
                if claim.get("action") == "failed":
                    self._finish_stale_delivery(job, error=error)
                    result["failed"] += 1
                    continue

                revision = int(getattr(job, "status_revision", 0) or 0)
                attempt = max(int(getattr(job, "attempt", 0) or 0) + 1, 1)
                try:
                    identity = self.dispatch(
                        job,
                        attempt=attempt,
                        task_suffix=f"reconcile-{revision}",
                    )
                except Exception:
                    database.update_deferred_job_recovery_dispatch(
                        job.key,
                        revision,
                        {"dispatch_state": "pending", "dispatched_at": None},
                        now,
                    )
                    raise
                database.update_deferred_job_recovery_dispatch(
                    job.key,
                    revision,
                    {
                        "dispatch_state": "dispatched",
                        "task_identity": identity,
                    },
                    now,
                )
                result["redispatched"] += 1
            except Exception as error:
                result["errors"] += 1
                exceptions.capture(
                    error,
                    context={
                        "deferred_job": {
                            "id": getattr(job, "urlsafe_key", None),
                            "operation": "reconcile",
                        }
                    },
                    level="warning",
                )
        return result

    def _reconcile_candidates(self, *, limit):
        records = []
        per_status = max(int(limit) // len(ACTIVE_STATUSES), 1)
        for status in ACTIVE_STATUSES:
            query = DATA.datastore.query(kind=KINDS.jobs.value)
            query.add_filter(
                filter=datastore_query.PropertyFilter("status", "=", status)
            )
            query.order = ["modified"]
            records.extend(query.fetch(limit=per_status))
        delivery_query = DATA.datastore.query(kind=KINDS.jobs.value)
        delivery_query.add_filter(
            filter=datastore_query.PropertyFilter(
                "dispatch_state",
                "=",
                "delivery_pending",
            )
        )
        delivery_query.order = ["modified"]
        records.extend(delivery_query.fetch(limit=per_status))
        records = list({record.key: record for record in records}.values())
        records.sort(key=lambda record: _datetime(record.get("modified")) or _utc())
        jobs = [Entities.DEFERRED_JOB(record) for record in records[: int(limit)]]
        return Entities.fetch(*jobs, request=Fetch.direct())

    def _finish_stale_delivery(self, job, *, error=None):
        error = error or exceptions.AIException(
            (job.error or {}).get("message")
            or "This operation could not finish after automatic recovery. Try again."
        )
        adapter = self.adapter(job.job_type)
        context = self._context(job)
        inputs_available = True
        try:
            context = adapter.load(context)
        except exceptions.ValidationError:
            inputs_available = False
        delivery = dict(job.delivery or {})
        delivery_changed = False
        if not inputs_available and not delivery.get("input_missing"):
            delivery["input_missing"] = True
            delivery_changed = True
        if job.status == DeferredJobStatus.FAILED.value and not delivery.get("failure"):
            if inputs_available:
                adapter.failure(context, error)
            delivery["failure"] = True
            delivery_changed = True
        if delivery_changed:
            self._save_terminal_fields(job, delivery=delivery)
        self._finish_terminal_delivery(
            job,
            adapter,
            context=context,
            error=error,
            inputs_available=inputs_available,
        )
        self._release(job, getattr(job, "lease_token", None))

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_runner_checkpoints_before_apply_and_resumes_without_prepare
    # @tests tests_unit/test_023_deferred_jobs.py::test_runner_classifies_wrapped_transient_errors_and_schedules_retry
    # @tests tests_unit/test_023_deferred_jobs.py::test_runner_treats_deleted_active_job_as_cancellation
    # @tests tests_unit/test_023_deferred_jobs.py::test_runner_supplies_bounded_ai_observability_context_during_prepare
    # @features deferred-jobs
    # @dimensions checkpoint recovery retry cancellation
    def run(self, job_key, *, now=None):
        now = _utc(now)
        lease_token = uuid.uuid4().hex
        claim = database.claim_deferred_job(
            job_key,
            lease_token,
            now + timedelta(seconds=DEFERRED_JOB_LEASE_SECONDS),
            now,
        )
        raw = claim.get("entity")
        if raw is None:
            return DeferredJobResult(
                DeferredJobRunState.FAILED,
                error="Deferred job not found.",
            )

        job = Entities.DEFERRED_JOB(raw)
        job = Entities.fetch_one(job, request=Fetch.direct()) or job
        adapter = self.adapter(job.job_type)
        if not claim.get("claimed"):
            if claim.get("reason") == "terminal":
                if job.status in {
                    DeferredJobStatus.SUCCEEDED.value,
                    DeferredJobStatus.FAILED.value,
                }:
                    self._finish_terminal_delivery(job, adapter)
                    self._release(job, getattr(job, "lease_token", None))
                state = (
                    DeferredJobRunState.COMPLETE
                    if job.status == DeferredJobStatus.SUCCEEDED.value
                    else DeferredJobRunState.FAILED
                )
                return DeferredJobResult(state, job=job)
            return DeferredJobResult(DeferredJobRunState.ACTIVE, job=job)

        deadline_at = now + timedelta(seconds=DEFERRED_JOB_ATTEMPT_DEADLINE_SECONDS)
        self._persist_claimed(
            job,
            lease_token,
            dispatch_state="claimed",
            deadline_at=deadline_at,
            progress={
                "phase": DeferredJobPhase.PREPARING_INPUTS.value,
                "updated_at": now.isoformat(),
            },
        )
        control = DeferredExecutionControl(
            deadline_at=deadline_at,
            active_check=lambda: self._claim_active(job, lease_token),
            progress_callback=lambda progress: self._persist_progress(
                job,
                lease_token,
                progress,
            ),
        )
        context = self._context(job)
        context.active_check = lambda: self._claim_active(job, lease_token)
        context.execution_control = control
        context.checkpoint_callback = lambda checkpoint, progress=None: (
            self._checkpoint_stage(
                job,
                lease_token,
                checkpoint,
                progress=progress,
            )
        )
        lease_guard = _DeferredLeaseGuard(self, job, lease_token, control)
        lease_guard.__enter__()
        try:
            if job.job_version not in SUPPORTED_DEFERRED_JOB_VERSIONS:
                raise exceptions.ValidationError(
                    "Deferred job version is not supported."
                )
            created = _datetime(getattr(job, "created", None))
            if (
                created
                and (now - created).total_seconds() >= DEFERRED_JOB_MAX_AGE_SECONDS
            ):
                raise exceptions.AIException(
                    "This operation exceeded its automatic recovery window. Try again."
                )
            authorization = job.authorization or {}
            if (
                authorization.get("policy") != job.job_type
                or authorization.get("actor") != getattr(job.actor, "urlsafe_key", None)
                or authorization.get("inputs") != (job.inputs or {})
            ):
                raise exceptions.ValidationError(
                    "Deferred job authorization snapshot is invalid."
                )
            context = adapter.load(context)
            if context.actor is None:
                raise exceptions.ValidationError("Deferred job actor is missing.")
            adapter.authorize(context)
            if getattr(job, "start_completed", None) is False:
                adapter.started(context)
                self._persist_claimed(
                    job,
                    lease_token,
                    start_completed=True,
                    status_revision=(int(getattr(job, "status_revision", 0) or 0) + 1),
                )
            self._heartbeat(job, lease_token)

            if not adapter.checkpoint_ready(context):
                from .ai.observability import ai_execution_context

                with ai_execution_context(
                    job_type=job.job_type,
                    attempt=job.attempt,
                    contract_version=job.job_version,
                    telemetry_id=getattr(job, "telemetry_id", None),
                    execution_control=control,
                ):
                    prepared = adapter.prepare(context)
                checkpoint = _json_copy(prepared or context.checkpoint or {})
                _validate_payload(
                    authorization=job.authorization or {},
                    inputs=job.inputs or {},
                    parameters=job.parameters or {},
                    client=job.client or {},
                    checkpoint=checkpoint,
                )
                if prepared is not None:
                    self._persist_claimed(
                        job,
                        lease_token,
                        checkpoint=checkpoint,
                        progress={
                            "phase": DeferredJobPhase.PREPARED.value,
                            "updated_at": _utc().isoformat(),
                        },
                    )
                    context.checkpoint = checkpoint
                if not adapter.checkpoint_ready(context):
                    raise exceptions.ValidationError(
                        "Deferred job preparation did not reach a final checkpoint."
                    )

            control.ensure_active()
            apply_context = self._context(job)
            apply_context.checkpoint = dict(context.checkpoint or {})
            apply_context.active_check = context.active_check
            apply_context.execution_control = control
            apply_context.checkpoint_callback = context.checkpoint_callback
            context = adapter.load(apply_context)
            if context.actor is None:
                raise exceptions.ValidationError("Deferred job actor is missing.")
            adapter.authorize(context)
            adapter.validate_apply(context)
            control.ensure_active()

            inspection = adapter.inspect(context)
            if inspection is DeferredJobInspection.DRIFTED:
                raise DeferredJobDriftError("Prepared deferred-job state has changed.")
            if inspection is DeferredJobInspection.NOT_APPLIED:
                control.set_phase(DeferredJobPhase.APPLYING)
                result = _json_copy(adapter.apply(context) or {})
            else:
                result = _json_copy(
                    job.result or context.checkpoint.get("result") or {}
                )

            _validate_payload(
                authorization=job.authorization or {},
                inputs=job.inputs or {},
                parameters=job.parameters or {},
                client=job.client or {},
                checkpoint=context.checkpoint,
                result=result,
            )
            self._persist_claimed(
                job,
                lease_token,
                status=DeferredJobStatus.SUCCEEDED.value,
                dispatch_state="delivery_pending",
                deadline_at=None,
                result=result,
                error={},
                progress={
                    "phase": DeferredJobPhase.COMPLETE.value,
                    "updated_at": _utc().isoformat(),
                },
                delivery={"cleanup": False, "notification": False, "event": False},
                status_revision=int(getattr(job, "status_revision", 0) or 0) + 1,
            )
            context.checkpoint = job.checkpoint or context.checkpoint
            self._finish_terminal_delivery(job, adapter, context=context)
            self._release(job, lease_token)
            return DeferredJobResult(DeferredJobRunState.COMPLETE, job=job)
        except DeferredJobClaimLostError as error:
            return DeferredJobResult(
                DeferredJobRunState.FAILED,
                job=job,
                error=str(error),
            )
        except DeferredJobInfrastructureError:
            self._expire_claim(job, lease_token, now)
            raise
        except Exception as error:
            if not self._claim_active(job, lease_token):
                return DeferredJobResult(
                    DeferredJobRunState.FAILED,
                    job=job,
                    error="Deferred job was cancelled or superseded.",
                )
            if job.status in TERMINAL_STATUSES:
                raise DeferredJobInfrastructureError(
                    "Deferred job terminal delivery is incomplete."
                ) from error
            if _retryable(error) and int(job.attempt or 0) <= len(_retry_delays(error)):
                return self._schedule_retry(
                    job,
                    adapter,
                    context,
                    lease_token,
                    error,
                    now,
                )
            try:
                return self._fail(job, adapter, context, lease_token, error)
            except DeferredJobInfrastructureError:
                self._expire_claim(job, lease_token, now)
                raise
        finally:
            lease_guard.__exit__()

    # @testable infrastructure
    def _context(self, job):
        return DeferredJobContext(
            job=job,
            actor=job.actor,
            notification=job.notification,
            inputs=dict(job.inputs or {}),
            parameters=dict(job.parameters or {}),
            checkpoint=dict(job.checkpoint or {}),
        )

    # @testable infrastructure
    def _heartbeat(self, job, lease_token, phase=None):
        values = {
            "lease_expires": _utc() + timedelta(seconds=DEFERRED_JOB_LEASE_SECONDS),
        }
        if phase:
            values["progress"] = {"phase": phase}
        self._persist_claimed(job, lease_token, **values)

    def _persist_progress(self, job, lease_token, progress):
        self._persist_claimed(
            job,
            lease_token,
            progress=_json_copy(progress),
            status_revision=int(getattr(job, "status_revision", 0) or 0) + 1,
        )

    def _checkpoint_stage(
        self,
        job,
        lease_token,
        checkpoint,
        *,
        progress=None,
    ):
        checkpoint = _json_copy(checkpoint or {})
        _validate_payload(
            authorization=job.authorization or {},
            inputs=job.inputs or {},
            parameters=job.parameters or {},
            client=job.client or {},
            checkpoint=checkpoint,
        )
        values = {
            "checkpoint": checkpoint,
            "status_revision": int(getattr(job, "status_revision", 0) or 0) + 1,
        }
        if progress:
            values["progress"] = {
                **_json_copy(progress),
                "updated_at": _utc().isoformat(),
            }
        self._persist_claimed(job, lease_token, **values)

    def _renew_claim(self, job, lease_token):
        """Renew without mutating shared entity caches from the guard thread."""
        now = _utc()
        lease_expires = now + timedelta(seconds=DEFERRED_JOB_LEASE_SECONDS)
        return database.update_claimed_deferred_job(
            job.key,
            lease_token,
            {"lease_expires": lease_expires},
            now,
        )

    # @testable infrastructure
    def _claim_active(self, job, lease_token):
        """Check lease ownership at cancellation boundaries."""
        try:
            now = _utc()
            lease_expires = now + timedelta(seconds=DEFERRED_JOB_LEASE_SECONDS)
            active = database.update_claimed_deferred_job(
                job.key,
                lease_token,
                {"lease_expires": lease_expires},
                now,
            )
            if active:
                job.lease_expires = lease_expires
            return active
        except Exception as error:
            raise DeferredJobInfrastructureError(
                "Deferred job activity could not be verified."
            ) from error

    # @testable infrastructure
    def _persist_claimed(self, job, claim_token, **values):
        for name, value in values.items():
            setattr(job, name, value)
        updates = {name: job.db.get(job.properties[name].db_key) for name in values}
        if not database.update_claimed_deferred_job(
            job.key,
            claim_token,
            updates,
            _utc(),
        ):
            raise DeferredJobClaimLostError("Deferred job was cancelled or superseded.")

    # @testable infrastructure
    def _release(self, job, lease_token):
        values = {
            "lease_token": None,
            "lease_expires": None,
            "next_attempt_at": None,
        }
        if job.status in TERMINAL_STATUSES:
            values.update({"dispatch_state": "complete", "deadline_at": None})
        self._persist_claimed(job, lease_token, **values)

    # @testable infrastructure
    def _expire_claim(self, job, lease_token, now):
        if job.status in TERMINAL_STATUSES:
            return
        try:
            self._persist_claimed(job, lease_token, lease_expires=now)
        except DeferredJobInfrastructureError:
            return

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_runner_increases_later_quota_backoff_without_adding_attempts
    # @pairs deferred-jobs:retry
    def _schedule_retry(self, job, adapter, context, lease_token, error, now):
        attempt = int(job.attempt or 0)
        delay = _retry_delay(error, attempt)
        scheduled_at = max(_utc(), now)
        next_attempt_at = scheduled_at + timedelta(seconds=delay)
        self._persist_claimed(
            job,
            lease_token,
            status=DeferredJobStatus.RETRY_WAIT.value,
            dispatch_state="pending",
            next_attempt_at=next_attempt_at,
            lease_expires=scheduled_at,
            deadline_at=None,
            error=_error_record(error, retryable=True, attempt=attempt),
            progress={
                "phase": DeferredJobPhase.RETRY_WAIT.value,
                "delay_seconds": delay,
                "updated_at": scheduled_at.isoformat(),
            },
            status_revision=int(getattr(job, "status_revision", 0) or 0) + 1,
        )
        try:
            task_identity = self.dispatch(
                job,
                attempt=attempt + 1,
                delay_seconds=delay,
            )
            self._persist_claimed(
                job,
                lease_token,
                dispatch_state="dispatched",
                task_identity=task_identity,
                dispatched_at=_utc(),
                status_revision=int(getattr(job, "status_revision", 0) or 0) + 1,
            )
        except Exception as schedule_error:
            self._persist_claimed(
                job,
                lease_token,
                next_attempt_at=scheduled_at,
                lease_expires=scheduled_at,
            )
            raise DeferredJobInfrastructureError(
                "Deferred job retry could not be scheduled."
            ) from schedule_error

        if context.notification is not None:
            context.notification.body = adapter.retry_message
            context.notification.pending = True
            Entities.save(context.notification, context.actor)
            _send_notification(context.notification, (job.client or {}).get("token"))
        return DeferredJobResult(
            DeferredJobRunState.RETRY_SCHEDULED,
            job=job,
            error=str(error),
        )

    # @testable infrastructure
    def _fail(self, job, adapter, context, lease_token, error):
        exceptions.capture(
            error,
            context={
                "deferred_job": {
                    "id": job.urlsafe_key,
                    "type": job.job_type,
                    "attempt": job.attempt,
                }
            },
            wait_for_delivery=True,
        )
        terminal_error = _terminal_error(
            error,
            requires_ai=adapter.requires_ai,
        )
        try:
            adapter.failure(context, terminal_error)
        except Exception as failure_error:
            raise DeferredJobInfrastructureError(
                "Deferred job failure state could not be persisted."
            ) from failure_error
        self._persist_claimed(
            job,
            lease_token,
            status=DeferredJobStatus.FAILED.value,
            dispatch_state="delivery_pending",
            deadline_at=None,
            error=_error_record(
                terminal_error,
                retryable=False,
                attempt=job.attempt,
            ),
            progress={
                "phase": DeferredJobPhase.FAILED.value,
                "updated_at": _utc().isoformat(),
            },
            delivery={
                "failure": True,
                "cleanup": False,
                "notification": False,
                "event": False,
            },
            status_revision=int(getattr(job, "status_revision", 0) or 0) + 1,
        )
        try:
            self._finish_terminal_delivery(
                job,
                adapter,
                context=context,
                error=terminal_error,
            )
            self._release(job, lease_token)
        except DeferredJobInfrastructureError:
            raise
        except Exception as delivery_error:
            raise DeferredJobInfrastructureError(
                "Deferred job failure delivery is incomplete."
            ) from delivery_error
        return DeferredJobResult(
            DeferredJobRunState.FAILED,
            job=job,
            error=str(terminal_error),
        )

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_terminal_notification_transient_retries_without_reapplying_domain
    # @tests tests_unit/test_023_deferred_jobs.py::test_terminal_event_transient_retries_after_notification_without_reapplying_domain
    # @tests tests_unit/test_023_deferred_jobs.py::test_terminal_notification_can_duplicate_after_acceptance_before_delivery_checkpoint
    # @tests tests_unit/test_023_deferred_jobs.py::test_reconciler_completes_terminal_delivery_when_input_was_deleted
    # @pair deferred-jobs:orphaned-input
    def _finish_terminal_delivery(
        self,
        job,
        adapter,
        context=None,
        error=None,
        *,
        inputs_available=True,
    ):
        if context is None:
            context = self._context(job)
            try:
                context = adapter.load(context)
            except exceptions.ValidationError:
                inputs_available = False
        delivery = dict(job.delivery or {})
        succeeded = job.status == DeferredJobStatus.SUCCEEDED.value

        if not inputs_available:
            delivery_changed = False
            if not delivery.get("input_missing"):
                delivery["input_missing"] = True
                delivery_changed = True
            if not succeeded and not delivery.get("failure"):
                delivery["failure"] = True
                delivery_changed = True
            if delivery_changed:
                self._save_terminal_fields(job, delivery=delivery)

        if not delivery.get("cleanup"):
            adapter.cleanup(context, terminal=True)
            delivery["cleanup"] = True
            self._save_terminal_fields(
                job,
                delivery=delivery,
                parameters=context.parameters,
            )

        if not delivery.get("notification"):
            if not inputs_available:
                if context.notification is not None:
                    context.notification.body = MISSING_INPUT_MESSAGE
                    context.notification.pending = False
                    Entities.save(
                        *[
                            entity
                            for entity in (context.notification, context.actor)
                            if entity is not None
                        ]
                    )
            elif context.notification is None and adapter.completion_notification_only:
                context.notification = Entities.NOTIFICATION.create(
                    {
                        "parent": context.actor,
                        "target": adapter.notification_target(context),
                        "body": adapter.terminal_message(
                            context,
                            succeeded=succeeded,
                            error=error or (job.error or {}).get("message"),
                        ),
                        "pending": False,
                    }
                )
                Entities.save(context.notification, context.actor)
                job.notification = context.notification
                self._save_terminal_fields(job, notification=context.notification)
            if inputs_available and context.notification is not None:
                message_error = error or (job.error or {}).get("message")
                context.notification.body = adapter.terminal_message(
                    context,
                    succeeded=succeeded,
                    error=message_error,
                )
                context.notification.pending = False
                Entities.save(
                    *[
                        entity
                        for entity in (context.notification, context.actor)
                        if entity is not None
                    ]
                )
                _send_notification(
                    context.notification,
                    (job.client or {}).get("token"),
                )
            delivery["notification"] = True
            self._save_terminal_fields(job, delivery=delivery)

        if not delivery.get("event"):
            if inputs_available:
                event = adapter.event(context)
                if event:
                    _send_event(event, (job.client or {}).get("token"))
            delivery["event"] = True
            client = dict(job.client or {})
            client.pop("token", None)
            self._save_terminal_fields(job, delivery=delivery, client=client)

    # @testable infrastructure
    def _save_terminal_fields(self, job, **values):
        token = job.lease_token
        if not token:
            for name, value in values.items():
                setattr(job, name, value)
            Entities.save(job)
            return
        self._persist_claimed(job, token, **values)


DeferredJobs = DeferredJobRegistry()


# @testable infrastructure
def _serialize_inputs(inputs):
    result = {}
    for name, value in (inputs or {}).items():
        if hasattr(value, "urlsafe_key"):
            result[name] = {
                "kind": value.entity_kind,
                "id": value.urlsafe_key,
            }
        elif isinstance(value, dict) and value.get("kind") and value.get("id"):
            result[name] = {"kind": value["kind"], "id": value["id"]}
        elif value is None:
            result[name] = None
        else:
            raise TypeError(f"Deferred job input {name!r} must be an entity reference")
    return result


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
def _validate_payload(**sections):
    size = len(
        json.dumps(sections, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    )
    if size > DEFERRED_JOB_PAYLOAD_LIMIT_BYTES:
        raise exceptions.ValidationError(
            "Deferred job payload exceeds the 750 KiB persistence limit."
        )
    return size


# @testable infrastructure
def _new_idempotency_key(spec):
    source = ":".join(
        (
            spec.job_type.value,
            spec.actor.urlsafe_key,
            uuid.uuid4().hex,
        )
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_request_fingerprint_excludes_refreshable_push_token
# @features deferred-jobs
# @dimensions operation-fingerprint token-exclusion routing-identity
def _request_fingerprint(
    *,
    job_type,
    actor,
    authorization,
    inputs,
    parameters,
    client,
):
    """Hash immutable operation data without binding a refreshed push token."""
    public_client = {
        key: value for key, value in (client or {}).items() if key != "token"
    }
    payload = json.dumps(
        {
            "job_type": job_type,
            "actor": actor,
            "authorization": authorization,
            "inputs": inputs,
            "parameters": parameters,
            "client": public_client,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# @testable infrastructure
def _task_id(job, attempt, *, suffix=None):
    digest = hashlib.sha256(job.idempotency_key.encode("utf-8")).hexdigest()[:32]
    task_id = f"job-{digest}-a{int(attempt)}"
    if suffix:
        bounded = "".join(
            character
            for character in str(suffix).lower()
            if character.isalnum() or character == "-"
        )[:40]
        if bounded:
            task_id = f"{task_id}-{bounded}"
    return task_id


# @testable infrastructure
def _feedback_task_id(job):
    digest = hashlib.sha256(job.idempotency_key.encode("utf-8")).hexdigest()[:32]
    return f"job-{digest}-feedback"


# @testable infrastructure
def _utc(value=None):
    return value or datetime.now(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/deferred_jobs.py::_status_projection
# @covered-by lagniappe/core/tools/deferred_jobs.py::DeferredJobRegistry.reconcile
# @reason shared normalization for Datastore and serialized operation timestamps
def _datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


# @testable false
# @covered-by lagniappe/core/tools/deferred_jobs.py::_status_projection
# @reason status projection owns elapsed-time presentation semantics
def _elapsed_seconds(start, now):
    start = _datetime(start)
    return max(int((now - start).total_seconds()), 0) if start else 0


# @testable true
# @tests tests_e2e/002_home/test_002o_deferred_jobs.py::test_deferred_status_is_owner_safe_and_batched
# @tests tests_unit/test_023_deferred_jobs.py::test_status_projection_is_bounded_and_marks_stale_work
# @features deferred-jobs
# @dimensions status progress timing stale-state privacy
def _status_projection(job, *, now):
    progress = dict(getattr(job, "progress", None) or {})
    client = dict(getattr(job, "client", None) or {})
    phase = progress.get("phase") or getattr(job, "status", None) or "queued"
    modified = _datetime(getattr(job, "modified", None))
    stale = bool(
        getattr(job, "status", None) in ACTIVE_STATUSES
        and modified
        and (now - modified).total_seconds() >= DEFERRED_JOB_HEARTBEAT_SECONDS * 2
    )
    error = getattr(job, "error", None) or {}
    result = {
        "key": job.urlsafe_key,
        "type": getattr(job, "job_type", None),
        "status": getattr(job, "status", None),
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, "Working"),
        "attempt": int(getattr(job, "attempt", 0) or 0),
        "elapsed_seconds": _elapsed_seconds(getattr(job, "created", None), now),
        "phase_elapsed_seconds": _elapsed_seconds(progress.get("updated_at"), now),
        "updated_at": modified.isoformat() if modified else None,
        "next_attempt_at": (
            _datetime(getattr(job, "next_attempt_at", None)).isoformat()
            if _datetime(getattr(job, "next_attempt_at", None))
            else None
        ),
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
# @tests tests_unit/test_023_deferred_jobs.py::test_admin_projection_exposes_diagnostics_without_payload_content
# @pair deferred-jobs:diagnostics
# @pair deferred-jobs:privacy
def _admin_projection(job, *, now):
    """Extend owner-visible status with bounded operational diagnostics."""
    projection = _status_projection(job, now=now)
    actor = getattr(job, "actor", None)
    inputs = getattr(job, "inputs", None) or {}
    input_refs = {
        str(name): {
            "kind": value.get("kind"),
            "id": value.get("id"),
        }
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
        value = _datetime(getattr(job, attribute_name, None))
        timestamps[output_name] = value.isoformat() if value else None

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
            "created_at": (
                _datetime(getattr(job, "created", None)).isoformat()
                if _datetime(getattr(job, "created", None))
                else None
            ),
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
                for key in (
                    "failure",
                    "cleanup",
                    "notification",
                    "event",
                    "input_missing",
                )
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


# @testable infrastructure
def _error_record(error, *, retryable, attempt):
    return {
        "type": type(error).__name__,
        "message": str(error),
        "retryable": bool(retryable),
        "attempt": int(attempt or 0),
        "context": _json_copy(getattr(error, "context", None) or {}),
    }


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_runner_retries_sdk_timeout
# @tests tests_unit/test_023_deferred_jobs.py::test_runner_retries_sdk_5xx_and_persists_clean_terminal_message
# @pair deferred-jobs:provider-timeout
# @pair deferred-jobs:provider-errors
# @pair deferred-jobs:retry
def _retryable(error):
    transient = (
        DeferredJobDeadlineError,
        exceptions.AIQuotaError,
        *TRANSIENT_GOOGLE_ERRORS,
        ConnectionError,
        TimeoutError,
    )
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        from .ai.core import is_provider_transient_error

        if isinstance(current, transient) or is_provider_transient_error(current):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


# @testable infrastructure
def _quota_error(error):
    """Return a wrapped provider-quota error, when present."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        if isinstance(current, exceptions.AIQuotaError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


# @testable infrastructure
def _retry_delays(error):
    """Choose stronger application backoff after provider quota exhaustion."""
    if _quota_error(error):
        return DEFERRED_JOB_QUOTA_RETRY_DELAYS
    return DEFERRED_JOB_RETRY_DELAYS


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_runner_retries_sdk_5xx_and_persists_clean_terminal_message
# @pair deferred-jobs:terminal-message
def _terminal_error(error, *, requires_ai=False):
    """Replace exhausted provider details with a concise user-facing message."""
    quota_error = _quota_error(error)
    if quota_error is not None:
        return exceptions.AIQuotaError(
            MODEL_BUSY_MESSAGE,
            context=dict(getattr(quota_error, "context", None) or {}),
        )
    if requires_ai and _retryable(error):
        return exceptions.AIException(
            MODEL_BUSY_MESSAGE,
            context=dict(getattr(error, "context", None) or {}),
        )
    return error


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_runner_increases_later_quota_backoff_without_adding_attempts
# @pairs deferred-jobs:quota deferred-jobs:backoff deferred-jobs:jitter
def _retry_delay(error, attempt):
    delays = _retry_delays(error)
    delay = delays[int(attempt) - 1]
    if delays is DEFERRED_JOB_QUOTA_RETRY_DELAYS:
        delay += random.randint(0, DEFERRED_JOB_QUOTA_RETRY_JITTER_SECONDS)
    return delay


# @testable infrastructure
def _send_notification(notification, token):
    if notification is None:
        return PushDeliveryOutcome.ACCEPTED
    from lagniappe.web import responses

    outcome = responses.send_notification(notification, token)
    if outcome is PushDeliveryOutcome.TRANSIENT_FAILURE:
        raise DeferredJobInfrastructureError(
            "Deferred job notification delivery is temporarily unavailable."
        )
    return outcome


# @testable infrastructure
def _send_event(event, token):
    from lagniappe.web import responses

    outcome = responses.send_message(
        {"type": "server-change", "message": json.dumps(event)},
        token,
    )
    if outcome is PushDeliveryOutcome.TRANSIENT_FAILURE:
        raise DeferredJobInfrastructureError(
            "Deferred job event delivery is temporarily unavailable."
        )
    return outcome
