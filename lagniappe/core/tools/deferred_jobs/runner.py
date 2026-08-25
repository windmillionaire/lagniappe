"""Claim-through-terminal deferred-job execution."""

from datetime import timedelta
import uuid

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    DEFERRED_JOB_ATTEMPT_DEADLINE_SECONDS,
    DEFERRED_JOB_LEASE_SECONDS,
    DEFERRED_JOB_MAX_AGE_SECONDS,
    SUPPORTED_DEFERRED_JOB_VERSIONS,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobResult,
    DeferredJobRunState,
    DeferredJobStatus,
    Fetch,
)
from lagniappe.core.entities import Entities
from lagniappe.core.properties.deferred_job_lifecycle import (
    TERMINAL_STATUSES,
    datetime_value as _datetime,
)
from lagniappe.core.properties.deferred_job_request import validate_payload as _validate_payload
from lagniappe.core.tools import database

from .common import _error_record, _json_copy, _publish_operation_projection, _utc
from .context import DeferredJobContext
from .control import DeferredExecutionControl, _DeferredLeaseGuard
from .errors import (
    DeferredJobClaimLostError,
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
    DeferredJobDriftError,
    DeferredJobInfrastructureError,
)
from .retry import (
    _provider_retry_attempt,
    _retry_delay,
    _retry_delays,
    _retryable,
    _terminal_error,
)


DEPENDENCY_RETRY_DELAY_SECONDS = 60
MISSING_INPUT_MESSAGE = (
    "This operation stopped because the item it was working on was deleted."
)


