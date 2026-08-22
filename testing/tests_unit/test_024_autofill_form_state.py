"""Focused contracts for autofill form state and optional lock behavior."""

from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import FileConsumer, FileConsumerLimitError
from lagniappe.core.entities import Entities
from lagniappe.core.tools.deferred_jobs.adapters import (
    autofill as deferred_job_adapters,
)
from lagniappe.core.tools.deferred_jobs import autofill as autofill_jobs
from lagniappe.core.tools.notifications import service as notifications
from lagniappe.core.tools.polling import forms as form_state
from lagniappe.core.tools.polling import projections as polling


pytestmark = pytest.mark.unit


# @pairs deferred-jobs:form-lock ai:autofill
def test_autofill_explicit_lock_opt_out_skips_target_lock():
    adapter = deferred_job_adapters.AutofillAdapter()
    spec = SimpleNamespace(
        inputs={"target": SimpleNamespace(urlsafe_key="new-page")},
        parameters={"lock_target": False},
    )
    job = SimpleNamespace(urlsafe_key="operation", idempotency_key="request")

    assert adapter.start_lock(spec, job) is None


# @pairs deferred-jobs:form-revision ai:autofill
def test_lockless_autofill_keeps_revision_drift_guard(monkeypatch):
    target = SimpleNamespace(autofill_revision="revision-one")
    context = SimpleNamespace(
        parameters={"lock_target": False},
        job=SimpleNamespace(
            urlsafe_key="operation",
            authorization={"form_revision": "revision-one"},
        ),
        input=lambda name: target if name == "target" else None,
    )
    monkeypatch.setattr(
        deferred_job_adapters,
        "active_deferred_job_lock",
        lambda _target: (_ for _ in ()).throw(
            AssertionError("lockless create autofill queried a target lock")
        ),
    )

    deferred_job_adapters.AutofillAdapter().validate_apply(context)

    target.autofill_revision = "revision-two"
    with pytest.raises(deferred_job_adapters.DeferredJobDriftError):
        deferred_job_adapters.AutofillAdapter().validate_apply(context)


# @pairs sync:validation sync:document-only sync:client-identity forms:no-live-sync
def test_sync_payload_validation_is_document_only_and_bounded():
    invalid = {
        "client_id": "form-contract-test",
        "updates": [
            {
                "key": "page-key",
                "sync_id": "page-hash:form-hash:form",
                "update": "encoded-state",
                "save": False,
            }
        ],
    }
    valid = {
        "client_id": "document-contract-test",
        "updates": [
            {
                "key": "page-key",
                "sync_id": "page-hash:document",
                "ydoc": "encoded-state",
                "save": False,
            }
        ],
    }

    assert (
        form_state.validate_sync_payload(invalid)
        == "Only identified document widgets may use live sync."
    )
    assert form_state.validate_sync_payload(valid) is None
    valid["updates"][0]["mentions"] = [
        {
            "occurrence_id": "mention_1234",
            "recipient": "recipient-key",
            "display_name": "Recipient",
        }
    ]
    assert form_state.validate_sync_payload(valid) is None
    valid["updates"][0]["mentions"] = [{}]
    assert (
        form_state.validate_sync_payload(valid)
        == "Document mention occurrence is invalid."
    )
    assert (
        form_state.validate_sync_payload({"updates": []})
        == "Sync payload missing client_id."
    )
    assert (
        form_state.validate_sync_payload({"client_id": "x", "updates": [valid] * 65})
        == "Sync payload updates must be a bounded list."
    )
    assert (
        form_state.validate_sync_payload({"client_id": "x", "updates": [{}]})
        == "Only identified document widgets may use live sync."
    )


# @pairs offline:replay-precondition forms:conflict-review
def test_offline_replay_conflict_requires_stale_origin_fingerprint():
    entity = SimpleNamespace(fingerprint="current")

    assert form_state.offline_replay_conflicts(
        entity,
        {"offline": "True", "offline-fingerprint": "originating"},
    )
    assert not form_state.offline_replay_conflicts(
        entity,
        {"offline": "True", "offline-fingerprint": "current"},
    )
    assert not form_state.offline_replay_conflicts(
        entity,
        {"offline-fingerprint": "originating"},
    )


# @pairs deferred-jobs:form-lock deferred-jobs:quick-edit
def test_form_field_membership_uses_the_attached_schema():
    entity = SimpleNamespace(form=SimpleNamespace(schema=[{"id": "form-field"}]))

    assert form_state.is_form_field(entity, "form-field")
    assert not form_state.is_form_field(entity, "task-setting")


