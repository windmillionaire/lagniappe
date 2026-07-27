"""Tooling tests for the ``run.py test`` command wrapper."""

import json
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

import run
from testing.utility import traceability_common, traceability_results

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
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n")
    evidence = tmp_path / traceability_common.LATEST_TEST_RUN
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"tests": {}}\n')

    def fake_git(repo_root, *args, **kwargs):
        del repo_root, kwargs
        stdout = (
            b".github/workflows/ci.yml\0"
            b"src/example.py\0"
            b"testing/evidence/latest.json\0"
            if args == ("ls-files", "-z")
            else b""
        )
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(traceability_common, "_git", fake_git)

    fingerprints = traceability_common.behavior_path_fingerprints(tmp_path)

    assert "src/example.py" in fingerprints
    assert ".github/workflows/ci.yml" not in fingerprints
    assert "testing/evidence/latest.json" not in fingerprints


def test_traceability_result_plugin_merges_focused_results_without_session_history(
    monkeypatch, tmp_path
):
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


def test_traceability_result_plugin_migrates_legacy_snapshot_maps(
    monkeypatch, tmp_path
):
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
        '"""first module note"""\n# @features old\ndef value():\n    """old note"""\n    return 1\n'
    )
    python_before = traceability_common.behavior_file_fingerprint(python_path)
    python_path.write_text(
        '"""new module note"""\n# @features new\ndef value():\n    """new note"""\n    return 1\n'
    )

    javascript_path = tmp_path / "sample.mjs"
    javascript_path.write_text(
        "/** @features old */\nexport function value() { return 'https://a.test'; }\n"
    )
    javascript_before = traceability_common.behavior_file_fingerprint(javascript_path)
    javascript_path.write_text(
        "// @features new\nexport function value() { return 'https://a.test'; }\n"
    )

    assert traceability_common.behavior_file_fingerprint(python_path) == python_before
    assert (
        traceability_common.behavior_file_fingerprint(javascript_path)
        == javascript_before
    )


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


def test_normalize_test_args_expands_supported_suite_aliases_only():
    assert run.normalize_test_args(["unit"]) == (
        False,
        ["testing/tests_unit/"],
    )
    assert run.normalize_test_args(["e2e"]) == (
        False,
        ["testing/tests_e2e/"],
    )
    assert run.normalize_test_args(["js"]) == (
        False,
        ["testing/tests_js/"],
    )
    assert run.normalize_test_args(["tooling"]) == (
        False,
        ["testing/tests_tooling/"],
    )
    assert run.normalize_test_args(["setup"]) == (
        False,
        run.TEST_SUITE_ALIASES["setup"],
    )
    assert all("setup_drift" not in path for path in run.TEST_SUITE_ALIASES["setup"])
    opt_in_targets = {
        target for targets in run.SETUP_OPT_IN_TESTS.values() for target in targets
    }
    assert opt_in_targets.isdisjoint(run.TEST_SUITE_ALIASES["setup"])


# @features testing setup
# @dimensions cli-routing pytest-markers opt-in
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
def test_normalize_test_args_adds_setup_opt_in_targets_without_filenames(
    marker_expression, expected_markers
):
    _, normalized = run.normalize_test_args(["setup", "-m", marker_expression])

    expected_targets = [
        target
        for marker in expected_markers
        for target in run.SETUP_OPT_IN_TESTS[marker]
    ]
    assert normalized[: len(run.TEST_SUITE_ALIASES["setup"])] == (
        run.TEST_SUITE_ALIASES["setup"]
    )
    assert normalized[
        len(run.TEST_SUITE_ALIASES["setup"]) : -2
    ] == expected_targets
    assert normalized[-2] == "-m"
    assert normalized[-1] == (
        "setup_drift or setup_provider"
        if marker_expression == "provider"
        else marker_expression
    )


def test_normalize_test_args_preserves_real_nodeids_and_drops_redundant_scope():
    target = "testing/tests_tooling/test_007_run_py_test_command.py::test_example"

    assert run.normalize_test_args([target]) == (False, [target])
    assert run.normalize_test_args(["tooling", target, "--tb=short"]) == (
        False,
        [target, "--tb=short"],
    )


def test_normalize_test_args_handles_strict_and_pytest_separator():
    assert run.normalize_test_args(["--strict", "unit"]) == (
        True,
        ["testing/tests_unit/"],
    )
    assert run.normalize_test_args(["--", "-k", "category"]) == (
        False,
        ["-k", "category"],
    )
    assert run.normalize_test_args(["-k", "unit"]) == (
        False,
        ["-k", "unit"],
    )


