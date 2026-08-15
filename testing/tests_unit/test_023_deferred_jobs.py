"""Durable deferred-job envelope and runner behavior."""

import copy
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
from lagniappe.core.tools import deferred_jobs
from lagniappe.core.tools import deferred_job_adapters
from lagniappe.core.tools import notification_service
from lagniappe.core.tools import task_queue
from lagniappe.core.tools.ai.prompt import Prompt
from lagniappe.core.tools.ai import observability
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.files import extract as file_extract


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def operation_projection(monkeypatch):
    """Keep deferred-job unit tests isolated from the Redis provider."""
    published = []
    monkeypatch.setattr(
        deferred_jobs.cache,
        "update_operation_projection",
        lambda *jobs: published.extend(jobs),
    )
    return published


class FakeTransaction:
    def __init__(self, entity):
        self.entity = entity
        self.saved = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _key):
        return self.entity

    def put(self, entity):
        self.saved.append(dict(entity))


class FakeDatastore:
    def __init__(self, entity):
        self.transaction_instance = FakeTransaction(entity)

    def transaction(self):
        return self.transaction_instance

    def key(self, *parts):
        return tuple(parts)

    def get(self, _key, transaction=None):
        assert transaction is self.transaction_instance
        if isinstance(_key, tuple) and _key[-1] == "deferred-jobs-control":
            return None
        return self.transaction_instance.entity


class KeyedEntity(dict):
    def __init__(self, key, **values):
        super().__init__(values)
        self.key = key


class KeyedTransaction:
    def __init__(self, datastore):
        self.datastore = datastore

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def put(self, entity):
        self.datastore.saved.append(entity)
        self.datastore.entities[entity.key] = entity

    def delete(self, key):
        self.datastore.deleted.append(key)
        self.datastore.entities.pop(key, None)


class KeyedDatastore:
    def __init__(self, *entities):
        self.entities = {entity.key: entity for entity in entities}
        self.deleted = []
        self.saved = []

    def transaction(self):
        return KeyedTransaction(self)

    def key(self, *parts):
        return tuple(parts)

    def get(self, key, transaction=None):
        assert isinstance(transaction, KeyedTransaction)
        return self.entities.get(key)


class ContendedTransaction:
    def __init__(self, datastore):
        self.datastore = datastore
        self.entity = copy.deepcopy(datastore.entity)
        self.saved = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.datastore.attempts += 1
        if self.datastore.attempts <= self.datastore.aborted_attempts:
            raise google_exceptions.Aborted("transaction contention")
        if self.saved is not None:
            self.datastore.entity = self.saved
        return False

    def put(self, entity):
        self.saved = copy.deepcopy(entity)


