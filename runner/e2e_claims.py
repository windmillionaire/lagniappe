"""Per-test resource reservations for workers sharing one coordinator host."""

from contextlib import contextmanager, ExitStack
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import time

import pytest


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_case_claims_overlap_independent_work_and_release_after_failure
# @tests tests_tooling/test_015_e2e_parallel.py::test_case_claims_stop_waiting_on_timeout_or_lost_authority
# @matrix testing : parallel-e2e
@contextmanager
def reserve_resources(directory, resources, assert_active, *, timeout=600):
    """Acquire all direct claims together; release on teardown, error or exit."""
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    assert_active()
    started = time.monotonic()
    next_check = started + 1
    while True:
        now = time.monotonic()
        if now >= next_check:
            assert_active()
            next_check = now + 1
        with ExitStack() as locks:
            try:
                for resource in sorted(set(resources)):
                    path = directory / sha256(resource.encode()).hexdigest()
                    handle = locks.enter_context(path.open("a", encoding="utf-8"))
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # Release the partial set before waiting; no hold-and-wait cycle.
                pass
            else:
                yield time.monotonic() - started
                return
        if time.monotonic() - started >= timeout:
            raise RuntimeError(f"Timed out waiting for E2E resources: {sorted(resources)}")
        time.sleep(0.05)


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_case_claim_hook_covers_fixture_teardown_and_continues_after_failure
# @matrix testing : parallel-e2e
@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    """Hold claims across all setup/call/teardown, including failed fixtures."""
    if not os.environ.get("LAGNIAPPE_E2E_WORKER_CONTEXT"):
        yield
        return
    from testing.utility.e2e_worker import assert_owner, context

    record = context()
    claims = record.get("test_resources")
    if claims is None:  # The small protocol batches retain process-level claims.
        yield
        return
    resources = claims[item.nodeid.removeprefix("testing/")]
    log = Path(record["artifacts"]) / "resource-events.jsonl"

    def event(state, **details):
        with log.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"nodeid": item.nodeid, "resources": resources,
                                     "event": state, "at": time.monotonic(), **details}) + "\n")

    event("waiting")
    with reserve_resources(Path(record["resource_registry"]) / "claims", resources,
                           lambda: assert_owner(record)) as waited:
        event("acquired", wait_seconds=waited)
        try:
            yield
        finally:
            event("released")
