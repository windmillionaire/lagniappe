"""Lagniappe setup command-line boundary."""

import argparse
import sys


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_routes_every_mode_and_returns_status
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_rejects_multiple_or_dashed_commands
# @features setup
# @dimensions cli-routing argument-validation
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
    return parser


# @testable false
# @covered-by installer/__main__.py::main
# @reason small argument-to-operation mapping owned by the tested CLI boundary
def _mode(args):
    return args.command or "install"


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_routes_every_mode_and_returns_status
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_treats_none_cancellation_as_failure
# @features setup
# @dimensions cli-status failure-propagation
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
# @features setup
# @dimensions prerequisites dependency-bootstrap focused-mode
def _prepare_setup_dependencies(args):
    """Bootstrap focused modes before importing their dependency-backed handlers."""
    if _mode(args) == "install":
        # The full installer owns this step so it can announce recovery and ask
        # for consent before changing the project environment.
        return

    from installer.package_install import ensure_pip_is_available, ensure_setup_dependencies

    ensure_pip_is_available()
    ensure_setup_dependencies()

    from runner.gcloud import activate_repository_gcloud

    activate_repository_gcloud(ensure_adc=_mode(args) != "doctor")


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_routes_every_mode_and_returns_status
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_provider_failures_are_nonzero
# @features setup
# @dimensions cli-routing lazy-imports failure-propagation
def _dispatch(args):
    command = args.command
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

    from installer.install import install

    return install()


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_python_runtime_gate_precedes_every_cli_mode
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_rejects_multiple_or_dashed_commands
# @features setup
# @dimensions cli-routing prerequisites operation-journal
def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    args = parser.parse_args(arguments)
    if getattr(args, "branch", None) is not None:
        args.branch = args.branch.strip()
        if not args.branch:
            parser.error("--branch requires a non-empty value")

    from installer import verify_setup_runtime

    verify_setup_runtime()
    _prepare_setup_dependencies(args)

    if args.command == "doctor":
        return _status(_dispatch(args))

    from installer.state import setup_operation

    with setup_operation(_mode(args), arguments):
        return _status(_dispatch(args))


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_provider_failures_are_nonzero
# @tests tests_tooling/test_001e_setup_orchestration.py::test_cli_subprocess_treats_none_cancellation_as_failure
# @features setup
# @dimensions cli-status failure-propagation unexpected-errors
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
