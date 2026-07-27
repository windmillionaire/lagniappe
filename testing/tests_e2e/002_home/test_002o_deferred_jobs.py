"""Durable deferred-job integration stories."""

from uuid import uuid4

from firebase_admin import messaging
import pytest

from lagniappe.core.definitions import (
    DeferredJobSpec,
    DeferredJobType,
    Fetch,
    PushDeliveryOutcome,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import deferred_jobs
from lagniappe.core.tools import deferred_job_adapters
from lagniappe.core.tools.deferred_jobs import DeferredJobs
from lagniappe.web import app as web_app, responses
from testing.definitions import SitePages, Users


pytestmark = pytest.mark.e2e


def test_deferred_push_classifies_provider_delivery_outcomes(monkeypatch):
    event = {"type": "deferred-complete", "destination": "test:Destination"}
    sent = []
    captured = []
    monkeypatch.setattr(responses.messaging, "send", sent.append)
    monkeypatch.setattr(
        responses.exceptions,
        "capture",
        lambda error, **kwargs: captured.append((error, kwargs)),
    )

    assert (
        deferred_jobs._send_event(event, "browser-token")
        is PushDeliveryOutcome.ACCEPTED
    )
    assert len(sent) == 1

    def unregistered(_message):
        raise messaging.UnregisteredError("token is no longer registered")

    monkeypatch.setattr(responses.messaging, "send", unregistered)
    assert (
        deferred_jobs._send_event(event, "expired-token")
        is PushDeliveryOutcome.PERMANENT_TOKEN_FAILURE
    )
    assert captured == []

    def quota_failure(_message):
        raise messaging.QuotaExceededError("provider quota unavailable")

    monkeypatch.setattr(responses.messaging, "send", quota_failure)
    assert (
        responses.send_message({"type": "ordinary"}, "browser-token")
        is PushDeliveryOutcome.TRANSIENT_FAILURE
    )
    with pytest.raises(
        deferred_jobs.DeferredJobInfrastructureError,
        match="event delivery is temporarily unavailable",
    ):
        deferred_jobs._send_event(event, "browser-token")
    assert len(captured) == 2


def test_report_generation_runs_through_durable_job_checkpoint(get_user, monkeypatch):
    """The report adapter checkpoints provider output before applying it."""
    user = get_user(Users.OWNER)
    owner = Entities.USER.load(user.email)
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": "Durable report generation",
            "tool": "organize",
            "instructions": "Review the workspace without changing it.",
            "status": "pending",
            "pending": True,
        }
    )
    Entities.save(report, owner)
    proposal = {
        "summary": "No changes are needed.",
        "confidence": 1,
        "issues": [],
        "actions": [],
    }
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "finalize_report_upload_manifest",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "summarize_report_input_files",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "prepare_organize_retrieval_context",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "organize_prompt",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_organize_plan",
        lambda _prompt: proposal,
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "complete_organize_submissions",
        lambda value, *_args, **_kwargs: value,
    )
    job, _notification = DeferredJobs.start(
        DeferredJobSpec(
            job_type=DeferredJobType.REPORT_ORGANIZE,
            actor=owner,
            inputs={"report": report},
            notification_target=report,
        )
    )

    with web_app.test_request_context("/"):
        result = DeferredJobs.run(job.urlsafe_key)

    saved_job = Entities.fetch_one(job.urlsafe_key, request=Fetch.direct())
    saved_report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
    assert result.success is True
    assert saved_job.checkpoint == {
        "schema_version": 1,
        "stage": "ready_to_apply",
        "proposal": proposal,
        "status": "ready",
    }
    assert saved_job.status == "succeeded"
    assert saved_report.proposal == proposal
    assert saved_report.status == "ready"


# @features deferred-jobs
# @dimensions status owner batch etag progress timing
def test_deferred_status_is_owner_safe_and_batched(get_user):
    owner_browser = get_user(Users.OWNER)
    other_browser = get_user(Users.create_user, creator=owner_browser)
    owner = Entities.USER.load(owner_browser.email)
    other = Entities.USER.load(other_browser.email)

    operation_suffix = uuid4().hex
    owner_job, _ = DeferredJobs.start(
        DeferredJobSpec(
            job_type=DeferredJobType.AUTOFILL,
            actor=owner,
            idempotency_key=f"status-owner-operation-{operation_suffix}",
            inputs={},
        )
    )
    other_job, _ = DeferredJobs.start(
        DeferredJobSpec(
            job_type=DeferredJobType.AUTOFILL,
            actor=other,
            idempotency_key=f"status-other-operation-{operation_suffix}",
            inputs={},
        )
    )
    owner_browser.go(SitePages.HOME)

    result = owner_browser.page.evaluate(
        """async (operations) => {
            const headers = {
                "Content-Type": "application/json",
                "X-CSRFToken": document.getElementById("token")?.value || "",
                "X-Lagniappe-Request": "true",
            };
            const first = await fetch("/tools/operations/status", {
                method: "POST",
                headers,
                body: JSON.stringify({operations}),
            });
            const body = await first.json();
            const etag = first.headers.get("ETag");
            const second = await fetch("/tools/operations/status", {
                method: "POST",
                headers: {...headers, "If-None-Match": etag},
                body: JSON.stringify({operations}),
            });
            return {body, etag, secondStatus: second.status};
        }""",
        [owner_job.urlsafe_key, other_job.urlsafe_key, "missing-operation"],
    )

    assert [status["key"] for status in result["body"]["operations"]] == [
        owner_job.urlsafe_key
    ]
    assert result["body"]["operations"][0]["phase"] == "queued"
    assert result["body"]["operations"][0]["elapsed_seconds"] >= 0
    assert result["body"]["operations"][0]["phase_elapsed_seconds"] >= 0
    assert result["etag"]
    assert result["secondStatus"] == 304
