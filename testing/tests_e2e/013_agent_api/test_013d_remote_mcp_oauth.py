"""OAuth browser/HTTP wiring and the service-authenticated API envelope."""

import base64
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from config.remote_mcp import (
    PENDING_SECONDS,
    USER_TOKEN_HEADER,
    CLIENT_ID,
    REDIRECT_URI,
)
from lagniappe import CONFIG
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.auth import agent_api, remote_mcp as auth
from lagniappe.core.tools import cache as cache_store
from lagniappe.core.tools.cache import rate_limit as rate_limiter
from lagniappe.core.tools.database import analytics as analytics_database, get as database_get
from lagniappe.core.tools.email.notifications import presence
from lagniappe.core.tools.services import identity_platform
from lagniappe.web import app


pytestmark = pytest.mark.e2e
ISSUER = "https://lagniappe.test"
VERIFIER = "v" * 43
PENDING_COOKIE = "__Secure-lagniappe-mcp-pending"


class Actor:
    email = "pilot@example.com"
    name = "Pilot"
    hash = "abcdefghijkl"
    key = "oauth-pilot-user"
    urlsafe_key = "oauth-pilot-user"
    is_authenticated = True
    is_active = True
    is_public = False

    def __init__(self, db=None):
        self.db = db if db is not None else {"timezone": "UTC"}
        self.page = SimpleNamespace(urlsafe_key="pilot-personal-page")

    def get_id(self):
        return self.urlsafe_key


