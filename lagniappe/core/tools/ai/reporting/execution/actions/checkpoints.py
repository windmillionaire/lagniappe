"""Before-state and post-commit checkpoints for report actions."""

import copy

from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility

from .results import (
    _action_attachment_results,
    _attachment_target_result,
    _entity_result,
    _remember_created,
)
from .common import (
    _data,
    _first_data_reference,
)
from .references import (
    _file_attached_to_endpoint,
    _load_result_entity,
    _reference_key,
    _resolve_action_page,
    _resolve_entity,
    _resolve_file_endpoint,
    _resolve_file_entity,
    _resolve_report_file,
)
from .forms import _resolve_submission_update_entity, _submission_previous_value
from .completed_tasks import (
    _capture_completed_task_before,
    _completed_event_belongs_in_history,
    _is_completed_task_event,
    _parse_completed_task_completed_on,
    _should_archive_live_completion,
    _snapshot_entity,
    _task_state_fingerprint,
    _value_fingerprint,
)


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @matrix ai-report : create idempotency post-commit-checkpoint recovery
def _allocate_action_output_key(action, created, context):
    action_type = action.get("type")
    if not action_type.startswith("create_"):
        return None
    if action_type == "create_task" and _is_completed_task_event(_data(action)):
        return None
    kind = {
        "create_form": "form",
        "create_category": "category",
        "create_project": "project",
        "create_model_task": "model",
        "create_page": "page",
        "create_task": "task",
    }.get(action_type)
    if not kind:
        return None

    parent = None
    if action_type == "create_model_task":
        data = _data(action)
        reference = _reference_key(
            data.get("project")
            or data.get("project_id")
            or data.get("project_ref")
            or data.get("project_action")
        )
        parent_entity = created.get(reference)
        if parent_entity is not None:
            parent = parent_entity.key
        else:
            parent_record = context.get("action_records", {}).get(reference) or {}
            parent = context.setdefault("prepared_keys", {}).get(
                parent_record.get("idempotency_key")
            )
            if parent is None and parent_record.get("output_key"):
                parent = database_get.datastore_key(parent_record["output_key"])
            if parent is None:
                parent = database_get.datastore_key(reference)

    return database_utility.create_key(kind, parent)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason action checkpoints are asserted through public compensation behavior
