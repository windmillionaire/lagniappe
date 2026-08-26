"""Tooling tests for the ``run.py test`` command wrapper."""

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest
import yaml

import run
from runner import pytest_routing
from testing.utility import (
    traceability_common,
    traceability_results,
)

pytestmark = pytest.mark.tooling


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
def test_traceability_result_plugin_records_failure_tracebacks(
    monkeypatch, tmp_path, phase
):
    outcomes = {}
    with monkeypatch.context() as patch:
        patch.setattr(traceability_results, "_OUTCOMES", outcomes)
        patch.setattr(
            traceability_results,
            "behavior_snapshot",
            lambda repo_root: (
                "snapshot",
                {"testing/tests_unit/test_failure.py": "a"},
            ),
        )

        traceability_results.pytest_runtest_logreport(
            types.SimpleNamespace(
                nodeid="tests_unit/test_failure.py::test_failure",
                duration=0.25,
                failed=True,
                skipped=False,
                when=phase,
                longreprtext=f"{phase} failure traceback",
            )
        )
        traceability_results._write_manifest(
            tmp_path,
            ["run.py", "test", "tests_unit/test_failure.py::test_failure"],
            outcomes,
            1,
        )

    payload = json.loads((tmp_path / "testing/evidence/latest.json").read_text())
    result = payload["tests"]["tests_unit/test_failure.py::test_failure"]
    assert result["outcome"] == "failed"
    assert result["failed_phase"] == phase
    assert result["traceback"] == f"{phase} failure traceback"
    assert "traceback_truncated" not in result


def test_traceability_result_plugin_bounds_failure_tracebacks(monkeypatch):
    outcomes = {}
    oversized = "begin\n" + ("x" * traceability_results.MAX_TRACEBACK_CHARS) + "\nend"

    with monkeypatch.context() as patch:
        patch.setattr(traceability_results, "_OUTCOMES", outcomes)
        traceability_results.pytest_runtest_logreport(
            types.SimpleNamespace(
                nodeid="tests_unit/test_failure.py::test_failure",
                duration=0.25,
                failed=True,
                skipped=False,
                when="call",
                longreprtext=oversized,
            )
        )

    result = outcomes["tests_unit/test_failure.py::test_failure"]
    assert len(result["traceback"]) == traceability_results.MAX_TRACEBACK_CHARS
    assert result["traceback"].startswith("begin\n")
    assert result["traceback"].endswith("\nend")
    assert traceability_results.TRACEBACK_TRUNCATION_MARKER in result["traceback"]
    assert result["traceback_truncated"] is True


def test_traceability_snapshot_interning_round_trips_path_maps():
    snapshots = {
        "snapshot-one": {
            "testing/tests_unit/test_a.py": "test-a",
            "pkg/shared.py": "shared",
        },
        "snapshot-two": {
            "testing/tests_unit/test_b.py": "test-b",
            "pkg/shared.py": "shared",
        },
    }

    fingerprint_pairs, encoded = traceability_common.encode_test_run_snapshots(
        snapshots
    )
    manifest = {
        "schema_version": traceability_common.TEST_RUN_SCHEMA_VERSION,
        "fingerprint_pairs": fingerprint_pairs,
        "snapshots": encoded,
    }

    assert fingerprint_pairs.count(["pkg/shared.py", "shared"]) == 1
    assert traceability_common.decode_test_run_snapshots(manifest) == snapshots


def test_behavior_snapshot_excludes_tracked_test_evidence(monkeypatch, tmp_path):
    source = tmp_path / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n")
    workflow = tmp_path / ".github/workflows/release.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n")
    evidence = tmp_path / traceability_common.LATEST_TEST_RUN
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"tests": {}}\n')

    def fake_git(repo_root, *args, **kwargs):
        del repo_root, kwargs
        stdout = (
            b".github/workflows/release.yml\0"
            b"src/example.py\0"
            b"testing/evidence/latest.json\0"
            if args == ("ls-files", "-z")
            else b""
        )
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(traceability_common, "_git", fake_git)

    fingerprints = traceability_common.behavior_path_fingerprints(tmp_path)

    assert "src/example.py" in fingerprints
    assert ".github/workflows/release.yml" not in fingerprints
    assert "testing/evidence/latest.json" not in fingerprints


def test_traceability_result_plugin_merges_focused_results_without_session_history(
    monkeypatch, tmp_path
):
    tests_root = tmp_path / "testing/tests_unit"
    tests_root.mkdir(parents=True)
    (tests_root / "test_a.py").write_text("def test_a():\n    pass\n")
    (tests_root / "test_b.py").write_text("def test_b():\n    pass\n")
    generated_at = "2026-01-01T00:00:00+00:00"
    monkeypatch.setattr(
        traceability_results,
        "utc_now",
        lambda: generated_at,
    )
    for nodeid in ("tests_unit/test_a.py::test_a", "tests_unit/test_b.py::test_b"):
        command = ["run.py", "test", nodeid]
        traceability_results._write_manifest(
            tmp_path,
            command,
            {nodeid: {"outcome": "passed", "duration": 0.1}},
            0,
        )

    payload = json.loads((tmp_path / "testing/evidence/latest.json").read_text())
    assert sorted(payload["tests"]) == [
        "tests_unit/test_a.py::test_a",
        "tests_unit/test_b.py::test_b",
    ]
    assert payload["sessions"] == [
        {
            "generated_at": generated_at,
            "command": [
                "run.py",
                "test",
                "tests_unit/test_b.py::test_b",
            ],
            "exit_status": 0,
            "tests": 1,
            "snapshot": payload["tests"]["tests_unit/test_b.py::test_b"][
                "snapshot"
            ],
        }
    ]
    assert payload["provenance"] == {
        "generated_at": generated_at,
        "command": [
            "run.py",
            "test",
            "tests_unit/test_b.py::test_b",
        ],
        "behavior_snapshot": payload["sessions"][0]["snapshot"],
    }


def test_traceability_result_plugin_replaces_a_tests_previous_result(
    monkeypatch, tmp_path
):
    snapshots = iter(
        [
            ("snapshot-one", {"testing/tests_unit/test_a.py": "a"}),
            ("snapshot-two", {"testing/tests_unit/test_a.py": "b"}),
        ]
    )
    monkeypatch.setattr(
        traceability_results, "behavior_snapshot", lambda repo_root: next(snapshots)
    )
    nodeid = "tests_unit/test_a.py::test_a"
    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", nodeid],
        {
            nodeid: {
                "outcome": "failed",
                "duration": 0.2,
                "traceback": "old failure",
            }
        },
        1,
    )
    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", nodeid],
        {nodeid: {"outcome": "passed", "duration": 0.1}},
        0,
    )

    payload = json.loads((tmp_path / "testing/evidence/latest.json").read_text())
    assert payload["tests"] == {
        nodeid: {
            "outcome": "passed",
            "duration": 0.1,
            "snapshot": "snapshot-two",
        }
    }
    assert set(payload["snapshots"]) == {"snapshot-two"}
    assert payload["fingerprint_pairs"] == [
        ["testing/tests_unit/test_a.py", "b"]
    ]
    assert traceability_common.decode_test_run_snapshots(payload) == {
        "snapshot-two": {"testing/tests_unit/test_a.py": "b"}
    }
    assert len(payload["sessions"]) == 1
    assert payload["sessions"][0]["exit_status"] == 0


def test_traceability_result_plugin_replaces_a_completed_parameter_set(
    monkeypatch, tmp_path
):
    snapshots = iter(
        [
            ("snapshot-one", {"testing/tests_unit/test_a.py": "old"}),
            ("snapshot-two", {"testing/tests_unit/test_a.py": "current"}),
        ]
    )
    monkeypatch.setattr(
        traceability_results, "behavior_snapshot", lambda repo_root: next(snapshots)
    )
    base_nodeid = "tests_unit/test_a.py::test_a"
    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", base_nodeid],
        {
            f"{base_nodeid}[current]": {"outcome": "passed", "duration": 0.1},
            f"{base_nodeid}[removed]": {"outcome": "passed", "duration": 0.1},
        },
        0,
    )

    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", base_nodeid],
        {
            f"{base_nodeid}[current]": {"outcome": "passed", "duration": 0.1},
        },
        0,
    )

    payload = json.loads((tmp_path / "testing/evidence/latest.json").read_text())
    assert set(payload["tests"]) == {f"{base_nodeid}[current]"}
    assert set(payload["snapshots"]) == {"snapshot-two"}


