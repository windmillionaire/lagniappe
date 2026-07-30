import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import webbrowser

from runner.context import GCLOUD_CLI, format_command, setup_command
from config.constants import UNSUPPORTED_SETTING_KEYS
from config.recovery import (
    CONFIG_KIND,
    CONFIG_SCHEMA_VERSION,
)
from config.locations import (
    normalize_app_engine_location,
    normalize_resource_region,
)
from installer import wrap_text
from installer.utils import run_gcloud_command, validate_input
from installer.errors import GCLOUD_TIMEOUT, SetupCancelled, SetupError

GCLOUD_VALUE_SUCCESS = "success"
GCLOUD_VALUE_UNSET = "unset"
GCLOUD_VALUE_ERROR = "error"
PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_ACTIVE_ADC_TRANSACTION = None
ADC_QUOTA_TIMEOUT = 60
ADC_PROJECT_PROPAGATION_DELAYS = (2, 4, 8, 15, 20)
BOOTSTRAP_GOOGLE_CLOUD_APIS = {
    "cloudbilling.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
}
BOOTSTRAP_API_TIMEOUT = 300
GOOGLE_AUTH_PERMISSION_GUIDANCE = (
    "On Google's permission screen, choose Select all if it appears, then "
    "Continue or Allow. In practical terms, you are granting these permissions "
    "to yourself: they let Google Cloud CLI and the setup code on this computer "
    "act for you in your project, and do not give the Lagniappe maintainer "
    "access. Every requested permission is needed to configure, verify, or "
    "deploy your installation."
)


# @testable false
# @covered-by installer/create_config.py::verify_application_config
# @reason small typed-failure adapter exercised through configuration validation
def _fail(message="Setup configuration failed."):
    raise SetupError(message)


# @testable false
# @covered-by installer/create_config.py::_adc_auth_transaction
# @reason platform-specific Cloud SDK credential location owned by ADC rollback
def _adc_credentials_path():
    override = str(os.environ.get("CLOUDSDK_CONFIG") or "").strip()
    if override:
        return Path(override).expanduser() / "application_default_credentials.json"
    if os.name == "nt":
        app_data = str(os.environ.get("APPDATA") or "").strip()
        if app_data:
            return Path(app_data) / "gcloud" / "application_default_credentials.json"
    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_authentication_is_kept_only_after_project_permission_confirmation
