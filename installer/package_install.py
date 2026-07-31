from contextlib import contextmanager
import importlib
from importlib import metadata
import os
import re
import subprocess
import sys

from runner.context import REPOSITORY_ROOT
from installer.errors import PIP_TIMEOUT, SetupCancelled, SetupError

_ACTIVE_SPINNERS = []
_PROJECT_ROOT = REPOSITORY_ROOT
_PINNED_REQUIREMENTS = (
    _PROJECT_ROOT / "requirements-installer.txt",
    _PROJECT_ROOT / "requirements.txt",
    _PROJECT_ROOT / "requirements-dev.txt",
)
_SETUP_DEPENDENCIES = (
    ("yaml", "PyYAML", "YAML configuration"),
    ("yaspin", "yaspin", "setup progress display"),
    ("colorama", "colorama", "portable terminal output"),
    ("certifi", "certifi", "trusted certificate authorities"),
    ("requests", "requests", "provider HTTP requests"),
    ("google.auth", "google-auth", "Google authentication"),
    ("google.api_core", "google-api-core", "Google API error handling"),
    ("google.cloud.iam_admin_v1", "google-cloud-iam", "service-account setup"),
    (
        "google.cloud.resourcemanager_v3",
        "google-cloud-resource-manager",
        "project IAM setup",
    ),
    (
        "google.cloud.appengine_admin_v1",
        "google-cloud-appengine-admin",
        "App Engine setup",
    ),
    ("google.cloud.tasks_v2", "google-cloud-tasks", "Cloud Tasks setup"),
    ("google.cloud.documentai", "google-cloud-documentai", "Document AI setup"),
    ("google.cloud.datastore", "google-cloud-datastore", "Datastore setup"),
    ("google.cloud.storage", "google-cloud-storage", "Cloud Storage setup"),
    ("redis", "redis", "Redis validation"),
)


# @testable false
# @covered-by installer/package_install.py::track_spinner_factory
# @reason context-manager adapter; behavior is owned by the spinner factory wrapper
class _TrackedSpinnerContext:
    def __init__(self, context):
        self._context = context
        self._spinner = None

    def __enter__(self):
        self._spinner = self._context.__enter__()
        _ACTIVE_SPINNERS.append(self._spinner)
        return self._spinner

    def __exit__(self, exc_type, exc, tb):
        try:
            return self._context.__exit__(exc_type, exc, tb)
        finally:
            if self._spinner in _ACTIVE_SPINNERS:
                _ACTIVE_SPINNERS.remove(self._spinner)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_install_if_missing_pauses_active_spinner_for_prompt
# @features setup
# @dimensions package-install spinner
def track_spinner_factory(yaspin_factory):
    """Wrap a yaspin factory so package installs can pause active spinners."""

    # @testable false
    # @covered-by installer/package_install.py::track_spinner_factory
    # @reason closure returned by spinner factory wrapper
    def tracked_yaspin(*args, **kwargs):
        return _TrackedSpinnerContext(yaspin_factory(*args, **kwargs))

    return tracked_yaspin


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_install_if_missing_pauses_active_spinner_for_prompt
# @features setup
# @dimensions package-install spinner
@contextmanager
def _pause_active_spinners():
    paused = []
    for spinner in reversed(_ACTIVE_SPINNERS):
        stop = getattr(spinner, "stop", None)
        if callable(stop):
            stop()
            paused.append(spinner)

    try:
        yield
    finally:
        for spinner in reversed(paused):
            start = getattr(spinner, "start", None)
            if callable(start):
                start()


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_package_install_helpers
# @features setup
# @dimensions package-install
def ensure_pip_is_available():
    """Checks if pip is available, tries to install it if not, and provides guidance."""
    try:
        # Try to run pip --version
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return  # pip is available
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        # pip is not found or python executable itself is not found
        pass  # Proceed to try and install it

    print("Pip not found. Attempting to install it...")
    try:
        # Try to install pip using ensurepip
        subprocess.check_call(
            [sys.executable, "-m", "ensurepip", "--upgrade", "--default-pip"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PIP_TIMEOUT,
        )
        # Verify pip installation
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        print("Pip installed successfully.")
        return  # pip is now available
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ) as e:
        print(
            f"Error: Automatic installation of 'pip' failed. ({e})\n"
            f"Please install pip manually for your Python environment ({sys.executable}).\n\n"
            "Instructions:\n"
            "-------------\n"
            "1. Download get-pip.py from https://bootstrap.pypa.io/get-pip.py\n"
            f"2. Run: '{sys.executable}' get-pip.py\n\n"
            "For Windows (if the above fails or python is not in PATH):\n"
            "  - Search for 'Manage app execution aliases' in Windows settings.\n"
            "  - Ensure 'python.exe' and 'python3.exe' (if present) provided by 'Python Software Foundation' are enabled.\n"
            "  - Or, use the full path to your python.exe when running get-pip.py, e.g.:\n"
            f"    '{sys.executable}' get-pip.py\n\n"
            "For macOS/Linux (if python is not in PATH or you have multiple Pythons):\n"
            "  - Use 'python3' or the specific Python executable path:\n"
            f"    '{sys.executable}' get-pip.py\n"
            "  - You might need to use 'sudo' if installing system-wide (not recommended if using virtual environments):\n"
            f"    sudo '{sys.executable}' get-pip.py\n\n"
            "After installing pip, please re-run this setup script.",
            file=sys.stderr,
        )
        raise SetupError("Automatic pip installation failed.") from e


