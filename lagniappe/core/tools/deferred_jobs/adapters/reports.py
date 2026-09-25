"""Deferred-job adapters for the reports domain."""

from copy import deepcopy

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobType,
    Fetch,
    MutationIntent,
)
from lagniappe.core.entities import Entities
from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint
from lagniappe.core.tools.ai import external_operations
from lagniappe.core.tools.ai import planner as report_planner
from lagniappe.core.tools.ai.reporting import uploads as report_uploads
from lagniappe.core.tools.ai.reporting.completion import files as report_files
from lagniappe.core.tools.ai.reporting.execution import ledger as report_ledger
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
from lagniappe.core.tools.database import agent_api as agent_api_store

from .base import DeferredJobAdapter
from ..errors import (
    DeferredJobDriftError,
)


# @testable true
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_report_phases_reuse_current_report_without_loading_input_files
# @matrix ai-report : input-files no-extra-read fresh-read
class ReportAdapter(DeferredJobAdapter):
    """Shared report generation and revision behavior."""

    queued_message = "Creating report..."
    retry_message = "The model is busy right now. We'll try again later."

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_report_replacement_supersedes_old_job_and_ignores_old_failure
    # @pairs ai-report:active-operation deferred-jobs:superseded
    def started(self, context):
        report = context.input("report")
        current = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
        if isinstance(current, Entities.REPORT):
            report = current
            context.inputs["report"] = report
        previous = report.deferred_job or {}
        if previous.get("key") and previous.get("key") != context.job.urlsafe_key:
            from ..service import DeferredJobs

            DeferredJobs.supersede(previous)
        report.deferred_job = {
            "key": context.job.urlsafe_key,
            "idempotency_key": context.job.idempotency_key,
            "revision": int(getattr(context.job, "status_revision", 0) or 0),
        }
        Entities.save(report, context.actor)

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_corrective_report_generation_requires_create_access
    # @pair ai-access:provider-boundary
    def authorize(self, context):
        super().authorize(context)
        report = context.input("report")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred report user is invalid.")
        if not isinstance(report, Entities.REPORT):
            raise exceptions.ValidationError("Deferred report is invalid.")
        if not report.available:
            raise exceptions.ValidationError("this plan is no longer available")
        if report.db.get("correction") and not context.actor.access(AI.CREATE):
            raise exceptions.ValidationError(
                "Creating corrective plans requires Create AI access."
            )
        if not report.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to update this report."
            )

    def validate_apply(self, context):
        """Only the operation recorded on the report may publish its proposal."""
        report = context.input("report")
        active_job = report.deferred_job or {}
        if active_job.get("key") != context.job.urlsafe_key:
            raise exceptions.ValidationError(
                "This report operation was replaced by a newer request."
            )

    # @testable infrastructure
    def inspect(self, context):
        report = Entities.fetch_one(
            context.input("report").urlsafe_key,
            request=Fetch.direct(),
        )
        if report is None:
            raise exceptions.ValidationError("Deferred report is missing.")
        context.inputs["report"] = report
        self.validate_apply(context)
        proposal = context.checkpoint.get("proposal")
        status = context.checkpoint.get("status")
        if report.proposal == proposal and report.status == status:
            return DeferredJobInspection.APPLIED
        if report.status in {"pending", "revising"}:
            return DeferredJobInspection.NOT_APPLIED
        return DeferredJobInspection.DRIFTED

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_ai_report_resumes_prepared_proposal
    # @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_answers_from_attached_corpus_receipt
    # @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_uses_structured_filter_for_form_submission_query
    # @matrix ai-report : proposal-publication status
    # @matrix ai-report : async persistence
    def apply(self, context):
        context.ensure_active()
        self.validate_apply(context)
        report = context.input("report")
        proposal = deepcopy(context.checkpoint["proposal"])
        if proposal.get("actions") and not context.actor.access(AI.CREATE):
            raise exceptions.ValidationError(
                "Creating proposals requires Create AI access."
            )
        from lagniappe.core.tools.ai.reporting.schema_updates import (
            prepare_schema_updates,
        )

        prepare_schema_updates(proposal, context.actor)
        snapshot = external_operations.report_snapshot(report)
        report.properties.process.set_proposal(proposal)
        report.file_usage = deepcopy(context.checkpoint.get("file_usage") or [])
        outcome = external_operations.save_plan_if_idle(
            report, snapshot,
            active_job=(context.job.key, context.job.lease_token),
        )
        if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
            raise DeferredJobDriftError("Report generation was cancelled or replaced.")
        return {
            "report_key": report.urlsafe_key,
            "status": report.status,
            "action_count": len(proposal.get("actions") or []),
        }

    # @testable true
    # @matrix ai-report : cancellation revision reload
    def cleanup(self, context, *, terminal):
        if not terminal:
            return
        report = context.input("report")
        if not isinstance(report, Entities.REPORT):
            return
        report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
        if not isinstance(report, Entities.REPORT):
            return
        context.inputs["report"] = report
        active_job = report.deferred_job or {}
        if active_job.get("key") != context.job.urlsafe_key:
            return
        snapshot = external_operations.report_snapshot(report)
        if context.job.status == "cancelled" and report.status in {"pending", "revising", "failed"}:
            if context.parameters.get("mode") == "revise" and report.proposal:
                report.properties.process.revision_failed("Generation cancelled.")
            else:
                report.status = "cancelled"
                report.pending = False
                report.error = "Generation cancelled. Retry to start again."
        if active_job.get("key") == context.job.urlsafe_key:
            report.deferred_job = None
        report_uploads.cleanup_report_upload_manifest(report)
        if report.upload_manifest:
            report.upload_manifest = None
        outcome = external_operations.save_plan_if_idle(report, snapshot)
        if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
            raise DeferredJobDriftError("Report changed during generation cleanup.")

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_report_replacement_supersedes_old_job_and_ignores_old_failure
    # @pair ai-report:failure-isolation
    def failure(self, context, error):
        report = context.input("report")
        if not isinstance(report, Entities.REPORT):
            return
        report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
        if not isinstance(report, Entities.REPORT):
            return
        context.inputs["report"] = report
        if (report.deferred_job or {}).get("key") != context.job.urlsafe_key:
            return
        snapshot = external_operations.report_snapshot(report)
        if context.parameters.get("mode") == "revise" and report.proposal:
            report.properties.process.revision_failed(str(error))
        else:
            result = (
                {"error_context": error.context}
                if getattr(error, "context", None)
                else None
            )
            report.properties.process.fail(str(error), result=result)
        external_operations.save_plan_if_idle(report, snapshot)

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        label = "AI"
        if context.job.status in {"cancelled", "superseded"}:
            return "AI report generation cancelled."
        revision = context.parameters.get("mode") == "revise"
        if succeeded:
            return f"{label} report {'revision ' if revision else ''}is ready."
        return f"{label} report failed. {str(error or '').strip()}".strip()


