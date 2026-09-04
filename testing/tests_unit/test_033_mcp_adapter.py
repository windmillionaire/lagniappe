"""Standalone MCP adapter contracts; this module must run without app imports."""

from __future__ import annotations

import ast
import asyncio
from contextlib import contextmanager, suppress
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import select
import socket
import stat
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode
import warnings

import httpx
from mcp import Client
from mcp.shared.message import SessionMessage
from mcp.shared.exceptions import MCPError
from mcp_types import JSONRPCRequest
import pytest

from lagniappe_mcp._telemetry import classify_error, telemetry_scope
from lagniappe_mcp import schema as schema_module
from lagniappe_mcp.adapter import (
    AdapterResult,
    LagniappeAdapter,
    _reject_private_model_data,
)
from lagniappe_mcp.catalog import (
    READ_ANNOTATIONS,
    ToolDefinition,
    build_tool_registry,
    catalog_tools,
    get_file_output_schema,
    lifecycle_tools,
)
from lagniappe_mcp.codex_config import (
    codex_config_path,
    install_entry,
    remove_entry,
    render_entry,
)
from lagniappe_mcp.configuration import ConnectionConfig, from_environment
from lagniappe_mcp.errors import (
    AdapterError,
    ConfigurationError,
    SchemaError,
    TransportError,
)
from lagniappe_mcp.limits import (
    MAX_ERROR_BYTES,
    MAX_MEDIA_RAW_BYTES,
    MAX_REQUEST_FRAME_BYTES,
    MAX_STARTUP_DIAGNOSTIC_BYTES,
    MAX_STDERR_BYTES,
    MAX_STRUCTURED_RESULT_BYTES,
)
from lagniappe_mcp.profiles import (
    atomic_write,
    connection_from_profile,
    delete_profile,
    load_profile,
    load_profile_snapshot,
    profile_path,
    profile_fingerprint,
    save_profile,
    secure_read,
)
from lagniappe_mcp.rest import RESTClient, validate_openapi_compatibility
from lagniappe_mcp.schema import (
    compact_json,
    inject_plan_id,
    validate_schema_document,
    validate_value,
)
from lagniappe_mcp.server import (
    _bounded_stdin_lines,
    _bounded_stdio_requests,
    _error_result,
    _success_result,
)
from lagniappe_mcp.url_security import normalize_site_url, validate_storage_url
from testing.utility import mcp_client_driver


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "clients" / "lagniappe_mcp"


def _profile_value() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "personal",
        "site_url": "https://example.com",
        "api_key": "secret-key",
        "allowed_roots": ["/tmp/approved"],
        "actor": {"name": "Person", "hash": "abcdefghijkl"},
        "credential": {
            "expires_at": "2099-01-01T00:00:00+00:00",
            "display_prefix": "lag_1234…",
            "generation": 1,
        },
        "client": {
            "name": "lagniappe-personal",
            "mode": "automatic",
            "registered": True,
            "fingerprint": "a" * 64,
            "executable": "/usr/bin/lagniappe-mcp",
            "required": False,
        },
    }


def _signed_download_url(**updates: str) -> str:
    values = {
        "X-Goog-Algorithm": "GOOG4-RSA-SHA256",
        "X-Goog-Credential": "account/20990101/auto/storage/goog4_request",
        "X-Goog-Date": "20990101T000000Z",
        "X-Goog-Expires": "300",
        "X-Goog-SignedHeaders": "host",
        "X-Goog-Signature": "a" * 64,
    }
    values.update(updates)
    return f"https://storage.googleapis.com/bucket/object.png?{urlencode(values)}"


def _actor() -> dict[str, Any]:
    return {
        "user": {
            "name": "Person",
            "hash": "abcdefghijkl",
            "timezone": "UTC",
            "personal_page": {
                "kind": "page",
                "hash": "hash:abcdefghijkl",
                "name": "Personal Page",
                "url": "/pages/personal",
                "can_view": True,
                "can_edit": True,
            },
        },
        "credential": {
            "active": True,
            "display_prefix": "lgn_actor…",
            "issued_at": "2026-09-04T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "generation": 1,
        },
        "capabilities": {"ask": True, "create": True, "organize": True},
    }


def _plan() -> dict[str, Any]:
    return {
        "id": "abcdefghijkl",
        "status": "draft",
        "tool": "create",
        "name": "Draft",
        "instructions": "Prepare one safe change.",
        "files": [],
        "uploads_pending": False,
        "upload_batch_id": None,
        "contract_version": 6,
        "contract_url": "https://example.com/api/v1/plans/abcdefghijkl/contract",
        "submit_url": "https://example.com/api/v1/plans/abcdefghijkl/submit",
        "status_url": "https://example.com/api/v1/plans/abcdefghijkl",
        "preview_url": "https://example.com/tools/api-plan/abcdefghijkl",
        "review_url": "https://example.com/tools/reports/abcdefghijkl",
        "proposal": None,
    }


