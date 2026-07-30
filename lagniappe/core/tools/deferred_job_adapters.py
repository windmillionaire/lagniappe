"""Domain adapters for the shared durable deferred-job runner."""

from copy import deepcopy
import hashlib
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobStatus,
    DeferredJobType,
    Fetch,
    FetchReason,
    FileConsumer,
    Resource,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, database, files, site_export
from lagniappe.core.tools.database import assets as storage_assets

from .deferred_jobs import (
    AUTOFILL_FORM_LOCK_SCOPE,
    DeferredJobAdapter,
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
    DeferredJobDriftError,
    active_deferred_job_lock,
    deferred_job_lock_key,
)


# @testable infrastructure
class ReportAdapter(DeferredJobAdapter):
    """Shared report generation and revision behavior."""

    queued_message = "Creating report..."
    retry_message = "The model is busy right now. We'll try again later."

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_report_replacement_supersedes_old_job_and_ignores_old_failure
    # @pair deferred-jobs:superseded
    # @pair ai-report:active-operation
    def started(self, context):
        report = context.input("report")
        current = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
        if isinstance(current, Entities.REPORT):
            report = current
            context.inputs["report"] = report
        previous = report.deferred_job or {}
        if previous.get("key") and previous.get("key") != context.job.urlsafe_key:
            from .deferred_jobs import DeferredJobs

            DeferredJobs.supersede(previous)
        report.deferred_job = {
            "key": context.job.urlsafe_key,
            "idempotency_key": context.job.idempotency_key,
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

    # @testable infrastructure
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
    # @tests tests_unit/test_023_deferred_jobs.py::test_report_replacement_supersedes_old_job_and_ignores_old_failure
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
# @tests tests_unit/test_023_deferred_jobs.py::test_organize_retry_uses_priority_for_every_generation_stage
# @tests tests_unit/test_023_deferred_jobs.py::test_organize_prepare_stops_before_report_save_after_cancellation
# @tests tests_unit/test_023_deferred_jobs.py::test_organize_resumes_plan_checkpoint_without_second_planning_call
# @pair deferred-jobs:service-tier
# @pair deferred-jobs:quota
# @pair deferred-jobs:retry
# @pair deferred-jobs:cancellation
# @pair deferred-jobs:checkpoint
# @pair ai-report:plan-resume
# @pair ai-report:submission-completion
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
            stage_index >= 3
            and not isinstance(checkpoint.get("proposal"), dict)
        ):
            checkpoint = {}
            stage_index = 0
        service_tier = (
            "priority"
            if int(getattr(context.job, "attempt", 0) or 0) > 1
            else None
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


# @testable infrastructure
class AskReportAdapter(ReportAdapter):
    job_type = DeferredJobType.REPORT_ASK
    required_ai_access = AI.ASK

    # @testable infrastructure
    def prepare(self, context):
        report = context.input("report")
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
# @tests tests_unit/test_023_deferred_jobs.py::test_report_execution_adapter_runs_the_reviewed_proposal
# @tests tests_unit/test_023_deferred_jobs.py::test_report_execution_failure_preserves_a_retryable_ledger
# @pair deferred-jobs:report-execution
# @pair deferred-jobs:cancellation
# @pair ai-report:deterministic-run
# @pair ai-report:recovery
class ReportExecutionAdapter(DeferredJobAdapter):
    """Durably execute a reviewed report through its per-action ledger."""

    job_type = DeferredJobType.REPORT_EXECUTION
    required_ai_access = AI.CREATE
    synchronous_testing = True
    queued_message = "Saving report changes..."
    retry_message = "Saving is taking longer than expected; retrying safely..."
    active_message = "Still saving report changes..."

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
        previous = report.deferred_job or {}
        previous_status = (
            previous.get("previous_status")
            if previous.get("key") == context.job.urlsafe_key
            else report.status
        )
        if previous.get("key") and previous.get("key") != context.job.urlsafe_key:
            from .deferred_jobs import DeferredJobs

            DeferredJobs.supersede(previous)
        report.deferred_job = {
            "key": context.job.urlsafe_key,
            "idempotency_key": context.job.idempotency_key,
            "previous_status": previous_status,
        }
        report.status = "running"
        report.pending = True
        report.error = None
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
            previous_status = active_job.get("previous_status")
            report.status = previous_status if previous_status == "failed" else "ready"
            report.pending = False
            report.error = str(error)
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
            report.deferred_job = None
            Entities.save(report, context.actor)

    def terminal_message(self, context, *, succeeded, error=None):
        if succeeded:
            return "Report changes are saved."
        return f"Report execution failed. {str(error or '').strip()}".strip()


# @testable false
# @covered-by lagniappe/core/tools/deferred_job_adapters.py::ReportExecutionAdapter
# @reason execution authorization and drift checks own this canonical proposal hash
def _report_proposal_fingerprint(report):
    proposal = getattr(report, "proposal", None)
    canonical = json.dumps(
        proposal,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# @testable infrastructure
class AutofillAdapter(DeferredJobAdapter):
    job_type = DeferredJobType.AUTOFILL
    required_ai_access = AI.CREATE
    queued_message = "Autofilling form..."
    retry_message = "AI is temporarily busy; retrying autofill shortly..."
    dependency_message = "Waiting for attached file summaries before autofilling..."
    mutation_inputs = ()

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_autofill_revision_tracks_only_form_apply_state
    # @pairs deferred-jobs:form-revision ai:autofill
    def authorization(self, spec):
        authorization = super().authorization(spec)
        target = spec.inputs.get("target")
        authorization["form_revision"] = getattr(
            target,
            "autofill_revision",
            None,
        )
        return authorization

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_autofill_start_acquires_one_target_lock
    # @tests tests_unit/test_024_autofill_form_state.py::test_create_page_autofill_explicitly_opts_out_of_target_lock
    # @pairs deferred-jobs:form-lock ai:autofill pages:create-autofill
    def start_lock(self, spec, job):
        if spec.parameters.get("lock_target", True) is False:
            return None
        target = spec.inputs.get("target")
        if target is None:
            return None
        key = deferred_job_lock_key(target)
        if key is None:
            raise exceptions.ValidationError("Deferred autofill target is invalid.")
        return Entities.DEFERRED_JOB_LOCK.create(
            {
                "key": key,
                "scope": AUTOFILL_FORM_LOCK_SCOPE,
                "target": target.urlsafe_key,
                "operation": job.urlsafe_key,
                "idempotency_key": job.idempotency_key,
            }
        )

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_autofill_status_is_visible_to_target_editor
    # @pairs deferred-jobs:status ai:collaboration
    def can_view_status(self, job, actor):
        try:
            target = (job.inputs or {}).get("target")
            target = Entities.fetch_one(
                target.get("id"),
                request=Fetch.nested(
                    because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION
                ),
            )
        except (AttributeError, exceptions.ValidationError):
            return False
        return bool(
            isinstance(target, (Entities.PAGE, Entities.TASK))
            and target.allowed(Action.EDIT, user=actor)
        )

    # @testable infrastructure
    def load(self, context):
        super().load(context)
        target = context.input("target")
        if isinstance(target, Entities.TASK):
            context.inputs["target"] = Entities.fetch_one(
                target,
                request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
            )
        return context

    # @testable infrastructure
    def authorize(self, context):
        super().authorize(context)
        target = context.input("target")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred autofill user is invalid.")
        if not isinstance(target, (Entities.PAGE, Entities.TASK)):
            raise exceptions.ValidationError("Deferred autofill target is invalid.")
        if not target.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to autofill this form."
            )

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_autofill_revision_tracks_only_form_apply_state
    # @tests tests_unit/test_023_deferred_jobs.py::test_autofill_lock_cleanup_is_compare_and_delete
    # @tests tests_unit/test_024_autofill_form_state.py::test_lockless_create_page_autofill_keeps_revision_drift_guard
    # @pairs deferred-jobs:form-revision deferred-jobs:form-lock ai:autofill pages:create-autofill
    def validate_apply(self, context):
        target = context.input("target")
        if context.parameters.get("lock_target", True):
            active = active_deferred_job_lock(target)
            if active is None or active[1].urlsafe_key != context.job.urlsafe_key:
                raise DeferredJobDriftError(
                    "Autofill no longer owns this form. Run autofill again."
                )
        expected = (context.job.authorization or {}).get("form_revision")
        if expected != getattr(target, "autofill_revision", None):
            raise DeferredJobDriftError(
                "The form changed while autofill was running. Run autofill again."
            )

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_autofill_prepare_waits_for_attached_file_summaries
    # @features deferred-jobs ai files
    # @dimensions autofill summary-dependency pending failed
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.PREPARING_INPUTS)
        dependencies = ai.autofill_summary_dependencies(
            context.input("target"),
            context.actor,
        )
        if dependencies["failed"]:
            raise DeferredJobDependencyFailedError(
                "An attached file summary failed. Fix or remove that file, then "
                "run autofill again."
            )
        if dependencies["pending"]:
            complete = len(dependencies["complete"])
            total = complete + len(dependencies["pending"])
            context.set_phase(
                DeferredJobPhase.SUMMARIZING,
                completed=complete,
                total=total,
            )
            raise DeferredJobDependencyPendingError(
                "Attached file summaries are still processing."
            )

        record = context.parameters.get("upload_record")
        upload = (
            storage_assets.direct_upload_file(
                record,
                consumer=FileConsumer.AI_INLINE,
            )
            if record
            else None
        )
        prompt_data = ai.autofill_prompt_data(
            context.input("target"),
            context.actor,
            user_context=context.parameters.get("user_context"),
            file=upload,
            mimetype=context.parameters.get("mimetype"),
        )
        prompt = ai.form_autofill_prompt(**prompt_data)
        context.set_phase(DeferredJobPhase.GENERATING)
        return {"submission": ai.generate_autofilled_submission(prompt)}

    # @testable infrastructure
    def inspect(self, context):
        current = context.input("target").properties.submission.value
        if current == context.checkpoint.get("submission"):
            return DeferredJobInspection.APPLIED
        return DeferredJobInspection.NOT_APPLIED

    # @testable infrastructure
    def apply(self, context):
        context.ensure_active()
        target = context.input("target")
        target.ai_submission(deepcopy(context.checkpoint["submission"]))
        target.save()
        return {"target_key": target.urlsafe_key, "target_kind": target.entity_kind}

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_autofill_terminal_cleanup_releases_target_lock
    # @pairs deferred-jobs:terminal-cleanup deferred-jobs:form-lock
    def cleanup(self, context, *, terminal):
        record = context.parameters.pop("upload_record", None)
        context.job.parameters = context.parameters
        if terminal:
            target = context.input("target")
            target_reference = (getattr(context.job, "inputs", None) or {}).get(
                "target",
                {},
            )
            if not isinstance(target_reference, dict):
                target_reference = {}
            target_key = getattr(target, "urlsafe_key", None) or target_reference.get(
                "id"
            )
            operation = getattr(context.job, "urlsafe_key", None)
            if (
                context.parameters.get("lock_target", True)
                and target_key
                and operation
            ):
                lock_key = deferred_job_lock_key(target_key)
                database.release_deferred_job_lock(lock_key, operation)
        if terminal and record:
            storage_assets.delete_direct_upload(record)

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        target = context.input("target")
        label = "Task" if isinstance(target, Entities.TASK) else "Page"
        if succeeded:
            return f"{label} autofill is ready."
        return f"Autofill failed. {str(error or '').strip()}".strip()