# @testable false
# @covered-by installer/package_install.py::_pinned_requirement
# @reason package-name normalization is an internal part of setup pin lookup
def _normalize_package_name(package_name):
    return re.sub(r"[-_.]+", "-", package_name.split("[", 1)[0]).lower()


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_dependency_transaction_validates_versions_and_pip_check
# @features setup
# @dimensions package-install dependency-pins
def _requirement_version(requirement):
    match = re.match(
        r"^([a-zA-Z0-9_.-]+)(?:\[[^\]]+\])?==([^;\s]+)",
        requirement,
    )
    if not match:
        raise RuntimeError(f"Setup requirement is not exactly pinned: {requirement}")
    return match.group(1), match.group(2)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_package_install_helpers
# @features setup
# @dimensions package-install dependency-pins
def _pinned_requirement(package_name):
    normalized_name = _normalize_package_name(package_name)

    for requirements_path in _PINNED_REQUIREMENTS:
        if not requirements_path.exists():
            continue
        for line in requirements_path.read_text(encoding="utf-8").splitlines():
            requirement = line.strip()
            if not requirement or requirement.startswith(("#", "-")):
                continue
            match = re.match(r"^([a-zA-Z0-9_.-]+)(?:\[[^\]]+\])?==[^;\s]+$", requirement)
            if match and _normalize_package_name(match.group(1)) == normalized_name:
                return requirement

    raise RuntimeError(
        f"Setup dependency {package_name!r} has no exact pin in "
        "requirements-installer.txt, requirements.txt, or requirements-dev.txt"
    )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_dependency_transaction_validates_versions_and_pip_check
