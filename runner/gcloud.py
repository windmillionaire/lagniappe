import json
import os
from typing import TypedDict

from runner import presentation as ui
from runner.console import wrap_text
from runner.context import GCLOUD_CLI, format_command
from runner.presentation import output as print
from runner.process import run_command


class GcloudConfiguration(TypedDict):
    name: str
    properties: dict[str, dict[str, str]]


def activate_repository_gcloud(
    *,
    ensure_adc: bool = False,
    ensure_cli_token: bool = False,
    allow_cli_login: bool = False,
    allow_runtime_adc: bool = False,
    allow_adc_login: bool | None = None,
    select_adc_target: bool = False,
) -> bool:
    """Activate the complete gcloud/ADC target saved for this repository."""
    from config import SETTINGS

    saved = SETTINGS.GCLOUD_CONFIG or {}
    target = {
        key: str(saved.get(key) or "").strip()
        for key in ("NAME", "ACCOUNT", "PROJECT")
    }
    configured_values = [value for value in target.values() if value]

    if not configured_values:
        return False
    if len(configured_values) != len(target):
        missing = ", ".join(key for key, value in target.items() if not value)
        raise RuntimeError(
            "The repository gcloud target is incomplete in lagniappe_dev.yaml; "
            f"missing: {missing}."
        )
    if not GCLOUD_CLI:
        raise RuntimeError(
            "This repository has a saved gcloud target, but the gcloud CLI "
            "is not installed or is not available on PATH."
        )

    config_gcloud(announce=False)
    if ensure_cli_token:
        from runner.adc import ensure_gcloud_source_login

        ensure_gcloud_source_login(
            target["ACCOUNT"],
            allow_login=allow_cli_login,
        )
    adc_identity = None
    if ensure_adc:
        from runner.adc import ensure_adc_target

        allowed_principals = ()
        if allow_runtime_adc:
            allowed_principals = (
                SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL"),
                SETTINGS.APP.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"),
            )
        adc_options = {
            "allowed_principals": allowed_principals,
            "select_gcloud_target": select_adc_target,
            "announce": False,
        }
        if allow_adc_login is not None:
            adc_options["allow_login"] = allow_adc_login
        adc_identity = ensure_adc_target(
            target["ACCOUNT"],
            target["PROJECT"],
            **adc_options,
        )
    print(ui.success("Google Cloud configuration verified"))
    for label, value in (
        ("Configuration", target["NAME"]),
        ("Account", target["ACCOUNT"]),
        ("Project", target["PROJECT"]),
    ):
        print(ui.value(label, value, column=17, verbatim=True))
    if adc_identity:
        principal = adc_identity.get("principal")
        if principal and principal.casefold() != target["ACCOUNT"].casefold():
            print(ui.value("ADC account", principal, column=17, verbatim=True))
    return True


def list_configurations() -> list[GcloudConfiguration]:
    """List all available gcloud configurations."""
    result = run_command(
        [GCLOUD_CLI or "gcloud", "config", "configurations", "list", "--format=json"]
    )
    configs = json.loads(result.stdout)
    return configs


def get_active_configuration() -> str:
    """Get the currently active configuration name."""
    result = run_command(
        [
            GCLOUD_CLI or "gcloud",
            "config",
            "configurations",
            "list",
            "--filter=is_active:true",
            "--format=value(name)",
        ]
    )
    return result.stdout.strip()


def get_authenticated_accounts() -> list[str]:
    """Get list of authenticated accounts."""
    result = run_command([GCLOUD_CLI or "gcloud", "auth", "list", "--format=value(account)"])
    accounts = [acc.strip() for acc in result.stdout.split("\n") if acc.strip()]
    return accounts


def is_account_authenticated(account: str) -> bool:
    """Check if a specific account is authenticated."""
    authenticated_accounts = get_authenticated_accounts()
    return account in authenticated_accounts


def check_account_authentication(account: str) -> None:
    """Check if account is authenticated, exit with instructions if not."""
    if not is_account_authenticated(account):
        print(ui.error("The saved account is not authenticated with gcloud"))
        print(ui.value("Account", account, verbatim=True))
        print(wrap_text("\nTo authenticate this account, run:"))
        print(f"\n  {ui.literal(format_command([GCLOUD_CLI or 'gcloud', 'auth', 'login', account]))}")
        print(wrap_text("\nThis will open a browser window where you can sign in."))
        print(wrap_text("\nAuthenticated accounts:"))
        authenticated = get_authenticated_accounts()
        if authenticated:
            for acc in authenticated:
                print(f"  - {acc}")
        else:
            print("  (none)")
        raise RuntimeError(f"Account '{account}' is not authenticated.")


def create_configuration(name: str, account: str, project: str) -> None:
    """Create a new gcloud configuration."""
    print(wrap_text(f"\nCreating configuration '{name}'..."))
    run_command(
        [GCLOUD_CLI or "gcloud", "config", "configurations", "create", name, "--no-activate"]
    )
    run_command(
        [GCLOUD_CLI or "gcloud", "config", "set", "account", account, "--configuration", name]
    )
    run_command(
        [GCLOUD_CLI or "gcloud", "config", "set", "project", project, "--configuration", name]
    )
    print(ui.success(f"Configuration '{name}' created"))


