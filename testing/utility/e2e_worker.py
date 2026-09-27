"""Internal worker protocol. Workers never acquire, renew or release the lease."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import threading

from runner.test_session import inspect_process_identity


def context():
    return json.loads(Path(os.environ["LAGNIAPPE_E2E_WORKER_CONTEXT"]).read_text(encoding="utf-8"))


def assert_owner(record):
    from lagniappe.core.tools.hosted_e2e.lease import e2e_lease_active

    if inspect_process_identity(record["owner"]) != "match" or not e2e_lease_active(record["run_id"]):
        raise RuntimeError("E2E worker coordinator or lease is no longer active")


@contextmanager
def worker_runtime():
    from lagniappe import CONFIG
    from lagniappe.core.entities import Entities
    from testing.utility.e2e_runtime import (
        E2ERuntime, hosted_e2e_browser_cookie, validate_hosted_e2e_health,
    )

    record = context()
    if not CONFIG.testing or CONFIG.PREFIX != "test-" or CONFIG.BASE_URL != record["base_url"]:
        raise RuntimeError("E2E worker environment does not match its coordinator")
    assert_owner(record)
    stopped = threading.Event()

    def monitor():
        while not stopped.wait(1):
            try:
                assert_owner(record)
            except Exception:
                # Kill the worker's own group, including browsers. An orphan must
                # not keep renewing the outer lease or continue the next test.
                os.killpg(os.getpid(), signal.SIGTERM)
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        cookies = ()
        if CONFIG.hosted_e2e_runner:
            validate_hosted_e2e_health()
            cookies = (hosted_e2e_browser_cookie(record["run_id"]),)
        else:
            from runner.testing import wait_for_session_server
            if not wait_for_session_server(record["base_url"], record["run_id"],
                                           expected_pid=record["server_pid"],
                                           expected_mode="local-e2e", timeout_seconds=2):
                raise RuntimeError("E2E worker inherited a different local server")
        Entities.initialize()
        yield E2ERuntime(run_id=record["run_id"], browser_cookies=cookies)
        assert_owner(record)
    finally:
        stopped.set()
        watcher.join(timeout=2)


def write_results(session, outcomes, exitstatus):
    record = context()
    selected = [item.nodeid for item in session.items]
    path = Path(record["artifacts"]) / "outcomes.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "attempt": record["attempt"], "snapshot": record["snapshot"],
        "batch": record["batch"], "exit_status": int(exitstatus),
        "selected": selected, "outcomes": outcomes,
    }), encoding="utf-8")
    temporary.replace(path)