def test_normalize_test_args_does_not_expand_legacy_shorthand():
    legacy_args = [
        "003b",
        "003b::test_preview_panel",
        "home",
        "pages",
        "-unit",
        "-e2e",
        "-js",
        "-tooling",
    ]

    assert run.normalize_test_args(legacy_args) == (False, legacy_args)


def test_configure_test_environment_prepares_frontend_only_for_e2e(monkeypatch):
    calls = []
    config_module = types.ModuleType("config")
    config_module.__path__ = ["config"]
    testing_module = types.ModuleType("runner.testing")
    testing_module.ensure_test_frontend_bundle = lambda: calls.append("bundle")
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "runner.testing", testing_module)

    run.configure_test_environment(["testing/tests_unit/"])
    assert calls == []

    run.configure_test_environment(
        ["testing/tests_e2e/001_site/test_001d_offline.py::test_offline"]
    )
    run.configure_test_environment([])

    assert calls == ["bundle", "bundle"]


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

    assert (
        run.run_tests(
            ["tooling", "testing/tests_tooling/test_007_run_py_test_command.py"]
        )
        == 3
    )

    command, kwargs = calls[0]
    assert command == [
        run.sys.executable,
        "-m",
        "pytest",
        "-c",
        "testing/pytest.ini",
        "-p",
        "testing.utility.traceability_results",
        "testing/tests_tooling/test_007_run_py_test_command.py",
    ]
    assert kwargs == {
        "cwd": run.REPOSITORY_ROOT,
        "start_new_session": True,
    }
    assert "Running:" in capsys.readouterr().out
    assert os.environ["LAGNIAPPE_TEST_COMMAND"] == '["outer", "test"]'


def test_run_py_e2e_aligns_adc_before_pytest(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 8642

        def wait(self):
            return 0

    monkeypatch.setattr(
        run,
        "configure_test_environment",
        lambda args: calls.append(("environment", args)),
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

    assert run.run_tests(["e2e"]) == 0
    assert calls[:2] == [
        ("environment", ["testing/tests_e2e/"]),
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
    monkeypatch.setattr(run, "configure_test_environment", lambda args: None)
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


# @features development
# @dimensions gcloud-config adc launch-order
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
    monkeypatch.setattr(
        development.subprocess,
        "run",
        lambda command, **kwargs: calls.append(
            ("flask", command, kwargs)
        )
        or types.SimpleNamespace(returncode=0),
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
                "timeout": 900,
            },
        ),
    ]


# @features development
# @dimensions gcloud-config adc launch-order noninteractive
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
        "run",
        lambda *args, **kwargs: pytest.fail("Flask must not start"),
    )

    assert development.run_dev_server() == 1
    output = capsys.readouterr().out
    assert "Development server startup stopped:" in output
    assert "run.py auth" in output


# @features auth
# @dimensions adc runtime-identity interactive explicit-command
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


# @features auth
# @dimensions adc runtime-identity interactive explicit-command
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


