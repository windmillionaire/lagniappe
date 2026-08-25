"""Unit tests for Identity Platform runtime operations."""

import smtplib

import pytest

from lagniappe.core.tools.email import smtp as auth_email
from lagniappe.core.tools.services import identity_platform

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, data, *, ok=True, status_code=200):
        self._data = data
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


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


class RejectedSMTP(FakeSMTP):
    def login(self, email, password):
        raise smtplib.SMTPAuthenticationError(535, b"Bad credentials")


# @matrix login : audience identity-platform issuer token-verification
def test_verify_identity_token_enforces_project_issuer_and_subject(monkeypatch):
    claims = {
        "aud": "project-1",
        "iss": "https://securetoken.google.com/project-1",
        "sub": "identity-user-1",
        "email": "user@example.test",
    }
    calls = []
    monkeypatch.setattr(
        identity_platform.id_token,
        "verify_firebase_token",
        lambda token, request, audience: (
            calls.append((token, request, audience)) or claims.copy()
        ),
    )
    adapter = object()

    assert (
        identity_platform.verify_identity_token(
            "identity-token",
            "project-1",
            adapter,
        )["sub"]
        == "identity-user-1"
    )
    assert calls == [("identity-token", adapter, "project-1")]

    claims["iss"] = "https://securetoken.google.com/other-project"
    with pytest.raises(ValueError, match="issuer"):
        identity_platform.verify_identity_token(
            "identity-token",
            "project-1",
            adapter,
        )


# @matrix login : audience email-verification google-oauth token-verification
def test_verify_google_credential_enforces_client_and_verified_email(monkeypatch):
    claims = {
        "sub": "google-user-1",
        "email": "user@example.test",
        "email_verified": True,
    }
    calls = []
    monkeypatch.setattr(
        identity_platform.id_token,
        "verify_oauth2_token",
        lambda token, request, audience: (
            calls.append((token, request, audience)) or claims.copy()
        ),
    )
    adapter = object()

    assert (
        identity_platform.verify_google_credential(
            "google-token",
            "google-client-id",
            adapter,
        )["email"]
        == "user@example.test"
    )
    assert calls == [("google-token", adapter, "google-client-id")]

    claims["email_verified"] = False
    with pytest.raises(ValueError, match="not verified"):
        identity_platform.verify_google_credential(
            "google-token",
            "google-client-id",
            adapter,
        )


# @matrix login : google-oauth identity-platform provider-error-code token-exchange
def test_exchange_google_credential_uses_identity_platform_idp_endpoint():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "idToken": "identity-token",
                    "localId": "identity-user-1",
                    "email": "user@example.test",
                }
            )
        ]
    )

    result = identity_platform.exchange_google_credential(
        "google-id-token",
        {"apiKey": "public-key", "projectId": "project-1"},
        "https://project-1.example",
        session,
    )

    assert result["idToken"] == "identity-token"
    url, kwargs = session.calls[0]
    assert url.endswith("/accounts:signInWithIdp?key=public-key")
    assert kwargs["timeout"] == identity_platform.IDENTITY_REQUEST_TIMEOUT
    assert kwargs["json"]["requestUri"] == "https://project-1.example"
    assert (
        kwargs["json"]["postBody"] == "id_token=google-id-token&providerId=google.com"
    )
    assert kwargs["json"]["returnSecureToken"] is True

    disabled_session = FakeSession(
        [
            FakeResponse(
                {"error": {"message": "USER_DISABLED: Account disabled"}},
                ok=False,
                status_code=400,
            )
        ]
    )
    with pytest.raises(identity_platform.IdentityPlatformError) as error:
        identity_platform.exchange_google_credential(
            "google-id-token",
            {"apiKey": "public-key", "projectId": "project-1"},
            "https://project-1.example",
            disabled_session,
        )
    assert error.value.provider_code == "USER_DISABLED"

    payload_error_session = FakeSession(
        [FakeResponse({"errorMessage": "USER_DISABLED : Account disabled"})]
    )
    with pytest.raises(identity_platform.IdentityPlatformError) as error:
        identity_platform.exchange_google_credential(
            "google-id-token",
            {"apiKey": "public-key", "projectId": "project-1"},
            "https://project-1.example",
            payload_error_session,
        )
    assert error.value.provider_code == "USER_DISABLED"


# @matrix login : google-oauth identity-platform provider-state
def test_google_provider_enabled_reads_live_provider_state():
    session = FakeSession(
        [
            FakeResponse({"enabled": True}),
            FakeResponse({"enabled": False}),
            FakeResponse({"name": "projects/project-1/google.com"}),
            FakeResponse({}, ok=False, status_code=404),
        ]
    )

    arguments = {
        "project_id": "project/one",
        "access_token": "access-token",
        "session": session,
    }
    assert identity_platform.google_provider_enabled(**arguments) is True
    assert identity_platform.google_provider_enabled(**arguments) is False
    assert identity_platform.google_provider_enabled(**arguments) is False
    assert identity_platform.google_provider_enabled(**arguments) is False

    url, request = session.calls[0]
    assert url.endswith("/projects/project%2Fone/defaultSupportedIdpConfigs/google.com")
    assert request["headers"]["Authorization"] == "Bearer access-token"
    assert request["timeout"] == identity_platform.IDENTITY_REQUEST_TIMEOUT

    unavailable_session = FakeSession([])
    unavailable_session.get = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        identity_platform.http_requests.Timeout("timed out")
    )
    with pytest.raises(identity_platform.IdentityPlatformError, match="lookup failed"):
        identity_platform.google_provider_enabled(
            project_id="project-1",
            access_token="access-token",
            session=unavailable_session,
        )


