"""Deterministic execution for stored AI report proposals."""

import copy
import hashlib
import json
import re
from datetime import datetime

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Action,
    Fetch,
    FetchReason,
    MutationIntent,
    Resource,
)
from lagniappe.core.entities import Entities
from lagniappe.core.properties.schema import SchemaValidationError, canonicalize_schema
from lagniappe.core.tools import cache, database, dates

from .debug import ai_debug
from .organize import validate_proposal


TASK_FORM_TYPE_ERROR = "Create task actions require a task form."
PAGE_FORM_TYPE_ERROR = "Add form to page actions require a page form."
SUBMISSION_UPDATE_ROWS_ERROR = (
    "Submission update action requires at least one update."
)
REPORT_LEDGER_VERSION = 1
ACTION_APPLIED = "applied"
ACTION_NOT_APPLIED = "not-applied"
ACTION_DRIFTED = "drifted"


# @testable infrastructure
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
class ReportActionAdapter:
    """Recovery contract for one deterministic report action type."""

    def __init__(self, action_type):
        self.action_type = action_type

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

    # @testable infrastructure
    def compensate(self, record, report, user):
        return _undo_result_action(record, report, user)

    # @testable infrastructure
    def inspect_compensated(self, record, report, user):
        return _inspect_action_compensated(record, report, user)


REPORT_ACTION_ADAPTERS = {
    action_type: ReportActionAdapter(action_type)
    for action_type in (
        "create_form",
        "create_category",
        "create_project",
        "create_model_task",
        "create_page",
        "create_task",
        "add_form_to_page",
        "add_category",
        "move_page",
        "move_task",
        "move_file",
        "rename_entity",
        "update_submission_fields",
        "update_form_schema",
        "attach_file_to_page",
        "attach_file_to_task",
        "delete_page",
        "summarize_file",
        "skip",
        "needs_review",
    )
}


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020_ai_reports.py::test_run_report_records_dateless_historical_task_completion
# @tests tests_unit/test_020_ai_reports.py::test_run_report_records_older_completed_event_without_mutating_live_task
# @tests tests_unit/test_020_ai_reports.py::test_run_report_promotes_newer_completed_event_to_live_task
# @tests tests_unit/test_020_ai_reports.py::test_run_report_reuses_one_created_task_for_multiple_completed_events
# @tests tests_unit/test_020_ai_reports.py::test_run_report_reuses_existing_task_for_completed_event
# @tests tests_unit/test_020_ai_reports.py::test_run_report_resolves_task_page_by_exact_page_name_when_reference_is_wrong_kind
# @tests tests_unit/test_020_ai_reports.py::test_run_report_resolves_attachment_page_from_single_prior_task_when_reference_is_file
# @tests tests_unit/test_020_ai_reports.py::test_run_report_resolves_attachment_page_by_exact_page_name_when_reference_missing
# @tests tests_unit/test_020_ai_reports.py::test_run_report_marks_missing_file_placements_failed_and_continues
# @tests tests_unit/test_020_ai_reports.py::test_run_report_rejects_category_used_as_attachment_page
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_file_by_exact_source_attachment_name
# @tests tests_unit/test_020_ai_reports.py::test_run_report_adds_page_category_without_changing_primary_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_run_report_adds_form_to_existing_page_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_run_report_skips_invalid_completed_task_events_and_continues
# @tests tests_unit/test_020_ai_reports.py::test_run_report_rejects_saved_pending_submissions_before_execution
# @tests tests_unit/test_020_ai_reports.py::test_run_report_checks_deferred_execution_guard
# @tests tests_unit/test_020_ai_reports.py::test_run_report_propagates_deferred_control_stop
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_stops_when_completed_prefix_permission_is_revoked
# @tests tests_unit/test_020_ai_reports.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @tests tests_unit/test_020_ai_reports.py::test_run_report_retry_validates_completed_move_and_update_prefix
# @tests tests_unit/test_020_ai_reports.py::test_completed_task_retry_and_undo_restore_reused_task
# @tests tests_unit/test_020_ai_reports.py::test_run_report_renames_entity_without_submission_and_undoes
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_schema_section_and_runs_submission_updates
# @tests tests_e2e/002_home/test_002l_home_tools_ai.py::test_organize_completion_corpus_executes_usable_submissions*
# @features ai-report
# @dimensions deterministic-run create-order partial-result completed-task validation recoverable continue page-form moves batch-field-patch schema-update skip-action execute persistence attachments default-category recovery create idempotency completed-prefix post-commit-checkpoint reuse compensation permissions rename cancellation
def run_report(report, user, ensure_active=None):
    """Execute or resume a stored AI report proposal from durable checkpoints."""
    ensure_active = ensure_active or (lambda: None)
    ensure_active()
    proposal = validate_proposal(
        report.proposal,
        allow_empty_submission_updates=True,
        allow_pending_submissions=False,
    )
    proposal_fingerprint = _proposal_fingerprint(proposal)
    existing = report.result if isinstance(report.result, dict) else {}
    resuming = (
        existing.get("ledger_version") == REPORT_LEDGER_VERSION
        and existing.get("status") != "undone"
    )
    if resuming:
        result = existing
        if result.get("proposal_fingerprint") != proposal_fingerprint:
            raise exceptions.ValidationError(
                "This report proposal changed after execution started."
            )
        _validate_report_ledger(proposal, result)
    else:
        result = _new_report_ledger(report, proposal, proposal_fingerprint)

    result["status"] = "running"
    result.pop("failed_at", None)
    result.pop("undo", None)
    created = _restore_completed_action_entities(result)
    context = _build_report_run_context(proposal)
    context["action_records"] = {
        record.get("id"): record
        for record in result["actions"]
        if record.get("id")
    }

    report.status = "running"
    report.pending = True
    report.error = None
    report.result = result
    ensure_active()
    Entities.save(report)

    for index, action in enumerate(proposal.get("actions", [])):
        ensure_active()
        action_record = result["actions"][index]
        adapter = REPORT_ACTION_ADAPTERS[action["type"]]
        if action_record.get("status") in {"complete", "skipped"}:
            state = adapter.inspect_applied(action, report, user, action_record)
            if action_record.get("status") == "complete" and state != ACTION_APPLIED:
                return _fail_report_recovery(
                    report,
                    result,
                    action_record,
                    index,
                    "Recorded report action state has changed; recovery stopped.",
                )
            continue

        if action.get("skip") is True:
            action_record["status"] = "skipped"
            action_record["note"] = action.get("reason") or "Skipped by user."
            Entities.save(report)
            continue

        try:
            if action_record.get("status") in {"applying", "failed"}:
                state = adapter.inspect_applied(action, report, user, action_record)
                if state == ACTION_APPLIED:
                    action_record["status"] = "complete"
                    action_record.pop("error", None)
                    Entities.save(report)
                    _restore_created_action_entity(created, action_record)
                    continue
                if state == ACTION_DRIFTED:
                    return _fail_report_recovery(
                        report,
                        result,
                        action_record,
                        index,
                        "Recorded report action state has changed; recovery stopped.",
                    )

            if not action_record.get("prepared"):
                adapter.prepare(
                    action,
                    report,
                    user,
                    created,
                    context,
                    action_record,
                )
                ensure_active()
                action_record["prepared"] = True
            action_record["status"] = "applying"
            action_record["attempts"] = int(action_record.get("attempts") or 0) + 1
            action_record.pop("error", None)
            report.result = result
            Entities.save(report)

            context["action_record"] = action_record
            entity, to_save, metadata = adapter.apply(
                action,
                report,
                user,
                created,
                context,
            )
            ensure_active()
            _record_action_result(
                action_record,
                action,
                entity,
                to_save,
                metadata,
                created,
                context,
            )
            action_record["expected"] = _expected_action_state(
                action,
                action_record,
            )
            action_record["status"] = "complete"
            action_record.pop("error", None)
            report.result = result
            Entities.save(*to_save, report)
        except Exception as error:
            from lagniappe.core.tools.deferred_jobs import (
                DeferredJobClaimLostError,
                DeferredJobDeadlineError,
                DeferredJobInfrastructureError,
            )

            if isinstance(
                error,
                (
                    DeferredJobClaimLostError,
                    DeferredJobDeadlineError,
                    DeferredJobInfrastructureError,
                ),
            ):
                raise
            if _is_recoverable_action_error(action, error):
                if _is_required_file_placement(action):
                    _record_required_file_placement_error(action_record, error)
                    exceptions.capture(
                        error,
                        context={
                            "ai_report_runner": {
                                "operation": "required_file_placement_failed",
                                "report": _diagnostic_entity(report),
                                "action": {
                                    "id": action.get("id"),
                                    "type": action.get("type"),
                                    "display_label": action.get("display_label"),
                                },
                                "error": str(error),
                            }
                        },
                    )
                else:
                    _record_recoverable_action_error(action_record, error)
                Entities.save(report)
                continue
            action_record["status"] = "failed"
            action_record["error"] = str(error)
            result["status"] = "failed"
            result["failed_at"] = index + 1
            report.status = "failed"
            report.pending = False
            report.error = str(error)
            report.result = result
            Entities.save(report)
            return result

    failed_placements = [
        (index, record)
        for index, record in enumerate(result["actions"])
        if record.get("status") == "failed"
        and record.get("type") in {"attach_file_to_page", "attach_file_to_task"}
    ]
    if failed_placements:
        result["status"] = "failed"
        result["failed_at"] = failed_placements[0][0] + 1
        report.status = "failed"
        report.pending = False
        report.error = (
            "One or more files could not be attached to their planned page or "
            "task. Review the failed file placement before retrying or undoing "
            "the completed actions."
        )
        report.result = result
        Entities.save(report)
        return result

    result["status"] = "complete"
    report.status = "complete"
    report.pending = False
    report.result = result
    report.error = None
    ensure_active()
    Entities.save(report)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason proposal identity is exercised through public retry behavior
