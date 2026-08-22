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
    DEFERRED_JOB_PAYLOAD_LIMIT_BYTES,
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
from lagniappe.core.properties import (
    deferred_job_dispatch,
    deferred_job_lifecycle,
    deferred_job_lock,
    deferred_job_request,
)
from lagniappe.core.tools import database, task_queue
from lagniappe.core.tools.deferred_jobs import locks as deferred_locks
from lagniappe.core.tools.ai.prompt import Prompt
from lagniappe.core.tools.ai import observability
from lagniappe.core.tools.database import deferred_jobs as deferred_database
from lagniappe.core.tools.database import notifications as notification_database
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
# @dimensions persisted-schema property-ownership json-encoding index-exclusion
def test_deferred_job_property_split_preserves_persisted_schema():
    job = Entities.DEFERRED_JOB(testing=True)
    registry = job.properties._registry
    expected = {
        "actor": deferred_job_request.Actor,
        "notification": deferred_job_request.Notification,
        "job_type": deferred_job_request.JobType,
        "status": deferred_job_lifecycle.Status,
        "job_version": deferred_job_request.Version,
        "idempotency_key": deferred_job_request.IdempotencyKey,
        "request_fingerprint": deferred_job_request.RequestFingerprint,
        "dispatch_state": deferred_job_dispatch.DispatchState,
        "task_identity": deferred_job_dispatch.TaskIdentity,
        "dispatched_at": deferred_job_dispatch.DispatchedAt,
        "deadline_at": deferred_job_dispatch.DeadlineAt,
        "status_revision": deferred_job_lifecycle.StatusRevision,
        "start_completed": deferred_job_request.StartCompleted,
        "telemetry_id": deferred_job_request.TelemetryId,
        "authorization": deferred_job_request.Authorization,
        "inputs": deferred_job_request.Inputs,
        "parameters": deferred_job_request.Parameters,
        "client": deferred_job_request.Client,
        "attempt": deferred_job_dispatch.Attempt,
        "lease_token": deferred_job_dispatch.LeaseToken,
        "lease_expires": deferred_job_dispatch.LeaseExpires,
        "next_attempt_at": deferred_job_dispatch.NextAttemptAt,
        "progress": deferred_job_lifecycle.Progress,
        "checkpoint": deferred_job_lifecycle.Checkpoint,
        "result": deferred_job_lifecycle.Result,
        "error": deferred_job_lifecycle.Error,
        "delivery": deferred_job_lifecycle.Delivery,
    }
    assert {name: registry[name] for name in expected} == expected

    job.inputs = {}
    job.client = {"destination": "info:PageInfo"}
    job.dispatch_state = "pending"
    assert job.db == {
        "inputs": "{}",
        "client": '{"destination": "info:PageInfo"}',
        "dispatch_state": "pending",
    }
    assert job.entity_kind == "job"
    assert job.exclude_from_index == frozenset(
        {
            "authorization",
            "inputs",
            "parameters",
            "client",
            "progress",
            "checkpoint",
            "result",
            "error",
            "delivery",
            "idempotency_key",
            "request_fingerprint",
            "lease_token",
            "task_identity",
            "telemetry_id",
            "start_completed",
        }
    )

    lock = Entities.DEFERRED_JOB_LOCK(testing=True)
    lock_registry = lock.properties._registry
    assert {
        name: lock_registry[name]
        for name in ("target", "operation", "idempotency_key", "scope")
    } == {
        "target": deferred_job_lock.Target,
        "operation": deferred_job_lock.Operation,
        "idempotency_key": deferred_job_lock.IdempotencyKey,
        "scope": deferred_job_lock.Scope,
    }
    assert lock.entity_kind == "job_lock"
    assert lock.exclude_from_index == frozenset(
        {"target", "operation", "idempotency_key", "scope"}
    )