@pytest.fixture
def pilot(monkeypatch):
    monkeypatch.setattr(CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "APP_URL", ISSUER)
    monkeypatch.setattr(CONFIG, "CUSTOM_DOMAIN", "")
    monkeypatch.setattr(CONFIG, "MCP_RESOURCE", "https://pilot.run.app/mcp")
    monkeypatch.setattr(
        CONFIG, "MCP_SERVICE_ACCOUNT",
        "lagniappe-mcp@pilot-project.iam.gserviceaccount.com",
    )
    config = {**auth.settings(), "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI}
    monkeypatch.setattr(auth.Entities, "USER", Actor)
    actor, rows = Actor(), {}
    monkeypatch.setattr(
        auth.Entities,
        "fetch_one",
        lambda key, **kwargs: actor if key == actor.key else None,
    )
    monkeypatch.setattr(app.login_manager, "_user_callback", lambda _: actor)
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
        external_api,
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
    # Exercise the real route limiters with an isolated client, and remove only
    # this fixture's counters so other HTTP tests keep their own rate-limit state.
    address = uuid4().hex[:24]
    client_ip = "2001:db8:" + ":".join(
        address[offset:offset + 4] for offset in range(0, 24, 4)
    )
    client.environ_base["REMOTE_ADDR"] = client_ip
    limiter_keys = {
        scope: cache_store.Keys.RATE_LIMIT.value.format(
            scope, hashlib.sha256(identifier.encode()).hexdigest()[:16]
        )
        for scope, identifier in (
            ("remote-mcp-oauth", client_ip),
            ("remote-mcp-envelope", client_ip),
            ("agent-api-general", f"{actor.urlsafe_key}:{client_ip}"),
            ("google-signin", client_ip),
        )
    }
    try:
        yield SimpleNamespace(
            config=config, actor=actor, rows=rows, parameters=parameters,
            client=client, limiter_keys=limiter_keys,
        )
    finally:
        rate_limiter.cache.redis.delete(*limiter_keys.values())


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
    assert "scopes_supported" not in metadata.json
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


# @matrix error-handling : csrf
# @source lagniappe/web/start/errors.py::handle_http_error
@pytest.mark.parametrize("csrf_failure", ["changed-session", "missing-token"])
def test_oauth_csrf_failure_shows_connection_restart_guidance(pilot, csrf_failure):
    _login(pilot)
    form = _consent_page(pilot)
    before = deepcopy(pilot.rows)
    if csrf_failure == "changed-session":
        with pilot.client.session_transaction(base_url=ISSUER) as session:
            session["csrf_token"] = "another-signin-session"
    else:
        form.pop("csrf_token")

    rejected = _open(
        pilot, "POST", "/oauth/authorize", data={"decision": "allow", **form}
    )
    assert rejected.status_code == 400
    assert rejected.mimetype == "text/html"
    assert rejected.headers["X-Lagniappe-CSRF"] == "invalid"
    assert "no-store" in rejected.headers["Cache-Control"]
    assert "Location" not in rejected.headers
    assert 'role="alert"' in rejected.text
    assert "This connection request no longer matches your sign-in session." in rejected.text
    assert "Start again from your AI client" in rejected.text
    assert "Return to Lagniappe" in rejected.text
    assert 'name="decision"' not in rejected.text
    assert all(value not in rejected.text for value in form.values())
    assert pilot.parameters["state"] not in rejected.text
    assert pilot.rows == before

    # Starting over reaches a fresh consent form and a normal denial callback.
    fresh_form = _consent_page(pilot)
    denied = _open(
        pilot, "POST", "/oauth/authorize", data={"decision": "deny", **fresh_form}
    )
    assert denied.status_code == 303
    assert parse_qs(urlsplit(denied.location).query)["error"] == ["access_denied"]


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
    saved_users, login_events = [], []
    monkeypatch.setattr(CONFIG, "GOOGLE_SIGNIN_ENABLED", True)
    monkeypatch.setattr(CONFIG, "GOOGLE_LOGIN_URI", ISSUER + "/users/google-signin")
    monkeypatch.setattr(CONFIG, "ANALYTICS", True)
    monkeypatch.setattr(database_get, "user", lambda email: pilot.actor.db)
    monkeypatch.setattr(Actor, "save", lambda user: saved_users.append(user), raising=False)
    monkeypatch.setattr(analytics_database, "create_event", login_events.append)
    monkeypatch.setattr(presence, "record_site_activity", lambda *args: None)
    claims = {
        "email": pilot.actor.email,
        "email_verified": True,
        "sub": "google-pilot-user",
    }
    monkeypatch.setattr(
        identity_platform, "verify_google_credential", lambda *args: claims
    )
    monkeypatch.setattr(
        identity_platform,
        "exchange_google_credential",
        lambda *args: {"idToken": "provider-token"},
    )
    monkeypatch.setattr(
        identity_platform, "verify_identity_token", lambda *args: claims
    )

    started = _open(pilot, "GET", "/oauth/authorize", query_string=pilot.parameters)
    pending_header = next(
        value
        for value in started.headers.getlist("Set-Cookie")
        if value.startswith(PENDING_COOKIE + "=")
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
        PENDING_COOKIE, domain=domain, path="/oauth"
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
    assert len(saved_users) == 1 and saved_users[0].db is pilot.actor.db
    assert saved_users[0].last_login is not None
    assert len(login_events) == 1
    assert login_events[0]["user_key"] == pilot.actor.urlsafe_key
    assert login_events[0]["navigation_type"] == "identity-google"
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    with pilot.client.session_transaction(base_url=ISSUER) as session:
        assert session["_user_id"] == pilot.actor.get_id()
        assert "before_google_callback" not in session
    assert (
        pilot.client.get_cookie(
            PENDING_COOKIE, domain=domain, path="/oauth"
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
            PENDING_COOKIE, domain=domain, path="/oauth"
        )
        is None
    )


# @matrix mcp-oauth : token revocation csrf-exemption csrf browser-settings
# @matrix agent-api : bearer-only session-independent request-recheck
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
    key = pilot.limiter_keys["remote-mcp-envelope"]
    rate_limiter.cache.redis.set(key, 60, ex=17)
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
    assert 0 < int(result.headers["Retry-After"]) <= 17
    assert int(rate_limiter.cache.redis.get(key)) == 61
    assert rate_limiter.cache.redis.get(pilot.limiter_keys["agent-api-general"]) is None


# @matrix mcp-oauth : consent loopback csrf client-isolation
def test_codex_browser_consent_names_client_and_revokes_only_its_connection(pilot):
    from config.remote_mcp import CODEX_CLIENT_ID

    _login(pilot)
    # Establish ChatGPT first, then prove Codex does not replace it.
    form = _consent_page(pilot)
    allowed = _open(
        pilot, "POST", "/oauth/authorize", data={**form, "decision": "allow"}
    )
    chatgpt_code = parse_qs(urlsplit(allowed.location).query)["code"][0]
    chatgpt = _open(
        pilot,
        "POST",
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": pilot.config["client_id"],
            "resource": pilot.config["resource"],
            "redirect_uri": pilot.config["redirect_uri"],
            "code": chatgpt_code,
            "code_verifier": VERIFIER,
        },
    )
    assert chatgpt.status_code == 200
    pilot.parameters.update(
        client_id=CODEX_CLIENT_ID, redirect_uri="http://127.0.0.1:54321/callback"
    )
    form = _consent_page(pilot)
    page = _open(pilot, "GET", "/oauth/authorize")
    assert "Connect Codex to Lagniappe" in page.text
    allowed = _open(
        pilot, "POST", "/oauth/authorize", data={**form, "decision": "allow"}
    )
    target = urlsplit(allowed.location)
    assert target.scheme == "http" and target.netloc == "127.0.0.1:54321"
    assert target.path == "/callback"
    returned = parse_qs(target.query)
    assert returned["iss"] == [ISSUER]
    codex = _open(
        pilot,
        "POST",
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CODEX_CLIENT_ID,
            "resource": pilot.config["resource"],
            "redirect_uri": pilot.parameters["redirect_uri"],
            "code": returned["code"][0],
            "code_verifier": VERIFIER,
        },
    )
    assert codex.status_code == 200
    page = _open(pilot, "GET", "/oauth/connection")
    assert "Revoke ChatGPT access" in page.text and "Revoke Codex access" in page.text
    revoked = _open(
        pilot,
        "POST",
        "/oauth/connection",
        data={
            "csrf_token": form["csrf_token"],
            "client_id": CODEX_CLIENT_ID,
        },
    )
    assert revoked.status_code == 200
    assert (
        "Revoke ChatGPT access" in revoked.text
        and "Codex is not connected" in revoked.text
    )
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(codex.json["access_token"])
    assert auth.authenticate_access(chatgpt.json["access_token"])[0] is pilot.actor


