"""Provision the repository's pinned ``uv`` executable without third parties."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from tarfile import open as open_tar_archive
import tempfile
from types import MappingProxyType
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PROJECT_VIRTUALENV = REPOSITORY_ROOT / "venv"
BOOTSTRAP_MANIFEST = REPOSITORY_ROOT / "clients/lagniappe_mcp/uv-bootstrap.json"
UV_TOOLS_ROOT = PROJECT_VIRTUALENV / "tools" / "uv"
DOWNLOAD_TIMEOUT_SECONDS = 120
_DOWNLOAD_CHUNK_SIZE = 64 * 1024
_MAX_ARCHIVE_SIZE = 256 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 128
_MAX_MEMBER_NAME_LENGTH = 512
_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HOST_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


# @testable false
# @covered-by runner/uv_bootstrap.py::install_uv
# @reason typed bootstrap failures are exercised through the public install/check boundaries
class UvBootstrapError(RuntimeError):
    """Raised when managed uv cannot be selected, installed, or verified."""


# @testable false
# @covered-by runner/uv_bootstrap.py::load_manifest
# @reason immutable validated artifact data is exercised through manifest loading
@dataclass(frozen=True)
class UvArtifact:
    """One validated platform-specific uv release artifact."""

    platform_key: str
    system: str
    architecture: str
    libc: str
    url: str
    sha256: str
    archive_size: int
    member: str
    member_sha256: str


# @testable false
# @covered-by runner/uv_bootstrap.py::load_manifest
# @reason immutable validated manifest data is exercised through manifest loading
@dataclass(frozen=True)
class UvBootstrapManifest:
    """The validated bootstrap policy committed with the adapter project."""

    version: str
    allowed_redirect_hosts: frozenset[str]
    platforms: MappingProxyType


# @testable false
# @covered-by runner/uv_bootstrap.py::load_manifest
# @reason strict object-shape validation is covered through malformed manifest cases
def _require_keys(value, expected, *, label):
    if not isinstance(value, dict):
        raise UvBootstrapError(f"{label} must be a JSON object.")
    actual = set(value)
    expected = set(expected)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise UvBootstrapError(f"{label} has invalid fields ({'; '.join(details)}).")


# @testable false
# @covered-by runner/uv_bootstrap.py::load_manifest
# @reason URL policy is exercised through manifest and redirect rejection cases
def _validate_https_url(url, allowed_hosts, *, version=None):
    if not isinstance(url, str):
        raise UvBootstrapError("uv archive URL must be a string.")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as error:
        raise UvBootstrapError("uv archive URL is malformed.") from error
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise UvBootstrapError(
            "uv archive URL must use a declared HTTPS release host without "
            "credentials, a nonstandard port, or fragment."
        )
    if version is not None and (
        parsed.query
        or "latest" in parsed.path.casefold()
        or f"/{version}/" not in parsed.path
    ):
        raise UvBootstrapError("uv archive URL must bind the exact manifest version.")


# @testable false
# @covered-by runner/uv_bootstrap.py::load_manifest
# @reason member-path validation is exercised through unsafe archive cases
def _validate_member_name(name, *, directory=False):
    if (
        not isinstance(name, str)
        or not name
        or len(name) > _MAX_MEMBER_NAME_LENGTH
        or "\x00" in name
        or "\\" in name
    ):
        raise UvBootstrapError("uv archive contains an unsafe member name.")
    candidate = name[:-1] if directory and name.endswith("/") else name
    parts = candidate.split("/")
    if (
        not candidate
        or candidate.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or (parts and parts[0].endswith(":"))
        or PurePosixPath(candidate).is_absolute()
    ):
        raise UvBootstrapError("uv archive contains an unsafe member name.")


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_manifest_and_managed_context_path
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_rejects_malformed_manifest
# @matrix mcp-package setup : bootstrap manifest platform-pin url-policy validation
def load_manifest(path=BOOTSTRAP_MANIFEST):
    """Load and strictly validate the committed uv bootstrap manifest."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise UvBootstrapError(f"uv bootstrap manifest is missing: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UvBootstrapError(
            f"uv bootstrap manifest is unreadable: {path}"
        ) from error

    _require_keys(
        data,
        {"schema", "version", "allowed_redirect_hosts", "platforms"},
        label="uv bootstrap manifest",
    )
    if data["schema"] != 1:
        raise UvBootstrapError("uv bootstrap manifest schema must be 1.")
    version = data["version"]
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise UvBootstrapError("uv bootstrap manifest version is invalid.")

    hosts = data["allowed_redirect_hosts"]
    if (
        not isinstance(hosts, list)
        or not hosts
        or any(not isinstance(host, str) or not host for host in hosts)
    ):
        raise UvBootstrapError(
            "uv bootstrap manifest redirect hosts must be a nonempty string list."
        )
    normalized_hosts = [host.casefold() for host in hosts]
    if len(set(normalized_hosts)) != len(normalized_hosts) or any(
        not _HOST_PATTERN.fullmatch(host) for host in normalized_hosts
    ):
        raise UvBootstrapError("uv bootstrap manifest redirect hosts are invalid.")
    allowed_hosts = frozenset(normalized_hosts)

    platforms = data["platforms"]
    if not isinstance(platforms, dict) or not platforms:
        raise UvBootstrapError("uv bootstrap manifest platforms must be nonempty.")
    artifacts = {}
    artifact_fields = {
        "system",
        "architecture",
        "libc",
        "url",
        "sha256",
        "archive_size",
        "member",
        "member_sha256",
    }
    for platform_key, raw_artifact in platforms.items():
        if not isinstance(platform_key, str) or not platform_key:
            raise UvBootstrapError("uv bootstrap platform key is invalid.")
        _require_keys(
            raw_artifact,
            artifact_fields,
            label=f"uv bootstrap platform {platform_key!r}",
        )
        system = raw_artifact["system"]
        architecture = raw_artifact["architecture"]
        libc = raw_artifact["libc"]
        if not all(
            isinstance(value, str) and value and value == value.casefold()
            for value in (system, architecture, libc)
        ):
            raise UvBootstrapError(
                f"uv bootstrap platform {platform_key!r} has invalid tuple values."
            )
        expected_key = f"{system}-{architecture}-{libc}"
        if platform_key != expected_key:
            raise UvBootstrapError(
                f"uv bootstrap platform key must match its tuple: {expected_key}."
            )
        digest = raw_artifact["sha256"]
        if not isinstance(digest, str) or not _DIGEST_PATTERN.fullmatch(digest):
            raise UvBootstrapError(
                f"uv bootstrap platform {platform_key!r} has an invalid SHA-256."
            )
        archive_size = raw_artifact["archive_size"]
        if (
            isinstance(archive_size, bool)
            or not isinstance(archive_size, int)
            or archive_size <= 0
            or archive_size > _MAX_ARCHIVE_SIZE
        ):
            raise UvBootstrapError(
                f"uv bootstrap platform {platform_key!r} has an invalid archive size."
            )
        member = raw_artifact["member"]
        _validate_member_name(member)
        member_digest = raw_artifact["member_sha256"]
        if not isinstance(member_digest, str) or not _DIGEST_PATTERN.fullmatch(
            member_digest
        ):
            raise UvBootstrapError(
                f"uv bootstrap platform {platform_key!r} has an invalid member SHA-256."
            )
        url = raw_artifact["url"]
        _validate_https_url(url, allowed_hosts, version=version)
        artifacts[platform_key] = UvArtifact(
            platform_key=platform_key,
            system=system,
            architecture=architecture,
            libc=libc,
            url=url,
            sha256=digest,
            archive_size=archive_size,
            member=member,
            member_sha256=member_digest,
        )

    return UvBootstrapManifest(
        version=version,
        allowed_redirect_hosts=allowed_hosts,
        platforms=MappingProxyType(artifacts),
    )


