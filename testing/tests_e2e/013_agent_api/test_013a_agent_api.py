"""HTTP contract coverage for external-agent API and key management."""

from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import AI
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.web import app
from lagniappe.web import auth as web_auth
from lagniappe.web.routes.api import main as api_routes
from lagniappe.web.routes.users import api_key as api_key_routes
from lagniappe.web.routes.tools import main as tool_routes
from lagniappe.web.routes.tools import preview as tool_preview_routes


pytestmark = pytest.mark.e2e


class PersonalPage:
    hash = "personalpage"
    name = "External Planner"
    url = "/pages/actor-page"

    def allowed(self, action, user=None):
        return True


class Actor:
    name = "External Planner"
    hash = "actorhash123"
    urlsafe_key = "actor-key"
    key = "actor-datastore-key"
    ai_access = "CREATE"
    db = {"timezone": "America/Los_Angeles"}
    is_public = False
    is_authenticated = True
    page = PersonalPage()

    def access(self, required):
        return required in {AI.ASK, AI.CREATE}

    def _get_current_object(self):
        return self


def _report(actor, tool="organize"):
    return SimpleNamespace(
        urlsafe_key="report-key",
        hash="reporthash12",
        status="draft",
        tool=tool,
        name="External plan",
        instructions="Organize these files.",
        input_files=[],
        upload_manifest=None,
        proposal=None,
        result=None,
        error=None,
        deferred_job=None,
        agent_manifest={
            "contract_version": api_routes.external_api.CONTRACT_VERSION
        },
        origin="api",
        properties=SimpleNamespace(user=SimpleNamespace(key=actor.key)),
        allowed=lambda action, user=None: user is actor,
    )


