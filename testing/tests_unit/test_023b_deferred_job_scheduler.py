"""Durable recovery membership and Cloud Scheduler convergence behavior."""

from datetime import datetime, timezone
from types import SimpleNamespace

from google.cloud.datastore import Key
import pytest

from lagniappe.core.tools import deferred_job_scheduler, deferred_jobs
from lagniappe.core.tools.database import utility as database_utility


pytestmark = pytest.mark.unit


class MemoryTransaction:
    def __init__(self, datastore):
        self.datastore = datastore

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def put(self, entity):
        self.datastore.entities[entity.key] = entity


class MemoryDatastore:
    def __init__(self):
        self.entities = {}

    def key(self, kind, identifier):
        return Key(kind, identifier, project="scheduler-test")

    def transaction(self):
        return MemoryTransaction(self)

    def get(self, key, transaction=None):
        if transaction is not None:
            assert isinstance(transaction, MemoryTransaction)
        return self.entities.get(key)


class FakeResponse:
    def __init__(self, state):
        self.state = state

    def raise_for_status(self):
        return None

    def json(self):
        return {"state": self.state.upper()}


class FakeSchedulerSession:
    def __init__(self, state="enabled", *, before_change=None, failure=None):
        self.state = state
        self.before_change = before_change
        self.failure = failure
        self.calls = []

    def request(self, method, url, timeout):
        self.calls.append((method, url, timeout))
        if self.failure is not None:
            raise self.failure
        if method == "GET":
            return FakeResponse(self.state)
        if self.before_change is not None:
            callback = self.before_change
            self.before_change = None
            callback()
        if url.endswith(":pause"):
            self.state = "paused"
        elif url.endswith(":resume"):
            self.state = "enabled"
        else:
            raise AssertionError(f"Unexpected Scheduler mutation: {url}")
        return FakeResponse(self.state)


