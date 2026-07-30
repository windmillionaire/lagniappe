"""Routes for AI tool reports."""

import json
from types import SimpleNamespace

from flask import abort, redirect, request, url_for
from flask_login import current_user

from lagniappe.core.definitions import (
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
from lagniappe.core.tools.deferred_jobs import DeferredJobs
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web.auth import abort_ai_restricted_action, logged_in

from . import tools

REPORT_JOB_TYPES = {
    "organize": DeferredJobType.REPORT_ORGANIZE,
    "ask": DeferredJobType.REPORT_ASK,
    "create": DeferredJobType.REPORT_CREATE,
}


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_organize_report
# @covered-by lagniappe/web/routes/tools/main.py::create_ask_report
# @covered-by lagniappe/web/routes/tools/main.py::create_create_report
# @reason user-facing tool labels are route presentation plumbing
def _tool_label(tool):
    return {"organize": "Organize", "ask": "Ask", "create": "Create"}.get(tool, "AI")


# @testable true
# @tests tests_e2e/002_home/test_002n_file_consumer_routes.py::test_organize_report_rejects_zero_byte_folder_placeholder
# @features ai-report
# @dimensions upload
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
        )
        files.append(file)
    return files


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_organize_report
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
# @covered-by lagniappe/web/routes/tools/main.py::create_organize_report
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
# @covered-by lagniappe/web/routes/tools/main.py::create_organize_report
# @reason explain modal shares the real organize prompt assembly
def _explain_organize_prompt():
    report = SimpleNamespace(
        instructions=request.form.get("instructions"),
        input_files=_preview_report_files(),
    )
    return responses.explain(ai.organize_prompt(report, current_user))


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_ask_report
# @reason explain modal shares the real ask prompt assembly
def _explain_ask_prompt():
    report = SimpleNamespace(instructions=request.form.get("instructions"))
    return responses.explain(ai.ask_prompt(report, current_user))


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_create_report
# @reason explain modal shares the real create prompt assembly
def _explain_create_prompt():
    report = SimpleNamespace(instructions=request.form.get("instructions"))
    return responses.explain(ai.create_prompt(report, current_user))


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_organize_report
# @reason route permission mirrors the final organize upload endpoint
@tools.route("/organize/direct-upload", methods=["POST"])
@logged_in
def create_organize_report_direct():
    abort_ai_restricted_action()

    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_tool_starts_pending_report
