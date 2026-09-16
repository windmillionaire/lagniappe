"""Deferred-job adapters for the email domain."""

import hashlib

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    DeferredJobSpec,
    DeferredJobPhase,
    DeferredJobStatus,
    DeferredJobType,
    Fetch,
    FetchReason,
    FileConsumer,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import utility as database_utility

from .base import DeferredJobAdapter


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_ingest_adapter_starts_existing_report_job_idempotently
# @tests tests_unit/test_028_ai_email.py::test_email_ingest_failure_surfaces_bounded_diagnostic
# @tests tests_unit/test_023c_deferred_job_runner.py::test_email_ingest_notification_is_created_only_for_failure
# @matrix ai-email deferred-jobs : acceptance diagnostics failure idempotency privacy report-handoff terminal-delivery
# @matrix feedback : diagnostics failure privacy terminal-delivery
# @pair deferred-jobs:failure-only-notification
class EmailIngestAdapter(DeferredJobAdapter):
    """Finalize received attachments, then start the normal report adapter."""

    job_type = DeferredJobType.EMAIL_INGEST
    queued_message = "Preparing email submission..."
    success_message = "Email submission accepted."
    failure_prefix = "Email submission failed."
    notification_policy = "failure"

    def authorize(self, context):
        super().authorize(context)
        report = context.input("report")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Email report user is invalid.")
        if not isinstance(report, Entities.REPORT) or report.origin != "email":
            raise exceptions.ValidationError("Email report is invalid.")
        if not report.available or not context.actor.access(AI.ASK):
            raise exceptions.ValidationError("This user does not have the required AI access or the plan is unavailable.")
        if not report.allowed(Action.EDIT, user=context.actor):
            raise exceptions.ValidationError(
                "You do not have permission to update this report."
            )

    def checkpoint_ready(self, context):
        return (context.checkpoint or {}).get("stage") == "acceptance_sent"

    def prepare(self, context):
        from lagniappe import CONFIG
        from lagniappe.core.definitions import enforce_file_consumer
        from lagniappe.core.tools.email.ai import (
            AIEmailRejection,
            ResendAIEmailClient,
            send_report_feedback,
        )
        from ..service import DeferredJobs

        report = context.input("report")
        actor = context.actor
        parameters = context.parameters
        parameters["_diagnostic_code"] = "email_ingest_failed"
        attachments = parameters.get("attachments") or []
        if not isinstance(attachments, list):
            raise exceptions.ValidationError("Email attachment manifest is invalid.")
        config = CONFIG.AI_EMAIL_CONFIG
        if not config:
            raise exceptions.ValidationError("AI email configuration is unavailable.")
        client = ResendAIEmailClient(
            config["resend"]["inboundApiKey"],
            config["resend"]["sendingApiKey"],
        )
        limits = config["limits"]
        input_files = list(report.input_files or [])
        attached = {file.key: file for file in input_files}
        total_bytes = 0

        for index, attachment in enumerate(attachments):
            context.ensure_active()
            if not isinstance(attachment, dict) or not attachment.get("id"):
                raise exceptions.ValidationError(
                    "Email attachment manifest is invalid."
                )
            identity = hashlib.sha256(
                f"{parameters.get('event_digest')}:{attachment['id']}".encode("utf-8")
            ).hexdigest()
            file_key = database_utility.create_named_key("file", f"email-{identity}")
            file = attached.get(file_key) or Entities.fetch_one(
                file_key,
                request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
            )
            if not isinstance(file, Entities.FILE):
                parameters["_diagnostic_code"] = "attachment_download_failed"
                try:
                    upload, actual_size = client.download_received_attachment(
                        parameters.get("provider_message_id"),
                        attachment,
                        max_file_bytes=limits["maxFileBytes"],
                        max_total_bytes=limits["maxTotalFileBytes"],
                        total_bytes=total_bytes,
                    )
                except AIEmailRejection as error:
                    raise exceptions.ValidationError(str(error)) from error
                try:
                    parameters["_diagnostic_code"] = "attachment_prepare_failed"
                    enforce_file_consumer(
                        upload,
                        FileConsumer.AI_EMAIL_ATTACHMENT,
                        filename=attachment.get("filename"),
                        size=actual_size,
                    )
                    file = Entities.FILE.create(
                        upload=upload,
                        data={
                            "filename": attachment.get("filename"),
                            "mimetype": attachment.get("content_type"),
                        },
                        key=file_key,
                        report_user=actor,
                    )
                finally:
                    upload.close()
                total_bytes += actual_size
            else:
                total_bytes += int(
                    getattr(file, "size", 0) or attachment.get("size") or 0
                )
            if file.key not in attached:
                input_files.append(file)
                attached[file.key] = file
                report.input_files = input_files
                report.summary = (
                    f"Preparing files ({index + 1} of {len(attachments)})..."
                )
                context.ensure_active()
                Entities.save(file, report, actor)

        report.input_files = input_files
        report.summary = None
        Entities.save(report, actor)
        parameters["_diagnostic_code"] = "report_start_failed"
        child, _notification = DeferredJobs.start(
            DeferredJobSpec(
                job_type=DeferredJobType.REPORT_AI,
                actor=actor,
                inputs={"report": report},
                notification_body="Creating AI report...",
                notification_target=report,
                client={
                    "source_widget": "CreateToolReport",
                    "destination": "tools:ToolReportList",
                },
                idempotency_key=f"ai-email/report/{parameters.get('event_digest')}",
            )
        )
        context.checkpoint_stage(
            "report_job_started",
            {"report_job": child.urlsafe_key},
            phase=DeferredJobPhase.PREPARING_INPUTS.value,
        )
        parameters["_diagnostic_code"] = "feedback_delivery_failed"
        send_report_feedback(report, "acceptance", client=client)
        context.checkpoint_stage(
            "acceptance_sent",
            {"report_job": child.urlsafe_key},
            phase=DeferredJobPhase.PREPARED.value,
        )
        return context.checkpoint

    def apply(self, context):
        return {
            "report_key": context.input("report").urlsafe_key,
            "report_job": context.checkpoint.get("report_job"),
        }

    def failure(self, context, error):
        from lagniappe.core.tools.email.ai import (
            AIEmailProviderError,
            AIEmailRejection,
        )

        report = context.input("report")
        if not isinstance(report, Entities.REPORT):
            return
        current = Entities.fetch_one(report, request=Fetch.direct()) or report
        if (
            current.deferred_job
            or (context.checkpoint or {}).get("stage")
            in {"report_job_started", "acceptance_sent"}
            or current.status not in {"pending", "running"}
        ):
            return
        diagnostic_codes = {
            "email_ingest_failed",
            "email_route_failed",
            "attachment_download_failed",
            "attachment_prepare_failed",
            "report_start_failed",
            "feedback_delivery_failed",
        }
        code = str(context.parameters.get("_diagnostic_code") or "")
        if code not in diagnostic_codes:
            code = "email_ingest_failed"
        message = f"The email submission could not be prepared. Diagnostic: {code}."
        if isinstance(error, AIEmailRejection):
            message = f"{message} {error.public_message}"
        elif isinstance(error, AIEmailProviderError):
            message = f"{message} {str(error)[:300]}"
        context.parameters["_diagnostic_message"] = message
        current.properties.process.fail(message)
        Entities.save(current, context.actor)

    def cleanup(self, context, *, terminal):
        if not terminal:
            return
        context.parameters.pop("provider_message_id", None)
        context.parameters.pop("attachments", None)
        context.parameters.pop("event_digest", None)
        context.parameters.pop("_diagnostic_code", None)

    def external_delivery_required(self, context):
        return bool(
            context.job.status == DeferredJobStatus.FAILED.value
            and (context.checkpoint or {}).get("stage")
            not in {"report_job_started", "acceptance_sent"}
        )

    def notification_target(self, context):
        report = context.input("report")
        return report if isinstance(report, Entities.REPORT) else None

    def external_delivery(self, context, *, succeeded, error=None):
        from lagniappe.core.tools.email.ai import send_report_feedback

        return send_report_feedback(
            context.input("report"),
            "failure",
            message=(
                context.parameters.get("_diagnostic_message")
                or "The email submission could not be prepared. Open the report for details."
            ),
        )