def test_traceability_result_plugin_keeps_other_tests_across_tree_changes(
    monkeypatch, tmp_path
):
    tests_root = tmp_path / "testing/tests_unit"
    tests_root.mkdir(parents=True)
    (tests_root / "test_a.py").write_text("def test_a():\n    pass\n")
    (tests_root / "test_b.py").write_text("def test_b():\n    pass\n")
    generated_times = iter(
        [
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:01:00+00:00",
        ]
    )
    snapshots = iter(
        [
            ("snapshot-one", {"testing/tests_unit/test_a.py": "a"}),
            ("snapshot-two", {"testing/tests_unit/test_b.py": "b"}),
        ]
    )
    monkeypatch.setattr(
        traceability_results,
        "utc_now",
        lambda: next(generated_times),
    )
    monkeypatch.setattr(
        traceability_results, "behavior_snapshot", lambda repo_root: next(snapshots)
    )

    for nodeid in ("tests_unit/test_a.py::test_a", "tests_unit/test_b.py::test_b"):
        traceability_results._write_manifest(
            tmp_path,
            ["run.py", "test", nodeid],
            {nodeid: {"outcome": "passed", "duration": 0.1}},
            0,
        )

    payload = json.loads((tmp_path / "testing/evidence/latest.json").read_text())
    assert sorted(payload["tests"]) == [
        "tests_unit/test_a.py::test_a",
        "tests_unit/test_b.py::test_b",
    ]
    assert set(payload["snapshots"]) == {"snapshot-one", "snapshot-two"}
    assert traceability_common.decode_test_run_snapshots(payload) == {
        "snapshot-one": {"testing/tests_unit/test_a.py": "a"},
        "snapshot-two": {"testing/tests_unit/test_b.py": "b"},
    }


def test_traceability_result_plugin_prunes_deleted_test_modules(monkeypatch, tmp_path):
    tests_root = tmp_path / "testing/tests_unit"
    tests_root.mkdir(parents=True)
    deleted_path = tests_root / "test_deleted.py"
    retained_path = tests_root / "test_retained.py"
    deleted_path.write_text("def test_deleted():\n    pass\n")
    retained_path.write_text("def test_retained():\n    pass\n")
    snapshots = iter(
        [
            (
                "snapshot-one",
                {
                    "testing/tests_unit/test_deleted.py": "deleted",
                    "testing/tests_unit/test_retained.py": "retained-old",
                },
            ),
            (
                "snapshot-two",
                {"testing/tests_unit/test_retained.py": "retained-current"},
            ),
        ]
    )
    monkeypatch.setattr(
        traceability_results, "behavior_snapshot", lambda repo_root: next(snapshots)
    )
    deleted_nodeid = "tests_unit/test_deleted.py::test_deleted"
    retained_nodeid = "tests_unit/test_retained.py::test_retained"
    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", "testing/tests_unit"],
        {
            deleted_nodeid: {"outcome": "passed", "duration": 0.1},
            retained_nodeid: {"outcome": "passed", "duration": 0.1},
        },
        0,
    )

    deleted_path.unlink()
    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", retained_nodeid],
        {retained_nodeid: {"outcome": "passed", "duration": 0.1}},
        0,
    )

    payload = json.loads((tmp_path / "testing/evidence/latest.json").read_text())
    assert set(payload["tests"]) == {retained_nodeid}
    assert set(payload["snapshots"]) == {"snapshot-two"}
    assert traceability_common.decode_test_run_snapshots(payload) == {
        "snapshot-two": {"testing/tests_unit/test_retained.py": "retained-current"}
    }


def test_traceability_result_plugin_prunes_deleted_test_functions(
    monkeypatch, tmp_path
):
    tests_root = tmp_path / "testing/tests_unit"
    tests_root.mkdir(parents=True)
    module = tests_root / "test_example.py"
    module.write_text(
        "def test_removed():\n    pass\n\n"
        "def test_retained():\n    pass\n"
    )
    snapshots = iter(
        [
            ("snapshot-one", {"testing/tests_unit/test_example.py": "old"}),
            ("snapshot-two", {"testing/tests_unit/test_example.py": "current"}),
        ]
    )
    monkeypatch.setattr(
        traceability_results, "behavior_snapshot", lambda repo_root: next(snapshots)
    )
    removed = "tests_unit/test_example.py::test_removed"
    retained = "tests_unit/test_example.py::test_retained"
    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", "testing/tests_unit"],
        {
            removed: {"outcome": "passed", "duration": 0.1},
            retained: {"outcome": "passed", "duration": 0.1},
        },
        0,
    )

    module.write_text("def test_retained():\n    pass\n")
    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", retained],
        {retained: {"outcome": "passed", "duration": 0.1}},
        0,
    )

    payload = json.loads((tmp_path / "testing/evidence/latest.json").read_text())
    assert set(payload["tests"]) == {retained}
    assert set(payload["snapshots"]) == {"snapshot-two"}


def test_traceability_result_plugin_migrates_legacy_snapshot_maps(
    monkeypatch, tmp_path
):
    tests_root = tmp_path / "testing/tests_unit"
    tests_root.mkdir(parents=True)
    (tests_root / "test_a.py").write_text("def test_a():\n    pass\n")
    (tests_root / "test_b.py").write_text("def test_b():\n    pass\n")
    destination = tmp_path / "testing/evidence/latest.json"
    destination.parent.mkdir(parents=True)
    destination.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "kind": "test-run",
                "provenance": {},
                "tests": {
                    "tests_unit/test_a.py::test_a": {
                        "outcome": "passed",
                        "duration": 0.1,
                        "snapshot": "snapshot-one",
                    }
                },
                "snapshots": {
                    "snapshot-one": {
                        "paths": {
                            "testing/tests_unit/test_a.py": "test-a",
                            "pkg/shared.py": "shared",
                        }
                    }
                },
            }
        )
    )
    monkeypatch.setattr(
        traceability_results,
        "behavior_snapshot",
        lambda repo_root: (
            "snapshot-two",
            {
                "testing/tests_unit/test_b.py": "test-b",
                "pkg/shared.py": "shared",
            },
        ),
    )

    traceability_results._write_manifest(
        tmp_path,
        ["run.py", "test", "tests_unit/test_b.py::test_b"],
        {
            "tests_unit/test_b.py::test_b": {
                "outcome": "passed",
                "duration": 0.1,
            }
        },
        0,
    )

    payload = json.loads(destination.read_text())
    assert payload["schema_version"] == traceability_common.TEST_RUN_SCHEMA_VERSION
    assert sorted(payload["tests"]) == [
        "tests_unit/test_a.py::test_a",
        "tests_unit/test_b.py::test_b",
    ]
    assert payload["fingerprint_pairs"].count(["pkg/shared.py", "shared"]) == 1
    assert traceability_common.decode_test_run_snapshots(payload) == {
        "snapshot-one": {
            "testing/tests_unit/test_a.py": "test-a",
            "pkg/shared.py": "shared",
        },
        "snapshot-two": {
            "testing/tests_unit/test_b.py": "test-b",
            "pkg/shared.py": "shared",
        },
    }


def test_behavior_fingerprint_ignores_python_and_javascript_comments(tmp_path):
    python_path = tmp_path / "sample.py"
    python_path.write_text(
        '"""first module note"""\n# @matrix old : behavior\ndef value():\n    """old note"""\n    return 1\n'
    )
    python_before = traceability_common.behavior_file_fingerprint(python_path)
    python_path.write_text(
        '"""new module note"""\n# @matrix new : behavior\ndef value():\n    """new note"""\n    return 1\n'
    )

    javascript_path = tmp_path / "sample.mjs"
    javascript_path.write_text(
        "/** @matrix old : behavior */\nexport function value() { return 'https://a.test'; }\n"
    )
    javascript_before = traceability_common.behavior_file_fingerprint(javascript_path)
    javascript_path.write_text(
        "// @matrix new : behavior\nexport function value() { return 'https://a.test'; }\n"
    )

    assert traceability_common.behavior_file_fingerprint(python_path) == python_before
    assert (
        traceability_common.behavior_file_fingerprint(javascript_path)
        == javascript_before
    )


def test_behavior_fingerprint_ignores_generated_build_id(tmp_path):
    constants_path = tmp_path / "config/constants.py"
    constants_path.parent.mkdir(parents=True)
    constants_path.write_text('BUILD_ID = "b0000000"\nVALUE = 1\n')
    before = traceability_common.behavior_file_fingerprint(constants_path)

    constants_path.write_text('BUILD_ID = "b1234567"\nVALUE = 1\n')
    assert traceability_common.behavior_file_fingerprint(constants_path) == before

    constants_path.write_text('BUILD_ID = "b1234567"\nVALUE = 2\n')
    assert traceability_common.behavior_file_fingerprint(constants_path) != before


def test_behavior_snapshot_fingerprints_style_records_independently(tmp_path):
    styles = tmp_path / "src/style/styles.yaml"
    styles.parent.mkdir(parents=True)
    styles.write_text(
        "button:\n"
        "  submit:\n"
        "    classes: flex\n"
        "label:\n"
        "  default:\n"
        "    classes: font-semibold\n"
    )

    before = traceability_common.behavior_path_fingerprints(tmp_path)
    styles.write_text(
        "button:\n"
        "  submit:\n"
        "    classes: flex gap-2\n"
        "label:\n"
        "  default:\n"
        "    classes: font-semibold\n"
    )
    after = traceability_common.behavior_path_fingerprints(tmp_path)

    assert before["@style/button.submit"] != after["@style/button.submit"]
    assert before["@style/label.default"] == after["@style/label.default"]


