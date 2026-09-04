"""HTTP contract coverage for external-agent API and key management."""

from types import SimpleNamespace
import re
from uuid import uuid4

import pytest

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import AI
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai as ai_tools
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai import external_operations
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.core.tools import cache as cache_store
from lagniappe.core.tools.database import agent_api as agent_api_store
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.web import app


pytestmark = pytest.mark.e2e


class FakeProperties(SimpleNamespace):
    """Minimal property registry for route-level fake entities."""

    def __contains__(self, _name):
        return False


class PersonalPage:
    hash = "personalpage"
    name = "External Planner"
    url = "/pages/actor-page"
    urlsafe_key = "actor-page-key"

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

    def __init__(self):
        identifier = uuid4().hex
        self.urlsafe_key = f"actor-{identifier}"
        self.key = f"actor-key-{identifier}"

    def access(self, required):
        return required in {AI.ASK, AI.CREATE}

    def _get_current_object(self):
        return self

    def get_id(self):
        return self.urlsafe_key


def _authenticated_client(monkeypatch, actor):
    client = app.test_client()
    monkeypatch.setattr(
        app.login_manager,
        "_user_callback",
        lambda _identifier: actor,
    )
    with client.session_transaction() as client_session:
        client_session["_user_id"] = actor.get_id()
        client_session["_fresh"] = True
    return client


def _report(actor, tool="organize"):
    return SimpleNamespace(
        key="report-datastore-key",
        kind="report",
        db={},
        processes={},
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
            "contract_version": external_api.CONTRACT_VERSION
        },
        origin="api",
        parent=None,
        user=None,
        properties=FakeProperties(
            user=SimpleNamespace(key=actor.key),
            parent=SimpleNamespace(key=actor.key),
        ),
        allowed=lambda action, user=None: user is actor,
    )


def _allow_claimed_saves(monkeypatch, saved_reports=None):
    """Commit route mutation plans without bypassing the decorated HTTP route."""

    def commit(_report_key, *, writes, **_options):
        if saved_reports is not None:
            saved_reports.extend(
                entity
                for entity, _property_mask in writes
                if getattr(entity, "kind", None) == "report"
            )
        return agent_api_store.PLAN_OPERATION_COMMITTED

    monkeypatch.setattr(agent_api_store, "commit_plan_operation", commit)
    monkeypatch.setattr(cache_store, "update", lambda *_entities, **_options: None)
    monkeypatch.setattr(
        cache_store,
        "update_owner_projection",
        lambda *_entities, **_options: None,
    )


# @matrix agent-api mcp-package : discovery origin-validation proposal-contract setup-command
def test_external_api_uses_only_a_configured_request_origin(monkeypatch):
    actor = Actor()
    report = _report(actor)
    allowed_origin = "https://version-dot-project.uc.r.appspot.com"
    authorization = {"Authorization": "Bearer valid-key"}
    monkeypatch.setattr(
        agent_auth,
        "authenticate_credential",
        lambda _token: (actor, {"active": True}),
    )
    monkeypatch.setattr(
        CONFIG,
        "MCP_EVALUATION_ORIGINS",
        (allowed_origin,),
    )
    monkeypatch.setattr(
        external_api,
        "create_plan",
        lambda *_args, **_kwargs: report,
    )
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda _identifier, request: report,
    )
    monkeypatch.setattr(
        external_api,
        "plan_contract",
        lambda current, user, *, submit_url: {
            "contract_version": external_api.CONTRACT_VERSION,
            "actor": user.hash,
            "submission_format": {"method": "POST", "url": submit_url},
        },
    )
    client = app.test_client()

    index = client.get(
        "/api/v1",
        base_url=allowed_origin,
        headers=authorization,
    )
    assert index.status_code == 200
    for field in (
        "base_url",
        "openapi_url",
        "actor_url",
        "tools_url",
        "plans_url",
        "client_skill_url",
    ):
        assert index.json[field].startswith(f"{allowed_origin}/")

    skill = client.get(
        "/api/v1/client-skill.md",
        base_url=allowed_origin,
        headers=authorization,
    )
    assert skill.status_code == 200
    assert allowed_origin in skill.get_data(as_text=True)

    openapi = client.get(
        "/api/v1/openapi.json",
        base_url=allowed_origin,
        headers=authorization,
    )
    assert openapi.status_code == 200
    assert openapi.json["servers"] == [{"url": allowed_origin}]

    created = client.post(
        "/api/v1/plans",
        base_url=allowed_origin,
        headers=authorization,
        json={"tool": "organize", "instructions": "Organize these files."},
    )
    assert created.status_code == 201
    for field in (
        "contract_url",
        "submit_url",
        "status_url",
        "preview_url",
        "review_url",
    ):
        assert created.json[field].startswith(f"{allowed_origin}/")

    contract = client.get(
        "/api/v1/plans/report-key/contract",
        base_url=allowed_origin,
        headers=authorization,
    )
    assert contract.status_code == 200
    assert contract.json["submission_format"]["url"].startswith(
        f"{allowed_origin}/"
    )

    hostile = client.get(
        "/api/v1",
        base_url="https://credential-thief.invalid",
        headers=authorization,
    )
    assert hostile.status_code == 200
    assert all(
        "credential-thief.invalid" not in hostile.json[field]
        for field in (
            "base_url",
            "openapi_url",
            "actor_url",
            "tools_url",
            "plans_url",
            "client_skill_url",
        )
    )


