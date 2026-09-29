"""Concurrency, cancellation and evidence contracts without a live app."""

import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from runner.e2e_parallel import Batch, await_worker_file, merge_results, schedule
from runner.e2e_pilot import TARGETS, pilot_arguments
from runner.e2e_inventory import discover_resources, duration_estimates, pytest_collection_finish, story_batches
from runner.e2e_claims import reserve_resources


pytestmark = pytest.mark.tooling


# @matrix testing : parallel-e2e
def test_collection_preserves_group_and_serial_markers(tmp_path, monkeypatch):
    destination = tmp_path / "collection.json"
    monkeypatch.setenv("LAGNIAPPE_E2E_COLLECTION", str(destination))
    markers = {"e2e_group": SimpleNamespace(args=("owner",), kwargs={}),
               "e2e_serial": SimpleNamespace(args=(), kwargs={"phase": "before"})}
    item = SimpleNamespace(nodeid="tests_e2e/test_story.py::test_one", fixturenames=[],
                           get_closest_marker=markers.get)
    session = SimpleNamespace(items=[item])
    pytest_collection_finish(session)
    assert json.loads(destination.read_text()) == [{
        "nodeid": item.nodeid, "fixtures": [], "serial": True, "serial_phase": "before", "group": "owner",
    }]
    for args, kwargs in [((), {}), (("",), {}), ((1,), {}), (("a", "b"), {}), (("a",), {"workers": 1})]:
        markers["e2e_group"] = SimpleNamespace(args=args, kwargs=kwargs)
        with pytest.raises(ValueError, match="one nonempty name"):
            pytest_collection_finish(session)


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
def test_inventory_balances_cases_without_transitive_resource_groups(tmp_path):
    folder = tmp_path / "testing/tests_e2e"
    folder.mkdir(parents=True)
    (folder / "test_story.py").write_text('''
from testing.definitions import Pages
def test_a(): Pages.shared.get(None)
def test_b():
    Pages.shared.get(None)
    Pages.other.get(None)
def test_c(): Pages.other.get(None)
def test_d(): pass
def test_reset(): pass
''', encoding="utf-8")
    records = [{"nodeid": f"tests_e2e/test_story.py::test_{name}", "fixtures": [], "serial": name == "d"}
               for name in "abcd"]
    records.append({"nodeid": "tests_e2e/test_story.py::test_reset", "fixtures": [],
                    "serial": True, "serial_phase": "before"})
    durations = {f"tests_e2e/test_story.py::test_{name}": value for name, value in zip("abc", (8, 5, 3))}
    batches, inventory = story_batches(tmp_path, records, workers=2, durations=durations)
    assert len(batches) == 4
    assert batches[0].exclusive and batches[0].nodeid.endswith("test_reset")
    assert batches[1].nodeids == ("testing/tests_e2e/test_story.py::test_a",)
    assert batches[2].nodeids == ("testing/tests_e2e/test_story.py::test_b", "testing/tests_e2e/test_story.py::test_c")
    assert not batches[1].resources and not batches[2].resources
    assert batches[-1].exclusive and batches[-1].nodeid.endswith("test_d")
    assert inventory[1]["resources"] == ["Pages.other", "Pages.shared"]
    assert inventory[2]["estimated_seconds"] == 3


# @matrix testing : parallel-e2e
@pytest.mark.parametrize("workers", [1, 3, 6])
def test_marked_groups_stay_on_one_worker_without_becoming_exclusive(tmp_path, workers):
    folder = tmp_path / "testing/tests_e2e"
    folder.mkdir(parents=True)
    (folder / "test_story.py").write_text('''
from testing.definitions import Users
def test_owner(): Users.OWNER.get(None)
def test_other(): pass
def test_quiet(): pass
''', encoding="utf-8")
    records = [
        {"nodeid": f"tests_e2e/test_story.py::test_owner[{i}]", "group": "owner"}
        for i in range(3)
    ] + [
        {"nodeid": f"tests_e2e/test_story.py::test_other[{i}]"} for i in range(12)
    ] + [{"nodeid": "tests_e2e/test_story.py::test_quiet", "group": "owner", "serial": True}]
    records = [{"fixtures": [], "serial": False, **record} for record in records]
    batches, inventory = story_batches(tmp_path, records, workers=workers)
    ordinary = [batch for batch in batches if not batch.exclusive]
    assert len(ordinary) == workers
    owner_batches = [batch for batch in ordinary if any("test_owner[" in node for node in batch.nodeids)]
    assert len(owner_batches) == 1
    assert sum("test_owner[" in node for node in owner_batches[0].nodeids) == 3
    assert all(not batch.resources for batch in ordinary)  # Per-test claims still apply.
    assert batches[-1].exclusive and batches[-1].nodeid.endswith("test_quiet")
    assert sorted(node.removeprefix("testing/") for batch in batches for node in batch.nodeids) == sorted(
        record["nodeid"] for record in records
    )
    assert inventory[0]["resources"] == ["Users.OWNER"]


