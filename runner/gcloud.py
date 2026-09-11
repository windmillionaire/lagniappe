from runner import presentation as ui
from runner.presentation import output as print

import json
import os

from runner.context import GCLOUD_CLI, format_command
from runner.console import wrap_text
from runner.process import run_command


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_gcloud_activation_uses_complete_saved_target
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_gcloud_activation_skips_unconfigured_repository
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_gcloud_activation_rejects_partial_saved_target
# @matrix auth development setup testing : activation gcloud-config gcloud-token unconfigured validation
def activate_repository_gcloud(
    *,
    ensure_adc=False,
    ensure_cli_token=False,
    allow_cli_login=False,
    allow_runtime_adc=False,
    allow_adc_login=None,
    select_adc_target=False,
):
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
    if ensure_adc:
        principal = (adc_identity or {}).get("principal")
        if principal and principal.casefold() != target["ACCOUNT"].casefold():
            print(ui.value("ADC account", principal, column=17, verbatim=True))
    return True


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason gcloud CLI query wrapper exercised through configuration switching
def list_configurations():
    """List all available gcloud configurations."""
    result = run_command(
        [GCLOUD_CLI, "config", "configurations", "list", "--format=json"]
    )
    configs = json.loads(result.stdout)
    return configs


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason gcloud CLI query wrapper exercised through configuration switching
def get_active_configuration():
    """Get the currently active configuration name."""
    result = run_command(
        [
            GCLOUD_CLI,
            "config",
            "configurations",
            "list",
            "--filter=is_active:true",
            "--format=value(name)",
        ]
    )
    return result.stdout.strip()


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason gcloud CLI query wrapper exercised through configuration switching
def get_authenticated_accounts():
    """Get list of authenticated accounts."""
    result = run_command([GCLOUD_CLI, "auth", "list", "--format=value(account)"])
    accounts = [acc.strip() for acc in result.stdout.split("\n") if acc.strip()]
    return accounts


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason small authentication helper used by gcloud configuration switching
def is_account_authenticated(account):
    """Check if a specific account is authenticated."""
    authenticated_accounts = get_authenticated_accounts()
    return account in authenticated_accounts


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason console guidance around authentication failures
def check_account_authentication(account):
    """Check if account is authenticated, exit with instructions if not."""
    if not is_account_authenticated(account):
        print(ui.error("The saved account is not authenticated with gcloud"))
        print(ui.value("Account", account, verbatim=True))
        print(wrap_text("\nTo authenticate this account, run:"))
        print(f"\n  {ui.literal(format_command([GCLOUD_CLI, 'auth', 'login', account]))}")
        print(wrap_text("\nThis will open a browser window where you can sign in."))
        print(wrap_text("\nAuthenticated accounts:"))
        authenticated = get_authenticated_accounts()
        if authenticated:
            for acc in authenticated:
                print(f"  - {acc}")
        else:
            print("  (none)")
        raise RuntimeError(f"Account '{account}' is not authenticated.")


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason gcloud CLI mutation wrapper exercised through configuration switching
def create_configuration(name, account, project):
    """Create a new gcloud configuration."""
    print(wrap_text(f"\nCreating configuration '{name}'..."))
    run_command(
        [GCLOUD_CLI, "config", "configurations", "create", name, "--no-activate"]
    )
    run_command(
        [GCLOUD_CLI, "config", "set", "account", account, "--configuration", name]
    )
    run_command(
        [GCLOUD_CLI, "config", "set", "project", project, "--configuration", name]
    )
    print(ui.success(f"Configuration '{name}' created"))


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason gcloud CLI mutation wrapper exercised through configuration switching
def activate_configuration(name):
    """Activate a specific gcloud configuration."""
    print(wrap_text(f"\nActivating configuration '{name}'..."))
    run_command([GCLOUD_CLI, "config", "configurations", "activate", name])


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason gcloud CLI query wrapper exercised through configuration switching
def get_configuration_value(key, configuration=None):
    command = [GCLOUD_CLI, "config", "get-value", key]
    if configuration:
        command.extend(["--configuration", configuration])
    result = run_command(command)
    return result.stdout.strip()


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason property reconciliation branch inside gcloud configuration switching
def ensure_configuration_properties(name, account, project):
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
            [GCLOUD_CLI, "config", "set", "account", account, "--configuration", name]
        )

    if current_project != project:
        print(
            wrap_text(
                f"Updating gcloud configuration '{name}' project: {current_project or '(unset)'} -> {project}"
            )
        )
        run_command(
            [GCLOUD_CLI, "config", "set", "project", project, "--configuration", name]
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_gcloud_switcher_exports_project_for_child_processes
# @matrix setup : env-export gcloud-config
def verify_active_configuration(name, account, project, *, announce=True):
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
            for label, value in zip(("Configuration", "Account", "Project"), values):
                print(ui.value(label, value, column=17, verbatim=True))
        raise RuntimeError(
            "Active gcloud configuration does not match expected settings."
        )

    os.environ["CLOUDSDK_ACTIVE_CONFIG_NAME"] = name
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


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason console-only inspection helper
def display_configurations():
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


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_gcloud_switcher_exports_project_for_child_processes
# @matrix setup : env-export gcloud-config
def config_gcloud(*, announce=True):
    from config import SETTINGS

    config = SETTINGS.GCLOUD_CONFIG
    if not config:
        print("No gcloud configuration found")
        raise RuntimeError("No saved gcloud configuration was found.")

    expected_name = config.get("NAME")
    expected_account = config.get("ACCOUNT")
    expected_project = config.get("PROJECT")

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
    os.environ["GLOG_minloglevel"] = "2"
    create_configuration(expected_name, expected_account, expected_project)
    activate_configuration(expected_name)
    verify_active_configuration(
        expected_name, expected_account, expected_project, announce=announce
    )
