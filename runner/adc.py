"""Application Default Credentials alignment for repository-local commands."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from runner import presentation as ui
from runner.console import wrap_text
from runner.context import GCLOUD_CLI, format_command, python_command, setup_command
from runner.presentation import output as print
from runner.process import run_command

if TYPE_CHECKING:
    from google.auth.credentials import Credentials
    from google.auth.transport.requests import Request
    from requests import Response


ADC_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
)
ADC_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def read_adc_identity(
    *,
    auth_default: Callable[..., tuple[Credentials, str | None]] | None = None,
    request_factory: Callable[[], Request] | None = None,
    token_lookup: Callable[..., Response] | None = None,
) -> dict[str, str]:
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


def ensure_gcloud_source_login(account: str, *, allow_login: bool = False) -> None:
    """Verify that the saved gcloud account can mint a fresh access token."""
    token_check = run_command(
        [GCLOUD_CLI or "gcloud", "auth", "print-access-token", account],
        check=False,
        timeout=60,
    )
    if token_check.returncode == 0:
        return

    login_command = [GCLOUD_CLI or "gcloud", "auth", "login", account, "--force"]
    if not allow_login:
        raise RuntimeError(
            f"The saved gcloud login for '{account}' needs to be refreshed. "
            "Setup stopped before making changes. Run "
            f"{setup_command('auth')}, then retry this setup command."
        )

    print(
        wrap_text(
            f"The saved gcloud login for '{account}' needs to be refreshed; "
            "opening account authentication:"
        )
    )
    print(f"  {ui.literal(format_command(login_command))}")
    result = run_command(
        login_command,
        check=False,
        capture_output=False,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError("The saved gcloud account login did not complete.")
    token_check = run_command(
        [GCLOUD_CLI or "gcloud", "auth", "print-access-token", account],
        check=False,
        timeout=60,
    )
    if token_check.returncode != 0:
        raise RuntimeError(
            "The saved gcloud account still cannot refresh an access token."
        )


def _select_gcloud_auth_target(account, project):
    print(wrap_text(f"Selecting gcloud account '{account}'..."))
    run_command(
        [GCLOUD_CLI or "gcloud", "config", "set", "account", account],
        timeout=60,
    )
    ensure_gcloud_source_login(account, allow_login=True)

    print(wrap_text(f"Selecting gcloud project '{project}'..."))
    run_command(
        [GCLOUD_CLI or "gcloud", "config", "set", "project", project],
        timeout=60,
    )


def ensure_adc_target(
    account: str,
    project: str,
    *,
    allowed_principals: Sequence[str | None] = (),
    allow_login: bool | None = None,
    select_gcloud_target: bool = False,
    announce: bool = True,
) -> dict[str, str]:
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
        if announce:
            print(ui.success("Application Default Credentials verified"))
            print(ui.value("Account", identity["principal"], column=10, verbatim=True))
            print(ui.value("Project", project, column=10, verbatim=True))
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
            wrap_text(
                "Application Default Credentials do not match this checkout; "
                "opening the saved account login:"
            )
        )
        print(f"  {ui.literal(format_command(login_command))}")
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

    if announce:
        print(ui.success("Application Default Credentials verified"))
        print(ui.value("Account", identity["principal"], column=10, verbatim=True))
        print(ui.value("Project", project, column=10, verbatim=True))
    return identity
