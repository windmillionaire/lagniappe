"""Signed Resend webhook boundary for AI email submissions."""

from flask import Response, request

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.tools.email.ai import (
    AIEmailWebhookError,
    parse_resend_event,
    process_resend_email,
    verify_svix_signature,
)

from . import webhooks


# @testable infrastructure
# @covered-by lagniappe/core/tools/email/ai.py::verify_svix_signature
# @covered-by lagniappe/core/tools/email/ai.py::process_resend_email
@webhooks.post("/resend/ai-email")
def resend_ai_email():
    """Verify and hand one Resend event to the durable report workflow."""
    config = getattr(CONFIG, "AI_EMAIL_CONFIG", None)
    if not config or not config.get("enabled"):
        return Response(status=404)

    raw_body = request.get_data(cache=True)
    try:
        event_id = verify_svix_signature(
            raw_body,
            request.headers,
            config["resend"]["webhookSecret"],
        )
        event = parse_resend_event(raw_body)
    except AIEmailWebhookError:
        return Response(status=401)

    if event["type"] != "email.received":
        return Response(status=204)
    try:
        process_resend_email(
            event,
            event_id,
            config,
            CONFIG.SECRET_KEY,
        )
    except Exception as error:
        exceptions.capture(
            error,
            context={
                "ai_email": {
                    "operation": "submission_handoff",
                    "error_code": "message_unavailable",
                }
            },
            level="warning",
        )
        return Response(status=503)
    return Response(status=204)
