"""Opt-in five-case pilot using the same coordinator locally and in Cloud Run."""

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from uuid import uuid4

from runner.context import REPOSITORY_ROOT
from runner.e2e_parallel import Batch, merge_results, schedule


PILOT_FILE = "testing/tests_e2e/001_site/test_001h_parallel_pilot.py"
CASES = ("independent-a", "independent-b", "shared-a", "shared-b", "exclusive")
TARGETS = tuple(f"{PILOT_FILE}::test_worker_page_and_task[{case}]" for case in CASES)


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_pilot_arguments_are_bounded_and_keep_normal_runs_unchanged
# @matrix testing : parallel-e2e
def pilot_arguments(arguments):
    if "--experiments" not in arguments:
        return False, arguments
    rest = [arg for arg in arguments if arg != "--experiments"]
    if any(not arg.startswith("--junitxml=") for arg in rest):
        raise ValueError("test --experiments selects the fixed E2E pilot; only --junitxml= is additional")
    return True, [*rest, *TARGETS]


# @testable infrastructure
@contextmanager
def pilot_authority(local_authority):
    if local_authority is not None:
        yield local_authority
        return
    from lagniappe.core.tools.hosted_e2e.lease import E2ELease
    from runner.testing import cleanup_test_data, initialize_test_data, prepare_test_artifacts
    from testing.utility.e2e_runtime import validate_hosted_e2e_health

    validate_hosted_e2e_health()
    with E2ELease() as authority:
        try:
            cleanup_test_data(authority)
            initialize_test_data(authority)
            prepare_test_artifacts(authority)
            yield authority
        finally:
            authority.assert_active()
            cleanup_test_data(authority)


# @testable true
# @tests tests_e2e/001_site/test_001h_parallel_pilot.py::test_worker_page_and_task
# @matrix testing : parallel-e2e
def run_pilot(authority, command, pytest_args):
    from lagniappe import CONFIG
    from lagniappe.core.entities import Entities
    from runner.test_session import capture_process_identity, load_session_state
    from testing.utility.traceability_common import behavior_snapshot
    from testing.utility.traceability_results import _write_manifest

    authority.assert_active()
    Entities.initialize()
    attempt = uuid4().hex
    snapshot, _ = behavior_snapshot(REPOSITORY_ROOT)
    root = REPOSITORY_ROOT / "reports" / "e2e-pilot" / attempt
    root.mkdir(parents=True)
    shared = Entities.PAGE.create({"name": f"Pilot shared {attempt[:8]}"})
    shared.save()
    shared.remember_empty_notes()
    fixtures = {"shared_page": shared.urlsafe_key}
    owner = capture_process_identity(os.getpid())
    if owner is None:
        raise RuntimeError("Cannot identify E2E pilot coordinator")
    run_id = getattr(authority, "run_id", None) or authority.nonce
    local = load_session_state() if not CONFIG.hosted_e2e_runner else None
    batches = tuple(Batch(case, target, frozenset({"shared-page"}) if case.startswith("shared")
                          else frozenset(), exclusive=case == "exclusive")
                    for case, target in zip(CASES, TARGETS))
    destination = next((arg.split("=", 1)[1] for arg in pytest_args if arg.startswith("--junitxml=")),
                       str(root / "junit.xml"))
    statuses, events, scheduler_error = {}, [], None
    previous = {}

    def cancel(signum, frame):
        raise KeyboardInterrupt(f"E2E pilot cancelled by signal {signum}")

    with ExitStack() as stack:
        contexts = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="lagniappe-e2e-workers-")))

        def launch(batch):
            artifacts = root / batch.name
            artifacts.mkdir()
            record = {"attempt": attempt, "snapshot": snapshot, "batch": batch.name,
                      "nodeid": batch.nodeid, "run_id": run_id, "owner": owner,
                      "base_url": CONFIG.BASE_URL, "fixtures": fixtures,
                      "server_pid": local["server"]["pid"] if local else None,
                      "artifacts": str(artifacts)}
            path = contexts / f"{batch.name}.json"
            path.write_text(json.dumps(record))
            path.chmod(0o600)
            output = stack.enter_context((artifacts / "pytest.log").open("w"))
            child_command = [sys.executable, "-m", "pytest", "-c", "testing/pytest.ini",
                             "-p", "testing.utility.traceability_results", "-p", "runner.pytest_routing",
                             "-o", f"cache_dir={artifacts / 'pytest-cache'}",
                             f"--junitxml={artifacts / 'junit.xml'}", batch.nodeid]
            print(f"Pilot starting {batch.name}", flush=True)
            return subprocess.Popen(child_command, cwd=REPOSITORY_ROOT, start_new_session=True,
                                    stdout=output, stderr=subprocess.STDOUT,
                                    env={**os.environ, "LAGNIAPPE_E2E_WORKER_CONTEXT": str(path),
                                         "LAGNIAPPE_TEST_ARTIFACTS": str(artifacts)})

        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, cancel)
            schedule(batches, launch, authority.assert_active, finished=statuses, events=events)
        except (OSError, RuntimeError, KeyboardInterrupt) as error:
            scheduler_error = str(error)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    outcomes, errors = merge_results(batches, root, statuses, attempt=attempt,
                                     snapshot=snapshot, destination=destination)
    if scheduler_error:
        errors.append(scheduler_error)
    if behavior_snapshot(REPOSITORY_ROOT)[0] != snapshot:
        errors.append("Source changed during E2E pilot; results are not importable")
    status = int(bool(errors) or any(row["outcome"] != "passed" for row in outcomes.values()))
    summary = {"attempt": attempt, "source_snapshot": snapshot,
               "hosted": CONFIG.hosted_e2e_runner, "workers": 2,
               "selected": list(TARGETS), "events": events,
               "exit_status": status, "errors": errors}
    (root / "summary.json").write_text(json.dumps(summary, indent=2))
    if not any("Source changed" in error for error in errors):
        _write_manifest(REPOSITORY_ROOT, command, outcomes, status)
    print(f"Pilot: {sum(row['outcome'] == 'passed' for row in outcomes.values())}/{len(batches)} passed; {root}", flush=True)
    for error in errors:
        print(error, flush=True)
    return status
