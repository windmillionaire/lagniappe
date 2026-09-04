"""Offline repository-tooling coverage for the standalone MCP environment."""

from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tomllib
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.tooling
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
UV_SCRIPT = b"#!/bin/sh\nprintf '%s\\n' 'uv 0.12.9'\n"


class _ArchiveResponse(io.BytesIO):
    status = 200

    def __init__(self, payload, url):
        super().__init__(payload)
        self._url = url
        self.headers = {
            "Content-Length": str(len(payload)),
            "Content-Encoding": "identity",
        }

    def geturl(self):
        return self._url


class _ArchiveOpener:
    def __init__(self, payload, *, final_url=None):
        self.payload = payload
        self.final_url = final_url
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        return _ArchiveResponse(
            self.payload,
            self.final_url or request.full_url,
        )


def _archive(*, unsafe_member=None):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        directory = tarfile.TarInfo("uv-x86_64-unknown-linux-gnu")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)

        executable = tarfile.TarInfo("uv-x86_64-unknown-linux-gnu/uv")
        executable.size = len(UV_SCRIPT)
        executable.mode = 0o755
        archive.addfile(executable, io.BytesIO(UV_SCRIPT))

        if unsafe_member is not None:
            archive.addfile(unsafe_member)
    return buffer.getvalue()


def _write_manifest(path, payload, *, digest=None, member_digest=None):
    manifest = {
        "schema": 1,
        "version": "0.12.9",
        "allowed_redirect_hosts": [
            "github.com",
            "release-assets.githubusercontent.com",
        ],
        "platforms": {
            "linux-x86_64-gnu": {
                "system": "linux",
                "architecture": "x86_64",
                "libc": "gnu",
                "url": (
                    "https://github.com/astral-sh/uv/releases/download/"
                    "0.12.9/uv-x86_64-unknown-linux-gnu.tar.gz"
                ),
                "sha256": digest or hashlib.sha256(payload).hexdigest(),
                "archive_size": len(payload),
                "member": "uv-x86_64-unknown-linux-gnu/uv",
                "member_sha256": member_digest
                or hashlib.sha256(UV_SCRIPT).hexdigest(),
            }
        },
    }
    path.write_text(f"{json.dumps(manifest, indent=2)}\n", encoding="utf-8")
    return manifest


def _uv_runner(command, **_kwargs):
    executable = Path(command[0])
    try:
        content = executable.read_bytes()
    except OSError:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="missing")
    version = "uv 0.12.9\n" if content == UV_SCRIPT else "uv corrupt\n"
    return subprocess.CompletedProcess(command, 0, stdout=version, stderr="")


def test_uv_bootstrap_is_standard_library_only():
    path = REPOSITORY_ROOT / "runner/uv_bootstrap.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots <= sys.stdlib_module_names | {"__future__"}
    assert "shutil.which" not in source


