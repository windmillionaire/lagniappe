"""Upgrade script for Node.js, npm packages, and Python dependencies."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import Directory
from runner.context import NODE_CLI, NPM_CLI

PIP_COMMAND = [sys.executable, "-m", "pip"]
NODE_COMMAND = NODE_CLI or "node"
NPM_COMMAND = NPM_CLI or "npm"
REQUIREMENTS_PATHS = (
    Path("requirements-installer.txt"),
    Path("requirements.txt"),
    Path("requirements-dev.txt"),
)
NODE_VERSION_PIN_PATH = Path(".nvmrc")


@dataclass
class VersionChange:
    """A before/after dependency version or requested-range change."""

    ecosystem: str
    name: str
    before: str
    after: str
    source: str
    direct: bool = True


@dataclass
class CommandLog:
    """Captured subprocess output for the upgrade report."""

    command: str
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    error: str = ""


@dataclass
class UpgradeReport:
    """State collected while the dependency upgrade runs."""

    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    changes: list[VersionChange] = field(default_factory=list)
    command_logs: list[CommandLog] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    report_path: Path | None = None

    def add_change(
        self,
        ecosystem: str,
        name: str,
        before: object,
        after: object,
        source: str,
        *,
        direct: bool = True,
    ) -> None:
        before_text = _version_text(before)
        after_text = _version_text(after)
        if before_text == after_text:
            return
        self.changes.append(
            VersionChange(
                ecosystem=ecosystem,
                name=name,
                before=before_text,
                after=after_text,
                source=source,
                direct=direct,
            )
        )

    def add_error(self, step: str, message: str) -> None:
        self.errors.append(f"{step}: {message}")

    def add_note(self, message: str) -> None:
        self.notes.append(message)

    def record_command(
        self,
        command: list[str] | str,
        returncode: int | None,
        *,
        stdout: str | None = "",
        stderr: str | None = "",
        error: str = "",
    ) -> None:
        self.command_logs.append(
            CommandLog(
                command=_format_command(command),
                returncode=returncode,
                stdout=stdout or "",
                stderr=stderr or "",
                error=error,
            )
        )


def _version_text(value: object) -> str:
    if value is None or value == "":
        return "(missing)"
    return str(value)


def _format_command(command: list[str] | str) -> str:
    if isinstance(command, str):
        return command
    return shlex.join(str(part) for part in command)


# @testable false
# @reason upgrade subprocess/report adapter is exercised by package upgrade flows
def run_command(
    command: list[str],
    check: bool = True,
    capture: bool = True,
    report: UpgradeReport | None = None,
) -> subprocess.CompletedProcess:
    """Run a command, keeping stdout/stderr quiet unless written to the report."""
    try:
        result = subprocess.run(
            command,
            capture_output=capture,
            text=True,
            check=check,
            timeout=900,
        )
        if report is not None:
            report.record_command(
                command,
                result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result
    except subprocess.CalledProcessError as e:
        if report is not None:
            report.record_command(
                command,
                e.returncode,
                stdout=e.stdout,
                stderr=e.stderr,
                error=str(e),
            )
        if check:
            raise
        return subprocess.CompletedProcess(
            e.cmd,
            e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        )
    except FileNotFoundError as e:
        if report is not None:
            report.record_command(command, None, error=str(e))
        raise


def run_nvm_command(
    args: list[str],
    *,
    check: bool = True,
    report: UpgradeReport | None = None,
) -> subprocess.CompletedProcess:
    """Run node/npm commands in an nvm shell so they use the latest version.

    nvm is shell-scoped: `nvm use` only affects that shell. Direct subprocess
    direct subprocess calls use whatever node is currently on PATH (often the
    old default). This wraps commands with nvm setup so they see the upgraded
    version.
    """
    nvm_script = Path.home() / ".nvm" / "nvm.sh"
    if not nvm_script.exists():
        return run_command(args, check=check, report=report)
    shell_args = list(args)
    if shell_args and shell_args[0] in {NODE_CLI, NPM_CLI}:
        shell_args[0] = Path(shell_args[0]).name
    cmd_str = " ".join(shlex.quote(a) for a in shell_args)
    shell_script = (
        f"source {shlex.quote(str(nvm_script))} "
        f"&& nvm use node 2>/dev/null && {cmd_str}"
    )
    return run_command(["bash", "-lc", shell_script], check=check, report=report)


def _normalize_package_name(name: str) -> str:
    return name.lower().replace("_", "-")


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


def record_mapping_changes(
    report: UpgradeReport,
    ecosystem: str,
    before: dict[str, str],
    after: dict[str, str],
    source: str,
    *,
    direct_names: set[str] | None = None,
    direct: bool = True,
) -> None:
    """Record sorted before/after changes between two version maps."""
    for name in sorted(set(before) | set(after), key=str.lower):
        before_value = before.get(name)
        after_value = after.get(name)
        if before_value == after_value:
            continue
        is_direct = direct if direct_names is None else name in direct_names
        change_source = source
        if direct_names is not None:
            change_source = (
                f"{source} (direct)" if is_direct else f"{source} (transitive)"
            )
        report.add_change(
            ecosystem,
            name,
            before_value,
            after_value,
            change_source,
            direct=is_direct,
        )


def _record_node_change(
    report: UpgradeReport,
    before: str | None,
    after: str | None,
) -> None:
    if before and after:
        report.add_change("node", "Node.js", before, after, "node --version")
    elif after:
        report.add_note(f"Node.js version after upgrade: {after}")


def _node_version_from_output(output: str) -> str:
    matches = re.findall(r"v\d+\.\d+\.\d+(?:[-+][^\s)]+)?", output)
    return matches[-1] if matches else output.strip()


# @testable true
# @tests tests_tooling/test_003_config.py::test_dependency_upgrade_updates_node_version_pin
# @matrix dependencies : node-version pinning upgrade
def update_node_version_pin(
    version: str,
    report: UpgradeReport,
    path: Path = NODE_VERSION_PIN_PATH,
) -> bool:
    """Write the resolved Node version to the repository's nvm pin."""
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", str(version).strip())
    if not match:
        report.add_error("Node.js pin", f"Could not normalize Node version: {version}")
        return False

    normalized = match.group(1)
    before = path.read_text(encoding="utf-8").strip() if path.exists() else None
    path.write_text(f"{normalized}\n", encoding="utf-8")
    report.add_change("node", "Node.js pin", before, normalized, str(path))
    return True


