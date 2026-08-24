"""Focused deferred-job behavior tests."""

from datetime import datetime, timedelta, timezone
import threading
from types import SimpleNamespace

from google.api_core import exceptions as google_exceptions
from google.genai import errors as genai_errors
import httpx
import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    DeferredJobPhase,
    DeferredJobRunState,
    DeferredJobStatus,
    DeferredJobType,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.deferred_jobs import control as deferred_control
from lagniappe.core.tools.ai import observability
from lagniappe.core.tools.deferred_jobs import retry as deferred_retry
from lagniappe.core.tools.deferred_jobs.adapters.base import DeferredJobAdapter
from lagniappe.core.tools.deferred_jobs.adapters import email as email_adapters
from lagniappe.core.tools.deferred_jobs.adapters import registry_defaults
from lagniappe.core.tools.deferred_jobs.adapters.registry import (
    DeferredJobAdapterRegistry,
)
from lagniappe.core.tools.deferred_jobs.control import (
    DeferredExecutionControl,
    _DeferredLeaseGuard,
)
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobClaimLostError,
    DeferredJobDeadlineError,
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
)
from lagniappe.core.tools.deferred_jobs.retry import MODEL_BUSY_MESSAGE
from lagniappe.core.tools.deferred_jobs.service import DeferredJobService
from testing.utility.deferred_job_fakes import (
    RecordingAdapter,
    RunnerJob,
    runner as make_runner,
)
from testing.utility.deferred_job_fakes import operation_projection  # noqa: F401
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


# @pair deferred-jobs:preparation-context
# @pair observability:job-type
# @pair observability:attempt
# @pair observability:contract-version
# @pair observability:no-job-key
@pytest.mark.unit
def test_runner_supplies_bounded_ai_observability_context_during_prepare(monkeypatch):
    job = RunnerJob(attempt=3)
    adapter = RecordingAdapter()
    registry = make_runner(monkeypatch, job, adapter)

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.COMPLETE
    assert adapter.ai_execution_context == observability.AIExecutionContext(
        job_type="autofill",
        attempt=3,
        contract_version=1,
    )
    assert not hasattr(adapter.ai_execution_context, "job_key")
    assert observability._EXECUTION_CONTEXT.get() == observability.AIExecutionContext()


def _registered_ai_job_types():
    registry = DeferredJobService()
    registry.adapter_registry._load_default_adapters()
    return tuple(
        sorted(
            (
                job_type
                for job_type, adapter in registry.adapter_registry._adapters.items()
                if adapter.required_ai_access is not None
            ),
            key=lambda job_type: job_type.value,
        )
    )


# @pair ai-access:tier-declaration
# @pair deferred-jobs:tier-declaration
# @pair deferred-jobs:adapter-registry
# @pair deferred-jobs:domain-strategy
# @pair deferred-jobs:adapter-registration
# @pair deferred-jobs:adapter-lookup
@pytest.mark.unit
def test_registered_adapters_declare_required_ai_tiers():
    registry = DeferredJobService()
    registry.adapter_registry._load_default_adapters()

    expected = {
        DeferredJobType.REPORT_ASK: AI.ASK,
        DeferredJobType.REPORT_ORGANIZE: AI.CREATE,
        DeferredJobType.REPORT_CREATE: AI.CREATE,
        DeferredJobType.REPORT_EXECUTION: AI.CREATE,
        DeferredJobType.AUTOFILL: AI.CREATE,
        DeferredJobType.PAGE_GENERATION: AI.CREATE,
        DeferredJobType.FILE_SUMMARIZE: AI.CREATE,
        DeferredJobType.FILE_EXTRACT: None,
        DeferredJobType.EMAIL_INGEST: None,
    }

    assert set(registry.adapter_registry._adapters) == set(DeferredJobType)
    assert {
        job_type: registry.adapter(job_type).required_ai_access for job_type in expected
    } == expected


# @pairs deferred-jobs:adapter-registry deferred-jobs:adapter-registration
def test_adapter_registry_rejects_duplicate_job_types():
    registry = DeferredJobAdapterRegistry()
    registry.register(RecordingAdapter())

    with pytest.raises(ValueError, match="autofill"):
        registry.register(RecordingAdapter())