# @pairs polling:channel polling:revision polling:permissions polling:mounted-scope polling:batching
# @pair messaging:polling-revision
def test_channel_revisions_batch_only_requested_site_fingerprints():
    user = SimpleNamespace(
        fingerprint="unchanged-user-fingerprint",
        permissions_fingerprint="unchanged-permissions",
    )
    loads = []

    def load(paths):
        loads.append(tuple(paths))
        return {path: f"site:{path}" for path in paths}

    revisions = polling.channel_revisions(
        ("home-notes", "tasks", "messages", "starred", "tasks"),
        user,
        fingerprint_loader=load,
        notification_state={
            "generation": "messages-a",
            "message_revision": 4,
        },
    )

    assert set(revisions) == {"home-notes", "tasks", "messages", "starred"}
    assert loads == [("/", "/tasks/index")]

    starred_before = revisions["starred"]
    home_before = revisions["home-notes"]
    messages_before = revisions["messages"]
    user.fingerprint = "changed-user-fingerprint"
    changed = polling.channel_revisions(
        ("home-notes", "starred"),
        user,
        fingerprint_loader=load,
    )
    assert changed["starred"] != starred_before
    assert changed["home-notes"] == home_before

    load_count = len(loads)
    ordinary_changed = polling.channel_revisions(
        ("messages",),
        user,
        fingerprint_loader=load,
        notification_state={
            "generation": "messages-a",
            "revision": 99,
            "message_revision": 4,
        },
    )
    assert ordinary_changed["messages"] == messages_before
    message_changed = polling.channel_revisions(
        ("messages",),
        user,
        fingerprint_loader=load,
        notification_state={
            "generation": "messages-a",
            "revision": 99,
            "message_revision": 5,
        },
    )
    assert message_changed["messages"] != messages_before
    assert len(loads) == load_count


# @pairs deferred-jobs:server-render deferred-jobs:status polling:batching
# @source lagniappe/core/tools/polling/projections.py::render_operation_statuses
def test_render_operation_statuses_batches_and_attaches_known_jobs():
    reports = [
        SimpleNamespace(deferred_job={"key": f"job-{index}"}) for index in range(51)
    ]
    loads = []

    def load(keys, user):
        loads.append((list(keys), user))
        return [{"key": key, "revision": 3, "status": "running"} for key in keys]

    statuses = polling.render_operation_statuses(
        reports,
        "viewer",
        status_loader=load,
    )

    assert [len(keys) for keys, _user in loads] == [50, 1]
    assert all(user == "viewer" for _keys, user in loads)
    assert len(statuses) == 51
    assert reports[0]._operation_status == {
        "key": "job-0",
        "revision": 3,
        "status": "running",
    }


# @pairs polling:revision polling:batching polling:permissions
# @pairs deferred-jobs:redis-projection deferred-jobs:owner deferred-jobs:cache-failure-isolation
def test_operation_statuses_skip_fresh_cached_jobs_and_batch_stale_jobs(monkeypatch):
    from google.cloud.datastore import Key

    actor_key = Key("users", "owner", project="poll-test")
    user = SimpleNamespace(urlsafe_key=actor_key.to_legacy_urlsafe().decode("utf-8"))
    loaded = []

    def statuses(keys, actor):
        loaded.append((list(keys), actor))
        return [{"key": key, "revision": 3} for key in keys]

    stale = [
        {
            "id": f"operation:{index}",
            "type": "operation",
            "key": Key("jobs", str(index), parent=actor_key)
            .to_legacy_urlsafe()
            .decode("utf-8"),
            "revision": 1,
        }
        for index in range(51)
    ]
    projected, unchanged = polling.operation_statuses(
        stale,
        user,
        status_loader=statuses,
        state_loader=lambda _keys: {},
        state_writer=lambda *_statuses: None,
        now=100,
    )
    assert projected == {
        descriptor["key"]: {"key": descriptor["key"], "revision": 3}
        for descriptor in stale
    }
    assert unchanged == set()
    assert loaded == [
        ([descriptor["key"] for descriptor in stale[:50]], user),
        ([stale[50]["key"]], user),
    ]

    loaded.clear()
    current = {stale[0]["key"]: {"revision": 3, "verified_at": 99}}
    projected, unchanged = polling.operation_statuses(
        [{**stale[0], "revision": 3}],
        user,
        status_loader=statuses,
        state_loader=lambda _keys: current,
        state_writer=lambda *_statuses: None,
        now=100,
    )
    assert projected == {}
    assert unchanged == {stale[0]["key"]}
    assert loaded == []

    captured = []
    monkeypatch.setattr(
        polling.exceptions,
        "capture",
        lambda error, **kwargs: captured.append((error, kwargs)),
    )
    projected, unchanged = polling.operation_statuses(
        [{**stale[0], "revision": 3}],
        user,
        status_loader=statuses,
        state_loader=lambda _keys: (_ for _ in ()).throw(
            RuntimeError("redis unavailable")
        ),
        state_writer=lambda *_statuses: None,
        now=100,
    )
    assert projected == {stale[0]["key"]: {"key": stale[0]["key"], "revision": 3}}
    assert unchanged == set()
    assert loaded == [([stale[0]["key"]], user)]
    assert str(captured[0][0]) == "redis unavailable"

    collaborator_key = Key("users", "collaborator", project="poll-test")
    collaborator_job = (
        Key("jobs", "shared", parent=collaborator_key)
        .to_legacy_urlsafe()
        .decode("utf-8")
    )
    loaded.clear()
    projected, unchanged = polling.operation_statuses(
        [
            {
                "id": "operation:shared",
                "type": "operation",
                "key": collaborator_job,
                "revision": 3,
            }
        ],
        user,
        status_loader=statuses,
        state_loader=lambda _keys: {
            collaborator_job: {"revision": 3, "verified_at": 99}
        },
        state_writer=lambda *_statuses: None,
        now=100,
    )
    assert projected == {collaborator_job: {"key": collaborator_job, "revision": 3}}
    assert unchanged == set()
    assert loaded == [([collaborator_job], user)]


