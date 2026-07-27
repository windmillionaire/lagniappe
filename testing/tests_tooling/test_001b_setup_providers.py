"""Tooling tests for setup provider API helpers."""

import smtplib
import sys
import types

import pytest

from installer.errors import (
    ProviderConflict,
    ProviderError,
    ProviderPermissionDenied,
    ProviderTimeout,
    ProviderTransientError,
)
from testing.utility.setup_fakes import (
    FakeResponse,
    FakeSession,
    SpinnerRecorder,
    spinner_factory,
)

pytestmark = pytest.mark.tooling


@pytest.fixture(autouse=True)
def fake_yaspin_module(monkeypatch):
    from testing.utility.setup_fakes import spinner_factory

    monkeypatch.setitem(
        sys.modules, "yaspin", types.SimpleNamespace(yaspin=spinner_factory())
    )


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.started_tls = None
        self.credentials = None
        self.message = None
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context):
        self.started_tls = context

    def login(self, email, password):
        self.credentials = (email, password)

    def send_message(self, message):
        self.message = message


# @features setup
# @dimensions authentication-email validation smtp app-password
def test_auth_email_config_requires_canonical_smtp():
    from installer import auth_email

    assert auth_email.normalize_app_password("abcd efgh ijkl mnop") == (
        "abcdefghijklmnop"
    )
    assert auth_email.normalize_app_password("short") is None
    generic = {
        "provider": "smtp",
        "service": "Resend",
        "host": "smtp.resend.com",
        "port": "465",
        "security": "SSL",
        "username": "resend",
        "password": "provider-key",
        "senderEmail": "noreply@example.test",
        "senderName": "Demo",
    }
    assert auth_email.normalize_auth_email_config(generic)["port"] == 465
    assert auth_email.auth_email_config_matches(generic)
    assert not auth_email.auth_email_config_matches(
        {
            **generic,
            "senderEmail": "not-an-email",
            "senderName": "Demo",
        }
    )


# @features setup
# @dimensions authentication-email smtp tls
def test_smtp_test_message_supports_starttls_and_implicit_tls():
    from installer import auth_email

    FakeSMTP.instances.clear()
    tls_context = object()
    starttls_config = {
        "provider": "smtp",
        "service": "Resend",
        "host": "smtp.resend.test",
        "port": 587,
        "security": "starttls",
        "username": "resend",
        "password": "provider-key",
        "senderEmail": "sender@example.test",
        "senderName": "Demo",
    }
    assert auth_email.test_smtp_delivery(
        starttls_config,
        "recipient@example.test",
        smtp_factory=FakeSMTP,
        tls_context=tls_context,
    )
    starttls = FakeSMTP.instances[0]
    assert (starttls.host, starttls.port, starttls.timeout) == (
        "smtp.resend.test",
        587,
        auth_email.SMTP_TIMEOUT,
    )
    assert starttls.started_tls is tls_context
    assert starttls.credentials == ("resend", "provider-key")
    assert starttls.message["To"] == "recipient@example.test"

    assert auth_email.test_smtp_delivery(
        {
            **starttls_config,
            "port": 465,
            "security": "ssl",
        },
        "recipient@example.test",
        smtp_ssl_factory=FakeSMTP,
        tls_context=tls_context,
    )
    implicit_tls = FakeSMTP.instances[1]
    assert implicit_tls.context is tls_context
    assert implicit_tls.started_tls is None

    class RejectingSMTP(FakeSMTP):
        def send_message(self, message):
            raise smtplib.SMTPDataError(
                550,
                b"The sender domain is not verified.",
            )

    with pytest.raises(
        ProviderError,
        match=r"Resend rejected.*SMTP 550: The sender domain is not verified",
    ):
        auth_email.test_smtp_delivery(
            {
                **starttls_config,
                "port": 465,
                "security": "ssl",
            },
            "recipient@example.test",
            smtp_ssl_factory=RejectingSMTP,
            tls_context=tls_context,
        )