def _proposal_fingerprint(proposal):
    canonical = json.dumps(
        proposal,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason action identity is asserted through public retry behavior
def _action_idempotency_key(report, proposal_fingerprint, index, action):
    value = ":".join(
        (
            report.urlsafe_key,
            proposal_fingerprint,
            str(index),
            str(action.get("id") or ""),
            str(action.get("type") or ""),
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason ledger construction is asserted through public retry behavior
def _new_report_ledger(report, proposal, proposal_fingerprint):
    return {
        "ledger_version": REPORT_LEDGER_VERSION,
        "proposal_fingerprint": proposal_fingerprint,
        "status": "running",
        "actions": [
            {
                "id": action.get("id"),
                "type": action.get("type"),
                "display_label": action.get("display_label"),
                "idempotency_key": _action_idempotency_key(
                    report,
                    proposal_fingerprint,
                    index,
                    action,
                ),
                "status": "pending",
                "attempts": 0,
            }
            for index, action in enumerate(proposal.get("actions") or [])
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason ledger validation is exercised through public resume behavior
def _validate_report_ledger(proposal, result):
    actions = proposal.get("actions") or []
    records = result.get("actions") or []
    if len(actions) != len(records):
        raise exceptions.ValidationError("Stored report recovery ledger is invalid.")
    for action, record in zip(actions, records):
        if (
            record.get("id") != action.get("id")
            or record.get("type") != action.get("type")
            or not record.get("idempotency_key")
        ):
            raise exceptions.ValidationError(
                "Stored report recovery ledger does not match the proposal."
            )


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason created-reference restoration is exercised through dependent retries
def _restore_completed_action_entities(result):
    created = {}
    for record in result.get("actions") or []:
        if record.get("status") != "complete":
            continue
        _restore_created_action_entity(created, record)
    return created


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason created-reference restoration is exercised through dependent retries
def _restore_created_action_entity(created, record):
    if not str(record.get("type") or "").startswith("create_"):
        return
    entity = _load_result_entity(record.get("entity"))
    if entity is None:
        return
    action = {"id": record.get("id")}
    _remember_created(created, action, entity)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason recovery failure persistence is exercised through public retry tests
def _fail_report_recovery(report, result, record, index, message):
    record["status"] = "failed"
    record["error"] = message
    result["status"] = "failed"
    result["failed_at"] = index + 1
    report.status = "failed"
    report.pending = False
    report.error = message
    report.result = result
    Entities.save(report)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason output allocation is asserted through create retry idempotency
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
# @reason before-state serialization is exercised through compensation tests
def _snapshot_entity(entity):
    return _entity_result(entity) if entity is not None else None


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


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason checkpoint date serialization is exercised through task recovery
def _checkpoint_datetime(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason task checkpoint content is asserted through task recovery and undo
def _task_checkpoint_state(task):
    if task is None:
        return None
    return {
        "entity": _entity_result(task),
        "name": task.name,
        "description": task.description,
        "completed": bool(task.completed),
        "completed_on": _checkpoint_datetime(task.completed_on),
        "due_date": _checkpoint_datetime(task.due_date),
        "submission": copy.deepcopy(task.submission),
        "history": bool(task.db.get("history", False)),
        "page": _snapshot_entity(task.page),
        "form": _snapshot_entity(task.form),
        "project": _snapshot_entity(task.project),
        "model": _snapshot_entity(task.model),
        "assigned_to": _snapshot_entity(task.assigned_to),
        "assigned_by": _snapshot_entity(task.assigned_by),
        "completed_by": _snapshot_entity(task.completed_by),
        "linked_pages": [_entity_result(page) for page in task.linked_pages or []],
        "files": [_entity_result(file) for file in task.files or []],
        "assets": copy.deepcopy(getattr(task, "assets", {}) or {}),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason completed-task checkpointing is asserted through retry and undo
def _capture_completed_task_before(action, data, user, created):
    page = _resolve_action_page(data, created, user)
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
    existing = _find_completed_task_match(
        action,
        data,
        created,
        page,
        form,
        project,
        model,
        user,
    )
    return {
        "existing_task": existing is not None,
        "task": _task_checkpoint_state(existing),
        "entity": _snapshot_entity(existing),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason durable preparation is asserted through interrupted-action recovery
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
            created.get(_reference_key(target_reference))
            if target_reference
            else None
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


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason result checkpointing is asserted through public report execution
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason state fingerprints are exercised through completed-prefix validation
def _value_fingerprint(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
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
        expected["task_state_fingerprint"] = record.get(
            "task_state_fingerprint"
        )
    return expected


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason task state validation is exercised through completed-task retry
def _task_state_fingerprint(task):
    return _value_fingerprint(_task_checkpoint_state(task))


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


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason applied-state inspection is asserted through interrupted retries
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
        return (
            ACTION_APPLIED
            if entity.name == expected.get("name")
            else ACTION_DRIFTED
        )
    if action_type == "update_submission_fields":
        for update in expected.get("updates") or []:
            target_entity = _fetch_report_entity(update.get("entity"))
            if target_entity is None:
                return ACTION_DRIFTED
            current = _submission_previous_value(
                target_entity, update.get("schema_id")
            )
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
            return (
                ACTION_APPLIED
                if previous_id in category_ids
                else ACTION_NOT_APPLIED
            )
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
            ACTION_APPLIED
            if entity.name == before.get("name")
            else ACTION_NOT_APPLIED
        )
    if action_type == "update_submission_fields":
        for previous in before.get("updates") or []:
            target = _load_result_entity(previous.get("entity"))
            if target is None:
                return ACTION_DRIFTED
            current = _submission_previous_value(target, previous.get("schema_id"))
            if (
                current["had_value"] != previous.get("had_value")
                or current["value"] != previous.get("previous_value")
            ):
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
    return (
        isinstance(error, exceptions.ValidationError)
        and not str(error).startswith("You do not have permission")
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason required placement failures are asserted through full report execution
def _is_required_file_placement(action):
    return action.get("type") in {"attach_file_to_page", "attach_file_to_task"}


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason required placement failures are asserted through full report execution
def _record_required_file_placement_error(action_record, error):
    action_record["status"] = "failed"
    action_record["error"] = str(error)
    action_record["note"] = "This required file placement was not completed."


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason recoverable action error notes are asserted through full report execution
def _recoverable_action_error_note(action_record, message):
    if message == "Referenced report file was not found.":
        return "Skipped because a referenced report file was not found."
    if (
        action_record.get("type") in {"attach_file_to_page", "attach_file_to_task"}
        and message.startswith("Referenced entity not found:")
    ):
        return "Skipped because a referenced attachment target was not found."
    if action_record.get("type") == "create_task" and message == TASK_FORM_TYPE_ERROR:
        return (
            "Skipped because the action referenced a page form instead of a task form."
        )
    if (
        action_record.get("type") == "add_form_to_page"
        and message == PAGE_FORM_TYPE_ERROR
    ):
        return "Skipped because the action referenced a task form instead of a page form."
    if (
        action_record.get("type") == "update_submission_fields"
        and message == SUBMISSION_UPDATE_ROWS_ERROR
    ):
        return "Skipped because no executable submission field updates were provided."
    return "Skipped because this action could not be completed."


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason recoverable action errors are asserted through full report execution
def _record_recoverable_action_error(action_record, error):
    message = str(error)
    action_record["status"] = "skipped"
    action_record["error"] = message
    action_record["note"] = _recoverable_action_error_note(action_record, message)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_undo_report_deletes_created_entities_and_unlinks_files
# @tests tests_unit/test_020_ai_reports.py::test_run_report_adds_form_to_existing_page_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_undo_report_compensates_completed_prefix_of_failed_report
# @tests tests_unit/test_020_ai_reports.py::test_completed_task_retry_and_undo_restore_reused_task
# @tests tests_unit/test_020_ai_reports.py::test_run_report_renames_entity_without_submission_and_undoes
# @features ai-report
# @dimensions deterministic-run undo delete-links report-files page-form idempotent idempotency compensation failed-prefix recovery completed-task reuse created-entities file-links rename
def undo_report(report, user):
    """Compensate a complete report or the completed prefix of a failed report."""
    result = report.result if isinstance(report.result, dict) else {}
    if result.get("ledger_version") != REPORT_LEDGER_VERSION:
        raise exceptions.ValidationError("This report has no recovery ledger.")
    if result.get("status") == "undone" or result.get("undone"):
        raise exceptions.ValidationError("This report has already been undone.")
    if report.status not in {"complete", "failed", "undo_failed", "undoing"}:
        raise exceptions.ValidationError(
            "Only complete or partially completed reports can be undone."
        )

    completed_indexes = [
        index
        for index, action in enumerate(result.get("actions") or [])
        if action.get("status") == "complete"
    ]
    if not completed_indexes:
        raise exceptions.ValidationError("This report has no completed actions to undo.")

    undo = result.get("undo") if isinstance(result.get("undo"), dict) else None
    if not undo or undo.get("status") not in {"running", "failed"}:
        undo = {
            "status": "running",
            "actions": [
                {
                    "action_index": index,
                    "id": result["actions"][index].get("id"),
                    "type": result["actions"][index].get("type"),
                    "status": "pending",
                    "attempts": 0,
                }
                for index in reversed(completed_indexes)
            ],
        }
    else:
        undo["status"] = "running"
    result["undo"] = undo
    report.status = "undoing"
    report.pending = True
    report.error = None
    report.result = result
    Entities.save(report)

    for undo_record in undo["actions"]:
        action = result["actions"][undo_record["action_index"]]
        adapter = REPORT_ACTION_ADAPTERS[action["type"]]
        if undo_record.get("status") == "complete":
            continue
        try:
            if undo_record.get("status") in {"applying", "failed"}:
                state = adapter.inspect_compensated(action, report, user)
                if state == ACTION_APPLIED:
                    undo_record["status"] = "complete"
                    undo_record.pop("error", None)
                    Entities.save(report)
                    continue
                if state == ACTION_DRIFTED:
                    raise exceptions.ValidationError(
                        "Recorded report action state changed during undo."
                    )

            undo_record["status"] = "applying"
            undo_record["attempts"] = int(undo_record.get("attempts") or 0) + 1
            undo_record.pop("error", None)
            Entities.save(report)
            summary = adapter.compensate(action, report, user)
            undo_record.update(summary)
            undo_record["status"] = "complete"
            Entities.save(report)
        except Exception as error:
            undo_record["status"] = "failed"
            undo_record["error"] = str(error)
            undo["status"] = "failed"
            result["undo"] = undo
            report.result = result
            report.status = "undo_failed"
            report.pending = False
            report.error = str(error)
            Entities.save(report)
            return undo

    undo["status"] = "complete"
    result["status"] = "undone"
    result["undone"] = True
    report.status = "ready"
    report.pending = False
    report.error = None
    report.result = result
    Entities.save(report)
    return undo


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason run-scoped report context setup is verified through report execution
def _build_report_run_context(proposal):
    return {}


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
    action_type = action.get("type")
    handlers = {
        "create_form": _create_form,
        "create_category": _create_category,
        "create_project": _create_project,
        "create_model_task": _create_model_task,
        "create_page": _create_page,
        "create_task": _create_task,
        "add_form_to_page": _add_form_to_page,
        "add_category": _add_category,
        "move_page": _move_page,
        "move_task": _move_task,
        "move_file": _move_file,
        "rename_entity": _rename_entity,
        "update_submission_fields": _update_submission_fields,
        "update_form_schema": _update_form_schema,
        "attach_file_to_page": _attach_file_to_page,
        "attach_file_to_task": _attach_file_to_task,
        "delete_page": _manual_delete_page_action,
        "summarize_file": _summarize_file,
        "skip": _skip_action,
        "needs_review": _needs_review_action,
    }
    handler = handlers[action_type]
    if action_type == "create_task":
        return _normalize_handler_result(
            _create_task(action, report, user, created, context or {})
        )
    return _normalize_handler_result(handler(action, report, user, created))


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason permission failures are covered through runner action handlers
def _require_allowed(allowed, message):
    if not allowed:
        raise exceptions.ValidationError(message)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason action data extraction is exercised by each handler
def _data(action):
    data = action.get("data") or {}
    if not isinstance(data, dict):
        raise exceptions.ValidationError("Action data must be an object.")
    return data


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason form creation is exercised through ordered deterministic report runs
def _create_form(action, _report, user, _created):
    _require_allowed(
        Resource.FORMS.allowed(Action.CREATE, user),
        "You do not have permission to create forms.",
    )
    data = _data(action)
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise exceptions.ValidationError("Create form actions require data.name.")
    form_type = data.get("form_type") or data.get("form-type")
    if form_type not in {"page", "task"}:
        raise exceptions.ValidationError("Create form actions require data.form_type.")
    schema = data.get("schema")
    if not isinstance(schema, list) or not schema:
        raise exceptions.ValidationError(
            "Create form actions require at least one schema field."
        )
    form = Entities.FORM.create(
        {
            "name": name,
            "form-type": form_type,
            "schema": schema,
        }
    )
    form.ai_generated = True
    return form, [form]


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason category creation is exercised through ordered deterministic report runs
def _create_category(action, _report, user, created):
    _require_allowed(
        Resource.CATEGORY.allowed(Action.CREATE, user),
        "You do not have permission to create categories.",
    )
    data = _data(action)
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
        optional=True,
    )
    category = Entities.CATEGORY.create(
        {
            "name": data.get("name") or "Generated category",
            "description": data.get("description"),
            "form": form,
            "attributes": data.get("attributes"),
        }
    )
    category.ai_generated = True
    return category, [category]


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason project creation is exercised through ordered deterministic report runs
def _create_project(action, _report, user, _created):
    _require_allowed(
        Resource.PROJECT.allowed(Action.CREATE, user),
        "You do not have permission to create projects.",
    )
    data = _data(action)
    project = Entities.PROJECT.create(
        {
            "name": data.get("name") or "Generated project",
            "description": data.get("description"),
            "attributes": data.get("attributes"),
        }
    )
    project.ai_generated = True
    return project, [project]


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason model task creation is exercised through ordered deterministic report runs
def _create_model_task(action, _report, user, created):
    data = _data(action)
    project = _resolve_entity(
        data.get("project")
        or data.get("project_id")
        or data.get("project_ref")
        or data.get("project_action"),
        created,
        expected=Entities.PROJECT,
    )
    _require_allowed(
        project.allowed(Action.EDIT, user=user),
        "You do not have permission to edit this project.",
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
    model_task = Entities.MODEL_TASK.create(
        project,
        {
            "name": data.get("name") or "Generated model task",
            "form": form,
        },
    )
    return model_task, [model_task, project]


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason page creation is exercised through ordered deterministic report runs
def _create_page(action, _report, user, created):
    data = _data(action)
    category = _resolve_entity(
        data.get("category")
        or data.get("category_id")
        or data.get("category_ref")
        or data.get("category_action")
        or data.get("model")
        or data.get("model_id")
        or data.get("model_action"),
        created,
        expected=Entities.CATEGORY,
        optional=True,
    )
    if category is None:
        category = Entities.CATEGORY.get_uncategorized_pages()
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to create pages in this category.",
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
    page_form = form or _category_form(category)
    page = Entities.PAGE.create(
        {
            "name": data.get("name") or "Generated page",
            "description": data.get("description"),
            "model": category,
            "categories": data.get("categories") or [],
            "form": page_form,
            "attributes": data.get("attributes"),
        }
    )
    if page_form is not None and "submission" in data:
        page.ai_submission(data.get("submission") or {})
    if data.get("document"):
        page.properties.document.html = data["document"]
    metadata = {}
    if page_form is not None:
        metadata["form"] = _entity_result(page_form)
    if "submission" in data:
        metadata["submission"] = _submission_result(
            page,
            data.get("submission_empty_reason"),
        )
    return page, [page, category], metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason task creation is exercised through ordered deterministic report runs
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

    metadata = _task_structure_result(task)
    metadata["page"] = _entity_result(page)
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


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason page form attachment is exercised through deterministic report-run tests
def _add_form_to_page(action, _report, user, created):
    data = _data(action)
    page = _resolve_entity(
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action"),
        created,
        expected=Entities.PAGE,
    )
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
    )
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to add a form to this page.",
    )
    _require_form_type(form, "page", PAGE_FORM_TYPE_ERROR)

    previous_form = page.form
    previous_owners = list(page.page_list_owners)
    had_form = (
        previous_form is not None
        and getattr(previous_form, "key", None) == getattr(form, "key", None)
    )
    if not had_form:
        page.form = form
        for category in page.page_list_owners:
            if isinstance(category, Entities.CATEGORY):
                category.properties.forms.add(form)
        page.add_mutation_intents(
            *(
                MutationIntent.touch(
                    owner,
                    reason="report-page-previous-owner",
                )
                for owner in previous_owners
            )
        )

    metadata = {
        "target": _entity_result(form),
        "form": _entity_result(form),
        "previous": {
            "form": _entity_result(previous_form) if previous_form else None,
            "had_form": had_form,
        },
    }
    if had_form:
        metadata["note"] = "Page already had this form."
    return page, _unique_entities([page, form, *previous_owners]), metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason category add behavior is exercised through deterministic report-run tests
def _add_category(action, _report, user, created):
    data = _data(action)
    page = _resolve_entity(
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action"),
        created,
        expected=Entities.PAGE,
    )
    category = _resolve_entity(
        data.get("category")
        or data.get("category_id")
        or data.get("category_ref")
        or data.get("category_action")
        or data.get("model")
        or data.get("model_id")
        or data.get("model_ref")
        or data.get("model_action"),
        created,
        expected=Entities.CATEGORY,
    )
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to add categories to this page.",
    )
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to add this category to pages.",
    )

    previous_categories = list(page.categories or [])
    previous_owners = list(page.page_list_owners)
    had_category = any(
        getattr(existing, "key", None) == getattr(category, "key", None)
        for existing in previous_categories
    )
    if not had_category:
        page.categories = [*previous_categories, category]
        if page.form:
            category.properties.forms.add(page.form)
        page.add_mutation_intents(
            *(
                MutationIntent.touch(
                    owner,
                    reason="report-page-previous-owner",
                )
                for owner in previous_owners
            )
        )

    metadata = {
        "target": _entity_result(category),
        "previous": {
            "had_category": had_category,
        },
    }
    if had_category:
        metadata["note"] = "Page already had this category."
    return page, _unique_entities([page, category, *previous_owners]), metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason page move behavior is exercised through deterministic report-run tests
def _move_page(action, _report, user, created):
    data = _data(action)
    page = _resolve_entity(
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action"),
        created,
        expected=Entities.PAGE,
    )
    category = _resolve_entity(
        data.get("category")
        or data.get("category_id")
        or data.get("category_ref")
        or data.get("category_action")
        or data.get("model")
        or data.get("model_id")
        or data.get("model_ref")
        or data.get("model_action"),
        created,
        expected=Entities.CATEGORY,
    )
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to move this page.",
    )
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to move pages to this category.",
    )

    previous_model = page.model
    previous_categories = list(page.categories or [])
    previous_owners = list(page.page_list_owners)

    previous_model_key = getattr(previous_model, "key", None)
    category_key = getattr(category, "key", None)
    page.categories = [
        category,
        *[
            existing
            for existing in previous_categories
            if getattr(existing, "key", None)
            not in {previous_model_key, category_key}
        ],
    ]
    if page.form:
        category.properties.forms.add(page.form)
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-previous-owner",
            )
            for owner in previous_owners
        )
    )

    metadata = {
        "target": _entity_result(category),
        "moved": {
            "from": _entity_result(previous_model) if previous_model else None,
            "to": _entity_result(category),
        },
        "previous": {
            "model": _entity_result(previous_model) if previous_model else None,
            "categories": [_entity_result(category) for category in previous_categories],
        },
    }
    return page, _unique_entities([page, category, *previous_owners]), metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason task move behavior is exercised through deterministic report-run tests
