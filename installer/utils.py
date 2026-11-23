from runner import presentation as ui
from runner.presentation import output as print, read_input as input
from collections.abc import Callable
from functools import wraps
from typing import Concatenate

from runner.console import format_prompt, wrap_text
from .errors import SetupCancelled
from .package_install import install_if_missing


def ensure_datastore_dependency() -> None:
    install_if_missing(
        "google.cloud.datastore",
        "Google Cloud Datastore client",
        package_name="google-cloud-datastore",
    )


def ensure_storage_dependency() -> None:
    install_if_missing(
        "google.cloud.storage",
        "Google Cloud Storage client",
        package_name="google-cloud-storage",
    )


def validate_input[**P, T](
    prompt: str,
    validation_fn: Callable[[str], object] | None = None,
    error_msg: str | None = None,
    allow_empty: bool = False,
    default: object = None,
) -> Callable[[Callable[Concatenate[str, P], T]], Callable[P, T]]:
    """Decorator factory for validated input with an optional Enter default."""

    def decorator(func: Callable[Concatenate[str, P], T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
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


def deploy_to_app_engine(
    *,
    print_final_summary: bool = True,
    upgrade_notice_handled: bool = False,
    first_install: bool = False,
) -> None:
    """Forward deployment from an upgrade process started on an older checkout."""
    from installer.deploy import deploy_to_app_engine as deploy

    return deploy(
        print_final_summary=print_final_summary,
        upgrade_notice_handled=upgrade_notice_handled,
        first_install=first_install,
    )
