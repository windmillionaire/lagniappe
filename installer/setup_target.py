"""Interactive selection and read-only verification of the installer target."""

from dataclasses import dataclass
import json
import re
import secrets

from runner import presentation as ui
from runner.presentation import output as print, read_input as input
from runner.console import format_prompt
from runner.context import GCLOUD_CLI, format_command, setup_command
from installer import wrap_text
from installer.commands import run_gcloud_command, _fail
from installer.errors import SetupCancelled
from installer.utils import validate_input

GCLOUD_VALUE_SUCCESS = "success"

GCLOUD_VALUE_UNSET = "unset"

GCLOUD_VALUE_ERROR = "error"

PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


# @testable infrastructure
# @covered-by installer/create_config.py::set_application_defaults
@dataclass(frozen=True)
class SetupTarget:
    """The confirmed non-secret target, independent of mutable settings."""

    app_name: str
    configuration_name: str
    account: str
    project_id: str


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_config_status_save_and_gcloud_login_helpers
# @pair setup:gcloud-config
def _gcloud_debug_value(command):
    """Return a structured gcloud value without promoting errors to values."""
    result = run_gcloud_command(command, check=False)
    value = (result.stdout or "").strip()
    if result.returncode == 0 and value and value.lower() != "(unset)":
        return {
            "state": GCLOUD_VALUE_SUCCESS,
            "value": value,
            "error": None,
            "command": list(command),
        }
    if result.returncode == 0:
        return {
            "state": GCLOUD_VALUE_UNSET,
            "value": None,
            "error": None,
            "command": list(command),
        }
    error = (result.stderr or result.stdout or "").strip()
    return {
        "state": GCLOUD_VALUE_ERROR,
        "value": None,
        "error": error or "gcloud command failed",
        "command": list(command),
    }


# @testable false
# @covered-by installer/setup_target.py::_gcloud_debug_value
# @reason console rendering for structured gcloud diagnostic values
def _display_gcloud_value(result):
    if result["state"] == GCLOUD_VALUE_SUCCESS:
        return result["value"]
    if result["state"] == GCLOUD_VALUE_UNSET:
        return "(unset)"
    return f"(error: {result['error']})"


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_gcloud_account_selection_requires_an_explicit_authenticated_identity
# @matrix setup : gcloud-config gcloud-token interactive-input
def _get_gcloud_account(account):
    from runner.gcloud import check_account_authentication

    if account:
        check_account_authentication(account)
        return account

    active_result = run_gcloud_command(
        [
            "auth",
            "list",
            "--filter=status:ACTIVE",
            "--format=value(account)",
        ],
        check=False,
    )
    active_accounts = [
        value.strip()
        for value in str(active_result.stdout or "").splitlines()
        if value.strip()
    ]
    if active_result.returncode != 0 or len(active_accounts) != 1:
        login_command = format_command([GCLOUD_CLI, "auth", "login"])
        raise RuntimeError(
            "Setup could not identify exactly one active gcloud CLI account. Run "
            f"{login_command}, then rerun setup."
        )

    account = active_accounts[0]
    print(wrap_text(f"\nThe active gcloud CLI account is: {account}"))
    while True:
        answer = input(
            format_prompt("Use this account for the installation? [y/N]: ")
        ).strip()
        if answer.casefold() in {"y", "yes"}:
            break
        if answer.casefold() in {"", "n", "no", "x", "exit"}:
            login_command = format_command([GCLOUD_CLI, "auth", "login"])
            print(
                ui.status("Setup cancelled before project selection. Run "
                f"{login_command}, choose the installation account, then "
                "rerun setup.")
            )
            raise SetupCancelled("Setup cancelled during account confirmation.")
        print(ui.error(wrap_text("Enter Y to confirm this account, or N to cancel.")))

    check_account_authentication(account)
    token_check = run_gcloud_command(
        ["auth", "print-access-token", account],
        check=False,
        timeout=60,
    )
    if token_check.returncode != 0 or not str(token_check.stdout or "").strip():
        login_command = format_command([GCLOUD_CLI, "auth", "login", account])
        raise RuntimeError(
            f"The gcloud CLI login for '{account}' could not be verified. Run "
            f"{login_command}, then rerun setup."
        )
    print(ui.success(wrap_text(f"Verified gcloud CLI installation account: {account}")))

    return account


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_project_id_selection_prefers_requested_name_and_suffixes_collisions
# @matrix setup : interactive-input project-id
def _project_id_from_app_name(sanitized_app_name):
    base = re.sub(r"[^a-z0-9-]", "-", sanitized_app_name.lower()).strip("-")
    if not base or not base[0].isalpha():
        base = f"lagniappe-{base}".strip("-")
    return re.sub(r"-+", "-", base)[:30].rstrip("-")


