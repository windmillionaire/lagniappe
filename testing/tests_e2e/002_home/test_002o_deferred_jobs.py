"""Durable deferred-job integration stories."""

from uuid import uuid4

import pytest

from lagniappe.core.definitions import (
    DeferredJobSpec,
    DeferredJobType,
    Fetch,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import deferred_job_adapters
from lagniappe.core.tools.deferred_jobs import DeferredJobs
from lagniappe.web import app as web_app
from testing.definitions import SitePages, Users


pytestmark = pytest.mark.e2e


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


# @pairs polling:protocol polling:operation polling:owner polling:batching
# @pairs polling:progress polling:timing polling:revision polling:unavailable
# @pair polling:permissions
# @pairs deferred-jobs:status deferred-jobs:owner deferred-jobs:batching
# @pairs deferred-jobs:progress deferred-jobs:timing
def test_poll_operation_is_owner_safe(get_user):
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
            const response = await fetch("/poll", {
                method: "POST",
                headers,
                body: JSON.stringify({
                    version: 1,
                    client_id: "operation-owner-test",
                    subscriptions: operations.map((key, index) => ({
                        id: index === 0 ? `operation:${key}` : `operation-${index}`,
                        type: "operation",
                        key,
                        revision: null,
                    })),
                }),
            });
            const body = await response.json();
            const current = body.results[0];
            const unchangedResponse = await fetch("/poll", {
                method: "POST",
                headers,
                body: JSON.stringify({
                    version: 1,
                    client_id: "operation-owner-test",
                    subscriptions: [{
                        id: `operation:${operations[0]}`,
                        type: "operation",
                        key: operations[0],
                        revision: current.revision,
                        operation_revision: current.operation_revision,
                    }],
                }),
            });
            return {
                status: response.status,
                body,
                unchangedStatus: unchangedResponse.status,
                unchangedBody: await unchangedResponse.json(),
            };
        }""",
        [owner_job.urlsafe_key, other_job.urlsafe_key, "missing-operation"],
    )

    assert result["status"] == 200
    statuses = result["body"]["results"]
    assert statuses[0]["id"] == f"operation:{owner_job.urlsafe_key}"
    assert len(statuses[0]["id"]) > 128
    assert statuses[0]["status"] == "changed"
    assert statuses[0]["payload"]["key"] == owner_job.urlsafe_key
    assert statuses[0]["payload"]["phase"] == "queued"
    assert statuses[0]["payload"]["elapsed_seconds"] >= 0
    assert statuses[0]["payload"]["phase_elapsed_seconds"] >= 0
    assert statuses[0]["revision"] == statuses[0]["payload"]["revision"]
    assert isinstance(statuses[0]["operation_revision"], int)
    assert statuses[1]["status"] == "unavailable"
    assert statuses[2]["status"] == "unavailable"
    assert result["unchangedStatus"] == 200
    unchanged = result["unchangedBody"]["results"][0]
    assert unchanged["status"] == "unchanged"
    assert unchanged["revision"] == statuses[0]["revision"]
    assert unchanged["operation_revision"] == statuses[0]["operation_revision"]
