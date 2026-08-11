"""Application Default Credentials alignment for repository-local commands."""

import os
import sys

from runner.context import GCLOUD_CLI, format_command, python_command
from runner.process import run_command


ADC_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
)
ADC_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_adc_identity_is_secret_free_and_project_bound
# @pairs setup:adc setup:identity setup:project-identity
# @pairs testing:adc testing:identity testing:project-identity
# @pairs development:adc development:identity development:project-identity
def read_adc_identity(
    *,
    auth_default=None,
    request_factory=None,
    token_lookup=None,
):
    """Return a secret-free view of the current Application Default Credentials."""
    if auth_default is None:
        import google.auth

        auth_default = google.auth.default

    try:
        credentials, project = auth_default(scopes=list(ADC_SCOPES))
        principal = (
            getattr(credentials, "service_account_email", None)
            or getattr(credentials, "signer_email", None)
        )
        if not principal:
            if request_factory is None:
                from google.auth.transport.requests import Request

                request_factory = Request
            credentials.refresh(request_factory())
            if credentials.token:
                if token_lookup is None:
                    import requests

                    token_lookup = requests.get
                response = token_lookup(
                    ADC_TOKEN_INFO_URL,
                    params={"access_token": credentials.token},
                    timeout=5,
                )
                if response.status_code == 200:
                    principal = response.json().get("email")

        return {
            "state": "success",
            "principal": str(principal or "").strip(),
            "project": str(project or "").strip(),
            "quota_project": str(
                getattr(credentials, "quota_project_id", None) or ""
            ).strip(),
        }
    except Exception as error:
        return {
            "state": "error",
            "principal": "",
            "project": "",
            "quota_project": "",
            "error": type(error).__name__,
        }


