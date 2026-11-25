"""Offline Flask ``test_client()`` suite configuration.

Exercises real Flask routes, decorators, CSRF, security headers, error
handlers, and Jinja wiring without launching Chromium, contacting cloud
Datastore/Redis/Storage, or requiring gcloud/ADC credentials.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import traceback

import pytest

SUITE_ROOT = Path(__file__).resolve().parent


def _invocation_includes_e2e(config: pytest.Config) -> bool:
    e2e_root = (SUITE_ROOT.parent / "tests_e2e").resolve()
    for raw in getattr(config, "args", ()) or ():
        path_text = str(raw).replace("\\", "/").split("::", 1)[0]
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = Path(config.invocation_params.dir) / candidate
        resolved = candidate.resolve(strict=False)
        if (
            resolved == e2e_root
            or resolved.is_relative_to(e2e_root)
            or e2e_root.is_relative_to(resolved)
        ):
            return True
    return False


def pytest_configure(config: pytest.Config) -> None:
    """Keep Flask web boot strictly offline when E2E is not in the session."""
    os.environ["FLASK_ENV"] = "testing"
    if not _invocation_includes_e2e(config):
        os.environ.setdefault("LAGNIAPPE_OFFLINE_WEB_TEST", "1")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test collected under testing/tests_http/ with pytest.mark.http."""
    for item in items:
        if Path(item.path).resolve().is_relative_to(SUITE_ROOT):
            item.add_marker(pytest.mark.http)


def _forbid_live_resource(resource: str):
    """Raise with the application caller when an offline HTTP test reaches live I/O."""

    def fail(*_args, **_kwargs):
        frames = [
            frame
            for frame in traceback.extract_stack()
            if "/lagniappe/" in frame.filename
            and "/testing/" not in frame.filename
            and not frame.filename.endswith("tools/cache/core.py")
            and not frame.filename.endswith("tools/database/core.py")
        ]
        caller = frames[-1] if frames else traceback.extract_stack()[-2]
        raise AssertionError(
            "Offline HTTP tests may not initialize or contact live "
            f"{resource}; attempted by {caller.filename}:{caller.lineno} "
            f"in {caller.name}"
        )

    return fail


@pytest.fixture(autouse=True)
def forbid_live_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent offline HTTP tests from initializing cloud clients or opening sockets."""
    from lagniappe.core.tools.cache import core as cache_core
    from lagniappe.core.tools.database import core as database_core

    monkeypatch.setattr(
        database_core.DataServices,
        "initialize",
        _forbid_live_resource("Datastore or Storage"),
    )
    monkeypatch.setattr(
        cache_core.Cache,
        "initialize",
        _forbid_live_resource("Redis"),
    )
    monkeypatch.setattr(
        cache_core.CacheJSON,
        "initialize",
        _forbid_live_resource("Redis JSON"),
    )

    blocked = _forbid_live_resource("network resources")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)

    try:
        import requests
    except ImportError:
        return
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)


@pytest.fixture(autouse=True)
def in_memory_rate_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    """Provide an isolated in-memory Redis shim for fixed-window rate limiting."""
    from types import SimpleNamespace
    from lagniappe.core.tools.cache import rate_limit

    counts: dict[str, int] = {}
    ttls: dict[str, int] = {}

    class _InMemoryRateLimitRedis:
        def incr(self, key: str) -> int:
            counts[key] = counts.get(key, 0) + 1
            return counts[key]

        def expire(self, key: str, seconds: int) -> bool:
            ttls[key] = seconds
            return True

        def ttl(self, key: str) -> int:
            return ttls.get(key, -1)

    monkeypatch.setattr(
        rate_limit, "cache", SimpleNamespace(redis=_InMemoryRateLimitRedis())
    )
    return counts


@pytest.fixture
def http_client():
    """Return a clean Flask test_client() backed by the offline web app."""
    from lagniappe.web import app

    return app.test_client()


@pytest.fixture
def authenticated_http_client(monkeypatch: pytest.MonkeyPatch):
    """Return a factory for a Flask test_client() authenticated as ``actor``."""
    from lagniappe.web import app

    def _build(actor, *, session_values: dict | None = None):
        client = app.test_client()
        actor_id = actor.get_id() if hasattr(actor, "get_id") else actor.urlsafe_key
        monkeypatch.setattr(
            app.login_manager,
            "_user_callback",
            lambda identifier: actor if identifier == actor_id else None,
        )
        with client.session_transaction() as client_session:
            client_session["_user_id"] = actor_id
            client_session["_fresh"] = True
            if session_values:
                client_session.update(session_values)
        return client

    return _build
