"""Unit contracts for production AI email ingestion and report handoff."""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from types import SimpleNamespace

import pytest

from config.ai_email import AI_EMAIL_LIMITS, normalize_ai_email_config
from lagniappe.core.definitions import Action
from lagniappe.core.tools.email import ai as ai_email
from lagniappe.core.tools import ai as ai_tools
from lagniappe.core.tools.email.ai import (
    AIEmailRejection,
    AIEmailWebhookError,
    InboundAttachment,
    REPLY_MARKER,
    ResendAIEmailClient,
    authentication_results_candidates,
    normalize_resend_message,
    parse_mailbox,
    parse_resend_event,
    verify_svix_signature,
)
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


def _config():
    return normalize_ai_email_config(
        {
            "version": 1,
            "provider": "resend",
            "enabled": True,
            "domain": "inbound.example.com",
            "aliases": {
                "ai": "ai",
                "ask": "ask",
                "create": "create",
                "organize": "organize",
            },
            "resend": {
                "domainId": "domain-1",
                "webhookId": "webhook-1",
                "webhookSecret": "whsec_dGVzdC1zZWNyZXQ=",
                "inboundApiKey": "re_full",
                "sendingApiKey": "re_send",
                "senderEmail": "noreply@example.com",
                "senderName": "Lagniappe",
            },
            "limits": dict(AI_EMAIL_LIMITS),
        }
    )


def _signed_headers(raw_body, *, event_id="event-1", timestamp=None):
    timestamp = (
        int(datetime.now(timezone.utc).timestamp())
        if timestamp is None
        else timestamp
    )
    signed = f"{event_id}.{timestamp}.".encode() + raw_body
    signature = base64.b64encode(
        hmac.new(b"test-secret", signed, hashlib.sha256).digest()
    ).decode()
    return {
        "svix-id": event_id,
        "svix-timestamp": str(timestamp),
        "svix-signature": f"v0,ignored v1,{signature}",
    }


# @matrix ai-email webhook : event-id headers raw-body rotation signature
def test_svix_signature_verification_accepts_raw_body_case_insensitive_headers_and_any_v1_signature():
    raw_body = b'{"type":"email.received","data":{"email_id":"one"}}'
    headers = {
        key.title(): value for key, value in _signed_headers(raw_body).items()
    }
    headers["Svix-Signature"] = (
        f"v1,{base64.b64encode(b'wrong').decode()} "
        f"{headers['Svix-Signature']} v2,ignored"
    )

    assert (
        verify_svix_signature(
            raw_body,
            headers,
            "whsec_dGVzdC1zZWNyZXQ=",
        )
        == "event-1"
    )


# @matrix ai-email webhook : invalid raw-body signature
def test_svix_signature_verification_rejects_changed_or_non_bytes_body():
    raw_body = b"{}"
    headers = _signed_headers(raw_body)
    with pytest.raises(AIEmailWebhookError) as changed:
        verify_svix_signature(b"{ }", headers, "whsec_dGVzdC1zZWNyZXQ=")
    assert str(changed.value) == ""

    for not_raw_bytes in ("{}", bytearray(b"{}")):
        with pytest.raises(
            AIEmailWebhookError,
            match=r"^Webhook body must be raw bytes\.$",
        ):
            verify_svix_signature(
                not_raw_bytes,
                headers,
                "whsec_dGVzdC1zZWNyZXQ=",
            )


# @matrix ai-email webhook : headers invalid secret signature
def test_svix_signature_verification_rejects_missing_or_malformed_authentication_inputs():
    raw_body = b"{}"
    signed_headers = _signed_headers(raw_body)
    invalid_inputs = []
    for missing_header in signed_headers:
        invalid_inputs.append(
            (
                {
                    key: value
                    for key, value in signed_headers.items()
                    if key != missing_header
                },
                "whsec_dGVzdC1zZWNyZXQ=",
            )
        )
    invalid_inputs.extend(
        (
            (
                {**signed_headers, "svix-signature": malformed},
                "whsec_dGVzdC1zZWNyZXQ=",
            )
            for malformed in ("malformed", "v1,not-base64!", "v1,too,many")
        )
    )
    invalid_inputs.append((signed_headers, "whsec_a"))

    for headers, secret in invalid_inputs:
        with pytest.raises(AIEmailWebhookError) as invalid:
            verify_svix_signature(raw_body, headers, secret)
        assert str(invalid.value) == ""


