"""Reporter and metadata contracts using supplied inventory data, without Node."""

import errno
import json
from unittest.mock import Mock

import pytest

from testing.utility import (
    native_js,
    template_contracts,
    contract_common,
    test_evidence,
    evidence_results,
)


pytestmark = pytest.mark.tooling


@pytest.fixture
def native_inventory(tmp_path, monkeypatch):
    path = tmp_path / "testing/tests_js/test_example.mjs"
    path.parent.mkdir(parents=True)
    path.write_text("// inventory is supplied to keep this a Python tooling test\n")
    rows = [
        dict(
            name="test_example",
            lineno=5,
            start_lineno=1,
            end_lineno=10,
            status="test",
            metadata_text="@matrix example : saved\n@template example.html::form\n@style button.submit",
            calls=["save"],
            selectors=['[data-role="saved"]'],
            source="example",
        )
    ]
    parsed = {"cases": rows, "imports": []}
    monkeypatch.setattr(native_js, "inventory", lambda path: parsed)
    monkeypatch.setattr(
        native_js, "inventories", lambda paths: {str(p.resolve()): parsed for p in paths}
    )
    return path, rows


def test_native_metadata_uses_existing_test_and_template_contracts(
    tmp_path, native_inventory
):
    path, _ = native_inventory
    tests = contract_common.collect_contract_tests(tmp_path)
    case = tests["tests_js/test_example.mjs::test_example"]
    assert case.styles == ["button.submit"]
    assert "package-lock.json" in native_js.execution_dependencies(path, tmp_path)
    refs = template_contracts.collect_template_references(tmp_path, path.name)
    assert [ref.nodeid for ref in refs] == [case.nodeid]
    assert refs[0].template_ref == "example.html::form"
    template = tmp_path / "lagniappe/web/templates/example.html"
    template.parent.mkdir(parents=True)
    template.write_text('{% macro form() %}<p data-role="saved"></p>{% endmacro %}')
    report = template_contracts.build_report(tmp_path, path.name)
    assert any(
        "data-role=saved" in evidence.matches
        for evidence in report.entries[0].selector_evidence
    )


@pytest.mark.parametrize("changed", ["testing/utility/native_js.py", ".nvmrc", "package-lock.json"])
def test_changed_native_runner_input_expires_contract_evidence(
    tmp_path, monkeypatch, native_inventory, changed
):
    path, _ = native_inventory
    case = "tests_js/test_example.mjs::test_example"
    fingerprints = dict.fromkeys(native_js.execution_dependencies(path, tmp_path), "old")
    monkeypatch.setattr(contract_common, "behavior_path_fingerprints", lambda _: fingerprints)
    test_evidence.write_json(tmp_path / test_evidence.LATEST_TEST_RUN, {
        "schema_version": 2,
        "snapshots": {"run": {"paths": fingerprints}},
        "tests": {case: {"outcome": "passed", "snapshot": "run"}},
    })
    tests = contract_common.collect_contract_tests(tmp_path)
    contract_common.attach_contract_results(tmp_path, tests)
    assert tests[case].execution_current
    fingerprints[changed] = "new"
    contract_common.attach_contract_results(tmp_path, tests)
    assert not tests[case].execution_current


@pytest.mark.parametrize(
    "changed",
    ["testing/utility/js/interop.mjs", "testing/utility/js/fixtures/value.mjs"],
)
def test_python_style_case_tracks_program_and_imported_helpers(tmp_path, monkeypatch, changed):
    program = tmp_path / "testing/utility/js/interop.mjs"
    child = program.parent / "fixtures/value.mjs"
    child.parent.mkdir(parents=True)
    program.write_text('import "./fixtures/value.mjs";')
    child.write_text("export const value = 1;")
    bridge = tmp_path / "testing/tests_js/test_bridge.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("# @style button.submit\n# @node-program testing/utility/js/interop.mjs\ndef test_bridge(): pass\n")
    monkeypatch.setattr(native_js, "inventory", lambda path: {
        "cases": [], "imports": ["./fixtures/value.mjs"] if path == program else [],
    })
    tests = contract_common.collect_contract_tests(tmp_path)
    case = tests["tests_js/test_bridge.py::test_bridge"]
    dependencies = native_js.execution_dependencies(program, tmp_path) | {"testing/tests_js/test_bridge.py"}
    fingerprints = dict.fromkeys(dependencies, "old")
    monkeypatch.setattr(contract_common, "behavior_path_fingerprints", lambda _: fingerprints)
    test_evidence.write_json(tmp_path / test_evidence.LATEST_TEST_RUN, {
        "schema_version": 2,
        "snapshots": {"run": {"paths": fingerprints}},
        "tests": {case.nodeid: {"outcome": "passed", "snapshot": "run"}},
    })
    contract_common.attach_contract_results(tmp_path, tests)
    assert case.execution_current
    fingerprints[changed] = "new"
    contract_common.attach_contract_results(tmp_path, tests)
    assert not case.execution_current