# @pairs deferred-jobs:adapter-registry deferred-jobs:failure-isolation
def test_adapter_registry_rolls_back_failed_default_loading(monkeypatch):
    registry = DeferredJobAdapterRegistry()
    adapter = RecordingAdapter()

    def fail_loading(target):
        target.register(adapter)
        raise RuntimeError("default import failed")

    monkeypatch.setattr(registry_defaults, "register_adapters", fail_loading)
    with pytest.raises(RuntimeError, match="default import failed"):
        registry._load_default_adapters()

    assert registry._adapters == {}
    assert registry._defaults_loaded is False

    monkeypatch.setattr(
        registry_defaults,
        "register_adapters",
        lambda target: target.register(adapter),
    )
    registry._load_default_adapters()

    assert registry._adapters == {DeferredJobType.AUTOFILL: adapter}
    assert registry._defaults_loaded is True


# @pairs deferred-jobs:adapter-registry deferred-jobs:concurrency
def test_adapter_registry_loads_defaults_once_across_threads(monkeypatch):
    registry = DeferredJobAdapterRegistry()
    started = threading.Event()
    release = threading.Event()
    calls = []
    failures = []

    def load_defaults(target):
        calls.append("load")
        started.set()
        assert release.wait(timeout=2)
        target.register(RecordingAdapter())

    def load_in_thread():
        try:
            registry._load_default_adapters()
        except Exception as error:  # pragma: no cover - asserted through failures
            failures.append(error)

    monkeypatch.setattr(registry_defaults, "register_adapters", load_defaults)
    first = threading.Thread(target=load_in_thread)
    second = threading.Thread(target=load_in_thread)
    first.start()
    assert started.wait(timeout=2)
    second.start()
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert calls == ["load"]
    assert registry._defaults_loaded is True


# @pair deferred-jobs:authorization
# @pair ai:authorization
# @pair ai:access-gate
# @pair ai:provider-boundary
@pytest.mark.parametrize(
    "job_type",
    _registered_ai_job_types(),
    ids=lambda job_type: job_type.value,
)
def test_registered_ai_adapters_reject_restricted_actor_before_prepare(
    monkeypatch,
    job_type,
):
    registry = DeferredJobService()
    adapter = registry.adapter(job_type)
    prepare_calls = []
    monkeypatch.setattr(
        adapter,
        "prepare",
        lambda _context: prepare_calls.append(job_type) or {},
    )

    job = RunnerJob()
    job.job_type = job_type.value
    job.authorization["policy"] = job_type.value
    job.actor = SimpleNamespace(
        urlsafe_key="actor-key",
        access=lambda _required: False,
    )
    runner = make_runner(monkeypatch, job, adapter)
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda *_args, **_kwargs: None,
    )

    result = runner.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert result.error == "This user does not have the required AI access."
    assert prepare_calls == []


# @features deferred-jobs
# @dimensions reauthorization
@pytest.mark.unit
def test_runner_rechecks_ai_access_before_apply(monkeypatch):
    class RevokedBeforeApplyAdapter(DeferredJobAdapter):
        job_type = DeferredJobType.AUTOFILL
        required_ai_access = AI.CREATE

        def __init__(self):
            self.prepared = 0
            self.applied = 0

        def prepare(self, _context):
            self.prepared += 1
            return {"prepared": True}

        def apply(self, _context):
            self.applied += 1
            return {"applied": True}

    class RevokingActor:
        urlsafe_key = "actor-key"

        def __init__(self):
            self.checks = 0

        def access(self, required):
            assert required is AI.CREATE
            self.checks += 1
            return self.checks == 1

    job = RunnerJob()
    job.actor = RevokingActor()
    adapter = RevokedBeforeApplyAdapter()
    runner = make_runner(monkeypatch, job, adapter)
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda *_args, **_kwargs: None,
    )

    result = runner.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert result.error == "This user does not have the required AI access."
    assert adapter.prepared == 1
    assert adapter.applied == 0
    assert job.actor.checks == 2


