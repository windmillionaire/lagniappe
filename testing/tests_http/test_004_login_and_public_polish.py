"""Offline HTTP tests for public-page snippet safety, login notice, and demo guest mode."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from flask import render_template_string

from lagniappe import CONFIG
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.web import app
from lagniappe.web.routes.users import login as login_routes


pytestmark = pytest.mark.http


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'<input id="token" type="hidden" value="([^"]+)"', html)
    assert match is not None, "Expected CSRF token hidden input in rendered HTML"
    return match.group(1)


def _stub_login_page_state(monkeypatch: pytest.MonkeyPatch, *, owner_setup: bool = False) -> None:
    monkeypatch.setattr(Entities.PUBLIC_GROUP, "enabled", lambda: False)
    monkeypatch.setattr(login_routes, "_owner_requires_first_login", lambda: owner_setup)


class _FakeDemoUser:
    def __init__(
        self,
        record: dict[str, object] | None = None,
        *,
        email: str = "demo@example.test",
        is_admin: bool = False,
        is_owner: bool = False,
    ) -> None:
        resolved_email = str((record or {}).get("email") or email)
        self.email = resolved_email
        self.name = "Demo Guest"
        self.hash = "demo-guest-hash"
        self.urlsafe_key = "demo-user-key"
        self.page = SimpleNamespace(urlsafe_key="demo-user-page-key")
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False
        self.is_admin = bool((record or {}).get("is_admin", is_admin))
        self.is_owner = bool((record or {}).get("is_owner", is_owner))
        self.invalidate_cache = False
        self.db: dict[str, object] = {}

    def get_id(self) -> str:
        return self.email


def test_offline_banner_in_base_layout_carries_data_nosnippet():
    with app.test_request_context("/offline-banner-check"):
        rendered = render_template_string(
            '{% extends "layouts/base.html" %}{% block content %}<p>Body</p>{% endblock %}'
        )

    banner_match = re.search(
        r'<section[^>]*data-role="upstream-unavailable"[^>]*>',
        rendered,
    )
    assert banner_match is not None
    assert "data-nosnippet" in banner_match.group(0)


def test_login_notice_is_absent_by_default_and_renders_safely_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    http_client,
):
    _stub_login_page_state(monkeypatch, owner_setup=False)
    monkeypatch.setattr(CONFIG, "LOGIN_NOTICE", "")
    monkeypatch.setattr(CONFIG, "DEMO_GUEST_EMAIL", "")

    default_response = http_client.get("/users/login")
    assert default_response.status_code == 200
    default_html = default_response.get_data(as_text=True)
    assert 'data-role="login-notice"' not in default_html
    assert 'data-role="demo-guest-form"' not in default_html

    monkeypatch.setattr(
        CONFIG,
        "LOGIN_NOTICE",
        (
            "Explore [public pages](/public/) or [docs](https://example.test/docs).\n"
            "<script>alert(1)</script> [blocked](javascript:alert(1)) [proto](//evil.test)"
        ),
    )
    configured_response = http_client.get("/users/login")
    assert configured_response.status_code == 200
    html = configured_response.get_data(as_text=True)
    assert 'data-role="login-notice"' in html
    assert 'href="/public/"' in html
    assert ">public pages</a>" in html
    assert 'href="https://example.test/docs"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html
    assert "<br>" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "javascript:alert(1)" in html
    assert 'href="javascript:alert(1)"' not in html
    assert 'href="//evil.test"' not in html

    # Initial owner setup suppresses the optional login notice.
    _stub_login_page_state(monkeypatch, owner_setup=True)
    setup_response = http_client.get("/users/login")
    assert setup_response.status_code == 200
    assert 'data-role="login-notice"' not in setup_response.get_data(as_text=True)


def test_demo_login_is_disabled_by_default_and_refuses_privileged_accounts(
    monkeypatch: pytest.MonkeyPatch,
    http_client,
):
    _stub_login_page_state(monkeypatch, owner_setup=False)
    monkeypatch.setattr(CONFIG, "DEMO_GUEST_EMAIL", "")

    login_html = http_client.get("/users/login").get_data(as_text=True)
    token = _extract_csrf_token(login_html)

    disabled = http_client.post("/users/demo-login", data={"csrf_token": token})
    assert disabled.status_code == 404

    # Configuring the owner email as demo guest must not expose the button or allow login.
    monkeypatch.setattr(CONFIG, "DEMO_GUEST_EMAIL", CONFIG.ADMIN_EMAIL.casefold())
    owner_html = http_client.get("/users/login").get_data(as_text=True)
    assert 'data-role="demo-guest-form"' not in owner_html
    refused_owner = http_client.post("/users/demo-login", data={"csrf_token": token})
    assert refused_owner.status_code == 403

    # A database user promoted to admin must also be rejected at login time.
    monkeypatch.setattr(CONFIG, "DEMO_GUEST_EMAIL", "demo-admin@example.test")
    monkeypatch.setattr(
        database_get,
        "user",
        lambda email: {"email": email, "is_admin": True},
    )
    monkeypatch.setattr(Entities, "USER", _FakeDemoUser)
    refused_admin = http_client.post("/users/demo-login", data={"csrf_token": token})
    assert refused_admin.status_code == 403


def test_demo_guest_login_enforces_read_only_guard_and_clean_logout(
    monkeypatch: pytest.MonkeyPatch,
    http_client,
):
    demo_email = "demo@example.test"
    demo_user = _FakeDemoUser(email=demo_email)
    recorded_logins: list[tuple[str, str | None]] = []

    _stub_login_page_state(monkeypatch, owner_setup=False)
    monkeypatch.setattr(CONFIG, "DEMO_GUEST_EMAIL", demo_email)
    monkeypatch.setattr(
        database_get,
        "user",
        lambda email: {"email": email} if email == demo_email else None,
    )
    monkeypatch.setattr(Entities, "USER", _FakeDemoUser)
    monkeypatch.setattr(
        login_routes,
        "record_login",
        lambda user, provider=None: recorded_logins.append((user.email, provider)),
    )
    monkeypatch.setattr(
        app.login_manager,
        "_user_callback",
        lambda identifier: demo_user if identifier == demo_email else None,
    )

    # Render /users/login with the secondary demo button and valid CSRF token.
    login_response = http_client.get("/users/login")
    assert login_response.status_code == 200
    login_html = login_response.get_data(as_text=True)
    assert 'data-role="demo-guest-form"' in login_html
    assert 'action="/users/demo-login"' in login_html
    token = _extract_csrf_token(login_html)

    # Missing CSRF token is still rejected.
    csrf_missing = http_client.post("/users/demo-login")
    assert csrf_missing.status_code == 400
    assert csrf_missing.headers["X-Lagniappe-CSRF"] == "invalid"

    # Valid demo sign-in redirects home, sets demo session flag, and omits remember cookie.
    signed_in = http_client.post(
        "/users/demo-login",
        data={"csrf_token": token, "next": "/pages/example"},
    )
    assert signed_in.status_code == 302
    assert signed_in.headers["Location"] == "/pages/example"
    assert recorded_logins == [(demo_email, "demo-guest")]
    set_cookies = signed_in.headers.getlist("Set-Cookie")
    assert not any("remember_token=" in cookie for cookie in set_cookies)

    with http_client.session_transaction() as client_session:
        assert client_session.get("_user_id") == demo_email
        assert client_session.get(CONFIG.LOGIN_DEMO_GUEST_KEY) is True

    # GET requests remain allowed.
    ping = http_client.get("/l/ping")
    assert ping.status_code == 200

    # Mutating HTTP methods are blocked across the app with 403.
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        blocked_json = http_client.open(
            "/l/site-settings/public-pages",
            method=method,
            headers={
                "X-CSRFToken": token,
                "X-Lagniappe-Request": "true",
            },
            json={"PUBLIC_PAGE_INDEXING": True},
        )
        assert blocked_json.status_code == 403
        assert blocked_json.json == {
            "success": False,
            "error": "Demo accounts are read-only.",
        }

    blocked_html = http_client.post(
        "/l/site-settings/public-pages",
        data={"csrf_token": token, "PUBLIC_PAGE_INDEXING": "true"},
    )
    assert blocked_html.status_code == 403
    assert "Demo accounts are read-only." in blocked_html.get_data(as_text=True)

    # Session timezone updates succeed in cookie session without saving the shared Datastore user.
    monkeypatch.setattr(Entities, "fetch", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        Entities,
        "save_root",
        lambda *_args, **_kwargs: pytest.fail("Demo guest must not persist Datastore writes"),
    )
    session_update = http_client.post(
        "/l/update-session",
        headers={"X-CSRFToken": token, "X-Lagniappe-Request": "true"},
        json={"timezone": "UTC"},
    )
    assert session_update.status_code == 200
    assert session_update.json == {"userHash": "demo-guest-hash"}

    # Read-only browser POST endpoints (/l/poll, /l/refresh) pass the demo-guest guard,
    # while document mutations (/l/sync) remain blocked with 403.
    poll_response = http_client.post(
        "/l/poll",
        headers={"X-CSRFToken": token, "X-Lagniappe-Request": "true"},
        json={"version": 1, "client_id": "demo-client", "subscriptions": []},
    )
    assert poll_response.status_code == 422
    assert (poll_response.json or {}).get("code") == "invalid_poll_contract"

    refresh_response = http_client.post(
        "/l/refresh",
        headers={"X-CSRFToken": token, "X-Lagniappe-Request": "true"},
        json={"view": {}, "targets": []},
    )
    assert refresh_response.status_code != 403

    sync_blocked = http_client.post(
        "/l/sync",
        headers={"X-CSRFToken": token, "X-Lagniappe-Request": "true"},
        json={"updates": []},
    )
    assert sync_blocked.status_code == 403
    assert sync_blocked.json == {
        "success": False,
        "error": "Demo accounts are read-only.",
    }

    # Even after _load_request_context falls back and re-seeds the session, the demo flag stays set.
    with http_client.session_transaction() as client_session:
        assert client_session.get(CONFIG.LOGIN_DEMO_GUEST_KEY) is True

    # Logout remains allowed, skips Datastore cache invalidation write, and clears demo session state.
    monkeypatch.setattr(
        login_routes,
        "_mark_logout_cache_invalidation",
        lambda: pytest.fail("Demo guest logout must not mutate the shared user entity"),
    )
    logged_out = http_client.post(
        "/users/logout",
        headers={"X-CSRFToken": token, "X-Lagniappe-Request": "true"},
    )
    assert logged_out.status_code == 200
    assert logged_out.json == {"success": True, "redirect": "/users/login"}

    with http_client.session_transaction() as client_session:
        assert client_session.get("_user_id") is None
        assert client_session.get(CONFIG.LOGIN_DEMO_GUEST_KEY) is None


def test_public_manual_sections_render_cleanly_including_all_mcp_clients(
    monkeypatch: pytest.MonkeyPatch,
    http_client,
):
    from lagniappe.core.definitions.manual import MANUAL_SECTIONS

    monkeypatch.setattr(CONFIG, "PUBLIC_MANUAL", True)
    for section in MANUAL_SECTIONS:
        response = http_client.get(f"/manual/section/{section['key']}")
        assert response.status_code == 200, f"Failed rendering manual section {section['key']}"
        html = response.get_data(as_text=True)
        if section["key"] == "ai":
            for role in (
                "external-ai-chatgpt-setup",
                "external-ai-codex-setup",
                "external-ai-claude-setup",
                "external-ai-antigravity-setup",
                "external-ai-pi-setup",
            ):
                assert f'data-role="{role}"' in html
            assert "My Page / User Settings / Manage AI connections" in html
            assert "developers.openai.com/plugins" not in html
        elif section["key"] == "under-the-hood":
            assert "cloud APIs, OAuth rules, cloud APIs" not in html
        elif section["key"] == "personalization":
            assert "<code>-update</code>" not in html
            assert "./setup.sh update" in html
        elif section["key"] == "installation":
            assert 'data-role="ai-assisted-install"' in html
            assert "./setup.sh --agent" in html
            assert "documentation/INSTALL_WITH_AI.md" in html
            assert "Assistant Playbook" in html


def test_public_directory_places_ordered_group_before_manual(
    monkeypatch: pytest.MonkeyPatch,
    http_client,
):
    from lagniappe.core.tools import cache

    snapshot = {
        "schema": 1,
        "site_indexing": True,
        "groups": [
            {
                "id": "public-pages",
                "name": "Public Pages",
                "pages": [
                    {
                        "path": "/pages/public/welcome",
                        "title": "Why Lagniappe?",
                        "description": "Overview and tour.",
                        "order": 1,
                    },
                    {
                        "path": "/pages/public/about",
                        "title": "About",
                        "description": None,
                    },
                ],
            },
            {
                "id": "category:z-cat",
                "name": "Zebra",
                "pages": [
                    {
                        "path": "/pages/public/zebra",
                        "title": "Zebra Notes",
                        "description": None,
                    }
                ],
            },
        ],
    }
    monkeypatch.setattr(CONFIG, "PUBLIC_MANUAL", True)
    monkeypatch.setattr(cache, "cached_public_directory", lambda _builder: snapshot)

    response = http_client.get("/public/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.index("Public Pages") < html.index("Manual") < html.index("Zebra")
    assert html.index("Why Lagniappe?") < html.index("About")


def test_readonly_page_and_project_templates_hide_empty_document_tab(
    monkeypatch: pytest.MonkeyPatch,
):
    from types import SimpleNamespace

    from flask import g, render_template

    from lagniappe.core.definitions import Action, Resource

    def _fake_entity(kind: str, *, can_edit: bool, has_document: bool):
        return SimpleNamespace(
            urlsafe_key=f"fake-{kind}-key",
            key=f"fake-{kind}-key",
            fingerprint="fp-1",
            hash="hash12345678",
            name=f"Sample {kind.title()}",
            description="",
            modified=SimpleNamespace(isoformat=lambda: "2026-11-24T00:00:00+00:00"),
            readonly=not can_edit,
            image=None,
            user=None,
            form=None,
            has_notes=False,
            properties=SimpleNamespace(filters=SimpleNamespace(preload=[])),
            categories=[],
            model=SimpleNamespace(name="Samples"),
            is_public=False,
            public_id=None,
            db={},
            sync_ids={
                "document": {
                    "id": "hash12345678:document",
                    "fingerprint": "doc-fp" if has_document else None,
                }
            },
            allowed=lambda action, **_kw: can_edit if action == Action.EDIT else False,
            get_asset=lambda name: {"path": "doc.html"} if (has_document and name == "document") else None,
        )

    fake_user = SimpleNamespace(
        page=SimpleNamespace(key="other-user-page"),
        is_public=False,
        is_owner=False,
        is_admin=False,
        is_authenticated=True,
        is_active=True,
        is_anonymous=False,
        hash="viewer-hash",
        authorization_fingerprint="auth-fp",
        properties=SimpleNamespace(
            starred=SimpleNamespace(keys=set()),
            restrictions=SimpleNamespace(user_assign_restrictions=False),
        ),
        access=lambda _tier: False,
    )
    monkeypatch.setattr(Resource, "allowed", lambda self, _action, **_kw: False)
    monkeypatch.setitem(app.jinja_env.globals, "owner_allows_assignments", lambda: False)
    monkeypatch.setitem(
        app.jinja_env.globals,
        "form_state",
        lambda *_a, **_k: SimpleNamespace(
            is_locked=False,
            review=None,
            active_job=None,
            failed_job=None,
            has_review=False,
            banner_state=None,
        ),
    )

    with app.test_request_context("/"):
        g._login_user = fake_user
        for template_name, var_name, kind in (
            ("pages/page.html", "page", "page"),
            ("projects/project.html", "project", "project"),
        ):
            empty_ro = render_template(
                template_name,
                **{
                    var_name: _fake_entity(kind, can_edit=False, has_document=False),
                    "focus_task": None,
                    "public_context": None,
                },
            )
            assert 'lp-show="document:active"' not in empty_ro
            assert 'data-widget="CollaborativeDocument"' not in empty_ro

            populated_ro = render_template(
                template_name,
                **{
                    var_name: _fake_entity(kind, can_edit=False, has_document=True),
                    "focus_task": None,
                    "public_context": None,
                },
            )
            assert 'lp-show="document:active"' in populated_ro
            assert 'data-widget="CollaborativeDocument"' in populated_ro

            empty_editable = render_template(
                template_name,
                **{
                    var_name: _fake_entity(kind, can_edit=True, has_document=False),
                    "focus_task": None,
                    "public_context": None,
                },
            )
            assert 'lp-show="document:active"' in empty_editable
            assert 'data-widget="CollaborativeDocument"' in empty_editable