# @matrix mcp-package setup : bootstrap manifest managed-path platform-pin url-policy version-pin
def test_uv_bootstrap_manifest_and_managed_context_path():
    from runner import context, uv_bootstrap

    manifest = uv_bootstrap.load_manifest()
    artifact = uv_bootstrap.select_artifact(
        manifest,
        system="Linux",
        architecture="amd64",
        libc="glibc>=2.17",
    )
    project = tomllib.loads(
        (REPOSITORY_ROOT / "clients/lagniappe_mcp/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    lock = tomllib.loads(
        (REPOSITORY_ROOT / "clients/lagniappe_mcp/uv.lock").read_text(
            encoding="utf-8"
        )
    )

    assert manifest.version == "0.12.9"
    assert project["tool"]["uv"]["required-version"] == "==0.12.9"
    assert project["dependency-groups"]["test"] == [
        "pytest==9.1.1",
        "uv-build==0.12.9",
    ]
    root_package = next(
        package for package in lock["package"] if package["name"] == "lagniappe-mcp"
    )
    assert root_package["metadata"]["requires-dev"]["test"] == [
        {"name": "pytest", "specifier": "==9.1.1"},
        {"name": "uv-build", "specifier": "==0.12.9"},
    ]
    assert manifest.allowed_redirect_hosts == {
        "github.com",
        "release-assets.githubusercontent.com",
    }
    assert artifact.platform_key == "linux-x86_64-gnu"
    assert artifact.sha256 == (
        "ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460"
    )
    assert artifact.archive_size == 19423276
    assert artifact.member == "uv-x86_64-unknown-linux-gnu/uv"
    assert artifact.member_sha256 == (
        "671793498fe0a545432e2524b6691ffb9eea4540d9fda43ca2f978df2dbf8426"
    )
    assert "/latest/" not in artifact.url
    assert context.UV_CLI == (REPOSITORY_ROOT / "venv/tools/uv/0.12.9/uv")
    assert "uv" not in context.TOOL_PATHS


# @matrix mcp-package setup : bootstrap macos platform-pin portability
def test_uv_bootstrap_manifest_preserves_supported_macos_development_hosts():
    from runner import uv_bootstrap

    manifest = uv_bootstrap.load_manifest()
    apple_silicon = uv_bootstrap.select_artifact(
        manifest,
        system="Darwin",
        architecture="arm64",
    )
    intel = uv_bootstrap.select_artifact(
        manifest,
        system="macOS",
        architecture="x86_64",
    )

    assert apple_silicon.platform_key == "darwin-aarch64-none"
    assert apple_silicon.sha256 == (
        "301f72afaf54060f92da7016cb0115bd077f43a9c8e39c1d8170a0bac80fd398"
    )
    assert apple_silicon.archive_size == 16636737
    assert apple_silicon.member == "uv-aarch64-apple-darwin/uv"
    assert apple_silicon.member_sha256 == (
        "5e2e4133be3e61a25f819b95f6d6bb38c61fb3062eddf3e0857bb72fa3c69205"
    )

    assert intel.platform_key == "darwin-x86_64-none"
    assert intel.sha256 == (
        "e1ca175824f1056589ce9908f7631879ebc3c36535b5e63dc06510beb370b4c1"
    )
    assert intel.archive_size == 19952135
    assert intel.member == "uv-x86_64-apple-darwin/uv"
    assert intel.member_sha256 == (
        "935ac2592d1f6975571fc332b02527049fc4c4fc3604917a9936b2cf329aa821"
    )


# @matrix hosted-e2e mcp-package deploy : build-context dependency-layer image-boundary installer-pin platform-pin
def test_mcp_docker_builds_pin_tools_and_explicitly_include_client_source():
    standard_root = REPOSITORY_ROOT / "runner/hosted_e2e_container"
    package_root = REPOSITORY_ROOT / "runner/mcp_package_container"
    metadata_copy = (
        "COPY clients/lagniappe_mcp/pyproject.toml "
        "clients/lagniappe_mcp/uv.lock clients/lagniappe_mcp/README.md "
        "clients/lagniappe_mcp/"
    )
    source_copy = "COPY clients/lagniappe_mcp/src clients/lagniappe_mcp/src"

    for container_root in (standard_root, package_root):
        dockerfile = (container_root / "Dockerfile").read_text(encoding="utf-8")
        ignore = (container_root / "gcloudignore").read_text(encoding="utf-8")
        cloudbuild = (container_root / "cloudbuild.yaml").read_text(encoding="utf-8")

        assert dockerfile.index(metadata_copy) < dockerfile.index(source_copy)
        assert dockerfile.index(source_copy) < dockerfile.rindex("COPY . .")
        assert "--locked --group test --no-install-project --no-editable" in dockerfile
        assert "--locked --group test --no-editable" in dockerfile
        assert "--no-build-isolation --offline" in dockerfile
        assert "!/clients/lagniappe_mcp/**" in ignore
        assert "/clients/lagniappe_mcp/.venv/" in ignore
        assert f"runner/{container_root.name}/Dockerfile" in cloudbuild

    root_ignore = (REPOSITORY_ROOT / ".gcloudignore").read_text(encoding="utf-8")
    assert "/clients/" in root_ignore
    standard = (standard_root / "Dockerfile").read_text(encoding="utf-8")
    final_standard = standard.rsplit("\nFROM ", 1)[1]
    assert "COPY --from=mcp-builder" in final_standard
    assert "pipx" not in final_standard
    assert "COPY --from=uv-runtime /uv" not in final_standard
    assert "ghcr.io/astral-sh/uv:0.12.9@sha256:" in standard

    package = (package_root / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.14-slim-bookworm@sha256:" in package
    assert "uv/releases/download/0.12.9/" in package
    assert "pypa/pipx/releases/download/1.17.2/pipx.pyz" in package
    assert "openai/codex/releases/download/rust-v0.153.0/" in package
    assert package.count("ADD --checksum=sha256:") == 3


# @matrix mcp-package setup : bootstrap manifest url-policy validation
def test_uv_bootstrap_rejects_malformed_manifest(tmp_path):
    from runner.uv_bootstrap import UvBootstrapError, load_manifest

    payload = _archive()
    manifest_path = tmp_path / "uv-bootstrap.json"
    manifest = _write_manifest(manifest_path, payload)
    manifest["unexpected"] = True
    manifest_path.write_text(
        f"{json.dumps(manifest)}\n",
        encoding="utf-8",
    )
    with pytest.raises(UvBootstrapError, match="unexpected unexpected"):
        load_manifest(manifest_path)

    manifest.pop("unexpected")
    manifest["platforms"]["linux-x86_64-gnu"]["url"] = (
        "http://github.com/astral-sh/uv/releases/download/0.12.9/uv.tar.gz"
    )
    manifest_path.write_text(
        f"{json.dumps(manifest)}\n",
        encoding="utf-8",
    )
    with pytest.raises(UvBootstrapError, match="declared HTTPS release host"):
        load_manifest(manifest_path)


# @matrix mcp-package setup : bootstrap platform-selection portability wsl
def test_uv_bootstrap_rejects_unsupported_host():
    from runner.uv_bootstrap import UvBootstrapError, load_manifest, select_artifact

    manifest = load_manifest()
    with pytest.raises(UvBootstrapError, match="linux-aarch64-musl"):
        select_artifact(
            manifest,
            system="Linux",
            architecture="arm64",
            libc="musl",
        )
    with pytest.raises(UvBootstrapError, match="windows-x86_64-none"):
        select_artifact(
            manifest,
            system="Windows",
            architecture="AMD64",
            libc="none",
        )


# @matrix mcp-package setup : atomic-install bootstrap diagnostics digest executable-permissions idempotence repair tar-safety version-verification
def test_uv_bootstrap_installs_idempotently_and_repairs_corrupt_copy(tmp_path):
    from runner.uv_bootstrap import check_uv, install_uv

    payload = _archive()
    manifest_path = tmp_path / "uv-bootstrap.json"
    _write_manifest(manifest_path, payload)
    virtualenv = tmp_path / "venv"
    virtualenv.mkdir(mode=0o700)
    opener = _ArchiveOpener(payload)
    options = {
        "manifest_path": manifest_path,
        "virtualenv": virtualenv,
        "system": "Linux",
        "architecture": "x86_64",
        "libc": "gnu",
        "opener": opener,
        "run": _uv_runner,
    }

    executable = install_uv(**options)
    assert executable.read_bytes() == UV_SCRIPT
    assert stat.S_IMODE(executable.stat().st_mode) == 0o700
    assert (
        check_uv(**{key: value for key, value in options.items() if key != "opener"})
        == executable
    )
    assert len(opener.requests) == 1

    assert install_uv(**options) == executable
    assert len(opener.requests) == 1

    executable.write_bytes(b"corrupt")
    executable.chmod(0o700)
    assert install_uv(**options) == executable
    assert executable.read_bytes() == UV_SCRIPT
    assert len(opener.requests) == 2


# @matrix mcp-package setup : bootstrap diagnostics executable-digest executable-permissions version-verification
def test_uv_bootstrap_check_rejects_wrong_version_and_permissions(tmp_path):
    from runner.uv_bootstrap import UvBootstrapError, check_uv, install_uv

    payload = _archive()
    manifest_path = tmp_path / "uv-bootstrap.json"
    _write_manifest(manifest_path, payload)
    virtualenv = tmp_path / "venv"
    virtualenv.mkdir(mode=0o700)
    executable = install_uv(
        manifest_path=manifest_path,
        virtualenv=virtualenv,
        system="Linux",
        architecture="x86_64",
        libc="gnu",
        opener=_ArchiveOpener(payload),
        run=_uv_runner,
    )

    executable.chmod(0o500)
    with pytest.raises(UvBootstrapError, match="owner-readable, writable"):
        check_uv(
            manifest_path=manifest_path,
            virtualenv=virtualenv,
            system="Linux",
            architecture="x86_64",
            libc="gnu",
            run=_uv_runner,
        )
    executable.chmod(0o722)
    with pytest.raises(UvBootstrapError, match="group/world writable"):
        check_uv(
            manifest_path=manifest_path,
            virtualenv=virtualenv,
            system="Linux",
            architecture="x86_64",
            libc="gnu",
            run=_uv_runner,
        )
    executable.chmod(0o700)
    def wrong_version(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="uv 0.12.8\n",
            stderr="",
        )
    with pytest.raises(UvBootstrapError, match="version mismatch"):
        check_uv(
            manifest_path=manifest_path,
            virtualenv=virtualenv,
            system="Linux",
            architecture="x86_64",
            libc="gnu",
            run=wrong_version,
        )

    executable.write_bytes(UV_SCRIPT + b"# same reported version, different bytes\n")
    executable.chmod(0o700)
    with pytest.raises(UvBootstrapError, match="SHA-256"):
        check_uv(
            manifest_path=manifest_path,
            virtualenv=virtualenv,
            system="Linux",
            architecture="x86_64",
            libc="gnu",
            run=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout="uv 0.12.9\n",
                stderr="",
            ),
        )


# @matrix mcp-package release : bootstrap executable-digest fail-closed reproducible-build
def test_artifact_builder_requires_exact_managed_uv_bytes(tmp_path):
    from runner import mcp_artifact

    payload = _archive()
    manifest_path = tmp_path / "clients/lagniappe_mcp/uv-bootstrap.json"
    manifest_path.parent.mkdir(parents=True)
    _write_manifest(manifest_path, payload)
    executable = tmp_path / "venv/tools/uv/0.12.9/uv"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(UV_SCRIPT)
    executable.chmod(0o700)

    assert mcp_artifact._managed_uv(tmp_path) == executable

    executable.write_bytes(UV_SCRIPT + b"# same version, untrusted bytes\n")
    executable.chmod(0o700)
    with pytest.raises(mcp_artifact.McpArtifactError, match="exact-byte"):
        mcp_artifact._managed_uv(tmp_path)


# @matrix mcp-package release : command-bridge interpreter-isolation managed-path
# @source runner/mcp_artifact.py::_managed_uv
def test_artifact_builder_loads_managed_uv_from_isolated_script(tmp_path):
    payload = _archive()
    manifest_path = tmp_path / "clients/lagniappe_mcp/uv-bootstrap.json"
    manifest_path.parent.mkdir(parents=True)
    _write_manifest(manifest_path, payload)
    executable = tmp_path / "venv/tools/uv/0.12.9/uv"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(UV_SCRIPT)
    executable.chmod(0o700)
    artifact_script = REPOSITORY_ROOT / "runner/mcp_artifact.py"
    probe = """
from pathlib import Path
import runpy
import sys

namespace = runpy.run_path(sys.argv[1], run_name="mcp_artifact_probe")
print(namespace["_managed_uv"](Path(sys.argv[2])))
""".strip()

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            probe,
            str(artifact_script),
            str(tmp_path),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(executable)


# @matrix mcp-package release : locked-dependencies build-isolation reproducible-build
def test_artifact_builder_uses_locked_build_backend(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from runner import mcp_artifact

    managed_uv = tmp_path / "venv/tools/uv/0.12.9/uv"
    monkeypatch.setattr(mcp_artifact, "_managed_uv", lambda _root: managed_uv)
    monkeypatch.setenv("UV_BUILD_POISON", "must-not-propagate")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == "build":
            output = Path(command[command.index("--out-dir") + 1])
            (output / "lagniappe_mcp-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    output = tmp_path / "wheel-output"
    assert mcp_artifact._run_wheel_build(tmp_path, output, run=run).is_file()
    sync, build = (call[0] for call in calls)
    assert sync[:2] == [str(managed_uv), "sync"]
    assert "--locked" in sync
    assert sync[sync.index("--group") + 1] == "test"
    assert "--no-install-project" in sync
    assert "--no-build" in sync
    assert build[:2] == [str(managed_uv), "build"]
    assert "--no-build-isolation" in build
    assert "--offline" in build
    assert build[build.index("--python") + 1].endswith(
        "clients/lagniappe_mcp/.venv/bin/python"
    )
    assert all("UV_BUILD_POISON" not in call[1]["env"] for call in calls)


# @matrix mcp-package setup : atomic-install bootstrap tar-safety url-policy
@pytest.mark.parametrize(
    "unsafe_member",
    [
        pytest.param(
            SimpleNamespace(
                name="../escape",
                type=tarfile.REGTYPE,
                size=0,
                mode=0o644,
            ),
            id="traversal",
        ),
        pytest.param(
            SimpleNamespace(
                name="uv-x86_64-unknown-linux-gnu/uv-link",
                type=tarfile.SYMTYPE,
                linkname="uv",
                size=0,
                mode=0o777,
            ),
            id="symlink",
        ),
    ],
)
def test_uv_bootstrap_rejects_unsafe_or_untrusted_archives_without_replacing(
    tmp_path,
    unsafe_member,
):
    from runner.uv_bootstrap import UvBootstrapError, install_uv

    safe_payload = _archive()
    manifest_path = tmp_path / "uv-bootstrap.json"
    _write_manifest(manifest_path, safe_payload)
    virtualenv = tmp_path / "venv"
    virtualenv.mkdir(mode=0o700)
    executable = install_uv(
        manifest_path=manifest_path,
        virtualenv=virtualenv,
        system="Linux",
        architecture="x86_64",
        libc="gnu",
        opener=_ArchiveOpener(safe_payload),
        run=_uv_runner,
    )
    original = executable.read_bytes()

    tar_member = tarfile.TarInfo(unsafe_member.name)
    tar_member.type = unsafe_member.type
    tar_member.size = unsafe_member.size
    tar_member.mode = unsafe_member.mode
    if hasattr(unsafe_member, "linkname"):
        tar_member.linkname = unsafe_member.linkname
    unsafe_payload = _archive(unsafe_member=tar_member)
    _write_manifest(manifest_path, unsafe_payload)

    def destination_looks_stale(command, **kwargs):
        if Path(command[0]) == executable:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="uv wrong\n",
                stderr="",
            )
        return _uv_runner(command, **kwargs)

    with pytest.raises(UvBootstrapError, match="unsafe member|link or special"):
        install_uv(
            manifest_path=manifest_path,
            virtualenv=virtualenv,
            system="Linux",
            architecture="x86_64",
            libc="gnu",
            opener=_ArchiveOpener(unsafe_payload),
            run=destination_looks_stale,
        )
    assert executable.read_bytes() == original

    with pytest.raises(UvBootstrapError, match="declared HTTPS release host"):
        install_uv(
            manifest_path=manifest_path,
            virtualenv=virtualenv,
            system="Linux",
            architecture="x86_64",
            libc="gnu",
            opener=_ArchiveOpener(
                unsafe_payload,
                final_url="https://attacker.example/uv.tar.gz",
            ),
            run=destination_looks_stale,
        )
    assert executable.read_bytes() == original


# @matrix mcp-package setup : atomic-install bootstrap digest download-bounds repair
@pytest.mark.parametrize(
    "failure",
    ["digest", "member-digest", "truncated", "oversized", "replace"],
)
def test_uv_bootstrap_preserves_existing_copy_on_download_or_replace_failure(
    tmp_path,
    failure,
):
    from runner.uv_bootstrap import UvBootstrapError, install_uv

    payload = _archive()
    manifest_path = tmp_path / "uv-bootstrap.json"
    _write_manifest(manifest_path, payload)
    virtualenv = tmp_path / "venv"
    virtualenv.mkdir(mode=0o700)
    executable = install_uv(
        manifest_path=manifest_path,
        virtualenv=virtualenv,
        system="Linux",
        architecture="x86_64",
        libc="gnu",
        opener=_ArchiveOpener(payload),
        run=_uv_runner,
    )
    original = executable.read_bytes()

    def destination_looks_stale(command, **kwargs):
        if Path(command[0]) == executable:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="uv wrong\n",
                stderr="",
            )
        return _uv_runner(command, **kwargs)

    replacement = None
    download = payload
    expected = ""
    if failure == "digest":
        _write_manifest(manifest_path, payload, digest="0" * 64)
        expected = "SHA-256"
    elif failure == "member-digest":
        _write_manifest(manifest_path, payload, member_digest="0" * 64)
        expected = "executable SHA-256"
    elif failure == "truncated":
        download = payload[:-1]
        expected = "size does not match"
    elif failure == "oversized":
        download = payload + b"x"
        expected = "size does not match"
    else:

        def fail_replace(_source, _destination):
            raise OSError("injected replacement failure")

        replacement = fail_replace
        expected = "atomically install"

    with pytest.raises(UvBootstrapError, match=expected):
        install_uv(
            manifest_path=manifest_path,
            virtualenv=virtualenv,
            system="Linux",
            architecture="x86_64",
            libc="gnu",
            opener=_ArchiveOpener(download),
            run=destination_looks_stale,
            replace=replacement,
        )
    assert executable.read_bytes() == original


# @matrix mcp-package setup : bootstrap fail-closed managed-path tar-safety
def test_uv_bootstrap_rejects_unsafe_destination(tmp_path):
    from runner.uv_bootstrap import UvBootstrapError, install_uv

    payload = _archive()
    manifest_path = tmp_path / "uv-bootstrap.json"
    _write_manifest(manifest_path, payload)
    virtualenv = tmp_path / "venv"
    virtualenv.mkdir(mode=0o700)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (virtualenv / "tools").symlink_to(elsewhere, target_is_directory=True)
    opener = _ArchiveOpener(payload)

    with pytest.raises(UvBootstrapError, match="directory is unsafe"):
        install_uv(
            manifest_path=manifest_path,
            virtualenv=virtualenv,
            system="Linux",
            architecture="x86_64",
            libc="gnu",
            opener=opener,
            run=_uv_runner,
        )
    assert opener.requests == []


# @matrix mcp-package setup : bootstrap cli diagnostics non-interactive
def test_uv_bootstrap_cli_is_noninteractive_and_actionable(monkeypatch, capsys):
    from runner import uv_bootstrap

    assert uv_bootstrap.main(["install"]) == 2
    assert "./setup.sh development" in capsys.readouterr().err

    installed = []
    monkeypatch.setattr(
        uv_bootstrap,
        "install_uv",
        lambda: installed.append(True) or Path("/managed/uv"),
    )
    assert uv_bootstrap.main(["install", "--non-interactive"]) == 0
    assert installed == [True]

    monkeypatch.setattr(
        uv_bootstrap,
        "check_uv",
        lambda: (_ for _ in ()).throw(uv_bootstrap.UvBootstrapError("missing")),
    )
    assert uv_bootstrap.main(["check"]) == 1
    assert "./setup.sh development" in capsys.readouterr().err


def _configure_mcp_environment(monkeypatch, tmp_path):
    from runner import mcp_environment

    project = tmp_path / "clients/lagniappe_mcp"
    environment = project / ".venv"
    python = environment / "bin/python"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[tool.uv]\nrequired-version = "==0.12.9"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_environment, "MCP_PROJECT", project)
    monkeypatch.setattr(mcp_environment, "MCP_ENVIRONMENT", environment)
    monkeypatch.setattr(mcp_environment, "MCP_ENVIRONMENT_PYTHON", python)
    monkeypatch.setattr(mcp_environment, "MCP_BASE_PYTHON", tmp_path / "python3.14")
    monkeypatch.setattr(
        mcp_environment,
        "MCP_BASE_PREFIX",
        Path("/managed/python-3.14"),
    )
    monkeypatch.setattr(
        mcp_environment,
        "UV_SYNC_ARGUMENTS",
        (
            "sync",
            "--project",
            "clients/lagniappe_mcp",
            "--locked",
            "--group",
            "test",
            "--python",
            str(tmp_path / "python3.14"),
            "--no-managed-python",
            "--no-python-downloads",
            "--no-config",
        ),
    )
    monkeypatch.setattr(mcp_environment, "GIT_CLI", tmp_path / "tools/git")
    monkeypatch.setattr(mcp_environment, "check_uv", lambda **_kwargs: Path("uv"))
    return mcp_environment, project, environment, python