# @testable true
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_ai_report_resumes_prepared_proposal
# @matrix ai-report : plan-resume proposal-publication status
# @matrix deferred-jobs : quota retry service-tier cancellation
class AIReportAdapter(ReportAdapter):
    job_type = DeferredJobType.REPORT_AI
    required_ai_access = AI.ASK
    max_lifetime_seconds = 10 * 60
    resume_preparation = False

    def checkpoint_ready(self, context):
        checkpoint = context.checkpoint or {}
        return checkpoint.get("stage") == "ready_to_apply" and isinstance(
            checkpoint.get("proposal"), dict
        )

    def prepare(self, context):
        report, actor = context.input("report"), context.actor
        stage = (context.checkpoint or {}).get("stage")
        stage_index = {
            None: 0,
            "uploads_finalized": 1,
            "summaries_ready": 2,
            "ready_to_apply": 3,
        }.get(stage, 0)
        service_tier = (
            "priority" if int(getattr(context.job, "attempt", 0) or 0) > 1 else None
        )
        if stage_index < 1:
            context.set_phase(DeferredJobPhase.PREPARING_INPUTS)
            report_uploads.finalize_report_upload_manifest(
                report, actor, ensure_active=context.ensure_active
            )
            context.checkpoint_stage(
                "uploads_finalized", phase=DeferredJobPhase.PREPARING_INPUTS.value
            )
        if not report.input_files and not str(report.instructions or "").strip():
            raise exceptions.ValidationError(
                "Provide instructions or at least one file."
            )
        if stage_index < 2:
            context.set_phase(DeferredJobPhase.SUMMARIZING)
            report_files.summarize_report_input_files(
                report,
                save=Entities.save,
                search=actor.access(AI.CREATE),
                service_tier=service_tier,
                ensure_active=context.ensure_active,
            )
            context.checkpoint_stage(
                "summaries_ready", phase=DeferredJobPhase.SUMMARIZING.value
            )
        if stage_index < 3:
            context.set_phase(DeferredJobPhase.GENERATING)
            feedback = (
                context.parameters.get("feedback")
                if context.parameters.get("mode") == "revise"
                else None
            )
            prompt = report_planner.report_prompt(report, actor, feedback=feedback)
            if service_tier:
                prompt.set_service_tier(service_tier)
            prepared = report_planner.generate_report(prompt)
            context.ensure_active()
            prepared["status"] = (
                "ready" if prepared["proposal"].get("actions") else "complete"
            )
            context.checkpoint_stage(
                "ready_to_apply", prepared, phase=DeferredJobPhase.PREPARED.value
            )
        return None


