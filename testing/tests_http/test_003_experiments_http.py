"""HTTP execution gates and request measurement lifecycle for experiments."""

import json
from copy import deepcopy
from types import SimpleNamespace

from flask import Flask, render_template_string
import pytest

from config.remote_mcp import USER_TOKEN_HEADER
from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.tools import measurements
from lagniappe.core.tools.ai.reporting.execution import request as execution
from lagniappe.core.tools.auth import agent_api, remote_mcp
from lagniappe.web import app
from lagniappe.web.experiments import initialize_measurements, task_list_context_keys
from lagniappe.web.routes.api import main as api

pytestmark = pytest.mark.http


def test_experiments_execute_requires_remote_admin_and_exact_proposal(monkeypatch):
    actor = SimpleNamespace(
        email=CONFIG.AGENT_ACCESS_EMAIL,
        key="actor-key",
        urlsafe_key="actor-key",
        is_authenticated=True,
        is_public=False,
        is_admin=True,
    )
    for name, value in {
        "EXPERIMENTS_ENABLED": True,
        "EXPERIMENTS_EXECUTION_ENABLED": True,
        "EXPERIMENTS_PROJECT": CONFIG.GOOGLE_CLOUD_PROJECT,
        "AGENT_ACCESS_ENABLED": True,
        "AI_ENABLED": True,
        "EXTERNAL_AI_ENABLED": True,
    }.items():
        monkeypatch.setattr(CONFIG, name, value)
    monkeypatch.setattr(agent_api, "authenticate_credential", lambda token: (actor, {}))
    monkeypatch.setattr(remote_mcp, "authenticate_envelope", lambda *args: (actor, {}))
    monkeypatch.setattr(
        api, "_load_plan", lambda identifier: SimpleNamespace(id=identifier)
    )
    monkeypatch.setattr(api, "_plan_payload", lambda plan, **kwargs: {"id": plan.id})
    calls = []

    def execute(report, user, **kwargs):
        calls.append(kwargs)
        if kwargs["expected_fingerprint"] != "f" * 64:
            raise exceptions.ValidationError("The submitted proposal changed.")
        return SimpleNamespace(
            idempotency_key=kwargs["operation_id"], status="queued"
        ), None

    monkeypatch.setattr(execution, "request_execution", execute)
    client = app.test_client()
    url = "/api/v1/plans/experiment-plan/execute"
    body = {"proposal_fingerprint": "f" * 64, "operation_id": "installation.setup-1"}
    direct = {"Authorization": "Bearer direct-key"}
    remote = {"Authorization": "Bearer service-token", USER_TOKEN_HEADER: "oauth-token"}
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, json=body, headers=direct).status_code == 403
    actor.is_admin = False
    assert client.post(url, json=body, headers=remote).status_code == 403
    actor.is_admin = True
    assert calls == []
    response = client.post(url, json=body, headers=remote)
    assert response.status_code == 202
    assert response.json["operation"] == {
        "id": "installation.setup-1",
        "status": "queued",
    }
    assert calls[-1]["remote_mcp"] is True
    assert (
        client.post(
            url, json={**body, "proposal_fingerprint": "0" * 64}, headers=remote
        ).status_code
        == 422
    )
    before = len(calls)
    assert (
        client.post(
            url, json={**body, "operation_id": "invalid/path"}, headers=remote
        ).status_code
        == 422
    )
    monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", False)
    assert client.post(url, json=body, headers=remote).status_code == 403
    assert len(calls) == before


