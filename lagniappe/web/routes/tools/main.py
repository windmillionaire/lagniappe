"""Routes for AI tool reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from flask import abort, redirect, request, url_for
from flask_login import current_user

from lagniappe import CONFIG
from lagniappe.core.definitions import (
    AI,
    Action,
    Resource,
    DeferredJobSpec,
    DeferredJobType,
    Fetch,
    FetchReason,
    FileConsumer,
    FileConsumerLimitError,
    INDIVIDUAL_FILES_ONLY_ERROR,
    enforce_file_consumer,
)
from lagniappe.core.entities import Entities
from lagniappe.core import exceptions
from lagniappe.core.tools.ai.reporting.proposals import selection as report_selection
from lagniappe.core.tools.ai.reporting import uploads as report_uploads
from lagniappe.core.tools.ai import external_operations, report_history
from lagniappe.core.tools.database import agent_api as agent_api_store
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.tools.forms import review as form_review
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web import deferred_autofill
from lagniappe.web.auth import authenticated_user, ai_access, logged_in, require_ai_access

from . import tools


@tools.route("/operations/<job_key>/cancel", methods=["POST"])
@logged_in
def cancel_generation(job_key: str) -> ResponseReturnValue:
    job = Entities.fetch_one(job_key, request=Fetch.direct())
    if not isinstance(job, Entities.DEFERRED_JOB) or job.job_type not in {"autofill", DeferredJobType.REPORT_AI.value}:
        abort(404)
    if job.job_type == "autofill":
        target = Entities.fetch_one(((job.inputs or {}).get("target") or {}).get("id"), request=Fetch.direct())
        if not isinstance(target, (Entities.PAGE, Entities.TASK)) or not target.allowed(Action.EDIT, user=current_user):
            abort(403)
        if (job.parameters or {}).get("mode") == "revise" and (job.actor is None or job.actor.key != current_user.key):
            abort(403)
        if request.form.get("operation-id") != job.idempotency_key:
            abort(409, description="This autofill control is stale. Refresh before trying again.")
        DeferredJobs.cancel(job)
        statuses = DeferredJobs.statuses([job_key], authenticated_user())
        was_cancelled = bool(statuses and statuses[0]["status"] in {"cancelled", "superseded"})
        return responses.json_response({"status": statuses[0] if statuses else None,
            "message": "Autofill cancelled. Saved answers and files were kept." if was_cancelled else "Autofill has already finished or applied its results."})
    if (job.actor is None or job.actor.key != current_user.key) and not current_user.has_permission(Resource.SITE, Action.EDIT):
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
    if job.actor is None or job.actor.key != current_user.key:
        return redirect(url_for("analytics.index"))
    return redirect(url_for("tools.report", key=report.urlsafe_key))


@tools.route("/autofill/<key>/revise", methods=["POST"])
@ai_access(AI.CREATE)
def refine_autofill(key: str) -> ResponseReturnValue:
    """Prompt-only, actor-private proposals; never save the modal's draft answers."""
    target = Entities.fetch_one(key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    if not isinstance(target, (Entities.PAGE, Entities.TASK)) or not target.allowed(Action.EDIT, user=current_user):
        abort(403)
    if getattr(target, "completed", False):
        abort(409, description="This task is complete.")
    if not form_review.stage_submission_guard(target, request.form):
        return deferred_autofill.conflict_response(target)
    locked = deferred_autofill.locked_response(target, {"role": "autofill-submit"})
    if locked:
        return locked
    try:
        import json
        submission = json.loads(request.form.get("submission", "{}"))
        if not isinstance(submission, dict) or len(request.form.get("submission", "")) > 300 * 1024:
            raise exceptions.ValidationError("The review draft is too large or invalid.")
        # Validate editable IDs/types and reference permissions before sealing.
        from lagniappe.core.tools.ai.autofill import validate_submission
        editable_ids = {field["id"] for field in target.submission_schema if field.get("type") not in {"signature", "status", "html"}}
        submission = {key: value for key, value in submission.items() if key in editable_ids}
        submission = validate_submission(submission, entity=target, user=authenticated_user(), schema=target.submission_schema)
        context: dict[str, object] = {
            "previous_suggestions": form_review.review_projection(target, authenticated_user()),
        }
        return deferred_autofill.start_deferred_autofill(
            target, authenticated_user(), request.form, mode="revise", submission=submission,
            review_context=context,
        )
    except (ValueError, exceptions.ValidationError, exceptions.AIException) as error:
        return responses.error(str(error))


@tools.route("/reports/<key>/retry-generation", methods=["POST"])
@ai_access(AI.ASK)
def retry_generation(key: str) -> ResponseReturnValue:
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
            actor=authenticated_user(),
            idempotency_key=request.form.get("operation-id"),
            inputs={"report": report},
            notification_body="Creating AI report...",
            notification_target=report,
            client={"source_widget": "CreateToolReport", "destination": "tools:ToolReportList"},
        ))
    except Exception:
        report.properties.process.fail("Generation could not be started. Retry to start again.")
        Entities.save(report, authenticated_user())
        raise
    return redirect(url_for("tools.report", key=report.urlsafe_key))

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
            report_user=authenticated_user(),
        )
        files.append(file)
    return files


def _report_upload_manifest():
    direct_uploads.direct_upload_files(
        "tool-files",
        consumer=FileConsumer.AI_REPORT,
    )
    records = direct_uploads.direct_upload_records(
        request.form,
        input_name="tool-files",
    )
    return report_uploads.prepare_report_upload_manifest(records)


@tools.route("/ai/direct-upload", methods=["POST"])
@ai_access(AI.ASK)
def create_ai_report_direct() -> ResponseReturnValue:
    return direct_uploads.direct_upload_response()