# @testable true
# @tests tests_tooling/test_003_config.py::test_dependency_upgrade_updates_node_version_pin
# @matrix dependencies : node-version pinning upgrade
def upgrade_node(report: UpgradeReport | None = None) -> bool:
    """Upgrade Node.js to the latest version using nvm when available."""
    report = report or UpgradeReport()

    before_version = None
    try:
        result = run_command(
            [NODE_COMMAND, "--version"], check=False, report=report
        )
        if result.returncode == 0:
            before_version = _node_version_from_output(result.stdout)
        else:
            report.add_note("Node.js not found; skipped Node.js upgrade.")
            return False
    except FileNotFoundError:
        report.add_note("Node.js not found; skipped Node.js upgrade.")
        return False

    nvm_dir = Path.home() / ".nvm"
    if nvm_dir.exists():
        nvm_script = nvm_dir / "nvm.sh"
        if nvm_script.exists():
            cmd = (
                f"source {shlex.quote(str(nvm_script))} && "
                "nvm install node && nvm use node && nvm alias default node"
            )
            result = run_command(["bash", "-lc", cmd], check=False, report=report)
            if result.returncode == 0:
                verify = run_nvm_command(
                    [NODE_COMMAND, "--version"],
                    check=False,
                    report=report,
                )
                if verify.returncode != 0:
                    report.add_error(
                        "Node.js", "Could not verify upgraded Node version"
                    )
                    return False
                after_version = _node_version_from_output(verify.stdout)
                _record_node_change(
                    report,
                    before_version,
                    after_version,
                )
                return update_node_version_pin(after_version, report)
            report.add_note("nvm Node.js upgrade failed; trying alternative methods.")

    try:
        result = run_command(["which", "n"], check=False, capture=True, report=report)
        if result.returncode == 0:
            upgrade = run_command(["sudo", "n", "lts"], check=False, report=report)
            verify = run_command(
                [NODE_COMMAND, "--version"], check=False, report=report
            )
            if upgrade.returncode != 0:
                report.add_error("Node.js", "n upgrade command failed")
                return False
            if verify.returncode != 0:
                report.add_error("Node.js", "Could not verify upgraded Node version")
                return False
            after_version = _node_version_from_output(verify.stdout)
            _record_node_change(
                report,
                before_version,
                after_version,
            )
            return update_node_version_pin(after_version, report)
    except FileNotFoundError:
        pass

    report.add_note(
        "No Node.js version manager found (nvm or n); skipped Node.js upgrade."
    )
    return False


