"""Adapter protocol for deterministic report actions."""

from .checkpoints import _prepare_action_checkpoint
from .recovery import _inspect_action_applied

ACTION_APPLIED = "applied"
ACTION_NOT_APPLIED = "not-applied"
ACTION_DRIFTED = "drifted"


# @testable infrastructure
class ReportActionAdapter:
    """Recovery contract for one deterministic report action type."""

    def __init__(
        self,
        action_type,
        apply_handler,
        *,
        uses_context=False,
        required=False,
    ):
        self.action_type = action_type
        self.apply_handler = apply_handler
        self.uses_context = uses_context
        self.required = required

    # @testable infrastructure
    def prepare(self, action, report, user, created, context, record):
        return _prepare_action_checkpoint(
            action,
            report,
            user,
            created,
            context,
            record,
        )

    # @testable infrastructure
    def inspect_applied(self, action, report, user, record):
        return _inspect_action_applied(action, report, user, record)

    # @testable true
    # @tests tests_unit/test_020h_ai_report_execution.py::test_report_action_registry_matches_proposal_contracts
    # @matrix ai-report : action-registry contract
    def apply(self, action, report, user, created, context):
        arguments = (action, report, user, created)
        if self.uses_context:
            return _normalize_handler_result(
                self.apply_handler(*arguments, context or {})
            )
        return _normalize_handler_result(self.apply_handler(*arguments))



# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/base.py::ReportActionAdapter.apply
# @reason handler result normalization is exercised through the adapter contract
def _normalize_handler_result(result):
    if len(result) == 2:
        entity, to_save = result
        return entity, to_save, {}
    return result
