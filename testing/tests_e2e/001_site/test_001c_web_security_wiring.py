"""Direct contracts for web startup, CSRF, authentication, and headers."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask, session

from lagniappe import CONFIG
from lagniappe.core.entities import Entities
from lagniappe.web import CSP, app, configure_flask_security
from lagniappe.web.routes.api import main as api_routes
from lagniappe.web.routes.users import login as user_login_routes
from lagniappe.web.start import blueprints as blueprint_start
from lagniappe.web.start import login as login_start


pytestmark = pytest.mark.e2e


class Sentinel:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Sentinel({self.name!r})"


class RecorderApp:
    def __init__(self, bindings, *, expose_google_endpoint=True):
        self.bindings = bindings
        self.expose_google_endpoint = expose_google_endpoint
        self.registrations = []
        self.view_functions = {}

    def register_blueprint(self, blueprint, **options):
        self.registrations.append((blueprint, options.get("url_prefix")))
        if blueprint is self.bindings["users"] and self.expose_google_endpoint:
            self.view_functions["users.login_google"] = self.bindings[
                "users.login_google"
            ]


class RecorderCSRF:
    def __init__(self):
        self.exemptions = []

    def exempt(self, target):
        self.exemptions.append(target)
        return target


def _wiring_recorders(*, expose_google_endpoint=True):
    bindings = {
        registration.binding: Sentinel(registration.binding)
        for registration in blueprint_start.BLUEPRINT_REGISTRATIONS
    }
    bindings["users.login_google"] = Sentinel("users.login_google")
    app_recorder = RecorderApp(
        bindings,
        expose_google_endpoint=expose_google_endpoint,
    )
    return app_recorder, RecorderCSRF(), bindings


def _open_request(
    method,
    path,
    *,
    headers=None,
    json=None,
    data=None,
    cookies=(),
    session_values=None,
):
    client = app.test_client()
    for name, value in cookies:
        client.set_cookie(name, value)
    if session_values:
        with client.session_transaction() as client_session:
            client_session.update(session_values)
    return client.open(
        path,
        method=method,
        headers=headers,
        json=json,
        data=data,
    )


# @matrix csrf web-startup : blueprint-registration exemption-policy
@pytest.mark.parametrize(
    ("analytics", "ai_observability", "analytics_enabled"),
    (
        (False, False, False),
        (True, False, True),
        (False, True, True),
    ),
)
def test_blueprint_registration_and_csrf_exemption_policy(
    analytics,
    ai_observability,
    analytics_enabled,
):
    app_recorder, csrf_recorder, bindings = _wiring_recorders()
    runtime_config = SimpleNamespace(
        ANALYTICS=analytics,
        AI_OBSERVABILITY=ai_observability,
    )

    blueprint_start.initialize(
        app_recorder,
        csrf_recorder,
        binding_factory=lambda config: bindings,
        runtime_config=runtime_config,
    )

    expected_registrations = [
        (bindings[registration.binding], registration.url_prefix)
        for registration in blueprint_start.BLUEPRINT_REGISTRATIONS
        if registration.binding != "analytics" or analytics_enabled
    ]
    assert app_recorder.registrations == expected_registrations
    assert len({target for target, _prefix in app_recorder.registrations}) == len(
        app_recorder.registrations
    )

    assert [
        (exemption.target_kind, exemption.target, exemption.rationale)
        for exemption in blueprint_start.CSRF_EXEMPTIONS
    ] == [
        (
            "blueprint",
            "process",
            "Google OIDC service-account validation",
        ),
        (
            "blueprint",
            "testing",
            "Hosted-E2E OIDC and run-bound session gate",
        ),
        ("blueprint", "webhooks", "Provider signature verification"),
        (
            "blueprint",
            "api_family",
            "Bearer-only external API authentication",
        ),
        (
            "blueprint",
            "api",
            "Bearer-only external API authentication",
        ),
        (
            "view",
            "users.login_google",
            "Google double-submit cookie/body token",
        ),
    ]
    assert csrf_recorder.exemptions == [
        bindings[exemption.target] for exemption in blueprint_start.CSRF_EXEMPTIONS
    ]
    assert bindings["users"] not in csrf_recorder.exemptions
    assert bindings["analytics"] not in csrf_recorder.exemptions


# @matrix csrf web-startup : exemption-policy validation
def test_blueprint_policy_rejects_invalid_bindings_and_exemptions():
    runtime_config = SimpleNamespace(ANALYTICS=False, AI_OBSERVABILITY=False)

    app_recorder, csrf_recorder, bindings = _wiring_recorders()
    del bindings["home"]
    with pytest.raises(RuntimeError, match="Missing blueprint binding: home"):
        blueprint_start.apply_blueprint_policy(
            app_recorder,
            csrf_recorder,
            bindings,
            runtime_config,
        )

    app_recorder, csrf_recorder, bindings = _wiring_recorders()
    duplicate_registration = (
        *blueprint_start.BLUEPRINT_REGISTRATIONS,
        blueprint_start.BLUEPRINT_REGISTRATIONS[0],
    )
    with pytest.raises(ValueError, match="Duplicate blueprint registration target"):
        blueprint_start.apply_blueprint_policy(
            app_recorder,
            csrf_recorder,
            bindings,
            runtime_config,
            registrations=duplicate_registration,
        )

    duplicate_exemption = (
        *blueprint_start.CSRF_EXEMPTIONS,
        blueprint_start.CSRF_EXEMPTIONS[0],
    )
    with pytest.raises(ValueError, match="Duplicate CSRF exemption target"):
        blueprint_start.apply_blueprint_policy(
            app_recorder,
            csrf_recorder,
            bindings,
            runtime_config,
            exemptions=duplicate_exemption,
        )

    missing_rationale = (
        replace(blueprint_start.CSRF_EXEMPTIONS[0], rationale=" "),
        *blueprint_start.CSRF_EXEMPTIONS[1:],
    )
    with pytest.raises(ValueError, match="CSRF exemption requires a rationale"):
        blueprint_start.apply_blueprint_policy(
            app_recorder,
            csrf_recorder,
            bindings,
            runtime_config,
            exemptions=missing_rationale,
        )

    app_recorder, csrf_recorder, bindings = _wiring_recorders(
        expose_google_endpoint=False
    )
    with pytest.raises(RuntimeError, match="view endpoint is unavailable"):
        blueprint_start.apply_blueprint_policy(
            app_recorder,
            csrf_recorder,
            bindings,
            runtime_config,
        )


# @matrix csrf : exemption-policy route-gate
# @pairs agent-api:error-envelope agent-api:routing error-handling:csrf login:google-signin
def test_csrf_exempt_surfaces_reach_replacement_authentication_gates(
    monkeypatch,
):
    monkeypatch.setattr(CONFIG, "HOSTED_E2E", False, raising=False)
    monkeypatch.setattr(CONFIG, "AI_EMAIL_CONFIG", None)
    monkeypatch.setattr(CONFIG, "GOOGLE_SIGNIN_ENABLED", True)
    monkeypatch.setattr(
        user_login_routes,
        "_enforce_auth_rate_limit",
        lambda *args, **kwargs: None,
    )

    route_owned_responses = (
        ("/process/jobs", 401, "Unauthorized"),
        ("/testing/session", 404, None),
        ("/webhooks/resend/ai-email", 404, None),
        ("/api", 405, None),
        ("/api/v1/plans", 401, None),
    )
    for path, expected_status, expected_text in route_owned_responses:
        response = _open_request("POST", path, json={})
        assert response.status_code == expected_status
        assert response.headers.get("X-Lagniappe-CSRF") is None
        if expected_text is not None:
            assert response.get_data(as_text=True) == expected_text

    family_response = _open_request("POST", "/api", json={})
    assert family_response.json["error"]["code"] == "method_not_allowed"
    assert family_response.headers["X-Request-ID"] == family_response.json["request_id"]

    logout_response = _open_request("POST", "/users/logout", json={})
    assert logout_response.status_code == 400
    assert logout_response.headers["X-Lagniappe-CSRF"] == "invalid"

    google_response = _open_request(
        "POST",
        "/users/google-signin",
        data={"g_csrf_token": "google-token"},
        cookies=(("g_csrf_token", "google-token"),),
    )
    assert google_response.status_code == 400
    assert "No credential provided" in google_response.get_data(as_text=True)
    assert google_response.headers.get("X-Lagniappe-CSRF") is None


# @matrix login session : cookie-hardening lifetime
# @pair web-headers:security
def test_flask_security_configuration_and_session_cookie_attributes():
    flask_app = Flask("security-wiring")
    runtime_config = SimpleNamespace(
        SECRET_KEY="test-security-secret",
        development=True,
        testing=True,
    )
    configure_flask_security(flask_app, runtime_config)

    assert flask_app.config["USE_SESSION_FOR_NEXT"] is True
    assert flask_app.config["SECRET_KEY"] == "test-security-secret"
    assert flask_app.config["SESSION_COOKIE_SECURE"] is True
    assert flask_app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert flask_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert flask_app.config["REMEMBER_COOKIE_SECURE"] is True
    assert flask_app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert flask_app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"
    assert flask_app.config["REMEMBER_COOKIE_DURATION"] == timedelta(days=30)
    assert flask_app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=1)
    assert flask_app.debug is True
    assert flask_app.testing is True

    @flask_app.get("/")
    def write_session():
        session.permanent = True
        session["security-contract"] = True
        return "ok"

    response = flask_app.test_client().get("/")
    session_cookie = response.headers["Set-Cookie"]
    assert "Secure" in session_cookie
    assert "HttpOnly" in session_cookie
    assert "SameSite=Lax" in session_cookie


# @matrix auth login : lazy-user-loading login-manager redirect-view
def test_login_manager_wiring_and_anonymous_redirect():
    class LoginManagerRecorder:
        def __init__(self):
            self.init_call = None
            self.login_view = None
            self.loader = None

        def init_app(self, flask_app, *, add_context_processor):
            self.init_call = (flask_app, add_context_processor)

        def user_loader(self, callback):
            self.loader = callback
            return callback

    fake_app = Sentinel("flask-app")
    manager = LoginManagerRecorder()
    login_start.initialize(fake_app, manager_factory=lambda: manager)

    assert manager.init_call == (fake_app, False)
    assert manager.login_view == "users.login"
    assert manager.loader.__self__ is Entities.USER
    assert manager.loader.__func__ is Entities.USER.load.__func__

    assert app.login_manager.login_view == "users.login"
    response = app.test_client().get("/users/index")
    assert response.status_code == 302
    location = urlsplit(response.headers["Location"])
    assert location.path == "/users/login"
    assert parse_qs(location.query) == {"next": ["/users/index"]}


# @pair web-headers:security
def test_common_security_headers():
    with app.test_request_context("/security-wiring"):
        response = app.process_response(app.make_response("ok"))

    assert response.headers["Strict-Transport-Security"] == (
        "max-age=31536000; includeSubDomains; preload"
    )
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Content-Security-Policy"] == CSP
    assert response.headers["Cache-Control"] == "private, no-cache"


# @matrix agent-api : bearer-only error-envelope no-store request-correlation session-independent
@pytest.mark.parametrize("path", ("/api", "/api/v1"))
def test_external_api_authentication_and_header_contract(monkeypatch, path):
    actor = SimpleNamespace(is_public=False, urlsafe_key="security-wiring-actor")
    monkeypatch.setattr(
        api_routes.agent_auth,
        "authenticate_credential",
        lambda token: (
            (actor, {"active": True})
            if token == "valid-key"
            else (_ for _ in ()).throw(
                api_routes.agent_auth.AgentAPICredentialError("invalid")
            )
        ),
    )
    monkeypatch.setattr(
        api_routes,
        "check_limit",
        lambda *args: {
            "allowed": True,
            "count": 1,
            "remaining": 59,
            "retry_after": 60,
        },
    )

    unauthorized = _open_request(
        "GET",
        path,
        headers={"X-Request-ID": "client-request-1"},
        session_values={"_user_id": "browser-session@example.test"},
    )
    assert unauthorized.status_code == 401
    assert unauthorized.headers["WWW-Authenticate"] == ('Bearer realm="Lagniappe API"')
    assert unauthorized.headers["Cache-Control"] == "no-store"
    assert unauthorized.headers["X-Request-ID"] == "client-request-1"
    assert unauthorized.json["request_id"] == "client-request-1"

    invalid_id = "invalid request id"
    replaced = _open_request(
        "GET",
        path,
        headers={"X-Request-ID": invalid_id},
    )
    assert replaced.status_code == 401
    assert replaced.headers["X-Request-ID"]
    assert replaced.headers["X-Request-ID"] != invalid_id
    assert replaced.headers["X-Request-ID"] == replaced.json["request_id"]

    authorized = _open_request(
        "GET",
        path,
        headers={
            "Authorization": "Bearer valid-key",
            "X-Request-ID": "success-request-1",
        },
    )
    assert authorized.status_code == 200
    assert authorized.headers["Cache-Control"] == "no-store"
    assert authorized.headers["X-Request-ID"] == "success-request-1"
    assert authorized.headers.get("WWW-Authenticate") is None
