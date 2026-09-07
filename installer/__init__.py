import os
import sys
from types import SimpleNamespace

from runner.console import (
    ProgressLabel,
    format_prompt,
    terminal_width,
    unstyle,
    wrap_text,
)

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
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_formatter_tracks_active_spinners
# @matrix setup : encoding portability
def _supports_unicode(stream, text):
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_formatter_tracks_active_spinners
# @tests tests_tooling/test_001k_setup_console.py::test_progress_modes
# @matrix setup : portability spinner
def _use_plain_progress(stream=None):
    """Animate only where the terminal can display and redraw a spinner safely."""
    stream = stream or sys.stdout
    return (
        os.name == "nt"
        or not stream.isatty()
        or os.environ.get("TERM", "").lower() == "dumb"
        or not _supports_unicode(stream, "⠋✔✗")
        or terminal_width() < 20
    )


# @testable false
# @covered-by installer/__init__.py::Formatter
# @reason non-TTY spinner adapter is exercised through formatter behavior
class _PlainSpinner:
    def __init__(self, text=""):
        self.text = unstyle(text or "")

    def __enter__(self):
        if self.text:
            print(wrap_text(self.text))
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write(self, message):
        print(message)

    def ok(self, glyph="[OK]"):
        print(wrap_text(f"{glyph} {self.text}"))

    def fail(self, glyph="[X]"):
        print(wrap_text(f"{glyph} {self.text}"))

    def start(self):
        return self

    def stop(self):
        return self


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
    _initialized = False

    def initialize(self):
        if self._initialized:
            return self

        from installer.package_install import install_if_missing, track_spinner_factory

        install_if_missing("yaspin", "progress indicator for the setup script")
        install_if_missing("colorama", "colorizes setup script output")

        import colorama

        colorama.just_fix_windows_console()
        color_enabled = (
            sys.stdout.isatty()
            and "NO_COLOR" not in os.environ
            and os.environ.get("TERM", "").lower() != "dumb"
        )

        if color_enabled:
            self.Fore = colorama.Fore
            self.Style = colorama.Style
        else:
            self.Fore = SimpleNamespace(RED="", YELLOW="", GREEN="", CYAN="")
            self.Style = SimpleNamespace(RESET_ALL="")
        from yaspin import yaspin

        def portable_yaspin(*args, **kwargs):
            if _use_plain_progress():
                text = kwargs.get("text", args[0] if args else "")
                return _PlainSpinner(text)
            if "text" in kwargs:
                kwargs["text"] = ProgressLabel(kwargs["text"])
            return yaspin(*args, **kwargs)

        self.yaspin = track_spinner_factory(portable_yaspin)
        if _supports_unicode(sys.stdout, "✔✗"):
            self.ok_glyph = "✔"
            self.fail_glyph = "✗"
        else:
            self.ok_glyph = "[OK]"
            self.fail_glyph = "[X]"
        self._initialized = True
        return self

    def error(self, message, error=None):
        heading = f"{self.Fore.RED}{message}{self.Style.RESET_ALL}"
        return f"{heading}\n{error}" if error else heading

    def warning(self, message):
        return f"{self.Fore.YELLOW}{message}{self.Style.RESET_ALL}"

    def success(self, message):
        return f"{self.Fore.GREEN}{message}{self.Style.RESET_ALL}"

    def info(self, message):
        return f"{self.Fore.CYAN}{message}{self.Style.RESET_ALL}"


FORMATTER = Formatter()