# @matrix agent-api : bearer-only bootstrap contract create-revision organize-revision discovery error-envelope plan-session proposal-contract routing submission tool-catalog tool-dispatch uploads
# @pairs agent-api:create-revision agent-api:organize-revision agent-api:plan-capability
def test_external_agent_api_requires_bearer_and_dispatches_as_bound_user(monkeypatch):
    actor = Actor()
    report = _report(actor)
    seen = {}
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
            (
                actor,
                {
                    "active": True,
                    "expires_at": "2026-09-30T00:00:00+00:00",
                    "generation": 4,
                },
            )
            if token == "valid-key"
            else (_ for _ in ()).throw(
                agent_auth.AgentAPICredentialError("invalid")
            )
        ),
    )

    client = app.test_client()
    family_unauthorized = client.get("/api")
    assert family_unauthorized.status_code == 401
    assert family_unauthorized.json["error"]["code"] == "unauthorized"

    unauthorized = client.get("/api/v1/me")
    assert unauthorized.status_code == 401
    assert unauthorized.json["error"]["code"] == "unauthorized"
    # The focused security-wiring module owns the complete API header matrix;
    # this workflow retains one representative cache-boundary assertion.
    assert unauthorized.headers["Cache-Control"] == "no-store"

    authorized = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert authorized.status_code == 200
    assert authorized.json["user"] == {
        "name": actor.name,
        "hash": actor.hash,
        "timezone": "America/Los_Angeles",
        "personal_page": {
            "kind": "page",
            "hash": "hash:personalpage",
            "name": "External Planner",
            "url": "/pages/actor-page",
            "can_view": True,
            "can_edit": True,
        },
    }
    assert authorized.json["capabilities"] == {
        "ask": True,
        "create": True,
        "organize": True,
    }

    family = client.get(
        "/api",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert family.status_code == 200
    assert family.json["current_version"] == "v1"
    assert family.json["versions"][0]["openapi_url"].endswith(
        "/api/v1/openapi.json"
    )

    index = client.get(
        "/api/v1",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert index.status_code == 200
    assert index.json["version"] == "v1"
    assert index.json["openapi_url"].endswith("/api/v1/openapi.json")
    assert index.json["actor_url"].endswith("/api/v1/me")
    assert index.json["client_skill_url"].endswith("/api/v1/client-skill.md")
    assert "before using or guessing resource paths" in index.json["instructions"]
    trailing_index = client.get(
        "/api/v1/",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert trailing_index.status_code == 200
    assert trailing_index.json == index.json

    client_skill = client.get(
        "/api/v1/client-skill.md",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert client_skill.status_code == 200
    assert client_skill.mimetype == "text/markdown"
    assert client_skill.headers["Content-Disposition"] == 'inline; filename="SKILL.md"'
    assert client_skill.headers["Cache-Control"] == "no-store"
    assert "name: lagniappe" in client_skill.get_data(as_text=True)
    assert "$LAGNIAPPE_API_KEY" in client_skill.get_data(as_text=True)

    openapi = client.get(
        "/api/v1/openapi.json",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert openapi.status_code == 200
    assert openapi.json["openapi"] == "3.1.0"
    assert "/api/v1" in openapi.json["paths"]
    assert "/api/v1/client-skill.md" in openapi.json["paths"]
    assert "/api/v1/plans/{plan_id}/submit" in openapi.json["paths"]
    assert "/api/v1/plans/{plan_id}/execute" not in openapi.json["paths"]
    assert "external API never applies those proposals" in openapi.json["info"][
        "description"
    ]
    assert "website Execute control is the only" in openapi.json["info"][
        "description"
    ]
    assert "task=organize" in openapi.json["info"]["description"]
    assert "two-phase workflow" in openapi.json["info"]["description"]
    assert "does not call a model" in openapi.json["info"]["description"]
    assert "one summary and two retrieval terms" in openapi.json["info"]["description"]
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
    assert create_schema["properties"]["tool"]["enum"] == [
        "ask",
        "create",
        "organize",
    ]
    upload_operation = openapi.json["paths"]["/api/v1/plans/{plan_id}/uploads"]["post"]
    assert upload_operation["requestBody"]["required"] is True
    tools_operation = openapi.json["paths"]["/api/v1/tools"]["get"]
    assert "task=organize" in tools_operation["description"]
    execute_tool_operation = openapi.json["paths"][
        "/api/v1/plans/{plan_id}/tools/{tool_name}"
    ]["post"]
    assert "ready Create or Organize plans" in execute_tool_operation["description"]
    assert "top-level arguments object" in execute_tool_operation["description"]
    submit_operation = openapi.json["paths"]["/api/v1/plans/{plan_id}/submit"]["post"]
    assert "Organize also requires at least one finalized file" in submit_operation[
        "description"
    ]
    assert "never executes actions" in submit_operation["description"]
    assert "without separate save confirmation" in submit_operation["description"]
    assert "Create/Organize proposal replaces" in submit_operation["description"]
    assert "submit it again" in submit_operation["description"]
    assert "authenticated website" in submit_operation["description"]
    submit_schema = submit_operation["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert submit_schema["required"] == ["contract_version", "proposal"]
    plan_schema = openapi.json["components"]["schemas"]["Plan"]
    assert "execute_url" not in plan_schema["properties"]
    assert "execution" not in plan_schema["properties"]
    assert "Execution" not in openapi.json["components"]["schemas"]

    unknown = client.get(
        "/api/v1/not-a-resource",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert unknown.status_code == 404
    assert unknown.is_json
    assert unknown.json["error"]["code"] == "not_found"

    unsupported_method = client.post(
        "/api/v1/me",
        headers={"Authorization": "Bearer valid-key"},
        json={},
    )
    assert unsupported_method.status_code == 405
    assert unsupported_method.is_json
    assert unsupported_method.json["error"]["code"] == "method_not_allowed"
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
    assert created.json["status_url"].endswith("/api/v1/plans/report-key")
    assert "execute_url" not in created.json
    assert "execution" not in created.json
    assert created.json["preview_url"].endswith("/tools/api-plan/reporthash12")

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

    class DownloadableFile:
        properties = SimpleNamespace(
            file=SimpleNamespace(value=SimpleNamespace(path="private/person.vcf"))
        )

        def allowed(self, action, user=None):
            return user is actor

    monkeypatch.setattr(api_routes.Entities, "FILE", DownloadableFile)
    monkeypatch.setattr(
        api_routes.Entities,
        "fetch_one",
        lambda identifier, request: DownloadableFile(),
    )
    monkeypatch.setattr(
        api_routes.ai_functions,
        "execute_registered_tool",
        lambda name, arguments, user: (
            {
                "filename": "person.vcf",
                "original_file": {
                    "supported": False,
                    "attached": False,
                    "reason": "Provider does not support this MIME type.",
                },
            },
            [],
        ),
    )
    signed = []
    monkeypatch.setattr(
        api_routes.storage_assets,
        "get_signed_url",
        lambda path, expires_in: signed.append((path, expires_in))
        or "https://storage.example/download",
    )

    original_available = client.post(
        "/api/v1/plans/report-key/tools/get_file",
        headers={"Authorization": "Bearer valid-key"},
        json={"arguments": {"id": "hash:filehash1234"}},
    )
    assert original_available.status_code == 200
    assert original_available.json["result"]["original_file"] == {
        "supported": True,
        "attached": False,
        "reason": (
            "Original content was not included by default. Call get_file again "
            "with include_original=true to receive a five-minute signed download URL."
        ),
    }
    assert signed == []

    original_requested = client.post(
        "/api/v1/plans/report-key/tools/get_file",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "arguments": {
                "id": "hash:filehash1234",
                "include_original": True,
            }
        },
    )
    assert original_requested.status_code == 200
    assert original_requested.json["result"]["original_file"] == {
        "supported": True,
        "attached": False,
        "download_url": "https://storage.example/download",
        "expires_in": 300,
    }
    assert signed == [("private/person.vcf", 300)]

    def submit(current, user, proposal, *, contract_version):
        assert user is actor
        assert contract_version == api_routes.external_api.CONTRACT_VERSION
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
        json={
            "contract_version": api_routes.external_api.CONTRACT_VERSION,
            "proposal": proposal,
        },
    )
    assert submitted.status_code == 200
    assert submitted.json["status"] == "ready"
    assert submitted.json["proposal"] == proposal
    assert "execute_url" not in submitted.json
    assert "execution" not in submitted.json

    ready_read = client.post(
        "/api/v1/plans/report-key/tools/search_entities",
        headers={"Authorization": "Bearer valid-key"},
        json={"arguments": {"query": "additional category"}},
    )
    assert ready_read.status_code == 200
    revised_proposal = {**proposal, "summary": "Revised organization for review."}
    revised_submission = client.post(
        "/api/v1/plans/report-key/submit",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "contract_version": api_routes.external_api.CONTRACT_VERSION,
            "proposal": revised_proposal,
        },
    )
    assert revised_submission.status_code == 200
    assert revised_submission.json["proposal"] == revised_proposal

    report.tool = "create"
    create_ready_read = client.post(
        "/api/v1/plans/report-key/tools/search_entities",
        headers={"Authorization": "Bearer valid-key"},
        json={"arguments": {"query": "additional form"}},
    )
    assert create_ready_read.status_code == 200
    create_revision = {**proposal, "summary": "Ready with a form for review."}
    create_revised_submission = client.post(
        "/api/v1/plans/report-key/submit",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "contract_version": api_routes.external_api.CONTRACT_VERSION,
            "proposal": create_revision,
        },
    )
    assert create_revised_submission.status_code == 200
    assert create_revised_submission.json["proposal"] == create_revision

    missing_execution = client.post(
        "/api/v1/plans/report-key/execute",
        headers={"Authorization": "Bearer valid-key"},
        json={},
    )
    assert missing_execution.status_code == 405
    assert missing_execution.json["error"]["code"] == "method_not_allowed"

    report.status = "running"
    browser_execution_locked_revision = client.post(
        "/api/v1/plans/report-key/submit",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "contract_version": api_routes.external_api.CONTRACT_VERSION,
            "proposal": proposal,
        },
    )
    assert browser_execution_locked_revision.status_code == 409
    assert browser_execution_locked_revision.json["error"]["code"] == (
        "plan_state_conflict"
    )


# @matrix agent-api : entitlement-independent public-user request-recheck stale-plan
def test_external_api_ignores_provider_entitlement_but_rechecks_public_eligibility(
    monkeypatch,
):
    actor = Actor()
    report = _report(actor, tool="create")
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
        lambda token: (actor, {"active": True, "generation": 1}),
    )
    monkeypatch.setattr(api_routes.Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        api_routes.Entities,
        "fetch_one",
        lambda plan_id, request: report,
    )

    client = app.test_client()
    headers = {"Authorization": "Bearer valid-key"}
    assert client.get("/api/v1/plans/report-key", headers=headers).status_code == 200

    actor.access = lambda required: False
    plan_without_provider_access = client.get(
        "/api/v1/plans/report-key", headers=headers
    )
    assert plan_without_provider_access.status_code == 200
    actor_without_provider_access = client.get("/api/v1/me", headers=headers)
    assert actor_without_provider_access.status_code == 200
    assert actor_without_provider_access.json["capabilities"] == {
        "ask": True,
        "create": True,
        "organize": True,
    }

    actor.is_public = True
    public = client.get("/api/v1/me", headers=headers)
    assert public.status_code == 403
    assert public.json["error"] == {
        "code": "forbidden",
        "message": "This user cannot use external agent plans.",
    }


# @matrix agent-api : creator-bound generic-not-found plan-isolation
def test_external_plan_resources_hide_other_users_plans(monkeypatch):
    owner = Actor()
    intruder = Actor()
    intruder.key = "other-user-key"
    intruder.urlsafe_key = "other-user-url-key"
    report = _report(owner)
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

    def authenticate(token):
        actor = owner if token == "owner-key" else intruder
        return actor, {"active": True, "generation": 1}

    monkeypatch.setattr(agent_auth, "authenticate_credential", authenticate)
    monkeypatch.setattr(api_routes.Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        api_routes.Entities,
        "fetch_one",
        lambda plan_id, request: report if plan_id == "report-key" else None,
    )

    client = app.test_client()
    foreign = client.get(
        "/api/v1/plans/report-key",
        headers={"Authorization": "Bearer intruder-key"},
    )
    missing = client.get(
        "/api/v1/plans/missing-key",
        headers={"Authorization": "Bearer intruder-key"},
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json["error"] == missing.json["error"] == {
        "code": "not_found",
        "message": "Plan not found.",
    }

    owned = client.get(
        "/api/v1/plans/report-key",
        headers={"Authorization": "Bearer owner-key"},
    )
    assert owned.status_code == 200
    assert owned.json["id"] == "report-key"


# @source lagniappe/web/routes/api/main.py::create_uploads
# @source lagniappe/web/routes/api/main.py::submit_plan
# @pairs agent-api:ask-refinement agent-api:entitlement-independent agent-api:envelope-validation agent-api:tool-selection agent-api:plan-session agent-api:uploads agent-api:submission agent-api:plan-capability
def test_external_plan_types_are_available_without_provider_access(monkeypatch):
    class ProviderDisabledActor(Actor):
        ai_access = "NONE"

        def access(self, required):
            return False

    actor = ProviderDisabledActor()
    report = _report(actor, tool="ask")
    report.instructions = "Which pages have open tasks?"
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
            actor,
            {
                "active": True,
                "expires_at": "2026-09-30T00:00:00+00:00",
                "generation": 1,
            },
        ),
    )
    created_tools = []

    def create(current, *, instructions, tool, name=None):
        assert current is actor
        created_tools.append(tool)
        report.tool = tool
        report.instructions = instructions
        return report

    monkeypatch.setattr(api_routes.external_api, "create_plan", create)
    monkeypatch.setattr(api_routes, "_load_plan", lambda plan_id: report)
    monkeypatch.setattr(
        api_routes.ai_functions,
        "execute_registered_tool",
        lambda tool_name, arguments, user: (
            {"tool": tool_name, "query": arguments.get("query")},
            [],
        ),
    )

    client = app.test_client()
    headers = {"Authorization": "Bearer ask-key"}
    capabilities = client.get("/api/v1/me", headers=headers)
    assert capabilities.status_code == 200
    assert capabilities.json["capabilities"] == {
        "ask": True,
        "create": True,
        "organize": True,
    }

    create_draft = client.post(
        "/api/v1/plans",
        headers=headers,
        json={"tool": "create", "instructions": "Make a project."},
    )
    assert create_draft.status_code == 201

    organize_draft = client.post(
        "/api/v1/plans",
        headers=headers,
        json={"tool": "organize", "instructions": "Organize these files."},
    )
    assert organize_draft.status_code == 201

    created = client.post(
        "/api/v1/plans",
        headers=headers,
        json={"tool": "ask", "instructions": report.instructions},
    )
    assert created.status_code == 201
    assert created.json["tool"] == "ask"
    assert "execute_url" not in created.json
    assert "execution" not in created.json
    assert created_tools == ["create", "organize", "ask"]

    malformed_tool = client.post(
        "/api/v1/plans/report-key/tools/search_entities",
        headers=headers,
        json={"query": "Avery"},
    )
    assert malformed_tool.status_code == 422
    assert malformed_tool.json["error"]["code"] == "invalid_arguments"
    assert "top-level arguments object" in malformed_tool.json["error"]["message"]

    upload = client.post(
        "/api/v1/plans/report-key/uploads",
        headers=headers,
        json={"files": [{"filename": "notes.txt", "size": 5}]},
    )
    assert upload.status_code == 409
    assert upload.json["error"]["code"] == "uploads_not_supported"

    proposal = {
        "summary": "Two pages have open tasks.",
        "answer_markdown": "## Open tasks\n\nTwo pages have open tasks.",
        "confidence": 0.9,
        "actions": [],
    }

    def submit(current, user, value, *, contract_version):
        assert current is report
        assert user is actor
        assert value is not None
        assert contract_version == api_routes.external_api.CONTRACT_VERSION
        current.status = "complete"
        current.proposal = {
            **value,
            "answer_html": "<h2>Open tasks</h2><p>Two pages have open tasks.</p>",
        }
        current.proposal.pop("answer_markdown", None)
        return current

    monkeypatch.setattr(api_routes.external_api, "submit_plan", submit)
    submitted = client.post(
        "/api/v1/plans/report-key/submit",
        headers=headers,
        json={
            "contract_version": api_routes.external_api.CONTRACT_VERSION,
            "proposal": proposal,
        },
    )
    assert submitted.status_code == 200
    assert submitted.json["status"] == "complete"
    assert "execute_url" not in submitted.json
    assert "execution" not in submitted.json
    assert submitted.json["proposal"]["answer_html"].startswith("<h2>")

    follow_up_read = client.post(
        "/api/v1/plans/report-key/tools/search_entities",
        headers=headers,
        json={"arguments": {"query": "Avery Rowan"}},
    )
    assert follow_up_read.status_code == 200
    assert follow_up_read.json["result"] == {
        "tool": "search_entities",
        "query": "Avery Rowan",
    }

    revised = client.post(
        "/api/v1/plans/report-key/submit",
        headers=headers,
        json={
            "contract_version": api_routes.external_api.CONTRACT_VERSION,
            "proposal": {**proposal, "summary": "One page has an open task."},
        },
    )
    assert revised.status_code == 200
    assert revised.json["proposal"]["summary"] == "One page has an open task."

    missing_execution = client.post(
        "/api/v1/plans/report-key/execute",
        headers=headers,
        json={},
    )
    assert missing_execution.status_code == 405
    assert missing_execution.json["error"]["code"] == "method_not_allowed"


