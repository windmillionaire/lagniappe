"""Conservative ownership-aware Codex MCP registration."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib
from typing import Any, Mapping

from .errors import ConfigurationError
from .profiles import (
    FileSnapshot,
    atomic_write,
    secure_read_snapshot,
    validate_profile_name,
)


_ENTRY_FIELDS = {
    "command",
    "args",
    "startup_timeout_sec",
    "tool_timeout_sec",
    "required",
    "default_tools_approval_mode",
}


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::install_entry
def codex_config_path(*, environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    if values.get("CODEX_HOME"):
        root = Path(values["CODEX_HOME"]).expanduser()
        if not root.is_absolute():
            raise ConfigurationError(
                "unsafe_path", "CODEX_HOME must be an absolute user path."
            )
    else:
        home_value = values.get("HOME")
        home = Path(home_value).expanduser() if home_value else Path.home()
        if not home.is_absolute():
            raise ConfigurationError(
                "unsafe_path", "HOME must resolve to an absolute user path."
            )
        root = home / ".codex"
    return root / "config.toml"


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::render_entry
def server_name(profile_name: str) -> str:
    return f"lagniappe-{validate_profile_name(profile_name)}"


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::render_entry
def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::render_entry
def entry_values(
    profile_name: str, executable: str, *, required: bool = False
) -> dict[str, Any]:
    path = Path(executable)
    if not path.is_absolute():
        raise ConfigurationError(
            "invalid_executable",
            "Codex registration requires an absolute executable path.",
        )
    return {
        "command": str(path),
        "args": ["serve", "--profile", validate_profile_name(profile_name)],
        "startup_timeout_sec": 30,
        "tool_timeout_sec": 300,
        "required": bool(required),
        "default_tools_approval_mode": "writes",
    }


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::render_entry
def entry_fingerprint(values: dict[str, Any]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_codex_install_is_lossless_backed_up_and_idempotent
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_remove_falls_back_without_claiming_manual_removal
def render_entry(
    profile_name: str, executable: str, *, required: bool = False
) -> tuple[str, str]:
    name = server_name(profile_name)
    values = entry_values(profile_name, executable, required=required)
    fingerprint = entry_fingerprint(values)
    args = ", ".join(_toml_string(item) for item in values["args"])
    block = (
        f"# BEGIN lagniappe-mcp {name} {fingerprint}\n"
        f"[mcp_servers.{name}]\n"
        f"command = {_toml_string(values['command'])}\n"
        f"args = [{args}]\n"
        f"startup_timeout_sec = {values['startup_timeout_sec']}\n"
        f"tool_timeout_sec = {values['tool_timeout_sec']}\n"
        f"required = {'true' if values['required'] else 'false'}\n"
        f"default_tools_approval_mode = {_toml_string(values['default_tools_approval_mode'])}\n"
        f"# END lagniappe-mcp {name}\n"
    )
    return block, fingerprint


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::inspect_entry
def _block_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?m)^# BEGIN lagniappe-mcp {re.escape(name)} ([0-9a-f]{{64}})\n"
        rf".*?^# END lagniappe-mcp {re.escape(name)}\n?",
        re.DOTALL,
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::inspect_entry
def _load_config(path: Path) -> tuple[str, dict[str, Any], FileSnapshot | None]:
    try:
        snapshot = secure_read_snapshot(path, private=False)
        if snapshot is None:
            return "", {}, None
    except ConfigurationError as error:
        if error.code == "profile_not_found":
            return "", {}, None
        raise
    except OSError as error:
        raise ConfigurationError(
            "unsafe_config", "Codex configuration could not be read safely."
        ) from error
    raw = snapshot[0]
    if len(raw) > 2 * 1024 * 1024:
        raise ConfigurationError(
            "config_too_large", "Codex configuration exceeds the safety limit."
        )
    try:
        text = raw.decode("utf-8")
        parsed = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(
            "manual_configuration_required",
            "Codex configuration is not safely editable; use the printed manual block.",
        ) from error
    return text, parsed, snapshot


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/codex_config.py::install_entry
def _validate_rendered_config(
    text: str,
    *,
    name: str,
    expected_entry: dict[str, Any] | None,
) -> None:
    """Refuse a textual edit that does not parse to the intended one-table change."""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(
            "manual_configuration_required",
            "Codex configuration cannot be updated losslessly; use the printed manual block.",
        ) from error
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ConfigurationError(
            "manual_configuration_required",
            "Codex MCP configuration has an unsupported shape; use the printed manual block.",
        )
    if expected_entry is None:
        if name in servers:
            raise ConfigurationError(
                "foreign_server",
                f"Codex server {name} was not removed exactly.",
            )
    elif servers.get(name) != expected_entry:
        raise ConfigurationError(
            "manual_configuration_required",
            "Codex configuration cannot represent the generated managed entry safely.",
        )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_codex_owned_entry_rejects_table_modified_behind_marker
# @tests tests_unit/test_033_mcp_adapter.py::test_codex_install_is_lossless_backed_up_and_idempotent
def inspect_entry(
    profile_name: str,
    *,
    expected_fingerprint: str | None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, Any], re.Match[str] | None, FileSnapshot | None]:
    path = codex_config_path(environ=environ)
    text, parsed, snapshot = _load_config(path)
    name = server_name(profile_name)
    matches = list(_block_pattern(name).finditer(text))
    if len(matches) > 1:
        raise ConfigurationError(
            "foreign_server",
            f"Codex server {name} has ambiguous ownership markers.",
        )
    match = matches[0] if matches else None
    raw_servers = parsed.get("mcp_servers") if isinstance(parsed, dict) else None
    if raw_servers is not None and not isinstance(raw_servers, dict):
        raise ConfigurationError(
            "manual_configuration_required",
            "Codex MCP configuration has an unsupported shape; use the printed manual block.",
        )
    servers = raw_servers or {}
    entry = servers.get(name)
    registered = entry is not None
    if registered != (match is not None):
        raise ConfigurationError(
            "foreign_server", f"Codex server {name} is not owned by this profile."
        )
    if match is not None:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
            raise ConfigurationError(
                "foreign_server", f"Codex server {name} has been modified."
            )
        command = entry.get("command")
        required = entry.get("required")
        if not isinstance(command, str) or not isinstance(required, bool):
            raise ConfigurationError(
                "foreign_server", f"Codex server {name} has been modified."
            )
        expected_values = entry_values(profile_name, command, required=required)
        actual_fingerprint = entry_fingerprint(entry)
        marker_fingerprint = match.group(1)
        canonical_block, canonical_fingerprint = render_entry(
            profile_name,
            command,
            required=required,
        )
        if (
            entry != expected_values
            or marker_fingerprint != actual_fingerprint
            or actual_fingerprint != canonical_fingerprint
            or match.group(0) != canonical_block
            or expected_fingerprint is None
            or actual_fingerprint != expected_fingerprint
        ):
            raise ConfigurationError(
                "foreign_server", f"Codex server {name} ownership could not be proven."
            )
    return text, parsed, match, snapshot


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_codex_owned_entry_rejects_table_modified_behind_marker
# @tests tests_unit/test_033_mcp_adapter.py::test_codex_install_is_lossless_backed_up_and_idempotent
def install_entry(
    profile_name: str,
    executable: str,
    *,
    expected_fingerprint: str | None,
    required: bool = False,
    environ: Mapping[str, str] | None = None,
) -> str:
    text, _parsed, match, snapshot = inspect_entry(
        profile_name,
        expected_fingerprint=expected_fingerprint,
        environ=environ,
    )
    block, fingerprint = render_entry(profile_name, executable, required=required)
    if match is not None:
        updated = text[: match.start()] + block + text[match.end() :]
    else:
        separator = (
            ""
            if not text or text.endswith("\n\n")
            else ("\n" if text.endswith("\n") else "\n\n")
        )
        updated = text + separator + block
    name = server_name(profile_name)
    _validate_rendered_config(
        updated,
        name=name,
        expected_entry=entry_values(profile_name, executable, required=required),
    )
    atomic_write(
        codex_config_path(environ=environ),
        updated.encode("utf-8"),
        private=False,
        backup=True,
        expected_snapshot=snapshot,
    )
    return fingerprint


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_codex_owned_entry_rejects_table_modified_behind_marker
def remove_entry(
    profile_name: str,
    *,
    expected_fingerprint: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    text, _parsed, match, snapshot = inspect_entry(
        profile_name,
        expected_fingerprint=expected_fingerprint,
        environ=environ,
    )
    updated = text if match is None else text[: match.start()] + text[match.end() :]
    _validate_rendered_config(
        updated,
        name=server_name(profile_name),
        expected_entry=None,
    )
    atomic_write(
        codex_config_path(environ=environ),
        updated.encode("utf-8"),
        private=False,
        backup=True,
        expected_snapshot=snapshot,
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_configure_codex
def console_executable() -> str:
    candidate = Path(sys.argv[0]).expanduser().absolute()
    if not candidate.exists() or not candidate.is_file():
        raise ConfigurationError(
            "invalid_executable",
            "Run configuration through the installed lagniappe-mcp entry point.",
        )
    return str(candidate.resolve(strict=True))


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_remove_falls_back_without_claiming_manual_removal
def manual_entry(
    profile_name: str,
    executable: str,
    *,
    remove: bool = False,
    required: bool = False,
) -> str:
    name = server_name(profile_name)
    if remove:
        block, _fingerprint = render_entry(
            profile_name,
            executable,
            required=required,
        )
        return (
            f"Remove this exact managed {name} block from your user Codex config:\n"
            f"{block}"
        )
    block, _fingerprint = render_entry(
        profile_name,
        executable,
        required=required,
    )
    return block