# @features setup
# @dimensions authentication-email interactive-input settings-save failure-isolation
def test_setup_auth_email_saves_generic_gmail_smtp_after_test(monkeypatch):
    from installer import auth_email

    saves = []
    settings = types.SimpleNamespace(
        APP={
            "ADMIN_EMAIL": "owner@example.test",
            "APP_NAME": "Demo",
        },
        save=lambda: saves.append(True),
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            error=lambda message: message,
            warning=lambda message: message,
            success=lambda message: message,
        )
    )
    monkeypatch.setattr(auth_email, "FORMATTER", formatter)
    opened_urls = []
    monkeypatch.setattr(
        auth_email.webbrowser,
        "open_new_tab",
        lambda url: opened_urls.append(url) or True,
    )
    deliveries = []
    monkeypatch.setattr(
        auth_email,
        "test_smtp_delivery",
        lambda config, recipient: deliveries.append(
            (config.copy(), recipient)
        )
        or True,
    )
    answers = iter(
        [
            "",
            "",
            "",
            "abcd efgh ijkl mnop",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert auth_email.setup_auth_email()
    assert settings.APP["AUTH_EMAIL_CONFIG"] == {
        "provider": "smtp",
        "service": "Gmail",
        "host": "smtp.gmail.com",
        "port": 587,
        "security": "starttls",
        "username": "owner@example.test",
        "password": "abcdefghijklmnop",
        "senderEmail": "owner@example.test",
        "senderName": "Demo",
    }
    assert deliveries == [
        (settings.APP["AUTH_EMAIL_CONFIG"], "owner@example.test")
    ]
    assert opened_urls == [auth_email.GMAIL_APP_PASSWORDS_URL]
    assert "accounts.google.com/AccountChooser" in opened_urls[0]
    assert "myaccount.google.com%2Fapppasswords" in opened_urls[0]
    assert saves == [True]


# @features setup
# @dimensions authentication-email custom-domain smtp interactive-input
def test_setup_auth_email_uses_custom_domain_provider_path(monkeypatch):
    from installer import auth_email
    from installer import custom_domain

    events = []
    settings = types.SimpleNamespace(
        APP={
            "ADMIN_EMAIL": "owner@example.test",
            "APP_NAME": "Demo",
        },
        save=lambda: events.append("save"),
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )

    def configure_domain(*, configure_auth=True):
        events.append(("domain", configure_auth))
        settings.APP["CUSTOM_DOMAIN"] = "app.example.test"
        settings.APP["GOOGLE_LOGIN_URI"] = (
            "https://app.example.test/users/google-signin"
        )
        return True

    monkeypatch.setattr(custom_domain, "_setup_custom_domain", configure_domain)
    monkeypatch.setattr(
        auth_email,
        "_setup_provider_auth_email",
        lambda: events.append("provider-email") or True,
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert auth_email.setup_auth_email()
    assert events == [
        ("domain", False),
        "save",
        "provider-email",
    ]


# @features setup
# @dimensions authentication-email smtp resend cloudflare-dns interactive-input settings-save
def test_provider_auth_email_uses_resend_cloudflare_shortcut(monkeypatch):
    from installer import auth_email

    saves = []
    settings = types.SimpleNamespace(
        APP={
            "ADMIN_EMAIL": "owner@example.test",
            "APP_NAME": "Demo",
            "CUSTOM_DOMAIN": "app.example.test",
            "CLOUDFLARE_ZONE_ID": "zone-1",
        },
        save=lambda: saves.append(True),
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            error=lambda message: message,
            warning=lambda message: message,
            success=lambda message: message,
            info=lambda message: message,
        )
    )
    monkeypatch.setattr(auth_email, "FORMATTER", formatter)
    opened_urls = []
    monkeypatch.setattr(
        auth_email.webbrowser,
        "open_new_tab",
        lambda url: opened_urls.append(url) or True,
    )
    deliveries = []
    monkeypatch.setattr(
        auth_email,
        "test_smtp_delivery",
        lambda config, recipient: deliveries.append(
            (config.copy(), recipient)
        )
        or True,
    )
    answers = iter(
        [
            "",
            "",
            "mail.app.example.test",
            "re_sending_key",
            "",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert auth_email._setup_provider_auth_email()
    assert settings.APP["AUTH_EMAIL_CONFIG"] == {
        "provider": "smtp",
        "service": "Resend",
        "host": "smtp.resend.com",
        "port": 465,
        "security": "ssl",
        "username": "resend",
        "password": "re_sending_key",
        "senderEmail": "noreply@mail.app.example.test",
        "senderName": "Demo",
    }
    assert deliveries == [
        (settings.APP["AUTH_EMAIL_CONFIG"], "owner@example.test")
    ]
    assert opened_urls == [
        auth_email.RESEND_DOMAINS_URL,
        auth_email.RESEND_API_KEYS_URL,
    ]
    assert saves == [True]


# @features setup
# @dimensions authentication-email smtp custom-domain interactive-input settings-save
def test_provider_auth_email_saves_only_after_successful_smtp_test(monkeypatch):
    from installer import auth_email

    saves = []
    settings = types.SimpleNamespace(
        APP={
            "ADMIN_EMAIL": "owner@example.test",
            "APP_NAME": "Demo",
            "CUSTOM_DOMAIN": "app.example.test",
        },
        save=lambda: saves.append(True),
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            error=lambda message: message,
            warning=lambda message: message,
            success=lambda message: message,
            info=lambda message: message,
        )
    )
    monkeypatch.setattr(auth_email, "FORMATTER", formatter)
    deliveries = []
    monkeypatch.setattr(
        auth_email,
        "test_smtp_delivery",
        lambda config, recipient: deliveries.append(
            (config.copy(), recipient)
        )
        or True,
    )
    answers = iter(
        [
            "n",
            "Resend",
            "smtp.resend.test",
            "465",
            "ssl",
            "resend",
            "provider-key",
            "noreply@example.test",
            "Demo",
            "owner@example.test",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert auth_email._setup_provider_auth_email()
    assert settings.APP["AUTH_EMAIL_CONFIG"] == {
        "provider": "smtp",
        "service": "Resend",
        "host": "smtp.resend.test",
        "port": 465,
        "security": "ssl",
        "username": "resend",
        "password": "provider-key",
        "senderEmail": "noreply@example.test",
        "senderName": "Demo",
    }
    assert deliveries == [
        (settings.APP["AUTH_EMAIL_CONFIG"], "owner@example.test")
    ]
    assert saves == [True]


# @features setup
# @dimensions firebase-api authentication retry
def test_firebase_access_token_refresh_retries_connection_resets(monkeypatch):
    import google.auth
    from installer import firebase

    attempts = []
    delays = []

    class Credentials:
        token = None

        def refresh(self, request):
            attempts.append(request)
            if len(attempts) < 3:
                raise ConnectionResetError(
                    10054,
                    "An existing connection was forcibly closed by the remote host",
                )
            self.token = "firebase-token"

    credentials = Credentials()
    monkeypatch.setattr(firebase, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        google.auth,
        "default",
        lambda scopes: (credentials, "target-project-1"),
    )
    monkeypatch.setattr(firebase.time, "sleep", delays.append)

    assert firebase._get_access_token() == "firebase-token"
    assert len(attempts) == 3
    assert delays == [1, 2]


# @features setup
# @dimensions firebase-api
# @pair setup:firebase-api
# @pair firebase-api:quota-project
def test_firebase_helpers_use_timeouts_and_report_errors(monkeypatch):
    from installer import firebase

    assert firebase._firebase_request_headers(
        "token",
        "quota-project-1",
        json_content=True,
    ) == {
        "Authorization": "Bearer token",
        "x-goog-user-project": "quota-project-1",
        "Content-Type": "application/json",
    }

    apps = [
        {"appId": "one", "displayName": "First"},
        {"appId": "two", "displayName": "Second"},
    ]
    assert firebase._find_web_app(apps, app_id="two") == apps[1]
    assert firebase._find_web_app(apps, display_name="First") == apps[0]
    assert firebase._find_web_app(apps, app_id="missing") is None

    session = FakeSession([FakeResponse(200, {"ok": True})])
    _, data = firebase._api_request(
        session,
        "GET",
        "https://firebase.googleapis.com/v1beta1/projects/demo",
        {"Authorization": "Bearer token"},
    )
    assert data == {"ok": True}
    assert session.calls[0]["timeout"] == firebase.FIREBASE_API_TIMEOUT

    patch_session = FakeSession([FakeResponse(200, {"updated": True})])
    _, data = firebase._api_request(
        patch_session,
        "PATCH",
        "https://identitytoolkit.googleapis.com/admin/v2/projects/demo/config",
        {"Authorization": "Bearer token"},
        {"signIn": {"email": {"enabled": True}}},
    )
    assert data == {"updated": True}
    assert patch_session.calls == [
        {
            "method": "PATCH",
            "url": (
                "https://identitytoolkit.googleapis.com/admin/v2/"
                "projects/demo/config"
            ),
            "headers": {"Authorization": "Bearer token"},
            "json": {"signIn": {"email": {"enabled": True}}},
            "timeout": firebase.FIREBASE_API_TIMEOUT,
        }
    ]

    bad_session = FakeSession(
        [FakeResponse(500, {"error": "boom"}, text="boom")] * 4
    )
    monkeypatch.setattr(firebase.time, "sleep", lambda delay: None)
    with pytest.raises(ProviderTransientError):
        firebase._api_request(bad_session, "POST", "https://firebase.example", {})
    assert len(bad_session.calls) == 4


# @features setup
# @dimensions firebase-api diagnostics retry
def test_firebase_api_request_reports_google_reason_and_retries_service_activation(
    monkeypatch,
    capsys,
):
    from installer import firebase

    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(info=lambda message: message)
    )
    monkeypatch.setattr(firebase, "FORMATTER", formatter)
    delays = []
    monkeypatch.setattr(firebase.time, "sleep", delays.append)
    service_disabled = {
        "error": {
            "code": 403,
            "message": "Identity Toolkit API has not been used in this project.",
            "status": "PERMISSION_DENIED",
            "details": [
                {
                    "reason": "SERVICE_DISABLED",
                    "metadata": {"activationUrl": "https://example.invalid/long"},
                },
                "ignore malformed details",
            ],
        }
    }
    session = FakeSession(
        [
            FakeResponse(403, service_disabled),
            FakeResponse(200, {"ready": True}),
        ]
    )

    _, data = firebase._api_request(
        session,
        "POST",
        "https://identitytoolkit.googleapis.com/v2/projects/demo/"
        "identityPlatform:initializeAuth",
        {},
        attempts=2,
        delays=(3,),
        retry_label="Identity Platform",
    )

    assert data == {"ready": True}
    assert delays == [3]
    assert "retrying in 3 seconds" in capsys.readouterr().out

    failure_session = FakeSession([FakeResponse(403, service_disabled)])
    with pytest.raises(ProviderTransientError) as caught:
        firebase._api_request(
            failure_session,
            "POST",
            "https://identitytoolkit.googleapis.com/v2/projects/demo/"
            "identityPlatform:initializeAuth",
            {},
            attempts=1,
        )
    message = str(caught.value)
    assert "HTTP 403 PERMISSION_DENIED (SERVICE_DISABLED)" in message
    assert "Identity Toolkit API has not been used" in message
    assert "activationUrl" not in message
    assert "identityPlatform:initializeAuth" not in message


# @features setup
# @dimensions firebase-api recovery provider-discovery settings-preservation
def test_firebase_recovery_discovers_saved_app_without_overwriting_snapshot(
    monkeypatch,
):
    import requests
    import installer as setup_package
    from installer import firebase

    saved_config = {
        "projectId": "recovered-project-1",
        "appId": "saved-app-id",
        "apiKey": "saved-api-key",
    }
    settings = types.SimpleNamespace(
        APP={
            "APP_NAME": "Recovered App",
            "FIREBASE_CONFIG": saved_config.copy(),
        },
        GCLOUD_CONFIG={"PROJECT": "recovered-project-1"},
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    monkeypatch.setattr(
        setup_package,
        "FORMATTER",
        types.SimpleNamespace(
            initialize=lambda: types.SimpleNamespace(
                success=lambda message: message,
                warning=lambda message: message,
                info=lambda message: message,
                error=lambda message, error=None: message,
                ok_glyph="[OK]",
                fail_glyph="[X]",
                yaspin=lambda **kwargs: spinner_factory(SpinnerRecorder())(),
            )
        ),
    )
    monkeypatch.setattr(firebase, "FORMATTER", setup_package.FORMATTER)
    monkeypatch.setattr(firebase, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(firebase, "_get_access_token", lambda: "access-token")
    session = FakeSession([FakeResponse(200, {"projectId": "recovered-project-1"})])
    monkeypatch.setattr(requests, "Session", lambda: session)

    calls = []

    def api_request(
        request_session,
        method,
        url,
        headers,
        data=None,
        allow_codes=None,
    ):
        calls.append((method, url, data))
        if url.endswith("/projects/recovered-project-1"):
            return FakeResponse(200), {
                "projectId": "recovered-project-1"
            }
        if url.endswith("/webApps"):
            return FakeResponse(200), {
                "apps": [
                    {
                        "appId": "different-app-id",
                        "displayName": "Recovered App",
                    },
                    {
                        "appId": "saved-app-id",
                        "displayName": "Old Display Name",
                    },
                ]
            }
        assert url.endswith("/webApps/saved-app-id/config")
        return FakeResponse(200), {
            "projectId": "recovered-project-1",
            "appId": "saved-app-id",
            "apiKey": "live-api-key",
        }

    monkeypatch.setattr(firebase, "_api_request", api_request)

    live_config = firebase._configure_firebase()

    assert live_config["apiKey"] == "live-api-key"
    assert [method for method, _url, _data in calls] == ["GET", "GET", "GET"]
    assert calls[-1][1].endswith("/webApps/saved-app-id/config")
    assert settings.APP["FIREBASE_CONFIG"] == saved_config


# @features setup
# @dimensions firebase-api
def test_firebase_operation_polling_uses_operation_endpoint(monkeypatch):
    from installer import firebase

    session = FakeSession(
        [
            FakeResponse(200, {"done": False}),
            FakeResponse(200, {"done": True, "response": {"name": "projects/demo"}}),
        ]
    )
    monkeypatch.setattr(firebase.time, "sleep", lambda seconds: None)

    response = firebase._poll_operation(
        session, "operations/provision-demo", {}, SpinnerRecorder()
    )

    assert response == {"name": "projects/demo"}
    assert [call["url"] for call in session.calls] == [
        "https://firebase.googleapis.com/v1beta1/operations/provision-demo",
        "https://firebase.googleapis.com/v1beta1/operations/provision-demo",
    ]


# @features setup
# @dimensions firebase-api
def test_firebase_operation_polling_exits_on_error_and_timeout(monkeypatch):
    from installer import firebase

    error_spinner = SpinnerRecorder()
    error_session = FakeSession(
        [FakeResponse(200, {"done": True, "error": {"message": "provision failed"}})]
    )

    with pytest.raises(ProviderError):
        firebase._poll_operation(
            error_session, "operations/error-demo", {}, error_spinner
        )

    assert error_spinner.fails == ["✗"]

    timeout_spinner = SpinnerRecorder()
    timeout_session = FakeSession()
    monotonic_values = iter([0, firebase.FIREBASE_OPERATION_TIMEOUT_SECONDS + 1])
    monkeypatch.setattr(firebase.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(ProviderTimeout):
        firebase._poll_operation(
            timeout_session, "operations/timeout-demo", {}, timeout_spinner
        )

    assert timeout_session.calls == []
    assert timeout_spinner.fails == ["✗"]


# @features setup
# @dimensions firebase-api pagination operation-response
def test_firebase_web_app_pagination_and_operation_response(monkeypatch):
    import requests
    import installer as setup_package
    from installer import firebase

    settings = types.SimpleNamespace(
        APP={"APP_NAME": "Demo"},
        GCLOUD_CONFIG={"PROJECT": "project-1"},
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            success=lambda message: message,
            warning=lambda message: message,
            info=lambda message: message,
            error=lambda message, error=None: message,
            ok_glyph="[OK]",
            fail_glyph="[X]",
            yaspin=lambda **kwargs: spinner_factory(SpinnerRecorder())(),
        )
    )
    monkeypatch.setattr(setup_package, "FORMATTER", formatter)
    monkeypatch.setattr(firebase, "FORMATTER", formatter)
    monkeypatch.setattr(firebase, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(firebase, "_get_access_token", lambda: "token")
    monkeypatch.setattr(firebase.time, "sleep", lambda seconds: None)
    session = FakeSession(
        [
            FakeResponse(200, {"projectId": "project-1"}),
            FakeResponse(200, {"apps": [], "nextPageToken": "page two"}),
            FakeResponse(200, {"apps": []}),
            FakeResponse(200, {"name": "operations/create-web-app"}),
            FakeResponse(200, {"done": False}),
            FakeResponse(
                200,
                {
                    "done": True,
                    "response": {
                        "projectId": "project-1",
                        "appId": "1:123:web:abc",
                        "displayName": "Demo",
                    },
                },
            ),
            FakeResponse(
                200,
                {
                    "projectId": "project-1",
                    "appId": "1:123:web:abc",
                    "apiKey": "live-key",
                },
            ),
        ]
    )
    monkeypatch.setattr(requests, "Session", lambda: session)

    assert firebase._configure_firebase()["appId"] == "1:123:web:abc"
    assert session.calls[2]["url"].endswith(
        "/webApps?pageToken=page%20two"
    )
    assert session.calls[3]["method"] == "POST"
    assert session.calls[4]["url"].endswith("/operations/create-web-app")
    assert session.calls[5]["url"].endswith("/operations/create-web-app")
    assert session.calls[6]["url"].endswith(
        "/webApps/1:123:web:abc/config"
    )


# @features setup
# @dimensions firebase-api conflict provider-convergence
def test_firebase_already_running_web_app_create_is_discovered(monkeypatch):
    import requests
    import installer as setup_package
    from installer import firebase

    settings = types.SimpleNamespace(
        APP={"APP_NAME": "Demo"},
        GCLOUD_CONFIG={"PROJECT": "project-1"},
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            success=lambda message: message,
            warning=lambda message: message,
            info=lambda message: message,
            error=lambda message, error=None: message,
            ok_glyph="[OK]",
            fail_glyph="[X]",
            yaspin=lambda **kwargs: spinner_factory(SpinnerRecorder())(),
        )
    )
    monkeypatch.setattr(setup_package, "FORMATTER", formatter)
    monkeypatch.setattr(firebase, "FORMATTER", formatter)
    monkeypatch.setattr(firebase, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(firebase, "_get_access_token", lambda: "token")
    monkeypatch.setattr(firebase.time, "sleep", lambda seconds: None)
    session = FakeSession(
        [FakeResponse(200, {"projectId": "project-1"})]
    )
    monkeypatch.setattr(requests, "Session", lambda: session)
    list_results = iter(
        [
            [],
            [
                {
                    "projectId": "project-1",
                    "appId": "1:123:web:existing",
                    "displayName": "Demo",
                }
            ],
        ]
    )
    monkeypatch.setattr(
        firebase,
        "_list_web_apps",
        lambda *args: next(list_results),
    )

    def api_request(
        request_session,
        method,
        url,
        headers,
        data=None,
        allow_codes=None,
    ):
        if method == "POST":
            return FakeResponse(409, {"error": "already running"}), {
                "error": "already running"
            }
        return FakeResponse(200), {
            "projectId": "project-1",
            "appId": "1:123:web:existing",
            "apiKey": "live-key",
        }

    monkeypatch.setattr(firebase, "_api_request", api_request)

    assert firebase._configure_firebase()["appId"] == "1:123:web:existing"


# @features setup
# @dimensions firebase-api permissions not-found
def test_firebase_project_permission_failure_is_not_treated_as_absent(
    monkeypatch,
):
    import requests
    import installer as setup_package
    from installer import firebase

    settings = types.SimpleNamespace(
        APP={"APP_NAME": "Demo"},
        GCLOUD_CONFIG={"PROJECT": "project-1"},
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            success=lambda message: message,
            warning=lambda message: message,
            info=lambda message: message,
            error=lambda message, error=None: message,
            ok_glyph="[OK]",
            fail_glyph="[X]",
            yaspin=lambda **kwargs: spinner_factory(SpinnerRecorder())(),
        )
    )
    monkeypatch.setattr(setup_package, "FORMATTER", formatter)
    monkeypatch.setattr(firebase, "FORMATTER", formatter)
    monkeypatch.setattr(firebase, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(firebase, "_get_access_token", lambda: "token")
    session = FakeSession([FakeResponse(403, {"error": "forbidden"})])
    monkeypatch.setattr(requests, "Session", lambda: session)

    with pytest.raises(ProviderPermissionDenied):
        firebase._configure_firebase()

    assert [call["method"] for call in session.calls] == ["GET"]


# @features setup
# @dimensions firebase-messaging public-config auth-separation
def test_firebase_messaging_client_config_excludes_auth_fields():
    from installer import firebase

    assert firebase._messaging_client_config(
        {
            "apiKey": "public-key",
            "appId": "1:123:web:abc",
            "authDomain": "project-1.firebaseapp.com",
            "measurementId": "G-MEASURE",
            "messagingSenderId": "123",
            "projectId": "project-1",
            "storageBucket": "project-1.firebasestorage.app",
        }
    ) == {
        "apiKey": "public-key",
        "appId": "1:123:web:abc",
        "messagingSenderId": "123",
        "projectId": "project-1",
    }


# @features setup
# @dimensions identity-platform provider-discovery provider-state permissions authorized-domain
def test_identity_platform_config_contract():
    from installer import identity

    enabled = {
        "subtype": "IDENTITY_PLATFORM",
        "client": {"apiKey": "public-key"},
        "signIn": {
            "email": {
                "enabled": True,
                "passwordRequired": True,
            }
        },
        "authorizedDomains": ["demo.example"],
        "notification": {
            "sendEmail": {
                "callbackUri": "https://demo.example/users/login",
            }
        },
    }
    assert identity.identity_platform_config_matches(
        enabled,
        "https://demo.example",
    )
    assert identity.identity_platform_target("https://demo.example/") == (
        "demo.example",
        "https://demo.example/users/login",
    )
    assert not identity.identity_platform_config_matches(
        {},
        "https://demo.example",
    )
    with pytest.raises(ProviderError):
        identity.identity_platform_target("http://demo.example")

    session = FakeSession(
        [
            FakeResponse(200, enabled),
            FakeResponse(404, {"error": "not found"}),
            FakeResponse(403, {"error": "forbidden"}),
        ]
    )
    assert identity.get_identity_platform_config(
        session, "project-1", {}
    ) == enabled
    assert identity.get_identity_platform_config(
        session, "project-1", {}
    ) is None
    with pytest.raises(ProviderPermissionDenied):
        identity.get_identity_platform_config(session, "project-1", {})


# @features setup
# @dimensions identity-platform provider-state settings-save authorized-domain provider-convergence
def test_identity_platform_setup_initializes_and_reconciles_provider_state(
    monkeypatch,
):
    import requests
    from installer import identity

    saves = []
    settings = types.SimpleNamespace(
        APP={"APP_URL": "https://demo.example"},
        GCLOUD_CONFIG={"PROJECT": "project-1"},
        save=lambda: saves.append(True),
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(
            success=lambda message: message,
            warning=lambda message: message,
            info=lambda message: message,
            error=lambda message, error=None: message,
            ok_glyph="[OK]",
            fail_glyph="[X]",
            yaspin=lambda **kwargs: spinner_factory(SpinnerRecorder())(),
        )
    )
    monkeypatch.setattr(identity, "FORMATTER", formatter)
    monkeypatch.setattr(identity, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(identity, "_get_access_token", lambda: "token")
    current = {
        "subtype": "IDENTITY_PLATFORM",
        "client": {"apiKey": "public-key"},
        "signIn": {"email": {"enabled": False, "passwordRequired": False}},
        "authorizedDomains": ["localhost"],
        "notification": {"sendEmail": {}},
    }
    core_expected = {
        **current,
        "signIn": {"email": {"enabled": True, "passwordRequired": True}},
        "authorizedDomains": ["localhost", "demo.example"],
    }
    session = FakeSession(
        [
            FakeResponse(404, {"error": "not initialized"}),
            FakeResponse(200, {}),
            FakeResponse(200, current),
            FakeResponse(200, {}),
            FakeResponse(200, core_expected),
        ]
    )
    monkeypatch.setattr(requests, "Session", lambda: session)
    mutations = []
    monkeypatch.setattr(
        identity,
        "record_mutation",
        lambda description, **kwargs: mutations.append((description, kwargs)),
    )

    assert identity.setup_identity_platform()
    assert settings.APP["IDENTITY_PLATFORM_CONFIG"] == {
        "apiKey": "public-key",
        "projectId": "project-1",
    }
    assert saves == [True]
    assert [call["method"] for call in session.calls] == [
        "GET",
        "POST",
        "GET",
        "PATCH",
        "GET",
    ]
    assert [mutation[1]["action"] for mutation in mutations] == [
        "created",
        "updated",
    ]


# @features setup
# @dimensions identity-platform provider-state provider-convergence retry diagnostics
def test_identity_platform_initialization_retries_api_activation(
    monkeypatch,
    capsys,
):
    from installer import firebase, identity

    current = {
        "subtype": "IDENTITY_PLATFORM",
        "client": {"apiKey": "public-key"},
        "signIn": {"email": {"enabled": True, "passwordRequired": True}},
        "authorizedDomains": ["demo.example"],
        "notification": {
            "sendEmail": {
                "callbackUri": "https://demo.example/users/login",
            }
        },
    }
    service_disabled = {
        "error": {
            "message": "Identity Toolkit API is still activating.",
            "status": "PERMISSION_DENIED",
            "details": [{"reason": "SERVICE_DISABLED"}],
        }
    }
    session = FakeSession(
        [
            FakeResponse(404, {"error": {"message": "Not initialized"}}),
            FakeResponse(403, service_disabled),
            FakeResponse(200, {}),
            FakeResponse(200, current),
        ]
    )
    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(info=lambda message: message)
    )
    monkeypatch.setattr(firebase, "FORMATTER", formatter)
    delays = []
    monkeypatch.setattr(firebase.time, "sleep", delays.append)
    mutations = []
    monkeypatch.setattr(
        identity,
        "record_mutation",
        lambda description, **kwargs: mutations.append((description, kwargs)),
    )

    assert identity.reconcile_identity_platform(
        session,
        "project-1",
        {},
        "https://demo.example",
    ) == current
    assert delays == [identity.IDENTITY_INITIALIZATION_DELAYS[0]]
    output = capsys.readouterr().out
    assert "config is absent" in output
    assert "still becoming available" in output
    assert "initialization accepted" in output
    assert mutations[0][1]["action"] == "created"


# @features setup
# @dimensions identity-platform provider-state idempotency
def test_identity_platform_initialization_accepts_existing_provider(
    monkeypatch,
    capsys,
):
    from installer import identity

    current = {
        "subtype": "IDENTITY_PLATFORM",
        "client": {"apiKey": "public-key"},
        "signIn": {"email": {"enabled": True, "passwordRequired": True}},
        "authorizedDomains": ["demo.example"],
        "notification": {
            "sendEmail": {
                "callbackUri": "https://demo.example/users/login",
            }
        },
    }
    session = FakeSession(
        [
            FakeResponse(404, {"error": {"message": "Not initialized"}}),
            FakeResponse(409, {"error": {"message": "Already initialized"}}),
            FakeResponse(200, current),
        ]
    )
    mutations = []
    monkeypatch.setattr(
        identity,
        "record_mutation",
        lambda description, **kwargs: mutations.append((description, kwargs)),
    )

    assert identity.reconcile_identity_platform(
        session,
        "project-1",
        {},
        "https://demo.example",
    ) == current
    assert "already exists" in capsys.readouterr().out
    assert mutations[0][1]["action"] == "existing"


# @features setup
# @dimensions identity-platform provider-state settings-save authorized-domain
def test_identity_platform_setup_is_idempotent_for_matching_provider_state(
    monkeypatch,
):
    import requests
    from installer import identity

    expected = {
        "subtype": "IDENTITY_PLATFORM",
        "client": {"apiKey": "public-key"},
        "signIn": {"email": {"enabled": True, "passwordRequired": True}},
        "authorizedDomains": ["demo.example"],
        "notification": {
            "sendEmail": {
                "callbackUri": "https://demo.example/users/login",
            }
        },
    }
    saves = []
    settings = types.SimpleNamespace(
        APP={
            "APP_URL": "https://demo.example",
            "IDENTITY_PLATFORM_CONFIG": {
                "apiKey": "public-key",
                "projectId": "project-1",
            },
        },
        GCLOUD_CONFIG={"PROJECT": "project-1"},
        save=lambda: saves.append(True),
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    monkeypatch.setattr(identity, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(identity, "_get_access_token", lambda: "token")
    session = FakeSession([FakeResponse(200, expected)])
    monkeypatch.setattr(requests, "Session", lambda: session)

    assert identity.setup_identity_platform()
    assert [call["method"] for call in session.calls] == ["GET"]
    assert saves == []


# @features setup
# @dimensions identity-platform provider-state auth-separation
def test_identity_platform_verification_preserves_standalone_subtype(
    monkeypatch,
):
    import requests
    from installer import identity

    settings = types.SimpleNamespace(
        APP={"APP_URL": "https://demo.example"},
        GCLOUD_CONFIG={"PROJECT": "project-1"},
    )
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    monkeypatch.setattr(identity, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(identity, "_get_access_token", lambda: "token")
    standalone = {
        "subtype": "IDENTITY_PLATFORM",
        "client": {"apiKey": "public-key"},
        "signIn": {"email": {"enabled": True, "passwordRequired": True}},
        "authorizedDomains": ["demo.example"],
        "notification": {
            "sendEmail": {
                "callbackUri": "https://demo.example/users/login",
            }
        },
    }
    monkeypatch.setattr(
        requests,
        "Session",
        lambda: FakeSession([FakeResponse(200, standalone)]),
    )
    assert identity.verify_standalone_identity_platform()

    firebase_auth = {**standalone, "subtype": "FIREBASE_AUTH"}
    monkeypatch.setattr(
        requests,
        "Session",
        lambda: FakeSession([FakeResponse(200, firebase_auth)]),
    )
    with pytest.raises(ProviderConflict, match="FIREBASE_AUTH"):
        identity.verify_standalone_identity_platform()


# @features setup
# @dimensions identity-platform google-oauth provider-state secrets
def test_identity_platform_google_provider_reconciliation(monkeypatch):
    import requests
    from installer import identity

    settings = types.SimpleNamespace(GCLOUD_CONFIG={"PROJECT": "project-1"})
    monkeypatch.setitem(
        sys.modules,
        "config",
        types.SimpleNamespace(SETTINGS=settings),
    )
    monkeypatch.setattr(identity, "install_if_missing", lambda *args, **kwargs: None)
    monkeypatch.setattr(identity, "_get_access_token", lambda: "token")
    session = FakeSession(
        [
            FakeResponse(404, {"error": "not found"}),
            FakeResponse(200, {}),
            FakeResponse(
                200,
                {
                    "enabled": True,
                    "clientId": "1234-demo.apps.googleusercontent.com",
                },
            ),
        ]
    )
    monkeypatch.setattr(requests, "Session", lambda: session)

    assert identity.setup_google_provider(
        "1234-demo.apps.googleusercontent.com",
        "oauth-secret",
    )
    assert session.calls[1]["method"] == "POST"
    assert "idpId=google.com" in session.calls[1]["url"]
    assert session.calls[1]["json"] == {
        "enabled": True,
        "clientId": "1234-demo.apps.googleusercontent.com",
        "clientSecret": "oauth-secret",
    }


# @features setup
# @pairs setup:identity-platform setup:recovery
def test_identity_platform_recovery_gets_live_config(monkeypatch):
    import requests
    from installer import firebase, identity, recovery

    monkeypatch.setattr(firebase, "_get_access_token", lambda: "token")
    firebase_session = FakeSession(
        [
            FakeResponse(200, {"projectId": "project-1"}),
            FakeResponse(
                200,
                {
                    "projectId": "project-1",
                    "appId": "1:123:web:abc",
                },
            ),
            FakeResponse(
                200,
                {
                    "projectId": "project-1",
                    "appId": "1:123:web:abc",
                    "apiKey": "live-key",
                },
            ),
        ]
    )
    monkeypatch.setattr(requests, "Session", lambda: firebase_session)
    observation = recovery._probe_firebase(
        "project-1",
        {"projectId": "project-1", "appId": "1:123:web:abc"},
    )
    assert observation["state"] == recovery.AVAILABLE
    assert observation["details"]["app"]["appId"] == "1:123:web:abc"

    monkeypatch.setattr(identity, "_get_access_token", lambda: "token")
    identity_session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "subtype": "IDENTITY_PLATFORM",
                    "signIn": {
                        "email": {
                            "enabled": True,
                            "passwordRequired": True,
                        }
                    },
                },
            )
        ]
    )
    monkeypatch.setattr(requests, "Session", lambda: identity_session)
    identity_observation = recovery._probe_identity_platform("project-1")
    assert identity_observation == {
        "state": recovery.AVAILABLE,
        "details": {
            "emailPasswordEnabled": True,
            "subtype": "IDENTITY_PLATFORM",
            "standalone": True,
        },
        "error": None,
    }


# @features setup
# @dimensions cloudflare-api cloudflare-dns zone-resolution dns-only idempotence provider-records partial-failure
def test_cloudflare_dns_only_reconciliation(monkeypatch):
    from installer.domain import cloudflare

    calls = []
    journal = []

    def fake_request(method, path, token, *, params=None, json_data=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "token": token,
                "params": params,
                "json": json_data,
            }
        )
        if path == "/zones":
            return {
                "result": [
                    {"id": "parent", "name": "co.uk"},
                    {
                        "id": "zone-1",
                        "name": "example.co.uk",
                        "account": {"id": "account-1"},
                    },
                ],
                "result_info": {"total_pages": 1},
            }
        if method == "GET":
            return {
                "result": [
                    {
                        "id": "existing",
                        "type": "A",
                        "name": "example.co.uk",
                        "content": "216.239.32.21",
                        "ttl": 300,
                        "proxied": True,
                    },
                    {
                        "id": "stale",
                        "type": "A",
                        "name": "example.co.uk",
                        "content": "216.239.30.21",
                        "ttl": 1,
                        "proxied": False,
                        "comment": cloudflare.CLOUDFLARE_RECORD_COMMENT,
                    },
                ]
            }
        if method == "PATCH":
            return {"result": {"id": "existing"}}
        if method == "POST":
            return {"result": {"id": "created"}}
        if method == "DELETE":
            return {"result": {"id": "stale"}}
        raise AssertionError((method, path))

    monkeypatch.setattr(cloudflare, "_cloudflare_request", fake_request)
    monkeypatch.setattr(
        cloudflare,
        "record_mutation",
        lambda step, **entry: journal.append({"step": step, **entry}),
    )
    api_token = "scoped-token-" + ("a" * 20)
    zone = cloudflare.get_cloudflare_zone(
        "app.example.co.uk",
        api_token,
    )
    assert zone["id"] == "zone-1"

    record_ids = cloudflare.reconcile_cloudflare_dns_records(
        "example.co.uk",
        zone,
        api_token,
        [
            {"type": "A", "rrdata": "216.239.32.21"},
            {"type": "A", "rrdata": "216.239.34.21"},
        ],
    )

    assert record_ids == ["existing", "created"]
    mutations = [call for call in calls if call["method"] in {"PATCH", "POST"}]
    assert all(call["json"]["proxied"] is False for call in mutations)
    assert all(call["json"]["ttl"] == 1 for call in mutations)
    assert {call["json"]["content"] for call in mutations} == {
        "216.239.32.21",
        "216.239.34.21",
    }
    assert any(call["method"] == "DELETE" for call in calls)
    assert any(
        entry["action"] == "updated"
        and entry["details"]["previous"]["content"] == "216.239.32.21"
        for entry in journal
    )
    assert any(
        entry["action"] == "deleted-stale"
        and entry["details"]["previous"]["content"] == "216.239.30.21"
        for entry in journal
    )
    assert api_token not in repr(journal)
    assert not any(
        marker in call["path"]
        for call in calls
        for marker in ("firewall", "bot", "rulesets", "settings")
    )