# @matrix login : action-codes authentication-email identity-platform
def test_generate_email_action_code_returns_provider_code_without_sending():
    session = FakeSession([FakeResponse({"oobCode": "reset-code"})])

    assert (
        identity_platform.generate_email_action_code(
            "PASSWORD_RESET",
            "USER@example.test",
            user_ip="203.0.113.1",
            project_id="project-1",
            access_token="access-token",
            session=session,
        )
        == "reset-code"
    )
    url, request = session.calls[0]
    assert url.endswith("/projects/project-1/accounts:sendOobCode")
    assert request["headers"]["Authorization"] == "Bearer access-token"
    assert request["json"] == {
        "requestType": "PASSWORD_RESET",
        "email": "user@example.test",
        "returnOobLink": True,
        "userIp": "203.0.113.1",
    }
    assert request["timeout"] == identity_platform.IDENTITY_REQUEST_TIMEOUT


# @matrix login : account-enumeration authentication-email availability smtp
def test_auth_email_connection_preflight_is_address_independent():
    config = {
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
    FakeSMTP.instances.clear()
    tls_context = object()

    assert auth_email.check_auth_email_connection(
        config=config,
        smtp_factory=FakeSMTP,
        tls_context=tls_context,
    )
    available = FakeSMTP.instances[0]
    assert available.started_tls is tls_context
    assert available.credentials == ("resend", "provider-key")
    assert available.message is None

    with pytest.raises(auth_email.AuthEmailError, match="SMTP service rejected"):
        auth_email.check_auth_email_connection(
            config=config,
            smtp_factory=RejectedSMTP,
            tls_context=tls_context,
        )


# @matrix login : authentication-email smtp tls
def test_send_auth_email_supports_generic_smtp_transports():
    FakeSMTP.instances.clear()
    tls_context = object()

    assert auth_email.send_auth_email(
        "user@example.test",
        "Verify",
        "Plain text",
        "<p>HTML</p>",
        config={
            "provider": "smtp",
            "service": "Resend",
            "host": "smtp.resend.test",
            "port": 587,
            "security": "starttls",
            "username": "resend",
            "password": "provider-key",
            "senderEmail": "sender@example.test",
            "senderName": "Demo",
        },
        smtp_factory=FakeSMTP,
        tls_context=tls_context,
    )
    starttls = FakeSMTP.instances[0]
    assert (starttls.host, starttls.port) == ("smtp.resend.test", 587)
    assert starttls.started_tls is tls_context
    assert starttls.credentials == ("resend", "provider-key")
    assert starttls.message["To"] == "user@example.test"
    assert starttls.message["From"] == "Demo <sender@example.test>"

    assert auth_email.send_auth_email(
        "user@example.test",
        "Verify",
        "Plain text",
        "<p>HTML</p>",
        config={
            "provider": "smtp",
            "service": "Postmark",
            "host": "smtp.postmark.test",
            "port": 465,
            "security": "ssl",
            "username": "server-token",
            "password": "server-token",
            "senderEmail": "sender@example.test",
            "senderName": "Demo",
        },
        smtp_ssl_factory=FakeSMTP,
        tls_context=tls_context,
    )
    implicit_tls = FakeSMTP.instances[1]
    assert implicit_tls.context is tls_context
    assert implicit_tls.started_tls is None


# @matrix login : action-link authentication-email templates
def test_auth_action_message_escapes_content_and_links():
    subject, text_body, html_body = auth_email.auth_action_message(
        "verifyEmail",
        "Demo & Test",
        'https://demo.example/users/login?oobCode=a&next="bad"',
    )

    assert subject == "Verify your email for Demo & Test"
    assert "https://demo.example/users/login" in text_body
    assert "Demo &amp; Test" in html_body
    assert "a&amp;next=&quot;bad&quot;" in html_body


# @matrix users : account-delete identity-platform
def test_delete_account_by_email_looks_up_and_deletes_identity_user():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "users": [
                        {
                            "localId": "identity-user-1",
                            "email": "user@example.test",
                        }
                    ]
                }
            ),
            FakeResponse({}),
        ]
    )

    assert identity_platform.delete_account_by_email(
        "USER@example.test",
        project_id="project-1",
        access_token="access-token",
        session=session,
    )
    lookup_url, lookup = session.calls[0]
    delete_url, delete = session.calls[1]
    assert lookup_url.endswith("/projects/project-1/accounts:lookup")
    assert lookup["json"] == {"email": ["user@example.test"]}
    assert delete_url.endswith("/projects/project-1/accounts:delete")
    assert delete["json"] == {"localId": "identity-user-1"}
    assert delete["headers"]["Authorization"] == "Bearer access-token"
