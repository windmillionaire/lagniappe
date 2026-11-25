"""Enable required Google Cloud APIs and guide service agreement acceptance."""

from __future__ import annotations

from contextlib import suppress
import time
import webbrowser

from config import constants
from installer import FORMATTER, wrap_text
from installer.commands import run_gcloud_command
from installer.errors import (
    ProviderTransientError,
    SetupCancelled,
    classify_provider_error,
    google_service_terms_error,
    retry_provider_call,
)
from installer.state import record_mutation
from runner import presentation as ui
from runner.console import format_prompt
from runner.presentation import output as print, read_input as input

GCLOUD_SERVICE_DISCOVERY_TIMEOUT = 60
GCLOUD_SERVICE_ENABLE_TIMEOUT = 300
GCLOUD_API_PROPAGATION_ATTEMPTS = 8
GCLOUD_API_PROPAGATION_DELAYS = (2, 4, 8, 15, 20, 30, 30)


def _guide_google_service_terms_acceptance(
    terms_error,
    *,
    account,
    owner_email,
    spinner,
):
    """Pause API activation for account-scoped Google terms acceptance."""
    FORMATTER.initialize()
    selected_account = str(account or "").strip()
    permanent_owner = str(owner_email or "").strip()
    delegated_maps = (
        terms_error.terms_id == "maps"
        and selected_account
        and permanent_owner
        and selected_account.casefold() != permanent_owner.casefold()
    )
    agreement_name = {
        "cloud": "Google Cloud service agreement",
        "maps": "Google Maps Platform agreement",
    }.get(
        terms_error.terms_id,
        f"Google service agreement '{terms_error.terms_id}'",
    )

    spinner.stop()
    try:
        print()
        print(
            wrap_text(

                    "Google requires the active setup account '"
                    f"{ui.literal(selected_account)}' to complete the "
                    f"{ui.literal(agreement_name)}."

            )
        )
        if delegated_maps:
            print(
                wrap_text(

                        f"Permanent Owner '{ui.literal(permanent_owner)}' must first review "
                        "the Google Maps Platform agreement and authorize the temporary "
                        "installer to acknowledge it with the business-controlled installer "
                        "account. The Owner does not need to enable Places API manually; "
                        "setup will retry and enable it."

                )
            )
        print(
            wrap_text(

                    "The terms page may first show Google Cloud's welcome agreement. "
                    "Complete every agreement it presents, and confirm the browser profile "
                    f"is '{ui.literal(selected_account)}'."

            )
        )
        print(
            ui.value(
                "Terms page",
                terms_error.terms_url,
                action=True,
                verbatim=True,
                standalone=True,
            )
        )
        with suppress(webbrowser.Error):
            webbrowser.open_new_tab(terms_error.terms_url)
        answer = input(
            format_prompt("Complete the agreement", hint="Enter to retry API activation; x to cancel")
        )
        if answer.strip().casefold() == "x":
            raise SetupCancelled(
                "Setup cancelled during Google service-terms acceptance."
            )
    finally:
        spinner.start()


def _enabled_google_cloud_apis(project_id):
    result = run_gcloud_command(
        [
            "services",
            "list",
            "--enabled",
            f"--project={project_id}",
            "--format=value(config.name)",
        ],
        timeout=GCLOUD_SERVICE_DISCOVERY_TIMEOUT,
    )
    return {
        value.strip()
        for value in result.stdout.splitlines()
        if value.strip()
    }


def enable_gcloud_apis() -> bool:
    """Enable only APIs missing from the confirmed target preflight."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    required_apis = constants.REQUIRED_GOOGLE_CLOUD_APIS

    feedback_text = ui.info("Enabling required Google Cloud APIs")
    project_id = str(SETTINGS.GCLOUD_CONFIG["PROJECT"])
    enabled_apis = getattr(
        SETTINGS,
        "_SETUP_ENABLED_GOOGLE_CLOUD_APIS",
        None,
    )
    with f.progress(
        text=feedback_text, success_text="Required Google Cloud APIs verified"
    ) as sp:
        if enabled_apis is None:
            result = retry_provider_call(
                lambda: _enabled_google_cloud_apis(project_id),
                description="List enabled Google Cloud APIs",
            )
            enabled_apis = set(result)

        missing_apis = sorted(set(required_apis) - set(enabled_apis))
        if missing_apis:
            sp.write(
                f.info(
                    wrap_text("Enabling Google Cloud APIs may take up to 5 minutes...")
                )
            )
            guided_terms = set()

            def enable_missing_services():
                while True:
                    result = run_gcloud_command(
                        [
                            "services",
                            "enable",
                            *missing_apis,
                            f"--project={project_id}",
                        ],
                        check=False,
                        timeout=GCLOUD_SERVICE_ENABLE_TIMEOUT,
                    )
                    if result.returncode == 0:
                        return result
                    detail = (result.stderr or result.stdout or "").strip()
                    terms_error = google_service_terms_error(
                        detail,
                        account=str(SETTINGS.GCLOUD_CONFIG.get("ACCOUNT") or ""),
                    )
                    if terms_error is not None:
                        if terms_error.terms_id in guided_terms:
                            raise terms_error
                        _guide_google_service_terms_acceptance(
                            terms_error,
                            account=str(SETTINGS.GCLOUD_CONFIG.get("ACCOUNT") or ""),
                            owner_email=SETTINGS.APP.get("ADMIN_EMAIL"),
                            spinner=sp,
                        )
                        guided_terms.add(terms_error.terms_id)
                        continue
                    raise classify_provider_error(
                        RuntimeError(detail or "gcloud services enable failed"),
                        message=(
                            "gcloud services enable failed: "
                            f"{detail or 'provider returned no detail'}"
                        ),
                    )

            retry_provider_call(
                enable_missing_services,
                description="Enable required Google Cloud APIs",
            )
            for service_name in missing_apis:
                record_mutation(
                    "enable Google Cloud APIs",
                    action="enabled",
                    resource="provider-api",
                    identifier=service_name,
                )

            def verify_enabled_services():
                discovered = _enabled_google_cloud_apis(project_id)
                pending = sorted(set(required_apis) - discovered)
                if pending:
                    raise ProviderTransientError(
                        "Required Google Cloud APIs are still propagating: "
                        + ", ".join(pending)
                    )
                return discovered

            def wait_for_services(delay):
                sp.write(
                    f.info(
                        "Google Cloud APIs are still becoming available; "
                        f"retrying in {delay} seconds..."
                    )
                )
                time.sleep(delay)

            enabled_apis = retry_provider_call(
                verify_enabled_services,
                description="Verify required Google Cloud APIs",
                attempts=GCLOUD_API_PROPAGATION_ATTEMPTS,
                delays=GCLOUD_API_PROPAGATION_DELAYS,
                sleep=wait_for_services,
            )

        SETTINGS._SETUP_ENABLED_GOOGLE_CLOUD_APIS = set(enabled_apis)
        sp.ok()
    return True
