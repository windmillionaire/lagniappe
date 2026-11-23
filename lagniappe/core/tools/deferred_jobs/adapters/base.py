"""Base strategy contract shared by deferred-job domain adapters."""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from lagniappe.core import exceptions
from lagniappe.core.definitions import DeferredJobSpec, DeferredJobType
from ..context import DeferredJobContext

if TYPE_CHECKING:
    from google.cloud.datastore import Key
    from lagniappe.core.entities.deferred_job import DeferredJob
    from lagniappe.core.entities.deferred_job_lock import DeferredJobLock
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.user import User
    from lagniappe.core.tools.database.utility import ExactEntityState
from lagniappe.core.definitions import DeferredJobInspection

from lagniappe.core.properties.deferred_job_request import Inputs


from ..common import _load_reference
from ..errors import DeferredJobDriftError


type StartWrites = tuple[Sequence[tuple[Entity, tuple[str, ...] | None]], Sequence[tuple[Key, Mapping[str, object] | ExactEntityState | None]]]


class DeferredJobAdapter:
    """Domain boundary plugged into the shared job lifecycle."""

    job_type: DeferredJobType | None = None
    synchronous_testing = False
    required_ai_access = None
    mutation_inputs: tuple[str, ...] = ()
    queued_message = "Working..."
    retry_message = "Work is temporarily delayed; retrying shortly..."
    dependency_message = "Waiting for required background work..."
    # Seconds between dependency checks; repeat the final delay for longer waits.
    dependency_retry_delays = (60,)
    active_message = (
        "Still working. This is taking longer than usual; we'll keep trying."
    )
    success_message = "Work is ready."
    failure_prefix = "Work failed."
    notification_policy = "pending"
    max_lifetime_seconds = None
    resume_preparation = True
    cancellable_provider = False

    def authorization(self, spec: DeferredJobSpec) -> dict[str, object]:
        assert self.job_type is not None
        authorization: dict[str, object] = {
            "policy": self.job_type.value,
            "actor": spec.actor.urlsafe_key,
            "inputs": Inputs.serialize(spec.inputs),
        }
        fingerprints = {
            name: getattr(spec.inputs.get(name), "fingerprint", None)
            for name in self.mutation_inputs
            if spec.inputs.get(name) is not None
        }
        if fingerprints:
            authorization["fingerprints"] = fingerprints
        return authorization

    def load(self, context: DeferredJobContext) -> DeferredJobContext:
        context.inputs = {
            name: _load_reference(reference)
            for name, reference in context.inputs.items()
        }
        return context

    def authorize(self, context: DeferredJobContext) -> None:
        required = self.required_ai_access
        if required and not getattr(
            context.actor,
            "access",
            lambda _required: False,
        )(required):
            raise exceptions.ValidationError(
                "This user does not have the required AI access."
            )

    def validate_apply(self, context: DeferredJobContext) -> None:
        """Reject generated output when an apply target changed in the queue."""
        expected = (context.job.authorization or {}).get("fingerprints") or {}
        if not isinstance(expected, dict):
            raise DeferredJobDriftError("The saved job fingerprint data is invalid.")
        for name in self.mutation_inputs:
            target = context.input(name)
            if target is None:
                continue
            if expected.get(name) != getattr(target, "fingerprint", None):
                raise DeferredJobDriftError(
                    "The target changed while this operation was running."
                )

    def prepare(self, context: DeferredJobContext) -> Mapping[str, object] | None:
        return {}

    def checkpoint_ready(self, context: DeferredJobContext) -> bool:
        """Return whether preparation has produced its final apply checkpoint."""
        return bool(context.checkpoint)

    def started(self, context: DeferredJobContext) -> None:
        """Persist domain metadata after the job exists and before dispatch."""
        return None

    def start_lock(self, spec: DeferredJobSpec, job: DeferredJob) -> DeferredJobLock | None:
        """Return an optional target-scoped lock created with the job."""
        return None

    def start_writes(self, spec: DeferredJobSpec, job: DeferredJob) -> StartWrites:
        """Optional guarded domain writes committed atomically with job creation."""
        return (), ()

    def before_cancel(self, job: DeferredJob) -> None:
        """Allow domains with partially applied work to retain their write fence."""
        return None

    def can_view_status(self, job: DeferredJob, actor: User) -> bool:
        """Authorize a non-owner for the bounded browser status projection."""
        return False

    def inspect(self, context: DeferredJobContext) -> DeferredJobInspection:
        return DeferredJobInspection.NOT_APPLIED

    def committed_result(self, job: DeferredJob) -> dict[str, object] | None:
        """Return an atomically committed result, or None if work is unfinished."""
        return None

    def apply(self, context: DeferredJobContext) -> Mapping[str, object] | None:
        raise NotImplementedError

    def cleanup(self, context: DeferredJobContext, *, terminal: bool) -> None:
        return None

    def failure(self, context: DeferredJobContext, error: BaseException | str) -> None:
        return None

    def terminal_message(self, context: DeferredJobContext, *, succeeded: bool, error: BaseException | str | None = None) -> str:
        if succeeded:
            return self.success_message
        message = str(error or "").strip()
        return f"{self.failure_prefix} {message}".strip()

    def notification_target(self, context: DeferredJobContext) -> Entity | None:
        return None

    def external_delivery_required(self, context: DeferredJobContext) -> bool:
        """Return whether this terminal job owns an external delivery step."""
        return False

    def external_delivery(self, context: DeferredJobContext, *, succeeded: bool, error: BaseException | str | None = None) -> dict[str, object] | None:
        return None