# @testable infrastructure
class PageGenerationAdapter(DeferredJobAdapter):
    job_type = DeferredJobType.PAGE_GENERATION
    required_ai_access = AI.CREATE
    queued_message = "Generating pages..."
    retry_message = "AI is temporarily busy; retrying page generation shortly..."
    success_message = "Generated pages are ready."
    failure_prefix = "Page generation failed."
    mutation_inputs = ("category", "form")

    # @testable infrastructure
    def authorize(self, context):
        super().authorize(context)
        category = context.input("category")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred page generation user is invalid.")
        if not isinstance(category, Entities.CATEGORY):
            raise exceptions.ValidationError("Deferred page generation category is invalid.")
        if not category.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to edit this category."
            )
        form = context.input("form")
        if form is not None and (
            not isinstance(form, Entities.FORM)
            or not form.allowed(Action.VIEW, user=context.actor)
        ):
            raise exceptions.ValidationError(
                "You do not have permission to use this form."
            )

    # @testable infrastructure
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.GENERATING)
        category = context.input("category")
        form = context.input("form")
        fields = context.parameters.get("fields") or {}
        form_schema = form.schema if form else None
        prompt = ai.page_generation_prompt(
            category_name=category.name,
            category_description=category.description,
            category_id=category.urlsafe_key,
            form_id=form.urlsafe_key if form else None,
            user_request=fields.get("user_description"),
            num_pages=fields.get("num_pages"),
            form_schema=form_schema,
            user=context.actor,
        )
        generated = ai.generate_pages(prompt, form_schema=form_schema)
        records = []
        for item in generated:
            key = database.create_key("page", None)
            records.append(
                {
                    "key": database.get.urlsafe_key(key),
                    "page": item,
                }
            )
        return {"pages": records}

    # @testable infrastructure
    def inspect(self, context):
        records = context.checkpoint.get("pages") or []
        if not records:
            return DeferredJobInspection.APPLIED
        existing = [
            Entities.fetch_one(record["key"], request=Fetch.direct())
            for record in records
        ]
        return (
            DeferredJobInspection.APPLIED
            if all(existing)
            else DeferredJobInspection.NOT_APPLIED
        )

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_page_generation_apply_uses_direct_fields_and_form_fallbacks
    # @pairs ai:page-generation pages:form-defaults pages:no-form
    def apply(self, context):
        context.ensure_active()
        category = context.input("category")
        form = context.input("form")
        pages = []
        for record in context.checkpoint.get("pages") or []:
            existing = Entities.fetch_one(record["key"], request=Fetch.direct())
            if existing:
                pages.append(existing)
                continue
            generated = deepcopy(record["page"])
            submission = generated.get("submission")
            if not isinstance(submission, dict):
                submission = {}
            name = generated.get("name") or submission.get("name")
            description = generated.get("description") or submission.get("description")
            page = Entities.PAGE.create(
                {
                    "model": category,
                    "form": form,
                    "name": name,
                    "description": description,
                }
            )
            page._key = database.get.datastore_key(record["key"])
            if generated.get("document"):
                page.properties.document.html = generated["document"]
            if form and submission:
                schema_ids = {
                    field.get("id")
                    for field in form.schema or []
                    if isinstance(field, dict)
                }
                if name and "name" in schema_ids:
                    submission["name"] = name
                if description and "description" in schema_ids:
                    submission["description"] = description
                page.ai_submission(submission)
            pages.append(page)
        Entities.save(*pages, category)
        return {"page_keys": [page.urlsafe_key for page in pages]}


