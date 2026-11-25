"""Parse and dispatch the hosted-e2e subcommands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runner import cloud_checkpoints

from . import runtime
from .candidate import create
from .evidence import (
    _evidence_exit_status,
    format_execute_summary,
    import_result_directory,
    results,
    validate_release_evidence,
)
from .execution import execute
from .lifecycle import status, teardown
from .provisioning import setup
from .runtime import (
    DEFAULT_BROWSER_WORKERS,
    HOSTED_E2E_ENVIRONMENTS,
    HostedE2EError,
    _environment,
)


def run_hosted_e2e_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="run.py hosted-e2e",
        description="Run repository tests in an isolated Google-hosted environment.",
    )
    commands = parser.add_subparsers(dest="action", required=True)
    parser.add_argument("--recover-generation", type=int, metavar="GENERATION",
                        help="Take over this GCS generation after the previous operator stopped.")
    init_parser = commands.add_parser("checkpoint-init", help="Seed private Cloud storage from a torn-down installation.")
    init_parser.add_argument("--from-checkout", type=Path, required=True)
    init_parser.add_argument("--project", required=True)

    def add_environment_argument(command_parser):
        command_parser.add_argument(
            "--environment",
            choices=HOSTED_E2E_ENVIRONMENTS,
            default="standard",
            help="Select the hosted E2E lifecycle.",
        )

    setup_parser = commands.add_parser(
        "setup", help="Provision stable hosted-E2E resources."
    )
    setup_parser.add_argument("--github-repository", metavar="OWNER/REPOSITORY")
    create_parser = commands.add_parser(
        "create",
        help="Deploy the committed production build as a matching app version and job.",
    )
    create_parser.add_argument(
        "--base",
        dest="base_ref",
        metavar="REF",
        help=(
            "Comparison base for release tree validation. "
            "Defaults to origin/main, then main."
        ),
    )
    add_environment_argument(create_parser)
    create_parser.add_argument("--workers", "--experiments-workers", dest="experiments_workers",
                               type=int, choices=range(1, 7), default=DEFAULT_BROWSER_WORKERS,
                               help="Browser workers (default 6): 1–3 use B2; 4–6 use B4 and a larger Cloud Run driver.")
    execute_parser = commands.add_parser("execute", help="Run the Cloud Run E2E job.")
    execute_parser.add_argument("--experiments", nargs="?", const="pilot", choices=("pilot", "all"), help="Run coordinated E2E: pilot or all.")
    add_environment_argument(execute_parser)
    execute_parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        help="Run one test nodeid from any suite; repeat for more. Omit to run all complete suites.",
    )
    execute_parser.add_argument(
        "--no-import-results",
        action="store_true",
        help="Leave this execution in Cloud Storage without importing it locally.",
    )
    results_parser = commands.add_parser(
        "results", help="Download and import job artifacts."
    )
    add_environment_argument(results_parser)
    result_selector = results_parser.add_mutually_exclusive_group()
    result_selector.add_argument("--execution")
    result_selector.add_argument("--latest", action="store_true")
    results_parser.add_argument("--download-only", action="store_true")
    results_parser.add_argument(
        "--skip-report-archive",
        action="store_true",
        help="Download manifest, evidence, and JUnit XML without reports.tar.gz.",
    )
    import_parser = commands.add_parser(
        "import-results",
        help="Merge an already-downloaded result bundle into local evidence.",
    )
    import_parser.add_argument("--directory", required=True, type=Path)
    import_parser.add_argument("--execution")
    validate_parser = commands.add_parser(
        "validate-release-evidence",
        help="Validate hosted evidence for a release candidate or continuation.",
    )
    validate_parser.add_argument("--candidate", required=True)
    validate_parser.add_argument("--evidence", required=True)
    validate_parser.add_argument("--base", required=True)
    status_parser = commands.add_parser(
        "status", help="Show local and provider lifecycle state."
    )
    add_environment_argument(status_parser)
    teardown_parser = commands.add_parser(
        "teardown", help="Delete the ephemeral version and job."
    )
    add_environment_argument(teardown_parser)
    teardown_parser.add_argument("--force", action="store_true")
    args = parser.parse_args(arguments)

    try:
        if args.action == "checkpoint-init":
            cloud_checkpoints.seed(args.from_checkout.resolve(), args.project)
            return 0
        return _dispatch_hosted_command(args)
    except HostedE2EError as error:
        print(f"Hosted E2E command stopped: {error}")
        return 2
    except RuntimeError as error:
        print(f"Hosted E2E command failed: {error}")
        return 1


def _dispatch_hosted_command(args: argparse.Namespace) -> int:
    with cloud_checkpoints.lifecycle(runtime, args):
        if args.action == "setup":
            payload = setup(args.github_repository)
            print(json.dumps(payload, indent=2, sort_keys=True))
            print(
                "Configure the GitHub environment variables documented in "
                "documentation/TESTING_HOSTED_E2E.md before dispatching CI."
            )
        elif args.action == "create":
            create_options = {"base_ref": args.base_ref}
            if args.experiments_workers != DEFAULT_BROWSER_WORKERS:
                create_options["experiments_workers"] = args.experiments_workers
            if args.environment != "standard":
                create_options["environment"] = args.environment
            payload = create(**create_options)
            print(f"Hosted E2E version ready: {payload['base_url']}")
        elif args.action == "execute":
            execute_options = {
                "targets": args.targets or (),
                "import_results": not args.no_import_results,
            }
            if args.experiments:
                execute_options["experiments"] = args.experiments
            if args.environment != "standard":
                execute_options["environment"] = args.environment
            payload = execute(
                **execute_options,
            )
            result_root = (
                _environment(args.environment).result_root if args.environment != "standard" else None
            )
            print(format_execute_summary(
                payload, imported=not args.no_import_results,
                environment=args.environment, result_root=result_root,
            ))
            return _evidence_exit_status(payload)
        elif args.action == "import-results":
            payload = import_result_directory(
                args.directory,
                expected_execution=args.execution,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        elif args.action == "results":
            result_options = {
                "execution": args.execution,
                "latest": args.latest,
                "merge": not args.download_only,
                "include_report_archive": not args.skip_report_archive,
            }
            if args.environment != "standard":
                result_options["environment"] = args.environment
            payload = results(
                **result_options,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return _evidence_exit_status(payload)
        elif args.action == "validate-release-evidence":
            payload = validate_release_evidence(
                args.candidate,
                args.evidence,
                base=args.base,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        elif args.action == "status":
            status_options = {}
            if args.environment != "standard":
                status_options["environment"] = args.environment
            print(json.dumps(status(**status_options), indent=2, sort_keys=True))
        elif args.action == "teardown":
            teardown_options = {"force": args.force}
            if args.environment != "standard":
                teardown_options["environment"] = args.environment
            payload = teardown(**teardown_options)
            print(f"Hosted E2E version {payload['version']} was torn down.")
    return 0