# @features deferred-jobs
# @dimensions checkpoint recovery
def test_runner_checkpoints_before_apply_and_resumes_without_prepare(monkeypatch):
    job = RunnerJob()
    adapter = RecordingAdapter()
    registry = make_runner(monkeypatch, job, adapter)

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.COMPLETE
    assert adapter.calls == [
        "load",
        "authorize",
        "prepare",
        "load",
        "authorize",
        "inspect",
        "apply",
    ]
    assert job.checkpoint == {"prepared": True}
    assert job.result == {"applied": True}
    assert job.status == DeferredJobStatus.SUCCEEDED.value

    resumed_job = RunnerJob(checkpoint={"prepared": True})
    resumed_adapter = RecordingAdapter()
    resumed_registry = make_runner(monkeypatch, resumed_job, resumed_adapter)

    resumed_registry.run(resumed_job.urlsafe_key)

    assert "prepare" not in resumed_adapter.calls
    assert resumed_adapter.calls == [
        "load",
        "authorize",
        "load",
        "authorize",
        "inspect",
        "apply",
    ]

    recovered_job = RunnerJob()
    recovered_job.start_completed = False
    recovered_adapter = RecordingAdapter()
    recovered_adapter.started = lambda _context: recovered_adapter.calls.append(
        "started"
    )
    recovered_registry = make_runner(
        monkeypatch,
        recovered_job,
        recovered_adapter,
    )

    recovered_registry.run(recovered_job.urlsafe_key)

    assert recovered_job.start_completed is True
    assert recovered_adapter.calls[:4] == [
        "load",
        "authorize",
        "started",
        "prepare",
    ]

    legacy_job = RunnerJob()
    del legacy_job.start_completed
    legacy_adapter = RecordingAdapter()
    legacy_adapter.started = lambda _context: legacy_adapter.calls.append("started")
    legacy_registry = make_runner(monkeypatch, legacy_job, legacy_adapter)

    legacy_registry.run(legacy_job.urlsafe_key)

    assert "started" not in legacy_adapter.calls


# @pair deferred-jobs:target-fingerprint
# @pair deferred-jobs:no-apply
def test_runner_rejects_changed_target_fingerprint_before_apply(monkeypatch):
    job = RunnerJob(checkpoint={"prepared": True})
    target = SimpleNamespace(fingerprint="new-target-state")
    job.inputs = {"target": target}
    job.authorization["inputs"] = job.inputs
    job.authorization["fingerprints"] = {"target": "original-target-state"}
    adapter = RecordingAdapter()
    adapter.mutation_inputs = ("target",)
    registry = make_runner(monkeypatch, job, adapter)
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda *_args, **_kwargs: None,
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert result.error == "The target changed while this operation was running."
    assert "apply" not in adapter.calls


# @features deferred-jobs
# @dimensions heartbeat deadline cancellation progress provider-boundary tool-boundary blocking-provider lease-loss
def test_execution_control_renews_and_observes_lost_claim(monkeypatch):
    progress = []
    boundary_control = DeferredExecutionControl(
        deadline_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        active_check=lambda: True,
        progress_callback=progress.append,
    )

    boundary_control.before_provider("tool")
    boundary_control.after_provider("tool")
    boundary_control.before_tool("get_entity")
    boundary_control.after_tool("get_entity")

    assert progress[0]["phase"] == "using_tools"
    assert progress[0]["provider_stage"] == "tool"
    assert boundary_control.remaining_seconds > 0

    renewed = threading.Event()
    registry = SimpleNamespace(
        _renew_claim=lambda _job, _token: renewed.set() and False,
    )
    control = DeferredExecutionControl(
        deadline_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        active_check=lambda: True,
        progress_callback=lambda _progress: None,
    )
    monkeypatch.setattr(deferred_control, "DEFERRED_JOB_HEARTBEAT_SECONDS", 0.01)

    with _DeferredLeaseGuard(
        registry,
        SimpleNamespace(),
        "lease-token",
        control,
    ):
        assert renewed.wait(0.5)

    with pytest.raises(
        DeferredJobClaimLostError,
        match="cancelled or superseded",
    ):
        control.ensure_active()

    expired = DeferredExecutionControl(
        deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        active_check=lambda: True,
        progress_callback=lambda _progress: None,
    )
    with pytest.raises(
        DeferredJobDeadlineError,
        match="execution deadline",
    ):
        expired.ensure_active()


# @features deferred-jobs
# @dimensions retry
def test_runner_classifies_wrapped_transient_errors_and_schedules_retry(monkeypatch):
    provider_error = google_exceptions.TooManyRequests("busy")
    wrapped = RuntimeError("provider wrapper")
    wrapped.__cause__ = provider_error
    job = RunnerJob(attempt=1)
    adapter = RecordingAdapter(error=wrapped)
    registry = make_runner(monkeypatch, job, adapter)
    dispatched = []
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda current, *, attempt, delay_seconds=0: dispatched.append(
            (current, attempt, delay_seconds)
        ),
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.RETRY_SCHEDULED
    assert job.status == DeferredJobStatus.RETRY_WAIT.value
    assert job.error["retryable"] is True
    assert dispatched == [(job, 2, 60)]