class ContendedDatastore:
    def __init__(self, entity, aborted_attempts):
        self.entity = entity
        self.aborted_attempts = aborted_attempts
        self.attempts = 0

    def transaction(self):
        return ContendedTransaction(self)

    def get(self, _key, transaction=None):
        return transaction.entity


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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(database_utility, "_deferred_job_key", lambda value: value)

    claimed = database_utility.claim_deferred_job(
        job_key,
        "lease-one",
        now + timedelta(minutes=15),
        now,
    )
    assert claimed["claimed"] is True

    assert database_utility.update_claimed_deferred_job(
        job_key,
        "lease-one",
        {"status_revision": 3, "progress": {"phase": "generating"}},
        now,
    )

    assert database_utility.update_claimed_deferred_job(
        job_key,
        "lease-one",
        {"lease_expires": now + timedelta(minutes=15)},
        now,
    )

    terminal = database_utility.update_claimed_deferred_job(
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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(database_utility, "_deferred_job_key", lambda _value: "job")

    claimed = database_utility.claim_deferred_job(
        "job",
        "lease-one",
        now + timedelta(minutes=15),
        now,
    )

    assert claimed["claimed"] is True
    assert entity["status"] == "running"
    assert entity["attempt"] == 1
    assert entity["lease_token"] == "lease-one"

    duplicate = database_utility.claim_deferred_job(
        "job",
        "lease-two",
        now + timedelta(minutes=15),
        now + timedelta(seconds=1),
    )
    assert duplicate["claimed"] is False
    assert duplicate["reason"] == "active"

    assert (
        database_utility.update_claimed_deferred_job(
            "job",
            "wrong-lease",
            {"checkpoint": {"prepared": True}},
            now,
        )
        is False
    )
    assert database_utility.update_claimed_deferred_job(
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
    monkeypatch.setattr(database_utility, "_deferred_job_key", lambda _value: "job")
    monkeypatch.setattr(
        database_utility,
        "_update_deferred_job_scheduler_tracking",
        lambda *_args, **_kwargs: None,
    )

    claim_datastore = ContendedDatastore(
        {"status": "queued", "attempt": 0},
        aborted_attempts=2,
    )
    monkeypatch.setattr(
        database_utility,
        "DATA",
        SimpleNamespace(datastore=claim_datastore),
    )
    claimed = database_utility.claim_deferred_job(
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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=update_datastore),
    )
    assert database_utility.update_claimed_deferred_job(
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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=exhausted_datastore),
    )
    with pytest.raises(google_exceptions.Aborted, match="transaction contention"):
        database_utility.claim_deferred_job(
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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(database_utility, "_deferred_job_key", lambda _value: "job")
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
        notification_service,
        "ensure_notification_aggregate",
        lambda owner: aggregate_repairs.append(owner),
    )
    monkeypatch.setattr(
        notification_service,
        "mutate_aggregate_in_transaction",
        lambda transaction, owner, **changes: aggregate_mutations.append(
            (transaction, owner, changes)
        ),
    )

    created = database_utility.create_deferred_job_if_absent(job, notification)

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
    duplicate = database_utility.create_deferred_job_if_absent(job, notification)
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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(
        database_utility,
        "_deferred_job_key",
        lambda value: getattr(value, "key", value),
    )
    monkeypatch.setattr(
        deferred_job_adapters,
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

    monkeypatch.setattr(deferred_job_adapters.Entities, "DEFERRED_JOB_LOCK", LockFactory)
    target = SimpleNamespace(urlsafe_key="target-key")
    adapter = deferred_job_adapters.AutofillAdapter()

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
    first = database_utility.create_deferred_job_if_absent(
        first_job,
        lock=first_lock,
    )

    assert first["created"] is True
    assert first_lock.db == {
        "scope": deferred_jobs.AUTOFILL_FORM_LOCK_SCOPE,
        "target": "target-key",
        "operation": "job-one",
        "idempotency_key": "idempotency-job-one",
    }

    second_job = make_job("job-two")
    second_lock = adapter.start_lock(
        SimpleNamespace(inputs={"target": target}, parameters={}),
        second_job,
    )
    second = database_utility.create_deferred_job_if_absent(
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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(
        database_utility,
        "_deferred_job_key",
        lambda value: getattr(value, "key", value),
    )

    assert not database_utility.release_deferred_job_lock(
        "target-form-lock",
        "job-one",
    )
    assert datastore.entities["target-form-lock"] is lock
    assert datastore.deleted == []

    assert database_utility.release_deferred_job_lock(
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
        deferred_jobs.database,
        "create_named_key",
        lambda kind, identifier: named_keys.append((kind, identifier))
        or f"lock:{identifier}",
    )
    target = SimpleNamespace(urlsafe_key="target-key")

    key = deferred_jobs.deferred_job_lock_key(target)

    expected = hashlib.sha256(b"form-autofill:target-key").hexdigest()
    assert key == f"lock:{expected}"
    assert named_keys == [("job_lock", expected)]

    class Lock:
        def __init__(self, key, target_key, operation):
            self.key = key
            self.target = target_key
            self.operation = operation
            self.scope = deferred_jobs.AUTOFILL_FORM_LOCK_SCOPE

    class Job:
        def __init__(self, key, status):
            self.urlsafe_key = key
            self.status = status
            self.status_revision = 3

    active_lock = Lock("lock:active", "target-active", "job-active")
    terminal_lock = Lock("lock:terminal", "target-terminal", "job-terminal")
    active_job = Job("job-active", "queued")
    terminal_job = Job("job-terminal", "succeeded")
    monkeypatch.setattr(deferred_jobs.Entities, "DEFERRED_JOB_LOCK", Lock)
    monkeypatch.setattr(deferred_jobs.Entities, "DEFERRED_JOB", Job)
    monkeypatch.setattr(
        deferred_jobs,
        "deferred_job_lock_key",
        lambda current, scope=deferred_jobs.AUTOFILL_FORM_LOCK_SCOPE: (
            f"lock:{getattr(current, 'urlsafe_key', current)}"
        ),
    )

    def fetch(*identifiers, request):
        del request
        if all(str(identifier).startswith("lock:") for identifier in identifiers):
            return [active_lock, terminal_lock]
        return [active_job, terminal_job]

    released = []
    monkeypatch.setattr(deferred_jobs.Entities, "fetch", fetch)
    monkeypatch.setattr(
        deferred_jobs.database,
        "release_deferred_job_lock",
        lambda *values: released.append(values),
    )
    targets = [
        SimpleNamespace(urlsafe_key="target-active"),
        SimpleNamespace(urlsafe_key="target-terminal"),
    ]

    resolved = deferred_jobs.deferred_job_lock_descriptors(targets)

    assert resolved == {"target-active": (active_lock, active_job)}
    assert released == [("lock:terminal", "job-terminal")]


# @features deferred-jobs
# @dimensions form-lock browser-projection
def test_deferred_job_lock_descriptor_is_browser_safe(monkeypatch):
    lock = SimpleNamespace(scope="form-autofill")
    job = SimpleNamespace(urlsafe_key="job-key", status_revision=7)
    monkeypatch.setattr(
        deferred_jobs,
        "active_deferred_job_lock",
        lambda target, scope=deferred_jobs.AUTOFILL_FORM_LOCK_SCOPE: (lock, job),
    )

    assert deferred_jobs.deferred_job_lock_descriptor("target-key") == {
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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(database_utility, "_deferred_job_key", lambda _value: "job")

    claimed = database_utility.claim_deferred_job_recovery(
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

    duplicate = database_utility.claim_deferred_job_recovery(
        "job",
        4,
        now,
        grace_seconds=120,
        max_age_seconds=3 * 60 * 60,
        stale_updates={"status": "failed"},
    )
    assert duplicate["claimed"] is False
    assert duplicate["reason"] == "revision"

    assert database_utility.update_deferred_job_recovery_dispatch(
        "job",
        5,
        {"dispatch_state": "dispatched", "task_identity": "task-1"},
        now,
    )
    entity["dispatch_state"] = "claimed"
    assert not database_utility.update_deferred_job_recovery_dispatch(
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
    not_due = database_utility.claim_deferred_job_recovery(
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
        database_utility,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(database_utility, "_deferred_job_key", lambda _value: "job")

    result = database_utility.transition_active_deferred_job(
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

    terminal = database_utility.transition_active_deferred_job(
        "job",
        {"status": "failed"},
        now,
    )
    assert terminal["transitioned"] is False
    assert terminal["reason"] == "terminal"
    assert entity["status"] == "cancelled"


# @pairs deferred-jobs:checkpoint file:extraction file:text-asset
def test_file_extract_adapter_checkpoints_and_applies_text_asset(monkeypatch):
    adapter = deferred_job_adapters.FileExtractAdapter()
    process = SimpleNamespace(
        complete=True,
        error=None,
        section={"status": "Text extracted successfully.", "complete": True},
    )
    prepared_file = SimpleNamespace(assets={})

    def extract(file, *, raise_errors):
        assert file is prepared_file
        assert raise_errors is True
        file.assets["text"] = {
            "type": "text",
            "visibility": "private",
            "path": "files/example/text.txt",
            "fingerprint": "text-fingerprint",
        }
        return process

    monkeypatch.setattr(deferred_job_adapters.files, "ocr_file", extract)
    phases = []
    checkpoint = adapter.prepare(
        SimpleNamespace(
            set_phase=phases.append,
            input=lambda name: prepared_file if name == "file" else None,
        )
    )

    assert phases == [deferred_jobs.DeferredJobPhase.PREPARING_INPUTS]
    assert checkpoint["process"] == process.section
    assert checkpoint["text_asset"] == prepared_file.assets["text"]

    saved = []
    applied_extract = SimpleNamespace(section={})
    applied_file = SimpleNamespace(
        assets={
            "file": {
                "type": "file",
                "visibility": "private",
                "path": "files/example/original.png",
            }
        },
        db={},
        properties=SimpleNamespace(extract=applied_extract),
        save=lambda: saved.append(True),
        urlsafe_key="file-key",
    )
    result = adapter.apply(
        SimpleNamespace(
            checkpoint=checkpoint,
            ensure_active=lambda: None,
            input=lambda name: applied_file if name == "file" else None,
        )
    )

    assert result == {"file_key": "file-key", "complete": True}
    assert json.loads(applied_file.db["assets"])["text"] == checkpoint["text_asset"]
    assert applied_extract.section == checkpoint["process"]
    assert saved == [True]


# @features deferred-jobs file
# @dimensions authorization validation original-asset fingerprint metadata-isolation
def test_file_adapter_drift_tracks_the_original_asset():
    adapter = deferred_job_adapters.FileSummarizeAdapter()
    original = SimpleNamespace(fingerprint="original-asset")
    file = SimpleNamespace(
        entity_kind="file",
        fingerprint="file-metadata-before",
        get_asset=lambda name: original if name == "file" else None,
        urlsafe_key="file-key",
    )
    actor = SimpleNamespace(urlsafe_key="actor-key")
    authorization = adapter.authorization(
        DeferredJobSpec(
            job_type=DeferredJobType.FILE_SUMMARIZE,
            actor=actor,
            inputs={"file": file},
        )
    )
    context = SimpleNamespace(
        job=SimpleNamespace(authorization=authorization),
        input=lambda name: file if name == "file" else None,
    )

    file.fingerprint = "file-metadata-after"
    adapter.validate_apply(context)

    original.fingerprint = "replacement-asset"
    with pytest.raises(
        deferred_jobs.DeferredJobDriftError,
        match="original file changed",
    ):
        adapter.validate_apply(context)


# @features deferred-jobs file
# @dimensions terminal follow-up extraction idempotency summary-first
@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_file_summary_terminal_cleanup_starts_extraction_once(monkeypatch, status):
    adapter = deferred_job_adapters.FileSummarizeAdapter()
    file = Entities.FILE(testing=True)
    actor = SimpleNamespace(urlsafe_key="actor-key")
    parameters = {"extract_after_summary": True}
    context = SimpleNamespace(
        actor=actor,
        parameters=parameters,
        job=SimpleNamespace(
            status=status,
            idempotency_key="summary-operation",
            client={},
        ),
        input=lambda name: file if name == "file" else None,
    )
    starts = []
    monkeypatch.setattr(
        deferred_job_adapters.files,
        "start_file_extraction",
        lambda *args, **kwargs: starts.append((args, kwargs)),
    )

    adapter.cleanup(context, terminal=True)
    adapter.cleanup(context, terminal=True)

    assert len(starts) == 1
    args, kwargs = starts[0]
    assert args == (file,)
    assert kwargs["actor"] is actor
    assert kwargs["delay_seconds"] == 0
    assert kwargs["idempotency_key"].startswith("file-extract-follow-up:")
    assert file.properties.extract.status == "Extracting text..."
    assert parameters == {}


# @features deferred-jobs file
# @dimensions summary expected-failure no-duplicate-capture
def test_file_summary_expected_rejection_is_not_reported_twice(monkeypatch):
    file = SimpleNamespace(
        properties=SimpleNamespace(
            summarize=SimpleNamespace(
                complete=None,
                error="PDF exceeds the AI summary page limit.",
            )
        )
    )
    context = SimpleNamespace(
        input=lambda name: file if name == "file" else None,
        set_phase=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_summary",
        lambda *_args, **_kwargs: file.properties.summarize,
    )

    with pytest.raises(
        deferred_jobs.DeferredJobDependencyFailedError,
        match="page limit",
    ):
        deferred_job_adapters.FileSummarizeAdapter().prepare(context)


# @features deferred-jobs file
# @dimensions follow-up extraction idempotency
def test_start_file_extraction_uses_explicit_actor_and_identity(monkeypatch):
    actor = SimpleNamespace(urlsafe_key="actor-key")
    file = SimpleNamespace(urlsafe_key="file-key")
    started = []
    monkeypatch.setattr(
        deferred_jobs.DeferredJobs,
        "start",
        lambda spec: started.append(spec) or "started",
    )

    result = file_extract.start_file_extraction(
        file,
        actor=actor,
        idempotency_key="follow-up-identity",
        delay_seconds=0,
    )

    assert result == "started"
    assert len(started) == 1
    spec = started[0]
    assert spec.job_type is DeferredJobType.FILE_EXTRACT
    assert spec.actor is actor
    assert spec.inputs == {"file": file}
    assert spec.client == {}
    assert spec.idempotency_key == "follow-up-identity"
    assert spec.delay_seconds == 0


class RunnerJob:
    def __init__(self, *, checkpoint=None, attempt=1):
        self.key = "job-key"
        self.urlsafe_key = "job-key"
        self.job_type = DeferredJobType.AUTOFILL.value
        self.job_version = 1
        self.status = DeferredJobStatus.RUNNING.value
        self.actor = SimpleNamespace(urlsafe_key="actor-key")
        self.notification = None
        self.authorization = {
            "policy": self.job_type,
            "actor": "actor-key",
            "inputs": {},
        }
        self.inputs = {}
        self.parameters = {}
        self.client = {}
        self.attempt = attempt
        self.lease_token = "lease-token"
        self.lease_expires = None
        self.next_attempt_at = None
        self.progress = {}
        self.checkpoint = checkpoint or {}
        self.result = {}
        self.error = {}
        self.delivery = {}
        self.idempotency_key = "deterministic-job-key"
        self.start_completed = True


class RecordingAdapter(deferred_jobs.DeferredJobAdapter):
    job_type = DeferredJobType.AUTOFILL
    required_ai_access = AI.CREATE

    def __init__(self, error=None):
        self.calls = []
        self.error = error
        self.ai_execution_context = None

    def load(self, context):
        self.calls.append("load")
        return context

    def authorize(self, context):
        self.calls.append("authorize")

    def prepare(self, context):
        self.calls.append("prepare")
        self.ai_execution_context = observability._EXECUTION_CONTEXT.get()
        if self.error:
            raise self.error
        return {"prepared": True}

    def inspect(self, context):
        self.calls.append("inspect")
        return DeferredJobInspection.NOT_APPLIED

    def apply(self, context):
        self.calls.append("apply")
        return {"applied": context.checkpoint["prepared"]}


# @pair ai:page-generation
# @pair pages:form-defaults
# @pair pages:no-form
def test_page_generation_apply_uses_direct_fields_and_form_fallbacks(monkeypatch):
    created = []
    saved = []

    class GeneratedPage:
        @classmethod
        def create(cls, data):
            page = cls()
            page.name = data.get("name")
            page.description = data.get("description")
            page.form = data.get("form")
            page.properties = SimpleNamespace(
                document=SimpleNamespace(html=None),
            )
            page.urlsafe_key = f"page-{len(created) + 1}"
            page.submission = None
            created.append(page)
            return page

        def ai_submission(self, submission):
            self.submission = dict(submission)
            self.name = submission.get("name", self.name)
            self.description = submission.get("description", self.description)

    monkeypatch.setattr(deferred_job_adapters.Entities, "PAGE", GeneratedPage)
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        deferred_job_adapters.database.get,
        "datastore_key",
        lambda key: f"datastore:{key}",
    )

    category = SimpleNamespace()
    adapter = deferred_job_adapters.PageGenerationAdapter()

    without_form = SimpleNamespace(
        ensure_active=lambda: None,
        checkpoint={
            "pages": [
                {
                    "key": "plain-key",
                    "page": {
                        "submission": {
                            "name": "Legacy fallback name",
                            "description": "Legacy fallback description",
                        }
                    },
                }
            ]
        },
        input=lambda name: category if name == "category" else None,
    )
    assert adapter.apply(without_form) == {"page_keys": ["page-1"]}
    assert created[0].name == "Legacy fallback name"
    assert created[0].description == "Legacy fallback description"
    assert created[0].submission is None

    form = SimpleNamespace(
        schema=[
            {"id": "name"},
            {"id": "description"},
            {"id": "input-topic"},
        ]
    )
    with_form = SimpleNamespace(
        ensure_active=lambda: None,
        checkpoint={
            "pages": [
                {
                    "key": "formed-key",
                    "page": {
                        "name": "Direct name",
                        "description": "Direct description",
                        "submission": {
                            "name": "Stale form name",
                            "description": "Stale form description",
                            "input-topic": "Preserved topic",
                        },
                    },
                }
            ]
        },
        input=lambda name: {
            "category": category,
            "form": form,
        }.get(name),
    )
    assert adapter.apply(with_form) == {"page_keys": ["page-2"]}
    assert created[1].name == "Direct name"
    assert created[1].description == "Direct description"
    assert created[1].submission == {
        "name": "Direct name",
        "description": "Direct description",
        "input-topic": "Preserved topic",
    }
    assert len(saved) == 2


# @features deferred-jobs
# @dimensions form-revision form-only drift
# @pair deferred-jobs:form-revision
# @pair ai:autofill
def test_autofill_revision_tracks_only_form_apply_state():
    class Target(SubmitterMixin):
        pass

    target = Target()
    target.form = SimpleNamespace(
        urlsafe_key="form-key",
        version="form-version-one",
        schema=[{"id": "field-one"}, {"id": "name"}],
    )
    target.db = {
        "schema_version": "schema-one",
        "default_submission": {"field-one": "default"},
    }
    target.name = "Original name"
    target.description = "Unmirrored description"
    target.properties = SimpleNamespace(
        submission=SimpleNamespace(value={"field-one": "answer"})
    )

    original = target.autofill_revision
    target.unrelated_task_setting = "changed"
    target.description = "Still unmirrored"
    assert target.autofill_revision == original

    target.properties.submission.value = {"field-one": "new answer"}
    submission_revision = target.autofill_revision
    assert submission_revision != original

    target.name = "Renamed"
    assert target.autofill_revision != submission_revision

    target.name = "Original name"
    target.form.version = "form-version-two"
    assert target.autofill_revision != original


# @features deferred-jobs
# @dimensions target-editor status authorization
# @pair deferred-jobs:status
# @pair ai:collaboration
def test_autofill_status_is_visible_to_target_editor(monkeypatch):
    actor = SimpleNamespace(urlsafe_key="editor-key")
    checked = []
    fetches = []

    class Target:
        def allowed(self, action, *, user):
            checked.append((action, user))
            return True

    target = Target()
    monkeypatch.setattr(deferred_job_adapters.Entities, "PAGE", Target)
    monkeypatch.setattr(deferred_job_adapters.Entities, "TASK", type(None))

    def fetch_one(key, request):
        fetches.append(request)
        return target if key == "target-key" else None

    monkeypatch.setattr(deferred_job_adapters.Entities, "fetch_one", fetch_one)
    job = SimpleNamespace(inputs={"target": {"id": "target-key"}})

    assert deferred_job_adapters.AutofillAdapter().can_view_status(job, actor)
    assert len(checked) == 1
    assert checked[0][1] is actor
    assert fetches[0].reason is FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION


# @pairs deferred-jobs:terminal-cleanup deferred-jobs:form-lock
def test_autofill_terminal_cleanup_releases_target_lock(monkeypatch):
    target = SimpleNamespace(urlsafe_key="page-key", deferred_job=None)
    context = SimpleNamespace(
        job=SimpleNamespace(
            parameters={},
            urlsafe_key="job-key",
            inputs={"target": {"id": "page-key"}},
        ),
        parameters={},
        input=lambda name: target if name == "target" else None,
    )
    released = []
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "PAGE",
        type(target),
    )
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "fetch_one",
        lambda key, **_kwargs: target if key == "page-key" else None,
    )
    monkeypatch.setattr(
        deferred_job_adapters,
        "deferred_job_lock_key",
        lambda current: f"lock:{getattr(current, 'urlsafe_key', current)}",
    )
    monkeypatch.setattr(
        deferred_job_adapters.database,
        "release_deferred_job_lock",
        lambda *values: released.append(values),
    )

    adapter = deferred_job_adapters.AutofillAdapter()
    adapter.cleanup(context, terminal=False)
    assert released == []

    adapter.cleanup(context, terminal=True)
    assert released == [("lock:page-key", "job-key")]

    missing_context = SimpleNamespace(
        job=SimpleNamespace(
            parameters={},
            urlsafe_key="missing-job-key",
            inputs={"target": {"id": "deleted-page-key"}},
        ),
        parameters={},
        input=lambda _name: None,
    )
    adapter.cleanup(missing_context, terminal=True)
    assert released[-1] == ("lock:deleted-page-key", "missing-job-key")


# @pairs deferred-jobs:active-operation pages:create-autofill
# @pairs deferred-jobs:terminal-cleanup deferred-jobs:compare-and-delete
def test_autofill_page_operation_reference_is_persisted_and_compare_cleared(
    monkeypatch,
):
    class Page:
        urlsafe_key = "page-key"

        def __init__(self):
            self.deferred_job = None

    page = Page()
    job = SimpleNamespace(
        parameters={"lock_target": True},
        inputs={"target": {"id": page.urlsafe_key}},
        urlsafe_key="job-key",
        idempotency_key="request-key",
        status_revision=2,
    )
    context = SimpleNamespace(
        job=job,
        actor=SimpleNamespace(),
        inputs={"target": page},
        parameters=job.parameters,
        input=lambda name: context.inputs.get(name),
    )
    saved = []
    released = []
    monkeypatch.setattr(deferred_job_adapters.Entities, "PAGE", Page)
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: page,
    )
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "save_root",
        lambda entity, **options: saved.append((entity, options)),
    )
    monkeypatch.setattr(
        deferred_job_adapters,
        "deferred_job_lock_key",
        lambda current: f"lock:{getattr(current, 'urlsafe_key', current)}",
    )
    monkeypatch.setattr(
        deferred_job_adapters.database,
        "release_deferred_job_lock",
        lambda *values: released.append(values),
    )

    adapter = deferred_job_adapters.AutofillAdapter()
    adapter.started(context)

    assert page.deferred_job == {
        "key": "job-key",
        "idempotency_key": "request-key",
        "revision": 2,
    }
    assert saved == [(page, {"property_mask": ("deferred_job",)})]

    page.deferred_job = {"key": "newer-job"}
    adapter.cleanup(context, terminal=True)

    assert page.deferred_job == {"key": "newer-job"}
    assert len(saved) == 1
    assert released == [("lock:page-key", "job-key")]

    page.deferred_job = {"key": "job-key"}
    adapter.cleanup(context, terminal=True)

    assert page.deferred_job is None
    assert saved[-1] == (page, {"property_mask": ("deferred_job",)})


# @features deferred-jobs ai files
# @dimensions autofill summary-dependency pending failed
def test_autofill_prepare_waits_for_attached_file_summaries(monkeypatch):
    adapter = deferred_job_adapters.AutofillAdapter()
    phases = []
    context = SimpleNamespace(
        actor=SimpleNamespace(),
        parameters={},
        input=lambda name: SimpleNamespace() if name == "target" else None,
        set_phase=lambda phase, **details: phases.append((phase, details)),
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "autofill_summary_dependencies",
        lambda *_args: {
            "complete": [SimpleNamespace()],
            "pending": [SimpleNamespace()],
            "failed": [],
        },
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_autofilled_submission",
        lambda _prompt: (_ for _ in ()).throw(
            AssertionError("Gemini must not run before summaries complete")
        ),
    )

    with pytest.raises(
        deferred_jobs.DeferredJobDependencyPendingError,
        match="still processing",
    ):
        adapter.prepare(context)

    assert phases[-1] == (
        DeferredJobPhase.SUMMARIZING,
        {"completed": 1, "total": 2},
    )

    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "autofill_summary_dependencies",
        lambda *_args: {
            "complete": [],
            "pending": [],
            "failed": [SimpleNamespace()],
        },
    )
    with pytest.raises(
        deferred_jobs.DeferredJobDependencyFailedError,
        match="summary failed",
    ):
        adapter.prepare(context)


def _runner(monkeypatch, job, adapter):
    registry = deferred_jobs.DeferredJobRegistry()
    registry._defaults_loaded = True
    registry.register(adapter)
    monkeypatch.setattr(
        deferred_jobs.database,
        "claim_deferred_job",
        lambda *_args: {"claimed": True, "reason": "claimed", "entity": job},
    )
    monkeypatch.setattr(Entities, "DEFERRED_JOB", lambda raw: raw)
    monkeypatch.setattr(Entities, "fetch_one", lambda value, request: value)

    def persist(current, _token, **values):
        for name, value in values.items():
            setattr(current, name, value)

    monkeypatch.setattr(registry, "_persist_claimed", persist)
    monkeypatch.setattr(registry, "_claim_active", lambda *_args: True)
    monkeypatch.setattr(registry, "_heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(registry, "_finish_terminal_delivery", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(registry, "_release", lambda *_args, **_kwargs: None)
    return registry


def _terminal_delivery_runner(monkeypatch, job, adapter, persist=None):
    registry = deferred_jobs.DeferredJobRegistry()
    registry._defaults_loaded = True
    registry.register(adapter)
    claim_count = {"value": 0}

    def claim(*_args):
        claim_count["value"] += 1
        return {
            "claimed": claim_count["value"] == 1,
            "reason": "claimed" if claim_count["value"] == 1 else "terminal",
            "entity": job,
        }

    def persist_values(current, _token, **values):
        for name, value in values.items():
            setattr(current, name, value)

    monkeypatch.setattr(deferred_jobs.database, "claim_deferred_job", claim)
    monkeypatch.setattr(Entities, "DEFERRED_JOB", lambda raw: raw)
    monkeypatch.setattr(Entities, "fetch_one", lambda value, request: value)
    monkeypatch.setattr(Entities, "save", lambda *_entities: None)
    monkeypatch.setattr(
        registry,
        "_persist_claimed",
        persist or persist_values,
    )
    monkeypatch.setattr(registry, "_heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(registry, "_claim_active", lambda *_args: True)
    return registry


# @pair deferred-jobs:preparation-context
# @pair observability:job-type
# @pair observability:attempt
# @pair observability:contract-version
# @pair observability:no-job-key
@pytest.mark.unit
def test_runner_supplies_bounded_ai_observability_context_during_prepare(monkeypatch):
    job = RunnerJob(attempt=3)
    adapter = RecordingAdapter()
    registry = _runner(monkeypatch, job, adapter)

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
    registry = deferred_jobs.DeferredJobRegistry()
    registry._load_default_adapters()
    return tuple(
        sorted(
            (
                job_type
                for job_type, adapter in registry._adapters.items()
                if adapter.required_ai_access is not None
            ),
            key=lambda job_type: job_type.value,
        )
    )


# @pair ai-access:tier-declaration
# @pair deferred-jobs:tier-declaration
@pytest.mark.unit
def test_registered_adapters_declare_required_ai_tiers():
    registry = deferred_jobs.DeferredJobRegistry()
    registry._load_default_adapters()

    expected = {
        DeferredJobType.REPORT_ASK: AI.ASK,
        DeferredJobType.REPORT_ORGANIZE: AI.CREATE,
        DeferredJobType.REPORT_CREATE: AI.CREATE,
        DeferredJobType.REPORT_EXECUTION: AI.CREATE,
        DeferredJobType.AUTOFILL: AI.CREATE,
        DeferredJobType.PAGE_GENERATION: AI.CREATE,
        DeferredJobType.FILE_SUMMARIZE: AI.CREATE,
        DeferredJobType.FILE_EXTRACT: None,
        DeferredJobType.SITE_EXPORT: None,
    }

    assert {
        job_type: registry.adapter(job_type).required_ai_access
        for job_type in expected
    } == expected


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
    registry = deferred_jobs.DeferredJobRegistry()
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
    runner = _runner(monkeypatch, job, adapter)
    monkeypatch.setattr(
        deferred_jobs.exceptions,
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
    class RevokedBeforeApplyAdapter(deferred_jobs.DeferredJobAdapter):
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
    runner = _runner(monkeypatch, job, adapter)
    monkeypatch.setattr(
        deferred_jobs.exceptions,
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
    registry = _runner(monkeypatch, job, adapter)

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
    resumed_registry = _runner(monkeypatch, resumed_job, resumed_adapter)

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
    recovered_registry = _runner(
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
    legacy_registry = _runner(monkeypatch, legacy_job, legacy_adapter)

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
    registry = _runner(monkeypatch, job, adapter)
    monkeypatch.setattr(
        deferred_jobs.exceptions,
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
    boundary_control = deferred_jobs.DeferredExecutionControl(
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
    control = deferred_jobs.DeferredExecutionControl(
        deadline_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        active_check=lambda: True,
        progress_callback=lambda _progress: None,
    )
    monkeypatch.setattr(deferred_jobs, "DEFERRED_JOB_HEARTBEAT_SECONDS", 0.01)

    with deferred_jobs._DeferredLeaseGuard(
        registry,
        SimpleNamespace(),
        "lease-token",
        control,
    ):
        assert renewed.wait(0.5)

    with pytest.raises(
        deferred_jobs.DeferredJobClaimLostError,
        match="cancelled or superseded",
    ):
        control.ensure_active()

    expired = deferred_jobs.DeferredExecutionControl(
        deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        active_check=lambda: True,
        progress_callback=lambda _progress: None,
    )
    with pytest.raises(
        deferred_jobs.DeferredJobDeadlineError,
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
    registry = _runner(monkeypatch, job, adapter)
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
        error=deferred_jobs.DeferredJobDependencyPendingError(
            "summaries are still processing"
        )
    )
    registry = _runner(monkeypatch, job, adapter)
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
        deferred_jobs.exceptions,
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
    assert deferred_jobs._provider_retry_attempt(job) == 1


# @features deferred-jobs
# @dimensions dependency-failure terminal no-duplicate-capture
def test_runner_fails_cleanly_when_dependency_failed(monkeypatch):
    error = deferred_jobs.DeferredJobDependencyFailedError(
        "attached file summary failed"
    )
    job = RunnerJob(attempt=1)
    adapter = RecordingAdapter(error=error)
    registry = _runner(monkeypatch, job, adapter)
    captured = []
    monkeypatch.setattr(
        deferred_jobs.exceptions,
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
    registry = _runner(monkeypatch, job, adapter)
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
    registry = _runner(monkeypatch, job, adapter)

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert result.error == deferred_jobs.MODEL_BUSY_MESSAGE
    assert job.status == DeferredJobStatus.FAILED.value
    assert job.error["message"] == deferred_jobs.MODEL_BUSY_MESSAGE


# @features deferred-jobs
# @dimensions quota retry backoff jitter
def test_runner_increases_later_quota_backoff_without_adding_attempts(monkeypatch):
    quota_error = exceptions.AIQuotaError("quota exhausted")
    transient_error = google_exceptions.ServiceUnavailable("unavailable")
    monkeypatch.setattr(deferred_jobs.random, "randint", lambda start, end: 0)
    assert [
        deferred_jobs._retry_delay(quota_error, attempt)
        for attempt in range(1, 3)
    ] == [60, 300]
    assert [
        deferred_jobs._retry_delay(transient_error, attempt)
        for attempt in range(1, 4)
    ] == [60, 180, 600]

    wrapped = RuntimeError("provider wrapper")
    wrapped.__cause__ = quota_error
    job = RunnerJob(attempt=2)
    adapter = RecordingAdapter(error=wrapped)
    registry = _runner(monkeypatch, job, adapter)
    dispatched = []
    monkeypatch.setattr(deferred_jobs.random, "randint", lambda start, end: 30)
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
    terminal_registry = _runner(monkeypatch, terminal_job, terminal_adapter)

    terminal_result = terminal_registry.run(terminal_job.urlsafe_key)

    assert terminal_result.state is DeferredJobRunState.FAILED
    assert terminal_job.status == DeferredJobStatus.FAILED.value
    assert terminal_result.error == deferred_jobs.MODEL_BUSY_MESSAGE
    assert terminal_job.error["message"] == deferred_jobs.MODEL_BUSY_MESSAGE


def test_runner_persists_terminal_domain_failure_without_provider_retry(monkeypatch):
    job = RunnerJob(attempt=1)
    error = ValueError("invalid domain input")
    adapter = RecordingAdapter(error=error)
    registry = _runner(monkeypatch, job, adapter)
    captured = []
    monkeypatch.setattr(
        deferred_jobs.exceptions,
        "capture",
        lambda captured_error, **kwargs: captured.append(
            (captured_error, kwargs)
        ),
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


# @pair deferred-jobs:cancellation
def test_runner_treats_deleted_active_job_as_cancellation(monkeypatch):
    error = ValueError("stale domain write")
    job = RunnerJob(attempt=1)
    adapter = RecordingAdapter(error=error)
    registry = _runner(monkeypatch, job, adapter)
    captured = []
    monkeypatch.setattr(registry, "_claim_active", lambda *_args: False)
    monkeypatch.setattr(
        deferred_jobs.exceptions,
        "capture",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    result = registry.run(job.urlsafe_key)

    assert result.state is DeferredJobRunState.FAILED
    assert result.error == "Deferred job was cancelled or superseded."
    assert job.status == DeferredJobStatus.RUNNING.value
    assert captured == []


class FakeTasksClient:
    def __init__(self):
        self.request = None

    def queue_path(self, project, location, queue):
        return f"projects/{project}/locations/{location}/queues/{queue}"

    def task_path(self, project, location, queue, task):
        return f"{self.queue_path(project, location, queue)}/tasks/{task}"

    def create_task(self, request):
        self.request = request
        return SimpleNamespace(name=request["task"]["name"])


# @features deferred-jobs
# @dimensions service-tier quota retry
def test_organize_retry_uses_priority_for_every_generation_stage(monkeypatch):
    adapter = deferred_job_adapters.OrganizeReportAdapter()
    report = SimpleNamespace(summary=None)
    actor = SimpleNamespace()
    summary_calls = []
    retrieval_calls = []
    generated = []

    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "finalize_report_upload_manifest",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "summarize_report_input_files",
        lambda _report, **kwargs: summary_calls.append(kwargs) or [],
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "prepare_organize_retrieval_context",
        lambda _report, _actor: retrieval_calls.append((_report, _actor)) or {},
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "organize_prompt",
        lambda *_args: Prompt("Organize", type="organize report"),
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_organize_plan",
        lambda prompt: generated.append(("plan", prompt.service_tier))
        or {"summary": "Ready", "actions": []},
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "complete_organize_submissions",
        lambda proposal, *_args, **kwargs: generated.append(
            ("submissions", kwargs.get("service_tier"))
        )
        or proposal,
    )

    for attempt in (1, 2):
        context = deferred_jobs.DeferredJobContext(
            job=SimpleNamespace(attempt=attempt),
            actor=actor,
            notification=None,
            inputs={"report": report},
            parameters={},
            checkpoint={},
        )
        adapter.prepare(context)

    assert "service_tier" not in summary_calls[0]
    assert summary_calls[1]["service_tier"] == "priority"
    assert retrieval_calls == [(report, actor), (report, actor)]
    assert generated == [
        ("plan", None),
        ("submissions", None),
        ("plan", "priority"),
        ("submissions", "priority"),
    ]


# @pair deferred-jobs:cancellation
def test_organize_prepare_stops_before_report_save_after_cancellation(monkeypatch):
    adapter = deferred_job_adapters.OrganizeReportAdapter()
    report = SimpleNamespace(summary=None)
    saved = []
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "finalize_report_upload_manifest",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "summarize_report_input_files",
        lambda *_args, **_kwargs: [SimpleNamespace()],
    )
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "save",
        lambda *_args: saved.append(_args),
    )
    context = deferred_jobs.DeferredJobContext(
        job=SimpleNamespace(attempt=1),
        actor=SimpleNamespace(),
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
        active_check=lambda: False,
    )

    with pytest.raises(
        deferred_jobs.DeferredJobClaimLostError,
        match="cancelled or superseded",
    ):
        adapter.prepare(context)

    assert saved == []


# @pair deferred-jobs:report-execution
# @pair deferred-jobs:cancellation
# @pair ai-report:deterministic-run
def test_report_execution_adapter_runs_the_reviewed_proposal(monkeypatch):
    adapter = deferred_job_adapters.ReportExecutionAdapter()

    class FakeUser:
        entity_kind = "user"
        urlsafe_key = "actor-key"

        def __init__(self):
            self.properties = SimpleNamespace()

        def access(self, required):
            return AI.CREATE.implies(required)

    class FakeProcess:
        def __init__(self, report):
            self.report = report

        def fail(self, message, result=None):
            self.report.status = "failed"
            self.report.pending = None
            self.report.error = message
            if result is not None:
                self.report.result = result

    class FakeReport:
        entity_kind = "report"
        urlsafe_key = "report-key"

        def __init__(self):
            self.status = "ready"
            self.pending = False
            self.error = None
            self.deferred_job = None
            self.result = None
            self.proposal = {
                "summary": "Reviewed proposal",
                "actions": [{"id": "save-one", "type": "skip"}],
            }
            self.properties = SimpleNamespace(process=FakeProcess(self))

        def allowed(self, *_args, **_kwargs):
            return True

    actor = FakeUser()
    report = FakeReport()
    job = SimpleNamespace(
        urlsafe_key="execution-job",
        idempotency_key="execution-operation",
        client={},
        authorization={},
    )
    context = deferred_jobs.DeferredJobContext(
        job=job,
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
        active_check=lambda: True,
    )
    saved = []
    calls = []
    monkeypatch.setattr(deferred_job_adapters.Entities, "USER", FakeUser)
    monkeypatch.setattr(deferred_job_adapters.Entities, "REPORT", FakeReport)
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: report,
    )

    spec = SimpleNamespace(actor=actor, inputs={"report": report})
    job.authorization = adapter.authorization(spec)
    adapter.started(context)
    adapter.authorize(context)
    adapter.validate_apply(context)

    def run_report(current, user, *, ensure_active):
        calls.append((current, user))
        ensure_active()
        current.status = "complete"
        current.pending = False
        current.result = {
            "ledger_version": 1,
            "status": "complete",
            "actions": [{"status": "skipped"}],
        }
        return current.result

    monkeypatch.setattr(deferred_job_adapters.ai, "run_report", run_report)

    result = adapter.apply(context)

    assert result == {
        "report_key": "report-key",
        "status": "complete",
        "action_count": 1,
    }
    assert calls == [(report, actor)]
    assert adapter.inspect(context) is DeferredJobInspection.APPLIED
    assert report.deferred_job == {
        "key": "execution-job",
        "idempotency_key": "execution-operation",
        "previous_status": "ready",
        "revision": 0,
    }

    adapter.cleanup(context, terminal=True)

    assert report.deferred_job is None
    assert saved


# @pair deferred-jobs:report-execution
# @pair ai-report:recovery
def test_report_execution_failure_preserves_a_retryable_ledger(monkeypatch):
    adapter = deferred_job_adapters.ReportExecutionAdapter()

    class FakeReport:
        entity_kind = "report"
        urlsafe_key = "report-key"

        def __init__(self):
            self.status = "running"
            self.pending = True
            self.error = None
            self.deferred_job = {
                "key": "execution-job",
                "idempotency_key": "execution-operation",
                "previous_status": "ready",
            }
            self.result = {
                "ledger_version": 1,
                "status": "running",
                "actions": [
                    {"status": "complete"},
                    {"status": "applying"},
                ],
            }
            self.properties = SimpleNamespace(
                process=SimpleNamespace(fail=self.fail)
            )

        def fail(self, message, result=None):
            self.status = "failed"
            self.pending = None
            self.error = message
            if result is not None:
                self.result = result

    report = FakeReport()
    actor = SimpleNamespace()
    context = deferred_jobs.DeferredJobContext(
        job=SimpleNamespace(urlsafe_key="execution-job"),
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
    )
    monkeypatch.setattr(deferred_job_adapters.Entities, "REPORT", FakeReport)
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: report,
    )
    monkeypatch.setattr(deferred_job_adapters.Entities, "save", lambda *_args: None)

    adapter.failure(context, ValueError("save worker stopped"))

    assert report.status == "failed"
    assert report.pending is None
    assert report.error == "save worker stopped"
    assert report.result["status"] == "failed"
    assert report.result["failed_at"] == 2


# @pair deferred-jobs:superseded
# @pair ai-report:active-operation
# @pair ai-report:failure-isolation
def test_report_replacement_supersedes_old_job_and_ignores_old_failure(monkeypatch):
    adapter = deferred_job_adapters.OrganizeReportAdapter()
    events = []

    class FakeReport:
        def __init__(self):
            self.urlsafe_key = "report-key"
            self.deferred_job = {"key": "old-operation"}

    report = FakeReport()
    actor = SimpleNamespace()
    context = deferred_jobs.DeferredJobContext(
        job=SimpleNamespace(
            urlsafe_key="new-operation",
            idempotency_key="new-idempotency-key",
        ),
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
    )
    monkeypatch.setattr(
        deferred_jobs.DeferredJobs,
        "supersede",
        lambda previous: events.append(("supersede", previous.copy())) or True,
    )
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "save",
        lambda *entities: events.append(("save", entities)),
    )

    adapter.started(context)

    assert events[0] == ("supersede", {"key": "old-operation"})
    assert events[1] == ("save", (report, actor))
    assert report.deferred_job == {
        "key": "new-operation",
        "idempotency_key": "new-idempotency-key",
        "revision": 0,
    }

    monkeypatch.setattr(deferred_job_adapters.Entities, "REPORT", FakeReport)
    stale_report = FakeReport()
    current_report = FakeReport()
    current_report.deferred_job = {"key": "new-operation"}
    context.inputs["report"] = stale_report
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: current_report,
    )
    context.job.urlsafe_key = "old-operation"
    adapter.failure(context, ValueError("old worker failed"))
    assert events == [
        ("supersede", {"key": "old-operation"}),
        ("save", (report, actor)),
    ]


# @pair ai-report:ask
# @pair ai-report:revision
# @pair ai-report:status
# @pair ai-report:proposal-publication
# @pair deferred-jobs:checkpoint
@pytest.mark.parametrize(
    ("parameters", "response", "expected_prompt", "expected_status"),
    [
        (
            {},
            {
                "summary": "No follow-up work is needed.",
                "confidence": 0.9,
                "actions": [],
            },
            "initial-prompt",
            "complete",
        ),
        (
            {"mode": "revise", "feedback": "Call out the ambiguity."},
            {
                "summary": "A human should confirm the ambiguous match.",
                "confidence": 0.5,
                "actions": [
                    {
                        "id": "review",
                        "type": "needs_review",
                        "data": {"note": "Confirm the matching record."},
                    }
                ],
            },
            "revision-prompt",
            "ready",
        ),
    ],
    ids=("answer", "revision-with-actions"),
)
def test_ask_report_adapter_prepares_and_applies_checkpointed_response(
    monkeypatch,
    parameters,
    response,
    expected_prompt,
    expected_status,
):
    adapter = deferred_job_adapters.AskReportAdapter()
    actor = SimpleNamespace()
    saved = []
    phases = []
    prompt_calls = []

    class Process:
        def set_proposal(self, proposal, status="ready"):
            report.proposal = proposal
            report.summary = proposal.get("summary")
            report.status = status
            report.pending = None
            report.error = None
            report.result = None

    report = SimpleNamespace(
        urlsafe_key="ask-report",
        deferred_job={"key": "ask-job"},
        proposal={"summary": "Previous answer", "actions": []},
        result={"stale": True},
        properties=SimpleNamespace(process=Process()),
    )
    job = SimpleNamespace(
        urlsafe_key="ask-job",
        idempotency_key="ask-operation",
    )

    class Control:
        def ensure_active(self):
            return None

        def set_phase(self, phase, **_details):
            phases.append(str(getattr(phase, "value", phase)))

    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "ask_prompt",
        lambda current_report, current_actor: prompt_calls.append(
            ("initial", current_report, current_actor)
        )
        or "initial-prompt",
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "revise_ask_prompt",
        lambda current_report, current_actor, feedback: prompt_calls.append(
            ("revision", current_report, current_actor, feedback)
        )
        or "revision-prompt",
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_ask_report",
        lambda prompt: prompt_calls.append(("generate", prompt)) or response,
    )
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    context = deferred_jobs.DeferredJobContext(
        job=job,
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters=parameters,
        checkpoint={},
        execution_control=Control(),
    )

    checkpoint = adapter.prepare(context)

    assert checkpoint == {"proposal": response, "status": expected_status}
    assert phases == ["generating", "validating"]
    assert prompt_calls[-1] == ("generate", expected_prompt)
    if parameters:
        assert prompt_calls[0] == (
            "revision",
            report,
            actor,
            parameters["feedback"],
        )
    else:
        assert prompt_calls[0] == ("initial", report, actor)
    assert report.result == {"stale": True}

    context.checkpoint = checkpoint
    result = adapter.apply(context)

    assert result == {
        "report_key": "ask-report",
        "status": expected_status,
        "action_count": len(response["actions"]),
    }
    assert report.proposal == response
    assert report.proposal is not response
    assert report.status == expected_status
    assert report.result is None
    assert saved == [(report, actor)]


# @pair deferred-jobs:checkpoint
# @pair ai-report:plan-resume
# @pair ai-report:submission-completion
# @pair ai-report:status
# @pair ai-report:proposal-publication
def test_organize_resumes_plan_checkpoint_without_second_planning_call(monkeypatch):
    adapter = deferred_job_adapters.OrganizeReportAdapter()
    proposal = {"summary": "Planned", "actions": []}
    completed = {"summary": "Completed", "actions": []}
    calls = []
    checkpoints = []
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_organize_plan",
        lambda _prompt: pytest.fail("planning should not run again"),
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "complete_organize_submissions",
        lambda value, report, actor, **kwargs: calls.append(
            (value, report, actor, kwargs)
        )
        or completed,
    )
    saved = []

    class Process:
        def set_proposal(self, value, status="ready"):
            report.proposal = value
            report.status = status

    report = SimpleNamespace(
        urlsafe_key="organize-report",
        deferred_job={"key": "organize-job"},
        properties=SimpleNamespace(process=Process()),
    )
    actor = SimpleNamespace()
    monkeypatch.setattr(
        deferred_job_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    context = deferred_jobs.DeferredJobContext(
        job=SimpleNamespace(
            attempt=2,
            urlsafe_key="organize-job",
            idempotency_key="organize-operation",
        ),
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={
            "schema_version": 1,
            "stage": "plan_ready",
            "proposal": proposal,
        },
        active_check=lambda: True,
        checkpoint_callback=lambda checkpoint, *, progress=None: checkpoints.append(
            (checkpoint, progress)
        ),
    )

    assert adapter.checkpoint_ready(context) is False
    assert adapter.checkpoint_ready(
        SimpleNamespace(
            checkpoint={
                "schema_version": 1,
                "stage": "ready_to_apply",
                "proposal": completed,
            }
        )
    ) is True
    assert adapter.checkpoint_ready(
        SimpleNamespace(
            checkpoint={
                "schema_version": 2,
                "stage": "ready_to_apply",
                "proposal": completed,
            }
        )
    ) is False

    assert adapter.prepare(context) is None
    assert calls == [
        (proposal, report, actor, {"service_tier": "priority"})
    ]
    assert checkpoints == [
        (
            {
                "schema_version": 1,
                "stage": "ready_to_apply",
                "proposal": completed,
                "status": "ready",
            },
            {"phase": "prepared"},
        )
    ]

    result = adapter.apply(context)

    assert result == {
        "report_key": "organize-report",
        "status": "ready",
        "action_count": 0,
    }
    assert report.proposal == completed
    assert report.proposal is not completed
    assert report.status == "ready"
    assert saved == [(report, actor)]


# @features deferred-jobs
# @dimensions cancellation deterministic-task-id
def test_cancel_deletes_tasks_and_persists_a_tombstone(
    monkeypatch,
    operation_projection,
):
    registry = deferred_jobs.DeferredJobRegistry()
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
        deferred_jobs.database,
        "transition_active_deferred_job",
        transition,
    )
    monkeypatch.setattr(Entities, "DEFERRED_JOB", lambda raw: raw)
    monkeypatch.setattr(Entities, "fetch_one", lambda value, request: value)
    monkeypatch.setattr(Entities, "save", lambda *entities: saved.extend(entities))

    assert registry.cancel(job) is True

    task_id = deferred_jobs._task_id(job, 3)
    feedback_task_id = deferred_jobs._feedback_task_id(job)
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
# @source lagniappe/core/tools/deferred_jobs.py::_publish_operation_projection
def test_operation_projection_failure_is_nonfatal(monkeypatch):
    job = SimpleNamespace(urlsafe_key="durable-job")
    captured = []
    monkeypatch.setattr(
        deferred_jobs.cache,
        "update_operation_projection",
        lambda *_jobs: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )
    monkeypatch.setattr(
        deferred_jobs.exceptions,
        "capture",
        lambda error, **kwargs: captured.append((error, kwargs)),
    )

    assert (
        deferred_jobs._publish_operation_projection(
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
# @source lagniappe/core/tools/deferred_jobs.py::DeferredJobRegistry._release
def test_terminal_release_reuses_committed_scheduler_control(monkeypatch):
    registry = deferred_jobs.DeferredJobRegistry()
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
    registry = deferred_jobs.DeferredJobRegistry()
    registry._defaults_loaded = True
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
    registry = deferred_jobs.DeferredJobRegistry()
    registry._defaults_loaded = True
    registry.register(RecordingAdapter())
    job = RunnerJob()
    job.notification = SimpleNamespace(body="Working...", pending=True)
    created = []

    monkeypatch.setattr(
        deferred_jobs,
        "CONFIG",
        SimpleNamespace(production=True),
    )
    monkeypatch.setattr(
        deferred_jobs,
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
            {"task_id": deferred_jobs._feedback_task_id(job)},
        )
    ]


# @pair deferred-jobs:dispatch
# @pair deferred-jobs:disabled-queue
# @pair deferred-jobs:task-identity
def test_production_dispatch_rejects_disabled_task_queue(monkeypatch):
    registry = deferred_jobs.DeferredJobRegistry()
    job = RunnerJob()
    job.job_type = DeferredJobType.SITE_EXPORT.value
    monkeypatch.setattr(
        deferred_jobs,
        "CONFIG",
        SimpleNamespace(production=True),
    )
    monkeypatch.setattr(
        task_queue,
        "CONFIG",
        SimpleNamespace(TASK_QUEUE_ENABLED=False, production=True),
    )
    monkeypatch.setattr(
        deferred_jobs,
        "url_for",
        lambda endpoint, _external: f"https://example.test/{endpoint}",
    )

    with pytest.raises(
        deferred_jobs.DeferredJobInfrastructureError,
        match="did not return a task identity",
    ):
        registry.dispatch(job, attempt=1)


def _fake_start_entities(monkeypatch):
    state = {"saved": []}
    actor = SimpleNamespace(urlsafe_key="actor-key")

    def create_notification(data):
        notification = SimpleNamespace(
            **data,
            urlsafe_key="notification-key",
        )
        state["notification"] = notification
        return notification

    def create_job(data):
        job = SimpleNamespace(
            **data,
            urlsafe_key="job-key",
            status=DeferredJobStatus.QUEUED.value,
            error={},
        )
        state["job"] = job
        return job

    monkeypatch.setattr(
        Entities,
        "NOTIFICATION",
        SimpleNamespace(create=create_notification),
    )
    monkeypatch.setattr(
        Entities,
        "DEFERRED_JOB",
        SimpleNamespace(create=create_job),
    )
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda *_args, **_kwargs: state.get("job"),
    )
    monkeypatch.setattr(
        Entities,
        "save",
        lambda *entities: state["saved"].append(entities),
    )
    monkeypatch.setattr(
        deferred_jobs.database,
        "create_named_key",
        lambda *_args, **_kwargs: "job-datastore-key",
    )
    monkeypatch.setattr(
        deferred_jobs.database,
        "create_deferred_job_if_absent",
        lambda *_args, **_kwargs: {"created": True, "entity": state.get("job")},
    )

    def update_dispatch(_key, revision, updates, _now):
        job = state["job"]
        if (
            job.status_revision != revision
            or job.dispatch_state != "dispatching"
        ):
            return False
        for name, value in updates.items():
            if name == "error" and isinstance(value, str):
                value = json.loads(value)
            setattr(job, name, value)
        return True

    monkeypatch.setattr(
        deferred_jobs.database,
        "update_deferred_job_recovery_dispatch",
        update_dispatch,
    )
    return actor, state


# @pair deferred-jobs:transient-dispatch
# @pair deferred-jobs:no-apply
# @pair export:intent-preservation
# @pair notifications:pending-state
def test_start_retains_site_export_intent_after_provider_enqueue_failure(monkeypatch):
    actor, state = _fake_start_entities(monkeypatch)
    registry = deferred_jobs.DeferredJobRegistry()
    adapter = registry.adapter(DeferredJobType.SITE_EXPORT)
    provider_or_apply_calls = []
    export_updates = []

    monkeypatch.setattr(
        deferred_jobs,
        "CONFIG",
        SimpleNamespace(production=True),
    )
    monkeypatch.setattr(
        deferred_jobs,
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
        deferred_job_adapters.database,
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
    actor, state = _fake_start_entities(monkeypatch)
    registry = deferred_jobs.DeferredJobRegistry()
    adapter = RecordingAdapter()
    registry._defaults_loaded = True
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
    actor, state = _fake_start_entities(monkeypatch)
    existing = SimpleNamespace(
        request_fingerprint="different-request",
        notification=SimpleNamespace(),
    )
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda *_args, **_kwargs: existing,
    )
    registry = deferred_jobs.DeferredJobRegistry()

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
    first = deferred_jobs._request_fingerprint(
        **values,
        client={"destination": "page:Form"},
    )
    extended = deferred_jobs._request_fingerprint(
        **values,
        client={"destination": "page:Form", "key": "page-key"},
    )
    rerouted = deferred_jobs._request_fingerprint(
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

    status = deferred_jobs._status_projection(job, now=now)

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

    projection = deferred_jobs._admin_projection(job, now=now)

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
        deferred_jobs,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )

    deleted = deferred_jobs.DeferredJobRegistry().delete_terminal(
        before=now - timedelta(days=7),
        batch_size=1,
    )

    assert deleted == 2
    assert deleted_batches == [["completed"], ["replaced"]]
    assert query.order == ["created"]
    assert len(query.filters) == 1


# @features deferred-jobs
# @dimensions reconciliation redispatch compare-and-set deterministic-task-id
def test_reconciler_redispatches_one_cas_claimed_stale_job(monkeypatch):
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    job = RunnerJob(attempt=2)
    job.status = DeferredJobStatus.RETRY_WAIT.value
    job.status_revision = 4
    job.dispatch_state = "pending"
    job.created = now - timedelta(minutes=10)
    registry = deferred_jobs.DeferredJobRegistry()
    monkeypatch.setattr(registry, "_reconcile_candidates", lambda *, limit: [job])

    def claim(key, revision, claimed_at, **kwargs):
        assert (key, revision, claimed_at) == (job.key, 4, now)
        assert kwargs["grace_seconds"] > 0
        job.status_revision = 5
        job.dispatch_state = "dispatching"
        return {"claimed": True, "action": "redispatch", "entity": job}

    monkeypatch.setattr(
        deferred_jobs.database,
        "claim_deferred_job_recovery",
        claim,
    )
    monkeypatch.setattr(Entities, "DEFERRED_JOB", lambda raw: raw)
    monkeypatch.setattr(Entities, "fetch_one", lambda value, request: value)
    dispatched = []
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda current, *, attempt, task_suffix: dispatched.append(
            (current, attempt, task_suffix)
        )
        or "recovered-task",
    )
    finalized = []
    monkeypatch.setattr(
        deferred_jobs.database,
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
    registry = deferred_jobs.DeferredJobRegistry()
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
    job.error = {
        "message": "This operation could not finish after automatic recovery."
    }
    job.notification = SimpleNamespace(body="Creating report...", pending=True)
    job.client = {
        "source_widget": "CreateToolReport",
        "destination": "tools:ToolReportList",
    }
    registry = deferred_jobs.DeferredJobRegistry()
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
        deferred_jobs.exceptions,
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
    assert job.notification.body == deferred_jobs.MISSING_INPUT_MESSAGE
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