def _contract() -> dict[str, Any]:
    return {
        "contract_version": 6,
        "tool": "create",
        "current_date": "2026-09-04",
        "timezone": "UTC",
        "personal_page": {},
        "proposal_schema": {
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
        "permissions": {},
        "required_file_refs": [],
        "upload_inventory": None,
        "file_checklist": [],
        "guidance_requirements": {},
        "uploads_supported": False,
        "workflow_rules": [],
        "reference_rules": [],
        "limits": {},
        "payload_sizes": {},
        "submission_format": {
            "method": "POST",
            "url": "https://example.com/api/v1/plans/abcdefghijkl/submit",
            "contract_version": 6,
            "body": {"contract_version": 6, "proposal": {}},
            "rule": "Replace the empty proposal template.",
        },
    }


def _compatible_openapi() -> dict[str, Any]:
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
    version_schema = {"properties": {"contract_version": {"const": 6}}}
    plan_schema = deepcopy(version_schema)
    plan_schema["required"] = ["upload_batch_id"]
    plan_schema["properties"]["upload_batch_id"] = {
        "oneOf": [batch_schema, {"type": "null"}],
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
                "Plan": plan_schema,
                "PlanContract": deepcopy(version_schema),
                "SubmissionReceipt": deepcopy(version_schema),
                "PlanSubmissionFormat": {
                    "properties": {
                        "contract_version": {"const": 6},
                        "body": {
                            "properties": {"contract_version": {"const": 6}}
                        },
                    }
                },
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


class _WorkflowREST:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []

    async def startup(self):
        return (
            {"version": "v1"},
            _actor(),
            {
                "tools": [
                    {
                        "name": "search",
                        "description": "Search within the current Plan.",
                        "input_schema": {
                            "type": "object",
                            "required": ["query"],
                            "properties": {"query": {"type": "string"}},
                            "additionalProperties": False,
                        },
                        "output_schema": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "result_paths": {
                            "primary_collection": "$",
                            "pagination": None,
                        },
                    }
                ],
                "view": "full",
                "selected_count": 1,
                "reference_format": "hash:<12-character-hash>",
                "execution_envelope": {
                    "success": {
                        "result": "<value matching the selected output_schema>"
                    },
                    "failure": {
                        "error": {"code": "tool_error", "message": "<message>"},
                        "request_id": "<request id>",
                    },
                },
            },
        )

    async def request_json(
        self, method: str, target: str, *, body: Any = None, **_kwargs: Any
    ):
        self.requests.append((method, target, body))
        if target == "me":
            return _actor(), "request-actor"
        if target == "plans":
            return _plan(), "request-start"
        if target == "plans/abcdefghijkl":
            return _plan(), "request-plan"
        if target == "plans/abcdefghijkl/contract":
            return _contract(), "request-contract"
        if target == "plans/abcdefghijkl/tools/search":
            return {"result": ["first", "second"]}, "request-search"
        if target == "https://example.com/api/v1/plans/abcdefghijkl/submit":
            return {
                "id": "abcdefghijkl",
                "status": "ready",
                "preview_url": "https://example.com/tools/api-plan/abcdefghijkl",
                "review_url": "https://example.com/tools/reports/abcdefghijkl",
                "status_url": "https://example.com/api/v1/plans/abcdefghijkl",
                "contract_version": 6,
                "proposal_fingerprint": "f" * 64,
            }, "request-submit"
        raise AssertionError(f"Unexpected request: {method} {target}")

    async def aclose(self) -> None:
        return None


# @pair mcp-adapter:product-contract
def test_profile_write_rejects_shared_private_directories(tmp_path: Path) -> None:
    config_home = tmp_path / "profile-config"
    config_home.mkdir(mode=0o700)
    profiles = config_home / "profiles"
    profiles.mkdir(mode=0o700)
    os.chmod(config_home, 0o777)
    environ = {"LAGNIAPPE_MCP_CONFIG_HOME": str(config_home)}

    with pytest.raises(ConfigurationError) as error:
        save_profile(_profile_value(), environ=environ)

    assert error.value.code == "unsafe_permissions"
    assert not (profiles / "personal.json").exists()


# @pair mcp-adapter:product-contract
def test_profile_paths_never_anchor_relative_config_roots_to_the_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    for variable in ("LAGNIAPPE_MCP_CONFIG_HOME", "XDG_CONFIG_HOME"):
        with pytest.raises(ConfigurationError) as error:
            profile_path("personal", environ={variable: "project-config"})
        assert error.value.code == "unsafe_path"
    with pytest.raises(ConfigurationError) as home_error:
        profile_path("personal", environ={"HOME": "project-home"})
    assert home_error.value.code == "unsafe_path"
    assert not (tmp_path / "project-config").exists()
    assert not (tmp_path / "project-home").exists()


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::install_entry
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::save_profile
def test_profile_and_codex_config_reject_symlinked_directory_components(
    tmp_path: Path,
) -> None:
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    redirected = tmp_path / "redirected"
    redirected.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ConfigurationError) as profile_error:
        save_profile(
            _profile_value(),
            environ={
                "LAGNIAPPE_MCP_CONFIG_HOME": str(redirected / "profile-config")
            },
        )
    assert profile_error.value.code == "unsafe_path"

    with pytest.raises(ConfigurationError) as codex_error:
        install_entry(
            "personal",
            "/usr/bin/lagniappe-mcp",
            expected_fingerprint=None,
            environ={"CODEX_HOME": str(redirected / "codex-config")},
        )
    assert codex_error.value.code == "unsafe_path"
    assert list(actual.iterdir()) == []


# @pair mcp-adapter:product-contract
def test_manual_environment_configuration_is_explicit_and_validated() -> None:
    config = from_environment(
        ["/tmp/approved"],
        environ={
            "LAGNIAPPE_URL": " https://example.com ",
            "LAGNIAPPE_API_KEY": " api-secret ",
        },
    )

    assert config.authority.origin == "https://example.com"
    assert config.api_key == "api-secret"
    assert config.allowed_roots == (Path("/tmp/approved"),)
    assert "api-secret" not in repr(config)
    assert "/tmp/approved" not in repr(config)
    with pytest.raises(ConfigurationError) as missing:
        from_environment([], environ={"LAGNIAPPE_URL": "https://example.com"})
    assert missing.value.code == "missing_environment"
    assert "LAGNIAPPE_API_KEY" in missing.value.message
    with pytest.raises(ConfigurationError) as empty:
        from_environment(
            [],
            environ={
                "LAGNIAPPE_URL": "https://example.com",
                "LAGNIAPPE_API_KEY": "   ",
            },
        )
    assert empty.value.code == "empty_environment"
    assert "LAGNIAPPE_API_KEY" in empty.value.message
    with pytest.raises(ConfigurationError) as missing_url:
        from_environment([], environ={"LAGNIAPPE_API_KEY": "api-secret"})
    assert missing_url.value.code == "missing_environment"
    assert "LAGNIAPPE_URL" in missing_url.value.message
    with pytest.raises(ConfigurationError) as empty_url:
        from_environment(
            [],
            environ={
                "LAGNIAPPE_URL": "   ",
                "LAGNIAPPE_API_KEY": "api-secret",
            },
        )
    assert empty_url.value.code == "empty_environment"
    assert "LAGNIAPPE_URL" in empty_url.value.message
    with pytest.raises(ConfigurationError) as unsafe_url:
        from_environment(
            [],
            environ={
                "LAGNIAPPE_URL": "http://example.com",
                "LAGNIAPPE_API_KEY": "key",
            },
        )
    assert unsafe_url.value.code == "invalid_url"


# @pair mcp-adapter:product-contract
def test_profile_atomic_write_detects_race_after_temp_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "value.json"
    target.parent.mkdir(mode=0o700)
    atomic_write(target, b"before", private=True)
    real_fsync = os.fsync
    raced = False

    def racing_fsync(descriptor: int) -> None:
        nonlocal raced
        details = os.fstat(descriptor)
        if not raced and stat.S_ISREG(details.st_mode):
            raced = True
            target.write_bytes(b"concurrent")
        real_fsync(descriptor)

    monkeypatch.setattr("lagniappe_mcp.profiles.os.fsync", racing_fsync)
    with pytest.raises(ConfigurationError) as error:
        atomic_write(target, b"replacement", private=True)

    assert error.value.code == "concurrent_change"
    assert target.read_bytes() == b"concurrent"
    assert not list(target.parent.glob(".value.json.*.tmp"))


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_profile_write_post_compare_race_is_restored_without_clobbering_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    directory = tmp_path / "codex"
    directory.mkdir(mode=0o700)
    target = directory / "config.toml"
    backup = directory / "config.toml.lagniappe-mcp.bak"
    target.write_bytes(b"reviewed")
    backup.write_bytes(b"older-backup")
    os.chmod(target, 0o600)
    os.chmod(backup, 0o600)
    real_exchange = profiles_module._rename_exchange
    raced = False

    def race_after_compare(
        directory_fd: int, source: str, destination: str
    ) -> None:
        nonlocal raced
        if destination == target.name and source.endswith(".tmp") and not raced:
            raced = True
            target.write_bytes(b"concurrent")
        real_exchange(directory_fd, source, destination)

    monkeypatch.setattr(profiles_module, "_rename_exchange", race_after_compare)
    with pytest.raises(ConfigurationError) as error:
        atomic_write(target, b"replacement", private=False, backup=True)

    assert error.value.code == "concurrent_change"
    assert target.read_bytes() == b"concurrent"
    assert backup.read_bytes() == b"older-backup"
    assert not list(directory.glob("*.recover"))


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_client_config_rollback_never_displaces_a_newer_canonical_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    directory = tmp_path / "codex"
    directory.mkdir(mode=0o700)
    target = directory / "config.toml"
    backup = directory / "config.toml.lagniappe-mcp.bak"
    target.write_bytes(b"reviewed")
    backup.write_bytes(b"older-backup")
    os.chmod(target, 0o600)
    os.chmod(backup, 0o600)

    def mutate_both_names_after_exchange(
        directory_fd: int,
        temporary: str,
        filename: str,
    ) -> None:
        newer = f".{filename}.newer"
        newer_fd = os.open(
            newer,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            os.write(newer_fd, b"newer")
            os.fsync(newer_fd)
        finally:
            os.close(newer_fd)
        os.rename(
            newer,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        displaced_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        try:
            os.write(displaced_fd, b"changed-displaced")
            os.fsync(displaced_fd)
        finally:
            os.close(displaced_fd)

    monkeypatch.setattr(
        profiles_module,
        "_after_exchange",
        mutate_both_names_after_exchange,
    )
    with pytest.raises(ConfigurationError) as error:
        atomic_write(target, b"replacement", private=False, backup=True)

    assert error.value.code == "configuration_recovery_required"
    assert target.read_bytes() == b"newer"
    assert backup.read_bytes() == b"older-backup"
    recoveries = list(directory.glob(".config.toml.*.recover"))
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == b"changed-displaced"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_private_profile_replace_crash_leaves_no_old_credential_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    class SimulatedCrash(BaseException):
        pass

    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    target = directory / "value.json"
    target.write_bytes(b"reviewed-old-key")
    os.chmod(target, 0o600)
    observed: list[tuple[bytes, tuple[str, ...]]] = []

    def crash_after_replace(directory_fd: int, filename: str) -> None:
        canonical_fd = os.open(
            filename,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        try:
            observed.append(
                (os.read(canonical_fd, 64), tuple(sorted(os.listdir(directory_fd))))
            )
        finally:
            os.close(canonical_fd)
        raise SimulatedCrash()

    monkeypatch.setattr(
        profiles_module,
        "_after_private_replace",
        crash_after_replace,
    )
    with pytest.raises(SimulatedCrash):
        atomic_write(target, b"replacement-new-key", private=True)

    assert observed == [
        (
            b"replacement-new-key",
            (".value.json.lagniappe-mcp.lock", "value.json"),
        )
    ]
    assert target.read_bytes() == b"replacement-new-key"
    assert not list(directory.glob(".value.json.*.tmp"))
    assert not list(directory.glob(".value.json.*.recover"))
    for entry in directory.iterdir():
        if entry.is_file():
            assert b"reviewed-old-key" not in entry.read_bytes()


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_profile_post_replace_validation_preserves_a_newer_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    target = directory / "value.json"
    target.write_bytes(b"reviewed")
    os.chmod(target, 0o600)

    def mutate_after_replace(directory_fd: int, filename: str) -> None:
        replacement = f".{filename}.newer"
        descriptor = os.open(
            replacement,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            os.write(descriptor, b"newer")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.rename(
            replacement,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )

    monkeypatch.setattr(
        profiles_module,
        "_after_private_replace",
        mutate_after_replace,
    )
    with pytest.raises(ConfigurationError) as error:
        atomic_write(target, b"replacement", private=True)

    assert error.value.code == "concurrent_change"
    assert target.read_bytes() == b"newer"
    assert not list(directory.glob(".value.json.*.tmp"))
    assert not list(directory.glob(".value.json.*.recover"))


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_delete
def test_profile_delete_detects_a_precommit_revision_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    target = tmp_path / "private" / "value.json"
    target.parent.mkdir(mode=0o700)
    atomic_write(target, b"reviewed", private=True)
    real_snapshot_matches = profiles_module._snapshot_matches
    raced = False

    def race_before_compare(
        directory_fd: int,
        filename: str,
        original: Any,
        *,
        private: bool,
    ) -> bool:
        nonlocal raced
        if filename == target.name and not raced:
            raced = True
            target.write_bytes(b"concurrent")
        return real_snapshot_matches(
            directory_fd,
            filename,
            original,
            private=private,
        )

    monkeypatch.setattr(profiles_module, "_snapshot_matches", race_before_compare)
    with pytest.raises(ConfigurationError) as error:
        profiles_module.atomic_delete(target, private=True)

    assert error.value.code == "concurrent_change"
    assert target.read_bytes() == b"concurrent"
    assert not list(target.parent.glob("*.recover"))


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_delete
def test_private_profile_delete_crash_leaves_no_credential_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    class SimulatedCrash(BaseException):
        pass

    target = tmp_path / "private" / "value.json"
    target.parent.mkdir(mode=0o700)
    atomic_write(target, b"old-key", private=True)
    observed: list[tuple[str, ...]] = []

    def crash_after_delete(directory_fd: int, filename: str) -> None:
        assert filename == target.name
        observed.append(tuple(os.listdir(directory_fd)))
        raise SimulatedCrash()

    monkeypatch.setattr(
        profiles_module,
        "_after_private_delete",
        crash_after_delete,
    )
    with pytest.raises(SimulatedCrash):
        profiles_module.atomic_delete(target, private=True)

    assert len(observed) == 1
    assert target.name not in observed[0]
    assert not target.exists()
    assert not list(target.parent.glob(".value.json.*.tmp"))
    assert not list(target.parent.glob(".value.json.*.recover"))
    for entry in target.parent.iterdir():
        if entry.is_file():
            assert b"old-key" not in entry.read_bytes()


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::secure_read
@pytest.mark.parametrize("suffix", ["tmp", "recover"])
def test_private_profile_access_cleans_abandoned_owner_only_transactions(
    tmp_path: Path,
    suffix: str,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    target = tmp_path / "private" / "value.json"
    target.parent.mkdir(mode=0o700)
    atomic_write(target, b"current-key", private=True)
    abandoned = target.parent / f".value.json.999.deadbeefdeadbeef.{suffix}"
    abandoned.write_bytes(b"abandoned-key")
    os.chmod(abandoned, 0o600)

    assert profiles_module.secure_read(target, private=True) == b"current-key"
    assert not abandoned.exists()


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_profile_create_post_compare_race_never_replaces_the_new_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    target = tmp_path / "private" / "value.json"
    target.parent.mkdir(mode=0o700)
    real_rename = profiles_module._rename_noreplace
    raced = False

    def race_after_compare(
        directory_fd: int, source: str, destination: str
    ) -> None:
        nonlocal raced
        if destination == target.name and source.endswith(".tmp") and not raced:
            raced = True
            target.write_bytes(b"concurrent-create")
            os.chmod(target, 0o600)
        real_rename(directory_fd, source, destination)

    monkeypatch.setattr(profiles_module, "_rename_noreplace", race_after_compare)
    with pytest.raises(ConfigurationError) as error:
        atomic_write(target, b"created-by-adapter", private=True)

    assert error.value.code == "concurrent_change"
    assert target.read_bytes() == b"concurrent-create"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_codex_backup_failure_rolls_back_main_without_replacing_a_newer_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    directory = tmp_path / "codex"
    directory.mkdir(mode=0o700)
    target = directory / "config.toml"
    backup = directory / "config.toml.lagniappe-mcp.bak"
    target.write_bytes(b"reviewed")
    backup.write_bytes(b"older-backup")
    os.chmod(target, 0o600)
    os.chmod(backup, 0o600)
    real_write = profiles_module._write_at

    def fail_backup(
        directory_fd: int,
        filename: str,
        data: bytes,
        **kwargs: Any,
    ):
        if filename == backup.name:
            raise ConfigurationError("save_failed", "injected backup failure")
        return real_write(directory_fd, filename, data, **kwargs)

    monkeypatch.setattr(profiles_module, "_write_at", fail_backup)
    with pytest.raises(ConfigurationError) as error:
        atomic_write(target, b"replacement", private=False, backup=True)

    assert error.value.code == "save_failed"
    assert target.read_bytes() == b"reviewed"
    assert backup.read_bytes() == b"older-backup"

    def fail_backup_after_newer_edit(
        directory_fd: int,
        filename: str,
        data: bytes,
        **kwargs: Any,
    ):
        if filename == backup.name:
            target.write_bytes(b"newer-edit")
            raise ConfigurationError("save_failed", "injected backup failure")
        return real_write(directory_fd, filename, data, **kwargs)

    monkeypatch.setattr(
        profiles_module,
        "_write_at",
        fail_backup_after_newer_edit,
    )
    with pytest.raises(ConfigurationError) as raced_error:
        atomic_write(target, b"replacement", private=False, backup=True)

    assert raced_error.value.code == "configuration_rollback_failed"
    assert target.read_bytes() == b"newer-edit"
    assert backup.read_bytes() == b"older-backup"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_profile_mutations_reject_nonregular_targets_without_blocking(
    tmp_path: Path,
    kind: str,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    target = directory / "value.json"
    if kind == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(b"outside")
        target.symlink_to(outside)
    else:
        os.mkfifo(target)

    with pytest.raises(ConfigurationError) as write_error:
        atomic_write(target, b"replacement", private=True)
    assert write_error.value.code == "unsafe_file"
    with pytest.raises(ConfigurationError) as delete_error:
        profiles_module.atomic_delete(target, private=True)
    assert delete_error.value.code == "unsafe_file"
    if kind == "symlink":
        assert outside.read_bytes() == b"outside"
    else:
        assert stat.S_ISFIFO(target.lstat().st_mode)


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_atomic_update_requires_kernel_no_clobber_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import profiles as profiles_module

    def unsupported(_directory_fd: int, _source: str, _destination: str) -> None:
        raise profiles_module._AtomicRenameUnavailable(
            profiles_module.errno.ENOSYS,
            "unsupported",
        )

    monkeypatch.setattr(profiles_module, "_rename_noreplace", unsupported)
    monkeypatch.setattr(profiles_module, "_rename_exchange", unsupported)
    private_target = tmp_path / "private" / "profile.json"
    private_target.parent.mkdir(mode=0o700)
    with pytest.raises(ConfigurationError) as profile_error:
        atomic_write(private_target, b"profile", private=True)
    assert profile_error.value.code == "atomic_update_unsupported"
    assert "--from-env" in profile_error.value.message
    assert not private_target.exists()

    codex_target = tmp_path / "codex" / "config.toml"
    codex_target.parent.mkdir(mode=0o700)
    codex_target.write_bytes(b"existing")
    os.chmod(codex_target, 0o600)
    with pytest.raises(ConfigurationError) as codex_error:
        atomic_write(codex_target, b"config", private=False)
    assert codex_error.value.code == "manual_configuration_required"
    assert "manual block" in codex_error.value.message
    assert codex_target.read_bytes() == b"existing"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_profile_and_codex_mutations_reject_changes_after_their_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import codex_config as codex_module
    from lagniappe_mcp import profiles as profiles_module

    profile_environ = {"LAGNIAPPE_MCP_CONFIG_HOME": str(tmp_path / "profiles")}
    save_profile(_profile_value(), environ=profile_environ)
    profile, profile_snapshot = load_profile_snapshot(
        "personal", environ=profile_environ
    )
    profile_target = tmp_path / "profiles" / "profiles" / "personal.json"
    concurrent_profile = deepcopy(profile)
    concurrent_profile["allowed_roots"] = ["/tmp/concurrent"]
    concurrent_bytes = (
        json.dumps(
            concurrent_profile,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    profile_target.write_bytes(concurrent_bytes)
    profile["allowed_roots"] = ["/tmp/replacement"]

    with pytest.raises(ConfigurationError) as profile_error:
        save_profile(
            profile,
            environ=profile_environ,
            expected_snapshot=profile_snapshot,
        )

    assert profile_error.value.code == "concurrent_change"
    assert profile_target.read_bytes() == concurrent_bytes

    codex_environ = {"CODEX_HOME": str(tmp_path / "codex")}
    fingerprint = install_entry(
        "personal",
        "/usr/bin/lagniappe-mcp",
        expected_fingerprint=None,
        environ=codex_environ,
    )
    codex_target = tmp_path / "codex" / "config.toml"
    real_atomic_write = profiles_module.atomic_write

    def race_before_lock(path: Path, data: bytes, **kwargs: Any) -> None:
        codex_target.write_text(
            codex_target.read_text(encoding="utf-8") + "# concurrent edit\n",
            encoding="utf-8",
        )
        real_atomic_write(path, data, **kwargs)

    monkeypatch.setattr(codex_module, "atomic_write", race_before_lock)
    with pytest.raises(ConfigurationError) as codex_error:
        install_entry(
            "personal",
            "/opt/lagniappe-mcp",
            expected_fingerprint=fingerprint,
            environ=codex_environ,
        )

    assert codex_error.value.code == "concurrent_change"
    assert codex_target.read_text(encoding="utf-8").endswith("# concurrent edit\n")


# @pair mcp-adapter:product-contract
def test_profile_round_trip_is_strict_and_owner_only(tmp_path: Path) -> None:
    environ = {"LAGNIAPPE_MCP_CONFIG_HOME": str(tmp_path / "profiles")}
    value = _profile_value()
    save_profile(value, environ=environ)
    loaded = load_profile("personal", environ=environ)
    target = tmp_path / "profiles" / "profiles" / "personal.json"

    assert loaded == value
    connection = connection_from_profile("personal", environ=environ)
    assert connection.authority.origin == value["site_url"]
    assert connection.actor_hash == value["actor"]["hash"]
    assert profile_fingerprint(value) == profile_fingerprint(loaded)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    os.chmod(tmp_path / "profiles", 0o755)
    with pytest.raises(ConfigurationError) as exposed_directory:
        load_profile("personal", environ=environ)
    assert exposed_directory.value.code == "unsafe_permissions"
    os.chmod(tmp_path / "profiles", 0o700)
    malformed = dict(value)
    malformed["allowed_roots"] = ["relative"]
    with pytest.raises(ConfigurationError, match="allowed roots"):
        save_profile(malformed, environ=environ)
    delete_profile("personal", environ=environ)
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_profile("personal", environ=environ)


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def test_codex_config_accepts_owned_readable_directory_but_rejects_writable_one(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir(mode=0o755)
    environ = {"CODEX_HOME": str(codex_home)}

    fingerprint = install_entry(
        "personal",
        "/usr/bin/lagniappe-mcp",
        expected_fingerprint=None,
        environ=environ,
    )
    target = codex_home / "config.toml"
    assert fingerprint
    assert stat.S_IMODE(codex_home.stat().st_mode) == 0o755
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    os.chmod(codex_home, 0o775)
    with pytest.raises(ConfigurationError) as error:
        secure_read(target, private=False)
    assert error.value.code == "unsafe_permissions"


# @pair mcp-adapter:product-contract
def test_codex_owned_entry_rejects_table_modified_behind_marker(tmp_path: Path) -> None:
    environ = {"CODEX_HOME": str(tmp_path / "codex")}
    fingerprint = install_entry(
        "personal",
        "/usr/bin/lagniappe-mcp",
        expected_fingerprint=None,
        environ=environ,
    )
    target = tmp_path / "codex" / "config.toml"
    original = target.read_text()
    target.write_text(
        original.replace("tool_timeout_sec = 300", "tool_timeout_sec = 301")
    )

    with pytest.raises(ConfigurationError) as error:
        remove_entry(
            "personal",
            expected_fingerprint=fingerprint,
            environ=environ,
        )

    assert error.value.code == "foreign_server"
    assert "tool_timeout_sec = 301" in target.read_text()


# @pair mcp-adapter:product-contract
def test_codex_install_is_lossless_backed_up_and_idempotent(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir(mode=0o700)
    target = codex_home / "config.toml"
    original = '# keep this comment\nmodel = "gpt-test"\n'
    target.write_text(original)
    os.chmod(target, 0o600)
    environ = {"CODEX_HOME": str(codex_home)}

    fingerprint = install_entry(
        "personal",
        "/usr/bin/lagniappe-mcp",
        expected_fingerprint=None,
        environ=environ,
    )
    installed_stat = target.stat()
    backup = codex_home / "config.toml.lagniappe-mcp.bak"
    assert target.read_text().startswith(original)
    assert backup.read_text() == original
    assert backup.stat().st_uid == os.getuid()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600

    repeated = install_entry(
        "personal",
        "/usr/bin/lagniappe-mcp",
        expected_fingerprint=fingerprint,
        environ=environ,
    )
    assert repeated == fingerprint
    assert target.stat().st_ino == installed_stat.st_ino


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::render_entry
# @source clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::install_entry
def test_codex_entry_required_mode_is_explicit_and_fingerprinted(
    tmp_path: Path,
) -> None:
    ordinary_block, ordinary_fingerprint = render_entry(
        "personal", "/usr/bin/lagniappe-mcp"
    )
    trial_block, trial_fingerprint = render_entry(
        "personal", "/usr/bin/lagniappe-mcp", required=True
    )

    assert "required = false\n" in ordinary_block
    assert "required = true\n" in trial_block
    assert ordinary_fingerprint != trial_fingerprint

    environ = {"CODEX_HOME": str(tmp_path / "codex")}
    installed_ordinary = install_entry(
        "personal",
        "/usr/bin/lagniappe-mcp",
        expected_fingerprint=None,
        environ=environ,
    )
    assert installed_ordinary == ordinary_fingerprint
    target = tmp_path / "codex" / "config.toml"
    assert "required = false\n" in target.read_text(encoding="utf-8")

    installed_trial = install_entry(
        "personal",
        "/usr/bin/lagniappe-mcp",
        expected_fingerprint=installed_ordinary,
        required=True,
        environ=environ,
    )
    assert installed_trial == trial_fingerprint
    configured = target.read_text(encoding="utf-8")
    assert "required = true\n" in configured
    assert "required = false\n" not in configured


# @pair mcp-adapter:product-contract
def test_cli_source_modes_and_lowercase_profile_names_are_exact() -> None:
    from lagniappe_mcp import cli as cli_module

    parser = cli_module._parser()
    profile_mode = parser.parse_args(["serve", "--profile", "personal"])
    assert profile_mode.profile == "personal"
    assert profile_mode.from_env is False
    env_mode = parser.parse_args(
        ["serve", "--from-env", "--allowed-root", "/tmp/approved"]
    )
    assert env_mode.profile is None
    assert env_mode.from_env is True
    assert env_mode.allowed_root == ["/tmp/approved"]

    for command in ("serve", "check"):
        with pytest.raises(ConfigurationError) as missing_source:
            parser.parse_args([command])
        assert missing_source.value.code == "invalid_arguments"
        with pytest.raises(ConfigurationError) as duplicate_source:
            parser.parse_args(
                [command, "--profile", "personal", "--from-env"]
            )
        assert duplicate_source.value.code == "invalid_arguments"
        with pytest.raises(ConfigurationError) as uppercase_profile:
            parser.parse_args([command, "--profile", "Personal"])
        assert uppercase_profile.value.code == "invalid_profile"

    with pytest.raises(ConfigurationError) as profile_roots:
        cli_module._connection(
            SimpleNamespace(profile="personal", allowed_root=["/tmp/approved"])
        )
    assert profile_roots.value.code == "invalid_arguments"

    with pytest.raises(ConfigurationError) as uppercase_configure:
        parser.parse_args(
            [
                "configure",
                "codex",
                "--url",
                "https://example.com",
                "--profile",
                "Personal",
            ]
        )
    assert uppercase_configure.value.code == "invalid_profile"

    controlled_trial = parser.parse_args(
        [
            "configure",
            "codex",
            "--url",
            "https://example.com",
            "--profile",
            "personal",
            "--trial-required",
        ]
    )
    assert controlled_trial.trial_required is True


# @pair mcp-adapter:product-contract
@pytest.mark.parametrize(
    ("url", "allowed_roots", "trial_required"),
    [
        ("https://example.com", [], False),
        (None, ["/tmp/approved"], False),
        (None, [], True),
    ],
    ids=("url", "allowed-root", "trial-required"),
)
def test_configure_remove_rejects_configuration_arguments(
    url: str | None,
    allowed_roots: list[str],
    trial_required: bool,
) -> None:
    from lagniappe_mcp import cli as cli_module

    with pytest.raises(ConfigurationError) as caught:
        asyncio.run(
            cli_module._configure_codex(
                SimpleNamespace(
                    profile="personal",
                    remove=True,
                    url=url,
                    allowed_root=allowed_roots,
                    trial_required=trial_required,
                )
            )
        )
    assert caught.value.code == "invalid_arguments"

    with pytest.raises(ConfigurationError) as missing_url:
        asyncio.run(
            cli_module._configure_codex(
                SimpleNamespace(
                    profile="personal",
                    remove=False,
                    url=None,
                    allowed_root=[],
                    trial_required=False,
                )
            )
        )
    assert missing_url.value.code == "invalid_arguments"


# @pair mcp-adapter:product-contract
@pytest.mark.parametrize("failure", ["warning", "eof", "oserror"])
def test_api_key_prompt_fails_closed_when_no_echo_is_unavailable(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lagniappe_mcp import cli as cli_module

    def unavailable(_prompt: str) -> str:
        if failure == "warning":
            warnings.warn(
                "echo fallback would expose echoed-secret",
                cli_module.getpass.GetPassWarning,
                stacklevel=2,
            )
            pytest.fail("the echoed fallback must never read a credential")
        if failure == "eof":
            raise EOFError("echoed-secret")
        raise OSError("echoed-secret")

    monkeypatch.setattr(cli_module.getpass, "getpass", unavailable)

    with pytest.raises(ConfigurationError) as caught:
        cli_module._prompt_key()

    assert caught.value.code == "secure_prompt_unavailable"
    assert "echoed-secret" not in caught.value.render()
    captured = capsys.readouterr()
    assert "echoed-secret" not in captured.out
    assert "echoed-secret" not in captured.err


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::install_entry
def test_codex_config_never_anchors_a_relative_home_in_the_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigurationError) as error:
        codex_config_path(environ={"CODEX_HOME": "project-codex"})
    assert error.value.code == "unsafe_path"
    with pytest.raises(ConfigurationError) as home_error:
        codex_config_path(environ={"HOME": "project-home"})
    assert home_error.value.code == "unsafe_path"
    assert not (tmp_path / "project-codex").exists()
    assert not (tmp_path / "project-home").exists()


# @pair mcp-adapter:product-contract
def test_configure_rolls_back_new_codex_entry_when_profile_save_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import cli as cli_module

    removed: list[tuple[str, str]] = []

    def missing_profile(_name: str):
        raise ConfigurationError("profile_not_found", "missing")

    async def valid_key(
        _site_url: str, _key: str, *, expected_hash: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert expected_hash is None
        return (
            {"name": "Person", "hash": "abcdefghijkl"},
            {"expires_at": "2099-01-01T00:00:00+00:00"},
        )

    monkeypatch.setattr(cli_module, "load_profile_snapshot", missing_profile)
    monkeypatch.setattr(cli_module, "_prompt_key", lambda: "api-secret")
    monkeypatch.setattr(cli_module, "_validate_key", valid_key)
    monkeypatch.setattr(cli_module, "console_executable", lambda: "/usr/bin/tool")
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)
    monkeypatch.setattr(cli_module, "install_entry", lambda *_args, **_kwargs: "a" * 64)
    monkeypatch.setattr(
        cli_module,
        "remove_entry",
        lambda name, *, expected_fingerprint: removed.append(
            (name, expected_fingerprint)
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda _profile, **_kwargs: (_ for _ in ()).throw(
            ConfigurationError("save_failed", "failed")
        ),
    )
    args = SimpleNamespace(
        profile="personal",
        remove=False,
        url="https://example.com",
        allowed_root=[],
    )

    with pytest.raises(ConfigurationError) as error:
        asyncio.run(cli_module._configure_codex(args))

    assert error.value.code == "save_failed"
    assert removed == [("personal", "a" * 64)]

    removed.clear()
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda _profile, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(cli_module._configure_codex(args))
    assert removed == [("personal", "a" * 64)]


# @pair mcp-adapter:product-contract
def test_configure_idempotently_preserves_existing_allowed_roots(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lagniappe_mcp import cli as cli_module

    profile = _profile_value()
    profile["client"].update(mode="manual", registered=False)
    saved: list[dict[str, Any]] = []
    installed: list[tuple[str, str, str | None, bool]] = []

    async def valid_key(
        site_url: str, key: str, *, expected_hash: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert (site_url, key, expected_hash) == (
            "https://example.com",
            "secret-key",
            "abcdefghijkl",
        )
        actor = _actor()
        return actor["user"], actor["credential"]

    snapshot = object()
    monkeypatch.setattr(
        cli_module,
        "load_profile_snapshot",
        lambda _name: (deepcopy(profile), snapshot),
    )
    monkeypatch.setattr(
        cli_module,
        "_prompt_key",
        lambda: pytest.fail("existing same-site configuration must not prompt"),
    )
    monkeypatch.setattr(cli_module, "_validate_key", valid_key)
    monkeypatch.setattr(cli_module, "_safe_root", lambda value: value)
    monkeypatch.setattr(cli_module, "console_executable", lambda: "/usr/bin/tool")
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)
    monkeypatch.setattr(
        cli_module,
        "install_entry",
        lambda name, executable, *, expected_fingerprint, required=False: installed.append(
            (name, executable, expected_fingerprint, required)
        )
        or "a" * 64,
    )
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda value, *, expected_snapshot: (
            expected_snapshot is snapshot or pytest.fail("stale profile snapshot")
        )
        and saved.append(value),
    )
    args = SimpleNamespace(
        profile="personal",
        remove=False,
        url="https://example.com",
        allowed_root=[],
    )

    assert asyncio.run(cli_module._configure_codex(args)) == 0
    assert installed == [("personal", "/usr/bin/tool", "a" * 64, False)]
    assert saved[0]["allowed_roots"] == ["/tmp/approved"]
    assert saved[0]["client"]["mode"] == "automatic"
    assert saved[0]["client"]["registered"] is True
    preview = capsys.readouterr().out
    assert "Proposed user Codex entry:" in preview
    assert "[mcp_servers.lagniappe-personal]" in preview
    assert "Allowed roots:\n  - /tmp/approved\n" in preview
    assert "secret-key" not in preview


# @pair mcp-adapter:product-contract
def test_configure_trial_required_uses_owned_required_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import cli as cli_module

    saved: list[dict[str, Any]] = []
    installed: list[tuple[str, str, str | None, bool]] = []

    def missing_profile(_name: str):
        raise ConfigurationError("profile_not_found", "missing")

    async def valid_key(
        site_url: str,
        key: str,
        *,
        expected_hash: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert (site_url, key, expected_hash) == (
            "https://example.com",
            "api-secret",
            None,
        )
        actor = _actor()
        return actor["user"], actor["credential"]

    monkeypatch.setattr(cli_module, "load_profile_snapshot", missing_profile)
    monkeypatch.setattr(cli_module, "_prompt_key", lambda: "api-secret")
    monkeypatch.setattr(cli_module, "_validate_key", valid_key)
    monkeypatch.setattr(cli_module, "console_executable", lambda: "/usr/bin/tool")
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)

    def install(
        name: str,
        executable: str,
        *,
        expected_fingerprint: str | None,
        required: bool = False,
    ) -> str:
        installed.append((name, executable, expected_fingerprint, required))
        return "b" * 64

    monkeypatch.setattr(cli_module, "install_entry", install)
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda value, *, expected_snapshot: (
            expected_snapshot is None or pytest.fail("unexpected prior profile")
        )
        and saved.append(value),
    )

    assert (
        asyncio.run(
            cli_module._configure_codex(
                SimpleNamespace(
                    profile="personal",
                    remove=False,
                    url="https://example.com",
                    allowed_root=[],
                    trial_required=True,
                )
            )
        )
        == 0
    )
    assert installed == [("personal", "/usr/bin/tool", None, True)]
    assert saved[0]["client"]["required"] is True
    assert saved[0]["client"]["fingerprint"] == "b" * 64


# @pair mcp-adapter:product-contract
def test_configure_manual_fallback_preserves_a_changed_manual_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import cli as cli_module

    profile = _profile_value()
    _old_block, old_fingerprint = cli_module.render_entry(
        "personal", "/opt/lagniappe-mcp", required=False
    )
    profile["client"].update(
        mode="manual",
        registered=False,
        fingerprint=old_fingerprint,
        executable="/opt/lagniappe-mcp",
        required=False,
    )
    original_client = deepcopy(profile["client"])

    async def valid_key(
        _site_url: str,
        _key: str,
        *,
        expected_hash: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert expected_hash == "abcdefghijkl"
        actor = _actor()
        return actor["user"], actor["credential"]

    monkeypatch.setattr(
        cli_module,
        "load_profile_snapshot",
        lambda _name: (profile, object()),
    )
    monkeypatch.setattr(cli_module, "_validate_key", valid_key)
    monkeypatch.setattr(cli_module, "_safe_root", lambda value: value)
    monkeypatch.setattr(
        cli_module, "console_executable", lambda: "/opt/lagniappe-mcp"
    )
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)
    monkeypatch.setattr(
        cli_module,
        "install_entry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ConfigurationError(
                "manual_configuration_required", "safe editing is unavailable"
            )
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda *_args, **_kwargs: pytest.fail(
            "a changed manual identity must not replace the removal fingerprint"
        ),
    )

    with pytest.raises(ConfigurationError) as caught:
        asyncio.run(
            cli_module._configure_codex(
                SimpleNamespace(
                    profile="personal",
                    remove=False,
                    url="https://example.com",
                    allowed_root=[],
                    trial_required=True,
                )
            )
        )

    assert caught.value.code == "managed_entry_update_requires_removal"
    assert profile["client"] == original_client


# @pair mcp-adapter:product-contract
def test_configure_save_failure_restores_prior_required_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import cli as cli_module

    profile = _profile_value()
    _old_block, old_fingerprint = cli_module.render_entry(
        "personal", "/opt/lagniappe-mcp", required=True
    )
    profile["client"].update(
        mode="automatic",
        registered=True,
        fingerprint=old_fingerprint,
        executable="/opt/lagniappe-mcp",
        required=True,
    )
    snapshot = object()
    installed: list[tuple[str, str, str | None, bool]] = []
    new_fingerprint = "c" * 64

    async def valid_key(
        _site_url: str,
        _key: str,
        *,
        expected_hash: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert expected_hash == "abcdefghijkl"
        actor = _actor()
        return actor["user"], actor["credential"]

    def install(
        name: str,
        executable: str,
        *,
        expected_fingerprint: str | None,
        required: bool = False,
    ) -> str:
        installed.append((name, executable, expected_fingerprint, required))
        return new_fingerprint if len(installed) == 1 else old_fingerprint

    monkeypatch.setattr(
        cli_module,
        "load_profile_snapshot",
        lambda _name: (deepcopy(profile), snapshot),
    )
    monkeypatch.setattr(cli_module, "_validate_key", valid_key)
    monkeypatch.setattr(cli_module, "_safe_root", lambda value: value)
    monkeypatch.setattr(
        cli_module, "console_executable", lambda: "/opt/lagniappe-mcp"
    )
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)
    monkeypatch.setattr(cli_module, "install_entry", install)
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda _profile, *, expected_snapshot: (
            expected_snapshot is snapshot or pytest.fail("stale profile snapshot")
        )
        and (_ for _ in ()).throw(ConfigurationError("save_failed", "failed")),
    )

    with pytest.raises(ConfigurationError) as caught:
        asyncio.run(
            cli_module._configure_codex(
                SimpleNamespace(
                    profile="personal",
                    remove=False,
                    url="https://example.com",
                    allowed_root=[],
                    trial_required=False,
                )
            )
        )

    assert caught.value.code == "save_failed"
    assert installed == [
        ("personal", "/opt/lagniappe-mcp", old_fingerprint, False),
        ("personal", "/opt/lagniappe-mcp", new_fingerprint, True),
    ]


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_configure_codex
@pytest.mark.parametrize(
    "new_executable",
    ["/opt/lagniappe-old", "/opt/lagniappe-new"],
    ids=("same-fingerprint", "changed-fingerprint"),
)
def test_configure_manual_fallback_does_not_orphan_an_existing_owned_entry(
    monkeypatch: pytest.MonkeyPatch,
    new_executable: str,
) -> None:
    from lagniappe_mcp import cli as cli_module

    profile = _profile_value()
    _old_block, old_fingerprint = cli_module.render_entry(
        "personal", "/opt/lagniappe-old"
    )
    profile["client"].update(
        mode="automatic",
        registered=True,
        fingerprint=old_fingerprint,
        executable="/opt/lagniappe-old",
    )
    snapshot = object()

    async def valid_key(
        site_url: str, key: str, *, expected_hash: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert (site_url, key, expected_hash) == (
            "https://example.com",
            "secret-key",
            "abcdefghijkl",
        )
        actor = _actor()
        return actor["user"], actor["credential"]

    monkeypatch.setattr(
        cli_module,
        "load_profile_snapshot",
        lambda _name: (profile, snapshot),
    )
    monkeypatch.setattr(cli_module, "_validate_key", valid_key)
    monkeypatch.setattr(cli_module, "_safe_root", lambda value: value)
    monkeypatch.setattr(cli_module, "console_executable", lambda: new_executable)
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)

    def manual_required(*_args: Any, **_kwargs: Any) -> str:
        raise ConfigurationError(
            "manual_configuration_required", "safe editing is unavailable"
        )

    monkeypatch.setattr(cli_module, "install_entry", manual_required)
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda *_args, **_kwargs: pytest.fail(
            "a failed identity change must not rewrite the owned profile"
        ),
    )
    args = SimpleNamespace(
        profile="personal",
        remove=False,
        url="https://example.com",
        allowed_root=[],
    )

    with pytest.raises(ConfigurationError) as caught:
        asyncio.run(cli_module._configure_codex(args))

    assert caught.value.code == "managed_entry_update_requires_removal"
    assert "no profile or ownership metadata was changed" in caught.value.message
    assert profile["client"] == {
        "name": "lagniappe-personal",
        "mode": "automatic",
        "registered": True,
        "fingerprint": old_fingerprint,
        "executable": "/opt/lagniappe-old",
        "required": False,
    }


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_run
def test_local_credential_and_profile_removal_are_distinct_state_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import cli as cli_module

    profile = _profile_value()
    saved: list[dict[str, Any]] = []
    deleted: list[str] = []
    snapshot = object()
    monkeypatch.setattr(
        cli_module,
        "load_profile_snapshot",
        lambda _name: (deepcopy(profile), snapshot),
    )
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda value, *, expected_snapshot: (
            expected_snapshot is snapshot or pytest.fail("stale profile snapshot")
        )
        and saved.append(value),
    )
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)

    remove_args = SimpleNamespace(
        profile="personal",
        credential_action="remove",
    )
    assert asyncio.run(cli_module._credentials(remove_args)) == 0
    assert saved[-1]["api_key"] is None
    assert saved[-1]["credential"] == {}
    assert saved[-1]["client"] == profile["client"]

    async def valid_replacement(
        site_url: str, key: str, *, expected_hash: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert (site_url, key, expected_hash) == (
            "https://example.com",
            "replacement-key",
            "abcdefghijkl",
        )
        actor = _actor()
        actor["credential"]["generation"] = 2
        return actor["user"], actor["credential"]

    monkeypatch.setattr(cli_module, "_prompt_key", lambda: "replacement-key")
    monkeypatch.setattr(cli_module, "_validate_key", valid_replacement)
    set_args = SimpleNamespace(profile="personal", credential_action="set")
    assert asyncio.run(cli_module._credentials(set_args)) == 0
    assert saved[-1]["api_key"] == "replacement-key"
    assert saved[-1]["credential"]["generation"] == 2
    assert saved[-1]["actor"]["hash"] == "abcdefghijkl"

    saved.clear()

    async def invalid_replacement(*_args: Any, **_kwargs: Any):
        raise ConfigurationError(
            "actor_mismatch", "The replacement belongs to another actor."
        )

    monkeypatch.setattr(cli_module, "_validate_key", invalid_replacement)
    with pytest.raises(ConfigurationError) as rejected:
        asyncio.run(cli_module._credentials(set_args))
    assert rejected.value.code == "actor_mismatch"
    assert saved == []

    monkeypatch.setattr(
        cli_module,
        "delete_profile",
        lambda name, *, expected_snapshot: (
            expected_snapshot is snapshot or pytest.fail("stale profile snapshot")
        )
        and deleted.append(name),
    )
    with pytest.raises(ConfigurationError) as registered:
        cli_module._remove_profile("personal")
    assert registered.value.code == "client_still_registered"
    assert deleted == []

    profile["client"]["registered"] = False
    profile["client"]["fingerprint"] = None
    assert cli_module._remove_profile("personal") == 0
    assert deleted == ["personal"]


# @pair mcp-adapter:product-contract
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (AdapterError("unauthorized", "The key is invalid for this site.", status=401), "unauthorized"),
        (ConfigurationError("invalid_credentials", "The API credential is inactive."), "invalid_credentials"),
        (ConfigurationError("invalid_credentials", "The API credential is expired."), "invalid_credentials"),
        (ConfigurationError("actor_mismatch", "The key belongs to another actor."), "actor_mismatch"),
    ],
    ids=("wrong-site-or-invalid", "inactive", "expired", "different-actor"),
)
def test_rejected_credential_replacement_preserves_the_saved_profile(
    monkeypatch: pytest.MonkeyPatch,
    failure: AdapterError,
    expected_code: str,
) -> None:
    from lagniappe_mcp import cli as cli_module

    profile = _profile_value()
    snapshot = object()
    saved: list[dict[str, Any]] = []

    async def reject(*_args: Any, **_kwargs: Any):
        raise failure

    monkeypatch.setattr(
        cli_module,
        "load_profile_snapshot",
        lambda _name: (deepcopy(profile), snapshot),
    )
    monkeypatch.setattr(cli_module, "_prompt_key", lambda: "rejected-key")
    monkeypatch.setattr(cli_module, "_validate_key", reject)
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda value, **_kwargs: saved.append(value),
    )

    with pytest.raises(AdapterError) as rejected:
        asyncio.run(
            cli_module._credentials(
                SimpleNamespace(profile="personal", credential_action="set")
            )
        )

    assert rejected.value.code == expected_code
    assert saved == []
    assert profile["api_key"] == "secret-key"
    assert profile["credential"]["generation"] == 1


# @pair mcp-adapter:product-contract
def test_removed_local_credential_takes_effect_only_in_a_new_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import cli as cli_module

    config_home = tmp_path / "lagniappe-mcp-config"
    monkeypatch.setenv("LAGNIAPPE_MCP_CONFIG_HOME", str(config_home))
    save_profile(_profile_value())
    already_running = connection_from_profile("personal")
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)

    assert asyncio.run(
        cli_module._credentials(
            SimpleNamespace(profile="personal", credential_action="remove")
        )
    ) == 0
    assert already_running.api_key == "secret-key"
    with pytest.raises(ConfigurationError) as restarted:
        connection_from_profile("personal")
    assert restarted.value.code == "missing_credentials"


# @pair mcp-adapter:product-contract
def test_configure_remove_falls_back_without_claiming_manual_removal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lagniappe_mcp import cli as cli_module

    profile = _profile_value()
    snapshot = object()
    monkeypatch.setattr(
        cli_module, "load_profile_snapshot", lambda _name: (profile, snapshot)
    )
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)

    def manual_required(*_args: Any, **_kwargs: Any) -> None:
        raise ConfigurationError(
            "manual_configuration_required", "manual editing required"
        )

    monkeypatch.setattr(cli_module, "remove_entry", manual_required)
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda _profile, **_kwargs: pytest.fail(
            "unverified removal must not update the profile"
        ),
    )
    args = SimpleNamespace(
        profile="personal",
        remove=True,
        url=None,
        allowed_root=[],
    )

    assert asyncio.run(cli_module._configure_codex(args)) == 0
    output = capsys.readouterr().out
    assert "Remove this exact managed lagniappe-personal block" in output
    assert "[mcp_servers.lagniappe-personal]" in output
    assert profile["client"]["registered"] is True


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_configure_codex
def test_manual_configuration_converges_only_after_exact_entry_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import cli as cli_module

    profile = _profile_value()
    profile["client"].update(mode="manual", registered=False)
    snapshot = object()
    saved: list[dict[str, Any]] = []
    removed: list[tuple[str, str]] = []
    marker = object()
    monkeypatch.setattr(
        cli_module, "load_profile_snapshot", lambda _name: (profile, snapshot)
    )
    monkeypatch.setattr(
        cli_module,
        "inspect_entry",
        lambda name, *, expected_fingerprint: (
            "",
            {},
            marker,
            None,
        )
        if (name, expected_fingerprint) == ("personal", "a" * 64)
        else pytest.fail("manual ownership was not checked exactly"),
    )
    monkeypatch.setattr(
        cli_module,
        "remove_entry",
        lambda name, *, expected_fingerprint: removed.append(
            (name, expected_fingerprint)
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "save_profile",
        lambda value, *, expected_snapshot: (
            expected_snapshot is snapshot or pytest.fail("stale profile snapshot")
        )
        and saved.append(deepcopy(value)),
    )
    monkeypatch.setattr(cli_module, "_confirm", lambda _message: None)
    args = SimpleNamespace(
        profile="personal",
        remove=True,
        url=None,
        allowed_root=[],
    )

    assert asyncio.run(cli_module._configure_codex(args)) == 0
    assert removed == [("personal", "a" * 64)]
    assert saved[-1]["client"]["registered"] is False
    assert saved[-1]["client"]["fingerprint"] is None

    removed.clear()
    saved.clear()
    profile["client"].update(mode="manual", registered=False, fingerprint="a" * 64)
    monkeypatch.setattr(
        cli_module,
        "inspect_entry",
        lambda *_args, **_kwargs: ("", {}, None, None),
    )
    assert asyncio.run(cli_module._configure_codex(args)) == 0
    assert removed == []
    assert saved[-1]["client"]["fingerprint"] is None


# @pair mcp-adapter:product-contract
def test_cli_entrypoint_bounds_errors_and_routes_commands(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lagniappe_mcp import cli as cli_module

    routed: list[str] = []

    async def configured(args: SimpleNamespace) -> int:
        routed.append(args.command)
        return 7

    monkeypatch.setattr(cli_module, "_configure_codex", configured)
    assert asyncio.run(cli_module._run(SimpleNamespace(command="configure"))) == 7

    async def rejected(args: SimpleNamespace) -> int:
        routed.append(args.command)
        raise ConfigurationError("invalid_credentials", "Bounded failure.")

    monkeypatch.setattr(cli_module, "_run", rejected)
    assert cli_module.main(["check", "--from-env"]) == 1
    assert routed == ["configure", "check"]
    assert "invalid_credentials" in capsys.readouterr().err

    oversized_argument = "X" * (MAX_STDERR_BYTES * 2)
    assert cli_module.main([oversized_argument]) == 1
    parser_error = capsys.readouterr().err
    assert len(parser_error.encode("utf-8")) <= MAX_STDERR_BYTES
    assert oversized_argument not in parser_error
    accidental_secret = "lgn_accidentally-pasted-secret"
    assert cli_module.main(["check", "--api-key", accidental_secret]) == 1
    assert accidental_secret not in capsys.readouterr().err

    async def mixed_failure(_args: SimpleNamespace) -> int:
        raise ExceptionGroup(
            "mixed failure",
            [BrokenPipeError(), RuntimeError("must remain visible")],
        )

    monkeypatch.setattr(cli_module, "_run", mixed_failure)
    assert cli_module.main(["check", "--from-env"]) == 1
    assert "adapter_failure" in capsys.readouterr().err


# @pair mcp-adapter:product-contract
def test_schema_rejects_dangling_refs_and_non_finite_json() -> None:
    with pytest.raises(SchemaError, match="dangling"):
        validate_schema_document(
            {
                "type": "object",
                "properties": {"value": {"$ref": "#/$defs/missing"}},
                "$defs": {},
            }
        )
    with pytest.raises(SchemaError) as error:
        compact_json({"value": float("nan")})
    assert error.value.code == "invalid_json"
    with pytest.raises(SchemaError) as dynamic:
        validate_schema_document({"$dynamicRef": "https://attacker.invalid/schema"})
    assert dynamic.value.code == "unsupported_schema"
    with pytest.raises(SchemaError) as recursive:
        validate_schema_document(
            {
                "type": "object",
                "properties": {"child": {"$ref": "#"}},
            }
        )
    assert recursive.value.code == "unsupported_schema"

    # A top-level applicator can reject plan_id even after it is inserted into
    # ``properties``.  Refuse those future catalog shapes at startup instead of
    # advertising an unusable or misleading MCP tool schema.
    for constrained in (
        {"allOf": [{"type": "object", "additionalProperties": False}]},
        {"propertyNames": {"pattern": "^query$"}},
        {"minProperties": 1},
        {"maxProperties": 1},
        {"const": {"query": "fixed"}},
        {"enum": [{"query": "fixed"}]},
    ):
        with pytest.raises(SchemaError) as reserved:
            inject_plan_id(
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    **constrained,
                }
            )
        assert reserved.value.code == "reserved_tool_argument"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def test_untrusted_schema_work_is_rejected_before_general_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator_called = False

    def unexpected_general_validation(_schema: Any) -> None:
        nonlocal validator_called
        validator_called = True
        raise AssertionError("unsafe schema reached the general validator")

    monkeypatch.setattr(
        schema_module.Draft202012Validator,
        "check_schema",
        unexpected_general_validation,
    )

    catastrophic_regex = {
        "type": "object",
        "properties": {
            "value": {
                "type": "string",
                "pattern": r"^(a+)+$",
            }
        },
    }
    started = time.monotonic()
    with pytest.raises(SchemaError) as regex_error:
        validate_schema_document(catastrophic_regex)
    assert regex_error.value.code == "unsupported_schema"

    # Each definition is tiny, but following both references doubles the
    # general validator's work at every level.  The preflight expansion budget
    # must reject this compact DAG without traversing its exponential closure.
    definitions: dict[str, Any] = {"level_0": {"type": "string"}}
    for level in range(1, 20):
        previous = f"#/$defs/level_{level - 1}"
        definitions[f"level_{level}"] = {
            "allOf": [{"$ref": previous}, {"$ref": previous}]
        }
    exponential_applicators = {
        "$defs": definitions,
        "$ref": "#/$defs/level_19",
    }
    with pytest.raises(SchemaError) as applicator_error:
        validate_schema_document(exponential_applicators)
    assert applicator_error.value.code == "schema_too_complex"

    with pytest.raises(SchemaError) as unbounded_unique_items:
        validate_schema_document(
            {
                "type": "array",
                "items": {"type": "object"},
                "uniqueItems": True,
            }
        )
    assert unbounded_unique_items.value.code == "schema_too_complex"
    assert validator_called is False
    assert time.monotonic() - started < 1.0


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/schema.py::validate_schema_document
def test_schema_subset_preserves_current_proposal_contract_features() -> None:
    schema = {
        "type": "object",
        "$defs": {
            "create_page": {
                "type": "object",
                "required": ["type", "data"],
                "properties": {
                    "type": {"type": "string", "const": "create_page"},
                    "data": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "string"},
                            "page_action": {"type": "string"},
                        },
                        "allOf": [
                            {
                                "anyOf": [
                                    {"required": ["page"]},
                                    {"required": ["page_action"]},
                                ]
                            }
                        ],
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            }
        },
        "required": ["actions", "retrieval_terms"],
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "oneOf": [{"$ref": "#/$defs/create_page"}],
                    "discriminator": {
                        "propertyName": "type",
                        "mapping": {
                            "create_page": "#/$defs/create_page",
                        },
                    },
                },
            },
            "retrieval_terms": {
                "type": "array",
                "items": {"type": "string", "maxLength": 80},
                "minItems": 2,
                "maxItems": 2,
                "uniqueItems": True,
            },
        },
        "additionalProperties": False,
    }

    assert validate_schema_document(schema, input_root=True) == schema
    validate_value(
        schema,
        {
            "actions": [
                {
                    "type": "create_page",
                    "data": {"page": "hash:abcdefghijkl"},
                }
            ],
            "retrieval_terms": ["primary", "secondary"],
        },
        phase="proposal",
    )


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/catalog.py::catalog_tools
def test_catalog_requires_complete_frozen_metadata_and_result_paths() -> None:
    catalog = asyncio.run(_WorkflowREST().startup())[2]
    converted = catalog_tools(catalog)
    assert converted[0].result_paths == {
        "primary_collection": "$",
        "pagination": None,
    }

    for mutate in (
        lambda value: value.pop("reference_format"),
        lambda value: value.update(selected_count=2),
        lambda value: value["tools"][0].pop("result_paths"),
        lambda value: value["tools"][0].update(result_paths=[]),
    ):
        incompatible = deepcopy(catalog)
        mutate(incompatible)
        with pytest.raises(TransportError) as error:
            catalog_tools(incompatible)
        assert error.value.code == "invalid_catalog"

    invalid_names = ("start_ask", "BadName", "bad-name", "x" * 65)
    for name in invalid_names:
        incompatible = deepcopy(catalog)
        incompatible["tools"][0]["name"] = name
        with pytest.raises(TransportError) as error:
            catalog_tools(incompatible)
        assert error.value.code == "invalid_catalog"

    conflict = deepcopy(catalog)
    conflict["tools"][0]["input_schema"]["properties"]["plan_id"] = {
        "type": "string"
    }
    with pytest.raises(SchemaError) as reserved:
        catalog_tools(conflict)
    assert reserved.value.code == "reserved_tool_argument"

    too_many = deepcopy(catalog)
    template = too_many["tools"][0]
    too_many["tools"] = [
        {**deepcopy(template), "name": f"read_{index}"} for index in range(57)
    ]
    too_many["selected_count"] = len(too_many["tools"])
    with pytest.raises(TransportError) as count_error:
        build_tool_registry(too_many)
    assert count_error.value.code == "catalog_too_large"


