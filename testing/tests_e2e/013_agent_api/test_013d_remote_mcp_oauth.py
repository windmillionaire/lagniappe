"""OAuth browser/HTTP wiring and the service-authenticated API envelope."""

import base64
from copy import deepcopy
import hashlib
import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from config.remote_mcp import (
    PENDING_SECONDS,
    USER_TOKEN_HEADER,
    normalize_remote_mcp_config,
)
from lagniappe import CONFIG
from lagniappe.core.tools.auth import agent_api, remote_mcp as auth
from lagniappe.web import app
from lagniappe.web.routes.api import main as api_routes
from lagniappe.web.routes.oauth import main as oauth_routes


pytestmark = pytest.mark.e2e
ISSUER = "https://lagniappe.test"
VERIFIER = "v" * 43


class Actor:
    email = "pilot@example.com"
    name = "Pilot"
    hash = "abcdefghijkl"
    key = "oauth-pilot-user"
    urlsafe_key = "oauth-pilot-user"
    is_authenticated = True
    is_active = True
    is_public = False
    db = {"timezone": "UTC"}

    def get_id(self):
        return self.urlsafe_key


@pytest.fixture
def pilot(monkeypatch):
    config = normalize_remote_mcp_config(
        {
            "enabled": True,
            "issuer": ISSUER,
            "resource": "https://pilot.run.app/mcp",
            "actors": [Actor.email],
            "service_account": "lagniappe-mcp@pilot-project.iam.gserviceaccount.com",
        }
    )
    monkeypatch.setattr(CONFIG, "REMOTE_MCP", config)
    monkeypatch.setattr(auth.Entities, "USER", Actor)
    actor, rows = Actor(), {}
    monkeypatch.setattr(
        auth.Entities,
        "fetch_one",
        lambda key, **kwargs: actor if key == actor.key else None,
    )
    monkeypatch.setattr(app.login_manager, "_user_callback", lambda _: actor)
    monkeypatch.setattr(oauth_routes, "check_limit", lambda *args: {"allowed": True})
    monkeypatch.setattr(api_routes, "_rate_limit", lambda *args: None)
    monkeypatch.setattr(auth, "client_metadata", lambda client_id: {})

    def atomic(operation):
        staged = deepcopy(rows)
        result = operation(
            SimpleNamespace(
                get=lambda key: deepcopy(staged.get(key)),
                put=lambda key, value: staged.__setitem__(key, deepcopy(dict(value))),
            )
        )
        rows.clear()
        rows.update(staged)
        return result

    monkeypatch.setattr(auth.store, "atomic", atomic)
    monkeypatch.setattr(auth.store, "read", lambda key: deepcopy(rows.get(key)))
    monkeypatch.setattr(
        api_routes.external_api,
        "personal_page_reference",
        lambda _: {
            "kind": "page",
            "hash": "hash:abcdefghijkl",
            "name": "Personal",
            "url": "/pages/personal",
            "can_view": True,
            "can_edit": True,
        },
    )
    parameters = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "resource": config["resource"],
        "scope": "mcp:use",
        "response_type": "code",
        "state": "state-not-in-login-url",
        "code_challenge_method": "S256",
        "code_challenge": base64.urlsafe_b64encode(
            hashlib.sha256(VERIFIER.encode()).digest()
        )
        .decode()
        .rstrip("="),
    }
    client = app.test_client()
    return SimpleNamespace(
        config=config, actor=actor, rows=rows, parameters=parameters, client=client
    )


def _login(pilot):
    with pilot.client.session_transaction(base_url=ISSUER) as session:
        session["_user_id"] = pilot.actor.get_id()
        session["_fresh"] = True


def _open(pilot, method, path, **kwargs):
    if method == "POST" and path in {"/oauth/authorize", "/oauth/connection"}:
        kwargs["headers"] = {"Referer": ISSUER + path, **kwargs.get("headers", {})}
    return pilot.client.open(path, method=method, base_url=ISSUER, **kwargs)


def _consent_page(pilot):
    result = _open(pilot, "GET", "/oauth/authorize", query_string=pilot.parameters)
    assert result.status_code == 303 and result.location == "/oauth/authorize"
    page = _open(pilot, "GET", "/oauth/authorize")
    return _consent_fields(page)


def _consent_fields(page):
    return {
        name: re.search(r'name="' + name + r'" value="([^"]+)"', page.text).group(1)
        for name in ("csrf_token", "pending", "user_id")
    }


