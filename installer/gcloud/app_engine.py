"""Discover or create the App Engine application in its permanent location."""

from __future__ import annotations

from typing import TYPE_CHECKING

from installer import FORMATTER, wrap_text
from installer.errors import (
    ProviderConflict,
    ProviderNotFound,
    ProviderTimeout,
    ProviderTransientError,
    SetupCancelled,
    classify_provider_error,
    retry_provider_call,
)
from installer.package_install import install_if_missing
from installer.state import record_mutation
from runner import presentation as ui
from runner.console import format_prompt
from runner.presentation import output as print, read_input as input

if TYPE_CHECKING:
    from google.cloud.appengine_admin_v1 import Application

APP_ENGINE_RPC_TIMEOUT = 60
APP_ENGINE_CREATE_TIMEOUT = 300


def create_app_engine_app(*, confirm: bool = True) -> Application:
    """Get the immutable App Engine application or create it after confirmation."""
    from config import SETTINGS
    from config.locations import normalize_app_engine_location

    f = FORMATTER.initialize()

    install_if_missing(
        "google.cloud.appengine_admin_v1",
        "Google App Engine Admin API",
        package_name="google-cloud-appengine-admin",
    )
    install_if_missing(
        "google.api_core", "Google API Core", package_name="google-api-core"
    )
    from google.cloud import appengine_admin_v1

    project_id = str(SETTINGS.GCLOUD_CONFIG["PROJECT"])
    location = normalize_app_engine_location(
        SETTINGS.APP["APP_ENGINE_LOCATION"]
    )

    client = appengine_admin_v1.ApplicationsClient()
    with f.progress(
        text="Discover App Engine application",
        success_text='App Engine application found',
    ) as sp:
        try:
            application = retry_provider_call(
                lambda: client.get_application(
                    request={"name": f"apps/{project_id}"},
                    timeout=APP_ENGINE_RPC_TIMEOUT,
                ),
                description=f"Discover App Engine application {project_id}",
            )
            record_mutation(
                "reconcile App Engine",
                action="existing",
                resource="app-engine-application",
                identifier=project_id,
            )
            sp.ok()
            return application
        except ProviderNotFound:
            pass

    print(
        f.warning(
            wrap_text(
                "App Engine location is permanent and cannot be changed after "
                f"creation. Selected location: {location}"
            )
        )
    )
    print(
        f.info(
            wrap_text("Creating the App Engine application may take up to 5 minutes.")
        )
    )
    if confirm:
        try:
            confirmation = input(
                format_prompt(
                    f"Create the App Engine application in '{location}'? [y/N]: "
                )
            )
        except EOFError as error:
            message = (
                "App Engine confirmation could not read from this terminal. "
                "Run setup again in an interactive terminal."
            )
            print(f.error(message))
            raise SetupCancelled(message) from error
        if confirmation.strip().lower() not in ("y", "yes"):
            print(ui.status(wrap_text("App Engine application creation cancelled.")))
            raise SetupCancelled("App Engine application creation was cancelled.")

    with f.progress(
        text="Create App Engine application (may take up to 5 minutes)",
        success_text='App Engine application created',
    ) as sp:
        application_to_create = appengine_admin_v1.Application()
        application_to_create.id = project_id
        application_to_create.location_id = location

        try:
            operation = client.create_application(
                request={"application": application_to_create},
                timeout=APP_ENGINE_RPC_TIMEOUT,
            )
            created_app = operation.result(timeout=APP_ENGINE_CREATE_TIMEOUT)
            record_mutation(
                "reconcile App Engine",
                action="created",
                resource="app-engine-application",
                identifier=project_id,
            )

            if created_app is None:
                raise RuntimeError("App Engine creation did not return an application.")
            sp.ok(f"App Engine application created in {created_app.location_id}")
            return created_app
        except Exception as e:
            classified = classify_provider_error(
                e,
                message=f"Failed to create the App Engine application: {e}",
            )
            if isinstance(classified, ProviderTimeout):
                message = (
                    "App Engine provisioning did not finish within the "
                    "5-minute setup window. Google may still be completing it. "
                    "Run setup again; it will discover and reuse the application "
                    "if creation finished."
                )
                sp.write(f.error(message))
                sp.fail()
                raise type(classified)(message) from e
            if isinstance(classified, ProviderTransientError):
                message = (
                    "Google returned a temporary error while provisioning App "
                    "Engine, so the final provider state is not yet known. Run "
                    "setup again; it will discover and reuse the application if "
                    "creation finished."
                )
                sp.write(f.error(message))
                sp.fail()
                raise type(classified)(message) from e
            if isinstance(classified, ProviderConflict):
                message = (
                    "Google reports that App Engine already exists or another "
                    "creation request won the race. Run setup again so it can "
                    "discover and reuse the provider application."
                )
                sp.write(f.error(message))
                sp.fail()
                raise ProviderConflict(message) from e
            sp.write(f.error(str(classified)))
            sp.fail()
            raise classified from e
