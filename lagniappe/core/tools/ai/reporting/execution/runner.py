"""Deterministic execution of stored AI report proposals."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities

from ..proposals.validation import validate_proposal
from .actions.base import (
    ACTION_APPLIED,
    ACTION_DRIFTED,
)
from .actions.checkpoints import _record_action_result
from .actions.recovery import (
    _is_recoverable_action_error,
    _is_required_file_placement,
    _record_recoverable_action_error,
    _record_required_file_placement_error,
)
from .actions.registry import report_action_adapter
from .actions.results import (
    _diagnostic_entity,
)
from .ledger import (
    REPORT_LEDGER_VERSION,
    _new_report_ledger,
    _restore_completed_action_entities,
    _restore_created_action_entity,
    _validate_report_ledger,
    proposal_fingerprint,
)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_marks_missing_file_placements_failed_and_continues
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_skips_invalid_completed_task_events_and_continues
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_rejects_saved_pending_submissions_before_execution
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_checks_deferred_execution_guard
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_propagates_deferred_control_stop
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_resumes_after_completed_create_without_duplicate
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_retry_continues_independent_work_after_completed_entity_changes
# @tests tests_unit/test_020h_ai_report_execution.py::test_run_report_reconciles_applying_create_when_output_already_exists
# @tests tests_unit/test_020h_ai_report_execution.py::test_completed_task_retry_preserves_reused_completion
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_uses_category_form_from_stored_key_for_page_submission
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_attach_file_targets_created_task
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_loads_attached_inputs_only_for_pending_file_work
# @matrix ai-report : attachments cancellation completed-prefix continue create create-order deterministic-run execute idempotency partial-result permissions persistence post-commit-checkpoint recoverable recovery reuse skip-action stale-proposal validation
# @matrix ai-report files : execution-inputs initial-load staged-inputs
# @matrix ai-report : preservation unavailable
def run_report(report, user, ensure_active=None):
    """Prepare actions in order and commit bounded groups with their receipts."""
    from .batch import ExecutionBatch, WorkingEntities, publish_pending_documents
    from lagniappe.core.tools.deferred_jobs.errors import (
        DeferredJobDeadlineError, DeferredJobInfrastructureError,
        DeferredJobDependencyPendingError,
    )

    ensure_active = ensure_active or (lambda: None)
    ensure_active()
    if report.db.get("superseded_by"):
        raise exceptions.ValidationError("This execution was superseded by an approved correction.")
    if not report.available:
        raise exceptions.ValidationError("this plan is no longer available")
    publish_pending_documents(report)
    proposal = validate_proposal(report.proposal, allow_pending_submissions=False, user=user)
    fingerprint = proposal_fingerprint(proposal)
    existing = report.result if isinstance(report.result, dict) else {}
    if existing.get("ledger_version") == REPORT_LEDGER_VERSION:
        result = existing
        if result.get("proposal_fingerprint") != fingerprint:
            raise exceptions.ValidationError("This report proposal changed after execution started.")
        _validate_report_ledger(proposal, result)
        if result.get("status") == "complete":
            return result
    else:
        result = _new_report_ledger(report, proposal, fingerprint)

    actions = proposal.get("actions", [])
    if any(action["type"] in {"attach_file", "summarize_file"} and not action.get("skip")
           and record.get("status") not in {"complete", "skipped"}
           for action, record in zip(actions, result["actions"])):
        attached_files = [file for file in report.input_files if file.has_references]
        if attached_files:
            Entities.fetch(*attached_files, request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))

    result["status"] = "running"
    result.pop("failed_at", None)
    report.properties.process.begin_execution(result)
    ensure_active()
    Entities.save(report)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
    # @reason a rejected preparation rebuilds only the uncommitted group
    def begin_batch():
        workspace = WorkingEntities()
        for alias, entity in _restore_completed_action_entities(result).items():
            workspace.remember(entity)
            workspace[alias] = workspace[entity.key]
        context = _build_report_run_context(proposal)
        context["action_records"] = {record.get("id"): record for record in result["actions"] if record.get("id")}
        batch = ExecutionBatch(report, result, workspace, ensure_active)
        context["batch"] = batch
        return workspace, context, batch

    created, context, batch = begin_batch()
    index = 0
    while index < len(actions):
        ensure_active()
        action, record = actions[index], result["actions"][index]
        if record.get("status") in {"complete", "skipped"}:
            index += 1
            continue
        if action.get("skip") or any(context["action_records"].get(dependency, {}).get("status") != "complete" for dependency in action.get("depends_on", [])):
            record.update(status="skipped", note=action.get("reason") or "Skipped by user or required prior action.")
            index += 1
            continue
        adapter = report_action_adapter(action["type"])
        try:
            # An existing ambiguous action can still be reconciled. New ordinary
            # writes publish their complete receipts with the whole batch.
            if (record.get("status") == "applying" or (record.get("status") == "failed" and record.get("expected"))) and not record.get("migration_id"):
                state = adapter.inspect_applied(action, report, user, record)
                if state == ACTION_APPLIED:
                    record["status"] = "complete"
                    _restore_created_action_entity(created, record)
                    index += 1
                    continue
                if state == ACTION_DRIFTED:
                    raise exceptions.ValidationError("Recorded action state changed; reconcile it before retrying.")
            if not record.get("prepared"):
                adapter.prepare(action, report, user, created, context, record)
                record["prepared"] = True
            record["attempts"] = int(record.get("attempts") or 0) + 1
            record.pop("error", None)
            context["action_record"] = record
            ensure_active()
            entity, writes, metadata = adapter.apply(action, report, user, created, context)
            ensure_active()
            _record_action_result(record, action, entity, writes, metadata, created, context)
            if entity is not None and action["type"].startswith("create_") and metadata.get("created") is not False:
                created.new_keys.add(entity.key)
            record["status"] = "complete"
            record.pop("expected", None)
            batch.stage(index, entity, writes)
        except DeferredJobDependencyPendingError:
            # The migration handler flushes staged work before starting its job.
            record["status"] = "waiting"
            result["status"] = "waiting"
            report.result = result
            Entities.save(report)
            raise
        except (DeferredJobInfrastructureError, DeferredJobDeadlineError):
            batch.discard()
            raise
        except Exception as error:
            restart = min(batch.indices or [index])
            batch.discard()
            record = result["actions"][index]
            if _is_recoverable_action_error(action, error):
                if _is_required_file_placement(action):
                    _record_required_file_placement_error(record, error)
                    exceptions.capture(error, context={"ai_report_runner": {"operation": "required_file_placement_failed", "report": _diagnostic_entity(report), "action": {"id": action.get("id"), "type": action["type"]}, "error": str(error)}})
                    # Retain the visible failure while processing independent work.
                    record["batch_skipped"] = True
                else:
                    _record_recoverable_action_error(record, error)
                created, context, batch = begin_batch()
                index = restart
                if record.get("batch_skipped"):
                    record["status"] = "skipped"
                continue
            record.update(status="failed", error=str(error))
            record.pop("expected", None)
            result.update(status="failed", failed_at=index + 1)
            report.properties.process.fail(str(error), result=result)
            Entities.save(report)
            return result

        index += 1
        if batch.full and index < len(actions):
            try:
                batch.commit()
            except (DeferredJobInfrastructureError, DeferredJobDeadlineError):
                raise
            except Exception as error:
                return _fail_batch(report, result, batch, error)

    failures = [i for i, record in enumerate(result["actions"]) if record.pop("batch_skipped", False)]
    if failures:
        for i in failures:
            result["actions"][i]["status"] = "failed"
        result.update(status="failed", failed_at=failures[0] + 1)
        report.properties.process.fail("One or more files could not be attached. Review the failed placements and retry.", result=result)
    else:
        result["status"] = "complete"
        report.properties.process.complete_execution(result)
    try:
        batch.commit()
    except (DeferredJobInfrastructureError, DeferredJobDeadlineError):
        raise
    except Exception as error:
        return _fail_batch(report, result, batch, error)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason rejected batches retain pending actions and a visible manual retry
def _fail_batch(report, result, batch, error):
    indices = list(batch.indices)
    batch.discard()
    index = min(indices or [0])
    if result["actions"]:
        record = result["actions"][index]
        record.update(status="failed", error=str(error))
        record.pop("expected", None)
    result.update(status="failed", failed_at=index + 1)
    report.properties.process.fail(str(error), result=result)
    Entities.save(report)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason run-scoped report context setup is verified through report execution
def _build_report_run_context(proposal):
    return {}