# @features deferred-jobs
# @dimensions dependency-wait retry provider-attempt-isolation
def test_runner_waits_for_dependency_without_consuming_provider_retry(monkeypatch):
    job = RunnerJob(attempt=2)
    job.parameters = {"_dependency_waits": 1}
    adapter = RecordingAdapter(
        error=DeferredJobDependencyPendingError("summaries are still processing")
    )
    registry = make_runner(monkeypatch, job, adapter)
    dispatched = []
    captured = []
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda current, *, attempt, delay_seconds=0: dispatched.append(
            (current, attempt, delay_seconds)
        ),
    )
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.RETRY_SCHEDULED
    assert job.status == DeferredJobStatus.RETRY_WAIT.value
    assert job.parameters["_dependency_waits"] == 2
    assert job.progress["phase"] == DeferredJobPhase.SUMMARIZING.value
    assert dispatched == [(job, 3, 60)]
    assert captured == []
    assert deferred_retry._provider_retry_attempt(job) == 1


# @features deferred-jobs
# @dimensions dependency-failure terminal no-duplicate-capture
def test_runner_fails_cleanly_when_dependency_failed(monkeypatch):
    error = DeferredJobDependencyFailedError("attached file summary failed")
    job = RunnerJob(attempt=1)
    adapter = RecordingAdapter(error=error)
    registry = make_runner(monkeypatch, job, adapter)
    captured = []
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert result.error == str(error)
    assert job.error["message"] == str(error)
    assert captured == []


# @features deferred-jobs
# @dimensions provider-timeout retry
def test_runner_retries_sdk_timeout(monkeypatch):
    job = RunnerJob(attempt=1)

    class TimeoutAdapter(RecordingAdapter):
        def prepare(self, context):
            raise httpx.ReadTimeout("provider request timed out")

    adapter = TimeoutAdapter()
    registry = make_runner(monkeypatch, job, adapter)
    dispatched = []
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda current, *, attempt, delay_seconds=0: dispatched.append(
            (current, attempt, delay_seconds)
        ),
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.RETRY_SCHEDULED
    assert job.status == DeferredJobStatus.RETRY_WAIT.value
    assert job.error["type"] == "ReadTimeout"
    assert dispatched == [(job, 2, 60)]


# @features deferred-jobs
# @dimensions provider-errors terminal-message
def test_runner_retries_sdk_5xx_and_persists_clean_terminal_message(monkeypatch):
    provider_error = genai_errors.ServerError(
        503,
        {
            "error": {
                "code": 503,
                "message": "upstream detail",
                "status": "UNAVAILABLE",
            }
        },
    )
    job = RunnerJob(attempt=4)
    adapter = RecordingAdapter(error=provider_error)
    registry = make_runner(monkeypatch, job, adapter)

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert result.error == MODEL_BUSY_MESSAGE
    assert job.status == DeferredJobStatus.FAILED.value
    assert job.error["message"] == MODEL_BUSY_MESSAGE


# @features deferred-jobs
# @dimensions quota retry backoff jitter
def test_runner_increases_later_quota_backoff_without_adding_attempts(monkeypatch):
    quota_error = exceptions.AIQuotaError("quota exhausted")
    transient_error = google_exceptions.ServiceUnavailable("unavailable")
    monkeypatch.setattr(deferred_retry.random, "randint", lambda start, end: 0)
    assert [
        deferred_retry._retry_delay(quota_error, attempt) for attempt in range(1, 3)
    ] == [60, 300]
    assert [
        deferred_retry._retry_delay(transient_error, attempt) for attempt in range(1, 4)
    ] == [60, 180, 600]

    wrapped = RuntimeError("provider wrapper")
    wrapped.__cause__ = quota_error
    job = RunnerJob(attempt=2)
    adapter = RecordingAdapter(error=wrapped)
    registry = make_runner(monkeypatch, job, adapter)
    dispatched = []
    monkeypatch.setattr(deferred_retry.random, "randint", lambda start, end: 30)
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda current, *, attempt, delay_seconds=0: dispatched.append(
            (current, attempt, delay_seconds)
        ),
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.RETRY_SCHEDULED
    assert job.progress["phase"] == "retry_wait"
    assert job.progress["delay_seconds"] == 330
    assert job.progress["updated_at"]
    assert dispatched == [(job, 3, 330)]

    terminal_job = RunnerJob(attempt=3)
    terminal_adapter = RecordingAdapter(error=quota_error)
    terminal_registry = make_runner(monkeypatch, terminal_job, terminal_adapter)

    terminal_result = terminal_registry.run(terminal_job.urlsafe_key)

    assert terminal_result.state is DeferredJobRunState.FAILED
    assert terminal_job.status == DeferredJobStatus.FAILED.value
    assert terminal_result.error == MODEL_BUSY_MESSAGE
    assert terminal_job.error["message"] == MODEL_BUSY_MESSAGE


