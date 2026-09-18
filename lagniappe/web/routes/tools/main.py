"""Routes for AI tool reports."""

from types import SimpleNamespace

from flask import abort, redirect, request, url_for
from flask_login import current_user

from lagniappe.core.definitions import (
    AI,
    Action,
    Resource,
    DeferredJobSpec,
    DeferredJobType,
    Fetch,
    FileConsumer,
    FileConsumerLimitError,
    INDIVIDUAL_FILES_ONLY_ERROR,
    enforce_file_consumer,
)
from lagniappe.core.entities import Entities
from lagniappe.core import exceptions
from lagniappe.core.tools import ai
from lagniappe.core.tools.ai import external_operations, report_history
from lagniappe.core.tools.database import agent_api as agent_api_store
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web.auth import ai_access, logged_in, require_ai_access

from . import tools


# @testable true
# @matrix ai-report : cancellation revision reload
@tools.route("/operations/<job_key>/cancel", methods=["POST"])
@logged_in
def cancel_generation(job_key):
    job = Entities.fetch_one(job_key, request=Fetch.direct())
    if not isinstance(job, Entities.DEFERRED_JOB) or job.job_type != DeferredJobType.REPORT_AI.value:
        abort(404)
    if job.actor.key != current_user.key and not current_user.has_permission(Resource.SITE, Action.EDIT):
        abort(403)
    if request.form.get("operation-id") != job.idempotency_key:
        abort(409, description="This generation control is stale. Refresh before trying again.")
    reference = (job.inputs or {}).get("report") or {}
    report = Entities.fetch_one(reference.get("id"), request=Fetch.direct())
    if not isinstance(report, Entities.REPORT):
        abort(404)
    if not report.available:
        abort(410, description="this plan is no longer available")
    if (report.deferred_job or {}).get("key") != job.urlsafe_key:
        abort(409, description="This report operation has changed.")
    DeferredJobs.cancel(job)
    if job.actor.key != current_user.key:
        return redirect(url_for("analytics.index"))
    return redirect(url_for("tools.report", key=report.urlsafe_key))


# @testable true
# @matrix ai-report : cancellation revision reload
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_corrective_plan_controls_require_create_access
# @pair ai-access:provider-boundary
@tools.route("/reports/<key>/retry-generation", methods=["POST"])
@ai_access(AI.ASK)
def retry_generation(key):
    report = _get_report(key)
    if report is None:
        abort(404)
    if report.db.get("correction"):
        require_ai_access(AI.CREATE)
    if report.origin == "api" or report.status not in {"failed", "cancelled"} or report.proposal or report.deferred_job:
        abort(409, description="This report cannot restart generation.")
    snapshot = external_operations.report_snapshot(report)
    report.properties.process.retry(None)
    outcome = external_operations.save_plan_if_idle(report, snapshot)
    if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
        abort(409, description="This report changed. Refresh before trying again.")
    try:
        DeferredJobs.start(DeferredJobSpec(
            job_type=DeferredJobType.REPORT_AI,
            actor=current_user._get_current_object(),
            idempotency_key=request.form.get("operation-id"),
            inputs={"report": report},
            notification_body="Creating AI report...",
            notification_target=report,
            client={"source_widget": "CreateToolReport", "destination": "tools:ToolReportList"},
        ))
    except Exception:
        report.properties.process.fail("Generation could not be started. Retry to start again.")
        Entities.save(report, current_user)
        raise
    return redirect(url_for("tools.report", key=report.urlsafe_key))

# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_organize_rejects_zero_byte_folder_placeholder
# @pair ai-report:upload
def _uploaded_report_files():
    files = []
    for upload in request.files.getlist("tool-files"):
        if not getattr(upload, "filename", None):
            continue
        size = enforce_file_consumer(
            upload,
            FileConsumer.AI_REPORT,
            filename=upload.filename,
        )
        if size == 0:
            raise exceptions.ValidationError(INDIVIDUAL_FILES_ONLY_ERROR)
        file = Entities.FILE.create(
            upload=upload,
            data={
                "filename": upload.filename,
                "mimetype": upload.content_type,
            },
            report_user=current_user._get_current_object(),
        )
        files.append(file)
    return files


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_ai_report
# @reason signed upload manifest parsing is exercised through the organize route
def _report_upload_manifest():
    direct_uploads.direct_upload_files(
        "tool-files",
        consumer=FileConsumer.AI_REPORT,
    )
    records = direct_uploads.direct_upload_records(
        request.form,
        input_name="tool-files",
    )
    return ai.prepare_report_upload_manifest(records)


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_ai_report
# @reason prompt preview uses upload metadata without persisting files
def _preview_report_files():
    files = []
    uploads = [
        {
            "filename": upload.filename,
            "content_type": upload.content_type,
        }
        for upload in request.files.getlist("tool-files")
    ]
    uploads.extend(
        direct_uploads.direct_upload_records(
            request.form,
            input_name="tool-files",
        )
    )
    for upload in uploads:
        filename = upload.get("filename")
        if not filename:
            continue
        files.append(
            SimpleNamespace(
                urlsafe_key=f"upload:{filename}",
                name=filename,
                filename=filename,
                mimetype=upload.get("content_type") or "application/octet-stream",
                summary=None,
            )
        )
    return files


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_ai_report
# @reason explain modal shares the real organize prompt assembly
def _explain_ai_prompt():
    report = SimpleNamespace(
        db={},
        origin="web",
        instructions=request.form.get("instructions"),
        input_files=_preview_report_files(),
    )
    return responses.explain(ai.report_prompt(report, current_user))


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_ai_report
# @reason route permission mirrors the final organize upload endpoint
@tools.route("/ai/direct-upload", methods=["POST"])
@ai_access(AI.ASK)
def create_ai_report_direct():
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_tool_starts_pending_report
# @matrix ai-report : create title-truncation
def _report_name(instructions):
    text = " ".join((instructions or "").split())
    if not text:
        return "Plan"
    suffix = "..." if len(text) > 80 else ""
    return f"{text[:80]}{suffix}"


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_ai_report
# @reason shared report persistence and dispatch are exercised through tool routes
def _start_tool_report(
    instructions,
    *,
    default_name,
    input_files=None,
    upload_manifest=None,
):
    input_files = list(input_files or [])
    report = Entities.REPORT.create(
        {
            "parent": current_user,
            "user": current_user,
            "name": request.form.get("name") or default_name,
            "instructions": instructions,
            "input_files": input_files,
            "upload_manifest": upload_manifest,
            "status": "pending",
            "pending": True,
        }
    )
    Entities.save(*input_files, report, current_user)

    try:
        job, notification = DeferredJobs.start(
            DeferredJobSpec(
                job_type=DeferredJobType.REPORT_AI,
                actor=current_user._get_current_object(),
                idempotency_key=request.form.get("operation-id"),
                inputs={"report": report},
                notification_body="Creating AI report...",
                notification_target=report,
                client={
                    "source_widget": "CreateToolReport",
                    "destination": "tools:ToolReportList",
                },
            )
        )
    except Exception as e:
        report.properties.process.fail(
            "AI report could not be started. Please try again."
        )
        Entities.save(report, current_user)
        exceptions.capture(
            e,
            context={
                "operation": "ai_report_queue_start",
                "report_key": report.urlsafe_key,
                "report": report.db,
            },
        )
        return responses.new_tool_report(report)

    # Starting the adapter may replace its report instance while recording the
    # operation. Render that saved state for an already-open homepage list too.
    report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct()) or report
    return responses.deferred_tool_report(report, notification, job=job)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_refreshes_stage_labels
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_tools_create_form_has_expected_controls
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_text_only_organize_plans_updates
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_tool_starts_pending_report
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_organize_rejects_zero_byte_folder_placeholder
# @matrix ai-report : remote-update async create http-boundary text-only upload validation persistence
# @matrix ai-report : list stage-labels
@tools.route("/ai", methods=["POST"])
@ai_access(AI.ASK)
def create_ai_report():
    if request.form.get("role") == "explain":
        return _explain_ai_prompt()

    try:
        input_files = _uploaded_report_files()
        upload_manifest = _report_upload_manifest()
    except (exceptions.ValidationError, FileConsumerLimitError) as error:
        return responses.error(str(error))
    instructions = (request.form.get("instructions") or "").strip()
    if not input_files and not upload_manifest and not instructions:
        return responses.error("Add files or instructions before creating a report.")
    filenames = [file.filename for file in input_files] + [record["filename"] for record in upload_manifest]
    default_name = _report_name(instructions) if instructions else (
        filenames[0] if len(filenames) == 1 else f"{len(filenames)} files"
    )
    return _start_tool_report(instructions, default_name=default_name, input_files=input_files, upload_manifest=upload_manifest)


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::report
# @covered-by lagniappe/web/routes/tools/main.py::run_report
# @covered-by lagniappe/web/routes/tools/main.py::delete_report
# @reason report lookup and owner guard are exercised through report routes
def _get_report(key, *, require_available=True):
    if getattr(current_user, "is_public", False):
        abort(403)
    report = Entities.fetch_one(
        key,
        request=Fetch.direct(),
    )
    if not isinstance(report, Entities.REPORT):
        return None
    if report.properties.parent.key != current_user.key:
        abort(403)
    if require_available and not report.available:
        abort(410, description="this plan is no longer available")
    return report


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::skip_report_action
# @covered-by lagniappe/web/routes/tools/main.py::delete_report
# @reason browser conflict responses are exercised by both guarded routes
def _external_plan_mutation_error(outcome):
    if outcome == agent_api_store.PLAN_OPERATION_MISSING:
        return responses.not_found("Report not found")
    message = (
        "This plan is being updated. Refresh it before trying again."
        if outcome == agent_api_store.PLAN_OPERATION_BUSY
        else "This plan changed. Refresh it before trying again."
    )
    response = responses.error(message)
    response.status_code = 409
    return response


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_runs_ready_report
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_action_dependencies
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_ask_report_detail_shows_answer_without_duplicate_proposal
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_report_detail_shows_revision_and_manual_execution
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_shows_review_only_proposal_without_execute
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_organize_report_detail_refreshes_when_submitted_revision_completes
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_schema_section_and_dependent_submission_updates
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_revision_requires_saved_response_and_allows_corrections
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_answers_from_attached_corpus_receipt
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_uses_structured_filter_for_form_submission_query
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_saved_report_controls_do_not_require_provider_access
# @matrix ai-report : detail live-submit needs-review no-execute organize revision schema-update skip-action
# @matrix ai-report : structured-filter workspace-tools
# @pair ai-access:provider-boundary
@tools.route("/reports/<key>", methods=["GET"])
@logged_in
def report(key):
    report = _get_report(key, require_available=False)
    if not report:
        return responses.not_found("Report not found")
    return responses.tool_report(report)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_runs_ready_report
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_failed_report_detail_offers_retry_and_preserves_completed_work
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_saved_report_controls_do_not_require_provider_access
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_api_report_run_start_error_does_not_save_stale_report
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_stale_schema_plan_keeps_review_and_explains_recovery
# @matrix ai-report : detail deterministic-run entitlement-independent idempotent recovery repeat-run retry
# @matrix ai-report : browser-review stale-proposal
# @matrix agent-api ai-report : browser-review error-isolation report-execution
# @matrix ai-report : failed-prefix failure reload
@tools.route("/reports/<key>/run", methods=["POST"])
@logged_in
def run_report(key):
    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
    if report.db.get("superseded_by"):
        return responses.error("This execution was superseded by an approved correction.")
    result = report.result if isinstance(report.result, dict) else {}
    retryable = (
        report.status == "failed"
        and result.get("ledger_version") == ai.REPORT_LEDGER_VERSION
        and result.get("status") == "failed"
    )
    if report.status == "complete" and result.get("status") == "complete":
        if not request.headers.get("X-Lagniappe-Request"):
            return redirect(url_for("tools.report", key=report.urlsafe_key))
        return responses.tool_report(report)

    operation_id = (request.form.get("operation-id") or "").strip()
    active_job = report.deferred_job or {}
    if (
        report.status == "running"
        and operation_id
        and active_job.get("idempotency_key") == operation_id
    ):
        job = Entities.fetch_one(active_job.get("key"), request=Fetch.direct())
        if isinstance(job, Entities.DEFERRED_JOB):
            if not request.headers.get("X-Lagniappe-Request"):
                return redirect(url_for("tools.report", key=report.urlsafe_key))
            return responses.deferred_tool_report(
                report,
                job.notification,
                job=job,
            )

    if report.status != "ready" and not retryable:
        return responses.error("Only ready or recoverable failed reports can be run.")

    from lagniappe.core.tools.ai.reporting.schema_updates import prepare_schema_updates
    from lagniappe.core.tools import form_changes, form_schema_updates

    try:
        if not retryable:
            prepare_schema_updates(report.proposal, current_user, verify=True)
        else:
            for record in result.get("actions", []):
                if record.get("migration_id"):
                    form = Entities.fetch_one(record.get("migration_form"), request=Fetch.direct())
                    if form and form.db.get(form_changes.PENDING):
                        form_changes.recover_change(form, current_user, "retry")
    except exceptions.ValidationError as error:
        if not retryable and str(error).startswith(form_schema_updates.STALE_MESSAGE):
            recovery = (
                "Ask the assistant that created it to refresh this same plan, "
                "then review the updated conversions."
                if report.origin == "api"
                else "Use Revise Plan to refresh it, then review the updated conversions."
            )
            return responses.error(
                "This plan needs another review because the form or saved answers changed. "
                "Execution hasn't started. " + recovery
            )
        return responses.error(str(error))

    try:
        from lagniappe.core.tools.ai.reporting.corrections import approve_correction
        approve_correction(report, current_user)
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    try:
        job, notification = DeferredJobs.start(
            DeferredJobSpec(
                job_type=DeferredJobType.REPORT_EXECUTION,
                actor=current_user._get_current_object(),
                idempotency_key=operation_id or None,
                inputs={"report": report},
                notification_body="Saving report changes...",
                notification_target=report,
                client={
                    "key": report.urlsafe_key,
                    "source_widget": "CreateToolReport",
                    "destination": "tools:ToolReportList",
                },
            )
        )
    except Exception as error:
        message = "Report execution could not be started. Please try again."
        current = _get_report(key) or report
        if current.origin != "api":
            if current.status == "running":
                current.status = "ready"
                current.pending = False
            current.error = message
            Entities.save(current, current_user)
        exceptions.capture(
            error,
            context={
                "operation": "report_execution_queue_start",
                "report_key": current.urlsafe_key,
                "report": current.db,
            },
        )
        return responses.error(message)

    if not request.headers.get("X-Lagniappe-Request"):
        return redirect(url_for("tools.report", key=report.urlsafe_key))
    return responses.deferred_tool_report(report, notification, job=job)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_organize_report_detail_refreshes_when_submitted_revision_completes
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_revision_requires_saved_response_and_allows_corrections
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_api_report_revision_is_provider_blocked
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_corrective_plan_controls_require_create_access
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_browser_correction_requires_create_access
# @matrix ai-report : async completed-state feedback live-submit organize ready-state revision route-guard
# @pair agent-api:provider-free-revision
# @pair ai-access:provider-boundary
@tools.route("/reports/<key>/revise", methods=["POST"])
@ai_access(AI.ASK)
def revise_report(key):
    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
    correcting = bool(report.result)
    if correcting or report.db.get("correction"):
        require_ai_access(AI.CREATE)
    if report.origin == "api" and not correcting:
        return responses.error("Revise an unexecuted external plan through its originating assistant.")
    can_revise = bool(report.proposal) and not report.pending and (report.status in {"complete", "failed"} if correcting else report.status == "ready" or (report.output_kind == "answer" and report.status == "complete"))
    if not can_revise:
        return responses.error("Only reports with saved responses can be revised.")

    feedback = (request.form.get("feedback") or "").strip()
    if not feedback:
        return responses.error("Add feedback before revising the report.")

    if correcting:
        from lagniappe.core.tools.ai.reporting.corrections import link_correction, save_correction
        source = report
        report = Entities.REPORT.create({"user": current_user._get_current_object(), "name": "Correction: " + source.name, "instructions": feedback, "origin": "web"})
        try:
            link_correction(report, source, current_user)
            save_correction(report, source)
        except exceptions.ValidationError as error:
            return responses.error(str(error))
    else:
        report.properties.process.revise()
        Entities.save(report, current_user)

    try:
        job, notification = DeferredJobs.start(
            DeferredJobSpec(
                job_type=DeferredJobType.REPORT_AI,
                actor=current_user._get_current_object(),
                idempotency_key=request.form.get("operation-id"),
                inputs={"report": report},
                parameters={"mode": "generate" if correcting else "revise", "feedback": feedback},
                notification_body="Revising AI report...",
                notification_target=report,
                client={
                    "source_widget": "CreateToolReport",
                    "destination": "tools:ToolReportList",
                },
            )
        )
    except Exception as e:
        if correcting:
            report.properties.process.fail("AI report correction could not be started. Please try again.")
        else:
            report.properties.process.revision_failed(
                "AI report revision could not be started. Please try again."
            )
        Entities.save(report, current_user)
        exceptions.capture(
            e,
            context={
                "operation": "ai_report_revision_queue_start",
                "report_key": report.urlsafe_key,
                "report": report.db,
            },
        )
        return responses.tool_report(report)

    return responses.deferred_tool_report(report, notification, job=job)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_action_dependencies
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_saved_report_controls_do_not_require_provider_access
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_api_report_browser_mutations_reject_fenced_state_without_side_effects
# @matrix ai-report : dependencies entitlement-independent skip-action
# @matrix agent-api ai-report : browser-review cas skip-action
@tools.route("/reports/<key>/actions/<int:action_index>/skip", methods=["POST"])
@logged_in
def skip_report_action(key, action_index):
    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
    if report.status != "ready":
        return responses.error("Only ready reports can be changed.")
    if report.origin == "api" and report.deferred_job:
        return _external_plan_mutation_error(agent_api_store.PLAN_OPERATION_BUSY)

    external_snapshot = (
        external_operations.report_snapshot(report)
        if report.origin == "api"
        else None
    )
    proposal = report.proposal
    payload = request.get_json(silent=True) or {}
    action_indexes = payload.get("action_indexes") or []
    include_dependencies = payload.get("include_dependencies") is not False
    if action_indexes:
        result = ai.toggle_proposal_action_indexes(
            proposal,
            action_index - 1,
            [int(index) - 1 for index in action_indexes],
            include_dependencies=include_dependencies,
        )
    else:
        result = ai.toggle_proposal_action_skip(proposal, action_index - 1)
    report.proposal = proposal
    if external_snapshot is not None:
        outcome = external_operations.save_plan_if_idle(
            report,
            external_snapshot,
        )
        if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
            return _external_plan_mutation_error(outcome)
    else:
        Entities.save(report, current_user)
    return responses.json_response(result)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_saved_report_controls_do_not_require_provider_access
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_api_report_browser_mutations_reject_fenced_state_without_side_effects
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_api_report_delete_rejects_active_execution_without_side_effects
# @matrix ai-report : delete delete-modal entitlement-independent file-cleanup
# @matrix agent-api ai-report : browser-review cas delete report-execution
@tools.route("/reports/<key>", methods=["DELETE"])
@logged_in
def delete_report(key):
    report = _get_report(key, require_available=False)
    if not report:
        return responses.not_found("Report not found")
    outcome = report_history.delete_report_record(report)
    if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
        return _external_plan_mutation_error(outcome)
    Entities.touch(current_user)
    return responses.ok()


# @testable true
# @tests tests_e2e/002_home/test_002n_home_report_filters.py::test_delete_executed_reports_confirms_snapshot_and_preserves_workspace
# @tests tests_e2e/002_home/test_002n_home_report_filters.py::test_bulk_report_delete_rechecks_ownership_and_validates_input
# @matrix ai-report : bulk-delete ownership validation
@tools.route("/reports/executed", methods=["DELETE"])
@logged_in
def delete_executed_reports():
    if getattr(current_user, "is_public", False):
        abort(403)
    data = request.get_json(silent=True)
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, list) or any(
        not isinstance(key, str) or not key.strip() for key in keys
    ):
        return responses.error("Provide the report keys to delete.")
    return responses.json_response(
        report_history.delete_executed_reports(current_user, keys)
    )
