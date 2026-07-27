from io import BytesIO
from types import SimpleNamespace

import pytest
from flask import Flask

from config.constants import DEFAULT_DEPLOYMENT_SETTINGS
from config.ai_models import AI_PRICING_URL
from lagniappe.web.routes.home import site

pytestmark = pytest.mark.e2e


@pytest.fixture
def route_app():
    app = Flask(__name__)
    app.testing = True
    return app


# @features admin
# @dimensions deployment-settings config route
def test_site_settings_loads_deployment_defaults_from_config(monkeypatch):
    config = SimpleNamespace(
        DEPLOY_SCALING_TYPE="automatic",
        DEPLOY_WORKER_COUNT="5",
        DEPLOY_INSTANCE_CLASS="F4",
        DEPLOY_MAX_INSTANCES="3",
        DEPLOY_MIN_IDLE_INSTANCES="1",
        DEPLOY_IDLE_TIMEOUT="10m",
    )
    monkeypatch.setattr(site, "CONFIG", config)
    monkeypatch.setattr(site.database.get, "site_deployment", lambda: None)

    deployment = site._deployment_settings()

    assert deployment == {
        "DEPLOY_SCALING_TYPE": "automatic",
        "DEPLOY_WORKER_COUNT": "5",
        "DEPLOY_INSTANCE_CLASS": "F4",
        "DEPLOY_MAX_INSTANCES": "3",
        "DEPLOY_MIN_IDLE_INSTANCES": "1",
        "DEPLOY_IDLE_TIMEOUT": "10m",
    }
    assert DEFAULT_DEPLOYMENT_SETTINGS["DEPLOY_SCALING_TYPE"] == "basic"
    assert DEFAULT_DEPLOYMENT_SETTINGS["DEPLOY_WORKER_COUNT"] == "3"


def _ai_test_config():
    return SimpleNamespace(
        GOOGLE_CLOUD_PROJECT="demo-project",
        AI_MODEL="gemini-3.5-flash",
        AI_UTILITY_MODEL="gemini-3.1-flash-lite",
        AI_IMAGE_MODEL="gemini-3.1-flash-image",
        AI_LOCATION="global",
        CLOUDFLARE_ACCOUNT_ID=None,
        CUSTOM_DOMAIN=None,
        google_credentials=None,
    )


def _ai_model_options():
    return {
        "pricing_url": AI_PRICING_URL,
        "text": [
            {
                "id": "gemini-3.5-flash",
                "label": "Gemini 3.5 Flash",
                "kind": "text",
            },
            {
                "id": "gemini-3.1-flash-lite",
                "label": "Gemini 3.1 Flash-Lite",
                "kind": "text",
            },
        ],
        "image": [
            {
                "id": "gemini-3.1-flash-image",
                "label": "Gemini 3.1 Flash Image",
                "kind": "image",
            }
        ],
    }


# @features admin
# @dimensions site-update audit success failure pending running
def test_site_update_returns_migration_report_and_failure_status(
    route_app, monkeypatch
):
    reports = iter(
        [
            {
                "status": "current",
                "updates_available": False,
                "counts": {"complete": 1},
            },
            {
                "status": "current",
                "updates_available": False,
                "counts": {"complete": 2},
            },
            {
                "status": "failed",
                "updates_available": True,
                "counts": {"failed": 1},
            },
            {
                "status": "running",
                "updates_available": True,
                "counts": {"running": 1},
            },
        ]
    )
    monkeypatch.setattr(
        site.database_migrations,
        "run_data_migrations",
        lambda: next(reports),
    )

    with route_app.test_request_context("/site-update", method="POST"):
        response, status = site.site_update.__wrapped__()
    assert status == 200
    assert response.get_json()["migration_status"]["status"] == "current"

    with route_app.test_request_context("/site-update", method="POST"):
        response, status = site.site_update.__wrapped__()
    assert status == 200
    assert response.get_json()["migration_status"]["counts"] == {"complete": 2}

    with route_app.test_request_context("/site-update", method="POST"):
        response, status = site.site_update.__wrapped__()
    assert status == 409
    assert response.get_json()["migration_status"]["counts"] == {"failed": 1}

    with route_app.test_request_context("/site-update", method="POST"):
        response, status = site.site_update.__wrapped__()
    assert status == 409
    assert response.get_json()["migration_status"]["status"] == "running"