# @matrix testing : cli-routing pytest-options target-selection
@pytest.mark.parametrize(
    ("arguments", "expected_args", "expected_targets", "includes_e2e"),
    (
        (
            ["unit"],
            ("testing/tests_unit/",),
            ("testing/tests_unit/",),
            False,
        ),
        (
            ["--color", "yes"],
            ("--color", "yes"),
            (str(Path(run.__file__).parent),),
            True,
        ),
        (
            ["--durations", "10", "unit"],
            ("--durations", "10", "testing/tests_unit/"),
            ("testing/tests_unit/",),
            False,
        ),
        (
            ["e2e", "--browser", "chromium"],
            ("--browser", "chromium", "testing/tests_e2e/"),
            ("testing/tests_e2e/",),
            True,
        ),
        (
            ["--browser=chromium", "e2e"],
            ("--browser=chromium", "testing/tests_e2e/"),
            ("testing/tests_e2e/",),
            True,
        ),
        (
            ["--browser-failure-diagnostics", "e2e"],
            ("--browser-failure-diagnostics", "testing/tests_e2e/"),
            ("testing/tests_e2e/",),
            True,
        ),
        (
            ["unit", "-k", "unit"],
            ("-k", "unit", "testing/tests_unit/"),
            ("testing/tests_unit/",),
            False,
        ),
        (
            ["-k", "unit"],
            ("-k", "unit"),
            (str(Path(run.__file__).parent),),
            True,
        ),
        (
            ["-k=-unit", "unit"],
            ("-k=-unit", "testing/tests_unit/"),
            ("testing/tests_unit/",),
            False,
        ),
        (
            ["unit", "tooling", "-m", "not unfinished"],
            (
                "-m",
                "not unfinished",
                "testing/tests_unit/",
                "testing/tests_tooling/",
            ),
            ("testing/tests_unit/", "testing/tests_tooling/"),
            False,
        ),
    ),
)
def test_normalize_pytest_invocation_routes_registered_option_values(
    arguments, expected_args, expected_targets, includes_e2e
):
    invocation = pytest_routing.normalize_pytest_invocation(
        arguments, Path(run.__file__).parent
    )

    assert invocation.pytest_args == expected_args
    assert invocation.collection_targets == expected_targets
    assert invocation.includes_e2e is includes_e2e


def test_setup_suite_inventory_classifies_every_setup_module_once():
    repository_root = Path(run.__file__).parent
    discovered = {
        path.relative_to(repository_root).as_posix()
        for path in (repository_root / "testing/tests_tooling").glob(
            "test_*_setup_*.py"
        )
    }
    configured = [
        target
        for targets in pytest_routing.SETUP_TEST_GROUPS.values()
        for target in targets
    ]
    configured_tooling = {
        target for target in configured if target.startswith("testing/tests_tooling/")
    }

    assert discovered == configured_tooling
    assert len(configured) == len(set(configured))
    assert all((repository_root / target).is_file() for target in configured)
    assert (
        "testing/tests_tooling/test_001h_setup_ai_email.py"
        in pytest_routing.TEST_SUITE_ALIASES["setup"]
    )


def test_pytest_cli_options_are_not_registered_in_suite_conftests():
    repository_root = Path(run.__file__).parent
    violations = []
    for path in (repository_root / "testing").rglob("conftest.py"):
        module = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "pytest_addoption"
            for node in ast.walk(module)
        ):
            violations.append(path.relative_to(repository_root).as_posix())

    assert violations == []


# @matrix setup testing : cli-routing opt-in pytest-markers
@pytest.mark.parametrize(
    ("marker_expression", "expected_markers"),
    (
        ("setup_drift", ("setup_drift",)),
        ("setup_provider", ("setup_provider",)),
        (
            "setup_drift or setup_provider",
            ("setup_drift", "setup_provider"),
        ),
        ("provider", ("setup_drift", "setup_provider")),
    ),
)
def test_normalize_pytest_invocation_adds_setup_opt_in_targets_without_filenames(
    marker_expression, expected_markers
):
    invocation = pytest_routing.normalize_pytest_invocation(
        ["setup", "-m", marker_expression], Path(run.__file__).parent
    )

    expected_targets = tuple(pytest_routing.TEST_SUITE_ALIASES["setup"]) + tuple(
        target
        for marker in expected_markers
        for target in pytest_routing.SETUP_OPT_IN_TESTS[marker]
    )
    assert invocation.collection_targets == expected_targets
    assert invocation.pytest_args[:2] == ("-m", marker_expression)
    assert invocation.pytest_args[2:] == expected_targets
    assert invocation.includes_e2e is ("setup_provider" in expected_markers)


def test_normalize_pytest_invocation_preserves_real_nodeids():
    target = "testing/tests_tooling/test_007_run_py_test_command.py::test_example"

    invocation = pytest_routing.normalize_pytest_invocation(
        [target, "--tb=short"], Path(run.__file__).parent
    )
    assert invocation.pytest_args == ("--tb=short", target)
    assert invocation.collection_targets == (target,)
    assert invocation.includes_e2e is False


def test_normalize_pytest_invocation_handles_strict_and_pytest_separator():
    strict = pytest_routing.normalize_pytest_invocation(
        ["--strict", "unit", "--tb=short"], Path(run.__file__).parent
    )
    assert strict.strict_relations is True
    assert strict.pytest_args == ("--tb=short", "testing/tests_unit/")

    passthrough = pytest_routing.normalize_pytest_invocation(
        ["--", "-k", "category"], Path(run.__file__).parent
    )
    assert passthrough.pytest_args == ("-k", "category")
    assert passthrough.includes_e2e is True

    literal_target = pytest_routing.normalize_pytest_invocation(
        ["--", "--", "--strict"], Path(run.__file__).parent
    )
    assert literal_target.strict_relations is False
    assert literal_target.pytest_args == ("--", "--strict")
    assert literal_target.collection_targets == ("--strict",)


# @matrix testing : cli-routing pytest-options target-selection
@pytest.mark.parametrize(
    "arguments",
    (
        ["tooling", "testing/tests_tooling/test_007_run_py_test_command.py"],
        ["--pyargs", "testing.tests_unit"],
        ["@test-targets.txt"],
        ["-p", "no:runner.pytest_routing", "unit"],
    ),
)
def test_normalize_pytest_invocation_rejects_ambiguous_or_indirect_targets(
    arguments,
):
    with pytest.raises(pytest_routing.PytestRoutingError):
        pytest_routing.normalize_pytest_invocation(
            arguments, Path(run.__file__).parent
        )


def test_normalize_pytest_invocation_rejects_hidden_addopts_targets(monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "testing/tests_unit/")

    with pytest.raises(pytest_routing.PytestRoutingError, match="PYTEST_ADDOPTS"):
        pytest_routing.normalize_pytest_invocation([], Path(run.__file__).parent)


def _configured_value_option_cases(tmp_path):
    from _pytest.config import _prepareconfig

    repository_root = Path(run.__file__).parent
    config = _prepareconfig(
        ["-c", pytest_routing.PYTEST_CONFIG, "--noconftest"],
        plugins=[pytest_routing, traceability_results],
        prog="run.py test",
    )
    special_values = {
        "basetemp": str(tmp_path / "pytest-base"),
        "base_url": "https://example.test",
        "cacheshow": "*",
        "confcutdir": str(repository_root),
        "debug": str(tmp_path / "pytest-debug.log"),
        "inifilename": str(repository_root / pytest_routing.PYTEST_CONFIG),
        "keyword": "unit-value",
        "log_auto_indent": "1",
        "log_cli_level": "INFO",
        "log_file": str(tmp_path / "pytest.log"),
        "log_file_level": "INFO",
        "log_level": "INFO",
        "markexpr": "not unfinished",
        "override_ini": "addopts=",
        "plugins": "no:terminalprogress",
        "pythonwarnings": "default",
        "rootdir": str(repository_root),
        "usepdb_cls": "pdb:Pdb",
        "xmlpath": str(tmp_path / "junit.xml"),
    }
    try:
        cases = []
        for action in config._parser.optparser._actions:
            if not action.option_strings or action.nargs == 0:
                continue
            option = next(
                (
                    candidate
                    for candidate in action.option_strings
                    if candidate.startswith("--")
                ),
                action.option_strings[0],
            )
            if action.dest in special_values:
                value = special_values[action.dest]
            elif action.choices:
                value = str(next(iter(action.choices)))
            elif action.type is int:
                value = "1"
            elif action.type is float:
                value = "0.1"
            else:
                value = "routing-value"
            cases.append((option, value, action.nargs))
        return cases
    finally:
        config._ensure_unconfigure()


