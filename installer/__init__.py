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


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_python_runtime_gate_precedes_every_cli_mode
# @matrix setup : portability prerequisites python-version virtualenv
def verify_setup_runtime():
    """Require supported Python from this checkout's project virtualenv."""
    from installer.errors import SetupError

    if sys.version_info < (3, 12):
        print(
            f"Python 3.12 or higher is required (you are running {sys.version})."
        )
        print(virtualenv_instructions())
        raise SetupError("Python 3.12 or higher is required.")

    if not project_virtualenv_active():
        print("Setup must run from this checkout's project virtualenv.")
        print(virtualenv_instructions())
        raise SetupError("Setup must run from this checkout's project virtualenv.")


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_config_status_save_and_gcloud_login_helpers
# @pair setup:config-files
def config_file_status():
    from config import File

    """Return expected config files and whether each one exists."""
    required = [File.APP_YAML, File.DEV_YAML, File.APP_SETTINGS_YAML]

    return {file.name: file.exists() for file in required}


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_formatter_tracks_active_spinners
# @tests tests_tooling/test_001k_setup_console.py::test_formatter_preserves_plain_and_colored_output
# @matrix setup : package-install spinner
class Formatter:
    """Bootstrap Rich once; formatting itself never changes dependencies."""

    _initialized = False
    progress = staticmethod(Progress)
    error = staticmethod(error)
    warning = staticmethod(warning)
    success = staticmethod(success)
    info = staticmethod(info)

    def initialize(self):
        if not self._initialized:
            from installer.package_install import install_if_missing

            install_if_missing("rich", "portable setup presentation")
            self._initialized = True
        return self


FORMATTER = Formatter()
