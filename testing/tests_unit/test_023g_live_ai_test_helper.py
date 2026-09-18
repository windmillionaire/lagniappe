"""Bounded live-AI recovery never hides non-provider failures."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from config.ai_models import AI_REQUEST_TIMEOUT_MS, AI_RETRY_ATTEMPTS
from lagniappe.core.definitions import DeferredJobStatus, DeferredJobType
from lagniappe.core.exceptions import AIException
from testing.utility import live_ai


def test_live_ai_response_timeout_covers_every_provider_attempt():
    assert live_ai.LIVE_AI_RESPONSE_TIMEOUT_MS == (
        AI_REQUEST_TIMEOUT_MS * AI_RETRY_ATTEMPTS + 60_000
    )


def _results():
    entries = []
    return SimpleNamespace(record=lambda name, value: entries.append((name, deepcopy(value)))), entries


# @matrix ai e2e : live-provider quota-fallback
@pytest.mark.parametrize("message,expected", [
    ("AI quota is temporarily exhausted. The report can retry shortly.", True),
    ("429 RESOURCE_EXHAUSTED. Resource exhausted, please try again later.", True),
    ("Generation failed. Please try again.  AI quota is temporarily exhausted. The report can retry shortly.", True),
    ("Generation failed. Please try again.  Invalid answer: 429 RESOURCE_EXHAUSTED was not expected", False),
    ("Invalid answer: the phrase RESOURCE_EXHAUSTED was not expected", False),
    ("Invalid answer: 429 RESOURCE_EXHAUSTED was not expected", False),
    ("The saved entity changed; retry", False),
    ("403 PERMISSION_DENIED", False),
    ("500 Internal Server Error", False),
])
def test_quota_classification_does_not_accept_application_errors(message, expected):
    assert live_ai.is_quota_message(message) is expected


# @matrix ai e2e : live-provider quota-fallback backoff
@pytest.mark.parametrize("error", [live_ai.ProviderQuotaBlocked("quota"), AssertionError("bad answer"), RuntimeError("bad save")])
def test_live_provider_retries_only_quota_and_records_the_outcome(error):
    results, entries = _results()
    attempts, waits = [], []
    def attempt(number):
        attempts.append(number)
        if number == 1:
            raise error
        return "verified live answer"
    def fallback():
        pytest.fail("A successful retry or product failure must not use fallback")
    if isinstance(error, live_ai.ProviderQuotaBlocked):
        assert live_ai.run_live_ai(attempt, results=results, fallback=fallback, sleep=waits.append) == "verified live answer"
        assert attempts == [1, 2] and waits == [30]
        assert entries[-1][1]["live_succeeded"] is True
        assert entries[-1][1]["fallback_used"] is False
    else:
        with pytest.raises(type(error), match=str(error)):
            live_ai.run_live_ai(attempt, results=results, fallback=fallback, sleep=waits.append)
        assert attempts == [1] and not waits


# @matrix ai e2e : live-provider quota-fallback backoff
@pytest.mark.parametrize("fallback_fails", [False, True])
def test_live_provider_requires_verified_fallback_after_bounded_attempts(fallback_fails):
    results, entries = _results()
    attempts, waits, checks = [], [], []
    def attempt(number):
        attempts.append(number)
        raise live_ai.ProviderQuotaBlocked("quota")
    def fallback():
        checks.append("independent verification")
        if fallback_fails:
            raise AssertionError("lookup is wrong")
        return "verified alternate result"
    if fallback_fails:
        with pytest.raises(AssertionError, match="lookup is wrong"):
            live_ai.run_live_ai(attempt, results=results, fallback=fallback, sleep=waits.append)
        assert not any(name == "live_provider_outcome" for name, _ in entries)
    else:
        assert live_ai.run_live_ai(attempt, results=results, fallback=fallback, sleep=waits.append) == "verified alternate result"
        assert entries[-1][1]["live_succeeded"] is False
        assert entries[-1][1]["fallback_used"] is True
    assert attempts == [1, 2] and waits == [30]
    assert checks == ["independent verification"]


def _jobs():
    shared = {"job_type": DeferredJobType.REPORT_AI.value, "actor": SimpleNamespace(key="owner"),
              "inputs": {"report": {"kind": "report", "id": "report"}}}
    failed = SimpleNamespace(**shared, urlsafe_key="old", status="failed", attempt=1,
                             checkpoint={"stage": "summaries_ready"}, error={"type": "AIQuotaError"})
    retry = SimpleNamespace(**shared, urlsafe_key="new", status="queued", attempt=0, checkpoint={}, error={})
    return failed, retry


# @matrix ai deferred-jobs e2e : checkpoint live-provider quota-fallback
@pytest.mark.parametrize("error_type,provider,expected", [
    ("AIException", {"quota_exhausted": True, "code": 429, "status": "RESOURCE_EXHAUSTED"}, True),
    ("AIException", {"quota_exhausted": True, "code": "429"}, True),
    ("AIException", {"quota_exhausted": True, "status": "RESOURCE_EXHAUSTED"}, True),
    ("AIException", {"quota_exhausted": False, "code": 429}, False),
    ("AIException", {"quota_exhausted": True, "code": 403, "status": "PERMISSION_DENIED"}, False),
    ("AIException", {"quota_exhausted": True}, False),
    ("AIException", None, False),
    ("AIException", "429 RESOURCE_EXHAUSTED", False),
    ("ValidationError", {"quota_exhausted": True, "code": 429}, False),
])
def test_job_quota_classification_requires_provider_evidence(error_type, provider, expected):
    failed, _retry = _jobs()
    failed.error = {
        "type": error_type,
        "message": "Generation failed. Please try again.  AI quota is temporarily exhausted.",
        "context": {"ai_provider": provider},
    }
    assert live_ai.quota_blocked_job(failed) is expected
    failed.status = "running"
    assert live_ai.quota_blocked_job(failed) is False
    failed.status = "failed"
    failed.checkpoint = {"stage": "ready_to_apply"}
    assert live_ai.quota_blocked_job(failed) is False


# @matrix ai deferred-jobs e2e : checkpoint live-provider quota-fallback
@pytest.mark.parametrize("wrapped", [False, True])
def test_quota_fallback_injects_resumable_report_checkpoint(monkeypatch, wrapped):
    failed, retry = _jobs()
    if wrapped:
        failed.error = {"type": "AIException", "context": {"ai_provider": {"quota_exhausted": True, "code": 429}}}
    saved = []
    proposal = {"summary": "Verified answer", "confidence": 1, "answer_html": "<p>Verified answer</p>", "actions": []}
    original = deepcopy(proposal)
    monkeypatch.setattr(live_ai.Entities, "save", saved.append)
    checkpoint = live_ai.inject_quota_fallback_checkpoint(retry, proposal, failed_job=failed)
    assert checkpoint["stage"] == "ready_to_apply"
    assert checkpoint["schema_version"] == 1
    assert checkpoint["file_usage"] == [] and checkpoint["status"] == "complete"
    assert checkpoint["proposal"]["answer_html"] == proposal["answer_html"]
    assert retry.checkpoint == checkpoint and saved == [retry]
    assert failed.status == "failed" and retry.status == "queued"
    assert proposal == original
    with pytest.raises(AIException):
        failed, retry = _jobs()
        live_ai.inject_quota_fallback_checkpoint(retry, {**proposal, "actions": [{"id": "write", "type": "create_project", "data": {"name": "Forbidden"}}]}, failed_job=failed)
    assert len(saved) == 1


# @matrix ai deferred-jobs e2e : checkpoint live-provider quota-fallback
@pytest.mark.parametrize("change", ["non_quota", "active", "checkpoint", "different_report", "different_actor", "same_job", "started"])
def test_quota_fallback_rejects_non_quota_job(change):
    failed, retry = _jobs()
    if change == "non_quota":
        failed.error = {"type": "ValidationError", "message": "quota", "retryable": True}
    elif change == "active":
        failed.status = DeferredJobStatus.RUNNING.value
    elif change == "checkpoint":
        failed.checkpoint = {"stage": "ready_to_apply"}
    elif change == "different_report":
        retry.inputs = {"report": {"kind": "report", "id": "different"}}
    elif change == "different_actor":
        retry.actor = SimpleNamespace(key="different")
    elif change == "same_job":
        retry.urlsafe_key = failed.urlsafe_key
    elif change == "started":
        retry.attempt = 1
    with pytest.raises(AssertionError, match="unstarted retry"):
        live_ai.inject_quota_fallback_checkpoint(retry, {}, failed_job=failed)


# @matrix ai deferred-jobs e2e : checkpoint live-provider quota-fallback
@pytest.mark.parametrize("failure", [None, "non_quota", "terminal", "wrong_type", "permission", "drift"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_autofill_fallback_retains_preparation_and_rejects_unrelated_failures(monkeypatch, failure, wrapped):
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

    job = SimpleNamespace(job_type=DeferredJobType.AUTOFILL.value, status="retry_wait",
                          error={"type": "AIQuotaError"}, checkpoint={}, next_attempt_at=None)
    if wrapped:
        job.error = {"type": "AIException", "context": {"ai_provider": {"quota_exhausted": True, "code": 429}}}
    context = SimpleNamespace(checkpoint={})
    calls, saved = [], []
    def authorize(_context):
        calls.append("authorize")
        if failure == "permission":
            raise ValueError("denied")
    def validate(_context):
        calls.append("validate")
        if failure == "drift":
            raise ValueError("changed")
    def prepare(current):
        calls.append("prepare")
        return {**current.checkpoint, "attachment": {"key": "existing-upload"}}
    adapter = SimpleNamespace(load=lambda value: value, authorize=authorize, validate_apply=validate, prepare=prepare)
    monkeypatch.setattr(DeferredJobs, "adapter", lambda _kind: adapter)
    monkeypatch.setattr(DeferredJobs, "_context", lambda _job: context)
    monkeypatch.setattr(live_ai.Entities, "save", saved.append)
    if failure == "non_quota":
        job.error = {"type": "ValidationError"}
    elif failure == "terminal":
        job.status = "failed"
    elif failure == "wrong_type":
        job.job_type = DeferredJobType.REPORT_AI.value
    if failure:
        with pytest.raises((AssertionError, ValueError)):
            live_ai.prepare_autofill_fallback(job, {"notes": "Known value"})
        assert not saved
        assert "prepare" not in calls
    else:
        submission = {"notes": "Known value"}
        checkpoint = live_ai.prepare_autofill_fallback(job, submission)
        assert checkpoint == {"submission": submission, "attachment": {"key": "existing-upload"}}
        assert calls == ["authorize", "validate", "prepare"]
        assert job.status == "retry_wait" and job.next_attempt_at is not None
        assert saved == [job]
        checkpoint["submission"]["notes"] = "Changed copy"
        assert job.checkpoint["submission"] == submission