# @testable false
# @covered-by runner/uv_bootstrap.py::select_artifact
# @reason host normalization is exercised through supported and unsupported selections
def _host_platform_key(*, system=None, architecture=None, libc=None):
    system = str(system or platform.system()).strip().casefold()
    architecture = str(architecture or platform.machine()).strip().casefold()
    if system == "linux":
        system = "linux"
    elif system in {"darwin", "macos"}:
        system = "darwin"
    elif system.startswith("win"):
        system = "windows"

    architecture = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get(architecture, architecture)
    if libc is None and system == "linux":
        libc = platform.libc_ver()[0]
    libc = str(libc or "none").strip().casefold()
    if libc in {"glibc", "gnu", "gnu libc"} or libc.startswith("glibc"):
        libc = "gnu"
    elif libc.startswith("musl"):
        libc = "musl"
    return f"{system}-{architecture}-{libc}"


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_manifest_and_managed_context_path
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_rejects_unsupported_host
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_manifest_preserves_supported_macos_development_hosts
# @matrix mcp-package setup : bootstrap macos platform-pin platform-selection portability wsl
def select_artifact(manifest, *, system=None, architecture=None, libc=None):
    """Select the one declared artifact matching the current host tuple."""
    platform_key = _host_platform_key(
        system=system,
        architecture=architecture,
        libc=libc,
    )
    try:
        return manifest.platforms[platform_key]
    except KeyError as error:
        raise UvBootstrapError(
            f"Managed uv does not support this host tuple ({platform_key})."
        ) from error


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_manifest_and_managed_context_path
# @matrix mcp-package setup : bootstrap managed-path version-pin
def managed_uv_path(*, manifest_path=BOOTSTRAP_MANIFEST, virtualenv=PROJECT_VIRTUALENV):
    """Return the manifest-versioned managed uv path without consulting PATH."""
    manifest = load_manifest(manifest_path)
    executable = "uv.exe" if os.name == "nt" else "uv"
    return Path(virtualenv) / "tools" / "uv" / manifest.version / executable