def test_normalize_pytest_invocation_routes_every_registered_valued_option(
    tmp_path,
):
    repository_root = Path(run.__file__).parent
    cases = _configured_value_option_cases(tmp_path)
    option_names = {option for option, _value, _nargs in cases}

    assert {
        "--base-url",
        "--browser",
        "--color",
        "--durations",
    }.issubset(option_names)
    assert len(cases) >= 50

    for option, value, nargs in cases:
        invocation = pytest_routing.normalize_pytest_invocation(
            [option, value, "unit"], repository_root
        )
        assert invocation.collection_targets == ("testing/tests_unit/",), option
        assert invocation.pytest_args[-1] == "testing/tests_unit/", option
        assert invocation.includes_e2e is False, option

        if option.startswith("--") and nargs in {None, "?"}:
            equals_invocation = pytest_routing.normalize_pytest_invocation(
                [f"{option}={value}", "unit"], repository_root
            )
            assert equals_invocation.collection_targets == (
                "testing/tests_unit/",
            ), option


def test_normalize_pytest_invocation_isolates_parser_imports_and_cwd(
    monkeypatch, tmp_path
):
    repository_root = Path(run.__file__).parent
    monkeypatch.chdir(tmp_path)
    before = set(sys.modules)

    invocation = pytest_routing.normalize_pytest_invocation(
        ["--color", "yes", "unit"], repository_root
    )

    assert Path.cwd() == tmp_path
    assert invocation.collection_targets == ("testing/tests_unit/",)
    imported = set(sys.modules) - before
    assert not any(
        module == "config"
        or module.startswith("lagniappe")
        or module.startswith("testing.tests_e2e.conftest")
        or module.startswith("testing.tests_unit.conftest")
        for module in imported
    )


# @matrix testing : cli-routing target-selection
def test_normalized_targets_control_actual_pytest_collection(
    monkeypatch, tmp_path
):
    (tmp_path / "testing/tests_unit").mkdir(parents=True)
    (tmp_path / "testing/tests_e2e").mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\n"
        "testpaths =\n"
        "    testing/tests_unit\n"
        "    testing/tests_e2e\n",
        encoding="utf-8",
    )
    (tmp_path / "testing/tests_unit/test_unit_sample.py").write_text(
        "def test_unit_sample():\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "testing/tests_e2e/test_e2e_sample.py").write_text(
        "def test_e2e_sample():\n    pass\n", encoding="utf-8"
    )
    monkeypatch.setattr(pytest_routing, "PYTEST_CONFIG", "pytest.ini")

    requests = (
        (
            ["--color", "no", "unit"],
            "test_unit_sample.py::test_unit_sample",
            "test_e2e_sample.py::test_e2e_sample",
            False,
        ),
        (
            ["e2e", "--browser", "chromium"],
            "test_e2e_sample.py::test_e2e_sample",
            "test_unit_sample.py::test_unit_sample",
            True,
        ),
    )
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    repository_root = Path(run.__file__).parent
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(repository_root), existing_pythonpath)
        if part
    )
    for arguments, selected, excluded, includes_e2e in requests:
        invocation = pytest_routing.normalize_pytest_invocation(
            arguments, tmp_path
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-c",
                "pytest.ini",
                "-p",
                pytest_routing.PYTEST_ROUTING_PLUGIN,
                "--collect-only",
                "-q",
                *invocation.pytest_args,
            ],
            cwd=tmp_path,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr + result.stdout
        assert selected in result.stdout
        assert excluded not in result.stdout
        assert invocation.includes_e2e is includes_e2e


# @matrix setup testing : pytest-markers
def test_pytest_routing_plugin_normalizes_provider_marker_tokens():
    config = types.SimpleNamespace(
        option=types.SimpleNamespace(markexpr="provider and not ai_provider")
    )

    pytest_routing.pytest_configure(config)

    assert config.option.markexpr == (
        "(setup_drift or setup_provider) and not ai_provider"
    )


def test_run_py_test_argument_errors_stop_before_preflight(monkeypatch, capsys):
    monkeypatch.setattr(
        run,
        "configure_test_environment",
        lambda **kwargs: pytest.fail("argument errors must skip environment setup"),
    )
    monkeypatch.setattr(
        run,
        "activate_repository_gcloud",
        lambda **kwargs: pytest.fail("argument errors must skip gcloud setup"),
    )
    monkeypatch.setattr(
        run,
        "_run_pytest_subprocess",
        lambda command: pytest.fail("argument errors must skip pytest"),
    )

    assert run.run_tests(
        ["tooling", "testing/tests_tooling/test_007_run_py_test_command.py"]
    ) == 4
    assert "suite aliases cannot be combined" in capsys.readouterr().err


# @pair testing:environment
def test_configure_test_environment_only_sets_import_environment(monkeypatch):
    calls = []
    config_module = types.ModuleType("config")
    config_module.__path__ = ["config"]
    testing_module = types.ModuleType("runner.testing")
    testing_module.ensure_test_frontend_bundle = lambda: calls.append("bundle")
    testing_module.hosted_e2e_enabled = lambda: False
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "runner.testing", testing_module)

    run.configure_test_environment(includes_e2e=False)
    assert calls == []

    run.configure_test_environment(includes_e2e=True)
    run.configure_test_environment(includes_e2e=True)

    assert calls == []


# @matrix hosted-e2e testing : cli-routing frontend-build provider-auth
def test_hosted_e2e_runner_skips_local_build_and_gcloud_activation(monkeypatch):
    calls = []
    from runner import testing as testing_module

    monkeypatch.setenv("LAGNIAPPE_HOSTED_E2E", "true")
    monkeypatch.setattr(
        testing_module,
        "ensure_test_frontend_bundle",
        lambda: calls.append("bundle"),
    )
    monkeypatch.setattr(
        run,
        "activate_repository_gcloud",
        lambda **kwargs: calls.append(("gcloud", kwargs)),
    )
    monkeypatch.setattr(
        run,
        "_run_pytest_subprocess",
        lambda command: calls.append(("pytest", command)) or 0,
    )

    assert run.run_tests(["e2e"]) == 0
    assert [name for name, *_rest in calls] == ["pytest"]


# @matrix hosted-e2e testing : cleanup fail-closed prefix
def test_cleanup_scope_requires_the_reserved_test_prefix():
    from runner import testing as testing_module

    testing_module._require_test_cleanup_scope(
        types.SimpleNamespace(testing=True, PREFIX="test-")
    )
    for config in (
        types.SimpleNamespace(testing=False, PREFIX="test-"),
        types.SimpleNamespace(testing=True, PREFIX=""),
        types.SimpleNamespace(testing=True, PREFIX="production-"),
    ):
        with pytest.raises(RuntimeError, match="reserved test- data prefix"):
            testing_module._require_test_cleanup_scope(config)


# @matrix hosted-e2e testing : cache database initialization migrations
def test_initialize_test_services_replays_server_persistence_startup():
    from runner import testing as testing_module

    calls = []
    database = types.SimpleNamespace(
        initialize=lambda: calls.append("database") or True
    )
    cache = types.SimpleNamespace(initialize=lambda: calls.append("cache"))
    migrations = types.SimpleNamespace(
        initialize_fresh_install=lambda fresh: calls.append(("migrations", fresh))
    )

    assert testing_module._initialize_test_services(
        database,
        cache,
        migrations,
    ) is True
    assert calls == ["cache", "database", ("migrations", True)]


def test_run_py_test_invokes_pytest_subprocess_with_shared_config(monkeypatch, capsys):
    calls = []
    events = []
    monkeypatch.setenv("LAGNIAPPE_TEST_COMMAND", '["outer", "test"]')

    class FakeProcess:
        pid = 2468

        def wait(self):
            return 3

    def fake_popen(command, **kwargs):
        assert events == [
            (
                "activate-gcloud",
                {
                    "ensure_adc": False,
                    "allow_runtime_adc": False,
                    "allow_adc_login": False,
                },
            )
        ]
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(
        run,
        "activate_repository_gcloud",
        lambda **kwargs: events.append(("activate-gcloud", kwargs)),
    )
    monkeypatch.setattr(run.subprocess, "Popen", fake_popen)

    assert run.run_tests(
        ["testing/tests_tooling/test_007_run_py_test_command.py"]
    ) == 3

    command, kwargs = calls[0]
    assert command == [
        run.sys.executable,
        "-m",
        "pytest",
        "-c",
        "testing/pytest.ini",
        "-p",
        "testing.utility.traceability_results",
        "-p",
        "runner.pytest_routing",
        "testing/tests_tooling/test_007_run_py_test_command.py",
    ]
    assert kwargs == {
        "cwd": run.REPOSITORY_ROOT,
        "start_new_session": True,
    }
    assert "Running:" in capsys.readouterr().out
    assert os.environ["LAGNIAPPE_TEST_COMMAND"] == '["outer", "test"]'


