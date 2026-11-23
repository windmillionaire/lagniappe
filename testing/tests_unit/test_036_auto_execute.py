"""Unit tests for v2.5 app-wide opt-in automatic plan execution and safety pauses."""

from types import SimpleNamespace

import pytest

from config.ai_settings import normalize_ai_settings
from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import AI, DeferredJobStatus
from lagniappe.core.properties.ai_report_proposal import proposal_fingerprint
from lagniappe.core.tools.ai import auto_execute
from lagniappe.core.tools.ai.external.validation import submission_validation_errors
from lagniappe.core.tools.ai.reporting.execution import request as execution
from lagniappe.core.tools.deferred_jobs.adapters.reports import (
    ReportAdapter,
    ReportExecutionAdapter,
)

pytestmark = pytest.mark.unit


def _make_user(
    *,
    allow_auto_execute=True,
    ai_create=True,
    is_public=False,
    is_admin=False,
    is_active=True,
    is_authenticated=True,
    email="user@example.test",
):
    from collections import defaultdict

    return SimpleNamespace(
        email=email,
        key="user-key",
        urlsafe_key="user-key",
        is_authenticated=is_authenticated,
        is_active=is_active,
        is_public=is_public,
        is_admin=is_admin,
        allow_auto_execute=allow_auto_execute,
        access=lambda level: ai_create if level == AI.CREATE else True,
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(
                ai_action_capabilities=defaultdict(lambda: True)
            )
        ),
    )


def _make_report(actor, *, proposal=None, origin="api", require_review=False):
    proposal = proposal if proposal is not None else {
        "summary": "Create a task",
        "actions": [{"id": "a1", "type": "create_task", "data": {"name": "Test"}}],
        "issues": [],
    }
    manifest = {"proposal_fingerprint": proposal_fingerprint(proposal)}
    if require_review:
        manifest["require_review"] = True
    return SimpleNamespace(
        available=True,
        allowed=lambda *args, **kwargs: True,
        db={},
        origin=origin,
        entity_kind="report",
        properties=SimpleNamespace(user=SimpleNamespace(key=actor.key)),
        proposal=proposal,
        agent_manifest=manifest,
        result=None,
        status="ready",
        upload_manifest=None,
        deferred_job=None,
        urlsafe_key="report-key",
    )


def test_ai_settings_auto_execute_normalization_and_runtime_default(monkeypatch):
    options = {
        "text": [{"id": "gemini-3.7-flash"}, {"id": "gemini-3.5-flash-lite"}],
        "image": [{"id": "gemini-3.1-flash-image"}],
    }
    base = {
        "AI_MODEL": "gemini-3.7-flash",
        "AI_UTILITY_MODEL": "gemini-3.5-flash-lite",
        "AI_IMAGE_MODEL": "gemini-3.1-flash-image",
        "AI_LOCATION": "global",
    }
    normalized = normalize_ai_settings(base, current_settings=base, model_options=options)
    assert "AI_AUTO_EXECUTE" not in normalized

    enabled = normalize_ai_settings(
        {**base, "AI_AUTO_EXECUTE": "true"},
        current_settings=base,
        model_options=options,
    )
    assert enabled["AI_AUTO_EXECUTE"] is True

    disabled = normalize_ai_settings(
        {**base, "AI_AUTO_EXECUTE": "false"},
        current_settings={**base, "AI_AUTO_EXECUTE": True},
        model_options=options,
    )
    assert disabled["AI_AUTO_EXECUTE"] is False

    with pytest.raises(exceptions.AISettingsError):
        normalize_ai_settings(
            {**base, "AI_AUTO_EXECUTE": "maybe"},
            current_settings=base,
            model_options=options,
        )


