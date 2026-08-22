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
    FileConsumer,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, database

from .base import DeferredJobAdapter


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_ingest_adapter_starts_existing_report_job_idempotently
# @tests tests_unit/test_028_ai_email.py::test_email_ingest_failure_surfaces_bounded_diagnostic
# @tests tests_unit/test_023c_deferred_job_runner.py::test_email_ingest_notification_is_created_only_for_failure
# @pairs ai-email:report-handoff ai-email:idempotency ai-email:acceptance
# @pairs deferred-jobs:report-handoff deferred-jobs:idempotency deferred-jobs:acceptance
# @pairs ai-email:failure ai-email:diagnostics ai-email:privacy ai-email:terminal-delivery
# @pairs deferred-jobs:failure deferred-jobs:diagnostics deferred-jobs:privacy deferred-jobs:terminal-delivery
# @pairs feedback:failure feedback:diagnostics feedback:privacy feedback:terminal-delivery
class EmailIngestAdapter(DeferredJobAdapter):
    """Finalize received attachments, then start the normal report adapter."""

    job_type = DeferredJobType.EMAIL_INGEST
    queued_message = "Preparing email submission..."
    success_message = "Email submission accepted."
    failure_prefix = "Email submission failed."
    notification_policy = "failure"

    def authorization(self, spec):
        authorization = super().authorization(spec)
        report = spec.inputs.get("report")
        authorization["tool"] = getattr(report, "tool", None)
        return authorization

    def authorize(self, context):
        super().authorize(context)
        report = context.input("report")
        if not isinstance(context.actor, Entities.USER):
            raise exceptions.ValidationError("Email report user is invalid.")
        if not isinstance(report, Entities.REPORT) or report.origin != "email":
            raise exceptions.ValidationError("Email report is invalid.")
        required = AI.ASK if report.tool == "ask" else AI.CREATE
        if report.tool not in {"ask", "create", "organize"} or not context.actor.access(
            required
        ):
            raise exceptions.ValidationError(
                "This user does not have the required AI access."
            )
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
        self._route_shared_address(report, actor, parameters, attachments)
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
            file_key = database.create_named_key("file", f"email-{identity}")
            file = attached.get(file_key) or Entities.fetch_one(
                file_key,
                request=Fetch.direct(),
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
        report_job_types = {
            "ask": DeferredJobType.REPORT_ASK,
            "create": DeferredJobType.REPORT_CREATE,
            "organize": DeferredJobType.REPORT_ORGANIZE,
        }
        parameters["_diagnostic_code"] = "report_start_failed"
        child, _notification = DeferredJobs.start(
            DeferredJobSpec(
                job_type=report_job_types[report.tool],
                actor=actor,
                inputs={"report": report},
                notification_body=f"Creating {report.tool} report...",
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

    # @testable true
    # @tests tests_unit/test_028_ai_email.py::test_email_ingest_adapter_routes_shared_address_once
    # @features ai-email deferred-jobs
    # @dimensions routing utility-model idempotency permissions
    def _route_shared_address(self, report, actor, parameters, attachments):
        manifest = dict(report.inbound_manifest or {})
        requested_tool = (
            parameters.get("requested_tool")
            or manifest.get("requested_tool")
            or manifest.get("tool")
            or report.tool
        )
        if requested_tool != "ai":
            return report.tool

        resolved_tool = manifest.get("resolved_tool")
        if resolved_tool not in {"ask", "create", "organize"}:
            eligible = ["ask"]
            if actor.access(AI.CREATE):
                eligible.extend(("create", "organize"))
            parameters["_diagnostic_code"] = "email_route_failed"
            route = ai.route_ai_email(
                manifest.get("subject"),
                manifest.get("body"),
                attachments,
                eligible,
            )
            resolved_tool = route["workflow"]
            manifest.update(
                {
                    "requested_tool": "ai",
                    "resolved_tool": resolved_tool,
                    "tool": resolved_tool,
                    "route_confidence": route["confidence"],
                    "route_reason": route["reason"],
                }
            )
            report.inbound_manifest = manifest

        required = AI.ASK if resolved_tool == "ask" else AI.CREATE
        if not actor.access(required):
            raise exceptions.ValidationError(
                "This user does not have the required AI access."
            )
        if report.tool != resolved_tool or report.inbound_manifest != manifest:
            report.tool = resolved_tool
            report.inbound_manifest = manifest
        Entities.save(report, actor)
        return resolved_tool

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
        context.parameters.pop("requested_tool", None)
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
