"""Lagniappe setup command-line boundary."""

import argparse
import sys


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_routes_every_mode_and_returns_status
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_rejects_multiple_or_dashed_commands
# @matrix setup : argument-validation cli-routing
def _parser():
    parser = argparse.ArgumentParser(description="Lagniappe Setup Tool")
    commands = parser.add_subparsers(
        dest="command",
        metavar="COMMAND",
        help="Setup operation; omit for a full installation",
    )
    commands.add_parser(
        "doctor",
        help="Inspect an existing installation without repairing it",
    )
    commands.add_parser(
        "repair",
        help="Reconcile and validate an existing installation",
    )
    commands.add_parser(
        "auth",
        help="Refresh Google Cloud CLI and Application Default Credentials",
    )
    commands.add_parser(
        "url",
        help="Configure a custom domain",
    )
    commands.add_parser(
        "email",
        help="Configure custom-domain authentication email",
    )
    commands.add_parser(
        "oauth",
        help="Replace and verify Google Sign-In OAuth settings",
    )
    commands.add_parser("ai", help="Configure AI")
    commands.add_parser(
        "ai-email",
        help="Configure, deploy, and activate Resend AI email submissions",
    )
    commands.add_parser(
        "security",
        help="Configure Redis transport security",
    )
    commands.add_parser(
        "jobs",
        help="Configure deferred-job recovery after deploying the app",
    )
    commands.add_parser(
        "update",
        help="Update with new settings",
    )
    upgrade = commands.add_parser(
        "upgrade",
        help="Replace source from a remote branch, update settings, and deploy",
    )
    upgrade.add_argument(
        "--branch",
        help="Reset to origin/BRANCH instead of origin/main",
    )
    commands.add_parser(
        "development",
        help="Add development tooling to an existing installation",
    )
    commands.add_parser(
        "handoff",
        help="Transfer delegated installer access to the permanent Owner",
    )
    backup = commands.add_parser(
        "backup",
        help="Create, prepare, list, or explicitly delete manual backups",
    )
    backup_commands = backup.add_subparsers(dest="backup_action", required=True)
    backup_commands.add_parser("create", help="Create or resume a manual backup")
    backup_commands.add_parser("list", help="List completed manual backups")
    backup_prepare = backup_commands.add_parser(
        "prepare", help="Prepare one automatic Google backup as a manual backup"
    )
    backup_prepare.add_argument("backup_id", metavar="BACKUP_ID")
    backup_delete = backup_commands.add_parser("delete", help="Delete one manual backup")
    backup_delete.add_argument("backup_id", metavar="BACKUP_ID")

    archive = commands.add_parser(
        "archive",
        help="Build a portable archive, or validate one without Google access",
    )
    archive.add_argument("archive_target", nargs="?", metavar="BACKUP_ID|validate")
    archive.add_argument("validation_path", nargs="?", metavar="ARCHIVE_PATH")
    archive.add_argument("--output", metavar="PATH")
    archive.add_argument("--zip", action="store_true", dest="zip_output")

    restore = commands.add_parser(
        "restore",
        help="Preflight or run a maintenance-gated merge into (default)",
    )
    restore.add_argument("backup_id", metavar="BACKUP_ID")
    restore.add_argument("--dry-run", action="store_true")
    return parser


