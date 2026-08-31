"""Provider-free external-agent API domain and credential coverage."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from google.cloud.datastore import Key
import pytest

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.core.tools.database import agent_api as credential_store
from testing.utility.ai_report_fakes import _patch_fake_keys, _test_user


# @matrix agent-api ai-report : draft report-session status
# @pair agent-api:origin
@pytest.mark.unit
def test_api_report_draft_preserves_agent_manifest(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("agent-api-owner")
    saved = []
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))

    report = external_api.create_plan(
        user,
        instructions="  Put these records into project pages.  ",
        name="Records import",
    )

    assert saved == [report]
    assert report.origin == "api"
    assert report.status == "draft"
    assert report.pending is False
    assert report.tool == "organize"
    assert report.instructions == "Put these records into project pages."
    assert report.agent_manifest["version"] == 1
    assert report.agent_manifest["contract_version"] == external_api.CONTRACT_VERSION
    assert report.note == "Waiting for external plan"


# @matrix agent-api ai-report : file-placement permissions proposal-contract
@pytest.mark.unit
def test_external_plan_contract_is_permission_and_file_scoped(monkeypatch):
    actor = object()
    report = SimpleNamespace(
        input_files=[SimpleNamespace(hash="aaaaaaaaaaaa")],
    )
    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("create_page",),
    )
    monkeypatch.setattr(
        external_api,
        "report_proposal_response_schema",
        lambda **options: {"allowed": options["allowed_actions"]},
    )
    monkeypatch.setattr(
        external_api,
        "report_action_permission_context",
        lambda user, allowed: {"allowed": allowed},
    )

    contract = external_api.plan_contract(report, actor)

    assert contract["version"] == external_api.CONTRACT_VERSION
    assert contract["proposal_schema"] == {"allowed": ("create_page",)}
    assert contract["permissions"] == {"allowed": ("create_page",)}
    assert contract["required_file_refs"] == ["hash:aaaaaaaaaaaa"]
    assert any(
        "Upload and finalize at least one file" in rule
        for rule in contract["workflow_rules"]
    )
    assert any("never executes" in rule for rule in contract["workflow_rules"])
    assert contract["limits"]["max_tool_calls"] == external_api.MAX_PLAN_TOOL_CALLS


# @matrix agent-api ai : permission-context provider-neutral-dispatch provider-neutral-schema tool-catalog tool-registry
@pytest.mark.unit
def test_external_tool_catalog_and_dispatch_share_registered_tools(monkeypatch):
    names = [tool["name"] for tool in ai_functions.tool_catalog()]
    assert names == list(ai_functions.DECLARATIONS)
    assert all(tool["input_schema"]["type"] == "object" for tool in ai_functions.tool_catalog())
    rest_get_file = next(
        tool
        for tool in ai_functions.tool_catalog(transport="rest")
        if tool["name"] == "get_file"
    )
    assert "short-lived download URL" in rest_get_file["description"]
    assert "expires after five minutes" in rest_get_file["description"]
    assert "temporary credential" in rest_get_file["description"]
    assert "provider file part" not in rest_get_file["description"]

    seen = {}

    def execute(arguments, user):
        seen.update(arguments=arguments, user=user)
        return {"items": ["one"]}, [{"uri": "gs://private/one"}]

    actor = object()
    monkeypatch.setitem(ai_functions.HANDLERS, "search_entities", execute)
    monkeypatch.setattr(
        ai_functions,
        "normalize_hash_references",
        lambda arguments: {**arguments, "normalized": True},
    )

    result, parts = ai_functions.execute_registered_tool(
        "search_entities",
        {"query": "one"},
        actor,
    )

    assert seen == {
        "arguments": {"query": "one", "normalized": True},
        "user": actor,
    }
    assert result == {"items": ["one"]}
    assert parts == [{"uri": "gs://private/one"}]


# @matrix agent-api ai-report : file-placement permissions proposal-validation references
@pytest.mark.unit
def test_external_proposal_validation_enforces_permissions_files_and_shape(
    monkeypatch,
):
    actor = object()
    report = SimpleNamespace(
        input_files=[SimpleNamespace(hash="aaaaaaaaaaaa")],
    )
    captured = {}

    def validate(proposal, **options):
        captured.update(options)
        return proposal

    monkeypatch.setattr(external_api, "allowed_report_actions", lambda user: ("create_page",))
    monkeypatch.setattr(external_api, "validate_proposal", validate)

    proposal = {
        "summary": "Create a page for the uploaded file.",
        "confidence": 0.9,
        "issues": [],
        "actions": [],
    }
    assert external_api.validate_external_proposal(proposal, report, actor) is proposal
    assert captured["allowed_actions"] == ("create_page",)
    assert captured["allow_pending_submissions"] is False
    assert captured["required_file_refs"] == ["hash:aaaaaaaaaaaa"]
    assert captured["validate_reference_kinds"] is True

    with pytest.raises(exceptions.AIException, match="confidence"):
        external_api.validate_external_proposal(
            {**proposal, "confidence": "certain"},
            report,
            actor,
        )

    inaccessible = {
        **proposal,
        "actions": [
            {
                "id": "page-1",
                "type": "create_page",
                "data": {"category": "hash:bbbbbbbbbbbb"},
            }
        ],
    }
    monkeypatch.setattr(
        external_api.cache,
        "get_details_by_hash",
        lambda hashes: {"bbbbbbbbbbbb": {"id": "opaque-id"}},
    )
    denied = SimpleNamespace(
        hash="bbbbbbbbbbbb",
        allowed=lambda action, user: False,
    )
    monkeypatch.setattr(
        external_api.Entities,
        "fetch",
        lambda *identifiers, request: [denied],
    )
    with pytest.raises(exceptions.AIException, match="inaccessible"):
        external_api.validate_external_proposal(inaccessible, report, actor)


# @matrix agent-api ai-report : idempotency proposal-publication ready-state
@pytest.mark.unit
def test_external_proposal_submission_is_idempotent_and_provider_free(monkeypatch):
    proposal = {
        "summary": "Create one page.",
        "confidence": 1,
        "issues": [],
        "actions": [],
    }
    saved = []
    report = SimpleNamespace(
        status="draft",
        pending=False,
        proposal=None,
        summary=None,
        error=None,
        result=None,
        upload_manifest=None,
        input_files=[object()],
        agent_manifest={"contract_version": 1},
    )

    class Process:
        def set_proposal(self, value, status="ready"):
            report.proposal = value
            report.summary = value["summary"]
            report.status = status

    report.properties = SimpleNamespace(process=Process())
    monkeypatch.setattr(
        external_api,
        "validate_external_proposal",
        lambda value, current_report, user: value,
    )
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))

    submitted = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=1,
    )
    repeated = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=1,
    )

    assert submitted is report
    assert repeated is report
    assert report.status == "ready"
    assert report.proposal == proposal
    assert report.agent_manifest["proposal_fingerprint"]
    assert len(saved) == 1


# @matrix agent-api : authentication expiry issue revoke shown-once
@pytest.mark.unit
def test_issue_authenticate_expire_and_revoke_credential(monkeypatch):
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    user = _test_user("credential-owner")
    rows = {}

    def rotate(identifier, user_key, **values):
        row = {
            **values,
            "credential_id": identifier,
            "user": user_key,
            "active": True,
            "generation": int(rows.get(identifier, {}).get("generation") or 0) + 1,
        }
        rows[identifier] = row
        return row

    def revoke(identifier, user_key, **values):
        row = rows[identifier]
        assert row["user"] == user_key
        row = {
            **row,
            **values,
            "active": False,
            "generation": row["generation"] + 1,
        }
        row.pop("token_digest")
        rows[identifier] = row
        return row

    monkeypatch.setattr(credential_store, "rotate_credential", rotate)
    monkeypatch.setattr(credential_store, "revoke_credential", revoke)
    monkeypatch.setattr(
        credential_store,
        "get_credential",
        lambda identifier: rows.get(identifier),
    )
    monkeypatch.setattr(
        agent_auth.Entities,
        "fetch_one",
        lambda identifier, request: user,
    )
    monkeypatch.setattr(CONFIG, "SECRET_KEY", "agent-api-test-secret")

    token, issued = agent_auth.issue_credential(user, now=now)
    authenticated, metadata = agent_auth.authenticate_credential(token, now=now)

    assert authenticated is user
    assert issued == metadata
    assert issued["active"] is True
    assert token.startswith("lgn_")
    assert token not in repr(rows)
    assert agent_auth.credential_status(user, now=now)["active"] is True

    with pytest.raises(agent_auth.AgentAPICredentialError, match="expired"):
        agent_auth.authenticate_credential(
            token,
            now=now + agent_auth.TOKEN_LIFETIME + timedelta(seconds=1),
        )

    revoked = agent_auth.revoke_credential(user, now=now)
    assert revoked["active"] is False
    with pytest.raises(agent_auth.AgentAPICredentialError):
        agent_auth.authenticate_credential(token, now=now)


# @matrix agent-api : authentication tamper user-binding
@pytest.mark.unit
def test_authenticate_rejects_tampered_and_mismatched_credentials(monkeypatch):
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    user = _test_user("credential-mismatch-owner")
    token = (
        f"lgn_{agent_auth.credential_id(user)}."
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN12"
    )
    row = {
        "user": user.key,
        "active": True,
        "generation": 1,
        "token_digest": agent_auth._token_digest(token),
        "issued_at": now,
        "expires_at": now + timedelta(days=1),
    }
    monkeypatch.setattr(credential_store, "get_credential", lambda identifier: row)
    monkeypatch.setattr(agent_auth.Entities, "fetch_one", lambda identifier, request: user)

    with pytest.raises(agent_auth.AgentAPICredentialError):
        agent_auth.authenticate_credential(f"{token[:-1]}x", now=now)

    monkeypatch.setattr(agent_auth, "credential_id", lambda current_user: "x" * 24)
    with pytest.raises(agent_auth.AgentAPICredentialError):
        agent_auth.authenticate_credential(token, now=now)


# @matrix agent-api : credential persistence revoke rotate
@pytest.mark.unit
def test_credential_rotation_and_revocation_are_transactional(monkeypatch):
    key = Key("agent-api", "credential", project="test-project")
    rows = {}
    transactions = []

    class Transaction:
        def __enter__(self):
            transactions.append(self)
            return self

        def __exit__(self, *args):
            return False

        def put(self, row):
            rows[row.key] = row

    class Datastore:
        def transaction(self):
            return Transaction()

        def get(self, requested, transaction=None):
            assert transaction in transactions
            return rows.get(requested)

    monkeypatch.setattr(credential_store, "credential_key", lambda identifier: key)
    monkeypatch.setattr(credential_store.DATA, "_datastore_client", Datastore())
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)

    first = credential_store.rotate_credential(
        "credential",
        "user-key",
        token_digest="first",
        display_prefix="lgn_first",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    second = credential_store.rotate_credential(
        "credential",
        "user-key",
        token_digest="second",
        display_prefix="lgn_second",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    second_generation = second["generation"]
    revoked = credential_store.revoke_credential(
        "credential",
        "user-key",
        revoked_at=now,
    )

    assert first["generation"] == 1
    assert second_generation == 2
    assert revoked["generation"] == 3
    assert revoked["active"] is False
    assert "token_digest" not in revoked
    assert len(transactions) == 3


# @matrix agent-api ai-report : upload-finalization temporary-view-ownership
@pytest.mark.unit
def test_external_upload_finalization_binds_report_user(monkeypatch):
    actor = object()
    captured = {}

    def finalize(report, user, *, file_factory):
        captured["user"] = user
        captured["file"] = file_factory(
            upload=SimpleNamespace(),
            data={"filename": "records.pdf"},
        )
        return [captured["file"]]

    monkeypatch.setattr(external_api, "finalize_report_upload_manifest", finalize)
    monkeypatch.setattr(
        external_api.Entities.FILE,
        "create",
        lambda **options: SimpleNamespace(**options),
    )

    files = external_api.finalize_uploads(object(), actor)

    assert files == [captured["file"]]
    assert captured["user"] is actor
    assert captured["file"].report_user is actor
