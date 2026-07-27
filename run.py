#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import os
import re
import signal
import subprocess
import sys

from runner.context import (
    GCLOUD_CLI,
    GIT_CLI,
    REPOSITORY_ROOT,
    format_command,
    python_command,
)
from runner.gcloud import activate_repository_gcloud

if len(sys.argv) > 1 and sys.argv[1] in {"browser-review", "test", "test-server"}:
    os.environ["FLASK_ENV"] = "testing"


def includes_e2e_tests(test_args: list[str]) -> bool:
    """Return whether normalized pytest arguments include the E2E suite."""
    target_indexes = _positional_arg_indexes(test_args)
    targets = [test_args[index] for index in sorted(target_indexes)]
    normalized_targets = [
        target.replace("\\", "/").split("::", 1)[0].rstrip("/")
        for target in targets
    ]
    return not normalized_targets or any(
        target == "testing/tests_e2e"
        or target.startswith("testing/tests_e2e/")
        or "/testing/tests_e2e/" in target
        for target in normalized_targets
    )


def configure_test_environment(test_args: list[str]) -> None:
    """Set test env vars before pytest imports the app package."""
    os.environ["FLASK_ENV"] = "testing"
    if includes_e2e_tests(test_args):
        from runner.testing import ensure_test_frontend_bundle

        ensure_test_frontend_bundle()


PYTEST_CONFIG = "testing/pytest.ini"
TRACEABILITY_RESULTS_PLUGIN = "testing.utility.traceability_results"
TEST_SUITE_ALIASES = {
    "unit": ["testing/tests_unit/"],
    "e2e": ["testing/tests_e2e/"],
    "js": ["testing/tests_js/"],
    "tooling": ["testing/tests_tooling/"],
    "setup": [
        "testing/tests_tooling/test_001a_setup_validation_config.py",
        "testing/tests_tooling/test_001b_setup_providers.py",
        "testing/tests_tooling/test_001c_setup_runtime_resources.py",
        "testing/tests_tooling/test_001e_setup_orchestration.py",
        "testing/tests_tooling/test_001f_setup_portability.py",
        "testing/tests_tooling/test_001g_setup_release_readiness.py",
    ],
}
SETUP_OPT_IN_TESTS = {
    "setup_drift": ("testing/tests_tooling/test_001d_setup_drift.py",),
    "setup_provider": (
        "testing/tests_e2e/001_site/test_001g_setup_provider_contracts.py",
    ),
}
PYTEST_OPTIONS_WITH_VALUES = {
    "-c",
    "-k",
    "-m",
    "-o",
    "--basetemp",
    "--confcutdir",
    "--deselect",
    "--ignore",
    "--ignore-glob",
    "--import-mode",
    "--junit-prefix",
    "--junit-xml",
    "--junitxml",
    "--lfnf",
    "--log-cli-date-format",
    "--log-cli-format",
    "--log-cli-level",
    "--log-date-format",
    "--log-file",
    "--log-file-date-format",
    "--log-file-format",
    "--log-file-level",
    "--log-format",
    "--log-level",
    "--maxfail",
    "--override-ini",
    "--pastebin",
    "--rootdir",
    "--tb",
    "--verbosity",
}
RELEASES_DIR = REPOSITORY_ROOT / "documentation/releases"
REPORTING_PRIVACY_MARKDOWN_PATH = REPOSITORY_ROOT / "ERROR_REPORTING_PRIVACY.md"
REPORTING_PRIVACY_TEMPLATE_PATH = (
    REPOSITORY_ROOT / "lagniappe/web/templates/home/reporting_privacy.html"
)
PR_DISPOSABLE_GENERATED_PATHS = (
    "lagniappe/web/static",
    "lagniappe/web/start/styles/icons.py",
    "lagniappe/web/start/styles/styles.py",
)
PR_PRESERVED_LOCAL_PATHS = (
    "config/files",
    "index.yaml",
    "lagniappe.yaml",
)
PR_GENERATED_PATHS = (
    *PR_PRESERVED_LOCAL_PATHS,
    *PR_DISPOSABLE_GENERATED_PATHS,
)
PR_BUILD_ID_PATH = "config/constants.py"


