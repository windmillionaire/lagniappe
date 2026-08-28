"""Test-only budgets and quota fallbacks for live provider stories."""

from copy import deepcopy
from datetime import datetime, timezone

from config.ai_models import AI_REQUEST_TIMEOUT_MS, AI_RETRY_ATTEMPTS
from lagniappe.core.definitions import DeferredJobStatus
from lagniappe.core.entities import Entities


# The SDK timeout applies to each provider attempt, not to the complete request.
# Leave one minute for retry delays and the surrounding application response.
LIVE_AI_RESPONSE_TIMEOUT_MS = (
    AI_REQUEST_TIMEOUT_MS * AI_RETRY_ATTEMPTS + 60_000
)


# @testable true
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_quota_fallback_injects_resumable_report_checkpoint
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_quota_fallback_rejects_non_quota_job
# @matrix ai deferred-jobs e2e : checkpoint live-provider quota-fallback
def inject_quota_fallback_checkpoint(job, proposal):
    """Give a quota-blocked test job a synthetic checkpoint it can apply normally."""
    error = job.error or {}
    if (
        job.status != DeferredJobStatus.RETRY_WAIT.value
        or error.get("type") != "AIQuotaError"
    ):
        raise AssertionError(
            "Synthetic AI fallback requires a retry-wait AIQuotaError job."
        )

    checkpoint = {
        "proposal": deepcopy(proposal),
        "status": "ready" if proposal.get("actions") else "complete",
    }
    job.checkpoint = checkpoint
    job.next_attempt_at = datetime.now(timezone.utc)
    Entities.save(job)
    return checkpoint
