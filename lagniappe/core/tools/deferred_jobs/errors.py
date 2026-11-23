"""Deferred-job orchestration and domain-boundary errors."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...entities.deferred_job import DeferredJob

from lagniappe.core import exceptions




class DeferredJobInfrastructureError(RuntimeError):
    """The delivery should be retried because orchestration could not persist."""




class DeferredJobClaimLostError(DeferredJobInfrastructureError):
    """The current worker no longer owns an existing deferred job."""




class DeferredJobDeadlineError(RuntimeError):
    """One attempt reached its bounded execution deadline."""




class DeferredJobDependencyPendingError(RuntimeError):
    """A required background dependency has not completed yet."""




class DeferredJobDependencyFailedError(exceptions.ValidationError):
    """A required background dependency cannot complete successfully."""




class DeferredJobDriftError(exceptions.ValidationError):
    """Prepared job state no longer matches the durable domain state."""




# @testable infrastructure
class DeferredJobLockedError(exceptions.ValidationError):
    """A target-scoped operation already owns the requested mutation surface."""

    def __init__(self, job: DeferredJob) -> None:
        super().__init__("Autofill is already running for this form.")
        self.job = job
