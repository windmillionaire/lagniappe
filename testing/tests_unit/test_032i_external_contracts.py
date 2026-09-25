"""External contract ownership and guarded checkpoint behavior without Flask."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from lagniappe.core.tools.ai import external_operations as operations
from lagniappe.core.tools.ai.external.openapi import build_openapi_document
from lagniappe.core.tools.ai.reporting.uploads import (
    CHECKPOINT_AMBIGUOUS,
    CHECKPOINT_NOT_COMMITTED,
)


# @pair agent-api:contract
def test_openapi_publishes_runtime_defaults_limits_and_independent_documents():
    document = build_openapi_document(app_name="Example", server_url="https://example.test")
    assert document["info"]["title"] == "Example External Agent API"
    assert document["servers"] == [{"url": "https://example.test"}]
    paths = document["paths"]
    create = paths["/api/v1/plans"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert set(create["properties"]) == {"instructions", "name", "revises_plan_id"}
    assert create["properties"]["revises_plan_id"]["type"] == ["string", "null"]
    assert create["properties"]["name"]["maxLength"] == 120
    contract = paths["/api/v1/plans/{plan_id}/contract"]["get"]
    view = next(item["schema"] for item in contract["parameters"] if item["name"] == "view")
    assert view["enum"] == ["full", "summary", "schema"]
    assert view["default"] == "summary"
    submit = paths["/api/v1/plans/{plan_id}/submit"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert submit["required"] == ["contract_version", "proposal", "file_usage"]
    assert submit["additionalProperties"] is False
    upload = document["components"]["schemas"]["UploadFile"]
    assert upload["required"] == ["filename", "size"]
    assert upload["properties"]["size"] == {
        "type": "integer", "minimum": 1, "maximum": 30 * 1024 * 1024,
        "description": "Exact file size in bytes.",
    }
    assert upload["properties"]["content_type"]["default"] == "application/octet-stream"
    original = deepcopy(document)
    create["properties"]["name"]["maxLength"] = 1
    submit["properties"]["file_usage"]["items"]["properties"].clear()
    upload["properties"].clear()
    assert build_openapi_document(app_name="Example", server_url="https://example.test") == original


# @matrix agent-api : checkpoint concurrency
@pytest.mark.parametrize("failure,reason,disposition", [
    ("prepare", None, CHECKPOINT_NOT_COMMITTED),
    ("transaction", None, CHECKPOINT_AMBIGUOUS),
    ("lost", "plan_operation_lost", CHECKPOINT_NOT_COMMITTED),
    ("stale", "plan_state_conflict", CHECKPOINT_NOT_COMMITTED),
])
def test_claimed_save_preserves_definite_and_ambiguous_checkpoint_failures(monkeypatch, failure, reason, disposition):
    report = SimpleNamespace(key="report", db={"revision": 1})
    plan = object()
    monkeypatch.setattr(operations, "plan_mutation", lambda *args: plan)

    def prepare(current):
        assert current is plan
        if failure == "prepare":
            raise RuntimeError("preparation failed")
        return [SimpleNamespace(entity=report, property_mask=None)]

    def commit(key, **kwargs):
        assert key == "report"
        assert kwargs["expected_report"] == {"revision": 1}
        assert kwargs["claim_token"] == "exact-token"
        assert kwargs["operation_id"] == "batch"
        if failure == "transaction":
            raise RuntimeError("transaction response lost")
        return {
            "lost": operations.agent_api_store.PLAN_OPERATION_LOST,
            "stale": operations.agent_api_store.PLAN_OPERATION_STALE,
        }[failure]

    monkeypatch.setattr(operations, "prepare_durable_writes", prepare)
    monkeypatch.setattr(operations.agent_api_store, "commit_plan_operation", commit)
    monkeypatch.setattr(operations, "consume_mutation_intents", lambda *args: pytest.fail("Failed checkpoint consumed intents"))
    save = operations.claimed_plan_save(report, phase="finalize", operation_id="batch", claim_token="exact-token", user=object(), request_id="request")
    report.db["revision"] = 2
    with pytest.raises(operations.ExternalPlanError if reason else RuntimeError) as caught:
        save(report)
    assert caught.value.checkpoint_disposition == disposition
    if reason:
        assert caught.value.reason == reason


# @matrix agent-api : checkpoint concurrency
def test_claimed_save_advances_snapshot_and_isolates_post_commit_failure(monkeypatch):
    report = SimpleNamespace(key="report", db={"revision": 1})
    actor = object()
    commits, consumed, captured = [], [], []
    monkeypatch.setattr(operations, "plan_mutation", lambda *args: "plan")
    monkeypatch.setattr(operations, "prepare_durable_writes", lambda plan: [SimpleNamespace(entity=report, property_mask={"revision"})])

    def commit(key, **kwargs):
        commits.append(deepcopy(kwargs["expected_report"]))
        assert key == "report"
        assert kwargs["notification_user"] is actor
        assert kwargs["writes"] == [(report, {"revision"})]
        assert (kwargs["phase"], kwargs["operation_id"], kwargs["claim_token"]) == ("submit", "operation", "token")
        return operations.agent_api_store.PLAN_OPERATION_COMMITTED

    def post_commit(plan):
        raise RuntimeError("rebuildable cache unavailable")

    monkeypatch.setattr(operations.agent_api_store, "commit_plan_operation", commit)
    monkeypatch.setattr(operations, "consume_mutation_intents", consumed.append)
    monkeypatch.setattr(operations, "execute_post_commit", post_commit)
    monkeypatch.setattr(operations.exceptions, "capture", lambda error, *, context: captured.append(context))
    save = operations.claimed_plan_save(report, phase="submit", operation_id="operation", claim_token="token", user=actor, request_id="request")
    report.db["revision"] = 2
    save(report)
    report.db["revision"] = 3
    save(report)
    assert commits == [{"revision": 1}, {"revision": 2}]
    assert consumed == ["plan", "plan"]
    assert captured == [{"agent_api": {"request_id": "request", "phase": "submit_post_commit"}}] * 2
