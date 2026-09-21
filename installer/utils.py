from runner import presentation as ui
from runner.presentation import output as print, read_input as input
from functools import wraps

from runner.console import format_prompt, wrap_text
from .errors import SetupCancelled
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
            while True:
                value = input(format_prompt(
                    prompt, default=default_value if has_default else None,
                    hint="Enter to keep; x to exit" if has_default else "x to exit",
                ))
                if value.lower() == "x":
                    print(ui.status(wrap_text("Setup cancelled.")))
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


# @testable false
# @covered-by installer/deploy.py::deploy_to_app_engine
# @reason older upgrade processes reload utils after replacing source but retain their old caller
def deploy_to_app_engine(
    *,
    print_final_summary=True,
    upgrade_notice_handled=False,
    first_install=False,
):
    """Forward deployment from an upgrade process started on an older checkout."""
    from installer.deploy import deploy_to_app_engine as deploy

    return deploy(
        print_final_summary=print_final_summary,
        upgrade_notice_handled=upgrade_notice_handled,
        first_install=first_install,
    )