def _mcp_environment_runner(
    project,
    environment,
    python,
    events,
    *,
    sync_code=0,
    adapter_origin=None,
):
    def run(command, **kwargs):
        events.append((command, kwargs))
        if command[0] == str(python) and "-c" in command:
            payload = {
                "prefix": str(environment),
                "base_prefix": "/managed/python-3.14",
                "version": [3, 14],
                "origins": {
                    "lagniappe_mcp": str(
                        adapter_origin
                        or project / "src/lagniappe_mcp/__init__.py"
                    ),
                    "mcp": str(
                        environment / "lib/python3.14/site-packages/mcp/__init__.py"
                    ),
                    "pytest": str(
                        environment / "lib/python3.14/site-packages/pytest/__init__.py"
                    ),
                    "uv_build": str(
                        environment
                        / "lib/python3.14/site-packages/uv_build/__init__.py"
                    ),
                },
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))
        if "sync" in command:
            return subprocess.CompletedProcess(command, sync_code)
        return subprocess.CompletedProcess(command, 0)

    return run


# @matrix mcp-package : bootstrap environment-sync fail-closed interpreter isolation locked-dependencies managed-path version-verification
# @matrix testing : environment-sync fail-closed interpreter isolation locked-dependencies
def test_mcp_environment_uses_managed_uv_lock_and_isolated_python(
    monkeypatch,
    tmp_path,
):
    hostile_uv = {
        "UV_CONFIG_FILE": "/tmp/hostile-uv.toml",
        "UV_DEFAULT_INDEX": "https://packages.invalid/simple",
        "UV_FIND_LINKS": "/tmp/untrusted-wheels",
        "UV_MANAGED_PYTHON": "1",
        "UV_PYTHON": "/tmp/untrusted-python",
        "UV_PYTHON_DOWNLOADS": "automatic",
    }
    for name, value in hostile_uv.items():
        monkeypatch.setenv(name, value)
    mcp_environment, project, environment, python = _configure_mcp_environment(
        monkeypatch,
        tmp_path,
    )
    events = []
    runner = _mcp_environment_runner(project, environment, python, events)

    assert mcp_environment.prepare_environment(run=runner) == python
    sync_command, sync_options = events[0]
    assert sync_command == [
        str(mcp_environment.UV_CLI),
        "sync",
        "--project",
        "clients/lagniappe_mcp",
        "--locked",
        "--group",
        "test",
        "--python",
        str(mcp_environment.MCP_BASE_PYTHON),
        "--no-managed-python",
        "--no-python-downloads",
        "--no-config",
    ]
    assert sync_options["cwd"] == REPOSITORY_ROOT
    assert sync_options["env"]["UV_PROJECT_ENVIRONMENT"] == str(environment)
    assert sync_options["env"]["UV_NO_BUILD"] == "1"
    assert sync_options["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert sync_options["env"][mcp_environment.RUNNER_GIT_ENV] == str(
        mcp_environment.GIT_CLI
    )
    assert {
        name for name in sync_options["env"] if name.startswith("UV_")
    } == {"UV_CACHE_DIR", "UV_NO_BUILD", "UV_PROJECT_ENVIRONMENT"}
    assert "VIRTUAL_ENV" not in sync_options["env"]
    assert "PYTHONPATH" not in sync_options["env"]
    assert events[1][0][:2] == [str(python), "-I"]


