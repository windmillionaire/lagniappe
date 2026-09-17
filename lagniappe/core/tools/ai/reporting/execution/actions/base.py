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

    # @testable infrastructure
    def apply(self, action, report, user, created, context):
        return _execute_action(action, report, user, created, context)

    # @testable infrastructure
    def _apply(self, action, report, user, created, context):
        arguments = (action, report, user, created)
        if self.uses_context:
            return _normalize_handler_result(
                self.apply_handler(*arguments, context or {})
            )
        return _normalize_handler_result(self.apply_handler(*arguments))



# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason action dispatch is exercised through deterministic report-run tests
def _normalize_handler_result(result):
    if len(result) == 2:
        entity, to_save = result
        return entity, to_save, {}
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason action dispatch is exercised through deterministic report-run tests
def _execute_action(action, report, user, created, context=None):
    from .registry import report_action_adapter

    adapter = report_action_adapter(action["type"])
    return adapter._apply(action, report, user, created, context or {})
