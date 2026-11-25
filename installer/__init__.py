from typing import Self

import sys

from runner.console import (
    format_prompt,
    wrap_text,
)

from runner.presentation import Progress, error, info, output as print, success, warning

from runner.context import (
    GCLOUD_CLI,
    GIT_CLI,
    NODE_CLI,
    NPM_CLI,
    REPOSITORY_ROOT,
    format_command,
    project_virtualenv_active,
    setup_command,
    virtualenv_instructions,
)


def verify_python_version() -> None:
    """Require the Python minor used by the installer and deployed application."""
    if sys.version_info[:2] != (3, 14):
        from installer.errors import SetupError

        raise SetupError(
            f"Python 3.14 is required (you are running {sys.version}).",
            repair_action=virtualenv_instructions(),
        )


def verify_setup_runtime() -> None:
    """Require supported Python from this checkout's project virtualenv."""
    from installer.errors import SetupError

    verify_python_version()
    if not project_virtualenv_active():
        print("Setup must run from this checkout's project virtualenv.")
        print(virtualenv_instructions())
        raise SetupError("Setup must run from this checkout's project virtualenv.")


def config_file_status() -> dict[str, bool]:
    from config import File

    """Return expected config files and whether each one exists."""
    required = [File.APP_YAML, File.DEV_YAML, File.APP_SETTINGS_YAML]

    return {file.name: file.exists() for file in required}


class Formatter:
    """Bootstrap Rich once; formatting itself never changes dependencies."""

    _initialized = False
    progress = staticmethod(Progress)
    error = staticmethod(error)
    warning = staticmethod(warning)
    success = staticmethod(success)
    info = staticmethod(info)

    def initialize(self) -> Self:
        if not self._initialized:
            from installer.package_install import install_if_missing

            install_if_missing("rich", "portable setup presentation")
            self._initialized = True
        return self


FORMATTER = Formatter()
