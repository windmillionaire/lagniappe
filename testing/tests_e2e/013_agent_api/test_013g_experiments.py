"""HTTP execution gates and request measurement lifecycle for experiments."""

import json
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
from lagniappe.web.experiments import initialize_measurements
from lagniappe.web.routes.api import main as api

pytestmark = pytest.mark.e2e


# @matrix experiments : http-execution
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
    monkeypatch.setattr(api, "_rate_limit", lambda *args: None)
    monkeypatch.setattr(
        api, "_load_plan", lambda identifier: SimpleNamespace(id=identifier)
    )
    monkeypatch.setattr(api, "_plan_payload", lambda plan: {"id": plan.id})
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


# @matrix experiments : request-measurements
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