def _strip_runner_args(test_args: list[str]) -> tuple[bool, list[str]]:
    strict_relations = "--strict" in test_args
    pytest_args = [arg for arg in test_args if arg not in {"--strict", "--"}]
    return strict_relations, pytest_args


def _positional_arg_indexes(args: list[str]) -> set[int]:
    indexes = set()
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg in PYTEST_OPTIONS_WITH_VALUES:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        indexes.add(index)
    return indexes


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_normalize_test_args_adds_setup_opt_in_targets_without_filenames
# @features testing setup
# @dimensions cli-routing pytest-markers opt-in
def _resolve_setup_opt_in_args(args: list[str]) -> tuple[list[str], list[str]]:
    """Resolve setup opt-in markers to their otherwise uncollected test files."""
    resolved_args = list(args)
    selected_markers = set()

    for index, arg in enumerate(resolved_args[:-1]):
        if arg != "-m":
            continue

        marker_expression = resolved_args[index + 1]
        if marker_expression == "provider":
            marker_expression = "setup_drift or setup_provider"
            resolved_args[index + 1] = marker_expression

        marker_tokens = set(
            re.findall(r"[A-Za-z_][A-Za-z0-9_]*", marker_expression)
        )
        selected_markers.update(marker_tokens.intersection(SETUP_OPT_IN_TESTS))

    targets = []
    for marker in SETUP_OPT_IN_TESTS:
        if marker in selected_markers:
            targets.extend(SETUP_OPT_IN_TESTS[marker])

    return resolved_args, targets


def normalize_test_args(test_args: list[str]) -> tuple[bool, list[str]]:
    """Normalize runner-only flags and suite aliases for pytest."""
    strict_relations, pytest_args = _strip_runner_args(test_args)
    positional_indexes = _positional_arg_indexes(pytest_args)
    setup_alias_requested = any(
        pytest_args[index] == "setup" for index in positional_indexes
    )
    setup_opt_in_targets = []
    if setup_alias_requested:
        pytest_args, setup_opt_in_targets = _resolve_setup_opt_in_args(pytest_args)
        positional_indexes = _positional_arg_indexes(pytest_args)

    has_explicit_target = any(
        pytest_args[index] not in TEST_SUITE_ALIASES for index in positional_indexes
    )

    normalized = []
    for index, arg in enumerate(pytest_args):
        if index in positional_indexes and arg in TEST_SUITE_ALIASES:
            if has_explicit_target:
                continue
            normalized.extend(TEST_SUITE_ALIASES[arg])
            if arg == "setup":
                normalized.extend(setup_opt_in_targets)
            continue
        normalized.append(arg)

    return strict_relations, normalized