# @matrix ai-email webhook : future replay timestamp
def test_svix_signature_verification_rejects_replayed_or_future_events():
    raw_body = b"{}"
    now = int(datetime.now(timezone.utc).timestamp())

    for timestamp in (now - 301, now + 301):
        with pytest.raises(AIEmailWebhookError) as invalid:
            verify_svix_signature(
                raw_body,
                _signed_headers(raw_body, timestamp=timestamp),
                "whsec_dGVzdC1zZWNyZXQ=",
            )
        assert str(invalid.value) == ""


# @matrix ai-email webhook : event-shape json malformed webhook
def test_parse_resend_event_rejects_malformed_shapes():
    assert parse_resend_event(b'{"type":"email.received","data":{}}') == {
        "type": "email.received",
        "data": {},
    }
    for raw_body in (b"not-json", b"[]", b'{"type": 2, "data": {}}'):
        with pytest.raises(AIEmailWebhookError):
            parse_resend_event(raw_body)


class _HTTPResponse:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


# @matrix ai-email provider-adapter : attachments authorization idempotency outbound-email provider-adapter retrieval
def test_resend_runtime_client_retrieves_with_full_key_and_sends_with_scoped_key():
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/attachments"):
            return _HTTPResponse({"data": []})
        return _HTTPResponse({"id": "provider-object"})

    client = ResendAIEmailClient("re_full", "re_send", request=request)
    client.retrieve_received_email("email-1")
    client.list_received_attachments("email-1")
    client.retrieve_received_attachment("email-1", "attachment-1")
    client.send_email({"subject": "test"}, idempotency_key="feedback/one")

    assert calls[0][1].endswith("/emails/receiving/email-1")
    assert calls[1][1].endswith("/emails/receiving/email-1/attachments")
    assert calls[2][1].endswith("/emails/receiving/email-1/attachments/attachment-1")
    assert all(
        call[2]["headers"]["Authorization"] == "Bearer re_full" for call in calls[:3]
    )
    assert calls[3][1].endswith("/emails")
    assert calls[3][2]["headers"]["Authorization"] == "Bearer re_send"
    assert calls[3][2]["headers"]["Idempotency-Key"] == "feedback/one"


# @matrix ai-email attachments provider-adapter : bounded-stream provider-adapter signed-url size
def test_resend_attachment_download_is_bounded_and_does_not_return_signed_url():
    closed = []

    class Download:
        ok = True
        status_code = 200

        def iter_content(self, *, chunk_size):
            assert chunk_size > 0
            yield b"hello"
            yield b" world"

        def close(self):
            closed.append(True)

    for hostname in ("cdn.resend.app", "inbound-cdn.resend.com"):
        client = ResendAIEmailClient(
            "re_full",
            "re_send",
            request=lambda *_args, host=hostname, **_kwargs: _HTTPResponse(
                {"download_url": f"https://{host}/signed-secret"}
            ),
            download_request=lambda *_args, **_kwargs: Download(),
        )
        upload, size = client.download_received_attachment(
            "email-1",
            {
                "id": "attachment-1",
                "filename": "notes.txt",
                "content_type": "text/plain",
            },
            max_file_bytes=20,
            max_total_bytes=20,
        )
        try:
            assert size == 11
            assert upload.read() == b"hello world"
            assert "signed-secret" not in repr(upload)
        finally:
            upload.close()
    assert closed == [True, True]


# @matrix ai-email sender-auth : alignment authentication-results dmarc sender-auth telemetry
def test_authentication_results_candidates_require_aligned_dmarc_pass():
    assert authentication_results_candidates(
        {
            "Authentication-Results": (
                "mx.resend.test; dmarc=pass header.from=example.com; "
                "spf=pass smtp.mailfrom=sender@example.com"
            )
        },
        "example.com",
    ) == ("mx.resend.test",)
    assert (
        authentication_results_candidates(
            {
                "authentication-results": (
                    "mx.resend.test; dmarc=fail header.from=example.com; "
                    "spf=pass smtp.mailfrom=sender@example.com"
                )
            },
            "example.com",
        )
        == ()
    )