def test_policy_gates_for_site_user_external_and_onsite(monkeypatch):
    actor = _make_user(allow_auto_execute=True, ai_create=True)
    monkeypatch.setattr(CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", False)
    monkeypatch.setattr(
        auto_execute,
        "runtime_ai_settings",
        lambda config=CONFIG: {"AI_AUTO_EXECUTE": True},
    )

    assert auto_execute.site_auto_execute_enabled()
    assert auto_execute.can_execute_external_plan(actor, remote_mcp=False)
    assert auto_execute.can_execute_external_plan(actor, remote_mcp=True)
    assert auto_execute.can_auto_execute_onsite_plan(actor)

    # Disabling user opt-in blocks unattended external execution, while explicit
    # on-site per-request opt-in remains allowed when site policy & AI.CREATE hold.
    opted_out = _make_user(allow_auto_execute=False)
    assert not auto_execute.can_execute_external_plan(opted_out, remote_mcp=False)
    assert not auto_execute.can_execute_external_plan(opted_out, remote_mcp=True)
    assert auto_execute.can_auto_execute_onsite_plan(opted_out)

    # Public users are always blocked.
    public_user = _make_user(allow_auto_execute=True, is_public=True)
    assert not auto_execute.can_execute_external_plan(public_user, remote_mcp=True)
    assert not auto_execute.can_auto_execute_onsite_plan(public_user)

    # Without AI.CREATE, on-site auto-execute is blocked while external API/MCP still follows user opt-in.
    ask_only = _make_user(allow_auto_execute=True, ai_create=False)
    assert not auto_execute.can_auto_execute_onsite_plan(ask_only)
    assert auto_execute.can_execute_external_plan(ask_only, remote_mcp=False)

    # Disabling site setting blocks all non-experiments execution.
    monkeypatch.setattr(
        auto_execute,
        "runtime_ai_settings",
        lambda config=CONFIG: {"AI_AUTO_EXECUTE": False},
    )
    assert not auto_execute.site_auto_execute_enabled()
    assert not auto_execute.can_execute_external_plan(actor, remote_mcp=False)
    assert not auto_execute.can_auto_execute_onsite_plan(actor)


def test_safety_pause_detects_schema_updates_needs_review_issues_and_require_review():
    actor = _make_user()
    safe_report = _make_report(actor)
    assert auto_execute.plan_requires_review(safe_report) is None

    locked_report = _make_report(actor, require_review=True)
    assert "browser review" in (auto_execute.plan_requires_review(locked_report) or "")

    schema_report = _make_report(
        actor,
        proposal={
            "summary": "Edit form",
            "actions": [{"id": "s1", "type": "update_form_schema", "data": {}}],
            "issues": [],
        },
    )
    assert "form schema" in (auto_execute.plan_requires_review(schema_report) or "")

    needs_review_report = _make_report(
        actor,
        proposal={
            "summary": "Check",
            "actions": [{"id": "n1", "type": "needs_review", "data": {}}],
            "issues": [],
        },
    )
    assert "manual review" in (auto_execute.plan_requires_review(needs_review_report) or "")

    issues_report = _make_report(
        actor,
        proposal={
            "summary": "Check",
            "actions": [{"id": "a1", "type": "create_task", "data": {}}],
            "issues": ["Ambiguous target page"],
        },
    )
    assert "flagged issues" in (auto_execute.plan_requires_review(issues_report) or "")


def test_request_execution_supports_direct_api_and_enforces_safety_pause(monkeypatch):
    from lagniappe.core.tools.ai.reporting import corrections, schema_updates

    actor = _make_user(allow_auto_execute=True)
    monkeypatch.setattr(CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", False)
    monkeypatch.setattr(
        auto_execute,
        "runtime_ai_settings",
        lambda config=CONFIG: {"AI_AUTO_EXECUTE": True},
    )
    started = []
    monkeypatch.setattr(execution.database_utility, "create_named_key", lambda *args: "job-key")
    monkeypatch.setattr(execution.Entities, "fetch_one", lambda *args, **kwargs: None)
    monkeypatch.setattr(schema_updates, "prepare_schema_updates", lambda *args, **kwargs: None)
    monkeypatch.setattr(corrections, "approve_correction", lambda *args: None)
    monkeypatch.setattr(
        execution.DeferredJobs,
        "start",
        lambda spec: started.append(spec) or (SimpleNamespace(idempotency_key=spec.idempotency_key, status="queued"), None),
    )

    safe_report = _make_report(actor, origin="api")
    fp = safe_report.agent_manifest["proposal_fingerprint"]
    job, _ = execution.request_execution(
        safe_report,
        actor,
        operation_id="api-op-1",
        expected_fingerprint=fp,
        remote_mcp=False,
        external_execution=True,
    )
    assert job.idempotency_key == "api-op-1"
    assert started[0].parameters == {"external_execution": True, "remote_mcp": False}

    # Safety-paused proposal is rejected for automatic/external execution.
    schema_report = _make_report(
        actor,
        origin="api",
        proposal={
            "summary": "Schema edit",
            "actions": [{"id": "s1", "type": "update_form_schema", "data": {}}],
            "issues": [],
        },
    )
    with pytest.raises(exceptions.ValidationError, match="form schema"):
        execution.request_execution(
            schema_report,
            actor,
            operation_id="api-op-2",
            expected_fingerprint=schema_report.agent_manifest["proposal_fingerprint"],
            external_execution=True,
        )

    # require_review lock blocks external execution.
    locked = _make_report(actor, origin="api", require_review=True)
    with pytest.raises(exceptions.ValidationError, match="browser review"):
        execution.request_execution(
            locked,
            actor,
            operation_id="api-op-3",
            expected_fingerprint=locked.agent_manifest["proposal_fingerprint"],
            external_execution=True,
        )


def test_report_adapter_chains_safe_onsite_plans_and_pauses_unsafe_or_email(monkeypatch):
    actor = _make_user(allow_auto_execute=True, ai_create=True)
    monkeypatch.setattr(CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(
        auto_execute,
        "runtime_ai_settings",
        lambda config=CONFIG: {"AI_AUTO_EXECUTE": True},
    )

    saved_roots = []
    chained = []
    monkeypatch.setattr(
        "lagniappe.core.tools.deferred_jobs.adapters.reports.Entities.fetch_one",
        lambda key, **kwargs: actor if key == actor.key else None,
    )
    monkeypatch.setattr(
        "lagniappe.core.tools.deferred_jobs.adapters.reports.Entities.save_root",
        lambda entity, **kwargs: saved_roots.append((entity, kwargs)),
    )
    monkeypatch.setattr(
        execution,
        "request_execution",
        lambda report, user, **kwargs: chained.append((report, user, kwargs)) or (None, None),
    )

    adapter = ReportAdapter()
    context = SimpleNamespace(
        actor=actor,
        job=SimpleNamespace(
            status=DeferredJobStatus.SUCCEEDED.value,
            idempotency_key="gen-1",
            urlsafe_key="job-1",
        ),
        parameters={"auto_execute": True},
    )

    # Safe web report chains straight into execution.
    safe_web = _make_report(actor, origin="web")
    adapter._chain_auto_execution(context, safe_web)
    assert len(chained) == 1
    assert chained[0][2]["auto_execute"] is True
    assert chained[0][2]["operation_id"].startswith("auto-execute-")

    # Unsafe web report pauses and records reason instead of chaining.
    unsafe_web = _make_report(
        actor,
        origin="web",
        proposal={
            "summary": "Edit form",
            "actions": [{"id": "s1", "type": "update_form_schema", "data": {}}],
            "issues": [],
        },
    )
    adapter._chain_auto_execution(context, unsafe_web)
    assert len(chained) == 1
    assert "form schema" in unsafe_web.db["auto_execute_pause_reason"]
    assert saved_roots[-1][1] == {"property_mask": ("auto_execute_pause_reason",)}


def test_execution_adapter_rechecks_auto_execute_and_external_policy(monkeypatch):
    actor = _make_user(allow_auto_execute=True, ai_create=True)
    monkeypatch.setattr(CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXPERIMENTS_ENABLED", False)
    monkeypatch.setattr(
        auto_execute,
        "runtime_ai_settings",
        lambda config=CONFIG: {"AI_AUTO_EXECUTE": True},
    )
    monkeypatch.setattr(
        "lagniappe.core.tools.deferred_jobs.adapters.reports.Entities.fetch_one",
        lambda *args, **kwargs: actor,
    )

    adapter = ReportExecutionAdapter()
    for params in (
        {"external_execution": True, "remote_mcp": False},
        {"auto_execute": True},
    ):
        context = SimpleNamespace(actor=actor, parameters=params, ensure_active=lambda: None)
        adapter._ensure_execution_active(context)

    actor.allow_auto_execute = False
    context = SimpleNamespace(
        actor=actor,
        parameters={"external_execution": True, "remote_mcp": False},
        ensure_active=lambda: None,
    )
    with pytest.raises(exceptions.ValidationError, match="no longer allowed"):
        adapter._ensure_execution_active(context)

    # Disabling site AI_AUTO_EXECUTE halts both external and on-site auto-execution.
    monkeypatch.setattr(
        auto_execute,
        "runtime_ai_settings",
        lambda config=CONFIG: {"AI_AUTO_EXECUTE": False},
    )
    for params in (
        {"external_execution": True, "remote_mcp": False},
        {"auto_execute": True},
    ):
        context = SimpleNamespace(actor=actor, parameters=params, ensure_active=lambda: None)
        with pytest.raises(exceptions.ValidationError, match="no longer allowed"):
            adapter._ensure_execution_active(context)


def test_submission_validation_checks_execute_operation_id_and_require_review():
    actor = _make_user()
    report = _make_report(actor)
    base = {"contract_version": 10, "proposal": {"summary": "ok", "confidence": 0.9, "actions": []}, "file_usage": []}

    missing_op = submission_validation_errors({**base, "execute": True}, report, actor)
    assert any(err["path"] == "$.operation_id" for err in missing_op)

    conflict = submission_validation_errors(
        {**base, "execute": True, "require_review": True, "operation_id": "op-1"},
        report,
        actor,
    )
    assert any(err["code"] == "invalid_execution" for err in conflict)

    bad_op = submission_validation_errors(
        {**base, "execute": True, "operation_id": "bad/id"},
        report,
        actor,
    )
    assert any(err["code"] == "invalid_operation_id" for err in bad_op)