# @matrix hosted-e2e mcp-package testing : environment-check isolation
def test_mcp_environment_checks_prebuilt_environment_without_uv(
    monkeypatch,
    tmp_path,
):
    mcp_environment, project, environment, python = _configure_mcp_environment(
        monkeypatch,
        tmp_path,
    )
    events = []
    runner = _mcp_environment_runner(
        project,
        environment,
        python,
        events,
        adapter_origin=(
            environment / "lib/python3.14/site-packages/lagniappe_mcp/__init__.py"
        ),
    )

    with pytest.raises(
        mcp_environment.McpEnvironmentError,
        match="accepted only by the hosted E2E runner",
    ):
        mcp_environment.check_environment(run=runner)
    monkeypatch.setenv("LAGNIAPPE_HOSTED_E2E", "1")
    with pytest.raises(
        mcp_environment.McpEnvironmentError,
        match="accepted only by the hosted E2E runner",
    ):
        mcp_environment.check_environment(run=runner)
    monkeypatch.setenv("LAGNIAPPE_HOSTED_E2E", "true")
    assert mcp_environment.check_environment(run=runner) == python
    assert len(events) == 1
    assert events[0][0][:2] == [str(python), "-I"]


# @matrix mcp-package : bootstrap fail-closed managed-path repair-guidance
def test_mcp_environment_rejects_unmanaged_uv_with_repair_command(
    monkeypatch,
    tmp_path,
):
    from runner import mcp_environment

    monkeypatch.setattr(mcp_environment, "UV_CLI", tmp_path / "ambient-uv")
    with pytest.raises(
        mcp_environment.McpEnvironmentError,
        match=r"Run \./setup\.sh development",
    ):
        mcp_environment.verify_managed_uv()

    project = tmp_path / "stale-project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[tool.uv]\nrequired-version = "==0.12.8"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_environment, "MCP_PROJECT", project)
    monkeypatch.setattr(
        mcp_environment,
        "UV_CLI",
        mcp_environment.managed_uv_path(),
    )
    with pytest.raises(
        mcp_environment.McpEnvironmentError,
        match=r"required-version.*Run \./setup\.sh development",
    ):
        mcp_environment.verify_managed_uv()


