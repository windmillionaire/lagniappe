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
)
from runner.gcloud import activate_repository_gcloud
from runner.frontend_build import GitFrontendBuildReader, inspect_frontend_build
from runner.pytest_routing import (
    PYTEST_CONFIG,
    PYTEST_ROUTING_PLUGIN,
    TRACEABILITY_RESULTS_PLUGIN,
    PytestRoutingError,
    normalize_pytest_invocation,
)

if len(sys.argv) > 1 and sys.argv[1] in {"browser-review", "test", "test-server"}:
    os.environ["FLASK_ENV"] = "testing"


# @testable false
# @covered-by run.py::configure_test_environment
# @covered-by run.py::run_tests
# @reason pure environment flag shared by the two test-runner launch boundaries
def hosted_e2e_enabled() -> bool:
    return os.environ.get("LAGNIAPPE_HOSTED_E2E", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_configure_test_environment_only_sets_import_environment
# @matrix testing : environment
def configure_test_environment(*, includes_e2e: bool) -> None:
    """Set test env vars before pytest imports the app package."""
    os.environ["FLASK_ENV"] = "testing"


RELEASES_DIR = REPOSITORY_ROOT / "documentation/releases"
REPORTING_PRIVACY_MARKDOWN_PATH = REPOSITORY_ROOT / "ERROR_REPORTING_PRIVACY.md"
REPORTING_PRIVACY_TEMPLATE_PATH = (
    REPOSITORY_ROOT / "lagniappe/web/templates/home/reporting_privacy.html"
)
RELEASE_LOCAL_PATHS = (
    "config/files",
    "index.yaml",
    "lagniappe.yaml",
)
RELEASE_BUILD_ID_PATH = "config/constants.py"
RELEASE_BUILD_METADATA_PATH = "lagniappe/web/static/build.json"
RELEASE_SERVICE_WORKER_PATH = "lagniappe/web/static/sw.js"
RELEASE_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)
RELEASE_BUILD_ID_PATTERN = re.compile(r"^b[0-9a-f]{7}$")