# @testable infrastructure
class SiteExportAdapter(DeferredJobAdapter):
    job_type = DeferredJobType.SITE_EXPORT
    synchronous_testing = True
    queued_message = "Building HTML export archive..."
    success_message = "HTML export archive is ready."
    failure_prefix = "HTML export failed."

    def checkpoint_ready(self, _context):
        """Site export has no provider preparation; its durable record is the intent."""
        return True

    # @testable infrastructure
    def authorize(self, context):
        if not isinstance(context.actor, Entities.USER) or not Resource.SITE.allowed(
            Action.VIEW,
            user=context.actor,
        ):
            raise exceptions.ValidationError(
                "You do not have permission to export this site."
            )

    # @testable infrastructure
    def inspect(self, context):
        record = database.site_export(context.parameters.get("export_id"))
        if record and record.get("status") == "complete":
            return DeferredJobInspection.APPLIED
        if record and record.get("status") in {"queued", "running", "failed"}:
            return DeferredJobInspection.NOT_APPLIED
        return DeferredJobInspection.DRIFTED

    # @testable infrastructure
    def apply(self, context):
        context.ensure_active()
        export_id = context.parameters["export_id"]
        database.update_site_export(
            export_id,
            {"status": "running", "started": site_export._utc(), "error": None},
        )
        updates = site_export.build_site_export(export_id)
        record = database.update_site_export(export_id, updates)
        return {key: value for key, value in dict(record or {}).items() if key != "type"}

    # @testable infrastructure
    def failure(self, context, error):
        export_id = context.parameters.get("export_id")
        if export_id:
            database.update_site_export(
                export_id,
                {
                    "status": "failed",
                    "completed": site_export._utc(),
                    "error": str(error),
                },
            )


