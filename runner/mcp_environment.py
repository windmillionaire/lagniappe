"""Locked repository bridge into the shared MCP library environment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

from runner.context import GIT_CLI, REPOSITORY_ROOT, UV_CLI
from runner.uv_bootstrap import (
    BOOTSTRAP_MANIFEST,
    UvBootstrapError,
    check_uv,
    load_manifest,
    managed_uv_path,
)


MCP_PROJECT_RELATIVE = Path("mcp")
MCP_PROJECT = REPOSITORY_ROOT / MCP_PROJECT_RELATIVE
MCP_ENVIRONMENT = MCP_PROJECT / ".venv"
MCP_ENVIRONMENT_PYTHON = MCP_ENVIRONMENT / "bin" / "python"
MCP_UV_CACHE = MCP_PROJECT / ".uv-cache"
MCP_REPAIR_COMMAND = "./setup.sh development"
MCP_BASE_PYTHON = Path(sys.executable).resolve()
MCP_BASE_PREFIX = Path(sys.base_prefix).resolve()
RUNNER_GIT_ENV = "LAGNIAPPE_RUNNER_GIT_CLI"
UV_SYNC_ARGUMENTS = (
    "sync",
    "--project",
    MCP_PROJECT_RELATIVE.as_posix(),
    "--locked",
    "--group",
    "test",
    "--python",
    str(MCP_BASE_PYTHON),
    "--no-managed-python",
    "--no-python-downloads",
    "--no-config",
)
_ENVIRONMENT_PROBE = """
import importlib.util
import json
import sys

origins = {}
for name in ("lagniappe_mcp", "mcp", "pytest", "uv_build"):
    spec = importlib.util.find_spec(name)
    origins[name] = None if spec is None else spec.origin
print(json.dumps({
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "version": list(sys.version_info[:2]),
    "origins": origins,
}))
""".strip()
_PYTEST_RESULT_DRIVER = """
import json
import os
from pathlib import Path
import sys

repository_root = Path(sys.argv[1]).resolve()
result_path = Path(sys.argv[2]).resolve()
del sys.argv[1:3]

sys.path.insert(0, str(repository_root))
from testing.utility import evidence_results
sys.path.pop(0)

def capture_results(_repo_root, _command, outcomes, exitstatus):
    payload = {
        "exit_status": int(exitstatus),
        "outcomes": outcomes,
    }
    temporary = result_path.with_name(
        f".{result_path.name}.{os.getpid()}.tmp"
    )
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\\n")
    os.replace(temporary, result_path)

evidence_results._write_manifest = capture_results