# @pair deferred-jobs:request-identity
# @pair deferred-jobs:input-serialization
# @pair deferred-jobs:payload-limit
def test_deferred_job_request_properties_own_identity_and_payload_validation(
    monkeypatch,
):
    spec = SimpleNamespace(
        job_type=DeferredJobType.REPORT_ASK,
        actor=SimpleNamespace(urlsafe_key="actor-key"),
    )
    monkeypatch.setattr(
        deferred_job_request.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex="nonce"),
    )
    assert deferred_job_request.IdempotencyKey.generate(spec) == hashlib.sha256(
        b"report-ask:actor-key:nonce"
    ).hexdigest()

    entity = SimpleNamespace(
        urlsafe_key="entity-key",
        entity_kind="page",
    )
    assert deferred_job_request.Inputs.serialize(
        {
            "entity": entity,
            "reference": {"kind": "file", "id": "file-key", "extra": True},
            "optional": None,
        }
    ) == {
        "entity": {"kind": "page", "id": "entity-key"},
        "reference": {"kind": "file", "id": "file-key"},
        "optional": None,
    }
    with pytest.raises(TypeError, match="must be an entity reference"):
        deferred_job_request.Inputs.serialize({"invalid": "private payload"})

    assert deferred_job_request.validate_payload(inputs={"entity": "small"}) > 0
    with pytest.raises(exceptions.ValidationError, match="750 KiB"):
        deferred_job_request.validate_payload(
            parameters={"value": "x" * DEFERRED_JOB_PAYLOAD_LIMIT_BYTES}
        )


# @pair deferred-jobs:task-identity
# @pair deferred-jobs:feedback-identity
def test_deferred_job_task_identity_is_deterministic_and_bounded():
    job = SimpleNamespace(idempotency_key="stable-operation")
    digest = hashlib.sha256(b"stable-operation").hexdigest()[:32]

    assert TaskIdentity.create(job, 3) == f"job-{digest}-a3"
    assert TaskIdentity.create(
        job,
        3,
        suffix="Reconcile_42 !",
    ) == f"job-{digest}-a3-reconcile42"
    assert TaskIdentity.feedback(job) == f"job-{digest}-feedback"


# @pair deferred-jobs:lock-identity
# @pair deferred-jobs:browser-projection
def test_deferred_job_lock_properties_own_identity_and_projection():
    target = SimpleNamespace(urlsafe_key="target-key")
    expected = hashlib.sha256(b"form-autofill:target-key").hexdigest()
    assert deferred_job_lock.Scope.identifier(target) == expected
    assert deferred_job_lock.Scope.identifier(None) is None

    lock = SimpleNamespace(scope=deferred_job_lock.Scope.AUTOFILL_FORM)
    job = SimpleNamespace(urlsafe_key="job-key", status_revision=4)
    assert deferred_job_lock.Operation.descriptor(lock, job) == {
        "locked": True,
        "scope": "form-autofill",
        "operation": "job-key",
        "revision": 4,
    }


# @pair deferred-jobs:timestamp-normalization
# @pair deferred-jobs:elapsed-time
def test_deferred_job_lifecycle_normalizes_timestamps_and_elapsed_time():
    now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
    naive = datetime(2026, 8, 22, 11, 58)

    assert deferred_job_lifecycle.datetime_value(naive) == naive.replace(
        tzinfo=timezone.utc
    )
    assert deferred_job_lifecycle.datetime_value("2026-08-22T11:58:00Z") == (
        naive.replace(tzinfo=timezone.utc)
    )
    assert deferred_job_lifecycle.datetime_value("not-a-date") is None
    assert deferred_job_lifecycle.elapsed_seconds(naive, now) == 120
    assert deferred_job_lifecycle.elapsed_seconds(now + timedelta(seconds=1), now) == 0
    assert deferred_job_lifecycle.elapsed_seconds(None, now) == 0
from lagniappe.core.tools.deferred_jobs.adapters import autofill as autofill_adapters



