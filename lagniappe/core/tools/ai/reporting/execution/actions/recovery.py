"""Inspection and recoverable-error classification for report actions."""


from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.definitions import Action
from lagniappe.core.tools.database import get as database_get

from ...contracts.actions import DELETE_TARGETS
from .common import TASK_FORM_TYPE_ERROR
from .results import (
    _entity_result,
)
from .references import _fetch_report_entity, _file_attached_to_endpoint
from .task_completion import _completion_state
from .completed_tasks import (
    _task_state_fingerprint,
    _value_fingerprint,
)

ACTION_APPLIED = "applied"
ACTION_NOT_APPLIED = "not-applied"
ACTION_DRIFTED = "drifted"


def _recovery_entity_allowed(entity, user):
    if entity is None:
        return False
    return bool(entity.allowed(Action.EDIT, user=user))


def _stored_reference_key(entity, name):
    value = entity.db.get(name)
    return _urlsafe_key_value(value)


def _urlsafe_key_value(value):
    if not value:
        return None
    encoded = database_get.urlsafe_key(value)
    if encoded:
        return encoded
    legacy = getattr(value, "to_legacy_urlsafe", None)
    if callable(legacy):
        result = legacy()
        return result.decode() if isinstance(result, bytes) else str(result)
    return getattr(value, "name", None) or str(value)


def _inspect_action_applied(action, report, user, record):
    action_type = action.get("type")
    if record.get("status") == "skipped" or action_type in {
        "skip",
        "needs_review",
        "suggest_page_deletion",
    }:
        return ACTION_APPLIED

    if action_type in {"append_page_document", "replace_page_document"}:
        from .documents import inspect_document_append

        return inspect_document_append(record, user)

    expected = record.get("expected") or {}
    entity_id = expected.get("entity") or (record.get("entity") or {}).get("id")
    entity = _fetch_report_entity(entity_id) if entity_id else None
    if action_type.startswith("create_"):
        if action_type == "create_task" and expected.get("task"):
            task = _fetch_report_entity(expected["task"])
            if task is None or not _recovery_entity_allowed(task, user):
                return ACTION_DRIFTED
            fingerprint = expected.get("task_state_fingerprint")
            if fingerprint and _task_state_fingerprint(task) != fingerprint:
                return ACTION_DRIFTED
            return ACTION_APPLIED
        if entity is not None:
            if not _recovery_entity_allowed(entity, user):
                return ACTION_DRIFTED
            return ACTION_APPLIED
        output_key = record.get("output_key")
        if output_key:
            entity = _fetch_report_entity(output_key)
            if entity is not None:
                record["entity"] = _entity_result(entity)
                record["created"] = True
                record["expected"] = {
                    "entity": entity.urlsafe_key,
                    "target": None,
                }
                return ACTION_APPLIED
        return ACTION_NOT_APPLIED
    if not expected:
        return ACTION_NOT_APPLIED
    if action_type in DELETE_TARGETS:
        return ACTION_APPLIED if entity is None else ACTION_NOT_APPLIED
    if entity is None and entity_id:
        return ACTION_DRIFTED
    if entity is not None and not _recovery_entity_allowed(entity, user):
        return ACTION_DRIFTED

    if action_type in {"update_task", "update_page", "update_project", "update_category", "update_model_task", "update_file"}:
        from lagniappe.core.tools.entity_patches import _projection
        if entity is not None and _projection(entity) == expected.get("entity_update_after"):
            return ACTION_APPLIED
        # A later completion can advance the recurrence or archive this submission.
        # Its full post-completion fingerprint is the authoritative final state.
        records = (report.result or {}).get("actions", [])
        position = next((index for index, prior in enumerate(records) if prior.get("id") == record.get("id")), len(records))
        for later in records[position + 1:]:
            if later.get("type") == "complete_task" and later.get("status") == "complete" and (later.get("entity") or {}).get("id") == entity_id and (later.get("expected") or {}).get("task_state_fingerprint"):
                return _inspect_action_applied({"type": "complete_task"}, report, user, later)
        return ACTION_DRIFTED

    target_id = expected.get("target")
    target = _fetch_report_entity(target_id) if target_id else None
    if action_type == "move_task":
        return (
            ACTION_APPLIED
            if _stored_reference_key(entity, "page") == target_id
            else ACTION_DRIFTED
        )
    if action_type == "move_file":
        if target is None:
            return ACTION_DRIFTED
        source_id = ((record.get("before") or {}).get("source") or {}).get("id")
        source = _fetch_report_entity(source_id) if source_id else None
        if _file_attached_to_endpoint(entity, target) and (
            source is None or not _file_attached_to_endpoint(entity, source)
        ):
            return ACTION_APPLIED
        return ACTION_DRIFTED
    if action_type == "complete_task":
        if expected.get("task_state_fingerprint") and _task_state_fingerprint(entity) != expected["task_state_fingerprint"]:
            return ACTION_DRIFTED
        return ACTION_APPLIED if _completion_state(entity) == expected.get("completion_state") else ACTION_DRIFTED
    if action_type in {"update_form_schema"}:
        return (
            ACTION_APPLIED
            if entity is not None and _value_fingerprint(entity.schema or [])
            == expected.get("schema_fingerprint")
            else ACTION_DRIFTED
        )
    if action_type == "attach_file":
        if target is None:
            return ACTION_DRIFTED
        return (
            ACTION_APPLIED
            if _file_attached_to_endpoint(entity, target)
            else ACTION_DRIFTED
        )
    if action_type == "summarize_file":
        if not isinstance(entity, Entities.FILE):
            return ACTION_DRIFTED
        terms = entity.properties.summarize.retrieval_terms or []
        return (
            ACTION_APPLIED
            if entity.summary == expected.get("summary")
            and entity.properties.summarize.complete is True
            and isinstance(terms, (list, tuple)) and list(terms)
            == expected.get("retrieval_terms")
            and entity.properties.summarize.search is expected.get("search")
            else ACTION_DRIFTED
        )
    return ACTION_APPLIED


def _is_recoverable_action_error(_action, error):
    if isinstance(error, exceptions.MutationConflict):
        return False  # A rejected atomic write must remain retryable.
    if _action.get("type") in {"update_form_schema"}:
        return False
    if _action.get("type") in {"append_page_document", "replace_page_document"}:
        return False  # A document conflict must remain retryable, not be skipped.
    return isinstance(error, exceptions.ValidationError) and not str(error).startswith(
        "You do not have permission"
    )


def _record_required_file_placement_error(action_record, error):
    action_record["status"] = "failed"
    action_record["error"] = str(error)
    action_record["note"] = "This required file placement was not completed."


def _recoverable_action_error_note(action_record, message):
    if message == "Referenced report file was not found.":
        return "Skipped because a referenced report file was not found."
    if action_record.get("type") == "attach_file" and message.startswith("Referenced entity not found:"):
        return "Skipped because a referenced attachment target was not found."
    if action_record.get("type") == "create_task" and message == TASK_FORM_TYPE_ERROR:
        return (
            "Skipped because the action referenced a page form instead of a task form."
        )
    return "Skipped because this action could not be completed."


def _record_recoverable_action_error(action_record, error):
    message = str(error)
    action_record["status"] = "skipped"
    action_record["error"] = message
    action_record["note"] = _recoverable_action_error_note(action_record, message)
