"""Lifecycle adapters and recovery inspection for deterministic report actions."""

import copy

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database

from ..contracts import ALLOWED_ACTIONS, REPORT_ACTION_DATA_CONTRACTS
from .operations import (
    PAGE_FORM_TYPE_ERROR,
    SUBMISSION_UPDATE_ROWS_ERROR,
    TASK_FORM_TYPE_ERROR,
    _action_attachment_results,
    _attachment_target_result,
    _data,
    _entity_result,
    _fetch_report_entity,
    _file_attached_to_endpoint,
    _first_data_reference,
    _load_result_entity,
    _reference_key,
    _remember_created,
    _resolve_action_page,
    _resolve_entity,
    _resolve_file_endpoint,
    _resolve_file_entity,
    _resolve_report_file,
    _undo_add_category_action,
    _undo_add_form_to_page_action,
    _undo_attachment_action,
    _undo_created_result_entity,
    _undo_move_action,
    _undo_rename_entity,
    _undo_summarize_file,
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
    _resolve_submission_update_entity,
    _submission_previous_value,
    _undo_form_schema_update,
    _undo_submission_updates,
    _update_form_schema,
    _update_submission_fields,
)
from .tasks import (
    _capture_completed_task_before,
    _completed_event_belongs_in_history,
    _create_task,
    _is_completed_task_event,
    _parse_completed_task_completed_on,
    _should_archive_live_completion,
    _snapshot_entity,
    _task_state_fingerprint,
    _undo_reused_completed_task,
    _value_fingerprint,
)

ACTION_APPLIED = "applied"
ACTION_NOT_APPLIED = "not-applied"
ACTION_DRIFTED = "drifted"


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_report_action_registry_matches_proposal_contracts
# @features ai-report
# @dimensions action-registry contract
class ReportActionAdapter:
    """Recovery contract for one deterministic report action type."""

    def __init__(
        self,
        action_type,
        apply_handler,
        compensate_handler,
        *,
        uses_context=False,
        required=False,
    ):
        self.action_type = action_type
        self.apply_handler = apply_handler
        self.compensate_handler = compensate_handler
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

    def _apply(self, action, report, user, created, context):
        arguments = (action, report, user, created)
        if self.uses_context:
            return _normalize_handler_result(
                self.apply_handler(*arguments, context or {})
            )
        return _normalize_handler_result(self.apply_handler(*arguments))

    # @testable infrastructure
    def compensate(self, record, report, user):
        return self.compensate_handler(record, report, user)

    # @testable infrastructure
    def inspect_compensated(self, record, report, user):
        return _inspect_action_compensated(record, report, user)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020_ai_reports.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @pair ai-report:recovery
# @pair ai-report:create
# @pair ai-report:idempotency
# @pair ai-report:post-commit-checkpoint
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
                parent = database.get.datastore_key(parent_record["output_key"])
            if parent is None:
                parent = database.get.datastore_key(reference)

    return database.create_key(kind, parent)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
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
            },
        }
    return {}


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020_ai_reports.py::test_completed_task_retry_and_undo_restore_reused_task
# @pair ai-report:recovery
# @pair ai-report:idempotency
# @pair ai-report:completed-task
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
            output_key = database.create_key("task", None)
        else:
            completed_on = _parse_completed_task_completed_on(_data(action))
            if _completed_event_belongs_in_history(existing, completed_on):
                output_key = database.create_key("task_history", existing)
            elif _should_archive_live_completion(existing):
                history_key = database.create_key("task_history", existing)
                record["history_output_key"] = database.get.urlsafe_key(history_key)
                context.setdefault("prepared_keys", {})[
                    f"{record['idempotency_key']}:history"
                ] = history_key
    else:
        output_key = _allocate_action_output_key(action, created, context)
    if output_key is not None:
        record["output_key"] = database.get.urlsafe_key(output_key)
        context.setdefault("prepared_keys", {})[record["idempotency_key"]] = output_key
    return record


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason key assignment is asserted through duplicate-free create recovery
def _assign_preallocated_key(entity, record, context):
    if entity is None or not record.get("output_key"):
        return entity
    key = context.setdefault("prepared_keys", {}).get(record["idempotency_key"])
    key = key or database.get.datastore_key(record["output_key"])
    if key is None:
        return entity
    entity._key = key
    entity.__dict__.pop("_urlsafe_key", None)
    if getattr(entity, "_db", None) is not None and hasattr(entity._db, "key"):
        entity._db.key = key
    return entity


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @pair ai-report:result
# @pair ai-report:attachments
# @pair ai-report:moves
# @pair ai-report:batch-field-patch
# @pair ai-report:schema-update
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/lifecycle.py::_inspect_action_applied
# @reason expected state is asserted through move, update, and task retries
def _expected_action_state(action, record):
    action_type = action.get("type")
    expected = {
        "entity": (record.get("entity") or {}).get("id"),
        "target": (record.get("target") or {}).get("id"),
    }
    if action_type == "update_submission_fields":
        applied = {
            item.get("index"): item
            for item in (record.get("updates") or {}).get("applied") or []
        }
        expected["updates"] = [
            {
                "entity": (applied[index].get("entity") or {}).get("id"),
                "schema_id": update.get("schema_id") or update.get("field_id"),
                "value": copy.deepcopy(update.get("new_value")),
            }
            for index, update in enumerate((_data(action).get("updates") or []), 1)
            if index in applied
        ]
    if action_type == "rename_entity":
        expected["name"] = str(_data(action).get("name") or "").strip()
    if action_type == "update_form_schema":
        expected["schema_fingerprint"] = record.get("schema_fingerprint")
    if action_type == "summarize_file":
        expected["summary"] = (
            _data(action).get("summary") or _data(action).get("description") or ""
        ).strip()
    if action_type == "create_task" and _is_completed_task_event(_data(action)):
        expected["task"] = (record.get("target") or {}).get("id")
        expected["task_state_fingerprint"] = record.get("task_state_fingerprint")
    return expected


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason recovery authorization is enforced through the public runner
def _recovery_entity_allowed(entity, user):
    if entity is None:
        return False
    return bool(entity.allowed(Action.EDIT, user=user))


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason stored reference comparison is exercised through move recovery
def _stored_reference_key(entity, name):
    value = entity.db.get(name)
    return _urlsafe_key_value(value)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason key normalization is exercised through action state inspection
