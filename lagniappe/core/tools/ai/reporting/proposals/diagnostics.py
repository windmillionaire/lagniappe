"""Bounded diagnostic projections for AI report proposals."""

from .references import _proposal_string


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::generate_organize_report
# @reason debug-only proposal summary is not behavior-bearing
def _proposal_debug_summary(proposal):
    if not isinstance(proposal, dict):
        return {"proposal_type": type(proposal).__name__}

    actions = proposal.get("actions") or []
    return {
        "summary_present": bool(proposal.get("summary")),
        "issue_count": len(proposal.get("issues") or []),
        "issues": proposal.get("issues") or [],
        "action_count": len(actions) if isinstance(actions, list) else None,
        "actions": [
            _proposal_action_debug_summary(action)
            for action in actions
            if isinstance(action, dict)
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/diagnostics.py::_proposal_debug_summary
# @reason debug-only action summary is not behavior-bearing
def _proposal_action_debug_summary(action):
    data = action.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    submission = data.get("submission")
    schema = data.get("schema")
    operations = data.get("operations")
    return {
        "id": action.get("id"),
        "type": action.get("type"),
        "display_label": action.get("display_label"),
        "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "schema_field_count": len(schema) if isinstance(schema, list) else None,
        "schema_fields": (
            [_schema_field_debug_summary(field) for field in schema]
            if isinstance(schema, list)
            else None
        ),
        "schema_operations": (
            [_schema_operation_debug_summary(operation) for operation in operations]
            if isinstance(operations, list)
            else None
        ),
        "page": _debug_ref(data, "page"),
        "project": _debug_ref(data, "project"),
        "model": _debug_ref(data, "model"),
        "form": _debug_ref(data, "form"),
        "completed": data.get("completed") is True,
        "completed_on": data.get("completed_on") or data.get("completed-on"),
        "file_refs": _debug_file_refs(data),
        "submission_key_present": "submission" in data,
        "submission_field_count": (
            len(submission) if isinstance(submission, dict) else None
        ),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/diagnostics.py::_proposal_action_debug_summary
# @reason compact schema diagnostics are exercised through failed-repair capture tests
def _schema_field_debug_summary(field):
    if not isinstance(field, dict):
        return {"field_type": type(field).__name__}
    return {
        "id": field.get("id"),
        "type": field.get("type"),
        "input": field.get("input"),
        "title_present": bool(_proposal_string(field.get("title"))),
        "label_present": bool(_proposal_string(field.get("label"))),
        "keys": sorted(field),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/diagnostics.py::_proposal_action_debug_summary
# @reason compact schema diagnostics are exercised through failed-repair capture tests
def _schema_operation_debug_summary(operation):
    if not isinstance(operation, dict):
        return {"operation_type": type(operation).__name__}
    return {
        "op": operation.get("op") or operation.get("type"),
        "schema_id": operation.get("schema_id") or operation.get("field_id"),
        "field": _schema_field_debug_summary(operation.get("field")),
        "option_keys": (
            sorted(operation["option"])
            if isinstance(operation.get("option"), dict)
            else None
        ),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/diagnostics.py::_proposal_action_debug_summary
# @reason debug-only reference summary is not behavior-bearing
def _debug_ref(data, name):
    return (
        data.get(name)
        or data.get(f"{name}_id")
        or data.get(f"{name}_ref")
        or data.get(f"{name}_action")
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/diagnostics.py::_proposal_action_debug_summary
# @reason debug-only file reference summary is not behavior-bearing
def _debug_file_refs(data):
    refs = []
    for key in ("file", "file_id", "file_ref"):
        value = data.get(key)
        if value:
            refs.append(value)
    files = data.get("files") or data.get("file_ids") or data.get("file_refs") or []
    if isinstance(files, str):
        refs.append(files)
    elif isinstance(files, list):
        refs.extend(files)
    return refs
