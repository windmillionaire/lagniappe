"""Provision the runtime service account and reconcile its IAM policy."""

from __future__ import annotations

import re
import time

from installer import FORMATTER, wrap_text
from installer import iam as iam_access
from installer.errors import (
    ProviderInvalidInput,
    ProviderNotFound,
    ProviderTransientError,
    classify_provider_error,
    retry_provider_call,
)
from installer.package_install import install_if_missing
from installer.state import record_mutation
from runner.presentation import output as print

from .services import GCLOUD_API_PROPAGATION_ATTEMPTS, GCLOUD_API_PROPAGATION_DELAYS


def configure_service_account() -> dict[str, str]:
    """Create or update the explicit keyless runtime service account."""
    from config import SETTINGS

    f = FORMATTER.initialize()

    install_if_missing(
        "google.cloud.iam_admin_v1",
        "Google IAM Admin API",
        package_name="google-cloud-iam",
    )
    from google.cloud import iam_admin_v1
    from google.cloud.iam_admin_v1 import types as iam_types

    project_id = str(SETTINGS.GCLOUD_CONFIG["PROJECT"])
    project_name = SETTINGS.GCLOUD_CONFIG.get("NAME") or re.sub(
        r"[^a-z0-9]", "-", project_id.lower()
    )
    runtime_email = str(
        SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
        or f"{project_name}@{project_id}.iam.gserviceaccount.com"
    ).strip().casefold()
    if not runtime_email.endswith(
        f"@{project_id}.iam.gserviceaccount.com"
    ):
        raise RuntimeError(
            "RUNTIME_SERVICE_ACCOUNT_EMAIL must identify a service "
            "account in the configured Google Cloud project."
        )
    deployer_email = SETTINGS.APP.get(
        "DEPLOYER_EMAIL"
    ) or SETTINGS.GCLOUD_CONFIG.get("ACCOUNT")
    if not isinstance(deployer_email, str) or not deployer_email:
        raise RuntimeError("A deployer Google account is required.")

    iam_admin_client = iam_admin_v1.IAMClient()
    resource = f"projects/{project_id}"

    def retry_iam(operation, description):
        def wait_for_retry(delay):
            print(
                f.info(
                    "Google IAM is still becoming available; "
                    f"retrying in {delay} seconds..."
                )
            )
            time.sleep(delay)

        return retry_provider_call(
            operation,
            description=description,
            attempts=GCLOUD_API_PROPAGATION_ATTEMPTS,
            delays=GCLOUD_API_PROPAGATION_DELAYS,
            sleep=wait_for_retry,
        )

    def apply_iam_policy(email):
        iam_access.reconcile_runtime_project_policy(
            project_id,
            email,
        )
        iam_access.reconcile_runtime_service_account_policy(
            project_id,
            email,
            deployer_email,
        )

    name = f"projects/{project_id}/serviceAccounts/{runtime_email}"
    lookup = iam_types.GetServiceAccountRequest(name=name)
    try:
        account = retry_iam(
            lambda: iam_admin_client.get_service_account(request=lookup),
            f"Discover service account {name}",
        )
        record_mutation(
            "reconcile service account",
            action="existing",
            resource="service-account",
            identifier=account.email,
        )
    except ProviderTransientError as e:
        message = (
            "Google IAM is enabled but did not become ready in time. "
            "Run setup again to resume."
        )
        print(f.error(message))
        raise ProviderTransientError(message) from e
    except ProviderNotFound:
        try:
            request = iam_types.CreateServiceAccountRequest()
            request.account_id = runtime_email.split("@", 1)[0]
            request.name = resource

            new_service_account = iam_types.ServiceAccount()
            new_service_account.display_name = str(SETTINGS.APP["APP_NAME"])
            request.service_account = new_service_account

            account = retry_iam(
                lambda: iam_admin_client.create_service_account(request=request),
                f"Create service account {name}",
            )
            record_mutation(
                "reconcile service account",
                action="created",
                resource="service-account",
                identifier=account.email,
            )
        except Exception as e:
            classified = classify_provider_error(e)
            if isinstance(classified, ProviderTransientError):
                message = (
                    "Google IAM is enabled but did not become ready in "
                    "time. Run setup again to resume."
                )
                print(f.error(message))
                raise ProviderTransientError(message) from e
            print(f.error(wrap_text("Failed to create service account.")))
            raise classify_provider_error(
                e,
                message="Failed to create service account.",
            ) from e

    def wait_for_service_account(name):
        active, count = False, 0
        while not active:
            try:
                request = iam_types.GetServiceAccountRequest(name=name)
                iam_admin_client.get_service_account(request=request)
                break
            except Exception as e:
                count += 1
                if count > 9:
                    raise e
                time.sleep(1)

    def _is_sa_policy_propagation_error(error: Exception) -> bool:
        classified = classify_provider_error(error)
        if isinstance(classified, ProviderTransientError):
            return True
        if isinstance(classified, (ProviderInvalidInput, ProviderNotFound)):
            text = str(error).casefold()
            return any(
                marker in text
                for marker in (
                    "does not exist",
                    "not found",
                    "service account",
                    "unknown service account",
                )
            )
        return False

    try:
        wait_for_service_account(account.name)
        propagation_delays = (3, 5, 10, 15)
        for attempt in range(len(propagation_delays) + 1):
            try:
                apply_iam_policy(account.email)
                break
            except Exception as exc:
                if (
                    attempt < len(propagation_delays)
                    and _is_sa_policy_propagation_error(exc)
                ):
                    delay = propagation_delays[attempt]
                    print(
                        f.info(
                            "New service account IAM is still propagating; "
                            f"retrying in {delay} seconds..."
                        )
                    )
                    time.sleep(delay)
                    continue
                raise
    except Exception as e:
        classified = classify_provider_error(e)
        if isinstance(classified, ProviderTransientError):
            message = (
                "Google IAM is enabled but did not become ready in time. "
                "Run setup again to resume."
            )
            print(f.error(message))
            raise ProviderTransientError(message) from e
        print(f.error(wrap_text("Failed to reconcile the service account.")))
        raise classify_provider_error(
            e,
            message="Failed to reconcile the keyless runtime service account.",
        ) from e

    return {"client_email": account.email}
