"""Cancellable provider calls use one loop and the current conversation."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from google.genai import types

from lagniappe.core.tools.ai import provider_session
from lagniappe.core.tools.deferred_jobs.errors import DeferredJobClaimLostError


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


# @matrix ai : cancellation deadline retry-ownership
def test_transient_retry_preserves_request_and_uses_one_budget(monkeypatch):
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
    assert config.http_options is None
