"""Repository-local paths and external tools shared by setup and runners."""

from pathlib import Path
from types import MappingProxyType
import os
import shlex
import shutil
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PROJECT_VIRTUALENV = REPOSITORY_ROOT / "venv"
TOOL_PATHS = MappingProxyType(
    {
        name: shutil.which(name)
        for name in (
            "gcloud",
            "git",
            "node",
            "npm",
        )
    }
)
GCLOUD_CLI = TOOL_PATHS["gcloud"]
GIT_CLI = TOOL_PATHS["git"]
NODE_CLI = TOOL_PATHS["node"]
NPM_CLI = TOOL_PATHS["npm"]


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_portable_runtime_paths_commands_and_virtualenv_instructions
# @features setup
# @dimensions portability repository-root virtualenv
def project_virtualenv_active(*, prefix=None, base_prefix=None):
    """Return whether Python is running from this checkout's ``venv``."""
    prefix = Path(prefix or sys.prefix)
    base_prefix = Path(
        base_prefix
        if base_prefix is not None
        else getattr(sys, "base_prefix", sys.prefix)
    )
    if os.path.normcase(os.path.abspath(prefix)) == os.path.normcase(
        os.path.abspath(base_prefix)
    ):
        return False
    return os.path.normcase(os.path.abspath(prefix)) == os.path.normcase(
        os.path.abspath(PROJECT_VIRTUALENV)
    )


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_portable_runtime_paths_commands_and_virtualenv_instructions
# @features setup
# @dimensions portability generated-command
def format_command(command, *, windows=None):
    """Render an argument-list command for the operator's supported shell."""
    command = [str(part) for part in command]
    windows = os.name == "nt" if windows is None else windows
    return subprocess.list2cmdline(command) if windows else shlex.join(command)


# @testable false
# @covered-by runner/context.py::setup_command
# @reason generic adapter is exercised through generated setup commands
def python_command(script, *arguments, windows=None):
    """Return an exact current-Python repository command."""
    return format_command(
        [sys.executable, REPOSITORY_ROOT / script, *arguments],
        windows=windows,
    )


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_portable_runtime_paths_commands_and_virtualenv_instructions
# @features setup
# @dimensions portability generated-command
def setup_command(*arguments, windows=None):
    """Return the supported setup launcher invocation for the user's platform."""
    windows = os.name == "nt" if windows is None else windows
    launcher = r".\setup.cmd" if windows else "./setup.sh"
    return format_command([launcher, *arguments], windows=windows)


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_portable_runtime_paths_commands_and_virtualenv_instructions
# @features setup
# @dimensions portability virtualenv instructions
def virtualenv_instructions():
    """Return both supported environment-bootstrap/setup command forms."""
    return (
        "macOS/Linux terminal:\n"
        "  ./setup.sh\n"
        "Windows PowerShell:\n"
        "  .\\setup.cmd\n"
        "Windows Command Prompt:\n"
        "  setup.cmd"
    )