# @pair mcp-adapter:product-contract
def test_model_visibility_screen_rejects_catalog_reflection_and_preserves_safe_result_paths() -> None:
    api_key = "lgn_exact_catalog_reflection_secret"
    base_catalog = asyncio.run(_WorkflowREST().startup())[2]
    safe_catalog = deepcopy(base_catalog)
    safe_catalog["tools"][0]["description"] = (
        "Explain storage.googleapis.com, X-Goog-Signature, and upload_id fields."
    )
    safe_catalog["tools"][0]["result_paths"] = {
        "primary_collection": "$.items[*].url",
        "pagination": "$.next_page",
    }

    class StartupREST(_WorkflowREST):
        def __init__(self, catalog: dict[str, Any], actor: dict[str, Any]) -> None:
            super().__init__()
            self.catalog = catalog
            self.startup_actor = actor

        async def startup(self):
            return {"version": "v1"}, self.startup_actor, self.catalog

    async def initialize(
        catalog: dict[str, Any], actor: dict[str, Any]
    ) -> LagniappeAdapter:
        rest = StartupREST(catalog, actor)
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), api_key),
            rest=rest,  # type: ignore[arg-type]
        )
        try:
            await adapter.initialize()
        except BaseException:
            await adapter.aclose()
            raise
        return adapter

    safe_adapter = asyncio.run(initialize(safe_catalog, _actor()))
    assert safe_adapter.tools["search"].as_mcp_tool().meta == {
        "lagniappe/resultPaths": {
            "primary_collection": "$.items[*].url",
            "pagination": "$.next_page",
        }
    }
    assert safe_adapter.tools["search"].description == (
        "Explain storage.googleapis.com, X-Goog-Signature, and upload_id fields."
    )
    asyncio.run(safe_adapter.aclose())

    hostile_values: list[tuple[dict[str, Any], dict[str, Any]]] = []
    reflected_description = deepcopy(base_catalog)
    reflected_description["tools"][0]["description"] = (
        f"Compromised metadata reflected Bearer {api_key}."
    )
    hostile_values.append((reflected_description, _actor()))

    reflected_result_path = deepcopy(base_catalog)
    reflected_result_path["tools"][0]["result_paths"] = {
        "primary_collection": _signed_download_url(),
        "pagination": None,
    }
    hostile_values.append((reflected_result_path, _actor()))

    reflected_actor = _actor()
    reflected_actor["user"]["name"] = api_key
    hostile_values.append((deepcopy(base_catalog), reflected_actor))

    for catalog, actor in hostile_values:
        with pytest.raises(TransportError) as rejected:
            asyncio.run(initialize(catalog, actor))
        rendered = rejected.value.render()
        assert rejected.value.code == "unsafe_transport_extension"
        assert api_key not in rendered
        assert "storage.googleapis.com" not in rendered
        assert "x-goog-signature" not in rendered.casefold()


