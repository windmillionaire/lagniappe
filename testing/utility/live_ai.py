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
def prepare_autofill_fallback(job, submission, *, failed_job):
    """Stage verified values on a fresh UI retry; never revive a terminal job."""
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
    from lagniappe.core.tools.deferred_jobs.locks import deferred_job_lock_key
    from lagniappe.core.tools.forms import review
    from lagniappe.core.tools.database import assets
    from lagniappe.core.tools.database.utility import ExactEntityState
    from lagniappe.core.mutations import execute_mutation, plan_root
    from lagniappe.core.definitions import Action, Fetch, FileConsumer

    assert (
        quota_blocked_job(failed_job)
        and failed_job.status == DeferredJobStatus.FAILED.value
        and job.job_type == failed_job.job_type == DeferredJobType.AUTOFILL.value
        and job.status == DeferredJobStatus.QUEUED.value
        and not job.attempt and not job.checkpoint
        and job.urlsafe_key != failed_job.urlsafe_key
        and job.inputs == failed_job.inputs and job.actor.key == failed_job.actor.key
        and all(job.parameters.get(key) == failed_job.parameters.get(key)
                for key in ("user_context", "upload_record", "file_key", "mode", "lock_target"))
    ), "Autofill fallback requires an unstarted retry of the same quota-blocked input."
    original = ExactEntityState(deepcopy(dict(job.db)))
    adapter = DeferredJobs.adapter(job.job_type)
    context = adapter.load(DeferredJobs._context(job))
    adapter.authorize(context)
    target = context.input("target")
    snapshot = job.parameters["snapshot"]
    assert review.snapshot_matches_form(snapshot, target), "The retry form changed."
    assert snapshot["revision"] == target.autofill_revision, "The retry answers changed."
    if job.parameters.get("upload_record"):
        assets.verify_direct_upload(job.parameters["upload_record"], max_age=None, consumer=FileConsumer.AI_INLINE)
    if job.parameters.get("file_key"):
        file = Entities.fetch_one(job.parameters["file_key"], request=Fetch.direct())
        assert isinstance(file, Entities.FILE) and file.allowed(Action.VIEW, user=context.actor)
    proposal = review.prepare_proposal(snapshot["prompt"]["schema"], deepcopy(submission), target, context.actor)
    guards = [(job.key, original), (target.key, ExactEntityState(deepcopy(dict(target.db))))]
    if target.form:
        guards.append((target.form.key, ExactEntityState(deepcopy(dict(target.form.db)))))
    if job.parameters.get("lock_target", True):
        guards.append((deferred_job_lock_key(target), {"operation": job.urlsafe_key}))
    job.checkpoint = {"submission": deepcopy(submission), "proposal": proposal}
    execute_mutation(plan_root(job, property_mask=("checkpoint",)), guards=guards)
    return deepcopy(job.checkpoint)


# @testable infrastructure
def run_hosted_autofill(user, job, *, results, verify_submission):
    """Exercise live autofill and its normal checkpoint/lock/publication path."""
    from testing.utility.hosted_deferred_jobs import dispatch_hosted_deferred_job

    current_job = job
    records = []

    def retry():
        nonlocal current_job
        from lagniappe.core.definitions import Fetch
        from playwright.sync_api import expect

        failed = current_job
        assert quota_blocked_job(failed) and failed.status == DeferredJobStatus.FAILED.value
        target_key = failed.inputs["target"]["id"]
        form = user.page.locator(f'form[data-operation="{failed.urlsafe_key}"]')
        button = form.get_by_role("button", name="Retry autofill", exact=True)
        expect(button).to_be_visible()
        with user.page.expect_response(
            lambda response: response.request.method == "PUT"
            and urlsplit(response.url).path.endswith(f"/{target_key}/update")
        ) as response_info:
            button.click()
        response = response_info.value
        assert response.ok, response.text()
        payload = response.json()
        assert payload.get("operation") and payload["operation"] != failed.urlsafe_key
        current_job = Entities.fetch_one(payload["operation"], request=Fetch.direct())
        results.record("provider_retry_operation", current_job.urlsafe_key)
        return failed

    def deliver():
        nonlocal current_job
        current_job, attempts = dispatch_hosted_deferred_job(
            user.page, current_job, attempt_limit=1,
            task_suffix=f"hosted-e2e-live-{len(records) + 1}",
        )
        records.extend(attempts)
        results.record("deferred_job_attempts", list(records))
        return current_job

    def attempt(number):
        if number > 1:
            retry()
        deliver()
        if quota_blocked_job(current_job):
            raise ProviderQuotaBlocked((current_job.error or {}).get("message", "AIQuotaError"))
        assert current_job.status == DeferredJobStatus.SUCCEEDED.value, records
        return current_job

    def fallback():
        submission = verify_submission()
        failed = retry()
        checkpoint = prepare_autofill_fallback(current_job, submission, failed_job=failed)
        results.record("provider_quota_fallback", {"used": True, "checkpoint": checkpoint})
        deliver()
        assert current_job.status == DeferredJobStatus.SUCCEEDED.value, records
        return current_job

    return run_live_ai(attempt, results=results, fallback=fallback)
