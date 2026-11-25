"""Provision Google Cloud resources for a Lagniappe installation."""

from __future__ import annotations

from contextlib import suppress
from importlib import reload as _reload
import re
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING
import webbrowser

from config import constants
from installer import FORMATTER, wrap_text
from installer import iam as iam_access
from installer.commands import run_gcloud_command
from installer.errors import (
    ProviderConflict,
    ProviderInvalidInput,
    ProviderNotFound,
    ProviderTimeout,
    ProviderTransientError,
    SetupCancelled,
    classify_provider_error,
    google_service_terms_error,
    retry_provider_call,
)
from installer.package_install import install_if_missing
from installer.state import record_mutation
from runner import presentation as ui
from runner.console import format_prompt
from runner.presentation import output as print, read_input as input

from . import accounts, app_engine, jobs, ocr, services, storage

if TYPE_CHECKING:
    from .app_engine import Application as Application

# The running installer reloads this package after replacing the checkout.
# reload() retains the previous export list. Refresh services first because
# accounts and storage import its retry settings.
if "__all__" in globals():
    for _resource in (services, accounts, app_engine, jobs, ocr, storage):
        _reload(_resource)

GCLOUD_SERVICE_DISCOVERY_TIMEOUT = services.GCLOUD_SERVICE_DISCOVERY_TIMEOUT
GCLOUD_SERVICE_ENABLE_TIMEOUT = services.GCLOUD_SERVICE_ENABLE_TIMEOUT
GCLOUD_API_PROPAGATION_ATTEMPTS = services.GCLOUD_API_PROPAGATION_ATTEMPTS
GCLOUD_API_PROPAGATION_DELAYS = services.GCLOUD_API_PROPAGATION_DELAYS
APP_ENGINE_RPC_TIMEOUT = app_engine.APP_ENGINE_RPC_TIMEOUT
APP_ENGINE_CREATE_TIMEOUT = app_engine.APP_ENGINE_CREATE_TIMEOUT

_guide_google_service_terms_acceptance = services._guide_google_service_terms_acceptance
_enabled_google_cloud_apis = services._enabled_google_cloud_apis
enable_gcloud_apis = services.enable_gcloud_apis
configure_service_account = accounts.configure_service_account
create_app_engine_app = app_engine.create_app_engine_app
configure_storage_buckets = storage.configure_storage_buckets
configure_data_protection = storage.configure_data_protection
create_task_queue = jobs.create_task_queue
create_deferred_job_reconciler = jobs.create_deferred_job_reconciler
create_ocr_processor = ocr.create_ocr_processor

__all__ = [
    "APP_ENGINE_CREATE_TIMEOUT",
    "APP_ENGINE_RPC_TIMEOUT",
    "GCLOUD_API_PROPAGATION_ATTEMPTS",
    "GCLOUD_API_PROPAGATION_DELAYS",
    "GCLOUD_SERVICE_DISCOVERY_TIMEOUT",
    "GCLOUD_SERVICE_ENABLE_TIMEOUT",
    "configure_data_protection",
    "configure_service_account",
    "configure_storage_buckets",
    "create_app_engine_app",
    "create_deferred_job_reconciler",
    "create_ocr_processor",
    "create_task_queue",
    "enable_gcloud_apis",
    "setup_app_engine",
    # The original module also exposed these imports to callers.
    "FORMATTER",
    "ProviderConflict",
    "ProviderInvalidInput",
    "ProviderNotFound",
    "ProviderTimeout",
    "ProviderTransientError",
    "SetupCancelled",
    "SimpleNamespace",
    "TYPE_CHECKING",
    "annotations",
    "classify_provider_error",
    "constants",
    "format_prompt",
    "google_service_terms_error",
    "iam_access",
    "input",
    "install_if_missing",
    "print",
    "re",
    "record_mutation",
    "retry_provider_call",
    "run_gcloud_command",
    "suppress",
    "time",
    "ui",
    "webbrowser",
    "wrap_text",
]


def setup_app_engine(*, confirm: bool = True) -> None:
    """Configure App Engine and service account."""
    from config import SETTINGS

    identity = configure_service_account()

    settings_changed = False
    runtime_email = identity.get("client_email")
    if SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") != runtime_email:
        SETTINGS.APP["RUNTIME_SERVICE_ACCOUNT_EMAIL"] = runtime_email
        settings_changed = True
    if (
        SETTINGS.APP.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL")
        != runtime_email
    ):
        SETTINGS.APP["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"] = runtime_email
        settings_changed = True
    if SETTINGS.DEPLOY.get("service_account") != runtime_email:
        SETTINGS.DEPLOY["service_account"] = runtime_email
        settings_changed = True
    from config.secrets import DEFAULT_RUNTIME_SECRET_NAME, uses_secret_manager

    if uses_secret_manager(SETTINGS.APP) and runtime_email:
        from installer.secrets import ensure_runtime_secrets_infrastructure

        ensure_runtime_secrets_infrastructure(
            str(SETTINGS.GCLOUD_CONFIG["PROJECT"]),
            str(runtime_email),
            secret_name=str(
                SETTINGS.APP.get("SECRETS_SECRET_NAME") or DEFAULT_RUNTIME_SECRET_NAME
            ),
        )
    if settings_changed:
        SETTINGS.save()

    application = (
        create_app_engine_app() if confirm else create_app_engine_app(confirm=False)
    )
    location = str(getattr(application, "location_id", "") or "").strip()
    hostname = str(getattr(application, "default_hostname", "") or "").strip()
    if not location or not hostname:
        raise RuntimeError(
            "App Engine returned an application without locationId or "
            "defaultHostname; setup will not guess immutable provider state."
        )
    SETTINGS.APP["APP_ENGINE_LOCATION"] = location
    SETTINGS.APP["APP_URL"] = f"https://{hostname}"
    if not SETTINGS.APP.get("CUSTOM_DOMAIN"):
        SETTINGS.APP["GOOGLE_LOGIN_URI"] = (
            f"https://{hostname}/users/google-signin"
        )
    SETTINGS.save()