def _move_task(action, _report, user, created):
    data = _data(action)
    task = _resolve_entity(
        data.get("task")
        or data.get("task_id")
        or data.get("task_ref")
        or data.get("task_action"),
        created,
        expected=Entities.TASK,
    )
    page = _resolve_entity(
        _first_data_reference(data, "to_page", "page"),
        created,
        expected=Entities.PAGE,
    )
    _require_allowed(
        task.allowed(Action.EDIT, user=user),
        "You do not have permission to move this task.",
    )
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to move tasks to this page.",
    )

    previous_page = task.page
    previous_owners = list(task.task_list_owners)
    task.page = page
    task.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-task-previous-owner",
            )
            for owner in previous_owners
        )
    )

    metadata = {
        "target": _entity_result(page),
        "page": _entity_result(page),
        "moved": {
            "from": _entity_result(previous_page) if previous_page else None,
            "to": _entity_result(page),
        },
        "previous": {
            "page": _entity_result(previous_page) if previous_page else None,
        },
    }
    return task, _unique_entities([task, page, *previous_owners]), metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason rename behavior is exercised through deterministic report-run tests
def _rename_entity(action, _report, user, created):
    data = _data(action)
    entity = _resolve_entity(_first_data_reference(data, "entity"), created)
    _require_allowed(
        entity.allowed(Action.EDIT, user=user),
        "You do not have permission to rename this entity.",
    )
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise exceptions.ValidationError("Rename entity actions require data.name.")

    previous_name = entity.name
    entity.name = name.strip()
    return (
        entity,
        [entity],
        {
            "previous": {"name": previous_name},
            "note": f"Renamed {previous_name} to {entity.name}.",
        },
    )


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_file_and_records_manual_page_cleanup_with_undo
# @features ai-report files
# @dimensions deterministic-run move-file manual-cleanup undo
def _move_file(action, _report, user, created):
    data = _data(action)
    source = _resolve_file_endpoint(data, created, endpoint="source")
    target = _resolve_file_endpoint(data, created, endpoint="target")
    file = _resolve_file_entity(data, created, source=source)
    if (
        getattr(source, "entity_kind", None) == getattr(target, "entity_kind", None)
        and getattr(source, "key", None) == getattr(target, "key", None)
    ):
        raise exceptions.ValidationError("File move source and target are the same.")

    _require_allowed(
        source.allowed(Action.EDIT, user=user),
        "You do not have permission to move files from this source.",
    )
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to move files to this target.",
    )
    if not _file_attached_to_endpoint(file, source):
        raise exceptions.ValidationError("File is not attached to the source.")

    _remove_file_from_endpoint(file, source)
    _add_file_to_endpoint(file, target)
    metadata = {
        "target": _entity_result(target),
        "moved": {
            "from": _entity_result(source),
            "to": _entity_result(target),
        },
        "previous": {
            "source": _entity_result(source),
            "target": _entity_result(target),
        },
        "file_summary": _file_summary_result(file),
    }
    return file, _unique_entities([file, source, target]), metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @reason file reference resolution is exercised through public file move tests
