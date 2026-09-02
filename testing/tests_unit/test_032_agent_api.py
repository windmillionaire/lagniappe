"""Provider-free external-agent API domain and credential coverage."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from google.cloud.datastore import Key
import pytest

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai import functions as ai_functions
from lagniappe.core.tools.ai import references as ai_references
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.core.tools.database import agent_api as credential_store
from testing.utility.ai_report_fakes import _patch_fake_keys, _test_user


def _contract_actor():
    page = SimpleNamespace(
        hash="personalpage",
        name="Personal Page",
        url="/pages/personal-page",
        allowed=lambda action, user=None: True,
    )
    return SimpleNamespace(page=page)


# @matrix agent-api : bootstrap discovery secret-handling tool-envelope
@pytest.mark.unit
def test_client_skill_markdown_is_minimal_and_discovery_first():
    skill = external_api.client_skill_markdown("https://lagniappe.test/api/v1/")

    assert skill.startswith("---\nname: lagniappe\n")
    assert "https://lagniappe.test/api/v1`" in skill
    assert "$LAGNIAPPE_API_KEY" in skill
    assert "`openapi_url`" in skill
    assert "`actor_url`" in skill
    assert '{"arguments": {...}}' in skill
    assert "reuse them in memory" in skill
    assert "exact `input_schema`" in skill
    assert "Choose Ask for a read-only answer" in skill
    assert "untrusted evidence" in skill
    assert "ready for authenticated website review" in skill
    assert "not a round-trippable submission source" in skill
    assert "authenticated website" in skill
    assert "create_page" not in skill
    assert "Bearer <" not in skill


# @matrix agent-api ai-report : draft report-session status
# @pair agent-api:entitlement-independent
# @pair agent-api:origin
@pytest.mark.unit
def test_api_report_draft_preserves_agent_manifest(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("agent-api-owner")
    user.ai_access = "NONE"
    user.access = lambda required: pytest.fail(
        "External plan creation consulted provider entitlement"
    )
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


# @matrix agent-api ai-report : external-schema proposal-contract structured-output
@pytest.mark.unit
def test_external_proposal_schema_has_named_discriminated_actions():
    schema = external_api.external_report_proposal_response_schema(
        allowed_actions=(
            "create_task",
            "attach_file_to_task",
            "summarize_file",
        ),
        require_file_summary_terms=True,
    )

    assert "propertyOrdering" not in schema
    assert schema["properties"]["actions"]["items"] == {
        "oneOf": [
            {"$ref": "#/$defs/create_task"},
            {"$ref": "#/$defs/attach_file_to_task"},
            {"$ref": "#/$defs/summarize_file"},
        ],
        "discriminator": {
            "propertyName": "type",
            "mapping": {
                "create_task": "#/$defs/create_task",
                "attach_file_to_task": "#/$defs/attach_file_to_task",
                "summarize_file": "#/$defs/summarize_file",
            },
        },
    }
    create_task = schema["$defs"]["create_task"]
    assert create_task["properties"]["type"] == {
        "type": "string",
        "const": "create_task",
    }
    assert create_task["properties"]["data"]["allOf"][0]["anyOf"] == [
        {"required": ["page"]},
        {"required": ["page_action"]},
    ]
    summary_data = schema["$defs"]["summarize_file"]["properties"]["data"]
    assert "retrieval_terms" in summary_data["required"]
    assert summary_data["properties"]["retrieval_terms"]["uniqueItems"] is True
    assert summary_data["properties"]["retrieval_terms"]["items"][
        "maxLength"
    ] == 80


# @matrix agent-api ai-report : file-placement file-summary permissions proposal-contract
@pytest.mark.unit
def test_external_plan_contract_is_permission_and_file_scoped(monkeypatch):
    actor = _contract_actor()
    report = SimpleNamespace(
        tool="organize",
        input_files=[SimpleNamespace(hash="aaaaaaaaaaaa")],
    )
    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("create_page", "move_page"),
    )
    monkeypatch.setattr(
        external_api,
        "external_report_proposal_response_schema",
        lambda **options: {
            "allowed": options["allowed_actions"],
            "require_file_summary_terms": options["require_file_summary_terms"],
        },
    )
    monkeypatch.setattr(
        external_api,
        "report_action_permission_context",
        lambda user, allowed: {"allowed": allowed},
    )
    monkeypatch.setattr(
        external_api.dates,
        "user_today",
        lambda _user=None: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )

    contract = external_api.plan_contract(report, actor)

    assert contract["version"] == external_api.CONTRACT_VERSION
    assert contract["current_date"] == "2026-08-31"
    assert contract["timezone"] == "UTC"
    assert contract["personal_page"] == {
        "kind": "page",
        "hash": "hash:personalpage",
        "name": "Personal Page",
        "url": "/pages/personal-page",
        "can_view": True,
        "can_edit": True,
    }
    assert contract["workflow_rules"][0].startswith(
        "personal_page is the authenticated user's guaranteed editable Page"
    )
    assert contract["submission_format"] == {
        "contract_version": external_api.CONTRACT_VERSION,
        "body": {
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": "<object matching proposal_schema>",
        },
        "rule": (
            "POST this wrapper object to submit_url; do not post the proposal "
            "object as the top-level request body."
        ),
    }
    assert contract["proposal_schema"] == {
        "allowed": ("create_page", "move_page", "summarize_file"),
        "require_file_summary_terms": True,
    }
    assert contract["permissions"] == {
        "allowed": ("create_page", "move_page", "summarize_file")
    }
    assert contract["required_file_refs"] == ["hash:aaaaaaaaaaaa"]
    assert any(
        "Upload and finalize at least one file" in rule
        for rule in contract["workflow_rules"]
    )
    assert any(
        "get_guidelines with task=organize" in rule
        for rule in contract["workflow_rules"]
    )
    assert any("two phases" in rule for rule in contract["workflow_rules"])
    assert any(
        "will not call a model" in rule for rule in contract["workflow_rules"]
    )
    assert any(
        "exactly one summarize_file" in rule
        for rule in contract["workflow_rules"]
    )
    assert any("never applies" in rule for rule in contract["workflow_rules"])
    assert any(
        "ready Organize proposal remains conversationally revisable" in rule
        for rule in contract["workflow_rules"]
    )
    assert any(
        "exact id of an earlier action" in rule
        and "never takes a workspace hash" in rule
        for rule in contract["reference_rules"]
    )
    assert any(
        "data.submission is the Form field-value object" in rule
        and "not an existing submission reference" in rule
        for rule in contract["reference_rules"]
    )
    assert contract["limits"]["max_tool_calls"] == external_api.MAX_PLAN_TOOL_CALLS


# @pairs agent-api:create-revision agent-api:organize-revision agent-api:proposal-contract ai-report:proposal-contract
# @pair ai-report:task-page
@pytest.mark.unit
def test_external_plan_contracts_distinguish_ask_and_create(monkeypatch):
    actor = _contract_actor()
    monkeypatch.setattr(
        external_api.dates,
        "user_today",
        lambda _user=None: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )

    ask_contract = external_api.plan_contract(
        SimpleNamespace(tool="ask", input_files=[]),
        actor,
    )

    assert ask_contract["tool"] == "ask"
    assert ask_contract["uploads_supported"] is False
    assert "execution_supported" not in ask_contract
    assert ask_contract["required_file_refs"] == []
    assert "answer_markdown" in ask_contract["proposal_schema"]["properties"]
    assert ask_contract["proposal_schema"]["properties"]["actions"]["maxItems"] == 0
    assert any("separate Create or Organize plan" in rule for rule in ask_contract["workflow_rules"])
    assert any(
        "without waiting for separate save confirmation" in rule
        for rule in ask_contract["workflow_rules"]
    )
    assert any(
        "remain available after an Ask submission" in rule
        for rule in ask_contract["workflow_rules"]
    )

    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("create_page", "create_task", "move_page", "needs_review"),
    )
    monkeypatch.setattr(
        external_api,
        "report_action_permission_context",
        lambda user, allowed: {"allowed_actions": list(allowed)},
    )
    create_contract = external_api.plan_contract(
        SimpleNamespace(tool="create", input_files=[]),
        actor,
    )

    assert create_contract["tool"] == "create"
    assert create_contract["uploads_supported"] is False
    assert "execution_supported" not in create_contract
    assert create_contract["permissions"]["allowed_actions"] == [
        "create_page",
        "create_task",
        "needs_review",
    ]
    action_items = create_contract["proposal_schema"]["properties"]["actions"][
        "items"
    ]
    assert set(action_items["discriminator"]["mapping"]) == {
        "create_page",
        "create_task",
        "needs_review",
    }
    create_page = create_contract["proposal_schema"]["$defs"]["create_page"]
    assert "document_markdown" in create_page["properties"]["data"]["properties"]
    assert any(
        "ready Create proposal remains conversationally revisable" in rule
        for rule in create_contract["workflow_rules"]
    )
    assert any(
        "authenticated website" in rule and "no execution operation" in rule
        for rule in create_contract["workflow_rules"]
    )
    assert any(
        "Every create_task action requires its editable destination Page" in rule
        and "page_name is display context only" in rule
        for rule in create_contract["reference_rules"]
    )


# @matrix agent-api : ask create organize tool-selection
@pytest.mark.unit
def test_external_plan_tool_selection_is_provider_independent():
    assert external_api.normalize_plan_tool(" Ask ") == "ask"
    with pytest.raises(exceptions.ValidationError, match="ask, create, or organize"):
        external_api.normalize_plan_tool("email")


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


# @matrix agent-api ai-report : file-placement file-summary permissions proposal-validation references
@pytest.mark.unit
def test_external_proposal_validation_enforces_permissions_files_and_shape(
    monkeypatch,
):
    actor = object()
    report = SimpleNamespace(
        tool="organize",
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
    assert captured["allowed_actions"] == ("create_page", "summarize_file")
    assert captured["allow_pending_submissions"] is False
    assert captured["required_file_refs"] == ["hash:aaaaaaaaaaaa"]
    assert captured["require_file_summaries"] is True
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
# @pair agent-api:organize-revision
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
        tool="organize",
        status="draft",
        pending=False,
        proposal=None,
        summary=None,
        error=None,
        result=None,
        upload_manifest=None,
        input_files=[object()],
        agent_manifest={"contract_version": external_api.CONTRACT_VERSION},
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
        contract_version=external_api.CONTRACT_VERSION,
    )
    repeated = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    revised = external_api.submit_plan(
        report,
        object(),
        {**proposal, "summary": "Create a different page."},
        contract_version=external_api.CONTRACT_VERSION,
    )

    assert submitted is repeated is revised is report
    assert report.status == "ready"
    assert report.proposal["summary"] == "Create a different page."
    assert report.agent_manifest["proposal_fingerprint"]
    assert saved == [report, report]


# @pairs agent-api:ask agent-api:ask-revision ai-report:answer-only
@pytest.mark.unit
def test_external_ask_submission_completes_without_files_or_execution(monkeypatch):
    proposal = {
        "summary": "The page has two open tasks.",
        "answer_markdown": "## Result\n\nThere are **two** open tasks.",
        "confidence": 0.95,
        "actions": [],
    }
    report = SimpleNamespace(
        tool="ask",
        status="draft",
        pending=False,
        proposal=None,
        summary=None,
        error=None,
        result=None,
        upload_manifest=None,
        input_files=[],
        agent_manifest={"contract_version": external_api.CONTRACT_VERSION},
    )

    class Process:
        def set_proposal(self, value, status="ready"):
            report.proposal = value
            report.summary = value["summary"]
            report.status = status

    report.properties = SimpleNamespace(process=Process())
    saved = []
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))

    submitted = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    repeated = external_api.submit_plan(
        report,
        object(),
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    revised = external_api.submit_plan(
        report,
        object(),
        {
            **proposal,
            "summary": "The page now has one open task.",
            "answer_markdown": "## Updated result\n\nThere is **one** open task.",
        },
        contract_version=external_api.CONTRACT_VERSION,
    )

    assert submitted is repeated is revised is report
    assert report.status == "complete"
    assert "answer_markdown" not in report.proposal
    assert report.summary == "The page now has one open task."
    assert "<h2>Updated result</h2>" in report.proposal["answer_html"]
    assert saved == [report, report]


# @pairs agent-api:ask ai-report:answer-only
@pytest.mark.unit
def test_external_ask_submission_allows_hash_token_in_named_link_destination(
    monkeypatch,
):
    monkeypatch.setattr(
        ai_references.cache,
        "get_details_by_hash",
        lambda hashes: {
            "8328b23bef92": {"id": "canonical-cypress-page-key"}
        },
    )
    report = SimpleNamespace(tool="ask")
    proposal = {
        "summary": "Cypress Hive has an open follow-up task.",
        "answer_markdown": (
            "Review [Cypress Hive](/pages/hash:8328b23bef92) for details."
        ),
        "confidence": 0.95,
        "actions": [],
    }

    normalized = external_api.validate_external_proposal(
        proposal,
        report,
        object(),
    )

    assert "answer_markdown" not in normalized
    assert 'href="/pages/canonical-cypress-page-key"' in normalized["answer_html"]
    assert ">Cypress Hive</a>" in normalized["answer_html"]
    assert "hash:8328b23bef92" not in normalized["answer_html"]

    proposal["answer_markdown"] = "The internal reference is hash:8328b23bef92."
    with pytest.raises(exceptions.AIException, match="human names and URLs"):
        external_api.validate_external_proposal(proposal, report, object())

    proposal.pop("answer_markdown")
    proposal["answer_html"] = "<script>alert('unsafe')</script><p>Result</p>"
    with pytest.raises(exceptions.AIException, match="unsupported fields: answer_html"):
        external_api.validate_external_proposal(proposal, report, object())


# @pairs agent-api:create ai-report:proposal-publication
# @pair agent-api:create-revision
@pytest.mark.unit
def test_external_create_submission_renders_markdown_without_files(monkeypatch):
    actor = object()
    proposal = {
        "summary": "Create a field guide page.",
        "confidence": 0.9,
        "issues": [],
        "actions": [
            {
                "id": "field-guide",
                "type": "create_page",
                "data": {
                    "name": "Field Guide",
                    "document_markdown": (
                        "# Field Guide\n\n- First item\n\n"
                        "[Source](https://example.com/reference) "
                        "[Unsafe](javascript:alert('no'))"
                    ),
                },
            }
        ],
    }
    report = SimpleNamespace(
        tool="create",
        status="draft",
        pending=False,
        proposal=None,
        summary=None,
        error=None,
        result=None,
        upload_manifest=None,
        input_files=[],
        agent_manifest={"contract_version": external_api.CONTRACT_VERSION},
    )

    class Process:
        def set_proposal(self, value, status="ready"):
            report.proposal = value
            report.summary = value["summary"]
            report.status = status

    report.properties = SimpleNamespace(process=Process())
    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("create_page", "needs_review"),
    )
    saved = []
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))

    submitted = external_api.submit_plan(
        report,
        actor,
        proposal,
        contract_version=external_api.CONTRACT_VERSION,
    )
    initial_document = report.proposal["actions"][0]["data"]["document"]
    assert 'href="https://example.com/reference"' in initial_document
    assert 'rel="noopener noreferrer"' in initial_document
    assert "javascript:" not in initial_document

    revised = external_api.submit_plan(
        report,
        actor,
        {
            **proposal,
            "summary": "Create a field guide page with a revised introduction.",
            "actions": [
                {
                    **proposal["actions"][0],
                    "data": {
                        **proposal["actions"][0]["data"],
                        "document_markdown": "# Field Guide\n\nA revised introduction.",
                    },
                }
            ],
        },
        contract_version=external_api.CONTRACT_VERSION,
    )

    assert submitted is revised is report
    assert report.status == "ready"
    assert submitted.input_files == []
    data = report.proposal["actions"][0]["data"]
    assert "document_markdown" not in data
    assert data["document"].startswith("<h1>Field Guide</h1>")
    assert "A revised introduction." in data["document"]
    assert saved == [report, report]


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

    replacement_token, replacement = agent_auth.issue_credential(user, now=now)
    assert replacement["active"] is True
    assert replacement["generation"] == revoked["generation"] + 1
    assert replacement_token != token
    with pytest.raises(agent_auth.AgentAPICredentialError):
        agent_auth.authenticate_credential(token, now=now)
    authenticated, metadata = agent_auth.authenticate_credential(
        replacement_token,
        now=now,
    )
    assert authenticated is user
    assert metadata == replacement


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
    replacement = credential_store.rotate_credential(
        "credential",
        "user-key",
        token_digest="replacement",
        display_prefix="lgn_replacement",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )

    assert first["generation"] == 1
    assert second_generation == 2
    assert revoked["generation"] == 3
    assert revoked["active"] is False
    assert "token_digest" not in revoked
    assert replacement["generation"] == 4
    assert replacement["active"] is True
    assert replacement["token_digest"] == "replacement"
    assert len(transactions) == 4


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