# @matrix mcp-oauth : discovery consent csrf login redirect
def test_oauth_metadata_login_consent_and_csrf(pilot):
    metadata = _open(pilot, "GET", "/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    assert metadata.json["issuer"] == ISSUER
    assert metadata.json["token_endpoint_auth_methods_supported"] == ["none"]
    assert metadata.json["authorization_response_iss_parameter_supported"] is True
    assert "registration_endpoint" not in metadata.json
    started = _open(pilot, "GET", "/oauth/authorize", query_string=pilot.parameters)
    assert started.status_code == 303
    login = _open(pilot, "GET", started.location)
    assert login.status_code == 302 and login.location.startswith("/users/login")
    assert "state-not-in-login-url" not in login.location
    with pilot.client.session_transaction(base_url=ISSUER) as session:
        assert "code_challenge" not in json.dumps(dict(session))
        assert "state-not-in-login-url" not in json.dumps(dict(session))
    _login(pilot)
    page = _open(pilot, "GET", "/oauth/authorize")
    assert page.status_code == 200 and "Allow" in page.text and Actor.email in page.text
    assert page.headers["Referrer-Policy"] == "same-origin"
    form = _consent_fields(page)
    assert (
        _open(pilot, "POST", "/oauth/authorize", data={"decision": "allow"}).status_code
        == 400
    )
    denied = _open(pilot, "POST", "/oauth/authorize", data={"decision": "deny", **form})
    assert denied.status_code == 303
    assert parse_qs(urlsplit(denied.location).query) == {
        "error": ["access_denied"],
        "state": ["state-not-in-login-url"],
        "iss": [ISSUER],
    }
    forged = {**pilot.parameters, "redirect_uri": "https://attacker.test/callback"}
    assert (
        _open(pilot, "GET", "/oauth/authorize", query_string=forged).status_code == 400
    )
    duplicate = list(pilot.parameters.items()) + [("resource", "https://attacker.test")]
    assert (
        _open(pilot, "GET", "/oauth/authorize", query_string=duplicate).status_code
        == 400
    )


# @matrix mcp-oauth : consent consent-binding
def test_oauth_consent_rejects_replaced_request_and_changed_account(pilot, monkeypatch):
    _login(pilot)
    original_form = _consent_page(pilot)
    invalid = {**pilot.parameters, "resource": "https://wrong.test/mcp"}
    assert (
        _open(pilot, "GET", "/oauth/authorize", query_string=invalid).status_code == 400
    )
    assert (
        _consent_fields(_open(pilot, "GET", "/oauth/authorize"))["pending"]
        == original_form["pending"]
    )
    replacement = {**pilot.parameters, "state": "replacement-state"}
    assert (
        _open(pilot, "GET", "/oauth/authorize", query_string=replacement).status_code
        == 303
    )
    rejected = _open(
        pilot, "POST", "/oauth/authorize", data={"decision": "allow", **original_form}
    )
    assert rejected.status_code == 400
    assert not any(name.startswith("c-") for name in pilot.rows)

    replacement_form = _consent_fields(_open(pilot, "GET", "/oauth/authorize"))
    second = Actor()
    second.email, second.key, second.urlsafe_key = (
        "second@example.com",
        "second-user",
        "second-user",
    )
    pilot.config["actors"] = (pilot.actor.email, second.email)
    monkeypatch.setattr(app.login_manager, "_user_callback", lambda _: second)
    with pilot.client.session_transaction(base_url=ISSUER) as session:
        session["_user_id"] = second.get_id()
    rejected = _open(
        pilot,
        "POST",
        "/oauth/authorize",
        data={"decision": "allow", **replacement_form},
    )
    assert rejected.status_code == 400
    assert not any(name.startswith("c-") for name in pilot.rows)

    current_page = _open(pilot, "GET", "/oauth/authorize")
    assert second.email in current_page.text
    current_form = _consent_fields(current_page)
    granted = _open(
        pilot, "POST", "/oauth/authorize", data={"decision": "allow", **current_form}
    )
    assert granted.status_code == 303
    assert parse_qs(urlsplit(granted.location).query)["state"] == ["replacement-state"]
    code_rows = [row for name, row in pilot.rows.items() if name.startswith("c-")]
    assert len(code_rows) == 1 and code_rows[0]["user"] == second.key


# @matrix mcp-oauth : login login-continuation consent redirect
# Flask-Login's remember-cookie implementation still uses utcnow on Python 3.14.
# Keep this dependency warning scoped to the real callback that exercises it.
@pytest.mark.filterwarnings(
    r"ignore:datetime\.datetime\.utcnow\(\) is deprecated.*:DeprecationWarning:flask_login\.login_manager"
)
def test_oauth_pending_survives_google_callback_session_replacement(pilot, monkeypatch):
    from lagniappe.web.routes.users import login as login_routes
    from lagniappe.core.tools.email.notifications import presence

    monkeypatch.setattr(CONFIG, "GOOGLE_SIGNIN_ENABLED", True)
    monkeypatch.setattr(CONFIG, "GOOGLE_LOGIN_URI", ISSUER + "/users/google-signin")
    monkeypatch.setattr(
        login_routes, "_enforce_auth_rate_limit", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(login_routes.database_get, "user", lambda email: pilot.actor.db)
    monkeypatch.setattr(
        login_routes, "verify_user", lambda *args, **kwargs: pilot.actor
    )
    monkeypatch.setattr(login_routes, "record_login", lambda *args: None)
    monkeypatch.setattr(presence, "record_site_activity", lambda *args: None)
    claims = {
        "email": pilot.actor.email,
        "email_verified": True,
        "sub": "google-pilot-user",
    }
    monkeypatch.setattr(
        login_routes.identity_platform, "verify_google_credential", lambda *args: claims
    )
    monkeypatch.setattr(
        login_routes.identity_platform,
        "exchange_google_credential",
        lambda *args: {"idToken": "provider-token"},
    )
    monkeypatch.setattr(
        login_routes.identity_platform, "verify_identity_token", lambda *args: claims
    )
    pilot.actor.page = SimpleNamespace(urlsafe_key="pilot-personal-page")

    started = _open(pilot, "GET", "/oauth/authorize", query_string=pilot.parameters)
    pending_header = next(
        value
        for value in started.headers.getlist("Set-Cookie")
        if value.startswith(oauth_routes._PENDING_COOKIE + "=")
    )
    for attribute in (
        "Secure",
        "HttpOnly",
        "SameSite=Lax",
        "Path=/oauth",
        f"Max-Age={PENDING_SECONDS}",
    ):
        assert attribute in pending_header
    assert (
        "state-not-in-login-url" not in pending_header
        and "code_challenge" not in pending_header
    )
    login = _open(pilot, "GET", "/oauth/authorize")
    assert login.status_code == 302 and login.location.startswith("/users/login")

    with pilot.client.session_transaction(base_url=ISSUER) as session:
        session["before_google_callback"] = True
    domain = urlsplit(ISSUER).hostname
    pending_cookie = pilot.client.get_cookie(
        oauth_routes._PENDING_COOKIE, domain=domain, path="/oauth"
    )
    assert pending_cookie is not None
    # Werkzeug does not enforce SameSite, so model the real cross-site POST by
    # omitting the main Lax session cookie. The path-scoped pending cookie stays
    # in the browser jar and is not sent to /users/google-signin either.
    pilot.client.delete_cookie(app.config["SESSION_COOKIE_NAME"], domain=domain)
    pilot.client.set_cookie("g_csrf_token", "google-csrf", domain=domain)
    callback = _open(
        pilot,
        "POST",
        "/users/google-signin",
        data={
            "credential": "google-credential",
            "g_csrf_token": "google-csrf",
            "state": "/oauth/authorize",
        },
        headers={"Origin": "https://accounts.google.com"},
    )
    assert callback.status_code == 302 and callback.location == "/oauth/authorize"
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    with pilot.client.session_transaction(base_url=ISSUER) as session:
        assert session["_user_id"] == pilot.actor.get_id()
        assert "before_google_callback" not in session
    assert (
        pilot.client.get_cookie(
            oauth_routes._PENDING_COOKIE, domain=domain, path="/oauth"
        ).value
        == pending_cookie.value
    )
    page = _open(pilot, "GET", callback.location)
    assert page.status_code == 200 and pilot.actor.email in page.text
    form = _consent_fields(page)
    assert form["pending"] == pending_cookie.value
    allowed = _open(
        pilot, "POST", "/oauth/authorize", data={"decision": "allow", **form}
    )
    assert allowed.status_code == 303
    assert parse_qs(urlsplit(allowed.location).query)["state"] == [
        pilot.parameters["state"]
    ]
    assert (
        pilot.client.get_cookie(
            oauth_routes._PENDING_COOKIE, domain=domain, path="/oauth"
        )
        is None
    )


# @matrix mcp-oauth : token revocation csrf-exemption csrf browser-settings
# @matrix agent-api : bearer-only session-independent request-recheck
# @source lagniappe/web/routes/api/main.py::authenticate_request
def test_oauth_token_api_envelope_and_browser_revocation(pilot, monkeypatch):
    _login(pilot)
    form = _consent_page(pilot)
    csrf = form["csrf_token"]
    allowed = _open(
        pilot, "POST", "/oauth/authorize", data={"decision": "allow", **form}
    )
    assert allowed.status_code == 303
    code = parse_qs(urlsplit(allowed.location).query)["code"][0]
    parameters = {
        "grant_type": "authorization_code",
        "client_id": pilot.config["client_id"],
        "resource": pilot.config["resource"],
        "redirect_uri": pilot.config["redirect_uri"],
        "code": code,
        "code_verifier": VERIFIER,
    }
    token = _open(pilot, "POST", "/oauth/token", data=parameters)
    assert token.status_code == 200, token.text
    assert token.headers["Cache-Control"] == "no-store"
    assert token.headers["Pragma"] == "no-cache"
    access = token.json["access_token"]
    assert _open(pilot, "POST", "/oauth/token", data=parameters).status_code == 400
    assert (
        _open(
            pilot, "GET", "/api/v1/me", headers={"Authorization": "Bearer " + access}
        ).status_code
        == 401
    )
    assert (
        _open(
            pilot, "GET", "/api/v1/me", headers={USER_TOKEN_HEADER: access}
        ).status_code
        == 401
    )
    claims = {
        "iss": "https://accounts.google.com",
        "aud": ISSUER + "/api/v1",
        "email": pilot.config["service_account"],
        "email_verified": True,
        "sub": "123456789",
    }
    monkeypatch.setattr(
        auth.id_token, "verify_oauth2_token", lambda *args, **kwargs: claims
    )
    headers = {"Authorization": "Bearer workload-proof", USER_TOKEN_HEADER: access}
    result = _open(pilot, "GET", "/api/v1/me", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json["user"]["name"] == "Pilot"
    assert set(result.json["credential"]) == {
        "active",
        "display_prefix",
        "issued_at",
        "expires_at",
        "generation",
    }
    page = _open(pilot, "GET", "/oauth/connection")
    assert "Revoke ChatGPT access" in page.text
    assert _open(pilot, "POST", "/oauth/connection").status_code == 400
    result = _open(pilot, "POST", "/oauth/connection", data={"csrf_token": csrf})
    assert result.status_code == 200 and "not connected" in result.text
    assert _open(pilot, "GET", "/api/v1/me", headers=headers).status_code == 401
    assert (
        _open(
            pilot,
            "POST",
            "/oauth/revoke",
            data={"client_id": pilot.config["client_id"], "token": "unknown"},
        ).status_code
        == 200
    )
    assert (
        _open(
            pilot,
            "POST",
            "/oauth/revoke",
            data={"client_id": pilot.config["client_id"], "token": access},
        ).status_code
        == 200
    )

    # Existing API-key clients still use their own independent authentication.
    monkeypatch.setattr(
        agent_api,
        "authenticate_credential",
        lambda token: (pilot.actor, {"active": True}),
    )
    assert (
        _open(
            pilot, "GET", "/api/v1/me", headers={"Authorization": "Bearer lgn_existing"}
        ).status_code
        == 200
    )


# @matrix agent-api : rate-limit bearer-only
# @source lagniappe/web/routes/api/main.py::authenticate_request
def test_remote_mcp_rate_limit_precedes_workload_verification(pilot, monkeypatch):
    calls = []

    def limited(scope, identifier, limit, seconds):
        calls.append((scope, identifier, limit, seconds))
        raise api_routes.APIProblem(
            "rate_limited", "Too many API requests.", 429, retry_after=17
        )

    monkeypatch.setattr(api_routes, "_rate_limit", limited)
    monkeypatch.setattr(
        auth,
        "authenticate_envelope",
        lambda *args: pytest.fail(
            "Rate-limited requests must not verify workload tokens"
        ),
    )
    result = _open(
        pilot,
        "GET",
        "/api/v1/me",
        headers={
            "Authorization": "Bearer forged-workload",
            USER_TOKEN_HEADER: "lgmo_a_" + "x" * 43,
        },
    )
    assert result.status_code == 429 and result.json["error"]["code"] == "rate_limited"
    assert result.headers["Retry-After"] == "17"
    assert len(calls) == 1 and calls[0][0] == "remote-mcp-envelope"
    assert calls[0][2:] == api_routes.GENERAL_RATE_LIMIT