# @pair testing:adc
def test_run_py_e2e_aligns_adc_before_pytest(monkeypatch):
    calls = []

    class FakeAuthority:
        nonce = "nonce-01234567890123456789"
        mode = "local-e2e"

        def update(self, **changes):
            calls.append(("update", changes))

        def complete(self):
            calls.append("complete")

        def mark_recovery_required(self):
            calls.append("recovery")

    fake_authority = FakeAuthority()
    fake_session = types.ModuleType("runner.test_session")
    fake_session.SESSION_MODE_ENV = "LAGNIAPPE_TEST_SESSION_MODE"
    fake_session.SESSION_NONCE_ENV = "LAGNIAPPE_TEST_SESSION_NONCE"
    fake_session.acquire_test_session = (
        lambda mode, command: calls.append(("acquire", mode, command))
        or fake_authority
    )
    fake_testing = types.ModuleType("runner.testing")
    fake_testing.require_legacy_test_server_clear = lambda: calls.append("legacy")
    fake_testing.require_server_port_available = lambda url: calls.append(("port", url))
    fake_testing.ensure_test_frontend_bundle = lambda authority: calls.append("bundle")
    fake_testing.prepare_test_artifacts = lambda authority: calls.append("artifacts")
    fake_testing.cleanup_test_data = lambda authority: calls.append("cleanup")
    fake_testing.run_test_server = lambda authority: types.SimpleNamespace(pid=5000)
    fake_testing.terminate_test_server_process = lambda process: calls.append("stop")
    fake_config = types.ModuleType("config")
    fake_config.__path__ = []
    fake_config.SETTINGS = types.SimpleNamespace(
        test_config={"BASE_URL": "http://127.0.0.1:5000"}
    )

    class FakeProcess:
        pid = 8642

        def wait(self):
            return 0

    monkeypatch.setattr(
        run,
        "configure_test_environment",
        lambda **kwargs: calls.append(("environment", kwargs)),
    )
    monkeypatch.setattr(
        run,
        "activate_repository_gcloud",
        lambda **kwargs: calls.append(("gcloud", kwargs)),
    )
    monkeypatch.setattr(
        run.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append(("pytest", command))
        or FakeProcess(),
    )
    monkeypatch.setitem(sys.modules, "runner.test_session", fake_session)
    monkeypatch.setitem(sys.modules, "runner.testing", fake_testing)
    monkeypatch.setitem(sys.modules, "config", fake_config)

    assert run.run_tests(["e2e"]) == 0
    assert calls[:2] == [
        ("environment", {"includes_e2e": True}),
        (
            "gcloud",
            {
                "ensure_adc": True,
                "allow_runtime_adc": True,
                "allow_adc_login": False,
            },
        ),
    ]


def test_run_py_e2e_adc_mismatch_stops_before_pytest(monkeypatch, capsys):
    monkeypatch.setattr(run, "configure_test_environment", lambda **kwargs: None)
    monkeypatch.setattr(
        run,
        "activate_repository_gcloud",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("Run python run.py auth and retry.")
        ),
    )
    monkeypatch.setattr(
        run.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("pytest must not start"),
    )

    assert run.run_tests(["e2e"]) == 1
    output = capsys.readouterr().out
    assert "Test startup stopped:" in output
    assert "run.py auth" in output


# @matrix development : adc gcloud-config launch-order
def test_run_dev_server_aligns_adc_before_flask_launch(monkeypatch):
    from runner import development

    calls = []
    monkeypatch.setattr(
        development,
        "SETTINGS",
        types.SimpleNamespace(dev_config={"SERVER_PORT": "5050"}),
    )
    monkeypatch.setattr(development, "APP_DIR", Path("/app"))
    monkeypatch.setattr(
        development,
        "activate_repository_gcloud",
        lambda **kwargs: calls.append(("gcloud", kwargs)),
    )
    class FakeProcess:
        pid = 5050

        def wait(self):
            return 0

    monkeypatch.setattr(
        development.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append(("flask", command, kwargs))
        or FakeProcess(),
    )
    monkeypatch.setenv("FLASK_ENV", "testing")

    assert development.run_dev_server() == 0

    assert calls == [
        (
            "gcloud",
            {
                "ensure_adc": True,
                "allow_runtime_adc": True,
                "allow_adc_login": False,
            },
        ),
        (
            "flask",
            [
                development.sys.executable,
                "-m",
                "flask",
                "--app",
                "main.py",
                "--debug",
                "run",
                "--port",
                "5050",
            ],
            {
                "env": {
                    **os.environ,
                    "FLASK_ENV": "development",
                },
                "cwd": Path("/app"),
                "start_new_session": True,
            },
        ),
    ]


# @matrix development : adc gcloud-config launch-order noninteractive
def test_run_dev_server_adc_mismatch_stops_before_flask(monkeypatch, capsys):
    from runner import development

    monkeypatch.setattr(
        development,
        "activate_repository_gcloud",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("Run python run.py auth and retry.")
        ),
    )
    monkeypatch.setattr(
        development.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("Flask must not start"),
    )

    assert development.run_dev_server() == 1
    output = capsys.readouterr().out
    assert "Development server startup stopped:" in output
    assert "run.py auth" in output