# @pairs deferred-jobs:user-write-isolation deferred-jobs:revision deferred-jobs:transaction
# @source lagniappe/core/tools/database/utility.py::claim_deferred_job
# @source lagniappe/core/tools/database/utility.py::update_claimed_deferred_job
def test_deferred_job_status_transactions_do_not_write_actor(monkeypatch):
    class JobKey:
        def __init__(self, parent):
            self.parent = parent

    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    actor_key = object()
    job_key = JobKey(actor_key)
    actor = KeyedEntity(
        actor_key,
        type="user",
        marker="unchanged",
    )
    job = KeyedEntity(
        job_key,
        type="job",
        status="queued",
        status_revision=1,
        attempt=0,
    )
    datastore = KeyedDatastore(actor, job)
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(deferred_database, "_deferred_job_key", lambda value: value)

    claimed = deferred_database.claim_deferred_job(
        job_key,
        "lease-one",
        now + timedelta(minutes=15),
        now,
    )
    assert claimed["claimed"] is True

    assert deferred_database.update_claimed_deferred_job(
        job_key,
        "lease-one",
        {"status_revision": 3, "progress": {"phase": "generating"}},
        now,
    )

    assert deferred_database.update_claimed_deferred_job(
        job_key,
        "lease-one",
        {"lease_expires": now + timedelta(minutes=15)},
        now,
    )

    terminal = deferred_database.update_claimed_deferred_job(
        job_key,
        "lease-one",
        {"status": "succeeded", "dispatch_state": "complete"},
        now,
        include_scheduler_control=True,
    )
    assert terminal["updated"] is True
    assert terminal["scheduler_control"]["active_jobs"] == 0
    assert actor["marker"] == "unchanged"
    assert all(entity is not actor for entity in datastore.saved)




# @features deferred-jobs
# @dimensions lease claim duplicate-delivery checkpoint compare-and-set
def test_deferred_job_claim_and_checkpoint_are_compare_and_set(monkeypatch):
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    entity = {"status": "queued", "attempt": 0}
    datastore = FakeDatastore(entity)
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(deferred_database, "_deferred_job_key", lambda _value: "job")

    claimed = deferred_database.claim_deferred_job(
        "job",
        "lease-one",
        now + timedelta(minutes=15),
        now,
    )

    assert claimed["claimed"] is True
    assert entity["status"] == "running"
    assert entity["attempt"] == 1
    assert entity["lease_token"] == "lease-one"

    duplicate = deferred_database.claim_deferred_job(
        "job",
        "lease-two",
        now + timedelta(minutes=15),
        now + timedelta(seconds=1),
    )
    assert duplicate["claimed"] is False
    assert duplicate["reason"] == "active"

    assert (
        deferred_database.update_claimed_deferred_job(
            "job",
            "wrong-lease",
            {"checkpoint": {"prepared": True}},
            now,
        )
        is False
    )
    assert deferred_database.update_claimed_deferred_job(
        "job",
        "lease-one",
        {"checkpoint": {"prepared": True}, "next_attempt_at": None},
        now,
    )
    assert entity["checkpoint"] == {"prepared": True}
    assert "next_attempt_at" not in entity




# @features deferred-jobs
# @dimensions transaction-contention retry
def test_deferred_job_transactions_retry_aborted_contention(monkeypatch):
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    sleeps = []
    monkeypatch.setattr(database_utility.time, "sleep", sleeps.append)
    monkeypatch.setattr(deferred_database, "_deferred_job_key", lambda _value: "job")
    monkeypatch.setattr(
        deferred_database,
        "_update_deferred_job_scheduler_tracking",
        lambda *_args, **_kwargs: None,
    )

    claim_datastore = ContendedDatastore(
        {"status": "queued", "attempt": 0},
        aborted_attempts=2,
    )
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=claim_datastore),
    )
    claimed = deferred_database.claim_deferred_job(
        "job",
        "lease-one",
        now + timedelta(minutes=15),
        now,
    )

    assert claimed["claimed"] is True
    assert claim_datastore.attempts == 3
    assert claim_datastore.entity["attempt"] == 1
    assert sleeps == [0.05, 0.1]

    update_datastore = ContendedDatastore(
        {"status": "running", "lease_token": "lease-one"},
        aborted_attempts=1,
    )
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=update_datastore),
    )
    assert deferred_database.update_claimed_deferred_job(
        "job",
        "lease-one",
        {"checkpoint": {"prepared": True}},
        now,
    )

    assert update_datastore.attempts == 2
    assert update_datastore.entity["checkpoint"] == {"prepared": True}
    assert sleeps == [0.05, 0.1, 0.05]

    exhausted_datastore = ContendedDatastore(
        {"status": "queued", "attempt": 0},
        aborted_attempts=4,
    )
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=exhausted_datastore),
    )
    with pytest.raises(google_exceptions.Aborted, match="transaction contention"):
        deferred_database.claim_deferred_job(
            "job",
            "lease-one",
            now + timedelta(minutes=15),
            now,
        )

    assert exhausted_datastore.attempts == 4
    assert exhausted_datastore.entity["attempt"] == 0
    assert sleeps[-3:] == [0.05, 0.1, 0.2]




