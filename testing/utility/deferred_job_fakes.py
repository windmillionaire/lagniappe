"""Shared fakes for deferred-job service, runner, and recovery unit tests."""

import copy
import json
from types import SimpleNamespace

from google.api_core import exceptions as google_exceptions
import pytest

from lagniappe.core.definitions import (
    AI,
    DeferredJobInspection,
    DeferredJobStatus,
    DeferredJobType,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database
from lagniappe.core.tools.ai import observability
from lagniappe.core.tools.deferred_jobs import common as deferred_common
from lagniappe.core.tools.deferred_jobs.adapters.base import DeferredJobAdapter
from lagniappe.core.tools.deferred_jobs.service import DeferredJobService


@pytest.fixture(autouse=True)
def operation_projection(monkeypatch):
    """Keep deferred-job unit tests isolated from the Redis provider."""
    published = []
    monkeypatch.setattr(
        deferred_common.cache,
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


class RecordingAdapter(DeferredJobAdapter):
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


def runner(monkeypatch, job, adapter):
    service = DeferredJobService()
    service.adapter_registry._defaults_loaded = True
    service.register(adapter)
    monkeypatch.setattr(
        database,
        "claim_deferred_job",
        lambda *_args: {"claimed": True, "reason": "claimed", "entity": job},
    )
    monkeypatch.setattr(Entities, "DEFERRED_JOB", lambda raw: raw)
    monkeypatch.setattr(Entities, "fetch_one", lambda value, request: value)

    def persist(current, _token, **values):
        for name, value in values.items():
            setattr(current, name, value)

    monkeypatch.setattr(service, "_persist_claimed", persist)
    monkeypatch.setattr(service, "_claim_active", lambda *_args: True)
    monkeypatch.setattr(service, "_heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service,
        "_finish_terminal_delivery",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(service, "_release", lambda *_args, **_kwargs: None)
    return service


def terminal_delivery_runner(monkeypatch, job, adapter, persist=None):
    service = DeferredJobService()
    service.adapter_registry._defaults_loaded = True
    service.register(adapter)
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

    monkeypatch.setattr(database, "claim_deferred_job", claim)
    monkeypatch.setattr(Entities, "DEFERRED_JOB", lambda raw: raw)
    monkeypatch.setattr(Entities, "fetch_one", lambda value, request: value)
    monkeypatch.setattr(Entities, "save", lambda *_entities: None)
    monkeypatch.setattr(service, "_persist_claimed", persist or persist_values)
    monkeypatch.setattr(service, "_heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_claim_active", lambda *_args: True)
    return service


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


def fake_start_entities(monkeypatch):
    state = {"saved": []}
    actor = SimpleNamespace(urlsafe_key="actor-key")

    def create_notification(data):
        notification = SimpleNamespace(**data, urlsafe_key="notification-key")
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
    monkeypatch.setattr(Entities, "DEFERRED_JOB", SimpleNamespace(create=create_job))
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
        database,
        "create_named_key",
        lambda *_args, **_kwargs: "job-datastore-key",
    )
    monkeypatch.setattr(
        database,
        "create_deferred_job_if_absent",
        lambda *_args, **_kwargs: {"created": True, "entity": state.get("job")},
    )

    def update_dispatch(_key, revision, updates, _now):
        job = state["job"]
        if job.status_revision != revision or job.dispatch_state != "dispatching":
            return False
        for name, value in updates.items():
            if name == "error" and isinstance(value, str):
                value = json.loads(value)
            setattr(job, name, value)
        return True

    monkeypatch.setattr(
        database,
        "update_deferred_job_recovery_dispatch",
        update_dispatch,
    )
    return actor, state