# @matrix mcp-package testing : environment-sync fail-closed locked-dependencies repair-guidance
def test_mcp_environment_sync_failure_is_actionable(monkeypatch, tmp_path):
    mcp_environment, project, environment, python = _configure_mcp_environment(
        monkeypatch,
        tmp_path,
    )
    runner = _mcp_environment_runner(
        project,
        environment,
        python,
        [],
        sync_code=1,
    )
    with pytest.raises(
        mcp_environment.McpEnvironmentError,
        match=r"lock may be stale.*Run \./setup\.sh development",
    ):
        mcp_environment.sync_environment(run=runner)


# @matrix mcp-package : command-bridge dev-shim environment-sync isolation pytest-config
# @matrix testing : command-bridge environment-sync isolation pytest-config
def test_mcp_environment_builds_isolated_adapter_and_pytest_commands(
    monkeypatch,
    tmp_path,
):
    mcp_environment, project, environment, python = _configure_mcp_environment(
        monkeypatch,
        tmp_path,
    )
    events = []
    runner = _mcp_environment_runner(project, environment, python, events)

    assert mcp_environment.run_adapter(["serve", "--profile", "trial"], run=runner) == 0
    assert events[-1][0] == [
        str(python),
        "-I",
        "-m",
        "lagniappe_mcp",
        "serve",
        "--profile",
        "trial",
    ]

    events.clear()
    selector = "testing/tests_unit/test_033_mcp_adapter.py::test_catalog"
    assert mcp_environment.run_pytest([selector], run=runner) == 0
    assert events[-1][0] == [
        str(python),
        "-I",
        "-m",
        "pytest",
        "-c",
        "testing/pytest.ini",
        "--rootdir=.",
        "--noconftest",
        "-p",
        "anyio.pytest_plugin",
        selector,
    ]


# @matrix mcp-package testing : command-bridge isolation
# @matrix mcp-package testing traceability : result-aggregation test-evidence
def test_mcp_environment_builds_result_transport_command(monkeypatch, tmp_path):
    mcp_environment, project, environment, python = _configure_mcp_environment(
        monkeypatch,
        tmp_path,
    )
    events = []
    runner = _mcp_environment_runner(project, environment, python, events)
    result_path = tmp_path / "transport/results.json"
    selector = "testing/tests_unit/test_033_mcp_adapter.py::test_catalog"

    assert mcp_environment.run_pytest(
        [selector],
        prepared=True,
        result_path=result_path,
        run=runner,
    ) == 0

    command = events[-1][0]
    assert command[:3] == [str(python), "-I", "-c"]
    assert "traceability_results._write_manifest = capture_results" in command[3]
    assert command[4:6] == [str(REPOSITORY_ROOT), str(result_path)]
    assert command[-7:] == [
        "-c",
        "testing/pytest.ini",
        "--rootdir=.",
        "--noconftest",
        "-p",
        "anyio.pytest_plugin",
        selector,
    ]
