"""Clean-home installation contract for the public standalone MCP adapter."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import csv
from email.parser import Parser
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import pty
import re
import select
import shutil
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

import pytest


pytestmark = [pytest.mark.e2e, pytest.mark.mcp_package_install]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_MANIFEST_PATH = "/mcp/manifest.json"
PACKAGE_NAME = "lagniappe-mcp"
ENTRY_POINT = "lagniappe-mcp"
PLATFORM_ID = "linux-x86_64-cpython-3.14"
TOOL_VERSIONS = {"uv": "0.12.9", "pipx": "1.17.2", "codex": "0.153.0"}
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_WHEEL_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
EXACT_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[A-Za-z0-9_,.-]+\])?==(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)$"
)
SYNTHETIC_KEY = "lagniappe_013c_synthetic_key_value"
PROFILE_NAME = "personal"
SERVER_NAME = "lagniappe-personal"
FIXTURE_VERSIONS = {
    "predecessor": "0.0.1",
    "successor": "0.2.0",
    "incompatible": "0.0.0",
}
COLD_START_CATALOG_ATTEMPTS = 5
MAX_COLD_START_CATALOG_SECONDS = 1.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    assert isinstance(value, str) and value, f"missing package-job input {name}"
    return value


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _download(url: str, *, cap: int) -> tuple[bytes, Any]:
    request = Request(url, headers={"Accept": "application/json, */*;q=0.1"})
    try:
        with build_opener(_NoRedirect).open(request, timeout=60) as response:
            assert response.status == 200
            declared = response.headers.get("Content-Length")
            assert declared is not None and declared.isdigit()
            expected = int(declared)
            assert 0 < expected <= cap
            value = response.read(cap + 1)
            assert len(value) == expected
            return value, response.headers
    except HTTPError as error:
        raise AssertionError(f"artifact request returned HTTP {error.code}") from error


def _manifest_release(manifest: dict[str, Any]) -> dict[str, Any]:
    assert set(manifest) == {
        "schema",
        "package",
        "application",
        "current",
        "releases",
        "release_ledger_sha256",
    }
    assert manifest["schema"] == 1
    package = manifest["package"]
    assert package["name"] == PACKAGE_NAME
    assert package["entry_point"] == ENTRY_POINT
    current = manifest["current"]
    assert isinstance(current, dict) and current in manifest["releases"]
    assert VERSION_RE.fullmatch(current["version"])
    assert current["supported"] is True
    assert current["python_requirement"] == ">=3.14,<3.15"
    assert SHA256_RE.fullmatch(current["sha256"])
    assert isinstance(current["size"], int) and 0 < current["size"] <= MAX_WHEEL_BYTES
    expected_filename = f"lagniappe_mcp-{current['version']}-py3-none-any.whl"
    assert current["filename"] == expected_filename
    assert current["artifact_path"] == (
        f"/mcp/releases/{current['version']}/{current['sha256']}/{expected_filename}"
    )
    platforms = current["platforms"]
    assert isinstance(platforms, list) and len(platforms) == 1
    target = platforms[0]
    assert {
        name: target[name]
        for name in ("id", "system", "architecture", "libc", "python")
    } == {
        "id": PLATFORM_ID,
        "system": "linux",
        "architecture": "x86_64",
        "libc": "glibc>=2.17",
        "python": "3.14",
    }
    dependencies = target["dependencies"]
    assert isinstance(dependencies, list) and dependencies
    assert _sha256(_json_bytes(dependencies)) == target["dependency_graph_sha256"]
    for dependency in dependencies:
        assert set(dependency) == {
            "name",
            "version",
            "filename",
            "sha256",
            "size",
            "source_url",
        }
        assert SHA256_RE.fullmatch(dependency["sha256"])
        assert isinstance(dependency["size"], int) and dependency["size"] > 0
        assert urlsplit(dependency["source_url"]).scheme == "https"
        assert dependency["filename"].endswith(".whl")
    compatibility = current["compatibility"]
    assert compatibility["api_min"] == compatibility["api_max"] == "v1"
    assert compatibility["contract_min"] <= compatibility["contract_max"]
    return current


def _validate_wheel(wheel: bytes, release: dict[str, Any]) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)) <= 512
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            assert not path.is_absolute() and ".." not in path.parts
            assert stat.S_IFMT(info.external_attr >> 16) != stat.S_IFLNK
        prefix = f"lagniappe_mcp-{release['version']}.dist-info/"
        metadata_path = f"{prefix}METADATA"
        wheel_path = f"{prefix}WHEEL"
        entries_path = f"{prefix}entry_points.txt"
        record_path = f"{prefix}RECORD"
        assert {metadata_path, wheel_path, entries_path, record_path} <= set(names)
        metadata = Parser().parsestr(archive.read(metadata_path).decode("utf-8"))
        assert metadata["Name"] == PACKAGE_NAME
        assert metadata["Version"] == release["version"]
        assert metadata["Requires-Python"] == release["python_requirement"]
        requirements = metadata.get_all("Requires-Dist") or []
        assert requirements == release["runtime_requirements"]
        assert "Tag: py3-none-any" in archive.read(wheel_path).decode("utf-8")
        assert "lagniappe-mcp = lagniappe_mcp.cli:main" in archive.read(
            entries_path
        ).decode("utf-8")
        records = list(
            csv.reader(io.StringIO(archive.read(record_path).decode("utf-8")))
        )
        assert len(records) == len(names)
        indexed = {row[0]: row[1:] for row in records}
        assert set(indexed) == set(names)
        for name in names:
            digest, size = indexed[name]
            if name == record_path:
                assert digest == size == ""
                continue
            value = archive.read(name)
            encoded = (
                base64.urlsafe_b64encode(hashlib.sha256(value).digest())
                .decode("ascii")
                .rstrip("=")
            )
            assert digest == f"sha256={encoded}"
            assert size == str(len(value))
    return requirements


def _fixture_wheel(
    wheel: bytes,
    *,
    old_version: str,
    new_version: str,
    contract_version: int,
    incompatible: bool,
) -> bytes:
    old_prefix = f"lagniappe_mcp-{old_version}.dist-info/"
    new_prefix = f"lagniappe_mcp-{new_version}.dist-info/"
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(wheel)) as source:
        for info in source.infolist():
            if info.is_dir() or info.filename.endswith("/RECORD"):
                continue
            name = info.filename
            if name.startswith(old_prefix):
                name = new_prefix + name.removeprefix(old_prefix)
            value = source.read(info.filename)
            if name == f"{new_prefix}METADATA":
                text = value.decode("utf-8")
                marker = f"\nVersion: {old_version}\n"
                assert text.count(marker) == 1
                value = text.replace(marker, f"\nVersion: {new_version}\n", 1).encode(
                    "utf-8"
                )
            if incompatible and name == "lagniappe_mcp/limits.py":
                marker = f"CONTRACT_VERSION_MAX = {contract_version}".encode()
                assert value.count(marker) == 1
                value = value.replace(
                    marker,
                    f"CONTRACT_VERSION_MAX = {contract_version + 1}".encode(),
                    1,
                )
            entries[name] = value

    record_path = f"{new_prefix}RECORD"
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name in sorted(entries):
        value = entries[name]
        encoded = (
            base64.urlsafe_b64encode(hashlib.sha256(value).digest())
            .decode("ascii")
            .rstrip("=")
        )
        writer.writerow((name, f"sha256={encoded}", len(value)))
    writer.writerow((record_path, "", ""))
    entries[record_path] = record.getvalue().encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as destination:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            destination.writestr(info, entries[name])
    return output.getvalue()


def _fixture_release(
    public: dict[str, Any],
    *,
    name: str,
    wheel: bytes,
    contract_version: int,
) -> dict[str, Any]:
    value = json.loads(json.dumps(public))
    version = FIXTURE_VERSIONS[name]
    digest = _sha256(wheel)
    filename = f"lagniappe_mcp-{version}-py3-none-any.whl"
    value.update(
        {
            "version": version,
            "sha256": digest,
            "size": len(wheel),
            "filename": filename,
            "artifact_path": f"/fixtures/releases/{version}/{digest}/{filename}",
            "source_sha256": digest,
        }
    )
    if name == "incompatible":
        value["compatibility"]["contract_min"] = contract_version + 1
        value["compatibility"]["contract_max"] = contract_version + 1
    return value


def _openapi(contract_version: int) -> dict[str, Any]:
    methods = {
        "/api/v1": "get",
        "/api/v1/client-skill.md": "get",
        "/api/v1/me": "get",
        "/api/v1/tools": "get",
        "/api/v1/plans": "post",
        "/api/v1/plans/{plan_id}": "get",
        "/api/v1/plans/{plan_id}/contract": "get",
        "/api/v1/plans/{plan_id}/submit": "post",
        "/api/v1/plans/{plan_id}/uploads": "post",
        "/api/v1/plans/{plan_id}/uploads/finalize": "post",
        "/api/v1/plans/{plan_id}/tools/{tool_name}": "post",
    }
    batch_schema = {"type": "string"}
    constant = {"properties": {"contract_version": {"const": contract_version}}}
    plan = {
        "required": ["upload_batch_id"],
        "properties": {
            "contract_version": {"const": contract_version},
            "upload_batch_id": {
                "oneOf": [batch_schema, {"type": "null"}],
            },
        },
    }
    paths = {path: {method: {}} for path, method in methods.items()}
    paths["/api/v1/plans/{plan_id}/uploads"]["post"] = {
        "responses": {
            "201": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "plan_id",
                                "upload_batch_id",
                                "uploads",
                            ],
                            "properties": {
                                "plan_id": {"type": "string"},
                                "upload_batch_id": batch_schema,
                                "uploads": {"type": "array"},
                            },
                        }
                    }
                }
            }
        }
    }
    paths["/api/v1/plans/{plan_id}/uploads/finalize"]["post"] = {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["upload_batch_id"],
                        "properties": {"upload_batch_id": batch_schema},
                    }
                }
            },
        }
    }
    return {
        "openapi": "3.1.0",
        "paths": paths,
        "components": {
            "schemas": {
                "Plan": plan,
                "PlanContract": constant,
                "PlanSubmissionFormat": {
                    "properties": {
                        "contract_version": {"const": contract_version},
                        "body": {
                            "properties": {
                                "contract_version": {"const": contract_version}
                            }
                        },
                    }
                },
                "SubmissionReceipt": constant,
                "UploadFile": {
                    "type": "object",
                    "required": ["filename", "size"],
                    "properties": {
                        "filename": {"type": "string"},
                        "content_type": {"type": "string"},
                        "size": {"type": "integer"},
                    },
                    "additionalProperties": False,
                },
            }
        },
    }


def _catalog() -> dict[str, Any]:
    return {
        "tools": [],
        "view": "full",
        "selected_count": 0,
        "reference_format": "hash:<12-character-hash>",
        "execution_envelope": {
            "success": {"result": "<value matching the selected output_schema>"},
            "failure": {
                "error": {"code": "tool_error", "message": "<message>"},
                "request_id": "<request id>",
            },
        },
    }


@contextmanager
def _fake_site(
    fixture_manifest: dict[str, Any], fixture_wheels: dict[str, bytes], contract: int
) -> Iterator[tuple[str, list[dict[str, str]]]]:
    requests: list[dict[str, str]] = []
    lock = threading.Lock()
    state: dict[str, str] = {"origin": ""}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", "mcp-package-fixture")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _handle(self) -> None:
            path = urlsplit(self.path).path
            with lock:
                requests.append(
                    {
                        "method": self.command,
                        "path": path,
                        "authorization": self.headers.get("Authorization", ""),
                        "cookie": self.headers.get("Cookie", ""),
                    }
                )
            if path == "/fixtures/manifest.json":
                self._send(200, _json_bytes(fixture_manifest), "application/json")
                return
            if path in fixture_wheels:
                self._send(200, fixture_wheels[path], "application/octet-stream")
                return
            api_payloads = {
                "/api/v1": {
                    "version": "v1",
                    "base_url": f"{state['origin']}/api/v1",
                    "openapi_url": f"{state['origin']}/api/v1/openapi.json",
                    "actor_url": f"{state['origin']}/api/v1/me",
                    "tools_url": f"{state['origin']}/api/v1/tools",
                    "plans_url": f"{state['origin']}/api/v1/plans",
                    "client_skill_url": f"{state['origin']}/api/v1/client-skill.md",
                },
                "/api/v1/me": {
                    "user": {
                        "name": "Package Fixture Actor",
                        "hash": "actor013c001",
                        "timezone": "UTC",
                        "personal_page": {
                            "kind": "page",
                            "hash": "page013c0001",
                            "name": "Package Fixture Actor",
                            "url": f"{state['origin']}/pages/page013c0001",
                            "can_view": True,
                            "can_edit": True,
                        },
                    },
                    "credential": {
                        "active": True,
                        "display_prefix": "lagniappe_013c",
                        "issued_at": "2026-01-01T00:00:00+00:00",
                        "expires_at": "2099-01-01T00:00:00+00:00",
                        "generation": 1,
                    },
                    "capabilities": {"ask": True, "create": True, "organize": True},
                },
                "/api/v1/tools": _catalog(),
                "/api/v1/openapi.json": _openapi(contract),
            }
            if path not in api_payloads:
                self._send(404, _json_bytes({"error": "not found"}), "application/json")
                return
            if self.headers.get("Authorization") != f"Bearer {SYNTHETIC_KEY}":
                self._send(
                    401,
                    _json_bytes(
                        {"error": {"code": "invalid_key", "message": "invalid key"}}
                    ),
                    "application/json",
                )
                return
            self._send(200, _json_bytes(api_payloads[path]), "application/json")

        do_GET = _handle
        do_HEAD = _handle

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    host, port = server.server_address
    state["origin"] = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state["origin"], requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _clean_environment(root: Path) -> dict[str, str]:
    home = root / "home"
    temporary = root / "tmp"
    for directory in (root, home, temporary):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    values = {
        "HOME": str(home),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "SHELL": "/bin/bash",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(temporary),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "CODEX_HOME": str(home / ".codex"),
        "LAGNIAPPE_MCP_CONFIG_HOME": str(home / ".config/lagniappe-mcp"),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PIPX_HOME": str(home / ".local/pipx"),
        "PIPX_BIN_DIR": str(home / ".local/bin-pipx"),
        "PIPX_MAN_DIR": str(home / ".local/share/man-pipx"),
        "SHIV_ROOT": str(home / ".local/share/shiv"),
        "PYTHONNOUSERSITE": "1",
        "UV_CACHE_DIR": str(home / ".cache/uv"),
        "UV_NO_CONFIG": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_TOOL_BIN_DIR": str(home / ".local/bin-uv"),
        "UV_TOOL_DIR": str(home / ".local/share/uv/tools"),
        "NO_PROXY": "127.0.0.1,localhost",
    }
    assert "PYTHONPATH" not in values and "VIRTUAL_ENV" not in values
    assert not any("API_KEY" in name or "TOKEN" in name for name in values)
    return values


def _run(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    expected: int = 0,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert SYNTHETIC_KEY not in combined
    assert result.returncode == expected, (
        f"command returned {result.returncode}, expected {expected}: {command!r}\n"
        f"{combined[-6000:]}"
    )
    return result


def _pty_run(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    interactions: tuple[tuple[bytes, bytes], ...],
    timeout: int = 120,
) -> str:
    master, slave = pty.openpty()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    output = bytearray()
    interaction_index = 0
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None or interaction_index < len(interactions):
            if time.monotonic() >= deadline:
                process.kill()
                raise AssertionError(f"interactive command timed out: {command!r}")
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master, 64 * 1024)
                except OSError:
                    chunk = b""
                output.extend(chunk)
                assert len(output) <= 2 * 1024 * 1024
            if interaction_index < len(interactions):
                prompt, response = interactions[interaction_index]
                if prompt in output:
                    os.write(master, response)
                    interaction_index += 1
            if process.poll() is not None and not readable:
                break
        while True:
            readable, _, _ = select.select([master], [], [], 0.05)
            if not readable:
                break
            try:
                chunk = os.read(master, 64 * 1024)
            except OSError:
                break
            if not chunk:
                break
            output.extend(chunk)
    finally:
        os.close(master)
    returncode = process.wait(timeout=10)
    text = output.decode("utf-8", errors="replace")
    assert interaction_index == len(interactions), text[-4000:]
    assert SYNTHETIC_KEY not in text
    assert returncode == 0, text[-6000:]
    return text


def _tool_python(executable: Path) -> Path:
    resolved = executable.resolve(strict=True)
    python = resolved.parent / "python"
    assert python.is_file()
    return python


def _installed_environment(
    executable: Path,
    *,
    expected_version: str,
    dependency_graph: list[dict[str, Any]],
    environment: dict[str, str],
    cwd: Path,
) -> dict[str, Any]:
    probe = r"""