# @matrix agent-api : bearer-only bootstrap contract create-revision organize-revision discovery error-envelope plan-session proposal-contract routing submission tool-catalog tool-dispatch uploads
# @pairs agent-api:create-revision agent-api:organize-revision agent-api:plan-capability
def test_external_agent_api_requires_bearer_and_dispatches_as_bound_user(monkeypatch):
    actor = Actor()
    report = _report(actor)
    seen = {}
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
    hostile_host_index = client.get(
        "/api/v1",
        headers={
            "Authorization": "Bearer valid-key",
            "Host": "credential-thief.invalid",
        },
    )
    assert hostile_host_index.status_code == 200
    assert hostile_host_index.json == index.json
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
    assert "follow its returned `contract_url`" in client_skill.get_data(as_text=True)

    openapi = client.get(
        "/api/v1/openapi.json",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert openapi.status_code == 200
    assert openapi.json["openapi"] == "3.1.0"
    hostile_host_openapi = client.get(
        "/api/v1/openapi.json",
        headers={
            "Authorization": "Bearer valid-key",
            "Host": "credential-thief.invalid",
        },
    )
    assert hostile_host_openapi.status_code == 200
    assert hostile_host_openapi.json["servers"] == openapi.json["servers"]
    assert "credential-thief.invalid" not in hostile_host_openapi.json["servers"][0][
        "url"
    ]
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
    assert create_schema["additionalProperties"] is False
    assert create_schema["properties"]["instructions"]["pattern"] == "\\S"
    assert create_schema["properties"]["tool"]["enum"] == [
        "ask",
        "create",
        "organize",
    ]
    create_description = openapi.json["paths"]["/api/v1/plans"]["post"][
        "description"
    ]
    assert "Follow the returned contract_url, submit_url, and status_url" in (
        create_description
    )
    assert "instead of reconstructing those lifecycle paths" in create_description
    upload_operation = openapi.json["paths"]["/api/v1/plans/{plan_id}/uploads"]["post"]
    assert upload_operation["requestBody"]["required"] is True
    upload_response_schema = upload_operation["responses"]["201"]["content"][
        "application/json"
    ]["schema"]
    assert upload_response_schema["additionalProperties"] is False
    assert upload_response_schema["required"] == [
        "plan_id",
        "upload_batch_id",
        "uploads",
    ]
    finalize_schema = openapi.json["paths"][
        "/api/v1/plans/{plan_id}/uploads/finalize"
    ]["post"]["requestBody"]
    assert finalize_schema["required"] is True
    assert finalize_schema["content"]["application/json"]["schema"]["required"] == [
        "upload_batch_id"
    ]
    tools_operation = openapi.json["paths"]["/api/v1/tools"]["get"]
    assert "task=organize" in tools_operation["description"]
    assert "exact input_schema" in tools_operation["description"]
    assert {parameter["name"] for parameter in tools_operation["parameters"]} == {
        "names",
        "view",
    }
    assert "ToolDefinition" in openapi.json["components"]["schemas"]
    execute_tool_operation = openapi.json["paths"][
        "/api/v1/plans/{plan_id}/tools/{tool_name}"
    ]["post"]
    assert "ready Create or Organize plans" in execute_tool_operation["description"]
    assert "top-level arguments object" in execute_tool_operation["description"]
    assert "error.code=tool_error" in execute_tool_operation["description"]
    assert execute_tool_operation["responses"]["422"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/Error"}
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
    assert submit_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/SubmissionReceipt"}
    assert submit_operation["responses"]["422"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/Error"}
    assert "error.details.errors" in submit_operation["responses"]["422"][
        "description"
    ]
    assert "ValidationErrorDetail" in openapi.json["components"]["schemas"]
    contract_response_schema = openapi.json["paths"][
        "/api/v1/plans/{plan_id}/contract"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert contract_response_schema == {
        "$ref": "#/components/schemas/PlanContract"
    }
    plan_contract_schema = openapi.json["components"]["schemas"]["PlanContract"]
    expected_contract_fields = {
        "contract_version",
        "tool",
        "current_date",
        "timezone",
        "personal_page",
        "submission_format",
        "proposal_schema",
        "permissions",
        "required_file_refs",
        "upload_inventory",
        "file_checklist",
        "guidance_requirements",
        "uploads_supported",
        "workflow_rules",
        "reference_rules",
        "limits",
        "payload_sizes",
    }
    assert set(plan_contract_schema["required"]) == expected_contract_fields
    assert set(plan_contract_schema["properties"]) == expected_contract_fields
    submission_format_schema = openapi.json["components"]["schemas"][
        "PlanSubmissionFormat"
    ]
    assert submission_format_schema["required"] == [
        "method",
        "url",
        "contract_version",
        "body",
        "rule",
    ]
    assert submission_format_schema["properties"]["method"]["const"] == "POST"
    plan_schema = openapi.json["components"]["schemas"]["Plan"]
    assert "submit_url" in plan_schema["required"]
    assert "upload_batch_id" in plan_schema["required"]
    assert plan_schema["properties"]["submit_url"] == {
        "type": "string",
        "format": "uri",
    }
    assert "execute_url" not in plan_schema["properties"]
    assert "execution" not in plan_schema["properties"]
    assert "Execution" not in openapi.json["components"]["schemas"]
    receipt_schema = openapi.json["components"]["schemas"]["SubmissionReceipt"]
    assert "proposal" not in receipt_schema["properties"]
    assert "proposal_fingerprint" in receipt_schema["required"]

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
        ai_functions.DECLARATIONS
    )
    assert all("output_schema" in tool for tool in catalog.json["tools"])
    assert all("result_paths" in tool for tool in catalog.json["tools"])
    selected_catalog = client.get(
        "/api/v1/tools?names=search_entities,get_page_details",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert [tool["name"] for tool in selected_catalog.json["tools"]] == [
        "search_entities",
        "get_page_details",
    ]
    compact_catalog = client.get(
        "/api/v1/tools?view=names&names=get_entity&names=get_file",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert compact_catalog.json["tools"] == ["get_entity", "get_file"]
    get_file = next(
        tool for tool in catalog.json["tools"] if tool["name"] == "get_file"
    )
    assert "short-lived download URL" in get_file["description"]
    assert "expires after five minutes" in get_file["description"]
    assert "temporary credential" in get_file["description"]
    assert "provider file part" not in get_file["description"]

    monkeypatch.setattr(external_api, "create_plan", lambda *args, **kwargs: report)
    malformed_plan_requests = [
        (
            {"instructions": report.instructions, "unexpected": True},
            "unsupported_field",
            {"path": "$", "fields": ["unexpected"]},
        ),
        (
            {"instructions": [report.instructions]},
            "invalid_instructions",
            {"path": "$.instructions", "expected": "non-empty string"},
        ),
        (
            {"instructions": "   \n\t"},
            "invalid_instructions",
            {"path": "$.instructions", "expected": "non-empty string"},
        ),
        (
            {"instructions": report.instructions, "name": 7},
            "invalid_name",
            {
                "path": "$.name",
                "expected": "string with at most 120 characters",
            },
        ),
        (
            {"instructions": report.instructions, "name": None},
            "invalid_name",
            {
                "path": "$.name",
                "expected": "string with at most 120 characters",
            },
        ),
        (
            {"instructions": report.instructions, "name": "x" * 121},
            "invalid_name",
            {
                "path": "$.name",
                "expected": "string with at most 120 characters",
            },
        ),
        (
            {"tool": "ORGANIZE", "instructions": report.instructions},
            "unsupported_tool",
            {"path": "$.tool"},
        ),
    ]
    for payload, code, expected_details in malformed_plan_requests:
        invalid_plan = client.post(
            "/api/v1/plans",
            headers={"Authorization": "Bearer valid-key"},
            json=payload,
        )
        assert invalid_plan.status_code == 422
        assert invalid_plan.json["error"]["code"] == code
        for field, value in expected_details.items():
            assert invalid_plan.json["error"]["details"][field] == value
    created = client.post(
        "/api/v1/plans",
        headers={"Authorization": "Bearer valid-key"},
        json={"tool": "organize", "instructions": report.instructions},
    )
    assert created.status_code == 201
    assert created.json["id"] == report.urlsafe_key
    assert created.json["status"] == "draft"
    assert created.json["status_url"].endswith("/api/v1/plans/report-key")
    assert created.json["submit_url"].endswith(
        "/api/v1/plans/report-key/submit"
    )
    assert "execute_url" not in created.json
    assert "execution" not in created.json
    assert created.json["preview_url"].endswith("/tools/api-plan/reporthash12")

    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda identifier, request: report,
    )
    fetched = client.get(
        "/api/v1/plans/report-key",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert fetched.status_code == 200
    assert fetched.json["id"] == "report-key"
    hostile_host_plan = client.get(
        "/api/v1/plans/report-key",
        headers={
            "Authorization": "Bearer valid-key",
            "Host": "credential-thief.invalid",
        },
    )
    assert hostile_host_plan.status_code == 200
    for field in (
        "contract_url",
        "submit_url",
        "status_url",
        "preview_url",
        "review_url",
    ):
        assert hostile_host_plan.json[field] == fetched.json[field]

    monkeypatch.setattr(
        external_api,
        "plan_contract",
        lambda current, user, *, submit_url: {
            "contract_version": external_api.CONTRACT_VERSION,
            "required_file_refs": [],
            "actor": user.hash,
            "submission_format": {
                "method": "POST",
                "url": submit_url,
            },
        },
    )
    contract = client.get(
        "/api/v1/plans/report-key/contract",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert contract.status_code == 200
    assert contract.json == {
        "contract_version": external_api.CONTRACT_VERSION,
        "required_file_refs": [],
        "actor": actor.hash,
        "submission_format": {
            "method": "POST",
            "url": created.json["submit_url"],
        },
    }

    monkeypatch.setattr(
        storage_assets,
        "create_direct_upload_session",
        lambda *args, **kwargs: {
            "token": "signed-upload-token",
            "session_url": "https://storage.example/upload",
            "chunk_size": 8 * 1024 * 1024,
        },
    )
    monkeypatch.setattr(
        agent_api_store,
        "claim_plan_operation",
        lambda *_args, **_kwargs: agent_api_store.PLAN_OPERATION_CLAIMED,
    )
    monkeypatch.setattr(
        agent_api_store,
        "renew_plan_operation",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        agent_api_store,
        "release_plan_operation",
        lambda *_args, **_kwargs: True,
    )
    _allow_claimed_saves(monkeypatch)
    monkeypatch.setattr(
        external_api,
        "bind_upload_file_identities",
        lambda _report, manifest, *, upload_batch_id: [
            {
                **record,
                "file_index": index,
                "file_key": f"stable-file-{index}",
            }
            for index, record in enumerate(manifest)
        ],
    )
    monkeypatch.setattr(Entities, "save", lambda *entities: None)
    invalid_upload = client.post(
        "/api/v1/plans/report-key/uploads",
        headers={"Authorization": "Bearer valid-key"},
        json={"files": [{"filename": "records.pdf", "size_bytes": 100}]},
    )
    assert invalid_upload.status_code == 422
    assert invalid_upload.json["error"] == {
        "code": "unsupported_field",
        "message": "Upload file entry contains unsupported fields.",
        "details": {
            "path": "$.files[0]",
            "fields": ["size_bytes"],
            "allowed_fields": ["content_type", "filename", "size"],
            "use_field": "size",
        },
    }
    redundant_alias = client.post(
        "/api/v1/plans/report-key/uploads",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "files": [
                {"filename": "records.pdf", "size": 100, "size_bytes": 100}
            ]
        },
    )
    assert redundant_alias.status_code == 422
    assert redundant_alias.json["error"]["code"] == "unsupported_field"
    unsupported_top_level = client.post(
        "/api/v1/plans/report-key/uploads",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "files": [{"filename": "records.pdf", "size": 100}],
            "plan_id": "report-key",
        },
    )
    assert unsupported_top_level.status_code == 422
    assert unsupported_top_level.json["error"]["details"] == {
        "path": "$",
        "fields": ["plan_id"],
        "allowed_fields": ["files"],
    }
    malformed_upload = client.post(
        "/api/v1/plans/report-key/uploads",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "files": [
                {"filename": "valid.pdf", "size": 100},
                {"filename": "invalid.pdf", "size": "many"},
            ]
        },
    )
    assert malformed_upload.status_code == 422
    assert malformed_upload.json["error"] == {
        "code": "invalid_file_size",
        "message": 'Each file\'s "size" must be a positive integer byte size.',
        "details": {
            "path": "$.files[1].size",
            "expected": "positive integer byte size",
        },
    }
    boolean_upload = client.post(
        "/api/v1/plans/report-key/uploads",
        headers={"Authorization": "Bearer valid-key"},
        json={"files": [{"filename": "invalid.pdf", "size": True}]},
    )
    assert boolean_upload.status_code == 422
    assert boolean_upload.json["error"]["details"] == {
        "path": "$.files[0].size",
        "expected": "positive integer byte size",
    }
    invalid_filename = client.post(
        "/api/v1/plans/report-key/uploads",
        headers={"Authorization": "Bearer valid-key"},
        json={"files": [{"filename": ["records.pdf"], "size": 100}]},
    )
    assert invalid_filename.status_code == 422
    assert invalid_filename.json["error"]["details"] == {
        "path": "$.files[0].filename",
        "expected": "non-empty string",
    }
    invalid_content_type = client.post(
        "/api/v1/plans/report-key/uploads",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "files": [
                {"filename": "records.pdf", "content_type": 7, "size": 100}
            ]
        },
    )
    assert invalid_content_type.status_code == 422
    assert invalid_content_type.json["error"]["details"] == {
        "path": "$.files[0].content_type",
        "expected": "non-empty string",
    }

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
    upload_batch_id = upload.json["upload_batch_id"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", upload_batch_id)
    assert upload.json["uploads"] == [
        {
            "index": 0,
            "filename": "records.pdf",
            "session_url": "https://storage.example/upload",
            "chunk_size": 8 * 1024 * 1024,
        }
    ]
    assert "token" not in upload.json["uploads"][0]

    def finalize(
        current,
        user,
        *,
        asset_nonce=None,
        ensure_active=None,
        save=None,
    ):
        assert user is actor
        assert re.fullmatch(r"[a-f0-9]{32}", asset_nonce)
        assert ensure_active is not None
        assert save is not None
        ensure_active()
        current.upload_manifest = None

    monkeypatch.setattr(external_api, "finalize_uploads", finalize)
    invalid_finalization = client.post(
        "/api/v1/plans/report-key/uploads/finalize",
        headers={"Authorization": "Bearer valid-key"},
        json={"force": True},
    )
    assert invalid_finalization.status_code == 422
    assert invalid_finalization.json["error"] == {
        "code": "unsupported_field",
        "message": "Upload finalization request contains unsupported fields.",
        "details": {
            "path": "$",
            "fields": ["force"],
            "allowed_fields": ["upload_batch_id"],
        },
    }
    missing_batch_identity = client.post(
        "/api/v1/plans/report-key/uploads/finalize",
        headers={"Authorization": "Bearer valid-key"},
        json={},
    )
    assert missing_batch_identity.status_code == 422
    assert missing_batch_identity.json["error"]["code"] == (
        "invalid_upload_batch_id"
    )
    assert report.upload_manifest
    finalized = client.post(
        "/api/v1/plans/report-key/uploads/finalize",
        headers={"Authorization": "Bearer valid-key"},
        json={"upload_batch_id": upload_batch_id},
    )
    assert finalized.status_code == 200
    assert finalized.json["uploads_pending"] is False
    assert finalized.json["upload_batch_id"] == upload_batch_id

    def execute(name, arguments, user):
        seen.update(name=name, arguments=arguments, user=user)
        return {"items": [{"hash": "pagehash1234"}]}, []

    monkeypatch.setattr(ai_functions, "execute_registered_tool", execute)
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

    monkeypatch.setattr(
        ai_functions,
        "execute_registered_tool",
        lambda name, arguments, user: (
            {
                "error": "id is required",
                "required": ["id"],
                "received": sorted(arguments),
            },
            [],
        ),
    )
    monkeypatch.setattr(
        agent_api_store,
        "claim_plan_operation",
        lambda *_args, **_kwargs: agent_api_store.PLAN_OPERATION_CLAIMED,
    )
    monkeypatch.setattr(
        agent_api_store,
        "release_plan_operation",
        lambda *_args, **_kwargs: True,
    )
    rejected_tool = client.post(
        "/api/v1/plans/report-key/tools/get_schema",
        headers={"Authorization": "Bearer valid-key"},
        json={"arguments": {"hash": "pagehash1234"}},
    )
    assert rejected_tool.status_code == 422
    assert rejected_tool.json["error"] == {
        "code": "tool_error",
        "message": "id is required",
        "details": {
            "tool": "get_schema",
            "required": ["id"],
            "received": ["hash"],
        },
    }

    class DownloadableFile:
        properties = SimpleNamespace(
            file=SimpleNamespace(value=SimpleNamespace(path="private/person.vcf"))
        )

        def allowed(self, action, user=None):
            return user is actor

    monkeypatch.setattr(Entities, "FILE", DownloadableFile)
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda identifier, request: (
            report if identifier == "report-key" else DownloadableFile()
        ),
    )
    monkeypatch.setattr(
        ai_functions,
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
        storage_assets,
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

    def submit(current, user, proposal, *, contract_version, save=None):
        assert user is actor
        assert contract_version == external_api.CONTRACT_VERSION
        assert save is not None
        current.status = "ready"
        current.proposal = proposal
        current.agent_manifest["proposal_fingerprint"] = "normalized-proposal"
        return current

    monkeypatch.setattr(external_api, "submit_plan", submit)
    monkeypatch.setattr(
        external_api,
        "_external_allowed_report_actions",
        lambda user, tool="organize": (
            ("needs_review", "summarize_file") if tool == "organize" else ()
        ),
    )
    proposal = {
        "summary": "Ready for review.",
        "confidence": 1,
        "issues": [],
        "actions": [],
    }
    malformed_submission = client.post(
        "/api/v1/plans/report-key/submit",
        headers={"Authorization": "Bearer valid-key"},
        json={"summary": "Raw proposal", "actions": []},
    )
    assert malformed_submission.status_code == 422
    assert malformed_submission.json["error"]["code"] == "validation_failed"
    malformed_paths = {
        error["path"]
        for error in malformed_submission.json["error"]["details"]["errors"]
    }
    assert {"$.contract_version", "$.proposal", "$.summary"} <= malformed_paths
    submitted = client.post(
        "/api/v1/plans/report-key/submit",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": proposal,
        },
    )
    assert submitted.status_code == 200
    assert submitted.json["status"] == "ready"
    assert submitted.json["proposal_fingerprint"] == "normalized-proposal"
    assert "proposal" not in submitted.json
    assert "execute_url" not in submitted.json
    assert "execution" not in submitted.json

    detailed_plan = client.get(
        "/api/v1/plans/report-key",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert detailed_plan.status_code == 200
    assert detailed_plan.json["proposal"] == proposal

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
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": revised_proposal,
        },
    )
    assert revised_submission.status_code == 200
    assert revised_submission.json["status"] == "ready"
    assert "proposal" not in revised_submission.json

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
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": create_revision,
        },
    )
    assert create_revised_submission.status_code == 200
    assert create_revised_submission.json["status"] == "ready"
    assert "proposal" not in create_revised_submission.json

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
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": proposal,
        },
    )
    assert browser_execution_locked_revision.status_code == 409
    assert browser_execution_locked_revision.json["error"]["code"] == (
        "plan_state_conflict"
    )


