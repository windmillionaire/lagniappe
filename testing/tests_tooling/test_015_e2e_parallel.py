"""Concurrency, cancellation and evidence contracts without a live app."""

import json
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

import pytest

from runner.e2e_parallel import Batch, await_worker_file, merge_results, schedule
from runner.e2e_pilot import TARGETS, pilot_arguments
from runner.e2e_inventory import discover_resources, story_batches


pytestmark = pytest.mark.tooling


# @matrix testing : parallel-e2e
def test_inventory_follows_helpers_constants_and_fixtures(tmp_path):
    helpers = tmp_path / "testing/utility"
    helpers.mkdir(parents=True)
    (helpers / "arrange.py").write_text('''
from testing.definitions.pages import Pages as P
SHARED = P.imported
def arrange_imported():
    return SHARED.get(None)
''', encoding="utf-8")
    source = tmp_path / "test_story.py"
    source.write_text('''
from testing.definitions import Pages as P, Categories, Users
from testing.utility.arrange import arrange_imported
SORTABLE = (P.alpha, P.beta)
def arrange(user):
    for page in SORTABLE:
        page.get(user)
def test_story(get_user):
    user = get_user(Users.ANONYMOUS)
    arrange(user)
    arrange_imported()
    user.go(Categories.table)
def fixture():
    return P.fixture.get(None)
''', encoding="utf-8")
    assert discover_resources(tmp_path, "test_story.py", "test_story", [("test_story.py", "fixture")]) == {
        "Pages.alpha", "Pages.beta", "Pages.fixture", "Pages.imported", "Categories.table",
    }


# @matrix testing : parallel-e2e
def test_inventory_groups_shared_resources_and_drains_serial_stories(tmp_path):
    folder = tmp_path / "testing/tests_e2e"
    folder.mkdir(parents=True)
    (folder / "test_story.py").write_text('''
from testing.definitions import Pages
def test_a(): Pages.shared.get(None)
def test_b(): Pages.shared.get(None)
def test_c(): Pages.other.get(None)
def test_d(): pass
''', encoding="utf-8")
    records = [{"nodeid": f"tests_e2e/test_story.py::test_{name}", "fixtures": [], "serial": name == "d"}
               for name in "abcd"]
    batches, inventory = story_batches(tmp_path, records, workers=2)
    assert len(batches) == 3
    assert batches[0].nodeids == ("testing/tests_e2e/test_story.py::test_a", "testing/tests_e2e/test_story.py::test_b")
    assert not (batches[0].resources & batches[1].resources)
    assert batches[-1].exclusive and batches[-1].nodeid.endswith("test_d")
    assert inventory[1]["resources"] == ["Pages.shared"]


# @matrix testing : parallel-e2e
def test_merge_preserves_each_parameter_and_reports_missing_batch_cases(tmp_path):
    targets = tuple(f"testing/tests_e2e/test_story.py::test_story[{i}]" for i in range(3))
    batch = Batch("stories", targets[0], additional_nodeids=targets[1:])
    folder = tmp_path / "stories"
    folder.mkdir()
    selected = [s.removeprefix("testing/") for s in targets]
    payload = {"attempt": "a", "snapshot": "s", "batch": "stories", "exit_status": 0,
               "selected": selected, "outcomes": {n: {"outcome": "passed", "duration": 1} for n in selected}}
    (folder / "outcomes.json").write_text(json.dumps(payload), encoding="utf-8")
    suite = ET.Element("testsuite")
    for target in selected:
        ET.SubElement(suite, "testcase", name=target.split("::")[-1], classname="tests_e2e.test_story")
    ET.ElementTree(suite).write(folder / "junit.xml")
    result, errors = merge_results([batch], tmp_path, {"stories": 0}, attempt="a", snapshot="s", destination=tmp_path / "combined.xml")
    assert not errors and set(result) == set(selected)
    payload["outcomes"].pop(selected[-1])
    (folder / "outcomes.json").write_text(json.dumps(payload), encoding="utf-8")
    result, errors = merge_results([batch], tmp_path, {"stories": 0}, attempt="a", snapshot="s", destination=tmp_path / "combined.xml")
    assert errors and len(result) == 3 and all(row["outcome"] == "failed" for row in result.values())


