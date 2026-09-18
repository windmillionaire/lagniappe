"""Bounded live-provider attempts and explicit, independently checked fallbacks."""

from copy import deepcopy
import logging
import re
import time
from urllib.parse import urlsplit

from config.ai_models import AI_REQUEST_TIMEOUT_MS, AI_RETRY_ATTEMPTS
from lagniappe.core.definitions import DeferredJobStatus, DeferredJobType
from lagniappe.core.entities import Entities


# The SDK timeout applies to each provider attempt, not to the complete request.
# Leave one minute for retry delays and the surrounding application response.
LIVE_AI_RESPONSE_TIMEOUT_MS = (
    AI_REQUEST_TIMEOUT_MS * AI_RETRY_ATTEMPTS + 60_000
)
LIVE_AI_QUOTA_BACKOFF_SECONDS = 30
LIVE_AI_ATTEMPTS = 2


# @testable false
# @covered-by testing/utility/live_ai.py::run_live_ai
# @reason sentinel keeps provider availability separate from failed assertions
class ProviderQuotaBlocked(RuntimeError):
    """A positively identified provider quota failure, never a bad answer."""


# @testable true
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_quota_classification_does_not_accept_application_errors
# @matrix ai e2e : live-provider quota-fallback
def is_quota_message(message):
    message = str(message or "").strip()
    message = message.removeprefix("AI unable to generate summary: ")
    message = message.removeprefix("Generation failed. Please try again.").strip()
    return message.startswith("AI quota is temporarily exhausted.") or bool(
        re.match(r"429\s+RESOURCE_EXHAUSTED\b", message)
    )


# @testable true
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_live_provider_retries_only_quota_and_records_the_outcome
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_live_provider_requires_verified_fallback_after_bounded_attempts
# @matrix ai e2e : live-provider quota-fallback backoff
def run_live_ai(attempt, *, results, fallback, sleep=None):
    """Try the real boundary twice; only quota can select an explicit fallback."""
    failures = []
    for number in range(1, LIVE_AI_ATTEMPTS + 1):
        try:
            value = attempt(number)
        except ProviderQuotaBlocked as error:
            failures.append({"attempt": number, "error": str(error)[:1000]})
            results.record("provider_quota_attempt", failures[-1])
            if number < LIVE_AI_ATTEMPTS:
                results.record("provider_backoff_seconds", LIVE_AI_QUOTA_BACKOFF_SECONDS)
                (sleep or time.sleep)(LIVE_AI_QUOTA_BACKOFF_SECONDS)
        else:
            results.record("live_provider_outcome", {
                "live_succeeded": True, "attempts": number, "fallback_used": False,
                "quota_failures": failures,
            })
            return value

    # A fallback is a test-owned alternate verification, not permission to turn
    # an arbitrary exception or an incorrect model answer into a passing test.
    value = fallback()
    results.record("live_provider_outcome", {
        "live_succeeded": False, "attempts": LIVE_AI_ATTEMPTS,
        "fallback_used": True, "quota_failures": failures,
    })
    logging.getLogger(__name__).warning(
        "Live provider remained quota-limited; the test verified its explicit fallback."
    )
    return value


# @testable infrastructure
def submit_live_ai(user, *, path, submit, results, browser_failures, fallback,
                   timeout=LIVE_AI_RESPONSE_TIMEOUT_MS):
    """Retry one UI request, accepting only quota-labelled error responses."""
    def attempt(_number):
        with browser_failures.expect_http_error(user, status=422, path=path, count=0, max_count=1):
            with user.page.expect_response(
                lambda response: response.request.method == "POST" and urlsplit(response.url).path == path,
                timeout=timeout,
            ) as response_info:
                submit()
            response = response_info.value
            body = response.text()
            results.record("provider_response", {"status": response.status, "body": body})
            quota = response.status == 422 and is_quota_message(body)
            assert response.ok or quota, body
        if quota:
            raise ProviderQuotaBlocked(body)
        return response

    return run_live_ai(attempt, results=results, fallback=fallback)