# @matrix agent-api ai-report : browser-review creator-bound short-link
def test_api_plan_preview_redirect_is_session_and_creator_bound(monkeypatch):
    actor = Actor()
    actor.access = lambda required: False
    report = _report(actor)
    looked_up = []
    monkeypatch.setattr(web_auth, "_load_request_context", lambda key=None: (actor, None))
    monkeypatch.setattr(tool_preview_routes, "current_user", actor)
    monkeypatch.setattr(tool_preview_routes.Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        tool_preview_routes.database_get,
        "ai_report_by_hash",
        lambda user_key, report_hash: looked_up.append((user_key, report_hash))
        or "raw-report",
    )
    monkeypatch.setattr(
        tool_preview_routes.Entities,
        "fetch_one",
        lambda record, request: report,
    )

    client = app.test_client()
    redirected = client.get("/tools/api-plan/reporthash12")
    assert redirected.status_code == 302
    assert redirected.headers["Location"].endswith("/tools/reports/report-key")
    assert looked_up == [(actor.key, report.hash)]

    invalid = client.get("/tools/api-plan/not-valid")
    assert invalid.status_code == 404
    assert looked_up == [(actor.key, report.hash)]

    report.properties.user.key = "different-owner"
    denied = client.get("/tools/api-plan/reporthash12")
    assert denied.status_code == 404

    anonymous = SimpleNamespace(is_authenticated=False)
    monkeypatch.setattr(
        web_auth,
        "_load_request_context",
        lambda key=None: (anonymous, None),
    )
    logged_out = client.get("/tools/api-plan/reporthash12")
    assert logged_out.status_code in {302, 401}
    assert "/tools/reports/report-key" not in logged_out.headers.get("Location", "")


# @matrix agent-api user-settings : expiry revoke rotate shown-once
def test_user_can_rotate_and_revoke_external_agent_api_key(monkeypatch):
    actor = Actor()
    actor.access = lambda required: False
    issued = {
        "active": True,
        "display_prefix": "lgn_actor…",
        "expires_at": "2026-09-30T00:00:00+00:00",
        "generation": 1,
    }
    revoked = {**issued, "active": False, "generation": 2}
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(web_auth, "_load_request_context", lambda key=None: (actor, None))
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