# @pair mcp-adapter:product-contract
def test_model_visibility_screen_rejects_successful_output_reflection() -> None:
    api_key = "lgn_exact_result_reflection_secret"

    class ReflectingREST(_WorkflowREST):
        result: Any = []

        async def request_json(
            self, method: str, target: str, *, body: Any = None, **kwargs: Any
        ):
            if target.endswith("/tools/search"):
                self.requests.append((method, target, body))
                return {"result": deepcopy(self.result)}, "request-search"
            return await super().request_json(method, target, body=body, **kwargs)

    async def exercise() -> list[str]:
        rest = ReflectingREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), api_key),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        rest.result = [
            "https://example.com/tools/reports/abcdefghijkl",
            "$.items[*].url",
            "ordinary storage guidance",
            "storage.googleapis.com is the documented storage hostname",
            "X-Goog-Signature and upload_id are transport field names",
        ]
        safe = await adapter.execute(
            "search", {"plan_id": "abcdefghijkl", "query": "safe"}
        )
        for reflected in (
            f"prefix {api_key} suffix",
            _signed_download_url(),
            "?X-Goog-Signature=opaque",
            "upload_id=opaque",
        ):
            rest.result = [reflected]
            with pytest.raises(TransportError) as rejected:
                await adapter.execute(
                    "search",
                    {"plan_id": "abcdefghijkl", "query": "unsafe"},
                )
            rendered = rejected.value.render()
            assert rejected.value.code == "unsafe_transport_extension"
            assert api_key not in rendered
            assert "storage.googleapis.com" not in rendered
            assert "x-goog-signature" not in rendered.casefold()
            assert "upload_id" not in rendered.casefold()
        await adapter.aclose()
        return safe.value

    assert asyncio.run(exercise()) == [
        "https://example.com/tools/reports/abcdefghijkl",
        "$.items[*].url",
        "ordinary storage guidance",
        "storage.googleapis.com is the documented storage hostname",
        "X-Goog-Signature and upload_id are transport field names",
    ]

    for reflected in (
        {"download_url": "https://example.com/private"},
        {"session_url": "opaque-session"},
        {"upload_id": "opaque-id"},
    ):
        with pytest.raises(TransportError) as rejected:
            _reject_private_model_data(reflected, bearer=api_key)
        assert rejected.value.code == "unsafe_transport_extension"

    with pytest.raises(TransportError) as encoded_bearer:
        _reject_private_model_data((b"ABC",), bearer="QUJD")
    assert encoded_bearer.value.code == "unsafe_transport_extension"


