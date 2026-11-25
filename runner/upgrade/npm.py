"""Upgrade npm dependency ranges and record changes to exact lockfile versions."""

from __future__ import annotations

import json
from pathlib import Path

from runner.context import NPM_CLI

from .commands import run_command, run_nvm_command
from .reporting import UpgradeReport, record_mapping_changes

NPM_COMMAND = NPM_CLI or "npm"


def _load_json_file(path: Path, report: UpgradeReport | None, label: str) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        if report is not None:
            report.add_error(label, f"Could not parse {path}: {e}")
        return {}
    if not isinstance(data, dict):
        if report is not None:
            report.add_error(label, f"{path} did not contain a JSON object")
        return {}
    return data


def _root_npm_dependencies(data: dict) -> dict[str, str]:
    dependencies = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        section_data = data.get(section)
        if isinstance(section_data, dict):
            dependencies.update(
                {str(name): str(spec) for name, spec in section_data.items()}
            )
    return dependencies


def read_package_json_specs(
    package_path: Path = Path("package.json"),
    report: UpgradeReport | None = None,
) -> dict[str, str]:
    """Read requested dependency ranges from package.json."""
    data = _load_json_file(package_path, report, "npm")
    return _root_npm_dependencies(data)


def _npm_lock_label(path: str) -> str:
    parts = [part.strip("/") for part in path.split("node_modules/") if part]
    return " > ".join(parts) or path


def read_package_lock_versions(
    lock_path: Path = Path("package-lock.json"),
    report: UpgradeReport | None = None,
) -> dict[str, str]:
    """Read exact package versions from package-lock.json."""
    data = _load_json_file(lock_path, report, "npm")
    packages = data.get("packages")
    if not isinstance(packages, dict):
        return {}

    versions = {}
    for path, metadata in packages.items():
        if not path or not isinstance(metadata, dict) or "version" not in metadata:
            continue
        versions[_npm_lock_label(str(path))] = str(metadata["version"])
    return versions


def upgrade_npm_packages(report: UpgradeReport | None = None) -> bool:
    """Look up latest versions once, update direct ranges, then install and audit."""
    report = report or UpgradeReport()

    package_json = Path("package.json")
    if not package_json.exists():
        report.add_note("No package.json found; skipped npm upgrade.")
        return True

    before_specs = read_package_json_specs(package_json, report)
    before_lock_versions = read_package_lock_versions(report=report)

    nvm_script = Path.home() / ".nvm" / "nvm.sh"
    run_node = run_nvm_command if nvm_script.exists() else run_command
    result = run_node(
        [
            NPM_COMMAND, "exec", "--yes", "--package=npm-check-updates", "--",
            "ncu", "--jsonUpgraded", "--no-interactive", "--install", "never",
            "--timeout", "60000", "--retry", "1",
        ],
        check=False, capture=True, report=report, timeout=90,
    )
    if result.returncode != 0:
        report.add_error("npm", f"Package lookup failed: {result.stderr or result.stdout}")
        return False
    try:
        updates = json.loads(result.stdout)
    except (ValueError, TypeError):
        report.add_error("npm", "Package lookup did not return valid JSON; no files changed.")
        return False
    if not isinstance(updates, dict) or not all(
        isinstance(name, str) and isinstance(version, str)
        for name, version in updates.items()
    ):
        report.add_error("npm", "Package lookup returned invalid versions; no files changed.")
        return False

    package = _load_json_file(package_json, report, "npm")
    if _root_npm_dependencies(package) != before_specs:
        report.add_error("npm", "Dependency ranges changed during lookup; rerun the command.")
        return False
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name in package.get(section, {}):
            if name in updates:
                print(f"  {name}: {package[section][name]} -> {updates[name]}", flush=True)
                package[section][name] = updates[name]
    if updates:
        package_json.write_text(
            json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    ok = True
    try:
        for command, description in (
            ([NPM_COMMAND, "install"], "Installing npm package updates"),
            ([NPM_COMMAND, "audit"], "Auditing npm dependencies"),
        ):
            result = run_node(command, check=False, report=report)
            if result.returncode != 0:
                report.add_error(
                    "npm",
                    f"{description} failed with exit code {result.returncode}",
                )
                ok = False
                break
    finally:
        # Include already-applied edits when an install times out or is cancelled.
        after_specs = read_package_json_specs(package_json, report)
        after_lock_versions = read_package_lock_versions(report=report)
        direct_names = set(before_specs) | set(after_specs)
        record_mapping_changes(
            report, "npm", before_lock_versions, after_lock_versions,
            "package-lock.json", direct_names=direct_names,
        )
        record_mapping_changes(
            report, "npm", before_specs, after_specs, "package.json",
        )

    if not any(change.ecosystem == "npm" for change in report.changes):
        report.add_note("No npm package version changes were detected.")

    return ok