# @matrix ai-email sender-auth : comments folding multiple-results sender-auth telemetry
def test_authentication_results_candidates_handle_folding_comments_and_multiple_values():
    headers = {
        "Authentication-Results": [
            "forged.example; dmarc=fail header.from=example.com",
            (
                "mx.resend.test (provider result);\r\n\t"
                "dmarc=pass (good) header.from=example.com"
            ),
        ]
    }
    assert authentication_results_candidates(headers, "example.com") == (
        "mx.resend.test",
    )


# @matrix ai-email normalization : attachments exact-local html-fallback reply-marker routing sender
def test_inbound_message_normalization_routes_alias_and_strips_reply_marker():
    message, tool = normalize_resend_message(
        {
            "id": "email-1",
            "from": "Owner <Owner@EXAMPLE.COM>",
            "to": ["Ask@inbound.example.com"],
            "subject": "  Review\r\nthis  ",
            "text": f"Keep this\n\n{REPLY_MARKER}\nOld thread",
            "headers": {},
            "created_at": "2026-08-14T12:00:00Z",
        },
        [
            {
                "id": "attachment-1",
                "filename": "notes.txt",
                "content_type": "text/plain",
                "size": 12,
            }
        ],
        _config(),
    )
    assert tool == "ask"
    assert message.sender == "Owner@example.com"
    assert message.subject == "Review this"
    assert message.text_body == "Keep this"
    assert message.attachments[0].filename == "notes.txt"

    html_message, _tool = normalize_resend_message(
        {
            "id": "email-2",
            "from": "Owner@example.com",
            "to": ["ask@inbound.example.com"],
            "subject": "HTML",
            "text": "",
            "html": "<p>Hello <strong>there</strong></p><script>bad()</script>",
            "headers": {},
        },
        [],
        _config(),
    )
    assert "Hello" in html_message.text_body
    assert "bad()" not in html_message.text_body
    for malformed in (
        "one@example.com, two@example.com",
        "Friends: owner@example.com;",
    ):
        with pytest.raises(AIEmailRejection, match="Sender"):
            parse_mailbox(malformed)


# @matrix ai-email : attachments content-disposition content-id inline
def test_inbound_attachment_disposition_overrides_content_id():
    attachment = InboundAttachment(
        "attachment-1",
        "photo.jpg",
        "image/jpeg",
        77_546,
        content_disposition="attachment",
        content_id="provider-content-id",
    )
    assert not attachment.inline
    assert InboundAttachment(
        "attachment-2",
        "inline.jpg",
        "image/jpeg",
        100,
        content_disposition="inline",
        content_id="provider-content-id",
    ).inline
    assert InboundAttachment(
        "attachment-3",
        "legacy-inline.jpg",
        "image/jpeg",
        100,
        content_id="provider-content-id",
    ).inline