def test_native_evidence_prunes_removed_case(tmp_path, native_inventory):
    _, rows = native_inventory
    nodeid = "tests_js/test_example.mjs::test_example"
    assert evidence_results._test_node_exists(tmp_path, nodeid, {})
    rows.clear()
    assert not evidence_results._test_node_exists(tmp_path, nodeid, {})


def test_native_reporter_requires_one_result_and_rejects_late_failures():
    passed = {"type": "test:pass", "name": "test_example", "nesting": 0}
    assert (
        native_js.interpret_result(json.dumps(passed), "", 0, "test_example") == passed
    )
    for output, diagnostic in (
        ("", "matching results 0"),
        ("invalid json", "Invalid Node reporter output"),
        (json.dumps(passed) + "\n" + json.dumps(passed), "matching results 2"),
        (
            json.dumps(passed)
            + "\n"
            + json.dumps(
                {"type": "test:fail", "name": "file", "error": "late failure"}
            ),
            "late failure",
        ),
    ):
        with pytest.raises(native_js.JavaScriptFailure) as error:
            native_js.interpret_result(output, "", 0, "test_example")
        assert diagnostic in str(error.value)

    with pytest.raises(native_js.JavaScriptFailure, match="exit 1"):
        native_js.interpret_result(
            json.dumps(passed), "process exited unexpectedly", 1, "test_example"
        )


def test_interpret_file_results_verifies_clean_batches_and_flags_fallback_cases():
    pass_a = {"type": "test:pass", "name": "test_a", "nesting": 0}
    pass_b = {"type": "test:pass", "name": "test_b", "nesting": 0}
    fail_b = {"type": "test:fail", "name": "test_b", "nesting": 0, "error": "boom"}
    hook_fail = {"type": "test:fail", "name": "bootstrap.mjs", "nesting": 0, "error": "hook"}

    # Clean multi-case batch needs zero fallbacks.
    verified, fallback = native_js.interpret_file_results(
        "\n".join(json.dumps(row) for row in (pass_a, pass_b)),
        "",
        0,
        ["test_a", "test_b"],
    )
    assert verified == {"test_a": pass_a, "test_b": pass_b}
    assert fallback == set()

    # Single attributed case failure keeps passing sibling and falls back only the failing case.
    verified, fallback = native_js.interpret_file_results(
        "\n".join(json.dumps(row) for row in (pass_a, fail_b)),
        "",
        1,
        ["test_a", "test_b"],
    )
    assert verified == {"test_a": pass_a}
    assert fallback == {"test_b"}

    # Missing case (e.g. process.exit(0) mid-file) falls back the missing case.
    verified, fallback = native_js.interpret_file_results(
        json.dumps(pass_a),
        "",
        0,
        ["test_a", "test_b"],
    )
    assert verified == {"test_a": pass_a}
    assert fallback == {"test_b"}

    # Hook/file-level failure, invalid JSON, or unattributed non-zero exit fall back the full file.
    for output, returncode in (
        ("\n".join(json.dumps(row) for row in (pass_a, pass_b, hook_fail)), 1),
        ("not json", 0),
        ("\n".join(json.dumps(row) for row in (pass_a, pass_b)), 1),
    ):
        verified, fallback = native_js.interpret_file_results(
            output, "", returncode, ["test_a", "test_b"]
        )
        assert verified == {}
        assert fallback == {"test_a", "test_b"}


