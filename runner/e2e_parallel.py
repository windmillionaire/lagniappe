"""Bounded E2E batches under one owner, with private results and conflict lanes."""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Batch:
    name: str
    nodeid: str
    resources: frozenset[str] = frozenset()
    exclusive: bool = False
    additional_nodeids: tuple[str, ...] = ()

    @property
    def nodeids(self):
        return (self.nodeid, *self.additional_nodeids)


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_worker_messages_allow_publication_during_completion
# @tests tests_tooling/test_015_e2e_parallel.py::test_worker_messages_reject_missing_completed_messages
# @matrix testing : parallel-e2e
def await_worker_file(path):
    """Wait for an atomic harness message, never for browser/app state."""
    deadline = time.monotonic() + 90
    while not path.is_file():
        outcome = path.parent / "outcomes.json"
        if outcome.is_file() and not path.is_file():
            raise AssertionError(f"Peer worker finished without {path.name}")
        if time.monotonic() >= deadline:
            raise AssertionError(f"Peer worker did not publish {path.name}")
        time.sleep(0.05)
    return json.loads(path.read_text(encoding="utf-8"))


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_scheduler_overlaps_independent_work_and_serializes_conflicts
# @tests tests_tooling/test_015_e2e_parallel.py::test_scheduler_stops_children_before_returning_on_lost_authority
# @tests tests_tooling/test_015_e2e_parallel.py::test_scheduler_reaps_a_crashed_workers_remaining_children
# @matrix testing : parallel-e2e
def schedule(batches, launch, assert_active, *, workers=2, timeout=180, finished=None, events=None):
    """Run nonconflicting batches; an exclusive entry is a draining barrier."""
    pending = list(batches)
    running = {}
    finished = {} if finished is None else finished
    events = [] if events is None else events
    started = time.monotonic()
    next_check = started
    try:
        while pending or running:
            now = time.monotonic()
            if now >= next_check:
                assert_active()
                next_check = now + 1
            for name, (batch, process, began) in list(running.items()):
                status = process.poll()
                if status is not None:
                    # A crashed pytest can leave a browser in its process group.
                    # Even successful workers must not leave live descendants.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    finished[name] = status
                    events.append({"batch": name, "event": "finish", "at": now - started,
                                   "status": status})
                    del running[name]
                elif now - began > timeout:
                    raise RuntimeError(f"E2E worker {name} exceeded {timeout}s")
            held = set().union(*(batch.resources for batch, _, _ in running.values()))
            for batch in list(pending):
                if len(running) >= workers or any(b.exclusive for b, _, _ in running.values()):
                    break
                if batch.exclusive:
                    if running:
                        break
                elif batch.resources & held:
                    continue
                assert_active()
                process = launch(batch)
                running[batch.name] = (batch, process, time.monotonic())
                pending.remove(batch)
                held.update(batch.resources)
                events.append({"batch": batch.name, "event": "start",
                               "at": time.monotonic() - started})
                if batch.exclusive:
                    break
            if running:
                time.sleep(0.05)
        return finished, events
    finally:
        # Each child leads its own process group, including its browser children.
        # Reap every remaining worker before the caller can clean shared data.
        for _, process, _ in running.values():
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for _, process, _ in running.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            finally:
                # A parent can exit on TERM while a descendant ignores it.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_merge_preserves_failures_and_rejects_missing_corrupt_or_duplicate_evidence
# @tests tests_tooling/test_015_e2e_parallel.py::test_merge_preserves_each_parameter_and_reports_missing_batch_cases
# @tests tests_tooling/test_015_e2e_parallel.py::test_merge_checks_each_case_identity_and_outcome
# @matrix testing : parallel-e2e
def merge_results(batches, directory, statuses, *, attempt, snapshot, destination):
    """Account for every selected nodeid without consulting earlier evidence."""
    outcomes = {}
    errors = []
    combined = ET.Element("testsuites")
    for batch in batches:
        expected = [nodeid.removeprefix("testing/") for nodeid in batch.nodeids]
        try:
            if len(set(expected)) != len(expected) or set(expected) & outcomes.keys():
                raise ValueError("duplicate selected nodeid")
            path = Path(directory) / batch.name
            payload = json.loads((path / "outcomes.json").read_text(encoding="utf-8"))
            status = statuses[batch.name]
            if (payload["attempt"] != attempt or payload["snapshot"] != snapshot
                    or payload["batch"] != batch.name or payload["exit_status"] != status
                    or payload["selected"] != expected
                    or set(payload["outcomes"]) != set(expected)):
                raise ValueError("worker identity, selection or status mismatch")
            rows = payload["outcomes"]
            for row in rows.values():
                if not isinstance(row, dict) or row.get("outcome") not in {"passed", "failed", "skipped"}:
                    raise ValueError("missing terminal outcome")
                duration = row.get("duration")
                if type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0:
                    raise ValueError("invalid worker duration")
            failed = any(row["outcome"] == "failed" for row in rows.values())
            if (status == 0) == failed:
                raise ValueError("worker status disagrees with outcome")
            root = ET.parse(path / "junit.xml").getroot()
            if root.tag not in {"testsuites", "testsuite"}:
                raise ValueError("invalid JUnit root")
            cases = list(root.iter("testcase"))
            identities = {}
            for nodeid in expected:
                path, *names = nodeid.split("::")
                classname = ".".join([path.removesuffix(".py").replace("/", "."), *names[:-1]])
                identities[(classname, names[-1])] = nodeid
            if not cases or {(case.get("classname"), case.get("name")) for case in cases} != set(identities):
                raise ValueError("JUnit selection mismatch")
            # Pytest can emit separate call/teardown failures for one case.
            xml_outcomes = {nodeid: "passed" for nodeid in expected}
            for case in cases:
                nodeid = identities[(case.get("classname"), case.get("name"))]
                if case.find("failure") is not None or case.find("error") is not None:
                    xml_outcomes[nodeid] = "failed"
                elif case.find("skipped") is not None and xml_outcomes[nodeid] != "failed":
                    xml_outcomes[nodeid] = "skipped"
            if any(xml_outcomes[nodeid] != rows[nodeid]["outcome"] for nodeid in expected):
                raise ValueError("JUnit outcome mismatch")
            combined.extend(list(root) if root.tag == "testsuites" else [root])
            outcomes.update(rows)
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
            message = f"{batch.name}: incomplete worker evidence ({error})"
            errors.append(message)
            suite = ET.SubElement(combined, "testsuite", name=batch.name,
                                  tests=str(len(expected)), errors=str(len(expected)))
            for nodeid in expected:
                outcomes[nodeid] = {"outcome": "failed", "duration": 0,
                                    "failed_phase": "worker", "traceback": message}
                path, *names = nodeid.split("::")
                case = ET.SubElement(suite, "testcase", name=names[-1],
                                     classname=".".join([path.removesuffix(".py").replace("/", "."), *names[:-1]]))
                ET.SubElement(case, "error", message=message)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".xml.tmp")
    ET.ElementTree(combined).write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(destination)
    return outcomes, errors