# @testable true
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_report_execution_adapter_runs_the_reviewed_proposal
# @tests tests_unit/test_023c_deferred_job_runner.py::test_runner_schedules_report_dependency_checks_with_backoff
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_report_execution_failure_preserves_a_retryable_ledger
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_external_report_execution_start_rejects_stale_browser_snapshot
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_external_report_duplicate_cleanup_cannot_overwrite_new_api_proposal
# @tests tests_unit/test_034_experiments.py::test_execution_rejects_stale_proposals_and_reuses_exact_operations
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_report_phases_reuse_current_report_without_loading_input_files
# @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_adapters_declare_required_ai_tiers
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_saved_report_controls_do_not_require_provider_access
# @matrix ai-report : deterministic-run entitlement-independent recovery
# @matrix deferred-jobs : cancellation provider-boundary report-execution tier-declaration
# @matrix agent-api ai-report deferred-jobs : browser-review cas report-execution terminal-delivery
# @matrix ai-report : input-files no-extra-read fresh-read
# @matrix deferred-jobs : dependency-wait backoff
# @matrix experiments : execution-policy
class ReportExecutionAdapter(DeferredJobAdapter):
    """Durably execute a reviewed report through its per-action ledger."""

    job_type = DeferredJobType.REPORT_EXECUTION
    dependency_retry_delays = (5, 10, 20, 30)
    synchronous_testing = True
    queued_message = "Saving report changes..."
    retry_message = "Saving is taking longer than expected; retrying safely..."
    active_message = "Still saving report changes..."
    notification_policy = "none"

    def checkpoint_ready(self, _context):
        """The report's action ledger is the execution checkpoint."""
        return True

    def authorization(self, spec):
        authorization = super().authorization(spec)
        report = spec.inputs.get("report")
        # The MCP request gate checks this submitted identity before new work.
        # Replays must also match the receipt after legacy execution normalized
        # its saved proposal; the shared service still compares the entire job.
        authorization["proposal_fingerprint"] = (
            (report.agent_manifest or {}).get("proposal_fingerprint")
            if spec.parameters.get("experiments_execution")
            else _report_proposal_fingerprint(report)
        )
        return authorization

    def started(self, context):
        report = context.input("report")
        if getattr(report, "db", {}).get("superseded_by"):
            raise exceptions.ValidationError("This execution was superseded by an approved correction.")
        external_snapshot = (
            external_operations.report_snapshot(report)
            if getattr(report, "origin", None) == "api"
            else None
        )
        from lagniappe.core.tools.database.utility import ExactEntityState
        initial_state = deepcopy(dict(report.db))
        previous = report.deferred_job or {}
        previous_status = (
            previous.get("previous_status")
            if previous.get("key") == context.job.urlsafe_key
            else report.status
        )
        if previous.get("key") and previous.get("key") != context.job.urlsafe_key:
            from ..service import DeferredJobs

            DeferredJobs.supersede(previous)
        report.deferred_job = {
            "key": context.job.urlsafe_key,
            "idempotency_key": context.job.idempotency_key,
            "previous_status": previous_status,
            "revision": int(getattr(context.job, "status_revision", 0) or 0),
        }
        report.properties.process.begin_execution()
        if external_snapshot is not None:
            if hasattr(report, "add_mutation_intents"):
                report.add_mutation_intents(
                    MutationIntent.touch(
                        context.actor,
                        reason="external-report-execution-owner-invalidation",
                    )
                )
            outcome = external_operations.save_plan_if_idle(
                report,
                external_snapshot,
            )
            if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
                raise exceptions.ValidationError(
                    "This plan changed while execution was starting. Refresh it "
                    "before trying again."
                )
        else:
            report._form_additional_guards = [(report.key, ExactEntityState(initial_state))]
            Entities.save(report, context.actor)

    def authorize(self, context):
        report = context.input("report")
        if context.parameters.get("experiments_execution"):
            from lagniappe.core.tools.experiments import can_execute
            if not can_execute(context.actor, remote_mcp=True):
                raise exceptions.ValidationError("Experiments execution is no longer allowed for this actor.")
        if getattr(report, "db", {}).get("superseded_by"):
            raise exceptions.ValidationError("This execution was superseded by an approved correction.")
        super().authorize(context)
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred report user is invalid.")
        if not isinstance(report, Entities.REPORT):
            raise exceptions.ValidationError("Deferred report is invalid.")
        if not report.available:
            raise exceptions.ValidationError("this plan is no longer available")
        if not report.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to execute this report."
            )

    def validate_apply(self, context):
        report = context.input("report")
        if getattr(report, "db", {}).get("superseded_by"):
            raise exceptions.ValidationError("This execution was superseded by an approved correction.")
        active_job = report.deferred_job or {}
        if active_job.get("key") != context.job.urlsafe_key:
            raise exceptions.ValidationError(
                "This report execution was replaced by a newer request."
            )
        expected = (context.job.authorization or {}).get("proposal_fingerprint")
        if expected != _report_proposal_fingerprint(report):
            raise DeferredJobDriftError(
                "The report proposal changed while execution was queued."
            )

    def inspect(self, context):
        report = Entities.fetch_one(
            context.input("report").urlsafe_key,
            request=Fetch.direct(),
        )
        if report is None:
            raise exceptions.ValidationError("Deferred report is missing.")
        context.inputs["report"] = report
        self.validate_apply(context)
        result = report.result if isinstance(report.result, dict) else {}
        if report.db.get("execution_documents"):
            return DeferredJobInspection.NOT_APPLIED
        if report.status == "complete" and result.get("status") == "complete":
            return DeferredJobInspection.APPLIED
        if report.status == "running":
            return DeferredJobInspection.NOT_APPLIED
        return DeferredJobInspection.DRIFTED

    def apply(self, context):
        context.ensure_active()
        self.validate_apply(context)
        report = context.input("report")
        if getattr(report, "db", {}).get("superseded_by"):
            raise exceptions.ValidationError("This execution was superseded by an approved correction.")
        result = report_runner.run_report(
            report,
            context.actor,
            ensure_active=lambda: self._ensure_execution_active(context),
        )
        if result.get("status") != "complete":
            raise exceptions.ValidationError(
                report.error or "This report could not be completed."
            )
        return {
            "report_key": report.urlsafe_key,
            "status": report.status,
            "action_count": len(result.get("actions") or []),
        }

    # @testable false
    # @covered-by lagniappe/core/tools/deferred_jobs/adapters/reports.py::ReportExecutionAdapter
    # @reason ledger mutation boundaries recheck the shared execution policy
    def _ensure_execution_active(self, context):
        context.ensure_active()
        if context.parameters.get("experiments_execution"):
            from lagniappe.core.tools.experiments import can_execute
            actor = Entities.fetch_one(context.actor.key, request=Fetch.direct())
            if not can_execute(actor, remote_mcp=True):
                raise exceptions.ValidationError("Experiments execution is no longer allowed for this actor.")

    def failure(self, context, error):
        report = context.input("report")
        if getattr(report, "db", {}).get("superseded_by"):
            raise exceptions.ValidationError("This execution was superseded by an approved correction.")
        if not isinstance(report, Entities.REPORT):
            return
        report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
        if not isinstance(report, Entities.REPORT):
            return
        context.inputs["report"] = report
        active_job = report.deferred_job or {}
        if active_job.get("key") != context.job.urlsafe_key:
            return

        external_snapshot = (
            external_operations.report_snapshot(report)
            if getattr(report, "origin", None) == "api"
            else None
        )
        result = report.result if isinstance(report.result, dict) else None
        if result and result.get("ledger_version") == report_ledger.REPORT_LEDGER_VERSION:
            result["status"] = "failed"
            if not result.get("failed_at"):
                for index, action in enumerate(result.get("actions") or [], 1):
                    if action.get("status") not in {"complete", "skipped"}:
                        result["failed_at"] = index
                        break
            report.properties.process.fail(str(error), result=result)
        else:
            report.properties.process.restore_after_execution_failure(
                str(error),
                previous_status=active_job.get("previous_status"),
            )
        if external_snapshot is not None:
            if hasattr(report, "add_mutation_intents"):
                report.add_mutation_intents(
                    MutationIntent.touch(
                        context.actor,
                        reason="external-report-execution-owner-invalidation",
                    )
                )
            external_operations.save_plan_if_idle(report, external_snapshot)
        else:
            Entities.save(report, context.actor)

    def cleanup(self, context, *, terminal):
        if not terminal:
            return
        report = context.input("report")
        if getattr(report, "db", {}).get("superseded_by"):
            raise exceptions.ValidationError("This execution was superseded by an approved correction.")
        if not isinstance(report, Entities.REPORT):
            return
        report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
        if not isinstance(report, Entities.REPORT):
            return
        context.inputs["report"] = report
        if (report.deferred_job or {}).get("key") == context.job.urlsafe_key:
            external_snapshot = (
                external_operations.report_snapshot(report)
                if getattr(report, "origin", None) == "api"
                else None
            )
            report.deferred_job = None
            if external_snapshot is not None:
                if hasattr(report, "add_mutation_intents"):
                    report.add_mutation_intents(
                        MutationIntent.touch(
                            context.actor,
                            reason="external-report-execution-owner-invalidation",
                        )
                    )
                external_operations.save_plan_if_idle(report, external_snapshot)
            else:
                Entities.save(report, context.actor)

    def terminal_message(self, context, *, succeeded, error=None):
        if succeeded:
            return "Report changes are saved."
        return f"Report execution failed. {str(error or '').strip()}".strip()


# @testable false
# @covered-by lagniappe/core/tools/deferred_jobs/adapters/reports.py::ReportExecutionAdapter
# @reason execution authorization and drift checks own this canonical proposal hash
def _report_proposal_fingerprint(report):
    return proposal_fingerprint(getattr(report, "proposal", None))
