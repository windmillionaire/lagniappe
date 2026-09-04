"""Add development tooling to an existing Lagniappe installation."""

import os
import re
import subprocess
import sys

from runner.context import (
    NODE_CLI,
    NPM_CLI,
    REPOSITORY_ROOT,
    python_command,
    setup_command,
)
from installer import config_file_status, virtualenv_instructions, wrap_text
from installer.errors import NPM_TIMEOUT, PIP_TIMEOUT, PLAYWRIGHT_TIMEOUT


APP_ROOT = REPOSITORY_ROOT
NODE_ENGINE_RANGE = "^22.18.0 || >=24.11.0"
_NODE_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_REQUIRED_INSTALLATION_FILES = (
    "APP_YAML",
    "DEV_YAML",
    "APP_SETTINGS_YAML",
)


# @testable false
# @covered-by installer/development.py::setup_development
# @reason platform branch is exercised through the development setup entrypoint
def _native_windows():
    return os.name == "nt"


# @testable false
# @covered-by installer/development.py::setup_development
# @reason virtualenv enforcement is exercised through the development setup entrypoint
def _in_virtualenv():
    return bool(
        getattr(sys, "real_prefix", None)
        or sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    )


# @testable false
# @covered-by installer/development.py::setup_development
# @reason installation prerequisite reporting is exercised through the development setup entrypoint
def _missing_installation_files():
    status = config_file_status()
    return [name for name in _REQUIRED_INSTALLATION_FILES if not status.get(name)]


# @testable false
# @covered-by installer/development.py::setup_development
# @reason Node discovery is exercised through the development setup entrypoint
def _installed_node_version():
    result = subprocess.run(
        [NODE_CLI, "--version"],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_development_setup_validates_node_range
# @matrix setup : development node-version
def node_version_supported(version):
    """Return whether a Node version satisfies the project's engine floor."""
    match = _NODE_VERSION_PATTERN.match(str(version).strip())
    if not match:
        return False

    parsed = tuple(int(part) for part in match.groups())
    if parsed[0] == 22:
        return parsed >= (22, 18, 0)
    return parsed >= (24, 11, 0)


# @testable false
# @covered-by installer/development.py::setup_development
# @reason subprocess sequencing and failures are exercised through the development setup entrypoint
def _run_command(label, command, timeout=None):
    print(f"\n{label}")
    if timeout is None:
        if "playwright" in command:
            timeout = PLAYWRIGHT_TIMEOUT
        elif "pip" in command:
            timeout = PIP_TIMEOUT
        else:
            timeout = NPM_TIMEOUT
    try:
        result = subprocess.run(command, cwd=APP_ROOT, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"{label} timed out after {timeout} seconds.")
        return False
    if result.returncode == 0:
        return True

    print(f"{label} failed with exit code {result.returncode}.")
    return False


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_development_setup_requires_existing_installation
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_development_setup_is_additive_and_idempotent
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_development_setup_directs_native_windows_to_wsl
# @matrix setup : development frontend-build idempotence package-install portability prerequisites windows
def setup_development():
    """Install local development dependencies after ordinary installer."""
    print("Lagniappe Development Setup")

    if _native_windows():
        print(
            wrap_text(
                "Native Windows development is not supported. Use WSL2 for "
                "development, browser tests, and local server process "
                "management. The Windows Google Cloud CLI Shell/Command Prompt "
                "support surface is installation, recovery, update, and "
                "deployment only."
            )
        )
        return 1
    if not _in_virtualenv():
        print("Development setup must run inside the project virtualenv.")
        print(virtualenv_instructions())
        return 1

    missing = _missing_installation_files()
    if missing:
        print(
            "Development setup requires a completed Lagniappe installation. "
            f"Run {setup_command()} first."
        )
        print(f"Missing installation files: {', '.join(missing)}")
        return 1

    missing_executables = [
        name
        for name, executable in (("node", NODE_CLI), ("npm", NPM_CLI))
        if not executable
    ]
    if missing_executables:
        print(
            "Development setup requires Node.js and npm. "
            f"Missing: {', '.join(missing_executables)}."
        )
        print(f"Supported Node versions: {NODE_ENGINE_RANGE}")
        return 1

    node_version = _installed_node_version()
    if not node_version or not node_version_supported(node_version):
        print(
            f"Unsupported Node version: {node_version or 'unknown'}. "
            f"Supported versions: {NODE_ENGINE_RANGE}."
        )
        return 1

    from installer.verify import prepare_existing_installation

    prepare_existing_installation()
    from installer.gcloud import configure_storage_buckets

    configure_storage_buckets(include_production=False, include_test=True)

    from installer.optional import configure_development_error_monitoring

    if not configure_development_error_monitoring():
        return 1

    commands = (
        (
            "Installing the pinned managed uv executable...",
            [
                sys.executable,
                "-m",
                "runner.uv_bootstrap",
                "install",
                "--non-interactive",
            ],
        ),
        (
            "Verifying the managed uv executable...",
            [sys.executable, "-m", "runner.uv_bootstrap", "check"],
        ),
        (
            "Installing Python development dependencies...",
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                "requirements-dev.txt",
            ],
        ),
        (
            "Installing locked frontend dependencies...",
            [NPM_CLI, "ci"],
        ),
        (
            "Installing Playwright Chromium...",
            [sys.executable, "-m", "playwright", "install", "chromium"],
        ),
        (
            "Building the development frontend...",
            [NPM_CLI, "run", "dev"],
        ),
    )
    for label, command in commands:
        if not _run_command(label, command):
            return 1

    print("\nDevelopment setup complete. Safe to rerun after dependency changes.")
    print(f"Start the local app: {python_command('run.py', 'dev')}")
    print(f"Run backend tests: {python_command('run.py', 'test', 'unit')}")
    print(f"Run frontend tests: {python_command('run.py', 'test', 'js')}")
    print(f"Run browser tests: {python_command('run.py', 'test', 'e2e')}")
    return 0
