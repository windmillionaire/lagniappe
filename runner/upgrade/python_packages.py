"""Resolve Python packages, validate the environment, and update requirement pins."""

from __future__ import annotations

from pathlib import Path
import re
import sys

from .commands import run_command
from .reporting import UpgradeReport

PIP_COMMAND = [sys.executable, "-m", "pip"]
REQUIREMENTS_PATHS = (
    Path("requirements-installer.txt"),
    Path("requirements.txt"),
    Path("requirements-dev.txt"),
    Path("build/font-requirements.txt"),
)


def _normalize_package_name(name: str) -> str:
    return name.lower().replace("_", "-")


def get_requirement_targets(requirements_path: Path) -> list[str]:
    """Parse direct requirement targets without their version constraints."""
    packages = []
    if not requirements_path.exists():
        return packages

    with open(requirements_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("#", "-")):
                continue
            match = re.match(r"^([a-zA-Z0-9_.-]+)(\[[^\]]+\])?", line)
            if match:
                packages.append(f"{match.group(1)}{match.group(2) or ''}")

    return packages


def _parse_pip_freeze(
    stdout: str,
    package_names: list[str] | None = None,
) -> dict[str, tuple[str, str]]:
    package_display = {
        _normalize_package_name(name): name for name in package_names or []
    }
    package_filter = set(package_display)
    versions = {}

    for line in stdout.splitlines():
        match = re.match(
            r"^([a-zA-Z0-9_.-]+)(?:\[[^\]]+\])?==(.+)$",
            line.strip(),
        )
        if not match:
            continue
        name, version = match.groups()
        normalized_name = _normalize_package_name(name)
        if package_filter and normalized_name not in package_filter:
            continue
        versions[normalized_name] = (
            package_display.get(normalized_name, name),
            version,
        )

    return versions


def collect_pip_installed_versions(
    packages: list[str] | None,
    report: UpgradeReport,
) -> dict[str, tuple[str, str]]:
    result = run_command(
        PIP_COMMAND + ["freeze"],
        check=False,
        capture=True,
        report=report,
    )
    if result.returncode != 0:
        report.add_error(
            "pip",
            f"pip freeze failed with exit code {result.returncode}",
        )
        return {}
    return _parse_pip_freeze(result.stdout, packages)


def record_pip_version_changes(
    report: UpgradeReport,
    before: dict[str, tuple[str, str]],
    after: dict[str, tuple[str, str]],
    source: str,
) -> None:
    for key in sorted(set(before) | set(after)):
        before_name, before_version = before.get(key, (key, "(missing)"))
        after_name, after_version = after.get(key, (before_name, "(missing)"))
        if before_version == after_version:
            continue
        report.add_change(
            "pip",
            after_name or before_name,
            before_version,
            after_version,
            source,
        )


def upgrade_pip_packages(report: UpgradeReport | None = None) -> bool:
    """Resolve direct setup, runtime, development, and font-tool requirements."""
    report = report or UpgradeReport()

    requirements_paths = [path for path in REQUIREMENTS_PATHS if path.exists()]
    if not requirements_paths:
        report.add_note("No requirements files found; skipped pip upgrade.")
        return True

    packages = []
    seen = set()
    for requirements_path in requirements_paths:
        for package in get_requirement_targets(requirements_path):
            normalized_name = _normalize_package_name(package.split("[", 1)[0])
            if normalized_name in seen:
                continue
            seen.add(normalized_name)
            packages.append(package)
    if not packages:
        report.add_note("No packages found in requirements files; skipped pip upgrade.")
        return True

    before_versions = collect_pip_installed_versions(None, report)
    result = run_command(
        PIP_COMMAND
        + ["install", "--upgrade", "--upgrade-strategy", "only-if-needed", *packages],
        check=False,
        report=report,
    )
    ok = result.returncode == 0
    if not ok:
        report.add_error(
            "pip",
            "Failed to resolve and upgrade requirements together: "
            + ", ".join(packages),
        )

    after_versions = collect_pip_installed_versions(None, report)
    record_pip_version_changes(
        report,
        before_versions,
        after_versions,
        "installed environment",
    )
    if before_versions == after_versions:
        report.add_note("No pip package version changes were detected.")

    return ok


def _parse_requirement_pin(line: str) -> tuple[str, str] | None:
    match = re.match(
        r"^([a-zA-Z0-9_.-]+)(?:\[[^\]]+\])?==(.+)$",
        line.strip(),
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def _update_requirements_file(
    requirements_path: Path,
    installed: dict[str, tuple[str, str]],
    report: UpgradeReport,
) -> None:
    with open(requirements_path, encoding="utf-8") as f:
        original_lines = f.readlines()

    updated_lines = []
    for line in original_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            updated_lines.append(line)
            continue

        match = re.match(r"^([a-zA-Z0-9_.-]+)(\[[^\]]+\])?([=<>!]+.+)?$", stripped)
        if match:
            pkg_name = match.group(1)
            extras = match.group(2) or ""
            normalized_name = _normalize_package_name(pkg_name)
            installed_entry = installed.get(normalized_name)
            if installed_entry:
                _, new_version = installed_entry
                updated_lines.append(f"{pkg_name}{extras}=={new_version}\n")
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    with open(requirements_path, "w", encoding="utf-8") as f:
        f.writelines(updated_lines)

    changed = False
    for original, updated in zip(original_lines, updated_lines, strict=False):
        if original == updated:
            continue
        changed = True
        original_pin = _parse_requirement_pin(original)
        updated_pin = _parse_requirement_pin(updated)
        if original_pin and updated_pin:
            report.add_change(
                "pip",
                updated_pin[0],
                original_pin[1],
                updated_pin[1],
                str(requirements_path),
            )
        else:
            report.add_change(
                "pip",
                updated.strip() or original.strip(),
                original.strip(),
                updated.strip(),
                str(requirements_path),
            )

    if not changed:
        report.add_note(f"No {requirements_path} changes were detected.")


def update_requirements_files(report: UpgradeReport | None = None) -> bool:
    """Update direct requirement pins only after Python resolution validates."""
    report = report or UpgradeReport()

    if any(
        error.startswith("pip:") or error.startswith("pip check:")
        for error in report.errors
    ):
        report.add_note(
            "Skipped requirements updates because Python dependency resolution "
            "did not validate."
        )
        return False

    requirements_paths = [path for path in REQUIREMENTS_PATHS if path.exists()]
    if not requirements_paths:
        report.add_note("No requirements files found; skipped requirements update.")
        return True

    result = run_command(
        PIP_COMMAND + ["freeze"],
        check=False,
        capture=True,
        report=report,
    )
    if result.returncode != 0:
        report.add_error(
            "requirements files",
            f"pip freeze failed with exit code {result.returncode}",
        )
        return False

    installed = _parse_pip_freeze(result.stdout)
    for requirements_path in requirements_paths:
        _update_requirements_file(requirements_path, installed, report)

    return True


def check_pip_environment(report: UpgradeReport | None = None) -> bool:
    """Verify the resolved Python environment has no broken requirements."""
    report = report or UpgradeReport()
    result = run_command(
        PIP_COMMAND + ["check"],
        check=False,
        capture=True,
        report=report,
    )
    if result.returncode == 0:
        report.add_note("pip check found no broken requirements.")
        return True

    details = (result.stdout or result.stderr or "dependency conflicts found").strip()
    report.add_error("pip check", details)
    return False
