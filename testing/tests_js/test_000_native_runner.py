"""Exercise the actual Node boundary; Python-only protocol tests live in tooling."""

import shutil
import subprocess
import sys

import pytest

from testing.utility import native_js


FIXTURES = native_js.REPO_ROOT / native_js.JS_HELPERS / "fixtures"


@pytest.mark.parametrize(
    "name, detail",
    [
        ("test_fail", "expected"),
        ("test_missing_result", "matching results 0"),
        ("test_import_error", "does-not-exist"),
        ("test_unhandled_error", "late exception"),
        ("test_caught_network", "Unaccounted network"),
    ],
)
def test_native_runner_reports_assertions_and_infrastructure_failures(name, detail):
    with pytest.raises(native_js.JavaScriptFailure, match=detail):
        native_js.run_case(FIXTURES / "cases.mjs", name)


def test_native_runner_isolates_cases_and_console_output():
    for name in ("test_pass", "test_write_global", "test_clean_global"):
        assert native_js.run_case(FIXTURES / "cases.mjs", name)["type"] == "test:pass"


def test_native_runner_times_out_processes():
    with pytest.raises(native_js.JavaScriptFailure, match="exceeded"):
        native_js.run_case(FIXTURES / "cases.mjs", "test_timeout", timeout=1)


@pytest.mark.parametrize("fixture", ["dynamic", "duplicate", "only", "nested", "suite"])
def test_native_discovery_rejects_ambiguous_case_registration(fixture):
    with pytest.raises(ValueError, match="discovery failed"):
        native_js.inventory(FIXTURES / f"{fixture}.mjs")


def test_native_pytest_collection_selection_skips_and_last_failure(tmp_path):
    target = tmp_path / "test_cases.mjs"
    shutil.copyfile(FIXTURES / "cases.mjs", target)
    (tmp_path / "conftest.py").write_text(
        "from testing.utility.native_js_pytest import collect_file as pytest_collect_file\n"
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(native_js.REPO_ROOT / "testing/pytest.ini"),
        "-o",
        f"cache_dir={tmp_path / 'cache'}",
        str(target),
    ]

    def invoke(*args):
        return subprocess.run(
            [*command, *args],
            cwd=native_js.REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    collected = invoke("--collect-only", "-q")
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert "11 tests collected" in collected.stdout
    selected = invoke("-k", "test_pass or test_skip or test_todo", "-o", "addopts=")
    assert selected.returncode == 0, selected.stdout + selected.stderr
    assert "1 passed, 2 skipped" in selected.stdout
    failed = invoke("-k", "test_fail or test_clean_global", "-x")
    assert failed.returncode == 1
    assert "1 failed" in failed.stdout
    rerun = invoke("--lf")
    assert rerun.returncode == 1
    assert "1 failed" in rerun.stdout


def test_native_batched_file_execution_preserves_isolation_and_error_attribution():
    outcomes = native_js.run_file_cases(
        FIXTURES / "cases.mjs",
        [
            "test_pass",
            "test_write_global",
            "test_clean_global",
            "test_fail",
            "test_caught_network",
            "test_missing_result",
            "test_unhandled_error",
        ],
    )
    assert isinstance(outcomes["test_pass"], dict)
    assert outcomes["test_pass"]["type"] == "test:pass"
    assert isinstance(outcomes["test_write_global"], dict)
    assert outcomes["test_write_global"]["type"] == "test:pass"
    # Even though test_write_global mutates globalThis in the same file,
    # isolated per-case fallback must keep test_clean_global passing.
    assert isinstance(outcomes["test_clean_global"], dict)
    assert outcomes["test_clean_global"]["type"] == "test:pass"

    assert isinstance(outcomes["test_fail"], native_js.JavaScriptFailure)
    assert "expected" in str(outcomes["test_fail"])
    assert isinstance(outcomes["test_caught_network"], native_js.JavaScriptFailure)
    assert "Unaccounted network" in str(outcomes["test_caught_network"])
    assert isinstance(outcomes["test_missing_result"], native_js.JavaScriptFailure)
    assert "matching results 0" in str(outcomes["test_missing_result"])
    assert isinstance(outcomes["test_unhandled_error"], native_js.JavaScriptFailure)
    assert "late exception" in str(outcomes["test_unhandled_error"])


def test_native_pytest_parallel_multi_file_execution(tmp_path):
    first = tmp_path / "test_first.mjs"
    second = tmp_path / "test_second.mjs"
    shutil.copyfile(FIXTURES / "cases.mjs", first)
    shutil.copyfile(FIXTURES / "cases.mjs", second)
    (tmp_path / "conftest.py").write_text(
        "from testing.utility.native_js_pytest import collect_file as pytest_collect_file\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(native_js.REPO_ROOT / "testing/pytest.ini"),
            "-o",
            f"cache_dir={tmp_path / 'cache'}",
            "-k",
            "test_pass or test_write_global or test_clean_global",
            str(first),
            str(second),
        ],
        cwd=native_js.REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "6 passed" in result.stdout