# @features setup
# @dimensions package-install dependency-pins
def _dependency_status(import_name, package_name, *, check_import=True):
    """Return whether a distribution matches its pin and optionally imports."""
    requirement = _pinned_requirement(package_name)
    distribution_name, expected_version = _requirement_version(requirement)
    try:
        installed_version = metadata.version(distribution_name)
    except metadata.PackageNotFoundError:
        return requirement, False, "not installed"

    if installed_version != expected_version:
        return (
            requirement,
            False,
            f"installed {installed_version}, expected {expected_version}",
        )

    if not check_import:
        return requirement, True, installed_version

    try:
        importlib.import_module(import_name)
    except Exception as error:
        return requirement, False, f"cannot import {import_name}: {error}"

    return requirement, True, installed_version


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_dependency_transaction_validates_versions_and_pip_check
# @features setup
# @dimensions package-install dependency-pins
def _run_pip_check():
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True,
        text=True,
        timeout=PIP_TIMEOUT,
    )
    if result.returncode != 0:
        details = (result.stdout or result.stderr or "").strip()
        raise RuntimeError(
            "The Python environment has incompatible dependencies"
            f"{f': {details}' if details else ''}"
        )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_dependency_transaction_validates_versions_and_pip_check
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_dependency_transaction_repairs_transitive_conflicts
# @features setup
# @dimensions package-install dependency-pins
def ensure_setup_dependencies():
    """Validate/install the default setup dependency set in one pip transaction."""
    pending = []
    for import_name, package_name, explanation in _SETUP_DEPENDENCIES:
        requirement, ready, detail = _dependency_status(
            import_name,
            package_name,
            check_import=False,
        )
        if not ready:
            pending.append((import_name, package_name, explanation, requirement, detail))

    compatibility_error = None
    if not pending:
        try:
            _run_pip_check()
        except RuntimeError as error:
            compatibility_error = str(error)

    transaction_required = bool(pending or compatibility_error)
    if transaction_required:
        interactive = sys.stdin.isatty() and os.environ.get(
            "LAGNIAPPE_NONINTERACTIVE", ""
        ).lower() not in ("1", "true", "yes")
        if interactive:
            print("Setup needs to install or correct these Python dependencies:")
            for _import_name, package_name, explanation, requirement, detail in pending:
                print(f"  {requirement} — {explanation} ({detail})")
            if compatibility_error:
                print(
                    "  transitive dependencies — compatibility repair "
                    f"({compatibility_error})"
                )
            if input("Continue with this dependency transaction? [Y/n]: ").lower() == "n":
                print("Aborting installer.")
                raise SetupCancelled(
                    "Setup dependency transaction cancelled by the operator."
                )

        requirements = list(
            dict.fromkeys(
                _pinned_requirement(package_name)
                for _import_name, package_name, _explanation in _SETUP_DEPENDENCIES
            )
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--upgrade-strategy",
                "eager",
                *requirements,
            ],
            capture_output=True,
            text=True,
            timeout=PIP_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pip install exited with {result.returncode}\n"
                f"stdout:\n{result.stdout.strip()}\n"
                f"stderr:\n{result.stderr.strip()}"
            )
        importlib.invalidate_caches()
        metadata.MetadataPathFinder.invalidate_caches()

    failures = []
    for import_name, package_name, _explanation in _SETUP_DEPENDENCIES:
        requirement, ready, detail = _dependency_status(import_name, package_name)
        if not ready:
            failures.append(f"{requirement}: {detail}")
    if failures:
        raise RuntimeError(
            "Setup dependencies did not validate after installation: "
            + "; ".join(failures)
        )

    if transaction_required:
        _run_pip_check()
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_package_install_helpers
# @features setup
# @dimensions package-install dependency-pins
def _install(package_name, import_name):
    requirement = _pinned_requirement(package_name)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", requirement],
        capture_output=True,
        text=True,
        timeout=PIP_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pip install exited with {result.returncode}\n"
            f"stdout:\n{result.stdout.strip()}\n"
            f"stderr:\n{result.stderr.strip()}"
        )

    importlib.invalidate_caches()
    importlib.import_module(import_name)
    _run_pip_check()


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_package_install_helpers
# @features setup
# @dimensions package-install
def install_if_missing(import_name, explanation=None, package_name=None):
    """Test import and install if missing.

    Uses stderr for all output and pauses active setup spinners so prompts
    remain visible when dependencies are discovered inside spinner-owned work.

    Args:
        import_name: The name used to import the module (e.g. 'google.auth').
        explanation: Human-readable description shown in the install prompt.
        package_name: The pip package name if different from import_name (e.g. 'google-auth').
    """
    package_name = package_name or import_name

    try:
        _requirement, ready, _detail = _dependency_status(import_name, package_name)
        if not ready:
            raise ImportError(import_name)
        return
    except ImportError:
        with _pause_active_spinners():
            interactive = sys.stdin.isatty() and os.environ.get(
                "LAGNIAPPE_NONINTERACTIVE", ""
            ).lower() not in ("1", "true", "yes")

            if interactive:
                prompt = f"Install {package_name}? ({explanation if explanation else ''}) [Y/n]: "
                sys.stderr.write(prompt)
                sys.stderr.flush()
                response = input()
                if response.lower() == "n":
                    print("Aborting installer.")
                    raise SetupCancelled(
                        f"Installation of {package_name} was cancelled."
                    )

            print(f"Installing {package_name}...", file=sys.stderr)
            try:
                _install(package_name, import_name)
            except Exception as e:
                print(f"Failed to install {package_name}. Error: {e}", file=sys.stderr)
                raise SetupError(
                    f"Failed to install setup dependency {package_name}."
                ) from e
            print(f"Installed {package_name} [OK]", file=sys.stderr)