@pytest.fixture
def scheduler_database(monkeypatch):
    datastore = MemoryDatastore()
    monkeypatch.setattr(
        database_utility,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    return datastore


def _job_key(identifier="job-one"):
    return Key("jobs", identifier, project="scheduler-test")


def _control():
    return database_utility.get_deferred_job_scheduler_control()


# @features deferred-jobs cloud-scheduler
# @dimensions durable-membership terminal-delivery idempotency transaction desired-state
def test_tracking_membership_follows_recovery_required_state(scheduler_database):
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    job_key = _job_key()
    with scheduler_database.transaction() as transaction:
        added = database_utility._update_deferred_job_scheduler_tracking(
            transaction,
            job_key,
            None,
            {"status": "queued", "dispatch_state": "pending"},
            now,
        )

    assert added["active_jobs"] == 1
    assert added["desired_state"] == "enabled"
    assert added["initialized"] is False

    repaired = database_utility.repair_deferred_job_scheduler_control(
        [job_key],
        added["generation"],
        now,
    )
    assert repaired["repaired"] is True
    assert repaired["control"]["initialized"] is True

    with scheduler_database.transaction() as transaction:
        status_changed = database_utility._update_deferred_job_scheduler_tracking(
            transaction,
            job_key,
            {"status": "running", "dispatch_state": "claimed"},
            {"status": "succeeded", "dispatch_state": "delivery_pending"},
            now,
        )
    assert status_changed["active_jobs"] == 1
    assert status_changed["generation"] > repaired["control"]["generation"]
    assert _control()["active_jobs"] == 1

    with scheduler_database.transaction() as transaction:
        removed = database_utility._update_deferred_job_scheduler_tracking(
            transaction,
            job_key,
            {"status": "succeeded", "dispatch_state": "delivery_pending"},
            {"status": "succeeded", "dispatch_state": "complete"},
            now,
        )
    assert removed["tracked_jobs"] == []
    assert removed["active_jobs"] == 0
    assert removed["desired_state"] == "paused"


# @features deferred-jobs cloud-scheduler
# @dimensions bootstrap drift-repair optimistic-concurrency state-read defaults
def test_scheduler_control_repair_is_revision_checked(scheduler_database):
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    job_key = _job_key()
    assert _control() == {
        "schema_version": 0,
        "initialized": False,
        "tracked_jobs": [],
        "active_jobs": 0,
        "desired_state": "enabled",
        "generation": 0,
        "applied_generation": 0,
        "applied_state": None,
        "sync_lease_token": None,
        "sync_lease_expires": None,
    }

    with scheduler_database.transaction() as transaction:
        database_utility._update_deferred_job_scheduler_tracking(
            transaction,
            job_key,
            None,
            {"status": "queued", "dispatch_state": "pending"},
            now,
        )

    raced = database_utility.repair_deferred_job_scheduler_control(
        [],
        0,
        now,
    )
    assert raced["repaired"] is False
    assert raced["reason"] == "generation"
    assert raced["control"]["tracked_jobs"] != []

    repaired = database_utility.repair_deferred_job_scheduler_control(
        [job_key],
        raced["control"]["generation"],
        now,
    )
    assert repaired["repaired"] is True
    assert repaired["control"]["initialized"] is True
    assert repaired["control"]["tracked_jobs"] == _control()["tracked_jobs"]


# @features deferred-jobs cloud-scheduler
# @dimensions exact-resource provider-api pause resume idempotency
def test_scheduler_provider_pause_and_resume_use_exact_job_resource():
    config = SimpleNamespace(
        GOOGLE_CLOUD_PROJECT="project-one",
        RESOURCE_REGION="us-central1",
    )
    session = FakeSchedulerSession("enabled")

    assert (
        deferred_job_scheduler.set_scheduler_state(
            "paused", session=session, config=config
        )
        == "paused"
    )
    assert (
        deferred_job_scheduler.set_scheduler_state(
            "enabled", session=session, config=config
        )
        == "enabled"
    )

    resource = (
        "https://cloudscheduler.googleapis.com/v1/projects/project-one/"
        "locations/us-central1/jobs/lagniappe-deferred-jobs-reconciler"
    )
    assert [call[:2] for call in session.calls] == [
        ("GET", resource),
        ("POST", f"{resource}:pause"),
        ("GET", resource),
        ("POST", f"{resource}:resume"),
    ]


# @features deferred-jobs cloud-scheduler
# @dimensions distributed-lease generation race convergence provider-state
def test_scheduler_sync_serializes_state_changes_and_converges_latest_generation(
    scheduler_database,
):
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    empty = database_utility.repair_deferred_job_scheduler_control([], 0, now)
    assert empty["control"]["desired_state"] == "enabled"
    empty = database_utility.repair_deferred_job_scheduler_control(
        [], empty["control"]["generation"], now
    )
    assert empty["control"]["desired_state"] == "paused"
    job_key = _job_key()

    def create_job_while_pause_is_in_flight():
        with scheduler_database.transaction() as transaction:
            database_utility._update_deferred_job_scheduler_tracking(
                transaction,
                job_key,
                None,
                {"status": "queued", "dispatch_state": "pending"},
                now,
            )

    session = FakeSchedulerSession(
        "enabled",
        before_change=create_job_while_pause_is_in_flight,
    )
    config = SimpleNamespace(
        production=True,
        GOOGLE_CLOUD_PROJECT="project-one",
        RESOURCE_REGION="us-central1",
    )

    result = deferred_job_scheduler.synchronize_deferred_job_reconciler(
        force=True,
        config=config,
        session=session,
        now_fn=lambda: now,
        sleep=lambda _delay: None,
    )

    assert result["synchronized"] is True
    assert result["control"]["desired_state"] == "enabled"
    assert result["control"]["applied_state"] == "enabled"
    assert result["control"]["applied_generation"] == result["control"]["generation"]
    assert [
        url.rsplit(":", 1)[-1]
        for method, url, _timeout in session.calls
        if method == "POST"
    ] == [
        "pause",
        "resume",
    ]


# @features deferred-jobs cloud-scheduler
# @dimensions distributed-lease provider-failure
def test_scheduler_sync_releases_lease_after_provider_failure(scheduler_database):
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    database_utility.repair_deferred_job_scheduler_control([], 0, now)
    config = SimpleNamespace(
        production=True,
        GOOGLE_CLOUD_PROJECT="project-one",
        RESOURCE_REGION="us-central1",
    )

    with pytest.raises(
        deferred_job_scheduler.DeferredJobSchedulerError,
        match="could not be read or changed",
    ):
        deferred_job_scheduler.synchronize_deferred_job_reconciler(
            force=True,
            config=config,
            session=FakeSchedulerSession(failure=RuntimeError("provider down")),
            now_fn=lambda: now,
            sleep=lambda _delay: None,
        )

    control = _control()
    assert control["sync_lease_token"] is None
    assert control["sync_lease_expires"] is None


# @features deferred-jobs cloud-scheduler
# @dimensions resume-failure pause-failure recovery-guarantee
def test_registry_requires_resume_but_tolerates_pause_failure(monkeypatch):
    registry = deferred_jobs.DeferredJobRegistry()
    captured = []

    def fail(**_kwargs):
        raise deferred_job_scheduler.DeferredJobSchedulerError("provider down")

    monkeypatch.setattr(
        deferred_jobs.deferred_job_scheduler,
        "synchronize_deferred_job_reconciler",
        fail,
    )
    monkeypatch.setattr(
        deferred_jobs.exceptions,
        "capture",
        lambda error, **kwargs: captured.append((error, kwargs)),
    )

    assert registry._sync_reconciler(required=False) is None
    with pytest.raises(
        deferred_jobs.DeferredJobInfrastructureError,
        match="recovery could not be enabled",
    ):
        registry._sync_reconciler(required=True)
    assert len(captured) == 2


# @features deferred-jobs cloud-scheduler
# @dimensions bootstrap drift-repair optimistic-concurrency self-pause
def test_reconciler_repairs_control_before_self_pausing(monkeypatch):
    registry = deferred_jobs.DeferredJobRegistry()
    repaired = []
    monkeypatch.setattr(deferred_jobs, "CONFIG", SimpleNamespace(production=True))
    monkeypatch.setattr(registry, "_reconcile_candidates", lambda limit: [])
    monkeypatch.setattr(
        deferred_jobs.database,
        "get_deferred_job_scheduler_control",
        lambda: {"generation": 4},
    )

    def repair(keys, generation, now):
        repaired.append((keys, generation, now))
        return {
            "repaired": True,
            "control": {"desired_state": "paused", "generation": 5},
        }

    monkeypatch.setattr(
        deferred_jobs.database,
        "repair_deferred_job_scheduler_control",
        repair,
    )
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)

    assert registry._repair_reconciler_control(now) == []
    assert repaired == [([], 4, now)]