# @matrix ai-email : attachments image-only inline quoted-content routing signature
def test_inline_attachment_selection_keeps_user_content_and_filters_signature_art(
    monkeypatch,
):
    monkeypatch.setattr(
        "lagniappe.core.tools.cache.rate_limit.check_limit",
        lambda *_args: {"allowed": True, "retry_after": 0},
    )
    message, _tool = normalize_resend_message(
        {
            "id": "email-inline",
            "from": "Owner@example.com",
            "to": ["ai@inbound.example.com"],
            "subject": "",
            "text": "[image: 2020_UCV_school_portrait.jpg]",
            "html": (
                '<img src="cid:photo-content" '
                'alt="2020_UCV_school_portrait.jpg">'
                '<div class="gmail_signature">'
                '<img src="cid:signature-content" alt="logo.png">'
                "</div>"
                '<blockquote><img src="cid:quoted-content" '
                'alt="quoted.png"></blockquote>'
            ),
            "headers": {},
        },
        [
            {
                "id": "photo",
                "filename": "2020_UCV_school_portrait.jpg",
                "content_type": "image/jpeg",
                "content_disposition": "inline",
                "content_id": "photo-content",
                "size": 77_546,
            },
            {
                "id": "signature",
                "filename": "logo.png",
                "content_type": "image/png",
                "content_disposition": "inline",
                "content_id": "signature-content",
                "size": 2_048,
            },
            {
                "id": "quoted",
                "filename": "quoted.png",
                "content_type": "image/png",
                "content_disposition": "inline",
                "content_id": "quoted-content",
                "size": 3_048,
            },
        ],
        _config(),
    )

    user = SimpleNamespace(access=lambda _required: True, urlsafe_key="user-one")
    _instructions, attachments = ai_email._preflight_submission(
        message, "ai", user, _config()
    )

    assert [attachment.id for attachment in attachments] == ["photo"]
    assert (
        ai_tools.route_ai_email(
            message.subject,
            message.text_body,
            [attachment.job_record() for attachment in attachments],
            ("ask", "create", "organize"),
        )["workflow"]
        == "organize"
    )

    image_only, _tool = normalize_resend_message(
        {
            "id": "email-image-only",
            "from": "Owner@example.com",
            "to": ["ai@inbound.example.com"],
            "subject": "",
            "text": "",
            "html": "",
            "headers": {},
        },
        [
            {
                "id": "photo-only",
                "filename": "camera-photo.jpg",
                "content_type": "image/jpeg",
                "content_disposition": "inline",
                "content_id": "photo-only-content",
                "size": 77_546,
            }
        ],
        _config(),
    )
    _instructions, attachments = ai_email._preflight_submission(
        image_only, "ai", user, _config()
    )

    assert [attachment.id for attachment in attachments] == ["photo-only"]


# @matrix ai-email ai-report : inbound-manifest legacy-default origin privacy
def test_email_report_shape_preserves_safe_inbound_display_fields():
    user = TestEntities.get("USER", {"name": "Owner", "owner": False})
    report = TestEntities.get(
        "REPORT",
        {
            "parent": user,
            "user": user,
        },
    )
    report.origin = "email"
    report.inbound_manifest = {
        "subject": "Quarterly notes",
        "body": "Summarize this",
        "tool": "ask",
        "alias": "ask@inbound.example.com",
        "received_at": "2026-08-14T12:00:00Z",
        "attachments": [{"filename": "notes.txt", "size": 12}],
    }
    assert report.origin == "email"
    assert report.inbound_manifest["subject"] == "Quarterly notes"
    assert "headers" not in report.inbound_manifest
    assert "provider_message_id" not in report.inbound_manifest
    legacy = TestEntities.get(
        "REPORT", {"name": "Legacy", "parent": user, "user": user}
    )
    assert legacy.origin == "web"


# @matrix ai-email : attachments generation privacy routing structured-output utility-model validation
def test_ai_email_router_uses_utility_model_and_safe_metadata(monkeypatch):
    prompts = []

    def generate(prompt, *, validator=None):
        prompts.append(prompt)
        result = {
            "workflow": "organize",
            "confidence": 0.97,
            "reason": "The attached invoice should fill a task submission.",
        }
        return validator(result) if validator else result

    monkeypatch.setattr(ai_tools.ai_model, "generate_content", generate)
    route = ai_tools.route_ai_email(
        "Paid invoice",
        "Update the existing task with its confirmation number.",
        [
            {
                "id": "private-provider-id",
                "filename": "invoice.pdf",
                "content_type": "application/pdf",
                "size": 1200,
                "download_url": "https://provider.example/private",
            }
        ],
        ("ask", "create", "organize"),
    )

    assert route["workflow"] == "organize"
    prompt = prompts[0]
    assert prompt.prompt_type == "ai email router"
    assert prompt.model_tier == "utility"
    assert prompt.thinking_budget == 0
    assert prompt.search is False
    assert prompt.tools is None
    assert prompt.response_schema["properties"]["workflow"]["enum"] == [
        "ask",
        "organize",
    ]
    built = prompt.build()
    assert "invoice.pdf" in built
    assert "private-provider-id" not in built
    assert "download_url" not in built


# @matrix ai-email : attachment-contract routing validation
def test_ai_email_router_normalizes_attachment_create_to_organize():
    assert ai_tools.validate_ai_email_route(
        {
            "workflow": "create",
            "confidence": 0.8,
            "reason": "Create an invoice task from the attachment.",
        },
        attachments=[{"filename": "invoice.pdf"}],
        eligible_workflows=("ask", "create", "organize"),
    ) == {
        "workflow": "organize",
        "confidence": 0.8,
        "reason": "Attachment-backed creation uses Organize.",
    }