import pytest
raise SystemExit(pytest.main(sys.argv[1:], plugins=[evidence_results]))
""".strip()


class McpEnvironmentError(RuntimeError):
    """A fail-closed error from the repository-only package bridge."""


def _repair_error(message: str) -> McpEnvironmentError:
    return McpEnvironmentError(f"{message} Run {MCP_REPAIR_COMMAND} to repair it.")


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("UV_") or name in {
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTEST_ADDOPTS",
            "PYTEST_PLUGINS",
            "VIRTUAL_ENV",
        }:
            environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["UV_NO_BUILD"] = "1"
    environment["UV_CACHE_DIR"] = str(MCP_UV_CACHE)
    environment["UV_PROJECT_ENVIRONMENT"] = str(MCP_ENVIRONMENT)
    if GIT_CLI:
        environment[RUNNER_GIT_ENV] = str(GIT_CLI)
    else:
        environment.pop(RUNNER_GIT_ENV, None)
    return environment


def verify_managed_uv(
    *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> Path:
    """Verify that the bridge and manifest select the same managed uv binary."""
    try:
        manifest = load_manifest(BOOTSTRAP_MANIFEST)
        expected = managed_uv_path(manifest_path=BOOTSTRAP_MANIFEST)
        project = tomllib.loads(
            (MCP_PROJECT / "pyproject.toml").read_text(encoding="utf-8")
        )
        required_version = project["tool"]["uv"]["required-version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        raise _repair_error("Managed uv project metadata validation failed.") from error
    except UvBootstrapError as error:
        raise _repair_error(
            f"Managed uv manifest validation failed: {error}"
        ) from error
    if required_version != f"=={manifest.version}":
        raise _repair_error(
            "Managed uv manifest and package required-version do not match."
        )
    if Path(UV_CLI) != expected:
        raise _repair_error(
            "Managed uv path does not match the committed bootstrap manifest."
        )
    try:
        return check_uv(manifest_path=BOOTSTRAP_MANIFEST, run=run)
    except UvBootstrapError as error:
        raise _repair_error(f"Managed uv verification failed: {error}") from error


def _verify_environment_python(*, editable: bool, run=subprocess.run) -> Path:
    try:
        result = run(
            [str(MCP_ENVIRONMENT_PYTHON), "-I", "-c", _ENVIRONMENT_PROBE],
            cwd=REPOSITORY_ROOT,
            env=_child_environment(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _repair_error(
            "The synchronized MCP package interpreter could not be executed."
        ) from error
    if result.returncode != 0:
        raise _repair_error(
            "The synchronized MCP package interpreter failed its isolation check."
        )
    try:
        payload = json.loads(result.stdout)
        prefix = Path(payload["prefix"]).resolve()
        base_prefix = Path(payload["base_prefix"]).resolve()
        version = payload["version"]
        origins = payload["origins"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _repair_error(
            "The synchronized MCP package interpreter returned invalid diagnostics."
        ) from error

    if not isinstance(origins, dict):
        raise _repair_error(
            "The synchronized MCP package interpreter returned invalid package diagnostics."
        )
    expected_environment = MCP_ENVIRONMENT.resolve()
    expected_adapter_root = (
        (MCP_PROJECT / "src").resolve() if editable else expected_environment
    )
    if (
        prefix != expected_environment
        or base_prefix != MCP_BASE_PREFIX
        or base_prefix == prefix
        or version != [3, 14]
    ):
        raise _repair_error(
            "The synchronized MCP package interpreter is not the expected Python 3.14 environment."
        )
    for package_name in ("mcp", "pytest", "uv_build"):
        origin = origins.get(package_name)
        if not isinstance(origin, str) or not Path(origin).resolve().is_relative_to(
            expected_environment
        ):
            raise _repair_error(
                f"The MCP package environment did not isolate {package_name}."
            )
    adapter_origin = origins.get("lagniappe_mcp")
    if not isinstance(adapter_origin, str) or not Path(
        adapter_origin
    ).resolve().is_relative_to(expected_adapter_root):
        raise _repair_error(
            "The MCP adapter did not resolve from its expected shared adapter package location."
        )
    return MCP_ENVIRONMENT_PYTHON


def sync_environment(
    *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> Path:
    """Synchronize the shared adapter package environment from its exact uv lock."""
    verify_managed_uv(run=run)
    command = [str(UV_CLI), *UV_SYNC_ARGUMENTS]
    try:
        result = run(
            command,
            cwd=REPOSITORY_ROOT,
            env=_child_environment(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _repair_error(
            "Locked MCP package environment sync could not start."
        ) from error
    if result.returncode != 0:
        raise _repair_error(
            "Locked MCP package environment sync failed; the lock may be stale "
            "or a binary dependency may be unavailable."
        )
    return MCP_ENVIRONMENT_PYTHON


def prepare_environment(
    *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> Path:
    """Synchronize and verify the isolated package interpreter."""
    sync_environment(run=run)
    return _verify_environment_python(editable=True, run=run)


def check_environment(
    *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> Path:
    """Verify an already-synchronized package environment without invoking uv."""
    if os.environ.get("LAGNIAPPE_HOSTED_E2E") != "true":
        raise _repair_error(
            "A non-editable prebuilt MCP environment is accepted only by the "
            "hosted E2E runner."
        )
    return _verify_environment_python(editable=False, run=run)


def run_python(
    arguments: Sequence[str | Path],
    *,
    prepared: bool = False,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Run arguments with isolated mode in the verified package interpreter."""
    python = MCP_ENVIRONMENT_PYTHON if prepared else prepare_environment(run=run)
    command = [str(python), "-I", *[str(argument) for argument in arguments]]
    try:
        result = run(
            command,
            cwd=REPOSITORY_ROOT,
            env=_child_environment(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _repair_error("MCP package command could not start.") from error
    return result.returncode


def run_pytest(
    arguments: Sequence[str],
    *,
    prepared: bool = False,
    result_path: Path | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Run adapter tests in isolation and optionally transport their results."""
    command = []
    if result_path is not None:
        command.extend(
            [
                "-c",
                _PYTEST_RESULT_DRIVER,
                str(REPOSITORY_ROOT),
                str(Path(result_path)),
            ]
        )
    else:
        command.extend(["-m", "pytest"])
    return run_python(
        [
            *command,
            "-c",
            "testing/pytest.ini",
            "--rootdir=.",
            "--noconftest",
            "-p",
            "anyio.pytest_plugin",
            *arguments,
        ],
        prepared=prepared,
        run=run,
    )
