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
from lagniappe.core.tools import ai
from lagniappe.core.tools.ai import external_operations
from lagniappe.core.tools.database import agent_api as agent_api_store

from .base import DeferredJobAdapter
from ..errors import (
    DeferredJobDriftError,
)


# @testable infrastructure
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

    # @testable infrastructure
    def authorize(self, context):
        super().authorize(context)
        report = context.input("report")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred report user is invalid.")
        if not isinstance(report, Entities.REPORT):
            raise exceptions.ValidationError("Deferred report is invalid.")
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
    # @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_ask_report_adapter_prepares_and_applies_checkpointed_response
    # @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_organize_resumes_plan_checkpoint_without_second_planning_call
    # @matrix ai-report : proposal-publication status
    def apply(self, context):
        context.ensure_active()
        self.validate_apply(context)
        report = context.input("report")
        proposal = deepcopy(context.checkpoint["proposal"])
        report.properties.process.set_proposal(
            proposal,
            status=context.checkpoint.get("status") or "ready",
        )
        Entities.save(report, context.actor)
        return {
            "report_key": report.urlsafe_key,
            "status": report.status,
            "action_count": len(proposal.get("actions") or []),
        }

    # @testable infrastructure
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
        if active_job.get("key") == context.job.urlsafe_key:
            report.deferred_job = None
        if self.job_type is DeferredJobType.REPORT_ORGANIZE:
            ai.cleanup_report_upload_manifest(report)
            if report.upload_manifest:
                report.upload_manifest = None
        Entities.save(report, context.actor)

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
        if context.parameters.get("mode") == "revise" and report.proposal:
            report.properties.process.revision_failed(str(error))
        else:
            result = (
                {"error_context": error.context}
                if getattr(error, "context", None)
                else None
            )
            report.properties.process.fail(str(error), result=result)
        Entities.save(report, context.actor)

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        label = self.job_type.value.removeprefix("report-").title()
        revision = context.parameters.get("mode") == "revise"
        if succeeded:
            return f"{label} report {'revision ' if revision else ''}is ready."
        return f"{label} report failed. {str(error or '').strip()}".strip()


# @testable true
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_organize_retry_uses_priority_for_every_generation_stage
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_organize_prepare_stops_before_report_save_after_cancellation
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_organize_resumes_plan_checkpoint_without_second_planning_call
# @matrix ai-report : plan-resume submission-completion
# @matrix deferred-jobs : cancellation checkpoint quota retry service-tier
class OrganizeReportAdapter(ReportAdapter):
    job_type = DeferredJobType.REPORT_ORGANIZE
    required_ai_access = AI.CREATE

    def checkpoint_ready(self, context):
        checkpoint = context.checkpoint or {}
        return (
            checkpoint.get("schema_version") in {None, 1}
            and isinstance(checkpoint.get("proposal"), dict)
            and checkpoint.get("stage") in {None, "ready_to_apply"}
        )

    # @testable infrastructure
    def prepare(self, context):
        report = context.input("report")
        actor = context.actor
        checkpoint = context.checkpoint or {}
        stage = checkpoint.get("stage")
        stages = {
            None: 0,
            "uploads_finalized": 1,
            "summaries_ready": 2,
            "plan_ready": 3,
            "ready_to_apply": 4,
        }
        stage_index = stages.get(stage, 0)
        if checkpoint.get("schema_version") not in {None, 1} or (
            stage_index >= 3 and not isinstance(checkpoint.get("proposal"), dict)
        ):
            checkpoint = {}
            stage_index = 0
        service_tier = (
            "priority" if int(getattr(context.job, "attempt", 0) or 0) > 1 else None
        )
        if stage_index < 1:
            context.set_phase(DeferredJobPhase.PREPARING_INPUTS)
            ai.finalize_report_upload_manifest(
                report,
                actor,
                ensure_active=context.ensure_active,
            )
            context.checkpoint_stage(
                "uploads_finalized",
                phase=DeferredJobPhase.PREPARING_INPUTS.value,
            )
            stage_index = 1

        if stage_index < 2:
            context.set_phase(DeferredJobPhase.SUMMARIZING)
            summary_options = {
                "save": Entities.save,
                "ensure_active": context.ensure_active,
            }
            if service_tier:
                summary_options["service_tier"] = service_tier
            summarized = ai.summarize_report_input_files(report, **summary_options)
            if summarized:
                report.summary = f"Summarized {len(summarized)} file(s)."
                context.ensure_active()
                Entities.save(report, actor)
            context.checkpoint_stage(
                "summaries_ready",
                phase=DeferredJobPhase.SUMMARIZING.value,
            )
            stage_index = 2

        if stage_index < 3:
            context.set_phase(DeferredJobPhase.GENERATING)
            retrieval_context = ai.prepare_organize_retrieval_context(
                report,
                actor,
            )
            if context.parameters.get("mode") == "revise":
                prompt = ai.revise_organize_prompt(
                    report,
                    actor,
                    context.parameters.get("feedback"),
                    retrieval_context,
                )
            else:
                prompt = ai.organize_prompt(report, actor, retrieval_context)
            if service_tier:
                prompt.set_service_tier(service_tier)
            proposal = ai.generate_organize_plan(prompt)
            context.ensure_active()
            context.checkpoint_stage(
                "plan_ready",
                {"proposal": proposal},
                phase=DeferredJobPhase.VALIDATING.value,
            )
        else:
            proposal = context.checkpoint["proposal"]

        if stage_index < 4:
            context.set_phase(DeferredJobPhase.FINALIZING)
            proposal = ai.complete_organize_submissions(
                proposal,
                report,
                actor,
                service_tier=service_tier,
            )
            context.ensure_active()
            context.checkpoint_stage(
                "ready_to_apply",
                {"proposal": proposal, "status": "ready"},
                phase=DeferredJobPhase.PREPARED.value,
            )
        return None