# @pair deferred-jobs:start
# @pair deferred-jobs:get-or-create
# @pair deferred-jobs:transactional-start
# @pair deferred-jobs:notification
# @pair deferred-jobs:idempotency
# @pair notifications:aggregate-count
def test_deferred_job_create_is_transactionally_idempotent(monkeypatch):
    datastore = FakeDatastore(None)
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(deferred_database, "_deferred_job_key", lambda _value: "job")
    job = SimpleNamespace(
        key="job",
        db={"status": "queued"},
        properties=None,
        exclude_from_index=frozenset(),
    )
    notification_owner = SimpleNamespace(urlsafe_key="notification-owner")
    notification = SimpleNamespace(
        key="notification",
        db={"pending": True},
        parent=notification_owner,
        notification_type="ordinary",
        properties=None,
        exclude_from_index=frozenset(),
    )
    aggregate_repairs = []
    aggregate_mutations = []
    monkeypatch.setattr(
        notification_database,
        "ensure_notification_aggregate",
        lambda owner: aggregate_repairs.append(owner),
    )
    monkeypatch.setattr(
        notification_database,
        "mutate_notification_aggregate",
        lambda transaction, owner, **changes: aggregate_mutations.append(
            (transaction, owner, changes)
        ),
    )

    created = deferred_database.create_deferred_job_if_absent(job, notification)

    assert created["created"] is True
    assert aggregate_repairs == [notification_owner]
    assert aggregate_mutations == [
        (
            datastore.transaction_instance,
            notification_owner,
            {"ordinary_delta": 1},
        )
    ]
    assert datastore.transaction_instance.saved[1:] == [
        {"status": "queued"},
        {"pending": True},
    ]
    control = dict(datastore.transaction_instance.saved[0])
    assert control.pop("modified").tzinfo is not None
    assert control == {
        "schema_version": 2,
        "tracked_jobs": ["job"],
        "active_jobs": 1,
        "desired_state": "enabled",
        "generation": 1,
    }
    assert created["scheduler_control"]["tracked_jobs"] == ["job"]

    datastore.transaction_instance.entity = {"status": "running"}
    duplicate = deferred_database.create_deferred_job_if_absent(job, notification)
    assert duplicate == {
        "created": False,
        "reason": "existing",
        "entity": {"status": "running"},
    }
    assert aggregate_repairs == [notification_owner, notification_owner]
    assert len(aggregate_mutations) == 1
    assert len(datastore.transaction_instance.saved) == 3




# @features deferred-jobs
# @dimensions form-lock transactional-start collision
# @pair deferred-jobs:form-lock
# @pair ai:autofill
def test_autofill_start_acquires_one_target_lock(monkeypatch):
    datastore = KeyedDatastore()
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(
        deferred_database,
        "_deferred_job_key",
        lambda value: getattr(value, "key", value),
    )
    monkeypatch.setattr(
        autofill_adapters,
        "deferred_job_lock_key",
        lambda _target: "target-form-lock",
    )

    class LockFactory:
        @classmethod
        def create(cls, data):
            return SimpleNamespace(
                key=data["key"],
                db=KeyedEntity(
                    data["key"],
                    **{k: v for k, v in data.items() if k != "key"},
                ),
                properties=None,
                exclude_from_index=frozenset(),
            )

    monkeypatch.setattr(autofill_adapters.Entities, "DEFERRED_JOB_LOCK", LockFactory)
    target = SimpleNamespace(urlsafe_key="target-key")
    adapter = autofill_adapters.AutofillAdapter()

    def make_job(key):
        return SimpleNamespace(
            key=key,
            urlsafe_key=key,
            idempotency_key=f"idempotency-{key}",
            db=KeyedEntity(key, status="queued"),
            properties=None,
            exclude_from_index=frozenset(),
        )

    first_job = make_job("job-one")
    first_lock = adapter.start_lock(
        SimpleNamespace(inputs={"target": target}, parameters={}),
        first_job,
    )
    first = deferred_database.create_deferred_job_if_absent(
        first_job,
        lock=first_lock,
    )

    assert first["created"] is True
    assert first_lock.db == {
        "scope": AUTOFILL_FORM_LOCK_SCOPE,
        "target": "target-key",
        "operation": "job-one",
        "idempotency_key": "idempotency-job-one",
    }

    second_job = make_job("job-two")
    second_lock = adapter.start_lock(
        SimpleNamespace(inputs={"target": target}, parameters={}),
        second_job,
    )
    second = deferred_database.create_deferred_job_if_absent(
        second_job,
        lock=second_lock,
    )

    assert second["created"] is False
    assert second["reason"] == "locked"
    assert second["entity"] is first_job.db
    assert "job-two" not in datastore.entities
    assert datastore.entities["target-form-lock"]["operation"] == "job-one"