# @testable false
# @covered-by installer/__main__.py::main
# @reason small argument-to-operation mapping owned by the tested CLI boundary
def _mode(args):
    return args.command or "install"


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_lifecycle_cli_routes_nested_commands_and_read_only_boundaries
# @matrix data-lifecycle : cli-routing read-only
def _local_only(args):
    return args.command == "archive" and args.archive_target == "validate"


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_lifecycle_cli_routes_nested_commands_and_read_only_boundaries
# @matrix data-lifecycle : cli-routing read-only
def _read_only(args):
    return (
        _local_only(args)
        or (args.command == "backup" and args.backup_action == "list")
        or (args.command == "restore" and args.dry_run)
    )


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_routes_every_mode_and_returns_status
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_treats_none_cancellation_as_failure
# @matrix setup : cli-status failure-propagation
def _status(result):
    """Normalize every setup entry point to an honest process status."""
    if result is True:
        return 0
    if result is False or result is None:
        return 1
    if isinstance(result, int):
        return result
    from installer.errors import SetupError

    raise SetupError(
        f"Setup command returned an unsupported result: {type(result).__name__}."
    )


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_python_runtime_gate_precedes_every_cli_mode
# @tests tests_tooling/test_001e_setup_orchestration.py::test_stale_gcloud_token_stops_with_setup_auth_instruction
# @matrix setup : dependency-bootstrap focused-mode gcloud-token prerequisites safe-failure
def _prepare_setup_dependencies(args):
    """Bootstrap focused modes before importing their dependency-backed handlers."""
    if _mode(args) == "install":
        # The full installer owns this step so it can announce recovery and ask
        # for consent before changing the project environment.
        return

    if _read_only(args):
        if _local_only(args):
            return
        from runner.gcloud import activate_repository_gcloud

        try:
            activate_repository_gcloud(
                ensure_adc=True,
                ensure_cli_token=True,
            )
        except RuntimeError as error:
            from installer.errors import SetupError

            raise SetupError(str(error)) from error
        return

    from installer.package_install import ensure_pip_is_available, ensure_setup_dependencies

    ensure_pip_is_available()
    ensure_setup_dependencies()

    if _mode(args) == "auth":
        return

    mutating = _mode(args) != "doctor"
    try:
        if _mode(args) == "handoff":
            from installer.handoff import prepare_handoff_operator

            prepare_handoff_operator()
        else:
            from runner.gcloud import activate_repository_gcloud

            activate_repository_gcloud(
                ensure_adc=mutating,
                ensure_cli_token=mutating,
            )
    except RuntimeError as error:
        from installer.errors import SetupError

        raise SetupError(str(error)) from error


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_routes_every_mode_and_returns_status
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_provider_failures_are_nonzero
# @matrix setup : cli-routing failure-propagation lazy-imports
def _dispatch(args):
    command = args.command
    if command == "auth":
        from installer.auth import authenticate

        return authenticate()
    if command == "doctor":
        from installer.doctor import run_doctor

        return run_doctor()
    if command == "repair":
        from installer.verify import repair_installation

        return repair_installation()
    if command == "url":
        from installer.custom_domain import add_custom_domain

        return add_custom_domain()
    if command == "email":
        from installer.auth_email import configure_auth_email

        return configure_auth_email()
    if command == "oauth":
        from installer.admin import configure_oauth

        return configure_oauth()
    if command == "ai":
        from installer.ai import configure_ai

        return configure_ai()
    if command == "ai-email":
        from installer.ai_email import configure_ai_email

        return configure_ai_email()
    if command == "security":
        from installer.security import configure_security

        return configure_security()
    if command == "jobs":
        from installer.verify import prepare_existing_installation

        prepare_existing_installation()
        from installer.gcloud import create_deferred_job_reconciler

        return create_deferred_job_reconciler()
    if command == "update":
        from installer.upgrade import update

        return update()
    if command == "upgrade":
        from installer.upgrade import upgrade

        return upgrade(branch=args.branch)
    if command == "development":
        from installer.development import setup_development

        return setup_development()
    if command == "handoff":
        from installer.handoff import handoff

        return handoff()
    if command == "backup":
        from installer.data_lifecycle import backup as lifecycle_backup

        if args.backup_action == "list":
            from installer.verify import validate_installation

            validate_installation()
            lifecycle_backup.list_backups()
            return 0
        from installer.verify import prepare_existing_installation

        prepare_existing_installation()
        if args.backup_action == "create":
            lifecycle_backup.create_backup()
        elif args.backup_action == "prepare":
            lifecycle_backup.prepare_automatic_backup(args.backup_id)
        else:
            lifecycle_backup.delete_backup(args.backup_id)
        return 0
    if command == "archive":
        if args.archive_target == "validate":
            from installer.data_lifecycle.validation import validate_archive

            result = validate_archive(args.validation_path)
            print(
                f"Archive {result['archive_id']} is valid "
                f"({result['entities']} entities, {result['files']} files)."
            )
            return 0
        from installer.verify import prepare_existing_installation

        prepare_existing_installation()
        from installer.data_lifecycle.archive import build_archive

        build_archive(
            args.archive_target,
            output=args.output,
            zip_output=args.zip_output,
        )
        return 0
    if command == "restore":
        from installer.data_lifecycle.restore import restore_backup
        if args.dry_run:
            from installer.verify import validate_installation

            validate_installation()
        else:
            from installer.verify import prepare_existing_installation

            prepare_existing_installation()
        restore_backup(args.backup_id, dry_run=args.dry_run)
        return 0

    from installer.install import install

    return install()


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_python_runtime_gate_precedes_every_cli_mode
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_rejects_multiple_or_dashed_commands
# @matrix setup : cli-routing operation-journal prerequisites
def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    args = parser.parse_args(arguments)
    if args.command == "archive":
        if args.archive_target == "validate":
            if not args.validation_path:
                parser.error("archive validate requires ARCHIVE_PATH")
            if args.output or args.zip_output:
                parser.error("archive validate does not accept --output or --zip")
        elif args.validation_path:
            parser.error("archive accepts at most one BACKUP_ID")
    if getattr(args, "branch", None) is not None:
        args.branch = args.branch.strip()
        if not args.branch:
            parser.error("--branch requires a non-empty value")

    from installer import verify_setup_runtime

    verify_setup_runtime()
    _prepare_setup_dependencies(args)

    if args.command == "doctor" or _read_only(args):
        return _status(_dispatch(args))

    from installer.state import setup_operation

    with setup_operation(_mode(args), arguments):
        return _status(_dispatch(args))


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_provider_failures_are_nonzero
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_treats_none_cancellation_as_failure
# @matrix setup : cli-status failure-propagation unexpected-errors
def cli(argv=None):
    from installer.errors import SetupError

    try:
        return main(argv)
    except SetupError as error:
        print(f"Setup failed [{error.category}]: {error}")
        if error.repair_action:
            print(f"Repair action: {error.repair_action}")
        return error.exit_code
    except Exception as error:
        print(f"Setup failed [unexpected]: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
