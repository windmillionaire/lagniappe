from functools import wraps
import subprocess

from . import GCLOUD_CLI
from .errors import (
    GCLOUD_TIMEOUT,
    SetupCancelled,
    SetupError,
    classify_provider_error,
)
from .package_install import install_if_missing


# @testable false
# @covered-by installer/image.py::get_images
# @covered-by installer/upgrade.py::_update_custom_images
# @covered-by installer/upgrade.py::_update_deployment_settings
# @reason shared dependency guard exercised through image/deployment restore flows
def ensure_datastore_dependency():
    install_if_missing(
        "google.cloud.datastore",
        "Google Cloud Datastore client",
        package_name="google-cloud-datastore",
    )


# @testable false
# @covered-by installer/image.py::save_images
# @covered-by installer/upgrade.py::_update_custom_images
# @reason shared dependency guard exercised through image restore flows
def ensure_storage_dependency():
    install_if_missing(
        "google.cloud.storage",
        "Google Cloud Storage client",
        package_name="google-cloud-storage",
    )


# @testable false
# @covered-by installer/utils.py::deploy_to_app_engine
# @reason console-only installation summary
def print_summary():
    from config import SETTINGS
    from installer.summary import print_install_summary

    print_install_summary(
        SETTINGS.APP,
        deploy=SETTINGS.DEPLOY,
        node=SETTINGS.NODE,
        gcloud_config=SETTINGS.GCLOUD_CONFIG,
        deployed=True,
    )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_validate_input_retries_allows_empty_and_exits
# @pair setup:interactive-input
def validate_input(
    prompt,
    validation_fn=None,
    error_msg=None,
    allow_empty=False,
    default=None,
):
    """Decorator factory for validated input with an optional Enter default."""

    # @testable false
    # @covered-by installer/utils.py::validate_input
    # @reason closure returned by the validate_input decorator factory
    def decorator(func):
        # @testable false
        # @covered-by installer/utils.py::validate_input
        # @reason interactive retry loop exercised through validate_input
        @wraps(func)
        def wrapper(*args, **kwargs):
            from installer import FORMATTER

            f = FORMATTER.initialize()
            has_default = default not in (None, "")
            default_value = str(default).strip() if has_default else ""
            if has_default:
                prompt_suffix = (
                    f" [{default_value}] "
                    "(press Enter to use the bracketed value; x to exit): "
                )
            else:
                prompt_suffix = " (x to exit): "

            while True:
                value = input(f.info(f"{prompt}{prompt_suffix}"))
                if value.lower() == "x":
                    print(f.error("Setup cancelled."))
                    raise SetupCancelled("Setup cancelled by the operator.")
                if not value and has_default:
                    value = default_value
                if not value and not allow_empty:
                    print(f.error("Input cannot be empty. Please try again."))
                    continue
                if validation_fn and not validation_fn(value):
                    print(f.error(error_msg or "Invalid input. Please try again."))
                    continue
                return func(value, *args, **kwargs)

        return wrapper

    return decorator


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_prerequisite_gcloud_and_deploy_helpers
# @pair setup:gcloud-command
def check_gcloud_cli():
    if not GCLOUD_CLI:
        print(
            "ERROR: gcloud CLI not found. Please install and configure the Google Cloud SDK."
        )
        raise SetupError(
            "gcloud CLI not found. Install the Google Cloud CLI and retry."
        )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_prerequisite_gcloud_and_deploy_helpers
# @pair setup:gcloud-command
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


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_prerequisite_gcloud_and_deploy_helpers
# @matrix setup : deploy failure gcloud-command progress
def deploy_to_app_engine(*, print_final_summary=True):
    from config import SETTINGS
    from installer import FORMATTER
    from runner.deploy import deploy

    f = FORMATTER.initialize()
    progress = f.success(
        "Deploy App Engine indexes and application "
        "(may take up to 10 minutes)"
    )
    with f.yaspin(text=progress) as spinner:
        try:
            deploy(
                build_assets=False,
                deploy_indexes=True,
                quiet=True,
                capture_output=True,
                announce_progress=False,
                announce_completion=False,
            )
        except Exception:
            spinner.fail(f.fail_glyph)
            raise
        spinner.ok(f.ok_glyph)

    custom_domain = str(SETTINGS.APP.get("CUSTOM_DOMAIN") or "").strip()
    if custom_domain:
        from installer.domain.gcp import wait_for_managed_certificate
        from installer.state import record_step

        record_step("verify custom-domain TLS certificate")
        wait_for_managed_certificate(custom_domain)

    if print_final_summary:
        print("Deployment complete!")
        print_summary()