# @matrix testing : parallel-e2e
@pytest.mark.parametrize("variant", ["valid", "wrong-module", "swapped-outcomes"])
def test_merge_checks_each_case_identity_and_outcome(tmp_path, variant):
    targets = tuple(f"testing/tests_e2e/test_{name}.py::test_story" for name in ("a", "b"))
    batch = Batch("stories", targets[0], additional_nodeids=targets[1:])
    folder = tmp_path / "stories"
    folder.mkdir()
    selected = [target.removeprefix("testing/") for target in targets]
    rows = {selected[0]: {"outcome": "failed", "duration": 1},
            selected[1]: {"outcome": "skipped", "duration": 0}}
    payload = {"attempt": "a", "snapshot": "s", "batch": "stories", "exit_status": 1,
               "selected": selected, "outcomes": rows}
    (folder / "outcomes.json").write_text(json.dumps(payload), encoding="utf-8")
    suite = ET.Element("testsuite")
    for name, outcome in (("a", "failure"), ("b", "skipped")):
        classname = f"tests_e2e.test_{name}" if variant != "wrong-module" else "tests_e2e.wrong"
        case = ET.SubElement(suite, "testcase", name="test_story", classname=classname)
        if variant == "swapped-outcomes":
            outcome = "skipped" if outcome == "failure" else "failure"
        ET.SubElement(case, outcome)
    ET.ElementTree(suite).write(folder / "junit.xml")
    outcomes, errors = merge_results([batch], tmp_path, {"stories": 1}, attempt="a", snapshot="s",
                                     destination=tmp_path / "combined.xml")
    if variant == "valid":
        assert not errors and outcomes == rows
    else:
        assert errors and all(row["failed_phase"] == "worker" for row in outcomes.values())


# @matrix testing : parallel-e2e
@pytest.mark.parametrize("name", ["ready.json", "outcomes.json"])
def test_worker_messages_allow_publication_during_completion(tmp_path, monkeypatch, name):
    path = tmp_path / name
    path.write_text('{"ready": true}')
    (tmp_path / "outcomes.json").write_text('{"ready": true}')
    is_file = Path.is_file
    first_read = True

    def before_publication(candidate):
        nonlocal first_read
        if candidate == path and first_read:
            first_read = False
            return False
        return is_file(candidate)

    monkeypatch.setattr(Path, "is_file", before_publication)
    assert await_worker_file(path) == {"ready": True}


# @matrix testing : parallel-e2e
def test_worker_messages_reject_missing_completed_messages(tmp_path):
    (tmp_path / "outcomes.json").write_text('{}')
    with pytest.raises(AssertionError, match="finished without ready.json"):
        await_worker_file(tmp_path / "ready.json")


# @matrix testing : parallel-e2e
def test_pilot_arguments_are_bounded_and_keep_normal_runs_unchanged():
    assert pilot_arguments(["unit"]) == (False, ["unit"])
    enabled, arguments = pilot_arguments(["--experiments", "--junitxml=result.xml"])
    assert enabled and arguments == ["--junitxml=result.xml", *TARGETS]
    assert pilot_arguments(["--experiments=all"]) == ("all", ["e2e"])
    for arguments in (["--experiments=unknown"], ["--experiments", "--experiments=all"]):
        with pytest.raises(ValueError):
            pilot_arguments(arguments)
    with pytest.raises(ValueError):
        pilot_arguments(["--experiments", "e2e"])