# @matrix ai-email : attachment-only deterministic inline routing
def test_ai_email_router_routes_attachment_only_message_to_organize(monkeypatch):
    monkeypatch.setattr(
        ai_tools.ai_model,
        "generate_content",
        lambda *_args, **_kwargs: pytest.fail(
            "Attachment-only routing should not require a model call"
        ),
    )

    result = ai_tools.route_ai_email(
        "",
        "[image: 2020_UCV_school_portrait.jpg]",
        [
            {
                "filename": "2020_UCV_school_portrait.jpg",
                "content_type": "image/jpeg",
                "size": 77_546,
            }
        ],
        ("ask", "create", "organize"),
    )

    assert result == {
        "workflow": "organize",
        "confidence": 1.0,
        "reason": "Attachment-only email uses Organize.",
    }


# @matrix ai-email files : temporary-view-ownership
def test_email_report_file_is_viewable_only_by_submitter_or_owner():
    submitter = TestEntities.get(
        "USER", {"name": "Submitter", "email": "submitter@example.com", "owner": False}
    )
    stranger = TestEntities.get(
        "USER", {"name": "Stranger", "email": "stranger@example.com", "owner": False}
    )
    file = TestEntities.get("FILE", {"filename": "private.txt"})
    file.report_user = submitter
    assert file.allowed(Action.VIEW, user=submitter)
    assert not file.allowed(Action.VIEW, user=stranger)


# @matrix ai-email : acceptance disabled-completion idempotency reply-to terminal-link
def test_report_feedback_links_to_report_and_remains_available_after_disable(
    monkeypatch,
):
    from lagniappe import CONFIG

    user = TestEntities.get("USER", {"name": "Owner", "owner": False})
    user.email = "Owner@example.com"
    report = TestEntities.get(
        "REPORT",
        {
            "hash": "email-report-one",
            "parent": user,
            "user": user,
            "tool": "ask",
        },
    )
    report.origin = "email"
    report.inbound_manifest = {
        "alias": "ai@inbound.example.com",
        "requested_tool": "ai",
        "resolved_tool": "ask",
    }
    config = _config()
    config["enabled"] = False
    monkeypatch.setattr(CONFIG, "AI_EMAIL_CONFIG", config)
    monkeypatch.setattr(CONFIG, "CUSTOM_DOMAIN", "app.example.com")
    monkeypatch.setattr(CONFIG, "SECRET_KEY", "feedback-secret")
    sent = []
    client = SimpleNamespace(
        send_email=lambda payload, *, idempotency_key: sent.append(
            (payload, idempotency_key)
        )
    )

    ai_email.send_report_feedback(report, "success", client=client)

    payload, idempotency_key = sent[0]
    assert payload["to"] == ["Owner@example.com"]
    assert payload["reply_to"] == "ai@inbound.example.com"
    assert "https://app.example.com/tools/reports/email-report-one" in payload["text"]
    assert REPLY_MARKER in payload["text"]
    assert payload["headers"]["Auto-Submitted"] == "auto-generated"
    assert idempotency_key.startswith("ai-email/success/")


# @matrix ai-email : generic-delivery terminal-delivery
def test_report_terminal_feedback_uses_generic_notification_delivery():
    from lagniappe.core.tools.deferred_jobs.adapters.reports import ReportAdapter

    adapter = ReportAdapter()
    user = TestEntities.get("USER", {"name": "Owner", "owner": False})
    email_report = TestEntities.get(
        "REPORT", {"parent": user, "user": user, "tool": "ask"}
    )
    email_report.origin = "email"
    browser_report = TestEntities.get(
        "REPORT", {"parent": user, "user": user, "tool": "ask"}
    )

    def context(report, parameters):
        return SimpleNamespace(
            input=lambda name: report if name == "report" else None,
            parameters=parameters,
        )

    assert not adapter.external_delivery_required(context(email_report, {}))
    assert not adapter.external_delivery_required(
        context(email_report, {"mode": "revise"})
    )
    assert not adapter.external_delivery_required(context(browser_report, {}))