def activate_configuration(name: str) -> None:
    """Activate a specific gcloud configuration."""
    print(wrap_text(f"\nActivating configuration '{name}'..."))
    run_command([GCLOUD_CLI or "gcloud", "config", "configurations", "activate", name])


def get_configuration_value(key: str, configuration: str | None = None) -> str:
    command = [GCLOUD_CLI or "gcloud", "config", "get-value", key]
    if configuration:
        command.extend(["--configuration", configuration])
    result = run_command(command)
    return result.stdout.strip()


def ensure_configuration_properties(name: str, account: str, project: str) -> None:
    """Ensure an existing gcloud configuration points at the expected account/project."""
    current_account = get_configuration_value("account", configuration=name)
    current_project = get_configuration_value("project", configuration=name)

    if current_account != account:
        print(
            wrap_text(
                f"Updating gcloud configuration '{name}' account: {current_account or '(unset)'} -> {account}"
            )
        )
        run_command(
            [GCLOUD_CLI or "gcloud", "config", "set", "account", account, "--configuration", name]
        )

    if current_project != project:
        print(
            wrap_text(
                f"Updating gcloud configuration '{name}' project: {current_project or '(unset)'} -> {project}"
            )
        )
        run_command(
            [GCLOUD_CLI or "gcloud", "config", "set", "project", project, "--configuration", name]
        )


def verify_active_configuration(
    name: str, account: str, project: str, *, announce: bool = True
) -> None:
    active = get_active_configuration()
    active_account = get_configuration_value("account")
    active_project = get_configuration_value("project")

    if active != name or active_account != account or active_project != project:
        print(
            ui.error("Active gcloud configuration does not match expected settings")
        )
        for heading, values in (
            ("Expected", (name, account, project)),
            ("Actual", (active, active_account, active_project)),
        ):
            print(ui.heading(heading))
            for label, value in zip(("Configuration", "Account", "Project"), values, strict=True):
                print(ui.value(label, value, column=17, verbatim=True))
        raise RuntimeError(
            "Active gcloud configuration does not match expected settings."
        )

    os.environ["CLOUDSDK_ACTIVE_CONFIG_NAME"] = name
    # Another checkout may rewrite the same named gcloud configuration while
    # a long-running deployment is between provider calls. Pin this process.
    os.environ["CLOUDSDK_CORE_ACCOUNT"] = account
    os.environ["CLOUDSDK_CORE_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_PROJECT"] = project
    os.environ["GCLOUD_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = project
    # os.environ["LAGNIAPPE_GCLOUD_CONFIGURED"] = name
    if announce:
        print(ui.success("Google Cloud configuration verified"))
        for label, value in (
            ("Configuration", name),
            ("Account", account),
            ("Project", project),
        ):
            print(ui.value(label, value, column=17, verbatim=True))


def display_configurations() -> None:
    """Display all configurations in a readable format."""
    configs = list_configurations()
    active = get_active_configuration()

    print(ui.heading("\nGoogle Cloud configurations"))

    for config in configs:
        is_active = " (ACTIVE)" if config["name"] == active else ""
        print(ui.value("\nName", f"{config['name']}{is_active}", verbatim=True))
        print(
            ui.value(
                "  Account",
                f"{config.get('properties', {}).get('core', {}).get('account', 'Not set')}",
                verbatim=True,
            )
        )
        print(
            ui.value(
                "  Project",
                f"{config.get('properties', {}).get('core', {}).get('project', 'Not set')}",
                verbatim=True,
            )
        )


def config_gcloud(*, announce: bool = True) -> None:
    from config import SETTINGS

    config = SETTINGS.GCLOUD_CONFIG
    if not config:
        print("No gcloud configuration found")
        raise RuntimeError("No saved gcloud configuration was found.")

    expected_name = config.get("NAME")
    expected_account = config.get("ACCOUNT")
    expected_project = config.get("PROJECT")
    if not (isinstance(expected_name, str) and isinstance(expected_account, str) and isinstance(expected_project, str)):
        raise RuntimeError("Saved gcloud configuration requires a name, account, and project.")

    # Re-activation must inspect the saved configuration without overrides
    # inherited from an earlier activation in this process or its parent.
    os.environ.pop("CLOUDSDK_CORE_ACCOUNT", None)
    os.environ.pop("CLOUDSDK_CORE_PROJECT", None)
    active = get_active_configuration()
    check_account_authentication(expected_account)

    configurations = list_configurations()
    for c in configurations:
        if c["name"] == expected_name:
            ensure_configuration_properties(
                expected_name, expected_account, expected_project
            )
            if active == expected_name:
                verify_active_configuration(
                    expected_name, expected_account, expected_project, announce=announce
                )
                return
            activate_configuration(c["name"])
            verify_active_configuration(
                expected_name, expected_account, expected_project, announce=announce
            )
            return

    os.environ["GRPC_VERBOSITY"] = "ERROR"
    os.environ["GLOG_minloglevel"] = "2"  # noqa: SIM112 -- glog requires this case-sensitive name.
    create_configuration(expected_name, expected_account, expected_project)
    activate_configuration(expected_name)
    verify_active_configuration(
        expected_name, expected_account, expected_project, announce=announce
    )