# @pair mcp-adapter:product-contract
def test_get_file_schema_projects_every_transport_extension() -> None:
    projected = get_file_output_schema(
        {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "mimetype": {"type": "string"},
                "summary": {"type": "string"},
                "content": {"type": "string"},
                "session_url": {"type": "string"},
                "original_file": {
                    "type": "object",
                    "required": ["supported", "attached", "session_token"],
                    "properties": {
                        "supported": {"type": "boolean"},
                        "attached": {"type": "boolean"},
                        "reason": {"type": "string"},
                        "download_url": {"type": "string"},
                        "expires_in": {"type": "integer"},
                        "session_token": {"type": "string"},
                    },
                    "additionalProperties": True,
                }
            },
            "additionalProperties": True,
        }
    )

    assert set(projected["properties"]) == {
        "hash",
        "display_name",
        "filename",
        "mimetype",
        "large",
        "summary",
        "permissions",
        "url",
        "content",
        "error",
        "original_file",
        "delivery",
    }
    assert projected["additionalProperties"] is False
    with pytest.raises(SchemaError):
        validate_value(
            projected,
            {
                "filename": "safe.txt",
                "original_file": {"supported": False, "attached": False},
                "signed_url": "https://storage.googleapis.com/private",
                "delivery": {"kind": "none"},
            },
            phase="output",
        )
    original = projected["properties"]["original_file"]
    assert set(original["properties"]) == {"supported", "attached", "reason"}
    assert original["required"] == ["supported", "attached"]
    assert original["additionalProperties"] is False


# @pair mcp-adapter:product-contract
def test_storage_url_requires_exact_resumable_and_signed_parameters() -> None:
    valid_upload = (
        "https://storage.googleapis.com/upload/storage/v1/b/bucket/o"
        "?uploadType=resumable&upload_id=opaque"
    )
    official_json_api_upload = (
        "https://storage.googleapis.com/upload/storage/v1/b/bucket/o"
        "?uploadType=resumable&name=tmp%2Ffile.png"
        "&ifGenerationMatch=0&upload_id=opaque"
    )
    assert validate_storage_url(valid_upload, upload=True) == valid_upload
    assert (
        validate_storage_url(official_json_api_upload, upload=True)
        == official_json_api_upload
    )
    assert validate_storage_url(_signed_download_url(), upload=False).startswith(
        "https://storage.googleapis.com/"
    )

    for unsafe in (
        "https://storage.googleapis.com/upload/storage/v1/b/bucket/o?upload_id=opaque",
        valid_upload + "&upload_id=second",
        valid_upload.replace("upload_id=opaque", "upload_id="),
        valid_upload + "&name=",
        valid_upload + "&ifGenerationMatch=1",
        valid_upload + "&unexpected=value",
    ):
        with pytest.raises(TransportError):
            validate_storage_url(unsafe, upload=True)
    with pytest.raises(TransportError):
        validate_storage_url(
            _signed_download_url(**{"X-Goog-Expires": "301"}), upload=False
        )


# @pair mcp-adapter:product-contract
def test_site_url_normalizes_only_canonical_https_or_loopback_origins() -> None:
    assert normalize_site_url("https://EXAMPLE.com:443/").origin == "https://example.com"
    assert (
        normalize_site_url("http://127.0.0.1:5050").origin
        == "http://127.0.0.1:5050"
    )
    assert normalize_site_url("http://[::1]:5050").origin == "http://[::1]:5050"
    for unsafe in (
        "http://example.com",
        "https://example.com:444",
        "https://user@example.com",
        "https://example.com/path",
        "https://example.com./",
        "https://münich.example",
        "https://bad_host.example",
        "http://127.0.0.1:0",
    ):
        with pytest.raises(ConfigurationError):
            normalize_site_url(unsafe)


# @pair mcp-adapter:product-contract
def test_openapi_compatibility_check_is_exact_and_runs_only_for_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _compatible_openapi()
    validate_openapi_compatibility(document)

    wrong_contract = deepcopy(document)
    wrong_contract["components"]["schemas"]["PlanContract"]["properties"][
        "contract_version"
    ]["const"] = 5
    with pytest.raises(TransportError) as contract_error:
        validate_openapi_compatibility(wrong_contract)
    assert contract_error.value.code == "incompatible_contract"

    missing_route = deepcopy(document)
    del missing_route["paths"]["/api/v1/plans/{plan_id}/submit"]
    with pytest.raises(TransportError) as route_error:
        validate_openapi_compatibility(missing_route)
    assert route_error.value.code == "incompatible_openapi"

    extra_route = deepcopy(document)
    extra_route["paths"]["/api/v1/arbitrary"] = {"post": {}}
    with pytest.raises(TransportError) as surface_error:
        validate_openapi_compatibility(extra_route)
    assert surface_error.value.code == "incompatible_openapi"

    open_upload = deepcopy(document)
    open_upload["components"]["schemas"]["UploadFile"][
        "additionalProperties"
    ] = True
    with pytest.raises(TransportError) as upload_error:
        validate_openapi_compatibility(open_upload)
    assert upload_error.value.code == "incompatible_openapi"

    unbound_finalize = deepcopy(document)
    unbound_finalize["paths"]["/api/v1/plans/{plan_id}/uploads/finalize"][
        "post"
    ]["requestBody"]["content"]["application/json"]["schema"]["required"] = []
    with pytest.raises(TransportError) as batch_error:
        validate_openapi_compatibility(unbound_finalize)
    assert batch_error.value.code == "incompatible_openapi"

    from lagniappe_mcp import server as server_module

    class FakeREST:
        checked = False

        async def check_openapi_compatibility(self) -> None:
            self.checked = True

    class FakeAdapter:
        current: "FakeAdapter | None" = None

        def __init__(self, _config: ConnectionConfig) -> None:
            self.rest = FakeREST()
            self.actor: dict[str, Any] | None = None
            FakeAdapter.current = self

        async def initialize(self) -> None:
            # Normal server startup remains the latency-bounded three-resource
            # bootstrap; only the explicit diagnostic adds OpenAPI retrieval.
            assert self.rest.checked is False
            self.actor = _actor()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(server_module, "LagniappeAdapter", FakeAdapter)
    config = ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    actor_name, actor_hash = asyncio.run(server_module.check(config))
    assert (actor_name, actor_hash) == ("Person", "abcdefghijkl")
    assert FakeAdapter.current is not None
    assert FakeAdapter.current.rest.checked is True


class _CaptureTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.headers: httpx.Headers | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.headers = request.headers
        return httpx.Response(
            200,
            headers={"Content-Length": "3", "Content-Type": "image/png"},
            content=b"png",
            request=request,
        )


# @pair mcp-adapter:product-contract
def test_media_download_does_not_inherit_client_credentials_or_cookies() -> None:
    async def exercise() -> tuple[bytes, str, httpx.Headers]:
        transport = _CaptureTransport()
        storage = httpx.AsyncClient(
            transport=transport,
            auth=httpx.BasicAuth("wrong", "secret"),
            cookies={"session": "secret"},
        )
        config = ConnectionConfig(
            normalize_site_url("https://example.com"), "api-secret"
        )
        rest = RESTClient(config, storage_client=storage)
        try:
            data, mime = await rest.download_media(_signed_download_url(), cap=1024)
            assert transport.headers is not None
            return data, mime, transport.headers
        finally:
            await rest.aclose()
            await storage.aclose()

    data, mime, headers = asyncio.run(exercise())
    assert (data, mime) == (b"png", "image/png")
    assert "authorization" not in headers
    assert "cookie" not in headers


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
def test_original_media_enforces_length_cap_status_and_redirect_boundaries() -> None:
    class MediaTransport(httpx.AsyncBaseTransport):
        def __init__(self, outcomes: list[tuple[int, dict[str, str], bytes]]) -> None:
            self.outcomes = list(outcomes)
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            status, headers, data = self.outcomes.pop(0)
            return httpx.Response(
                status,
                headers=headers,
                stream=httpx.ByteStream(data),
                request=request,
            )

    async def exercise() -> tuple[list[str], int]:
        transport = MediaTransport(
            [
                (200, {"Content-Type": "image/png"}, b"x"),
                (
                    200,
                    {"Content-Type": "image/png", "Content-Length": "2"},
                    b"x",
                ),
                (
                    200,
                    {"Content-Type": "image/png", "Content-Length": "5"},
                    b"12345",
                ),
                (302, {"Location": "https://attacker.invalid"}, b""),
                (
                    404,
                    {"Content-Type": "application/json", "Content-Length": "2"},
                    b"{}",
                ),
            ]
        )
        storage = httpx.AsyncClient(transport=transport)
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            storage_client=storage,
        )
        codes: list[str] = []
        try:
            for cap in (16, 16, 4, 16, 16):
                with pytest.raises(TransportError) as caught:
                    await rest.download_media(_signed_download_url(), cap=cap)
                codes.append(caught.value.code)
            return codes, transport.calls
        finally:
            await rest.aclose()
            await storage.aclose()

    codes, calls = asyncio.run(exercise())
    assert codes == [
        "invalid_download",
        "invalid_download",
        "media_too_large",
        "redirect_rejected",
        "download_failed",
    ]
    assert calls == 5


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
@pytest.mark.parametrize(
    ("mime_type", "kind"),
    [("image/png", "image"), ("audio/mpeg", "audio")],
)
def test_original_media_delivery_matches_the_emitted_content_index(
    mime_type: str,
    kind: str,
) -> None:
    rest = _WorkflowREST()

    async def download_media(_url: str, *, cap: int):
        assert cap == MAX_MEDIA_RAW_BYTES
        return b"original-bytes", mime_type

    rest.download_media = download_media
    adapter = LagniappeAdapter(
        ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
        rest=rest,  # type: ignore[arg-type]
    )
    raw = {
        "content": "extracted text",
        "mimetype": mime_type,
        "original_file": {
            "supported": True,
            "attached": False,
            "download_url": _signed_download_url(),
            "expires_in": 300,
        },
    }
    result = asyncio.run(
        adapter._project_file_result(raw, {"include_original": True})
    )
    rendered = _success_result(result).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert result.value["delivery"] == {
        "kind": kind,
        "mime_type": mime_type,
        "size_bytes": len(b"original-bytes"),
        "content_index": 1,
    }
    assert rendered["content"][1]["type"] == kind
    assert rendered["content"][1]["mimeType"] == mime_type
    assert "storage.googleapis.com" not in json.dumps(rendered)
    asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
def test_original_media_rejects_unsupported_binary_after_safe_download() -> None:
    rest = _WorkflowREST()

    async def download_media(_url: str, *, cap: int):
        assert cap == MAX_MEDIA_RAW_BYTES
        return b"pdf", "application/pdf"

    rest.download_media = download_media
    adapter = LagniappeAdapter(
        ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
        rest=rest,  # type: ignore[arg-type]
    )
    raw = {
        "content": "extracted text",
        "mimetype": "application/pdf",
        "original_file": {
            "supported": True,
            "attached": False,
            "download_url": _signed_download_url(),
            "expires_in": 300,
        },
    }
    try:
        with pytest.raises(TransportError) as caught:
            asyncio.run(
                adapter._project_file_result(raw, {"include_original": True})
            )
        assert caught.value.code == "unsupported_media"
        assert "storage.googleapis.com" not in caught.value.render()
    finally:
        asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
def test_api_request_uses_only_explicit_bearer_credentials() -> None:
    class APICaptureTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.request: httpx.Request | None = None

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.request = request
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"ok": True},
                request=request,
            )

    async def exercise() -> tuple[Any, httpx.Request]:
        transport = APICaptureTransport()
        injected = httpx.AsyncClient(
            transport=transport,
            auth=httpx.BasicAuth("wrong", "secret"),
            cookies={"session": "secret"},
            headers={"X-Unrelated-Default": "must-not-leak"},
        )
        config = ConnectionConfig(
            normalize_site_url("https://example.com"), "api-secret"
        )
        rest = RESTClient(config, client=injected)
        try:
            value, _request_id = await rest.request_json(
                "POST", "plans", body={"kind": "ask"}
            )
            assert transport.request is not None
            return value, transport.request
        finally:
            await rest.aclose()
            await injected.aclose()

    value, request = asyncio.run(exercise())
    assert value == {"ok": True}
    assert request.headers["authorization"] == "Bearer api-secret"
    assert request.headers["content-type"] == "application/json"
    assert "cookie" not in request.headers
    assert "x-unrelated-default" not in request.headers
    assert request.content == b'{"kind":"ask"}'


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/errors.py::AdapterError
def test_bounded_error_rendering_remains_valid_json() -> None:
    error = AdapterError(
        "validation_failed",
        "The request contains invalid fields.",
        status=422,
        request_id="request-123",
        details={"items": ["x" * 1024] * 20},
    )

    rendered = error.render()
    assert len(rendered.encode("utf-8")) <= MAX_ERROR_BYTES
    assert json.loads(rendered) == {
        "code": "validation_failed",
        "message": "The request contains invalid fields.",
        "retryable": False,
        "http_status": 422,
        "request_id": "request-123",
        "details": {"truncated": True},
    }

    control_heavy = AdapterError(
        "\x00" * 200,
        "\x00" * 2048,
        retryable=True,
        status=503,
    ).render()
    assert len(control_heavy.encode("utf-8")) <= MAX_ERROR_BYTES
    assert json.loads(control_heavy) == {
        "code": "adapter_error",
        "message": "The bounded error could not be rendered safely.",
        "retryable": True,
        "http_status": 503,
    }


# @pair mcp-adapter:product-contract
def test_api_errors_redact_credentials_and_duplicate_json_is_rejected() -> None:
    signed = _signed_download_url()

    async def exercise() -> tuple[AdapterError, TransportError]:
        responses = [
            httpx.Response(
                422,
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": "super-secret",
                },
                json={
                    "error": {
                        "code": "validation_failed",
                        "message": f"super-secret appeared beside {signed}",
                        "details": {
                            "api_key": "super-secret",
                            "nested": [signed, "upload_id=opaque"],
                        },
                    }
                },
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b'{"value":1,"value":2}',
            ),
        ]

        async def handler(request: httpx.Request) -> httpx.Response:
            response = responses.pop(0)
            response.request = request
            return response

        injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "super-secret"),
            client=injected,
        )
        try:
            with pytest.raises(AdapterError) as api_error:
                await rest.request_json("GET", "me")
            with pytest.raises(TransportError) as duplicate_error:
                await rest.request_json("GET", "me")
            return api_error.value, duplicate_error.value
        finally:
            await rest.aclose()
            await injected.aclose()

    api_error, duplicate_error = asyncio.run(exercise())
    rendered = api_error.render()
    assert api_error.code == "validation_failed"
    assert "super-secret" not in rendered
    assert "storage.googleapis.com" not in rendered
    assert "upload_id=opaque" not in rendered
    assert duplicate_error.code == "invalid_response"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
