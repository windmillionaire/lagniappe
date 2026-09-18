"""Supported forward-only report actions."""
from ...contracts.actions import ALLOWED_ACTIONS, REPORT_ACTION_DATA_CONTRACTS
from ...entity_updates import UPDATE_TARGETS, execute_update_action
from .base import ReportActionAdapter
from .entities import _create_form, _create_category, _create_project, _create_model_task, _create_page, _move_task, _suggest_page_deletion, _skip_action, _needs_review_action
from .files import _attach_file, _move_file, _summarize_file
from .forms import _update_form_schema
from .tasks import _create_task
from .documents import _append_page_document
from .task_completion import _complete_task

REPORT_ACTION_ADAPTERS = {adapter.action_type: adapter for adapter in (
    *(ReportActionAdapter(name, execute_update_action, uses_context=True) for name in UPDATE_TARGETS),
    ReportActionAdapter("create_form", _create_form),
    ReportActionAdapter("create_category", _create_category),
    ReportActionAdapter("create_project", _create_project),
    ReportActionAdapter("create_model_task", _create_model_task),
    ReportActionAdapter("create_page", _create_page, uses_context=True),
    ReportActionAdapter("create_task", _create_task, uses_context=True),
    ReportActionAdapter("append_page_document", _append_page_document, uses_context=True),
    ReportActionAdapter("complete_task", _complete_task, uses_context=True),
    ReportActionAdapter("move_task", _move_task),
    ReportActionAdapter("move_file", _move_file),
    ReportActionAdapter("update_form_schema", _update_form_schema, uses_context=True),
    ReportActionAdapter("attach_file", _attach_file, required=True),
    ReportActionAdapter("suggest_page_deletion", _suggest_page_deletion),
    ReportActionAdapter("summarize_file", _summarize_file),
    ReportActionAdapter("skip", _skip_action),
    ReportActionAdapter("needs_review", _needs_review_action),
)}

# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_report_action_registry_matches_proposal_contracts
# @matrix ai-report : action-registry contract
def validate_report_action_registry():
    if set(REPORT_ACTION_ADAPTERS) != set(REPORT_ACTION_DATA_CONTRACTS) or set(REPORT_ACTION_ADAPTERS) != set(ALLOWED_ACTIONS):
        raise RuntimeError("Report action contracts and lifecycle adapters are inconsistent.")

validate_report_action_registry()

# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason forward dispatch is exercised through deterministic report execution
def report_action_adapter(action_type):
    return REPORT_ACTION_ADAPTERS[action_type]


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason required placement failures are asserted through full report execution
def _is_required_file_placement(action):
    adapter = REPORT_ACTION_ADAPTERS.get(action.get("type"))
    return bool(adapter and adapter.required)