# @matrix agent-api mcp-upload : last-writer upload-batch-identity uploads
def test_upload_batch_identity_rejects_a_same_metadata_last_writer(monkeypatch):
    actor = Actor()
    report = _report(actor)
    headers = {
        "Authorization": "Bearer valid-key",
        "X-Request-ID": "upload-race-test",
    }
    monkeypatch.setattr(
        agent_auth,
        "authenticate_credential",
        lambda _token: (actor, {"active": True}),
    )
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(Entities, "save", lambda *_entities: None)
    claim_outcomes = {
        "create": agent_api_store.PLAN_OPERATION_CLAIMED,
        "finalize": agent_api_store.PLAN_OPERATION_CLAIMED,
    }
    claim_calls = []
    renew_calls = []

    def claim(report_key, **options):
        claim_calls.append((report_key, options))
        return claim_outcomes[options["phase"]]

    def renew(report_key, **options):
        renew_calls.append((report_key, options))
        return True

    monkeypatch.setattr(agent_api_store, "claim_plan_operation", claim)
    monkeypatch.setattr(agent_api_store, "renew_plan_operation", renew)
    monkeypatch.setattr(
        agent_api_store,
        "release_plan_operation",
        lambda *_args, **_kwargs: True,
    )
    _allow_claimed_saves(monkeypatch)
    monkeypatch.setattr(
        external_api,
        "bind_upload_file_identities",
        lambda _report, manifest, *, upload_batch_id: [
            {
                **record,
                "file_index": index,
                "file_key": f"stable-file-{index}",
            }
            for index, record in enumerate(manifest)
        ],
    )

    session_count = 0

    def create_session(*_args, **_kwargs):
        nonlocal session_count
        session_count += 1
        return {
            "token": f"storage-token-{session_count}",
            "session_url": f"https://storage.example/upload-{session_count}",
            "chunk_size": 8 * 1024 * 1024,
        }

    monkeypatch.setattr(
        storage_assets,
        "create_direct_upload_session",
        create_session,
    )
    client = app.test_client()
    first_bytes = b"AAAA"
    second_bytes = b"BBBB"
    assert first_bytes != second_bytes
    assert len(first_bytes) == len(second_bytes)
    declaration = {
        "files": [
            {
                "filename": "same.bin",
                "content_type": "application/octet-stream",
                "size": len(first_bytes),
            }
        ]
    }

    first = client.post(
        "/api/v1/plans/report-key/uploads",
        headers=headers,
        json=declaration,
    )
    assert first.status_code == 201
    first_record = dict(report.upload_manifest[0])

    # A worker with a pre-claim snapshot that shows no manifest cannot create
    # storage sessions while another transaction owns the report claim.
    report.upload_manifest = None
    claim_outcomes["create"] = agent_api_store.PLAN_OPERATION_BUSY
    competing = client.post(
        "/api/v1/plans/report-key/uploads",
        headers=headers,
        json=declaration,
    )
    assert competing.status_code == 409
    assert competing.json["error"]["code"] == "plan_operation_in_progress"
    assert session_count == 1
    assert report.upload_manifest is None

    # Once the previous operation has durably completed, a later batch with
    # identical public metadata remains valid and gets a distinct identity.
    claim_outcomes["create"] = agent_api_store.PLAN_OPERATION_CLAIMED
    second = client.post(
        "/api/v1/plans/report-key/uploads",
        headers=headers,
        json=declaration,
    )
    assert second.status_code == 201
    second_record = dict(report.upload_manifest[0])
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", first.json["upload_batch_id"])
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", second.json["upload_batch_id"])
    assert first.json["upload_batch_id"] != second.json["upload_batch_id"]
    assert first_record["token"] != second_record["token"]
    assert {
        key: first_record[key]
        for key in ("filename", "content_type", "size")
    } == {
        key: second_record[key]
        for key in ("filename", "content_type", "size")
    }

    finalized_batches = []

    def finalize(
        current,
        user,
        *,
        asset_nonce=None,
        ensure_active=None,
        save=None,
    ):
        assert user is actor
        assert re.fullmatch(r"[a-f0-9]{32}", asset_nonce)
        assert ensure_active is not None
        assert save is not None
        ensure_active()
        finalized_batches.append(current.upload_manifest[0]["upload_batch_id"])
        current.upload_manifest = None

    monkeypatch.setattr(external_api, "finalize_uploads", finalize)
    stale = client.post(
        "/api/v1/plans/report-key/uploads/finalize",
        headers=headers,
        json={"upload_batch_id": first.json["upload_batch_id"]},
    )
    assert stale.status_code == 409
    assert stale.json["error"]["code"] == "upload_batch_mismatch"
    assert finalized_batches == []
    assert report.upload_manifest[0]["token"] == second_record["token"]

    claim_outcomes["finalize"] = agent_api_store.PLAN_OPERATION_BUSY
    competing_finalizer = client.post(
        "/api/v1/plans/report-key/uploads/finalize",
        headers=headers,
        json={"upload_batch_id": second.json["upload_batch_id"]},
    )
    assert competing_finalizer.status_code == 409
    assert competing_finalizer.json["error"]["code"] == (
        "plan_operation_in_progress"
    )
    assert finalized_batches == []

    claim_outcomes["finalize"] = agent_api_store.PLAN_OPERATION_CLAIMED
    current = client.post(
        "/api/v1/plans/report-key/uploads/finalize",
        headers=headers,
        json={"upload_batch_id": second.json["upload_batch_id"]},
    )
    assert current.status_code == 200
    assert current.json["upload_batch_id"] == second.json["upload_batch_id"]
    assert finalized_batches == [second.json["upload_batch_id"]]
    assert len([call for call in claim_calls if call[1]["phase"] == "create"]) == 3
    assert len([call for call in claim_calls if call[1]["phase"] == "finalize"]) == 2
    assert len([call for call in renew_calls if call[1]["phase"] == "create"]) == 2
    assert len([call for call in renew_calls if call[1]["phase"] == "finalize"]) == 1