# @matrix development : lifecycle process-ownership signals
def test_run_dev_server_forwards_signals_and_restores_handlers(monkeypatch):
    from runner import development

    installed = {}
    restored = []
    sent = []
    previous = {
        development.signal.SIGINT: object(),
        development.signal.SIGTERM: object(),
    }

    class FakeProcess:
        pid = 8642

        def wait(self):
            installed[development.signal.SIGINT](development.signal.SIGINT, None)
            installed[development.signal.SIGTERM](development.signal.SIGTERM, None)
            return 7

    def fake_signal(signum, handler):
        if handler is previous[signum]:
            restored.append(signum)
        else:
            installed[signum] = handler

    monkeypatch.setattr(
        development,
        "SETTINGS",
        types.SimpleNamespace(dev_config={"SERVER_PORT": "5050"}),
    )
    monkeypatch.setattr(development, "activate_repository_gcloud", lambda **kwargs: None)
    monkeypatch.setattr(development.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(development.signal, "getsignal", lambda signum: previous[signum])
    monkeypatch.setattr(development.signal, "signal", fake_signal)
    monkeypatch.setattr(development.os, "killpg", lambda pid, signum: sent.append((pid, signum)))

    assert development.run_dev_server() == 7
    assert sent == [
        (8642, development.signal.SIGINT),
        (8642, development.signal.SIGTERM),
    ]
    assert restored == [development.signal.SIGINT, development.signal.SIGTERM]


# @matrix development : escalation exceptional-cleanup process-ownership
def test_run_dev_server_cleans_up_process_group_after_runner_failure(monkeypatch):
    from runner import development

    sent = []

    class FakeProcess:
        pid = 9753

        def __init__(self):
            self.waits = 0

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise RuntimeError("runner wait failed")
            if timeout == 5:
                raise development.subprocess.TimeoutExpired("flask", timeout)
            return -9

        def poll(self):
            return None

    monkeypatch.setattr(
        development,
        "SETTINGS",
        types.SimpleNamespace(dev_config={"SERVER_PORT": "5050"}),
    )
    monkeypatch.setattr(development, "activate_repository_gcloud", lambda **kwargs: None)
    monkeypatch.setattr(development.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(development.os, "killpg", lambda pid, signum: sent.append((pid, signum)))

    with pytest.raises(RuntimeError, match="runner wait failed"):
        development.run_dev_server()

    assert sent == [
        (9753, development.signal.SIGTERM),
        (9753, development.signal.SIGKILL),
    ]


# @matrix auth : adc explicit-command interactive runtime-identity
def test_run_py_auth_runs_interactive_human_adc_alignment(
    monkeypatch,
    capsys,
):
    calls = []
    monkeypatch.setattr(run, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        run,
        "activate_repository_gcloud",
        lambda **kwargs: calls.append(kwargs),
    )

    assert run.run_auth_command([]) == 0
    assert calls == [
        {
            "ensure_adc": True,
            "allow_runtime_adc": False,
            "allow_adc_login": True,
            "select_adc_target": True,
        }
    ]
    assert "Application Default Credentials are ready" in (
        capsys.readouterr().out
    )


# @matrix auth : adc explicit-command interactive runtime-identity
def test_run_py_auth_reports_alignment_failure(monkeypatch, capsys):
    monkeypatch.setattr(run, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        run,
        "activate_repository_gcloud",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("login failed")),
    )

    assert run.run_auth_command([]) == 1
    assert "Authentication failed: login failed" in capsys.readouterr().out


def test_run_py_test_strict_sets_env_and_removes_runner_arg(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 1357

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        calls.append(command)
        return FakeProcess()

    monkeypatch.delenv("STRICT_RELATION_LOADS", raising=False)
    monkeypatch.setattr(run, "activate_repository_gcloud", lambda **kwargs: None)
    monkeypatch.setattr(run.subprocess, "Popen", fake_popen)

    assert run.run_tests(["--strict", "unit"]) == 0

    assert os.environ["STRICT_RELATION_LOADS"] == "1"
    assert "--strict" not in calls[0]
    assert calls[0][-1] == "testing/tests_unit/"


def test_run_py_test_forwards_signals_to_pytest_process_group(monkeypatch):
    installed_handlers = {}
    restored_handlers = []
    previous_handlers = {
        run.signal.SIGINT: object(),
        run.signal.SIGTERM: object(),
    }
    sent_signals = []

    class FakeProcess:
        pid = 9753

        def wait(self):
            installed_handlers[run.signal.SIGINT](run.signal.SIGINT, None)
            installed_handlers[run.signal.SIGTERM](run.signal.SIGTERM, None)
            return 0

    def fake_signal(signum, handler):
        if handler is previous_handlers[signum]:
            restored_handlers.append(signum)
        else:
            installed_handlers[signum] = handler

    monkeypatch.setattr(
        run.subprocess,
        "Popen",
        lambda command, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(run, "activate_repository_gcloud", lambda **kwargs: None)
    monkeypatch.setattr(
        run.signal,
        "getsignal",
        lambda signum: previous_handlers[signum],
    )
    monkeypatch.setattr(run.signal, "signal", fake_signal)
    monkeypatch.setattr(
        run.os,
        "killpg",
        lambda pid, signum: sent_signals.append((pid, signum)),
    )

    assert run.run_tests(["unit"]) == 0

    assert sent_signals == [
        (9753, run.signal.SIGINT),
        (9753, run.signal.SIGTERM),
    ]
    assert restored_handlers == [run.signal.SIGINT, run.signal.SIGTERM]


# @pair setup:gcloud-token
def test_runner_gcloud_activation_uses_complete_saved_target(monkeypatch):
    from runner import adc as runner_adc
    from runner import gcloud as runner_gcloud

    calls = []
    settings = types.SimpleNamespace(
        APP={
            "RUNTIME_SERVICE_ACCOUNT_EMAIL": (
                "runtime@lagniappe-local-project.iam.gserviceaccount.com"
            ),
            "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": (
                "runtime@lagniappe-local-project.iam.gserviceaccount.com"
            ),
        },
        GCLOUD_CONFIG={
            "NAME": "lagniappe-local",
            "ACCOUNT": "owner@example.test",
            "PROJECT": "lagniappe-local-project",
        }
    )
    config_module = types.ModuleType("config")
    config_module.SETTINGS = settings
    monkeypatch.setattr(runner_gcloud, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        runner_gcloud,
        "config_gcloud",
        lambda: calls.append("activate"),
    )
    monkeypatch.setattr(
        runner_adc,
        "ensure_adc_target",
        lambda account, project, **kwargs: calls.append(
            ("adc", account, project, kwargs)
        ),
    )
    monkeypatch.setattr(
        runner_adc,
        "ensure_gcloud_source_login",
        lambda account, **kwargs: calls.append(("cli-token", account, kwargs)),
    )
    monkeypatch.setitem(sys.modules, "config", config_module)

    assert runner_gcloud.activate_repository_gcloud() is True
    assert runner_gcloud.activate_repository_gcloud(ensure_adc=True) is True
    assert (
        runner_gcloud.activate_repository_gcloud(
            ensure_adc=True,
            ensure_cli_token=True,
            allow_runtime_adc=True,
        )
        is True
    )
    assert calls == [
        "activate",
        "activate",
        (
            "adc",
            "owner@example.test",
            "lagniappe-local-project",
            {
                "allowed_principals": (),
                "select_gcloud_target": False,
            },
        ),
        "activate",
        ("cli-token", "owner@example.test", {"allow_login": False}),
        (
            "adc",
            "owner@example.test",
            "lagniappe-local-project",
            {
                "allowed_principals": (
                    "runtime@lagniappe-local-project.iam.gserviceaccount.com",
                    "runtime@lagniappe-local-project.iam.gserviceaccount.com",
                ),
                "select_gcloud_target": False,
            },
        ),
    ]


# @matrix auth : gcloud-token interactive refresh
def test_runner_gcloud_source_login_refreshes_stale_token(monkeypatch):
    from runner import adc as runner_adc

    commands = []
    token_checks = iter((1, 0))
    monkeypatch.setattr(runner_adc, "GCLOUD_CLI", "/usr/bin/gcloud")

    def run_command(command, **kwargs):
        commands.append((command, kwargs))
        if command[1:3] == ["auth", "print-access-token"]:
            return types.SimpleNamespace(
                returncode=next(token_checks),
                stdout="",
                stderr="",
            )
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner_adc, "run_command", run_command)

    runner_adc.ensure_gcloud_source_login(
        "owner@example.test",
        allow_login=True,
    )

    assert commands == [
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "print-access-token",
                "owner@example.test",
            ],
            {"check": False, "timeout": 60},
        ),
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "login",
                "owner@example.test",
                "--force",
            ],
            {
                "check": False,
                "capture_output": False,
                "timeout": 600,
            },
        ),
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "print-access-token",
                "owner@example.test",
            ],
            {"check": False, "timeout": 60},
        ),
    ]


# @matrix setup : gcloud-token safe-failure
def test_runner_gcloud_source_login_stops_before_authentication_by_default(
    monkeypatch,
):
    from runner import adc as runner_adc

    commands = []
    monkeypatch.setattr(runner_adc, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        runner_adc,
        "run_command",
        lambda command, **kwargs: commands.append((command, kwargs))
        or types.SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError) as error:
        runner_adc.ensure_gcloud_source_login("owner@example.test")

    message = str(error.value)
    assert "Setup stopped before making changes" in message
    assert "./setup.sh auth" in message
    assert "gcloud auth login" not in message
    assert commands == [
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "print-access-token",
                "owner@example.test",
            ],
            {"check": False, "timeout": 60},
        )
    ]


# @matrix development setup testing : adc identity project-identity
def test_runner_adc_identity_is_secret_free_and_project_bound():
    from runner import adc as runner_adc

    class Credentials:
        token = None
        quota_project_id = "lagniappe-local-project"

        def refresh(self, request):
            assert request == "request"
            self.token = "secret-access-token"

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"email": "owner@example.test"}

    identity = runner_adc.read_adc_identity(
        auth_default=lambda scopes: (
            Credentials(),
            "lagniappe-local-project",
        ),
        request_factory=lambda: "request",
        token_lookup=lambda url, **kwargs: Response(),
    )

    assert identity == {
        "state": "success",
        "principal": "owner@example.test",
        "project": "lagniappe-local-project",
        "quota_project": "lagniappe-local-project",
    }
    assert "secret-access-token" not in repr(identity)


# @matrix setup testing : adc automatic-activation identity project-identity quota-project
def test_runner_adc_alignment_reauthenticates_and_sets_quota_project(monkeypatch):
    from runner import adc as runner_adc

    identities = iter(
        [
            {
                "state": "success",
                "principal": "other@example.test",
                "project": "other-project",
                "quota_project": "other-project",
            },
            {
                "state": "success",
                "principal": "owner@example.test",
                "project": "lagniappe-local-project",
                "quota_project": "lagniappe-local-project",
            },
        ]
    )
    commands = []
    monkeypatch.setattr(runner_adc, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        runner_adc,
        "read_adc_identity",
        lambda: next(identities),
    )
    monkeypatch.setattr(
        runner_adc,
        "run_command",
        lambda command, **kwargs: commands.append((command, kwargs))
        or types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    identity = runner_adc.ensure_adc_target(
        "owner@example.test",
        "lagniappe-local-project",
        allow_login=True,
    )

    assert identity["principal"] == "owner@example.test"
    assert commands == [
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "application-default",
                "login",
                "owner@example.test",
                "--project=lagniappe-local-project",
            ],
            {
                "check": False,
                "capture_output": False,
                "timeout": 600,
            },
        ),
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "application-default",
                "set-quota-project",
                "lagniappe-local-project",
                "--quiet",
            ],
            {"check": False, "timeout": 60},
        ),
    ]


# @matrix auth : adc automatic-activation identity project-identity quota-project
def test_runner_adc_auth_selects_account_then_project_before_login(monkeypatch):
    from runner import adc as runner_adc

    identities = iter(
        [
            {
                "state": "success",
                "principal": "other@example.test",
                "project": "other-project",
                "quota_project": "other-project",
            },
            {
                "state": "success",
                "principal": "owner@example.test",
                "project": "lagniappe-local-project",
                "quota_project": "lagniappe-local-project",
            },
        ]
    )
    commands = []
    token_checks = iter((1, 0))
    monkeypatch.setattr(runner_adc, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        runner_adc,
        "read_adc_identity",
        lambda: next(identities),
    )

    def fake_run_command(command, **kwargs):
        commands.append((command, kwargs))
        source_login_check = command[1:4] == [
            "auth",
            "print-access-token",
            "owner@example.test",
        ]
        return types.SimpleNamespace(
            returncode=next(token_checks) if source_login_check else 0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(runner_adc, "run_command", fake_run_command)

    identity = runner_adc.ensure_adc_target(
        "owner@example.test",
        "lagniappe-local-project",
        allow_login=True,
        select_gcloud_target=True,
    )

    assert identity["principal"] == "owner@example.test"
    assert commands == [
        (
            [
                "/usr/bin/gcloud",
                "config",
                "set",
                "account",
                "owner@example.test",
            ],
            {"timeout": 60},
        ),
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "print-access-token",
                "owner@example.test",
            ],
            {"check": False, "timeout": 60},
        ),
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "login",
                "owner@example.test",
                "--force",
            ],
            {
                "check": False,
                "capture_output": False,
                "timeout": 600,
            },
        ),
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "print-access-token",
                "owner@example.test",
            ],
            {"check": False, "timeout": 60},
        ),
        (
            [
                "/usr/bin/gcloud",
                "config",
                "set",
                "project",
                "lagniappe-local-project",
            ],
            {"timeout": 60},
        ),
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "application-default",
                "login",
                "owner@example.test",
                "--project=lagniappe-local-project",
            ],
            {
                "check": False,
                "capture_output": False,
                "timeout": 600,
            },
        ),
        (
            [
                "/usr/bin/gcloud",
                "auth",
                "application-default",
                "set-quota-project",
                "lagniappe-local-project",
                "--quiet",
            ],
            {"check": False, "timeout": 60},
        ),
    ]