# @matrix testing : parallel-e2e
def test_duration_estimates_use_only_valid_passed_e2e_results(tmp_path, monkeypatch):
    monkeypatch.delenv("LAGNIAPPE_E2E_DURATIONS", raising=False)
    assert duration_estimates(tmp_path) == {}
    evidence = tmp_path / "testing/evidence/latest.json"
    evidence.parent.mkdir(parents=True)
    values = {"good": 3.2, "zero": 0, "negative": -1, "infinite": float("inf"),
              "string": "2", "missing": None, "boolean": True}
    rows = {f"tests_e2e/test_{name}.py::test_story": {"outcome": "passed", "duration": duration}
            for name, duration in values.items()}
    rows["tests_e2e/test_failed.py::test_story"] = {"outcome": "failed", "duration": 500}
    rows["tests_unit/test_other.py::test_story"] = {"outcome": "passed", "duration": 50}
    evidence.write_text(json.dumps({"tests": rows}))
    assert duration_estimates(tmp_path) == {"tests_e2e/test_good.py::test_story": 3.2}
    hints = tmp_path / "durations.json"
    hints.write_text(json.dumps({"tests_e2e/test_hosted.py::test_story": 7.5,
                                 "tests_e2e/test_bad.py::test_story": -4}))
    monkeypatch.setenv("LAGNIAPPE_E2E_DURATIONS", str(hints))
    assert duration_estimates(tmp_path) == {"tests_e2e/test_hosted.py::test_story": 7.5}


# @matrix testing : parallel-e2e
def test_case_claims_overlap_independent_work_and_release_after_failure(tmp_path):
    script = '''
from pathlib import Path
import sys, time
from runner.e2e_claims import reserve_resources
root, name, *resources = sys.argv[1:]
root = Path(root)
(root / (name + '-waiting')).touch()
with reserve_resources(root / 'claims', resources, lambda: None, timeout=5):
    (root / (name + '-acquired')).touch()
    while not (root / (name + '-release')).exists():
        time.sleep(.01)
'''
    processes = []

    def launch(name, *resources):
        child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), name, *resources])
        processes.append(child)
        return child

    def await_file(name):
        deadline = time.monotonic() + 5
        while not (tmp_path / name).exists():
            assert time.monotonic() < deadline, name
            time.sleep(.01)

    try:
        first = launch("first", "z")
        await_file("first-acquired")
        both = launch("both", "a", "z")
        await_file("both-waiting")
        other = launch("other", "a")
        await_file("other-acquired")
        assert not (tmp_path / "both-acquired").exists()
        (tmp_path / "other-release").touch()
        assert other.wait(timeout=5) == 0
        first.kill()  # OS releases its claims even without Python teardown.
        first.wait(timeout=5)
        await_file("both-acquired")
        (tmp_path / "both-release").touch()
        assert both.wait(timeout=5) == 0
        with reserve_resources(tmp_path / "claims", ["a", "z"], lambda: None, timeout=0):
            pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


# @matrix testing : parallel-e2e
def test_case_claims_stop_waiting_on_timeout_or_lost_authority(tmp_path):
    def lost():
        raise RuntimeError("lease lost")

    with reserve_resources(tmp_path, ["shared"], lambda: None):
        with pytest.raises(RuntimeError, match="Timed out"):
            with reserve_resources(tmp_path, ["shared"], lambda: None, timeout=0):
                pytest.fail("A conflicting claim was admitted")
        with pytest.raises(RuntimeError, match="lease lost"):
            with reserve_resources(tmp_path, ["shared"], lost):
                pytest.fail("Lost authority was ignored")
    with pytest.raises(ValueError):
        with reserve_resources(tmp_path, ["shared"], lambda: None):
            raise ValueError("fixture failed")
    with reserve_resources(tmp_path, ["shared"], lambda: None, timeout=0):
        pass