# @features setup
# @dimensions adc transactional-state permissions
class _AdcCredentialTransaction:
    """Restore or remove ADC when setup cannot confirm the selected operator."""

    def __init__(self, path=None):
        self.path = Path(path or _adc_credentials_path())
        self.captured = False
        self.previous = None
        self.committed = False
        self.refresh_required = False

    def capture(self):
        if self.captured:
            return
        self.captured = True
        self.previous = self.path.read_bytes() if self.path.is_file() else None

    def reject_current(self):
        if not self.captured:
            self.captured = True
            self.previous = None

    def commit(self):
        self.committed = True
        self.previous = None

    def rollback(self):
        if self.committed or not self.captured:
            return
        if self.previous is None:
            self.path.unlink(missing_ok=True)
            print(
                wrap_text(
                    "ADC validation failed; removed the unconfirmed Application "
                    "Default Credentials so the next setup run will reopen "
                    "authentication."
                )
            )
            return

        from config import _atomic_write_text

        _atomic_write_text(
            self.path,
            self.previous.decode("utf-8"),
            owner_only=True,
        )
        print(
            wrap_text(
                "ADC validation failed; restored the Application Default "
                "Credentials that were present before setup authentication."
            )
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_authentication_is_kept_only_after_project_permission_confirmation
# @features setup
# @dimensions adc transactional-state permissions
@contextmanager
def _adc_auth_transaction():
    global _ACTIVE_ADC_TRANSACTION

    transaction = _AdcCredentialTransaction()
    previous = _ACTIVE_ADC_TRANSACTION
    _ACTIVE_ADC_TRANSACTION = transaction
    try:
        yield transaction
    except BaseException:
        transaction.rollback()
        raise
    else:
        transaction.rollback()
    finally:
        _ACTIVE_ADC_TRANSACTION = previous


# @testable false
# @covered-by installer/create_config.py::_adc_auth_transaction
# @reason transaction adapter invoked immediately before interactive gcloud auth
def _capture_adc_credentials():
    if _ACTIVE_ADC_TRANSACTION is not None:
        _ACTIVE_ADC_TRANSACTION.capture()


# @testable false
# @covered-by installer/create_config.py::_adc_auth_transaction
# @reason permission rejection adapter owned by the ADC transaction
def _reject_current_adc_credentials():
    if _ACTIVE_ADC_TRANSACTION is not None:
        _ACTIVE_ADC_TRANSACTION.reject_current()


# @testable false
# @covered-by installer/create_config.py::_adc_auth_transaction
# @reason permission confirmation adapter owned by the ADC transaction
def _commit_adc_credentials():
    if _ACTIVE_ADC_TRANSACTION is not None:
        _ACTIVE_ADC_TRANSACTION.commit()


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_config_status_save_and_gcloud_login_helpers
# @features setup
# @dimensions gcloud-config
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
# @covered-by installer/create_config.py::_gcloud_debug_value
# @reason console rendering for structured gcloud diagnostic values
def _display_gcloud_value(result):
    if result["state"] == GCLOUD_VALUE_SUCCESS:
        return result["value"]
    if result["state"] == GCLOUD_VALUE_UNSET:
        return "(unset)"
    return f"(error: {result['error']})"


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_config_status_save_and_gcloud_login_helpers
# @features setup
# @dimensions gcloud-config
def _adc_login_command(account, project_id, *, force=False):
    command = [GCLOUD_CLI, "auth", "application-default", "login"]
    if account and not force:
        command.append(account)
    if project_id:
        command.append(f"--project={project_id}")
    return format_command(command)


# @testable false
# @covered-by installer/create_config.py::_set_adc_quota_project
# @reason thin subprocess wrapper for interactive browser auth; parent owns fallback flow
def _run_adc_login(account, project_id=None, *, force=False):
    from installer import GCLOUD_CLI

    _capture_adc_credentials()
    command = [
        GCLOUD_CLI,
        "auth",
        "application-default",
        "login",
    ]
    if account and not force:
        command.append(account)
    if project_id:
        command.append(f"--project={project_id}")
    return subprocess.run(command, check=False, timeout=GCLOUD_TIMEOUT)


# @testable false
# @covered-by installer/create_config.py::_get_gcloud_account
# @reason provider lookup branch owned by gcloud account selection
def _get_current_account_email(credentials=None):
    """Resolve the ADC principal email from the credential's access token."""
    import google.auth
    from google.auth.transport.requests import Request
    from installer.utils import install_if_missing

    scopes = ["https://googleapis.com/auth/userinfo.email", "openid"]
    if credentials is None:
        credentials, _ = google.auth.default(scopes=scopes)

    if hasattr(credentials, "service_account_email"):
        return credentials.service_account_email
    if hasattr(credentials, "signer_email"):
        return credentials.signer_email

    install_if_missing("requests", "HTTP library for Python")
    import requests

    auth_request = Request()
    try:
        credentials.refresh(auth_request)
    except google.auth.exceptions.RefreshError:
        return None

    if credentials.token:
        response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": credentials.token},
            timeout=5,
        )
        if response.status_code == 200:
            return response.json().get("email")

    return None


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_identity_reports_principal_project_and_quota
# @features setup
# @dimensions gcloud-config adc
def _adc_identity():
    """Return a secret-free structured view of Application Default Credentials."""
    from installer.utils import install_if_missing

    install_if_missing(
        "google.auth", "Google authentication library", package_name="google-auth"
    )
    import google.auth

    try:
        credentials, project_id = google.auth.default(
            scopes=[
                "https://www.googleapis.com/auth/cloud-platform",
                "https://www.googleapis.com/auth/userinfo.email",
                "openid",
            ]
        )
        principal = _get_current_account_email(credentials)
        return {
            "state": "success",
            "principal": principal,
            "project": project_id,
            "quota_project": getattr(credentials, "quota_project_id", None),
            "error": None,
        }
    except Exception as error:
        return {
            "state": "error",
            "principal": None,
            "project": None,
            "quota_project": None,
            "error": str(error),
        }


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_config_status_save_and_gcloud_login_helpers
# @features setup
# @dimensions gcloud-config
def _get_gcloud_account(account):
    from installer import FORMATTER
    from runner.gcloud import check_account_authentication
    from installer.utils import install_if_missing

    install_if_missing(
        "google.auth", "Google authentication library", package_name="google-auth"
    )
    import google.auth

    f = FORMATTER.initialize()

    if account:
        check_account_authentication(account)
        return account

    configured_account = _gcloud_debug_value(["config", "get-value", "account"])
    if configured_account["state"] == GCLOUD_VALUE_SUCCESS:
        account = configured_account["value"]
        check_account_authentication(account)
        return account
    if configured_account["state"] == GCLOUD_VALUE_ERROR:
        print(
            f.error(
                "Could not determine the active gcloud CLI account: "
                f"{configured_account['error']}"
            )
        )
        _fail()

    try:
        run_gcloud_command(["auth", "list"])
    except subprocess.CalledProcessError:
        login_command = format_command([GCLOUD_CLI, "auth", "login"])
        print(f.error(f"Not logged into gcloud. Run {login_command} first."))
        _fail()
    except google.auth.exceptions.DefaultCredentialsError:
        adc_command = format_command(
            [GCLOUD_CLI, "auth", "application-default", "login"]
        )
        print(
            f.error(
                "Application Default Credentials (ADC) not found.\n"
                f"Please run {adc_command} to set them up.\n"
                "ADC is required for the script to create and manage Google Cloud resources."
            )
        )
        _fail()
    except Exception as e:
        print(f.error(f"Authentication error: {e}"))
        _fail()

    account = input(
        f.info("Enter the authenticated gcloud CLI account to use: ")
    ).strip()
    if not account:
        print("Exiting installer.")
        raise SetupCancelled("Setup cancelled during account selection.")
    check_account_authentication(account)

    return account


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_project_id_selection_uses_unique_confirmed_candidate
# @features setup
# @dimensions project-id interactive-input
def _suggest_project_id(sanitized_app_name):
    base = re.sub(r"[^a-z0-9-]", "-", sanitized_app_name.lower()).strip("-")
    if not base or not base[0].isalpha():
        base = f"lagniappe-{base}".strip("-")
    base = re.sub(r"-+", "-", base)[:23].rstrip("-")
    return f"{base}-{secrets.token_hex(3)}"


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_validate_project_id_and_project_state_are_non_mutating
# @features setup
# @dimensions project-id
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
# @tests tests_tooling/test_001a_setup_validation_config.py::test_project_id_selection_uses_unique_confirmed_candidate
# @features setup
# @dimensions project-id interactive-input
def _confirm_project_candidate(project_id, state, formatter):
    if state["state"] == "unavailable":
        print(
            formatter.error(
                f"Could not validate project {project_id}: {state['error']}"
            )
        )
        return False

    if state["state"] == "available":
        action = "Use the existing"
    else:
        action = "Create a new"
    answer = input(
        formatter.info(f"{action} project '{project_id}'? [y/N]: ")
    ).strip()
    if answer.lower() in ("y", "yes"):
        return True
    if state["state"] == "available":
        return False
    raise SetupCancelled("Installation cancelled during project selection.")


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_project_id_selection_uses_unique_confirmed_candidate
# @features setup
# @dimensions project-id interactive-input
def _get_gcloud_project(project_id, sanitized_app_name):
    from installer import FORMATTER

    f = FORMATTER.initialize()
    configured_project = _gcloud_debug_value(["config", "get-value", "project"])

    if project_id:
        if not validate_project_id(project_id):
            print(f.error(f"Saved project ID is invalid: {project_id}"))
            _fail()
        return project_id

    if configured_project["state"] == GCLOUD_VALUE_ERROR:
        print(
            f.error(
                "Could not determine the active gcloud project: "
                f"{configured_project['error']}"
            )
        )
        _fail()

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

    suggestion = _suggest_project_id(sanitized_app_name)
    while True:
        entered = input(
            f.info(
                "Press Enter to use the suggested Google Cloud project ID "
                f"[{suggestion}], or type a different project ID: "
            )
        ).strip()
        candidate = entered or suggestion
        if not validate_project_id(candidate):
            continue
        state = _project_state(candidate)
        if _confirm_project_candidate(candidate, state, f):
            return candidate


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
# @features setup
# @dimensions project-id
def validate_project_id(project_id):
    """Validate the provider's project-ID syntax without mutating state."""
    if not PROJECT_ID_PATTERN.fullmatch(str(project_id or "")):
        print(
            wrap_text(
                "Invalid project ID format. Must be 6-30 lowercase letters, "
                "numbers, or hyphens, starting with a letter."
            )
        )
        return False

    return True


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_new_project_forces_transactional_adc_refresh
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_refreshes_adc_login_after_quota_failure
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_exits_when_adc_login_refresh_fails
# @features setup
# @dimensions gcloud-config
def _set_adc_quota_project(project_id, sp):
    from installer import FORMATTER
    from config import SETTINGS

    f = FORMATTER.initialize()
    account = SETTINGS.GCLOUD_CONFIG["ACCOUNT"]
    adc_refreshed = False

    # @testable false
    # @covered-by installer/create_config.py::_set_adc_quota_project
    # @reason local retry closure; quota-project behavior is owned by the parent
    def refresh_adc(reason, *, force=False):
        nonlocal adc_refreshed
        sp.write(f.warning(reason))
        sp.write(f.warning(GOOGLE_AUTH_PERMISSION_GUIDANCE))
        sp.write("Opening browser to authenticate ADC with the selected CLI account:")
        sp.write(
            f"  {_adc_login_command(account, project_id, force=force)}"
        )

        stop_spinner = getattr(sp, "stop", None)
        if callable(stop_spinner):
            stop_spinner()
        try:
            if force:
                adc_login_result = _run_adc_login(
                    account,
                    project_id,
                    force=True,
                )
            else:
                adc_login_result = _run_adc_login(account, project_id)
        finally:
            start_spinner = getattr(sp, "start", None)
            if callable(start_spinner):
                start_spinner()

        if adc_login_result.returncode != 0:
            sp.write(f.error("ADC login did not complete."))
            sp.write(
                "Setup could not refresh Application Default Credentials automatically."
            )
            sp.fail(f.fail_glyph)
            _fail()
        adc_refreshed = True

    new_project_refresh = False
    if (
        _ACTIVE_ADC_TRANSACTION is not None
        and _ACTIVE_ADC_TRANSACTION.refresh_required
    ):
        _ACTIVE_ADC_TRANSACTION.refresh_required = False
        new_project_refresh = True
        refresh_adc(
            "A new project was selected. Refreshing Application Default "
            "Credentials for this installation.",
            force=True,
        )

    quota_project_command = [
        "auth",
        "application-default",
        "set-quota-project",
        project_id,
        "--quiet",
    ]
    sp.write(f.info(f"Setting ADC quota project to '{project_id}'..."))
    quota_project_result = run_gcloud_command(
        quota_project_command,
        check=False,
        timeout=ADC_QUOTA_TIMEOUT,
    )
    if quota_project_result.returncode != 0 and new_project_refresh:
        for delay in ADC_PROJECT_PROPAGATION_DELAYS:
            sp.write(
                f.info(
                    "The new project is still becoming available to ADC; "
                    f"retrying in {delay} seconds..."
                )
            )
            time.sleep(delay)
            quota_project_result = run_gcloud_command(
                quota_project_command,
                check=False,
                timeout=ADC_QUOTA_TIMEOUT,
            )
            if quota_project_result.returncode == 0:
                break

    if quota_project_result.returncode != 0:
        detail = (
            quota_project_result.stderr or quota_project_result.stdout or ""
        ).strip()
        if adc_refreshed:
            sp.write(
                f.error(
                    "The selected project did not become available to ADC in "
                    "time. Run setup again to resume."
                )
            )
            if detail:
                sp.write(f.warning(detail.splitlines()[0]))
            sp.fail(f.fail_glyph)
            _fail()

        if detail:
            sp.write(f.warning(f"ADC quota command returned: {detail}"))
        refresh_adc(
            "ADC is separate from the active gcloud CLI login and could not "
            "use the selected quota project."
        )

        sp.write(f.info("Retrying the ADC quota project after authentication..."))
        quota_project_result = run_gcloud_command(
            quota_project_command,
            check=False,
            timeout=ADC_QUOTA_TIMEOUT,
        )
        if quota_project_result.returncode != 0:
            sp.write(
                f.error(
                    "ADC login completed, but setup still could not set the ADC quota project."
                )
            )
            sp.write(
                "Verify the selected account can access the project, then run setup again."
            )
            sp.fail(f.fail_glyph)
            _fail()

    sp.write(f.info("Reading the local ADC identity..."))
    identity = _adc_identity()
    mismatches = []
    if identity["state"] != "success":
        mismatches.append(identity["error"] or "ADC unavailable")
    else:
        if (identity["principal"] or "").casefold() != account.casefold():
            mismatches.append(
                f"principal={identity['principal'] or '(unknown)'}"
            )
        if identity["project"] != project_id:
            mismatches.append(
                f"project={identity['project'] or '(unset)'}"
            )
        if identity["quota_project"] != project_id:
            mismatches.append(
                f"quota_project={identity['quota_project'] or '(unset)'}"
            )

    if mismatches:
        refresh_adc(
            "ADC identity does not match the selected CLI account and target: "
            + ", ".join(mismatches)
        )
        sp.write(f.info("Rechecking the ADC quota project and identity..."))
        quota_project_result = run_gcloud_command(
            quota_project_command,
            check=False,
            timeout=ADC_QUOTA_TIMEOUT,
        )
        identity = _adc_identity()

    if (
        quota_project_result.returncode != 0
        or identity["state"] != "success"
        or (identity["principal"] or "").casefold() != account.casefold()
        or identity["project"] != project_id
        or identity["quota_project"] != project_id
    ):
        sp.write(
            f.error(
                "ADC still does not match the selected CLI account and target project."
            )
        )
        sp.fail(f.fail_glyph)
        _fail()

    return identity


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_principal_mismatch_requires_explicit_reauthentication
# @features setup
# @dimensions gcloud-config adc identity
def _ensure_adc_principal(account, project_id=None):
    """Authenticate ADC explicitly when it is not the selected CLI principal."""
    from installer import FORMATTER

    f = FORMATTER.initialize()
    identity = _adc_identity()
    if (
        identity["state"] == "success"
        and (identity["principal"] or "").casefold() == account.casefold()
    ):
        return identity

    actual = (
        identity["principal"]
        if identity["state"] == "success"
        else f"(error: {identity['error']})"
    )
    print(
        f.warning(
            "Application Default Credentials use a different principal. "
            f"CLI={account}; ADC={actual or '(unknown)'}."
        )
    )
    print(
        f.info(
            "Opening explicit ADC authentication for the selected CLI account:\n"
            f"  {_adc_login_command(account, project_id)}"
        )
    )
    print(f.warning(GOOGLE_AUTH_PERMISSION_GUIDANCE))
    result = _run_adc_login(account, project_id)
    if result.returncode != 0:
        print(f.error("ADC authentication did not complete."))
        _fail()

    identity = _adc_identity()
    if (
        identity["state"] != "success"
        or (identity["principal"] or "").casefold() != account.casefold()
    ):
        print(
            f.error(
                "ADC principal still does not match the selected gcloud CLI account."
            )
        )
        _fail()
    return identity


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_target_preflight_selects_billing_and_reports_required_apis
# @features setup
# @dimensions preflight billing provider-apis
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
# @features setup
# @dimensions billing interactive-input gcloud-config
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
                f"Using existing billing account {selected}: "
                f"{account.get('displayName') or '(unnamed)'}"
            )
        )
        return selected

    print(f.info("Accessible open billing accounts:"))
    for name, account in choices.items():
        print(f"  {name}: {account.get('displayName') or '(unnamed)'}")
    while True:
        selected = input(
            f.info("Billing account for this installation: ")
        ).strip()
        if selected in choices:
            return selected
        print(f.error("Enter one of the accessible billing account IDs shown above."))


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_project_billing_authorization_uses_existing_account_and_project_console
# @features setup
# @dimensions billing interactive-input browser
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
            "In Google Cloud, select 'Link a billing account' and choose your "
            f"existing billing account for project '{project_id}':\n  {url}"
        )
    )
    try:
        webbrowser.open_new_tab(url)
    except webbrowser.Error:
        pass

    while True:
        response = input(
            f.info(
                "After the existing billing account is linked, press Enter to "
                "continue (x to exit): "
            )
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
                f"Billing is not enabled for project '{project_id}' yet. "
                "Complete the Google Cloud page, then check again."
            )
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_target_preflight_selects_billing_and_reports_required_apis
# @tests tests_tooling/test_001a_setup_validation_config.py::test_target_preflight_defers_billing_discovery_until_new_project_exists
# @features setup
# @dimensions preflight billing provider-apis project-create
def _target_preflight(project_id):
    """Run read-only target, billing, and Service Usage checks."""
    from config import constants

    project = _project_state(project_id)
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
# @features setup
# @dimensions preflight project-create billing browser provider-apis
def _apply_target_preflight(project_id, preflight, project_ready=None):
    """Apply the already-confirmed project creation and billing mutations."""
    from config import constants
    from installer import FORMATTER

    f = FORMATTER.initialize()
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
                "Preparing Google Cloud project APIs. This may take up to "
                "5 minutes..."
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


