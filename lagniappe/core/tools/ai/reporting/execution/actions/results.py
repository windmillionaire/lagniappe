"""Bounded action results, diagnostics, and created-entity bookkeeping."""

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities

from ....debug import ai_debug
from .common import _safe_entity_relation, _stored_relation_key


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason result diagnostics are asserted through deterministic run results
def _file_summary_result(file):
    summarize = getattr(getattr(file, "properties", None), "summarize", None)
    result = {
        "enabled": bool(getattr(summarize, "enabled", False)),
        "complete": bool(getattr(summarize, "complete", False)),
        "present": bool(getattr(file, "summary", None)),
    }
    status = getattr(summarize, "status", None)
    error = getattr(summarize, "error", None)
    if status:
        result["status"] = status
    if error:
        result["error"] = error
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/tasks.py::_create_task
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason task structure diagnostics are asserted through deterministic run results
def _task_structure_result(task, project=None, model=None, form=None):
    result = {}
    project = project or _safe_entity_relation(task, "project")
    model = model or _safe_entity_relation(task, "model")
    form = form or _safe_entity_relation(task, "form")
    if project is not None:
        result["project"] = _entity_result(project)
    if model is not None:
        result["model"] = _entity_result(model, parent=project)
    if form is not None:
        result["form"] = _entity_result(form)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason submission diagnostics are asserted through deterministic run results
def _submission_result(entity, empty_reason=None):
    submission = getattr(entity, "submission", None)
    field_count = len(submission) if isinstance(submission, dict) else 0
    result = {
        "created": field_count > 0,
        "field_count": field_count,
    }
    if empty_reason and field_count == 0:
        result["empty_reason"] = empty_reason
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/completed_tasks.py::_record_completed_task_event
# @reason telemetry is provider-facing; behavior is covered by runner result tests
def _capture_missing_task_submission(action, data, report, page, project, model, form):
    ai_debug(
        "report_runner.create_task.missing_submission",
        report=_diagnostic_entity(report),
        action={
            "id": action.get("id"),
            "type": action.get("type"),
            "display_label": action.get("display_label"),
            "data_keys": sorted((data or {}).keys()),
            "completed_on": (
                data.get("completed_on")
                or data.get("completed-on")
                or data.get("completed")
            ),
        },
        page=_diagnostic_entity(page),
        project=_diagnostic_entity(project),
        model=_diagnostic_entity(model),
        form=_diagnostic_entity(form),
        form_schema=_diagnostic_schema(form),
        files=_diagnostic_file_refs(data),
    )
    exceptions.capture(
        "AI report create_task used a task form but omitted submission data.",
        context={
            "ai_report_runner": {
                "operation": "create_task_missing_submission",
                "report": _diagnostic_entity(report),
                "action": {
                    "id": action.get("id"),
                    "type": action.get("type"),
                    "display_label": action.get("display_label"),
                    "data_keys": sorted((data or {}).keys()),
                    "completed_on": (
                        data.get("completed_on")
                        or data.get("completed-on")
                        or data.get("completed")
                    ),
                    "submission_key_present": "submission" in data,
                },
                "page": _diagnostic_entity(page),
                "project": _diagnostic_entity(project),
                "model": _diagnostic_entity(model),
                "form": _diagnostic_entity(form),
                "form_schema": _diagnostic_schema(form),
                "files": _diagnostic_file_refs(data),
            }
        },
        level="warning",
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/results.py::_capture_missing_task_submission
# @reason compact diagnostic projection is exercised through runner telemetry
def _diagnostic_entity(entity):
    if entity is None:
        return None
    details = {
        "kind": getattr(entity, "kind", None),
        "name": getattr(entity, "name", None),
        "hash": getattr(entity, "hash", None),
        "id": getattr(entity, "urlsafe_key", None),
        "key": str(getattr(entity, "key", "")) or None,
    }
    form_type = getattr(entity, "form_type", None)
    if form_type:
        details["form_type"] = form_type
    return details


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/results.py::_capture_missing_task_submission
# @reason compact diagnostic projection is exercised through runner telemetry
def _diagnostic_schema(form):
    schema = getattr(form, "schema", None) or []
    fields = []
    for field in schema:
        if not isinstance(field, dict):
            continue
        fields.append(
            {
                "id": field.get("id"),
                "type": field.get("type"),
                "input": field.get("input"),
                "title": field.get("title") or field.get("label"),
            }
        )
    return fields


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/results.py::_capture_missing_task_submission
# @reason compact diagnostic projection is exercised through runner telemetry
def _diagnostic_file_refs(data):
    files = []
    if data.get("file"):
        files.append(data.get("file"))
    files.extend(data.get("files") or [])
    return files


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason created-reference bookkeeping is verified through ordered runner tests
def _remember_created(created, action, entity):
    for key in [action.get("id"), entity.key, entity.urlsafe_key]:
        if key:
            created[key] = entity


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason attachment target serialization is verified through report run outputs
def _attachment_target_result(action, to_save):
    if action.get("type") not in {"attach_file_to_page", "attach_file_to_task"}:
        return None
    if len(to_save) < 2:
        return None
    return _entity_result(to_save[1])


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason attachment metadata is verified through grouped result tests
def _action_attachment_results(action, to_save):
    return []


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason result serialization is exercised through report run outputs
def _entity_result(entity, parent=None):
    result = {
        "id": entity.urlsafe_key,
        "kind": entity.kind,
        "name": _entity_result_name(entity),
    }
    if (
        isinstance(entity, Entities.MODEL_TASK)
        or getattr(entity, "kind", None) == "model"
    ):
        parent = parent or _safe_entity_relation(entity, "project")
        if parent is not None:
            result["parent"] = _entity_result(parent)
        else:
            project_key = _stored_relation_key(entity, "project")
            if project_key:
                exceptions.capture(
                    "AI report serialized a model task without its project attached.",
                    context={
                        "ai_report_runner": {
                            "operation": "model_task_project_relation_missing",
                            "model": _diagnostic_entity(entity),
                            "project_key": str(project_key),
                        }
                    },
                    level="warning",
                )
    try:
        result["url"] = entity.url
    except Exception:
        pass
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/results.py::_entity_result
# @reason fallback naming is exercised through task-history report results
def _entity_result_name(entity):
    try:
        name = entity.name
    except AttributeError:
        name = None
    return name or "Task history"