def test_native_js_worker_and_batch_environment_overrides(monkeypatch):
    monkeypatch.delenv("LAGNIAPPE_JS_WORKERS", raising=False)
    monkeypatch.delenv("LAGNIAPPE_JS_BATCH", raising=False)
    assert 1 <= native_js.worker_count() <= native_js.DEFAULT_MAX_WORKERS
    assert native_js.batch_enabled() is True

    monkeypatch.setenv("LAGNIAPPE_JS_WORKERS", "3")
    assert native_js.worker_count() == 3
    monkeypatch.setenv("LAGNIAPPE_JS_WORKERS", "invalid")
    with pytest.raises(ValueError, match="LAGNIAPPE_JS_WORKERS"):
        native_js.worker_count()

    monkeypatch.setenv("LAGNIAPPE_JS_BATCH", "0")
    assert native_js.batch_enabled() is False
    monkeypatch.setenv("LAGNIAPPE_JS_BATCH", "false")
    assert native_js.batch_enabled() is False


def reported_case(name, passed=True):
    event = {"name": name, "type": "test:pass" if passed else "test:fail"}
    process = Mock(returncode=0 if passed else 1)
    process.communicate.return_value = (json.dumps(event), "")
    return process


def test_isolated_launch_error_preserves_verified_siblings_and_assertions(tmp_path, monkeypatch):
    path = tmp_path / "test_mixed.mjs"
    fault = OSError(errno.EFAULT, "Bad address")
    launch = Mock(side_effect=[reported_case("test_ok"), fault, reported_case("test_assert", False)])
    monkeypatch.setattr(native_js, "node_binary", lambda: "/test/node")
    monkeypatch.setattr(native_js.subprocess, "Popen", launch)
    monkeypatch.setenv("LAGNIAPPE_JS_BATCH", "1")

    outcomes = native_js.run_file_cases(path, ["test_ok", "test_fault", "test_assert"])

    assert outcomes["test_ok"]["type"] == "test:pass"
    error = outcomes["test_fault"]
    assert isinstance(error, native_js.JavaScriptLaunchError)
    assert error.__cause__ is fault
    for detail in ("isolated", "test_fault", str(path), "/test/node", str(fault)):
        assert detail in str(error)
    assert error.__notes__ == ["Isolated fallback from 3 selected cases: test_ok, test_fault, test_assert"]
    assert isinstance(outcomes["test_assert"], native_js.JavaScriptFailure)
    assert launch.call_count == 3


@pytest.mark.parametrize("number,attempts", [(errno.EAGAIN, 2), (errno.EINTR, 2), (errno.ENOENT, 1)])
def test_file_batch_launch_error_identifies_all_affected_cases(tmp_path, monkeypatch, number, attempts):
    path = tmp_path / "test_batch.mjs"
    fault = OSError(number, "injected launch failure")
    launch = Mock(side_effect=fault)
    monkeypatch.setattr(native_js, "node_binary", lambda: "/test/node")
    monkeypatch.setattr(native_js.subprocess, "Popen", launch)
    monkeypatch.setenv("LAGNIAPPE_JS_BATCH", "1")

    names = ["test_first", "test_last"]
    outcomes = native_js.run_file_cases(path, names)

    assert set(outcomes) == set(names)
    for error in outcomes.values():
        assert isinstance(error, native_js.JavaScriptLaunchError)
        assert error.__cause__ is fault
        for detail in ("batch", *names, str(path), "/test/node", str(fault)):
            assert detail in str(error)
    assert launch.call_count == attempts


def test_interrupted_node_launch_can_recover_once(tmp_path, monkeypatch):
    launch = Mock(side_effect=[InterruptedError(errno.EINTR, "interrupted"), reported_case("test_ok")])
    monkeypatch.setattr(native_js, "node_binary", lambda: "/test/node")
    monkeypatch.setattr(native_js.subprocess, "Popen", launch)

    assert native_js.run_case(tmp_path / "test_retry.mjs", "test_ok")["type"] == "test:pass"
    assert launch.call_count == 2
