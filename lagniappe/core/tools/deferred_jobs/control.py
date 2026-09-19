"""Attempt deadlines, progress boundaries, and background lease renewal."""

import threading

from lagniappe.core.definitions import DEFERRED_JOB_HEARTBEAT_SECONDS, DeferredJobPhase

from .common import _utc
from .errors import (
    DeferredJobClaimLostError,
    DeferredJobDeadlineError,
    DeferredJobInfrastructureError,
)




# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_execution_control_renews_and_observes_lost_claim
# @tests tests_unit/test_023h_deferred_job_control.py::test_local_stop_state_prevents_activity_reads
# @tests tests_unit/test_023h_deferred_job_control.py::test_local_stop_during_activity_read_is_observed
# @tests tests_unit/test_023h_deferred_job_control.py::test_claim_loss_stops_checks_and_prevents_heartbeat_renewal
# @tests tests_unit/test_023h_deferred_job_control.py::test_blocking_work_renews_only_on_the_heartbeat_cadence
# @matrix deferred-jobs : cancellation deadline heartbeat progress provider-boundary tool-boundary
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
        self.report_planning = False
        self.provider_retry_callback = None

    @property
    def remaining_seconds(self):
        return max((self.deadline_at - _utc()).total_seconds(), 0)

    def mark_lost(self):
        self._lost = True

    def mark_background_error(self, error):
        self._background_error = error

    def claim_provider_retry(self):
        self.ensure_active()
        return bool(self.provider_retry_callback and self.provider_retry_callback())

    def ensure_active(self):
        """Check local stop conditions and fresh durable ownership, without renewal."""
        self._check_local_state()
        if not self._active_check():
            self._lost = True
            raise DeferredJobClaimLostError("Deferred job was cancelled or superseded.")
        # A database read can overlap the deadline or a heartbeat failure.
        self._check_local_state()

    # @testable false
    # @covered-by lagniappe/core/tools/deferred_jobs/control.py::DeferredExecutionControl
    # @reason local stop conditions are checked through ensure_active
    def _check_local_state(self):
        if self._background_error is not None:
            raise DeferredJobInfrastructureError(
                "Deferred job heartbeat failed."
            ) from self._background_error
        if self._lost:
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
# @tests tests_unit/test_023c_deferred_job_runner.py::test_execution_control_renews_and_observes_lost_claim
# @tests tests_unit/test_023h_deferred_job_control.py::test_blocking_work_renews_only_on_the_heartbeat_cadence
# @matrix deferred-jobs : blocking-provider heartbeat lease-loss
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
