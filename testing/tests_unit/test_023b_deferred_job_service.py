"""Focused deferred-job behavior tests."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
from types import SimpleNamespace

from google.api_core import exceptions as google_exceptions
from google.genai import errors as genai_errors
import httpx
import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobRunState,
    DeferredJobSpec,
    DeferredJobStatus,
    DeferredJobType,
    FetchReason,
)
from lagniappe.core.entities import Entities
from lagniappe.core.mixins.submitter import SubmitterMixin
from lagniappe.core.properties.deferred_job_dispatch import TaskIdentity
from lagniappe.core.properties.deferred_job_request import RequestFingerprint
from lagniappe.core.properties import deferred_job_lifecycle
from lagniappe.core.tools import database, notification_service, task_queue
from lagniappe.core.tools.deferred_jobs import dispatch as deferred_dispatch
from lagniappe.core.tools.deferred_jobs import service as deferred_service
from lagniappe.core.tools.ai.prompt import Prompt
from lagniappe.core.tools.ai import observability
from lagniappe.core.tools.database import deferred_jobs as deferred_database
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.deferred_jobs import common as deferred_common
from lagniappe.core.tools.deferred_jobs import retry as deferred_retry
from lagniappe.core.tools.deferred_jobs.adapters.base import DeferredJobAdapter
from lagniappe.core.tools.deferred_jobs.context import DeferredJobContext
from lagniappe.core.tools.deferred_jobs.control import (
    DeferredExecutionControl,
    _DeferredLeaseGuard,
)
from lagniappe.core.tools.deferred_jobs.dispatch import DeferredJobDispatch
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobClaimLostError,
    DeferredJobDeadlineError,
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
    DeferredJobDriftError,
    DeferredJobInfrastructureError,
    DeferredJobLockedError,
)
from lagniappe.core.tools.deferred_jobs.locks import (
    AUTOFILL_FORM_LOCK_SCOPE,
    active_deferred_job_lock,
    deferred_job_lock_descriptor,
    deferred_job_lock_descriptors,
    deferred_job_lock_key,
)
from lagniappe.core.tools.deferred_jobs.retry import MODEL_BUSY_MESSAGE
from lagniappe.core.tools.deferred_jobs.runner import MISSING_INPUT_MESSAGE
from lagniappe.core.tools.deferred_jobs.service import DeferredJobService, DeferredJobs
from lagniappe.core.tools.deferred_jobs.adapters import site as site_adapters
from lagniappe.core.tools.files import extract as file_extract
from testing.utility.deferred_job_fakes import (
    ContendedDatastore,
    FakeDatastore,
    FakeTasksClient,
    KeyedDatastore,
    KeyedEntity,
    RecordingAdapter,
    RunnerJob,
    fake_start_entities,
    operation_projection,
    runner,
    terminal_delivery_runner,
)
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit



# @features deferred-jobs
# @dimensions cancellation deterministic-task-id
def test_cancel_deletes_tasks_and_persists_a_tombstone(
    monkeypatch,
    operation_projection,
):
    registry = DeferredJobService()
    job = RunnerJob(attempt=2)
    job.status = DeferredJobStatus.RETRY_WAIT.value
    job.notification = SimpleNamespace(name="pending notification")
    deleted_tasks = []
    saved = []
    monkeypatch.setattr(
        task_queue,
        "CONFIG",
        SimpleNamespace(
            GOOGLE_CLOUD_PROJECT="project",
            RESOURCE_REGION="region",
            TASK_QUEUE_NAME="jobs",
        ),
    )
    monkeypatch.setattr(
        task_queue,
        "delete_task",
        lambda name: deleted_tasks.append(name) or True,
    )

    def transition(key, updates, _now):
        assert key == job.key
        current = job
        for name, value in updates.items():
            if name in {"client", "progress"}:
                value = json.loads(value)
            setattr(current, name, value)
        current.status_revision = int(getattr(current, "status_revision", 0) or 0) + 1
        return {"transitioned": True, "entity": current}

    monkeypatch.setattr(
        database,
        "transition_active_deferred_job",
        transition,
    )
    monkeypatch.setattr(Entities, "DEFERRED_JOB", lambda raw: raw)
    monkeypatch.setattr(Entities, "fetch_one", lambda value, request: value)
    monkeypatch.setattr(Entities, "save", lambda *entities: saved.extend(entities))

    assert registry.cancel(job) is True

    task_id = TaskIdentity.create(job, 3)
    feedback_task_id = TaskIdentity.feedback(job)
    assert deleted_tasks == [
        f"projects/project/locations/region/queues/jobs/tasks/{task_id}",
        f"projects/project/locations/region/queues/jobs/tasks/{feedback_task_id}",
    ]
    assert job.status == DeferredJobStatus.CANCELLED.value
    assert job.progress["phase"] == "cancelled"
    assert job.notification.pending is False
    assert saved == [job, job.notification]
    assert operation_projection == [job]




# @pairs deferred-jobs:redis-projection deferred-jobs:cache-failure-isolation
# @source lagniappe/core/tools/deferred_jobs/common.py::_publish_operation_projection
def test_operation_projection_failure_is_nonfatal(monkeypatch):
    job = SimpleNamespace(urlsafe_key="durable-job")
    captured = []
    monkeypatch.setattr(
        deferred_common.cache,
        "update_operation_projection",
        lambda *_jobs: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda error, **kwargs: captured.append((error, kwargs)),
    )

    assert (
        deferred_common._publish_operation_projection(
            job,
            operation="status_projection",
        )
        is None
    )
    assert str(captured[0][0]) == "redis unavailable"
    assert captured[0][1]["level"] == "warning"
    assert captured[0][1]["context"] == {
        "deferred_job": {
            "id": "durable-job",
            "operation": "status_projection",
        }
    }




# @pairs deferred-jobs:terminal-delivery cloud-scheduler:datastore-read-isolation
# @source lagniappe/core/tools/deferred_jobs/runner.py::DeferredJobRunner._release
def test_terminal_release_reuses_committed_scheduler_control(monkeypatch):
    registry = DeferredJobService()
    job = RunnerJob()
    job.status = DeferredJobStatus.SUCCEEDED.value
    control = {"generation": 9, "desired_state": "paused"}
    persisted = []
    synchronized = []
    monkeypatch.setattr(
        registry,
        "_persist_claimed",
        lambda current, lease, **values: (
            persisted.append((current, lease, values)) or control
        ),
    )
    monkeypatch.setattr(
        registry,
        "_sync_reconciler",
        lambda **options: synchronized.append(options),
    )

    registry._release(job, "lease-one")

    assert persisted == [
        (
            job,
            "lease-one",
            {
                "lease_token": None,
                "lease_expires": None,
                "next_attempt_at": None,
                "dispatch_state": "complete",
                "deadline_at": None,
            },
        )
    ]
    assert synchronized == [{"control": control}]




# @features deferred-jobs notifications
# @dimensions long-running feedback terminal-safety
def test_long_running_feedback_updates_pending_notification(monkeypatch):
    registry = DeferredJobService()
    registry.adapter_registry._defaults_loaded = True
    adapter = RecordingAdapter()
    registry.register(adapter)
    job = RunnerJob()
    job.notification = SimpleNamespace(body="Working...", pending=True)
    job.client = {}
    saved = []

    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda key, request: job if key == job.urlsafe_key else None,
    )
    monkeypatch.setattr(Entities, "save", lambda *entities: saved.extend(entities))
    assert registry.feedback(job.urlsafe_key) is True
    assert job.notification.body == adapter.active_message
    assert job.notification.pending is True
    assert saved == [job.notification]

    job.status = DeferredJobStatus.SUCCEEDED.value
    saved.clear()

    assert registry.feedback(job.urlsafe_key) is False
    assert saved == []




# @features deferred-jobs notifications
# @dimensions long-running feedback scheduling
def test_long_running_feedback_dispatch_is_delayed_and_deterministic(monkeypatch):
    registry = DeferredJobService()
    registry.adapter_registry._defaults_loaded = True
    registry.register(RecordingAdapter())
    job = RunnerJob()
    job.notification = SimpleNamespace(body="Working...", pending=True)
    created = []

    monkeypatch.setattr(
        deferred_dispatch,
        "CONFIG",
        SimpleNamespace(production=True),
    )
    monkeypatch.setattr(
        deferred_dispatch,
        "url_for",
        lambda endpoint, _external: f"https://example.test/{endpoint}",
    )
    monkeypatch.setattr(
        task_queue,
        "create_task",
        lambda *args, **kwargs: created.append((args, kwargs)) or "feedback-task",
    )

    assert registry.dispatch_feedback(job) == "feedback-task"
    assert created == [
        (
            (
                "https://example.test/process.deferred_job_feedback",
                {"job_key": job.urlsafe_key},
                120,
            ),
            {"task_id": TaskIdentity.feedback(job)},
        )
    ]




# @pair deferred-jobs:dispatch
# @pair deferred-jobs:disabled-queue
# @pair deferred-jobs:task-identity
def test_production_dispatch_rejects_disabled_task_queue(monkeypatch):
    registry = DeferredJobService()
    job = RunnerJob()
    job.job_type = DeferredJobType.SITE_EXPORT.value
    monkeypatch.setattr(
        deferred_dispatch,
        "CONFIG",
        SimpleNamespace(production=True),
    )
    monkeypatch.setattr(
        task_queue,
        "CONFIG",
        SimpleNamespace(TASK_QUEUE_ENABLED=False, production=True),
    )
    monkeypatch.setattr(
        deferred_dispatch,
        "url_for",
        lambda endpoint, _external: f"https://example.test/{endpoint}",
    )

    with pytest.raises(
        DeferredJobInfrastructureError,
        match="did not return a task identity",
    ):
        registry.dispatch(job, attempt=1)




# @pair deferred-jobs:transient-dispatch
# @pair deferred-jobs:no-apply
# @pair export:intent-preservation
# @pair notifications:pending-state
def test_start_retains_site_export_intent_after_provider_enqueue_failure(monkeypatch):
    actor, state = fake_start_entities(monkeypatch)
    registry = DeferredJobService()
    adapter = registry.adapter(DeferredJobType.SITE_EXPORT)
    provider_or_apply_calls = []
    export_updates = []

    monkeypatch.setattr(
        deferred_service,
        "CONFIG",
        SimpleNamespace(production=True),
    )
    monkeypatch.setattr(
        deferred_dispatch,
        "CONFIG",
        SimpleNamespace(production=True),
    )
    monkeypatch.setattr(
        deferred_dispatch,
        "url_for",
        lambda endpoint, _external: f"https://example.test/{endpoint}",
    )

    def enqueue_failure(*_args, **_kwargs):
        raise google_exceptions.ServiceUnavailable("queue provider unavailable")

    monkeypatch.setattr(task_queue, "create_task", enqueue_failure)
    monkeypatch.setattr(
        adapter,
        "prepare",
        lambda _context: provider_or_apply_calls.append("prepare") or {},
    )
    monkeypatch.setattr(
        adapter,
        "apply",
        lambda _context: provider_or_apply_calls.append("apply") or {},
    )
    monkeypatch.setattr(
        site_adapters.database,
        "update_site_export",
        lambda export_id, updates: export_updates.append((export_id, updates))
        or updates,
    )

    returned_job, returned_notification = registry.start(
        DeferredJobSpec(
            job_type=DeferredJobType.SITE_EXPORT,
            actor=actor,
            inputs={},
            parameters={"export_id": "export-1"},
            notification_body="Building HTML export archive...",
        )
    )

    job = state["job"]
    notification = state["notification"]
    assert returned_job is job
    assert returned_notification is notification
    assert job.status == DeferredJobStatus.QUEUED.value
    assert job.dispatch_state == "pending"
    assert job.error["type"] == "ServiceUnavailable"
    assert job.error["attempt"] == 0
    assert job.error["retryable"] is True
    assert job.start_completed is True
    assert notification.pending is True
    assert notification.body == "Building HTML export archive..."
    assert export_updates == []
    assert provider_or_apply_calls == []
    assert len(state["saved"]) == 3




# @features deferred-jobs
# @dimensions dispatch-worker-race compare-and-set
def test_start_dispatch_marker_does_not_overwrite_a_fast_worker(monkeypatch):
    actor, state = fake_start_entities(monkeypatch)
    registry = DeferredJobService()
    adapter = RecordingAdapter()
    registry.adapter_registry._defaults_loaded = True
    registry.register(adapter)

    def fast_dispatch(job, **_kwargs):
        job.status = DeferredJobStatus.RUNNING.value
        job.dispatch_state = "claimed"
        job.status_revision += 1
        return "task-created-before-worker-claim"

    monkeypatch.setattr(registry, "dispatch", fast_dispatch)

    returned_job, _notification = registry.start(
        DeferredJobSpec(
            job_type=DeferredJobType.AUTOFILL,
            actor=actor,
            idempotency_key="fast-worker-operation",
            inputs={},
        )
    )

    assert returned_job is state["job"]
    assert returned_job.status == DeferredJobStatus.RUNNING.value
    assert returned_job.dispatch_state == "claimed"
    assert getattr(returned_job, "task_identity", None) is None




# @pair deferred-jobs:start
# @pair deferred-jobs:operation-fingerprint
# @pair deferred-jobs:mismatch
def test_start_rejects_operation_id_reuse_for_different_request(monkeypatch):
    actor, state = fake_start_entities(monkeypatch)
    existing = SimpleNamespace(
        request_fingerprint="different-request",
        notification=SimpleNamespace(),
    )
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda *_args, **_kwargs: existing,
    )
    registry = DeferredJobService()

    with pytest.raises(
        exceptions.ValidationError,
        match="reused for a different request",
    ):
        registry.start(
            DeferredJobSpec(
                job_type=DeferredJobType.AUTOFILL,
                actor=actor,
                idempotency_key="browser-operation-id",
                inputs={},
                parameters={"value": "new"},
            )
        )

    assert "job" not in state




# @pair deferred-jobs:retention
# @pair deferred-jobs:terminal-delivery
def test_delete_terminal_jobs_preserves_active_and_incomplete_delivery(monkeypatch):
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)

    class Record(dict):
        def __init__(self, key, **values):
            super().__init__(**values)
            self.key = key

    records = [
        Record(
            "completed",
            created=now - timedelta(days=8),
            status=DeferredJobStatus.SUCCEEDED.value,
            dispatch_state="complete",
        ),
        Record(
            "replaced",
            created=now - timedelta(days=9),
            status=DeferredJobStatus.SUPERSEDED.value,
            dispatch_state=DeferredJobStatus.SUPERSEDED.value,
        ),
        Record(
            "delivery-pending",
            created=now - timedelta(days=10),
            status=DeferredJobStatus.FAILED.value,
            dispatch_state="delivery_pending",
        ),
        Record(
            "active",
            created=now - timedelta(days=11),
            status=DeferredJobStatus.RUNNING.value,
            dispatch_state="claimed",
        ),
        Record(
            "recent",
            created=now - timedelta(days=1),
            status=DeferredJobStatus.CANCELLED.value,
            dispatch_state=DeferredJobStatus.CANCELLED.value,
        ),
    ]

    class Query:
        def __init__(self):
            self.filters = []
            self.order = []

        def add_filter(self, *, filter):
            self.filters.append(filter)

        def fetch(self):
            return iter(records)

    query = Query()
    deleted_batches = []
    datastore = SimpleNamespace(
        query=lambda **_kwargs: query,
        delete_multi=lambda keys: deleted_batches.append(list(keys)),
    )
    monkeypatch.setattr(
        deferred_service,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )

    deleted = DeferredJobService().delete_terminal(
        before=now - timedelta(days=7),
        batch_size=1,
    )

    assert deleted == 2
    assert deleted_batches == [["completed"], ["replaced"]]
    assert query.order == ["created"]
    assert len(query.filters) == 1




# @features deferred-jobs
# @dimensions task-payload deterministic-task-id dispatch-deadline
def test_cloud_task_dispatch_uses_key_payload_stable_id_and_deadline(monkeypatch):
    client = FakeTasksClient()
    monkeypatch.setattr(
        task_queue,
        "CONFIG",
        SimpleNamespace(
            TASK_QUEUE_ENABLED=True,
            production=True,
            google_credentials="credentials",
            GOOGLE_CLOUD_PROJECT="project",
            RESOURCE_REGION="region",
            TASK_QUEUE_NAME="jobs",
            INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL="oidc-caller@example.test",
        ),
    )
    monkeypatch.setattr(
        task_queue.tasks_v2,
        "CloudTasksClient",
        lambda credentials: client,
    )

    name = task_queue.create_task(
        "https://example.test/process/jobs",
        {"job_key": "job-key"},
        task_id="job-stable-a1",
        dispatch_deadline_seconds=1800,
    )

    task = client.request["task"]
    assert name.endswith("/tasks/job-stable-a1")
    assert task["name"] == name
    assert task["dispatch_deadline"].seconds == 1800
    assert task["http_request"]["body"] == b'{"job_key": "job-key"}'
    assert task["http_request"]["oidc_token"] == {
        "service_account_email": "oidc-caller@example.test"
    }