# @matrix agent-api mcp-upload : authoritative-reload concurrency checkpoint resume stale-snapshot
def test_claimed_upload_routes_reload_before_storage_side_effects(monkeypatch):
    actor = Actor()
    headers = {"Authorization": "Bearer valid-key"}
    monkeypatch.setattr(
        agent_auth,
        "authenticate_credential",
        lambda _token: (actor, {"active": True}),
    )
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        agent_api_store,
        "claim_plan_operation",
        lambda *_args, **_kwargs: agent_api_store.PLAN_OPERATION_CLAIMED,
    )
    monkeypatch.setattr(
        agent_api_store,
        "renew_plan_operation",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        agent_api_store,
        "release_plan_operation",
        lambda *_args, **_kwargs: True,
    )

    existing_file = SimpleNamespace(
        key="existing-file-key",
        db={},
        properties={},
        urlsafe_key="existing-file-key",
        hash="existingfile1",
        name="Earlier upload",
        filename="earlier.txt",
        mimetype="text/plain",
        size=7,
    )
    initial_create = _report(actor)
    canonical_create = _report(actor)
    canonical_create.input_files = [existing_file]
    fetched = iter((initial_create, canonical_create))
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda *_args, **_kwargs: next(fetched),
    )
    saved_reports = []
    _allow_claimed_saves(monkeypatch, saved_reports)
    monkeypatch.setattr(
        storage_assets,
        "create_direct_upload_session",
        lambda *_args, **_kwargs: {
            "token": "new-storage-token",
            "session_url": "https://storage.example/new-session",
            "chunk_size": 8 * 1024 * 1024,
        },
    )
    monkeypatch.setattr(
        external_api,
        "bind_upload_file_identities",
        lambda _report, manifest, *, upload_batch_id: [
            {
                **record,
                "file_index": index,
                "file_key": f"stable-file-{index}",
            }
            for index, record in enumerate(manifest)
        ],
    )
    client = app.test_client()
    created = client.post(
        "/api/v1/plans/report-key/uploads",
        headers=headers,
        json={"files": [{"filename": "new.txt", "size": 5}]},
    )
    assert created.status_code == 201
    assert saved_reports == [canonical_create]
    assert canonical_create.input_files == [existing_file]
    assert initial_create.upload_manifest is None

    batch_id = "batch-aaaaaaaaaaaaaaaa"
    initial_finalize = _report(actor)
    initial_finalize.agent_manifest["upload_batch_id"] = batch_id
    initial_finalize.upload_manifest = [
        {"upload_batch_id": batch_id, "token": "old-first"},
        {"upload_batch_id": batch_id, "token": "old-second"},
    ]
    canonical_finalize = _report(actor)
    canonical_finalize.agent_manifest["upload_batch_id"] = batch_id
    canonical_finalize.input_files = [existing_file]
    canonical_finalize.upload_manifest = [
        {
            "upload_batch_id": batch_id,
            "token": "old-first",
            "file_key": existing_file.urlsafe_key,
            "complete": True,
        },
        {"upload_batch_id": batch_id, "token": "old-second"},
    ]
    fetched = iter((initial_finalize, canonical_finalize, canonical_finalize))
    finalized_reports = []
    monkeypatch.setattr(
        external_api,
        "finalize_uploads",
        lambda current, _user, **_kwargs: (
            finalized_reports.append(current),
            setattr(current, "upload_manifest", None),
        ),
    )
    finalized = client.post(
        "/api/v1/plans/report-key/uploads/finalize",
        headers=headers,
        json={"upload_batch_id": batch_id},
    )
    assert finalized.status_code == 200
    assert finalized_reports == [canonical_finalize]
    assert initial_finalize.upload_manifest[0].get("complete") is not True