# @testable true
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_ask_report_adapter_prepares_and_applies_checkpointed_response
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_answers_from_attached_corpus_receipt
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_uses_structured_filter_for_form_submission_query
# @matrix ai-report : ask async live-provider persistence revision status
# @pair deferred-jobs:checkpoint
class AskReportAdapter(ReportAdapter):
    job_type = DeferredJobType.REPORT_ASK
    required_ai_access = AI.ASK

    # @testable infrastructure
    def prepare(self, context):
        report = context.input("report")
        context.set_phase(DeferredJobPhase.GENERATING)
        if getattr(report, "input_files", None):
            context.set_phase(DeferredJobPhase.SUMMARIZING)
            ai.summarize_report_input_files(
                report,
                save=Entities.save,
                search=False,
                ensure_active=context.ensure_active,
            )
            context.set_phase(DeferredJobPhase.GENERATING)
        if context.parameters.get("mode") == "revise":
            prompt = ai.revise_ask_prompt(
                report,
                context.actor,
                context.parameters.get("feedback"),
            )
        else:
            prompt = ai.ask_prompt(report, context.actor)
        proposal = ai.generate_ask_report(prompt)
        context.set_phase(DeferredJobPhase.VALIDATING)
        return {
            "proposal": proposal,
            "status": "ready" if proposal.get("actions") else "complete",
        }


# @testable infrastructure
class CreateReportAdapter(ReportAdapter):
    job_type = DeferredJobType.REPORT_CREATE
    required_ai_access = AI.CREATE

    # @testable infrastructure
    def prepare(self, context):
        report = context.input("report")
        context.set_phase(DeferredJobPhase.GENERATING)
        if context.parameters.get("mode") == "revise":
            prompt = ai.revise_create_prompt(
                report,
                context.actor,
                context.parameters.get("feedback"),
            )
        else:
            prompt = ai.create_prompt(report, context.actor)
        return {
            "proposal": ai.generate_create_report(prompt),
            "status": "ready",
        }


# @testable true
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_report_execution_adapter_runs_the_reviewed_proposal
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_report_execution_failure_preserves_a_retryable_ledger
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_external_report_execution_start_rejects_stale_browser_snapshot
# @tests tests_unit/test_023e_deferred_job_adapters_reports.py::test_external_report_duplicate_cleanup_cannot_overwrite_new_api_proposal
# @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_adapters_declare_required_ai_tiers
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_saved_report_controls_do_not_require_provider_access
# @matrix ai-report : deterministic-run entitlement-independent recovery
# @matrix deferred-jobs : cancellation provider-boundary report-execution tier-declaration
# @matrix agent-api ai-report deferred-jobs : browser-review cas report-execution terminal-delivery
class ReportExecutionAdapter(DeferredJobAdapter):
    """Durably execute a reviewed report through its per-action ledger."""

    job_type = DeferredJobType.REPORT_EXECUTION
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
        authorization["proposal_fingerprint"] = _report_proposal_fingerprint(
            spec.inputs.get("report")
        )
        return authorization

    def started(self, context):
        report = context.input("report")
        external_snapshot = (
            external_operations.report_snapshot(report)
            if getattr(report, "origin", None) == "api"
            else None
        )
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
            Entities.save(report, context.actor)

    def authorize(self, context):
        report = context.input("report")
        super().authorize(context)
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred report user is invalid.")
        if not isinstance(report, Entities.REPORT):
            raise exceptions.ValidationError("Deferred report is invalid.")
        if not report.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to execute this report."
            )

    def validate_apply(self, context):
        report = context.input("report")
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
        if report.status == "complete" and result.get("status") == "complete":
            return DeferredJobInspection.APPLIED
        if report.status == "running":
            return DeferredJobInspection.NOT_APPLIED
        return DeferredJobInspection.DRIFTED

    def apply(self, context):
        context.ensure_active()
        self.validate_apply(context)
        report = context.input("report")
        result = ai.run_report(
            report,
            context.actor,
            ensure_active=context.ensure_active,
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

    def failure(self, context, error):
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

        external_snapshot = (
            external_operations.report_snapshot(report)
            if getattr(report, "origin", None) == "api"
            else None
        )
        result = report.result if isinstance(report.result, dict) else None
        if result and result.get("ledger_version") == ai.REPORT_LEDGER_VERSION:
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