# @testable false
# @covered-by installer/setup_target.py::_get_gcloud_project
# @reason collision fallback is exercised through interactive project selection
def _randomized_project_id(sanitized_app_name):
    base = _project_id_from_app_name(sanitized_app_name)[:23].rstrip("-")
    return f"{base}-{secrets.token_hex(3)}"


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_validate_project_id_and_project_state_are_non_mutating
# @pair setup:project-id
def _project_state(project_id):
    result = run_gcloud_command(
        ["projects", "describe", project_id, "--format=json"],
        check=False,
    )
    if result.returncode == 0:
        try:
            details = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            details = {}
        return {"state": "available", "details": details, "error": None}

    error = (result.stderr or result.stdout or "").strip()
    normalized = error.casefold()
    if "not_found" in normalized or "not found" in normalized:
        return {"state": "absent", "details": None, "error": None}
    if any(
        marker in normalized
        for marker in (
            "permission_denied",
            "permission denied",
            "does not have permission",
            "caller does not have permission",
            "or it may not exist",
        )
    ):
        return {
            "state": "unverified",
            "details": None,
            "error": (
                "the project is either unused or inaccessible to the selected account"
            ),
        }
    return {
        "state": "unavailable",
        "details": None,
        "error": error or "project lookup failed",
    }


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_project_id_selection_prefers_requested_name_and_suffixes_collisions
# @matrix setup : interactive-input project-id
def _confirm_project_candidate(project_id, state, formatter):
    if state["state"] == "unavailable":
        print(
            formatter.error(
                wrap_text(f"Could not validate project {project_id}: {state['error']}")
            )
        )
        return False

    if state["state"] == "available":
        action = "Use the existing"
    else:
        action = "Create a new"
    answer = input(
        format_prompt(f"{action} project '{project_id}'? [y/N]: ")
    ).strip()
    if answer.lower() in ("y", "yes"):
        return True
    if state["state"] == "available":
        return False
    raise SetupCancelled("Installation cancelled during project selection.")


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_project_id_selection_prefers_requested_name_and_suffixes_collisions
# @matrix setup : interactive-input project-id
def _get_gcloud_project(project_id, sanitized_app_name):
    from installer import FORMATTER

    f = FORMATTER.initialize()
    configured_project = _gcloud_debug_value(["config", "get-value", "project"])

    if project_id:
        if not validate_project_id(project_id):
            print(f.error(wrap_text(f"Saved project ID is invalid: {project_id}")))
            _fail()
        return project_id

    if configured_project["state"] == GCLOUD_VALUE_ERROR:
        print(
            f.error(
                wrap_text(
                    "Could not determine the active gcloud project: "
                    f"{configured_project['error']}"
                )
            )
        )
        _fail()

    declined_existing_projects = set()
    if configured_project["state"] == GCLOUD_VALUE_SUCCESS:
        candidate = configured_project["value"]
        configured_name = _gcloud_debug_value(
            [
                "config",
                "configurations",
                "list",
                "--filter=is_active:true",
                "--format=value(name)",
            ]
        )
        active_name_matches = (
            configured_name["state"] == GCLOUD_VALUE_SUCCESS
            and configured_name["value"] == sanitized_app_name
        )
        if active_name_matches and validate_project_id(candidate):
            state = _project_state(candidate)
            if _confirm_project_candidate(candidate, state, f):
                return candidate
            if state["state"] == "available":
                declined_existing_projects.add(candidate)

    suggestion = _project_id_from_app_name(sanitized_app_name)
    if suggestion in declined_existing_projects:
        suggestion = _randomized_project_id(sanitized_app_name)
    while True:
        entered = input(
            format_prompt(
                "Google Cloud project ID", default=suggestion,
                hint="Enter to keep; or type a different project ID",
            )
        ).strip()
        candidate = entered or suggestion
        if not validate_project_id(candidate):
            continue
        state = _project_state(candidate)
        if _confirm_project_candidate(candidate, state, f):
            return candidate
        if candidate == suggestion and state["state"] == "available":
            suggestion = _randomized_project_id(sanitized_app_name)