# @testable false
# @covered-by installer/iam.py::require_operator_permissions
# @reason setup preflight adapter owned by the IAM permission reporter
def _require_operator_permissions(
    project_id,
    *,
    billing_account=None,
    require_billing_link=False,
):
    from installer.iam import require_operator_permissions

    return require_operator_permissions(
        project_id,
        billing_account=billing_account,
        require_billing_link=require_billing_link,
    )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_authentication_is_kept_only_after_project_permission_confirmation
# @features setup
# @dimensions adc transactional-state permissions
def _confirm_operator_permissions(
    project_id,
    *,
    billing_account=None,
    require_billing_link=False,
):
    try:
        missing = _require_operator_permissions(
            project_id,
            billing_account=billing_account,
            require_billing_link=require_billing_link,
        )
    except Exception:
        _reject_current_adc_credentials()
        raise
    _commit_adc_credentials()
    return missing


# @testable false
# @covered-by installer/create_config.py::set_application_defaults
# @reason secret-free console summary owned by the fresh-install confirmation flow
def _display_install_identity_summary(preflight, adc_identity):
    from config import SETTINGS

    print("\n=== Configuration ===")
    print(f"Active gcloud configuration: {SETTINGS.GCLOUD_CONFIG['NAME']}")
    print(f"Active gcloud CLI account: {SETTINGS.GCLOUD_CONFIG['ACCOUNT']}")
    if adc_identity.get("state") != "pending":
        print(f"ADC principal: {adc_identity.get('principal') or '(unknown)'}")
        print(f"ADC project: {adc_identity.get('project') or '(unset)'}")
        print(f"ADC quota project: {adc_identity.get('quota_project') or '(unset)'}")
    print(f"Target project: {SETTINGS.GCLOUD_CONFIG['PROJECT']}")
    print(
        f"Installer/provisioner: "
        f"{SETTINGS.APP.get('INSTALLER_EMAIL') or SETTINGS.GCLOUD_CONFIG['ACCOUNT']}"
    )
    print(
        f"Deployer: "
        f"{SETTINGS.APP.get('DEPLOYER_EMAIL') or SETTINGS.GCLOUD_CONFIG['ACCOUNT']}"
    )
    print(f"Application owner: {SETTINGS.APP.get('ADMIN_EMAIL') or '(not set)'}")
    runtime_email = SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
    if runtime_email:
        print(f"Runtime service account: {runtime_email}")
    else:
        planned_email = (
            f"{SETTINGS.GCLOUD_CONFIG['NAME']}@"
            f"{SETTINGS.GCLOUD_CONFIG['PROJECT']}.iam.gserviceaccount.com"
        )
        print(f"Runtime service account (planned): {planned_email}")
    print(
        "Required APIs already enabled: "
        f"{len(preflight['enabled_apis'])}; pending: {len(preflight['missing_apis'])}"
    )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_build_app_settings_refreshes_agent_access_defaults