def _report_name(instructions):
    text = " ".join((instructions or "").split())
    if not text:
        return "Plan"
    suffix = "..." if len(text) > 80 else ""
    return f"{text[:80]}{suffix}"


def _start_tool_report(
    instructions,
    *,
    default_name,
    input_files=None,
    upload_manifest=None,
    auto_execute=False,
):
    input_files = list(input_files or [])
    report = Entities.REPORT.create(
        {
            "parent": authenticated_user(),
            "user": authenticated_user(),
            "name": request.form.get("name") or default_name,
            "instructions": instructions,
            "input_files": input_files,
            "upload_manifest": upload_manifest,
            "status": "pending",
            "pending": True,
        }
    )
    if auto_execute:
        report.db["auto_execute"] = True
    if (CONFIG.EXPERIMENTS_ENABLED and (input_files or upload_manifest)
            and request.headers.get("X-Lagniappe-Experiments-Report-Files") == "summaries"):
        report.db["summaries_first"] = True
    Entities.save(*input_files, report, authenticated_user())

    try:
        job, notification = DeferredJobs.start(
            DeferredJobSpec(
                job_type=DeferredJobType.REPORT_AI,
                actor=authenticated_user(),
                idempotency_key=request.form.get("operation-id"),
                inputs={"report": report},
                parameters={"auto_execute": True} if auto_execute else {},
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
        Entities.save(report, authenticated_user())
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
    current = Entities.fetch_one(report.key, request=Fetch.direct())
    if isinstance(current, Entities.REPORT):
        report = current
    return responses.deferred_tool_report(report, notification, job=job)


@tools.route("/ai", methods=["POST"])
@ai_access(AI.ASK)
def create_ai_report() -> ResponseReturnValue:
    if request.form.get("role") == "explain":
        return responses.error("Initial Prompt is no longer available.")

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
    from lagniappe.core.tools.ai.auto_execute import can_auto_execute_onsite_plan

    auto_execute = (
        request.form.get("auto_execute") == "true"
        and can_auto_execute_onsite_plan(authenticated_user())
    )
    return _start_tool_report(
        instructions,
        default_name=default_name,
        input_files=input_files,
        upload_manifest=upload_manifest,
        auto_execute=auto_execute,
    )


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


@tools.route("/reports/<key>", methods=["GET"])
@logged_in
def report(key: str) -> ResponseReturnValue:
    report = _get_report(key, require_available=False)
    if not report:
        return responses.not_found("Report not found")
    return responses.tool_report(report)


@tools.route("/reports/<key>/run", methods=["POST"])
@logged_in
def run_report(key: str) -> ResponseReturnValue:
    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
    from lagniappe.core.tools.ai.reporting.execution.request import request_execution
    try:
        job, notification = request_execution(
            report,
            authenticated_user(),
            operation_id=(request.form.get("operation-id") or "").strip() or None,
        )
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    except Exception as error:
        message = "Report execution could not be started. Please try again."
        current = _get_report(key) or report
        if current.origin != "api":
            if current.status == "running":
                current.status = "ready"
                current.pending = False
            current.error = message
            Entities.save(current, authenticated_user())
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
    if job is None:
        return responses.tool_report(report)
    return responses.deferred_tool_report(report, notification, job=job)


@tools.route("/reports/<key>/revise", methods=["POST"])
@ai_access(AI.ASK)
def revise_report(key: str) -> ResponseReturnValue:
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
        report = Entities.REPORT.create({"user": authenticated_user(), "name": "Correction: " + (source.name or "Report"), "instructions": feedback, "origin": "web"})
        try:
            link_correction(report, source, authenticated_user())
            save_correction(report, source)
        except exceptions.ValidationError as error:
            return responses.error(str(error))
    else:
        report.properties.process.revise()
        Entities.save(report, authenticated_user())

    try:
        job, notification = DeferredJobs.start(
            DeferredJobSpec(
                job_type=DeferredJobType.REPORT_AI,
                actor=authenticated_user(),
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
        Entities.save(report, authenticated_user())
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


@tools.route("/reports/<key>/actions/<int:action_index>/skip", methods=["POST"])
@logged_in
def skip_report_action(key: str, action_index: int) -> ResponseReturnValue:
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
        result = report_selection.toggle_proposal_action_indexes(
            proposal,
            action_index - 1,
            [int(index) - 1 for index in action_indexes],
            include_dependencies=include_dependencies,
        )
    else:
        result = report_selection.toggle_proposal_action_skip(proposal, action_index - 1)
    report.proposal = proposal
    if external_snapshot is not None:
        outcome = external_operations.save_plan_if_idle(
            report,
            external_snapshot,
        )
        if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
            return _external_plan_mutation_error(outcome)
    else:
        Entities.save(report, authenticated_user())
    return responses.json_response(result)


@tools.route("/reports/<key>", methods=["DELETE"])
@logged_in
def delete_report(key: str) -> ResponseReturnValue:
    report = _get_report(key, require_available=False)
    if not report:
        return responses.not_found("Report not found")
    outcome = report_history.delete_report_record(report)
    if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
        return _external_plan_mutation_error(outcome)
    Entities.touch(authenticated_user())
    return responses.ok()


@tools.route("/reports/executed", methods=["DELETE"])
@logged_in
def delete_executed_reports() -> ResponseReturnValue:
    if getattr(current_user, "is_public", False):
        abort(403)
    data = request.get_json(silent=True)
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, list) or any(
        not isinstance(key, str) or not key.strip() for key in keys
    ):
        return responses.error("Provide the report keys to delete.")
    return responses.json_response(
        report_history.delete_executed_reports(authenticated_user(), keys)
    )
