"""Direct contracts for web startup, CSRF, authentication, and headers."""

from dataclasses import replace
from datetime import timedelta
import io
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask, session
from werkzeug.test import EnvironBuilder

from lagniappe import CONFIG
from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.web import CSP, app, configure_flask_security
from lagniappe.web.start import blueprints as blueprint_start
from lagniappe.web.start import login as login_start


pytestmark = pytest.mark.http


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
        if blueprint is self.bindings["oauth"]:
            for name in ("oauth.token", "oauth.revoke"):
                self.view_functions[name] = self.bindings[name]
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
    bindings["oauth.token"] = Sentinel("oauth.token")
    bindings["oauth.revoke"] = Sentinel("oauth.revoke")
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
        ("view", "oauth.token", "Public OAuth code/PKCE or refresh-token proof; browser sessions are not authentication"),
        ("view", "oauth.revoke", "Opaque OAuth token possession; browser sessions are not authentication"),
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


def test_csrf_exempt_surfaces_reach_replacement_authentication_gates(
    monkeypatch,
):
    monkeypatch.setattr(CONFIG, "HOSTED_E2E", False, raising=False)
    monkeypatch.setattr(CONFIG, "AI_EMAIL_CONFIG", None)
    monkeypatch.setattr(CONFIG, "GOOGLE_SIGNIN_ENABLED", True)
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