# @pairs agent-api:concurrency agent-api:plan-operation agent-api:submission
# @pairs mcp-upload:concurrency mcp-upload:plan-operation
def test_submission_is_serialized_with_upload_operations(monkeypatch):
    actor = Actor()
    report = _report(actor, tool="ask")
    monkeypatch.setattr(
        agent_auth,
        "authenticate_credential",
        lambda _token: (actor, {"active": True}),
    )
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: report)
    claims = []

    def claim(report_key, **options):
        claims.append((report_key, options))
        return agent_api_store.PLAN_OPERATION_BUSY

    monkeypatch.setattr(agent_api_store, "claim_plan_operation", claim)
    monkeypatch.setattr(
        external_api,
        "submit_plan",
        lambda *_args, **_kwargs: pytest.fail(
            "submission must not run while an upload operation owns the claim"
        ),
    )
    response = app.test_client().post(
        "/api/v1/plans/report-key/submit",
        headers={"Authorization": "Bearer valid-key"},
        json={"contract_version": external_api.CONTRACT_VERSION, "proposal": {}},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "plan_operation_in_progress"
    assert claims[0][0] == report.key
    assert claims[0][1]["phase"] == "submit"


# @matrix agent-api : entitlement-independent public-user request-recheck stale-plan
def test_external_api_ignores_provider_entitlement_but_rechecks_public_eligibility(
    monkeypatch,
):
    actor = Actor()
    report = _report(actor, tool="create")
    monkeypatch.setattr(
        agent_auth,
        "authenticate_credential",
        lambda token: (actor, {"active": True, "generation": 1}),
    )
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        Entities,
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
    def authenticate(token):
        actor = owner if token == "owner-key" else intruder
        return actor, {"active": True, "generation": 1}

    monkeypatch.setattr(agent_auth, "authenticate_credential", authenticate)
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        Entities,
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

    monkeypatch.setattr(external_api, "create_plan", create)
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda identifier, request: report,
    )
    monkeypatch.setattr(
        agent_api_store,
        "claim_plan_operation",
        lambda *_args, **_kwargs: agent_api_store.PLAN_OPERATION_CLAIMED,
    )
    monkeypatch.setattr(
        agent_api_store,
        "release_plan_operation",
        lambda *_args, **_kwargs: True,
    )
    _allow_claimed_saves(monkeypatch)
    monkeypatch.setattr(
        ai_functions,
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

    def submit(current, user, value, *, contract_version, save=None):
        assert current is report
        assert user is actor
        assert value is not None
        assert contract_version == external_api.CONTRACT_VERSION
        assert save is not None
        current.status = "complete"
        current.proposal = {
            **value,
            "answer_html": "<h2>Open tasks</h2><p>Two pages have open tasks.</p>",
        }
        current.proposal.pop("answer_markdown", None)
        current.agent_manifest["proposal_fingerprint"] = "normalized-answer"
        return current

    monkeypatch.setattr(external_api, "submit_plan", submit)
    submitted = client.post(
        "/api/v1/plans/report-key/submit",
        headers=headers,
        json={
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": proposal,
        },
    )
    assert submitted.status_code == 200
    assert submitted.json["status"] == "complete"
    assert "execute_url" not in submitted.json
    assert "execution" not in submitted.json
    assert submitted.json["proposal_fingerprint"] == "normalized-answer"
    assert "proposal" not in submitted.json

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
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": {**proposal, "summary": "One page has an open task."},
        },
    )
    assert revised.status_code == 200
    assert revised.json["status"] == "complete"
    assert "proposal" not in revised.json

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
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        database_get,
        "ai_report_by_hash",
        lambda user_key, report_hash: looked_up.append((user_key, report_hash))
        or "raw-report",
    )
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda record, request: report,
    )

    client = _authenticated_client(monkeypatch, actor)
    redirected = client.get("/tools/api-plan/reporthash12")
    assert redirected.status_code == 302, redirected.get_data(as_text=True)
    assert redirected.headers["Location"].endswith("/tools/reports/report-key")
    assert looked_up == [(actor.key, report.hash)]

    invalid = client.get("/tools/api-plan/not-valid")
    assert invalid.status_code == 404
    assert looked_up == [(actor.key, report.hash)]

    report.properties.user.key = "different-owner"
    denied = client.get("/tools/api-plan/reporthash12")
    assert denied.status_code == 404

    with client.session_transaction() as client_session:
        client_session.clear()
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
    monkeypatch.setattr(
        agent_auth,
        "credential_status",
        lambda current: {"active": False, "generation": 0},
    )
    monkeypatch.setattr(
        agent_auth,
        "issue_credential",
        lambda current: ("lgn_shown-once", issued),
    )
    monkeypatch.setattr(
        agent_auth,
        "revoke_credential",
        lambda current: revoked,
    )

    client = _authenticated_client(monkeypatch, actor)
    status = client.get("/users/me/api-key")
    assert status.status_code == 200, status.get_data(as_text=True)
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
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(
        Entities,
        "fetch_one",
        lambda identifier, request: report,
    )
    monkeypatch.setattr(
        DeferredJobs,
        "start",
        lambda *args, **kwargs: pytest.fail("API report revision called the provider"),
    )

    response = _authenticated_client(monkeypatch, actor).post(
        "/tools/reports/report-key/revise",
        data={"feedback": "Change it"},
    )

    assert response.status_code == 422, response.get_data(as_text=True)
    assert "cannot be revised with the AI provider" in response.get_data(as_text=True)