import importlib.metadata
import importlib.util
import json
import sys

rows = [
    {"name": item.metadata.get("Name"), "version": item.version}
    for item in importlib.metadata.distributions()
]
spec = importlib.util.find_spec("lagniappe_mcp")
print(json.dumps({
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "version": list(sys.version_info[:2]),
    "origin": None if spec is None else spec.origin,
    "packages": rows,
}, sort_keys=True))
"""
    python = _tool_python(executable)
    result = _run(
        [str(python), "-I", "-c", probe],
        environment=environment,
        cwd=cwd,
    )
    payload = json.loads(result.stdout)
    prefix = Path(payload["prefix"]).resolve()
    assert payload["version"] == [3, 14]
    assert prefix != Path(payload["base_prefix"]).resolve()
    origin = Path(payload["origin"]).resolve()
    assert origin.is_relative_to(prefix)
    assert not origin.is_relative_to(REPOSITORY_ROOT)
    packages: dict[str, str] = {}
    for row in payload["packages"]:
        name = row["name"]
        if not isinstance(name, str):
            continue
        canonical = _canonical_name(name)
        assert canonical not in packages
        packages[canonical] = row["version"]
    expected = {
        _canonical_name(item["name"]): item["version"] for item in dependency_graph
    }
    assert packages[PACKAGE_NAME] == expected_version
    for name, version in expected.items():
        assert packages[name] == version
    assert set(packages) - {PACKAGE_NAME, "pip", "setuptools", "wheel"} == set(expected)
    payload["package_versions"] = packages
    return payload


def _uv_install(
    uv: str,
    wheel_url: str,
    *,
    environment: dict[str, str],
    cwd: Path,
    force: bool = False,
) -> Path:
    command = [
        uv,
        "tool",
        "install",
        "--python",
        "/usr/local/bin/python3.14",
        "--no-managed-python",
        "--no-python-downloads",
        "--no-build",
        "--no-sources",
        "--no-cache",
        "--no-config",
        "--no-progress",
    ]
    if urlsplit(wheel_url).scheme == "http":
        command.extend(["--allow-insecure-host", "127.0.0.1"])
    if force:
        command.extend(["--force", "--reinstall"])
    command.append(wheel_url)
    _run(command, environment=environment, cwd=cwd)
    executable = Path(environment["UV_TOOL_BIN_DIR"]) / ENTRY_POINT
    assert executable.is_file()
    return executable


def _pipx_install_command(
    pipx: str,
    wheel_url: str,
    *,
    force: bool = False,
    upgrade: bool = False,
    report_path: Path | None = None,
) -> list[str]:
    assert not (force and upgrade)
    pip_arguments = "--only-binary=:all: --no-cache-dir"
    if report_path is not None:
        assert report_path.is_absolute() and not report_path.exists()
        pip_arguments += f" --report={report_path}"
    if urlsplit(wheel_url).scheme == "http":
        pip_arguments += " --trusted-host 127.0.0.1"
    command = [
        pipx,
        "install",
        "--skip-maintenance",
        "--python",
        "/usr/local/bin/python3.14",
        "--fetch-python=never",
        "--backend=pip",
        "--cooldown=0",
        f"--app={ENTRY_POINT}",
        f"--pip-args={pip_arguments}",
    ]
    if force:
        command.append("--force")
    if upgrade:
        command.append("--upgrade")
    command.append(wheel_url)
    return command


def _pipx_install(
    pipx: str,
    wheel_url: str,
    *,
    environment: dict[str, str],
    cwd: Path,
    force: bool = False,
    upgrade: bool = False,
    report_path: Path | None = None,
) -> Path:
    command = _pipx_install_command(
        pipx,
        wheel_url,
        force=force,
        upgrade=upgrade,
        report_path=report_path,
    )
    _run(command, environment=environment, cwd=cwd)
    if report_path is not None:
        assert report_path.is_file() and report_path.stat().st_size <= 2 * 1024 * 1024
    executable = Path(environment["PIPX_BIN_DIR"]) / ENTRY_POINT
    assert executable.is_file()
    return executable


def _validate_pip_report(
    report_path: Path,
    *,
    release: dict[str, Any],
    artifact_url: str,
    dependency_graph: list[dict[str, Any]],
) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["version"] == "1"
    installed = report["install"]
    assert isinstance(installed, list)
    by_name = {_canonical_name(item["metadata"]["name"]): item for item in installed}
    assert len(by_name) == len(installed)
    expected = {
        PACKAGE_NAME: {
            "version": release["version"],
            "filename": release["filename"],
            "sha256": release["sha256"],
            "source_url": artifact_url,
        },
        **{
            _canonical_name(item["name"]): {
                "version": item["version"],
                "filename": item["filename"],
                "sha256": item["sha256"],
                "source_url": item["source_url"],
            }
            for item in dependency_graph
        },
    }
    assert set(by_name) == set(expected)
    for name, wanted in expected.items():
        item = by_name[name]
        assert item["metadata"]["version"] == wanted["version"]
        download = item["download_info"]
        parsed = urlsplit(download["url"])
        assert unquote(PurePosixPath(parsed.path).name) == wanted["filename"]
        assert download["archive_info"]["hashes"]["sha256"] == wanted["sha256"]
        assert parsed.scheme == "https"
        assert not parsed.username and not parsed.password
        assert parsed._replace(fragment="").geturl() == wanted["source_url"]


def _check_adapter(
    executable: Path,
    *,
    environment: dict[str, str],
    cwd: Path,
    origin: str,
    allowed_root: Path,
    expected: int = 0,
) -> subprocess.CompletedProcess[str]:
    child = dict(environment)
    child.update({"LAGNIAPPE_URL": origin, "LAGNIAPPE_API_KEY": SYNTHETIC_KEY})
    result = _run(
        [
            str(executable),
            "check",
            "--from-env",
            "--allowed-root",
            str(allowed_root),
        ],
        environment=child,
        cwd=cwd,
        expected=expected,
    )
    if expected == 0:
        assert "compatible; actor=verified" in result.stdout
    return result


SDK_DRIVER = r"""
import asyncio
import io
import json
from pathlib import Path
import sys
import tempfile
import time

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


def dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


async def main():
    specification = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    diagnostics = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    started = time.perf_counter()
    transport = stdio_client(
        StdioServerParameters(
            command=specification["command"],
            args=specification["args"],
            env=specification["environment"],
        ),
        errlog=diagnostics,
    )
    try:
        async with Client(transport, mode="auto", cache=None) as client:
            tools = dump(await client.list_tools())["tools"]
            catalog_seconds = time.perf_counter() - started
            actor = dump(await client.call_tool("get_actor", {}))
            protocol_version = client.protocol_version
            server_info = dump(client.server_info)
        diagnostics.flush()
        diagnostics.seek(0)
        diagnostic_text = diagnostics.read()
    finally:
        diagnostics.close()
    result = {
        "prefix": sys.prefix,
        "protocol_version": protocol_version,
        "server_info": server_info,
        "tools": tools,
        "catalog_seconds": catalog_seconds,
        "actor": actor,
        "diagnostics": diagnostic_text,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


asyncio.run(main())
"""


def _sdk_call(
    executable: Path,
    *,
    registration: dict[str, Any],
    environment: dict[str, str],
    cwd: Path,
) -> dict[str, Any]:
    driver = cwd / "mcp_sdk_driver.py"
    specification_path = cwd / "mcp_sdk_specification.json"
    driver.write_text(SDK_DRIVER, encoding="utf-8")
    transport = registration["transport"]
    assert transport["type"] == "stdio"
    assert transport.get("env") is None
    assert transport.get("env_vars") == []
    assert transport.get("cwd") is None
    specification = {
        "command": transport["command"],
        "args": transport["args"],
        "environment": {
            name: environment[name]
            for name in (
                "HOME",
                "PATH",
                "CODEX_HOME",
                "LAGNIAPPE_MCP_CONFIG_HOME",
                "PYTHONNOUSERSITE",
                "XDG_CACHE_HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_STATE_HOME",
            )
        },
    }
    specification_path.write_text(
        json.dumps(specification, sort_keys=True), encoding="utf-8"
    )
    result = _run(
        [str(_tool_python(executable)), "-I", str(driver), str(specification_path)],
        environment=environment,
        cwd=cwd,
    )
    assert SYNTHETIC_KEY not in specification_path.read_text(encoding="utf-8")
    value = json.loads(result.stdout)
    assert SYNTHETIC_KEY not in value["diagnostics"]
    assert len(value["diagnostics"].encode("utf-8")) <= 8 * 1024
    return value


def _is_compatible(release: dict[str, Any], *, api: str, contract: int) -> bool:
    compatibility = release["compatibility"]
    return (
        compatibility["api_min"] <= api <= compatibility["api_max"]
        and compatibility["contract_min"] <= contract <= compatibility["contract_max"]
    )


# @matrix hosted-e2e mcp-package release : clean-home client-registration dependency-graph downgrade immutable-release installer-pin platform-pin public-artifact
def test_public_mcp_wheel_clean_home_installation_contract(
    tmp_path: Path, record_property: Any
) -> None:
    assert sys.version_info[:2] == (3, 14)
    assert platform.system() == "Linux"
    assert platform.machine() in {"x86_64", "AMD64"}
    assert platform.libc_ver()[0].casefold() in {"glibc", "libc"}
    work = tmp_path / "outside-checkout"
    work.mkdir(mode=0o700)
    assert not work.resolve().is_relative_to(REPOSITORY_ROOT)

    base_url = _required_environment("LAGNIAPPE_HOSTED_E2E_BASE_URL")
    build_id = _required_environment("LAGNIAPPE_HOSTED_E2E_BUILD_ID")
    parsed_base = urlsplit(base_url)
    assert parsed_base.scheme == "https" and parsed_base.path == ""
    assert (
        not parsed_base.query and not parsed_base.fragment and not parsed_base.username
    )
    manifest_url = f"{base_url}{PUBLIC_MANIFEST_PATH}"
    manifest_bytes, manifest_headers = _download(manifest_url, cap=MAX_MANIFEST_BYTES)
    assert _sha256(manifest_bytes) == _required_environment(
        "LAGNIAPPE_MCP_MANIFEST_SHA256"
    )
    assert manifest_headers.get("X-Lagniappe-Build-ID") == build_id
    manifest = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
    release = _manifest_release(manifest)
    assert manifest["application"]["build_id"] == build_id
    assert manifest["release_ledger_sha256"] == _required_environment(
        "LAGNIAPPE_MCP_LEDGER_SHA256"
    )
    assert release["sha256"] == _required_environment("LAGNIAPPE_MCP_WHEEL_SHA256")
    target = release["platforms"][0]
    assert target["id"] == _required_environment("LAGNIAPPE_MCP_PLATFORM")
    assert target["dependency_graph_sha256"] == _required_environment(
        "LAGNIAPPE_MCP_DEPENDENCY_GRAPH_SHA256"
    )

    artifact_url = urljoin(base_url, release["artifact_path"])
    parsed_artifact = urlsplit(artifact_url)
    assert parsed_artifact.scheme == "https"
    assert parsed_artifact.netloc == parsed_base.netloc
    assert parsed_artifact.path == release["artifact_path"]
    assert not parsed_artifact.query and not parsed_artifact.fragment
    wheel, wheel_headers = _download(artifact_url, cap=MAX_WHEEL_BYTES)
    assert wheel_headers.get_content_type() == "application/octet-stream"
    assert len(wheel) == release["size"]
    assert _sha256(wheel) == release["sha256"]
    requirements = _validate_wheel(wheel, release)
    resolved_requirements = {}
    for requirement in requirements:
        match = EXACT_REQUIREMENT_RE.fullmatch(requirement)
        assert match is not None
        resolved_requirements[_canonical_name(match["name"])] = match["version"]
    graph = target["dependencies"]
    assert resolved_requirements == {
        _canonical_name(item["name"]): item["version"] for item in graph
    }

    ledger_path = REPOSITORY_ROOT / "clients/lagniappe_mcp/releases/releases.json"
    ledger_bytes = ledger_path.read_bytes()
    assert _sha256(ledger_bytes) == manifest["release_ledger_sha256"]
    ledger = json.loads(ledger_bytes, object_pairs_hook=_unique_object)
    assert ledger["current"] == release["version"]

    contract = release["compatibility"]["contract_max"]
    fixture_wheel_bytes = {
        name: _fixture_wheel(
            wheel,
            old_version=release["version"],
            new_version=version,
            contract_version=contract,
            incompatible=name == "incompatible",
        )
        for name, version in FIXTURE_VERSIONS.items()
    }
    fixture_releases = {
        name: _fixture_release(
            release,
            name=name,
            wheel=fixture_wheel_bytes[name],
            contract_version=contract,
        )
        for name in FIXTURE_VERSIONS
    }
    fixture_manifest = {
        "schema": 1,
        "package": manifest["package"],
        "application": manifest["application"],
        "current": fixture_releases["successor"],
        "releases": list(fixture_releases.values()),
        "release_ledger_sha256": "f" * 64,
    }
    fixture_routes = {
        value["artifact_path"]: fixture_wheel_bytes[name]
        for name, value in fixture_releases.items()
    }
    public_versions = {item["version"] for item in manifest["releases"]}
    public_digests = {item["sha256"] for item in manifest["releases"]}
    ledger_versions = {item["version"] for item in ledger["releases"]}
    ledger_digests = {item["sha256"] for item in ledger["releases"]}
    assert not (set(FIXTURE_VERSIONS.values()) & (public_versions | ledger_versions))
    assert not (
        {_sha256(value) for value in fixture_wheel_bytes.values()}
        & (public_digests | ledger_digests)
    )

    uv_environment = _clean_environment(tmp_path / "uv-public")
    pipx_environment = _clean_environment(tmp_path / "pipx-public")
    checksum_environment = _clean_environment(tmp_path / "pipx-checksum-failure")
    fixture_environment = _clean_environment(tmp_path / "pipx-fixtures")
    uv = shutil.which("uv", path=uv_environment["PATH"])
    pipx = shutil.which("pipx", path=pipx_environment["PATH"])
    codex = shutil.which("codex", path=uv_environment["PATH"])
    python = shutil.which("python3.14", path=uv_environment["PATH"])
    assert uv == "/usr/local/bin/uv"
    assert pipx == "/usr/local/bin/pipx"
    assert codex == "/usr/local/bin/codex"
    assert python == "/usr/local/bin/python3.14"
    tool_outputs = {
        "uv": _run(
            [uv, "--version"], environment=uv_environment, cwd=work
        ).stdout.strip(),
        "pipx": _run(
            [pipx, "--version"], environment=pipx_environment, cwd=work
        ).stdout.strip(),
        "codex": _run(
            [codex, "--version"], environment=uv_environment, cwd=work
        ).stdout.strip(),
    }
    assert tool_outputs == {
        "uv": "uv 0.12.9 (x86_64-unknown-linux-gnu)",
        "pipx": "1.17.2",
        "codex": "codex-cli 0.153.0",
    }
    for name, expected in TOOL_VERSIONS.items():
        assert (
            _required_environment(f"LAGNIAPPE_MCP_{name.upper()}_VERSION") == expected
        )

    install_url = f"{artifact_url}#sha256={release['sha256']}"
    with _fake_site(fixture_manifest, fixture_routes, contract) as (
        fixture_origin,
        requests,
    ):
        allowed_root = work / "allowed-files"
        allowed_root.mkdir(mode=0o700)

        uv_executable = _uv_install(
            uv, install_url, environment=uv_environment, cwd=work
        )
        uv_probe = _installed_environment(
            uv_executable,
            expected_version=release["version"],
            dependency_graph=graph,
            environment=uv_environment,
            cwd=work,
        )
        _check_adapter(
            uv_executable,
            environment=uv_environment,
            cwd=work,
            origin=fixture_origin,
            allowed_root=allowed_root,
        )
        _run(
            [uv, "tool", "update-shell", "--no-config"],
            environment=uv_environment,
            cwd=work,
        )
        uv_executable = _uv_install(
            uv,
            install_url,
            environment=uv_environment,
            cwd=work,
            force=True,
        )
        _installed_environment(
            uv_executable,
            expected_version=release["version"],
            dependency_graph=graph,
            environment=uv_environment,
            cwd=work,
        )
        _run(
            [uv, "tool", "uninstall", PACKAGE_NAME, "--no-config"],
            environment=uv_environment,
            cwd=work,
        )
        assert not uv_executable.exists()

        bad_install_url = f"{artifact_url}#sha256={'0' * 64}"
        checksum_failure = _run(
            _pipx_install_command(pipx, bad_install_url),
            environment=checksum_environment,
            cwd=work,
            expected=1,
        )
        checksum_output = (checksum_failure.stdout + checksum_failure.stderr).casefold()
        assert "hash" in checksum_output
        assert "0" * 64 in checksum_output
        assert not (Path(checksum_environment["PIPX_BIN_DIR"]) / ENTRY_POINT).exists()
        assert not (
            Path(checksum_environment["PIPX_HOME"]) / "venvs" / PACKAGE_NAME
        ).exists()

        pip_report = work / "pipx-public-install-report.json"
        pipx_executable = _pipx_install(
            pipx,
            install_url,
            environment=pipx_environment,
            cwd=work,
            report_path=pip_report,
        )
        _validate_pip_report(
            pip_report,
            release=release,
            artifact_url=artifact_url,
            dependency_graph=graph,
        )
        pipx_probe = _installed_environment(
            pipx_executable,
            expected_version=release["version"],
            dependency_graph=graph,
            environment=pipx_environment,
            cwd=work,
        )
        _check_adapter(
            pipx_executable,
            environment=pipx_environment,
            cwd=work,
            origin=fixture_origin,
            allowed_root=allowed_root,
        )
        ensurepath = _run(
            [pipx, "ensurepath", "--dry-run"],
            environment=pipx_environment,
            cwd=work,
        )
        assert pipx_environment["PIPX_BIN_DIR"] in (
            ensurepath.stdout + ensurepath.stderr
        )
        _run(
            [pipx, "ensurepath"],
            environment=pipx_environment,
            cwd=work,
        )
        assert pipx_environment["PIPX_BIN_DIR"] in (
            Path(pipx_environment["HOME"]) / ".bashrc"
        ).read_text(encoding="utf-8")
        pipx_executable = _pipx_install(
            pipx,
            install_url,
            environment=pipx_environment,
            cwd=work,
            force=True,
        )
        _installed_environment(
            pipx_executable,
            expected_version=release["version"],
            dependency_graph=graph,
            environment=pipx_environment,
            cwd=work,
        )

        configure_environment = dict(pipx_environment)
        configure_environment["TERM"] = "dumb"
        codex_home = Path(pipx_environment["CODEX_HOME"])
        codex_home.mkdir(parents=True, mode=0o755)
        codex_home.chmod(0o755)
        codex_config = codex_home / "config.toml"
        unrelated_codex_config = (
            'model = "gpt-5.3-codex"\n\n'
            '[projects."/tmp/unrelated-project"]\n'
            'trust_level = "trusted"\n'
        )
        codex_config.write_text(unrelated_codex_config, encoding="utf-8")
        codex_config.chmod(0o600)
        _pty_run(
            [
                str(pipx_executable),
                "configure",
                "codex",
                "--url",
                fixture_origin,
                "--profile",
                PROFILE_NAME,
                "--allowed-root",
                str(allowed_root),
            ],
            environment=configure_environment,
            cwd=work,
            interactions=(
                (b"Lagniappe API key:", SYNTHETIC_KEY.encode() + b"\n"),
                (b"[y/N]", b"y\n"),
            ),
        )
        profile_path = (
            Path(pipx_environment["LAGNIAPPE_MCP_CONFIG_HOME"])
            / "profiles/personal.json"
        )
        codex_backup = codex_config.with_name(f"{codex_config.name}.lagniappe-mcp.bak")
        assert stat.S_IMODE(profile_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(codex_home.stat().st_mode) == 0o755
        assert stat.S_IMODE(codex_config.stat().st_mode) == 0o600
        assert stat.S_IMODE(codex_backup.stat().st_mode) == 0o600
        assert codex_backup.read_text(encoding="utf-8") == unrelated_codex_config
        profile_value = json.loads(profile_path.read_text(encoding="utf-8"))
        assert profile_value["api_key"] == SYNTHETIC_KEY
        assert profile_value["client"]["registered"] is True
        codex_text = codex_config.read_text(encoding="utf-8")
        assert SYNTHETIC_KEY not in codex_text
        assert unrelated_codex_config in codex_text
        assert f"# BEGIN lagniappe-mcp {SERVER_NAME}" in codex_text
        assert "required = false" in codex_text
        assert 'default_tools_approval_mode = "writes"' in codex_text

        profile_check = _run(
            [str(pipx_executable), "check", "--profile", PROFILE_NAME],
            environment=pipx_environment,
            cwd=work,
        )
        assert "compatible; actor=verified" in profile_check.stdout

        list_result = _run(
            [codex, "mcp", "list", "--json"],
            environment=pipx_environment,
            cwd=work,
        )
        listed = json.loads(list_result.stdout)
        assert [item["name"] for item in listed] == [SERVER_NAME]
        get_result = _run(
            [codex, "mcp", "get", SERVER_NAME, "--json"],
            environment=pipx_environment,
            cwd=work,
        )
        registered = json.loads(get_result.stdout)
        assert registered["name"] == SERVER_NAME
        assert registered["transport"]["type"] == "stdio"
        assert Path(registered["transport"]["command"]).is_absolute()
        assert registered["transport"]["command"] == str(pipx_executable.resolve())
        assert registered["transport"]["args"] == [
            "serve",
            "--profile",
            PROFILE_NAME,
        ]
        get_text = _run(
            [codex, "mcp", "get", SERVER_NAME],
            environment=pipx_environment,
            cwd=work,
        ).stdout
        assert "default_tools_approval_mode: writes" in get_text
        assert "startup_timeout_sec: 30" in get_text
        assert "tool_timeout_sec: 300" in get_text

        sdk_results = [
            _sdk_call(
                pipx_executable,
                registration=registered,
                environment=pipx_environment,
                cwd=work,
            )
            for _attempt in range(COLD_START_CATALOG_ATTEMPTS)
        ]
        assert max(
            result["catalog_seconds"] for result in sdk_results
        ) <= MAX_COLD_START_CATALOG_SECONDS
        assert all(
            result["tools"] == sdk_results[0]["tools"] for result in sdk_results[1:]
        )
        sdk_result = sdk_results[0]
        assert (
            Path(sdk_result["prefix"]).resolve() == Path(pipx_probe["prefix"]).resolve()
        )
        assert sdk_result["protocol_version"] == "2026-07-28"
        assert sdk_result["server_info"]["name"] == "lagniappe"
        tool_names = {item["name"] for item in sdk_result["tools"]}
        assert {
            "get_actor",
            "start_ask",
            "start_create",
            "start_organize",
        } <= tool_names
        actor_result = sdk_result["actor"]
        assert actor_result["isError"] is False
        assert actor_result["structuredContent"]["user"]["hash"] == "actor013c001"

        blocked_remove = _run(
            [str(pipx_executable), "profile", "remove", "--profile", PROFILE_NAME],
            environment=pipx_environment,
            cwd=work,
            expected=1,
        )
        assert "client_still_registered" in blocked_remove.stderr
        _pty_run(
            [
                str(pipx_executable),
                "configure",
                "codex",
                "--remove",
                "--profile",
                PROFILE_NAME,
            ],
            environment=configure_environment,
            cwd=work,
            interactions=((b"[y/N]", b"y\n"),),
        )
        assert (
            json.loads(
                _run(
                    [codex, "mcp", "list", "--json"],
                    environment=pipx_environment,
                    cwd=work,
                ).stdout
            )
            == []
        )
        profile_value = json.loads(profile_path.read_text(encoding="utf-8"))
        assert profile_value["client"]["registered"] is False
        assert profile_value["api_key"] == SYNTHETIC_KEY

        _pty_run(
            [
                str(pipx_executable),
                "credentials",
                "remove",
                "--profile",
                PROFILE_NAME,
            ],
            environment=configure_environment,
            cwd=work,
            interactions=((b"[y/N]", b"y\n"),),
        )
        assert SYNTHETIC_KEY not in profile_path.read_text(encoding="utf-8")
        _pty_run(
            [str(pipx_executable), "profile", "remove", "--profile", PROFILE_NAME],
            environment=configure_environment,
            cwd=work,
            interactions=((b"[y/N]", b"y\n"),),
        )
        assert not profile_path.exists()

        _run(
            [pipx, "uninstall", PACKAGE_NAME],
            environment=pipx_environment,
            cwd=work,
        )
        assert not pipx_executable.exists()

        fixture_manifest_bytes, _headers = _download(
            f"{fixture_origin}/fixtures/manifest.json", cap=MAX_MANIFEST_BYTES
        )
        loaded_fixtures = json.loads(
            fixture_manifest_bytes, object_pairs_hook=_unique_object
        )
        fixtures_by_version = {
            item["version"]: item for item in loaded_fixtures["releases"]
        }
        predecessor = fixtures_by_version[FIXTURE_VERSIONS["predecessor"]]
        successor = fixtures_by_version[FIXTURE_VERSIONS["successor"]]
        incompatible = fixtures_by_version[FIXTURE_VERSIONS["incompatible"]]
        assert _is_compatible(predecessor, api="v1", contract=contract)
        assert _is_compatible(successor, api="v1", contract=contract)
        assert not _is_compatible(incompatible, api="v1", contract=contract)

        fixture_root = work / "fixture-allowed-files"
        fixture_root.mkdir(mode=0o700)

        def install_fixture(
            item: dict[str, Any], *, enforce_compatibility: bool = True
        ) -> Path:
            if enforce_compatibility and not _is_compatible(
                item, api="v1", contract=contract
            ):
                raise ValueError("fixture release is incompatible")
            url = f"{fixture_origin}{item['artifact_path']}#sha256={item['sha256']}"
            installed = Path(fixture_environment["PIPX_BIN_DIR"]) / ENTRY_POINT
            return _pipx_install(
                pipx,
                url,
                environment=fixture_environment,
                cwd=work,
                upgrade=installed.exists(),
            )

        fixture_executable = install_fixture(predecessor)
        _installed_environment(
            fixture_executable,
            expected_version=predecessor["version"],
            dependency_graph=graph,
            environment=fixture_environment,
            cwd=work,
        )
        fixture_executable = install_fixture(successor)
        _installed_environment(
            fixture_executable,
            expected_version=successor["version"],
            dependency_graph=graph,
            environment=fixture_environment,
            cwd=work,
        )
        fixture_executable = install_fixture(predecessor)
        _installed_environment(
            fixture_executable,
            expected_version=predecessor["version"],
            dependency_graph=graph,
            environment=fixture_environment,
            cwd=work,
        )
        _check_adapter(
            fixture_executable,
            environment=fixture_environment,
            cwd=work,
            origin=fixture_origin,
            allowed_root=fixture_root,
        )
        fixture_executable = install_fixture(successor)
        _installed_environment(
            fixture_executable,
            expected_version=successor["version"],
            dependency_graph=graph,
            environment=fixture_environment,
            cwd=work,
        )
        with pytest.raises(ValueError, match="fixture release is incompatible"):
            install_fixture(incompatible)
        _installed_environment(
            fixture_executable,
            expected_version=successor["version"],
            dependency_graph=graph,
            environment=fixture_environment,
            cwd=work,
        )
        fixture_executable = install_fixture(incompatible, enforce_compatibility=False)
        _installed_environment(
            fixture_executable,
            expected_version=incompatible["version"],
            dependency_graph=graph,
            environment=fixture_environment,
            cwd=work,
        )
        incompatible_check = _check_adapter(
            fixture_executable,
            environment=fixture_environment,
            cwd=work,
            origin=fixture_origin,
            allowed_root=fixture_root,
            expected=1,
        )
        assert "incompatible_contract" in incompatible_check.stderr
        _run(
            [pipx, "uninstall", PACKAGE_NAME],
            environment=fixture_environment,
            cwd=work,
        )
        assert not fixture_executable.exists()

        api_requests = [item for item in requests if item["path"].startswith("/api/")]
        fixture_requests = [
            item for item in requests if item["path"].startswith("/fixtures/")
        ]
        assert api_requests and fixture_requests
        assert all(
            item["authorization"] == f"Bearer {SYNTHETIC_KEY}" and not item["cookie"]
            for item in api_requests
        )
        assert all(
            not item["authorization"] and not item["cookie"]
            for item in fixture_requests
        )
        for item in fixture_releases.values():
            assert any(request["path"] == item["artifact_path"] for request in requests)

    record_property("mcp_platform", PLATFORM_ID)
    record_property("mcp_public_version", release["version"])
    record_property("mcp_public_wheel_sha256", release["sha256"])
    record_property("mcp_dependency_graph_sha256", target["dependency_graph_sha256"])
    record_property("mcp_dependency_graph", json.dumps(graph, sort_keys=True))
    record_property("mcp_tool_versions", json.dumps(TOOL_VERSIONS, sort_keys=True))
    record_property("mcp_uv_prefix", uv_probe["prefix"])
    record_property("mcp_pipx_prefix", pipx_probe["prefix"])