# @matrix development testing : adc automatic-activation identity project-identity quota-project
@pytest.mark.parametrize(
    "identity",
    [
        {
            "state": "success",
            "principal": "other@example.test",
            "project": "lagniappe-local-project",
            "quota_project": "lagniappe-local-project",
        },
        {
            "state": "success",
            "principal": "owner@example.test",
            "project": "lagniappe-local-project",
            "quota_project": "other-project",
        },
    ],
)
def test_runner_local_adc_mismatch_directs_to_auth_command(
    monkeypatch,
    identity,
):
    from runner import adc as runner_adc

    monkeypatch.setattr(runner_adc, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        runner_adc,
        "read_adc_identity",
        lambda: identity,
    )
    monkeypatch.setattr(
        runner_adc,
        "run_command",
        lambda *args, **kwargs: pytest.fail(
            "noninteractive ADC checks must not mutate authentication"
        ),
    )

    with pytest.raises(RuntimeError, match="run.py auth"):
        runner_adc.ensure_adc_target(
            "owner@example.test",
            "lagniappe-local-project",
            allowed_principals=(
                "runtime@lagniappe-local-project.iam.gserviceaccount.com",
            ),
            allow_login=False,
        )


# @matrix setup testing : adc automatic-activation quota-project
def test_runner_adc_alignment_updates_only_stale_quota_project(monkeypatch):
    from runner import adc as runner_adc

    identities = iter(
        [
            {
                "state": "success",
                "principal": "owner@example.test",
                "project": "lagniappe-local-project",
                "quota_project": "other-project",
            },
            {
                "state": "success",
                "principal": "owner@example.test",
                "project": "lagniappe-local-project",
                "quota_project": "lagniappe-local-project",
            },
        ]
    )
    commands = []
    monkeypatch.setattr(runner_adc, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        runner_adc,
        "read_adc_identity",
        lambda: next(identities),
    )
    monkeypatch.setattr(
        runner_adc,
        "run_command",
        lambda command, **kwargs: commands.append(command)
        or types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    runner_adc.ensure_adc_target(
        "owner@example.test",
        "lagniappe-local-project",
        allow_login=False,
    )

    assert commands == [
        [
            "/usr/bin/gcloud",
            "auth",
            "application-default",
            "set-quota-project",
            "lagniappe-local-project",
            "--quiet",
        ]
    ]


# @matrix auth development setup testing : activation gcloud-config unconfigured
def test_runner_gcloud_activation_skips_unconfigured_repository(monkeypatch):
    from runner import gcloud as runner_gcloud

    config_module = types.ModuleType("config")
    config_module.SETTINGS = types.SimpleNamespace(GCLOUD_CONFIG={})
    monkeypatch.setitem(sys.modules, "config", config_module)

    assert runner_gcloud.activate_repository_gcloud() is False


# @matrix auth development setup testing : activation gcloud-config validation
def test_runner_gcloud_activation_rejects_partial_saved_target(monkeypatch):
    from runner import gcloud as runner_gcloud

    config_module = types.ModuleType("config")
    config_module.SETTINGS = types.SimpleNamespace(
        GCLOUD_CONFIG={
            "ACCOUNT": "owner@example.test",
            "PROJECT": "lagniappe-local-project",
        }
    )
    monkeypatch.setitem(sys.modules, "config", config_module)

    with pytest.raises(RuntimeError, match="missing: NAME"):
        runner_gcloud.activate_repository_gcloud()


def test_run_py_upgrade_without_branch_runs_dependency_upgrade(monkeypatch):
    config_module = types.ModuleType("config")
    config_module.__path__ = ["config"]
    upgrade_module = types.ModuleType("runner.upgrade")
    upgrade_module.upgrade_all = lambda: 4

    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "runner.upgrade", upgrade_module)

    assert run.run_upgrade_command([]) == 4


def test_run_py_upgrade_rejects_removed_software_upgrade_branch():
    with pytest.raises(SystemExit, match="2"):
        run.run_upgrade_command(["--branch", "release/candidate"])


def _git(repo: Path, *args: str):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _release_frontend_contract():
    return {
        "schema": 1,
        "source_roots": ["src/script"],
        "source_files": [
            "build/publication.json",
            "package-lock.json",
            "package.json",
        ],
        "exclusive_artifact_roots": ["lagniappe/web/static/chunks"],
        "required_artifacts": [
            "lagniappe/web/static/script.js",
            "lagniappe/web/static/sw.js",
        ],
        "required_artifact_prefixes": ["lagniappe/web/static/"],
    }


def _write_release_frontend_metadata(repo, *, build_id, mode, version):
    contract = _release_frontend_contract()
    contract_path = repo / "build/publication.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(f"{json.dumps(contract, sort_keys=True)}\n")

    source_paths = set()
    for relative_root in contract["source_roots"]:
        source_paths.update(
            path.relative_to(repo).as_posix()
            for path in (repo / relative_root).rglob("*")
            if path.is_file()
        )
    source_paths.update(contract["source_files"])
    source_digest = hashlib.sha256(b"frontend-source-v1\0")
    for relative in sorted(source_paths):
        source_digest.update(relative.encode())
        source_digest.update(b"\0")
        source_digest.update((repo / relative).read_bytes())
        source_digest.update(b"\0")

    artifacts = []
    for relative in contract["required_artifacts"]:
        content = (repo / relative).read_bytes()
        artifacts.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )
    metadata = {
        "schema": 1,
        "build_id": build_id,
        "mode": mode,
        "version": version,
        "source": {"sha256": source_digest.hexdigest()},
        "artifacts": artifacts,
    }
    metadata_path = repo / "lagniappe/web/static/build.json"
    metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n")


def _release_check_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Release Check Test")
    _git(repo, "config", "user.email", "release-check@example.test")

    files = {
        ".gitignore": "config/files/\nlagniappe.yaml\nindex.yaml\n",
        "runner/__init__.py": "",
        "runner/context.py": (
            (Path(run.__file__).parent / "runner" / "context.py").read_text(
                encoding="utf-8"
            )
        ),
        "runner/process.py": (
            (Path(run.__file__).parent / "runner" / "process.py").read_text(
                encoding="utf-8"
            )
        ),
        "runner/gcloud.py": (
            (Path(run.__file__).parent / "runner" / "gcloud.py").read_text(
                encoding="utf-8"
            )
        ),
        "runner/frontend_build.py": (
            (Path(run.__file__).parent / "runner" / "frontend_build.py").read_text(
                encoding="utf-8"
            )
        ),
        "runner/pytest_routing.py": (
            (
                Path(run.__file__).parent / "runner" / "pytest_routing.py"
            ).read_text(encoding="utf-8")
        ),
        "run.py": Path(run.__file__).read_text(encoding="utf-8"),
        "package.json": '{"name": "lagniappe", "version": "0.1.0"}\n',
        "package-lock.json": (
            '{"name": "lagniappe", "version": "0.1.0", '
            '"packages": {"": {"name": "lagniappe", "version": "0.1.0"}}}\n'
        ),
        "documentation/releases/0.1.0.md": (
            "# Version 0.1.0\n\n- Initial test release.\n"
        ),
        "src/script/example.mjs": "export const value = 1;\n",
        "lagniappe/web/static/script.js": "built-main\n",
        "lagniappe/web/static/sw.js": 'const BUILD_ID = "base1234";\n',
        "lagniappe/web/start/styles/icons.py": "ICONS = {}\n",
        "lagniappe/web/start/styles/styles.py": "STYLES = {}\n",
        "config/constants.py": 'SENTRY_DSN = "test"\nBUILD_ID = "base1234"\n',
    }
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    _write_release_frontend_metadata(
        repo,
        build_id="base1234",
        mode="production",
        version="0.1.0",
    )

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Base")
    _git(repo, "switch", "-c", "next/0.2.0")
    return repo


