"""Account, execution and measurement contracts with no live resources."""

from contextvars import copy_context
import hashlib
import json
from types import SimpleNamespace

from google.cloud.datastore import Entity, Key
import pytest

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint
from lagniappe.core.tools import experiments, measurements

pytestmark = pytest.mark.unit


def _enable(monkeypatch):
    for key, value in {
        "EXPERIMENTS_ENABLED": True,
        "EXPERIMENTS_EXECUTION_ENABLED": True,
        "EXPERIMENTS_PROJECT": CONFIG.GOOGLE_CLOUD_PROJECT,
        "AI_ENABLED": True,
        "EXTERNAL_AI_ENABLED": True,
        "AGENT_ACCESS_ENABLED": True,
        "AGENT_ACCESS_EMAIL": "agent@example.test",
    }.items():
        monkeypatch.setattr(CONFIG, key, value)
    return SimpleNamespace(
        email="agent@example.test",
        is_admin=True,
        is_authenticated=True,
        is_public=False,
        key="agent-key",
        urlsafe_key="agent-key",
    )


# @matrix experiments : execution-policy
def test_execution_requires_designated_admin_and_current_policy(monkeypatch):
    actor = _enable(monkeypatch)
    assert experiments.can_execute(actor, remote_mcp=True)
    assert not experiments.can_execute(actor)
    for setting, value in (
        ("EXPERIMENTS_ENABLED", False),
        ("EXPERIMENTS_EXECUTION_ENABLED", False),
        ("EXPERIMENTS_PROJECT", "other-project"),
        ("AI_ENABLED", False),
        ("EXTERNAL_AI_ENABLED", False),
        ("AGENT_ACCESS_ENABLED", False),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(CONFIG, setting, value)
            assert not experiments.can_execute(actor, remote_mcp=True)
    for field, value in (
        ("email", "owner@example.test"),
        ("is_admin", False),
        ("is_authenticated", False),
        ("is_public", True),
    ):
        other = SimpleNamespace(**{**vars(actor), field: value})
        assert not experiments.can_execute(other, remote_mcp=True)


# @matrix experiments : bootstrap
@pytest.mark.parametrize("concurrent", [False, True])
def test_bootstrap_is_guarded_idempotent_and_preserves_roles(monkeypatch, concurrent):
    from config import Environment

    _enable(monkeypatch)
    monkeypatch.setattr(CONFIG, "ENV", Environment.PRODUCTION)
    monkeypatch.setattr(CONFIG, "ADMIN_EMAIL", "owner@example.test")
    rows, creations, guards_seen = {}, [], []

    def key(kind, identifier):
        return Key(kind, identifier, project="offline-tests")

    def create(data, *, key):
        creations.append(data)
        row = Entity(key)
        row.update(data, owner=data["email"] == CONFIG.ADMIN_EMAIL)
        return SimpleNamespace(key=key, db=row)

    def save(plan, *, guards):
        guards_seen.extend(guards)
        rows[plan.key] = plan.db
        if concurrent:
            raise exceptions.MutationConflict("Another worker created this account")
        return SimpleNamespace(post_commit_complete=True)

    client = SimpleNamespace(
        key=key, get=rows.get, put=lambda row: rows.__setitem__(row.key, row)
    )
    monkeypatch.setattr(experiments, "DATA", SimpleNamespace(datastore=client))
    monkeypatch.setattr(
        experiments, "Entities", SimpleNamespace(USER=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(
        experiments, "plan_mutation", lambda operation, user, **kwargs: user
    )
    monkeypatch.setattr(experiments, "execute_mutation", save)
    experiments.bootstrap()
    assert len(creations) == 2
    assert creations[1]["admin"] is True
    assert all(previous is None for _, previous in guards_seen)
    state = rows[key(experiments.KINDS.site.value, "experiments-bootstrap")]
    assert rows[state["owner"]]["owner"] is True
    assert rows[state["agent"]]["admin"] is True
    rows[state["agent"]]["admin"] = False
    experiments.bootstrap()
    assert len(creations) == 2
    assert rows[state["agent"]]["admin"] is False
    rows.pop(state["agent"])
    experiments.bootstrap()
    assert state["agent"] not in rows  # deliberate deletion is not undone
    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_EMAIL", "another@example.test")
    with pytest.raises(RuntimeError, match="identities"):
        experiments.bootstrap()


# @matrix experiments : execution-policy
def test_execution_rejects_stale_proposals_and_reuses_exact_operations(monkeypatch):
    from lagniappe.core.tools.ai.reporting.execution import request as execution
    from lagniappe.core.tools.ai.reporting import corrections, schema_updates
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobService

    actor = _enable(monkeypatch)
    report = SimpleNamespace(
        available=True,
        allowed=lambda *args, **kwargs: True,
        db={},
        origin="api",
        entity_kind="report",
        properties=SimpleNamespace(user=SimpleNamespace(key=actor.key)),
        proposal={"actions": []},
        result=None,
        status="ready",
        upload_manifest=None,
        urlsafe_key="report-key",
    )
    started, prepared = [], []
    monkeypatch.setattr(
        execution.database_utility, "create_named_key", lambda *args: "job-key"
    )
    monkeypatch.setattr(execution.Entities, "fetch_one", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        schema_updates,
        "prepare_schema_updates",
        lambda *args, **kwargs: prepared.append(True),
    )
    monkeypatch.setattr(corrections, "approve_correction", lambda *args: None)
    monkeypatch.setattr(
        execution.DeferredJobs,
        "start",
        lambda spec: started.append(spec) or ("job", None),
    )
    kwargs = {
        "operation_id": "save-1",
        "expected_fingerprint": proposal_fingerprint(report.proposal),
        "remote_mcp": True,
    }
    report.agent_manifest = {"proposal_fingerprint": kwargs["expected_fingerprint"]}
    with pytest.raises(exceptions.ValidationError, match="proposal changed"):
        execution.request_execution(
            report, actor, **{**kwargs, "expected_fingerprint": "0" * 64}
        )
    assert started == []
    assert execution.request_execution(report, actor, **kwargs) == ("job", None)
    assert len(prepared) == 1
    assert started[0].parameters == {"experiments_execution": True}

    # Use the real deferred service for replay: its complete request identity
    # must still match the original receipt after execution normalized the copy.
    accepted = {
        "job_type": "report-execution",
        "actor": "agent-key",
        "authorization": {
            "policy": "report-execution",
            "actor": "agent-key",
            "inputs": {"report": {"kind": "report", "id": "report-key"}},
            "proposal_fingerprint": kwargs["expected_fingerprint"],
        },
        "inputs": {"report": {"kind": "report", "id": "report-key"}},
        "parameters": {"experiments_execution": True},
        "client": {
            "key": "report-key",
            "source_widget": "CreateToolReport",
            "destination": "tools:ToolReportList",
        },
    }
    existing = SimpleNamespace(
        request_fingerprint=hashlib.sha256(
            json.dumps(accepted, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        status="succeeded",
        notification=None,
    )
    report.status = "complete"
    report.proposal = {"actions": [], "summary": "Legacy execution normalized this"}
    monkeypatch.setattr(
        execution.Entities, "fetch_one", lambda *args, **kwargs: existing
    )
    monkeypatch.setattr(execution, "DeferredJobs", DeferredJobService())
    assert execution.request_execution(report, actor, **kwargs) == (existing, None)
    assert len(prepared) == 1  # exact retry reaches the existing service receipt
    with pytest.raises(exceptions.ValidationError, match="proposal changed"):
        execution.request_execution(
            report, actor, **{**kwargs, "expected_fingerprint": "0" * 64}
        )
    report.urlsafe_key = "other-report"
    with pytest.raises(exceptions.ValidationError, match="different request"):
        execution.request_execution(report, actor, **kwargs)
    report.urlsafe_key = "report-key"
    monkeypatch.setattr(execution.Entities, "fetch_one", lambda *args, **kwargs: None)
    with pytest.raises(exceptions.ValidationError, match="proposal changed"):
        execution.request_execution(report, actor, **kwargs)
    actor.is_admin = False
    with pytest.raises(exceptions.ValidationError, match="unavailable"):
        execution.request_execution(report, actor, **kwargs)


# @source lagniappe/core/tools/deferred_jobs/adapters/reports.py::ReportExecutionAdapter
# @matrix deferred-jobs : report-execution
def test_execution_rechecks_admin_role_at_ledger_boundaries(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.adapters.reports import (
        ReportExecutionAdapter,
        Entities,
    )

    actor = _enable(monkeypatch)
    context = SimpleNamespace(
        actor=actor,
        parameters={"experiments_execution": True},
        ensure_active=lambda: None,
    )
    monkeypatch.setattr(Entities, "fetch_one", lambda *args, **kwargs: actor)
    adapter = ReportExecutionAdapter()
    adapter._ensure_execution_active(context)
    actor.is_admin = False
    with pytest.raises(exceptions.ValidationError, match="no longer allowed"):
        adapter._ensure_execution_active(context)


# @matrix experiments : request-measurements
def test_measurements_are_bounded_private_and_context_local():
    assert measurements.CURRENT.get() is None
    with measurements.span("auth", "context"):
        pass
    measurement = measurements.Measurement("trace")
    token = measurements.CURRENT.set(measurement)
    try:
        for _ in range(measurements.TRACE_LIMIT + 4):
            with measurements.span("auth", "context"):
                pass
        with pytest.raises(ValueError), measurements.span("datastore", "lookup"):
            raise ValueError("private payload must not be logged")
        assert measurement.summary()["operations"]["datastore.lookup"]["errors"] == 1
        assert len(measurement.trace) == measurements.TRACE_LIMIT
        assert measurement.dropped == 5
        assert "private" not in json.dumps(measurement.summary())
        copied = copy_context()
        copied.run(measurements.CURRENT.set, None)
        assert measurements.CURRENT.get() is measurement
    finally:
        measurements.CURRENT.reset(token)
    assert measurements.CURRENT.get() is None


# @matrix experiments : provider-measurements
def test_measurements_count_provider_calls_without_arguments():
    api = SimpleNamespace(
        lookup=lambda *args, **kwargs: SimpleNamespace(
            found=[1, 2], missing=[3], deferred=[]
        )
    )
    measurements.instrument_datastore(SimpleNamespace(_datastore_api=api))
    storage = SimpleNamespace(
        _http=SimpleNamespace(
            request=lambda *args, **kwargs: SimpleNamespace(status_code=200)
        )
    )
    measurements.instrument_storage(storage)
    pipe = SimpleNamespace(
        command_stack=[
            (("GET", "private-key"), {}),
            (("SET", "private-key", "private-value"), {}),
        ],
        execute=lambda: [None, True],
        immediate_execute_command=lambda *args, **kwargs: True,
    )
    redis = SimpleNamespace(
        execute_command=lambda *args, **kwargs: None, pipeline=lambda: pipe
    )
    measurements.instrument_redis(redis)
    measurement = measurements.Measurement("summary")
    token = measurements.CURRENT.set(measurement)
    try:
        api.lookup(request="private-query")
        storage._http.request(
            "GET", "https://private-object", headers={"Authorization": "private-secret"}
        )
        redis.execute_command("GET", "private-key")
        redis.pipeline().execute()
    finally:
        measurements.CURRENT.reset(token)
    summary = measurement.summary()
    assert summary["operations"]["datastore.lookup"]["found"] == 2
    assert summary["operations"]["storage.GET"]["calls"] == 1
    assert summary["operations"]["redis.GET"]["misses"] == 1
    assert summary["operations"]["redis.pipeline"]["calls"] == 1
    assert summary["operations"]["redis.pipeline"]["count"] == 2
    assert "private" not in json.dumps(summary)
    assert "trace" not in summary