@pytest.mark.parametrize("status", [401, 403, 404, 409, 422, 429, 500, 503])
def test_api_status_errors_remain_typed_text_only_and_are_never_retried(
    status: int,
) -> None:
    async def exercise() -> tuple[AdapterError, int]:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                status,
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": request.headers["x-request-id"],
                },
                json={
                    "error": {
                        "code": f"status_{status}",
                        "message": "A bounded API failure.",
                        "details": {"field": "proposal"},
                    },
                    "request_id": request.headers["x-request-id"],
                },
                request=request,
            )

        injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=injected,
        )
        try:
            with pytest.raises(AdapterError) as caught:
                await rest.request_json("POST", "plans", body={"tool": "ask"})
            return caught.value, calls
        finally:
            await rest.aclose()
            await injected.aclose()

    error, calls = asyncio.run(exercise())
    assert calls == 1
    assert error.code == f"status_{status}"
    assert error.status == status
    assert error.request_id is not None
    assert error.request_id.startswith("mcp-")
    # A returned 429 is an unambiguous rejection with a server wait hint.
    # Stateful POST failures remain non-retryable even for transient 5xx status.
    assert error.retryable is (status == 429)
    result = _error_result(error).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert result["isError"] is True
    assert result["resultType"] == "complete"
    assert "structuredContent" not in result


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def test_api_transport_failures_are_bounded_distinct_and_never_retried() -> None:
    async def exercise() -> tuple[list[str], int]:
        outcomes: list[object] = [
            httpx.Response(302, headers={"Location": "https://attacker.invalid"}),
            httpx.Response(200, headers={"Content-Type": "text/html"}, text="no"),
            httpx.Response(
                200, headers={"Content-Type": "application/json"}, content=b"{"
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "application/json", "Content-Length": "9"},
                content=b'{"ok":1}',
            ),
            "timeout",
            "connection",
            "cancel",
        ]
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            outcome = outcomes.pop(0)
            if outcome == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            if outcome == "connection":
                raise httpx.ConnectError("unavailable", request=request)
            if outcome == "cancel":
                raise asyncio.CancelledError
            assert isinstance(outcome, httpx.Response)
            outcome.request = request
            return outcome

        injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=injected,
        )
        codes: list[str] = []
        try:
            for max_bytes in (1024, 1024, 1024, 4, 1024, 1024):
                with pytest.raises(AdapterError) as caught:
                    await rest.request_json("GET", "me", max_bytes=max_bytes)
                codes.append(caught.value.code)
                assert len(caught.value.render().encode("utf-8")) <= 4096
            with pytest.raises(asyncio.CancelledError):
                await rest.request_json("GET", "me")
            return codes, calls
        finally:
            await rest.aclose()
            await injected.aclose()

    codes, calls = asyncio.run(exercise())
    assert codes == [
        "redirect_rejected",
        "invalid_response",
        "invalid_response",
        "response_too_large",
        "api_timeout",
        "api_unavailable",
    ]
    assert calls == 7


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def test_api_retryability_distinguishes_safe_reads_from_ambiguous_posts() -> None:
    async def exercise(method: str, outcome: str) -> TransportError:
        async def handler(request: httpx.Request) -> httpx.Response:
            if outcome == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            if outcome == "connection":
                raise httpx.ConnectError("unavailable", request=request)
            return httpx.Response(
                503,
                headers={"Content-Type": "application/json"},
                json={},
                request=request,
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=client,
        )
        try:
            with pytest.raises(TransportError) as caught:
                await rest.request_json(method, "plans", body={} if method == "POST" else None)
            return caught.value
        finally:
            await rest.aclose()
            await client.aclose()

    for outcome in ("timeout", "connection", "status"):
        assert asyncio.run(exercise("GET", outcome)).retryable is True
        assert asyncio.run(exercise("POST", outcome)).retryable is False


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
# @source clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.download_media
def test_rest_operations_have_total_wall_clock_deadlines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import rest as rest_module

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Length": "2",
            },
            content=b"{}",
            request=request,
        )

    async def exercise() -> tuple[TransportError, TransportError]:
        api_client = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
        storage_client = httpx.AsyncClient(
            transport=httpx.MockTransport(slow_handler)
        )
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=api_client,
            storage_client=storage_client,
        )
        try:
            with pytest.raises(TransportError) as api_error:
                await rest.request_json("GET", "me")
            with pytest.raises(TransportError) as media_error:
                await rest.download_media(_signed_download_url(), cap=1024)
            return api_error.value, media_error.value
        finally:
            await rest.aclose()
            await api_client.aclose()
            await storage_client.aclose()

    monkeypatch.setattr(rest_module, "RESPONSE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(rest_module, "MEDIA_TIMEOUT_SECONDS", 0.01)
    api_error, media_error = asyncio.run(exercise())
    assert (api_error.code, api_error.retryable) == ("api_timeout", True)
    assert (media_error.code, media_error.retryable) == ("download_timeout", True)


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/server.py::_success_result
def test_structured_and_complete_frame_limits_fail_as_tool_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = AdapterResult({"value": "x" * MAX_STRUCTURED_RESULT_BYTES})
    with pytest.raises(TransportError) as structured:
        LagniappeAdapter._enforce_result_limits(oversized)
    assert structured.value.code == "result_too_large"

    from lagniappe_mcp import server as server_module

    monkeypatch.setattr(server_module, "MAX_COMPLETE_FRAME_BYTES", 128)
    with pytest.raises(TransportError) as frame:
        _success_result(AdapterResult({"value": "bounded"}))
    assert frame.value.code == "result_too_large"

    monkeypatch.setattr(server_module, "MAX_COMPLETE_FRAME_BYTES", 1024)
    with pytest.raises(TransportError) as request_id_frame:
        _success_result(
            AdapterResult({"value": "bounded"}),
            request_id="r" * 900,
            server_info={"name": "lagniappe", "version": "test"},
        )
    assert request_id_frame.value.code == "result_too_large"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/server.py::create_server
def test_stdio_rejects_oversized_request_ids_without_reflecting_them() -> None:
    oversized_id = "private-" + "x" * 512
    unsafe_ids = (
        oversized_id,
        "white space",
        "line\nbreak",
        "unicode-é",
        "../local/path",
        '"quoted"',
    )
    normal = [
        SessionMessage(
            JSONRPCRequest(jsonrpc="2.0", id="bounded", method="ping", params={})
        ),
        SessionMessage(
            JSONRPCRequest(
                jsonrpc="2.0",
                id="req-123:part_4.5",
                method="ping",
                params={},
            )
        ),
        SessionMessage(
            JSONRPCRequest(jsonrpc="2.0", id=7, method="ping", params={})
        ),
    ]

    class ReadStream:
        def __init__(self) -> None:
            self.items = iter(
                [
                    *(
                        SessionMessage(
                            JSONRPCRequest(
                                jsonrpc="2.0",
                                id=request_id,
                                method="ping",
                                params={},
                            )
                        )
                        for request_id in unsafe_ids
                    ),
                    *normal,
                ]
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.items)
            except StopIteration:
                raise StopAsyncIteration from None

    class WriteStream:
        def __init__(self) -> None:
            self.items: list[SessionMessage] = []

        async def send(self, item: SessionMessage) -> None:
            self.items.append(item)

    async def exercise() -> tuple[list[SessionMessage], list[SessionMessage]]:
        output = WriteStream()
        accepted = [
            item
            async for item in _bounded_stdio_requests(ReadStream(), output)
        ]
        return accepted, output.items

    accepted, rejected = asyncio.run(exercise())
    assert accepted == normal
    assert len(rejected) == len(unsafe_ids)
    for request_id, rejected_item in zip(unsafe_ids, rejected, strict=True):
        error = rejected_item.message
        assert error.id is None
        assert error.error.code == -32600
        assert request_id not in error.model_dump_json()


# @pair mcp-adapter:product-contract
def test_bounded_raw_stdio_input_discards_oversized_frame_and_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lagniappe_mcp import server as server_module

    private_value = b"private-frame-value"
    valid_frame = b"{}\n"
    requested_sizes: list[int] = []

    class RecordingInput(io.BytesIO):
        def readline(self, size: int = -1) -> bytes:
            requested_sizes.append(size)
            return super().readline(size)

    source = RecordingInput(private_value * 10 + b"\n" + valid_frame)
    monkeypatch.setattr(server_module, "MAX_REQUEST_FRAME_BYTES", 32)
    monkeypatch.setattr(server_module, "_STDIO_DRAIN_CHUNK_BYTES", 16)

    async def exercise() -> list[str]:
        return [line async for line in _bounded_stdin_lines(source)]

    frames = asyncio.run(exercise())
    assert frames == ["{\n", valid_frame.decode()]
    assert private_value.decode() not in "".join(frames)
    assert requested_sizes
    assert max(requested_sizes) <= 33


def test_mcp_driver_persists_only_owner_only_bounded_privacy_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "lgn_driver_result_secret"
    csrf_token = "driver-csrf-secret"
    session_cookie = "driver-session-secret"
    allowed_root = tmp_path / "private-root"
    upload_path = allowed_root / "boundary-note.txt"
    signed_url = _signed_download_url()
    specification = {
        "allowed_root": str(allowed_root),
        "upload_path": str(upload_path),
        "revoke": {
            "csrf_token": csrf_token,
            "cookies": {"session": session_cookie},
        },
    }
    specification_path = tmp_path / "driver-specification.json"
    result_path = tmp_path / "driver-result.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    async def leaking_workflow(_specification: dict[str, Any]):
        return (
            {
                "many": [signed_url for _index in range(100)],
                "storage": {
                    "googleapis": {"com": f"nested reflection {api_key}"}
                },
                api_key: "credential also appeared in an object key",
                "credential": f"reflected Bearer {api_key}",
                "local_path": f"opened {upload_path}",
                "transport": signed_url,
            },
            f"stderr reflected {csrf_token} and {session_cookie}",
        )

    temporary_modes: list[int] = []
    real_replace = mcp_client_driver.os.replace

    def capture_replace(source: str | Path, destination: str | Path) -> None:
        temporary_modes.append(stat.S_IMODE(Path(source).stat().st_mode))
        real_replace(source, destination)

    monkeypatch.setenv("LAGNIAPPE_API_KEY", api_key)
    monkeypatch.setenv("LAGNIAPPE_URL", "https://example.com")
    monkeypatch.setattr(mcp_client_driver, "_workflow", leaking_workflow)
    monkeypatch.setattr(mcp_client_driver.os, "replace", capture_replace)

    status = mcp_client_driver.main(
        ["workflow", str(specification_path), str(result_path)]
    )

    assert status == 1
    assert temporary_modes == [0o600]
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(f".{result_path.name}.*.tmp"))
    assert result_path.stat().st_size <= 8 * 1024
    persisted = result_path.read_text(encoding="utf-8")
    for private in (
        api_key,
        csrf_token,
        session_cookie,
        str(allowed_root),
        str(upload_path),
        "storage.googleapis.com",
        "x-goog-",
        "upload_id",
    ):
        assert private.casefold() not in persisted.casefold()
    value = json.loads(persisted)
    assert set(value) == {
        "diagnostics",
        "driver_error",
        "privacy_findings",
        "privacy_findings_truncated",
    }
    assert value["driver_error"] == "MCP evidence failed privacy screening."
    assert value["diagnostics"]["contains_sensitive_value"] is True
    assert value["privacy_findings_truncated"] is True
    assert value["privacy_findings"]
    assert len(value["privacy_findings"]) <= 24
    assert {finding["kind"] for finding in value["privacy_findings"]} == {
        "credential",
        "local_path",
        "transport",
    }
    assert all(
        set(finding) == {"kind", "path", "redacted", "type"}
        and finding["redacted"] is True
        and len(finding["path"]) <= 160
        and finding["type"] in {"object_key", "string"}
        for finding in value["privacy_findings"]
    )

    async def leaking_failure(_specification: dict[str, Any]):
        raise RuntimeError(f"failed with {api_key} at {upload_path}: {signed_url}")

    failed_result_path = tmp_path / "driver-failed-result.json"
    monkeypatch.setattr(mcp_client_driver, "_workflow", leaking_failure)
    failed_status = mcp_client_driver.main(
        ["workflow", str(specification_path), str(failed_result_path)]
    )
    failed_persisted = failed_result_path.read_text(encoding="utf-8")

    assert failed_status == 1
    assert temporary_modes == [0o600, 0o600]
    assert stat.S_IMODE(failed_result_path.stat().st_mode) == 0o600
    assert json.loads(failed_persisted)["driver_error"] == (
        "MCP evidence failed privacy screening."
    )
    for private in (api_key, str(upload_path), "storage.googleapis.com", "x-goog-"):
        assert private.casefold() not in failed_persisted.casefold()


# @pair mcp-adapter:product-contract
def test_failed_concurrent_startup_cancels_sibling_requests() -> None:
    class FailingStartup:
        def __init__(self) -> None:
            self.cancelled: set[str] = set()

        async def request_json(self, _method: str, target: str, **_kwargs: Any):
            if target == "":
                await asyncio.sleep(0)
                raise TransportError("startup_failed", "startup failed")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.add(target)
                raise

    fake = FailingStartup()
    with pytest.raises(TransportError):
        asyncio.run(RESTClient.startup(fake))  # type: ignore[arg-type]
    assert fake.cancelled == {"me", "tools"}


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/catalog.py::lifecycle_tools
def test_plan_start_rejects_whitespace_instructions_before_dispatch() -> None:
    async def exercise() -> list[tuple[str, str, Any]]:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(
                normalize_site_url("https://example.com"),
                "api-secret",
            ),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        with pytest.raises(SchemaError) as rejected:
            await adapter.execute("start_ask", {"instructions": " \t\n "})
        assert rejected.value.code == "input_validation_failed"
        await adapter.aclose()
        return rest.requests

    assert asyncio.run(exercise()) == []


@pytest.mark.parametrize(("status", "code"), [(401, "unauthorized"), (403, "forbidden")])
# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter
def test_published_tools_still_honor_next_request_revocation_or_permission_loss(
    status: int,
    code: str,
) -> None:
    class AccessREST(_WorkflowREST):
        blocked = False

        async def request_json(
            self, method: str, target: str, *, body: Any = None, **kwargs: Any
        ):
            if self.blocked and target.endswith("/tools/search"):
                self.requests.append((method, target, body))
                raise AdapterError(
                    code,
                    "Access changed after MCP tool discovery.",
                    status=status,
                )
            return await super().request_json(
                method,
                target,
                body=body,
                **kwargs,
            )

    async def exercise() -> tuple[AdapterError, AccessREST]:
        rest = AccessREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(
                normalize_site_url("https://example.com"),
                "api-secret",
            ),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        assert "search" in adapter.tools
        rest.blocked = True
        with pytest.raises(AdapterError) as rejected:
            await adapter.execute(
                "search",
                {"plan_id": "abcdefghijkl", "query": "must reauthorize"},
            )
        await adapter.aclose()
        return rejected.value, rest

    rejected, rest = asyncio.run(exercise())
    assert (rejected.code, rejected.status) == (code, status)
    assert rest.requests == [
        (
            "POST",
            "plans/abcdefghijkl/tools/search",
            {"arguments": {"query": "must reauthorize"}},
        )
    ]


# @pair mcp-adapter:product-contract
def test_adapter_executes_only_typed_lifecycle_and_catalog_routes() -> None:
    async def exercise() -> tuple[_WorkflowREST, dict[str, Any]]:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(
                normalize_site_url("https://example.com"),
                "api-secret",
                actor_hash="abcdefghijkl",
            ),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        assert list(adapter.tools)[-1] == "search"
        assert adapter.tools["search"].as_mcp_tool().meta == {
            "lagniappe/resultPaths": {
                "primary_collection": "$",
                "pagination": None,
            }
        }

        actor = await adapter.execute("get_actor", {})
        assert actor.value["user"]["hash"] == "abcdefghijkl"
        started = await adapter.execute(
            "start_create", {"instructions": "Prepare one safe change."}
        )
        assert not {
            "contract_url",
            "submit_url",
            "status_url",
            "upload_batch_id",
        } & started.value.keys()
        fetched = await adapter.execute("get_plan", {"plan_id": "abcdefghijkl"})
        assert fetched.value["id"] == "abcdefghijkl"
        projected = await adapter.execute(
            "get_plan_contract", {"plan_id": "abcdefghijkl"}
        )
        assert "submission_format" not in projected.value
        assert projected.value["mcp_submission"]["proposal_schema"] == "$.proposal_schema"
        searched = await adapter.execute(
            "search", {"plan_id": "abcdefghijkl", "query": "needle"}
        )
        assert searched.value == ["first", "second"]
        await adapter.aclose()
        return rest, projected.value

    rest, projected = asyncio.run(exercise())
    assert projected["proposal_schema"]["required"] == ["title"]
    assert (
        "POST",
        "plans",
        {"tool": "create", "instructions": "Prepare one safe change."},
    ) in rest.requests
    assert (
        "POST",
        "plans/abcdefghijkl/tools/search",
        {"arguments": {"query": "needle"}},
    ) in rest.requests

    unsafe_actor = _actor()
    unsafe_actor["credential"]["api_key"] = "must-not-cross-mcp"
    with pytest.raises(SchemaError):
        validate_value(lifecycle_tools()[0].output_schema, unsafe_actor, phase="output")


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_plan_start_rejects_a_valid_plan_for_the_wrong_requested_tool() -> None:
    async def exercise() -> None:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        with pytest.raises(TransportError) as error:
            await adapter.execute(
                "start_ask",
                {"instructions": "Answer one question."},
            )
        assert error.value.code == "invalid_response"
        assert rest.requests[-1] == (
            "POST",
            "plans",
            {"tool": "ask", "instructions": "Answer one question."},
        )
        await adapter.aclose()

    asyncio.run(exercise())


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_read_arguments_and_results_are_validated_at_the_dispatch_boundary() -> None:
    async def exercise() -> None:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        before = list(rest.requests)
        with pytest.raises(SchemaError) as invalid_input:
            await adapter.execute("search", {"plan_id": "abcdefghijkl"})
        assert invalid_input.value.code == "input_validation_failed"
        assert rest.requests == before

        original_request = rest.request_json

        async def invalid_result(
            method: str, target: str, *, body: Any = None, **kwargs: Any
        ):
            if target.endswith("/tools/search"):
                rest.requests.append((method, target, body))
                return {"result": [1]}, "request-invalid-result"
            return await original_request(method, target, body=body, **kwargs)

        rest.request_json = invalid_result  # type: ignore[method-assign]
        with pytest.raises(SchemaError) as invalid_output:
            await adapter.execute(
                "search", {"plan_id": "abcdefghijkl", "query": "needle"}
            )
        assert invalid_output.value.code == "upstream_output_validation_failed"
        assert rest.requests[-1][1] == "plans/abcdefghijkl/tools/search"
        await adapter.aclose()

    asyncio.run(exercise())


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_lifecycle_transport_and_human_links_fail_closed() -> None:
    adapter = LagniappeAdapter(
        ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    )
    try:
        transport_variants = (
            "https://attacker.invalid/api/v1/plans/abcdefghijkl/contract",
            "https://user@example.com/api/v1/plans/abcdefghijkl/contract",
            "https://example.com:444/api/v1/plans/abcdefghijkl/contract",
            "https://example.com/not-api/plans/abcdefghijkl/contract",
            "https://example.com/api/v1/plans/other/contract",
            "https://example.com/api/v1/plans/abcdefghijkl/contract?next=1",
        )
        for value in transport_variants:
            plan = _plan()
            plan["contract_url"] = value
            with pytest.raises(TransportError) as error:
                adapter._safe_plan(plan)
            assert error.value.code == "incompatible_url"
            assert "attacker.invalid" not in error.value.render()

        human_variants = (
            "https://attacker.invalid/tools/api-plan/abcdefghijkl",
            "https://example.com/tools/api-plan/abcdefghijkl?token=secret",
            "https://example.com/unexpected/abcdefghijkl",
        )
        for value in human_variants:
            plan = _plan()
            plan["preview_url"] = value
            with pytest.raises(TransportError) as error:
                adapter._safe_plan(plan)
            assert error.value.code == "incompatible_link"
            assert "token=secret" not in error.value.render()
    finally:
        asyncio.run(adapter.aclose())

    class HostileContractREST(_WorkflowREST):
        async def request_json(
            self, method: str, target: str, *, body: Any = None, **kwargs: Any
        ):
            if target.endswith("/contract"):
                self.requests.append((method, target, body))
                value = _contract()
                value["submission_format"]["url"] = (
                    "https://attacker.invalid/api/v1/plans/abcdefghijkl/submit"
                )
                return value, "request-contract"
            return await super().request_json(method, target, body=body, **kwargs)

    async def reject_submission() -> HostileContractREST:
        rest = HostileContractREST()
        candidate = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,  # type: ignore[arg-type]
        )
        await candidate.initialize()
        with pytest.raises(TransportError) as error:
            await candidate.execute(
                "submit_plan",
                {
                    "plan_id": "abcdefghijkl",
                    "contract_version": 6,
                    "proposal": {"title": "Safe"},
                },
            )
        assert error.value.code == "incompatible_url"
        assert not any(method == "POST" for method, target, _ in rest.requests if target.endswith("/submit"))
        await candidate.aclose()
        return rest

    rejected = asyncio.run(reject_submission())
    assert [target for _, target, _ in rejected.requests].count(
        "plans/abcdefghijkl/contract"
    ) == 1


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/adapter.py::LagniappeAdapter.execute
def test_lifecycle_responses_reject_values_outside_the_frozen_contract() -> None:
    adapter = LagniappeAdapter(
        ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    )
    try:
        invalid_plans: list[dict[str, Any]] = []
        for field, value in (
            ("status", "queued"),
            ("name", None),
            ("contract_version", 7),
        ):
            plan = _plan()
            plan[field] = value
            invalid_plans.append(plan)
        invalid_file = _plan()
        invalid_file["files"] = [
            {
                "ref": "not-a-reference",
                "name": None,
                "filename": "file.txt",
                "mimetype": "text/plain",
                "size": -1,
            }
        ]
        invalid_plans.append(invalid_file)

        for plan in invalid_plans:
            with pytest.raises(SchemaError) as plan_error:
                adapter._safe_plan(plan)
            assert plan_error.value.code == "upstream_output_validation_failed"

        receipt = {
            "id": "abcdefghijkl",
            "status": "ready",
            "preview_url": "https://example.com/tools/api-plan/abcdefghijkl",
            "review_url": "https://example.com/tools/reports/abcdefghijkl",
            "status_url": "https://example.com/api/v1/plans/abcdefghijkl",
            "contract_version": 6,
            "proposal_fingerprint": "f" * 64,
        }
        for field, value in (
            ("status", "draft"),
            ("contract_version", 7),
            ("proposal_fingerprint", ""),
        ):
            invalid_receipt = {**receipt, field: value}
            with pytest.raises(SchemaError) as receipt_error:
                adapter._safe_receipt(
                    invalid_receipt, expected_plan_id="abcdefghijkl"
                )
            assert receipt_error.value.code == "upstream_output_validation_failed"
    finally:
        asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
