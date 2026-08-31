"""HTTP contract coverage for external-agent API and key management."""

from types import SimpleNamespace

import pytest

from lagniappe import CONFIG
from lagniappe.core.definitions import AI
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.web import app
from lagniappe.web import auth as web_auth
from lagniappe.web.routes.api import main as api_routes
from lagniappe.web.routes.users import api_key as api_key_routes
from lagniappe.web.routes.tools import main as tool_routes


pytestmark = pytest.mark.e2e


class Actor:
    name = "External Planner"
    hash = "actorhash123"
    urlsafe_key = "actor-key"
    key = "actor-datastore-key"
    ai_access = "CREATE"
    is_public = False
    is_authenticated = True

    def access(self, required):
        return required is AI.CREATE

    def _get_current_object(self):
        return self


def _report(actor):
    return SimpleNamespace(
        urlsafe_key="report-key",
        hash="reporthash12",
        status="draft",
        tool="organize",
        name="External plan",
        instructions="Organize these files.",
        input_files=[],
        upload_manifest=None,
        proposal=None,
        origin="api",
        properties=SimpleNamespace(user=SimpleNamespace(key=actor.key)),
    )


# @matrix agent-api : bearer-only contract error-envelope plan-session proposal-contract routing submission tool-catalog tool-dispatch uploads
def test_external_agent_api_requires_bearer_and_dispatches_as_bound_user(monkeypatch):
    actor = Actor()
    report = _report(actor)
    seen = {}
    monkeypatch.setattr(CONFIG, "EXTERNAL_AGENT_API_ENABLED", True)
    monkeypatch.setattr(
        api_routes,
        "check_limit",
        lambda *args: {
            "allowed": True,
            "count": 1,
            "remaining": 59,
            "retry_after": 60,
        },
    )
    monkeypatch.setattr(
        agent_auth,
        "authenticate_credential",
        lambda token: (
            (actor, {"active": True, "expires_at": "2026-09-30T00:00:00+00:00"})
            if token == "valid-key"
            else (_ for _ in ()).throw(
                agent_auth.AgentAPICredentialError("invalid")
            )
        ),
    )

    client = app.test_client()
    unauthorized = client.get("/api/v1/me")
    assert unauthorized.status_code == 401
    assert unauthorized.json["error"]["code"] == "unauthorized"
    assert unauthorized.headers["WWW-Authenticate"].startswith("Bearer")
    assert unauthorized.headers["Cache-Control"] == "no-store"

    authorized = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert authorized.status_code == 200
    assert authorized.json["user"] == {
        "name": actor.name,
        "hash": actor.hash,
        "ai_access": "CREATE",
    }
    assert authorized.json["capabilities"] == {"organize": True, "execute": False}

    openapi = client.get(
        "/api/v1/openapi.json",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert openapi.status_code == 200
    assert openapi.json["openapi"] == "3.1.0"
    assert "/api/v1/plans/{plan_id}/submit" in openapi.json["paths"]
    assert "does not execute proposed actions" in openapi.json["info"]["description"]
    assert "task=organize" in openapi.json["info"]["description"]
    operations = [
        operation
        for path in openapi.json["paths"].values()
        for operation in path.values()
    ]
    assert all(operation["operationId"] for operation in operations)
    assert all(operation["description"] for operation in operations)
    assert all(operation["responses"] for operation in operations)
    create_schema = openapi.json["paths"]["/api/v1/plans"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    assert create_schema["required"] == ["instructions"]
    upload_operation = openapi.json["paths"]["/api/v1/plans/{plan_id}/uploads"]["post"]
    assert upload_operation["requestBody"]["required"] is True
    tools_operation = openapi.json["paths"]["/api/v1/tools"]["get"]
    assert "task=organize" in tools_operation["description"]
    submit_operation = openapi.json["paths"]["/api/v1/plans/{plan_id}/submit"]["post"]
    assert "Requires at least one finalized file" in submit_operation["description"]
    submit_schema = submit_operation["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert submit_schema["required"] == ["contract_version", "proposal"]

    unknown = client.get(
        "/api/v1/not-a-resource",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert unknown.status_code == 404
    assert unknown.is_json
    assert unknown.json["error"]["code"] == "not_found"
    assert unknown.headers["Cache-Control"] == "no-store"
    assert unknown.headers["X-Request-ID"] == unknown.json["request_id"]

    unsupported_method = client.post(
        "/api/v1/me",
        headers={"Authorization": "Bearer valid-key"},
        json={},
    )
    assert unsupported_method.status_code == 405
    assert unsupported_method.is_json
    assert unsupported_method.json["error"]["code"] == "method_not_allowed"
    assert unsupported_method.headers["Cache-Control"] == "no-store"
    assert "GET" in unsupported_method.headers["Allow"]

    catalog = client.get(
        "/api/v1/tools",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert catalog.status_code == 200
    assert {tool["name"] for tool in catalog.json["tools"]} == set(
        api_routes.ai_functions.DECLARATIONS
    )
    get_file = next(
        tool for tool in catalog.json["tools"] if tool["name"] == "get_file"
    )
    assert "short-lived download URL" in get_file["description"]
    assert "expires after five minutes" in get_file["description"]
    assert "temporary credential" in get_file["description"]
    assert "provider file part" not in get_file["description"]

    monkeypatch.setattr(api_routes.external_api, "create_plan", lambda *args, **kwargs: report)
    created = client.post(
        "/api/v1/plans",
        headers={"Authorization": "Bearer valid-key"},
        json={"tool": "organize", "instructions": report.instructions},
    )
    assert created.status_code == 201
    assert created.json["id"] == report.urlsafe_key
    assert created.json["status"] == "draft"

    monkeypatch.setattr(api_routes, "_load_plan", lambda plan_id: report)
    fetched = client.get(
        "/api/v1/plans/report-key",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert fetched.status_code == 200
    assert fetched.json["id"] == "report-key"

    monkeypatch.setattr(
        api_routes.external_api,
        "plan_contract",
        lambda current, user: {
            "version": 1,
            "required_file_refs": [],
            "actor": user.hash,
        },
    )
    contract = client.get(
        "/api/v1/plans/report-key/contract",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert contract.status_code == 200
    assert contract.json == {
        "version": 1,
        "required_file_refs": [],
        "actor": actor.hash,
    }

    monkeypatch.setattr(
        api_routes.storage_assets,
        "create_direct_upload_session",
        lambda *args, **kwargs: {
            "token": "signed-upload-token",
            "session_url": "https://storage.example/upload",
            "chunk_size": 8 * 1024 * 1024,
        },
    )
    monkeypatch.setattr(
        api_routes.external_api,
        "prepare_upload_manifest",
        lambda records: records,
    )
    monkeypatch.setattr(api_routes.Entities, "save", lambda *entities: None)
    upload = client.post(
        "/api/v1/plans/report-key/uploads",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "files": [
                {
                    "filename": "records.pdf",
                    "content_type": "application/pdf",
                    "size": 100,
                }
            ]
        },
    )
    assert upload.status_code == 201
    assert upload.json["uploads"] == [
        {
            "index": 0,
            "filename": "records.pdf",
            "session_url": "https://storage.example/upload",
            "chunk_size": 8 * 1024 * 1024,
        }
    ]
    assert "token" not in upload.json["uploads"][0]

    def finalize(current, user):
        assert user is actor
        current.upload_manifest = None

    monkeypatch.setattr(api_routes.external_api, "finalize_uploads", finalize)
    finalized = client.post(
        "/api/v1/plans/report-key/uploads/finalize",
        headers={"Authorization": "Bearer valid-key"},
        json={},
    )
    assert finalized.status_code == 200
    assert finalized.json["uploads_pending"] is False

    def execute(name, arguments, user):
        seen.update(name=name, arguments=arguments, user=user)
        return {"items": [{"hash": "pagehash1234"}]}, []

    monkeypatch.setattr(api_routes.ai_functions, "execute_registered_tool", execute)
    tool = client.post(
        "/api/v1/plans/report-key/tools/search_entities",
        headers={"Authorization": "Bearer valid-key"},
        json={"arguments": {"query": "records"}},
    )
    assert tool.status_code == 200
    assert tool.json["result"] == {"items": [{"hash": "pagehash1234"}]}
    assert seen == {
        "name": "search_entities",
        "arguments": {"query": "records"},
        "user": actor,
    }

    def submit(current, user, proposal, *, contract_version):
        assert user is actor
        assert contract_version == 1
        current.status = "ready"
        current.proposal = proposal
        return current

    monkeypatch.setattr(api_routes.external_api, "submit_plan", submit)
    proposal = {
        "summary": "Ready for review.",
        "confidence": 1,
        "issues": [],
        "actions": [],
    }
    submitted = client.post(
        "/api/v1/plans/report-key/submit",
        headers={"Authorization": "Bearer valid-key"},
        json={"contract_version": 1, "proposal": proposal},
    )
    assert submitted.status_code == 200
    assert submitted.json["status"] == "ready"
    assert submitted.json["proposal"] == proposal

    monkeypatch.setattr(CONFIG, "EXTERNAL_AGENT_API_ENABLED", False)
    disabled = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert disabled.status_code == 404
    assert disabled.json["error"]["code"] == "not_found"


# @matrix agent-api user-settings : expiry revoke rotate shown-once
def test_user_can_rotate_and_revoke_external_agent_api_key(monkeypatch):
    actor = Actor()
    issued = {
        "active": True,
        "display_prefix": "lgn_actor…",
        "expires_at": "2026-09-30T00:00:00+00:00",
        "generation": 1,
    }
    revoked = {**issued, "active": False, "generation": 2}
    monkeypatch.setattr(CONFIG, "EXTERNAL_AGENT_API_ENABLED", True)
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(web_auth, "_load_request_context", lambda key=None: (actor, None))
    monkeypatch.setattr(web_auth, "require_ai_access", lambda required: None)
    monkeypatch.setattr(api_key_routes, "current_user", actor)
    monkeypatch.setattr(api_key_routes, "_rotation_limit", lambda current: None)
    monkeypatch.setattr(
        api_key_routes.agent_api,
        "credential_status",
        lambda current: {"active": False, "generation": 0},
    )
    monkeypatch.setattr(
        api_key_routes.agent_api,
        "issue_credential",
        lambda current: ("lgn_shown-once", issued),
    )
    monkeypatch.setattr(
        api_key_routes.agent_api,
        "revoke_credential",
        lambda current: revoked,
    )

    client = app.test_client()
    status = client.get("/users/me/api-key")
    assert status.status_code == 200
    assert status.json == {"credential": {"active": False, "generation": 0}}

    rotated = client.post("/users/me/api-key", json={})
    assert rotated.status_code == 201
    assert rotated.json["token"] == "lgn_shown-once"
    assert rotated.json["shown_once"] is True
    assert rotated.json["credential"] == issued

    removed = client.delete("/users/me/api-key")
    assert removed.status_code == 200
    assert removed.json == {"credential": revoked}


# @pair agent-api:provider-free-revision
def test_api_report_revision_is_provider_blocked(monkeypatch):
    actor = Actor()
    report = _report(actor)
    report.origin = "api"
    report.status = "ready"
    report.proposal = {"summary": "Ready", "actions": []}
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(web_auth, "_load_request_context", lambda key=None: (actor, None))
    monkeypatch.setattr(web_auth, "require_ai_access", lambda required: None)
    monkeypatch.setattr(tool_routes, "_get_report", lambda key: report)
    monkeypatch.setattr(
        tool_routes.DeferredJobs,
        "start",
        lambda *args, **kwargs: pytest.fail("API report revision called the provider"),
    )

    response = app.test_client().post(
        "/tools/reports/report-key/revise",
        data={"feedback": "Change it"},
    )

    assert response.status_code == 422
    assert "cannot be revised with the AI provider" in response.get_data(as_text=True)