def _resolve_file_entity(data, created, source=None):
    reference = (
        data.get("file")
        or data.get("file_id")
        or data.get("file_ref")
        or data.get("file_action")
    )
    if reference:
        try:
            return _resolve_entity(reference, created, expected=Entities.FILE)
        except exceptions.ValidationError:
            file = _resolve_file_from_source(data, source, reference)
            if file is not None:
                return file
            raise

    file = _resolve_file_from_source(data, source)
    if file is not None:
        return file
    return _resolve_entity(reference, created, expected=Entities.FILE)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _resolve_file_from_source(data, source, reference=None):
    labels = _move_file_label_candidates(data, reference)
    if not labels or source is None:
        return None

    matches = [
        file
        for file in _endpoint_file_entities(source)
        if _file_matches_labels(file, labels)
    ]
    matches = _unique_entities(matches)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise exceptions.ValidationError(
            "File move file reference matched multiple source files."
        )
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _move_file_label_candidates(data, reference=None):
    candidates = []
    for value in [
        reference,
        data.get("display_name"),
        data.get("file_name"),
        data.get("file_label"),
        data.get("file_display"),
        data.get("filename"),
        data.get("name"),
    ]:
        if isinstance(value, dict):
            for key in ("display_name", "file_name", "file_label", "filename", "name"):
                if value.get(key):
                    candidates.append(value[key])
        elif value:
            candidates.append(value)
    return {
        str(candidate).strip().casefold()
        for candidate in candidates
        if str(candidate).strip()
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _endpoint_file_entities(endpoint):
    try:
        files = list(endpoint.files or [])
    except AttributeError:
        files = []
    return [file for file in files if isinstance(file, Entities.FILE)]


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _file_matches_labels(file, labels):
    for value in [file.name, file.filename, getattr(file, "display_name", None)]:
        if value and str(value).strip().casefold() in labels:
            return True
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @reason endpoint resolution is covered through public file move tests
def _resolve_file_endpoint(data, created, endpoint):
    if endpoint == "source":
        page_roots = ("from_page", "source_page", "page_from")
        task_roots = ("from_task", "source_task", "task_from")
    else:
        page_roots = ("to_page", "target_page", "destination_page", "page")
        task_roots = ("to_task", "target_task", "destination_task", "task")

    page_ref = _first_data_reference(data, *page_roots)
    task_ref = _first_data_reference(data, *task_roots)
    if bool(page_ref) == bool(task_ref):
        raise exceptions.ValidationError(
            f"File move {endpoint} requires exactly one page or task reference."
        )
    if page_ref:
        return _resolve_entity(page_ref, created, expected=Entities.PAGE)
    return _resolve_entity(task_ref, created, expected=Entities.TASK)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @reason reference alias lookup is covered through endpoint resolution tests
def _first_data_reference(data, *roots):
    for root in roots:
        for key in (root, f"{root}_id", f"{root}_ref", f"{root}_action"):
            value = data.get(key)
            if value:
                return value
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment mutation is covered through move and undo tests
def _file_attached_to_endpoint(file, endpoint):
    if isinstance(endpoint, Entities.PAGE):
        return endpoint.key in list(file.db.get("pages") or [])
    if isinstance(endpoint, Entities.TASK):
        return (
            endpoint.key in list(file.db.get("tasks") or [])
            or file.key in list(endpoint.db.get("files") or [])
        )
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment mutation is covered through move and undo tests
def _remove_file_from_endpoint(file, endpoint):
    if isinstance(endpoint, Entities.PAGE):
        return file.properties.pages.remove(endpoint)
    if isinstance(endpoint, Entities.TASK):
        return endpoint.properties.files.remove(file)
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_move_file
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment mutation is covered through move and undo tests
def _add_file_to_endpoint(file, endpoint):
    if isinstance(endpoint, Entities.PAGE):
        return file.properties.pages.add(endpoint)
    if isinstance(endpoint, Entities.TASK):
        return endpoint.properties.files.add(file)
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason batch submission patching is exercised through deterministic report-run tests
def _update_submission_fields(action, _report, user, created):
    data = _data(action)
    updates = data.get("updates") or []
    if not isinstance(updates, list):
        raise exceptions.ValidationError("Submission update action requires updates.")
    if not updates:
        raise exceptions.ValidationError(SUBMISSION_UPDATE_ROWS_ERROR)

    applied = []
    skipped = []
    previous = []
    to_save = []
    for index, update in enumerate(updates, 1):
        if not isinstance(update, dict):
            skipped.append({"index": index, "reason": "Update row must be an object."})
            continue

        entity = _resolve_submission_update_entity(update, created)
        _require_allowed(
            entity.allowed(Action.EDIT, user=user),
            "You do not have permission to update this submission.",
        )
        schema_id = update.get("schema_id") or update.get("field_id")
        if not isinstance(schema_id, str) or not schema_id.strip():
            skipped.append({"index": index, "reason": "Missing schema_id."})
            continue
        schema_id = schema_id.strip()

        before = _submission_previous_value(entity, schema_id)
        try:
            changed, note = _apply_submission_field_update(
                entity,
                schema_id,
                update.get("new_value"),
            )
        except Exception as error:
            skipped.append(
                {
                    "index": index,
                    "entity": _entity_result(entity),
                    "schema_id": schema_id,
                    "reason": str(error),
                }
            )
            continue

        if not changed:
            skipped.append(
                {
                    "index": index,
                    "entity": _entity_result(entity),
                    "schema_id": schema_id,
                    "reason": note or "Value did not change.",
                }
            )
            continue

        record = {
            "index": index,
            "entity": _entity_result(entity),
            "schema_id": schema_id,
        }
        applied.append(record)
        previous.append(
            {
                **record,
                "had_value": before["had_value"],
                "previous_value": before["value"],
            }
        )
        to_save.append(entity)

    return (
        None,
        _unique_entities(to_save),
        {
            "updates": {"applied": applied, "skipped": skipped},
            "previous": previous,
            "note": _update_summary_note("Updated", applied, skipped),
        },
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason schema update behavior is exercised through deterministic report-run tests
def _update_form_schema(action, _report, user, created):
    data = _data(action)
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
    )
    _require_allowed(
        form.allowed(Action.EDIT, user=user),
        "You do not have permission to update this form schema.",
    )
    if getattr(form, "reserved", False):
        raise exceptions.ValidationError("Reserved forms cannot be updated by reports.")

    operations = data.get("operations") or []
    if not isinstance(operations, list):
        raise exceptions.ValidationError("Schema update action requires operations.")

    previous_schema = copy.deepcopy(form.schema or [])
    schema = copy.deepcopy(previous_schema)
    applied = []
    skipped = []
    for index, operation in enumerate(operations, 1):
        if not isinstance(operation, dict):
            skipped.append({"index": index, "reason": "Operation must be an object."})
            continue
        op = operation.get("op") or operation.get("type")
        if op == "add_field":
            result = _schema_add_field(schema, operation.get("field"))
        elif op == "add_select_option":
            result = _schema_add_select_option(schema, operation)
        else:
            result = None, "Unsupported schema operation."

        change, reason = result
        if change:
            applied.append({"index": index, **change})
        else:
            skipped.append({"index": index, "reason": reason})

    if applied:
        form.set_schema(schema)

    return (
        form,
        [form] if applied else [],
        {
            "form": _entity_result(form),
            "schema_updates": {"applied": applied, "skipped": skipped},
            "previous_schema": previous_schema,
            "note": _update_summary_note("Updated schema with", applied, skipped),
        },
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_update_submission_fields
# @reason row entity resolution is covered through batch submission report-run tests
def _resolve_submission_update_entity(update, created):
    page_reference = (
        update.get("page")
        or update.get("page_id")
        or update.get("page_ref")
        or update.get("page_action")
    )
    task_reference = (
        update.get("task")
        or update.get("task_id")
        or update.get("task_ref")
        or update.get("task_action")
    )
    if bool(page_reference) == bool(task_reference):
        raise exceptions.ValidationError(
            "Submission update rows require exactly one page or task reference."
        )
    if page_reference:
        return _resolve_entity(page_reference, created, expected=Entities.PAGE)
    return _resolve_entity(task_reference, created, expected=Entities.TASK)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_update_submission_fields
# @reason previous value capture is covered through undo tests
def _submission_previous_value(entity, schema_id):
    submission = getattr(entity, "submission", None)
    if not isinstance(submission, dict):
        submission = {}
    return {
        "had_value": schema_id in submission,
        "value": copy.deepcopy(submission.get(schema_id)),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_update_submission_fields
# @reason validation behavior is covered through batch submission report-run tests
def _apply_submission_field_update(entity, schema_id, value):
    if not getattr(entity, "form", None):
        return False, "Target has no form."

    submission = entity.properties.submission
    field = submission.fields.get(schema_id)
    if not field:
        return False, "Field is not in the target's current form schema."

    before = _submission_previous_value(entity, schema_id)
    field.reset()
    field.validate_ai(value)
    entity.save_submission()
    after = _submission_previous_value(entity, schema_id)
    changed = (
        before["had_value"] != after["had_value"]
        or before["value"] != after["value"]
    )
    if not changed:
        return False, "Value did not change after validation."
    return True, None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_update_form_schema
# @reason schema operation parsing is covered through schema update report-run tests
def _schema_add_field(schema, raw_field):
    field = _safe_schema_field(raw_field)
    if not field:
        return None, "Field definition is not valid for additive schema updates."
    if any(existing.get("id") == field["id"] for existing in schema):
        return None, f"Field {field['id']} already exists."

    schema.append(field)
    return {
        "op": "add_field",
        "schema_id": field["id"],
        "label": field.get("label") or field.get("title") or field["id"],
    }, None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_update_form_schema
# @reason schema operation parsing is covered through schema update report-run tests
def _schema_add_select_option(schema, operation):
    schema_id = operation.get("schema_id") or operation.get("field_id")
    if not isinstance(schema_id, str) or not schema_id.strip():
        return None, "Missing schema_id."
    schema_id = schema_id.strip()

    field = next(
        (
            candidate
            for candidate in schema
            if isinstance(candidate, dict) and candidate.get("id") == schema_id
        ),
        None,
    )
    if not field:
        return None, f"Field {schema_id} was not found."
    if field.get("type") not in {"select", "radio"}:
        return None, f"Field {schema_id} is not a select or radio field."

    option = operation.get("option") or {}
    value = option.get("value") if isinstance(option, dict) else None
    label = option.get("label") if isinstance(option, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None, "Option value is required."
    if not isinstance(label, str) or not label.strip():
        return None, "Option label is required."
    value = value.strip()
    label = label.strip()

    options = field.setdefault("options", [])
    if not isinstance(options, list):
        field["options"] = options = []
    if any(option.get("value") == value for option in options if isinstance(option, dict)):
        return None, f"Option {value} already exists."

    options.append({"value": value, "label": label})
    return {
        "op": "add_select_option",
        "schema_id": schema_id,
        "value": value,
        "label": label,
    }, None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_update_form_schema
# @reason field sanitization is covered through schema update report-run tests
def _safe_schema_field(raw_field):
    if not isinstance(raw_field, dict):
        return None
    field = copy.deepcopy(raw_field)
    schema_id = field.get("id")
    if not isinstance(schema_id, str) or not schema_id.strip():
        return None
    field["id"] = schema_id.strip()
    if field.get("type") in {"html", "signature"}:
        return None

    field["required"] = False
    field.pop("visibility", None)
    try:
        return canonicalize_schema([field])[0]
    except (IndexError, SchemaValidationError):
        return None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_update_submission_fields
# @covered-by lagniappe/core/tools/ai/report_runner.py::_update_form_schema
# @reason user-facing notes are asserted through report-run result tests
def _update_summary_note(prefix, applied, skipped):
    count = len(applied or [])
    skipped_count = len(skipped or [])
    if count and skipped_count:
        return f"{prefix} {count}; skipped {skipped_count}."
    if count:
        return f"{prefix} {count}."
    if skipped_count:
        return f"No changes applied; skipped {skipped_count}."
    return "No changes applied."


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_create_task
# @covered-by lagniappe/core/tools/ai/report_runner.py::_attach_file_to_page
# @reason page reference repair is exercised through task creation and attachment tests
def _resolve_action_page(data, created, user):
    reference = (
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action")
    )
    page_name = data.get("page_name") or data.get("page-name")

    if reference:
        key = _reference_key(reference)
        entity = created.get(key)
        if entity is None:
            entity = _fetch_report_entity(key, derived_page=True)
        if entity is None:
            named_page = _resolve_page_by_exact_name(page_name, user)
            if named_page is not None:
                return named_page

            if page_name:
                context_page = _page_from_created_context(created, page_name)
                if context_page is not None:
                    return context_page

            raise exceptions.ValidationError(f"Referenced entity not found: {key}")
        if isinstance(entity, Entities.PAGE):
            return entity

        derived_page = _page_from_non_page_reference(entity, page_name)
        if derived_page is not None:
            return derived_page

        named_page = _resolve_page_by_exact_name(page_name, user)
        if named_page is not None:
            return named_page

        context_page = _page_from_created_context(created, page_name)
        if context_page is not None:
            return context_page

        entity_name = getattr(entity, "name", None) or page_name or "The destination"
        entity_kind = (
            getattr(entity, "kind", None)
            or getattr(entity, "entity_kind", None)
            or "record"
        )
        raise exceptions.ValidationError(
            f"{entity_name} is a {entity_kind}, not a page."
        )

    named_page = _resolve_page_by_exact_name(page_name, user)
    if named_page is not None:
        return named_page

    raise exceptions.ValidationError("Missing required entity reference.")


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_resolve_action_page
# @reason non-page page inference is covered through task creation and attachment tests
def _page_from_non_page_reference(entity, page_name=None):
    if isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
        page = getattr(entity, "page", None)
        if page and _page_name_matches(page, page_name):
            return page
    if isinstance(entity, Entities.FILE):
        pages = [
            page
            for page in getattr(entity, "pages", []) or []
            if _page_name_matches(page, page_name)
        ]
        if len(pages) == 1:
            return pages[0]
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_resolve_action_page
# @reason unique prior page inference is covered through report-run attachment tests
def _page_from_created_context(created, page_name=None):
    candidates = {}
    for entity in created.values():
        page = None
        if isinstance(entity, Entities.PAGE):
            page = entity
        elif isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
            page = getattr(entity, "page", None)
        elif isinstance(entity, Entities.FILE):
            pages = [
                linked_page
                for linked_page in getattr(entity, "pages", []) or []
                if _page_name_matches(linked_page, page_name)
            ]
            if len(pages) == 1:
                page = pages[0]

        if page and _page_name_matches(page, page_name):
            candidates[getattr(page, "key", id(page))] = page

    return next(iter(candidates.values())) if len(candidates) == 1 else None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_resolve_action_page
# @reason exact page-name fallback is covered through task creation and attachment tests
def _resolve_page_by_exact_name(page_name, user):
    if not page_name:
        return None

    restrictions = getattr(getattr(user, "properties", None), "restrictions", None)
    required = getattr(restrictions, "search", [])
    belongs_to = getattr(restrictions, "belongs_to", [])
    results, _total = cache.search(
        page_name,
        required,
        belongs_to,
        kinds=["page"],
        limit=10,
    )
    normalized_name = _normalized_lookup_name(page_name)
    matches = [
        result
        for result in results
        if result.get("kind") == "page"
        and _normalized_lookup_name(result.get("name")) == normalized_name
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise exceptions.ValidationError(
            f"Page name {page_name!r} matched multiple pages."
        )

    page = Entities.fetch_one(matches[0]["id"], request=Fetch.direct())
    return page if isinstance(page, Entities.PAGE) else None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_resolve_action_page
# @reason page-name matching is covered through task creation and attachment tests
def _page_name_matches(page, page_name=None):
    if not page:
        return False
    if not page_name:
        return True
    return _normalized_lookup_name(page.name) == _normalized_lookup_name(page_name)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_resolve_action_page
# @reason lookup normalization is covered through task creation and attachment tests
def _normalized_lookup_name(value):
    return " ".join(str(value or "").strip().casefold().split())


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_create_task
# @reason completed task event detection is covered through report-run behavior
def _is_completed_task_event(data):
    return bool(
        data.get("completed_on")
        or data.get("completed-on")
        or data.get("completed")
    )


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_records_older_completed_event_without_mutating_live_task
# @tests tests_unit/test_020_ai_reports.py::test_run_report_promotes_newer_completed_event_to_live_task
# @tests tests_unit/test_020_ai_reports.py::test_run_report_reuses_one_created_task_for_multiple_completed_events
# @tests tests_unit/test_020_ai_reports.py::test_run_report_keeps_untargeted_same_model_tasks_distinct
# @tests tests_unit/test_020_ai_reports.py::test_run_report_loads_model_task_form_from_stored_key_for_history
# @tests tests_unit/test_020_ai_reports.py::test_run_report_reuses_existing_task_for_completed_event
# @tests tests_unit/test_020_ai_reports.py::test_run_report_automatically_reuses_dated_completed_task_family
# @tests tests_unit/test_020_ai_reports.py::test_run_report_keeps_ambiguous_completed_task_families_distinct
# @tests tests_unit/test_020_ai_reports.py::test_run_report_rejects_completed_task_target_from_another_page
# @features ai-report tasks task-completion
# @dimensions completed-task older-event name description attachments submission explicit-task-identity automatic-task-family period-name same-report ambiguity duplicate-task-prevention newest-completion live-task history-name model-form lazy-load distinct-task same-model existing-task page-validation
def _record_completed_task_event(
    action,
    data,
    page,
    form,
    project,
    model,
    report,
    user,
    created,
    context,
):
    action_record = context.get("action_record") or {}
    completed_on = _parse_completed_task_completed_on(data)
    submission = data.get("submission") if "submission" in data else None

    task, created_task = _find_or_create_completed_task(
        action,
        data,
        page,
        form,
        project,
        model,
        user,
        created,
    )
    _ensure_task_form_from_model(task, model)
    if form and not getattr(task, "form", None):
        task.form = form

    if created_task:
        name = _completed_event_task_name(action, data, page, model)
    else:
        name = task.name or _completed_event_task_name(action, data, page, model)
    description = data.get("description")
    project = _safe_entity_relation(task, "project") or project
    model = _safe_entity_relation(task, "model") or model
    task_form = _safe_entity_relation(task, "form") or form
    ai_debug(
        "report_runner.completed_task_event.resolved",
        report=_diagnostic_entity(report),
        action={
            "id": action.get("id"),
            "type": action.get("type"),
            "display_label": action.get("display_label"),
            "data_keys": sorted(data.keys()),
            "completed_on": completed_on,
            "submission_key_present": "submission" in data,
            "submission_field_count": (
                len(submission) if isinstance(submission, dict) else None
            ),
        },
        task=_diagnostic_entity(task),
        created_task=created_task,
        page=_diagnostic_entity(page),
        project=_diagnostic_entity(project),
        model=_diagnostic_entity(model),
        form=_diagnostic_entity(task_form),
        files=[],
    )
    if task_form is not None and "submission" not in data:
        _capture_missing_task_submission(
            action,
            data,
            report,
            page,
            project,
            model,
            task_form,
        )
    if _completed_event_belongs_in_history(task, completed_on):
        history_key = context.setdefault("prepared_keys", {}).get(
            action_record.get("idempotency_key")
        )
        if history_key is None and action_record.get("output_key"):
            history_key = database.get.datastore_key(
                action_record["output_key"]
            )
        history = task.create_history_entry(
            completed_on=completed_on,
            files=[],
            submission=submission,
            name=name,
            description=description,
            form=task_form,
            history_key=history_key,
        )
        metadata = _task_structure_result(task, project, model, task_form)
        metadata.update(
            {
                "page": _entity_result(page),
                "created": True,
                "target": _entity_result(task),
                "submission": _submission_result(
                    history,
                    data.get("submission_empty_reason"),
                ),
                "task_state_fingerprint": _task_state_fingerprint(task),
                "note": "Recorded as task history.",
            }
        )
        return history, _unique_entities([history, task]), metadata

    archived = []
    if _should_archive_live_completion(task):
        history_key = context.setdefault("prepared_keys", {}).get(
            f"{action_record.get('idempotency_key')}:history"
        )
        if history_key is None and action_record.get("history_output_key"):
            history_key = database.get.datastore_key(
                action_record["history_output_key"]
            )
        task.uncomplete(history_key=history_key)
        archived = list(getattr(task, "new_history_created", []) or [])

    _apply_completed_task_event(
        task,
        name,
        description,
        completed_on,
        [],
        submission,
        task_form,
    )
    saved = [task, page]
    for history in archived:
        saved.extend([history, *history.files])

    metadata = _task_structure_result(task, project, model, task_form)
    metadata.update(
        {
            "page": _entity_result(page),
            "created": created_task,
            "target": _entity_result(task),
            "submission": _submission_result(
                task,
                data.get("submission_empty_reason"),
            ),
            "created_histories": [
                _entity_result(history) for history in archived
            ],
            "task_state_fingerprint": _task_state_fingerprint(task),
            "note": (
                "Moved the previous completion to history."
                if archived
                else "Recorded as the task's current completion."
            ),
        }
    )
    return task, _unique_entities(saved), metadata


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason task reuse is covered through completed event report-run tests
def _find_or_create_completed_task(
    action,
    data,
    page,
    form,
    project,
    model,
    user,
    created,
):
    task = _find_completed_task_match(
        action,
        data,
        created,
        page,
        form,
        project,
        model,
        user,
    )
    if task is not None:
        return task, False

    name = _completed_event_task_name(action, data, page, model)
    task = Entities.TASK.create(
        {
            "page": page,
            "name": name,
            "description": data.get("description"),
            "form": form,
            "project": project,
            "model": model,
        }
    )
    return task, True


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_find_or_create_completed_task
# @reason task naming is verified through report-run completed event tests
def _completed_event_task_name(action, data, page, model):
    raw_name = data.get("name") or ""
    name = _strip_history_event_name(raw_name, getattr(page, "name", None))
    if name:
        return name
    if model and getattr(model, "name", None):
        return model.name
    return "Generated task"


_MONTH_NAMES = (
    "jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|"
    "aug|august|sep|sept|september|oct|october|nov|november|dec|december"
)
_NUMERIC_DATE_PATTERN = (
    r"(?:\d{4}[-_/ ]\d{1,2}[-_/ ]\d{1,2}|"
    r"\d{1,2}[-_/ ]\d{1,2}[-_/ ]\d{2,4})"
)
_MONTH_DATE_PATTERN = (
    rf"(?:(?:{_MONTH_NAMES})\.?\s+\d{{1,2}},?\s+\d{{4}}|"
    rf"(?:{_MONTH_NAMES})\.?\s+\d{{4}})"
)
_EVENT_DATE_PATTERN = rf"(?:{_NUMERIC_DATE_PATTERN}|{_MONTH_DATE_PATTERN})"


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_completed_event_task_name
# @reason normalized names are covered through report-run completed event tests
def _strip_history_event_name(value, page_name=None):
    name = " ".join(str(value or "").replace("_", " ").split())
    name = re.sub(r"\.(pdf|png|jpe?g|heic|txt|csv)$", "", name, flags=re.I)
    for _ in range(3):
        before = name
        name = re.sub(rf"^\s*{_EVENT_DATE_PATTERN}\s+", "", name, flags=re.I)
        name = _strip_leading_page_name(name, page_name)
        name = re.sub(
            rf"\s*(?:-|:|,)?\s*{_EVENT_DATE_PATTERN}\s*$",
            "",
            name,
            flags=re.I,
        )
        name = re.sub(
            (
                r"\s+(?:receipt|bill|invoice|payment confirmation|"
                r"confirmation|certificate|instal{1,2}ments?)\s*$"
            ),
            "",
            name,
            flags=re.I,
        )
        name = name.strip(" -:,.")
        if name == before:
            break
    return name or None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_strip_history_event_name
# @reason page prefix cleanup is covered through report-run tracker reuse tests
def _strip_leading_page_name(name, page_name):
    if not page_name:
        return name
    return re.sub(
        rf"^\s*{re.escape(str(page_name).strip())}\b\s*(?:-|:)?\s*",
        "",
        name,
        flags=re.I,
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_find_or_create_completed_task
# @covered-by lagniappe/core/tools/ai/report_runner.py::_capture_completed_task_before
# @reason deterministic task-family matching is exercised through report-run reuse tests
def _find_completed_task_match(
    action,
    data,
    created,
    page,
    form,
    project,
    model,
    user,
):
    """Resolve an explicit target or one unambiguous completed-task family."""
    task = _resolve_completed_task_target(
        data,
        created,
        page,
        form,
        project,
        model,
        user,
        optional=True,
    )
    if task is not None:
        return task

    name = _completed_event_task_name(action, data, page, model)
    matches = [
        candidate
        for candidate in _completed_task_candidates(page, created)
        if candidate.allowed(Action.EDIT, user=user)
        and _completed_task_family_matches(
            candidate,
            page,
            project,
            model,
            form,
            name,
        )
    ]
    return matches[0] if len(matches) == 1 else None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_find_completed_task_match
# @reason candidate collection is exercised through completed-task reuse and retry tests
def _completed_task_candidates(page, created):
    candidates = [*_page_task_candidates(page)]
    candidates.extend(
        entity
        for entity in created.values()
        if isinstance(entity, Entities.TASK)
        and _same_entity(_safe_entity_relation(entity, "page"), page)
    )
    unique = {}
    for task in candidates:
        key = getattr(task, "key", None)
        if key is not None:
            unique[key] = task
    return list(unique.values())


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_find_completed_task_match
# @reason exact task-family matching is exercised through completed-task reuse tests
def _completed_task_family_matches(task, page, project, model, form, name):
    if not _same_entity(_safe_entity_relation(task, "page"), page):
        return False
    if not _same_entity(_safe_entity_relation(task, "model"), model):
        return False
    if project is not None and not _same_entity(
        _safe_entity_relation(task, "project"), project
    ):
        return False

    task_form = _safe_entity_relation(task, "form") or _model_task_form(
        _safe_entity_relation(task, "model")
    )
    if form is not None and not _same_entity(task_form, form):
        return False

    return _normalized_task_name_key(task.name) == _normalized_task_name_key(name)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_completed_task_family_matches
# @reason normalized task-family names are exercised through dated completed-task reuse tests
def _normalized_task_name_key(name):
    name = _strip_history_event_name(name) or str(name or "")
    name = re.sub(r"[^a-z0-9]+", " ", name.lower())
    return " ".join(name.split())


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_find_completed_task_match
# @reason page task loading fallback is covered through completed-task reuse tests
def _page_task_candidates(page):
    candidates = []
    for attr in ("_tasks", "_completed"):
        values = getattr(page, attr, None)
        if isinstance(values, list):
            candidates.extend(values)

    if not candidates:
        try:
            candidates.extend(page.tasks or [])
            candidates.extend(page.completed or [])
        except Exception:
            pass

    unique = {}
    for task in candidates:
        key = getattr(task, "key", None)
        if key:
            unique[key] = task
    return list(unique.values())


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_find_completed_task_match
# @reason explicit task references remain the strict completed-task override
def _resolve_completed_task_target(
    data,
    created,
    page,
    form,
    project,
    model,
    user,
    optional=False,
):
    reference = _first_data_reference(data, "task")
    if not reference:
        if optional:
            return None
        raise exceptions.ValidationError("Missing required task reference.")

    task = _resolve_entity(reference, created, expected=Entities.TASK)
    _require_allowed(
        task.allowed(Action.EDIT, user=user),
        "You do not have permission to record history for this task.",
    )
    if not _same_entity(_safe_entity_relation(task, "page"), page):
        raise exceptions.ValidationError(
            "Completed task target does not belong to the referenced page."
        )

    actual_project = _safe_entity_relation(task, "project")
    actual_model = _safe_entity_relation(task, "model")
    actual_form = _safe_entity_relation(task, "form") or _model_task_form(
        actual_model
    )
    for label, supplied, actual in (
        ("project", project, actual_project),
        ("model task", model, actual_model),
        ("form", form, actual_form),
    ):
        if supplied is not None and not _same_entity(supplied, actual):
            raise exceptions.ValidationError(
                f"Completed task target has a different {label}."
            )
    return task


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_resolve_completed_task_target
# @reason relation identity comparison is exercised through completed-target validation
def _same_entity(left, right):
    if left is None or right is None:
        return left is right
    return getattr(left, "key", None) == getattr(right, "key", None)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason archive suppression is verified through completion promotion tests
def _should_archive_live_completion(task):
    if not task.completed:
        return False
    return bool(task.completed_on or task.files or _task_has_submission_data(task))


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason dated and dateless event placement is exercised through report-run completion tests
def _completed_event_belongs_in_history(task, completed_on):
    if not task.completed:
        return False
    if completed_on is None:
        return True
    current_completed_on = task.completed_on
    return current_completed_on is not None and completed_on <= current_completed_on


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason live task mutation is verified through completion event tests
def _apply_completed_task_event(
    task,
    name,
    description,
    completed_on,
    files,
    submission,
    form,
):
    task.name = name
    task.description = description
    if form:
        task.form = form
    task.completed = True
    task.completed_on = completed_on
    task.completed_by = None
    task.assigned_to = None
    task.due_date = None
    task.files = list(files or [])
    if submission is not None:
        task.ai_submission(submission)
    else:
        task.submission = None
        task.linked_pages = []


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason blank-submission detection is exercised through completion event tests
def _task_has_submission_data(task):
    return bool(getattr(task, "submission", None))


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason save-list deduplication supports report-run action results
def _unique_entities(entities):
    unique = []
    seen = set()
    for entity in entities:
        if entity is None:
            continue
        key = getattr(entity, "key", None) or id(entity)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entity)
    return unique


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_create_task
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason model-form inheritance is verified through report-run completed event tests
def _model_task_form(model):
    if model is None:
        return None

    form_property = getattr(getattr(model, "properties", None), "form", None)
    if form_property is not None and getattr(form_property, "is_set", False):
        form = form_property.value
        if form is not None:
            return form

    form_key = _stored_relation_key(model, "form")
    if not form_key:
        return None

    form = Entities.fetch_one(form_key, request=Fetch.direct())
    if form is not None:
        exceptions.capture(
            "AI report runner recovered a model task form from a stored relation key.",
            context={
                "ai_report_runner": {
                    "operation": "model_task_form_relation_recovered",
                    "model": _diagnostic_entity(model),
                    "form": _diagnostic_entity(form),
                    "form_key": str(form_key),
                }
            },
            level="warning",
        )
    else:
        exceptions.capture(
            "AI report runner found a model task form key but could not load the form.",
            context={
                "ai_report_runner": {
                    "operation": "model_task_form_relation_missing",
                    "model": _diagnostic_entity(model),
                    "form_key": str(form_key),
                }
            },
            level="warning",
        )
    return form if isinstance(form, Entities.FORM) else None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason page form inheritance is verified through report-run page creation tests
def _category_form(category):
    if category is None:
        return None

    form_property = getattr(getattr(category, "properties", None), "form", None)
    if form_property is not None and getattr(form_property, "is_set", False):
        form = form_property.value
        if form is not None:
            return form

    form = getattr(category, "form", None)
    if form is not None:
        return form

    form_key = _stored_relation_key(category, "form")
    if not form_key:
        return None

    form = Entities.fetch_one(form_key, request=Fetch.direct())
    return form if isinstance(form, Entities.FORM) else None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::_create_task
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::_task_structure_result
# @reason relation access failures are represented by omitted diagnostics
def _safe_entity_relation(entity, name):
    try:
        return getattr(entity, name, None)
    except Exception:
        return None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::_capture_missing_task_submission
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::_create_task
# @reason mismatched form type behavior is covered through public report runner tests
def _require_form_type(form, expected_type, message):
    if form is None:
        return
    form_type = getattr(form, "form_type", None)
    if form_type and form_type != expected_type:
        raise exceptions.ValidationError(message)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_capture_missing_task_submission
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::_capture_missing_task_submission
# @reason compact diagnostic projection is exercised through runner telemetry
def _diagnostic_file_refs(data):
    files = []
    if data.get("file"):
        files.append(data.get("file"))
    files.extend(data.get("files") or [])
    return files


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_create_task
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason existing task repair is verified through report-run completed event tests
def _ensure_task_form_from_model(task, model=None):
    if getattr(task, "form", None):
        return
    form = _model_task_form(model or getattr(task, "model", None))
    if form is not None:
        task.form = form


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_record_completed_task_event
# @reason date parsing failures are covered through the public report runner
def _parse_completed_task_completed_on(data):
    raw = data.get("completed_on") or data.get("completed-on")
    if not raw and data.get("completed") is True:
        return None
    raw = raw or data.get("completed")
    if not raw:
        raise exceptions.ValidationError(
            "Completed task evidence requires completed: true or a date."
        )

    completed_on = dates.parse_imported_date_as_utc(raw)
    if not completed_on:
        raise exceptions.ValidationError(
            "Completed task evidence completion date is invalid."
        )
    return completed_on


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason page attachment handling is covered through report action dispatch
def _attach_file_to_page(action, report, user, created):
    data = _data(action)
    page = _resolve_action_page(data, created, user)
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to attach files to this page.",
    )
    file = _resolve_report_file(
        data.get("file") or data.get("file_id") or data.get("file_ref"),
        report,
    )
    file.properties.pages.add(page)
    return file, [file, page], {"file_summary": _file_summary_result(file)}


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason task attachment handling is covered through report action dispatch
def _attach_file_to_task(action, report, user, created):
    data = _data(action)
    target = _resolve_entity(
        data.get("task")
        or data.get("task_id")
        or data.get("task_ref")
        or data.get("task_action"),
        created,
    )
    if not isinstance(target, (Entities.TASK, Entities.TASK_HISTORY)):
        raise exceptions.ValidationError(
            "Referenced entity is not a task or task history."
        )
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to attach files to this task.",
    )
    file = _resolve_report_file(
        data.get("file") or data.get("file_id") or data.get("file_ref"),
        report,
    )
    target.properties.files.add(file)
    return file, [file, target], {"file_summary": _file_summary_result(file)}


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason manual cleanup suggestions are represented through report results
def _manual_delete_page_action(action, _report, user, created):
    data = _data(action)
    page = _resolve_entity(
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action"),
        created,
        expected=Entities.PAGE,
    )
    _require_allowed(
        page.allowed(Action.VIEW, user=user),
        "You do not have permission to view this page.",
    )
    return (
        page,
        [],
        {
            "manual": {
                "type": "delete_page",
                "action": "delete",
                "reason": (
                    "Use the page delete button to confirm cleanup after "
                    "reviewing the completed report actions."
                ),
            },
            "note": "Manual cleanup suggested.",
        },
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason file summary actions are covered through report action dispatch
def _summarize_file(action, report, _user, _created):
    data = _data(action)
    file = _resolve_report_file(
        data.get("file") or data.get("file_id") or data.get("file_ref"),
        report,
    )
    summary = (data.get("summary") or data.get("description") or "").strip()
    if not summary:
        raise exceptions.ValidationError("Summarize file actions require summary text.")
    summarize = file.properties.summarize
    summarize.enabled = True
    summarize.search = data.get("search", True) is not False
    summarize.status = "Summary saved from report."
    summarize.error = None
    summarize.complete = True
    file.summary = summary
    return file, [file], {"file_summary": _file_summary_result(file)}


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason skip actions are covered through deterministic report action dispatch
def _skip_action(_action, _report, _user, _created):
    return None, []


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason review actions are covered through deterministic report action dispatch
def _needs_review_action(_action, _report, _user, _created):
    return None, []


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason created-reference bookkeeping is verified through ordered runner tests
def _remember_created(created, action, entity):
    for key in [action.get("id"), entity.key, entity.urlsafe_key]:
        if key:
            created[key] = entity


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason attachment target serialization is verified through report run outputs
def _attachment_target_result(action, to_save):
    if action.get("type") not in {"attach_file_to_page", "attach_file_to_task"}:
        return None
    if len(to_save) < 2:
        return None
    return _entity_result(to_save[1])


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason attachment metadata is verified through grouped result tests
def _action_attachment_results(action, to_save):
    return []


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::_entity_result
# @reason telemetry-only relation key projection is covered by result serialization
def _stored_relation_key(entity, name):
    relation = getattr(getattr(entity, "properties", None), name, None)
    if relation is not None:
        try:
            key = relation.key
        except Exception:
            key = None
        if key:
            return key

    db = getattr(entity, "db", None)
    if isinstance(db, dict):
        return db.get(name)
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_entity_result
# @reason fallback naming is exercised through task-history report results
def _entity_result_name(entity):
    try:
        name = entity.name
    except AttributeError:
        name = None
    return name or "Task history"


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason reference resolution is exercised through ordered runner tests
def _resolve_entity(reference, created, expected=None, optional=False):
    if not reference:
        if optional:
            return None
        raise exceptions.ValidationError("Missing required entity reference.")

    key = _reference_key(reference)
    entity = created.get(key)
    if entity is None:
        entity = _fetch_report_entity(key)

    if entity is None:
        if optional:
            return None
        raise exceptions.ValidationError(f"Referenced entity not found: {key}")

    if expected and not isinstance(entity, expected):
        raise exceptions.ValidationError(
            f"Referenced entity {key} is not a {expected.entity_kind}."
        )
    return entity


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason reference normalization is covered through runner reference tests
def _reference_key(reference):
    if isinstance(reference, dict):
        reference = reference.get("action") or reference.get("id") or reference.get("key")
    if isinstance(reference, str) and reference.startswith("$"):
        return reference[1:]
    if isinstance(reference, str) and reference.startswith("action:"):
        return reference.split(":", 1)[1]
    return reference


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason file-reference lookup is exercised by attach action tests
def _resolve_report_file(reference, report):
    if isinstance(reference, dict):
        reference = (
            reference.get("file")
            or reference.get("id")
            or reference.get("key")
            or reference.get("url")
            or reference.get("href")
        )

    references = _report_file_reference_candidates(reference)
    for file in report.input_files:
        if any(
            candidate in {file.urlsafe_key, file.key, file.name, file.filename}
            for candidate in references
        ):
            return file

    raise exceptions.ValidationError("Referenced report file was not found.")


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_resolve_report_file
# @reason helper behavior is covered through public report runner file matching tests
def _report_file_reference_candidates(reference):
    if reference is None:
        return []
    candidates = [reference]
    if isinstance(reference, str):
        text = reference.strip()
        if text and text != reference:
            candidates.append(text)
        if text.startswith("file:"):
            candidates.append(text.split(":", 1)[1])
        if "/files/" in text:
            path = text.split("/files/", 1)[1].split("?", 1)[0].split("#", 1)[0]
            file_id = path.strip("/").split("/", 1)[0]
            if file_id:
                candidates.append(file_id)
    return _unique_values(candidates)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_resolve_report_file
# @reason helper behavior is covered through public report runner file matching tests
def _unique_values(values):
    unique = []
    seen = set()
    for value in values:
        key = value if isinstance(value, (str, int, float, tuple)) else id(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason undo dispatch is exercised through public undo tests
def _undo_result_action(action, report, user):
    action_type = action.get("type")
    if (
        action_type == "create_task"
        and action.get("created") is False
        and (action.get("before") or {}).get("existing_task")
    ):
        return _undo_reused_completed_task(action, user)
    if action_type == "add_form_to_page":
        return _undo_add_form_to_page_action(action, user)
    if action_type == "add_category":
        return _undo_add_category_action(action, user)
    if action_type in {"move_page", "move_task", "move_file"}:
        return _undo_move_action(action, user)
    if action_type == "rename_entity":
        return _undo_rename_entity(action, user)
    if action_type == "update_submission_fields":
        return _undo_submission_updates(action, user)
    if action_type == "update_form_schema":
        return _undo_form_schema_update(action, user)
    if action_type in {"attach_file_to_page", "attach_file_to_task"}:
        return _undo_attachment_action(action, user)
    if action_type == "delete_page":
        return {"note": "Manual cleanup suggestion; nothing was executed."}
    if action_type == "summarize_file":
        return _undo_summarize_file(action, user)
    if action_type in {"skip", "needs_review"}:
        return {"note": "No created entities or links to undo."}
    if action_type and action_type.startswith("create_"):
        if action.get("created") is False:
            return {"note": "Reused existing entity; nothing deleted."}
        return _undo_created_result_entity(action, report, user)
    return {"note": "No undo handler for this action type."}


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason checkpoint resolution is exercised through completed-task undo
def _checkpoint_entity(details):
    return _load_result_entity(details) if details else None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason checkpoint resolution is exercised through completed-task undo
def _checkpoint_entities(details):
    return [
        entity
        for entity in (_checkpoint_entity(item) for item in details or [])
        if entity is not None
    ]


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason date restoration is exercised through completed-task undo
def _restore_checkpoint_datetime(value):
    if not value or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason asset restoration is owned by completed-task compensation
def _restore_task_checkpoint_assets(task, state, histories):
    previous = copy.deepcopy(state.get("assets") or {})
    for name, definition in list(task.assets.items()):
        if previous.get(name) != definition:
            task.delete_asset(name)

    task._assets = previous
    task.db["assets"] = json.dumps(previous)
    for history in histories:
        for name in list(getattr(history, "assets", {}).keys()):
            if name in previous:
                task.copy_asset(history.get_asset(name), name)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason reused-task restoration is asserted through public retry and undo
def _undo_reused_completed_task(action, user):
    before = action.get("before") or {}
    state = before.get("task") or {}
    task = _load_result_entity(before.get("entity"))
    if task is None:
        return {"note": "Reused task is missing."}
    _require_allowed(
        task.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this task.",
    )

    histories = _checkpoint_entities(action.get("created_histories"))
    _restore_task_checkpoint_assets(task, state, histories)
    current_relations = [
        getattr(task, name, None)
        for name in (
            "page",
            "form",
            "project",
            "model",
            "assigned_to",
            "assigned_by",
            "completed_by",
        )
    ]
    current_relations.extend(list(task.linked_pages or []))
    current_relations.extend(list(task.files or []))

    task.name = state.get("name")
    task.description = state.get("description")
    task.completed = bool(state.get("completed"))
    task.completed_on = _restore_checkpoint_datetime(state.get("completed_on"))
    task.due_date = _restore_checkpoint_datetime(state.get("due_date"))
    task.submission = copy.deepcopy(state.get("submission"))
    task.page = _checkpoint_entity(state.get("page"))
    task.form = _checkpoint_entity(state.get("form"))
    task.project = _checkpoint_entity(state.get("project"))
    task.model = _checkpoint_entity(state.get("model"))
    task.assigned_to = _checkpoint_entity(state.get("assigned_to"))
    task.assigned_by = _checkpoint_entity(state.get("assigned_by"))
    task.completed_by = _checkpoint_entity(state.get("completed_by"))
    task.linked_pages = _checkpoint_entities(state.get("linked_pages"))
    task.files = _checkpoint_entities(state.get("files"))
    task.db["history"] = bool(state.get("history", False))

    restored_relations = [
        getattr(task, name, None)
        for name in (
            "page",
            "form",
            "project",
            "model",
            "assigned_to",
            "assigned_by",
            "completed_by",
        )
    ]
    restored_relations.extend(task.linked_pages or [])
    restored_relations.extend(task.files or [])
    relations = _unique_entities([*current_relations, *restored_relations])
    if relations:
        task.add_mutation_intents(
            *(
                MutationIntent.touch(
                    relation,
                    reason="report-task-restored-relation",
                )
                for relation in relations
            )
        )
    Entities.save(*_unique_entities([task, *relations]))
    if histories:
        Entities.delete(*histories)
    return {
        "entity": _entity_result(task),
        "note": "Restored the task state from before the report action.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason page form restoration is covered through public undo tests
def _undo_add_form_to_page_action(action, user):
    previous = action.get("previous") or {}
    if previous.get("had_form"):
        return {"note": "Page already had this form; nothing changed."}

    page = _load_result_entity(action.get("entity"))
    if page is None:
        return {"note": "Page already missing."}
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this page's form.",
    )

    previous_details = previous.get("form")
    previous_form = _load_result_entity(previous_details)
    if previous_details and previous_form is None:
        return {"note": "Previous page form is no longer available."}

    current_owners = list(page.page_list_owners)
    page.form = previous_form
    if previous_form is not None:
        for category in page.page_list_owners:
            if isinstance(category, Entities.CATEGORY):
                category.properties.forms.add(previous_form)
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([page, previous_form, *current_owners]))
    return {
        "entity": _entity_result(page),
        "target": _entity_result(previous_form) if previous_form else None,
        "note": "Restored previous page form.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason category add restoration is covered through public undo tests
def _undo_add_category_action(action, user):
    previous = action.get("previous") or {}
    if previous.get("had_category"):
        return {"note": "Category was already present; nothing removed."}

    page = _load_result_entity(action.get("entity"))
    category = _load_result_entity(action.get("target"))
    if page is None or category is None:
        return {"note": "Page or category already missing."}
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to remove this category from the page.",
    )
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to undo this category add.",
    )

    current_owners = list(page.page_list_owners)
    category_key = getattr(category, "key", None)
    page.categories = [
        existing
        for existing in page.categories or []
        if getattr(existing, "key", None) != category_key
    ]
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([page, category, *current_owners]))
    return {
        "entity": _entity_result(page),
        "target": _entity_result(category),
        "note": "Removed added page category.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason move undo is exercised through public undo tests
def _undo_move_action(action, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Moved entity already missing."}
    if action.get("type") == "move_file":
        return _undo_file_move(action, entity, user)
    _require_allowed(
        entity.allowed(Action.EDIT, user=user),
        "You do not have permission to undo this move.",
    )

    if action.get("type") == "move_page":
        return _undo_page_move(action, entity, user)
    return _undo_task_move(action, entity, user)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason rename restoration is exercised through public undo tests
def _undo_rename_entity(action, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Renamed entity is missing."}
    _require_allowed(
        entity.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this entity name.",
    )
    previous_name = (action.get("before") or {}).get("name")
    entity.name = previous_name
    Entities.save(entity)
    return {
        "entity": _entity_result(entity),
        "note": "Restored previous entity name.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_undo_move_action
# @reason page move restoration is covered through public undo tests
def _undo_page_move(action, page, user):
    previous = action.get("previous") or {}
    previous_model = _load_result_entity(previous.get("model"))
    previous_categories = [
        category
        for category in (
            _load_result_entity(category)
            for category in previous.get("categories") or []
        )
        if category is not None
    ]
    if previous_model is not None:
        _require_allowed(
            previous_model.allowed(Action.EDIT, user=user),
            "You do not have permission to move this page back.",
        )

    current_owners = list(page.page_list_owners)
    page.model = previous_model
    page.categories = previous_categories
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([page, previous_model, *previous_categories, *current_owners]))
    return {
        "entity": _entity_result(page),
        "target": _entity_result(previous_model) if previous_model else None,
        "note": "Restored previous page category.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_undo_move_action
# @reason task move restoration is covered through public undo tests
def _undo_task_move(action, task, user):
    previous = action.get("previous") or {}
    previous_page = _load_result_entity(previous.get("page"))
    if previous_page is None:
        return {"entity": _entity_result(task), "note": "Previous page is missing."}
    _require_allowed(
        previous_page.allowed(Action.EDIT, user=user),
        "You do not have permission to move this task back.",
    )

    current_owners = list(task.task_list_owners)
    task.page = previous_page
    task.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-task-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([task, previous_page, *current_owners]))
    return {
        "entity": _entity_result(task),
        "target": _entity_result(previous_page),
        "note": "Restored previous task page.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_undo_move_action
# @reason file move restoration is covered through public undo tests
def _undo_file_move(action, file, user):
    previous = action.get("previous") or {}
    source = _load_result_entity(previous.get("source"))
    target = _load_result_entity(previous.get("target"))
    if source is None:
        return {"entity": _entity_result(file), "note": "Previous source is missing."}
    if target is None:
        return {"entity": _entity_result(file), "note": "Previous target is missing."}
    _require_allowed(
        source.allowed(Action.EDIT, user=user),
        "You do not have permission to move this file back.",
    )
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to unlink this file from its target.",
    )

    _remove_file_from_endpoint(file, target)
    _add_file_to_endpoint(file, source)
    Entities.save(*_unique_entities([file, source, target]))
    return {
        "entity": _entity_result(file),
        "target": _entity_result(source),
        "note": "Restored previous file attachment.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason submission update restoration is covered through public undo tests
def _undo_submission_updates(action, user):
    restored = []
    skipped = []
    to_save = []
    for previous in action.get("previous") or []:
        entity = _load_result_entity(previous.get("entity"))
        if entity is None:
            skipped.append({**previous, "reason": "Entity is missing."})
            continue
        _require_allowed(
            entity.allowed(Action.EDIT, user=user),
            "You do not have permission to restore this submission.",
        )
        schema_id = previous.get("schema_id")
        if not schema_id:
            skipped.append({**previous, "reason": "Missing schema_id."})
            continue
        _restore_submission_field(
            entity,
            schema_id,
            previous.get("had_value"),
            previous.get("previous_value"),
        )
        restored.append(
            {
                "entity": _entity_result(entity),
                "schema_id": schema_id,
            }
        )
        to_save.append(entity)

    if to_save:
        Entities.save(*_unique_entities(to_save))
    return {
        "updates": {"applied": restored, "skipped": skipped},
        "note": _update_summary_note("Restored", restored, skipped),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::_undo_submission_updates
# @reason field restoration is covered through public undo tests
def _restore_submission_field(entity, schema_id, had_value, previous_value):
    if getattr(entity, "form", None):
        field = entity.properties.submission.fields.get(schema_id)
        if field is not None:
            if had_value:
                field.db_value = previous_value
            else:
                field.unset()
            entity.save_submission()
            return

    submission = dict(getattr(entity, "submission", None) or {})
    if had_value:
        submission[schema_id] = previous_value
    else:
        submission.pop(schema_id, None)
    entity.properties.submission.value = submission or None
    if getattr(entity, "form", None):
        entity.db["schema_version"] = entity.form.version


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason schema restoration is covered through public undo tests
def _undo_form_schema_update(action, user):
    form = _load_result_entity(action.get("entity")) or _load_result_entity(
        action.get("form")
    )
    if form is None:
        return {"note": "Form already missing."}
    _require_allowed(
        form.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this form schema.",
    )
    previous_schema = action.get("previous_schema")
    if not isinstance(previous_schema, list):
        return {"entity": _entity_result(form), "note": "Previous schema missing."}

    form.set_schema(previous_schema)
    Entities.save(form)
    return {
        "entity": _entity_result(form),
        "note": "Restored previous form schema.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason created-entity deletion is exercised through public undo tests
def _undo_created_result_entity(action, report, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Entity already missing."}
    _require_allowed(
        entity.allowed(Action.DELETE, user=user)
        or entity.allowed(Action.EDIT, user=user),
        "You do not have permission to delete this report-created entity.",
    )
    touched = _detach_report_files_before_delete(entity, action, report)
    if touched:
        Entities.save(*touched)
    deleted = _entity_result(entity)
    Entities.delete(entity)
    return {"entity": deleted, "note": "Deleted report-created entity."}


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment unlinking is exercised through public undo tests
def _undo_attachment_action(action, user):
    file = _load_result_entity(action.get("entity"))
    target = _load_result_entity(action.get("target"))
    if file is None or target is None:
        return {"note": "Attachment target already missing."}
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to unlink this attachment.",
    )
    if (action.get("before") or {}).get("linked"):
        return {
            "entity": _entity_result(file),
            "target": _entity_result(target),
            "note": "Attachment already existed; nothing removed.",
        }
    if action.get("type") == "attach_file_to_page":
        changed = _remove_file_page_reference(file, target)
    else:
        changed = _remove_task_file_reference(target, file)
    if changed:
        Entities.save(file, target)
    return {
        "entity": _entity_result(file),
        "target": _entity_result(target),
        "note": (
            "Removed report-created file link."
            if changed
            else "Link already gone."
        ),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason file summary restoration is owned by public report compensation
def _undo_summarize_file(action, user):
    file = _load_result_entity(action.get("entity"))
    if file is None:
        return {"note": "Summarized file is missing."}
    _require_allowed(
        file.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this file summary.",
    )
    before = action.get("before") or {}
    previous = before.get("summarize") or {}
    file.summary = before.get("summary")
    summarize = file.properties.summarize
    for name in ("enabled", "search", "status", "error", "complete"):
        setattr(summarize, name, previous.get(name))
    Entities.save(file)
    return {
        "entity": _entity_result(file),
        "note": "Restored previous file summary state.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason result entity loading is exercised through public undo tests
def _load_result_entity(details):
    if not isinstance(details, dict) or not details.get("id"):
        return None
    return _fetch_report_entity(details["id"])


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason polymorphic report references are exercised through run and undo tests
def _fetch_report_entity(identifier, *, derived_page=False):
    entity = Entities.fetch_one(identifier, request=Fetch.root())
    if entity is None:
        return None

    if derived_page and not isinstance(entity, Entities.PAGE):
        request = Fetch.nested(because=FetchReason.DERIVED_PAGE_SAVE_REQUIREMENTS)
    elif isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
        request = Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS)
    else:
        request = Fetch.direct()

    return Entities.fetch_one(entity, request=request)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason report file preservation is exercised through public undo tests
def _detach_report_files_before_delete(entity, action, report):
    touched = []
    if isinstance(entity, Entities.PAGE):
        for file in report.input_files:
            if _remove_file_page_reference(file, entity):
                touched.append(file)
    elif isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
        files = _action_attachment_entities(action)
        if not files:
            files = list(getattr(entity, "files", []) or [])
        for file in files:
            if _remove_task_file_reference(entity, file):
                touched.append(file)
            if isinstance(entity, Entities.TASK_HISTORY):
                task = getattr(entity, "task", None)
                if task and _remove_history_task_file_reference(task, file, entity):
                    touched.append(file)
        if touched:
            touched.append(entity)
    return touched


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment loading is exercised through public undo tests
def _action_attachment_entities(action):
    entities = []
    for attachment in action.get("attachments") or []:
        entity = _load_result_entity(attachment.get("entity"))
        if entity is not None:
            entities.append(entity)
    return entities


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason relationship cleanup is exercised through public undo tests
def _remove_file_page_reference(file, page):
    before = list(file.db.get("pages") or [])
    after = [key for key in before if key != page.key]
    changed = before != after
    if after:
        file.db["pages"] = after
    else:
        file.db.pop("pages", None)
    return changed


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason relationship cleanup is exercised through public undo tests
def _remove_task_file_reference(task, file, *, remove_task_attachment=True):
    task_before = list(task.db.get("files") or [])
    task_after = [key for key in task_before if key != file.key]
    file_before = list(file.db.get("tasks") or [])
    file_after = [key for key in file_before if key != task.key]
    changed = file_before != file_after
    if remove_task_attachment:
        changed = changed or task_before != task_after
        if task_after:
            task.db["files"] = task_after
        else:
            task.db.pop("files", None)
    if file_after:
        file.db["tasks"] = file_after
    else:
        file.db.pop("tasks", None)
    return changed


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason history parent reverse-link cleanup is exercised through public undo tests
def _remove_history_task_file_reference(task, file, history):
    if file.key in list(task.db.get("files") or []):
        return False

    for linked in getattr(file, "tasks", []) or []:
        if getattr(linked, "key", None) == getattr(history, "key", None):
            continue
        if getattr(linked, "entity_kind", None) != "task_history":
            continue
        if getattr(getattr(linked, "task", None), "key", None) == task.key:
            return False

    return _remove_task_file_reference(task, file, remove_task_attachment=False)
