"""Installer gcloud command execution and prerequisite checks."""

import subprocess

from runner import presentation as ui
from runner.presentation import output as print
from runner.console import wrap_text

from . import GCLOUD_CLI
from .errors import GCLOUD_TIMEOUT, SetupError, classify_provider_error


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_prerequisite_gcloud_and_deploy_helpers
# @pair setup:gcloud-command
def check_gcloud_cli():
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
def run_gcloud_command(command, check=True, timeout=GCLOUD_TIMEOUT):
    """Run a shell command and return the result."""
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
