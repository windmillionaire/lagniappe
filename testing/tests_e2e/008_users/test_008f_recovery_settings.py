from types import SimpleNamespace

from flask import Flask
import pytest
from werkzeug.exceptions import ServiceUnavailable
import yaml

from config import recovery
from lagniappe.web import responses
from lagniappe.web.routes.reference import main as reference


pytestmark = pytest.mark.e2e


@pytest.fixture
def route_app():
    app = Flask(__name__)
    app.testing = True
    return app


def _persisted_settings():
    return {
        "CONFIG_KIND": recovery.CONFIG_KIND,
        "CONFIG_SCHEMA_VERSION": recovery.CONFIG_SCHEMA_VERSION,
        "APP_NAME": "My Custom Installation",
        "GOOGLE_CLOUD_PROJECT": "recovered-project-1",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
            "runtime@recovered-project-1.iam.gserviceaccount.com"
        ),
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
            "runtime@recovered-project-1.iam.gserviceaccount.com"
        ),
        "AUTH_EMAIL_CONFIG": {
            "provider": "smtp",
            "service": "Resend",
            "host": "smtp.resend.com",
            "port": 465,
            "security": "ssl",
            "username": "resend",
            "password": "smtp-secret",
            "senderEmail": "noreply@example.test",
            "senderName": "My Custom Installation",
        },
        "FIREBASE_CONFIG": {
            "apiKey": "firebase-secret",
            "appId": "firebase-app-1",
            "messagingSenderId": "123456789",
            "projectId": "recovered-project-1",
            "vapidKey": "firebase-vapid-key",
        },
        "IDENTITY_PLATFORM_CONFIG": {
            "apiKey": "identity-api-key",
            "projectId": "recovered-project-1",
        },
        "SENTRY_AUTH_TOKEN": "sentry-secret",
        "SECRET_KEY": "application-secret",
        "DEPLOY_MAX_INSTANCES": "1",
        "AI_MODEL": "persisted-model",
        "REDIS_TLS": False,
    }


# @features admin
# @dimensions recovery-export secrets web-headers
def test_owner_download_is_complete_canonical_and_not_cacheable(
    route_app,
    monkeypatch,
    caplog,
):
    persisted = _persisted_settings()
    monkeypatch.setattr(
        reference,
        "SETTINGS",
        SimpleNamespace(app_settings=persisted),
    )
    monkeypatch.setattr(
        reference.database.get,
        "site_deployment",
        lambda: {"DEPLOY_MAX_INSTANCES": "4", "version": 2},
    )
    monkeypatch.setattr(
        reference.database.get,
        "site_ai",
        lambda: {"AI_MODEL": "live-model", "version": 3},
    )

    with route_app.test_request_context("/reference/download-settings"):
        response, status = reference.download_settings.__wrapped__()

    downloaded = yaml.safe_load(response.get_data(as_text=True))
    assert status == 200
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="lagniappe_settings.yaml"'
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.mimetype == "application/yaml"
    assert downloaded["APP_NAME"] == "My Custom Installation"
    assert downloaded["CONFIG_KIND"] == recovery.CONFIG_KIND
    assert downloaded["CONFIG_SCHEMA_VERSION"] == recovery.CONFIG_SCHEMA_VERSION
    assert downloaded["RUNTIME_SERVICE_ACCOUNT_EMAIL"] == (
        "runtime@recovered-project-1.iam.gserviceaccount.com"
    )
    assert downloaded["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] == (
        "runtime@recovered-project-1.iam.gserviceaccount.com"
    )
    assert downloaded["SENTRY_AUTH_TOKEN"] == "sentry-secret"
    assert downloaded["DEPLOY_MAX_INSTANCES"] == "4"
    assert downloaded["AI_MODEL"] == "live-model"
    assert "smtp-secret" not in caplog.text
    assert "sentry-secret" not in caplog.text


# @features admin
# @dimensions configuration-display secrets
def test_inline_configuration_redacts_secrets(route_app, monkeypatch):
    rendered = []

    def render(template, **context):
        rendered.append((template, context))
        return context["environment_variables"]

    monkeypatch.setattr(responses, "render_template", render)
    settings = _persisted_settings()

    with route_app.test_request_context("/reference/environment-variables"):
        html, status = responses.reference_environment_variables(settings)
    with route_app.test_request_context("/site-configuration"):
        modal, modal_status = responses.site_configuration(settings)

    assert status == modal_status == 200
    assert "application-secret" not in html
    assert "smtp-secret" not in html
    assert "firebase-secret" not in html
    assert "sentry-secret" not in html
    assert recovery.REDACTED_VALUE in html
    assert "application-secret" not in modal
    assert "smtp-secret" not in modal
    assert "firebase-secret" not in modal
    assert [template for template, _ in rendered] == [
        "reference/env_variables.html",
        "reference/site_configuration.html",
    ]
    assert settings["SECRET_KEY"] == "application-secret"


# @features admin
# @dimensions recovery-export failure-isolation
def test_owner_download_fails_closed_when_live_settings_are_unavailable(
    route_app,
    monkeypatch,
    caplog,
):
    persisted = _persisted_settings()
    monkeypatch.setattr(
        reference,
        "SETTINGS",
        SimpleNamespace(app_settings=persisted),
    )
    monkeypatch.setattr(
        reference.database.get,
        "site_deployment",
        lambda: (_ for _ in ()).throw(ConnectionError("provider unavailable")),
    )

    with route_app.test_request_context("/reference/download-settings"):
        with pytest.raises(ServiceUnavailable) as error:
            reference.download_settings.__wrapped__()

    assert error.value.code == 503
    assert "No settings were downloaded" in error.value.description
    assert "application-secret" not in error.value.description
    assert "application-secret" not in caplog.text
