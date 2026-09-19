"""Cancellation reads and lease heartbeats remain independent and fenced."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from google.cloud.datastore import Key
import pytest

from lagniappe.core.tools.database import deferred_jobs as database
from lagniappe.core.tools.deferred_jobs import control as control_module
from lagniappe.core.tools.deferred_jobs import runner as runner_module
from lagniappe.core.tools.deferred_jobs.control import DeferredExecutionControl, _DeferredLeaseGuard
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobClaimLostError,
    DeferredJobDeadlineError,
    DeferredJobInfrastructureError,
)
from lagniappe.core.tools.deferred_jobs.service import DeferredJobService
from testing.utility.deferred_job_fakes import KeyedDatastore, KeyedEntity

pytestmark = pytest.mark.unit


class CountingDatastore(KeyedDatastore):
    def __init__(self, *entities):
        super().__init__(*entities)
        self.reads = []

    def get(self, key, transaction=None):
        self.reads.append((key, transaction))
        if transaction is None:
            return deepcopy(self.entities.get(key))
        return super().get(key, transaction=transaction)


@pytest.fixture
def claimed_job(monkeypatch):
    now = [datetime(2026, 9, 19, tzinfo=timezone.utc)]
    key = Key("jobs", "claimed", project="test-project")
    row = KeyedEntity(
        key, status="running", lease_token="worker-one",
        lease_expires=now[0] + timedelta(minutes=5), modified=now[0],
    )
    store = CountingDatastore(row)
    monkeypatch.setattr(database, "DATA", SimpleNamespace(datastore=store))
    monkeypatch.setattr(control_module, "_utc", lambda: now[0])
    monkeypatch.setattr(runner_module, "_utc", lambda: now[0])
    job = SimpleNamespace(key=key, lease_expires=row["lease_expires"])
    registry = DeferredJobService()
    control = DeferredExecutionControl(
        deadline_at=now[0] + timedelta(minutes=9),
        active_check=lambda: registry._claim_active(job, "worker-one"),
        progress_callback=lambda _progress: None,
    )
    return SimpleNamespace(
        now=now, row=row, store=store, job=job, registry=registry, control=control,
    )


# @matrix deferred-jobs : cancellation lease read-path
@pytest.mark.parametrize(
    "state, token, expected",
    [
        ("running", "worker-one", True),
        ("running", "replacement", False),
        ("cancelled", None, False),
        ("superseded", None, False),
        ("missing", None, False),
        ("invalid-key", None, False),
        ("succeeded", "worker-one", True),  # Terminal delivery still owns the token.
    ],
)
def test_claim_checks_observe_durable_ownership_without_writes(claimed_job, state, token, expected):
    case = claimed_job
    case.row.update(status=state, lease_token=token)
    key = case.job.key
    if state == "missing":
        del case.store.entities[key]
    elif state == "invalid-key":
        key = None
    before = deepcopy(case.store.entities)

    assert database.owns_deferred_job_claim(key, "worker-one") is expected

    assert case.store.entities == before
    assert case.store.saved == []
    assert case.store.reads == ([] if key is None else [(key, None)])


# @matrix deferred-jobs : cancellation heartbeat read-path
def test_blocking_work_renews_only_on_the_heartbeat_cadence(claimed_job):
    case = claimed_job
    started = case.now[0]
    guard = _DeferredLeaseGuard(case.registry, case.job, "worker-one", case.control)

    def wait(seconds):
        assert seconds == 60
        if case.now[0] == started + timedelta(minutes=3):
            return True
        # Simulate one-second provider checks between real heartbeat iterations.
        for _ in range(60):
            case.now[0] += timedelta(seconds=1)
            case.control.ensure_active()
        return False

    guard.stop_event = SimpleNamespace(wait=wait)
    guard._run()

    assert sum(transaction is None for _, transaction in case.store.reads) == 180
    assert sum(transaction is not None for _, transaction in case.store.reads) == 3
    assert len(case.store.saved) == 3
    assert case.row["lease_expires"] == started + timedelta(minutes=8)
    assert case.row["modified"] == started + timedelta(minutes=3)
    assert case.job.lease_expires == started + timedelta(minutes=5)


# @matrix deferred-jobs : cancellation heartbeat lease-loss
@pytest.mark.parametrize("loss", ["cancelled", "superseded", "replacement", "deleted"])
def test_claim_loss_stops_checks_and_prevents_heartbeat_renewal(claimed_job, loss):
    case = claimed_job
    case.control.ensure_active()
    if loss == "deleted":
        del case.store.entities[case.job.key]
    elif loss == "replacement":
        case.row["lease_token"] = "worker-two"
    else:
        case.row.update(status=loss, lease_token=None)
    before = deepcopy(case.store.entities)

    with pytest.raises(DeferredJobClaimLostError):
        case.control.ensure_active()
    assert len(case.store.reads) == 2  # Every active boundary checks current ownership.
    with pytest.raises(DeferredJobClaimLostError):
        case.control.ensure_active()
    assert len(case.store.reads) == 2  # Known loss needs no further I/O.

    assert case.registry._renew_claim(case.job, "worker-one") is False
    assert case.store.entities == before
    assert case.store.saved == []


# @matrix deferred-jobs : read-path lease-loss
def test_activity_lookup_failure_is_an_infrastructure_error(claimed_job, monkeypatch):
    case = claimed_job
    error = RuntimeError("Datastore unavailable")
    monkeypatch.setattr(case.store, "get", Mock(side_effect=error))

    with pytest.raises(DeferredJobInfrastructureError, match="activity could not be verified") as caught:
        case.control.ensure_active()

    assert caught.value.__cause__ is error
    assert case.store.saved == []


# @matrix deferred-jobs : cancellation deadline heartbeat
@pytest.mark.parametrize(
    "stop, expected_error",
    [
        ("deadline", DeferredJobDeadlineError),
        ("claim-loss", DeferredJobClaimLostError),
        ("heartbeat-error", DeferredJobInfrastructureError),
    ],
)
def test_local_stop_state_prevents_activity_reads(claimed_job, stop, expected_error):
    case = claimed_job
    if stop == "deadline":
        case.now[0] = case.control.deadline_at
    elif stop == "claim-loss":
        case.control.mark_lost()
    else:
        case.control.mark_background_error(RuntimeError("Heartbeat unavailable"))

    with pytest.raises(expected_error):
        case.control.ensure_active()

    assert case.store.reads == []
    assert case.store.saved == []


# @matrix deferred-jobs : cancellation deadline heartbeat
@pytest.mark.parametrize(
    "stop, expected_error",
    [
        ("deadline", DeferredJobDeadlineError),
        ("claim-loss", DeferredJobClaimLostError),
        ("heartbeat-error", DeferredJobInfrastructureError),
    ],
)
def test_local_stop_during_activity_read_is_observed(claimed_job, monkeypatch, stop, expected_error):
    case = claimed_job

    def read(_key):
        if stop == "deadline":
            case.now[0] = case.control.deadline_at
        elif stop == "claim-loss":
            case.control.mark_lost()
        else:
            case.control.mark_background_error(RuntimeError("Heartbeat unavailable"))
        return case.row

    monkeypatch.setattr(case.store, "get", read)
    with pytest.raises(expected_error):
        case.control.ensure_active()
    assert case.store.saved == []