# @pairs deferred-jobs:form-lock polling:revision
def test_form_lock_revision_is_independent_of_entity_fingerprint():
    entity = SimpleNamespace(
        urlsafe_key="page-key",
        fingerprint="entity-fingerprint",
        allowed=lambda _action, user=None: user == "editor",
    )
    descriptor = {
        "id": "form-lock:page-key",
        "type": "form-lock",
        "key": entity.urlsafe_key,
        "revision": "operation-key:5",
    }
    active_locks = {
        entity.urlsafe_key: (
            SimpleNamespace(scope="form-autofill"),
            SimpleNamespace(urlsafe_key="operation-key", status_revision=6),
        )
    }

    changed = polling.lock_result(
        descriptor,
        entity,
        active_locks,
        user="editor",
    )
    assert changed["status"] == "changed"
    assert changed["revision"] == "operation-key:6"
    assert changed["payload"]["locked"] is True

    entity.fingerprint = "changed-entity-fingerprint"
    current = polling.lock_result(
        {**descriptor, "revision": "operation-key:6"},
        entity,
        active_locks,
        user="editor",
    )
    assert current == {
        "id": "form-lock:page-key",
        "type": "form-lock",
        "status": "unchanged",
        "revision": "operation-key:6",
        "poll_after_ms": 15000,
    }


# @pairs ai:autofill ai:deferred pages:autofill tasks:autofill
def test_autofill_job_spec_contains_only_durable_inputs(monkeypatch):
    class Task:
        pass

    monkeypatch.setattr(autofill_jobs.Entities, "TASK", Task)
    entity = SimpleNamespace(urlsafe_key="page-key")
    user = SimpleNamespace(urlsafe_key="user-key")
    record = {"token": "signed", "filename": "context.pdf"}

    spec = autofill_jobs.autofill_job_spec(
        entity,
        user,
        {
            "operation-id": "operation-id",
            "autofill-description": "Use the attachment",
            "mimetype": "application/pdf",
        },
        upload_record=record,
    )

    assert spec.actor is user
    assert spec.inputs == {"target": entity}
    assert spec.parameters["upload_record"] == record
    assert spec.parameters["lock_target"] is True
    assert spec.client["destination"] == "info:PageInfo"

    task = Task()
    task.hash = "task-hash"
    task.page = SimpleNamespace(urlsafe_key="parent-page-key")
    task_spec = autofill_jobs.autofill_job_spec(task, user, {})
    assert task_spec.client == {
        "key": "parent-page-key",
        "source_widget": "TaskForm",
        "destination": "task-hash:TaskForm",
    }


# @pairs ai:autofill ai:deferred notifications:autofill
def test_autofill_upload_is_validated_before_job_start(monkeypatch):
    started = []
    error = FileConsumerLimitError(
        "oversized.pdf is too large for AI autofill attachment.",
        consumer=FileConsumer.AI_INLINE,
        size=31,
        max_bytes=30,
    )
    monkeypatch.setattr(
        autofill_jobs.storage_assets,
        "direct_upload_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        autofill_jobs.DeferredJobs,
        "start",
        lambda spec: started.append(spec),
    )

    with pytest.raises(FileConsumerLimitError):
        autofill_jobs.start_autofill_job(
            SimpleNamespace(urlsafe_key="page-key"),
            SimpleNamespace(urlsafe_key="user-key"),
            {},
            upload_record={"token": "signed", "filename": "oversized.pdf"},
        )
    assert started == []


# @pairs notifications:task-queue notifications:create notifications:body
def test_process_notification_requires_a_valid_user(monkeypatch):
    user = SimpleNamespace(kind="user")
    saved = []
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda key, request: user if key == "user-key" else None,
    )
    monkeypatch.setattr(
        Entities.NOTIFICATION,
        "create",
        lambda data: SimpleNamespace(**data),
    )
    monkeypatch.setattr(Entities, "save", lambda value: saved.append(value))

    assert notifications.create_process_notification({}, "Ignored") is None
    created = notifications.create_process_notification(
        {"user_key": "user-key"},
        "Completed",
    )
    assert created.parent is user
    assert created.body == "Completed"
    assert saved == [created]