# @testable infrastructure
class FileAdapter(DeferredJobAdapter):
    completion_notification_only = True

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_file_adapter_drift_tracks_the_original_asset
    # @features deferred-jobs file
    # @dimensions authorization original-asset fingerprint metadata-isolation
    def authorization(self, spec):
        authorization = super().authorization(spec)
        file = spec.inputs.get("file")
        try:
            asset_fingerprint = file.get_asset("file").fingerprint
        except AttributeError:
            asset_fingerprint = None
        if asset_fingerprint:
            authorization.pop("fingerprints", None)
            authorization["file_asset_fingerprint"] = asset_fingerprint
        return authorization

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_file_adapter_drift_tracks_the_original_asset
    # @features deferred-jobs file
    # @dimensions validation original-asset fingerprint metadata-isolation
    def validate_apply(self, context):
        expected = (context.job.authorization or {}).get(
            "file_asset_fingerprint"
        )
        if expected is None:
            return super().validate_apply(context)
        file = context.input("file")
        try:
            current = file.get_asset("file").fingerprint
        except AttributeError:
            current = None
        if current != expected:
            raise DeferredJobDriftError(
                "The original file changed while this operation was running."
            )

    # @testable infrastructure
    # @tests tests_unit/test_023_deferred_jobs.py::test_registered_ai_adapters_reject_restricted_actor_before_prepare
    def authorize(self, context):
        super().authorize(context)
        file = context.input("file")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Deferred file user is invalid.")
        if not isinstance(file, Entities.FILE):
            raise exceptions.ValidationError("Deferred file is invalid.")
        if not file.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to process this file."
            )

    # @testable infrastructure
    def notification_target(self, context):
        file = context.input("file")
        return file if isinstance(file, Entities.FILE) else None