# @matrix ai-email webhook : lease privacy replay terminal-compaction transaction transient-release
def test_ai_email_event_claim_is_durable_and_replay_safe(monkeypatch):
    from lagniappe.core.tools.database import ai_email as email_database

    class Record(dict):
        def __init__(self, key=None, **_kwargs):
            super().__init__()
            self.key = key

    class Store:
        def __init__(self):
            self.rows = {}

        def key(self, kind, identifier, parent=None):
            return kind, identifier, parent

        def transaction(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, key, transaction=None):
            return self.rows.get(key)

        def put(self, record):
            self.rows[record.key] = record

    store = Store()
    monkeypatch.setattr(email_database, "Entity", Record)
    monkeypatch.setattr(email_database.DATA, "_datastore_client", store)
    digest = "a" * 64
    now = datetime.now(timezone.utc)

    assert email_database.claim_ai_email_event(digest, "lease-one", now)["claimed"]
    active = email_database.claim_ai_email_event(
        digest, "lease-two", now + timedelta(seconds=1)
    )
    assert active == {"claimed": False, "reason": "active", "state": "processing"}
    assert not email_database.release_ai_email_event(digest, "wrong-lease", now)
    assert email_database.release_ai_email_event(digest, "lease-one", now)
    resumed = email_database.claim_ai_email_event(digest, "lease-two", now)
    assert resumed["claimed"]
    assert email_database.finish_ai_email_event(digest, "lease-two", "accepted", now)
    terminal = email_database.claim_ai_email_event(digest, "lease-three", now)
    assert terminal == {"claimed": False, "reason": "terminal", "state": "accepted"}
    only_row = next(iter(store.rows.values()))
    assert "lease_token" not in only_row
    assert "event-1" not in repr(only_row)


class _InboundClient:
    def retrieve_received_email(self, email_id):
        return {
            "id": email_id,
            "from": "Owner@example.com",
            "to": ["ask@inbound.example.com"],
            "subject": "Question",
            "text": "What changed?",
            "headers": {},
        }

    def list_received_attachments(self, _email_id):
        return []


# @matrix ai-email webhook : exact-match replay report-handoff sender user-policy
def test_process_resend_email_hands_off_to_existing_report_pipeline(monkeypatch):
    from lagniappe.core.entities import Entities
    from lagniappe.core.tools.database import ai_email as email_database
    from lagniappe.core.tools.database import get as database_get

    user = TestEntities.get(
        "USER",
        {"name": "Owner", "owner": False},
    )
    user.email = "Owner@example.com"
    user.is_public = False
    report = SimpleNamespace(urlsafe_key="report-one")
    states = []
    monkeypatch.setattr(
        email_database, "claim_ai_email_event", lambda *_args: {"claimed": True}
    )
    monkeypatch.setattr(
        email_database,
        "finish_ai_email_event",
        lambda *args: states.append(args[2]),
    )
    monkeypatch.setattr(email_database, "release_ai_email_event", lambda *_args: None)
    monkeypatch.setattr(
        database_get, "user", lambda email: "raw-user" if email == user.email else None
    )
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda value, *, request: user if value == "raw-user" else None,
    )
    monkeypatch.setattr(
        ai_email,
        "_preflight_submission",
        lambda message, tool, actor, config: ("Subject: Question\n\nWhat changed?", ()),
    )
    monkeypatch.setattr(
        ai_email,
        "_create_email_report",
        lambda *args, **kwargs: report,
    )

    result = ai_email.process_resend_email(
        {"type": "email.received", "data": {"email_id": "email-1"}},
        "event-1",
        _config(),
        "secret",
        client=_InboundClient(),
    )
    assert result.state == "accepted"
    assert result.report is report
    assert states == ["accepted"]


