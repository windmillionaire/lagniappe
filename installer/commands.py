"""Installer gcloud command execution and prerequisite checks."""

import subprocess
from typing import Literal, Never, overload

from runner import presentation as ui
from runner.presentation import output as print
from runner.console import wrap_text

from . import GCLOUD_CLI
from .errors import GCLOUD_TIMEOUT, SetupError, classify_provider_error


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_prerequisite_gcloud_and_deploy_helpers
# @pair setup:gcloud-command
def check_gcloud_cli() -> None:
    if not GCLOUD_CLI:
        print(
            ui.error(wrap_text(
                "gcloud CLI not found. Please install and configure the Google Cloud SDK."
            ))
        )
        raise SetupError(
            "gcloud CLI not found. Install the Google Cloud CLI and retry."
        )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_prerequisite_gcloud_and_deploy_helpers
# @pair setup:gcloud-command
# @pair setup:timeout
@overload
def run_gcloud_command(command: list[str], check: Literal[True] = True, timeout: float = GCLOUD_TIMEOUT) -> subprocess.CompletedProcess[str]: ...


@overload
def run_gcloud_command(command: list[str], check: bool, timeout: float = GCLOUD_TIMEOUT) -> subprocess.CompletedProcess[str] | subprocess.CalledProcessError: ...


def run_gcloud_command(
    command: list[str],
    check: bool = True,
    timeout: float = GCLOUD_TIMEOUT,
) -> subprocess.CompletedProcess[str] | subprocess.CalledProcessError:
    """Run a shell command and return the result."""
    if GCLOUD_CLI is None:
        raise SetupError("gcloud CLI not found. Install the Google Cloud CLI and retry.")
    try:
        result = subprocess.run(
            [GCLOUD_CLI] + command,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            check=check,
            timeout=timeout,
        )
        return result
    except subprocess.CalledProcessError as e:
        if check:
            raise classify_provider_error(
                e,
                message=(
                    f"gcloud {' '.join(command)} failed: "
                    f"{(e.stderr or '').strip() or e}"
                ),
            ) from e
        return e
    except subprocess.TimeoutExpired as error:
        raise classify_provider_error(
            error,
            message=f"gcloud {' '.join(command)} timed out after {timeout} seconds.",
        ) from error


GOOGLE_CLOUD_TERMS_URL = "https://console.developers.google.com/terms/cloud"


# @testable false
# @covered-by installer/create_config.py::verify_application_config
# @reason small typed-failure adapter exercised through configuration validation
def _fail(
    message: str = "Setup configuration failed.", *, repair_action: str | None = None
) -> Never:
    raise SetupError(message, repair_action=repair_action)


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_google_cloud_terms_failure_has_account_specific_repair
# @matrix setup : error-guidance google-cloud-terms
def _is_google_cloud_terms_error(detail: object) -> bool:
    """Recognize Google's account-level Cloud service-terms rejection."""
    normalized = str(detail or "").casefold()
    return any(
        marker in normalized
        for marker in (
            "ureq_tos_not_accepted",
            "tos_id=cloud",
            "terms of service 'cloud' must be accepted",
        )
    )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_google_cloud_terms_failure_has_account_specific_repair
# @matrix setup : error-guidance google-cloud-terms identity
def _google_cloud_terms_repair_action(account: str) -> str:
    """Return safe first-use guidance for the exact selected Cloud identity."""
    from runner.context import setup_command

    return (
        f"Sign in as '{account}' at {GOOGLE_CLOUD_TERMS_URL}, accept the "
        f"Google Cloud service terms, then rerun {setup_command()}."
    )
