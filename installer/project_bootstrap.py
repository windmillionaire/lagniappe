"""Inspect project prerequisites, then apply explicitly confirmed bootstrap work."""

import json
import webbrowser

from runner import presentation as ui
from runner.presentation import output as print, read_input as input
from runner.console import format_prompt
from installer import wrap_text, setup_target
from installer.commands import (
    run_gcloud_command, _fail,
    _is_google_cloud_terms_error, _google_cloud_terms_repair_action,
)
from installer.errors import SetupCancelled, SetupError

BOOTSTRAP_GOOGLE_CLOUD_APIS = {
    "cloudbilling.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
}

BOOTSTRAP_API_TIMEOUT = 300


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_target_preflight_selects_billing_and_reports_required_apis
# @matrix setup : billing preflight provider-apis
def _load_gcloud_json(command, description):
    result = run_gcloud_command(command, check=False)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{description} failed: {error or 'gcloud command failed'}")
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{description} returned invalid JSON") from error


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_billing_selection_defers_to_project_console_when_cli_returns_no_open_account
# @tests tests_tooling/test_001a_setup_validation_config.py::test_target_preflight_selects_billing_and_reports_required_apis
# @matrix setup : billing gcloud-config interactive-input
def _select_billing_account(accounts):
    from installer import FORMATTER

    f = FORMATTER.initialize()
    accounts = [
        account for account in accounts if account.get("open") is not False
    ]
    if not accounts:
        return None

    choices = {}
    for account in accounts:
        name = str(account.get("name") or "").removeprefix("billingAccounts/")
        if not name:
            continue
        choices[name] = account
    if not choices:
        raise RuntimeError(
            "Google Cloud returned no usable open billing account identifiers."
        )

    if len(choices) == 1:
        selected, account = next(iter(choices.items()))
        print(
            f.info(
                wrap_text(
                    f"Using existing billing account {selected}: "
                    f"{account.get('displayName') or '(unnamed)'}"
                )
            )
        )
        return selected

    print(ui.heading(wrap_text("Accessible open billing accounts:")))
    for name, account in choices.items():
        print(wrap_text(f"  {ui.styled(name, 'cyan')}: {account.get('displayName') or '(unnamed)'}"))
    while True:
        selected = input(
            format_prompt("Billing account for this installation: ")
        ).strip()
        if selected in choices:
            return selected
        print(
            f.error(
                wrap_text(
                    "Enter one of the accessible billing account IDs shown above."
                )
            )
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_project_billing_authorization_uses_existing_account_and_project_console
# @matrix setup : billing browser interactive-input
def _authorize_project_billing(project_id):
    """Open the target's billing page and verify its existing-account link."""
    from installer import FORMATTER

    f = FORMATTER.initialize()
    url = (
        "https://console.cloud.google.com/billing/linkedaccount"
        f"?project={project_id}"
    )
    print(
        f.info(
            wrap_text(
                (
                    f"In Google Cloud, select '{ui.literal('Link a billing account')}' and "
                    "choose your existing billing account for project '"
                    f"{ui.literal(project_id)}':\n  {ui.literal(url)}"
                )
            )
        )
    )
    try:
        webbrowser.open_new_tab(url)
    except webbrowser.Error:
        pass

    while True:
        response = input(
            format_prompt("Link the existing billing account", hint="Enter to continue; x to exit")
        ).strip()
        if response.lower() == "x":
            raise SetupCancelled(
                "Installation cancelled during project billing authorization."
            )

        billing = _load_gcloud_json(
            ["billing", "projects", "describe", project_id, "--format=json"],
            "Billing verification",
        )
        billing_account = str(
            billing.get("billingAccountName") or ""
        ).removeprefix("billingAccounts/")
        if billing.get("billingEnabled") and billing_account:
            return billing_account
        print(
            f.warning(
                wrap_text(
                    f"Billing is not enabled for project '{project_id}' yet. "
                    "Complete the Google Cloud page, then check again."
                )
            )
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_target_preflight_selects_billing_and_reports_required_apis
# @tests tests_tooling/test_001a_setup_validation_config.py::test_target_preflight_defers_billing_discovery_until_new_project_exists
# @matrix setup : billing preflight project-create provider-apis
def _target_preflight(target: setup_target.SetupTarget):
    """Run read-only target, billing, and Service Usage checks."""
    from config import constants

    project_id = target.project_id
    project = setup_target._project_state(project_id)
    if project["state"] == "unavailable":
        raise RuntimeError(
            f"Could not inspect target project {project_id}: {project['error']}"
        )

    accounts = []
    billing_account = None
    billing_enabled = False
    enabled_apis = set()

    if project["state"] == "available":
        billing = _load_gcloud_json(
            ["billing", "projects", "describe", project_id, "--format=json"],
            "Project billing preflight",
        )
        billing_enabled = bool(billing.get("billingEnabled"))
        billing_account = str(
            billing.get("billingAccountName") or ""
        ).removeprefix("billingAccounts/") or None

        services = run_gcloud_command(
            [
                "services",
                "list",
                "--enabled",
                f"--project={project_id}",
                "--format=value(config.name)",
            ],
            check=False,
        )
        if services.returncode != 0:
            error = (services.stderr or services.stdout or "").strip()
            raise RuntimeError(
                "Required-API preflight failed: "
                f"{error or 'could not list enabled services'}"
            )
        enabled_apis = {
            value.strip() for value in services.stdout.splitlines() if value.strip()
        }

    if not billing_enabled and project["state"] == "available":
        accounts = _load_gcloud_json(
            ["billing", "accounts", "list", "--format=json"],
            "Billing-account preflight",
        )
        billing_account = _select_billing_account(accounts)

    required_apis = set(constants.REQUIRED_GOOGLE_CLOUD_APIS)
    return {
        "project": project,
        "billing_account": billing_account,
        "billing_enabled": billing_enabled,
        "enabled_apis": enabled_apis,
        "missing_apis": sorted(required_apis - enabled_apis),
    }


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_apply_target_preflight_creates_and_bills_confirmed_project
# @tests tests_tooling/test_001a_setup_validation_config.py::test_apply_target_preflight_authorizes_billing_after_project_creation_when_cli_list_is_empty
# @tests tests_tooling/test_001a_setup_validation_config.py::test_apply_target_preflight_rediscovers_and_links_existing_billing_account
# @tests tests_tooling/test_001a_setup_validation_config.py::test_google_cloud_terms_failure_has_account_specific_repair
# @matrix setup : billing browser preflight project-create provider-apis
def _apply_target_preflight(
    target: setup_target.SetupTarget, preflight, project_ready=None
):
    """Apply the already-confirmed project creation and billing mutations."""
    from config import constants
    from installer import FORMATTER

    f = FORMATTER.initialize()
    project_id = target.project_id
    if preflight["project"]["state"] in ("absent", "unverified"):
        result = run_gcloud_command(
            ["projects", "create", project_id],
            check=False,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "").strip()
            print(
                f.error(
                    f"Failed to create project {project_id}: "
                    f"{error or 'gcloud command failed'}"
                )
            )
            _fail()

    bootstrap_missing = sorted(
        BOOTSTRAP_GOOGLE_CLOUD_APIS - set(preflight["enabled_apis"])
    )
    if bootstrap_missing:
        print(
            f.info(
                wrap_text(
                    "Preparing Google Cloud project APIs. This may take up to "
                    "5 minutes..."
                )
            )
        )
        result = run_gcloud_command(
            [
                "services",
                "enable",
                *bootstrap_missing,
                f"--project={project_id}",
                "--quiet",
            ],
            check=False,
            timeout=BOOTSTRAP_API_TIMEOUT,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "").strip()
            if _is_google_cloud_terms_error(error):
                account = target.account or "the installer"
                raise SetupError(
                    "Google Cloud service terms have not been accepted for "
                    f"'{account}'.",
                    repair_action=_google_cloud_terms_repair_action(account),
                )
            raise RuntimeError(
                f"Could not prepare Google Cloud project APIs: "
                f"{error or 'gcloud command failed'}"
            )
        preflight["enabled_apis"].update(bootstrap_missing)
        preflight["missing_apis"] = sorted(
            set(preflight["missing_apis"]) - set(bootstrap_missing)
        )

    if not preflight["billing_enabled"] and not preflight["billing_account"]:
        accounts = _load_gcloud_json(
            ["billing", "accounts", "list", "--format=json"],
            "Billing-account discovery after project preparation",
        )
        preflight["billing_account"] = _select_billing_account(accounts)

    if project_ready is not None:
        project_ready()

    if not preflight["billing_enabled"]:
        if preflight["billing_account"]:
            result = run_gcloud_command(
                [
                    "billing",
                    "projects",
                    "link",
                    project_id,
                    f"--billing-account={preflight['billing_account']}",
                ],
                check=False,
            )
            if result.returncode != 0:
                error = (result.stderr or result.stdout or "").strip()
                print(
                    f.error(
                        f"Failed to link billing for {project_id}: "
                        f"{error or 'gcloud command failed'}"
                    )
                )
                _fail()
        else:
            preflight["billing_account"] = _authorize_project_billing(project_id)

    billing = _load_gcloud_json(
        ["billing", "projects", "describe", project_id, "--format=json"],
        "Billing verification",
    )
    linked_account = str(
        billing.get("billingAccountName") or ""
    ).removeprefix("billingAccounts/")
    if (
        not billing.get("billingEnabled")
        or linked_account != preflight["billing_account"]
    ):
        raise RuntimeError(
            f"Billing verification failed for {project_id}: expected "
            f"{preflight['billing_account']}, found {linked_account or '(none)'}"
        )

    services = run_gcloud_command(
        [
            "services",
            "list",
            "--enabled",
            f"--project={project_id}",
            "--format=value(config.name)",
        ],
        check=False,
    )
    if services.returncode != 0:
        error = (services.stderr or services.stdout or "").strip()
        raise RuntimeError(
            "Required-API verification failed before enablement: "
            f"{error or 'could not list enabled services'}"
        )
    enabled_apis = {
        value.strip() for value in services.stdout.splitlines() if value.strip()
    }
    preflight["enabled_apis"] = enabled_apis
    preflight["missing_apis"] = sorted(
        set(constants.REQUIRED_GOOGLE_CLOUD_APIS) - enabled_apis
    )

