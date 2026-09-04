"""Build and verify the public, content-addressed MCP adapter artifacts."""

from __future__ import annotations

import argparse
import ast
import base64
import configparser
import csv
from dataclasses import dataclass
from email.parser import Parser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from types import SimpleNamespace
from urllib.parse import unquote, urlparse
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
# ``run.py mcp-artifact`` deliberately executes this file with Python's
# isolated mode.  Make only this repository root importable so the artifact
# builder can reach the standard-library-only managed-uv verifier without
# inheriting the caller's import path.
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
MCP_PROJECT_RELATIVE = Path("clients/lagniappe_mcp")
MCP_RELEASES_RELATIVE = MCP_PROJECT_RELATIVE / "releases"
MCP_LEDGER_RELATIVE = MCP_RELEASES_RELATIVE / "releases.json"
MCP_DEPLOY_RELATIVE = Path("lagniappe/web/static/mcp")
RUNNER_GIT_ENV = "LAGNIAPPE_RUNNER_GIT_CLI"
FRONTEND_BUILD_RELATIVE = Path("lagniappe/web/static/build.json")
PYPROJECT_RELATIVE = MCP_PROJECT_RELATIVE / "pyproject.toml"
LOCK_RELATIVE = MCP_PROJECT_RELATIVE / "uv.lock"
BOOTSTRAP_RELATIVE = MCP_PROJECT_RELATIVE / "uv-bootstrap.json"
OPENAPI_SOURCE_RELATIVE = Path("lagniappe/web/routes/api/main.py")
APPLICATION_CONTRACT_RELATIVE = Path("lagniappe/core/tools/ai/external_api.py")
MCP_PACKAGE_NAME = "lagniappe-mcp"
MCP_ENTRY_POINT = "lagniappe-mcp"
MCP_API_VERSION = "v1"
MCP_TEST_REQUIREMENTS = ("pytest==9.1.1", "uv-build==0.12.9")
MCP_LEDGER_SCHEMA = 1
MCP_MANIFEST_SCHEMA = 1
MCP_PLATFORM = {
    "id": "linux-x86_64-cpython-3.14",
    "system": "linux",
    "architecture": "x86_64",
    "libc": "glibc>=2.17",
    "python": "3.14",
}
MCP_PLATFORM_MARKERS = {
    "implementation_name != 'PyPy'": True,
    "platform_python_implementation != 'PyPy'": True,
    "sys_platform != 'emscripten'": True,
    "sys_platform == 'emscripten'": False,
    "sys_platform == 'win32'": False,
}
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_DEPLOYMENT_BYTES = 64 * 1024 * 1024
MAX_DEPLOYMENT_FILES = 128
MAX_WHEEL_MEMBERS = 512
MAX_WHEEL_EXPANDED_BYTES = 64 * 1024 * 1024
SOURCE_DATE_EPOCH = "315532800"
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
EXACT_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[(?P<extras>[A-Za-z0-9_,.-]+)\])?"
    r"==(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)$"
)
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
FROZEN_OPENAPI_APP_NAME = "Lagniappe"
FROZEN_OPENAPI_ORIGIN = "https://application.invalid"
_PUBLIC_SCHEMA_HOSTS = frozenset({"json-schema.org"})
_PUBLIC_URL_RE = re.compile(r"https?://(?P<host>[A-Za-z0-9.-]+)(?::\d{1,5})?")
_PUBLIC_INSTANCE_HOST_RE = re.compile(
    r"(?i)(?:^|\.)(?:appspot\.com|r\.appspot\.com|run\.app)$"
)
_PUBLIC_LAGNIAPPE_KEY_RE = re.compile(
    r"\blgn_[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{40,50}\b"
)
_PUBLIC_RECOGNIZED_CREDENTIAL_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b"
)
_PUBLIC_BEARER_RE = re.compile(
    r"(?i)\bbearer[ \t]+(?![<{[$'\"])[A-Za-z0-9._~+/=-]{16,}\b"
)
_PUBLIC_SENSITIVE_LITERAL_RE = re.compile(
    r"""(?ix)
    \b(?:[a-z0-9]+[_-])*
    (?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password|credential)
    \b["']?\s*[:=]\s*
    (?P<quote>["'])(?P<value>[^"'\\\r\n]{8,})(?P=quote)
    """
)
_PUBLIC_UNIX_LOCAL_PATH_RE = re.compile(
    r"(?:^|[\s\"'=])(?:"
    r"/(?:home|tmp|workspace|workspaces|builds|__w)/"
    r"|/Users/|/private/(?:tmp|var/folders)/"
    r"|/mnt/[A-Za-z]/Users/"
    r"|/opt/(?:runner|actions-runner)/"
    r")[^\s\"'<>]+"
)
_PUBLIC_WINDOWS_LOCAL_PATH_RE = re.compile(
    r"(?i)(?:^|[\s\"'=])[A-Z]:[\\/]+(?:Users|Temp|Windows\\Temp)[\\/]+"
    r"[^\s\"'<>]+"
)


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_rejects_rebinding_and_corruption
# @matrix mcp-package : fail-closed immutable-release
class McpArtifactError(RuntimeError):
    """Raised when MCP release or deploy artifacts fail closed validation."""


@dataclass(frozen=True)
class ProjectMetadata:
    version: str
    requires_python: str
    dependencies: tuple[str, ...]
    source_url: str
    license_expression: str
    license_url: str


@dataclass(frozen=True)
class WheelMetadata:
    version: str
    size: int
    sha256: str
    filename: str
    requires_python: str
    dependencies: tuple[str, ...]


