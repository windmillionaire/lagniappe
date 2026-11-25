"""Upgrade Node.js and publish its version declarations together."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import tempfile
from urllib.request import Request, urlopen

from runner.context import NODE_CLI

from .commands import run_command, run_nvm_command
from .reporting import UpgradeReport

NODE_COMMAND = NODE_CLI or "node"
NODE_VERSION_PIN_PATH = Path(".nvmrc")
NODE_DOCKERFILE_PATH = Path("runner/hosted_e2e_container/Dockerfile")


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


def _publish_node_declarations(replacements, report):
    """Stage the full set, restoring prior files if publication is interrupted."""
    directories = []
    prepared = []
    attempted = []
    retain_backups = False
    try:
        for destination, content in replacements.items():
            content = content.encode("utf-8")
            existed = destination.exists()
            if existed and destination.read_bytes() == content:
                continue
            directory = Path(tempfile.mkdtemp(
                prefix=f".{destination.name}-", dir=destination.parent
            ))
            directories.append(directory)
            candidate = directory / "new"
            backup = directory / "previous" if existed else None
            if backup is not None:
                shutil.copy2(destination, backup)
            candidate.write_bytes(content)
            if backup is not None:
                shutil.copymode(backup, candidate)
            prepared.append((destination, candidate, backup))

        for destination, candidate, backup in prepared:
            # Track the attempt before rename, including an interrupt delivered
            # just after the filesystem has already replaced the destination.
            attempted.append((destination, backup))
            candidate.replace(destination)
    except BaseException as error:
        # Never discard recovery copies if recovery itself is interrupted.
        retain_backups = True
        recovery_errors = []
        for destination, backup in reversed(attempted):
            try:
                if backup is not None:
                    backup.replace(destination)
                else:
                    destination.unlink(missing_ok=True)
            except OSError as recovery_error:
                recovery = (
                    f"restore the previous file from {backup}"
                    if backup is not None
                    else "remove this newly created file (previously absent)"
                )
                recovery_errors.append(f"{destination}: {recovery_error}; {recovery}")
        if recovery_errors:
            report.add_error(
                "Node.js declaration recovery",
                f"Publication failed ({type(error).__name__}: {error}); "
                "restoration was incomplete: " + "; ".join(recovery_errors)
                + ". Recovery files retained in: "
                + ", ".join(str(directory) for directory in directories),
            )
        else:
            retain_backups = False
        raise
    finally:
        if not retain_backups:
            for directory in directories:
                try:
                    shutil.rmtree(directory)
                except OSError as cleanup_error:
                    report.add_note(
                        f"Could not remove Node.js staging directory {directory}: "
                        f"{cleanup_error}"
                    )


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

    # Resolve the image and validate inputs before staging any declaration.
    try:
        _publish_node_declarations(replacements, report)
    except OSError as error:
        report.add_error("Node.js declarations", f"Could not publish {normalized}: {error}")
        return False
    report.add_change("node", "Node.js pin", before, normalized, str(path))
    report.add_change("node", "Node.js engine", before_engine, engine, str(package_path))
    report.add_change("node", "Hosted Node image", matches[0].group(1), image, str(docker_path))
    return True


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