# @features setup
# @dimensions config-files agent-access ai-defaults source-link
def _build_app_settings():
    from config import SETTINGS, constants

    SETTINGS.APP.pop("FIREBASE_CONFIG", None)
    unsupported = sorted(UNSUPPORTED_SETTING_KEYS.intersection(SETTINGS.APP))
    if unsupported:
        raise RuntimeError(
            "Current setup found unsupported settings: "
            + ", ".join(unsupported)
        )
    version = str(SETTINGS.NODE.get("version") or "").strip()
    if not version:
        raise RuntimeError("package.json must define the current application version.")
    app_engine_location = normalize_app_engine_location(
        SETTINGS.APP.get("APP_ENGINE_LOCATION")
        or constants.DEFAULT_APP_ENGINE_LOCATION
    )
    resource_region = normalize_resource_region(
        SETTINGS.APP.get("RESOURCE_REGION")
        or constants.DEFAULT_RESOURCE_REGION
    )
    planned_runtime_email = (
        f"{SETTINGS.GCLOUD_CONFIG['NAME']}@"
        f"{SETTINGS.GCLOUD_CONFIG['PROJECT']}.iam.gserviceaccount.com"
    )
    runtime_email = (
        SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
        or planned_runtime_email
    )
    internal_caller_email = (
        SETTINGS.APP.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL")
        or runtime_email
    )
    default_settings = {
        "CONFIG_KIND": CONFIG_KIND,
        "CONFIG_SCHEMA_VERSION": CONFIG_SCHEMA_VERSION,
        "GOOGLE_CLOUD_PROJECT": SETTINGS.GCLOUD_CONFIG["PROJECT"],
        "INSTALLER_EMAIL": SETTINGS.GCLOUD_CONFIG["ACCOUNT"],
        "DEPLOYER_EMAIL": SETTINGS.GCLOUD_CONFIG["ACCOUNT"],
        "ADMIN_EMAIL": (
            SETTINGS.APP.get("ADMIN_EMAIL")
            or SETTINGS.GCLOUD_CONFIG["ACCOUNT"]
        ),
        "VERSION": version,
        "GIBBERISH": SETTINGS.APP.get("GIBBERISH", secrets.token_hex(16)),
        "SECRET_KEY": SETTINGS.APP.get("SECRET_KEY", secrets.token_hex(32)),
        "AGENT_ACCESS_ENABLED": SETTINGS.APP.get(
            "AGENT_ACCESS_ENABLED", constants.DEFAULT_AGENT_ACCESS_ENABLED
        ),
        "AGENT_ACCESS_EMAIL": SETTINGS.APP.get("AGENT_ACCESS_EMAIL")
        or constants.DEFAULT_AGENT_ACCESS_EMAIL,
        "AGENT_ACCESS_NAME": SETTINGS.APP.get("AGENT_ACCESS_NAME")
        or constants.DEFAULT_AGENT_ACCESS_NAME,
        "AGENT_ACCESS_CODE": SETTINGS.APP.get("AGENT_ACCESS_CODE")
        or secrets.token_urlsafe(32),
        "APP_ENGINE_LOCATION": app_engine_location,
        "RESOURCE_REGION": resource_region,
        "OCR_LOCATION": SETTINGS.APP.get(
            "OCR_LOCATION", constants.DEFAULT_OCR_LOCATION
        ),
        "AI_MODEL": SETTINGS.APP.get("AI_MODEL", constants.DEFAULT_AI_MODEL),
        "AI_UTILITY_MODEL": SETTINGS.APP.get(
            "AI_UTILITY_MODEL", constants.DEFAULT_UTILITY_AI_MODEL
        ),
        "AI_IMAGE_MODEL": SETTINGS.APP.get(
            "AI_IMAGE_MODEL", constants.DEFAULT_AI_IMAGE_MODEL
        ),
        "AI_LOCATION": SETTINGS.APP.get("AI_LOCATION", constants.DEFAULT_AI_LOCATION),
        "ANALYTICS": SETTINGS.APP.get("ANALYTICS", constants.DEFAULT_ANALYTICS_ENABLED),
        "CAPTURE_ERRORS": SETTINGS.APP.get(
            "CAPTURE_ERRORS", constants.DEFAULT_ERROR_MONITORING_ENABLED
        ),
        "PUBLIC_MANUAL": SETTINGS.APP.get(
            "PUBLIC_MANUAL", constants.DEFAULT_PUBLIC_MANUAL
        ),
        "SOURCE_URL": SETTINGS.APP.get(
            "SOURCE_URL", constants.DEFAULT_SOURCE_URL
        ),
        "REDIS_TLS": SETTINGS.APP.get(
            "REDIS_TLS", constants.DEFAULT_REDIS_TLS_ENABLED
        ),
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": runtime_email,
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": internal_caller_email,
    }
    SETTINGS.APP.update(default_settings)


