"""Deterministic coverage for hosted deferred-job test orchestration."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from lagniappe.core.definitions import DeferredJobStatus
from testing.utility import hosted_deferred_jobs


class _Handle:
    def json_value(self):
        return {"status": "succeeded", "terminal": True}


class _Page:
    def __init__(self):
        self.evaluations = []
        self.wait = None

    def evaluate(self, script, arg):
        self.evaluations.append((script, arg))

    def wait_for_function(self, script, *, arg, polling, timeout):
        self.wait = {
            "script": script,
            "arg": arg,
            "polling": polling,
            "timeout": timeout,
        }
        return _Handle()


# @matrix deferred-jobs hosted-e2e : polling revision timing
def test_hosted_transition_poll_starts_after_existing_revision():
    page = _Page()

    result = hosted_deferred_jobs.wait_for_hosted_job_transition(
        page,
        "job-key",
        after_revision=7,
        timeout=240_000,
    )

    assert result == {"status": "succeeded", "terminal": True}
    assert page.evaluations[0][1] == {
        "key": "job-key",
        "stateKey": "__lagniappeHostedJobjob-key",
        "afterRevision": 7,
    }
    assert "revision: afterRevision" in page.evaluations[0][0]
    assert page.wait["timeout"] == 240_000


# @matrix deferred-jobs hosted-e2e : retry revision scheduling timing
def test_hosted_retry_waits_for_new_revision_and_scheduled_delay(monkeypatch):
    now = datetime.now(timezone.utc)
    retry_job = SimpleNamespace(
        urlsafe_key="retry-job",
        status=DeferredJobStatus.RETRY_WAIT.value,
        status_revision=4,
        next_attempt_at=now + timedelta(seconds=65),
    )
    succeeded_job = SimpleNamespace(
        urlsafe_key="retry-job",
        status=DeferredJobStatus.SUCCEEDED.value,
        status_revision=6,
        next_attempt_at=None,
        attempt=2,
        error={},
        progress={"phase": "complete"},
    )
    waits = []
    created = []
    deleted = []

    monkeypatch.setattr(
        hosted_deferred_jobs,
        "CONFIG",
        SimpleNamespace(
            hosted_e2e_runner=True,
            TASK_QUEUE_ENABLED=True,
            APP_URL="https://hosted-e2e.test",
        ),
    )
    monkeypatch.setattr(
        hosted_deferred_jobs.TaskIdentity,
        "create",
        lambda *args, **kwargs: "retry-task",
    )
    monkeypatch.setattr(
        hosted_deferred_jobs.task_queue,
        "create_task",
        lambda endpoint, payload, **kwargs: created.append(kwargs) or "retry-task",
    )
    monkeypatch.setattr(
        hosted_deferred_jobs.task_queue,
        "delete_task",
        deleted.append,
    )
    monkeypatch.setattr(
        hosted_deferred_jobs,
        "wait_for_hosted_job_transition",
        lambda page, key, **kwargs: waits.append(kwargs)
        or {"status": "succeeded", "terminal": True},
    )
    monkeypatch.setattr(
        hosted_deferred_jobs.Entities,
        "fetch_one",
        lambda *args, **kwargs: succeeded_job,
    )

    completed, attempts = hosted_deferred_jobs.dispatch_hosted_deferred_job(
        object(),
        retry_job,
        attempt_limit=1,
    )

    assert completed is succeeded_job
    assert attempts[0]["status"] == DeferredJobStatus.SUCCEEDED.value
    assert created[0]["delay_seconds"] in {64, 65}
    assert waits == [
        {
            "after_revision": 4,
            "timeout": 180_000 + created[0]["delay_seconds"] * 1_000,
        }
    ]
    assert deleted == ["retry-task"]
