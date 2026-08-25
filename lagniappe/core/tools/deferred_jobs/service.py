"""Public durable lifecycle service for deferred jobs."""

import hashlib
import json
import uuid

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    DeferredJobPhase,
    DeferredJobResult,
    DeferredJobSpec,
    DeferredJobStatus,
    Fetch,
)
from lagniappe.core.entities import Entities
from lagniappe.core.properties.deferred_job_dispatch import TaskIdentity
from lagniappe.core.properties.deferred_job_lifecycle import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    admin_projection as _admin_projection,
    status_projection as _status_projection,
)
from lagniappe.core.properties.deferred_job_request import (
    IdempotencyKey,
    Inputs,
    RequestFingerprint,
    validate_payload as _validate_payload,
)
from lagniappe.core.tools import database
from lagniappe.core.tools.database import deferred_jobs as deferred_database
from lagniappe.core.tools.services import task_queue

from . import scheduler
from .adapters.registry import DeferredJobAdapterRegistry
from .common import _error_record, _json_copy, _publish_operation_projection, _utc
from .context import DeferredJobContext
from .dispatch import DeferredJobDispatch
from .errors import DeferredJobInfrastructureError, DeferredJobLockedError
from .recovery import DeferredJobRecovery
from .runner import DeferredJobRunner


_serialize_inputs = Inputs.serialize
_new_idempotency_key = IdempotencyKey.generate
_request_fingerprint = RequestFingerprint.create
_task_id = TaskIdentity.create
_feedback_task_id = TaskIdentity.feedback