# @matrix agent-api ai-report : browser-review cas delete skip-action
@pytest.mark.parametrize(
    ("outcome", "message"),
    (
        (agent_api_store.PLAN_OPERATION_BUSY, "being updated"),
        (agent_api_store.PLAN_OPERATION_STALE, "plan changed"),
    ),
)
def test_api_report_browser_mutations_reject_fenced_state_without_side_effects(
    monkeypatch,
    outcome,
    message,
):
    actor = Actor()
    report = _report(actor)
    report.status = "ready"
    report.db = {"proposal": "authoritative-api-proposal"}
    report.proposal = {
        "summary": "Review this external proposal.",
        "confidence": 1,
        "actions": [
            {
                "id": "review-external-plan",
                "type": "needs_review",
                "display_label": "Review external plan",
                "data": {},
            }
        ],
    }
    guarded_calls = []

    def reject_save(current, expected_report, *_entities):
        guarded_calls.append(("save", current, expected_report))
        return outcome

    def reject_delete(current, expected_report, *_entities):
        guarded_calls.append(("delete", current, expected_report))
        return outcome

    def forbidden_side_effect(*_args, **_kwargs):
        pytest.fail("A rejected browser Plan mutation performed a side effect")

    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(Entities, "save", forbidden_side_effect)
    monkeypatch.setattr(Entities, "delete", forbidden_side_effect)
    monkeypatch.setattr(Entities, "touch", forbidden_side_effect)
    monkeypatch.setattr(
        external_operations,
        "save_plan_if_idle",
        reject_save,
    )
    monkeypatch.setattr(
        external_operations,
        "delete_plan_if_idle",
        reject_delete,
    )
    monkeypatch.setattr(DeferredJobs, "cancel", forbidden_side_effect)
    monkeypatch.setattr(
        ai_tools,
        "cleanup_report_upload_manifest",
        forbidden_side_effect,
    )
    client = _authenticated_client(monkeypatch, actor)

    skipped = client.post(
        "/tools/reports/report-key/actions/1/skip",
        json={},
    )
    deleted = client.delete("/tools/reports/report-key")

    assert skipped.status_code == 409, skipped.get_data(as_text=True)
    assert deleted.status_code == 409, deleted.get_data(as_text=True)
    assert message in skipped.get_data(as_text=True).lower()
    assert message in deleted.get_data(as_text=True).lower()
    assert [call[0] for call in guarded_calls] == ["save", "delete"]
    assert all(call[1] is report for call in guarded_calls)
    assert all(
        call[2] == {"proposal": "authoritative-api-proposal"}
        for call in guarded_calls
    )


