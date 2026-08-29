"""Base strategy contract shared by deferred-job domain adapters."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import DeferredJobInspection

from lagniappe.core.properties.deferred_job_request import Inputs
from ..common import _load_reference
from ..errors import DeferredJobDriftError




# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_adapters_declare_required_ai_tiers
# @matrix ai-access deferred-jobs : tier-declaration
class DeferredJobAdapter:
    """Domain boundary plugged into the shared job lifecycle."""

    job_type = None
    synchronous_testing = False
    required_ai_access = None
    mutation_inputs = ()
    queued_message = "Working..."
    retry_message = "Work is temporarily delayed; retrying shortly..."
    dependency_message = "Waiting for required background work..."
    active_message = (
        "Still working. This is taking longer than usual; we'll keep trying."
    )
    success_message = "Work is ready."
    failure_prefix = "Work failed."
    notification_policy = "pending"

    # @testable infrastructure
    def authorization(self, spec):
        authorization = {
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

    # @testable infrastructure
    def load(self, context):
        context.inputs = {
            name: _load_reference(reference)
            for name, reference in context.inputs.items()
        }
        return context

    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_ai_adapters_reject_restricted_actor_before_prepare
    # @matrix ai : access-gate authorization provider-boundary
    # @pair deferred-jobs:authorization
    def authorize(self, context):
        required = self.required_ai_access
        if required and not getattr(
            context.actor,
            "access",
            lambda _required: False,
        )(required):
            raise exceptions.ValidationError(
                "This user does not have the required AI access."
            )

    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_rejects_changed_target_fingerprint_before_apply
    # @matrix deferred-jobs : no-apply target-fingerprint
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
    def terminal_message(self, context, *, succeeded, error=None):
        if succeeded:
            return self.success_message
        message = str(error or "").strip()
        return f"{self.failure_prefix} {message}".strip()

    # @testable infrastructure
    def notification_target(self, context):
        return None

    # @testable true
    # @tests tests_unit/test_028_ai_email.py::test_report_terminal_feedback_uses_generic_notification_delivery
    # @matrix ai-email : generic-delivery terminal-delivery
    def external_delivery_required(self, context):
        """Return whether this terminal job owns an external delivery step."""
        return False

    # @testable infrastructure
    def external_delivery(self, context, *, succeeded, error=None):
        return None