# @features deferred-jobs
# @dimensions form-lock compare-and-delete stale-worker
# @pair deferred-jobs:form-lock
# @pair deferred-jobs:compare-and-set
def test_autofill_lock_cleanup_is_compare_and_delete(monkeypatch):
    lock = KeyedEntity("target-form-lock", operation="job-two")
    datastore = KeyedDatastore(lock)
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(
        deferred_database,
        "_deferred_job_key",
        lambda value: getattr(value, "key", value),
    )

    assert not deferred_database.release_deferred_job_lock(
        "target-form-lock",
        "job-one",
    )
    assert datastore.entities["target-form-lock"] is lock
    assert datastore.deleted == []

    assert deferred_database.release_deferred_job_lock(
        "target-form-lock",
        "job-two",
    )
    assert "target-form-lock" not in datastore.entities
    assert datastore.deleted == ["target-form-lock"]




# @pair deferred-jobs:form-lock
# @pair deferred-jobs:deterministic-key
# @pair deferred-jobs:stale-cleanup
def test_deferred_job_lock_resolution_is_target_scoped(monkeypatch):
    named_keys = []
    monkeypatch.setattr(
        database,
        "create_named_key",
        lambda kind, identifier: named_keys.append((kind, identifier))
        or f"lock:{identifier}",
    )
    target = SimpleNamespace(urlsafe_key="target-key")

    key = deferred_job_lock_key(target)

    expected = hashlib.sha256(b"form-autofill:target-key").hexdigest()
    assert key == f"lock:{expected}"
    assert named_keys == [("job_lock", expected)]

    class Lock:
        def __init__(self, key, target_key, operation):
            self.key = key
            self.target = target_key
            self.operation = operation
            self.scope = AUTOFILL_FORM_LOCK_SCOPE

    class Job:
        def __init__(self, key, status):
            self.urlsafe_key = key
            self.status = status
            self.status_revision = 3

    active_lock = Lock("lock:active", "target-active", "job-active")
    terminal_lock = Lock("lock:terminal", "target-terminal", "job-terminal")
    active_job = Job("job-active", "queued")
    terminal_job = Job("job-terminal", "succeeded")
    monkeypatch.setattr(deferred_locks.Entities, "DEFERRED_JOB_LOCK", Lock)
    monkeypatch.setattr(deferred_locks.Entities, "DEFERRED_JOB", Job)
    monkeypatch.setattr(
        deferred_locks,
        "deferred_job_lock_key",
        lambda current, scope=AUTOFILL_FORM_LOCK_SCOPE: (
            f"lock:{getattr(current, 'urlsafe_key', current)}"
        ),
    )

    def fetch(*identifiers, request):
        del request
        if all(str(identifier).startswith("lock:") for identifier in identifiers):
            return [active_lock, terminal_lock]
        return [active_job, terminal_job]

    released = []
    monkeypatch.setattr(deferred_locks.Entities, "fetch", fetch)
    monkeypatch.setattr(
        database,
        "release_deferred_job_lock",
        lambda *values: released.append(values),
    )
    targets = [
        SimpleNamespace(urlsafe_key="target-active"),
        SimpleNamespace(urlsafe_key="target-terminal"),
    ]

    resolved = deferred_job_lock_descriptors(targets)

    assert resolved == {"target-active": (active_lock, active_job)}
    assert released == [("lock:terminal", "job-terminal")]




