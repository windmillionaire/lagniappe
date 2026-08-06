"""Durable deferred-job integration stories."""

from uuid import uuid4

import pytest

from lagniappe.core.definitions import DeferredJobSpec, DeferredJobType
from lagniappe.core.entities import Entities
from lagniappe.core.tools.deferred_jobs import DeferredJobs
from testing.definitions import SitePages, Users


pytestmark = pytest.mark.e2e


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
            const response = await fetch("/l/poll", {
                method: "POST",
                headers,
                body: JSON.stringify({
                    version: 1,
                    client_id: "operation-owner-test",
                    subscriptions: operations.map((key, index) => ({
                        id: index === 0 ? `operation:${key}` : `operation-${index}`,
                        type: "operation",
                        key,
                        revision: 0,
                    })),
                    closed_documents: [],
                }),
            });
            const responseText = await response.text();
            let body;
            try {
                body = JSON.parse(responseText);
            } catch (_error) {
                return { status: response.status, responseText };
            }
            const current = body.results[0];
            const unchangedResponse = await fetch("/l/poll", {
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
                    }],
                    closed_documents: [],
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

    assert result["status"] == 200, result
    statuses = result["body"]["results"]
    assert statuses[0]["id"] == f"operation:{owner_job.urlsafe_key}"
    assert len(statuses[0]["id"]) > 128
    assert statuses[0]["status"] == "changed"
    assert statuses[0]["payload"]["key"] == owner_job.urlsafe_key
    assert statuses[0]["payload"]["phase"] == "queued"
    assert statuses[0]["payload"]["elapsed_seconds"] >= 0
    assert statuses[0]["payload"]["phase_elapsed_seconds"] >= 0
    assert statuses[0]["revision"] == statuses[0]["payload"]["revision"]
    assert statuses[1]["status"] == "unavailable"
    assert statuses[2]["status"] == "unavailable"
    assert result["unchangedStatus"] == 200
    unchanged = result["unchangedBody"]["results"][0]
    assert unchanged["status"] == "unchanged"
    assert unchanged["revision"] == statuses[0]["revision"]
