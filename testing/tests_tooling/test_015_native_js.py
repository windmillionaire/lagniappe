"""Reporter and metadata contracts using supplied inventory data, without Node."""

import json

import pytest

from testing.utility import (
    native_js,
    template_contracts,
    traceability,
    traceability_results,
)


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
    monkeypatch.setattr(native_js, "inventories", lambda paths: {})
    return path, rows


def test_native_metadata_uses_existing_test_and_template_contracts(
    tmp_path, native_inventory
):
    path, _ = native_inventory
    tests = traceability.discover_tests(tmp_path, ["testing/tests_js"])
    case = tests["tests_js/test_example.mjs::test_example"]
    assert case.metadata.features == ["example"]
    assert case.metadata.styles == ["button.submit"]
    assert case.start_lineno == 1
    assert "package-lock.json" in case._execution_dependencies
    refs = template_contracts.collect_template_references(tmp_path, path.name)
    assert [ref.nodeid for ref in refs] == [case.nodeid]
    assert refs[0].template_ref == "example.html::form"
    assert traceability.NODEID_LINE_RE.match(case.nodeid)
    assert traceability.test_matches_target(case, "test_example.mjs")
    template = tmp_path / "lagniappe/web/templates/example.html"
    template.parent.mkdir(parents=True)
    template.write_text('{% macro form() %}<p data-role="saved"></p>{% endmacro %}')
    report = template_contracts.build_report(tmp_path, path.name)
    assert any(
        "data-role=saved" in evidence.matches
        for evidence in report.entries[0].selector_evidence
    )


def test_native_helper_changes_focus_and_invalidate_evidence(
    tmp_path, monkeypatch, native_inventory
):
    tests = traceability.discover_tests(tmp_path, ["testing/tests_js"])
    case = next(iter(tests.values()))
    dependency = "testing/utility/native_js.py"
    case.execution_current = True
    case._execution_snapshots = [{dependency: "old"}]
    monkeypatch.setattr(
        traceability, "behavior_path_fingerprints", lambda root: {dependency: "new"}
    )
    traceability.apply_test_dependency_fingerprints(
        tests, {case.nodeid: set(case._execution_dependencies)}, tmp_path
    )
    assert not case.execution_current
    assert traceability.changed_tests_for_paths(tests, [dependency], {}) == [case]


def test_native_evidence_prunes_removed_case(tmp_path, native_inventory):
    _, rows = native_inventory
    nodeid = "tests_js/test_example.mjs::test_example"
    assert traceability_results._test_node_exists(tmp_path, nodeid, {})
    rows.clear()
    assert not traceability_results._test_node_exists(tmp_path, nodeid, {})


def test_native_node_pin_changes_invalidate_evidence(tmp_path, native_inventory):
    pin = tmp_path / ".nvmrc"
    pin.write_text("26.8.2\n")
    tests = traceability.discover_tests(tmp_path, ["testing/tests_js"])
    case = next(iter(tests.values()))
    case.execution_current = True
    case._execution_snapshots = [traceability.behavior_path_fingerprints(tmp_path)]
    dependencies = {case.nodeid: set(case._execution_dependencies)}
    traceability.apply_test_dependency_fingerprints(tests, dependencies, tmp_path)
    assert case.execution_current
    pin.write_text("26.9.0\n")
    traceability.apply_test_dependency_fingerprints(tests, dependencies, tmp_path)
    assert not case.execution_current


def test_native_reporter_requires_one_result_and_rejects_late_failures():
    passed = {"type": "test:pass", "name": "test_example", "nesting": 0}
    assert (
        native_js.interpret_result(json.dumps(passed), "", 0, "test_example") == passed
    )
    for output in (
        "",
        "invalid json",
        json.dumps(passed) + "\n" + json.dumps(passed),
        json.dumps(passed)
        + "\n"
        + json.dumps({"type": "test:fail", "name": "file", "error": "late failure"}),
    ):
        with pytest.raises(native_js.JavaScriptFailure):
            native_js.interpret_result(output, "", 0, "test_example")