def pytest_command(pytest_args: list[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        PYTEST_CONFIG,
        "-p",
        TRACEABILITY_RESULTS_PLUGIN,
        *pytest_args,
    ]


def _forward_signal_to_process_group(process: subprocess.Popen, signum: int) -> None:
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def _run_pytest_subprocess(command: list[str]) -> int:
    print("Running:", format_command(command), flush=True)
    process = subprocess.Popen(
        command,
        cwd=REPOSITORY_ROOT,
        start_new_session=True,
    )
    previous_handlers = {}

    def forward_signal(signum, frame):
        _forward_signal_to_process_group(process, signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, forward_signal)

    try:
        return process.wait()
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def run_tests(test_args: list[str]) -> int:
    """Run pytest through the repo wrapper.

    Examples:
        python run.py test
        python run.py test unit
        python run.py test e2e
        python run.py test js
        python run.py test tooling
        python run.py test setup
        python run.py test path/to/test_file.py::test_name
        python run.py test --strict unit
        python run.py test -- -k "keyword"
    """
    strict_relations, pytest_args = normalize_test_args(test_args)
    if strict_relations or includes_e2e_tests(pytest_args):
        os.environ["STRICT_RELATION_LOADS"] = "1"

    configure_test_environment(pytest_args)
    e2e_tests = includes_e2e_tests(pytest_args)
    try:
        activate_repository_gcloud(
            ensure_adc=e2e_tests,
            allow_runtime_adc=e2e_tests,
            allow_adc_login=False,
        )
    except RuntimeError as error:
        print(f"Test startup stopped: {error}")
        return 1
    command_variable = "LAGNIAPPE_TEST_COMMAND"
    previous_command = os.environ.get(command_variable)
    os.environ[command_variable] = json.dumps(
        [sys.executable, str(REPOSITORY_ROOT / "run.py"), "test", *test_args]
    )
    try:
        return _run_pytest_subprocess(pytest_command(pytest_args))
    finally:
        if previous_command is None:
            os.environ.pop(command_variable, None)
        else:
            os.environ[command_variable] = previous_command


def run_test_server_command(command_args: list[str]) -> int:
    from testing.utility import test_server_seed

    parser = argparse.ArgumentParser(
        prog="run.py test-server",
        description="Manage the detached Flask server used for browser-based test review.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--start",
        action="store_true",
        help="Start the testing server in the background.",
    )
    action.add_argument(
        "--teardown",
        action="store_true",
        help="Stop the background testing server and clean test data.",
    )
    parser.add_argument(
        "--load",
        action="append",
        choices=test_server_seed.available_pack_names(),
        metavar="PACK",
        help=(
            "After --start, load a browser-review seed data pack. "
            "Repeatable. Available: "
            + ", ".join(test_server_seed.available_pack_names())
        ),
    )
    args = parser.parse_args(command_args)
    if args.load and not args.start:
        parser.error("--load can only be used with --start")

    if not GCLOUD_CLI:
        print("gcloud CLI not found")
        return 1

    from config import SETTINGS
    from runner.testing import (
        start_managed_test_server,
        teardown_managed_test_server,
    )

    try:
        if args.start:
            pid = start_managed_test_server()
            print(
                f"Test server started at "
                f"{SETTINGS.test_config['BASE_URL']} (pid {pid})"
            )
            if args.load:
                summary = test_server_seed.load_packs(args.load)
                report = test_server_seed.LOAD_REPORT
                print(
                    "Loaded test-server seed pack(s): "
                    + ", ".join(summary["packs"])
                    + f" ({len(summary['resources'])} resources)"
                )
                for landing in summary["landings"]:
                    print(f"Seed landing: {landing['name']} - {landing['url']}")
                print(f"Seed report written to {report}")
            return 0

        pid = teardown_managed_test_server()
        if pid:
            print(f"Test server torn down (pid {pid})")
        else:
            print("Test server torn down")
        return 0
    except RuntimeError as error:
        print(f"Test server command stopped: {error}")
        return 1


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_auth_runs_interactive_human_adc_alignment
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_auth_reports_alignment_failure
# @features auth
# @dimensions adc runtime-identity interactive explicit-command
def run_auth_command(command_args: list[str]) -> int:
    """Interactively align human ADC for local runtime impersonation."""
    parser = argparse.ArgumentParser(
        prog="run.py auth",
        description=(
            "Authenticate human Application Default Credentials used for "
            "this checkout's local runtime impersonation."
        ),
    )
    parser.parse_args(command_args)

    if not GCLOUD_CLI:
        print("Authentication failed: gcloud CLI not found.")
        return 1

    try:
        activate_repository_gcloud(
            ensure_adc=True,
            allow_runtime_adc=False,
            allow_adc_login=True,
            select_adc_target=True,
        )
    except RuntimeError as error:
        print(f"Authentication failed: {error}")
        return 1

    print(
        "Application Default Credentials are ready; local app clients will "
        "use the configured runtime service account."
    )
    return 0


def _release_note_path(version: str) -> Path:
    return RELEASES_DIR / f"{version}.md"


def _ensure_release_note(version: str) -> Path:
    path = _release_note_path(version)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Version {version}\n\n", encoding="utf-8")
    return path


def _append_version_note(version: str, message: str) -> Path:
    path = _ensure_release_note(version)
    content = path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        content += "\n"
    path.write_text(f"{content}- {message}\n", encoding="utf-8")
    return path


def _current_version() -> str:
    from config import SETTINGS

    return str(SETTINGS.APP.get("VERSION") or SETTINGS.NODE.get("version"))


def _update_reporting_privacy_version(version: str) -> tuple[Path, ...]:
    targets = (
        (
            REPORTING_PRIVACY_MARKDOWN_PATH,
            re.compile(
                r"^(\*\*Applies to:\*\* Lagniappe )[^\r\n]*?([ \t]*)$",
                flags=re.MULTILINE,
            ),
        ),
        (
            REPORTING_PRIVACY_TEMPLATE_PATH,
            re.compile(
                r"^([ \t]*Applies to: Lagniappe )[^\r\n<]*?([ \t]*)$",
                flags=re.MULTILINE,
            ),
        ),
    )
    updates = []
    for path, pattern in targets:
        content = path.read_text(encoding="utf-8")
        updated, count = pattern.subn(
            lambda match: f"{match.group(1)}{version}{match.group(2)}",
            content,
        )
        if count != 1:
            raise RuntimeError(
                f"Expected one Lagniappe version marker in {path}, found {count}."
            )
        updates.append((path, updated))

    for path, content in updates:
        path.write_text(content, encoding="utf-8")
    return tuple(path for path, _content in updates)


def run_version_command(command_args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="run.py version",
        description="Manage deliberate Lagniappe app versions and release notes.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("show", help="Show package, settings, and build versions.")

    set_parser = subparsers.add_parser("set", help="Set the deliberate app version.")
    set_parser.add_argument("version")

    note_parser = subparsers.add_parser("note", help="Append a version note.")
    note_parser.add_argument("message")
    note_parser.add_argument("--version")

    args = parser.parse_args(command_args)

    if args.action == "show":
        from config import SETTINGS, constants

        version = SETTINGS.APP.get("VERSION")
        package_version = SETTINGS.NODE.get("version")
        build_id = getattr(constants, "BUILD_ID", None) or version or package_version
        print(f"VERSION: {version}")
        print(f"package.json: {package_version}")
        print(f"BUILD_ID: {build_id}")
        return 0

    if args.action == "set":
        from config import File, SETTINGS
        from runner.deploy import update_package_lock_version

        SETTINGS.NODE["version"] = args.version
        SETTINGS.APP["VERSION"] = args.version
        SETTINGS.APP.pop("BUILD_ID", None)
        SETTINGS.save(File.PACKAGE_JSON, File.APP_SETTINGS_YAML)
        update_package_lock_version(args.version)
        _ensure_release_note(args.version)
        _update_reporting_privacy_version(args.version)
        print(f"VERSION set to {args.version}")
        return 0

    if args.action == "note":
        version = args.version or _current_version()
        path = _append_version_note(version, args.message)
        print(f"Added version note to {path}")
        return 0

    return 1


def run_upgrade_command(command_args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="run.py upgrade",
        description="Run the maintainer dependency-upgrade workflow.",
    )
    parser.parse_args(command_args)

    from runner.upgrade import upgrade_all

    return upgrade_all()


def run_backup_command(command_args: list[str]) -> int:
    """Create or list complete production data recovery sets."""
    parser = argparse.ArgumentParser(
        prog="run.py backup",
        description="Manage full Datastore and Cloud Storage recovery sets.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("create", help="Create a complete recovery set.")
    subparsers.add_parser("list", help="List completed recovery sets.")
    args = parser.parse_args(command_args)

    from runner.data_recovery import (
        DataRecoveryError,
        create_backup,
        list_backups,
    )

    try:
        if args.action == "create":
            create_backup()
        else:
            list_backups()
    except DataRecoveryError as error:
        print(f"Backup command failed: {error}")
        return 1
    return 0


def run_restore_command(command_args: list[str]) -> int:
    """Restore one completed production data recovery set."""
    parser = argparse.ArgumentParser(
        prog="run.py restore",
        description=(
            "Replace production Datastore and Cloud Storage contents from "
            "one completed recovery set."
        ),
    )
    parser.add_argument("backup_id", metavar="BACKUP_ID")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and describe the restore without changing data.",
    )
    args = parser.parse_args(command_args)

    from runner.data_recovery import DataRecoveryError, restore_backup

    try:
        restored = restore_backup(args.backup_id, dry_run=args.dry_run)
    except DataRecoveryError as error:
        print(f"Restore failed: {error}")
        return 1
    return 0 if restored else 1


def _run_pr_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [GIT_CLI, *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return result


def _resolve_pr_base(repo_root: Path, requested: str | None) -> str:
    candidates = [requested] if requested else ["origin/main", "main"]
    for candidate in candidates:
        result = subprocess.run(
            [GIT_CLI, "rev-parse", "--verify", f"{candidate}^{{commit}}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return candidate

    if requested:
        raise RuntimeError(f"Git base ref does not exist: {requested}")
    raise RuntimeError(
        "Could not find origin/main or main. Pass the PR base with --base REF."
    )


def _nul_paths(result: subprocess.CompletedProcess) -> set[str]:
    return {path for path in result.stdout.split("\0") if path}


def _diff_changes_build_id(result: subprocess.CompletedProcess) -> bool:
    return any(
        re.match(r"^[+-]BUILD_ID\s*=", line)
        for line in result.stdout.splitlines()
        if not line.startswith(("+++", "---"))
    )


def pr_generated_artifact_changes(repo_root: Path, base_ref: str) -> tuple[str, list[str]]:
    """Return build-managed artifacts present in the prospective PR index."""
    merge_base = _run_pr_git(
        repo_root,
        ["merge-base", "HEAD", base_ref],
    ).stdout.strip()
    if not merge_base:
        raise RuntimeError(f"Could not determine a merge base with {base_ref}")

    changed_paths = _nul_paths(
        _run_pr_git(
            repo_root,
            [
                "diff",
                "--cached",
                "--name-only",
                "-z",
                merge_base,
                "--",
                *PR_GENERATED_PATHS,
            ],
        )
    )

    build_id_changed = _diff_changes_build_id(
        _run_pr_git(
            repo_root,
            [
                "diff",
                "--cached",
                "--unified=0",
                "--no-color",
                merge_base,
                "--",
                PR_BUILD_ID_PATH,
            ],
        )
    )
    if build_id_changed:
        changed_paths.add(f"{PR_BUILD_ID_PATH} (BUILD_ID)")

    return merge_base, sorted(changed_paths)


def _restore_pr_build_id(repo_root: Path, merge_base: str) -> bool:
    base_content = _run_pr_git(
        repo_root,
        ["show", f"{merge_base}:{PR_BUILD_ID_PATH}"],
    ).stdout
    path = repo_root / PR_BUILD_ID_PATH
    if not path.is_file():
        raise RuntimeError(
            f"Cannot selectively restore BUILD_ID because {PR_BUILD_ID_PATH} "
            "is missing."
        )

    base_match = re.search(r"^BUILD_ID\s*=.*$", base_content, flags=re.MULTILINE)
    current_content = path.read_text(encoding="utf-8")
    current_match = re.search(
        r"^BUILD_ID\s*=.*$",
        current_content,
        flags=re.MULTILINE,
    )
    if not base_match or not current_match:
        raise RuntimeError(
            f"Cannot locate BUILD_ID in the merge-base and current "
            f"{PR_BUILD_ID_PATH} files."
        )

    index_changed = _diff_changes_build_id(
        _run_pr_git(
            repo_root,
            [
                "diff",
                "--cached",
                "--unified=0",
                "--no-color",
                merge_base,
                "--",
                PR_BUILD_ID_PATH,
            ],
        )
    )
    worktree_changed = current_match.group(0) != base_match.group(0)
    if not worktree_changed and not index_changed:
        return False

    if worktree_changed:
        updated = (
            current_content[: current_match.start()]
            + base_match.group(0)
            + current_content[current_match.end() :]
        )
        path.write_text(updated, encoding="utf-8")
    _run_pr_git(repo_root, ["add", "--", PR_BUILD_ID_PATH])
    return True


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_pr_clean_restores_unstaged_generated_worktree
def _pr_disposable_artifact_changes(
    repo_root: Path,
    merge_base: str,
) -> tuple[list[str], list[str]]:
    """Return tracked and untracked disposable generated worktree changes."""
    tracked_paths: set[str] = set()
    for diff_args in (
        ["diff", "--cached", "--name-only", "-z", merge_base],
        ["diff", "--name-only", "-z", merge_base],
    ):
        tracked_paths.update(
            _nul_paths(
                _run_pr_git(
                    repo_root,
                    [*diff_args, "--", *PR_DISPOSABLE_GENERATED_PATHS],
                )
            )
        )

    untracked_paths = _nul_paths(
        _run_pr_git(
            repo_root,
            [
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                *PR_DISPOSABLE_GENERATED_PATHS,
            ],
        )
    )
    return sorted(tracked_paths), sorted(untracked_paths)


def run_pr_clean_command(
    command_args: list[str],
    *,
    repo_root: Path | None = None,
) -> int:
    """Restore disposable generated output and exclude local config from the PR."""
    parser = argparse.ArgumentParser(
        prog="run.py pr-clean",
        description=(
            "Restore maintainer-owned generated files, exclude installation "
            "configuration from the PR index, and restore BUILD_ID."
        ),
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        help="PR base ref. Defaults to origin/main, then main.",
    )
    parser.add_argument(
        "--keep-build",
        action="store_true",
        help=(
            "Keep disposable generated files in the working tree while "
            "excluding them from the PR index."
        ),
    )
    args = parser.parse_args(command_args)
    repo_root = (repo_root or REPOSITORY_ROOT).resolve()

    try:
        base_ref = _resolve_pr_base(repo_root, args.base)
        merge_base, changes = pr_generated_artifact_changes(repo_root, base_ref)
        prospective_paths = [
            path for path in changes if path != f"{PR_BUILD_ID_PATH} (BUILD_ID)"
        ]
        if args.keep_build:
            cleaned_paths = prospective_paths
            if cleaned_paths:
                _run_pr_git(
                    repo_root,
                    [
                        "restore",
                        f"--source={merge_base}",
                        "--staged",
                        "--",
                        *cleaned_paths,
                    ],
                )
        else:
            preserved_paths = [
                path
                for path in prospective_paths
                if not any(
                    path == root or path.startswith(f"{root}/")
                    for root in PR_DISPOSABLE_GENERATED_PATHS
                )
            ]
            if preserved_paths:
                _run_pr_git(
                    repo_root,
                    [
                        "restore",
                        f"--source={merge_base}",
                        "--staged",
                        "--",
                        *preserved_paths,
                    ],
                )

            tracked_paths, untracked_paths = _pr_disposable_artifact_changes(
                repo_root,
                merge_base,
            )
            if tracked_paths:
                _run_pr_git(
                    repo_root,
                    [
                        "restore",
                        f"--source={merge_base}",
                        "--staged",
                        "--worktree",
                        "--",
                        *tracked_paths,
                    ],
                )
            for relative in untracked_paths:
                try:
                    (repo_root / relative).unlink()
                except FileNotFoundError:
                    pass
            cleaned_paths = sorted(
                {*preserved_paths, *tracked_paths, *untracked_paths}
            )
        build_id_restored = _restore_pr_build_id(repo_root, merge_base)
    except RuntimeError as error:
        print(f"PR clean could not run: {error}")
        return 2

    if not cleaned_paths and not build_id_restored:
        print(f"No generated PR artifacts need cleaning against {base_ref}.")
        return 0

    action = (
        "Removed generated artifacts from the PR index"
        if args.keep_build
        else "Restored generated artifacts"
    )
    print(f"{action} against {base_ref} (merge base {merge_base[:12]}):")
    for path in cleaned_paths:
        print(f"  - {path}")
    if build_id_restored:
        print(f"  - {PR_BUILD_ID_PATH} (BUILD_ID only)")
    if args.keep_build:
        print(
            "Disposable generated files remain in the working tree for testing; "
            "pr-check ignores files that are not part of the prospective commit."
        )
    else:
        print(
            "Local installation configuration remains in place; authored "
            "source and test evidence were not changed."
        )
    print(
        "If this cleanup reverses generated files from an earlier commit, "
        "commit the staged cleanup before pushing the PR."
    )
    return 0


def run_pr_check_command(
    command_args: list[str],
    *,
    repo_root: Path | None = None,
) -> int:
    """Reject contributor PRs that contain maintainer-owned build output."""
    parser = argparse.ArgumentParser(
        prog="run.py pr-check",
        description=(
            "Check that a contributor PR contains authored source only. "
            "Generated delivery files are built by the maintainer during integration."
        ),
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        help="PR base ref. Defaults to origin/main, then main.",
    )
    args = parser.parse_args(command_args)
    repo_root = (repo_root or REPOSITORY_ROOT).resolve()

    try:
        base_ref = _resolve_pr_base(repo_root, args.base)
        merge_base, changes = pr_generated_artifact_changes(repo_root, base_ref)
    except RuntimeError as error:
        print(f"PR check could not run: {error}")
        return 2

    if changes:
        print(
            f"PR check failed against {base_ref} "
            f"(merge base {merge_base[:12]}):"
        )
        for path in changes:
            print(f"  - {path}")
        print(
            "\nContributor PRs must contain authored source only. Remove these "
            "generated changes from the PR yourself or run "
            f"{python_command('run.py', 'pr-clean')}, then rerun pr-check."
        )
        print(
            "The maintainer will apply the source to main, run 'npm run build', "
            "and commit the newly generated delivery files with the source."
        )
        return 1

    print(
        f"PR generated-artifact check passed against {base_ref} "
        f"(merge base {merge_base[:12]})."
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        sys.exit(run_auth_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        sys.exit(run_tests(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "test-server":
        sys.exit(run_test_server_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "browser-review":
        from testing.utility import browser_review

        sys.exit(browser_review.main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "traceability":
        from testing.utility import traceability

        sys.exit(traceability.main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "template-contracts":
        from testing.utility import template_contracts

        sys.exit(template_contracts.main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "mutation-contracts":
        from testing.utility import mutation_contracts

        sys.exit(mutation_contracts.main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "version":
        sys.exit(run_version_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "upgrade":
        sys.exit(run_upgrade_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "backup":
        sys.exit(run_backup_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "restore":
        sys.exit(run_restore_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "pr-check":
        sys.exit(run_pr_check_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "pr-clean":
        sys.exit(run_pr_clean_command(sys.argv[2:]))

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "auth",
            "backup",
            "browser-review",
            "dev",
            "indexes",
            "deploy",
            "icons",
            "mutation-contracts",
            "pr-clean",
            "pr-check",
            "restore",
            "test",
            "test-server",
            "traceability",
            "template-contracts",
            "upgrade",
            "version",
        ],
    )
    args = parser.parse_args()

    from runner.gcloud import config_gcloud
    from runner.deploy import deploy
    from runner.development import run_dev_server
    from runner.icons import update_icons
    from runner.testing import update_test_indexes

    if not GCLOUD_CLI:
        print("gcloud CLI not found")
        sys.exit(1)

    if args.command != "dev":
        config_gcloud()

    if args.command == "indexes":
        update_test_indexes()
    elif args.command == "dev":
        sys.exit(run_dev_server())
    elif args.command == "deploy":
        deploy()
    elif args.command == "icons":
        update_icons()