@pytest.fixture
def codex_loopback():
    callbacks = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            target = urlsplit(self.path)
            if target.path != "/callback":
                self.send_error(404)
                return
            callbacks.append(parse_qs(target.query))
            body = b"Codex callback received"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/callback", callbacks
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


# @matrix mcp-oauth : consent loopback browser-callback submit-progress
# @matrix web-headers : security
@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_codex_native_consent_reaches_loopback_and_shows_submit_progress(
    pilot, browser, codex_loopback, decision
):
    from playwright.sync_api import expect
    from config.remote_mcp import CODEX_CLIENT_ID

    callback_url, callbacks = codex_loopback
    pilot.parameters.update(client_id=CODEX_CLIENT_ID, redirect_uri=callback_url)
    _login(pilot)
    _consent_page(pilot)
    decisions, progress, browser_errors = [], [], []
    before = deepcopy(pilot.rows)
    with browser.new_context(service_workers="block") as context:
        page = context.new_page()
        page.on(
            "console",
            lambda message: (
                browser_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.on("requestfailed", lambda request: browser_errors.append(request.failure))
        page.expose_function(
            "recordConsentProgress", lambda value: progress.append(value)
        )

        def serve_application(route):
            request = route.request
            parsed = urlsplit(request.url)
            if request.method == "POST" and parsed.path == "/oauth/authorize":
                decisions.append(parse_qs(request.post_data)["decision"])
            kwargs = {}
            if request.post_data is not None:
                kwargs.update(
                    data=request.post_data,
                    content_type=request.headers.get("content-type"),
                )
            response = _open(
                pilot,
                request.method,
                parsed.path + ("?" + parsed.query if parsed.query else ""),
                **kwargs,
            )
            try:
                route.fulfill(
                    status=response.status_code,
                    headers=dict(response.headers),
                    body=response.data,
                )
            finally:
                response.close()

        context.route(ISSUER + "/**", serve_application)
        page.goto(ISSUER + "/oauth/authorize")
        # The extra observer runs after the product's submit handler and
        # records visible DOM state before the native navigation replaces it.
        page.evaluate("""() => document.addEventListener('submit', () => {
            const button = document.querySelector('button[aria-busy="true"]');
            const icon = button.querySelector('[data-role="icon"]');
            window.recordConsentProgress({busy: button.getAttribute('aria-busy'),
                visible: icon.getBoundingClientRect().width > 0,
                icon: icon.textContent});
        })""")
        page.get_by_role(
            "button", name="Allow" if decision == "allow" else "Cancel", exact=True
        ).click()
        expect(page, str(browser_errors)).to_have_url(
            re.compile("^" + re.escape(callback_url) + r"\?")
        )
        expect(page.locator("body")).to_have_text("Codex callback received")
        assert decisions == [[decision]]
        assert len(progress) == 1 and progress[0]["busy"] == "true"
        assert progress[0]["visible"] and progress[0]["icon"]
        assert len(callbacks) == 1 and callbacks[0]["iss"] == [ISSUER]
        assert callbacks[0]["state"] == [pilot.parameters["state"]]
        if decision == "allow":
            assert len(callbacks[0]["code"]) == 1
        else:
            assert callbacks[0]["error"] == ["access_denied"]
            assert "code" not in callbacks[0]
            assert pilot.rows.keys() == before.keys()


# @matrix mcp-oauth : site-policy discovery
# @matrix agent-api : site-policy bearer-only
# @source lagniappe/web/routes/oauth/main.py::metadata
# @source lagniappe/web/routes/api/main.py::authenticate_request
@pytest.mark.parametrize("flag", ["AI_ENABLED", "EXTERNAL_AI_ENABLED"])
def test_site_policy_closes_oauth_discovery_and_external_routes(pilot, monkeypatch, flag):
    monkeypatch.setattr(CONFIG, flag, False)
    assert _open(pilot, "GET", "/.well-known/oauth-authorization-server").status_code == 404
    assert _open(pilot, "GET", "/oauth/connection").status_code == 404
    for path in ("/api/v1/", "/api/v1/client-skill.md", "/api/v1/actor"):
        response = _open(pilot, "GET", path, headers={"Authorization": "Bearer previously-issued"})
        assert response.status_code == 403
        assert response.json["error"]["code"] == "external_ai_disabled"


# @matrix manual : site-policy address-redaction anonymous-access ajax-section
# @source lagniappe/web/responses.py::manual_content
def test_external_ai_manual_shows_connection_details_only_to_eligible_readers(pilot, monkeypatch):
    pilot.actor.access = lambda _: False
    monkeypatch.setattr(CONFIG, "MCP_NAME", "cwright-mcp")
    monkeypatch.setattr(CONFIG, "CUSTOM_DOMAIN", "workspace.example.test")
    monkeypatch.setattr(CONFIG, "PUBLIC_MANUAL", True)
    _login(pilot)
    response = _open(pilot, "GET", "/manual/section/ai")
    assert response.status_code == 200
    text = response.text
    assert 'data-role="external-ai-account-details"' in text
    assert "https://pilot.run.app/mcp" in text
    assert "https://workspace.example.test/api/v1/client-skill.md" in text
    assert (
        "codex mcp add cwright-mcp --url https://pilot.run.app/mcp "
        "--oauth-client-id lagniappe-codex"
    ) in text
    assert "codex mcp login cwright-mcp" in text
    assert 'data-role="external-ai-chatgpt-setup"' in text
    assert "Restart any existing Codex sessions" in text
    assert "MCP-ENDPOINT" not in text
    assert re.search(r'<details\s+data-role="external-ai-help">', text)
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    # Another installation must render its own configured URL in the command.
    monkeypatch.setattr(CONFIG, "MCP_RESOURCE", "https://another-installation.run.app/mcp")
    monkeypatch.setattr(CONFIG, "MCP_NAME", "another-mcp")
    another = _open(pilot, "GET", "/manual/section/ai").text
    assert "codex mcp add another-mcp --url https://another-installation.run.app/mcp " in another
    assert "codex mcp login another-mcp" in another
    assert "cwright-mcp" not in another
    assert "https://pilot.run.app/mcp" not in another
    monkeypatch.setattr(CONFIG, "MCP_RESOURCE", None)
    disabled = _open(pilot, "GET", "/manual/section/ai").text
    assert 'data-role="external-ai-codex-setup"' not in disabled
    assert 'data-role="external-ai-chatgpt-setup"' not in disabled
    for anonymous in (False, True):
        pilot.actor.is_public = True
        if anonymous:
            with pilot.client.session_transaction(base_url=ISSUER) as session:
                session.clear()
        response = _open(pilot, "GET", "/manual/section/ai")
        assert response.status_code == 200
        assert 'data-role="external-ai-account-details"' not in response.text
        assert 'data-role="external-ai-generic-details"' in response.text
        assert "https://pilot.run.app/mcp" not in response.text
        assert "https://another-installation.run.app/mcp" not in response.text
        assert "https://workspace.example.test" not in response.text
        assert "another-mcp" not in response.text
        assert "/api/v1/client-skill.md" in response.text
        assert (
            "codex mcp add lagniappe-remote --url https://MCP-ENDPOINT/mcp "
            "--oauth-client-id lagniappe-codex"
        ) in response.text
    pilot.actor.is_public = False
    _login(pilot)
    monkeypatch.setattr(CONFIG, "EXTERNAL_AI_ENABLED", False)
    response = _open(pilot, "GET", "/manual/section/ai")
    assert response.status_code == 200
    assert 'data-role="external-ai-account-details"' not in response.text


# @matrix mcp-oauth : consent user-binding
# @source lagniappe/web/routes/oauth/main.py::authorize
# @source lagniappe/core/tools/auth/remote_mcp.py::eligible_user
@pytest.mark.parametrize("client", ["chatgpt", "codex"])
def test_public_user_cannot_authorize_with_valid_client_setup(pilot, client):
    from config.remote_mcp import CODEX_CLIENT_ID

    # A supported client does not make a public user eligible. Keep a valid
    # pre-existing form to test POST as well.
    if client == "codex":
        pilot.parameters.update(
            client_id=CODEX_CLIENT_ID, redirect_uri="http://127.0.0.1:38417/callback"
        )
    _login(pilot)
    form = _consent_page(pilot)
    pilot.actor.is_public = True
    rejected = _open(pilot, "GET", "/oauth/authorize")
    assert rejected.status_code == 403
    assert 'name="decision"' not in rejected.text
    rejected = _open(
        pilot, "POST", "/oauth/authorize", data={"decision": "allow", **form}
    )
    assert rejected.status_code == 403
    assert not any(name.startswith(("c-", "a-", "r-", "grant-")) for name in pilot.rows)


# @matrix ai-access : site-policy
# @source lagniappe/core/entities/user.py::User.access
# @template pages/photo.html::image
# @template home/site_settings.html::site_settings
# @template home/categories.html::create
# @template home/projects.html::create
def test_disabled_ai_removes_provider_controls_from_rendered_views(monkeypatch):
    from flask import render_template_string
    from flask_login import login_user
    from lagniappe.core.definitions import Resource
    from types import MethodType
    from lagniappe.core.entities.user import User

    actor = Actor()
    actor.ai_access = "CREATE"
    actor.is_owner = False
    actor.is_admin = True
    actor.access = MethodType(User.access, actor)
    monkeypatch.setattr(Resource, "allowed", lambda *args, **kwargs: False)
    template = '''
      {% from 'pages/photo.html' import image %}
      {% from 'home/site_settings.html' import site_settings %}
      {% from 'home/categories.html' import create as create_category %}
      {% from 'home/projects.html' import create as create_project %}
      {{ image(page) }}{{ site_settings() }}{{ create_category() }}{{ create_project() }}
    '''
    with app.test_request_context("/"):
        login_user(actor)
        enabled = render_template_string(template, page=SimpleNamespace(image=None))
        assert 'data-ai-create="true"' in enabled
        assert 'data-role="ai-settings"' in enabled
        assert 'data-role="generate"' in enabled
        monkeypatch.setattr(CONFIG, "AI_ENABLED", False)
        disabled = render_template_string(template, page=SimpleNamespace(image=None))
        assert 'data-ai-create="false"' in disabled
        assert 'data-role="ai-settings"' not in disabled
        assert 'data-role="generate"' not in disabled
        assert 'data-widget="CreateCategory"' in disabled
        assert 'data-widget="CreateProject"' in disabled
        assert "drop image here" in disabled