def test_submit_refetches_contract_and_posts_only_a_valid_exact_wrapper() -> None:
    async def exercise() -> _WorkflowREST:
        rest = _WorkflowREST()
        adapter = LagniappeAdapter(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            rest=rest,  # type: ignore[arg-type]
        )
        await adapter.initialize()
        with pytest.raises(SchemaError) as stale:
            await adapter.execute(
                "submit_plan",
                {"plan_id": "abcdefghijkl", "contract_version": 5, "proposal": {}},
            )
        assert stale.value.code == "stale_contract_version"
        with pytest.raises(SchemaError):
            await adapter.execute(
                "submit_plan",
                {
                    "plan_id": "abcdefghijkl",
                    "contract_version": 6,
                    "proposal": {"title": 7},
                },
            )
        assert not any(target.endswith("/submit") for _, target, _ in rest.requests)

        receipt = await adapter.execute(
            "submit_plan",
            {
                "plan_id": "abcdefghijkl",
                "contract_version": 6,
                "proposal": {"title": "Approved in the browser"},
            },
        )
        assert receipt.value["status"] == "ready"
        assert "status_url" not in receipt.value
        await adapter.aclose()
        return rest

    rest = asyncio.run(exercise())
    assert sum(target.endswith("/contract") for _, target, _ in rest.requests) == 3
    assert rest.requests[-1] == (
        "POST",
        "https://example.com/api/v1/plans/abcdefghijkl/submit",
        {
            "contract_version": 6,
            "proposal": {"title": "Approved in the browser"},
        },
    )


# @pair mcp-adapter:product-contract
def test_mcp_v2_results_use_direct_structured_values_and_complete_aliases() -> None:
    success = _success_result(AdapterResult([{"hash": "abcdefghijkl"}]))
    dumped = success.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert dumped["resultType"] == "complete"
    assert dumped["structuredContent"] == [{"hash": "abcdefghijkl"}]
    assert dumped["content"] == [{"type": "text", "text": '[{"hash":"abcdefghijkl"}]'}]

    error = _error_result(TransportError("failed", "Bounded failure."))
    dumped_error = error.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert dumped_error["resultType"] == "complete"
    assert dumped_error["isError"] is True
    assert "structuredContent" not in dumped_error


# @pair mcp-adapter:product-contract
def test_low_level_server_negotiates_modern_types_without_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()

    class FakeAdapter:
        def __init__(self, _config: ConnectionConfig) -> None:
            self.tools = {
                "get_actor": lifecycle_tools()[0],
                "array_read": ToolDefinition(
                    "array_read",
                    "Return an array.",
                    {"type": "object", "properties": {}, "additionalProperties": False},
                    {"type": "array", "items": {"type": "integer"}},
                    "read",
                    READ_ANNOTATIONS,
                ),
            }

        async def initialize(self) -> None:
            return None

        async def execute(self, _name: str, _arguments: Any) -> AdapterResult:
            return AdapterResult(actor if _name == "get_actor" else [1, 2])

        async def aclose(self) -> None:
            return None

    async def exercise() -> None:
        from lagniappe_mcp import files as files_module
        from lagniappe_mcp import server as server_module

        checked_roots: list[tuple[Path, ...]] = []
        monkeypatch.setattr(
            files_module,
            "validate_allowed_roots",
            lambda roots: checked_roots.append(tuple(roots)),
        )
        monkeypatch.setattr(server_module, "LagniappeAdapter", FakeAdapter)
        config = ConnectionConfig(
            normalize_site_url("https://example.com"), "api-secret"
        )
        server = server_module.create_server(config)
        async with Client(server, mode="auto") as client:
            assert client.protocol_version == "2026-07-28"
            assert client.server_capabilities.resources is None
            listed = await client.list_tools()
            assert listed.result_type == "complete"
            assert [tool.name for tool in listed.tools] == ["get_actor", "array_read"]
            called = await client.call_tool("get_actor", {})
            assert called.result_type == "complete"
            assert called.structured_content == actor
            array_result = await client.call_tool("array_read", {})
            assert array_result.structured_content == [1, 2]
            with pytest.raises(MCPError) as unknown:
                await client.call_tool("unknown", {})
            assert unknown.value.code == -32602
            assert unknown.value.data is None
        assert checked_roots == [()]

    asyncio.run(exercise())


# @pair mcp-adapter:product-contract
def test_requested_unsupported_original_is_a_bounded_tool_error() -> None:
    config = ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    adapter = LagniappeAdapter(config)
    raw = {
        "filename": "notes.txt",
        "mimetype": "text/plain",
        "summary": "Safe metadata",
        "content": "Extracted text",
        "session_url": "https://storage.googleapis.com/private?upload_id=secret",
        "original_file": {
            "supported": False,
            "attached": False,
            "reason": "Unavailable",
        },
    }
    try:
        with pytest.raises(TransportError) as error:
            asyncio.run(adapter._project_file_result(raw, {"include_original": True}))
        assert error.value.code == "unsupported_media"
        assert len(error.value.render().encode("utf-8")) < 4096
        projected = asyncio.run(
            adapter._project_file_result(raw, {"include_original": False})
        )
        assert "session_url" not in projected.value
        assert projected.value["filename"] == "notes.txt"
        assert projected.value["mimetype"] == "text/plain"
        assert projected.value["summary"] == "Safe metadata"
        domain_error = asyncio.run(
            adapter._project_file_result(
                {"error": "File not found"}, {"include_original": False}
            )
        )
        assert domain_error.value == {
            "error": "File not found",
            "delivery": {"kind": "none"},
        }
        with pytest.raises(TransportError) as extension_error:
            asyncio.run(
                adapter._project_file_result(
                    {
                        **raw,
                        "signed_url": _signed_download_url(),
                    },
                    {"include_original": False},
                )
            )
        assert extension_error.value.code == "unsafe_transport_extension"
        for alias in ("href", "location"):
            with pytest.raises(TransportError) as alias_error:
                asyncio.run(
                    adapter._project_file_result(
                        {
                            **raw,
                            alias: _signed_download_url(),
                        },
                        {"include_original": False},
                    )
                )
            assert alias_error.value.code == "unsafe_transport_extension"
        with pytest.raises(TransportError) as value_error:
            asyncio.run(
                adapter._project_file_result(
                    {
                        **raw,
                        "summary": _signed_download_url(),
                    },
                    {"include_original": False},
                )
            )
        assert value_error.value.code == "unsafe_transport_extension"
    finally:
        asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
def test_requested_missing_original_is_a_bounded_tool_error() -> None:
    config = ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    adapter = LagniappeAdapter(config)
    try:
        with pytest.raises(TransportError) as error:
            asyncio.run(
                adapter._project_file_result(
                    {"content": "Extracted text"}, {"include_original": True}
                )
            )
        assert error.value.code == "original_unavailable"
    finally:
        asyncio.run(adapter.aclose())


# @pair mcp-adapter:product-contract
def test_original_download_mime_must_match_upstream_file_metadata() -> None:
    """Transport-only file metadata still constrains emitted MCP media."""
    rest = _WorkflowREST()
    config = ConnectionConfig(normalize_site_url("https://example.com"), "api-secret")
    adapter = LagniappeAdapter(config, rest=rest)

    async def download_media(_url: str, *, cap: int):
        assert cap == MAX_MEDIA_RAW_BYTES
        return b"not-a-png", "audio/mpeg"

    rest.download_media = download_media
    raw = {
        "content": "extracted text",
        "mimetype": "image/png",
        "original_file": {
            "supported": True,
            "attached": False,
            "download_url": _signed_download_url(),
            "expires_in": 300,
        },
    }

    try:
        with pytest.raises(TransportError) as error:
            asyncio.run(
                adapter._project_file_result(raw, {"include_original": True})
            )
        assert error.value.code == "mime_mismatch"
    finally:
        asyncio.run(adapter.aclose())


def test_standalone_sources_have_no_application_imports() -> None:
    sources = [Path(__file__), *(PACKAGE_ROOT / "src" / "lagniappe_mcp").glob("*.py")]
    imported: set[str] = set()
    for source in sources:
        tree = ast.parse(source.read_text())
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
    assert not any(
        name == "lagniappe" or name.startswith("lagniappe.") for name in imported
    )


class _StdioLifecycleAPI:
    """Tiny loopback API whose second actor response stalls mid-body."""

    def __init__(self) -> None:
        self.actor_calls = 0
        self.actor_lock = threading.Lock()
        self.request_started = threading.Event()
        self.client_disconnected = threading.Event()
        self.release_request = threading.Event()
        state = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: Any) -> None:
                return None

            def _send_json(self, value: Any) -> None:
                body = json.dumps(value, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

            def _stall_actor_response(self) -> None:
                body = json.dumps(_actor(), separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body[:1])
                self.wfile.flush()
                state.request_started.set()

                deadline = time.monotonic() + 5
                while not state.release_request.is_set() and time.monotonic() < deadline:
                    readable, _, _ = select.select([self.connection], [], [], 0.05)
                    if not readable:
                        continue
                    try:
                        pending = self.connection.recv(1, socket.MSG_PEEK)
                    except (ConnectionError, OSError):
                        state.client_disconnected.set()
                        return
                    if not pending:
                        state.client_disconnected.set()
                        return
                with suppress(BrokenPipeError, ConnectionError, OSError):
                    self.wfile.write(body[1:])
                    self.wfile.flush()

            def do_GET(self) -> None:
                if self.path == "/api/v1":
                    origin = state.origin
                    self._send_json(
                        {
                            "version": "v1",
                            "base_url": f"{origin}/api/v1",
                            "openapi_url": f"{origin}/api/v1/openapi.json",
                            "actor_url": f"{origin}/api/v1/me",
                            "tools_url": f"{origin}/api/v1/tools",
                            "plans_url": f"{origin}/api/v1/plans",
                            "client_skill_url": f"{origin}/api/v1/client-skill.md",
                        }
                    )
                    return
                if self.path == "/api/v1/tools":
                    self._send_json(
                        {
                            "tools": [],
                            "view": "full",
                            "selected_count": 0,
                            "reference_format": "hash:<12-character-hash>",
                            "execution_envelope": {
                                "success": {
                                    "result": "<value matching the selected output_schema>"
                                },
                                "failure": {
                                    "error": {
                                        "code": "tool_error",
                                        "message": "<message>",
                                    },
                                    "request_id": "<request id>",
                                },
                            },
                        }
                    )
                    return
                if self.path == "/api/v1/me":
                    with state.actor_lock:
                        state.actor_calls += 1
                        actor_call = state.actor_calls
                    if actor_call == 1:
                        self._send_json(_actor())
                    else:
                        self._stall_actor_response()
                    return
                self.send_error(404)

        class Server(ThreadingHTTPServer):
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        host, port = self.server.server_address[:2]
        self.origin = f"http://{host}:{port}"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="mcp-stdio-test-api",
            daemon=True,
        )

    def __enter__(self) -> "_StdioLifecycleAPI":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release_request.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@contextmanager