# @testable infrastructure
class FileExtractAdapter(FileAdapter):
    job_type = DeferredJobType.FILE_EXTRACT
    mutation_inputs = ("file",)

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_file_extract_adapter_checkpoints_and_applies_text_asset
    # @features deferred-jobs file
    # @dimensions checkpoint extraction text-asset
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.PREPARING_INPUTS)
        file = context.input("file")
        extract = files.ocr_file(file, raise_errors=True)
        if not extract.complete:
            raise exceptions.ValidationError(
                extract.error or "Text extraction did not complete."
            )
        text_asset = deepcopy(file.assets.get("text"))
        if not text_asset:
            raise exceptions.ValidationError(
                "Extracted text could not be attached to the file."
            )
        return {
            "process": deepcopy(extract.section),
            "text_asset": text_asset,
        }

    # @testable infrastructure
    def inspect(self, context):
        file = Entities.fetch_one(
            context.input("file").urlsafe_key,
            request=Fetch.direct(),
        )
        if file is None:
            raise exceptions.ValidationError("Deferred file is missing.")
        context.inputs["file"] = file
        return (
            DeferredJobInspection.APPLIED
            if file.properties.extract.complete and file.get_asset("text")
            else DeferredJobInspection.NOT_APPLIED
        )

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_file_extract_adapter_checkpoints_and_applies_text_asset
    # @features deferred-jobs file
    # @dimensions checkpoint extraction text-asset
    def apply(self, context):
        context.ensure_active()
        file = context.input("file")
        text_asset = context.checkpoint.get("text_asset")
        if not isinstance(text_asset, dict):
            raise exceptions.ValidationError(
                "Extracted text asset metadata is missing."
            )
        file.assets["text"] = deepcopy(text_asset)
        file.db["assets"] = json.dumps(file.assets)
        file.properties.extract.section = context.checkpoint["process"]
        file.save()
        return {"file_key": file.urlsafe_key, "complete": True}

    # @testable infrastructure
    def failure(self, context, error):
        file = context.input("file")
        if isinstance(file, Entities.FILE):
            file.properties.extract.error = str(error)
            file.save()

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        file = context.input("file")
        name = getattr(file, "name", "file")
        if succeeded:
            return f"Text extraction complete for {name}"
        return f"Text extraction failed for {name}. {str(error or '').strip()}".strip()