# @testable false
# @covered-by runner/uv_bootstrap.py::install_uv
# @reason destination ownership and symlink rules are covered through install cases
def _require_safe_directory(path, *, create=False):
    path = Path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if not create:
            raise UvBootstrapError(f"Managed uv directory is missing: {path}")
        try:
            path.mkdir(mode=0o700)
            metadata = path.lstat()
        except OSError as error:
            raise UvBootstrapError(
                f"Could not create managed uv directory: {path}"
            ) from error
    except OSError as error:
        raise UvBootstrapError(
            f"Could not inspect managed uv directory: {path}"
        ) from error

    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise UvBootstrapError(f"Managed uv directory is unsafe: {path}")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise UvBootstrapError(
            f"Managed uv directory is not owned by this user: {path}"
        )
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise UvBootstrapError(f"Managed uv directory is group/world writable: {path}")


# @testable false
# @covered-by runner/uv_bootstrap.py::install_uv
# @reason safe directory creation is exercised through the public installer
def _prepare_destination(virtualenv, version):
    virtualenv = Path(virtualenv)
    if not virtualenv.is_absolute():
        raise UvBootstrapError("Managed uv virtualenv path must be absolute.")
    _require_safe_directory(virtualenv)
    current = virtualenv
    for component in ("tools", "uv", version):
        current = current / component
        _require_safe_directory(current, create=True)
    executable = current / ("uv.exe" if os.name == "nt" else "uv")
    try:
        metadata = executable.lstat()
    except FileNotFoundError:
        return executable
    except OSError as error:
        raise UvBootstrapError(
            f"Could not inspect managed uv executable: {executable}"
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or executable.is_symlink():
        raise UvBootstrapError(f"Managed uv executable is unsafe: {executable}")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise UvBootstrapError(
            f"Managed uv executable is not owned by this user: {executable}"
        )
    return executable


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_installs_idempotently_and_repairs_corrupt_copy
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_check_rejects_wrong_version_and_permissions
# @matrix mcp-package setup : bootstrap executable-permissions version-verification
def verify_uv(executable, version, expected_sha256, *, run=subprocess.run):
    """Verify ownership, mode, exact bytes, and version of managed uv."""
    executable = Path(executable)
    try:
        metadata = executable.lstat()
    except FileNotFoundError as error:
        raise UvBootstrapError(
            f"Managed uv executable is missing: {executable}"
        ) from error
    except OSError as error:
        raise UvBootstrapError(
            f"Could not inspect managed uv executable: {executable}"
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or executable.is_symlink():
        raise UvBootstrapError(
            f"Managed uv executable is not a regular file: {executable}"
        )
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise UvBootstrapError(
            f"Managed uv executable is not owned by this user: {executable}"
        )
    required_mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    if metadata.st_mode & required_mode != required_mode:
        raise UvBootstrapError(
            f"Managed uv executable is not owner-readable, writable, and executable: {executable}"
        )
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise UvBootstrapError(
            f"Managed uv executable is group/world writable: {executable}"
        )
    digest = hashlib.sha256()
    try:
        with executable.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_DOWNLOAD_CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError as error:
        raise UvBootstrapError(
            f"Managed uv executable could not be read: {executable}"
        ) from error
    if digest.hexdigest() != expected_sha256:
        raise UvBootstrapError(
            f"Managed uv executable SHA-256 does not match the manifest: {executable}"
        )
    try:
        result = run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise UvBootstrapError(
            f"Managed uv could not be executed: {executable}"
        ) from error
    output = str(result.stdout or "").strip().split()
    if result.returncode != 0 or len(output) < 2 or output[:2] != ["uv", version]:
        raise UvBootstrapError(
            f"Managed uv version mismatch; expected uv {version}: {executable}"
        )
    return executable


# @testable false
# @covered-by runner/uv_bootstrap.py::install_uv
# @reason redirect enforcement is exercised through guarded-download install cases
class _AllowedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts):
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        _validate_https_url(
            new_url,
            self._allowed_hosts,
        )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


# @testable false
# @covered-by runner/uv_bootstrap.py::install_uv
# @reason bounded transport behavior is exercised with offline response fixtures
def _download_archive(manifest, artifact, destination, *, opener=None):
    _validate_https_url(
        artifact.url,
        manifest.allowed_redirect_hosts,
        version=manifest.version,
    )
    if opener is None:
        opener = build_opener(
            HTTPSHandler(),
            _AllowedRedirectHandler(manifest.allowed_redirect_hosts),
        )
    request = Request(
        artifact.url,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": f"lagniappe-uv-bootstrap/{manifest.version}",
        },
        method="GET",
    )
    try:
        open_request = opener.open
        response = open_request(request, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        with response:
            _validate_https_url(
                response.geturl(),
                manifest.allowed_redirect_hosts,
            )
            status_code = getattr(response, "status", 200)
            if status_code != 200:
                raise UvBootstrapError(
                    f"uv archive download returned HTTP {status_code}."
                )
            content_encoding = str(response.headers.get("Content-Encoding", "identity"))
            if content_encoding.casefold() not in {"", "identity"}:
                raise UvBootstrapError("uv archive response used unexpected encoding.")
            length_header = response.headers.get("Content-Length")
            if length_header is not None:
                try:
                    declared_length = int(length_header)
                except (TypeError, ValueError) as error:
                    raise UvBootstrapError(
                        "uv archive response has an invalid Content-Length."
                    ) from error
                if declared_length != artifact.archive_size:
                    raise UvBootstrapError(
                        "uv archive response size does not match the manifest."
                    )

            digest = hashlib.sha256()
            received = 0
            with Path(destination).open("xb") as archive_file:
                while True:
                    chunk = response.read(_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > artifact.archive_size:
                        raise UvBootstrapError(
                            "uv archive exceeded the manifest size ceiling."
                        )
                    archive_file.write(chunk)
                    digest.update(chunk)
                archive_file.flush()
                os.fsync(archive_file.fileno())
    except UvBootstrapError:
        raise
    except (HTTPError, URLError, OSError, http.client.HTTPException) as error:
        raise UvBootstrapError(f"uv archive download failed: {error}") from error

    if received != artifact.archive_size:
        raise UvBootstrapError(
            "uv archive was truncated or its size does not match the manifest."
        )
    if digest.hexdigest() != artifact.sha256:
        raise UvBootstrapError("uv archive SHA-256 does not match the manifest.")


# @testable false
# @covered-by runner/uv_bootstrap.py::install_uv
# @reason tar member/type/size validation is exercised through unsafe archive cases
def _extract_executable(archive_path, artifact, destination):
    member_limit = max(1024 * 1024, artifact.archive_size * 8)
    selected = None
    try:
        with open_tar_archive(archive_path, mode="r:*") as archive:
            for member_index, member in enumerate(archive):
                if member_index >= _MAX_ARCHIVE_MEMBERS:
                    raise UvBootstrapError("uv archive contains too many members.")
                _validate_member_name(member.name, directory=member.isdir())
                if member.isdir():
                    continue
                if not member.isfile():
                    raise UvBootstrapError(
                        f"uv archive contains a link or special member: {member.name}"
                    )
                if member.size < 0 or member.size > member_limit:
                    raise UvBootstrapError(
                        f"uv archive member exceeds the extraction limit: {member.name}"
                    )
                if member.name == artifact.member:
                    if selected is not None:
                        raise UvBootstrapError(
                            "uv archive contains the declared executable more than once."
                        )
                    selected = member

            if selected is None:
                raise UvBootstrapError(
                    "uv archive does not contain the declared executable member."
                )
            source = archive.extractfile(selected)
            if source is None:
                raise UvBootstrapError(
                    "uv archive executable member could not be read."
                )
            written = 0
            digest = hashlib.sha256()
            with source, Path(destination).open("xb") as executable_file:
                while True:
                    chunk = source.read(_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > member_limit:
                        raise UvBootstrapError(
                            "uv archive executable exceeded the extraction limit."
                        )
                    executable_file.write(chunk)
                    digest.update(chunk)
                if written != selected.size:
                    raise UvBootstrapError("uv archive executable was truncated.")
                if digest.hexdigest() != artifact.member_sha256:
                    raise UvBootstrapError(
                        "uv archive executable SHA-256 does not match the manifest."
                    )
                executable_file.flush()
                os.fsync(executable_file.fileno())
    except UvBootstrapError:
        raise
    except (OSError, tarfile.TarError) as error:
        raise UvBootstrapError(f"uv archive extraction failed: {error}") from error


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_installs_idempotently_and_repairs_corrupt_copy
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_preserves_existing_copy_on_download_or_replace_failure
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_rejects_unsafe_destination
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_rejects_unsafe_or_untrusted_archives_without_replacing
# @matrix mcp-package setup : atomic-install bootstrap digest download-bounds fail-closed idempotence managed-path repair tar-safety url-policy
def install_uv(
    *,
    manifest_path=BOOTSTRAP_MANIFEST,
    virtualenv=PROJECT_VIRTUALENV,
    system=None,
    architecture=None,
    libc=None,
    opener=None,
    run=subprocess.run,
    replace=None,
):
    """Install or repair the declared uv executable without replacing a valid copy."""
    manifest = load_manifest(manifest_path)
    artifact = select_artifact(
        manifest,
        system=system,
        architecture=architecture,
        libc=libc,
    )
    destination = _prepare_destination(virtualenv, manifest.version)
    if destination.exists():
        try:
            return verify_uv(
                destination,
                manifest.version,
                artifact.member_sha256,
                run=run,
            )
        except UvBootstrapError:
            pass

    replace = os.replace if replace is None else replace
    try:
        temporary_directory = tempfile.mkdtemp(
            prefix=".uv-bootstrap-",
            dir=destination.parent,
        )
    except OSError as error:
        raise UvBootstrapError(
            f"Could not create a private managed uv staging directory: {destination.parent}"
        ) from error
    try:
        os.chmod(temporary_directory, 0o700)
        temporary_root = Path(temporary_directory)
        archive_path = temporary_root / "uv-release.tar"
        candidate = temporary_root / destination.name
        _download_archive(manifest, artifact, archive_path, opener=opener)
        _extract_executable(archive_path, artifact, candidate)
        candidate.chmod(0o700)
        verify_uv(
            candidate,
            manifest.version,
            artifact.member_sha256,
            run=run,
        )
        try:
            replace(candidate, destination)
        except OSError as error:
            raise UvBootstrapError(
                f"Could not atomically install managed uv: {destination}"
            ) from error
        try:
            directory_descriptor = os.open(destination.parent, os.O_RDONLY)
            try:
                try:
                    os.fsync(directory_descriptor)
                except OSError:
                    # Some supported filesystems do not permit directory fsync;
                    # os.replace has already provided the atomic boundary.
                    pass
            finally:
                os.close(directory_descriptor)
        except OSError:
            # Atomic replacement has completed. Directory fsync is a best-effort
            # durability improvement on filesystems that support it.
            pass
    except UvBootstrapError:
        raise
    except OSError as error:
        raise UvBootstrapError(f"Managed uv installation failed: {error}") from error
    finally:
        shutil.rmtree(temporary_directory, ignore_errors=True)
    return destination


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_installs_idempotently_and_repairs_corrupt_copy
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_check_rejects_wrong_version_and_permissions
# @matrix mcp-package setup : bootstrap diagnostics executable-digest executable-permissions version-verification
def check_uv(
    *,
    manifest_path=BOOTSTRAP_MANIFEST,
    virtualenv=PROJECT_VIRTUALENV,
    system=None,
    architecture=None,
    libc=None,
    run=subprocess.run,
):
    """Verify the manifest-selected managed uv executable without downloading."""
    manifest = load_manifest(manifest_path)
    artifact = select_artifact(
        manifest,
        system=system,
        architecture=architecture,
        libc=libc,
    )
    executable = managed_uv_path(
        manifest_path=manifest_path,
        virtualenv=virtualenv,
    )
    return verify_uv(
        executable,
        manifest.version,
        artifact.member_sha256,
        run=run,
    )


# @testable true
# @tests tests_tooling/test_012_mcp_package.py::test_uv_bootstrap_cli_is_noninteractive_and_actionable
# @matrix mcp-package setup : bootstrap cli diagnostics non-interactive
def main(arguments=None):
    """Run the explicit managed-uv install or read-only verification command."""
    parser = argparse.ArgumentParser(
        prog="python -m runner.uv_bootstrap",
        description="Install or verify Lagniappe's pinned development uv executable.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Confirm that the pinned download may run without prompting.",
    )
    subparsers.add_parser("check")
    parsed = parser.parse_args(arguments)

    if parsed.command == "install" and not parsed.non_interactive:
        print(
            "Managed uv installation requires --non-interactive. "
            "Run ./setup.sh development.",
            file=sys.stderr,
        )
        return 2
    try:
        if parsed.command == "install":
            executable = install_uv()
            print(f"Managed uv is installed: {executable}")
        else:
            executable = check_uv()
            print(f"Managed uv is ready: {executable}")
    except UvBootstrapError as error:
        print(f"Managed uv check failed: {error}", file=sys.stderr)
        print("Run ./setup.sh development to repair it.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