# @features ai-report
# @dimensions create title-truncation
def _create_report_name(instructions):
    text = " ".join((instructions or "").split())
    if not text:
        return "Create:"
    suffix = "..." if len(text) > 80 else ""
    return f"Create: {text[:80]}{suffix}"


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_organize_report
# @covered-by lagniappe/web/routes/tools/main.py::create_ask_report
# @covered-by lagniappe/web/routes/tools/main.py::create_create_report
# @reason shared report persistence and dispatch are exercised through tool routes
def _start_tool_report(
    tool,
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
            "tool": tool,
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
                job_type=REPORT_JOB_TYPES[tool],
                actor=current_user._get_current_object(),
                idempotency_key=request.form.get("operation-id"),
                inputs={"report": report},
                notification_body=f"Creating {_tool_label(tool).lower()} report...",
                notification_target=report,
                client={
                    "source_widget": "CreateToolReport",
                    "destination": "tools:ToolReportList",
                },
            )
        )
    except Exception as e:
        tool_label = _tool_label(tool)
        report.properties.process.fail(
            f"{tool_label} report could not be started. Please try again."
        )
        Entities.save(report, current_user)
        exceptions.capture(
            e,
            context={
                "operation": f"{tool}_report_queue_start",
                "report_key": report.urlsafe_key,
                "report": report.db,
            },
        )
        return responses.new_tool_report(report)

    return responses.deferred_tool_report(report, notification, job=job)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_refreshes_stage_labels
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_tools_create_form_has_expected_controls
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_text_only_organize_uses_ask
# @tests tests_e2e/002_home/test_002n_file_consumer_routes.py::test_organize_report_accepts_oversized_input
# @features ai-report
# @dimensions create upload async explain-button text-only ask-fallback
@tools.route("/organize", methods=["POST"])
@logged_in
def create_organize_report():
    abort_ai_restricted_action()

    if request.form.get("role") == "explain":
        return _explain_organize_prompt()

    try:
        input_files = _uploaded_report_files()
        upload_manifest = _report_upload_manifest()
    except (exceptions.ValidationError, FileConsumerLimitError) as error:
        return responses.error(str(error))
    instructions = request.form.get("instructions")
    if not input_files and not upload_manifest and not instructions:
        return responses.error("Add files or instructions before creating a report.")
    if not input_files and not upload_manifest:
        return _start_tool_report(
            "ask",
            instructions,
            default_name=ai.ask_report_name(instructions),
        )

    uploaded_filenames = [file.filename for file in input_files] + [
        record["filename"] for record in upload_manifest
    ]
    default_name = (
        f"Organize: {uploaded_filenames[0]}"
        if len(uploaded_filenames) == 1
        else f"Organize: {len(uploaded_filenames)} files"
    )
    return _start_tool_report(
        "organize",
        instructions,
        default_name=default_name,
        input_files=input_files,
        upload_manifest=upload_manifest,
    )


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_tools_create_form_has_expected_controls
# @features ai-report
# @dimensions ask explain-button tool-switcher
@tools.route("/ask", methods=["POST"])
@logged_in
def create_ask_report():
    abort_ai_restricted_action()

    if request.form.get("role") == "explain":
        return _explain_ask_prompt()

    instructions = request.form.get("instructions")
    if not instructions:
        return responses.error("Ask a question before creating a report.")
    return _start_tool_report(
        "ask",
        instructions,
        default_name=ai.ask_report_name(instructions),
    )


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_tools_create_form_has_expected_controls
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_tool_starts_pending_report
# @features ai-report
# @dimensions create explain-button tool-switcher async persistence
@tools.route("/create", methods=["POST"])
@logged_in
def create_create_report():
    abort_ai_restricted_action()

    if request.form.get("role") == "explain":
        return _explain_create_prompt()

    instructions = request.form.get("instructions")
    if not instructions:
        return responses.error("Describe what to create before creating a report.")
    return _start_tool_report(
        "create",
        instructions,
        default_name=_create_report_name(instructions),
    )


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::report
# @covered-by lagniappe/web/routes/tools/main.py::run_report
# @covered-by lagniappe/web/routes/tools/main.py::delete_report
# @reason report lookup and owner guard are exercised through report routes
def _get_report(key):
    report = Entities.fetch_one(
        key,
        request=Fetch.direct(),
    )
    if not isinstance(report, Entities.REPORT):
        return None
    if report.properties.parent.key != current_user.key:
        abort(403)
    return report


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_runs_ready_report
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_action_dependencies
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_ask_report_detail_shows_answer_without_duplicate_proposal
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_report_detail_shows_revision_and_manual_execution
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_shows_review_only_proposal_without_execute
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_organize_report_detail_refreshes_when_submitted_revision_completes
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_schema_section_and_runs_submission_updates
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_revision_is_only_available_before_completion
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_answers_from_attached_corpus_receipt
# @tests tests_e2e/002_home/test_002m_home_ask_ai.py::test_ask_uses_structured_filter_for_form_submission_query
# @features ai-report
# @dimensions detail skip-action ask answer-html links no-actions create revision execute report-view needs-review no-execute deferred-refresh pending
@tools.route("/reports/<key>", methods=["GET"])
@logged_in
def report(key):
    abort_ai_restricted_action()

    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
    return responses.tool_report(report)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_runs_ready_report
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_failed_report_detail_offers_retry_and_partial_undo
# @features ai-report
# @dimensions deterministic-run recovery retry detail repeat-run idempotent
@tools.route("/reports/<key>/run", methods=["POST"])
@logged_in
def run_report(key):
    abort_ai_restricted_action()

    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
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
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_failed_report_detail_offers_retry_and_partial_undo
# @features ai-report
# @dimensions deterministic-undo failed-prefix recovery undo
@tools.route("/reports/<key>/undo", methods=["POST"])
@logged_in
def undo_report(key):
    abort_ai_restricted_action()

    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
    result = report.result if isinstance(report.result, dict) else {}
    has_completed_actions = any(
        action.get("status") == "complete"
        for action in result.get("actions") or []
    )
    if (
        report.status not in {"complete", "failed", "undo_failed"}
        or not has_completed_actions
    ):
        return responses.error(
            "Only complete or partially completed reports can be undone."
        )

    try:
        ai.undo_report(report, current_user)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    Entities.touch(current_user)
    if not request.headers.get("X-Lagniappe-Request"):
        return redirect(url_for("tools.report", key=report.urlsafe_key))
    return responses.tool_report(report)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_organize_report_detail_refreshes_when_submitted_revision_completes
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_revision_is_only_available_before_completion
# @features ai-report
# @dimensions revision feedback async completed-state
@tools.route("/reports/<key>/revise", methods=["POST"])
@logged_in
def revise_report(key):
    abort_ai_restricted_action()

    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
    if report.tool not in {"organize", "ask", "create"}:
        return responses.error("This report cannot be revised.")
    can_revise = bool(report.proposal) and report.status == "ready"
    if not can_revise:
        return responses.error("Only reports with saved responses can be revised.")

    feedback = (request.form.get("feedback") or "").strip()
    if not feedback:
        return responses.error("Add feedback before revising the report.")

    report.properties.process.revise()
    Entities.save(report, current_user)

    tool_label = _tool_label(report.tool)
    try:
        job, notification = DeferredJobs.start(
            DeferredJobSpec(
                job_type=REPORT_JOB_TYPES[report.tool],
                actor=current_user._get_current_object(),
                idempotency_key=request.form.get("operation-id"),
                inputs={"report": report},
                parameters={"mode": "revise", "feedback": feedback},
                notification_body=f"Revising {tool_label.lower()} report...",
                notification_target=report,
                client={
                    "source_widget": "CreateToolReport",
                    "destination": "tools:ToolReportList",
                },
            )
        )
    except Exception as e:
        report.properties.process.revision_failed(
            f"{tool_label} report revision could not be started. Please try again."
        )
        Entities.save(report, current_user)
        exceptions.capture(
            e,
            context={
                "operation": f"{report.tool}_report_revision_queue_start",
                "report_key": report.urlsafe_key,
                "report": report.db,
            },
        )
        return responses.tool_report(report)

    return responses.deferred_tool_report(report, notification, job=job)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_action_dependencies
# @features ai-report
# @dimensions skip-action dependencies
@tools.route("/reports/<key>/actions/<int:action_index>/skip", methods=["POST"])
@logged_in
def skip_report_action(key, action_index):
    abort_ai_restricted_action()

    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")
    if report.status != "ready":
        return responses.error("Only ready reports can be changed.")

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
    Entities.save(report, current_user)
    return responses.json_response(result)


# @testable true
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
# @features ai-report
# @dimensions delete-modal file-cleanup
@tools.route("/reports/<key>", methods=["DELETE"])
@logged_in
def delete_report(key):
    abort_ai_restricted_action()

    report = _get_report(key)
    if not report:
        return responses.not_found("Report not found")

    files_to_delete = [
        file for file in report.input_files if not file.has_references
    ]
    DeferredJobs.cancel(report.deferred_job)
    ai.cleanup_report_upload_manifest(report)
    Entities.delete(report, *files_to_delete)
    Entities.touch(current_user)
    return responses.ok()