# @features setup testing development auth
# @dimensions gcloud-config activation
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
    monkeypatch.setitem(sys.modules, "config", config_module)

    assert runner_gcloud.activate_repository_gcloud() is True
    assert runner_gcloud.activate_repository_gcloud(ensure_adc=True) is True
    assert (
        runner_gcloud.activate_repository_gcloud(
            ensure_adc=True,
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


# @pairs setup:adc setup:identity setup:project-identity
# @pairs testing:adc testing:identity testing:project-identity
# @pairs development:adc development:identity development:project-identity
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


# @pairs setup:adc setup:identity setup:project-identity setup:automatic-activation setup:quota-project
# @pairs testing:adc testing:identity testing:project-identity testing:automatic-activation testing:quota-project
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


# @pairs auth:adc auth:identity auth:project-identity auth:automatic-activation auth:quota-project
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
    monkeypatch.setattr(runner_adc, "GCLOUD_CLI", "/usr/bin/gcloud")
    monkeypatch.setattr(
        runner_adc,
        "read_adc_identity",
        lambda: next(identities),
    )

    def fake_run_command(command, **kwargs):
        commands.append((command, kwargs))
        stale_source_login = command[1:4] == [
            "auth",
            "print-access-token",
            "owner@example.test",
        ]
        return types.SimpleNamespace(
            returncode=1 if stale_source_login else 0,
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


# @pairs testing:adc testing:identity testing:project-identity
# @pairs development:adc development:identity development:project-identity
# @pairs testing:automatic-activation testing:quota-project
# @pairs development:automatic-activation development:quota-project
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


# @pairs setup:adc setup:automatic-activation setup:quota-project
# @pairs testing:adc testing:automatic-activation testing:quota-project
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


# @features setup testing development auth
# @dimensions gcloud-config activation unconfigured
def test_runner_gcloud_activation_skips_unconfigured_repository(monkeypatch):
    from runner import gcloud as runner_gcloud

    config_module = types.ModuleType("config")
    config_module.SETTINGS = types.SimpleNamespace(GCLOUD_CONFIG={})
    monkeypatch.setitem(sys.modules, "config", config_module)

    assert runner_gcloud.activate_repository_gcloud() is False


# @features setup testing development auth
# @dimensions gcloud-config activation validation
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


def _pr_check_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "PR Check Test")
    _git(repo, "config", "user.email", "pr-check@example.test")

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
        "run.py": Path(run.__file__).read_text(encoding="utf-8"),
        "src/script/example.mjs": "export const value = 1;\n",
        "lagniappe/web/static/script.js": "built-main\n",
        "lagniappe/web/start/styles/icons.py": "ICONS = {}\n",
        "lagniappe/web/start/styles/styles.py": "STYLES = {}\n",
        "config/constants.py": 'SENTRY_DSN = "test"\nBUILD_ID = "base1234"\n',
    }
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Base")
    _git(repo, "switch", "-c", "feature")
    return repo


def test_run_py_pr_check_allows_authored_source_only(tmp_path):
    repo = _pr_check_repository(tmp_path)
    source = repo / "src/script/example.mjs"
    source.write_text("export const value = 2;\n", encoding="utf-8")
    _git(repo, "add", str(source.relative_to(repo)))
    _git(repo, "commit", "-m", "Change source")

    result = subprocess.run(
        [sys.executable, str(repo / "run.py"), "pr-check"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "check passed against main" in result.stdout


def test_run_py_pr_check_rejects_committed_static_output(tmp_path, capsys):
    repo = _pr_check_repository(tmp_path)
    static = repo / "lagniappe/web/static/script.js"
    static.write_text("contributor-build\n", encoding="utf-8")
    _git(repo, "add", str(static.relative_to(repo)))
    _git(repo, "commit", "-m", "Commit contributor build")

    assert run.run_pr_check_command(["--base", "main"], repo_root=repo) == 1
    output = capsys.readouterr().out
    assert "lagniappe/web/static/script.js" in output
    assert "maintainer will apply the source to main" in output


def test_run_py_pr_check_rejects_build_id_and_staged_generated_files(
    tmp_path, capsys
):
    repo = _pr_check_repository(tmp_path)
    constants = repo / "config/constants.py"
    constants.write_text(
        'SENTRY_DSN = "test"\nBUILD_ID = "contributor-build"\n',
        encoding="utf-8",
    )
    icons = repo / "lagniappe/web/start/styles/icons.py"
    icons.write_text('ICONS = {"changed": True}\n', encoding="utf-8")
    _git(repo, "add", str(icons.relative_to(repo)))
    chunk = repo / "lagniappe/web/static/chunks/contributor.js"
    chunk.parent.mkdir(parents=True)
    chunk.write_text("untracked chunk\n", encoding="utf-8")
    _git(
        repo,
        "add",
        str(constants.relative_to(repo)),
        str(chunk.relative_to(repo)),
    )

    assert run.run_pr_check_command(["--base", "main"], repo_root=repo) == 1
    output = capsys.readouterr().out
    assert "config/constants.py (BUILD_ID)" in output
    assert "lagniappe/web/start/styles/icons.py" in output
    assert "lagniappe/web/static/chunks/contributor.js" in output


def test_run_py_pr_clean_restores_generated_output_and_keeps_authored_changes(
    tmp_path, capsys
):
    repo = _pr_check_repository(tmp_path)
    source = repo / "src/script/example.mjs"
    source.write_text("export const value = 2;\n", encoding="utf-8")
    static = repo / "lagniappe/web/static/script.js"
    static.write_text("contributor-build\n", encoding="utf-8")
    icons = repo / "lagniappe/web/start/styles/icons.py"
    icons.write_text('ICONS = {"changed": True}\n', encoding="utf-8")
    chunk = repo / "lagniappe/web/static/chunks/contributor.js"
    chunk.parent.mkdir(parents=True)
    chunk.write_text("local generated chunk\n", encoding="utf-8")
    constants = repo / "config/constants.py"
    constants.write_text(
        'SENTRY_DSN = "test"\n'
        'BUILD_ID = "contributor-build"\n'
        "FEATURE_FLAG = True\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")

    assert run.run_pr_clean_command(["--base", "main"], repo_root=repo) == 0

    assert static.read_text(encoding="utf-8") == "built-main\n"
    assert icons.read_text(encoding="utf-8") == "ICONS = {}\n"
    assert not chunk.exists()
    assert constants.read_text(encoding="utf-8") == (
        'SENTRY_DSN = "test"\nBUILD_ID = "base1234"\nFEATURE_FLAG = True\n'
    )

    staged = set(_git(repo, "diff", "--cached", "--name-only", "main").stdout.split())
    assert "src/script/example.mjs" in staged
    assert "config/constants.py" in staged
    assert "lagniappe/web/static/script.js" not in staged
    assert "lagniappe/web/static/chunks/contributor.js" not in staged
    assert "lagniappe/web/start/styles/icons.py" not in staged
    assert run.run_pr_check_command(["--base", "main"], repo_root=repo) == 0
    assert "Restored generated artifacts" in capsys.readouterr().out


def test_run_py_pr_clean_restores_unstaged_generated_worktree(tmp_path, capsys):
    repo = _pr_check_repository(tmp_path)
    source = repo / "src/script/example.mjs"
    source.write_text("export const value = 2;\n", encoding="utf-8")
    static = repo / "lagniappe/web/static/script.js"
    static.write_text("local development build\n", encoding="utf-8")
    chunk = repo / "lagniappe/web/static/chunks/local-only.js"
    chunk.parent.mkdir(parents=True)
    chunk.write_text("local generated chunk\n", encoding="utf-8")

    assert run.run_pr_clean_command(["--base", "main"], repo_root=repo) == 0

    assert source.read_text(encoding="utf-8") == "export const value = 2;\n"
    assert static.read_text(encoding="utf-8") == "built-main\n"
    assert not chunk.exists()
    changed = _git(repo, "status", "--short").stdout.splitlines()
    assert changed == [" M src/script/example.mjs"]
    output = capsys.readouterr().out
    assert "lagniappe/web/static/script.js" in output
    assert "lagniappe/web/static/chunks/local-only.js" in output


def test_run_py_pr_clean_keep_build_only_cleans_index(tmp_path, capsys):
    repo = _pr_check_repository(tmp_path)
    static = repo / "lagniappe/web/static/script.js"
    static.write_text("local development build\n", encoding="utf-8")
    _git(repo, "add", str(static.relative_to(repo)))

    assert (
        run.run_pr_clean_command(
            ["--base", "main", "--keep-build"],
            repo_root=repo,
        )
        == 0
    )

    assert static.read_text(encoding="utf-8") == "local development build\n"
    assert _git(repo, "diff", "--cached", "--name-only").stdout == ""
    assert "remain in the working tree" in capsys.readouterr().out


def test_run_py_pr_clean_stages_reversal_of_committed_generated_output(
    tmp_path, capsys
):
    repo = _pr_check_repository(tmp_path)
    static = repo / "lagniappe/web/static/script.js"
    static.write_text("committed-contributor-build\n", encoding="utf-8")
    _git(repo, "add", str(static.relative_to(repo)))
    _git(repo, "commit", "-m", "Commit contributor build")

    assert run.run_pr_clean_command(["--base", "main"], repo_root=repo) == 0

    assert static.read_text(encoding="utf-8") == "built-main\n"
    staged = _git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
    assert staged == ["lagniappe/web/static/script.js"]
    assert run.run_pr_check_command(["--base", "main"], repo_root=repo) == 0
    assert "commit the staged cleanup before pushing" in capsys.readouterr().out


def test_run_py_pr_check_and_clean_exclude_installation_config(tmp_path, capsys):
    repo = _pr_check_repository(tmp_path)
    installation_files = {
        "config/files/lagniappe_settings.yaml": "SECRET_KEY: local-secret\n",
        "config/files/lagniappe_dev.yaml": "SERVER_PORT: 5050\n",
        "lagniappe.yaml": "runtime: python314\n",
        "index.yaml": "indexes: []\n",
    }
    for relative, content in installation_files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-f", *installation_files)

    assert run.run_pr_check_command(["--base", "main"], repo_root=repo) == 1
    failed_output = capsys.readouterr().out
    for relative in installation_files:
        assert relative in failed_output

    assert run.run_pr_clean_command(["--base", "main"], repo_root=repo) == 0
    cleaned_output = capsys.readouterr().out
    for relative, content in installation_files.items():
        assert relative in cleaned_output
        assert (repo / relative).read_text(encoding="utf-8") == content

    staged = _git(repo, "diff", "--cached", "--name-only", "main").stdout
    assert staged == ""
    assert run.run_pr_check_command(["--base", "main"], repo_root=repo) == 0


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
