"""Validate one completed frontend build across filesystem and Git readers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from runner.context import GIT_CLI


BUILD_METADATA_PATH = "lagniappe/web/static/build.json"
BUILD_CONSTANTS_PATH = "config/constants.py"
BUILD_SERVICE_WORKER_PATH = "lagniappe/web/static/sw.js"
PUBLICATION_CONTRACT_PATH = "build/publication.json"
BUILD_ID_RE = re.compile(r"^b[0-9a-f]{7}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# @testable infrastructure
# @covered-by runner/frontend_build.py::inspect_frontend_build
@dataclass(frozen=True)
class FrontendBuildValidation:
    """Validated metadata and the current generated-output fingerprint."""

    metadata: dict
    output_fingerprint: str


# @testable infrastructure
# @covered-by runner/frontend_build.py::inspect_frontend_build
class FilesystemFrontendBuildReader:
    """Read frontend publication inputs and outputs from one checkout."""

    def __init__(self, root):
        self.root = Path(root)

    def read_bytes(self, relative_path):
        return (self.root / relative_path).read_bytes()

    def list_files(self, relative_roots):
        paths = set()
        for relative_root in relative_roots:
            root = self.root / relative_root
            if not root.is_dir():
                continue
            paths.update(
                path.relative_to(self.root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
        return sorted(paths)


# @testable infrastructure
# @covered-by runner/frontend_build.py::inspect_frontend_build
class GitFrontendBuildReader:
    """Read frontend publication inputs and outputs from an index or commit."""

    def __init__(self, repo_root, *, revision=None, index=False, git_cli=None):
        if bool(revision) == bool(index):
            raise ValueError("Choose exactly one Git frontend build source.")
        self.repo_root = Path(repo_root)
        self.revision = revision
        self.index = index
        self.git_cli = git_cli or GIT_CLI or "git"

    def _run(self, arguments):
        return subprocess.run(
            [self.git_cli, *arguments],
            cwd=self.repo_root,
            capture_output=True,
            check=False,
        )

    def read_bytes(self, relative_path):
        object_name = (
            f":{relative_path}" if self.index else f"{self.revision}:{relative_path}"
        )
        result = self._run(["show", object_name])
        if result.returncode != 0:
            raise FileNotFoundError(relative_path)
        return result.stdout

    def list_files(self, relative_roots):
        if self.index:
            arguments = ["ls-files", "--cached", "-z", "--", *relative_roots]
        else:
            arguments = [
                "ls-tree",
                "-r",
                "-z",
                "--name-only",
                self.revision,
                "--",
                *relative_roots,
            ]
        result = self._run(arguments)
        if result.returncode != 0:
            raise RuntimeError("Git could not enumerate frontend source inputs.")
        return sorted(
            path.decode("utf-8") for path in result.stdout.split(b"\0") if path
        )


def _safe_relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix() if path.as_posix() == value else None


def _read(reader, path, issues, label):
    try:
        return reader.read_bytes(path)
    except (FileNotFoundError, OSError, RuntimeError) as error:
        issues.append(f"{label} is missing or unreadable: {path} ({error})")
        return None


def _read_json(reader, path, issues, label):
    content = _read(reader, path, issues, label)
    if content is None:
        return None, None
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        issues.append(f"{label} is not valid JSON: {path} ({error})")
        return None, content
    if not isinstance(value, dict):
        issues.append(f"{label} must contain a JSON object: {path}")
        return None, content
    return value, content


def _contract_paths(contract, key, issues):
    values = contract.get(key)
    if not isinstance(values, list) or not values:
        issues.append(f"Frontend publication contract {key} must be a nonempty list.")
        return []
    normalized = []
    for value in values:
        path = _safe_relative_path(value)
        if path is None:
            issues.append(
                f"Frontend publication contract has an unsafe {key} path: {value}"
            )
        else:
            normalized.append(path)
    if normalized != sorted(set(normalized)):
        issues.append(f"Frontend publication contract {key} must be unique and sorted.")
    return normalized


def _contract_prefixes(contract, issues):
    values = contract.get("required_artifact_prefixes")
    if not isinstance(values, list) or not values:
        issues.append(
            "Frontend publication contract required_artifact_prefixes must be a nonempty list."
        )
        return []
    normalized = []
    for value in values:
        if not isinstance(value, str) or not value or "\\" in value:
            issues.append(
                "Frontend publication contract has an unsafe "
                f"required_artifact_prefixes path: {value}"
            )
            continue
        suffix = "/" if value.endswith("/") else ""
        path = _safe_relative_path(value.removesuffix("/"))
        if path is None:
            issues.append(
                "Frontend publication contract has an unsafe "
                f"required_artifact_prefixes path: {value}"
            )
        else:
            normalized.append(f"{path}{suffix}")
    if normalized != sorted(set(normalized)):
        issues.append(
            "Frontend publication contract required_artifact_prefixes must be unique and sorted."
        )
    return normalized


def _source_digest(reader, contract, issues):
    source_roots = _contract_paths(contract, "source_roots", issues)
    source_files = _contract_paths(contract, "source_files", issues)
    try:
        paths = set(reader.list_files(source_roots))
    except (OSError, RuntimeError, UnicodeDecodeError) as error:
        issues.append(f"Frontend source inputs could not be enumerated: {error}")
        return None

    contents = {}
    for path in sorted(paths | set(source_files)):
        normalized = _safe_relative_path(path)
        if normalized is None:
            issues.append(f"Frontend source inventory contains an unsafe path: {path}")
            continue
        content = _read(reader, normalized, issues, "Frontend source input")
        if content is not None:
            contents[normalized] = content

    digest = hashlib.sha256(f"frontend-source-v{contract['schema']}\0".encode())
    for path, content in sorted(contents.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


# @testable true
# @tests tests_tooling/test_005a_frontend_build.py::test_frontend_build_validator_checks_recursive_artifacts_and_source_identity
# @tests tests_tooling/test_005a_frontend_build.py::test_frontend_build_validator_rejects_unsafe_and_incoherent_metadata
# @features frontend-build
# @dimensions artifact-integrity source-integrity build-metadata path-safety build-identity
def inspect_frontend_build(
    reader,
    *,
    expected_mode=None,
    expected_version=None,
):
    """Return a validated build and a complete list of publication issues."""
    issues = []
    metadata, metadata_content = _read_json(
        reader,
        BUILD_METADATA_PATH,
        issues,
        "Frontend build metadata",
    )
    contract, _ = _read_json(
        reader,
        PUBLICATION_CONTRACT_PATH,
        issues,
        "Frontend publication contract",
    )
    if metadata is None or contract is None:
        return None, issues
    if metadata.get("schema") != 1:
        issues.append("Frontend build metadata schema is missing or unsupported.")
    if contract.get("schema") != 1:
        issues.append("Frontend publication contract schema is missing or unsupported.")
        return None, issues

    build_id = metadata.get("build_id")
    mode = metadata.get("mode")
    version = metadata.get("version")
    if not isinstance(build_id, str) or not BUILD_ID_RE.fullmatch(build_id):
        issues.append("Frontend build metadata has an invalid build ID.")
    if mode not in {"development", "production"}:
        issues.append("Frontend build metadata has an invalid mode.")
    if not isinstance(version, str) or not version:
        issues.append("Frontend build metadata has an invalid version.")
    if expected_mode is not None and mode != expected_mode:
        issues.append(
            f"Frontend build mode is {mode or '<missing>'}; expected {expected_mode}."
        )
    if expected_version is not None and version != expected_version:
        issues.append(
            f"Frontend build version is {version or '<missing>'}; expected {expected_version}."
        )

    source = metadata.get("source")
    recorded_source = source.get("sha256") if isinstance(source, dict) else None
    if not isinstance(recorded_source, str) or not SHA256_RE.fullmatch(recorded_source):
        issues.append("Frontend build metadata has an invalid source identity.")
    current_source = _source_digest(reader, contract, issues)
    if recorded_source and current_source and recorded_source != current_source:
        issues.append("Frontend build was created from different source inputs.")

    required_artifacts = _contract_paths(contract, "required_artifacts", issues)
    required_prefixes = _contract_prefixes(contract, issues)
    exclusive_roots = _contract_paths(
        contract,
        "exclusive_artifact_roots",
        issues,
    )
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        issues.append("Frontend build metadata has no artifact inventory.")
        artifacts = []

    actual_paths = []
    output_digest = hashlib.sha256(metadata_content or b"")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            issues.append("Frontend build artifact records must be objects.")
            continue
        path = _safe_relative_path(artifact.get("path"))
        sha256 = artifact.get("sha256")
        size = artifact.get("size")
        if path is None:
            issues.append(
                f"Frontend build artifact has an unsafe path: {artifact.get('path')}"
            )
            continue
        actual_paths.append(path)
        if path == BUILD_METADATA_PATH or path.endswith(".map"):
            issues.append(f"Frontend build artifact is not publishable: {path}")
        if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
            issues.append(f"Frontend build artifact has an invalid hash: {path}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            issues.append(f"Frontend build artifact has an invalid size: {path}")
        content = _read(reader, path, issues, "Frontend build artifact")
        if content is None:
            continue
        output_digest.update(path.encode())
        output_digest.update(b"\0")
        output_digest.update(content)
        output_digest.update(b"\0")
        if isinstance(size, int) and len(content) != size:
            issues.append(f"Frontend build artifact size does not match: {path}")
        current_hash = hashlib.sha256(content).hexdigest()
        if isinstance(sha256, str) and current_hash != sha256:
            issues.append(f"Frontend build artifact hash does not match: {path}")

    if actual_paths != sorted(set(actual_paths)):
        issues.append("Frontend build artifacts must be unique and sorted by path.")
    for required in required_artifacts:
        if required not in actual_paths:
            issues.append(f"Frontend build is missing required artifact: {required}")
    for prefix in required_prefixes:
        if not any(path.startswith(prefix) for path in actual_paths):
            issues.append(
                f"Frontend build has no artifact under required prefix: {prefix}"
            )
    try:
        exclusive_paths = reader.list_files(exclusive_roots)
    except (OSError, RuntimeError, UnicodeDecodeError) as error:
        issues.append(f"Frontend build outputs could not be enumerated: {error}")
        exclusive_paths = []
    for path in exclusive_paths:
        normalized = _safe_relative_path(path)
        if normalized is None:
            issues.append(f"Frontend build output has an unsafe path: {path}")
        elif normalized not in actual_paths:
            issues.append(
                f"Frontend build output is not in the artifact inventory: {normalized}"
            )

    constants = _read(
        reader,
        BUILD_CONSTANTS_PATH,
        issues,
        "Frontend build constants",
    )
    if constants is not None:
        match = re.search(
            rb'(?m)^BUILD_ID\s*=\s*"([^"]+)"\s*$',
            constants,
        )
        constants_build_id = match.group(1).decode() if match else None
        if constants_build_id != build_id:
            issues.append(
                "Frontend build metadata and constants have different build IDs."
            )

    service_worker = _read(
        reader,
        BUILD_SERVICE_WORKER_PATH,
        issues,
        "Frontend service worker",
    )
    if service_worker is not None and isinstance(build_id, str):
        if build_id.encode() not in service_worker:
            issues.append(
                "Frontend service worker does not contain the current build ID."
            )

    validation = None
    if not issues:
        validation = FrontendBuildValidation(
            metadata=metadata,
            output_fingerprint=output_digest.hexdigest(),
        )
    return validation, issues


# @testable true
# @tests tests_tooling/test_005a_frontend_build.py::test_verify_frontend_build_reports_actionable_failure
# @tests tests_tooling/test_003_config.py::test_deploy_modes_separate_dev_build_from_setup_publish
# @features frontend-build deploy
# @dimensions validation safe-failure
def verify_frontend_build(
    *,
    app_dir,
    expected_mode=None,
    expected_version=None,
):
    """Require a coherent completed build from the filesystem."""
    validation, issues = inspect_frontend_build(
        FilesystemFrontendBuildReader(app_dir),
        expected_mode=expected_mode,
        expected_version=expected_version,
    )
    if issues:
        detail = "\n".join(f"  - {issue}" for issue in issues)
        raise RuntimeError(
            "Frontend build is incomplete or stale. Rerun the appropriate "
            f"npm build command before continuing:\n{detail}"
        )
    return validation


__all__ = [
    "BUILD_METADATA_PATH",
    "FilesystemFrontendBuildReader",
    "FrontendBuildValidation",
    "GitFrontendBuildReader",
    "inspect_frontend_build",
    "verify_frontend_build",
]
