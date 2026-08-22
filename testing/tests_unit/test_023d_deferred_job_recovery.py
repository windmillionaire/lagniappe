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
from lagniappe.core.tools import database
from lagniappe.core.tools.services import task_queue
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
# @dimensions reconciliation redispatch compare-and-set deterministic-task-id
def test_reconciler_redispatches_one_cas_claimed_stale_job(monkeypatch):
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    job = RunnerJob(attempt=2)
    job.status = DeferredJobStatus.RETRY_WAIT.value
    job.status_revision = 4
    job.dispatch_state = "pending"
    job.created = now - timedelta(minutes=10)
    registry = DeferredJobService()
    monkeypatch.setattr(registry, "_reconcile_candidates", lambda *, limit: [job])

    def claim(key, revision, claimed_at, **kwargs):
        assert (key, revision, claimed_at) == (job.key, 4, now)
        assert kwargs["grace_seconds"] > 0
        job.status_revision = 5
        job.dispatch_state = "dispatching"
        return {"claimed": True, "action": "redispatch", "entity": job}

    monkeypatch.setattr(
        database,
        "claim_deferred_job_recovery",
        claim,
    )
    monkeypatch.setattr(Entities, "DEFERRED_JOB", lambda raw: raw)
    monkeypatch.setattr(Entities, "fetch_one", lambda value, request: value)
    dispatched = []
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda current, *, attempt, task_suffix: (
            dispatched.append((current, attempt, task_suffix)) or "recovered-task"
        ),
    )
    finalized = []
    monkeypatch.setattr(
        database,
        "update_deferred_job_recovery_dispatch",
        lambda *args: finalized.append(args) or True,
    )

    result = registry.reconcile(now=now)

    assert result == {
        "examined": 1,
        "redispatched": 1,
        "failed": 0,
        "delivered": 0,
        "errors": 0,
    }
    assert dispatched == [(job, 3, "reconcile-5")]
    assert finalized == [
        (
            job.key,
            5,
            {"dispatch_state": "dispatched", "task_identity": "recovered-task"},
            now,
        )
    ]


# @pair deferred-jobs:reconciliation
# @pair deferred-jobs:terminal-delivery
# @pair deferred-jobs:grace
# @pair notifications:terminal-delivery
def test_reconciler_resumes_stale_terminal_delivery_after_grace(monkeypatch):
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    job = RunnerJob()
    job.status = DeferredJobStatus.SUCCEEDED.value
    job.dispatch_state = "delivery_pending"
    job.modified = now - timedelta(minutes=3)
    registry = DeferredJobService()
    monkeypatch.setattr(registry, "_reconcile_candidates", lambda *, limit: [job])
    delivered = []
    monkeypatch.setattr(
        registry,
        "_finish_stale_delivery",
        lambda current: delivered.append(current),
    )

    result = registry.reconcile(now=now)

    assert result["delivered"] == 1
    assert delivered == [job]

    job.modified = now - timedelta(seconds=30)
    delivered.clear()
    result = registry.reconcile(now=now)
    assert result["delivered"] == 0
    assert delivered == []


# @pair deferred-jobs:orphaned-input
def test_reconciler_completes_terminal_delivery_when_input_was_deleted(
    monkeypatch,
):
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    job = RunnerJob()
    job.job_type = DeferredJobType.REPORT_ORGANIZE.value
    job.status = DeferredJobStatus.FAILED.value
    job.dispatch_state = "delivery_pending"
    job.modified = now - timedelta(minutes=3)
    job.lease_token = None
    job.inputs = {
        "report": {"kind": "report", "id": "deleted-report-key"},
    }
    job.delivery = {
        "failure": False,
        "cleanup": False,
        "notification": False,
    }
    job.error = {"message": "This operation could not finish after automatic recovery."}
    job.notification = SimpleNamespace(body="Creating report...", pending=True)
    job.client = {
        "source_widget": "CreateToolReport",
        "destination": "tools:ToolReportList",
    }
    registry = DeferredJobService()
    captured = []

    def persist(current, _token, **values):
        for name, value in values.items():
            setattr(current, name, value)

    monkeypatch.setattr(
        registry,
        "_reconcile_candidates",
        lambda *, limit: [job] if job.dispatch_state == "delivery_pending" else [],
    )
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(Entities, "save", lambda *_entities: None)
    monkeypatch.setattr(
        registry,
        "_persist_claimed",
        persist,
    )
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )
    first = registry.reconcile(now=now)

    assert first == {
        "examined": 1,
        "redispatched": 0,
        "failed": 0,
        "delivered": 1,
        "errors": 0,
    }
    assert job.dispatch_state == "complete"
    assert job.delivery == {
        "failure": True,
        "cleanup": True,
        "notification": True,
        "input_missing": True,
    }
    assert job.notification.pending is False
    assert job.notification.body == MISSING_INPUT_MESSAGE
    assert job.client == {
        "source_widget": "CreateToolReport",
        "destination": "tools:ToolReportList",
    }
    assert captured == []

    assert registry.reconcile(now=now + timedelta(minutes=5)) == {
        "examined": 0,
        "redispatched": 0,
        "failed": 0,
        "delivered": 0,
        "errors": 0,
    }
