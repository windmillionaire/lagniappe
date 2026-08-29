"""Loaded entity context passed through one deferred-job adapter."""

from collections.abc import Callable
from dataclasses import dataclass

from .common import _json_copy
from .errors import DeferredJobClaimLostError


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

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/runner.py::DeferredJobRunner.run
    def set_phase(self, phase, **details):
        """Persist a bounded user-visible phase for this claimed job."""
        if self.execution_control is not None:
            self.execution_control.set_phase(phase, **details)

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/runner.py::DeferredJobRunner.run
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
