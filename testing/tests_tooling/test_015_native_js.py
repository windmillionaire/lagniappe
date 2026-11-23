"""Reporter and metadata contracts using supplied inventory data, without Node."""

import json

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