def _capture_action_before(action, report, user, created, context=None):
    action_type = action.get("type")
    data = _data(action)
    if action_type == "create_task" and _is_completed_task_event(data):
        return _capture_completed_task_before(
            action,
            data,
            user,
            created,
        )
    if action_type.startswith("create_"):
        return {"entity_exists": False}
    if action_type == "add_form_to_page":
        page = _resolve_entity(
            _first_data_reference(data, "page"), created, expected=Entities.PAGE
        )
        return {
            "entity": _snapshot_entity(page),
            "form": _snapshot_entity(page.form),
        }
    if action_type == "add_category":
        page = _resolve_entity(
            _first_data_reference(data, "page"), created, expected=Entities.PAGE
        )
        category = _resolve_entity(
            _first_data_reference(data, "category", "model"),
            created,
            expected=Entities.CATEGORY,
        )
        return {
            "entity": _snapshot_entity(page),
            "target": _snapshot_entity(category),
            "had_category": category.key in [item.key for item in page.categories],
        }
    if action_type in {"move_page", "move_task"}:
        root = "page" if action_type == "move_page" else "task"
        expected = Entities.PAGE if root == "page" else Entities.TASK
        entity = _resolve_entity(
            _first_data_reference(data, root), created, expected=expected
        )
        previous = entity.model if root == "page" else entity.page
        return {
            "entity": _snapshot_entity(entity),
            "parent": _snapshot_entity(previous),
        }
    if action_type == "move_file":
        source = _resolve_file_endpoint(data, created, endpoint="source")
        target = _resolve_file_endpoint(data, created, endpoint="target")
        file = _resolve_file_entity(data, created, source=source)
        return {
            "entity": _snapshot_entity(file),
            "source": _snapshot_entity(source),
            "target": _snapshot_entity(target),
        }
    if action_type == "rename_entity":
        entity = _resolve_entity(_first_data_reference(data, "entity"), created)
        return {
            "entity": _snapshot_entity(entity),
            "name": entity.name,
        }
    if action_type == "update_submission_fields":
        previous = []
        for index, update in enumerate(data.get("updates") or [], 1):
            if not isinstance(update, dict):
                continue
            entity = _resolve_submission_update_entity(update, created)
            schema_id = update.get("schema_id") or update.get("field_id")
            before = _submission_previous_value(entity, schema_id)
            previous.append(
                {
                    "index": index,
                    "entity": _entity_result(entity),
                    "schema_id": schema_id,
                    "had_value": before["had_value"],
                    "previous_value": before["value"],
                }
            )
        return {"updates": previous}
    if action_type == "update_form_schema":
        form = _resolve_entity(
            _first_data_reference(data, "form"), created, expected=Entities.FORM
        )
        return {
            "entity": _entity_result(form),
            "schema": copy.deepcopy(form.schema or []),
        }
    if action_type in {"attach_file_to_page", "attach_file_to_task"}:
        target = (
            _resolve_action_page(data, created, user)
            if action_type == "attach_file_to_page"
            else _resolve_entity(_first_data_reference(data, "task"), created)
        )
        file = _resolve_report_file(
            data.get("file") or data.get("file_id") or data.get("file_ref"),
            report,
        )
        return {
            "entity": _entity_result(file),
            "target": _entity_result(target),
            "linked": _file_attached_to_endpoint(file, target),
        }
    if action_type == "summarize_file":
        file = _resolve_report_file(
            data.get("file") or data.get("file_id") or data.get("file_ref"),
            report,
        )
        summarize = file.properties.summarize
        return {
            "entity": _entity_result(file),
            "summary": file.summary,
            "summarize": {
                "enabled": summarize.enabled,
                "search": summarize.search,
                "status": summarize.status,
                "error": summarize.error,
                "complete": summarize.complete,
                "retrieval_terms": summarize.retrieval_terms,
            },
        }
    return {}


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020h_ai_report_execution.py::test_completed_task_retry_and_undo_restore_reused_task
# @matrix ai-report : completed-task idempotency recovery
def _prepare_action_checkpoint(action, report, user, created, context, record):
    record["before"] = _capture_action_before(
        action,
        report,
        user,
        created,
        context,
    )
    output_key = None
    if action.get("type") == "create_task" and _is_completed_task_event(_data(action)):
        before = record["before"]
        target_reference = _first_data_reference(_data(action), "task")
        existing = (
            created.get(_reference_key(target_reference)) if target_reference else None
        )
        if not isinstance(existing, Entities.TASK):
            existing = _load_result_entity(before.get("entity"))
        if existing is None:
            output_key = database_utility.create_key("task", None)
        else:
            completed_on = _parse_completed_task_completed_on(_data(action))
            if _completed_event_belongs_in_history(existing, completed_on):
                output_key = database_utility.create_key("task_history", existing)
            elif _should_archive_live_completion(existing):
                history_key = database_utility.create_key("task_history", existing)
                record["history_output_key"] = database_get.urlsafe_key(history_key)
                context.setdefault("prepared_keys", {})[
                    f"{record['idempotency_key']}:history"
                ] = history_key
    else:
        output_key = _allocate_action_output_key(action, created, context)
    if output_key is not None:
        record["output_key"] = database_get.urlsafe_key(output_key)
        context.setdefault("prepared_keys", {})[record["idempotency_key"]] = output_key
    return record


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason key assignment is asserted through duplicate-free create recovery
def _assign_preallocated_key(entity, record, context):
    if entity is None or not record.get("output_key"):
        return entity
    key = context.setdefault("prepared_keys", {}).get(record["idempotency_key"])
    key = key or database_get.datastore_key(record["output_key"])
    if key is None:
        return entity
    entity._key = key
    entity.__dict__.pop("_urlsafe_key", None)
    if getattr(entity, "_db", None) is not None and hasattr(entity._db, "key"):
        entity._db.key = key
    return entity


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @matrix ai-report : attachments batch-field-patch moves result schema-update
def _record_action_result(record, action, entity, to_save, metadata, created, context):
    metadata = _default_action_metadata(action, entity, metadata)
    if (
        entity
        and action.get("type", "").startswith("create_")
        and metadata.get("created") is not False
    ):
        _assign_preallocated_key(entity, record, context)
    if (
        isinstance(entity, Entities.TASK)
        and action.get("type") == "create_task"
        and _is_completed_task_event(_data(action))
    ):
        metadata["target"] = _entity_result(entity)
        metadata["task_state_fingerprint"] = _task_state_fingerprint(entity)
    if entity:
        _remember_created(created, action, entity)
        record["entity"] = _entity_result(entity)
        if action.get("type") == "delete_page":
            record["entity"]["fingerprint"] = entity.fingerprint
    if "created" in metadata:
        record["created"] = metadata["created"]
    target = (
        metadata["target"]
        if "target" in metadata
        else _attachment_target_result(action, to_save)
    )
    if target:
        record["target"] = target
    attachments = (
        metadata["attachments"]
        if "attachments" in metadata
        else _action_attachment_results(action, to_save)
    )
    if attachments:
        record["attachments"] = attachments
    for key in (
        "created_histories",
        "file_summary",
        "submission",
        "schedule",
        "project",
        "model",
        "form",
        "page",
        "moved",
        "updates",
        "schema_updates",
        "previous",
        "previous_schema",
        "manual",
        "task_state_fingerprint",
    ):
        if key in metadata:
            record[key] = metadata[key]
    if action.get("type") == "update_form_schema" and entity is not None:
        record["schema_fingerprint"] = _value_fingerprint(entity.schema or [])
    if metadata.get("note"):
        record["note"] = metadata["note"]
    if action.get("reason"):
        record.setdefault("note", action.get("reason"))


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason result metadata is asserted through deterministic run results
def _default_action_metadata(action, entity, metadata):
    metadata = dict(metadata or {})
    action_type = action.get("type") or ""
    if entity and action_type.startswith("create_"):
        metadata.setdefault("created", True)
    return metadata
