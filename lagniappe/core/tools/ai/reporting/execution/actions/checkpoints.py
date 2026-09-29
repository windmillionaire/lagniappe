"""Action identities, completion decisions, and committed result receipts."""

from datetime import datetime, timezone

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
    _load_result_entity,
    _reference_key,
    _resolve_entity,
)
from .task_completion import _completion_state
from .documents import prepare_document_append
from .completed_tasks import (
    _capture_completed_task_before,
    _completed_event_belongs_in_history,
    _is_completed_task_event,
    _parse_completed_task_completed_on,
    _should_archive_live_completion,
    _task_state_fingerprint,
    _task_checkpoint_state,
    _value_fingerprint,
)


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @tests tests_unit/test_032h_report_batches.py::test_create_batch_reserves_one_key_per_output_and_reuses_receipts
# @tests tests_unit/test_032h_report_batches.py::test_create_key_batches_are_bounded_and_keep_parent_groups_separate
# @matrix ai-report : create idempotency post-commit-checkpoint recovery
# @matrix ai-report : id-allocation batching parent bounded
def _allocate_action_output_key(action, created, context):
    spec = _creation_key_spec(action, created, context)
    if spec is None:
        return None
    record = context.get("action_records", {}).get(action.get("id")) or {}
    prepared = context.setdefault("prepared_keys", {})
    identity = record.get("idempotency_key")
    if identity in prepared:
        return prepared[identity]
    actions = context.get("allocation_actions", [])
    index = next((i for i, item in enumerate(actions) if item.get("id") == action.get("id")), None)
    if identity is None or index is None:
        return database_utility.create_key(*spec)

    # Reserve only a bounded lookahead with the same physical kind and parent.
    # Unresolved parents are deferred until their creation has been applied.
    group = []
    kind, parent = spec
    for item in actions[index:index + 50]:
        pending = context["action_records"].get(item.get("id")) or {}
        pending_id = pending.get("idempotency_key")
        if (not pending_id or pending_id in prepared or pending.get("prepared")
                or pending.get("output_key") or pending.get("status") in {"complete", "skipped"}
                or item.get("skip")):
            continue
        candidate = _creation_key_spec(item, created, context)
        if candidate and (database_utility.KINDS[candidate[0]], candidate[1]) == (database_utility.KINDS[kind], parent):
            group.append(pending_id)
    if not group:
        return database_utility.create_key(*spec)
    keys = database_utility.create_keys(kind, parent, len(group))
    prepared.update(zip(group, keys))
    return prepared[identity]


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/checkpoints.py::_allocate_action_output_key
# @reason eligible output kinds and resolved parents are exercised through Plan creation
def _creation_key_spec(action, created, context):
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

        if parent is None:
            return None
    return kind, parent


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason construction uses the same identity that is persisted with the action receipt
def _prepared_output_key(context):
    context = context or {}
    record = context.get("action_record") or {}
    return (context.get("prepared_keys", {}).get(record.get("idempotency_key"))
            or database_get.datastore_key(record.get("output_key")))


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason action checkpoints are asserted through public forward recovery behavior
def _capture_action_before(action, report, user, created, context=None):
    action_type = action.get("type")
    data = _data(action)
    if action_type == "complete_task":
        task = _resolve_entity(data.get("task"), created, expected=Entities.TASK)
        return {"entity": _entity_result(task), "completion_state": _completion_state(task), "task": _task_checkpoint_state(task)}
    if action_type == "create_task" and _is_completed_task_event(data):
        return _capture_completed_task_before(
            action,
            data,
            user,
            created,
        )
    return {}


# @testable true
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020h_ai_report_execution.py::test_completed_task_retry_preserves_reused_completion
# @matrix ai-report : completed-task idempotency recovery
def _prepare_action_checkpoint(action, report, user, created, context, record):
    if action.get("type") in {"append_page_document", "replace_page_document"}:
        prepare_document_append(action, report, user, created, record)
        return
    if action.get("type") == "create_page" and _data(action).get("document"):
        record["document_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # Only completion preparation needs a prior completion to decide whether
    # to create history. Ordinary writes commit their receipt with the batch;
    # they no longer need a second copy of the reviewed proposal/before-state.
    record["before"] = (
        _capture_action_before(action, report, user, created, context)
        if action.get("type") == "complete_task" or (
            action.get("type") == "create_task" and _is_completed_task_event(_data(action))
        ) else {}
    )
    output_key = None
    if action.get("type") == "complete_task":
        task = _resolve_entity(_data(action).get("task"), created, expected=Entities.TASK)
        history_key = database_utility.create_key("task_history", task)
        record["history_output_key"] = database_get.urlsafe_key(history_key)
        context.setdefault("prepared_keys", {})[
            f"{record['idempotency_key']}:history"
        ] = history_key
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
            completed_on = _parse_completed_task_completed_on(_data(action), user=user)
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
# @matrix ai-report : attachments result
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
        if action.get("type") == "suggest_page_deletion":
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
        "completion_state",
        "due_date_state",
        "document_after",
        "entity_update_after",
    ):
        if key in metadata:
            record[key] = metadata[key]
    if action.get("type") in {"update_form_schema"} and entity is not None:
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
