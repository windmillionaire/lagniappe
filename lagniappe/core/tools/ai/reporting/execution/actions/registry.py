"""Action-type registry for deterministic execution and compensation."""

from ...contracts.actions import ALLOWED_ACTIONS, REPORT_ACTION_DATA_CONTRACTS
from .base import ReportActionAdapter
from .compensation import (
    _compensate_created,
    _compensate_created_task,
    _manual_compensation,
    _noop_compensation,
    _without_report,
)
from .entities import (
    _add_page_category,
    _add_form_to_page,
    _create_category,
    _create_form,
    _create_model_task,
    _create_page,
    _create_project,
    _suggest_page_deletion,
    _move_page,
    _move_task,
    _needs_review_action,
    _rename_entity,
    _skip_action,
)
from .files import (
    _attach_file,
    _move_file,
    _summarize_file,
)
from .forms import (
    _undo_form_schema_update,
    _undo_submission_updates,
    _extend_form_schema,
    _update_form_values,
)
from .compensation import (
    _undo_add_page_category_action,
    _undo_add_form_to_page_action,
    _undo_attachment_action,
    _undo_move_action,
    _undo_rename_entity,
    _undo_summarize_file,
)
from .tasks import _create_task
from .documents import _append_page_document, _undo_page_document
from .task_completion import _complete_task, _undo_complete_task

REPORT_ACTION_ADAPTERS = {
    adapter.action_type: adapter
    for adapter in (
        ReportActionAdapter("create_form", _create_form, _compensate_created),
        ReportActionAdapter("create_category", _create_category, _compensate_created),
        ReportActionAdapter("create_project", _create_project, _compensate_created),
        ReportActionAdapter(
            "create_model_task",
            _create_model_task,
            _compensate_created,
        ),
        ReportActionAdapter("create_page", _create_page, _compensate_created, uses_context=True),
        ReportActionAdapter("append_page_document", _append_page_document, _undo_page_document, uses_context=True),
        ReportActionAdapter("complete_task", _complete_task, _undo_complete_task, uses_context=True),
        ReportActionAdapter(
            "create_task",
            _create_task,
            _compensate_created_task,
            uses_context=True,
        ),
        ReportActionAdapter(
            "add_form_to_page",
            _add_form_to_page,
            _without_report(_undo_add_form_to_page_action),
        ),
        ReportActionAdapter(
            "add_page_category",
            _add_page_category,
            _without_report(_undo_add_page_category_action),
        ),
        ReportActionAdapter(
            "move_page", _move_page, _without_report(_undo_move_action)
        ),
        ReportActionAdapter(
            "move_task", _move_task, _without_report(_undo_move_action)
        ),
        ReportActionAdapter(
            "move_file", _move_file, _without_report(_undo_move_action)
        ),
        ReportActionAdapter(
            "rename_entity",
            _rename_entity,
            _without_report(_undo_rename_entity),
        ),
        ReportActionAdapter(
            "update_form_values",
            _update_form_values,
            _without_report(_undo_submission_updates),
        ),
        ReportActionAdapter(
            "extend_form_schema",
            _extend_form_schema,
            _without_report(_undo_form_schema_update),
        ),
        ReportActionAdapter(
            "attach_file",
            _attach_file,
            _without_report(_undo_attachment_action),
            required=True,
        ),
        ReportActionAdapter(
            "suggest_page_deletion", _suggest_page_deletion, _manual_compensation
        ),
        ReportActionAdapter(
            "summarize_file",
            _summarize_file,
            _without_report(_undo_summarize_file),
        ),
        ReportActionAdapter("skip", _skip_action, _noop_compensation),
        ReportActionAdapter("needs_review", _needs_review_action, _noop_compensation),
    )
}


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_report_action_registry_matches_proposal_contracts
# @matrix ai-report : action-registry contract
def validate_report_action_registry():
    if set(REPORT_ACTION_ADAPTERS) != set(REPORT_ACTION_DATA_CONTRACTS) or set(
        REPORT_ACTION_ADAPTERS
    ) != set(ALLOWED_ACTIONS):
        raise RuntimeError(
            "Report action contracts and lifecycle adapters are inconsistent."
        )


validate_report_action_registry()