def _urlsafe_key_value(value):
    if not value:
        return None
    encoded = database.get.urlsafe_key(value)
    if encoded:
        return encoded
    legacy = getattr(value, "to_legacy_urlsafe", None)
    if callable(legacy):
        result = legacy()
        return result.decode() if isinstance(result, bytes) else str(result)
    return getattr(value, "name", None) or str(value)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_stops_when_completed_prefix_permission_is_revoked
# @tests tests_unit/test_020_ai_reports.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_validates_completed_move_and_update_prefix[move]
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_validates_completed_move_and_update_prefix[update]
# @tests tests_unit/test_020_ai_reports.py::test_completed_task_retry_and_undo_restore_reused_task
# @pair ai-report:recovery
# @pair ai-report:permissions
# @pair ai-report:completed-prefix
# @pair ai-report:post-commit-checkpoint
# @pair ai-report:moves
# @pair ai-report:batch-field-patch
# @pair ai-report:completed-task
def _inspect_action_applied(action, report, user, record):
    action_type = action.get("type")
    if record.get("status") == "skipped" or action_type in {
        "skip",
        "needs_review",
        "delete_page",
    }:
        return ACTION_APPLIED

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
    if entity is None and entity_id:
        return ACTION_DRIFTED
    if entity is not None and not _recovery_entity_allowed(entity, user):
        return ACTION_DRIFTED

    target_id = expected.get("target")
    target = _fetch_report_entity(target_id) if target_id else None
    if action_type == "add_form_to_page":
        return (
            ACTION_APPLIED
            if _stored_reference_key(entity, "form") == target_id
            else ACTION_DRIFTED
        )
    if action_type == "add_category":
        keys = [
            _urlsafe_key_value(key)
            for key in [entity.db.get("model"), *(entity.db.get("categories") or [])]
            if key
        ]
        return ACTION_APPLIED if target_id in keys else ACTION_DRIFTED
    if action_type == "move_page":
        category_ids = {
            _urlsafe_key_value(key)
            for key in [entity.db.get("model"), *(entity.db.get("categories") or [])]
            if key
        }
        return ACTION_APPLIED if target_id in category_ids else ACTION_DRIFTED
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
    if action_type == "rename_entity":
        return ACTION_APPLIED if entity.name == expected.get("name") else ACTION_DRIFTED
    if action_type == "update_submission_fields":
        for update in expected.get("updates") or []:
            target_entity = _fetch_report_entity(update.get("entity"))
            if target_entity is None:
                return ACTION_DRIFTED
            current = _submission_previous_value(target_entity, update.get("schema_id"))
            if current["value"] != update.get("value"):
                return ACTION_DRIFTED
        return ACTION_APPLIED
    if action_type == "update_form_schema":
        return (
            ACTION_APPLIED
            if _value_fingerprint(entity.schema or [])
            == expected.get("schema_fingerprint")
            else ACTION_DRIFTED
        )
    if action_type in {"attach_file_to_page", "attach_file_to_task"}:
        if target is None:
            return ACTION_DRIFTED
        return (
            ACTION_APPLIED
            if _file_attached_to_endpoint(entity, target)
            else ACTION_DRIFTED
        )
    if action_type == "summarize_file":
        return (
            ACTION_APPLIED
            if entity.summary == expected.get("summary")
            and entity.properties.summarize.complete is True
            else ACTION_DRIFTED
        )
    return ACTION_APPLIED


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason compensation inspection is exercised through repeat-safe undo
def _inspect_action_compensated(record, report, user):
    action_type = record.get("type")
    before = record.get("before") or {}
    if action_type in {"skip", "needs_review", "delete_page"}:
        return ACTION_APPLIED
    if action_type.startswith("create_"):
        if record.get("created") is False:
            if action_type == "create_task" and before.get("existing_task"):
                task = _load_result_entity(before.get("entity"))
                if task is None or not _recovery_entity_allowed(task, user):
                    return ACTION_DRIFTED
                return (
                    ACTION_APPLIED
                    if _task_state_fingerprint(task)
                    == _value_fingerprint(before.get("task"))
                    else ACTION_NOT_APPLIED
                )
            return ACTION_APPLIED
        return (
            ACTION_APPLIED
            if _load_result_entity(record.get("entity")) is None
            else ACTION_NOT_APPLIED
        )

    entity = _load_result_entity(record.get("entity"))
    if entity is None:
        return ACTION_DRIFTED
    if action_type == "add_form_to_page":
        previous_id = (before.get("form") or {}).get("id")
        return (
            ACTION_APPLIED
            if _stored_reference_key(entity, "form") == previous_id
            else ACTION_NOT_APPLIED
        )
    if action_type == "add_category":
        target_id = (record.get("target") or {}).get("id")
        keys = {
            _urlsafe_key_value(key)
            for key in [entity.db.get("model"), *(entity.db.get("categories") or [])]
            if key
        }
        present = target_id in keys
        expected_present = bool(before.get("had_category"))
        return ACTION_APPLIED if present is expected_present else ACTION_NOT_APPLIED
    if action_type in {"move_page", "move_task"}:
        previous_id = (before.get("parent") or {}).get("id")
        if action_type == "move_page":
            category_ids = {
                _urlsafe_key_value(key)
                for key in [
                    entity.db.get("model"),
                    *(entity.db.get("categories") or []),
                ]
                if key
            }
            return ACTION_APPLIED if previous_id in category_ids else ACTION_NOT_APPLIED
        return (
            ACTION_APPLIED
            if _stored_reference_key(entity, "page") == previous_id
            else ACTION_NOT_APPLIED
        )
    if action_type == "move_file":
        source = _load_result_entity(before.get("source"))
        target = _load_result_entity(before.get("target"))
        if source is None or target is None:
            return ACTION_DRIFTED
        return (
            ACTION_APPLIED
            if _file_attached_to_endpoint(entity, source)
            and not _file_attached_to_endpoint(entity, target)
            else ACTION_NOT_APPLIED
        )
    if action_type == "rename_entity":
        return (
            ACTION_APPLIED if entity.name == before.get("name") else ACTION_NOT_APPLIED
        )
    if action_type == "update_submission_fields":
        for previous in before.get("updates") or []:
            target = _load_result_entity(previous.get("entity"))
            if target is None:
                return ACTION_DRIFTED
            current = _submission_previous_value(target, previous.get("schema_id"))
            if current["had_value"] != previous.get("had_value") or current[
                "value"
            ] != previous.get("previous_value"):
                return ACTION_NOT_APPLIED
        return ACTION_APPLIED
    if action_type == "update_form_schema":
        return (
            ACTION_APPLIED
            if _value_fingerprint(entity.schema or [])
            == _value_fingerprint(before.get("schema") or [])
            else ACTION_NOT_APPLIED
        )
    if action_type in {"attach_file_to_page", "attach_file_to_task"}:
        target = _load_result_entity(record.get("target"))
        if target is None:
            return ACTION_DRIFTED
        linked = _file_attached_to_endpoint(entity, target)
        return (
            ACTION_APPLIED
            if linked is bool(before.get("linked"))
            else ACTION_NOT_APPLIED
        )
    if action_type == "summarize_file":
        summarize = entity.properties.summarize
        previous = before.get("summarize") or {}
        restored = (
            entity.summary == before.get("summary")
            and summarize.enabled == previous.get("enabled")
            and summarize.search == previous.get("search")
            and summarize.status == previous.get("status")
            and summarize.error == previous.get("error")
            and summarize.complete == previous.get("complete")
        )
        return ACTION_APPLIED if restored else ACTION_NOT_APPLIED
    return ACTION_APPLIED


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason recoverable action errors are asserted through full report execution
def _is_recoverable_action_error(_action, error):
    return isinstance(error, exceptions.ValidationError) and not str(error).startswith(
        "You do not have permission"
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason required placement failures are asserted through full report execution
def _is_required_file_placement(action):
    adapter = REPORT_ACTION_ADAPTERS.get(action.get("type"))
    return bool(adapter and adapter.required)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_marks_missing_file_placements_failed_and_continues
# @pair ai-report:partial-result
# @pair ai-report:attachments
def _record_required_file_placement_error(action_record, error):
    action_record["status"] = "failed"
    action_record["error"] = str(error)
    action_record["note"] = "This required file placement was not completed."


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/lifecycle.py::_record_recoverable_action_error
# @reason recoverable action error notes are asserted through full report execution
def _recoverable_action_error_note(action_record, message):
    if message == "Referenced report file was not found.":
        return "Skipped because a referenced report file was not found."
    if action_record.get("type") in {
        "attach_file_to_page",
        "attach_file_to_task",
    } and message.startswith("Referenced entity not found:"):
        return "Skipped because a referenced attachment target was not found."
    if action_record.get("type") == "create_task" and message == TASK_FORM_TYPE_ERROR:
        return (
            "Skipped because the action referenced a page form instead of a task form."
        )
    if (
        action_record.get("type") == "add_form_to_page"
        and message == PAGE_FORM_TYPE_ERROR
    ):
        return (
            "Skipped because the action referenced a task form instead of a page form."
        )
    if (
        action_record.get("type") == "update_submission_fields"
        and message == SUBMISSION_UPDATE_ROWS_ERROR
    ):
        return "Skipped because no executable submission field updates were provided."
    return "Skipped because this action could not be completed."


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_skips_empty_submission_update_and_continues
# @tests tests_unit/test_020_ai_reports.py::test_run_report_skips_invalid_completed_task_events_and_continues
# @tests tests_unit/test_020_ai_reports.py::test_run_report_skips_task_that_references_page_form_and_continues
# @pair ai-report:recoverable
# @pair ai-report:continue
# @pair ai-report:empty-update
# @pair ai-report:completed-task
# @pair ai-report:mismatched-form
def _record_recoverable_action_error(action_record, error):
    message = str(error)
    action_record["status"] = "skipped"
    action_record["error"] = message
    action_record["note"] = _recoverable_action_error_note(action_record, message)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason result metadata is asserted through deterministic run results
def _default_action_metadata(action, entity, metadata):
    metadata = dict(metadata or {})
    action_type = action.get("type") or ""
    if entity and action_type.startswith("create_"):
        metadata.setdefault("created", True)
    return metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason action dispatch is exercised through deterministic report-run tests
def _normalize_handler_result(result):
    if len(result) == 2:
        entity, to_save = result
        return entity, to_save, {}
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason action dispatch is exercised through deterministic report-run tests
def _execute_action(action, report, user, created, context=None):
    adapter = REPORT_ACTION_ADAPTERS[action["type"]]
    return adapter._apply(action, report, user, created, context or {})


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason undo dispatch is exercised through public undo tests
def _undo_result_action(action, report, user):
    return REPORT_ACTION_ADAPTERS[action["type"]].compensate(action, report, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason create-action compensation is exercised through public undo tests
def _compensate_created(action, report, user):
    if action.get("created") is False:
        return {"note": "Reused existing entity; nothing deleted."}
    return _undo_created_result_entity(action, report, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason task compensation is exercised through completed-task undo tests
def _compensate_created_task(action, report, user):
    if action.get("created") is False and (action.get("before") or {}).get(
        "existing_task"
    ):
        return _undo_reused_completed_task(action, user)
    return _compensate_created(action, report, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason adapter binding is exercised through public undo dispatch
def _without_report(handler):
    return lambda action, _report, user: handler(action, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason manual actions are represented explicitly in public undo results
def _manual_compensation(_action, _report, _user):
    return {"note": "Manual cleanup suggestion; nothing was executed."}


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason no-op actions are represented explicitly in public undo results
def _noop_compensation(_action, _report, _user):
    return {"note": "No created entities or links to undo."}


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

if set(REPORT_ACTION_ADAPTERS) != set(REPORT_ACTION_DATA_CONTRACTS) or set(
    REPORT_ACTION_ADAPTERS
) != set(ALLOWED_ACTIONS):
    raise RuntimeError(
        "Report action contracts and lifecycle adapters are inconsistent."
    )