@pytest.mark.parametrize("path", ("/api", "/api/v1"))
def test_external_api_authentication_and_header_contract(monkeypatch, path):
    actor = SimpleNamespace(is_public=False, urlsafe_key="security-wiring-actor")
    monkeypatch.setattr(
        agent_auth,
        "authenticate_credential",
        lambda token: (
            (actor, {"active": True})
            if token == "valid-key"
            else (_ for _ in ()).throw(
                agent_auth.AgentAPICredentialError("invalid")
            )
        ),
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
    assert unauthorized.headers["X-Lagniappe-Build-ID"] == CONFIG.BUILD_ID
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
    assert authorized.headers["X-Lagniappe-Build-ID"] == CONFIG.BUILD_ID
    assert authorized.headers.get("WWW-Authenticate") is None


def test_external_api_bounds_json_without_a_declared_content_length(monkeypatch):
    actor = SimpleNamespace(is_public=False, urlsafe_key="bounded-body-actor")
    monkeypatch.setattr(
        agent_auth,
        "authenticate_credential",
        lambda _token: (actor, {"active": True}),
    )
    max_json_body_bytes = external_api.MAX_PROPOSAL_BYTES + 64 * 1024
    body = b'{"padding":"' + (
        b"x" * max_json_body_bytes
    ) + b'"}'

    builder = EnvironBuilder(
        path="/api/v1/plans",
        method="POST",
        headers={
            "Authorization": "Bearer valid-key",
            "Content-Type": "application/json",
        },
        input_stream=io.BytesIO(body),
    )
    environ = builder.get_environ()
    environ.pop("CONTENT_LENGTH", None)
    environ["wsgi.input_terminated"] = True
    response = app.test_client().open(environ)

    assert response.status_code == 413
    assert response.json["error"] == {
        "code": "request_too_large",
        "message": "Request body is too large.",
    }


def test_home_tasks_etag_and_poll_revision_share_the_authenticated_snapshot(monkeypatch, http_client):
    from datetime import UTC, datetime
    from flask import g, url_for
    from google.cloud.datastore import Entity, Key
    from lagniappe.core.tools.database import utility
    from lagniappe.core.tools.polling.projections import channel_revision
    from lagniappe.web import auth, responses
    from lagniappe.web.routes.home import main

    actor = SimpleNamespace(
        is_authenticated=True, is_public=False, modified=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="user-v1", authorization_fingerprint="permissions-v1",
    )
    with app.test_request_context():
        route = url_for("internal.get", kind="tasks")
    key = Key("site", "tasks", project="offline")
    current = Entity(key=key)
    current["fingerprint"] = "tasks-v1"
    reads = []
    monkeypatch.setattr(utility.DATA, "_datastore_client", SimpleNamespace(key=lambda kind, name: Key(kind, name, project="offline")))

    def load(*, context_keys):
        reads.append(context_keys)
        g.request_context_records = {key: current}
        return actor, None

    monkeypatch.setattr(auth, "_load_request_context", load)
    monkeypatch.setattr(auth, "authenticated_user", lambda: actor)
    monkeypatch.setattr(main, "authenticated_user", lambda: actor)
    monkeypatch.setattr(responses, "home_section", lambda section: ("rendered", 200))
    with http_client.session_transaction() as client_session:
        client_session[auth.LOGIN_USER_KEY] = "user"
    first = http_client.get(route)
    assert first.status_code == 200
    assert first.headers["X-Lagniappe-Poll-Revision"] == channel_revision(
        "tasks", actor, site_fingerprints={"/tasks/index": "tasks-v1"},
    )
    headers = {"If-None-Match": first.headers["ETag"]}
    assert http_client.get(route, headers=headers).status_code == 304
    current["fingerprint"] = "tasks-v2"
    changed = http_client.get(route, headers=headers)
    assert changed.status_code == 200
    assert changed.headers["X-Lagniappe-Poll-Revision"] != first.headers["X-Lagniappe-Poll-Revision"]
    # Every request, including the 304, rechecks the live record with auth.
    assert reads == [(key,)] * 3


def test_stage_list_selection_preserves_project_membership_and_view_permission(monkeypatch):
    from google.cloud.datastore import Entity, Key
    from lagniappe.web.routes.projects import tasks

    project_key = Key("models", "project", project="offline")
    other_project_key = Key("models", "other", project="offline")
    record = Entity(key=project_key)
    record.update(type="project", hash="project-hash")
    project = Entities.PROJECT(record)
    stage = Entity(key=Key("models", "stage", parent=project_key))
    stage.update(type="model", project=project_key, hash="stage-hash", requires=["project-hash"])
    monkeypatch.setattr(tasks.database_get, "model_tasks", lambda _project: [stage])

    user_record = Entity(key=Key("users", "reader", project="offline"))
    user_record.update(type="user", email="reader@example.invalid")
    actor = Entities.USER(user_record)
    monkeypatch.setattr(tasks, "authenticated_user", lambda: actor)
    stage_key = stage.key.to_legacy_urlsafe().decode()
    assert tasks._project_model(project, stage_key, from_stage_list=True) is None
    actor.permissions = {"project-hash": "VIEW"}
    assert tasks._project_model(project, stage_key, from_stage_list=True) is project.model_tasks[0]

    foreign_key = Key("models", "stage", parent=other_project_key).to_legacy_urlsafe().decode()
    assert tasks._project_model(project, foreign_key, from_stage_list=True) is None
    assert tasks._project_model(project, "invalid", from_stage_list=True) is None


@pytest.mark.parametrize("stored,expected", [({}, True), ({"AI_AUTO_EXECUTE": False}, False)])
def test_home_ai_display_uses_settings_from_the_session_lookup(monkeypatch, stored, expected):
    from flask import g
    from google.cloud.datastore import Key
    from lagniappe.web import ai_display

    key = Key("site", "ai", project="offline")
    monkeypatch.setattr(CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(CONFIG, "AI_AUTO_EXECUTE", True, raising=False)
    monkeypatch.setattr(ai_display.site, "key", lambda _: key)
    with app.test_request_context("/"):
        assert ai_display.home_ai_context_keys() == (key,)
        g.request_context_records = {key: stored} if stored else {}
        assert ai_display.auto_execute_site_enabled() is expected

    with app.test_request_context("/", headers={"If-None-Match": '"cached"'}):
        assert ai_display.home_ai_context_keys() == ()


def test_personal_page_fingerprint_and_template_share_one_setting_per_request(monkeypatch):
    from lagniappe.web import ai_display
    from lagniappe.web.routes.pages.main import _user_settings_fingerprint

    values = iter([False, True])
    monkeypatch.setattr(ai_display, "site_auto_execute_enabled", lambda: next(values))
    template_setting = app.jinja_env.globals["auto_execute_site_enabled"]
    for enabled in (False, True):
        with app.test_request_context("/"):
            assert _user_settings_fingerprint(SimpleNamespace(fingerprint="page"), None) == f"page:{int(enabled)}"
            assert template_setting() is enabled


def test_page_notes_load_only_other_authors_and_preserve_visibility(monkeypatch):
    from flask import g
    from google.cloud.datastore import Entity, Key
    from lagniappe.web.routes.pages import notes

    def row(kind, name, **fields):
        record = Entity(key=Key(kind, name, project="offline"))
        record.update(type=kind, name=name, hash=name, **fields)
        return record

    page = Entities.PAGE(row("page", "page"))
    viewer = Entities.USER(row("user", "viewer", email="viewer@example.invalid"))
    other = row("user", "other", email="other@example.invalid")
    data = [
        row("note", name, parent=page.key, user=user, visibility=visibility, scope="page")
        for name, user, visibility in (
            ("mine", viewer.key, "private"),
            ("hidden", other.key, "private"),
            ("shared", other.key, "everyone"),
        )
    ]
    monkeypatch.setattr(notes.database_get, "page_notes", lambda _page: data)
    monkeypatch.setattr(notes.responses, "page_notes", lambda items, _page: [(n.name, n.user.name) for n in items])
    viewer.permissions = {page.hash: "VIEW"}
    page.db["requires"] = [page.hash]
    reads = []

    def read(keys):
        if keys:
            reads.append(set(keys))
        return [other] if other.key in keys else []

    monkeypatch.setattr(notes.database_get, "entities", read)
    with app.test_request_context():
        g._login_user = viewer
        assert notes.get_notes.__wrapped__(page.urlsafe_key, entity=page) == [("mine", "viewer"), ("shared", "other")]
    assert reads == [{other.key}]


def test_page_visibility_retries_once_on_mutation_conflict_and_returns_409_when_persistent(
    monkeypatch,
):
    from google.cloud.datastore import Entity, Key
    from lagniappe.core import exceptions
    from lagniappe.core.definitions import Action
    from lagniappe.web.routes.pages import main as pages_main

    def _make_page(fp: str):
        row = Entity(key=Key("page", "pub-page", project="offline"))
        row.update(
            type="page",
            name="Public Page",
            hash="pubpage",
            public=False,
            public_id="existingpub123",
            fingerprint=fp,
        )
        page = Entities.PAGE(row)
        page.allowed = lambda action, **_kw: action == Action.PUBLISH
        return page

    stale_page = _make_page("fp-stale")
    fresh_page = _make_page("fp-fresh")
    monkeypatch.setattr(
        pages_main.Entities,
        "fetch_one",
        lambda _key, **_kw: fresh_page,
    )
    monkeypatch.setattr(
        pages_main.responses,
        "page_document_settings",
        lambda entity: ({"entity": entity}, 200),
    )

    # First conflict recovers on reload; persistent conflict returns 409 instead of 500.
    saves = iter([exceptions.MutationConflict("concurrent sync"), None])

    def _save_first_conflict(*entities):
        outcome = next(saves)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(pages_main.Entities, "save", _save_first_conflict)
    with app.test_request_context(
        f"/pages/{stale_page.urlsafe_key}/visibility",
        method="PUT",
        data={"visibility": "public", "public-settings-present": "false"},
    ):
        response = pages_main.visibility.__wrapped__(stale_page.urlsafe_key, entity=stale_page)
        assert response[1] == 200
        assert response[0]["entity"] is fresh_page

    def _always_conflict(*_entities):
        raise exceptions.MutationConflict("persistent conflict")

    monkeypatch.setattr(pages_main.Entities, "save", _always_conflict)
    with app.test_request_context(
        f"/pages/{stale_page.urlsafe_key}/visibility",
        method="PUT",
        data={"visibility": "public", "public-settings-present": "false"},
    ):
        response = pages_main.visibility.__wrapped__(stale_page.urlsafe_key, entity=stale_page)
        assert response.status_code == 409
        assert "Please try again" in response.get_data(as_text=True)
