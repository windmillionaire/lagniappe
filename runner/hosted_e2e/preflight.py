"""Select, validate, and export the Git revision for a hosted test candidate."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from config import APP_DIR, SETTINGS
from runner.context import GIT_CLI, NPM_CLI
from runner.frontend_build import GitFrontendBuildReader, inspect_frontend_build
from runner.process import run_command

from .runtime import HostedE2EError


def _git(*arguments, check=True, repo_root=None):
    result = run_command(
        [GIT_CLI or "git", *map(str, arguments)],
        check=False,
        timeout=60,
        cwd=repo_root or APP_DIR,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise HostedE2EError(detail or "Git command failed.")
    return result


def require_clean_source(repo_root: Path = APP_DIR) -> str:
    """Return HEAD when authored and runtime source exactly match the commit."""
    status = run_command(
        [
            GIT_CLI or "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude)lagniappe/web/static/**",
        ],
        cwd=Path(repo_root),
        check=False,
        timeout=60,
    )
    if status.returncode != 0:
        raise HostedE2EError("Could not inspect the Git working tree.")
    if status.stdout.strip():
        raise HostedE2EError(
            "Hosted E2E versions require a clean working tree so the app, "
            "runner image, and evidence all identify one committed source."
        )
    head = run_command(
        [GIT_CLI or "git", "rev-parse", "HEAD"],
        cwd=Path(repo_root),
        check=False,
        timeout=60,
    )
    source = head.stdout.strip().casefold()
    if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise HostedE2EError("Hosted E2E requires a committed Git HEAD.")
    return source


def _require_committed_production_build(
    source,
    *,
    repo_root=APP_DIR,
    expected_version=None,
):
    """Validate and return the production build ID stored in ``source``."""
    configured_version = (
        SETTINGS.APP.get("VERSION") if expected_version is None else expected_version
    )
    expected_version = (
        str(configured_version).strip() if configured_version is not None else ""
    )
    if not expected_version:
        raise HostedE2EError(
            "Hosted E2E create requires a configured frontend build version."
        )
    return _committed_build_id(source, repo_root, expected_version=expected_version)


def _committed_build_id(source: str, repo_root: Path, *, expected_version: str | None = None) -> str:
    validation, issues = inspect_frontend_build(
        GitFrontendBuildReader(repo_root, revision=source),
        expected_mode="production",
        expected_version=expected_version,
    )
    if issues or validation is None:
        detail = "; ".join(issues)
        raise HostedE2EError(
            "Hosted E2E requires a coherent committed production frontend "
            f"build. Run `npm run build`, commit every generated artifact, and "
            f"retry. {detail}"
        )
    return validation.metadata["build_id"]


def _resolve_create_preflight_base(requested=None):
    """Resolve the release base to one exact commit for the create preflight."""
    candidates = [requested] if requested else ["origin/main", "main"]
    for candidate in candidates:
        result = _git("rev-parse", "--verify", f"{candidate}^{{commit}}", check=False)
        revision = (result.stdout or "").strip().casefold()
        if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", revision):
            return revision
    if requested:
        raise HostedE2EError(f"Git base ref does not exist: {requested}")
    raise HostedE2EError(
        "Could not find origin/main or main. Pass the hosted create release "
        "base with --base REF."
    )


def _run_create_preflight(source, *, base_ref=None):
    """Validate the HEAD candidate before hosted create can touch the provider."""
    if not NPM_CLI:
        raise HostedE2EError("npm is required for the hosted E2E create preflight.")
    base_revision = _resolve_create_preflight_base(base_ref)
    python = sys.executable
    run_py = APP_DIR / "run.py"
    gates = (
        ("authored frontend source", [NPM_CLI or "npm", "run", "check"]),
        ("frontend type checking", [NPM_CLI or "npm", "run", "typecheck"]),
        ("Python source", [python, "-m", "ruff", "check", "."]),
        ("Python type checking", [python, "-m", "basedpyright", "--warnings"]),
        (
            "locked MCP environment",
            [python, "-c", "from runner.mcp_environment import prepare_environment; prepare_environment()"],
        ),
        (
            "MCP type checking",
            [python, "-m", "basedpyright", "--warnings", "--project", "mcp/pyrightconfig.json"],
        ),
        (
            "tooling tests",
            [python, run_py, "test", "--no-test-evidence", "tooling"],
        ),
        (
            "template contracts",
            [python, run_py, "template-contracts", "--check", "--no-report"],
        ),
        (
            "style and icon contracts",
            [
                python,
                run_py,
                "style-contracts",
                "--check",
                "--no-report",
                "--no-manifest",
            ],
        ),
        (
            "mutation contracts",
            [python, run_py, "mutation-contracts", "--check"],
        ),
        (
            "complete release tree",
            [python, run_py, "release-check", "--base", base_revision],
        ),
    )
    print(
        f"Running hosted E2E create preflight for HEAD {source} "
        f"against comparison base {base_revision}."
    )
    for label, command in gates:
        result = run_command(
            command,
            check=False,
            capture_output=False,
            timeout=1800,
            cwd=APP_DIR,
        )
        if result.returncode != 0:
            raise HostedE2EError(
                f"Hosted E2E create preflight failed while checking {label}."
            )
    return base_revision


@contextmanager
def _committed_source_tree(source, *, repo_root=APP_DIR):
    """Yield a temporary source tree exported from one exact Git commit."""
    with tempfile.TemporaryDirectory(prefix="lagniappe-hosted-e2e-") as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "source.tar"
        source_root = temporary_root / "source"
        source_root.mkdir()
        result = run_command(
            [
                GIT_CLI or "git",
                "archive",
                "--format=tar",
                f"--output={archive_path}",
                source,
            ],
            cwd=Path(repo_root),
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise HostedE2EError(
                detail or "Could not export the committed hosted-E2E source."
            )
        shutil.unpack_archive(archive_path, source_root, format="tar")
        yield source_root