# @testable false
# @covered-by runner/adc.py::ensure_adc_target
# @reason ADC mismatch normalization is exercised through target verification
def _identity_mismatches(identity, *, principals, project):
    if identity.get("state") != "success":
        return ["ADC identity is unavailable"]

    mismatches = []
    principal = str(identity.get("principal") or "").casefold()
    if principal not in principals:
        mismatches.append(
            f"principal={identity.get('principal') or '(unknown)'}"
        )
    if identity.get("project") != project:
        mismatches.append(f"project={identity.get('project') or '(unset)'}")
    if identity.get("quota_project") != project:
        mismatches.append(
            f"quota_project={identity.get('quota_project') or '(unset)'}"
        )
    return mismatches


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_gcloud_source_login_refreshes_stale_token
# @features setup auth
# @dimensions gcloud-token interactive refresh
def ensure_gcloud_source_login(account, *, allow_login=None):
    """Verify that the saved gcloud account can mint a fresh access token."""
    token_check = run_command(
        [GCLOUD_CLI, "auth", "print-access-token", account],
        check=False,
        timeout=60,
    )
    if token_check.returncode == 0:
        return

    login_command = [GCLOUD_CLI, "auth", "login", account]
    allow_login = sys.stdin.isatty() if allow_login is None else allow_login
    if not allow_login:
        raise RuntimeError(
            f"The saved gcloud login for '{account}' cannot refresh an access "
            f"token. Run {format_command(login_command)} and retry."
        )

    print(
        f"The saved gcloud login for '{account}' needs to be refreshed; "
        "opening account authentication:"
    )
    print(f"  {format_command(login_command)}")
    result = run_command(
        login_command,
        check=False,
        capture_output=False,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError("The saved gcloud account login did not complete.")
    token_check = run_command(
        [GCLOUD_CLI, "auth", "print-access-token", account],
        check=False,
        timeout=60,
    )
    if token_check.returncode != 0:
        raise RuntimeError(
            "The saved gcloud account still cannot refresh an access token."
        )


# @testable false
# @covered-by runner/adc.py::ensure_adc_target
# @reason ordered gcloud selection is exercised through explicit local ADC alignment
def _select_gcloud_auth_target(account, project):
    print(f"Selecting gcloud account '{account}'...")
    run_command(
        [GCLOUD_CLI, "config", "set", "account", account],
        timeout=60,
    )
    ensure_gcloud_source_login(account, allow_login=True)
    print(f"[OK] Using gcloud account '{account}'")

    print(f"Selecting gcloud project '{project}'...")
    run_command(
        [GCLOUD_CLI, "config", "set", "project", project],
        timeout=60,
    )
    print(f"[OK] Using gcloud project '{project}'")


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_adc_alignment_reauthenticates_and_sets_quota_project
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_adc_auth_selects_account_then_project_before_login
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_local_adc_mismatch_directs_to_auth_command
# @tests tests_tooling/test_007_run_py_test_command.py::test_runner_adc_alignment_updates_only_stale_quota_project
# @pairs setup:adc setup:identity setup:project-identity setup:automatic-activation setup:quota-project
# @pairs testing:adc testing:identity testing:project-identity testing:automatic-activation testing:quota-project
# @pairs development:adc development:identity development:project-identity development:automatic-activation development:quota-project
# @pairs auth:adc auth:identity auth:project-identity auth:automatic-activation auth:quota-project
def ensure_adc_target(
    account,
    project,
    *,
    allowed_principals=(),
    allow_login=None,
    select_gcloud_target=False,
):
    """Align local ADC with the requested repository identity and project."""
    account = str(account or "").strip()
    project = str(project or "").strip()
    if not account or not project:
        raise RuntimeError("ADC alignment requires an account and project.")
    if not GCLOUD_CLI:
        raise RuntimeError("ADC alignment requires the gcloud CLI.")

    principals = {
        normalized.casefold()
        for value in (account, *allowed_principals)
        if (normalized := str(value or "").strip())
    }
    identity = read_adc_identity()
    principal = str(identity.get("principal") or "").casefold()
    needs_login = (
        identity.get("state") != "success"
        or principal not in principals
        or identity.get("project") != project
    )

    mismatches = _identity_mismatches(
        identity,
        principals=principals,
        project=project,
    )
    if not mismatches:
        print(
            f"[OK] Using Application Default Credentials "
            f"({identity['principal']}, {project})"
        )
        return identity

    if allowed_principals and allow_login is False:
        raise RuntimeError(
            "Application Default Credentials do not match this "
            f"checkout ({', '.join(mismatches)}). Run "
            f"{python_command('run.py', 'auth')} and retry."
        )

    login_command = [
        GCLOUD_CLI,
        "auth",
        "application-default",
        "login",
        account,
    ]
    login_command.append(f"--project={project}")
    if needs_login:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS overrides the saved repository "
                "account. Remove the override or point it at an allowed "
                f"identity for project '{project}'."
            )
        allow_login = sys.stdin.isatty() if allow_login is None else allow_login
        if not allow_login:
            hint = (
                python_command("run.py", "auth")
                if allowed_principals
                else format_command(login_command)
            )
            raise RuntimeError(
                "Application Default Credentials do not match this checkout. "
                f"Run {hint} and retry."
            )

        if select_gcloud_target:
            _select_gcloud_auth_target(account, project)
        print(
            "Application Default Credentials do not match this checkout; "
            "opening the saved account login:"
        )
        print(f"  {format_command(login_command)}")
        result = run_command(
            login_command,
            check=False,
            capture_output=False,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Application Default Credentials login did not complete."
            )

    quota_command = [
        GCLOUD_CLI,
        "auth",
        "application-default",
        "set-quota-project",
        project,
        "--quiet",
    ]
    if needs_login or identity.get("quota_project") != project:
        result = run_command(quota_command, check=False, timeout=60)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                "Could not set the Application Default Credentials quota "
                f"project to '{project}'"
                f"{f': {detail.splitlines()[0]}' if detail else ''}."
            )

    identity = read_adc_identity()
    mismatches = _identity_mismatches(
        identity,
        principals=principals,
        project=project,
    )
    if mismatches:
        raise RuntimeError(
            "Application Default Credentials still do not match this checkout: "
            + ", ".join(mismatches)
            + "."
        )

    print(
        f"[OK] Using Application Default Credentials "
        f"({identity['principal']}, {project})"
    )
    return identity