# @testable infrastructure
class FileSummarizeAdapter(FileAdapter):
    job_type = DeferredJobType.FILE_SUMMARIZE
    required_ai_access = AI.CREATE
    mutation_inputs = ("file",)

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_file_summary_expected_rejection_is_not_reported_twice
    # @features deferred-jobs file
    # @dimensions summary expected-failure no-duplicate-capture
    def prepare(self, context):
        context.set_phase(DeferredJobPhase.SUMMARIZING)
        file = context.input("file")
        summarize = ai.generate_summary(file, raise_quota=True, raise_errors=True)
        if not summarize.complete:
            raise DeferredJobDependencyFailedError(
                summarize.error or "File summary did not complete."
            )
        return {
            "summary": file.summary,
            "process": deepcopy(summarize.section),
        }

    # @testable infrastructure
    def inspect(self, context):
        file = Entities.fetch_one(
            context.input("file").urlsafe_key,
            request=Fetch.direct(),
        )
        if file is None:
            raise exceptions.ValidationError("Deferred file is missing.")
        context.inputs["file"] = file
        if (
            file.summary == context.checkpoint.get("summary")
            and file.properties.summarize.complete
        ):
            return DeferredJobInspection.APPLIED
        return DeferredJobInspection.NOT_APPLIED

    # @testable infrastructure
    def apply(self, context):
        context.ensure_active()
        file = context.input("file")
        file.summary = context.checkpoint.get("summary")
        file.properties.summarize.section = context.checkpoint["process"]
        file.save()
        return {"file_key": file.urlsafe_key}

    # @testable infrastructure
    def failure(self, context, error):
        file = context.input("file")
        if isinstance(file, Entities.FILE):
            file.properties.summarize.error = str(error)
            file.save()

    # @testable true
    # @tests tests_unit/test_023_deferred_jobs.py::test_file_summary_terminal_cleanup_starts_extraction_once
    # @features deferred-jobs file
    # @dimensions terminal follow-up extraction idempotency summary-first
    def cleanup(self, context, *, terminal):
        if (
            not terminal
            or context.job.status
            not in {
                DeferredJobStatus.SUCCEEDED.value,
                DeferredJobStatus.FAILED.value,
            }
            or not context.parameters.get("extract_after_summary")
        ):
            return

        file = context.input("file")
        if not isinstance(file, Entities.FILE):
            return
        file.properties.extract.status = "Extracting text..."
        file.save()
        identity = hashlib.sha256(
            str(context.job.idempotency_key).encode("utf-8")
        ).hexdigest()
        files.start_file_extraction(
            file,
            actor=context.actor,
            idempotency_key=f"file-extract-follow-up:{identity}",
            delay_seconds=0,
        )
        context.parameters.pop("extract_after_summary", None)

    # @testable infrastructure
    def terminal_message(self, context, *, succeeded, error=None):
        file = context.input("file")
        name = getattr(file, "name", "file")
        if succeeded:
            return f"File summary complete for {name}"
        return f"File summary failed for {name}. {str(error or '').strip()}".strip()


# @testable infrastructure
def register_adapters(registry):
    """Register the clean-cutover deferred workflow cohort."""
    for adapter in (
        OrganizeReportAdapter(),
        AskReportAdapter(),
        CreateReportAdapter(),
        ReportExecutionAdapter(),
        AutofillAdapter(),
        PageGenerationAdapter(),
        SiteExportAdapter(),
        FileExtractAdapter(),
        FileSummarizeAdapter(),
    ):
        registry.register(adapter)