# @features cache
# @dimensions migration-gate current pending
def test_rebuild_cache_requires_current_migrations(route_app, monkeypatch):
    reports = iter(
        [
            {
                "status": "pending",
                "cache_refresh_allowed": False,
                "counts": {"pending": 1},
            },
            {
                "status": "current",
                "cache_refresh_allowed": True,
                "counts": {"complete": 1},
            },
        ]
    )
    cache_deletions = []
    monkeypatch.setattr(
        site.database_migrations,
        "get_migration_status",
        lambda: next(reports),
    )
    monkeypatch.setattr(site.cache, "delete_cache", lambda: cache_deletions.append(True))
    monkeypatch.setattr(site.database.get, "all_models", lambda: iter(()))
    monkeypatch.setattr(site.database.get, "all_instances", lambda: iter(()))
    monkeypatch.setattr(site.database.get, "all_files", lambda: iter(()))
    monkeypatch.setattr(site.database.get, "all_users", lambda: iter(()))

    with route_app.test_request_context("/rebuild-cache", method="POST"):
        response, status = site.rebuild_cache.__wrapped__()
    assert status == 409
    assert response.get_json()["migration_status"]["status"] == "pending"
    assert cache_deletions == []

    with route_app.test_request_context("/rebuild-cache", method="POST"):
        response, status = site.rebuild_cache.__wrapped__()
    assert status == 200
    assert response == ""
    assert cache_deletions == [True]


# @features admin
# @dimensions ai-settings config metadata route
def test_site_settings_loads_ai_settings_and_options(route_app, monkeypatch):
    monkeypatch.setattr(site, "CONFIG", _ai_test_config())
    monkeypatch.setattr(site.database.get, "site_image", lambda: None)
    monkeypatch.setattr(site.database.get, "site_deployment", lambda: None)
    monkeypatch.setattr(
        site.database.get,
        "site_ai",
        lambda: {
            "AI_MODEL": "gemini-3.5-flash",
            "AI_UTILITY_MODEL": "gemini-3.1-flash-lite",
            "AI_IMAGE_MODEL": "gemini-3.1-flash-image",
            "AI_LOCATION": "global",
        },
    )
    monkeypatch.setattr(
        site,
        "discover_model_options",
        lambda **_kwargs: _ai_model_options(),
    )
    monkeypatch.setattr(
        site.database_migrations,
        "get_migration_status",
        lambda: {
            "status": "pending",
            "current_version": "0.1",
            "updates_available": True,
            "cache_refresh_allowed": False,
            "counts": {"pending": 1},
            "migrations": [],
        },
    )

    with route_app.test_request_context("/site-settings", method="GET"):
        response, status = site.site_settings.__wrapped__()

    data = response.get_json()
    assert status == 200
    assert data["ai_settings"] == {
        "AI_MODEL": "gemini-3.5-flash",
        "AI_UTILITY_MODEL": "gemini-3.1-flash-lite",
        "AI_IMAGE_MODEL": "gemini-3.1-flash-image",
        "AI_LOCATION": "global",
    }
    assert data["ai_model_options"]["pricing_url"] == AI_PRICING_URL
    assert [option["id"] for option in data["ai_model_options"]["text"]] == [
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    ]
    assert data["migration_status"]["status"] == "pending"


# @features admin
# @dimensions ai-settings validation route
def test_set_ai_settings_saves_valid_payload(route_app, monkeypatch):
    saved = []

    monkeypatch.setattr(site, "CONFIG", _ai_test_config())
    monkeypatch.setattr(site.database.get, "site_ai", lambda: None)
    monkeypatch.setattr(
        site,
        "discover_model_options",
        lambda **_kwargs: _ai_model_options(),
    )
    monkeypatch.setattr(site.database, "save_site_ai", lambda data: saved.append(data))

    payload = {
        "AI_MODEL": "gemini-3.5-flash",
        "AI_UTILITY_MODEL": "gemini-3.1-flash-lite",
        "AI_IMAGE_MODEL": "gemini-3.1-flash-image",
        "AI_LOCATION": "global",
    }
    with route_app.test_request_context(
        "/set-ai-settings",
        method="POST",
        data=payload,
    ):
        response, status = site.set_ai_settings.__wrapped__()

    assert status == 200
    assert response.get_json()["ai_settings"] == payload
    assert saved == [payload]


