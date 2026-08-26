"""Collection recovery and terminal-delivery reconciliation."""

import json
from datetime import timedelta

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    DEFERRED_JOB_MAX_AGE_SECONDS,
    DEFERRED_JOB_RECONCILE_GRACE_SECONDS,
    DeferredJobPhase,
    DeferredJobStatus,
    Fetch,
)
from lagniappe.core.entities import Entities
from lagniappe.core.properties.deferred_job_lifecycle import (
    TERMINAL_STATUSES,
    datetime_value as _datetime,
)
from lagniappe.core.tools.database import deferred_jobs as database_deferred_jobs

from .common import _error_record, _publish_operation_projection, _utc
from .errors import DeferredJobInfrastructureError


# @testable infrastructure
class DeferredJobRecovery:
    # @testable true
    # @tests tests_unit/test_023f_deferred_job_scheduler.py::test_reconciler_repairs_control_before_self_pausing
    # @matrix cloud-scheduler deferred-jobs : drift-repair optimistic-concurrency self-pause
    def _repair_reconciler_control(self, now, *, attempts=4):
        """Scan durable recovery work and publish it without losing raced changes."""
        if not CONFIG.production:
            return self._reconcile_candidates(limit=None)
        jobs = []
        for _attempt in range(max(int(attempts), 1)):
            snapshot = database_deferred_jobs.get_deferred_job_scheduler_control()
            jobs = self._reconcile_candidates(limit=None)
            repair = database_deferred_jobs.repair_deferred_job_scheduler_control(
                [job.key for job in jobs],
                snapshot["generation"],
                now,
            )
            if repair.get("repaired"):
                return jobs
        exceptions.capture(
            DeferredJobInfrastructureError(
                "Deferred-job recovery membership changed during repair."
            ),
            context={"deferred_job": {"operation": "scheduler_control_repair"}},
            level="warning",
        )
        return jobs

    # @testable true
    # @tests tests_unit/test_023d_deferred_job_recovery.py::test_reconciler_redispatches_one_cas_claimed_stale_job
    # @tests tests_unit/test_023d_deferred_job_recovery.py::test_reconciler_resumes_stale_terminal_delivery_after_grace
    # @tests tests_unit/test_023d_deferred_job_recovery.py::test_reconciler_completes_terminal_delivery_when_input_was_deleted
    # @matrix deferred-jobs : compare-and-set deterministic-task-id grace orphaned-input reconciliation redispatch terminal-delivery
    # @pair notifications:terminal-delivery
    def reconcile(self, *, now=None, limit=250):
        """Redispatch stranded work and bound the age of every operation."""
        now = _utc(now)
        jobs = self._repair_reconciler_control(now)
        self._sync_reconciler(force=True)
        jobs = jobs[: max(int(limit), 0)]
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
                claim = database_deferred_jobs.claim_deferred_job_recovery(
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
                            }
                        ),
                    },
                )
                if not claim.get("claimed"):
                    continue
                job = Entities.DEFERRED_JOB(claim["entity"])
                job = Entities.fetch_one(job, request=Fetch.direct()) or job
                _publish_operation_projection(job, operation="recovery_projection")
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
                    database_deferred_jobs.update_deferred_job_recovery_dispatch(
                        job.key,
                        revision,
                        {"dispatch_state": "pending", "dispatched_at": None},
                        now,
                    )
                    raise
                database_deferred_jobs.update_deferred_job_recovery_dispatch(
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
        self._sync_reconciler()
        return result

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/recovery.py::DeferredJobRecovery.reconcile
    def _reconcile_candidates(self, *, limit):
        records = database_deferred_jobs.recovery_records(limit=limit)
        jobs = [Entities.DEFERRED_JOB(record) for record in records]
        return Entities.fetch(*jobs, request=Fetch.direct())

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/recovery.py::DeferredJobRecovery.reconcile
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