# @matrix agent-api ai-report : browser-review delete report-execution
def test_api_report_delete_rejects_active_execution_without_side_effects(monkeypatch):
    actor = Actor()
    report = _report(actor)
    report.status = "ready"
    report.deferred_job = {"key": "active-execution-job"}

    def forbidden_side_effect(*_args, **_kwargs):
        pytest.fail("Deleting an active API-origin report performed a side effect")

    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(Entities, "delete", forbidden_side_effect)
    monkeypatch.setattr(Entities, "touch", forbidden_side_effect)
    monkeypatch.setattr(
        external_operations,
        "delete_plan_if_idle",
        forbidden_side_effect,
    )
    monkeypatch.setattr(DeferredJobs, "cancel", forbidden_side_effect)
    monkeypatch.setattr(
        ai_tools,
        "cleanup_report_upload_manifest",
        forbidden_side_effect,
    )

    response = _authenticated_client(monkeypatch, actor).delete(
        "/tools/reports/report-key"
    )

    assert response.status_code == 409, response.get_data(as_text=True)
    assert "being updated" in response.get_data(as_text=True).lower()


# @matrix agent-api ai-report : browser-review cas compensation delete undo
def test_api_report_undo_delete_first_fence_stops_before_compensation(monkeypatch):
    actor = Actor()
    report = _report(actor)
    report.status = "complete"
    report.db = {"process": "complete-api-report"}
    report.result = {
        "ledger_version": 1,
        "status": "complete",
        "actions": [{"id": "undo-one", "type": "skip", "status": "complete"}],
    }
    undo_calls = []
    guarded_calls = []
    compensation_calls = []

    def undo(current, user, *, save=None):
        undo_calls.append((current, user._get_current_object(), save))
        assert save is not None
        save(current)
        compensation_calls.append(current)

    def reject_deleted_report(current, expected_report):
        guarded_calls.append((current, expected_report))
        return agent_api_store.PLAN_OPERATION_MISSING

    def forbidden_side_effect(*_args, **_kwargs):
        pytest.fail("A delete-first guarded undo performed a persistence side effect")

    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(Entities, "save", forbidden_side_effect)
    monkeypatch.setattr(Entities, "delete", forbidden_side_effect)
    monkeypatch.setattr(Entities, "touch", forbidden_side_effect)
    monkeypatch.setattr(ai_tools, "undo_report", undo)
    monkeypatch.setattr(
        external_operations,
        "save_plan_if_idle",
        reject_deleted_report,
    )

    response = _authenticated_client(monkeypatch, actor).post(
        "/tools/reports/report-key/undo"
    )

    assert response.status_code == 422, response.get_data(as_text=True)
    assert "plan changed while undo was in progress" in response.get_data(
        as_text=True
    ).lower()
    assert len(undo_calls) == 1
    assert undo_calls[0][:2] == (report, actor)
    assert guarded_calls == [(report, {"process": "complete-api-report"})]
    assert compensation_calls == []