# @features admin
# @dimensions ai-settings validation route
@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "AI_MODEL": "not-a-real-model",
                "AI_UTILITY_MODEL": "gemini-3.1-flash-lite",
                "AI_IMAGE_MODEL": "gemini-3.1-flash-image",
                "AI_LOCATION": "global",
            },
            "Primary model",
        ),
        (
            {
                "AI_MODEL": "gemini-3.5-flash",
                "AI_UTILITY_MODEL": "gemini-3.1-flash-lite",
                "AI_IMAGE_MODEL": "gemini-3.1-flash-image",
                "AI_LOCATION": "us-central1",
            },
            "global",
        ),
    ],
    ids=["invalid-model", "invalid-location"],
)
def test_set_ai_settings_rejects_invalid_payloads(
    route_app,
    monkeypatch,
    payload,
    message,
):
    def save_site_ai(_ai_settings):
        raise AssertionError("invalid AI settings should not be saved")

    monkeypatch.setattr(site, "CONFIG", _ai_test_config())
    monkeypatch.setattr(site.database.get, "site_ai", lambda: None)
    monkeypatch.setattr(
        site,
        "discover_model_options",
        lambda **_kwargs: _ai_model_options(),
    )
    monkeypatch.setattr(site.database, "save_site_ai", save_site_ai)

    with route_app.test_request_context(
        "/set-ai-settings",
        method="POST",
        data=payload,
    ):
        response, status = site.set_ai_settings.__wrapped__()

    assert status == 422
    assert message in response


# @features admin
# @dimensions deployment-settings validation route
@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "DEPLOY_SCALING_TYPE": "manual",
                "DEPLOY_WORKER_COUNT": "2",
                "DEPLOY_INSTANCE_CLASS": "F2",
                "DEPLOY_MAX_INSTANCES": "1",
                "DEPLOY_MIN_IDLE_INSTANCES": "0",
            },
            "Scaling type",
        ),
        (
            {
                "DEPLOY_SCALING_TYPE": "automatic",
                "DEPLOY_WORKER_COUNT": "0",
                "DEPLOY_INSTANCE_CLASS": "F2",
                "DEPLOY_MAX_INSTANCES": "1",
                "DEPLOY_MIN_IDLE_INSTANCES": "0",
            },
            "Worker count",
        ),
        (
            {
                "DEPLOY_SCALING_TYPE": "automatic",
                "DEPLOY_WORKER_COUNT": "2",
                "DEPLOY_INSTANCE_CLASS": "F2",
                "DEPLOY_MAX_INSTANCES": "0",
                "DEPLOY_MIN_IDLE_INSTANCES": "0",
            },
            "Instance count",
        ),
    ],
    ids=["invalid-scaling", "invalid-workers", "invalid-instances"],
)
def test_set_deployment_settings_rejects_invalid_payloads(
    route_app, monkeypatch, payload, message
):
    def save_site_deployment(_deployment):
        raise AssertionError("invalid deployment settings should not be saved")

    monkeypatch.setattr(site.database, "save_site_deployment", save_site_deployment)

    with route_app.test_request_context(
        "/set-deployment-settings",
        method="POST",
        data=payload,
    ):
        response, status = site.set_deployment_settings.__wrapped__()

    assert status == 422
    assert message in response


# @features admin
# @dimensions site-image-upload public-preview route
def test_set_site_image_returns_static_image_paths(route_app, monkeypatch):
    monkeypatch.setattr(
        site.site_image,
        "create_site_image",
        lambda _upload: {
            "version": 12,
            "apple-touch-icon.png": "apple-touch-icon.png",
            "logo-192x192.png": "logo-192x192.png",
        },
    )

    with route_app.test_request_context(
        "/set-site-image",
        method="POST",
        data={"site-image": (BytesIO(b"image"), "site-image.png")},
    ):
        response, status = site.set_site_image.__wrapped__()

    assert status == 200
    assert response.get_json()["site_image"] == {
        "apple-touch-icon.png": "/images/apple-touch-icon.png",
        "logo-192x192.png": "/images/logo-192x192.png",
    }
