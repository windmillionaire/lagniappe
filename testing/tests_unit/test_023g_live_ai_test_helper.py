"""Deterministic coverage for live-AI E2E test support."""

from types import SimpleNamespace

import pytest

from config.ai_models import AI_REQUEST_TIMEOUT_MS, AI_RETRY_ATTEMPTS
from lagniappe.core.definitions import DeferredJobStatus
from testing.utility import live_ai


def test_live_ai_response_timeout_covers_every_provider_attempt():
    assert live_ai.LIVE_AI_RESPONSE_TIMEOUT_MS == (
        AI_REQUEST_TIMEOUT_MS * AI_RETRY_ATTEMPTS + 60_000
    )


def test_quota_fallback_injects_resumable_report_checkpoint(monkeypatch):
    saved = []
    job = SimpleNamespace(
        status=DeferredJobStatus.RETRY_WAIT.value,
        error={"type": "AIQuotaError", "retryable": True},
        checkpoint={},
        next_attempt_at=None,
    )
    proposal = {
        "summary": "Synthetic answer",
        "answer_html": "<p>Synthetic answer</p>",
        "actions": [],
    }
    monkeypatch.setattr(live_ai.Entities, "save", saved.append)

    checkpoint = live_ai.inject_quota_fallback_checkpoint(job, proposal)

    assert checkpoint == {"proposal": proposal, "status": "complete"}
    assert job.checkpoint == checkpoint
    assert job.next_attempt_at is not None
    assert saved == [job]


def test_quota_fallback_rejects_non_quota_job():
    job = SimpleNamespace(
        status=DeferredJobStatus.RETRY_WAIT.value,
        error={"type": "AIException", "retryable": True},
    )

    with pytest.raises(
        AssertionError,
        match="retry-wait AIQuotaError",
    ):
        live_ai.inject_quota_fallback_checkpoint(job, {})