# @matrix testing : parallel-e2e
def test_case_claim_hook_covers_fixture_teardown_and_continues_after_failure(tmp_path, monkeypatch):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text('''
from testing.utility import e2e_worker
e2e_worker.assert_owner = lambda record: None
''')
    (tmp_path / "test_claim.py").write_text('''
from pathlib import Path
import pytest
from runner.e2e_claims import reserve_resources
root = Path(__file__).parent
def assert_reserved():
    with pytest.raises(RuntimeError, match='Timed out'):
        with reserve_resources(root / 'claims', ['shared'], lambda: None, timeout=0):
            pytest.fail('Claim absent during fixture lifecycle')
@pytest.fixture
def broken_teardown():
    assert_reserved()
    yield
    assert_reserved()
    raise ValueError('intentional teardown failure')
def test_one(broken_teardown):
    assert_reserved()
def test_two():
    assert_reserved()
''')
    record = tmp_path / "context.json"
    record.write_text(json.dumps({"resource_registry": str(tmp_path), "artifacts": str(tmp_path),
                                  "test_resources": {f"test_claim.py::test_{n}": ["shared"]
                                                     for n in ("one", "two")}}))
    monkeypatch.setenv("LAGNIAPPE_E2E_WORKER_CONTEXT", str(record))
    result = subprocess.run([sys.executable, "-m", "pytest", "-c", str(tmp_path / "pytest.ini"),
                             "-p", "runner.e2e_claims", str(tmp_path / "test_claim.py"), "-q"],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "2 passed, 1 error" in result.stdout
    events = [json.loads(line) for line in (tmp_path / "resource-events.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events] == ["waiting", "acquired", "released"] * 2
    with reserve_resources(tmp_path / "claims", ["shared"], lambda: None, timeout=0):
        pass


# @matrix testing : parallel-e2e
def test_worker_progress_counts_cases_without_double_counting_phases(tmp_path, monkeypatch):
    from testing.utility.e2e_worker import write_progress

    record = tmp_path / "context.json"
    record.write_text(json.dumps({"artifacts": str(tmp_path), "nodeids": ["a", "b", "c"]}))
    monkeypatch.setenv("LAGNIAPPE_E2E_WORKER_CONTEXT", str(record))
    outcomes = {"a": {"outcome": "passed"}, "b": {"outcome": "skipped"}}
    write_progress(outcomes, "b")
    outcomes["a"]["outcome"] = "failed"  # A teardown failure changes the same case.
    write_progress(outcomes, "a")
    assert json.loads((tmp_path / "progress.json").read_text()) == {
        "passed": 0, "failed": 1, "skipped": 1, "completed": 2, "total": 3, "last_nodeid": "a",
    }
    assert not (tmp_path / "progress.tmp").exists()


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
def test_pilot_arguments_are_bounded_and_keep_normal_runs_unchanged(monkeypatch):
    monkeypatch.delenv("LAGNIAPPE_HOSTED_E2E_WORKERS", raising=False)
    assert pilot_arguments(["unit"]) == (False, 3, ["unit"])
    assert pilot_arguments(["--parallel"]) == ("all", 3, ["e2e"])
    assert pilot_arguments(["--parallel", "--workers=6"]) == ("all", 6, ["e2e"])
    with pytest.raises(ValueError):
        pilot_arguments(["--parallel", "--experiments"])
    enabled, workers, arguments = pilot_arguments(["--experiments", "--junitxml=result.xml"])
    assert enabled and workers == 3 and arguments == ["--junitxml=result.xml", *TARGETS]
    assert pilot_arguments(["--experiments=all"]) == ("all", 3, ["e2e"])
    assert pilot_arguments(["--experiments=all", "--experiments-workers", "6"]) == ("all", 6, ["e2e"])
    for arguments in (["--experiments=unknown"], ["--experiments", "--experiments=all"]):
        with pytest.raises(ValueError):
            pilot_arguments(arguments)
    with pytest.raises(ValueError):
        pilot_arguments(["--experiments", "e2e"])
    for arguments in (["--experiments-workers=6"], ["--experiments", "--experiments-workers=0"],
                      ["--experiments", "--experiments-workers=7"], ["--experiments", "--experiments-workers=x"]):
        with pytest.raises(ValueError):
            pilot_arguments(arguments)
    monkeypatch.setenv("LAGNIAPPE_HOSTED_E2E_WORKERS", "3")
    with pytest.raises(ValueError, match="capacity"):
        pilot_arguments(["--experiments", "--experiments-workers=6"])
    monkeypatch.setenv("LAGNIAPPE_HOSTED_E2E_WORKERS", "6")
    assert pilot_arguments(["--experiments=all"]) == ("all", 6, ["e2e"])


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
        while True:
            try:
                if status_file.read_text().split()[2] == "Z":
                    break
            except (FileNotFoundError, ProcessLookupError):
                break
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
    while True:
        try:
            if status_file.read_text().split()[2] == "Z":
                break
        except (FileNotFoundError, ProcessLookupError):
            break
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