# @matrix ai-email : idempotency privacy report-handoff routing
def test_create_shared_address_email_report_preserves_routing_input(monkeypatch):
    from lagniappe.core.entities import Entities
    from lagniappe.core.tools.database import utility as database_utility
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

    user = SimpleNamespace(urlsafe_key="user-one")
    message = SimpleNamespace(
        provider_message_id="provider-message-one",
        subject="Paid invoice",
        text_body="Fill its task and save the confirmation number.",
        received_at="2026-08-15T12:00:00Z",
    )
    attachment = InboundAttachment(
        "attachment-one",
        "invoice.pdf",
        "application/pdf",
        1200,
    )
    saved = []
    starts = []

    monkeypatch.setattr(
        database_utility, "create_named_key", lambda *_args: "report-key"
    )
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: None)

    def create_report(data, *, key):
        return SimpleNamespace(
            **data,
            key=key,
            urlsafe_key="email-report-one",
        )

    monkeypatch.setattr(Entities.REPORT, "create", create_report)
    monkeypatch.setattr(Entities, "save", lambda *entities: saved.append(entities))
    monkeypatch.setattr(
        DeferredJobs,
        "start",
        lambda spec: starts.append(spec) or (SimpleNamespace(), None),
    )

    report = ai_email._create_email_report(
        message,
        "ai",
        user,
        "Subject: Paid invoice\n\nFill its task.",
        (attachment,),
        "a" * 64,
        _config(),
    )

    assert report.tool == "ask"
    assert report.name == "Email: Paid invoice"
    assert report.inbound_manifest["requested_tool"] == "ai"
    assert report.inbound_manifest["tool"] == "ask"
    assert report.inbound_manifest["alias"] == "ai@inbound.example.com"
    assert report.inbound_manifest["attachments"] == [attachment.display_record()]
    assert saved == [(report, user)]
    assert starts[0].parameters["requested_tool"] == "ai"
    assert starts[0].parameters["attachments"] == [attachment.job_record()]


# @matrix ai-email deferred-jobs : acceptance idempotency report-handoff
def test_email_ingest_adapter_starts_existing_report_job_idempotently(monkeypatch):
    from lagniappe import CONFIG
    from lagniappe.core.tools.deferred_jobs.adapters import email as email_adapters

    user = TestEntities.get("USER", {"name": "Owner", "owner": False})
    user.email = "Owner@example.com"
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Ask: Question",
            "tool": "ask",
            "input_files": [],
            "user": user,
            "parent": user,
        },
    )
    report.origin = "email"
    starts = []
    feedback = []
    monkeypatch.setattr(CONFIG, "AI_EMAIL_CONFIG", _config())
    monkeypatch.setattr(email_adapters.Entities, "save", lambda *_args: None)
    monkeypatch.setattr(
        "lagniappe.core.tools.deferred_jobs.service.DeferredJobs.start",
        lambda spec: (
            starts.append(spec) or SimpleNamespace(urlsafe_key="child-job"),
            None,
        ),
    )
    monkeypatch.setattr(
        ai_email,
        "send_report_feedback",
        lambda submitted, kind, client=None: feedback.append((submitted, kind)),
    )
    checkpoint_state = {}

    def checkpoint_stage(stage, values=None, phase=None):
        checkpoint_state.update(
            {
                "schema_version": 1,
                "stage": stage,
                **(values or {}),
            }
        )

    context = SimpleNamespace(
        actor=user,
        parameters={"attachments": [], "event_digest": "a" * 64},
        checkpoint=checkpoint_state,
        input=lambda name: report if name == "report" else None,
        ensure_active=lambda: None,
        checkpoint_stage=checkpoint_stage,
    )
    checkpoint = email_adapters.EmailIngestAdapter().prepare(context)
    assert checkpoint == {
        "schema_version": 1,
        "stage": "acceptance_sent",
        "report_job": "child-job",
    }
    assert starts[0].job_type.value == "report-ask"
    assert starts[0].idempotency_key == f"ai-email/report/{'a' * 64}"
    assert feedback == [(report, "acceptance")]