def test_runner_persists_terminal_domain_failure_without_provider_retry(monkeypatch):
    job = RunnerJob(attempt=1)
    error = ValueError("invalid domain input")
    adapter = RecordingAdapter(error=error)
    registry = make_runner(monkeypatch, job, adapter)
    captured = []
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda captured_error, **kwargs: captured.append((captured_error, kwargs)),
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert job.status == DeferredJobStatus.FAILED.value
    assert job.error == {
        "type": "ValueError",
        "message": "invalid domain input",
        "retryable": False,
        "attempt": 1,
        "context": {},
    }
    assert captured == [
        (
            error,
            {
                "context": {
                    "deferred_job": {
                        "id": "job-key",
                        "type": DeferredJobType.AUTOFILL.value,
                        "attempt": 1,
                    }
                },
                "wait_for_delivery": True,
            },
        )
    ]


# @source lagniappe/core/tools/deferred_jobs/runner.py::DeferredJobRunner._finish_terminal_delivery
# @source lagniappe/core/tools/deferred_jobs/adapters/email.py::EmailIngestAdapter
# @pair deferred-jobs:failure-only-notification
def test_email_ingest_notification_is_created_only_for_failure(monkeypatch):
    registry = DeferredJobService()
    adapter = email_adapters.EmailIngestAdapter()
    actor = SimpleNamespace(urlsafe_key="email-actor")
    report_parent = TestEntities.get(
        "USER",
        {"name": "Email report owner", "hash": "email-report-owner"},
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Ask: Received email",
            "tool": "ask",
            "parent": report_parent,
        },
    )
    created = []
    saved = []

    def create_notification(data):
        created.append(data)
        return SimpleNamespace(**data)

    monkeypatch.setattr(Entities.NOTIFICATION, "create", create_notification)
    monkeypatch.setattr(Entities, "save", lambda *entities: saved.extend(entities))

    def finish(status, error=None):
        job = SimpleNamespace(
            status=status,
            delivery={
                "cleanup": True,
                "notification": False,
                "external_email": True,
            },
            error={"message": str(error)} if error else {},
            lease_token=None,
            notification=None,
        )
        context = SimpleNamespace(
            actor=actor,
            job=job,
            notification=None,
            parameters={},
            checkpoint={},
            input=lambda name: report if name == "report" else None,
        )
        registry._finish_terminal_delivery(
            job,
            adapter,
            context=context,
            error=error,
        )
        return job, context

    assert adapter.notification_policy == "failure"
    succeeded_job, succeeded_context = finish(DeferredJobStatus.SUCCEEDED.value)
    assert succeeded_context.notification is None
    assert succeeded_job.notification is None
    assert succeeded_job.delivery["notification"] is True
    assert created == []

    failure = RuntimeError("provider unavailable")
    failed_job, failed_context = finish(DeferredJobStatus.FAILED.value, failure)
    assert failed_context.notification is failed_job.notification
    assert failed_context.notification.body == (
        "Email submission failed. provider unavailable"
    )
    assert failed_context.notification.target is report
    assert failed_context.notification.pending is False
    assert failed_context.notification in saved
    assert failed_job.delivery["notification"] is True


# @pair deferred-jobs:cancellation
def test_runner_treats_deleted_active_job_as_cancellation(monkeypatch):
    error = ValueError("stale domain write")
    job = RunnerJob(attempt=1)
    adapter = RecordingAdapter(error=error)
    registry = make_runner(monkeypatch, job, adapter)
    captured = []
    monkeypatch.setattr(registry, "_claim_active", lambda *_args: False)
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert result.error == "Deferred job was cancelled or superseded."
    assert job.status == DeferredJobStatus.RUNNING.value
    assert captured == []