def upgrade_npm_packages(report: UpgradeReport | None = None) -> bool:
    """Check and upgrade npm packages using npm-check-updates."""
    report = report or UpgradeReport()

    package_json = Path("package.json")
    if not package_json.exists():
        report.add_note("No package.json found; skipped npm upgrade.")
        return True

    before_specs = read_package_json_specs(package_json, report)
    before_lock_versions = read_package_lock_versions(report=report)

    nvm_script = Path.home() / ".nvm" / "nvm.sh"
    run_node = run_nvm_command if nvm_script.exists() else run_command
    ok = True

    result = run_node(
        [NPM_COMMAND, "list", "-g", "npm-check-updates"],
        check=False,
        report=report,
    )
    if result.returncode != 0:
        report.add_note("npm-check-updates was not installed globally; installing it.")
        install = run_node(
            [NPM_COMMAND, "install", "-g", "npm-check-updates"],
            check=False,
            report=report,
        )
        if install.returncode != 0:
            report.add_error(
                "npm",
                "Failed to install npm-check-updates globally",
            )
            ok = False

    for command, description in (
        (["ncu"], "Checking npm package updates"),
        (["ncu", "-u"], "Updating package.json with npm package updates"),
        ([NPM_COMMAND, "install"], "Installing npm package updates"),
        ([NPM_COMMAND, "audit", "fix"], "Running npm audit fix"),
    ):
        result = run_node(command, check=False, report=report)
        if result.returncode != 0:
            report.add_error(
                "npm",
                f"{description} failed with exit code {result.returncode}",
            )
            ok = False

    after_specs = read_package_json_specs(package_json, report)
    after_lock_versions = read_package_lock_versions(report=report)
    direct_names = set(before_specs) | set(after_specs)

    record_mapping_changes(
        report,
        "npm",
        before_lock_versions,
        after_lock_versions,
        "package-lock.json",
        direct_names=direct_names,
    )
    record_mapping_changes(
        report,
        "npm",
        before_specs,
        after_specs,
        "package.json",
    )

    if not any(change.ecosystem == "npm" for change in report.changes):
        report.add_note("No npm package version changes were detected.")

    return ok


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


# @testable true
# @tests tests_tooling/test_003_config.py::test_dependency_upgrade_resolves_and_rewrites_all_requirement_files
# @pair dependencies:upgrade-requirements
def upgrade_pip_packages(report: UpgradeReport | None = None) -> bool:
    """Resolve setup, runtime, and development requirements in one transaction."""
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
        + ["install", "--upgrade", "--upgrade-strategy", "eager", *packages],
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
    for original, updated in zip(original_lines, updated_lines):
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


# @testable true
# @tests tests_tooling/test_003_config.py::test_dependency_upgrade_resolves_and_rewrites_all_requirement_files
# @pair dependencies:upgrade-requirements
def update_requirements_files(report: UpgradeReport | None = None) -> bool:
    """Update setup, runtime, and development pins from the environment."""
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


