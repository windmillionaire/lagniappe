from functools import wraps
import subprocess

from runner.console import format_prompt, wrap_text
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
                prompt_suffix = f" [{default_value}]: "
            else:
                prompt_suffix = " (x to exit): "

            if has_default:
                print(wrap_text("Press Enter to use the bracketed value; x to exit."))
            while True:
                value = input(format_prompt(f.info(f"{prompt}{prompt_suffix}")))
                if value.lower() == "x":
                    print(f.error(wrap_text("Setup cancelled.")))
                    raise SetupCancelled("Setup cancelled by the operator.")
                if not value and has_default:
                    value = default_value
                if not value and not allow_empty:
                    print(
                        f.error(wrap_text("Input cannot be empty. Please try again."))
                    )
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
            wrap_text(
                "ERROR: gcloud CLI not found. Please install and configure the Google Cloud SDK."
            )
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
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_legacy_upgrade_warning_can_cancel_before_provider_deploy
# @matrix setup : deploy failure gcloud-command progress
# @pairs migrations:deploy setup:legacy-upgrade setup:major-version
def deploy_to_app_engine(
    *,
    print_final_summary=True,
    upgrade_notice_handled=False,
    first_install=False,
):
    from config import SETTINGS
    from installer import FORMATTER
    from installer.upgrade_notice import (
        confirm_legacy_upgrade_deployment,
        legacy_upgrade_deploy_notice_required,
        print_post_upgrade_maintenance_steps,
    )
    from runner.deploy import deploy

    f = FORMATTER.initialize()
    legacy_upgrade_notice = (
        not upgrade_notice_handled and legacy_upgrade_deploy_notice_required(SETTINGS)
    )
    if legacy_upgrade_notice:
        target_version = str(
            SETTINGS.APP.get("VERSION") or SETTINGS.NODE.get("version") or ""
        ).strip()
        confirm_legacy_upgrade_deployment(f, target_version)

    print(
        wrap_text(
            "Deploying App Engine indexes and the application may take up to 10 minutes."
        )
    )
    with f.yaspin(text="Deploying application") as spinner:
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

    from installer.mcp import requested

    if requested(SETTINGS.APP):
        print(wrap_text(f"{f.ok_glyph} {f.success('MCP server is ready')}"))
    elif (SETTINGS.APP.get("REMOTE_MCP") or {}).get("resource"):
        print(wrap_text("External AI access is disabled."))

    from installer.monitoring import reconcile_memory_alert_after_deploy

    reconcile_memory_alert_after_deploy()

    custom_domain = str(SETTINGS.APP.get("CUSTOM_DOMAIN") or "").strip()
    if custom_domain:
        from installer.domain.gcp import wait_for_managed_certificate
        from installer.state import record_step

        record_step("verify custom-domain TLS certificate")
        wait_for_managed_certificate(custom_domain, announce_ready=first_install)

    if print_final_summary:
        print(wrap_text("Deployment complete!"))
        print_summary()
    if legacy_upgrade_notice:
        print_post_upgrade_maintenance_steps(f)