def _write_release_candidate(
    repo: Path,
    *,
    mode: str = "production",
    build_id: str = "b1234567",
):
    updates = {
        "package.json": '{"name": "lagniappe", "version": "0.2.0"}\n',
        "package-lock.json": (
            '{"name": "lagniappe", "version": "0.2.0", '
            '"packages": {"": {"name": "lagniappe", "version": "0.2.0"}}}\n'
        ),
        "documentation/releases/0.2.0.md": (
            "# Version 0.2.0\n\n- Added the release workflow.\n"
        ),
        "lagniappe/web/static/sw.js": f'const BUILD_ID = "{build_id}";\n',
        "config/constants.py": (f'SENTRY_DSN = "test"\nBUILD_ID = "{build_id}"\n'),
    }
    for relative, content in updates.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _write_release_frontend_metadata(
        repo,
        build_id=build_id,
        mode=mode,
        version="0.2.0",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Prepare release")


def test_main_release_workflow_contract():
    repository = Path(run.__file__).parent
    assert not (repository / ".github/workflows/release.yml").exists()

    workflow_path = repository / ".github/workflows/hosted-e2e.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    assert workflow["name"] == "Hosted release validation"
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    assert workflow["on"]["pull_request"]["types"] == ["opened", "reopened"]
    assert workflow["on"]["push"]["branches"] == ["next/**", "hotfix/**"]
    assert list(workflow["jobs"]) == ["request", "execute", "quality", "attest"]
    assert workflow["jobs"]["request"]["permissions"] == {
        "pull-requests": "read"
    }
    assert "Source quality and traceability" in workflow["jobs"]["quality"]["name"]
    assert "Manual dispatch guard" in workflow["jobs"]["quality"]["name"]
    assert workflow["jobs"]["attest"]["permissions"] == {"statuses": "write"}
    assert workflow["jobs"]["attest"]["needs"] == "quality"
    assert '"next/**"' in workflow_text
    assert "next/*|hotfix/*" in workflow_text
    assert "npm run check" in workflow_text
    assert "ruff check ." in workflow_text
    assert "run.py traceability" not in workflow_text
    assert 'release-check --base "$RELEASE_BASE_REF"' in workflow_text
    assert "pr-check" not in workflow_text
    assert "pr-clean" not in workflow_text


# @pair release:delivery-tree
def test_run_py_release_check_accepts_complete_release(tmp_path, capsys):
    repo = _release_check_repository(tmp_path)
    _write_release_candidate(repo)

    assert run.run_release_check_command(["--base", "main"], repo_root=repo) == 0
    (repo / "lagniappe/web/static/build.json").write_text(
        '{"build_id": "unstaged", "mode": "development", '
        '"version": "unreleased"}\n',
        encoding="utf-8",
    )
    assert run.run_release_check_command(["--base", "main"], repo_root=repo) == 0
    result = subprocess.run(
        [
            sys.executable,
            str(repo / "run.py"),
            "release-check",
            "--base",
            "main",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Release check passed against main" in result.stdout
    assert "Release check passed against main" in capsys.readouterr().out


# @matrix release : build-mode delivery-tree
def test_run_py_release_check_rejects_development_build(tmp_path, capsys):
    repo = _release_check_repository(tmp_path)
    _write_release_candidate(repo, mode="development")

    assert run.run_release_check_command(["--base", "main"], repo_root=repo) == 1
    output = capsys.readouterr().out
    assert "must identify a production build" in output
    assert "was not changed by a fresh production build" not in output
    assert "does not contain a newly generated BUILD_ID" not in output


# @pair release:delivery-tree
def test_run_py_release_check_rejects_incomplete_release(tmp_path, capsys):
    repo = _release_check_repository(tmp_path)
    (repo / "package.json").write_text(
        '{"name": "lagniappe", "version": "0.2"}\n',
        encoding="utf-8",
    )
    (repo / "lagniappe/web/static/build.json").write_text(
        '{"build_id": "base1234", "mode": "development", '
        '"version": "0.1.0"}\n',
        encoding="utf-8",
    )
    local_config = repo / "config/files/lagniappe_settings.yaml"
    local_config.parent.mkdir(parents=True, exist_ok=True)
    local_config.write_text("SECRET_KEY: do-not-publish\n", encoding="utf-8")
    _git(repo, "add", "package.json", "lagniappe/web/static/build.json")
    _git(repo, "add", "-f", "config/files/lagniappe_settings.yaml")
    _git(repo, "commit", "-m", "Incomplete release")

    assert run.run_release_check_command(["--base", "main"], repo_root=repo) == 1
    output = capsys.readouterr().out
    assert "Installation-local files are present" in output
    assert "package.json version must use stable X.Y.Z form" in output
    assert "was not changed by a fresh production build" in output
    assert "does not contain a newly generated BUILD_ID" in output
    assert "must identify a production build" in output


# @pair version:cli-routing
@pytest.mark.parametrize(
    ("settings_exist", "settings_version", "expected_version"),
    [
        (False, None, "0.2.0"),
        (True, "0.1.9", "0.1.9"),
    ],
)
def test_run_py_version_show_uses_package_only_before_generated_settings_exist(
    monkeypatch,
    capsys,
    settings_exist,
    settings_version,
    expected_version,
):
    settings = types.SimpleNamespace(
        APP={"VERSION": settings_version} if settings_version else {},
        NODE={"version": "0.2.0"},
    )
    app_settings_file = types.SimpleNamespace(exists=lambda: settings_exist)
    config_module = types.ModuleType("config")
    config_module.SETTINGS = settings
    config_module.File = types.SimpleNamespace(APP_SETTINGS_YAML=app_settings_file)
    config_module.constants = types.SimpleNamespace(BUILD_ID=None)
    monkeypatch.setitem(sys.modules, "config", config_module)

    assert run.run_version_command(["show"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"VERSION: {expected_version}",
        "package.json: 0.2.0",
        f"BUILD_ID: {expected_version}",
    ]


# @pair version:cli-routing
def test_run_py_version_note_appends_concise_release_entry(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run, "RELEASES_DIR", tmp_path / "documentation" / "releases")

    assert (
        run.run_version_command(
            ["note", "Fixed category ownership sync", "--version", "1.25"]
        )
        == 0
    )

    path = tmp_path / "documentation" / "releases" / "1.25.md"
    assert path.read_text() == "# Version 1.25\n\n- Fixed category ownership sync\n"
    assert "Added version note" in capsys.readouterr().out


# @pair version:cli-routing
def test_run_py_version_set_updates_package_settings_and_release_file(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(run, "RELEASES_DIR", tmp_path / "documentation" / "releases")
    reporting_markdown = tmp_path / "ERROR_REPORTING_PRIVACY.md"
    reporting_template = (
        tmp_path / "lagniappe/web/templates/home/reporting_privacy.html"
    )
    reporting_template.parent.mkdir(parents=True)
    reporting_markdown.write_text(
        "# Notice\n\n"
        "**Applies to:** Lagniappe 1.24  \n"
        "**Effective date:** July 26, 2026  \n",
        encoding="utf-8",
    )
    reporting_template.write_text(
        "<p>\n"
        "  Applies to: Lagniappe 1.24\n"
        "  <br>\n"
        "  Effective date: July 26, 2026\n"
        "</p>\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run, "REPORTING_PRIVACY_MARKDOWN_PATH", reporting_markdown)
    monkeypatch.setattr(run, "REPORTING_PRIVACY_TEMPLATE_PATH", reporting_template)
    settings = types.SimpleNamespace(
        NODE={"version": "1.24"},
        APP={"VERSION": "1.24", "BUILD_ID": "build1234"},
    )
    saved = {}

    class FakeFileRef:
        def __init__(self, key):
            self.key = key

        def save(self, data):
            saved[self.key] = dict(data)

    config_module = types.ModuleType("config")
    config_module.SETTINGS = settings
    config_module.File = types.SimpleNamespace(
        PACKAGE_JSON=FakeFileRef("package"),
        APP_SETTINGS_YAML=FakeFileRef("settings"),
    )

    def save_settings(*file_refs):
        for file_ref in file_refs:
            data = settings.NODE if file_ref.key == "package" else settings.APP
            file_ref.save(data)

    settings.save = save_settings
    deploy_module = types.ModuleType("runner.deploy")
    lock_versions = []
    deploy_module.update_package_lock_version = lambda version: lock_versions.append(version)

    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "runner.deploy", deploy_module)

    assert run.run_version_command(["set", "1.25"]) == 0

    assert settings.NODE["version"] == "1.25"
    assert settings.APP["VERSION"] == "1.25"
    assert "BUILD_ID" not in settings.APP
    assert saved == {
        "package": {"version": "1.25"},
        "settings": {"VERSION": "1.25"},
    }
    assert lock_versions == ["1.25"]
    assert (tmp_path / "documentation" / "releases" / "1.25.md").read_text() == (
        "# Version 1.25\n\n"
    )
    assert "**Applies to:** Lagniappe 1.25  " in reporting_markdown.read_text()
    assert "**Effective date:** July 26, 2026  " in reporting_markdown.read_text()
    assert "  Applies to: Lagniappe 1.25\n" in reporting_template.read_text()
    assert "  Effective date: July 26, 2026\n" in reporting_template.read_text()
    assert "VERSION set to 1.25" in capsys.readouterr().out
