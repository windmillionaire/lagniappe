"""Task creation report action."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities

from ....debug import ai_debug
from ...schedules import apply_task_schedule
from .completed_tasks import (
    _is_completed_task_event,
    _model_task_form,
    _record_completed_task_event,
)
from .common import (
    TASK_FORM_TYPE_ERROR,
    _data,
    _first_data_reference,
    _require_allowed,
    _require_form_type,
    _unique_entities,
)
from .results import (
    _capture_missing_task_submission,
    _diagnostic_entity,
    _diagnostic_file_refs,
    _entity_result,
    _submission_result,
    _task_structure_result,
)
from .references import (
    _resolve_action_page,
    _resolve_entity,
)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_warns_but_continues_when_task_form_submission_missing
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_skips_task_that_references_page_form_and_continues
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_attach_file_to_task_targets_created_task
# @pair ai-report:task-form
# @pair ai-report:completed-task
# @pair ai-report:continue
# @pair ai-report:deterministic-run
# @pair tasks:task-form
# @pair tasks:completed-task
# @pair tasks:continue
# @pair tasks:deterministic-run
# @pair tasks:missing-submission
# @pair tasks:recoverable
# @pair task-completion:task-form
# @pair task-completion:completed-task
# @pair task-completion:continue
# @pair ai-report:missing-submission
# @pair task-completion:missing-submission
# @pair ai-report:mismatched-form
# @pair tasks:mismatched-form
# @pair forms:continue
# @pair forms:deterministic-run
# @pair forms:mismatched-form
# @pair forms:recoverable
# @pair ai-report:submission-completion
# @pair ai-report:persistence
def _create_task(action, _report, user, created, context=None):
    data = _data(action)
    page = _resolve_action_page(data, created, user)
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to create tasks on this page.",
    )
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
        optional=True,
    )
    project = _resolve_entity(
        data.get("project")
        or data.get("project_id")
        or data.get("project_ref")
        or data.get("project_action"),
        created,
        expected=Entities.PROJECT,
        optional=True,
    )
    model = _resolve_entity(
        data.get("model")
        or data.get("model_id")
        or data.get("model_ref")
        or data.get("model_action"),
        created,
        expected=Entities.MODEL_TASK,
        optional=True,
    )
    form = form or _model_task_form(model)
    _require_form_type(form, "task", TASK_FORM_TYPE_ERROR)
    ai_debug(
        "report_runner.create_task.resolved",
        report=_diagnostic_entity(_report),
        action={
            "id": action.get("id"),
            "type": action.get("type"),
            "display_label": action.get("display_label"),
            "data_keys": sorted(data.keys()),
            "completed": _is_completed_task_event(data),
            "submission_key_present": "submission" in data,
            "submission_field_count": (
                len(data.get("submission"))
                if isinstance(data.get("submission"), dict)
                else None
            ),
        },
        page=_diagnostic_entity(page),
        project=_diagnostic_entity(project),
        model=_diagnostic_entity(model),
        form=_diagnostic_entity(form),
        files=_diagnostic_file_refs(data),
    )
    if _is_completed_task_event(data):
        return _record_completed_task_event(
            action,
            data,
            page,
            form,
            project,
            model,
            _report,
            user,
            created,
            context,
        )

    task = Entities.TASK.create(
        {
            "page": page,
            "name": data.get("name") or "Generated task",
            "description": data.get("description"),
            "form": form,
            "project": project,
            "model": model,
            "due_date": data.get("due_date") or data.get("due-date"),
        }
    )
    if form is not None and "submission" in data:
        task.ai_submission(data.get("submission") or {})
    if data.get("schedule") is not None:
        metadata_schedule = apply_task_schedule(task, data["schedule"])
    else:
        metadata_schedule = None

    metadata = _task_structure_result(task)
    metadata["page"] = _entity_result(page)
    if metadata_schedule is not None:
        metadata["schedule"] = metadata_schedule
    if "submission" in data:
        metadata["submission"] = _submission_result(
            task,
            data.get("submission_empty_reason"),
        )
    ai_debug(
        "report_runner.create_task.created",
        task=_diagnostic_entity(task),
        form=_diagnostic_entity(form),
        submission=_submission_result(task),
    )
    return task, _unique_entities([task, page]), metadata