@pytest.mark.parametrize("execute,field_type", [(False, "todo"), (True, "signature")])
def test_submit_rejects_invalid_page_form_before_saving_or_queueing(monkeypatch, execute, field_type):
    from lagniappe.core.tools.ai.external import plans
    from testing.utility.ai_report_fakes import _patch_fake_keys, _test_user
    from testing.utility.test_entities import TestEntities

    plans.Entities.initialize()
    TestEntities.initialize(plans.Entities)
    _patch_fake_keys(monkeypatch)
    actor = _test_user("form-plan-owner")
    monkeypatch.setattr(CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(agent_api, "authenticate_credential", lambda token: (actor, {}))
    monkeypatch.setattr(plans.Entities, "save", lambda *items: None)
    report = plans.create_plan(actor, instructions="Create a Page form.")
    if execute:
        plans.submit_plan(
            report, actor, {"summary": "Earlier review", "confidence": 1, "actions": [
                {"id": "review", "type": "needs_review", "data": {"reason": "Review the form."}},
            ]}, contract_version=plans.CONTRACT_VERSION, file_usage=[],
        )
    previous = deepcopy((report.status, report.proposal, report.agent_manifest))

    def reject_save(*items):
        pytest.fail("Invalid revision was saved")

    monkeypatch.setattr(plans.Entities, "fetch_one", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        plans.agent_api_store, "claim_plan_operation",
        lambda *args, **kwargs: plans.agent_api_store.PLAN_OPERATION_CLAIMED,
    )
    monkeypatch.setattr(plans, "release_plan_operation_claim", lambda *a, **k: None)
    monkeypatch.setattr(plans, "claimed_plan_save", lambda *args, **kwargs: reject_save)
    monkeypatch.setattr(execution, "request_execution", lambda *a, **k: pytest.fail("Invalid revision queued execution"))

    body = {
        "contract_version": plans.CONTRACT_VERSION, "file_usage": [],
        "proposal": {"summary": "Add forms", "confidence": 1, "actions": [
            {"id": "page-form", "type": "create_form", "data": {
                "name": "Page details", "form_type": "page",
                "schema": [{"id": "field_custom", "type": field_type, "title": "Details"}],
            }},
        ]},
    }
    if execute:
        body.update(execute=True, operation_id="attempt-invalid-form")
    response = app.test_client().post(
        f"/api/v1/plans/{report.urlsafe_key}/submit",
        headers={"Authorization": "Bearer form-plan-token"}, json=body,
    )
    assert response.status_code == 422, response.json
    assert response.json["error"]["code"] == "validation_failed"
    message = response.json["error"]["message"]
    assert "page-form" in message and "field_custom" in message and "only on task forms" in message
    assert (report.status, report.proposal, report.agent_manifest) == previous


def test_app_wide_auto_execute_api_key_compact_get_and_one_step_submit(monkeypatch):
    from lagniappe.core.tools.ai import auto_execute

    actor = SimpleNamespace(
        email="member@example.test",
        key="member-key",
        urlsafe_key="member-key",
        hash="memberhash12",
        name="Member",
        db={"timezone": "UTC"},
        page=SimpleNamespace(
            hash="memberhash12",
            name="Member",
            url="/pages/member",
            allowed=lambda *_a, **_k: True,
        ),
        is_authenticated=True,
        is_active=True,
        is_public=False,
        is_admin=False,
        allow_auto_execute=True,
    )
    monkeypatch.setattr(CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", False)
    monkeypatch.setattr(
        auto_execute,
        "runtime_ai_settings",
        lambda config=CONFIG: {"AI_AUTO_EXECUTE": True},
    )
    monkeypatch.setattr(agent_api, "authenticate_credential", lambda token: (actor, {"active": True}))

    plan_calls = []

    def fake_plan_payload(plan, *, include_proposal=True):
        plan_calls.append(include_proposal)
        return {
            "id": plan.urlsafe_key,
            "status": plan.status,
            "preview_url": "https://example.test/tools/api-plan/plan-1",
            "review_url": "https://example.test/tools/reports/plan-1",
            "status_url": "https://example.test/api/v1/plans/plan-1",
            "contract_version": 10,
            "proposal": {"summary": "full"} if include_proposal else None,
        }

    report = SimpleNamespace(
        urlsafe_key="plan-1",
        status="ready",
        available=True,
        output_kind="proposal",
        proposal={"summary": "Create a task", "actions": [{"id": "a1", "type": "create_task", "data": {}}], "issues": []},
        agent_manifest={"proposal_fingerprint": "f" * 64},
    )
    monkeypatch.setattr(api, "_load_plan", lambda identifier: report)
    monkeypatch.setattr(api, "_plan_payload", fake_plan_payload)
    monkeypatch.setattr(api.external_api, "require_submission_available", lambda _r: None)

    def fake_request_execution(r, u, **kwargs):
        r.status = "running"
        return (
            SimpleNamespace(idempotency_key=kwargs["operation_id"], status="queued"),
            None,
        )

    monkeypatch.setattr(execution, "request_execution", fake_request_execution)

    client = app.test_client()
    headers = {"Authorization": "Bearer direct-key"}

    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json["capabilities"] == {"plans": True, "execute_plan": True}

    compact = client.get("/api/v1/plans/plan-1?include_proposal=false", headers=headers)
    assert compact.status_code == 200
    assert compact.json["proposal"] is None
    assert plan_calls[-1] is False

    full = client.get("/api/v1/plans/plan-1", headers=headers)
    assert full.status_code == 200
    assert full.json["proposal"] == {"summary": "full"}
    assert plan_calls[-1] is True

    executed = client.post(
        "/api/v1/plans/plan-1/execute",
        headers=headers,
        json={"proposal_fingerprint": "f" * 64, "operation_id": "direct-op-1"},
    )
    assert executed.status_code == 202
    assert executed.json["plan"]["proposal"] is None
    assert plan_calls[-1] is False
    assert executed.json["operation"] == {"id": "direct-op-1", "status": "queued"}

    # One-step submit with execute=True (safe -> starts execution)
    monkeypatch.setattr(
        api.external_api,
        "submit_plan_request",
        lambda *_a, **_k: report,
    )
    submitted_run = client.post(
        "/api/v1/plans/plan-1/submit",
        headers=headers,
        json={
            "contract_version": 10,
            "proposal": {},
            "file_usage": [],
            "execute": True,
            "operation_id": "one-step-1",
        },
    )
    assert submitted_run.status_code == 200
    assert submitted_run.json["status"] == "running"
    assert submitted_run.json["operation"] == {"id": "one-step-1", "status": "queued"}
    assert submitted_run.json["execution"] == {"started": True}

    # One-step submit with execute=True on a safety-paused proposal -> stays ready with pause reason
    report.status = "ready"
    report.proposal = {
        "summary": "Schema change",
        "actions": [{"id": "a1", "type": "update_form_schema", "data": {}}],
        "issues": [],
    }
    submitted_paused = client.post(
        "/api/v1/plans/plan-1/submit",
        headers=headers,
        json={
            "contract_version": 10,
            "proposal": {},
            "file_usage": [],
            "execute": True,
            "operation_id": "one-step-2",
        },
    )
    assert submitted_paused.status_code == 200
    assert submitted_paused.json["status"] == "ready"
    assert submitted_paused.json["execution"]["started"] is False
    assert "form schema" in submitted_paused.json["execution"]["reason"].lower()

    # Designated experiments agent over remote MCP bypasses allow_auto_execute,
    # site AI_AUTO_EXECUTE, and the normal-user safety pause on one-step submit.
    agent_actor = SimpleNamespace(
        email=CONFIG.AGENT_ACCESS_EMAIL,
        key="agent-key",
        urlsafe_key="agent-key",
        hash="agenthash123",
        name="Agent",
        db={"timezone": "UTC"},
        page=SimpleNamespace(
            hash="agenthash123",
            name="Agent",
            url="/pages/agent",
            allowed=lambda *_a, **_k: True,
        ),
        is_authenticated=True,
        is_active=True,
        is_public=False,
        is_admin=True,
        allow_auto_execute=False,
    )
    for name, value in {
        "EXPERIMENTS_ENABLED": True,
        "EXPERIMENTS_EXECUTION_ENABLED": True,
        "EXPERIMENTS_PROJECT": CONFIG.GOOGLE_CLOUD_PROJECT,
        "AGENT_ACCESS_ENABLED": True,
    }.items():
        monkeypatch.setattr(CONFIG, name, value)
    monkeypatch.setattr(
        auto_execute,
        "runtime_ai_settings",
        lambda config=CONFIG: {"AI_AUTO_EXECUTE": False},
    )
    monkeypatch.setattr(
        remote_mcp, "authenticate_envelope", lambda *args: (agent_actor, {"active": True})
    )
    remote_headers = {
        "Authorization": "Bearer service-token",
        USER_TOKEN_HEADER: "oauth-token",
    }
    agent_me = client.get("/api/v1/me", headers=remote_headers)
    assert agent_me.status_code == 200
    assert agent_me.json["capabilities"] == {"plans": True, "execute_plan": True}

    report.status = "ready"
    submitted_agent = client.post(
        "/api/v1/plans/plan-1/submit",
        headers=remote_headers,
        json={
            "contract_version": 10,
            "proposal": {},
            "file_usage": [],
            "execute": True,
            "operation_id": "one-step-agent-schema",
        },
    )
    assert submitted_agent.status_code == 200
    assert submitted_agent.json["status"] == "running"
    assert submitted_agent.json["execution"] == {"started": True}
    assert submitted_agent.json["operation"] == {
        "id": "one-step-agent-schema",
        "status": "queued",
    }


@pytest.mark.parametrize(
    "enabled,mode", [(False, "off"), (True, "off"), (True, "summary"), (True, "trace")]
)
def test_experiments_request_headers_and_private_log_summary(
    monkeypatch, enabled, mode
):
    flask_app = Flask("experiments-http-test")
    config = SimpleNamespace(
        EXPERIMENTS_ENABLED=enabled,
        EXPERIMENTS_DIAGNOSTICS=mode,
        EXPERIMENTS_SOURCE_ID="d" * 64,
    )
    records = []
    monkeypatch.setattr(measurements, "emit", records.append)
    initialize_measurements(flask_app, config)

    @flask_app.after_request
    def later_hook(response):
        with measurements.span("auth", "response_hook"):
            pass
        return response

    @flask_app.get("/fixture/<identifier>")
    def fixture(identifier):
        with measurements.span("entity", "fetch"):
            pass
        return render_template_string("Fixture ready")

    client = flask_app.test_client()
    response = client.get(
        "/fixture/private-record?secret=private-value",
        headers={"Authorization": "Bearer private-credential"},
    )
    assert response.status_code == 200
    assert measurements.CURRENT.get() is None
    if not enabled or mode == "off":
        assert "X-Lagniappe-Request-ID" not in response.headers
        assert records == []
        return
    assert len(records) == 1
    summary = records[0]
    assert summary["request_id"] == response.headers["X-Lagniappe-Request-ID"]
    assert response.headers["X-Lagniappe-Source-ID"] == "d" * 64
    assert "lagniappe;dur=" in response.headers["Server-Timing"]
    assert summary["route"] == "/fixture/<identifier>"
    assert summary["operations"]["auth.response_hook"]["calls"] == 1
    assert summary["operations"]["template.render"]["calls"] == 1
    assert summary["response_bytes"] == len(response.data)
    assert "private" not in json.dumps(summary)
    assert ("trace" in summary) == (mode == "trace")
    client.get("/fixture/second")
    assert records[1]["request_id"] != summary["request_id"]


def test_experiments_comparison_metadata_survives_304(monkeypatch):
    from lagniappe.core.tools.polling import task_lists

    flask_app = Flask("experiments-comparison-test")
    config = SimpleNamespace(
        EXPERIMENTS_ENABLED=True, EXPERIMENTS_DIAGNOSTICS="summary",
        EXPERIMENTS_SOURCE_ID="d" * 64,
    )
    records = []
    monkeypatch.setattr(measurements, "emit", records.append)
    monkeypatch.setattr(
        task_lists,
        "DATA",
        SimpleNamespace(datastore=SimpleNamespace(key=lambda *parts: parts)),
    )
    initialize_measurements(flask_app, config)

    @flask_app.get("/fixture")
    def fixture():
        task_list_context_keys()
        return "", 304

    client = flask_app.test_client()
    for enabled, variant, expected in (
        (True, "unbatched", "p5-01:unbatched"),
        (True, "batched", "p5-01:batched"),
        (True, "invalid-private-value", None),
        (False, "unbatched", None),
    ):
        monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", enabled)
        response = client.get("/fixture", headers={"X-Lagniappe-Experiments-Task-List": variant})
        assert response.status_code == 304 and response.data == b""
        assert response.headers.get("X-Lagniappe-Experiment") == expected
        assert records[-1].get("experiment") == expected
        assert (isinstance(records[-1].get("process"), int)) == bool(expected)
        assert "invalid-private-value" not in json.dumps(records[-1])
