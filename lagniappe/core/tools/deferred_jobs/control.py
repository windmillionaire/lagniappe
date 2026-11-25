"""Attempt deadlines, progress boundaries, and background lease renewal."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
import threading

from lagniappe.core.definitions import DEFERRED_JOB_HEARTBEAT_SECONDS, DeferredJobPhase
from lagniappe.core.tools.ai.observability import generation_timing

from .common import _utc
from .errors import (
    DeferredJobClaimLostError,
    DeferredJobDeadlineError,
    DeferredJobInfrastructureError,
)




class DeferredExecutionControl:
    """Lease, deadline, cancellation, and coarse progress for one attempt."""

    _PROVIDER_PHASES = {
        "initial": DeferredJobPhase.GENERATING,
        "tool": DeferredJobPhase.USING_TOOLS,
        "structured_final": DeferredJobPhase.FINALIZING,
    }

    def __init__(
        self, *, deadline_at: datetime, active_check: Callable[[], bool],
        progress_callback: Callable[[dict[str, str | int]], object],
    ) -> None:
        self.deadline_at = deadline_at
        self._active_check = active_check
        self._progress_callback = progress_callback
        self._phase: str | None = None
        self._phase_held = False
        self._provider_retry_lock = threading.Lock()
        self._details: dict[str, str | int] = {}
        self._lost = False
        self._background_error: BaseException | None = None
        self.report_planning = False
        self.provider_retry_callback: Callable[[], bool] | None = None
        self.cancellable_provider = False

    @property
    def remaining_seconds(self) -> float:
        return max((self.deadline_at - _utc()).total_seconds(), 0)

    def mark_lost(self) -> None:
        self._lost = True

    def mark_background_error(self, error: BaseException) -> None:
        self._background_error = error

    def claim_provider_retry(self) -> bool:
        with self._provider_retry_lock:
            self.ensure_active()
            return bool(self.provider_retry_callback and self.provider_retry_callback())

    def ensure_active(self) -> None:
        """Check local stop conditions and fresh durable ownership, without renewal."""
        self._check_local_state()
        with generation_timing("claim_check"):
            active = self._active_check()
        if not active:
            self._lost = True
            raise DeferredJobClaimLostError("Deferred job was cancelled or superseded.")
        # A database read can overlap the deadline or a heartbeat failure.
        self._check_local_state()

    def _check_local_state(self) -> None:
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

    def set_phase(self, phase: DeferredJobPhase | str, **details: object) -> None:
        if self._phase_held:
            self.ensure_active()
            return
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
        with generation_timing("progress_write"):
            self._progress_callback(
                {
                    "phase": phase,
                    **bounded,
                    "updated_at": _utc().isoformat(),
                }
            )
        self._phase = phase
        self._details = bounded

    @contextmanager
    def hold_phase(self, phase: DeferredJobPhase | str) -> Iterator[None]:
        """Parallel provider calls share one progress phase and retain cancellation checks."""
        self.set_phase(phase)
        previously_held = self._phase_held
        self._phase_held = True
        try:
            yield
        finally:
            self._phase_held = previously_held

    def before_provider(self, stage: str) -> None:
        self.set_phase(
            self._PROVIDER_PHASES.get(stage, DeferredJobPhase.GENERATING),
            provider_stage=stage,
        )

    def after_provider(self, _stage: str) -> None:
        self.ensure_active()

    def before_tool(self, _name: str) -> None:
        self.set_phase(DeferredJobPhase.USING_TOOLS)

    def after_tool(self, _name: str) -> None:
        self.ensure_active()




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
