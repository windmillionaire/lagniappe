"""Upgrade script for Node.js, npm packages, and Python dependencies."""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from config import Directory
from runner.context import NODE_CLI, NPM_CLI

PIP_COMMAND = [sys.executable, "-m", "pip"]
NODE_COMMAND = NODE_CLI or "node"
NPM_COMMAND = NPM_CLI or "npm"
REQUIREMENTS_PATHS = (
    Path("requirements-installer.txt"),
    Path("requirements.txt"),
    Path("requirements-dev.txt"),
    Path("build/font-requirements.txt"),
)
NODE_VERSION_PIN_PATH = Path(".nvmrc")
NODE_DOCKERFILE_PATH = Path("runner/hosted_e2e_container/Dockerfile")


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
# @covered-by runner/upgrade.py::run_command
# @reason cancel only the subprocess group created for this dependency command
def _stop_command(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            timeout=10,
        )
        if process.poll() is None:
            process.kill()
    process.wait(timeout=5)


# @testable true
# @tests tests_tooling/test_014_dependency_upgrade.py::test_dependency_command_streams_prompts_and_preserves_output
# @tests tests_tooling/test_014_dependency_upgrade.py::test_dependency_command_timeout_preserves_output_and_stops_children
# @matrix dependencies : subprocess-output timeout cancellation
def run_command(
    command: list[str],
    check: bool = True,
    capture: bool = False,
    report: UpgradeReport | None = None,
    timeout: float = 900,
) -> subprocess.CompletedProcess:
    """Stream commands and prompts, retaining output even on timeout or cancel."""
    print(f"\n  $ {_format_command(command)}", flush=True)
    output = {"stdout": [], "stderr": []}
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL if capture else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    except OSError as e:
        if report is not None:
            report.record_command(command, None, error=str(e))
        raise

    # @testable false
    # @covered-by runner/upgrade.py::run_command
    # @reason drain both pipes without waiting for newline-terminated prompts
    def drain(pipe, name, destination):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        with pipe:
            while chunk := pipe.read1(65536):
                text = decoder.decode(chunk)
                output[name].append(text)
                if not capture:
                    destination.write(text)
                    destination.flush()
            text = decoder.decode(b"", final=True)
            output[name].append(text)
            if not capture:
                destination.write(text)
                destination.flush()

    readers = [
        threading.Thread(target=drain, args=(process.stdout, "stdout", sys.stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, "stderr", sys.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    started = time.monotonic()
    failure = None
    try:
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                process.wait(timeout=min(30, remaining))
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started
                if elapsed >= timeout:
                    raise subprocess.TimeoutExpired(command, timeout) from None
                print(f"  Still running ({elapsed:.0f}s)...", flush=True)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        failure = error
        _stop_command(process)
    finally:
        for reader in readers:
            reader.join(timeout=3)
        if any(reader.is_alive() for reader in readers):
            _stop_command(process)
            for reader in readers:
                reader.join(timeout=3)
        stdout, stderr = "".join(output["stdout"]), "".join(output["stderr"])
        if report is not None:
            report.record_command(
                command, process.returncode, stdout=stdout, stderr=stderr,
                error="Interrupted" if isinstance(failure, KeyboardInterrupt) else str(failure or ""),
            )
    if failure:
        if isinstance(failure, subprocess.TimeoutExpired):
            failure.output, failure.stderr = stdout, stderr
        raise failure
    if check and process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


# @testable false
# @covered-by runner/upgrade.py::upgrade_npm_packages
# @reason select the upgraded Node runtime while preserving command I/O options
def run_nvm_command(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    report: UpgradeReport | None = None,
    timeout: float = 900,
) -> subprocess.CompletedProcess:
    """Run node/npm commands in an nvm shell so they use the latest version.

    nvm is shell-scoped: `nvm use` only affects that shell. Direct subprocess
    calls use whatever node is currently on PATH (often the
    old default). This wraps commands with nvm setup so they see the upgraded
    version.
    """
    nvm_script = Path.home() / ".nvm" / "nvm.sh"
    if not nvm_script.exists():
        return run_command(args, check=check, capture=capture, report=report, timeout=timeout)
    shell_args = list(args)
    if shell_args and shell_args[0] in {NODE_CLI, NPM_CLI}:
        shell_args[0] = Path(shell_args[0]).name
    cmd_str = " ".join(shlex.quote(a) for a in shell_args)
    shell_script = (
        f"source {shlex.quote(str(nvm_script))} "
        f"&& nvm use --silent node && exec {cmd_str}"
    )
    return run_command(
        ["bash", "-lc", shell_script], check=check, capture=capture,
        report=report, timeout=timeout,
    )


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
# @tests tests_tooling/test_014_dependency_upgrade.py::test_node_alignment_failure_preserves_all_declarations
# @matrix dependencies : node-version pinning upgrade
def update_node_version_pin(
    version: str,
    report: UpgradeReport,
    path: Path = NODE_VERSION_PIN_PATH,
) -> bool:
    """Align the nvm pin, npm engine, and hosted image with upgraded Node."""
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", str(version).strip())
    if not match:
        report.add_error("Node.js pin", f"Could not normalize Node version: {version}")
        return False

    normalized = match.group(1)
    root = path.resolve().parent
    package_path = root / "package.json"
    lock_path = root / "package-lock.json"
    docker_path = root / NODE_DOCKERFILE_PATH
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        docker = docker_path.read_text(encoding="utf-8")
        matches = list(re.finditer(r"^FROM (node:\S+) AS node-runtime$", docker, re.MULTILINE))
        if len(matches) != 1:
            raise ValueError("Expected one named node-runtime stage in hosted E2E Dockerfile")
        image = resolve_node_image(normalized)
        engine = f">={normalized}"
        before_engine = package.get("engines", {}).get("node")
        package.setdefault("engines", {})["node"] = engine
        replacements = {
            path: f"{normalized}\n",
            package_path: json.dumps(package, indent=2) + "\n",
            docker_path: docker[:matches[0].start(1)] + image + docker[matches[0].end(1):],
        }
        if lock_path.exists():
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock.setdefault("packages", {}).setdefault("", {}).setdefault("engines", {})["node"] = engine
            replacements[lock_path] = json.dumps(lock, indent=2) + "\n"
        before = path.read_text(encoding="utf-8").strip() if path.exists() else None
    except (OSError, ValueError) as error:
        report.add_error("Node.js declarations", f"Could not align {normalized}: {error}")
        return False

    # Resolve the exact published image and validate every input before writing.
    for output, content in replacements.items():
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            output.write_text(content, encoding="utf-8")
    report.add_change("node", "Node.js pin", before, normalized, str(path))
    report.add_change("node", "Node.js engine", before_engine, engine, str(package_path))
    report.add_change("node", "Hosted Node image", matches[0].group(1), image, str(docker_path))
    return True


# @testable true
# @tests tests_tooling/test_014_dependency_upgrade.py::test_node_image_lookup_verifies_registry_digest
# @matrix dependencies : node-version pinning upgrade
def resolve_node_image(version: str) -> str:
    """Resolve an exact official Node tag without installing Docker or layers."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Node image version must be an exact stable version")
    token_url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/node:pull"
    with urlopen(token_url, timeout=30) as response:
        credentials = json.load(response)
    token = credentials.get("token") if isinstance(credentials, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("Node image registry did not return an access token")
    tag = f"{version}-bookworm-slim"
    request = Request(
        f"https://registry-1.docker.io/v2/library/node/manifests/{tag}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json",
        },
    )
    with urlopen(request, timeout=30) as response:
        content = response.read(2_000_001)
        digest = response.headers.get("Docker-Content-Digest", "")
    if len(content) > 2_000_000 or digest != f"sha256:{hashlib.sha256(content).hexdigest()}":
        raise ValueError("Node image manifest digest verification failed")
    manifest = json.loads(content)
    if manifest.get("schemaVersion") != 2 or not manifest.get("manifests"):
        raise ValueError("Expected a multi-platform Node image manifest")
    return f"node:{tag}@{digest}"


# @testable true
# @tests tests_tooling/test_003_config.py::test_dependency_upgrade_updates_node_version_pin
# @matrix dependencies : node-version pinning upgrade
def upgrade_node(report: UpgradeReport | None = None) -> bool:
    """Upgrade Node.js to the latest version using nvm when available."""
    report = report or UpgradeReport()

    before_version = None
    try:
        result = run_command(
            [NODE_COMMAND, "--version"], check=False, capture=True, report=report
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
                    capture=True,
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
            upgrade = run_command(["sudo", "n", "latest"], check=False, report=report)
            verify = run_command(
                [NODE_COMMAND, "--version"], check=False, capture=True, report=report
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


# @testable true
# @tests tests_tooling/test_014_dependency_upgrade.py::test_npm_upgrade_uses_one_bounded_lookup_and_preserves_package_metadata
# @tests tests_tooling/test_014_dependency_upgrade.py::test_npm_lookup_failure_does_not_modify_or_install_dependencies
# @tests tests_tooling/test_014_dependency_upgrade.py::test_npm_interruption_records_completed_file_changes
# @matrix dependencies : upgrade failure-propagation package-lock cancellation upgrade-report
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
        package_json.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

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
        (
            "build/font-requirements.txt Pins",
            _changes_by(report, "pip", "build/font-requirements.txt"),
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
        if remaining > 0:
            print(f"  ... {remaining} more in the report")

    print(f"\nReport: {report_path}")


# @testable true
# @tests tests_tooling/test_014_dependency_upgrade.py::test_dependency_upgrade_stops_on_failure_and_saves_report
# @tests tests_tooling/test_014_dependency_upgrade.py::test_dependency_upgrade_saves_report_on_interrupt
# @matrix dependencies : cancellation failure-propagation upgrade-report
def upgrade_all(*, only: str | None = None) -> int:
    """Run selected upgrade steps with visible progress and a durable report."""
    report = UpgradeReport()
    success = True
    interrupted = False
    steps = [
        ("node", "Node.js", upgrade_node),
        ("npm", "npm packages", upgrade_npm_packages),
        ("python", "Python packages", upgrade_pip_packages),
        ("python", "Python dependency check", check_pip_environment),
        ("python", "Requirements files", update_requirements_files),
    ]
    steps = [item for item in steps if only is None or item[0] == only]
    try:
        for index, (_, step_name, step) in enumerate(steps, start=1):
            print(f"\n[{index}/{len(steps)}] {step_name}", flush=True)
            started = time.monotonic()
            try:
                step_ok = step(report)
                if not step_ok and report.errors:
                    success = False
                    break
            except Exception as error:
                report.add_error(step_name, str(error))
                success = False
                break
            print(f"  Finished in {time.monotonic() - started:.1f}s", flush=True)
    except KeyboardInterrupt:
        interrupted = True
        success = False
        report.add_error("Cancelled", "Interrupted by the user; completed changes are retained.")
    finally:
        success = success and not report.errors
        report_path = write_upgrade_report(report)
        print_upgrade_summary(report, success, report_path)
    if interrupted:
        return 130
    return 0 if success else 1
