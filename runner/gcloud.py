import json
import os

from runner.context import GCLOUD_CLI, format_command
from runner.process import run_command


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_gcloud_activation_uses_complete_saved_target
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_gcloud_activation_skips_unconfigured_repository
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_gcloud_activation_rejects_partial_saved_target
# @features setup testing development auth
# @dimensions gcloud-config activation unconfigured validation
# @pair setup:gcloud-token
def activate_repository_gcloud(
    *,
    ensure_adc=False,
    ensure_cli_token=False,
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

    config_gcloud()
    if ensure_cli_token:
        from runner.adc import ensure_gcloud_source_login

        ensure_gcloud_source_login(target["ACCOUNT"], allow_login=False)
        print(f"[OK] gcloud account access is ready ({target['ACCOUNT']})")
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
        }
        if allow_adc_login is not None:
            adc_options["allow_login"] = allow_adc_login
        ensure_adc_target(
            target["ACCOUNT"],
            target["PROJECT"],
            **adc_options,
        )
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
        print(f"\n{'=' * 70}")
        print(f"ERROR: Account '{account}' is not authenticated")
        print(f"{'=' * 70}")
        print(f"\nThe account '{account}' has not been authenticated with gcloud.")
        print("\nTo authenticate this account, run:")
        print(f"\n  {format_command([GCLOUD_CLI, 'auth', 'login', account])}")
        print("\nThis will open a browser window where you can sign in.")
        print("\nAuthenticated accounts:")
        authenticated = get_authenticated_accounts()
        if authenticated:
            for acc in authenticated:
                print(f"  [OK] {acc}")
        else:
            print("  (none)")
        print(f"\n{'=' * 70}\n")
        raise RuntimeError(f"Account '{account}' is not authenticated.")


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason gcloud CLI mutation wrapper exercised through configuration switching
def create_configuration(name, account, project):
    """Create a new gcloud configuration."""
    print(f"\nCreating configuration '{name}'...")
    run_command(
        [GCLOUD_CLI, "config", "configurations", "create", name, "--no-activate"]
    )
    run_command(
        [GCLOUD_CLI, "config", "set", "account", account, "--configuration", name]
    )
    run_command(
        [GCLOUD_CLI, "config", "set", "project", project, "--configuration", name]
    )
    print(f"[OK] Configuration '{name}' created successfully")


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason gcloud CLI mutation wrapper exercised through configuration switching
def activate_configuration(name):
    """Activate a specific gcloud configuration."""
    print(f"\nActivating configuration '{name}'...")
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
            f"Updating gcloud configuration '{name}' account: {current_account or '(unset)'} -> {account}"
        )
        run_command(
            [GCLOUD_CLI, "config", "set", "account", account, "--configuration", name]
        )

    if current_project != project:
        print(
            f"Updating gcloud configuration '{name}' project: {current_project or '(unset)'} -> {project}"
        )
        run_command(
            [GCLOUD_CLI, "config", "set", "project", project, "--configuration", name]
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_gcloud_switcher_exports_project_for_child_processes
# @features setup
# @dimensions gcloud-config env-export
def verify_active_configuration(name, account, project):
    active = get_active_configuration()
    active_account = get_configuration_value("account")
    active_project = get_configuration_value("project")

    if active != name or active_account != account or active_project != project:
        print(f"\n{'=' * 70}")
        print("ERROR: Active gcloud configuration does not match expected settings")
        print(f"{'=' * 70}")
        print(f"Expected: config={name}, account={account}, project={project}")
        print(
            f"Actual:   config={active}, account={active_account}, project={active_project}"
        )
        print(f"{'=' * 70}\n")
        raise RuntimeError(
            "Active gcloud configuration does not match expected settings."
        )

    os.environ["CLOUDSDK_ACTIVE_CONFIG_NAME"] = name
    os.environ["GOOGLE_CLOUD_PROJECT"] = project
    os.environ["GCLOUD_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = project
    # os.environ["LAGNIAPPE_GCLOUD_CONFIGURED"] = name
    print(f"[OK] Using gcloud configuration '{name}' ({account}, {project})")


# @testable false
# @covered-by runner/gcloud.py::config_gcloud
# @reason console-only inspection helper
def display_configurations():
    """Display all configurations in a readable format."""
    configs = list_configurations()
    active = get_active_configuration()

    print("\n" + "=" * 70)
    print("GCloud Configurations:")
    print("=" * 70)

    for config in configs:
        is_active = " (ACTIVE)" if config["name"] == active else ""
        print(f"\nName: {config['name']}{is_active}")
        print(
            f"  Account: {config.get('properties', {}).get('core', {}).get('account', 'Not set')}"
        )
        print(
            f"  Project: {config.get('properties', {}).get('core', {}).get('project', 'Not set')}"
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_gcloud_switcher_exports_project_for_child_processes
# @features setup
# @dimensions gcloud-config env-export
def config_gcloud():
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
                    expected_name, expected_account, expected_project
                )
                return
            activate_configuration(c["name"])
            verify_active_configuration(
                expected_name, expected_account, expected_project
            )
            return

    os.environ["GRPC_VERBOSITY"] = "ERROR"
    os.environ["GLOG_minloglevel"] = "2"
    create_configuration(expected_name, expected_account, expected_project)
    activate_configuration(expected_name)
    verify_active_configuration(expected_name, expected_account, expected_project)
