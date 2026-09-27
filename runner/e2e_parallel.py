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
# @matrix testing : parallel-e2e
def merge_results(batches, directory, statuses, *, attempt, snapshot, destination):
    """Account for every selected nodeid without consulting earlier evidence."""
    outcomes = {}
    errors = []
    combined = ET.Element("testsuites")
    for batch in batches:
        nodeid = batch.nodeid.removeprefix("testing/")
        try:
            if nodeid in outcomes:
                raise ValueError("duplicate selected nodeid")
            path = Path(directory) / batch.name
            payload = json.loads((path / "outcomes.json").read_text())
            status = statuses[batch.name]
            if (payload["attempt"] != attempt or payload["snapshot"] != snapshot
                    or payload["batch"] != batch.name or payload["exit_status"] != status
                    or payload["selected"] != [nodeid]
                    or set(payload["outcomes"]) != {nodeid}):
                raise ValueError("worker identity, selection or status mismatch")
            row = payload["outcomes"][nodeid]
            if not isinstance(row, dict) or row.get("outcome") not in {"passed", "failed", "skipped"}:
                raise ValueError("missing terminal outcome")
            duration = row.get("duration")
            if type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0:
                raise ValueError("invalid worker duration")
            if (status == 0) != (row["outcome"] != "failed"):
                raise ValueError("worker status disagrees with outcome")
            root = ET.parse(path / "junit.xml").getroot()
            if root.tag not in {"testsuites", "testsuite"}:
                raise ValueError("invalid JUnit root")
            cases = list(root.iter("testcase"))
            if not cases or any(case.get("name") != nodeid.split("::")[-1] for case in cases):
                raise ValueError("JUnit selection mismatch")
            xml_failed = any(list(case.iter("failure")) or list(case.iter("error")) for case in cases)
            if xml_failed != (row["outcome"] == "failed"):
                raise ValueError("JUnit outcome mismatch")
            combined.extend(list(root) if root.tag == "testsuites" else [root])
            outcomes[nodeid] = row
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
            message = f"{batch.name}: incomplete worker evidence ({error})"
            errors.append(message)
            outcomes[nodeid] = {"outcome": "failed", "duration": 0,
                                "failed_phase": "worker", "traceback": message}
            suite = ET.SubElement(combined, "testsuite", name=batch.name, tests="1", errors="1")
            case = ET.SubElement(suite, "testcase", name=nodeid.split("::")[-1])
            ET.SubElement(case, "error", message=message)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".xml.tmp")
    ET.ElementTree(combined).write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(destination)
    return outcomes, errors