def _stdio_adapter_process(api: _StdioLifecycleAPI):
    """Launch the real console module with the isolated test interpreter."""
    assert (Path(sys.prefix) / "pyvenv.cfg").is_file()
    process = subprocess.Popen(
        [sys.executable, "-I", "-m", "lagniappe_mcp", "serve", "--from-env"],
        cwd=PACKAGE_ROOT,
        env={
            "LAGNIAPPE_API_KEY": "stdio-secret-key",
            "LAGNIAPPE_URL": api.origin,
            "PATH": os.environ.get("PATH", ""),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        start_new_session=True,
    )
    try:
        yield process
    finally:
        api.release_request.set()
        if process.stdin is not None and not process.stdin.closed:
            with suppress(BrokenPipeError, OSError):
                process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {
        "name": "lagniappe-stdio-test",
        "version": "1",
    },
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _write_stdio_frame(
    process: subprocess.Popen[bytes],
    *,
    request_id: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> None:
    assert process.stdin is not None
    body = dict(params or {})
    body["_meta"] = deepcopy(_MODERN_META)
    frame = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": body,
    }
    process.stdin.write(json.dumps(frame, separators=(",", ":")).encode() + b"\n")
    process.stdin.flush()


def _write_stdio_cancel(process: subprocess.Popen[bytes], request_id: str) -> None:
    assert process.stdin is not None
    frame = {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": request_id, "reason": "deterministic test cancel"},
    }
    process.stdin.write(json.dumps(frame, separators=(",", ":")).encode() + b"\n")
    process.stdin.flush()


def _read_stdio_frame(
    process: subprocess.Popen[bytes], buffer: bytearray, *, timeout: float = 3
) -> dict[str, Any]:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    while b"\n" not in buffer:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError("Timed out waiting for an MCP stdout frame.")
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            raise AssertionError("Timed out waiting for an MCP stdout frame.")
        chunk = os.read(process.stdout.fileno(), 64 * 1024)
        if not chunk:
            raise AssertionError("MCP process closed stdout before the expected frame.")
        buffer.extend(chunk)
    line, _, remainder = buffer.partition(b"\n")
    buffer[:] = remainder
    value = json.loads(line)
    assert isinstance(value, dict)
    return value


def _read_stdio_until(
    process: subprocess.Popen[bytes],
    buffer: bytearray,
    request_id: str,
    *,
    timeout: float = 3,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    frames: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        frame = _read_stdio_frame(
            process,
            buffer,
            timeout=max(0.01, deadline - time.monotonic()),
        )
        frames.append(frame)
        if frame.get("id") == request_id:
            return frames
    raise AssertionError(f"MCP response {request_id!r} did not arrive.")


def _stdio_diagnostics(process: subprocess.Popen[bytes]) -> str:
    assert process.stderr is not None
    diagnostic = process.stderr.read().decode("utf-8", errors="replace")
    assert len(diagnostic.encode("utf-8")) <= MAX_STDERR_BYTES
    assert "stdio-secret-key" not in diagnostic
    assert "Traceback" not in diagnostic
    assert "ExceptionGroup" not in diagnostic
    return diagnostic


def _stdio_telemetry(diagnostic: str) -> list[dict[str, Any]]:
    lines = diagnostic.splitlines()
    assert lines
    assert all(len(line.encode("utf-8")) + 1 <= MAX_STDERR_BYTES for line in lines)
    events = [json.loads(line) for line in lines]
    assert all(
        event.get("event")
        in {"lagniappe_mcp_scope", "lagniappe_mcp_upstream"}
        for event in events
    )
    return events


# @pair mcp-adapter:product-contract
def test_real_stdio_subprocess_rejects_oversized_frame_and_resumes() -> None:
    with _StdioLifecycleAPI() as api, _stdio_adapter_process(api) as process:
        assert process.stdin is not None
        private_marker = b"private-oversized-frame-marker"
        padding_size = MAX_REQUEST_FRAME_BYTES + 1 - len(private_marker)
        oversized = private_marker + (b"x" * padding_size) + b"\n"
        remaining = memoryview(oversized)
        while remaining:
            written = process.stdin.write(remaining)
            assert written is not None and written > 0
            remaining = remaining[written:]
        process.stdin.flush()

        _write_stdio_frame(process, request_id="after-oversized", method="tools/list")
        frames = _read_stdio_until(process, bytearray(), "after-oversized", timeout=5)

        parse_errors = [
            frame
            for frame in frames
            if frame.get("id") is None
            and isinstance(frame.get("error"), dict)
            and frame["error"].get("code") == -32700
        ]
        assert len(parse_errors) == 1
        assert "result" in frames[-1]
        assert private_marker.decode() not in json.dumps(frames)

        process.stdin.close()
        assert process.wait(timeout=3) == 0
        _stdio_telemetry(_stdio_diagnostics(process))


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/server.py::create_server
def test_real_stdio_subprocess_cancellation_emits_no_result_and_cleans_http() -> None:
    with _StdioLifecycleAPI() as api, _stdio_adapter_process(api) as process:
        buffer = bytearray()
        _write_stdio_frame(process, request_id="ready", method="tools/list")
        frames = _read_stdio_until(process, buffer, "ready")
        assert "result" in frames[-1]

        _write_stdio_frame(
            process,
            request_id="cancelled-call",
            method="tools/call",
            params={"name": "get_actor", "arguments": {}},
        )
        assert api.request_started.wait(timeout=2)
        _write_stdio_cancel(process, "cancelled-call")
        _write_stdio_frame(process, request_id="after-cancel", method="tools/list")
        frames.extend(_read_stdio_until(process, buffer, "after-cancel"))

        assert api.client_disconnected.wait(timeout=2)
        _write_stdio_frame(process, request_id="settled", method="tools/list")
        frames.extend(_read_stdio_until(process, buffer, "settled"))
        assert all(frame.get("id") != "cancelled-call" for frame in frames)

        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=3) == 0
        telemetry = _stdio_telemetry(_stdio_diagnostics(process))
        summaries = [
            event for event in telemetry if event["event"] == "lagniappe_mcp_scope"
        ]
        assert [(event["scope"], event["outcome"]) for event in summaries] == [
            ("startup", "success"),
            ("call", "cancelled"),
        ]
        assert summaries[-1]["error_kind"] == "client_cancelled"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/server.py::create_server
def test_real_stdio_subprocess_disconnect_cancels_inflight_call_and_shuts_down() -> None:
    with _StdioLifecycleAPI() as api, _stdio_adapter_process(api) as process:
        buffer = bytearray()
        _write_stdio_frame(process, request_id="ready", method="tools/list")
        frames = _read_stdio_until(process, buffer, "ready")
        assert "result" in frames[-1]
        _write_stdio_frame(
            process,
            request_id="in-flight",
            method="tools/call",
            params={"name": "get_actor", "arguments": {}},
        )
        assert api.request_started.wait(timeout=2)

        assert process.stdin is not None
        process.stdin.close()
        assert api.client_disconnected.wait(timeout=2)
        assert process.wait(timeout=3) == 0

        assert process.stdout is not None
        buffer.extend(process.stdout.read())
        for line in buffer.splitlines():
            frame = json.loads(line)
            assert frame.get("jsonrpc") == "2.0"
        telemetry = _stdio_telemetry(_stdio_diagnostics(process))
        summaries = [
            event for event in telemetry if event["event"] == "lagniappe_mcp_scope"
        ]
        assert [(event["scope"], event["outcome"]) for event in summaries] == [
            ("startup", "success"),
            ("call", "cancelled"),
        ]


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/server.py::create_server
def test_real_stdio_subprocess_broken_output_pipe_exits_without_diagnostics() -> None:
    with _StdioLifecycleAPI() as api, _stdio_adapter_process(api) as process:
        buffer = bytearray()
        _write_stdio_frame(process, request_id="ready", method="tools/list")
        frames = _read_stdio_until(process, buffer, "ready")
        assert "result" in frames[-1]

        assert process.stdout is not None
        process.stdout.close()
        _write_stdio_frame(process, request_id="broken-pipe", method="tools/list")
        assert process.stdin is not None
        process.stdin.close()
        return_code = process.wait(timeout=3)
        diagnostic = _stdio_diagnostics(process)
        assert return_code == 0, diagnostic
        telemetry = _stdio_telemetry(diagnostic)
        summaries = [
            event for event in telemetry if event["event"] == "lagniappe_mcp_scope"
        ]
        assert [(event["scope"], event["outcome"]) for event in summaries] == [
            ("startup", "success"),
        ]


# @pair mcp-adapter:product-contract
def test_telemetry_correlates_concurrent_calls_without_sensitive_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_key = "telemetry-secret-api-key"
    captured_request_ids: list[str] = []

    async def exercise() -> None:
        arrived = 0
        both_arrived = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal arrived
            captured_request_ids.append(request.headers["x-request-id"])
            arrived += 1
            if arrived == 2:
                both_arrived.set()
            await asyncio.wait_for(both_arrived.wait(), timeout=1)
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": request.headers["x-request-id"],
                    "X-Lagniappe-Build-ID": "deadbeef",
                },
                json={"ok": True},
                request=request,
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), api_key),
            client=client,
        )

        async def one_call(plan_id: str, private_query: str) -> None:
            with telemetry_scope("call", "read"):
                await rest.request_json(
                    "POST",
                    f"plans/{plan_id}/tools/search",
                    body={"arguments": {"query": private_query}},
                )

        try:
            await asyncio.gather(
                one_call("private-plan-alpha", "private argument alpha"),
                one_call("private-plan-beta", "/private/local/path"),
            )
        finally:
            await rest.aclose()
            await client.aclose()

    asyncio.run(exercise())
    diagnostic = capsys.readouterr().err
    lines = diagnostic.splitlines()
    events = [json.loads(line) for line in lines]

    assert len(events) == 4
    assert all(len(line.encode("utf-8")) + 1 <= MAX_STDERR_BYTES for line in lines)
    for forbidden in (
        api_key,
        "private-plan-alpha",
        "private-plan-beta",
        "private argument alpha",
        "/private/local/path",
        "https://",
    ):
        assert forbidden not in diagnostic

    correlations = {event["correlation_id"] for event in events}
    assert len(correlations) == 2
    for correlation in correlations:
        grouped = [event for event in events if event["correlation_id"] == correlation]
        assert {event["event"] for event in grouped} == {
            "lagniappe_mcp_scope",
            "lagniappe_mcp_upstream",
        }
        request = next(
            event for event in grouped if event["event"] == "lagniappe_mcp_upstream"
        )
        summary = next(
            event for event in grouped if event["event"] == "lagniappe_mcp_scope"
        )
        assert request == {
            **request,
            "api_request_id": request["api_request_id"],
            "operation": "read",
            "outcome": "success",
            "request_index": 1,
            "scope": "call",
            "status": 200,
            "transport": "api",
        }
        assert request["api_request_id"] in captured_request_ids
        assert request["api_request_id"].startswith(f"mcp-{correlation[:20]}-")
        assert request["response_build_id"] == "deadbeef"
        assert summary["operation"] == "read"
        assert summary["outcome"] == "success"
        assert summary["upstream_requests"] == 1
        assert summary["api_requests"] == 1
        assert summary["storage_requests"] == 0
        assert summary["request_bytes"] == request["request_bytes"]
        assert summary["response_bytes"] == request["response_bytes"]


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/_telemetry.py::TelemetryScope
def test_telemetry_bounds_startup_without_dropping_later_call_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup_diagnostic = io.StringIO()
    monkeypatch.setattr(sys, "stderr", startup_diagnostic)

    for _index in range(128):
        with telemetry_scope("startup", "bootstrap"):
            pass

    startup_rendered = startup_diagnostic.getvalue()
    assert startup_rendered
    assert (
        len(startup_rendered.encode("utf-8"))
        <= MAX_STARTUP_DIAGNOSTIC_BYTES
    )
    assert all(json.loads(line) for line in startup_rendered.splitlines())

    call_diagnostic = io.StringIO()
    monkeypatch.setattr(sys, "stderr", call_diagnostic)
    for _index in range(128):
        with telemetry_scope("call", "read"):
            pass

    call_lines = call_diagnostic.getvalue().splitlines()
    assert len(call_lines) == 128
    assert len(call_diagnostic.getvalue().encode("utf-8")) > MAX_STDERR_BYTES
    assert all(len(line.encode("utf-8")) + 1 <= MAX_STDERR_BYTES for line in call_lines)
    assert all(json.loads(line) for line in call_lines)


# @pair mcp-adapter:product-contract
def test_telemetry_separates_startup_and_records_storage_bytes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_key = "startup-storage-api-secret"
    upload_secret = "upload-private-session"
    signature = "b" * 64

    async def exercise() -> None:
        async def api_handler(request: httpx.Request) -> httpx.Response:
            origin = "https://example.com"
            values: dict[str, Any]
            if request.url.path == "/api/v1":
                values = {
                    "version": "v1",
                    "base_url": f"{origin}/api/v1",
                    "openapi_url": f"{origin}/api/v1/openapi.json",
                    "actor_url": f"{origin}/api/v1/me",
                    "tools_url": f"{origin}/api/v1/tools",
                    "plans_url": f"{origin}/api/v1/plans",
                    "client_skill_url": f"{origin}/api/v1/client-skill.md",
                }
            elif request.url.path == "/api/v1/me":
                values = {"actor": "private actor value"}
            else:
                values = {"tools": []}
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json=values,
                request=request,
            )

        async def storage_handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    headers={"Content-Length": "3", "Content-Type": "image/png"},
                    content=b"png",
                    request=request,
                )
            status = 200 if request.headers["content-range"].startswith("bytes */") else 308
            return httpx.Response(status, content=b"", request=request)

        api_client = httpx.AsyncClient(transport=httpx.MockTransport(api_handler))
        storage_client = httpx.AsyncClient(
            transport=httpx.MockTransport(storage_handler)
        )
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), api_key),
            client=api_client,
            storage_client=storage_client,
        )
        upload_url = (
            "https://storage.googleapis.com/upload/storage/v1/b/private-bucket/o"
            f"?uploadType=resumable&upload_id={upload_secret}"
        )
        try:
            with telemetry_scope("startup", "bootstrap"):
                await rest.startup()
            with telemetry_scope("call", "upload"):
                chunk = httpx.Request(
                    "PUT",
                    upload_url,
                    headers={
                        "Content-Length": "4",
                        "Content-Range": "bytes 0-3/4",
                    },
                    content=b"data",
                )
                chunk_response = await rest.storage_client.send(
                    chunk, stream=True, auth=None, follow_redirects=False
                )
                await chunk_response.aclose()
                probe = httpx.Request(
                    "PUT",
                    upload_url,
                    headers={
                        "Content-Length": "0",
                        "Content-Range": "bytes */4",
                    },
                    content=b"",
                )
                probe_response = await rest.storage_client.send(
                    probe, stream=True, auth=None, follow_redirects=False
                )
                await probe_response.aclose()
                await rest.download_media(
                    _signed_download_url(**{"X-Goog-Signature": signature}),
                    cap=16,
                )
        finally:
            await rest.aclose()
            await api_client.aclose()
            await storage_client.aclose()

    asyncio.run(exercise())
    diagnostic = capsys.readouterr().err
    lines = diagnostic.splitlines()
    events = [json.loads(line) for line in lines]

    assert len(events) == 8
    for forbidden in (
        api_key,
        upload_secret,
        signature,
        "private-bucket",
        "private actor value",
        "storage.googleapis.com",
        "upload_id",
    ):
        assert forbidden not in diagnostic
    assert all(len(line.encode("utf-8")) + 1 <= MAX_STDERR_BYTES for line in lines)

    summaries = [event for event in events if event["event"] == "lagniappe_mcp_scope"]
    assert [(event["scope"], event["operation"]) for event in summaries] == [
        ("startup", "bootstrap"),
        ("call", "upload"),
    ]
    startup = summaries[0]
    assert (startup["api_requests"], startup["storage_requests"]) == (3, 0)
    assert startup["upstream_requests"] == 3
    upload = summaries[1]
    assert (upload["api_requests"], upload["storage_requests"]) == (0, 3)
    assert upload["upstream_requests"] == 3

    storage = [
        event
        for event in events
        if event["event"] == "lagniappe_mcp_upstream"
        and event["transport"] == "storage"
    ]
    assert [event["operation"] for event in storage] == [
        "upload_chunk",
        "upload_status",
        "download",
    ]
    assert [event["request_bytes"] for event in storage] == [4, 0, 0]
    assert [event["response_bytes"] for event in storage] == [0, 0, 3]
    assert [event["status"] for event in storage] == [308, 200, 200]
    assert all(event["outcome"] == "success" for event in storage)


# @pair mcp-adapter:product-contract
def test_telemetry_records_safe_api_error_status_and_retry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def exercise() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            request_id = request.headers["x-request-id"]
            return httpx.Response(
                429,
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": "17",
                    "X-Lagniappe-Build-ID": "deadbeef",
                    "X-Request-ID": request_id,
                },
                json={
                    "error": {
                        "code": "rate_limited",
                        "message": "Wait before retrying.",
                    },
                    "request_id": request_id,
                },
                request=request,
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(
                normalize_site_url("https://example.com"), "private-api-key"
            ),
            client=client,
        )
        try:
            with telemetry_scope("call", "start_ask") as metric:
                try:
                    await rest.request_json("POST", "plans", body={"private": True})
                except AdapterError as error:
                    metric.complete("error", error_kind=classify_error(error))
        finally:
            await rest.aclose()
            await client.aclose()

    asyncio.run(exercise())
    diagnostic = capsys.readouterr().err
    assert "private-api-key" not in diagnostic
    events = [json.loads(line) for line in diagnostic.splitlines()]
    assert len(events) == 2
    request = next(
        event for event in events if event["event"] == "lagniappe_mcp_upstream"
    )
    summary = next(
        event for event in events if event["event"] == "lagniappe_mcp_scope"
    )
    assert request["status"] == 429
    assert request["outcome"] == "error"
    assert request["error_kind"] == "api_domain"
    assert request["retry_after_seconds"] == 17
    assert request["response_build_id"] == "deadbeef"
    assert summary["outcome"] == "error"
    assert summary["error_kind"] == "api_domain"


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient
def test_rest_rejects_encoded_or_over_cap_raw_bodies_before_buffering() -> None:
    class NeverRead(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.iterated = False

        async def __aiter__(self):
            self.iterated = True
            raise AssertionError("encoded response body must not be consumed")
            yield b""  # pragma: no cover

    class OneChunk(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 64

    async def exercise() -> tuple[list[str], list[str], bool, bool]:
        api_encoded = NeverRead()
        storage_encoded = NeverRead()
        api_outcomes: list[httpx.Response] = [
            httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "Content-Encoding": "gzip",
                    "Content-Length": "1",
                },
                stream=api_encoded,
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=OneChunk(),
            ),
        ]
        storage_outcomes: list[httpx.Response] = [
            httpx.Response(
                200,
                headers={
                    "Content-Type": "image/png",
                    "Content-Encoding": "br",
                    "Content-Length": "1",
                },
                stream=storage_encoded,
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "image/png", "Content-Length": "4"},
                stream=OneChunk(),
            ),
        ]

        async def api_handler(request: httpx.Request) -> httpx.Response:
            response = api_outcomes.pop(0)
            response.request = request
            return response

        async def storage_handler(request: httpx.Request) -> httpx.Response:
            response = storage_outcomes.pop(0)
            response.request = request
            return response

        api_client = httpx.AsyncClient(transport=httpx.MockTransport(api_handler))
        storage_client = httpx.AsyncClient(
            transport=httpx.MockTransport(storage_handler)
        )
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), "api-secret"),
            client=api_client,
            storage_client=storage_client,
        )
        api_codes: list[str] = []
        storage_codes: list[str] = []
        try:
            for _index in range(2):
                with pytest.raises(TransportError) as error:
                    await rest.request_json("GET", "me", max_bytes=4)
                api_codes.append(error.value.code)
            for _index in range(2):
                with pytest.raises(TransportError) as error:
                    await rest.download_media(_signed_download_url(), cap=4)
                storage_codes.append(error.value.code)
        finally:
            await rest.aclose()
            await api_client.aclose()
            await storage_client.aclose()
        return api_codes, storage_codes, api_encoded.iterated, storage_encoded.iterated

    api_codes, storage_codes, api_read, storage_read = asyncio.run(exercise())
    assert api_codes == ["invalid_response", "response_too_large"]
    assert storage_codes == ["invalid_download", "media_too_large"]
    assert api_read is False
    assert storage_read is False


# @pair mcp-adapter:product-contract
# @source clients/lagniappe_mcp/src/lagniappe_mcp/rest.py::RESTClient.request_json
def test_upstream_error_details_use_a_control_free_safe_key_allowlist() -> None:
    api_key = "error-detail-secret-key"
    hostile_url = _signed_download_url()

    async def exercise() -> AdapterError:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                headers={"Content-Type": "application/json"},
                json={
                    "error": {
                        "code": "validation_failed",
                        "message": f"bad\x00value {api_key} {hostile_url}",
                        "details": {
                            "path": "$.proposal\x07.summary",
                            "errors": [
                                {
                                    "code": "type",
                                    "path": "$\x1f.proposal",
                                    "message": f"bad {api_key} {hostile_url}",
                                    "credential_backup": "must not survive",
                                }
                            ],
                            "api_secret_backup": "must not survive",
                            "callback_url": hostile_url,
                            "unexpected": "must not survive",
                        },
                    }
                },
                request=request,
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rest = RESTClient(
            ConnectionConfig(normalize_site_url("https://example.com"), api_key),
            client=client,
        )
        try:
            with pytest.raises(AdapterError) as caught:
                await rest.request_json("POST", "plans", body={"private": True})
            return caught.value
        finally:
            await rest.aclose()
            await client.aclose()

    rendered = asyncio.run(exercise()).render()
    payload = json.loads(rendered)
    assert api_key not in rendered
    assert "storage.googleapis.com" not in rendered
    assert "must not survive" not in rendered
    assert "callback_url" not in rendered
    assert "api_secret_backup" not in rendered
    assert not any(ord(character) < 32 for character in rendered)
    assert payload["details"] == {
        "path": "$.proposal .summary",
        "errors": [
            {
                "code": "type",
                "path": "$ .proposal",
                "message": "bad [redacted] [redacted URL]",
            }
        ],
    }