def default_upgrade_report_path(timestamp: datetime | None = None) -> Path:
    """Return a timestamped dependency upgrade report path."""
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    candidate = Directory.REPORTS.value / f"upgrade-{stamp}.md"
    suffix = 2
    while candidate.exists():
        candidate = Directory.REPORTS.value / f"upgrade-{stamp}-{suffix}.md"
        suffix += 1
    return candidate


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _inline_code(value: object) -> str:
    escaped = str(value).replace("`", "\\`")
    return f"`{escaped}`"


def _fenced_text(value: str) -> str:
    return value.rstrip().replace("```", "`` `") or "(no output)"


def _render_change_table(title: str, changes: list[VersionChange]) -> list[str]:
    if not changes:
        return []

    lines = [f"### {title}", ""]
    lines.extend(
        [
            "| Package | Before | After | Source |",
            "| --- | --- | --- | --- |",
        ]
    )
    for change in changes:
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown(change.name),
                    _markdown(change.before),
                    _markdown(change.after),
                    _markdown(change.source),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _changes_by(
    report: UpgradeReport,
    ecosystem: str,
    source: str | None = None,
) -> list[VersionChange]:
    changes = [
        change
        for change in report.changes
        if change.ecosystem == ecosystem and (source is None or change.source == source)
    ]
    return sorted(changes, key=lambda change: change.name.lower())


def _is_warning_line(line: str) -> bool:
    if line.strip() == "npm warn allow-scripts":
        return False
    return bool(re.match(r"^(WARNING:|WARN\b|npm warn\b)", line.strip(), re.IGNORECASE))


def _warning_summary(report: UpgradeReport) -> dict[str, dict[str, object]]:
    warnings: dict[str, dict[str, object]] = {}
    for index, log in enumerate(report.command_logs, start=1):
        for output in (log.stdout, log.stderr, log.error):
            for line in output.splitlines():
                warning = line.strip()
                if not warning or not _is_warning_line(warning):
                    continue
                item = warnings.setdefault(
                    warning,
                    {"count": 0, "commands": []},
                )
                item["count"] = int(item["count"]) + 1
                commands = item["commands"]
                if isinstance(commands, list) and index not in commands:
                    commands.append(index)
    return warnings


