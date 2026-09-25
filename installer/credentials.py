"""Transactional installer ADC with explicit account, project and transaction.

The orchestrator decides when operator permissions justify committing credentials.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import time

from runner import presentation as ui
from runner.presentation import output as print
from runner.context import GCLOUD_CLI, format_command
from installer import wrap_text
from installer.setup_target import SetupTarget
from installer.commands import run_gcloud_command, _fail, _google_cloud_terms_repair_action
from installer.errors import GCLOUD_TIMEOUT

ADC_QUOTA_TIMEOUT = 60

ADC_PROJECT_PROPAGATION_DELAYS = (2, 4, 8, 15, 20)

ADC_LOGIN_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
)

GOOGLE_AUTH_PERMISSION_GUIDANCE = (
    "On Google's permission screen, choose Select all if it appears, then "
    "Continue or Allow. This authorizes setup on this computer; it does not "
    "give the Lagniappe maintainer access."
)


# @testable false
# @covered-by installer/credentials.py::_adc_auth_transaction
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
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_transaction_rolls_back_uncommitted_interruption
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_transaction_rejects_existing_credentials_and_keeps_committed_identity
# @matrix setup : adc permissions transactional-state
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
                ui.warning(wrap_text(
                    "ADC validation failed; removed the unconfirmed Application "
                    "Default Credentials so the next setup run will reopen "
                    "authentication."
                ))
            )
            return

        from config import _atomic_write_text

        _atomic_write_text(
            self.path,
            self.previous.decode("utf-8"),
            owner_only=True,
        )
        print(
            ui.warning(wrap_text(
                "ADC validation failed; restored the Application Default "
                "Credentials that were present before setup authentication."
            ))
        )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_authentication_is_kept_only_after_project_permission_confirmation
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_transaction_rolls_back_uncommitted_interruption
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_transaction_rejects_existing_credentials_and_keeps_committed_identity
# @matrix setup : adc permissions transactional-state
@contextmanager
def _adc_auth_transaction(path=None):
    transaction = _AdcCredentialTransaction(path)
    try:
        yield transaction
    finally:
        transaction.rollback()


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_config_status_save_and_gcloud_login_helpers
# @pair setup:gcloud-config
def _adc_login_command(account, project_id, *, force=False):
    command = [GCLOUD_CLI, "auth", "application-default", "login"]
    if account and not force:
        command.append(account)
    if project_id:
        command.append(f"--project={project_id}")
    command.append(f"--scopes={','.join(ADC_LOGIN_SCOPES)}")
    return format_command(command)


# @testable false
# @covered-by installer/credentials.py::_set_adc_quota_project
# @reason thin subprocess wrapper for interactive browser auth; parent owns fallback flow
def _run_adc_login(account, project_id=None, *, transaction, force=False):
    from installer import GCLOUD_CLI

    transaction.capture()
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
    command.append(f"--scopes={','.join(ADC_LOGIN_SCOPES)}")
    with ui.pause_progress():
        return subprocess.run(command, check=False, timeout=GCLOUD_TIMEOUT)


# @testable false
# @covered-by installer/credentials.py::_adc_identity
# @reason provider principal lookup owned by the ADC identity inspection
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
# @matrix setup : adc gcloud-config
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
# @tests tests_tooling/test_001a_setup_validation_config.py::test_new_project_forces_transactional_adc_refresh
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_refreshes_adc_login_after_quota_failure
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_exits_when_adc_login_refresh_fails
# @matrix setup : adc gcloud-config new-project transactional-state
def _set_adc_quota_project(target: SetupTarget, sp, *, transaction):
    from installer import FORMATTER

    f = FORMATTER.initialize()
    account, project_id = target.account, target.project_id
    adc_refreshed = False

    # @testable false
    # @covered-by installer/credentials.py::_set_adc_quota_project
    # @reason local retry closure; quota-project behavior is owned by the parent
    def refresh_adc(reason, *, force=False):
        nonlocal adc_refreshed
        sp.write(f.warning(reason))
        sp.write(f.warning(GOOGLE_AUTH_PERMISSION_GUIDANCE))
        sp.write(
            wrap_text(
                "Opening browser to authenticate ADC with the selected CLI account:"
            )
        )
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
                    transaction=transaction,
                )
            else:
                adc_login_result = _run_adc_login(account, project_id, transaction=transaction)
        finally:
            start_spinner = getattr(sp, "start", None)
            if callable(start_spinner):
                start_spinner()

        if adc_login_result.returncode != 0:
            sp.write(f.error(wrap_text("ADC login did not complete.")))
            sp.write(
                wrap_text(
                    "Setup could not refresh Application Default Credentials automatically."
                )
            )
            sp.fail()
            _fail(
                "ADC authentication did not complete.",
                repair_action=_google_cloud_terms_repair_action(account),
            )
        adc_refreshed = True

    new_project_refresh = False
    if transaction.refresh_required:
        transaction.refresh_required = False
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
    sp.write(f.info(wrap_text(f"Setting ADC quota project to '{project_id}'...")))
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
                    wrap_text(
                        "The selected project did not become available to ADC in "
                        "time. Run setup again to resume."
                    )
                )
            )
            if detail:
                sp.write(f.warning(detail.splitlines()[0]))
            sp.fail()
            _fail()

        refresh_adc(
            "ADC is separate from the active gcloud CLI login and could not "
            "use the selected quota project."
        )

        sp.write(
            f.info(wrap_text("Retrying the ADC quota project after authentication..."))
        )
        quota_project_result = run_gcloud_command(
            quota_project_command,
            check=False,
            timeout=ADC_QUOTA_TIMEOUT,
        )
        if quota_project_result.returncode != 0:
            detail = (
                quota_project_result.stderr
                or quota_project_result.stdout
                or ""
            ).strip()
            sp.write(
                f.error(
                    wrap_text(
                        "ADC login completed, but setup still could not set the ADC quota project."
                    )
                )
            )
            if detail:
                sp.write(
                    f.warning(
                        wrap_text(f"Google Cloud returned: {detail.splitlines()[0]}")
                    )
                )
            sp.write(
                wrap_text(
                    "Verify the selected account can access the project, then run setup again."
                )
            )
            sp.fail()
            _fail()

    sp.write(f.info(wrap_text("Reading the local ADC identity...")))
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
        sp.write(f.info(wrap_text("Rechecking the ADC quota project and identity...")))
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
                wrap_text(
                    "ADC still does not match the selected CLI account and target project."
                )
            )
        )
        sp.fail()
        _fail()

    return identity


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_principal_mismatch_requires_explicit_reauthentication
# @matrix setup : adc gcloud-config identity
def _ensure_adc_principal(target: SetupTarget, *, transaction):
    """Authenticate ADC explicitly when it is not the selected CLI principal."""
    account, project_id = target.account, target.project_id
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
            wrap_text(
                "Application Default Credentials use a different principal. "
                f"CLI={account}; ADC={actual or '(unknown)'}."
            )
        )
    )
    print(
        f.info(
            "Opening explicit ADC authentication for the selected CLI account:\n"
            f"  {_adc_login_command(account, project_id)}"
        )
    )
    print(f.warning(GOOGLE_AUTH_PERMISSION_GUIDANCE))
    result = _run_adc_login(account, project_id, transaction=transaction)
    if result.returncode != 0:
        print(f.error(wrap_text("ADC authentication did not complete.")))
        _fail(
            "ADC authentication did not complete.",
            repair_action=_google_cloud_terms_repair_action(account),
        )

    identity = _adc_identity()
    if (
        identity["state"] != "success"
        or (identity["principal"] or "").casefold() != account.casefold()
    ):
        print(
            f.error(
                wrap_text(
                    "ADC principal still does not match the selected gcloud CLI account."
                )
            )
        )
        _fail()
    return identity