# @testable infrastructure
class DeferredJobRunner:

    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_checkpoints_before_apply_and_resumes_without_prepare
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_classifies_wrapped_transient_errors_and_schedules_retry
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_waits_for_dependency_without_consuming_provider_retry
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_treats_deleted_active_job_as_cancellation
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_supplies_bounded_ai_observability_context_during_prepare
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_rechecks_ai_access_before_apply
    # @matrix deferred-jobs : cancellation checkpoint reauthorization recovery retry
    # @pair deferred-jobs:preparation-context
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

        _publish_operation_projection(job, operation="claim_projection")

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
                from lagniappe.core.tools.ai.observability import ai_execution_context

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
                delivery={"cleanup": False, "notification": False},
                status_revision=int(getattr(job, "status_revision", 0) or 0) + 1,
            )
            context.checkpoint = job.checkpoint or context.checkpoint
            self._finish_terminal_delivery(job, adapter, context=context)
            self._release(job, lease_token)
            return DeferredJobResult(DeferredJobRunState.COMPLETE, job=job)
        except DeferredJobDependencyPendingError as error:
            return self._schedule_dependency_wait(
                job,
                adapter,
                context,
                lease_token,
                error,
                now,
            )
        except DeferredJobDependencyFailedError as error:
            return self._fail(
                job,
                adapter,
                context,
                lease_token,
                error,
                capture_error=False,
            )
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
            if _retryable(error) and _provider_retry_attempt(job) <= len(
                _retry_delays(error)
            ):
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


    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/runner.py::DeferredJobRunner.run
    def _persist_progress(self, job, lease_token, progress):
        self._persist_claimed(
            job,
            lease_token,
            progress=_json_copy(progress),
            status_revision=int(getattr(job, "status_revision", 0) or 0) + 1,
        )


    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/runner.py::DeferredJobRunner.run
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


    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/runner.py::DeferredJobRunner.run
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
        persisted = database.update_claimed_deferred_job(
            job.key,
            claim_token,
            updates,
            _utc(),
            include_scheduler_control=True,
        )
        if not persisted:
            raise DeferredJobClaimLostError("Deferred job was cancelled or superseded.")
        if "status_revision" in values:
            _publish_operation_projection(job, operation="status_projection")
        return (
            persisted.get("scheduler_control")
            if isinstance(persisted, dict)
            else None
        )


    # @testable true
    # @tests tests_unit/test_023b_deferred_job_service.py::test_terminal_release_reuses_committed_scheduler_control
    # @pairs cloud-scheduler:datastore-read-isolation deferred-jobs:terminal-delivery
    def _release(self, job, lease_token):
        values = {
            "lease_token": None,
            "lease_expires": None,
            "next_attempt_at": None,
        }
        terminal = job.status in TERMINAL_STATUSES
        if terminal:
            values.update({"dispatch_state": "complete", "deadline_at": None})
        scheduler_control = self._persist_claimed(job, lease_token, **values)
        if terminal:
            self._sync_reconciler(control=scheduler_control)


    # @testable infrastructure
    def _expire_claim(self, job, lease_token, now):
        if job.status in TERMINAL_STATUSES:
            return
        try:
            self._persist_claimed(job, lease_token, lease_expires=now)
        except DeferredJobInfrastructureError:
            return


    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_increases_later_quota_backoff_without_adding_attempts
    # @pair deferred-jobs:retry
    def _schedule_retry(self, job, adapter, context, lease_token, error, now):
        attempt = int(job.attempt or 0)
        delay = _retry_delay(error, _provider_retry_attempt(job))
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
            Entities.save(context.notification)
        return DeferredJobResult(
            DeferredJobRunState.RETRY_SCHEDULED,
            job=job,
            error=str(error),
        )


    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_waits_for_dependency_without_consuming_provider_retry
    # @matrix deferred-jobs : dependency-wait provider-attempt-isolation retry
    def _schedule_dependency_wait(
        self,
        job,
        adapter,
        context,
        lease_token,
        error,
        now,
    ):
        attempt = int(job.attempt or 0)
        scheduled_at = max(_utc(), now)
        next_attempt_at = scheduled_at + timedelta(
            seconds=DEPENDENCY_RETRY_DELAY_SECONDS
        )
        parameters = dict(job.parameters or {})
        parameters["_dependency_waits"] = (
            int(parameters.get("_dependency_waits", 0) or 0) + 1
        )
        self._persist_claimed(
            job,
            lease_token,
            status=DeferredJobStatus.RETRY_WAIT.value,
            dispatch_state="pending",
            next_attempt_at=next_attempt_at,
            lease_expires=scheduled_at,
            deadline_at=None,
            parameters=parameters,
            error=_error_record(error, retryable=True, attempt=attempt),
            progress={
                "phase": DeferredJobPhase.SUMMARIZING.value,
                "updated_at": scheduled_at.isoformat(),
            },
            status_revision=int(getattr(job, "status_revision", 0) or 0) + 1,
        )
        try:
            task_identity = self.dispatch(
                job,
                attempt=attempt + 1,
                delay_seconds=DEPENDENCY_RETRY_DELAY_SECONDS,
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
                "Deferred job dependency check could not be scheduled."
            ) from schedule_error

        if context.notification is not None:
            context.notification.body = adapter.dependency_message
            context.notification.pending = True
            Entities.save(context.notification)
        return DeferredJobResult(
            DeferredJobRunState.RETRY_SCHEDULED,
            job=job,
            error=str(error),
        )


    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_fails_cleanly_when_dependency_failed
    # @matrix deferred-jobs : dependency-failure no-duplicate-capture terminal
    def _fail(
        self,
        job,
        adapter,
        context,
        lease_token,
        error,
        *,
        capture_error=True,
    ):
        if capture_error:
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
            requires_ai=adapter.required_ai_access is not None,
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
    # @tests tests_unit/test_023d_deferred_job_recovery.py::test_reconciler_completes_terminal_delivery_when_input_was_deleted
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_email_ingest_notification_is_created_only_for_failure
    # @matrix deferred-jobs : failure-only-notification orphaned-input
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
            if adapter.notification_policy == "none":
                if context.notification is not None:
                    Entities.delete(context.notification)
                    context.notification = None
                    job.notification = None
                    self._save_terminal_fields(job, notification=None)
            elif not inputs_available:
                if context.notification is not None:
                    context.notification.body = MISSING_INPUT_MESSAGE
                    context.notification.pending = False
                    Entities.save(context.notification)
            elif context.notification is None and (
                adapter.notification_policy == "completion"
                or (adapter.notification_policy == "failure" and not succeeded)
            ):
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
                Entities.save(context.notification)
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
                Entities.save(context.notification)
            delivery["notification"] = True
            self._save_terminal_fields(job, delivery=delivery)

        if (
            inputs_available
            and adapter.external_delivery_required(context)
            and not delivery.get("external_email")
        ):
            adapter.external_delivery(
                context,
                succeeded=succeeded,
                error=error or (job.error or {}).get("message"),
            )
            delivery["external_email"] = True
            self._save_terminal_fields(job, delivery=delivery)


    # @testable infrastructure
    def _save_terminal_fields(self, job, **values):
        token = job.lease_token
        if not token:
            for name, value in values.items():
                setattr(job, name, value)
            Entities.save(job)
            return
        self._persist_claimed(job, token, **values)