def _render_warnings(report: UpgradeReport) -> list[str]:
    warnings = _warning_summary(report)
    if not warnings:
        return []

    lines = [
        "## Warnings",
        "",
        "| Warning | Count | Commands |",
        "| --- | ---: | --- |",
    ]
    for warning, details in warnings.items():
        commands = details["commands"]
        command_list = (
            ", ".join(f"#{index}" for index in commands)
            if isinstance(commands, list)
            else ""
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown(warning),
                    str(details["count"]),
                    command_list,
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


# @testable true
# @tests tests_tooling/test_003_config.py::test_dependency_upgrade_report_includes_setup_pins
# @pair dependencies:upgrade-report
def render_upgrade_report(report: UpgradeReport) -> str:
    """Render the captured upgrade run as Markdown."""
    status = "completed with errors" if report.errors else "completed"
    finished_at = report.finished_at or datetime.now()
    lines = [
        "# Dependency Upgrade Report",
        "",
        f"- Started: {report.started_at.isoformat(timespec='seconds')}",
        f"- Finished: {finished_at.isoformat(timespec='seconds')}",
        f"- Status: {status}",
        "",
    ]

    change_lines = []
    for title, changes in (
        ("Node.js", _changes_by(report, "node")),
        (
            "npm Exact Direct Packages",
            _changes_by(report, "npm", "package-lock.json (direct)"),
        ),
        (
            "npm Exact Transitive Packages",
            _changes_by(report, "npm", "package-lock.json (transitive)"),
        ),
        (
            "npm Requested Ranges",
            _changes_by(report, "npm", "package.json"),
        ),
        (
            "pip Installed Packages",
            _changes_by(report, "pip", "installed environment"),
        ),
        (
            "requirements-installer.txt Pins",
            _changes_by(report, "pip", "requirements-installer.txt"),
        ),
        (
            "requirements.txt Pins",
            _changes_by(report, "pip", "requirements.txt"),
        ),
        (
            "requirements-dev.txt Pins",
            _changes_by(report, "pip", "requirements-dev.txt"),
        ),
    ):
        change_lines.extend(_render_change_table(title, changes))

    lines.extend(["## Version Changes", ""])
    if change_lines:
        lines.extend(change_lines)
    else:
        lines.extend(["_No version changes recorded._", ""])

    if report.errors:
        lines.extend(["## Errors", ""])
        lines.extend(f"- {_markdown(error)}" for error in report.errors)
        lines.append("")

    if report.notes:
        lines.extend(["## Notes", ""])
        lines.extend(f"- {_markdown(note)}" for note in report.notes)
        lines.append("")

    lines.extend(_render_warnings(report))

    if report.command_logs:
        lines.extend(["## Command Output", ""])
    for index, log in enumerate(report.command_logs, start=1):
        returncode = "not started" if log.returncode is None else str(log.returncode)
        lines.extend(
            [
                f"### {index}. {_inline_code(log.command)}",
                "",
                f"- Exit code: {returncode}",
            ]
        )
        if log.error:
            lines.append(f"- Error: {_markdown(log.error)}")
        lines.extend(
            [
                "",
                "stdout:",
                "",
                "```text",
                _fenced_text(log.stdout),
                "```",
                "",
                "stderr:",
                "",
                "```text",
                _fenced_text(log.stderr),
                "```",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def write_upgrade_report(
    report: UpgradeReport,
    report_path: Path | None = None,
) -> Path:
    """Save the Markdown upgrade report under reports/."""
    report.finished_at = datetime.now()
    path = report_path or default_upgrade_report_path(report.finished_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    report.report_path = path
    path.write_text(render_upgrade_report(report), encoding="utf-8")
    return path


def _console_changes(
    report: UpgradeReport,
    ecosystem: str,
    preferred_sources: tuple[str, ...],
) -> list[VersionChange]:
    for source in preferred_sources:
        changes = _changes_by(report, ecosystem, source)
        if changes:
            return changes
    return []


def _print_console_group(title: str, changes: list[VersionChange]) -> None:
    print(f"\n{title}:")
    if not changes:
        print("  No changes")
        return
    for change in changes:
        print(f"  {change.name}: {change.before} -> {change.after}")


# @testable true
# @tests tests_tooling/test_003_config.py::test_dependency_upgrade_report_includes_setup_pins
# @pair dependencies:upgrade-report
def print_upgrade_summary(
    report: UpgradeReport,
    success: bool,
    report_path: Path,
) -> None:
    """Print the concise console summary for an upgrade run."""
    print("Lagniappe dependency upgrade")
    print("Complete." if success else "Completed with errors.")

    _print_console_group("Node.js", _changes_by(report, "node"))
    _print_console_group(
        "npm packages",
        _console_changes(
            report,
            "npm",
            ("package-lock.json (direct)", "package.json"),
        ),
    )
    _print_console_group(
        "pip packages",
        _console_changes(
            report,
            "pip",
            (
                "installed environment",
                "requirements-installer.txt",
                "requirements.txt",
                "requirements-dev.txt",
            ),
        ),
    )

    if report.errors:
        print("\nErrors:")
        for error in report.errors[:5]:
            print(f"  {error}")
        remaining = len(report.errors) - 5
        if remaining:
            print(f"  ... {remaining} more in the report")

    print(f"\nReport: {report_path}")


def upgrade_all() -> int:
    """Run all upgrade steps and write a report."""
    report = UpgradeReport()
    success = True

    for step_name, step in (
        ("Node.js", upgrade_node),
        ("npm", upgrade_npm_packages),
        ("pip", upgrade_pip_packages),
        ("pip check", check_pip_environment),
        ("requirements files", update_requirements_files),
    ):
        try:
            step_ok = step(report)
            if not step_ok and report.errors:
                success = False
        except Exception as e:
            report.add_error(step_name, str(e))
            success = False

    if report.errors:
        success = False

    report_path = write_upgrade_report(report)
    print_upgrade_summary(report, success, report_path)

    return 0 if success else 1