def pytest_command(pytest_args: list[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        PYTEST_CONFIG,
        "-p",
        TRACEABILITY_RESULTS_PLUGIN,
        "-p",
        PYTEST_ROUTING_PLUGIN,
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


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_e2e_aligns_adc_before_pytest
# @tests tests_tooling/test_007_run_py_test_command.py::test_hosted_e2e_runner_skips_local_build_and_gcloud_activation
# @pairs hosted-e2e:frontend-build testing:adc
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
    try:
        invocation = normalize_pytest_invocation(test_args, REPOSITORY_ROOT)
    except PytestRoutingError as error:
        print(f"Test argument error: {error}", file=sys.stderr)
        return 4

    if invocation.strict_relations or invocation.includes_e2e:
        os.environ["STRICT_RELATION_LOADS"] = "1"

    configure_test_environment(includes_e2e=invocation.includes_e2e)
    if not hosted_e2e_enabled():
        try:
            activate_repository_gcloud(
                ensure_adc=invocation.includes_e2e,
                allow_runtime_adc=invocation.includes_e2e,
                allow_adc_login=False,
            )
        except RuntimeError as error:
            print(f"Test startup stopped: {error}")
            return 1
    command_variable = "LAGNIAPPE_TEST_COMMAND"
    previous_command = os.environ.get(command_variable)
    full_command = [
        sys.executable,
        str(REPOSITORY_ROOT / "run.py"),
        "test",
        *test_args,
    ]
    os.environ[command_variable] = json.dumps(full_command)
    authority = None
    server_process = None
    crossed_data_boundary = False
    session_environment = {}
    try:
        if invocation.includes_e2e and not hosted_e2e_enabled():
            from runner.test_session import (
                SESSION_MODE_ENV,
                SESSION_NONCE_ENV,
                acquire_test_session,
            )
            from runner.testing import (
                cleanup_test_data,
                ensure_test_frontend_bundle,
                prepare_test_artifacts,
                require_legacy_test_server_clear,
                require_server_port_available,
                run_test_server,
            )

            require_legacy_test_server_clear()
            authority = acquire_test_session("local-e2e", full_command)
            for name, value in (
                (SESSION_NONCE_ENV, authority.nonce),
                (SESSION_MODE_ENV, authority.mode),
            ):
                session_environment[name] = os.environ.get(name)
                os.environ[name] = value

            from config import SETTINGS

            require_server_port_available(SETTINGS.test_config["BASE_URL"])
            ensure_test_frontend_bundle(authority)
            prepare_test_artifacts(authority)
            # Treat cleanup as crossed before invoking it: partial provider
            # deletion still requires the guarded final cleanup path.
            crossed_data_boundary = True
            cleanup_test_data(authority)
            server_process = run_test_server(authority)
            authority.update(phase="ready")

        return _run_pytest_subprocess(pytest_command(list(invocation.pytest_args)))
    except RuntimeError as error:
        print(f"Test startup stopped: {error}")
        return 1
    finally:
        try:
            if authority is not None:
                from runner.testing import (
                    cleanup_test_data,
                    terminate_test_server_process,
                )

                try:
                    if server_process is not None:
                        terminate_test_server_process(server_process)
                    if crossed_data_boundary:
                        cleanup_test_data(authority)
                    authority.complete()
                except BaseException:
                    authority.mark_recovery_required()
                    raise
        finally:
            for name, previous in session_environment.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous
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
    action.add_argument(
        "--status",
        action="store_true",
        help="Show the recorded session, process, and health status.",
    )
    action.add_argument(
        "--recover",
        action="store_true",
        help="Recover a stale session only after proving its owner exited.",
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

    if not args.status and not GCLOUD_CLI:
        print("gcloud CLI not found")
        return 1

    from config import SETTINGS
    from runner.testing import (
        recover_managed_test_server,
        start_managed_test_server,
        test_server_status,
        teardown_managed_test_server,
    )

    try:
        if args.start:
            result = start_managed_test_server(args.load or ())
            print(
                f"Test server started at "
                f"{SETTINGS.test_config['BASE_URL']} (pid {result['pid']}, "
                f"keeper {result['keeper_pid']})"
            )
            summary = result.get("seed_summary")
            if summary:
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

        if args.status:
            status = test_server_status()
            print(json.dumps(status, indent=2, sort_keys=True))
            return 0

        if args.recover:
            result = recover_managed_test_server()
            print(result["detail"])
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
# @matrix auth : explicit-command interactive
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


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_version_show_uses_package_only_before_generated_settings_exist
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_version_note_appends_concise_release_entry
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_version_set_updates_package_settings_and_release_file
# @pair version:cli-routing
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
        from config import File, SETTINGS, constants

        package_version = SETTINGS.NODE.get("version")
        version = SETTINGS.APP.get("VERSION")
        if not File.APP_SETTINGS_YAML.exists():
            version = package_version
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


def _run_release_git(
    repo_root: Path,
    args: list[str],
) -> subprocess.CompletedProcess:
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


def _resolve_release_base(repo_root: Path, requested: str | None) -> str:
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
        "Could not find origin/main or main. Pass the release base with --base REF."
    )


def _nul_paths(result: subprocess.CompletedProcess) -> set[str]:
    return {path for path in result.stdout.split("\0") if path}


def _diff_changes_build_id(result: subprocess.CompletedProcess) -> bool:
    return any(
        re.match(r"^[+-]BUILD_ID\s*=", line)
        for line in result.stdout.splitlines()
        if not line.startswith(("+++", "---"))
    )


def _read_release_text(
    repo_root: Path,
    relative_path: str,
    issues: list[str],
) -> str | None:
    try:
        return _run_release_git(
            repo_root,
            ["show", f":{relative_path}"],
        ).stdout
    except RuntimeError as error:
        issues.append(f"{relative_path} could not be read from the index: {error}")
        return None


def _read_release_json(
    repo_root: Path,
    relative_path: str,
    issues: list[str],
) -> dict:
    content = _read_release_text(repo_root, relative_path, issues)
    if content is None:
        return {}
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        issues.append(f"{relative_path} could not be read as JSON: {error}")
        return {}
    if not isinstance(value, dict):
        issues.append(f"{relative_path} must contain a JSON object.")
        return {}
    return value


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_release_check_accepts_complete_release
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_release_check_rejects_development_build
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_py_release_check_rejects_incomplete_release
# @matrix release : build-mode delivery-tree
def release_readiness_issues(
    repo_root: Path,
    base_ref: str,
) -> tuple[str, list[str]]:
    """Return release-tree problems in the prospective commit."""
    merge_base = _run_release_git(
        repo_root,
        ["merge-base", "HEAD", base_ref],
    ).stdout.strip()
    if not merge_base:
        raise RuntimeError(f"Could not determine a merge base with {base_ref}")

    changed_paths = _nul_paths(
        _run_release_git(
            repo_root,
            ["diff", "--cached", "--name-only", "-z", merge_base],
        )
    )
    issues = []

    local_paths = sorted(
        path
        for path in changed_paths
        if any(
            path == root or path.startswith(f"{root}/")
            for root in RELEASE_LOCAL_PATHS
        )
    )
    if local_paths:
        issues.append(
            "Installation-local files are present in the release: "
            + ", ".join(local_paths)
        )

    for required_path in (
        RELEASE_BUILD_METADATA_PATH,
        RELEASE_SERVICE_WORKER_PATH,
    ):
        if required_path not in changed_paths:
            issues.append(
                f"{required_path} was not changed by a fresh production build."
            )

    build_id_changed = _diff_changes_build_id(
        _run_release_git(
            repo_root,
            [
                "diff",
                "--cached",
                "--unified=0",
                "--no-color",
                merge_base,
                "--",
                RELEASE_BUILD_ID_PATH,
            ],
        )
    )
    if not build_id_changed:
        issues.append(
            f"{RELEASE_BUILD_ID_PATH} does not contain a newly generated BUILD_ID."
        )

    package = _read_release_json(repo_root, "package.json", issues)
    package_lock = _read_release_json(repo_root, "package-lock.json", issues)
    build_metadata = _read_release_json(
        repo_root,
        RELEASE_BUILD_METADATA_PATH,
        issues,
    )

    version = package.get("version")
    if not isinstance(version, str) or not RELEASE_VERSION_PATTERN.fullmatch(version):
        issues.append("package.json version must use stable X.Y.Z form.")
        version = None

    lock_version = package_lock.get("version")
    lock_root = package_lock.get("packages", {})
    lock_root_version = (
        lock_root.get("", {}).get("version")
        if isinstance(lock_root, dict)
        and isinstance(lock_root.get(""), dict)
        else None
    )
    if version and (lock_version != version or lock_root_version != version):
        issues.append(
            "package-lock.json root versions do not match package.json "
            f"version {version}."
        )

    if version and build_metadata.get("version") != version:
        issues.append(
            f"{RELEASE_BUILD_METADATA_PATH} version does not match "
            f"package.json version {version}."
        )
    if build_metadata.get("mode") != "production":
        issues.append(
            f"{RELEASE_BUILD_METADATA_PATH} must identify a production build."
        )

    _frontend_validation, frontend_issues = inspect_frontend_build(
        GitFrontendBuildReader(repo_root, index=True),
        expected_mode="production",
        expected_version=version,
    )
    issues.extend(f"Frontend build: {issue}" for issue in frontend_issues)

    if version:
        release_note_relative = f"documentation/releases/{version}.md"
        release_note = _read_release_text(
            repo_root,
            release_note_relative,
            issues,
        )
        if release_note is not None:
            if not release_note.startswith(f"# Version {version}\n"):
                issues.append(
                    f"{release_note_relative} has the wrong title."
                )
            if not re.search(r"(?m)^- \S", release_note):
                issues.append(
                    f"{release_note_relative} has no release entries."
                )

    constants_content = (
        _read_release_text(repo_root, RELEASE_BUILD_ID_PATH, issues) or ""
    )
    build_id_match = re.search(
        r'^BUILD_ID\s*=\s*"([^"]+)"\s*$',
        constants_content,
        flags=re.MULTILINE,
    )
    build_id = build_id_match.group(1) if build_id_match else None
    if not build_id or not RELEASE_BUILD_ID_PATTERN.fullmatch(build_id):
        issues.append(
            f"{RELEASE_BUILD_ID_PATH} must contain a generated "
            "eight-character BUILD_ID."
        )
    elif build_metadata.get("build_id") != build_id:
        issues.append(
            f"{RELEASE_BUILD_METADATA_PATH} build_id does not match "
            f"{RELEASE_BUILD_ID_PATH}."
        )
    else:
        service_worker = _read_release_text(
            repo_root,
            RELEASE_SERVICE_WORKER_PATH,
            issues,
        )
        if service_worker is not None:
            if build_id not in service_worker:
                issues.append(
                    f"{RELEASE_SERVICE_WORKER_PATH} does not contain "
                    f"the current build ID {build_id}."
                )

    return merge_base, issues


def run_release_check_command(
    command_args: list[str],
    *,
    repo_root: Path | None = None,
) -> int:
    """Validate a complete release or hotfix PR tree."""
    parser = argparse.ArgumentParser(
        prog="run.py release-check",
        description=(
            "Check version metadata, release notes, local-file boundaries, "
            "and the maintainer-generated delivery build."
        ),
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        help="Release base ref. Defaults to origin/main, then main.",
    )
    args = parser.parse_args(command_args)
    repo_root = (repo_root or REPOSITORY_ROOT).resolve()

    try:
        base_ref = _resolve_release_base(repo_root, args.base)
        merge_base, issues = release_readiness_issues(repo_root, base_ref)
    except RuntimeError as error:
        print(f"Release check could not run: {error}")
        return 2

    if issues:
        print(
            f"Release check failed against {base_ref} "
            f"(merge base {merge_base[:12]}):"
        )
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print(
        f"Release check passed against {base_ref} "
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
    if len(sys.argv) > 1 and sys.argv[1] == "release-check":
        sys.exit(run_release_check_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "hosted-e2e":
        from runner.hosted_e2e import run_hosted_e2e_command

        sys.exit(run_hosted_e2e_command(sys.argv[2:]))

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "auth",
            "browser-review",
            "dev",
            "indexes",
            "deploy",
            "icons",
            "hosted-e2e",
            "mutation-contracts",
            "release-check",
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
