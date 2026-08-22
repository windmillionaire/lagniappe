"""Action-type registry for deterministic execution and compensation."""

from ...contracts.actions import ALLOWED_ACTIONS, REPORT_ACTION_DATA_CONTRACTS
from .base import ReportActionAdapter
from .compensation import (
    _compensate_created,
    _compensate_created_task,
    _manual_compensation,
    _noop_compensation,
    _undo_result_action,
    _without_report,
)
from .entities import (
    _add_category,
    _add_form_to_page,
    _create_category,
    _create_form,
    _create_model_task,
    _create_page,
    _create_project,
    _manual_delete_page_action,
    _move_page,
    _move_task,
    _needs_review_action,
    _rename_entity,
    _skip_action,
)
from .files import (
    _attach_file_to_page,
    _attach_file_to_task,
    _move_file,
    _summarize_file,
)
from .forms import (
    _undo_form_schema_update,
    _undo_submission_updates,
    _update_form_schema,
    _update_submission_fields,
)
from .compensation import (
    _undo_add_category_action,
    _undo_add_form_to_page_action,
    _undo_attachment_action,
    _undo_move_action,
    _undo_rename_entity,
    _undo_summarize_file,
)
from .tasks import _create_task

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
        ReportActionAdapter("create_page", _create_page, _compensate_created),
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
            "add_category",
            _add_category,
            _without_report(_undo_add_category_action),
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
            "update_submission_fields",
            _update_submission_fields,
            _without_report(_undo_submission_updates),
        ),
        ReportActionAdapter(
            "update_form_schema",
            _update_form_schema,
            _without_report(_undo_form_schema_update),
        ),
        ReportActionAdapter(
            "attach_file_to_page",
            _attach_file_to_page,
            _without_report(_undo_attachment_action),
            required=True,
        ),
        ReportActionAdapter(
            "attach_file_to_task",
            _attach_file_to_task,
            _without_report(_undo_attachment_action),
            required=True,
        ),
        ReportActionAdapter(
            "delete_page", _manual_delete_page_action, _manual_compensation
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
# @pair ai-report:action-registry
# @pair ai-report:contract
def validate_report_action_registry():
    if set(REPORT_ACTION_ADAPTERS) != set(REPORT_ACTION_DATA_CONTRACTS) or set(
        REPORT_ACTION_ADAPTERS
    ) != set(ALLOWED_ACTIONS):
        raise RuntimeError(
            "Report action contracts and lifecycle adapters are inconsistent."
        )


validate_report_action_registry()