# @testable false
# @covered-by runner/mcp_artifact.py::_manifest
# @reason canonical serialization is exercised through manifest construction and equality
def _canonical_json(value) -> bytes:
    return (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


# @testable false
# @covered-by runner/mcp_artifact.py::_inspect_wheel
# @reason byte hashing is exercised through verified content-addressed wheel metadata
def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


# @testable false
# @covered-by runner/mcp_artifact.py::_compatibility
# @reason bounded file hashing is exercised through frozen compatibility metadata
def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# @testable false
# @covered-by runner/mcp_artifact.py::_dependency_graph
# @reason package-name normalization is exercised by closed lock-graph validation
def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


# @testable false
# @covered-by runner/mcp_artifact.py::_inspect_wheel
# @reason the fixed wheel name is exercised by exact archive inspection
def _wheel_filename(version: str) -> str:
    return f"lagniappe_mcp-{version}-py3-none-any.whl"


# @testable false
# @covered-by runner/mcp_artifact.py::assemble_deployment_artifacts
# @reason the relative release layout is exercised through deploy-tree assembly
def _artifact_relative_path(version: str, digest: str) -> Path:
    return Path(version) / digest / _wheel_filename(version)


# @testable false
# @covered-by runner/mcp_artifact.py::build_and_promote_release
# @reason public content-addressed paths are exercised through release promotion
def _public_artifact_path(version: str, digest: str) -> str:
    return f"/mcp/releases/{_artifact_relative_path(version, digest).as_posix()}"


# @testable false
# @covered-by runner/mcp_artifact.py::validate_release_inputs
# @reason bounded release-input reads and LFS refusal are exercised through preflight validation
def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        value = path.read_bytes()
    except OSError as error:
        raise McpArtifactError(f"{label} is missing or unreadable.") from error
    if value.startswith(LFS_POINTER):
        raise McpArtifactError(f"{label} is a Git LFS pointer, not release bytes.")
    return value


# @testable false
# @covered-by runner/mcp_artifact.py::check_deployment_artifacts
# @reason strict deploy JSON reads are exercised through complete deploy preflight
def _read_json(path: Path, *, label: str):
    try:
        return json.loads(_read_bytes(path, label=label))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise McpArtifactError(f"{label} is not valid UTF-8 JSON.") from error


# @testable false
# @covered-by runner/mcp_artifact.py::load_release_ledger
# @reason closed-object validation is exercised through strict ledger loading
def _require_exact_keys(value, expected, *, label: str) -> None:
    if not isinstance(value, dict):
        raise McpArtifactError(f"{label} must be an object.")
    expected = set(expected)
    actual = set(value)
    if actual != expected:
        details = []
        if expected - actual:
            details.append("missing " + ", ".join(sorted(expected - actual)))
        if actual - expected:
            details.append("unexpected " + ", ".join(sorted(actual - expected)))
        raise McpArtifactError(f"{label} has invalid fields ({'; '.join(details)}).")


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_rejects_rebinding_and_corruption
# @matrix mcp-package : fail-closed release-validation url-policy
def _require_https_url(value, *, label: str) -> str:
    if not isinstance(value, str):
        raise McpArtifactError(f"{label} must be an HTTPS URL.")
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as error:
        raise McpArtifactError(f"{label} must be an HTTPS URL.") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise McpArtifactError(
            f"{label} must be an HTTPS URL without credentials, query, or fragment."
        )
    return value


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_public_artifact_audit_rejects_wheel_leaks
# @tests tests_tooling/test_012b_mcp_artifact.py::test_public_artifact_audit_rejects_ledger_and_manifest_leaks
# @matrix mcp-package release : credential-audit instance-neutrality path-safety public-artifact
def _audit_public_content(
    blobs: list[tuple[str, bytes]],
    *,
    repo_root: Path,
    allowed_urls: tuple[str, ...],
) -> None:
    """Reject installation-specific private values from public release text."""
    allowed_hosts = set(_PUBLIC_SCHEMA_HOSTS)
    for value in allowed_urls:
        try:
            host = urlparse(value).hostname
        except ValueError as error:
            raise McpArtifactError(
                "MCP public artifact URL context is invalid."
            ) from error
        if not host:
            raise McpArtifactError("MCP public artifact URL context is invalid.")
        allowed_hosts.add(host.casefold())

    forbidden_values = {str(repo_root.resolve())}
    for name, value in os.environ.items():
        if (
            name.startswith("LAGNIAPPE_")
            and name.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
            and len(value) >= 12
        ):
            forbidden_values.add(value)

    for label, raw in blobs:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise McpArtifactError(
                f"{label} is not auditable UTF-8 public artifact content."
            ) from error
        if any(value in text for value in forbidden_values):
            raise McpArtifactError(
                f"{label} contains private build or credential data."
            )
        if (
            _PUBLIC_LAGNIAPPE_KEY_RE.search(text)
            or _PUBLIC_RECOGNIZED_CREDENTIAL_RE.search(text)
            or _PUBLIC_BEARER_RE.search(text)
            or _PUBLIC_SENSITIVE_LITERAL_RE.search(text)
        ):
            raise McpArtifactError(
                f"{label} contains an embedded credential or test secret."
            )
        if (
            "file://" in text.casefold()
            or _PUBLIC_UNIX_LOCAL_PATH_RE.search(text)
            or _PUBLIC_WINDOWS_LOCAL_PATH_RE.search(text)
        ):
            raise McpArtifactError(f"{label} contains a machine-local path.")
        for match in _PUBLIC_URL_RE.finditer(text):
            host = match.group("host").casefold().rstrip(".")
            if _PUBLIC_INSTANCE_HOST_RE.search(host):
                raise McpArtifactError(
                    f"{label} contains an application instance hostname."
                )
            if host not in allowed_hosts:
                raise McpArtifactError(
                    f"{label} contains an undeclared absolute URL host."
                )


# @testable false
# @covered-by runner/mcp_artifact.py::_dependency_graph
# @reason exact requirement parsing is exercised through locked dependency graph validation
def _parse_exact_requirement(requirement: str) -> tuple[str, str]:
    match = EXACT_REQUIREMENT_RE.fullmatch(requirement.replace(" ", ""))
    if not match:
        raise McpArtifactError(
            f"MCP runtime requirement is not one exact, marker-free pin: {requirement!r}."
        )
    return _canonical_name(match.group("name")), match.group("version")


# @testable false
# @covered-by runner/mcp_artifact.py::build_and_promote_release
# @reason project metadata is consumed and cross-checked by release promotion
def _load_project(repo_root: Path) -> ProjectMetadata:
    path = repo_root / PYPROJECT_RELATIVE
    try:
        document = tomllib.loads(_read_bytes(path, label="MCP pyproject").decode())
        project = document["project"]
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise McpArtifactError("MCP pyproject metadata is invalid.") from error

    if project.get("name") != MCP_PACKAGE_NAME:
        raise McpArtifactError(f"MCP project name must be {MCP_PACKAGE_NAME!r}.")
    version = project.get("version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise McpArtifactError("MCP adapter version must use stable X.Y.Z form.")
    requires_python = project.get("requires-python")
    if requires_python != ">=3.14,<3.15":
        raise McpArtifactError("MCP Python support must remain >=3.14,<3.15.")
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise McpArtifactError("MCP runtime dependencies must be a nonempty pin list.")
    normalized = []
    seen = set()
    for requirement in dependencies:
        if not isinstance(requirement, str):
            raise McpArtifactError("MCP runtime requirements must be strings.")
        name, _version = _parse_exact_requirement(requirement)
        if name in seen:
            raise McpArtifactError(f"MCP runtime dependency {name!r} is duplicated.")
        seen.add(name)
        normalized.append(requirement.replace(" ", ""))

    scripts = project.get("scripts")
    if (
        not isinstance(scripts, dict)
        or scripts.get(MCP_ENTRY_POINT) != "lagniappe_mcp.cli:main"
    ):
        raise McpArtifactError("MCP console entry point metadata is invalid.")
    urls = project.get("urls")
    if not isinstance(urls, dict):
        raise McpArtifactError("MCP source and license URLs are required.")
    source_url = _require_https_url(urls.get("Source"), label="MCP source URL")
    license_url = _require_https_url(urls.get("License"), label="MCP license URL")
    license_expression = project.get("license")
    if license_expression != "GPL-3.0-or-later":
        raise McpArtifactError("MCP wheel must declare GPL-3.0-or-later.")

    build_system = document.get("build-system")
    if not isinstance(build_system, dict) or build_system.get("requires") != [
        "uv_build==0.12.9"
    ]:
        raise McpArtifactError("MCP build backend must be exactly pinned.")
    if build_system.get("build-backend") != "uv_build":
        raise McpArtifactError("MCP build backend must be uv_build.")
    dependency_groups = document.get("dependency-groups")
    test_requirements = (
        dependency_groups.get("test") if isinstance(dependency_groups, dict) else None
    )
    if test_requirements != list(MCP_TEST_REQUIREMENTS):
        raise McpArtifactError(
            "MCP locked test group must exactly pin pytest and the build backend."
        )
    tool_uv = document.get("tool", {}).get("uv", {})
    if tool_uv.get("required-version") != "==0.12.9":
        raise McpArtifactError("MCP project must require uv 0.12.9 exactly.")

    return ProjectMetadata(
        version=version,
        requires_python=requires_python,
        dependencies=tuple(normalized),
        source_url=source_url,
        license_expression=license_expression,
        license_url=license_url,
    )


# @testable false
# @covered-by runner/mcp_artifact.py::_inspect_wheel
# @reason member-name safety is exercised through strict wheel inspection
def _safe_zip_name(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name:
        return False
    candidate = PurePosixPath(name)
    return not candidate.is_absolute() and all(
        part not in {"", ".", ".."} for part in candidate.parts
    )


# @testable false
# @covered-by runner/mcp_artifact.py::_inspect_wheel
# @reason wheel requirement parsing is exercised through metadata/source comparison
def _metadata_requirements(message) -> tuple[str, ...]:
    requirements = []
    names = set()
    for requirement in message.get_all("Requires-Dist", []):
        if ";" in requirement:
            raise McpArtifactError("MCP wheel contains a marker-dependent requirement.")
        name, _version = _parse_exact_requirement(requirement)
        if name in names:
            raise McpArtifactError(
                "MCP wheel contains a duplicate runtime requirement."
            )
        names.add(name)
        requirements.append(requirement.replace(" ", ""))
    return tuple(requirements)


# @testable false
# @covered-by runner/mcp_artifact.py::_inspect_wheel
# @reason RECORD coverage and hashes are exercised through complete wheel inspection
def _verify_record(
    archive: zipfile.ZipFile, names: list[str], record_name: str
) -> None:
    try:
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    except (KeyError, UnicodeDecodeError, csv.Error) as error:
        raise McpArtifactError("MCP wheel RECORD is invalid.") from error
    records = {}
    for row in rows:
        if len(row) != 3 or not _safe_zip_name(row[0]) or row[0] in records:
            raise McpArtifactError("MCP wheel RECORD contains an invalid member.")
        records[row[0]] = (row[1], row[2])
    if set(records) != set(names):
        raise McpArtifactError("MCP wheel RECORD does not cover its exact file list.")
    for name in names:
        digest, size = records[name]
        if name == record_name:
            if digest or size:
                raise McpArtifactError(
                    "MCP wheel RECORD must leave its own hash empty."
                )
            continue
        data = archive.read(name)
        expected_digest = base64.urlsafe_b64encode(
            hashlib.sha256(data).digest()
        ).rstrip(b"=")
        if digest != f"sha256={expected_digest.decode('ascii')}" or size != str(
            len(data)
        ):
            raise McpArtifactError(f"MCP wheel RECORD mismatch for {name!r}.")


# @testable false
# @covered-by runner/mcp_artifact.py::_inspect_wheel
# @covered-by runner/mcp_artifact.py::_source_inputs
# @reason the closed source-to-wheel map is exercised through artifact inspection
def _package_source_files(repo_root: Path) -> dict[str, Path]:
    source_root = repo_root / MCP_PROJECT_RELATIVE / "src"
    if not source_root.is_dir() or source_root.is_symlink():
        raise McpArtifactError("MCP package source root is missing or unsafe.")
    entries = sorted(source_root.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise McpArtifactError("MCP package source may not contain symlinks.")
    source_files: dict[str, Path] = {}
    for source in entries:
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if "__pycache__" in relative.parts or source.suffix == ".pyc":
            continue
        if source.suffix != ".py":
            raise McpArtifactError(
                f"MCP package contains an undeclared non-Python source input: {relative}."
            )
        source_files[relative.as_posix()] = source
    if not source_files:
        raise McpArtifactError("MCP package contains no Python source files.")
    return source_files


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_copies_only_supported_content_addressed_wheels
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_rejects_rebinding_and_corruption
# @tests tests_tooling/test_012b_mcp_artifact.py::test_historical_wheel_remains_valid_after_current_source_changes
# @matrix mcp-package release : expanded-size fail-closed immutable-ledger member-count release-validation source-verification
def _inspect_wheel(
    path: Path,
    project: ProjectMetadata,
    repo_root: Path,
    *,
    match_current_source: bool = True,
) -> WheelMetadata:
    raw = _read_bytes(path, label="MCP release wheel")
    if not raw or len(raw) > MAX_ARTIFACT_BYTES:
        raise McpArtifactError(
            f"MCP wheel must be nonempty and at most {MAX_ARTIFACT_BYTES} bytes."
        )
    expected_filename = _wheel_filename(project.version)
    if path.name != expected_filename:
        raise McpArtifactError(f"MCP wheel filename must be {expected_filename!r}.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                not infos
                or len(infos) > MAX_WHEEL_MEMBERS
                or len(names) != len(set(names))
            ):
                raise McpArtifactError(
                    "MCP wheel has an invalid or duplicate file list."
                )
            if sum(info.file_size for info in infos) > MAX_WHEEL_EXPANDED_BYTES:
                raise McpArtifactError("MCP wheel expands beyond its safety ceiling.")
            for info in infos:
                mode = (info.external_attr >> 16) & 0o170000
                invalid_type = (
                    info.is_dir() and (info.file_size != 0 or mode not in (0, 0o040000))
                ) or (not info.is_dir() and mode not in (0, 0o100000))
                if (
                    not _safe_zip_name(info.filename)
                    or info.flag_bits & 0x1
                    or invalid_type
                ):
                    raise McpArtifactError("MCP wheel contains an unsafe member.")
            prefix = f"lagniappe_mcp-{project.version}.dist-info/"
            metadata_name = f"{prefix}METADATA"
            wheel_name = f"{prefix}WHEEL"
            entries_name = f"{prefix}entry_points.txt"
            record_name = f"{prefix}RECORD"
            required_members = {
                metadata_name,
                wheel_name,
                entries_name,
                record_name,
            }
            for required in required_members:
                if names.count(required) != 1:
                    raise McpArtifactError(f"MCP wheel is missing {required!r}.")
            file_names = {info.filename for info in infos if not info.is_dir()}
            package_members = file_names - required_members
            if (
                not package_members
                or any(
                    PurePosixPath(name).parts[0] != "lagniappe_mcp"
                    or PurePosixPath(name).suffix != ".py"
                    or "__pycache__" in PurePosixPath(name).parts
                    for name in package_members
                )
                or file_names != package_members | required_members
            ):
                raise McpArtifactError(
                    "MCP wheel contains an unauthorized package member."
                )
            expected_directories = {
                PurePosixPath(*parts[:index]).as_posix() + "/"
                for name in file_names
                for parts in (PurePosixPath(name).parts,)
                for index in range(1, len(parts))
            }
            directory_names = {info.filename for info in infos if info.is_dir()}
            if directory_names != expected_directories:
                raise McpArtifactError(
                    "MCP wheel contains an unauthorized directory member."
                )
            if match_current_source:
                source_files = _package_source_files(repo_root)
                if package_members != set(source_files):
                    raise McpArtifactError(
                        "MCP wheel file list does not exactly match committed package source."
                    )
                for name, source in source_files.items():
                    if archive.read(name) != _read_bytes(
                        source,
                        label=f"MCP package source {name}",
                    ):
                        raise McpArtifactError(
                            f"MCP wheel member {name!r} disagrees with package source."
                        )
            message = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
            if _canonical_name(message.get("Name", "")) != MCP_PACKAGE_NAME:
                raise McpArtifactError(
                    "MCP wheel package name disagrees with pyproject."
                )
            if message.get("Version") != project.version:
                raise McpArtifactError("MCP wheel version disagrees with pyproject.")
            wheel_python_requirement = message.get("Requires-Python", "").replace(
                " ", ""
            )
            if wheel_python_requirement != project.requires_python.replace(" ", ""):
                raise McpArtifactError(
                    "MCP wheel Python requirement disagrees with pyproject."
                )
            dependencies = _metadata_requirements(message)
            if dependencies != project.dependencies:
                raise McpArtifactError(
                    "MCP wheel dependency pins disagree with pyproject."
                )
            if message.get("License-Expression") != project.license_expression:
                raise McpArtifactError(
                    "MCP wheel license metadata disagrees with pyproject."
                )
            project_url_values = message.get_all("Project-URL", [])
            project_urls = {}
            for raw_url in project_url_values:
                name, separator, value = raw_url.partition(",")
                name = name.strip()
                if not separator or not name or name in project_urls:
                    raise McpArtifactError("MCP wheel project URL metadata is invalid.")
                project_urls[name] = value.strip()
            if project_urls != {
                "Source": project.source_url,
                "License": project.license_url,
            }:
                raise McpArtifactError(
                    "MCP wheel source/license metadata disagrees with pyproject."
                )

            wheel_message = Parser().parsestr(archive.read(wheel_name).decode("utf-8"))
            if wheel_message.get("Root-Is-Purelib", "").casefold() != "true":
                raise McpArtifactError("MCP wheel does not declare a pure-Python root.")
            if wheel_message.get_all("Tag", []) != ["py3-none-any"]:
                raise McpArtifactError(
                    "MCP wheel must have exactly the py3-none-any tag."
                )
            entry_points = configparser.ConfigParser(interpolation=None)
            entry_points.read_string(archive.read(entries_name).decode("utf-8"))
            if set(entry_points.sections()) != {"console_scripts"} or dict(
                entry_points["console_scripts"]
            ) != {MCP_ENTRY_POINT: "lagniappe_mcp.cli:main"}:
                raise McpArtifactError("MCP wheel console entry point is invalid.")
            _verify_record(
                archive,
                [info.filename for info in infos if not info.is_dir()],
                record_name,
            )
            _audit_public_content(
                [
                    (f"MCP wheel member {info.filename!r}", archive.read(info.filename))
                    for info in infos
                    if not info.is_dir()
                ],
                repo_root=repo_root,
                allowed_urls=(project.source_url, project.license_url),
            )
    except (zipfile.BadZipFile, UnicodeDecodeError, configparser.Error) as error:
        raise McpArtifactError(
            "MCP release wheel is not a valid wheel archive."
        ) from error

    return WheelMetadata(
        version=project.version,
        size=len(raw),
        sha256=_sha256_bytes(raw),
        filename=expected_filename,
        requires_python=project.requires_python,
        dependencies=dependencies,
    )


# @testable false
# @covered-by runner/mcp_artifact.py::build_and_promote_release
# @reason the closed package-input list is exercised through source-bound promotion
def _source_inputs(repo_root: Path) -> list[Path]:
    project_root = repo_root / MCP_PROJECT_RELATIVE
    candidates = [
        project_root / "README.md",
        project_root / "pyproject.toml",
        project_root / "uv-bootstrap.json",
        project_root / "uv.lock",
        *sorted(_package_source_files(repo_root).values()),
    ]
    if any(not path.is_file() or path.is_symlink() for path in candidates):
        raise McpArtifactError("MCP source inputs are missing or unsafe.")
    return candidates


# @testable false
# @covered-by runner/mcp_artifact.py::build_and_promote_release
# @reason length-framed source hashing is exercised through immutable release binding
def _source_digest(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for path in _source_inputs(repo_root):
        relative = path.relative_to(repo_root).as_posix().encode("utf-8")
        data = _read_bytes(path, label="MCP source input")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


# @testable false
# @covered-by runner/mcp_artifact.py::_compatibility
# @reason literal-only source extraction is exercised by frozen compatibility validation
def _literal_assignments(path: Path, names: set[str]) -> dict[str, object]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise McpArtifactError("MCP compatibility source is unreadable.") from error
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in names:
            try:
                values[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    if set(values) != names:
        raise McpArtifactError("MCP compatibility constants are missing or nonliteral.")
    return values


# @testable false
# @covered-by runner/mcp_artifact.py::_frozen_openapi_document
# @reason this closed AST primitive is exercised by canonical OpenAPI hashing
def _openapi_constant(node: ast.expr):
    """Evaluate the small literal expression subset used by OpenAPI constants."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
        if isinstance(node.value, bool):
            raise ValueError("booleans are not OpenAPI contract constants")
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        values = tuple(_openapi_constant(item) for item in node.elts)
        if not all(isinstance(item, str) for item in values):
            raise ValueError("OpenAPI sequences must contain strings")
        return values
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _openapi_constant(node.left)
        right = _openapi_constant(node.right)
        if (
            isinstance(left, bool)
            or not isinstance(left, int)
            or isinstance(right, bool)
            or not isinstance(right, int)
        ):
            raise ValueError("OpenAPI multiplication must use integers")
        value = left * right
        if not 0 <= value <= 2**63 - 1:
            raise ValueError("OpenAPI integer is outside the supported range")
        return value
    raise ValueError("unsupported OpenAPI constant expression")


# @testable false
# @covered-by runner/mcp_artifact.py::_frozen_openapi_document
# @reason application constants are validated through the canonical document
def _openapi_contract_constants(repo_root: Path) -> dict[str, object]:
    names = {
        "CONTRACT_VERSION",
        "MAX_FILE_BYTES",
        "MAX_PLAN_FILES",
        "MAX_VALIDATION_ERRORS",
        "SUPPORTED_PLAN_TOOLS",
        "UPLOAD_BATCH_ID_PATTERN",
    }
    path = repo_root / APPLICATION_CONTRACT_RELATIVE
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise McpArtifactError("Frozen OpenAPI constants are unreadable.") from error
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in names:
            continue
        try:
            values[target.id] = _openapi_constant(node.value)
        except ValueError as error:
            raise McpArtifactError(
                f"Frozen OpenAPI constant {target.id} is not a safe literal."
            ) from error
    if set(values) != names:
        raise McpArtifactError("Frozen OpenAPI constants are missing.")
    return values


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_compatibility_hashes_canonical_frozen_openapi_document
# @matrix mcp-package agent-api : frozen-openapi canonical-compatibility
def _frozen_openapi_document(repo_root: Path) -> dict:
    """Build the origin-neutral OpenAPI contract through a closed AST subset."""
    path = repo_root / OPENAPI_SOURCE_RELATIVE
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise McpArtifactError("Frozen OpenAPI source is unreadable.") from error
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "openapi_document"
    ]
    if len(functions) != 1:
        raise McpArtifactError("Frozen OpenAPI source must define one document.")
    function = functions[0]
    function.decorator_list = []
    allowed_nodes = {
        ast.Assign,
        ast.Attribute,
        ast.Call,
        ast.Constant,
        ast.Dict,
        ast.Expr,
        ast.FormattedValue,
        ast.FunctionDef,
        ast.JoinedStr,
        ast.List,
        ast.Load,
        ast.Name,
        ast.Return,
        ast.Store,
        ast.arg,
        ast.arguments,
    }
    if any(type(node) not in allowed_nodes for node in ast.walk(function)):
        raise McpArtifactError("Frozen OpenAPI source uses an unsafe construct.")
    if not function.body or any(
        type(node) not in {ast.Assign, ast.Expr, ast.FunctionDef, ast.Return}
        for node in function.body
    ):
        raise McpArtifactError("Frozen OpenAPI source has an unsafe statement.")
    assigned_names = {
        target.id
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    argument_names = {
        argument.arg
        for node in ast.walk(function)
        if isinstance(node, ast.FunctionDef)
        for argument in node.args.args
    }
    loaded_names = {
        node.id
        for node in ast.walk(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    if not loaded_names <= (
        assigned_names
        | argument_names
        | {"CONFIG", "_api_absolute_url", "external_api", "json_content", "list"}
    ):
        raise McpArtifactError("Frozen OpenAPI source uses an unsafe name.")
    constants = _openapi_contract_constants(repo_root)
    allowed_external = set(constants)
    for node in ast.walk(function):
        if not isinstance(node, ast.Attribute):
            continue
        allowed = (
            isinstance(node.value, ast.Name)
            and (
                (node.value.id == "CONFIG" and node.attr == "APP_NAME")
                or (node.value.id == "external_api" and node.attr in allowed_external)
            )
        ) or (
            node.attr == "rstrip"
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_api_absolute_url"
        )
        if not allowed:
            raise McpArtifactError("Frozen OpenAPI source uses an unsafe attribute.")
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        allowed = (
            isinstance(node.func, ast.Name)
            and node.func.id in {"_api_absolute_url", "json_content", "list"}
        ) or (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "rstrip"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "_api_absolute_url"
        )
        if not allowed:
            raise McpArtifactError("Frozen OpenAPI source uses an unsafe call.")

    namespace = {
        "__builtins__": {},
        "CONFIG": SimpleNamespace(APP_NAME=FROZEN_OPENAPI_APP_NAME),
        "external_api": SimpleNamespace(**constants),
        "_api_absolute_url": lambda _path: FROZEN_OPENAPI_ORIGIN,
        "list": list,
    }
    try:
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        exec(compile(module, str(path), "exec"), namespace)
        document = namespace["openapi_document"]()
        canonical = _canonical_json(document)
        round_trip = json.loads(canonical)
    except (Exception, SystemExit) as error:
        raise McpArtifactError("Frozen OpenAPI document could not be built.") from error
    if (
        not isinstance(document, dict)
        or round_trip != document
        or document.get("openapi") != "3.1.0"
        or document.get("servers") != [{"url": FROZEN_OPENAPI_ORIGIN}]
        or not isinstance(document.get("paths"), dict)
        or not document["paths"]
    ):
        raise McpArtifactError("Frozen OpenAPI document is invalid.")
    return document


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_compatibility_hashes_canonical_frozen_openapi_document
# @matrix agent-api mcp-package : canonical-compatibility frozen-openapi
def _compatibility(repo_root: Path) -> dict:
    limits_path = repo_root / MCP_PROJECT_RELATIVE / "src/lagniappe_mcp/limits.py"
    values = _literal_assignments(
        limits_path,
        {"API_VERSION", "CONTRACT_VERSION_MIN", "CONTRACT_VERSION_MAX"},
    )
    app_contract_path = repo_root / APPLICATION_CONTRACT_RELATIVE
    app_contract = _literal_assignments(app_contract_path, {"CONTRACT_VERSION"})
    if values["API_VERSION"] != MCP_API_VERSION:
        raise McpArtifactError("MCP API compatibility version is invalid.")
    minimum = values["CONTRACT_VERSION_MIN"]
    maximum = values["CONTRACT_VERSION_MAX"]
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or minimum <= 0
        or minimum > maximum
        or app_contract["CONTRACT_VERSION"] not in range(minimum, maximum + 1)
    ):
        raise McpArtifactError("MCP and application contract versions disagree.")
    openapi_document = _frozen_openapi_document(repo_root)
    return {
        "api_min": values["API_VERSION"],
        "api_max": values["API_VERSION"],
        "contract_min": minimum,
        "contract_max": maximum,
        "openapi_sha256": _sha256_bytes(_canonical_json(openapi_document)),
        "contract_source_sha256": _sha256_file(app_contract_path),
    }


# @testable false
# @covered-by runner/mcp_artifact.py::_dependency_graph
# @reason platform wheel ranking is exercised through the validated resolved dependency graph
def _wheel_score(filename: str) -> int | None:
    if not filename.endswith(".whl"):
        return None
    try:
        _prefix, python_tag, abi_tag, platform_tag = filename[:-4].rsplit("-", 3)
    except ValueError:
        return None
    if platform_tag == "any" and abi_tag == "none":
        if "py3" in python_tag.split("."):
            return 300
        return None
    proven_platform_tags = {
        "manylinux2014_x86_64",
        "manylinux_2_17_x86_64",
    }
    platform_tags = set(platform_tag.split("."))
    if not platform_tags or not platform_tags <= proven_platform_tags:
        return None
    if python_tag == "cp314" and abi_tag == "cp314":
        return 550
    match = re.fullmatch(r"cp3(\d{2})", python_tag)
    if match and abi_tag == "abi3" and int(match.group(1)) <= 14:
        return 450 + int(match.group(1))
    return None


# @testable false
# @covered-by runner/mcp_artifact.py::_dependency_graph
# @reason the closed marker subset is exercised while resolving the runtime closure
def _locked_dependency_applies(dependency: dict) -> bool:
    marker = dependency.get("marker")
    if marker is None:
        return True
    if not isinstance(marker, str) or marker not in MCP_PLATFORM_MARKERS:
        raise McpArtifactError(
            f"MCP uv lock contains an unsupported platform marker: {marker!r}."
        )
    return MCP_PLATFORM_MARKERS[marker]


# @testable false
# @covered-by runner/mcp_artifact.py::_dependency_graph
# @reason transitive and extra dependency traversal is exercised by graph validation
def _locked_runtime_closure(root_package: dict, packages: dict[str, dict]) -> set[str]:
    pending = list(root_package.get("dependencies", []))
    closure = set()
    requested_extras: dict[str, set[str]] = {}
    while pending:
        dependency = pending.pop()
        if not isinstance(dependency, dict) or not isinstance(
            dependency.get("name"), str
        ):
            raise McpArtifactError("MCP uv lock contains invalid dependency metadata.")
        if not _locked_dependency_applies(dependency):
            continue
        name = _canonical_name(dependency["name"])
        package = packages.get(name)
        if package is None:
            raise McpArtifactError(
                f"MCP uv lock runtime dependency {name!r} is unresolved."
            )
        extras = dependency.get("extra", [])
        if not isinstance(extras, list) or any(
            not isinstance(extra, str) or not extra for extra in extras
        ):
            raise McpArtifactError("MCP uv lock contains invalid dependency extras.")
        new_extras = set(extras) - requested_extras.setdefault(name, set())
        requested_extras[name].update(new_extras)
        if name not in closure:
            closure.add(name)
            dependencies = package.get("dependencies", [])
            if not isinstance(dependencies, list):
                raise McpArtifactError(
                    f"MCP uv lock dependency {name!r} has invalid dependencies."
                )
            pending.extend(dependencies)
        if new_extras:
            optional = package.get("optional-dependencies", {})
            if not isinstance(optional, dict):
                raise McpArtifactError(
                    f"MCP uv lock dependency {name!r} has invalid optional dependencies."
                )
            for extra in new_extras:
                extra_dependencies = optional.get(extra)
                if not isinstance(extra_dependencies, list):
                    raise McpArtifactError(
                        f"MCP uv lock dependency {name!r} does not resolve extra {extra!r}."
                    )
                pending.extend(extra_dependencies)
    return closure


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_rejects_rebinding_and_corruption
# @matrix mcp-package : dependency-graph fail-closed locked-dependencies release-validation
def _dependency_graph(
    repo_root: Path, project: ProjectMetadata
) -> tuple[list[dict], str]:
    try:
        lock = tomllib.loads(
            _read_bytes(repo_root / LOCK_RELATIVE, label="MCP uv lock").decode()
        )
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise McpArtifactError("MCP uv lock is invalid.") from error
    if lock.get("requires-python") != "==3.14.*":
        raise McpArtifactError("MCP uv lock Python range disagrees with pyproject.")
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise McpArtifactError("MCP uv lock package list is invalid.")
    by_name = {}
    root_package = None
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            raise McpArtifactError("MCP uv lock contains an invalid package.")
        name = _canonical_name(package["name"])
        if name in by_name:
            raise McpArtifactError(f"MCP uv lock duplicates package {name!r}.")
        by_name[name] = package
        if name == MCP_PACKAGE_NAME:
            root_package = package
    if not root_package or root_package.get("version") != project.version:
        raise McpArtifactError("MCP uv lock project version is stale.")
    locked_requirements = root_package.get("metadata", {}).get("requires-dist")
    if not isinstance(locked_requirements, list):
        raise McpArtifactError("MCP uv lock lacks resolved project requirements.")
    locked_pins = {}
    for requirement in locked_requirements:
        if not isinstance(requirement, dict):
            raise McpArtifactError("MCP uv lock contains invalid requirement metadata.")
        name = _canonical_name(requirement.get("name", ""))
        specifier = requirement.get("specifier")
        if not isinstance(specifier, str) or not specifier.startswith("=="):
            raise McpArtifactError("MCP uv lock contains a non-exact runtime pin.")
        locked_pins[name] = specifier[2:]
    project_pins = dict(_parse_exact_requirement(item) for item in project.dependencies)
    if locked_pins != project_pins:
        raise McpArtifactError("MCP uv lock runtime pins disagree with pyproject.")
    expected_test_pins = dict(
        _parse_exact_requirement(requirement) for requirement in MCP_TEST_REQUIREMENTS
    )
    locked_test_dependencies = root_package.get("dev-dependencies", {}).get("test")
    locked_test_metadata = (
        root_package.get("metadata", {}).get("requires-dev", {}).get("test")
    )
    if not isinstance(locked_test_dependencies, list) or not isinstance(
        locked_test_metadata, list
    ):
        raise McpArtifactError("MCP uv lock lacks the locked test/build group.")
    dependency_names = {
        _canonical_name(item.get("name", ""))
        for item in locked_test_dependencies
        if isinstance(item, dict)
    }
    metadata_pins = {
        _canonical_name(item.get("name", "")): str(item.get("specifier", ""))[2:]
        for item in locked_test_metadata
        if isinstance(item, dict) and str(item.get("specifier", "")).startswith("==")
    }
    if (
        dependency_names != set(expected_test_pins)
        or metadata_pins != expected_test_pins
    ):
        raise McpArtifactError("MCP uv lock test/build pins disagree with pyproject.")
    for name, version in expected_test_pins.items():
        package = by_name.get(name)
        if (
            not package
            or package.get("version") != version
            or package.get("source") != {"registry": "https://pypi.org/simple"}
            or not isinstance(package.get("wheels"), list)
            or not package["wheels"]
        ):
            raise McpArtifactError(
                f"MCP uv lock does not securely resolve test/build pin {name}=={version}."
            )
    runtime_closure = _locked_runtime_closure(root_package, by_name)
    if runtime_closure != set(project_pins):
        missing = sorted(runtime_closure - set(project_pins))
        extra = sorted(set(project_pins) - runtime_closure)
        detail = []
        if missing:
            detail.append("unpinned " + ", ".join(missing))
        if extra:
            detail.append("non-runtime " + ", ".join(extra))
        raise McpArtifactError(
            "MCP exact pins do not match the complete runtime dependency closure"
            f" ({'; '.join(detail)})."
        )

    graph = []
    for name, version in sorted(project_pins.items()):
        package = by_name.get(name)
        if not package or package.get("version") != version:
            raise McpArtifactError(f"MCP uv lock does not resolve {name}=={version}.")
        source = package.get("source")
        if source != {"registry": "https://pypi.org/simple"}:
            raise McpArtifactError(f"MCP dependency {name!r} has an unapproved source.")
        wheels = package.get("wheels")
        if not isinstance(wheels, list) or not wheels:
            raise McpArtifactError(f"MCP dependency {name!r} has no locked wheels.")
        candidates = []
        for wheel in wheels:
            if not isinstance(wheel, dict):
                continue
            url = wheel.get("url")
            digest = wheel.get("hash")
            size = wheel.get("size")
            if not isinstance(url, str) or not isinstance(digest, str):
                continue
            filename = unquote(PurePosixPath(urlparse(url).path).name)
            score = _wheel_score(filename)
            if (
                score is None
                or urlparse(url).scheme != "https"
                or urlparse(url).hostname != "files.pythonhosted.org"
                or not digest.startswith("sha256:")
                or not DIGEST_RE.fullmatch(digest.removeprefix("sha256:"))
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size <= 0
            ):
                continue
            candidates.append((score, filename, wheel))
        if not candidates:
            raise McpArtifactError(
                f"MCP dependency {name!r} has no Linux x86_64/Python 3.14 wheel."
            )
        _score, filename, selected = max(
            candidates, key=lambda item: (item[0], item[1])
        )
        graph.append(
            {
                "name": name,
                "version": version,
                "filename": filename,
                "sha256": selected["hash"].removeprefix("sha256:"),
                "size": selected["size"],
                "source_url": selected["url"],
            }
        )
    digest = _sha256_bytes(_canonical_json(graph))
    return graph, digest


# @testable false
# @covered-by runner/mcp_artifact.py::build_and_promote_release
# @reason release entry composition is exercised through immutable promotion
def _release_entry(
    repo_root: Path,
    project: ProjectMetadata,
    wheel: WheelMetadata,
) -> dict:
    graph, graph_digest = _dependency_graph(repo_root, project)
    platform = {
        **MCP_PLATFORM,
        "dependency_graph_sha256": graph_digest,
        "dependencies": graph,
    }
    return {
        "version": wheel.version,
        "sha256": wheel.sha256,
        "size": wheel.size,
        "filename": wheel.filename,
        "artifact_path": _public_artifact_path(wheel.version, wheel.sha256),
        "source_sha256": _source_digest(repo_root),
        "supported": True,
        "python_requirement": wheel.requires_python,
        "runtime_requirements": list(wheel.dependencies),
        "platforms": [platform],
        "compatibility": _compatibility(repo_root),
    }


# @testable false
# @covered-by runner/mcp_artifact.py::build_and_promote_release
# @reason first-release ledger composition is exercised through release promotion
def _new_ledger(project: ProjectMetadata, entry: dict) -> dict:
    return {
        "schema": MCP_LEDGER_SCHEMA,
        "package": MCP_PACKAGE_NAME,
        "entry_point": MCP_ENTRY_POINT,
        "current": entry["version"],
        "source_url": project.source_url,
        "license": {
            "expression": project.license_expression,
            "url": project.license_url,
        },
        "releases": [entry],
    }


# @testable false
# @covered-by runner/mcp_artifact.py::load_release_ledger
# @reason closed platform/dependency metadata is exercised by strict ledger loading
def _validate_dependency_graph(platform: dict, *, label: str) -> None:
    _require_exact_keys(
        platform,
        {
            "id",
            "system",
            "architecture",
            "libc",
            "python",
            "dependency_graph_sha256",
            "dependencies",
        },
        label=label,
    )
    for key, expected in MCP_PLATFORM.items():
        if platform.get(key) != expected:
            raise McpArtifactError(f"{label} advertises an unsupported {key}.")
    dependencies = platform.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise McpArtifactError(f"{label} dependency graph must be nonempty.")
    seen = set()
    for index, dependency in enumerate(dependencies):
        dependency_label = f"{label} dependency {index}"
        _require_exact_keys(
            dependency,
            {"name", "version", "filename", "sha256", "size", "source_url"},
            label=dependency_label,
        )
        name = dependency.get("name")
        if not isinstance(name, str) or _canonical_name(name) != name or name in seen:
            raise McpArtifactError(
                f"{dependency_label} has an invalid or duplicate name."
            )
        seen.add(name)
        if not isinstance(dependency.get("version"), str):
            raise McpArtifactError(f"{dependency_label} version is invalid.")
        if not DIGEST_RE.fullmatch(str(dependency.get("sha256", ""))):
            raise McpArtifactError(f"{dependency_label} digest is invalid.")
        if (
            isinstance(dependency.get("size"), bool)
            or not isinstance(dependency.get("size"), int)
            or dependency["size"] <= 0
        ):
            raise McpArtifactError(f"{dependency_label} size is invalid.")
        source_url = _require_https_url(
            dependency.get("source_url"), label=f"{dependency_label} URL"
        )
        filename = dependency.get("filename")
        if (
            not isinstance(filename, str)
            or PurePosixPath(filename).name != filename
            or _wheel_score(filename) is None
            or urlparse(source_url).hostname != "files.pythonhosted.org"
            or unquote(PurePosixPath(urlparse(source_url).path).name) != filename
        ):
            raise McpArtifactError(f"{dependency_label} wheel filename is unsupported.")
    expected = _sha256_bytes(_canonical_json(dependencies))
    if platform.get("dependency_graph_sha256") != expected:
        raise McpArtifactError(f"{label} dependency graph digest is stale.")


# @testable false
# @covered-by runner/mcp_artifact.py::load_release_ledger
# @reason release field and compatibility checks are exercised by strict ledger loading
def _validate_release_entry(entry: dict, *, label: str) -> None:
    _require_exact_keys(
        entry,
        {
            "version",
            "sha256",
            "size",
            "filename",
            "artifact_path",
            "source_sha256",
            "supported",
            "python_requirement",
            "runtime_requirements",
            "platforms",
            "compatibility",
        },
        label=label,
    )
    version = entry.get("version")
    digest = entry.get("sha256")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise McpArtifactError(f"{label} version is invalid.")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise McpArtifactError(f"{label} digest is invalid.")
    if entry.get("filename") != _wheel_filename(version):
        raise McpArtifactError(f"{label} filename is invalid.")
    if entry.get("artifact_path") != _public_artifact_path(version, digest):
        raise McpArtifactError(f"{label} content-addressed path is invalid.")
    if not DIGEST_RE.fullmatch(str(entry.get("source_sha256", ""))):
        raise McpArtifactError(f"{label} source digest is invalid.")
    size = entry.get("size")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 0 < size <= MAX_ARTIFACT_BYTES
    ):
        raise McpArtifactError(f"{label} size is invalid.")
    if not isinstance(entry.get("supported"), bool):
        raise McpArtifactError(f"{label} support flag is invalid.")
    if entry.get("python_requirement") != ">=3.14,<3.15":
        raise McpArtifactError(f"{label} Python requirement is invalid.")
    requirements = entry.get("runtime_requirements")
    if not isinstance(requirements, list) or not requirements:
        raise McpArtifactError(f"{label} runtime requirements are invalid.")
    requirement_names = set()
    for requirement in requirements:
        if not isinstance(requirement, str):
            raise McpArtifactError(f"{label} runtime requirements are invalid.")
        name, _version = _parse_exact_requirement(requirement)
        if name in requirement_names:
            raise McpArtifactError(f"{label} runtime requirements are duplicated.")
        requirement_names.add(name)
    platforms = entry.get("platforms")
    if not isinstance(platforms, list) or len(platforms) != 1:
        raise McpArtifactError(f"{label} must advertise exactly one proven platform.")
    _validate_dependency_graph(platforms[0], label=f"{label} platform")
    graph_versions = {
        dependency["name"]: dependency["version"]
        for dependency in platforms[0]["dependencies"]
    }
    requirement_versions = dict(
        _parse_exact_requirement(requirement) for requirement in requirements
    )
    if graph_versions != requirement_versions:
        raise McpArtifactError(f"{label} requirements and dependency graph disagree.")
    compatibility = entry.get("compatibility")
    _require_exact_keys(
        compatibility,
        {
            "api_min",
            "api_max",
            "contract_min",
            "contract_max",
            "openapi_sha256",
            "contract_source_sha256",
        },
        label=f"{label} compatibility",
    )
    if not (compatibility["api_min"] == compatibility["api_max"] == MCP_API_VERSION):
        raise McpArtifactError(f"{label} API compatibility is invalid.")
    for digest_key in ("openapi_sha256", "contract_source_sha256"):
        if not DIGEST_RE.fullmatch(str(compatibility.get(digest_key, ""))):
            raise McpArtifactError(f"{label} {digest_key} is invalid.")
    minimum = compatibility.get("contract_min")
    maximum = compatibility.get("contract_max")
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or minimum <= 0
        or minimum > maximum
    ):
        raise McpArtifactError(f"{label} contract compatibility is invalid.")


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_rejects_rebinding_and_corruption
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_copies_only_supported_content_addressed_wheels
# @matrix mcp-package release : fail-closed immutable-ledger platform-pin python-floor release-validation
def load_release_ledger(repo_root=REPOSITORY_ROOT) -> dict:
    """Load and strictly validate the durable adapter release ledger."""
    repo_root = Path(repo_root).resolve()
    ledger_path = repo_root / MCP_LEDGER_RELATIVE
    if ledger_path.is_symlink():
        raise McpArtifactError("MCP release ledger may not be a symlink.")
    ledger_bytes = _read_bytes(ledger_path, label="MCP release ledger")
    try:
        ledger = json.loads(ledger_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise McpArtifactError("MCP release ledger is not valid UTF-8 JSON.") from error
    _require_exact_keys(
        ledger,
        {
            "schema",
            "package",
            "entry_point",
            "current",
            "source_url",
            "license",
            "releases",
        },
        label="MCP release ledger",
    )
    if ledger.get("schema") != MCP_LEDGER_SCHEMA:
        raise McpArtifactError("MCP release ledger schema is unsupported.")
    if (
        ledger.get("package") != MCP_PACKAGE_NAME
        or ledger.get("entry_point") != MCP_ENTRY_POINT
    ):
        raise McpArtifactError("MCP release ledger package metadata is invalid.")
    _require_https_url(ledger.get("source_url"), label="MCP ledger source URL")
    license_value = ledger.get("license")
    _require_exact_keys(
        license_value, {"expression", "url"}, label="MCP ledger license"
    )
    if license_value.get("expression") != "GPL-3.0-or-later":
        raise McpArtifactError("MCP release ledger license is invalid.")
    _require_https_url(license_value.get("url"), label="MCP ledger license URL")
    releases = ledger.get("releases")
    if not isinstance(releases, list) or not releases:
        raise McpArtifactError("MCP release ledger must contain a release.")
    versions = set()
    digests = set()
    for index, entry in enumerate(releases):
        _validate_release_entry(entry, label=f"MCP release {index}")
        if entry["version"] in versions or entry["sha256"] in digests:
            raise McpArtifactError(
                "MCP release ledger contains a duplicate version or artifact."
            )
        versions.add(entry["version"])
        digests.add(entry["sha256"])
    current = ledger.get("current")
    current_entries = [entry for entry in releases if entry["version"] == current]
    if len(current_entries) != 1 or current_entries[0]["supported"] is not True:
        raise McpArtifactError(
            "MCP current release must be one supported ledger entry."
        )
    if ledger_bytes != _canonical_json(ledger):
        raise McpArtifactError("MCP release ledger is not canonically serialized.")
    _audit_public_content(
        [("MCP release ledger", ledger_bytes)],
        repo_root=repo_root,
        allowed_urls=(
            ledger["source_url"],
            ledger["license"]["url"],
            *(
                dependency["source_url"]
                for entry in ledger["releases"]
                for platform in entry["platforms"]
                for dependency in platform["dependencies"]
            ),
        ),
    )
    return ledger


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_historical_wheel_remains_valid_after_current_source_changes
# @matrix mcp-package release : historical-wheel immutable-ledger source-versioning
def _validate_durable_artifacts(repo_root: Path, ledger: dict) -> None:
    expected = {"releases.json"}
    for entry in ledger["releases"]:
        relative = _artifact_relative_path(entry["version"], entry["sha256"])
        expected.add(relative.as_posix())
        path = repo_root / MCP_RELEASES_RELATIVE / relative
        if path.is_symlink():
            raise McpArtifactError("MCP durable release wheel may not be a symlink.")
        raw = _read_bytes(path, label=f"MCP durable wheel {entry['version']}")
        if _sha256_bytes(raw) != entry["sha256"] or len(raw) != entry["size"]:
            raise McpArtifactError(f"MCP durable wheel {entry['version']} is corrupt.")
        wheel_project = ProjectMetadata(
            version=entry["version"],
            requires_python=entry["python_requirement"],
            dependencies=tuple(entry["runtime_requirements"]),
            source_url=ledger["source_url"],
            license_expression=ledger["license"]["expression"],
            license_url=ledger["license"]["url"],
        )
        _inspect_wheel(
            path,
            wheel_project,
            repo_root,
            match_current_source=entry["version"] == ledger["current"],
        )
    releases_root = repo_root / MCP_RELEASES_RELATIVE
    entries = list(releases_root.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise McpArtifactError("MCP durable release tree may not contain symlinks.")
    actual = {
        path.relative_to(releases_root).as_posix() for path in entries if path.is_file()
    }
    if actual != expected:
        raise McpArtifactError(
            "MCP durable release tree contains missing or unlisted wheels."
        )


# @testable false
# @covered-by runner/mcp_artifact.py::validate_release_inputs
# @reason current source, graph, and compatibility coherence are exercised by release preflight
def _validate_current_inputs(repo_root: Path, ledger: dict) -> None:
    project = _load_project(repo_root)
    current = next(
        entry for entry in ledger["releases"] if entry["version"] == ledger["current"]
    )
    if current["version"] != project.version:
        raise McpArtifactError(
            "MCP project version is not the ledger's current release."
        )
    if current["source_sha256"] != _source_digest(repo_root):
        raise McpArtifactError(
            "MCP current release source digest is stale; bump its version."
        )
    if set(current["runtime_requirements"]) != set(project.dependencies):
        raise McpArtifactError("MCP current release requirement pins are stale.")
    graph, graph_digest = _dependency_graph(repo_root, project)
    platform = current["platforms"][0]
    if (
        platform["dependencies"] != graph
        or platform["dependency_graph_sha256"] != graph_digest
    ):
        raise McpArtifactError("MCP current release dependency graph is stale.")
    if current["compatibility"] != _compatibility(repo_root):
        raise McpArtifactError(
            "MCP current release application compatibility is stale."
        )
    if ledger["source_url"] != project.source_url or ledger["license"] != {
        "expression": project.license_expression,
        "url": project.license_url,
    }:
        raise McpArtifactError("MCP current project source/license metadata is stale.")


# @testable false
# @covered-by runner/mcp_artifact.py::_manifest
# @reason production frontend and application build coupling is exercised in the manifest
def _application_metadata(repo_root: Path) -> dict:
    package = _read_json(
        repo_root / "package.json", label="application package metadata"
    )
    version = package.get("version") if isinstance(package, dict) else None
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise McpArtifactError("Application version must use stable X.Y.Z form.")
    constants_path = repo_root / "config/constants.py"
    build_id = _literal_assignments(constants_path, {"BUILD_ID"})["BUILD_ID"]
    if not isinstance(build_id, str) or not re.fullmatch(r"b[0-9a-f]{7}", build_id):
        raise McpArtifactError("Application build ID is invalid.")
    frontend_build = _read_bytes(
        repo_root / FRONTEND_BUILD_RELATIVE,
        label="frontend production build metadata",
    )
    try:
        frontend_metadata = json.loads(frontend_build)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise McpArtifactError(
            "Frontend production build metadata is invalid."
        ) from error
    if (
        not isinstance(frontend_metadata, dict)
        or frontend_metadata.get("mode") != "production"
        or frontend_metadata.get("version") != version
        or frontend_metadata.get("build_id") != build_id
    ):
        raise McpArtifactError("Frontend production build metadata is stale.")
    return {
        "version": version,
        "build_id": build_id,
        "frontend_build_sha256": _sha256_bytes(frontend_build),
    }


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_copies_only_supported_content_addressed_wheels
# @tests tests_tooling/test_012b_mcp_artifact.py::test_historical_wheel_remains_valid_after_current_source_changes
# @matrix mcp-package : deploy-surface source-versioning
def _manifest(repo_root: Path, ledger: dict) -> dict:
    supported = [entry for entry in ledger["releases"] if entry["supported"]]
    if not supported:
        raise McpArtifactError("MCP deployment has no supported releases.")
    by_version = {entry["version"]: entry for entry in supported}
    if ledger["current"] not in by_version:
        raise McpArtifactError("MCP current release is not deployable.")
    app_contract_path = repo_root / "lagniappe/core/tools/ai/external_api.py"
    app_contract = _literal_assignments(app_contract_path, {"CONTRACT_VERSION"})[
        "CONTRACT_VERSION"
    ]
    if any(
        not entry["compatibility"]["contract_min"]
        <= app_contract
        <= entry["compatibility"]["contract_max"]
        for entry in supported
    ):
        raise McpArtifactError(
            "MCP supported release set is incompatible with the application contract."
        )
    manifest = {
        "schema": MCP_MANIFEST_SCHEMA,
        "package": {
            "name": ledger["package"],
            "entry_point": ledger["entry_point"],
            "source_url": ledger["source_url"],
            "license": ledger["license"],
        },
        "application": _application_metadata(repo_root),
        "current": by_version[ledger["current"]],
        "releases": supported,
        "release_ledger_sha256": _sha256_file(repo_root / MCP_LEDGER_RELATIVE),
    }
    _audit_public_content(
        [("MCP deployment manifest", _canonical_json(manifest))],
        repo_root=repo_root,
        allowed_urls=(
            ledger["source_url"],
            ledger["license"]["url"],
            *(
                dependency["source_url"]
                for entry in supported
                for platform in entry["platforms"]
                for dependency in platform["dependencies"]
            ),
        ),
    )
    return manifest


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_release_check_validates_indexed_mcp_inputs_not_worktree
# @matrix mcp-package release : prospective-index release-validation
def validate_release_inputs(repo_root=REPOSITORY_ROOT) -> dict:
    """Validate durable releases and return their candidate deploy manifest."""
    repo_root = Path(repo_root).resolve()
    ledger = load_release_ledger(repo_root)
    _validate_durable_artifacts(repo_root, ledger)
    _validate_current_inputs(repo_root, ledger)
    return _manifest(repo_root, ledger)


# @testable false
# @covered-by runner/mcp_artifact.py::assemble_deployment_artifacts
# @reason atomic generated-tree publication is exercised by artifact assembly
def _replace_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise McpArtifactError("MCP generated output may not be a symlink.")
    if destination.exists():
        if not destination.is_dir():
            raise McpArtifactError("MCP generated output is not a directory.")
        shutil.rmtree(destination)
    os.replace(source, destination)


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_copies_only_supported_content_addressed_wheels
# @tests tests_e2e/013_agent_api/test_013b_agent_api_mcp.py::test_public_mcp_release_manifest_and_wheel_are_exact
# @matrix frontend-build mcp-package web-headers : artifact-order build-marker content-addressing deploy-surface immutable-cache public-artifact
def assemble_deployment_artifacts(repo_root=REPOSITORY_ROOT) -> dict:
    """Copy supported durable releases into one deterministic deploy tree."""
    repo_root = Path(repo_root).resolve()
    manifest = validate_release_inputs(repo_root)
    deploy_root = repo_root / MCP_DEPLOY_RELATIVE
    deploy_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".mcp-build-", dir=deploy_root.parent
    ) as temp:
        output = Path(temp) / "mcp"
        output.mkdir()
        (output / "manifest.json").write_bytes(_canonical_json(manifest))
        for entry in manifest["releases"]:
            relative = _artifact_relative_path(entry["version"], entry["sha256"])
            source = repo_root / MCP_RELEASES_RELATIVE / relative
            target = output / "releases" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        _replace_tree(output, deploy_root)
    check_deployment_artifacts(repo_root, require_git=False)
    return manifest


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_git_boundary_rejects_staged_uncommitted_inputs
# @matrix mcp-package release : deploy-preflight git-boundary
def _git_release_input_issues(
    repo_root: Path,
    ledger: dict,
    *,
    git_cli: str | os.PathLike[str] | None,
) -> list[str]:
    paths = [
        *(_source_inputs(repo_root)),
        repo_root / OPENAPI_SOURCE_RELATIVE,
        repo_root / APPLICATION_CONTRACT_RELATIVE,
        repo_root / "package.json",
        repo_root / "config/constants.py",
        repo_root / FRONTEND_BUILD_RELATIVE,
        repo_root / MCP_LEDGER_RELATIVE,
        *(
            repo_root
            / MCP_RELEASES_RELATIVE
            / _artifact_relative_path(entry["version"], entry["sha256"])
            for entry in ledger["releases"]
        ),
    ]
    relative = [path.relative_to(repo_root).as_posix() for path in paths]
    if git_cli is None or not Path(git_cli).is_absolute():
        return ["Git is unavailable for MCP release-input validation."]
    git = str(git_cli)
    try:
        tracked = subprocess.run(
            [git, "-C", str(repo_root), "ls-files", "--error-unmatch", "--", *relative],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        dirty = subprocess.run(
            [git, "-C", str(repo_root), "diff", "--quiet", "--", *relative],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        staged = subprocess.run(
            [
                git,
                "-C",
                str(repo_root),
                "diff",
                "--cached",
                "--quiet",
                "--",
                *relative,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return ["Git is unavailable for MCP release-input validation."]
    issues = []
    if tracked.returncode != 0:
        issues.append("MCP release inputs are not all tracked in ordinary Git.")
    if dirty.returncode != 0:
        issues.append("MCP release inputs contain unstaged changes.")
    if staged.returncode != 0:
        issues.append("MCP release inputs contain staged but uncommitted changes.")
    return issues


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_rejects_stale_frontend_or_uncommitted_release_input
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_copies_only_supported_content_addressed_wheels
# @matrix frontend-build mcp-package release : artifact-freshness deploy-preflight deploy-surface git-boundary retirement supported-wheel
def check_deployment_artifacts(
    repo_root=REPOSITORY_ROOT,
    *,
    require_git=True,
    git_cli: str | os.PathLike[str] | None = None,
) -> dict:
    """Validate ledger, wheels, manifest, frontend coupling, and Git boundary."""
    repo_root = Path(repo_root).resolve()
    ledger = load_release_ledger(repo_root)
    expected_manifest = validate_release_inputs(repo_root)
    deploy_root = repo_root / MCP_DEPLOY_RELATIVE
    actual_manifest = _read_json(
        deploy_root / "manifest.json", label="MCP deploy manifest"
    )
    if actual_manifest != expected_manifest:
        raise McpArtifactError("MCP deploy manifest is missing, corrupt, or stale.")
    expected_files = {"manifest.json"}
    total_size = (deploy_root / "manifest.json").stat().st_size
    for entry in expected_manifest["releases"]:
        relative = Path("releases") / _artifact_relative_path(
            entry["version"], entry["sha256"]
        )
        expected_files.add(relative.as_posix())
        path = deploy_root / relative
        raw = _read_bytes(path, label=f"MCP deploy wheel {entry['version']}")
        if (
            path.is_symlink()
            or _sha256_bytes(raw) != entry["sha256"]
            or len(raw) != entry["size"]
        ):
            raise McpArtifactError(f"MCP deploy wheel {entry['version']} is corrupt.")
        total_size += path.stat().st_size
    entries = list(deploy_root.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise McpArtifactError("MCP deploy tree may not contain symlinks.")
    actual_files = {
        path.relative_to(deploy_root).as_posix() for path in entries if path.is_file()
    }
    if actual_files != expected_files:
        raise McpArtifactError(
            "MCP deploy tree contains a missing or unauthorized file."
        )
    if len(actual_files) > MAX_DEPLOYMENT_FILES or total_size > MAX_DEPLOYMENT_BYTES:
        raise McpArtifactError(
            "MCP deploy tree exceeds its file-count or byte ceiling."
        )
    if require_git:
        issues = _git_release_input_issues(repo_root, ledger, git_cli=git_cli)
        if issues:
            raise McpArtifactError(" ".join(issues))
    return expected_manifest


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_artifact_builder_requires_exact_managed_uv_bytes
# @matrix mcp-package release : bootstrap command-bridge executable-digest fail-closed interpreter-isolation managed-path reproducible-build
def _managed_uv(repo_root: Path) -> Path:
    from runner.uv_bootstrap import UvBootstrapError, check_uv

    try:
        return check_uv(
            manifest_path=repo_root / BOOTSTRAP_RELATIVE,
            virtualenv=repo_root / "venv",
        )
    except UvBootstrapError as error:
        raise McpArtifactError(
            "Managed uv failed exact-byte verification. "
            "Run ./setup.sh development to repair it."
        ) from error


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_artifact_builder_uses_locked_build_backend
# @matrix mcp-package release : locked-dependencies build-isolation reproducible-build
def _run_wheel_build(repo_root: Path, output: Path, *, run=subprocess.run) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("UV_") or name in {
            "PYTHONHOME",
            "PYTHONPATH",
            "VIRTUAL_ENV",
        }:
            environment.pop(name, None)
    environment["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    environment["PYTHONNOUSERSITE"] = "1"
    project_root = repo_root / MCP_PROJECT_RELATIVE
    project_environment = project_root / ".venv"
    environment["UV_CACHE_DIR"] = str(project_root / ".uv-cache")
    environment["UV_PROJECT_ENVIRONMENT"] = str(project_environment)
    managed_uv = str(_managed_uv(repo_root))
    sync_command = [
        managed_uv,
        "sync",
        "--project",
        str(project_root),
        "--locked",
        "--group",
        "test",
        "--no-install-project",
        "--no-build",
        "--no-managed-python",
        "--python",
        str(repo_root / "venv/bin/python"),
    ]
    sync_result = run(
        sync_command,
        cwd=repo_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if sync_result.returncode != 0:
        raise McpArtifactError("Locked MCP build environment synchronization failed.")
    build_command = [
        managed_uv,
        "build",
        "--project",
        str(project_root),
        "--wheel",
        "--out-dir",
        str(output),
        "--python",
        str(
            project_environment
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        ),
        "--no-build-isolation",
        "--offline",
        "--no-python-downloads",
    ]
    result = run(
        build_command,
        cwd=repo_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise McpArtifactError("Reproducible MCP wheel build failed.")
    wheels = list(output.glob("*.whl"))
    if len(wheels) != 1:
        raise McpArtifactError("MCP wheel build did not produce exactly one wheel.")
    return wheels[0]


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_artifact_builder_rejects_rebinding_and_corruption
# @tests tests_e2e/013_agent_api/test_013c_mcp_package_install.py::test_public_mcp_wheel_clean_home_installation_contract
# @matrix hosted-e2e mcp-package release : clean-home client-registration dependency-graph downgrade immutable-release installer-pin platform-pin public-artifact
# @matrix mcp-package : reproducible-build immutable-ledger promotion
def build_and_promote_release(repo_root=REPOSITORY_ROOT) -> dict:
    """Build twice, require identical bytes, and immutably promote the version."""
    repo_root = Path(repo_root).resolve()
    project = _load_project(repo_root)
    with tempfile.TemporaryDirectory(prefix="lagniappe-mcp-wheel-") as temp:
        temp_root = Path(temp)
        first = _run_wheel_build(repo_root, temp_root / "first")
        second = _run_wheel_build(repo_root, temp_root / "second")
        first_bytes = _read_bytes(first, label="first MCP wheel build")
        second_bytes = _read_bytes(second, label="second MCP wheel build")
        if first_bytes != second_bytes:
            raise McpArtifactError("MCP wheel build is not reproducible byte-for-byte.")
        wheel = _inspect_wheel(first, project, repo_root)
        entry = _release_entry(repo_root, project, wheel)

        ledger_path = repo_root / MCP_LEDGER_RELATIVE
        if ledger_path.exists():
            ledger = load_release_ledger(repo_root)
            _validate_durable_artifacts(repo_root, ledger)
            if ledger["source_url"] != project.source_url or ledger["license"] != {
                "expression": project.license_expression,
                "url": project.license_url,
            }:
                raise McpArtifactError(
                    "MCP project source/license metadata disagrees with the release ledger."
                )
            existing = [
                item
                for item in ledger["releases"]
                if item["version"] == project.version
            ]
            if existing:
                if existing[0] != entry:
                    raise McpArtifactError(
                        f"MCP version {project.version} is already bound to different release bytes."
                    )
            else:
                ledger["releases"].append(entry)
                ledger["releases"].sort(
                    key=lambda item: tuple(map(int, item["version"].split(".")))
                )
                ledger["current"] = project.version
        else:
            ledger = _new_ledger(project, entry)

        relative = _artifact_relative_path(project.version, wheel.sha256)
        destination = repo_root / MCP_RELEASES_RELATIVE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (
            destination.exists()
            and _read_bytes(destination, label="existing MCP release wheel")
            != first_bytes
        ):
            raise McpArtifactError(
                "MCP content-addressed destination contains different bytes."
            )
        if not destination.exists():
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                dir=destination.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(first_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_ledger = ledger_path.with_name(f".{ledger_path.name}.tmp")
        temporary_ledger.write_bytes(_canonical_json(ledger))
        os.replace(temporary_ledger, ledger_path)

    assemble_deployment_artifacts(repo_root)
    return ledger


# @testable true
# @tests tests_tooling/test_012b_mcp_artifact.py::test_mcp_artifact_cli_checks_without_gcloud
# @matrix mcp-package : cli-routing build check
def run_mcp_artifact_command(arguments: list[str], *, repo_root=REPOSITORY_ROOT) -> int:
    """Run the repository-only MCP artifact build/check interface."""
    parser = argparse.ArgumentParser(
        prog="run.py mcp-artifact",
        description="Build or verify the public MCP adapter release artifacts.",
    )
    parser.add_argument("action", choices=("build", "check"))
    args = parser.parse_args(arguments)
    try:
        if args.action == "build":
            ledger = build_and_promote_release(repo_root)
            print(f"Built MCP adapter {ledger['current']} and deployment artifacts.")
        else:
            manifest = check_deployment_artifacts(
                repo_root,
                git_cli=os.environ.get(RUNNER_GIT_ENV),
            )
            print(
                "MCP deployment artifacts verified for adapter "
                f"{manifest['current']['version']}."
            )
    except McpArtifactError as error:
        print(f"MCP artifact check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run_mcp_artifact_command(sys.argv[1:]))