# @matrix agent-api ai-report : browser-review delete undo
def test_api_report_delete_rejects_undo_in_progress_without_side_effects(monkeypatch):
    actor = Actor()
    report = _report(actor)
    report.status = "undoing"

    def forbidden_side_effect(*_args, **_kwargs):
        pytest.fail("Deleting an API-origin undo in progress performed a side effect")

    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(Entities, "delete", forbidden_side_effect)
    monkeypatch.setattr(Entities, "touch", forbidden_side_effect)
    monkeypatch.setattr(
        external_operations,
        "delete_plan_if_idle",
        forbidden_side_effect,
    )
    monkeypatch.setattr(DeferredJobs, "cancel", forbidden_side_effect)
    monkeypatch.setattr(
        ai_tools,
        "cleanup_report_upload_manifest",
        forbidden_side_effect,
    )

    response = _authenticated_client(monkeypatch, actor).delete(
        "/tools/reports/report-key"
    )

    assert response.status_code == 409, response.get_data(as_text=True)
    assert "being updated" in response.get_data(as_text=True).lower()


# @matrix agent-api ai-report : browser-review error-isolation report-execution
def test_api_report_run_start_error_does_not_save_stale_report(monkeypatch):
    actor = Actor()
    report = _report(actor)
    report.status = "ready"
    report.proposal = {"summary": "Ready", "actions": []}
    start_calls = []

    def fail_start(spec):
        start_calls.append(spec)
        raise RuntimeError("stale external report")

    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(Entities, "REPORT", SimpleNamespace)
    monkeypatch.setattr(Entities, "fetch_one", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(
        Entities,
        "save",
        lambda *_args, **_kwargs: pytest.fail(
            "The API-origin report was saved after its run start failed"
        ),
    )
    monkeypatch.setattr(DeferredJobs, "start", fail_start)
    monkeypatch.setattr(exceptions, "capture", lambda *_args, **_kwargs: None)

    response = _authenticated_client(monkeypatch, actor).post(
        "/tools/reports/report-key/run",
        data={"operation-id": "external-run"},
    )

    assert response.status_code == 422, response.get_data(as_text=True)
    assert "could not be started" in response.get_data(as_text=True)
    assert len(start_calls) == 1
    assert start_calls[0].inputs["report"] is report