# @matrix testing : parallel-e2e
def test_scheduler_overlaps_independent_work_and_serializes_conflicts(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text('''
from pathlib import Path
import sys, time
root, name = Path(sys.argv[1]), sys.argv[2]
(root / name).touch()
peer = {"a": "b", "b": "c"}.get(name)
deadline = time.monotonic() + 5
while peer and not (root / peer).exists():
    assert time.monotonic() < deadline
    time.sleep(.01)
''')
    batches = [Batch("a", "a", frozenset({"page"})), Batch("b", "b"),
               Batch("c", "c", frozenset({"page"})), Batch("d", "d", frozenset({"page"})),
               Batch("e", "e", exclusive=True), Batch("f", "f")]

    def launch(batch):
        return subprocess.Popen([sys.executable, str(script), str(tmp_path), batch.name], start_new_session=True)

    statuses, events = schedule(batches, launch, lambda: None, timeout=10)
    assert statuses == dict.fromkeys("abcdef", 0)
    index = {(event["batch"], event["event"]): i for i, event in enumerate(events)}
    assert index["b", "start"] < index["a", "finish"] < index["b", "finish"]
    assert index["a", "finish"] < index["c", "start"] < index["c", "finish"] < index["d", "start"]
    assert max(index[name, "finish"] for name in "abcd") < index["e", "start"]
    assert index["e", "finish"] < index["f", "start"]


# @matrix testing : parallel-e2e
@pytest.mark.parametrize("failure", [RuntimeError("lease lost"), KeyboardInterrupt("cancelled")])
def test_scheduler_stops_children_before_returning_on_lost_authority(failure, tmp_path):
    processes = []
    child_code = ("import os, signal, time; from pathlib import Path; "
                  "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                  "Path(__import__('sys').argv[1]).write_text(str(os.getpid())); time.sleep(60)")

    def launch(batch):
        code = ("import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child_code!r}, {str(tmp_path / batch.name)!r}]); "
                "time.sleep(60)")
        process = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
        processes.append(process)
        return process

    def active():
        if len(processes) == 2:
            deadline = time.monotonic() + 5
            while not all((tmp_path / name).exists() for name in ("a", "b")):
                assert time.monotonic() < deadline
                time.sleep(.01)
            raise failure

    with pytest.raises(type(failure)):
        schedule([Batch("a", "a"), Batch("b", "b"), Batch("c", "c")], launch, active)
    assert len(processes) == 2
    assert all(process.poll() is not None for process in processes)
    for name in ("a", "b"):
        status_file = Path(f"/proc/{int((tmp_path / name).read_text())}/stat")
        deadline = time.monotonic() + 2
        while status_file.exists() and status_file.read_text().split()[2] != "Z":
            assert time.monotonic() < deadline, "cancelled worker's descendant survived"
            time.sleep(.01)


# @matrix testing : parallel-e2e
def test_scheduler_reaps_a_crashed_workers_remaining_children(tmp_path):
    pid_file = tmp_path / "child.pid"
    code = ("import subprocess, sys, os; from pathlib import Path; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"Path({str(pid_file)!r}).write_text(str(p.pid)); os._exit(7)")
    def launch(_batch):
        return subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    statuses, _ = schedule([Batch("crashed", "crashed")], launch, lambda: None)
    assert statuses == {"crashed": 7}
    status_file = Path(f"/proc/{int(pid_file.read_text())}/stat")
    deadline = time.monotonic() + 2
    while status_file.exists() and status_file.read_text().split()[2] != "Z":
        assert time.monotonic() < deadline, "worker's descendant survived"
        time.sleep(.01)


# @matrix testing : parallel-e2e
@pytest.mark.parametrize("variant", ["pass", "setup", "teardown", "missing", "corrupt", "duplicate",
                                      "wrong-source", "wrong-selection", "crash", "missing-junit"])
def test_merge_preserves_failures_and_rejects_missing_corrupt_or_duplicate_evidence(tmp_path, variant):
    batches = [Batch("a", "testing/tests_e2e/test_example.py::test_a"),
               Batch("b", "testing/tests_e2e/test_example.py::test_b")]
    statuses = {"a": 0, "b": 0}
    for batch in batches:
        folder = tmp_path / batch.name
        folder.mkdir()
        nodeid = batch.nodeid.removeprefix("testing/")
        row = {"outcome": "passed", "duration": 1.0}
        if batch.name == "b" and variant in {"setup", "teardown"}:
            row.update(outcome="failed", failed_phase=variant, traceback="Original failure")
            statuses["b"] = 1
        payload = {"attempt": "attempt", "snapshot": "source", "batch": batch.name,
                   "exit_status": statuses[batch.name], "selected": [nodeid], "outcomes": {nodeid: row}}
        (folder / "outcomes.json").write_text(json.dumps(payload))
        suite = ET.Element("testsuite")
        case = ET.SubElement(suite, "testcase", name=nodeid.split("::")[-1], classname="tests_e2e.test_example")
        if row["outcome"] == "failed":
            ET.SubElement(case, "error", message="Original failure")
        ET.ElementTree(suite).write(folder / "junit.xml")
    path = tmp_path / "b" / "outcomes.json"
    if variant in {"missing", "crash"}:
        path.unlink()
        statuses["b"] = -9 if variant == "crash" else 0
    elif variant == "corrupt":
        path.write_text("{")
    elif variant == "missing-junit":
        (tmp_path / "b" / "junit.xml").unlink()
    elif variant == "duplicate":
        batches.append(batches[0])
    elif variant in {"wrong-source", "wrong-selection"}:
        payload = json.loads(path.read_text())
        payload["snapshot" if variant == "wrong-source" else "selected"] = "different"
        path.write_text(json.dumps(payload))
    destination = tmp_path / "combined.xml"
    outcomes, errors = merge_results(batches, tmp_path, statuses, attempt="attempt", snapshot="source", destination=destination)
    assert set(outcomes) == {batch.nodeid.removeprefix("testing/") for batch in batches}
    if variant != "duplicate":
        assert outcomes["tests_e2e/test_example.py::test_a"]["outcome"] == "passed"
    if variant in {"setup", "teardown"}:
        assert not errors
        assert outcomes["tests_e2e/test_example.py::test_b"]["failed_phase"] == variant
        assert outcomes["tests_e2e/test_example.py::test_b"]["traceback"] == "Original failure"
    elif variant == "pass":
        assert not errors and all(row["outcome"] == "passed" for row in outcomes.values())
    else:
        assert errors and any(row["outcome"] == "failed" for row in outcomes.values())
    assert len(list(ET.parse(destination).iter("testcase"))) == len(batches)
