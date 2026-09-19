"""Cancellable provider calls use one loop and the current conversation."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from google.genai import types

from lagniappe.core.tools.ai import provider_session
from lagniappe.core.tools.deferred_jobs import control as control_module
from lagniappe.core.tools.deferred_jobs.control import DeferredExecutionControl
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobClaimLostError,
    DeferredJobDeadlineError,
    DeferredJobInfrastructureError,
)


# @matrix ai : cancellation deadline retry-ownership
def test_blocked_request_is_cancelled_and_closed(monkeypatch):
    events = []
    active = [True]

    async def generate(**kwargs):
        active[0] = False
        try:
            await asyncio.Event().wait()
        finally:
            events.append("cancelled")

    async def close():
        events.append("closed")

    def ensure():
        if not active[0]:
            raise DeferredJobClaimLostError("cancelled")

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate), aclose=close), close=lambda: events.append("sync_closed"))
    monkeypatch.setattr(provider_session.genai, "Client", lambda **kwargs: client)
    control = SimpleNamespace(ensure_active=ensure, remaining_seconds=0.001)
    session = provider_session.ProviderSession(control)
    try:
        with pytest.raises(DeferredJobClaimLostError):
            session.request(model="fake", contents=[], config=types.GenerateContentConfig())
    finally:
        session.close()
    assert events == ["cancelled", "closed", "sync_closed"]


# @source lagniappe/core/tools/ai/provider_session.py::ProviderSession
# @source lagniappe/core/tools/deferred_jobs/control.py::DeferredExecutionControl
# @matrix ai : cancellation deadline
# @matrix deferred-jobs : cancellation deadline heartbeat
@pytest.mark.parametrize(
    "stop, expected_error",
    [
        ("cancelled", DeferredJobClaimLostError),
        ("deadline", DeferredJobDeadlineError),
        ("heartbeat-error", DeferredJobInfrastructureError),
    ],
)
def test_execution_control_stops_blocked_provider_at_next_check(monkeypatch, stop, expected_error):
    now = [datetime(2026, 9, 19, tzinfo=timezone.utc)]
    monkeypatch.setattr(control_module, "_utc", lambda: now[0])
    owned = [True]
    activity_reads = Mock(side_effect=lambda: owned[0])
    control = DeferredExecutionControl(
        deadline_at=now[0] + timedelta(seconds=1 if stop == "deadline" else 60),
        active_check=activity_reads,
        progress_callback=lambda _progress: None,
    )
    events = []

    async def generate(**_kwargs):
        if stop == "cancelled":
            owned[0] = False
        elif stop == "heartbeat-error":
            control.mark_background_error(RuntimeError("Heartbeat unavailable"))
        try:
            await asyncio.Event().wait()
        finally:
            events.append("cancelled")

    async def close():
        events.append("closed")

    client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate), aclose=close),
        close=lambda: events.append("sync_closed"),
    )
    monkeypatch.setattr(provider_session.genai, "Client", lambda **_kwargs: client)
    real_wait = asyncio.wait
    waits = []

    async def advance_poll(tasks, *, timeout):
        result = await real_wait(tasks, timeout=0)
        waits.append(timeout)
        now[0] += timedelta(seconds=timeout)
        return result

    monkeypatch.setattr(provider_session.asyncio, "wait", advance_poll)
    session = provider_session.ProviderSession(control)
    try:
        with pytest.raises(expected_error):
            session.request(model="fake", contents=[], config=types.GenerateContentConfig())
    finally:
        session.close()

    assert waits == [1]
    assert activity_reads.call_count == (2 if stop == "cancelled" else 1)
    assert events == ["cancelled", "closed", "sync_closed"]


# @matrix ai : cancellation deadline retry-ownership service-tier
@pytest.mark.parametrize("service_tier", [None, "priority", "flex"])
def test_transient_retry_preserves_request_and_uses_one_budget(monkeypatch, service_tier):
    calls = []
    retries = []
    contents = ["existing conversation"]

    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) != 2:
            raise httpx.ReadTimeout("blocked")
        return "proposal"

    async def close():
        pass

    def claim_retry():
        retries.append(True)
        return len(retries) == 1

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate), aclose=close), close=lambda: None)
    monkeypatch.setattr(provider_session.genai, "Client", lambda **kwargs: client)
    control = SimpleNamespace(ensure_active=lambda: None, remaining_seconds=10, claim_provider_retry=claim_retry)
    session = provider_session.ProviderSession(control)
    config = types.GenerateContentConfig()
    headers = None
    if service_tier:
        headers = {
            "X-Vertex-AI-LLM-Request-Type": "shared",
            "X-Vertex-AI-LLM-Shared-Request-Type": service_tier,
        }
        config.http_options = types.HttpOptions(headers=headers)
    original_config = config.model_dump()
    try:
        assert session.request(model="fake", contents=contents, config=config) == "proposal"
        with pytest.raises(httpx.ReadTimeout):
            session.request(model="fake", contents=contents, config=config)
    finally:
        session.close()
    assert len(calls) == 3
    assert all(call["contents"] is contents for call in calls)
    assert all(call["config"].http_options.retry_options.attempts == 1 for call in calls)
    assert all(call["config"].http_options.timeout == 10000 for call in calls)
    assert all(call["config"].http_options.headers == headers for call in calls)
    assert config.model_dump() == original_config