# @features deferred-jobs
# @dimensions form-lock browser-projection
def test_deferred_job_lock_descriptor_is_browser_safe(monkeypatch):
    lock = SimpleNamespace(scope="form-autofill")
    job = SimpleNamespace(urlsafe_key="job-key", status_revision=7)
    monkeypatch.setattr(
        deferred_locks,
        "active_deferred_job_lock",
        lambda target, scope=AUTOFILL_FORM_LOCK_SCOPE: (lock, job),
    )

    assert deferred_job_lock_descriptor("target-key") == {
        "locked": True,
        "scope": "form-autofill",
        "operation": "job-key",
        "revision": 7,
    }




# @features deferred-jobs
# @dimensions reconciliation dispatch compare-and-set lease grace maximum-age worker-race
def test_deferred_job_recovery_claim_is_compare_and_set(monkeypatch):
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    entity = {
        "status": "queued",
        "status_revision": 4,
        "dispatch_state": "pending",
        "created": now - timedelta(minutes=5),
    }
    datastore = FakeDatastore(entity)
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(deferred_database, "_deferred_job_key", lambda _value: "job")

    claimed = deferred_database.claim_deferred_job_recovery(
        "job",
        4,
        now,
        grace_seconds=120,
        max_age_seconds=3 * 60 * 60,
        stale_updates={"status": "failed"},
    )

    assert claimed["claimed"] is True
    assert claimed["action"] == "redispatch"
    assert entity["dispatch_state"] == "dispatching"
    assert entity["status_revision"] == 5

    duplicate = deferred_database.claim_deferred_job_recovery(
        "job",
        4,
        now,
        grace_seconds=120,
        max_age_seconds=3 * 60 * 60,
        stale_updates={"status": "failed"},
    )
    assert duplicate["claimed"] is False
    assert duplicate["reason"] == "revision"

    assert deferred_database.update_deferred_job_recovery_dispatch(
        "job",
        5,
        {"dispatch_state": "dispatched", "task_identity": "task-1"},
        now,
    )
    entity["dispatch_state"] = "claimed"
    assert not deferred_database.update_deferred_job_recovery_dispatch(
        "job",
        5,
        {"dispatch_state": "dispatched"},
        now,
    )

    recent = {
        "status": "queued",
        "status_revision": 1,
        "dispatch_state": "pending",
        "created": now,
        "modified": now,
    }
    datastore.transaction_instance.entity = recent
    not_due = deferred_database.claim_deferred_job_recovery(
        "job",
        1,
        now + timedelta(seconds=30),
        grace_seconds=120,
        max_age_seconds=3 * 60 * 60,
        stale_updates={"status": "failed"},
    )
    assert not_due["claimed"] is False
    assert not_due["reason"] == "not-due"
    assert recent["dispatch_state"] == "pending"