# @testable infrastructure
class DeferredJobService(DeferredJobDispatch, DeferredJobRecovery, DeferredJobRunner):
    def __init__(self, adapter_registry=None):
        self.adapter_registry = adapter_registry or DeferredJobAdapterRegistry()

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/adapters/registry.py::DeferredJobAdapterRegistry.register
    def register(self, adapter):
        return self.adapter_registry.register(adapter)

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/adapters/registry.py::DeferredJobAdapterRegistry.adapter
    def adapter(self, job_type):
        return self.adapter_registry.adapter(job_type)

    # @testable true
    # @tests tests_unit/test_023f_deferred_job_scheduler.py::test_registry_requires_resume_but_tolerates_pause_failure
    # @matrix cloud-scheduler deferred-jobs : pause-failure recovery-guarantee resume-failure
    def _sync_reconciler(self, *, required=False, force=False, control=None):
        """Converge recovery scheduling, optionally requiring success to start."""
        try:
            options = {"force": force}
            if control is not None:
                options["initial_control"] = control
            return scheduler.synchronize_deferred_job_reconciler(**options)
        except Exception as error:
            exceptions.capture(
                error,
                context={
                    "deferred_job": {
                        "operation": "scheduler_sync",
                        "required": required,
                    }
                },
                level="warning",
            )
            if required:
                raise DeferredJobInfrastructureError(
                    "Background-job recovery could not be enabled. Try again."
                ) from error
            return None

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/service.py::DeferredJobService.start
    def _fail_unclaimed_start(
        self,
        job,
        adapter,
        context,
        notification,
        error,
        *,
        notification_error,
    ):
        """Finish pre-claim failure and recovery membership atomically."""
        adapter.failure(context, error)
        adapter.cleanup(context, terminal=True)
        now = _utc()
        transition = database.transition_active_deferred_job(
            job.key,
            {
                "status": DeferredJobStatus.FAILED.value,
                "dispatch_state": "failed",
                "lease_token": None,
                "lease_expires": None,
                "next_attempt_at": None,
                "deadline_at": None,
                "client": json.dumps(job.client or {}),
                "error": json.dumps(_error_record(error, retryable=False, attempt=0)),
                "progress": json.dumps(
                    {
                        "phase": DeferredJobPhase.FAILED.value,
                        "updated_at": now.isoformat(),
                    }
                ),
            },
            now,
        )
        if not transition.get("transitioned"):
            raise DeferredJobInfrastructureError(
                "Deferred operation failure could not be persisted."
            )
        _publish_operation_projection(
            Entities.DEFERRED_JOB(transition["entity"]),
            operation="failed_start_projection",
        )
        if notification is None and adapter.notification_policy == "failure":
            notification = Entities.NOTIFICATION.create(
                {
                    "parent": context.actor,
                    "target": adapter.notification_target(context),
                    "body": adapter.terminal_message(
                        context,
                        succeeded=False,
                        error=notification_error,
                    ),
                    "pending": False,
                }
            )
            Entities.save(notification)
        elif notification is not None:
            notification.body = adapter.terminal_message(
                context,
                succeeded=False,
                error=notification_error,
            )
            notification.pending = False
            Entities.save(notification)
        self._sync_reconciler(control=transition.get("scheduler_control"))

    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_create_is_transactionally_idempotent
    # @tests tests_unit/test_023b_deferred_job_service.py::test_start_rejects_operation_id_reuse_for_different_request
    # @tests tests_unit/test_023b_deferred_job_service.py::test_start_retains_generic_intent_after_dispatch_failure
    # @tests tests_unit/test_023b_deferred_job_service.py::test_start_dispatch_marker_does_not_overwrite_a_fast_worker
    # @matrix deferred-jobs : compare-and-set dispatch-worker-race mismatch no-apply operation-fingerprint start transactional-start transient-dispatch
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
            if (
                existing.status in ACTIVE_STATUSES
                or getattr(existing, "dispatch_state", None) == "delivery_pending"
            ):
                self._sync_reconciler(required=True)
            return existing, existing.notification

        notification = None
        if adapter.notification_policy == "pending":
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
            if (
                existing.status in ACTIVE_STATUSES
                or getattr(existing, "dispatch_state", None) == "delivery_pending"
            ):
                self._sync_reconciler(required=True)
            return existing, existing.notification
        self._sync_reconciler(
            required=True,
            control=creation.get("scheduler_control"),
        )
        Entities.save(*[entity for entity in (job, notification) if entity])

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
            self._fail_unclaimed_start(
                job,
                adapter,
                context,
                notification,
                error,
                notification_error="The operation could not be initialized.",
            )
            raise

        dispatch_revision = int(job.status_revision or 0) + 1
        dispatch_started_at = _utc()
        job.dispatch_state = "dispatching"
        job.dispatched_at = dispatch_started_at
        job.status_revision = dispatch_revision
        Entities.save(job)

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
                self._fail_unclaimed_start(
                    job,
                    adapter,
                    context,
                    notification,
                    terminal_error,
                    notification_error=terminal_error,
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

        return job, notification

    # @testable true
    # @tests tests_unit/test_023b_deferred_job_service.py::test_cancel_deletes_tasks_and_persists_a_tombstone
    # @matrix deferred-jobs : cancellation deterministic-task-id
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
                "client": json.dumps(job.client or {}),
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
        _publish_operation_projection(job, operation="cancel_projection")
        self._sync_reconciler(control=transition.get("scheduler_control"))
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

    # @testable false
    # @covered-by lagniappe/core/tools/deferred_jobs/service.py::DeferredJobService.cancel
    # @reason one-line status-specialized delegation retains cancel as the behavior owner
    def supersede(self, job):
        """Replace active work while retaining a terminal operation record."""
        return self.cancel(
            job,
            status=DeferredJobStatus.SUPERSEDED,
            message="Operation replaced by a newer request.",
        )

    # @testable true
    # @tests tests_unit/test_023b_deferred_job_service.py::test_long_running_feedback_updates_pending_notification
    # @matrix deferred-jobs notifications : feedback long-running terminal-safety
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
        Entities.save(notification)
        return True

    # @testable true
    # @tests tests_unit/test_023b_deferred_job_service.py::test_statuses_returns_only_jobs_visible_to_the_actor
    # @tests tests_unit/test_023b_deferred_job_service.py::test_statuses_rejects_more_than_fifty_jobs
    # @matrix deferred-jobs : batching owner progress status timing
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
        records = deferred_database.recent_records(limit)
        jobs = [Entities.DEFERRED_JOB(record) for record in records]
        jobs = Entities.fetch(*jobs, request=Fetch.direct())
        return [_admin_projection(job, now=_utc(now)) for job in jobs]

    # @testable true
    # @tests tests_unit/test_023b_deferred_job_service.py::test_delete_terminal_jobs_preserves_active_and_incomplete_delivery
    # @matrix deferred-jobs : retention terminal-delivery
    def delete_terminal(self, *, before=None, batch_size=500):
        """Delete retained terminal jobs without interrupting unfinished work."""
        before = _utc(before) if before is not None else None
        return deferred_database.delete_terminal_records(
            before=before,
            batch_size=batch_size,
        )


DeferredJobs = DeferredJobService()