# @testable false
# @covered-by installer/create_config.py::_set_default_config
# @reason config-file build step owned by the default config creation flow
def _build_deploy_yaml():
    from config import constants, SETTINGS

    from config.deployment import apply_deployment_settings

    apply_deployment_settings()

    SETTINGS.DEPLOY["default_expiration"] = constants.DEFAULT_EXPIRATION
    SETTINGS.DEPLOY["handlers"] = copy.deepcopy(constants.APP_HANDLERS)
    runtime_email = str(
        SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip()
    if not runtime_email:
        raise RuntimeError(
            "RUNTIME_SERVICE_ACCOUNT_EMAIL is required before generating "
            "the App Engine deployment configuration."
        )
    SETTINGS.DEPLOY["service_account"] = runtime_email


# @testable false
# @covered-by installer/create_config.py::_set_default_config
# @reason config-file build step owned by the default config creation flow
def _build_dev_yaml():
    from config import SETTINGS, constants

    SETTINGS.DEV_CONFIG["SERVER_NAME"] = SETTINGS.DEV_CONFIG.get(
        "SERVER_NAME", constants.DEFAULT_SERVER_NAME
    )
    SETTINGS.DEV_CONFIG["SERVER_PORT"] = SETTINGS.DEV_CONFIG.get(
        "SERVER_PORT", constants.DEFAULT_DEV_PORT
    )
    SETTINGS.TEST_CONFIG["ADMIN_EMAIL"] = SETTINGS.TEST_CONFIG.get(
        "ADMIN_EMAIL", constants.DEFAULT_ADMIN_EMAIL
    )
    SETTINGS.TEST_CONFIG["ADMIN_NAME"] = SETTINGS.TEST_CONFIG.get(
        "ADMIN_NAME", constants.DEFAULT_ADMIN_NAME
    )
    SETTINGS.TEST_CONFIG["SERVER_NAME"] = SETTINGS.TEST_CONFIG.get(
        "SERVER_NAME", constants.DEFAULT_SERVER_NAME
    )
    SETTINGS.TEST_CONFIG["SERVER_PORT"] = SETTINGS.TEST_CONFIG.get(
        "SERVER_PORT", constants.DEFAULT_TEST_PORT
    )
    SETTINGS.TEST_CONFIG["PREFIX"] = SETTINGS.TEST_CONFIG.get(
        "PREFIX", constants.DEFAULT_TEST_PREFIX
    )


# @testable false
# @covered-by installer/create_config.py::_set_default_config
# @reason config-file build step owned by the default config creation flow
def _build_index_yaml():
    from config import SETTINGS, constants

    SETTINGS.INDEX.update(copy.deepcopy(constants.INDEX_YAML))


# @testable false
# @covered-by installer/create_config.py::_set_default_config
# @reason config-file build step owned by the default config creation flow
def _build_manifest():
    from config import SETTINGS, constants
    from runner.deploy import update_manifest

    for k, v in constants.MANIFEST.items():
        SETTINGS.MANIFEST[k] = SETTINGS.MANIFEST.get(k, v)

    update_manifest()


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_deep_copies_templates
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_generates_fresh_settings
# @features setup
# @dimensions config-files
def _set_default_config():
    from config import SETTINGS

    _build_app_settings()
    _build_deploy_yaml()
    _build_dev_yaml()
    _build_index_yaml()
    _build_manifest()
    SETTINGS.DEV.pop("setup_draft", None)

    SETTINGS.save()


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_update_config_sets_application_version_from_package
# @features setup
# @dimensions config-files config-version
def update_config():
    """Refresh generated config defaults and return the active package version."""
    from config import SETTINGS

    version = str(SETTINGS.NODE.get("version") or "").strip()
    if not version:
        raise RuntimeError("package.json must define the current application version.")
    SETTINGS.APP["VERSION"] = version
    _set_default_config()

    return version


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_app_name_validation_rejects_control_characters_and_long_names
# @features setup
# @dimensions validation app-name
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
# @features setup
# @dimensions gcloud-config identity
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


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_refreshes_adc_login_after_quota_failure
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_exits_when_adc_login_refresh_fails
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_persists_prompted_name_before_cloud_change
# @tests tests_tooling/test_001e_setup_orchestration.py::test_recovery_uses_saved_project_preserves_owner_and_verifies_before_dev_write
# @features setup
# @dimensions config-files interactive-input gcloud-config recovery
def set_application_defaults():
    with _adc_auth_transaction():
        return _set_application_defaults()


# @testable false
# @covered-by installer/create_config.py::set_application_defaults
# @reason installer implementation runs within the public ADC transaction boundary
def _set_application_defaults():
    from config import File, SETTINGS
    from config.recovery import (
        materialize_recovery_redis_ca,
        validate_recovery_document,
    )
    from installer import FORMATTER

    f = FORMATTER.initialize()
    recovery_mode = File.APP_SETTINGS_YAML.exists() and not File.DEV_YAML.exists()
    SETTINGS.RECOVERY_MODE = recovery_mode
    if recovery_mode:
        print(
            f.warning(
                "Recovery mode: found config/files/lagniappe_settings.yaml "
                "without config/files/lagniappe_dev.yaml. No provider or local "
                "configuration mutation will occur until the recovered target "
                "has been authenticated and verified."
            )
        )
        recovered = validate_recovery_document(SETTINGS.APP)
        SETTINGS.APP.clear()
        SETTINGS.APP.update(recovered)

    setup_draft = (
        {}
        if recovery_mode
        else getattr(SETTINGS, "DEV", {}).get("setup_draft") or {}
    )
    app_name = str(
        SETTINGS.APP.get("APP_NAME") or setup_draft.get("APP_NAME") or ""
    ).strip()
    gcloud_name = SETTINGS.GCLOUD_CONFIG.get("NAME", "")
    account = SETTINGS.GCLOUD_CONFIG.get("ACCOUNT", "")
    project_id = (
        SETTINGS.APP["GOOGLE_CLOUD_PROJECT"]
        if recovery_mode
        else SETTINGS.GCLOUD_CONFIG.get("PROJECT", "")
    )

    if not _validate_app_name(app_name):
        app_name = _get_app_name()
        SETTINGS.APP["APP_NAME"] = app_name
    else:
        SETTINGS.APP["APP_NAME"] = app_name
    if not _validate_app_name(app_name):
        print(f.error("A name is required for your Lagniappe installation."))
        _fail()

    sanitized_app_name = _gcloud_configuration_name(app_name)
    if gcloud_name != sanitized_app_name:
        SETTINGS.GCLOUD_CONFIG["NAME"] = sanitized_app_name

    SETTINGS.GCLOUD_CONFIG["ACCOUNT"] = _get_gcloud_account(account)
    selected_project = _get_gcloud_project(
        project_id, sanitized_app_name
    )
    if recovery_mode and selected_project != project_id:
        raise RuntimeError(
            "Recovery cannot retarget the saved installation to another project."
        )
    SETTINGS.GCLOUD_CONFIG["PROJECT"] = selected_project
    account = SETTINGS.GCLOUD_CONFIG["ACCOUNT"]
    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    if not recovery_mode:
        SETTINGS.DEV["setup_draft"] = {"APP_NAME": app_name}
        SETTINGS.save(File.DEV_YAML)

    from runner import gcloud as switcher

    switcher.config_gcloud()
    cli_identity = _active_cli_identity()
    expected_cli = {
        "configuration": SETTINGS.GCLOUD_CONFIG["NAME"],
        "account": SETTINGS.GCLOUD_CONFIG["ACCOUNT"],
        "project": project_id,
    }
    if cli_identity != expected_cli:
        raise RuntimeError(
            f"Active gcloud CLI identity mismatch: expected {expected_cli}, "
            f"found {cli_identity}"
        )

    preflight = _target_preflight(project_id)
    cli_identity = _active_cli_identity()
    if cli_identity != expected_cli:
        raise RuntimeError(
            f"Active gcloud CLI identity mismatch after target preflight: "
            f"expected {expected_cli}, found {cli_identity}"
        )
    SETTINGS._SETUP_ENABLED_GOOGLE_CLOUD_APIS = set(preflight["enabled_apis"])
    if recovery_mode and preflight["project"]["state"] != "available":
        raise RuntimeError(
            f"Recovery requires positive access to existing project '{project_id}'; "
            f"provider state was {preflight['project']['state']}."
        )
    if recovery_mode and not (
        preflight["project"].get("details") or {}
    ).get("projectNumber"):
        raise RuntimeError(
            "Recovery could not verify the target project number needed to "
            "cross-check Cloud Storage ownership."
        )
    SETTINGS.GCLOUD_CONFIG["BILLING_ACCOUNT"] = preflight["billing_account"]
    if preflight["project"]["state"] == "available":
        adc_identity = _ensure_adc_principal(account, project_id)
    else:
        adc_identity = {"state": "pending"}
        if _ACTIVE_ADC_TRANSACTION is not None:
            _ACTIVE_ADC_TRANSACTION.refresh_required = True

    # @testable false
    # @covered-by installer/create_config.py::set_application_defaults
    # @reason spinner closure for the parent install preflight sequence
    def align_target_adc():
        with f.yaspin(text=f.success("Verifying Google Cloud credentials")) as sp:
            identity = _set_adc_quota_project(project_id, sp)
            sp.ok(f.ok_glyph)
        with f.yaspin(text=f.success("Verifying project permissions")) as sp:
            _confirm_operator_permissions(
                project_id,
                billing_account=preflight["billing_account"],
                require_billing_link=(
                    bool(preflight["billing_account"])
                    and not preflight["billing_enabled"]
                ),
            )
            sp.ok(f.ok_glyph)
        return identity

    if preflight["project"]["state"] == "available":
        adc_identity = align_target_adc()

    if recovery_mode:
        from installer.recovery import verify_recovery_resources

        materialize_recovery_redis_ca(SETTINGS.APP)
        recovery_report = verify_recovery_resources(
            SETTINGS.APP,
            project_id,
            project_details=preflight["project"].get("details"),
        )
        print("\n=== Recovery provider discovery ===")
        for resource, observation in recovery_report.items():
            print(f"{resource}: {observation['state']}")

    _set_default_config()

    _display_install_identity_summary(preflight, adc_identity)
    confirmation = input(f.warning("Continue with installation? [y/N]: "))
    if confirmation.strip().lower() not in ("y", "yes"):
        print(f.info("Installation cancelled. Configuration files were preserved."))
        raise SetupCancelled("Installation cancelled.")

    _apply_target_preflight(
        project_id,
        preflight,
        project_ready=(
            align_target_adc
            if preflight["project"]["state"] in ("absent", "unverified")
            else None
        ),
    )
    SETTINGS._SETUP_ENABLED_GOOGLE_CLOUD_APIS = set(preflight["enabled_apis"])
    if (
        SETTINGS.GCLOUD_CONFIG.get("BILLING_ACCOUNT")
        != preflight["billing_account"]
    ):
        SETTINGS.GCLOUD_CONFIG["BILLING_ACCOUNT"] = preflight["billing_account"]
        SETTINGS.save(File.DEV_YAML)

    return True


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_application_config_reports_missing_areas
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_application_config_rejects_keyless_identity_mismatch
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_application_config_reports_invalid_redis_tls
# @features setup
# @dimensions config-files validation redis-tls keyless-config project-identity
def verify_application_config(upgrade=False):
    from installer import FORMATTER

    f = FORMATTER.initialize()

    from config import constants, SETTINGS

    required_settings = constants.REQUIRED_APPLICATION_SETTINGS
    missing_areas = list(
        dict.fromkeys(
            area
            for setting, area in required_settings.items()
            if SETTINGS.APP.get(setting) is None
        )
    )
    if "RUNTIME_SERVICE_ACCOUNT_EMAIL" in required_settings:
        runtime_email = str(
            SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
        ).strip().casefold()
        internal_caller_email = str(
            SETTINGS.APP.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL") or ""
        ).strip().casefold()
        project_id = str(
            SETTINGS.APP.get("GOOGLE_CLOUD_PROJECT") or ""
        ).strip()
        expected_suffix = f"@{project_id}.iam.gserviceaccount.com"
        if (
            runtime_email
            and internal_caller_email
            and (
                runtime_email != internal_caller_email
                or not runtime_email.endswith(expected_suffix)
            )
            and "Google Cloud keyless identity" not in missing_areas
        ):
            missing_areas.append("Google Cloud keyless identity")

    if "AUTH_EMAIL_CONFIG" in required_settings:
        from installer.auth_email import auth_email_config_matches

        if (
            SETTINGS.APP.get("AUTH_EMAIL_CONFIG") is not None
            and not auth_email_config_matches(
                SETTINGS.APP.get("AUTH_EMAIL_CONFIG")
            )
            and "Authentication email" not in missing_areas
        ):
            missing_areas.append("Authentication email")

    if SETTINGS.APP.get("REDIS_TLS"):
        from config.redis import (
            RedisTLSConfigurationError,
            redis_client_kwargs,
        )

        try:
            redis_client_kwargs(SETTINGS.APP)
        except RedisTLSConfigurationError:
            if "Redis transport security" not in missing_areas:
                missing_areas.append("Redis transport security")

    if missing_areas and not upgrade:
        message = "The application configuration is missing required settings.\n"
    else:
        message = "New features require additional settings.\n"

    if missing_areas:
        print(
            f.error(
                f"{message}"
                f"Missing configuration areas: {', '.join(missing_areas)}.\n"
                f"Run {setup_command()} to add the missing settings while preserving the current configuration."
            )
        )
        _fail()

    print(f.success("Application configuration verified."))
    return True