# @testable true
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_quota_fallback_rejects_non_quota_job
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_job_quota_classification_requires_provider_evidence
# @matrix ai deferred-jobs e2e : checkpoint live-provider quota-fallback
def quota_blocked_job(job):
    error = job.error or {}
    context = error.get("context") or {}
    provider = context.get("ai_provider", {}) if isinstance(context, dict) else {}
    wrapped_quota = (
        error.get("type") == "AIException"
        and isinstance(provider, dict)
        and provider.get("quota_exhausted") is True
        and (
            str(provider.get("code")) == "429"
            or provider.get("status") == "RESOURCE_EXHAUSTED"
        )
    )
    return (
        job.status in {DeferredJobStatus.FAILED.value, DeferredJobStatus.RETRY_WAIT.value}
        and (error.get("type") == "AIQuotaError" or wrapped_quota)
        and (job.checkpoint or {}).get("stage") != "ready_to_apply"
    )


# @testable true
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_quota_fallback_injects_resumable_report_checkpoint
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_quota_fallback_rejects_non_quota_job
# @matrix ai deferred-jobs e2e : checkpoint live-provider quota-fallback
def inject_quota_fallback_checkpoint(job, proposal, *, failed_job):
    """Publish a verified answer through a fresh, UI-created retry operation."""
    if (
        not quota_blocked_job(failed_job)
        or job.job_type != DeferredJobType.REPORT_AI.value
        or failed_job.job_type != job.job_type
        or job.status != DeferredJobStatus.QUEUED.value
        or job.attempt
        or job.checkpoint
        or job.urlsafe_key == failed_job.urlsafe_key
        or job.inputs != failed_job.inputs
        or job.actor.key != failed_job.actor.key
    ):
        raise AssertionError(
            "AI fallback requires an unstarted retry of the same quota-blocked report."
        )

    from lagniappe.core.tools.ai.reporting.proposals.validation import validate_proposal

    proposal = validate_proposal(deepcopy(proposal), allowed_actions=(), require_response=True)
    checkpoint = {
        "schema_version": 1,
        "stage": "ready_to_apply",
        "proposal": proposal,
        "file_usage": [],
        "status": "complete",
    }
    job.checkpoint = checkpoint
    Entities.save(job)
    return checkpoint


# @testable true
# @tests tests_unit/test_023g_live_ai_test_helper.py::test_autofill_fallback_retains_preparation_and_rejects_unrelated_failures
# @matrix ai deferred-jobs e2e : checkpoint live-provider quota-fallback
def prepare_autofill_fallback(job, submission):
    """Retain real attachment preparation, authorization, and apply-time guards."""
    from datetime import datetime, timezone
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

    assert quota_blocked_job(job) and job.status == DeferredJobStatus.RETRY_WAIT.value
    assert job.job_type == DeferredJobType.AUTOFILL.value
    adapter = DeferredJobs.adapter(job.job_type)
    context = adapter.load(DeferredJobs._context(job))
    adapter.authorize(context)
    adapter.validate_apply(context)
    context.checkpoint = {"submission": deepcopy(submission)}
    job.checkpoint = adapter.prepare(context)
    # The remaining delivery publishes an already prepared value; it makes no
    # provider request, so the test need not wait out the provider backoff.
    job.next_attempt_at = datetime.now(timezone.utc)
    Entities.save(job)
    return deepcopy(job.checkpoint)


# @testable infrastructure
def run_hosted_autofill(user, job, *, results, verify_submission):
    """Exercise live autofill and its normal checkpoint/lock/publication path."""
    from testing.utility.hosted_deferred_jobs import dispatch_hosted_deferred_job

    current_job = job
    records = []

    def deliver():
        nonlocal current_job
        current_job, attempts = dispatch_hosted_deferred_job(
            user.page, current_job, attempt_limit=1,
            task_suffix=f"hosted-e2e-live-{len(records) + 1}",
        )
        records.extend(attempts)
        results.record("deferred_job_attempts", list(records))
        return current_job

    def attempt(_number):
        deliver()
        if quota_blocked_job(current_job):
            raise ProviderQuotaBlocked((current_job.error or {}).get("message", "AIQuotaError"))
        assert current_job.status == DeferredJobStatus.SUCCEEDED.value, records
        return current_job

    def fallback():
        checkpoint = prepare_autofill_fallback(current_job, verify_submission())
        results.record("provider_quota_fallback", {"used": True, "checkpoint": checkpoint})
        deliver()
        assert current_job.status == DeferredJobStatus.SUCCEEDED.value, records
        return current_job

    return run_live_ai(attempt, results=results, fallback=fallback)
