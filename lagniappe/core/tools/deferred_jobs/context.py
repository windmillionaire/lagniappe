"""Loaded entity context passed through one deferred-job adapter."""

from collections.abc import Mapping

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, overload

from lagniappe.core import exceptions

if TYPE_CHECKING:
    from lagniappe.core.definitions import DeferredJobPhase
    from lagniappe.core.entities.ai_report import AIReport
    from lagniappe.core.entities.file import File
    from lagniappe.core.entities.form import Form
    from lagniappe.core.entities.page import Page
    from lagniappe.core.entities.task import Task
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.deferred_job import DeferredJob
    from lagniappe.core.entities.notification import Notification
    from lagniappe.core.entities.user import User
    from .control import DeferredExecutionControl

from .common import _json_copy
from .errors import DeferredJobClaimLostError


@dataclass
class DeferredJobContext:
    job: DeferredJob
    actor: User
    notification: Notification | None
    inputs: dict
    parameters: dict
    checkpoint: dict
    active_check: Callable[[], bool] | None = None
    execution_control: DeferredExecutionControl | None = None
    checkpoint_callback: Callable[..., None] | None = None

    @overload
    def input(self, name: Literal["file"], default: None = None) -> File | None: ...
    @overload
    def input(self, name: Literal["report"], default: None = None) -> AIReport | None: ...
    @overload
    def input(self, name: Literal["form"], default: None = None) -> Form | None: ...
    @overload
    def input(self, name: Literal["target"], default: None = None) -> Page | Task | None: ...
    @overload
    def input(self, name: str, default: Entity | None = None) -> Entity | None: ...
    def input(self, name: str, default: Entity | None = None) -> Entity | None:
        return self.inputs.get(name, default)

    def ensure_active(self) -> None:
        """Stop domain writes after cancellation or lease replacement."""
        if self.execution_control is not None:
            self.execution_control.ensure_active()
            return
        if self.active_check is not None and not self.active_check():
            raise DeferredJobClaimLostError("Deferred job was cancelled or superseded.")

    def set_phase(self, phase: str | DeferredJobPhase, **details: object) -> None:
        """Persist a bounded user-visible phase for this claimed job."""
        if self.execution_control is not None:
            self.execution_control.set_phase(phase, **details)

    def checkpoint_stage(self, stage: str | DeferredJobPhase, payload: Mapping[str, object] | None = None, **progress: object) -> dict[str, object]:
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


@overload
def required_input(context: DeferredJobContext, name: Literal["file"]) -> File: ...
@overload
def required_input(context: DeferredJobContext, name: Literal["report"]) -> AIReport: ...
@overload
def required_input(context: DeferredJobContext, name: Literal["form"]) -> Form: ...
@overload
def required_input(context: DeferredJobContext, name: Literal["target"]) -> Page | Task: ...


def required_input(context: DeferredJobContext, name: str) -> Entity:
    """Read a mandatory loaded input after its adapter has authorized its kind."""
    entity = context.input(name)
    if entity is None:
        raise exceptions.ValidationError(f"Missing required deferred job input: {name}")
    return entity