# @matrix ai-email deferred-jobs : idempotency permissions routing utility-model
def test_email_ingest_adapter_routes_shared_address_once(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.adapters import email as email_adapters

    user = TestEntities.get("USER", {"name": "Owner", "owner": False})
    user.access = lambda _required: True
    report = TestEntities.get(
        "REPORT",
        {
            "name": "AI: Paid invoice",
            "tool": "ask",
            "user": user,
            "parent": user,
        },
    )
    report.origin = "email"
    report.inbound_manifest = {
        "subject": "Paid invoice",
        "body": "Fill the existing task with the confirmation number.",
        "tool": "ask",
        "requested_tool": "ai",
        "alias": "ai@inbound.example.com",
    }
    calls = []
    saved = []
    monkeypatch.setattr(
        email_adapters.ai,
        "route_ai_email",
        lambda *args: (
            calls.append(args)
            or {
                "workflow": "organize",
                "confidence": 0.96,
                "reason": "The attachment should update a submission.",
            }
        ),
    )
    monkeypatch.setattr(
        email_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    parameters = {"requested_tool": "ai"}
    attachments = [
        {
            "id": "attachment-1",
            "filename": "invoice.pdf",
            "content_type": "application/pdf",
            "size": 1200,
        }
    ]
    adapter = email_adapters.EmailIngestAdapter()

    assert (
        adapter._route_shared_address(report, user, parameters, attachments)
        == "organize"
    )
    assert (
        adapter._route_shared_address(report, user, parameters, attachments)
        == "organize"
    )

    assert len(calls) == 1
    assert report.tool == "organize"
    assert report.inbound_manifest["requested_tool"] == "ai"
    assert report.inbound_manifest["resolved_tool"] == "organize"
    assert report.inbound_manifest["route_confidence"] == 0.96
    assert len(saved) == 2


# @matrix ai-email deferred-jobs feedback : diagnostics failure privacy terminal-delivery
def test_email_ingest_failure_surfaces_bounded_diagnostic(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.adapters import email as email_adapters

    user = TestEntities.get("USER", {"name": "Owner", "owner": False})
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Organize: image.jpg",
            "tool": "organize",
            "user": user,
            "parent": user,
            "status": "pending",
            "pending": True,
        },
    )
    report.origin = "email"
    saved = []
    feedback = []
    monkeypatch.setattr(
        email_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: report,
    )
    monkeypatch.setattr(
        email_adapters.Entities,
        "save",
        lambda *entities: saved.extend(entities),
    )
    monkeypatch.setattr(
        ai_email,
        "send_report_feedback",
        lambda submitted, kind, *, message=None: feedback.append(
            (submitted, kind, message)
        ),
    )
    context = SimpleNamespace(
        actor=user,
        parameters={
            "provider_message_id": "private-provider-id",
            "attachments": [{"id": "private-attachment-id"}],
            "event_digest": "private-digest",
            "_diagnostic_code": "attachment_download_failed",
        },
        checkpoint={},
        input=lambda name: report if name == "report" else None,
    )
    error = ai_email.AIEmailProviderError("Resend returned an invalid attachment URL.")

    adapter = email_adapters.EmailIngestAdapter()
    adapter.failure(context, error)
    expected = (
        "The email submission could not be prepared. "
        "Diagnostic: attachment_download_failed. "
        "Resend returned an invalid attachment URL."
    )
    assert report.error == expected
    assert report in saved

    adapter.cleanup(context, terminal=True)
    adapter.external_delivery(context, succeeded=False, error=error)
    assert feedback == [(report, "failure", expected)]
    assert context.parameters == {"_diagnostic_message": expected}


# @matrix ai-email : access attachment-contract body-contract rate-limit
def test_submission_contract_keeps_create_and_organize_report_only(monkeypatch):
    monkeypatch.setattr(
        "lagniappe.core.tools.cache.rate_limit.check_limit",
        lambda *_args: {"allowed": True, "retry_after": 0},
    )
    user = SimpleNamespace(access=lambda _required: True, urlsafe_key="user-one")
    message = SimpleNamespace(
        headers={},
        subject="Create this",
        text_body="Use the existing report workflow.",
        attachments=(InboundAttachment("file-1", "notes.txt", "text/plain", 10),),
    )
    with pytest.raises(AIEmailRejection, match="Create email does not accept"):
        ai_email._preflight_submission(message, "create", user, _config())
    with pytest.raises(AIEmailRejection, match="requires at least one"):
        ai_email._preflight_submission(
            SimpleNamespace(
                headers={}, subject="Organize", text_body="", attachments=()
            ),
            "organize",
            user,
            _config(),
        )
    instructions, attachments = ai_email._preflight_submission(
        message,
        "ai",
        user,
        _config(),
    )
    assert instructions.startswith("Subject: Create this")
    assert [attachment.filename for attachment in attachments] == ["notes.txt"]