# @features deferred-jobs
# @dimensions cancellation tombstone lease compare-and-set terminal-race
def test_deferred_job_terminal_transition_revokes_the_active_lease(monkeypatch):
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    entity = {
        "status": "running",
        "lease_token": "worker-one",
        "lease_expires": now + timedelta(minutes=5),
        "status_revision": 7,
    }
    datastore = FakeDatastore(entity)
    monkeypatch.setattr(
        deferred_database,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(deferred_database, "_deferred_job_key", lambda _value: "job")

    result = deferred_database.transition_active_deferred_job(
        "job",
        {
            "status": "cancelled",
            "lease_token": None,
            "lease_expires": None,
        },
        now,
    )

    assert result["transitioned"] is True
    assert entity["status"] == "cancelled"
    assert "lease_token" not in entity
    assert "lease_expires" not in entity
    assert entity["status_revision"] == 8

    terminal = deferred_database.transition_active_deferred_job(
        "job",
        {"status": "failed"},
        now,
    )
    assert terminal["transitioned"] is False
    assert terminal["reason"] == "terminal"
    assert entity["status"] == "cancelled"




# @features deferred-jobs
# @dimensions operation-fingerprint client-contract routing-identity
def test_request_fingerprint_tracks_the_complete_client_contract():
    values = {
        "job_type": "autofill",
        "actor": "actor-key",
        "authorization": {"policy": "autofill"},
        "inputs": {"page": {"key": "page-key"}},
        "parameters": {"form": "form-key"},
    }
    first = RequestFingerprint.create(
        **values,
        client={"destination": "page:Form"},
    )
    extended = RequestFingerprint.create(
        **values,
        client={"destination": "page:Form", "key": "page-key"},
    )
    rerouted = RequestFingerprint.create(
        **values,
        client={"destination": "page:Other"},
    )

    assert first != extended
    assert first != rerouted




# @features deferred-jobs
# @dimensions status stale-state privacy timing
def test_status_projection_is_bounded_and_marks_stale_work():
    now = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
    job = SimpleNamespace(
        urlsafe_key="opaque-operation",
        job_type="ask_report",
        status=DeferredJobStatus.RUNNING.value,
        progress={
            "phase": "generating",
            "updated_at": (now - timedelta(minutes=3)).isoformat(),
        },
        attempt=2,
        created=now - timedelta(minutes=10),
        modified=now - timedelta(minutes=3),
        next_attempt_at=None,
        status_revision=7,
        dispatch_state="claimed",
        client={
            "source_widget": "AskToolReport",
            "destination": "tools:ToolReportList",
        },
        checkpoint={"prompt": "private authored content"},
        error={},
    )

    status = deferred_job_lifecycle.status_projection(job, now=now)

    assert status["stale"] is True
    assert status["recovering"] is True
    assert status["elapsed_seconds"] == 600
    assert status["phase_elapsed_seconds"] == 180
    assert "checkpoint" not in status
    assert "private authored content" not in json.dumps(status)




# @pair deferred-jobs:diagnostics
# @pair deferred-jobs:privacy
def test_admin_projection_exposes_diagnostics_without_payload_content():
    now = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
    job = SimpleNamespace(
        urlsafe_key="opaque-operation",
        job_type="report-organize",
        job_version=2,
        status=DeferredJobStatus.RUNNING.value,
        progress={
            "phase": "using_tools",
            "updated_at": (now - timedelta(minutes=3)).isoformat(),
            "private": "private progress content",
        },
        checkpoint={
            "schema_version": 1,
            "stage": "summaries_ready",
            "proposal": "private proposal content",
        },
        inputs={
            "report": {"kind": "report", "id": "report-key"},
        },
        parameters={"feedback": "private feedback content"},
        delivery={
            "cleanup": True,
            "notification": False,
            "input_missing": True,
        },
        error={
            "type": "TimeoutError",
            "message": "Provider request timed out.",
            "retryable": True,
            "attempt": 1,
            "context": {"secret": "private error context"},
        },
        actor=SimpleNamespace(name="Owner", email="owner@example.test"),
        attempt=1,
        created=now - timedelta(minutes=10),
        modified=now - timedelta(minutes=3),
        dispatched_at=now - timedelta(minutes=9),
        deadline_at=now + timedelta(minutes=14),
        lease_expires=now + timedelta(minutes=2),
        next_attempt_at=None,
        status_revision=7,
        dispatch_state="claimed",
        start_completed=True,
        telemetry_id="telemetry-id",
        client={
            "source_widget": "CreateToolReport",
            "destination": "tools:ToolReportList",
        },
    )

    projection = deferred_job_lifecycle.admin_projection(job, now=now)

    assert projection["key"] == "opaque-operation"
    assert projection["input_refs"] == {
        "report": {"kind": "report", "id": "report-key"}
    }
    assert projection["checkpoint_state"] == {
        "schema_version": 1,
        "stage": "summaries_ready",
    }
    assert projection["progress"] == {
        "phase": "using_tools",
        "updated_at": (now - timedelta(minutes=3)).isoformat(),
    }
    assert projection["last_error"] == {
        "type": "TimeoutError",
        "retryable": True,
        "attempt": 1,
    }
    assert projection["delivery_state"] == {
        "cleanup": True,
        "notification": False,
        "input_missing": True,
    }
    serialized = json.dumps(projection)
    assert "private feedback content" not in serialized
    assert "private proposal content" not in serialized
    assert "private progress content" not in serialized
    assert "private error context" not in serialized
    assert "Provider request timed out." not in serialized
