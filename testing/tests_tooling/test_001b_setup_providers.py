"""Tooling tests for setup provider API helpers."""

import importlib
import smtplib
import sys
import types
from pathlib import Path

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
# @dimensions authentication-email smtp tls transient-retry error-reporting
def test_smtp_test_message_supports_tls_and_reports_transport_failures():
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

    class FlakySMTP(FakeSMTP):
        attempts = 0

        def starttls(self, context):
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise smtplib.SMTPServerDisconnected(
                    "Connection unexpectedly closed"
                )
            super().starttls(context)

    retry_delays = []
    assert auth_email.test_smtp_delivery(
        starttls_config,
        "recipient@example.test",
        smtp_factory=FlakySMTP,
        tls_context=tls_context,
        retry_sleep=retry_delays.append,
    )
    assert FlakySMTP.attempts == 2
    assert retry_delays == [1]

    class DisconnectedSMTP(FakeSMTP):
        def login(self, email, password):
            raise smtplib.SMTPServerDisconnected("Connection reset")

    with pytest.raises(
        ProviderTransientError,
        match=(
            r"connection to Resend was interrupted.*sign in.*"
            r"not explicitly rejected"
        ),
    ):
        auth_email.test_smtp_delivery(
            starttls_config,
            "recipient@example.test",
            smtp_factory=DisconnectedSMTP,
            tls_context=tls_context,
            smtp_attempts=1,
        )


# @features setup
# @dimensions authentication-email interactive-input settings-save failure-isolation
def test_setup_auth_email_saves_generic_gmail_smtp_after_test(monkeypatch, capsys):
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

    def test_delivery(config, recipient):
        assert saves == []
        deliveries.append((config.copy(), recipient))
        if len(deliveries) == 1:
            raise ProviderTransientError("The Gmail connection was interrupted.")
        return True

    monkeypatch.setattr(auth_email, "test_smtp_delivery", test_delivery)
    answers = iter(
        [
            "",
            "",
            "",
            "abcd efgh ijkl mnop",
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
        (settings.APP["AUTH_EMAIL_CONFIG"], "owner@example.test"),
        (settings.APP["AUTH_EMAIL_CONFIG"], "owner@example.test"),
    ]
    assert opened_urls == [auth_email.GMAIL_APP_PASSWORDS_URL]
    assert "accounts.google.com/AccountChooser" in opened_urls[0]
    assert "myaccount.google.com%2Fapppasswords" in opened_urls[0]
    assert saves == [True]
    output = " ".join(capsys.readouterr().out.split())
    assert "enter 'Lagniappe', then click Create" in output
    assert "Copy the 16-character password Google displays" in output
    assert "on its owner's behalf" in output
    assert "people the owner invites can verify their email addresses" in output
    assert "sender name is what recipients will see" in output
    assert "retry with the same mailbox and app password" in output
    assert "only if Gmail explicitly rejects sign-in" in output


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
# @dimensions google-provider authentication retry
def test_google_provider_access_token_refresh_retries_connection_resets(monkeypatch):
    import google.auth
    from installer import google_provider

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
            self.token = "provider-token"

    credentials = Credentials()
    monkeypatch.setattr(
        google_provider, "install_if_missing", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        google.auth,
        "default",
        lambda scopes: (credentials, "target-project-1"),
    )
    monkeypatch.setattr(google_provider.time, "sleep", delays.append)

    assert google_provider._get_access_token() == "provider-token"
    assert len(attempts) == 3
    assert delays == [1, 2]


# @features setup
# @dimensions google-provider-api
# @pair setup:google-provider-api
# @pair google-provider-api:quota-project
def test_google_provider_helpers_use_timeouts_and_report_errors(monkeypatch):
    from installer import google_provider

    assert google_provider._google_request_headers(
        "token",
        "quota-project-1",
        json_content=True,
    ) == {
        "Authorization": "Bearer token",
        "x-goog-user-project": "quota-project-1",
        "Content-Type": "application/json",
    }

    session = FakeSession([FakeResponse(200, {"ok": True})])
    _, data = google_provider._api_request(
        session,
        "GET",
        "https://identitytoolkit.googleapis.com/admin/v2/projects/demo/config",
        {"Authorization": "Bearer token"},
    )
    assert data == {"ok": True}
    assert session.calls[0]["timeout"] == google_provider.PROVIDER_API_TIMEOUT

    patch_session = FakeSession([FakeResponse(200, {"updated": True})])
    _, data = google_provider._api_request(
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
            "timeout": google_provider.PROVIDER_API_TIMEOUT,
        }
    ]

    bad_session = FakeSession(
        [FakeResponse(500, {"error": "boom"}, text="boom")] * 4
    )
    monkeypatch.setattr(google_provider.time, "sleep", lambda delay: None)
    with pytest.raises(ProviderTransientError):
        google_provider._api_request(
            bad_session, "POST", "https://provider.example", {}
        )
    assert len(bad_session.calls) == 4


# @features setup
# @dimensions google-provider-api diagnostics retry
def test_google_provider_api_request_reports_reason_and_retries_service_activation(
    monkeypatch,
    capsys,
):
    from installer import google_provider

    formatter = types.SimpleNamespace(
        initialize=lambda: types.SimpleNamespace(info=lambda message: message)
    )
    monkeypatch.setattr(google_provider, "FORMATTER", formatter)
    delays = []
    monkeypatch.setattr(google_provider.time, "sleep", delays.append)
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

    _, data = google_provider._api_request(
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
        google_provider._api_request(
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
# @dimensions identity-platform provider-state provider-convergence retry diagnostics
def test_identity_platform_initialization_retries_api_activation(
    monkeypatch,
    capsys,
):
    from installer import google_provider, identity

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
    monkeypatch.setattr(google_provider, "FORMATTER", formatter)
    delays = []
    monkeypatch.setattr(google_provider.time, "sleep", delays.append)
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


# @pairs setup:identity-platform setup:provider-state setup:auth-separation
def test_identity_platform_verification_preserves_standalone_subtype():
    from installer import identity

    standalone = {
        "subtype": "IDENTITY_PLATFORM",
    }
    identity._ensure_standalone_subtype(standalone, "project-1")

    firebase_auth = {**standalone, "subtype": "FIREBASE_AUTH"}
    with pytest.raises(ProviderConflict, match="FIREBASE_AUTH"):
        identity._ensure_standalone_subtype(firebase_auth, "project-1")


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
    import installer
    from installer import google_provider

    config_module = types.ModuleType("config")
    config_module.__path__ = [
        str(Path(__file__).resolve().parents[2] / "config")
    ]
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.delitem(sys.modules, "installer.recovery", raising=False)
    monkeypatch.delattr(installer, "recovery", raising=False)
    recovery = importlib.import_module("installer.recovery")

    monkeypatch.setattr(google_provider, "_get_access_token", lambda: "token")
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