# @testable false
# @covered-by installer/setup_target.py::_list_owned_projects
# @reason per-project policy parsing is exercised through delegated discovery
def _has_direct_project_owner_binding(project_id, account):
    result = run_gcloud_command(
        [
            "projects",
            "get-iam-policy",
            project_id,
            "--format=json",
            f"--account={account}",
        ],
        check=False,
    )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(error or "project IAM policy lookup failed")
    try:
        policy = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError("project IAM policy lookup returned invalid JSON") from error
    member = f"user:{str(account or '').strip().casefold()}"
    return any(
        str(binding.get("role") or "") == "roles/owner"
        and not binding.get("condition")
        and member
        in {
            str(value or "").strip().casefold()
            for value in binding.get("members") or ()
        }
        for binding in policy.get("bindings") or ()
        if isinstance(binding, dict)
    )


# @testable false
# @covered-by installer/setup_target.py::_list_owned_projects
# @covered-by installer/setup_target.py::_select_existing_gcloud_project
# @reason project discovery normalization is exercised through both picker modes
def _list_active_projects(account):
    """Return normalized active projects visible to the selected account."""
    result = run_gcloud_command(
        [
            "projects",
            "list",
            "--filter=lifecycleState=ACTIVE",
            "--format=json",
            f"--account={account}",
        ],
        check=False,
    )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "Could not list Google Cloud projects accessible to "
            f"'{account}': {error or 'gcloud projects list failed'}"
        )
    try:
        discovered = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Google Cloud project discovery returned invalid JSON."
        ) from error
    if not isinstance(discovered, list):
        raise RuntimeError("Google Cloud project discovery returned invalid data.")

    projects = []
    seen = set()
    for project in discovered:
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("projectId") or "").strip()
        if not PROJECT_ID_PATTERN.fullmatch(project_id) or project_id in seen:
            continue
        display_name = str(
            project.get("displayName") or project.get("name") or project_id
        ).strip()
        if not display_name or display_name.startswith("projects/"):
            display_name = project_id
        projects.append(
            {
                "project_id": project_id,
                "display_name": display_name,
                "project_number": str(project.get("projectNumber") or "").strip(),
            }
        )
        seen.add(project_id)

    projects.sort(
        key=lambda project: (
            project["display_name"].casefold(),
            project["project_id"],
        )
    )
    return projects


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_delegated_project_picker_lists_only_direct_owner_projects
# @matrix setup : delegated-install existing-project gcloud-config project-iam project-picker provider-discovery
def _list_owned_projects(account):
    """Return active projects directly owned by the selected gcloud account."""
    projects = []
    policy_errors = []
    for project in _list_active_projects(account):
        try:
            owner = _has_direct_project_owner_binding(
                project["project_id"], account
            )
        except RuntimeError as error:
            policy_errors.append(f"{project['project_id']}: {error}")
            continue
        if owner:
            projects.append(project)

    if not projects:
        if policy_errors:
            raise RuntimeError(
                "Could not determine which accessible Google Cloud projects "
                f"are directly owned by '{account}': {policy_errors[0]}"
            )
        raise RuntimeError(
            f"No active Google Cloud project gives '{account}' a direct, "
            "unconditional Project Owner role. The permanent business Owner "
            "must create the project, link billing, and grant this installer "
            "Basic / Owner before setup can continue."
        )
    return projects


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_delegated_project_picker_lists_only_direct_owner_projects
# @tests tests_tooling/test_001a_setup_validation_config.py::test_initial_target_choice_uses_delegated_picker_or_ordinary_name_flow
# @matrix setup : delegated-install existing-project interactive-input ordinary-install project-iam project-picker provider-discovery
def _select_existing_gcloud_project(account, *, direct_owner_required=True):
    """Let the operator select an active project visible to their account."""
    if direct_owner_required:
        projects = _list_owned_projects(account)
        heading = f"Active Google Cloud projects owned directly by {account}:"
    else:
        projects = _list_active_projects(account)
        if not projects:
            raise RuntimeError(
                f"No active Google Cloud projects are accessible to '{account}'. "
                "Grant this account access to the intended project, or rerun "
                "setup and choose the new-project path."
            )
        heading = f"Active Google Cloud projects accessible to {account}:"

    print("\n" + ui.heading(heading))
    for index, project in enumerate(projects, start=1):
        print(
            ui.choice(index, project['display_name'], project['project_id'])
        )

    while True:
        entered = input(
            format_prompt(
                "Select the project for this installation by number",
                default="1" if len(projects) == 1 else None, hint="x to cancel",
            )
        ).strip()
        if not entered and len(projects) == 1:
            entered = "1"
        if entered.casefold() in {"x", "exit"}:
            raise SetupCancelled("Setup cancelled during project selection.")
        if entered.isdigit() and 1 <= int(entered) <= len(projects):
            selected = projects[int(entered) - 1]
            state = _project_state(selected["project_id"])
            if state["state"] != "available":
                raise RuntimeError(
                    f"Selected project '{selected['project_id']}' could not be "
                    "reverified as accessible to the active gcloud account."
                )
            print(
                wrap_text(
                    f"Selected existing project '{selected['display_name']}' "
                    f"({selected['project_id']})."
                )
            )
            return selected["display_name"], selected["project_id"]
        print(
            ui.error(wrap_text("Enter one of the project numbers shown above, or X to cancel."))
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_initial_target_choice_uses_delegated_picker_or_ordinary_name_flow
# @matrix setup : delegated-install interactive-input ordinary-install project-picker
def _select_initial_target(account):
    """Choose the delegated picker or ordinary installation naming flow."""
    while True:
        answer = (
            input(
                format_prompt(
                    "Are you installing Lagniappe for a different permanent Owner? "
                    "[y/N]: "
                )
            )
            .strip()
            .casefold()
        )
        if answer in {"y", "yes"}:
            return _select_existing_gcloud_project(
                account, direct_owner_required=True
            )
        if answer in {"", "n", "no"}:
            break
        print(
            ui.error(wrap_text(
                "Enter Y for a delegated installation, or N for your own installation."
            ))
        )

    while True:
        answer = (
            input(
                format_prompt(
                    "Has the Google Cloud project for this installation already been "
                    "created? [y/N]: "
                )
            )
            .strip()
            .casefold()
        )
        if answer in {"y", "yes"}:
            return _select_existing_gcloud_project(
                account, direct_owner_required=False
            )
        if answer in {"", "n", "no"}:
            app_name = _get_app_name()
            sanitized_app_name = _gcloud_configuration_name(app_name)
            project_id = _get_gcloud_project("", sanitized_app_name)
            return app_name, project_id
        print(ui.error(wrap_text("Enter Y to select an existing project, or N to create one.")))


# @testable false
# @covered-by installer/create_config.py::set_application_defaults
# @reason deterministic name normalization exercised through config-file creation
def _gcloud_configuration_name(name):
    normalized = re.sub(r"[^a-z0-9]", "-", name.lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized:
        normalized = "lagniappe"
    elif not normalized[0].isalpha():
        normalized = f"lagniappe-{normalized}"
    if len(normalized) < 6:
        normalized = f"{normalized}-setup"
    return normalized[:30].rstrip("-")


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_validate_project_id_and_project_state_are_non_mutating
# @pair setup:project-id
def validate_project_id(project_id):
    """Validate the provider's project-ID syntax without mutating state."""
    if not PROJECT_ID_PATTERN.fullmatch(str(project_id or "")):
        print(
            ui.error(wrap_text(
                "Invalid project ID format. Must be 6-30 lowercase letters, "
                "numbers, or hyphens, starting with a letter."
            ))
        )
        return False

    return True


# @testable false
# @covered-by installer/iam.py::require_operator_permissions
# @reason setup preflight adapter owned by the IAM permission reporter
def _require_operator_permissions(
    project_id,
    *,
    billing_account=None,
    require_billing_link=False,
    client=None,
):
    from installer.iam import require_operator_permissions

    return require_operator_permissions(
        project_id,
        billing_account=billing_account,
        require_billing_link=require_billing_link,
        client=client,
    )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_gcloud_project_client_uses_selected_cli_account_without_adc
# @matrix setup : adc gcloud-token identity
def _gcloud_project_client(account):
    """Create a Resource Manager client from the already-authenticated CLI login."""
    result = run_gcloud_command(
        ["auth", "print-access-token", account],
        check=False,
        timeout=60,
    )
    token = str(result.stdout or "").strip()
    if result.returncode != 0 or not token:
        raise RuntimeError(
            f"The gcloud CLI login for installer '{account}' is unavailable. "
            f"Run {setup_command('auth')}, then retry setup."
        )

    from installer.utils import install_if_missing

    install_if_missing(
        "google.cloud.resourcemanager_v3",
        "Google Resource Manager API",
        package_name="google-cloud-resource-manager",
    )
    from google.cloud import resourcemanager_v3
    from google.oauth2.credentials import Credentials

    return resourcemanager_v3.ProjectsClient(credentials=Credentials(token=token))


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_existing_project_checks_cli_installer_permissions_before_adc_authentication
# @matrix setup : adc gcloud-token operator-permissions preflight
def _preflight_operator_authority(account, project_id, *, client=None):
    """Verify the selected CLI installer before opening or changing ADC."""
    client = client or _gcloud_project_client(account)
    try:
        _require_operator_permissions(project_id, client=client)
    except Exception as error:
        raise RuntimeError(
            f"The gcloud CLI installer '{account}' is signed in, but setup "
            f"could not verify its required access to project '{project_id}' "
            "before ADC authentication. Application Default Credentials were "
            f"not changed. {error}"
        ) from error
    print(
        ui.success(wrap_text(
            f"gcloud CLI installer access is ready ({account}, {project_id})"
        ))
    )
    return client


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_app_name_validation_rejects_control_characters_and_long_names
# @matrix setup : app-name validation
def _validate_app_name(value):
    value = str(value or "").strip()
    return bool(value) and len(value) <= 80 and all(
        character.isprintable() for character in value
    )


# @testable false
# @covered-by installer/create_config.py::set_application_defaults
# @reason decorated input accessor; retry behavior is owned by installer/utils.py::validate_input
@validate_input(
    "Enter a name for your Lagniappe installation",
    validation_fn=_validate_app_name,
    error_msg="Use 1-80 visible characters for the application name.",
)
def _get_app_name(value):
    return value.strip()


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_cli_identity_snapshot_fails_closed_on_unset_or_error
# @matrix setup : gcloud-config identity
def _active_cli_identity():
    values = {
        "configuration": _gcloud_debug_value(
            [
                "config",
                "configurations",
                "list",
                "--filter=is_active:true",
                "--format=value(name)",
            ]
        ),
        "account": _gcloud_debug_value(["config", "get-value", "account"]),
        "project": _gcloud_debug_value(["config", "get-value", "project"]),
    }
    failures = [
        f"{name}={_display_gcloud_value(value)}"
        for name, value in values.items()
        if value["state"] != GCLOUD_VALUE_SUCCESS
    ]
    if failures:
        raise RuntimeError(
            "Could not positively identify the active gcloud CLI state: "
            + ", ".join(failures)
        )
    return {name: value["value"] for name, value in values.items()}

