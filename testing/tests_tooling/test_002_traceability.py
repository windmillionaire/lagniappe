"""Tests for the declared source/test traceability reporter."""

import json
from pathlib import Path

import pytest

from testing.utility import traceability, traceability_common

pytestmark = pytest.mark.tooling


def test_python_inventory_reads_docstrings_comments_and_decorators(tmp_path):
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        '''
# @testable true
# @tests tests_unit/test_sample.py::test_decorated
# @scaffolding testing/resources/sample.py::Widget.exercise
@decorator
def decorated():
    pass


class Thing:
    """
    @testable false
    @reason covered through the public workflow
    """

    # @testable true
    # @tests tests_unit/test_sample.py::test_method
    # @features widget
    # @dimensions edit
    # @pair widget:edit
    def method(self):
        pass
'''.lstrip()
    )

    symbols = {
        symbol.qualname: symbol
        for symbol in traceability.inventory_python_file(source, tmp_path)
    }

    assert symbols["decorated"].metadata.testable is True
    assert symbols["decorated"].metadata.tests == [
        "tests_unit/test_sample.py::test_decorated"
    ]
    assert symbols["decorated"].metadata.test_scaffolds == [
        "testing/resources/sample.py::Widget.exercise"
    ]
    assert symbols["decorated"].lineno == 5
    assert symbols["Thing"].metadata.testable is False
    assert symbols["Thing"].metadata.reason == "covered through the public workflow"
    assert symbols["Thing.method"].metadata.features == ["widget"]
    assert symbols["Thing.method"].metadata.dimensions == ["edit"]
    assert symbols["Thing.method"].metadata.pairs == ["widget:edit"]


def test_metadata_diagnoses_unsupported_suggestion_tag():
    metadata = traceability.parse_metadata(
        "@suggestion maybe test this later\n@tesable true"
    )

    assert metadata.issues == [
        "@suggestion is not tracked; use @todo for a concrete coverage gap",
        "unknown traceability tag @tesable; did you mean @testable?",
    ]


def test_metadata_rejects_malformed_exact_pairs():
    metadata = traceability.parse_metadata(
        "@pair missing-dimension\n@pair :empty-feature\n@pair good:pair"
    )

    assert metadata.pairs == ["good:pair"]
    assert metadata.features == ["good"]
    assert metadata.dimensions == ["pair"]
    assert metadata.issues == [
        "@pair must use FEATURE:DIMENSION",
        "@pair must use FEATURE:DIMENSION",
    ]


def test_metadata_tracks_semantic_style_evidence():
    metadata = traceability.parse_metadata(
        "@style combobox.panel\n@styles input.default, dropdown.panel"
    )

    assert metadata.styles == [
        "combobox.panel",
        "input.default",
        "dropdown.panel",
    ]
    assert metadata.issues == []


@pytest.mark.parametrize(
    "schema_version", [2, traceability_common.TEST_RUN_SCHEMA_VERSION]
)
def test_result_currentness_tracks_test_and_declared_source_fingerprints(
    monkeypatch, tmp_path, schema_version
):
    nodeid = "tests_unit/test_sample.py::test_behavior"
    results_path = tmp_path / traceability_common.LATEST_TEST_RUN
    results_path.parent.mkdir(parents=True)
    paths = {
        "testing/tests_unit/test_sample.py": "test-code",
        "pkg/source.py": "source-code",
    }
    if schema_version == 2:
        snapshot_payload = {"snapshots": {"run-one": {"paths": paths}}}
    else:
        fingerprint_pairs, snapshots = (
            traceability_common.encode_test_run_snapshots({"run-one": paths})
        )
        snapshot_payload = {
            "fingerprint_pairs": fingerprint_pairs,
            "snapshots": snapshots,
        }
    results_path.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "kind": "test-run",
                "provenance": {},
                "tests": {
                    nodeid: {
                        "outcome": "passed",
                        "duration": 0.1,
                        "snapshot": "run-one",
                    }
                },
                **snapshot_payload,
            }
        )
    )
    current = dict(paths)
    monkeypatch.setattr(
        traceability, "behavior_path_fingerprints", lambda repo_root: current
    )
    tests = {
        nodeid: make_test_case(
            nodeid,
            runnable=True,
            path="tests_unit/test_sample.py",
        )
    }

    traceability.attach_test_results(tests, tmp_path)
    traceability.apply_test_dependency_fingerprints(
        tests, {nodeid: {"pkg/source.py"}}, tmp_path
    )
    assert tests[nodeid].execution == "passed"
    assert tests[nodeid].execution_current is True

    current["pkg/source.py"] = "changed-source-code"
    traceability.apply_test_dependency_fingerprints(
        tests, {nodeid: {"pkg/source.py"}}, tmp_path
    )
    assert tests[nodeid].execution_current is False


def test_result_currentness_ignores_removed_parameter_variants(monkeypatch, tmp_path):
    base_nodeid = "tests_unit/test_sample.py::test_behavior"
    current_nodeid = f"{base_nodeid}[current]"
    removed_nodeid = f"{base_nodeid}[removed]"
    results_path = tmp_path / traceability_common.LATEST_TEST_RUN
    results_path.parent.mkdir(parents=True)
    fingerprint_pairs, snapshots = traceability_common.encode_test_run_snapshots(
        {
            "current-run": {
                "testing/tests_unit/test_sample.py": "current-test-code"
            },
            "removed-run": {
                "testing/tests_unit/test_sample.py": "removed-test-code"
            },
        }
    )
    results_path.write_text(
        json.dumps(
            {
                "schema_version": traceability_common.TEST_RUN_SCHEMA_VERSION,
                "kind": "test-run",
                "provenance": {},
                "tests": {
                    current_nodeid: {
                        "outcome": "passed",
                        "duration": 0.1,
                        "snapshot": "current-run",
                    },
                    removed_nodeid: {
                        "outcome": "failed",
                        "duration": 0.1,
                        "snapshot": "removed-run",
                    },
                },
                "fingerprint_pairs": fingerprint_pairs,
                "snapshots": snapshots,
            }
        )
    )
    monkeypatch.setattr(
        traceability,
        "behavior_path_fingerprints",
        lambda repo_root: {
            "testing/tests_unit/test_sample.py": "current-test-code"
        },
    )
    test = make_test_case(
        base_nodeid,
        runnable=True,
        path="tests_unit/test_sample.py",
    )
    test.collection_verified = True
    test._collected_nodeids = [current_nodeid]
    tests = {base_nodeid: test}

    traceability.attach_test_results(tests, tmp_path)

    assert test.execution == "passed"
    assert test.execution_current is True


def test_javascript_inventory_reads_jsdoc_comments_and_exports(tmp_path):
    source = tmp_path / "src" / "sample.mjs"
    source.parent.mkdir()
    source.write_text(
        """
/**
 * @testable true
 * @tests tests_unit/test_js.py::test_widget
 * @scaffolding testing/resources/widgets.py::WidgetScaffold.exercise
 */
export class Widget {
    /**
     * @testable false
     * @reason covered through Widget
     */
    init() {}
}

/**
 * @testable true
 * @tests tests_unit/test_js.py::test_helper
 */
export function helper() {}

// @testable true
// @tests tests_unit/test_js.py::test_arrow
export const arrow = () => {};

// @testable true
// @tests tests_e2e/test_editor.py::test_selection
export const SelectionHighlight = Extension.create({});
""".lstrip()
    )

    symbols = {
        symbol.qualname: symbol
        for symbol in traceability.inventory_javascript_files([source], tmp_path)
    }

    assert symbols["Widget"].metadata.testable is True
    assert symbols["Widget"].metadata.tests == ["tests_unit/test_js.py::test_widget"]
    assert symbols["Widget"].metadata.test_scaffolds == [
        "testing/resources/widgets.py::WidgetScaffold.exercise"
    ]
    assert symbols["Widget.init"].metadata.testable is False
    assert symbols["Widget.init"].metadata.reason == "covered through Widget"
    assert symbols["helper"].metadata.tests == ["tests_unit/test_js.py::test_helper"]
    assert symbols["arrow"].metadata.tests == ["tests_unit/test_js.py::test_arrow"]
    assert symbols["SelectionHighlight"].kind == "declaration"
    assert symbols["SelectionHighlight"].metadata.tests == [
        "tests_e2e/test_editor.py::test_selection"
    ]


def test_default_filter_ignores_boilerplate_python_symbols(tmp_path):
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        """
class Widget:
    def __init__(self):
        pass

    @property
    def value(self):
        return 1

    @value.setter
    def value(self, value):
        pass

    def init(self):
        pass

    def postreconcile(self):
        pass

    def update(self):
        pass
""".lstrip()
    )

    filtered = traceability.filter_symbols(
        traceability.inventory_python_file(source, tmp_path), default_config()
    )
    qualnames = {symbol.qualname for symbol in filtered}

    assert qualnames == {"Widget", "Widget.value", "Widget.update"}


def test_filter_includes_python_property_getters_as_source_symbols(tmp_path):
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        """
class Widget:
    @property
    def quiet(self):
        return 1

    # @testable true
    # @tests tests_unit/test_sample.py::test_annotated
    @property
    def annotated(self):
        return 2
""".lstrip()
    )

    filtered = traceability.filter_symbols(
        traceability.inventory_python_file(source, tmp_path), default_config()
    )
    symbols = {symbol.qualname: symbol for symbol in filtered}

    assert symbols["Widget.quiet"].subkind == "property"
    assert symbols["Widget.annotated"].metadata.testable is True
    assert symbols["Widget.annotated"].subkind == "property"


def test_build_report_allows_covered_by_to_reference_property(tmp_path, monkeypatch):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - pkg
exclude: []
""".lstrip()
    )
    source = tmp_path / "pkg" / "source.py"
    source.parent.mkdir()
    source.write_text(
        """
class Widget:
    @property
    def value(self):
        return 1


# @testable false
# @covered-by pkg/source.py::Widget.value
def helper():
    pass
""".lstrip()
    )
    monkeypatch.setattr(traceability, "collect_tests", lambda repo_root, roots=(): {})

    report = traceability.build_report(tmp_path, Path("traceability.yaml"))

    assert "pkg/source.py::Widget.value" in {
        symbol.source_id for symbol in report.missing_testable
    }
    assert report.summary["covered_by_missing"] == 0
    assert report.covered_by_missing == []


def test_full_inventory_attaches_template_and_style_contracts(tmp_path, monkeypatch):
    config = tmp_path / "traceability.yaml"
    config.write_text("source_roots: [pkg]\nexclude: []\n")
    source = tmp_path / "pkg" / "source.py"
    source.parent.mkdir()
    source.write_text(
        "# @testable infrastructure\ndef bootstrap():\n    pass\n"
    )
    calls = []

    def attach(report, tests, repo_root, *, changed_paths=None):
        calls.append((tests, repo_root, changed_paths))
        report.summary["template_contracts"] = 1
        report.summary["style_traceability"] = True

    monkeypatch.setattr(traceability, "collect_tests", lambda repo_root, roots=(): {})
    monkeypatch.setattr(traceability, "attach_contract_traceability", attach)

    report = traceability.build_report(tmp_path, Path("traceability.yaml"))

    assert calls == [({}, tmp_path, None)]
    assert report.summary["template_contracts"] == 1
    assert report.summary["style_traceability"] is True


def test_covered_by_owner_accepts_tested_property_getter_with_shared_qualname():
    owner_id = "pkg/source.py::Widget.value"
    child = source_symbol(
        "pkg/source.py",
        "helper",
        False,
        covered_by=[owner_id],
    )
    tested_getter = source_symbol(
        "pkg/source.py",
        "Widget.value",
        True,
        tests=["tests_unit/test_source.py::test_value"],
    )
    unannotated_setter = source_symbol(
        "pkg/source.py",
        "Widget.value",
        None,
    )

    issues = traceability.source_link_issues(
        [child, tested_getter, unannotated_setter]
    )

    assert issues == []


def test_parent_testable_decision_suppresses_unannotated_children(tmp_path):
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        """
# @testable true
# @tests tests_unit/test_sample.py::test_workflow
class Workflow:
    def helper(self):
        pass

    # @testable true
    # @tests tests_unit/test_sample.py::test_step
    def step(self):
        pass


# @testable infrastructure
class Framework:
    def helper(self):
        pass

    # @testable true
    # @tests tests_unit/test_sample.py::test_public
    def public(self):
        pass


# @testable false
# @covered-by pkg/owner.py
class Shell:
    def ignored(self):
        pass


class Concrete:
    def visible(self):
        pass
""".lstrip()
    )

    filtered = traceability.filter_symbols(
        traceability.inventory_python_file(source, tmp_path), default_config()
    )
    qualnames = {symbol.qualname for symbol in filtered}

    assert qualnames == {
        "Concrete",
        "Concrete.visible",
        "Framework",
        "Framework.public",
        "Shell",
        "Workflow",
        "Workflow.step",
    }


def test_default_filter_ignores_python_enum_and_data_only_classes(tmp_path):
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        """
from enum import Enum


class Label:
    name = "label"
    title = "Label"


class EmptyMarker:
    pass


class Behavior:
    name = "behavior"

    def run(self):
        return self.name


class Choice(Enum):
    A = "a"

    def normalize(self):
        return self.value
""".lstrip()
    )

    filtered = traceability.filter_symbols(
        traceability.inventory_python_file(source, tmp_path), default_config()
    )
    qualnames = {symbol.qualname for symbol in filtered}

    assert qualnames == {"Behavior", "Behavior.run", "Choice.normalize"}


def test_default_filter_ignores_boilerplate_javascript_symbols(tmp_path):
    source = tmp_path / "src" / "sample.mjs"
    source.parent.mkdir()
    source.write_text(
        """
export class Widget {
    constructor() {}
    get value() { return 1; }
    set value(next) {}
    init() {}
    postreconcile() {}
    update() {}
}
""".lstrip()
    )

    filtered = traceability.filter_symbols(
        traceability.inventory_javascript_files([source], tmp_path), default_config()
    )
    qualnames = {symbol.qualname for symbol in filtered}

    assert qualnames == {"Widget", "Widget.update"}


def test_parent_testable_infrastructure_suppresses_javascript_methods(tmp_path):
    source = tmp_path / "src" / "sample.mjs"
    source.parent.mkdir()
    source.write_text(
        """
/**
 * @testable infrastructure
 */
export class Framework {
    helper() {}

    /**
     * @testable true
     * @tests tests_unit/test_js.py::test_public
     */
    public() {}
}
""".lstrip()
    )

    filtered = traceability.filter_symbols(
        traceability.inventory_javascript_files([source], tmp_path), default_config()
    )
    qualnames = {symbol.qualname for symbol in filtered}

    assert qualnames == {"Framework", "Framework.public"}


def test_default_config_excludes_load_bearing_config_paths():
    repo_root = Path(__file__).resolve().parents[2]
    config = default_config()

    assert "config" not in config["source_roots"]
    assert "**/config/**" in config["exclude"]

    python_files, javascript_files = traceability.discover_source_files(
        config, repo_root
    )
    discovered = {
        traceability.relpath(path, repo_root)
        for path in [*python_files, *javascript_files]
    }

    assert not any(path.startswith("config/") for path in discovered)
    assert not any(path.startswith("src/script/config/") for path in discovered)


def test_default_config_limits_report_tests_to_behavior_suites():
    config = default_config()
    tests = {
        "tests_unit/test_unit.py::test_unit": make_test_case(
            "tests_unit/test_unit.py::test_unit",
            runnable=True,
            path="tests_unit/test_unit.py",
        ),
        "tests_e2e/001_site/test_site.py::test_site": make_test_case(
            "tests_e2e/001_site/test_site.py::test_site",
            runnable=True,
            path="tests_e2e/001_site/test_site.py",
        ),
        "tests_js/test_frontend.py::test_frontend": make_test_case(
            "tests_js/test_frontend.py::test_frontend",
            runnable=True,
            path="tests_js/test_frontend.py",
        ),
        "tests_tooling/test_tool.py::test_tool": make_test_case(
            "tests_tooling/test_tool.py::test_tool",
            runnable=True,
            path="tests_tooling/test_tool.py",
        ),
    }

    filtered = traceability.filter_tests_by_roots(tests, config["test_roots"])

    assert set(filtered) == {
        "tests_unit/test_unit.py::test_unit",
        "tests_e2e/001_site/test_site.py::test_site",
        "tests_js/test_frontend.py::test_frontend",
    }


def test_inventory_source_file_scopes_to_explicit_path(tmp_path):
    target = tmp_path / "outside_roots" / "target.py"
    target.parent.mkdir()
    target.write_text(
        """
def target():
    pass
""".lstrip()
    )
    other = tmp_path / "src" / "other.py"
    other.parent.mkdir()
    other.write_text(
        """
def other():
    pass
""".lstrip()
    )

    symbols = traceability.inventory_source_file(
        default_config(), tmp_path, Path("outside_roots/target.py")
    )

    assert [symbol.qualname for symbol in symbols] == ["target"]
    assert {symbol.path for symbol in symbols} == {"outside_roots/target.py"}


def test_test_metadata_reads_comments_docstrings_and_parameter_nodeids(tmp_path):
    test_file = tmp_path / "testing" / "tests_unit" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        '''
# @features login
# @dimensions a11y mobile
# @todo cover locked account state
def test_login():
    pass


def test_profile():
    """
    @features profile
    @dimensions desktop
    @todo cover avatar update
    """
    pass
'''.lstrip()
    )

    nodeids = [
        "tests_unit/test_sample.py::test_login[param]",
        "tests_unit/test_sample.py::test_profile",
    ]
    metadata = traceability.collect_test_metadata(nodeids, tmp_path)

    assert metadata[nodeids[0]].features == ["login"]
    assert metadata[nodeids[0]].dimensions == ["a11y", "mobile"]
    assert metadata[nodeids[0]].todos == ["cover locked account state"]
    assert metadata[nodeids[1]].features == ["profile"]
    assert metadata[nodeids[1]].dimensions == ["desktop"]
    assert metadata[nodeids[1]].todos == ["cover avatar update"]


def test_classify_reports_traceability_states():
    selected = "tests_unit/test_trace.py::test_selected"
    planned = "tests_unit/test_trace.py::test_planned"
    stale = "tests_unit/test_trace.py::test_missing"
    orphan = "tests_unit/test_trace.py::test_orphan"
    gap = "tests_unit/test_trace.py::test_gap"
    symbols = [
        source_symbol("pkg/source.py", "missing", None),
        source_symbol("pkg/source.py", "covered", True, tests=[selected]),
        source_symbol("pkg/source.py", "no_tests", True),
        source_symbol("pkg/source.py", "planned", True, tests=[planned]),
        source_symbol("pkg/source.py", "stale", True, tests=[stale]),
        source_symbol("pkg/source.py", "bad_false", False),
        source_symbol(
            "pkg/source.py",
            "bad_cover",
            False,
            covered_by=["pkg/source.py::not_found"],
        ),
        source_symbol(
            "pkg/source.py",
            "manual",
            False,
            reason="requires live provider validation",
            manual=True,
        ),
        source_symbol(
            "pkg/source.py",
            "gap",
            True,
            tests=[gap],
            features=["login"],
            dimensions=["mobile"],
        ),
    ]
    tests = {
        selected: make_test_case(
            selected,
            runnable=True,
            features=["login"],
            todos=["cover logout flow"],
        ),
        planned: make_test_case(planned, runnable=False),
        orphan: make_test_case(orphan, runnable=True),
        gap: make_test_case(
            gap, runnable=True, features=["profile"], dimensions=["desktop"]
        ),
    }

    report = traceability.classify(symbols, tests)

    assert report.summary["annotated_sources"] == 8
    assert report.summary["testable_true"] == 5
    assert report.summary["testable_false"] == 3
    assert report.summary["sources_with_known_tests"] == 3
    assert report.summary["sources_with_runnable_tests"] == 2
    assert report.summary["source_test_links"] == 4
    assert report.summary["source_test_links_known"] == 3
    assert report.summary["source_test_links_runnable"] == 2
    assert report.summary["source_test_links_unfinished"] == 1
    assert report.summary["source_test_links_stale"] == 1
    assert report.summary["referenced_tests"] == 3
    assert report.summary["referenced_runnable_tests"] == 2
    assert report.summary["referenced_unfinished_tests"] == 1
    assert report.summary["missing_testable"] == 1
    assert report.summary["testable_without_tests"] == 1
    assert report.summary["manual_validation"] == 1
    assert report.summary["test_todos"] == 1
    assert report.summary["test_todo_groups"] == 1
    assert report.summary["test_todos_runnable"] == 1
    assert report.summary["test_todos_unfinished"] == 0
    assert report.unfinished_coverage[0].qualname == "planned"
    assert report.stale_test_references[0]["tests"] == [stale]
    assert report.invalid_false[0]["source"].qualname == "bad_false"
    assert report.manual_validation[0].qualname == "manual"
    assert report.covered_by_missing[0]["covered_by"] == ["pkg/source.py::not_found"]
    assert report.feature_dimension_gaps[0]["source"].qualname == "gap"
    assert report.feature_dimension_gaps[0]["missing"] == [
        {
            "kind": "pair",
            "feature": "login",
            "dimension": "mobile",
            "name": "login:mobile",
        }
    ]
    assert report.test_todos[0]["todos"] == ["cover logout flow"]
    assert orphan in report.orphan_runnable_tests


def test_classify_checks_feature_dimension_pairs():
    home_permissions = "tests_e2e/002_home/test_home.py::test_permissions"
    search_load = "tests_e2e/002_home/test_home.py::test_search_load"
    symbols = [
        source_symbol(
            "pkg/source.py",
            "HomeSearch",
            True,
            tests=[home_permissions, search_load],
            features=["home", "search"],
            dimensions=["permissions", "load"],
        )
    ]
    tests = {
        home_permissions: make_test_case(
            home_permissions,
            runnable=True,
            features=["home"],
            dimensions=["permissions"],
        ),
        search_load: make_test_case(
            search_load,
            runnable=True,
            features=["search"],
            dimensions=["load"],
        ),
    }

    report = traceability.classify(symbols, tests)

    missing = report.feature_dimension_gaps[0]["missing"]
    assert {gap["name"] for gap in missing} == {"home:load", "search:permissions"}
    assert {gap["kind"] for gap in missing} == {"pair"}


def test_classify_exact_pairs_do_not_imply_a_cartesian_product():
    home_permissions = "tests_e2e/test_exact.py::test_home_permissions"
    search_load = "tests_e2e/test_exact.py::test_search_load"
    symbols = [
        source_symbol(
            "pkg/source.py",
            "HomeSearch",
            True,
            tests=[home_permissions, search_load],
            pairs=["home:permissions", "search:load"],
        )
    ]
    tests = {
        home_permissions: make_test_case(
            home_permissions,
            runnable=True,
            pairs=["home:permissions"],
        ),
        search_load: make_test_case(
            search_load,
            runnable=True,
            pairs=["search:load"],
        ),
    }

    report = traceability.classify(symbols, tests)

    assert report.feature_dimension_gaps == []
    assert traceability.feature_dimension_pairs(symbols[0].metadata) == {
        "home:permissions",
        "search:load",
    }


def test_classify_keeps_single_tag_family_checks_independent():
    feature_test = "tests_unit/test_tags.py::test_feature"
    dimension_test = "tests_unit/test_tags.py::test_dimension"
    symbols = [
        source_symbol(
            "pkg/source.py",
            "FeatureOnly",
            True,
            tests=[feature_test],
            features=["home", "search"],
        ),
        source_symbol(
            "pkg/source.py",
            "DimensionOnly",
            True,
            tests=[dimension_test],
            dimensions=["load", "layout"],
        ),
    ]
    tests = {
        feature_test: make_test_case(
            feature_test,
            runnable=True,
            features=["home"],
        ),
        dimension_test: make_test_case(
            dimension_test,
            runnable=True,
            dimensions=["load"],
        ),
    }

    report = traceability.classify(symbols, tests)

    gaps = {
        item["source"].qualname: item["missing"]
        for item in report.feature_dimension_gaps
    }
    assert gaps["FeatureOnly"] == [{"kind": "feature", "name": "search"}]
    assert gaps["DimensionOnly"] == [{"kind": "dimension", "name": "layout"}]


def test_classify_expands_glob_tests_and_file_level_covered_by():
    home_a = "tests_e2e/002_home/test_002a_home.py::test_home_a"
    home_b = "tests_e2e/002_home/test_002b_home.py::test_home_b"
    symbols = [
        source_symbol(
            "pkg/home.py",
            "Home",
            True,
            tests=["tests_e2e/002_home/*"],
        ),
        source_symbol("pkg/home.py", "Framework", traceability.TESTABLE_INFRASTRUCTURE),
        source_symbol(
            "pkg/home.py",
            "Projection",
            False,
            covered_by=["pkg/properties/home.py"],
        ),
        source_symbol(
            "pkg/home.py",
            "MissingProjection",
            False,
            covered_by=["pkg/properties/missing.py"],
        ),
        source_symbol(
            "pkg/home.py",
            "StalePattern",
            True,
            tests=["tests_e2e/999_missing/*"],
        ),
    ]
    tests = {
        home_a: make_test_case(home_a, runnable=True),
        home_b: make_test_case(home_b, runnable=False),
    }

    report = traceability.classify(
        symbols,
        tests,
        known_source_paths={"pkg/properties/home.py"},
    )

    assert report.summary["testable_infrastructure"] == 1
    assert report.summary["source_test_links"] == 3
    assert report.summary["source_test_links_known"] == 2
    assert report.summary["source_test_links_runnable"] == 1
    assert report.summary["source_test_links_unfinished"] == 1
    assert report.summary["source_test_links_stale"] == 1
    assert report.summary["referenced_tests"] == 2
    assert report.summary["referenced_runnable_tests"] == 1
    assert report.summary["referenced_unfinished_tests"] == 1
    assert report.summary["invalid_false"] == 0
    assert report.covered_by_missing[0]["covered_by"] == ["pkg/properties/missing.py"]
    assert report.stale_test_references[0]["tests"] == ["tests_e2e/999_missing/*"]


def test_classify_resolves_test_scaffold_references(tmp_path):
    owner = "tests_e2e/003_forms/test_access.py::test_owner"
    test_file = tmp_path / "testing" / "tests_e2e" / "003_forms" / "test_access.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
# @features forms
# @dimensions owner-restricted
def test_owner():
    form.builder.restrict_to_owner()
""".lstrip()
    )
    source = source_symbol(
        "src/script/views/formSettings.mjs",
        "FormSettings._input",
        True,
        test_scaffolds=["testing/resources/form.py::Builder.restrict_to_owner"],
        features=["forms"],
        dimensions=["owner-restricted"],
    )
    scaffold = source_symbol(
        "testing/resources/form.py",
        "Builder.restrict_to_owner",
        None,
    )
    tests = {
        owner: make_test_case(
            owner,
            runnable=True,
            features=["forms"],
            dimensions=["owner-restricted"],
            path="tests_e2e/003_forms/test_access.py",
            qualname="test_owner",
            lineno=3,
        )
    }

    report = traceability.classify(
        [source], tests, scaffold_symbols=[scaffold], repo_root=tmp_path
    )

    assert report.summary["testable_without_tests"] == 0
    assert report.summary["sources_with_known_tests"] == 1
    assert report.summary["source_test_links_known"] == 1
    assert report.summary["referenced_tests"] == 1
    assert report.summary["stale_test_references"] == 0
    assert report.feature_dimension_gaps == []
    assert report.orphan_runnable_tests == []


def test_classify_reports_missing_test_scaffolds_as_stale_references(tmp_path):
    selected = "tests_e2e/003_forms/test_access.py::test_owner"
    missing = source_symbol(
        "src/script/views/formSettings.mjs",
        "FormSettings._input",
        True,
        test_scaffolds=["testing/resources/form.py::Builder.missing"],
    )
    tests = {selected: make_test_case(selected, runnable=True)}

    report = traceability.classify(
        [missing], tests, scaffold_symbols=[], repo_root=tmp_path
    )
    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)

    assert report.summary["testable_without_tests"] == 0
    assert report.summary["stale_test_references"] == 1
    assert report.stale_test_references[0]["tests"] == [
        "@scaffolding testing/resources/form.py::Builder.missing"
    ]
    assert "[ERROR]" in formatted
    assert "@scaffolding testing/resources/form.py::Builder.missing" in markdown


def test_classify_can_suppress_orphan_runnable_tests():
    selected = "tests_unit/test_trace.py::test_selected"
    orphan = "tests_unit/test_trace.py::test_orphan"
    symbols = [source_symbol("pkg/source.py", "covered", True, tests=[selected])]
    tests = {
        selected: make_test_case(
            selected, runnable=True, todos=["finish selected edge case"]
        ),
        orphan: make_test_case(orphan, runnable=True, todos=["unrelated todo"]),
    }

    report = traceability.classify(symbols, tests, suppress_orphan_tests=True)
    formatted = traceability.format_report(report)

    assert report.summary["orphan_tests_suppressed"] is True
    assert report.summary["orphan_runnable_tests"] == 0
    assert report.orphan_runnable_tests == []
    assert report.summary["test_todos"] == 1
    assert report.test_todos[0]["todos"] == ["finish selected edge case"]
    assert "selected tests not referenced" not in formatted
    assert orphan not in formatted


def test_classify_reports_broad_source_owners():
    selected = "tests_unit/test_trace.py::test_selected"
    broad_class = source_symbol(
        "pkg/source.py",
        "Broad",
        True,
        tests=[selected],
        features=["submission"],
        dimensions=["a", "b", "c", "d", "e", "f"],
        kind="class",
    )
    broad_property = source_symbol(
        "pkg/source.py",
        "Widget.broad_property",
        True,
        tests=[selected],
        features=["submission"],
        dimensions=["a", "b", "c", "d", "e", "f"],
        kind="method",
        subkind="property",
    )
    report = traceability.classify(
        [broad_class, broad_property],
        {selected: make_test_case(selected, runnable=True)},
    )
    formatted = traceability.format_report(report, verbose=True)
    markdown = traceability.report_to_markdown(report, verbose=True)

    assert report.summary["broad_source_owners"] == 2
    assert report.summary["broad_source_owner_kinds"] == {
        "class": 1,
        "property": 1,
    }
    assert {item["source"].qualname for item in report.broad_source_owners} == {
        broad_class.qualname,
        broad_property.qualname,
    }
    assert "Annotated normally ignored symbols included" not in formatted
    assert "Broad source owners: 2" in formatted
    assert "broad source owners by kind: class=1, property=1" in formatted
    assert "kind=class" in formatted
    assert "kind=property" in formatted
    assert "Annotated normally ignored symbols included" not in markdown
    assert "Broad source owners" in markdown
    assert "Broad source owners by kind" in markdown


def test_markdown_report_can_be_saved(tmp_path):
    selected = "tests_unit/test_trace.py::test_selected"
    symbols = [source_symbol("pkg/source.py", "covered", True, tests=[selected])]
    tests = {selected: make_test_case(selected, runnable=True)}
    report = traceability.classify(symbols, tests)
    report.summary["source_scope"] = "configured source roots"

    markdown = traceability.report_to_markdown(report)
    saved_path = traceability.save_markdown_report(
        report, tmp_path, Path("reports/traceability.md")
    )

    assert "# Traceability Report" in markdown
    assert "| Source decisions | 1/1 |" in markdown
    assert "### Missing @testable metadata" not in markdown
    assert "_No error/warning traceability findings._" in markdown
    assert saved_path == tmp_path / "reports" / "traceability.md"
    assert saved_path.read_text() == markdown + "\n"


def test_markdown_report_unlinks_existing_file_before_save(tmp_path, monkeypatch):
    report = traceability.classify([], {})
    report.summary["source_scope"] = "configured source roots"
    output_path = tmp_path / "reports" / "traceability.md"
    output_path.parent.mkdir()
    output_path.write_text("stale report")
    unlink_calls = []
    original_unlink = Path.unlink
    original_write_text = Path.write_text

    def tracking_unlink(self, *args, **kwargs):
        if self == output_path:
            unlink_calls.append(self.exists())
        return original_unlink(self, *args, **kwargs)

    def tracking_write_text(self, *args, **kwargs):
        if self == output_path:
            assert unlink_calls == [True]
            assert not self.exists()
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", tracking_unlink)
    monkeypatch.setattr(Path, "write_text", tracking_write_text)

    saved_path = traceability.save_markdown_report(
        report, tmp_path, Path("reports/traceability.md")
    )

    assert saved_path == output_path
    assert output_path.read_text().startswith("# Traceability Report")


def test_default_markdown_report_path_uses_source_scope():
    report = traceability.classify([], {})
    report.summary["source_scope"] = "src/script/login/forms.mjs"

    assert traceability.default_markdown_report_path(report) == Path(
        "reports/traceability-src-script-login-forms-mjs.md"
    )


def test_build_report_source_flag_scopes_to_single_file(tmp_path, monkeypatch):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude: []
""".lstrip()
    )
    target = tmp_path / "outside_roots" / "target.py"
    target.parent.mkdir()
    target.write_text(
        """
# @testable false
# @covered-by src/other.py::other
def target():
    pass


def unannotated():
    pass
""".lstrip()
    )
    other = tmp_path / "src" / "other.py"
    other.parent.mkdir()
    other.write_text(
        """
def other():
    pass
""".lstrip()
    )
    monkeypatch.setattr(traceability, "collect_tests", lambda repo_root, roots=(): {})

    report = traceability.build_report(
        tmp_path, Path("traceability.yaml"), Path("outside_roots/target.py")
    )

    assert report.summary["source_scope"] == "outside_roots/target.py"
    assert report.summary["sources"] == 2
    assert report.summary["missing_testable"] == 1
    assert report.summary["covered_by_missing"] == 0
    assert report.summary["source_source_links"] == 1
    assert report.summary["source_source_links_known"] == 1
    assert report.summary["source_source_links_stale"] == 0
    assert report.missing_testable[0].qualname == "unannotated"


def test_build_report_source_flag_scopes_to_directory(tmp_path, monkeypatch):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude:
  - "src/ignore/**"
""".lstrip()
    )
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "alpha.py").write_text(
        """
# @testable infrastructure
def alpha():
    pass
""".lstrip()
    )
    (source_dir / "beta.py").write_text(
        """
def beta():
    pass
""".lstrip()
    )
    ignored = source_dir / "ignore"
    ignored.mkdir()
    (ignored / "hidden.py").write_text(
        """
def hidden():
    pass
""".lstrip()
    )
    monkeypatch.setattr(traceability, "collect_tests", lambda repo_root, roots=(): {})

    report = traceability.build_report(tmp_path, Path("traceability.yaml"), Path("src"))

    assert report.summary["source_scope"] == "src"
    assert report.summary["sources"] == 2
    assert {symbol.qualname for symbol in report.missing_testable} == {"beta"}


def test_build_report_source_flag_scopes_to_multiple_files(tmp_path, monkeypatch):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude: []
""".lstrip()
    )
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "alpha.py").write_text(
        """
# @testable infrastructure
def alpha():
    pass
""".lstrip()
    )
    (source_dir / "beta.py").write_text(
        """
def beta():
    pass
""".lstrip()
    )
    (source_dir / "gamma.py").write_text(
        """
def gamma():
    pass
""".lstrip()
    )
    monkeypatch.setattr(traceability, "collect_tests", lambda repo_root, roots=(): {})

    report = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        source_paths=[Path("src/alpha.py"), Path("src/beta.py")],
    )

    assert report.summary["source_scope"] == "src/alpha.py, src/beta.py"
    assert report.summary["source_paths"] == ["src/alpha.py", "src/beta.py"]
    assert report.summary["sources"] == 2
    assert {symbol.qualname for symbol in report.missing_testable} == {"beta"}
    assert traceability.default_markdown_report_path(report) == Path(
        "reports/traceability-src-alpha-py-plus-1-more.md"
    )


def test_build_report_source_flag_deduplicates_overlapping_paths(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude: []
""".lstrip()
    )
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "alpha.py").write_text(
        """
def alpha():
    pass
""".lstrip()
    )
    (source_dir / "beta.py").write_text(
        """
def beta():
    pass
""".lstrip()
    )
    monkeypatch.setattr(traceability, "collect_tests", lambda repo_root, roots=(): {})

    report = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        source_paths=[Path("src"), Path("src/alpha.py")],
    )

    assert report.summary["sources"] == 2
    assert [symbol.qualname for symbol in report.missing_testable] == [
        "alpha",
        "beta",
    ]


def test_build_report_includes_annotated_sources_outside_roots_without_missing_metadata(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
annotated_source_roots:
  - outside/explicit.py
exclude: []
""".lstrip()
    )
    route = tmp_path / "src" / "route.py"
    route.parent.mkdir()
    route.write_text(
        """
# @testable false
# @covered-by outside/covered.py::covered_render
def route():
    pass
""".lstrip()
    )
    explicit = tmp_path / "outside" / "explicit.py"
    explicit.parent.mkdir()
    explicit.write_text(
        """
# @testable true
# @tests tests_unit/test_sample.py::test_explicit
# @features search
# @dimensions query-display
def explicit_render():
    pass


def unannotated_explicit_helper():
    pass
""".lstrip()
    )
    covered = tmp_path / "outside" / "covered.py"
    covered.write_text(
        """
# @testable true
# @tests tests_unit/test_sample.py::test_covered
# @features search
# @dimensions result-title
def covered_render():
    pass


def unannotated_covered_helper():
    pass
""".lstrip()
    )
    tests = {
        "tests_unit/test_sample.py::test_explicit": traceability.TestCase(
            nodeid="tests_unit/test_sample.py::test_explicit",
            runnable=True,
            unfinished=False,
            metadata=traceability.Metadata(
                features=["search"], dimensions=["query-display"]
            ),
        ),
        "tests_unit/test_sample.py::test_covered": traceability.TestCase(
            nodeid="tests_unit/test_sample.py::test_covered",
            runnable=True,
            unfinished=False,
            metadata=traceability.Metadata(
                features=["search"], dimensions=["result-title"]
            ),
        ),
    }
    monkeypatch.setattr(traceability, "collect_tests", lambda repo_root, roots=(): tests)

    report = traceability.build_report(tmp_path, Path("traceability.yaml"))
    source_ids = {
        symbol.source_id
        for section in (
            report.missing_testable,
            report.testable_without_tests,
            report.unfinished_coverage,
        )
        for symbol in section
    }
    source_ids.update(
        item["source"].source_id for item in report.feature_dimension_gaps
    )

    assert report.summary["sources"] == 3
    assert report.summary["missing_testable"] == 0
    assert report.summary["covered_by_missing"] == 0
    assert report.summary["sources_with_known_tests"] == 2
    assert "outside/explicit.py::explicit_render" not in source_ids
    assert "outside/covered.py::covered_render" not in source_ids
    assert "unannotated_explicit_helper" not in {
        symbol.qualname for symbol in report.missing_testable
    }


def test_annotated_source_roots_can_explicitly_include_excluded_files(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
annotated_source_roots:
  - config/switcher.py
exclude:
  - "**/config/**"
""".lstrip()
    )
    source = tmp_path / "src" / "route.py"
    source.parent.mkdir()
    source.write_text(
        """
# @testable true
# @tests tests_unit/test_sample.py::test_route
# @features server
# @dimensions route
def route():
    pass
""".lstrip()
    )
    explicit = tmp_path / "config" / "switcher.py"
    explicit.parent.mkdir()
    explicit.write_text(
        """
# @testable true
# @tests tests_unit/test_sample.py::test_switcher
# @features setup
# @dimensions gcloud-config
def config_gcloud():
    pass


def unannotated_helper():
    pass
""".lstrip()
    )
    tests = {
        "tests_unit/test_sample.py::test_route": make_test_case(
            "tests_unit/test_sample.py::test_route",
            runnable=True,
            features=["server"],
            dimensions=["route"],
        ),
        "tests_unit/test_sample.py::test_switcher": make_test_case(
            "tests_unit/test_sample.py::test_switcher",
            runnable=True,
            features=["setup"],
            dimensions=["gcloud-config"],
        ),
    }
    monkeypatch.setattr(traceability, "collect_tests", lambda repo_root, roots=(): tests)

    loaded_config = traceability.load_config(Path("traceability.yaml"), tmp_path)
    python_files, _ = traceability.discover_source_files(loaded_config, tmp_path)
    report = traceability.build_report(tmp_path, Path("traceability.yaml"))

    assert "config/switcher.py" not in {
        traceability.relpath(path, tmp_path) for path in python_files
    }
    assert report.summary["sources"] == 2
    assert report.summary["sources_with_known_tests"] == 2
    assert "config/switcher.py::unannotated_helper" not in {
        symbol.source_id for symbol in report.missing_testable
    }


def test_build_report_test_flag_reports_reverse_traceability(tmp_path, monkeypatch):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude: []
""".lstrip()
    )
    source = tmp_path / "src" / "mod.py"
    source.parent.mkdir()
    source.write_text(
        """
# @testable true
# @tests tests_unit/test_sample.py::test_covered
# @features submission
# @dimensions db
def covered():
    pass
""".lstrip()
    )
    test_file = tmp_path / "testing" / "tests_unit" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
from src.mod import covered


# @features submission
# @dimensions db
# @template home/sample.html::create
# @todo cover blank submission
def test_covered():
    covered()
""".lstrip()
    )
    nodeid = "tests_unit/test_sample.py::test_covered"
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            nodeid: traceability.TestCase(
                nodeid=nodeid,
                runnable=True,
                unfinished=False,
                metadata=traceability.Metadata(
                    features=["submission"],
                    dimensions=["db"],
                    templates=["home/sample.html::create"],
                    todos=["cover blank submission"],
                ),
                path="tests_unit/test_sample.py",
                qualname="test_covered",
                lineno=7,
            )
        },
    )

    report = traceability.build_report(
        tmp_path, Path("traceability.yaml"), test_target="test_sample.py::test_covered"
    )
    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)

    assert report.summary["test_scope"] == "test_sample.py::test_covered"
    assert report.summary["focused_tests"] == 1
    assert report.summary["focused_tests_annotated"] == 1
    assert report.focused_source_references[0]["source"].qualname == "covered"
    assert report.focused_test_mappings[0]["pairs"][0]["name"] == "submission:db"
    assert (
        report.focused_test_mappings[0]["pairs"][0]["sources"][0].qualname == "covered"
    )
    assert report.focused_source_tag_gaps == []
    assert "Traceability Test Focus Report" in formatted
    assert "Focused test feature:dimension mappings: 1" in formatted
    assert "source: src/mod.py::covered:5" in formatted
    assert "Annotated tests missing feature:dimension source tags" not in formatted
    assert "Source Tag-Overlap Candidates" not in markdown
    assert "Imported source files" not in formatted
    assert "home/sample.html::create" in formatted
    assert "# Traceability Test Focus Report" in markdown


def test_build_report_test_flag_maps_template_backed_source_pairs(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude: []
""".lstrip()
    )
    source = tmp_path / "src" / "results.mjs"
    source.parent.mkdir()
    source.write_text(
        """
export class Results {
    /**
     * @testable true
     * @tests tests_e2e/009_search/test_search.py::test_result_titles
     * @features search
     * @dimensions url-state
     * @template search/results.html::search_results
     */
    handleFacetClick() {}
}
""".lstrip()
    )
    nodeid = "tests_e2e/009_search/test_search.py::test_result_titles"
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            nodeid: traceability.TestCase(
                nodeid=nodeid,
                runnable=True,
                unfinished=False,
                metadata=traceability.Metadata(
                    features=["search"],
                    dimensions=["result-title"],
                    templates=["search/results.html::search_results"],
                ),
                path="tests_e2e/009_search/test_search.py",
                qualname="test_result_titles",
                lineno=5,
            )
        },
    )

    report = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        test_target="test_search.py::test_result_titles",
    )
    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)

    pair = report.focused_test_mappings[0]["pairs"][0]

    assert report.summary["focused_source_tag_gaps"] == 0
    assert pair["name"] == "search:result-title"
    assert pair["sources"] == []
    assert pair["template_sources"][0]["source"].qualname == "Results.handleFacetClick"
    assert pair["template_sources"][0]["templates"] == [
        "search/results.html::search_results"
    ]
    assert "template-backed source: src/results.mjs::Results.handleFacetClick" in (
        formatted
    )
    assert "template-backed source" in markdown


def test_build_report_test_flag_maps_sources_through_test_scaffolds(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
test_scaffold_roots:
  - testing/resources
exclude: []
""".lstrip()
    )
    source = tmp_path / "src" / "formSettings.mjs"
    source.parent.mkdir()
    source.write_text(
        """
export class FormSettings {
    /**
     * @testable true
     * @scaffolding testing/resources/form.py::Builder.restrict_to_owner
     * @features forms
     * @dimensions owner-restricted
     */
    _input() {}
}
""".lstrip()
    )
    scaffold = tmp_path / "testing" / "resources" / "form.py"
    scaffold.parent.mkdir(parents=True)
    scaffold.write_text(
        """
class Builder:
    def restrict_to_owner(self):
        pass
""".lstrip()
    )
    test_file = tmp_path / "testing" / "tests_e2e" / "003_forms" / "test_access.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
# @features forms
# @dimensions owner-restricted
def test_owner():
    form.builder.restrict_to_owner()
""".lstrip()
    )
    nodeid = "tests_e2e/003_forms/test_access.py::test_owner"
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            nodeid: traceability.TestCase(
                nodeid=nodeid,
                runnable=True,
                unfinished=False,
                metadata=traceability.Metadata(
                    features=["forms"],
                    dimensions=["owner-restricted"],
                ),
                path="tests_e2e/003_forms/test_access.py",
                qualname="test_owner",
                lineno=3,
            )
        },
    )

    report = traceability.build_report(
        tmp_path, Path("traceability.yaml"), test_target="test_access.py::test_owner"
    )
    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)

    assert report.summary["focused_source_references"] == 1
    assert report.focused_source_references[0]["source"].qualname == (
        "FormSettings._input"
    )
    pair = report.focused_test_mappings[0]["pairs"][0]
    assert pair["name"] == "forms:owner-restricted"
    assert pair["sources"][0].qualname == "FormSettings._input"
    assert "via scaffold" not in formatted
    assert "via scaffold" not in markdown


def test_build_report_test_flag_reports_missing_source_tag_pairs(tmp_path, monkeypatch):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude: []
""".lstrip()
    )
    source = tmp_path / "src" / "mod.py"
    source.parent.mkdir()
    source.write_text(
        """
# @testable true
# @features submission
# @dimensions db
def unlinked_submission_owner():
    pass


# @testable true
# @tests tests_unit/test_sample.py::test_covered
# @features submission
# @dimensions db
def covered():
    pass


# @testable true
# @features profile
# @dimensions desktop
def unrelated_profile_owner():
    pass
""".lstrip()
    )
    test_file = tmp_path / "testing" / "tests_unit" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
from src.mod import covered


# @features submission
# @dimensions db api
def test_covered():
    covered()
""".lstrip()
    )
    nodeid = "tests_unit/test_sample.py::test_covered"
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            nodeid: traceability.TestCase(
                nodeid=nodeid,
                runnable=True,
                unfinished=False,
                metadata=traceability.Metadata(
                    features=["submission"],
                    dimensions=["db", "api"],
                ),
                path="tests_unit/test_sample.py",
                qualname="test_covered",
                lineno=6,
            )
        },
    )

    report = traceability.build_report(
        tmp_path, Path("traceability.yaml"), test_target="test_sample.py::test_covered"
    )
    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)

    assert report.summary["focused_source_tag_gaps"] == 1
    assert report.summary["focused_source_tag_gap_tests"] == 1
    assert report.focused_test_mappings[0]["pairs"][0]["name"] == "submission:api"
    assert report.focused_test_mappings[0]["pairs"][0]["sources"] == []
    assert (
        report.focused_test_mappings[0]["pairs"][1]["sources"][0].qualname == "covered"
    )
    assert report.focused_source_tag_gaps[0]["missing"] == ["submission:api"]
    assert "submission:db" in markdown
    assert "missing source tag: submission:api" in formatted
    assert "## Annotated Tests Missing Feature:Dimension Source Tags" in markdown
    assert "unlinked_submission_owner" not in formatted
    assert "Source Tag-Overlap Candidates" not in markdown


def test_build_report_feature_dimension_flag_lists_code_tests_and_templates(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude: []
""".lstrip()
    )
    source = tmp_path / "src" / "documents.py"
    source.parent.mkdir()
    save_nodeid = "tests_e2e/004_projects/test_document.py::test_document_save"
    load_nodeid = "tests_e2e/004_projects/test_document.py::test_document_load"
    source.write_text(
        f"""
# @testable true
# @tests {save_nodeid}
# @features document
# @dimensions save
# @template pages/document.html::editor
def save_document():
    pass


# @testable true
# @tests {load_nodeid}
# @features document
# @dimensions load
# @template pages/document.html::editor
def load_document():
    pass
""".lstrip()
    )
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            save_nodeid: make_test_case(
                save_nodeid,
                runnable=True,
                features=["document"],
                dimensions=["save"],
                templates=["pages/document.html::editor"],
                path="tests_e2e/004_projects/test_document.py",
                qualname="test_document_save",
                lineno=5,
            ),
            load_nodeid: make_test_case(
                load_nodeid,
                runnable=True,
                features=["document"],
                dimensions=["load"],
                templates=["pages/document.html::editor"],
                path="tests_e2e/004_projects/test_document.py",
                qualname="test_document_load",
                lineno=12,
            ),
        },
    )

    report = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        feature_dimension="document:save",
    )
    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)

    assert report.summary["feature_dimension_scope"] == "document:save"
    assert report.summary["feature_dimension_sources"] == 1
    assert report.summary["feature_dimension_tests"] == 1
    assert report.summary["feature_dimension_templates"] == 1
    assert report.summary["feature_dimension_source_test_links"] == 1
    assert report.feature_dimension_sources[0].qualname == "save_document"
    assert report.feature_dimension_tests[0].nodeid == save_nodeid
    assert report.feature_dimension_templates[0]["template"] == (
        "pages/document.html::editor"
    )
    assert traceability.default_markdown_report_path(report) == Path(
        "reports/traceability-feature-dimension-document-save.md"
    )

    assert "Traceability Feature:Dimension Report" in formatted
    assert "pair: document:save" in formatted
    assert "src/documents.py::save_document" in formatted
    assert save_nodeid in formatted
    assert "pages/document.html::editor" in formatted
    assert "load_document" not in formatted
    assert load_nodeid not in formatted

    assert "# Traceability Feature:Dimension Report" in markdown
    assert "## Source Symbols Tagged `document:save`" in markdown
    assert "`src/documents.py::save_document" in markdown
    assert f"`{save_nodeid}`" in markdown
    assert "`pages/document.html::editor`" in markdown


def test_build_report_test_flag_suggests_same_file_sources_when_requested(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src
exclude: []
""".lstrip()
    )
    source = tmp_path / "src" / "mod.py"
    source.parent.mkdir()
    source.write_text(
        """
# @testable true
# @tests tests_unit/test_sample.py::test_covered
# @features submission
# @dimensions db
def covered():
    pass


# @testable true
# @features submission
# @dimensions db fallback
def nearby_candidate():
    pass


# @testable true
# @features submission
# @dimensions api
def missing_api_candidate():
    pass


# @testable true
# @features submission
# @dimensions fallback
def feature_only_candidate():
    pass
""".lstrip()
    )
    nodeid = "tests_unit/test_sample.py::test_covered"
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            nodeid: traceability.TestCase(
                nodeid=nodeid,
                runnable=True,
                unfinished=False,
                metadata=traceability.Metadata(
                    features=["submission"],
                    dimensions=["db", "api"],
                ),
                path="tests_unit/test_sample.py",
                qualname="test_covered",
                lineno=1,
            )
        },
    )

    plain = traceability.build_report(
        tmp_path, Path("traceability.yaml"), test_target="test_sample.py::test_covered"
    )
    suggested = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        test_target="test_sample.py::test_covered",
        suggest_sources=True,
    )

    assert plain.focused_source_suggestions == []
    assert suggested.summary["focused_source_suggestions"] == 2
    assert suggested.summary["focused_source_suggestions_likely_missing"] == 1
    assert suggested.summary["focused_source_suggestions_additional"] == 1
    assert [
        item["source"].qualname for item in suggested.focused_source_suggestions
    ] == [
        "missing_api_candidate",
        "nearby_candidate",
    ]
    assert suggested.focused_source_suggestions[0]["category"] == "likely_missing"
    assert suggested.focused_source_suggestions[0]["missing_pairs"] == [
        "submission:api"
    ]
    assert suggested.focused_source_suggestions[1]["category"] == "additional"
    formatted = traceability.format_report(suggested, verbose=True)
    markdown = traceability.report_to_markdown(suggested, verbose=True)
    assert "Likely missing sources: 1" in formatted
    assert "Additional source candidates: 1" in formatted
    assert "fills missing pairs: submission:api" in formatted
    assert "feature_only_candidate" not in formatted
    assert "## Likely Missing Sources" in markdown
    assert "## Additional Source Candidates" in markdown


def test_build_report_test_flag_suggests_contextual_sources_when_requested(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - lagniappe/web/routes
exclude: []
""".lstrip()
    )
    source = tmp_path / "lagniappe/web/routes/projects/main.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
# @testable true
# @features projects
# @dimensions update
def update():
    pass
""".lstrip()
    )
    test_file = tmp_path / "testing/tests_e2e/004_projects/test_004b_info.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
# @template projects/info.html::info_form
def test_project_info_update():
    pass
""".lstrip()
    )
    nodeid = "tests_e2e/004_projects/test_004b_info.py::test_project_info_update"
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            nodeid: traceability.TestCase(
                nodeid=nodeid,
                runnable=True,
                unfinished=False,
                metadata=traceability.Metadata(
                    templates=["projects/info.html::info_form"],
                    features=["projects"],
                    dimensions=["update"],
                ),
                path="tests_e2e/004_projects/test_004b_info.py",
                qualname="test_project_info_update",
                lineno=2,
            )
        },
    )

    report = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        test_target="test_004b_info.py::test_project_info_update",
        suggest_sources=True,
    )

    assert report.summary["focused_source_suggestions"] == 1
    assert report.summary["focused_source_suggestions_likely_missing"] == 1
    assert report.focused_source_suggestions[0]["source"].qualname == "update"
    assert report.focused_source_suggestions[0]["missing_pairs"] == ["projects:update"]
    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)
    assert "Suggested source candidates: 1" in formatted
    assert "## Likely Missing Sources" in markdown


def test_build_report_test_flag_suggests_referenced_sources_for_sibling_gaps(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - lagniappe/web/routes
exclude: []
""".lstrip()
    )
    source = tmp_path / "lagniappe/web/routes/projects/main.py"
    source.parent.mkdir(parents=True)
    existing = "tests_unit/test_sample.py::test_existing"
    missing = "tests_unit/test_sample.py::test_missing"
    source.write_text(
        f"""
# @testable true
# @tests {existing}
# @features projects
# @dimensions metadata
def create_update_data():
    pass
""".lstrip()
    )
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            existing: make_test_case(
                existing,
                runnable=True,
                features=["projects"],
                dimensions=["metadata"],
                path="tests_unit/test_sample.py",
                qualname="test_existing",
                lineno=1,
            ),
            missing: make_test_case(
                missing,
                runnable=True,
                features=["projects"],
                dimensions=["metadata"],
                path="tests_unit/test_sample.py",
                qualname="test_missing",
                lineno=5,
            ),
        },
    )

    report = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        test_target="tests_unit/test_sample.py",
        suggest_sources=True,
    )

    assert report.summary["focused_source_suggestions"] == 1
    assert report.summary["focused_source_suggestions_likely_missing"] == 1
    assert report.focused_source_suggestions[0]["source"].qualname == (
        "create_update_data"
    )
    assert report.focused_source_suggestions[0]["missing_pairs"] == [
        "projects:metadata"
    ]


def test_build_report_source_flag_suggests_candidate_tests_when_requested(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - lagniappe/core/properties
exclude: []
""".lstrip()
    )
    source = tmp_path / "lagniappe/core/properties/common_assets.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
def add_image(image):
    return image.url
""".lstrip()
    )
    test_file = tmp_path / "testing/tests_e2e/004_projects/test_document.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
# lagniappe/core/properties/common_assets.py
# @features editor
# @dimensions image-upload
def test_add_image():
    document.add_image(upload)
""".lstrip()
    )
    nodeid = "tests_e2e/004_projects/test_document.py::test_add_image"
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            nodeid: make_test_case(
                nodeid,
                runnable=True,
                features=["editor"],
                dimensions=["image-upload"],
                path="tests_e2e/004_projects/test_document.py",
                qualname="test_add_image",
                lineno=4,
            )
        },
    )

    plain = traceability.build_report(
        tmp_path, Path("traceability.yaml"), source_path=source
    )
    suggested = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        source_path=source,
        suggest_sources=True,
    )

    assert plain.source_test_suggestions == []
    assert suggested.summary["source_test_suggestions"] == 1
    assert suggested.summary["source_test_suggestions_likely_existing"] == 1
    assert suggested.source_test_suggestions[0]["source"].qualname == "add_image"
    assert suggested.source_test_suggestions[0]["tests"][0].nodeid == nodeid
    formatted = traceability.format_report(suggested, verbose=True)
    markdown = traceability.report_to_markdown(suggested, verbose=True)
    assert "Suggested test candidates: 1" in formatted
    assert "Likely matching tests: 1" in formatted
    assert nodeid in formatted
    assert "## Suggested test candidates" in markdown
    assert "## Likely Matching Tests" in markdown


def test_source_suggestions_suppress_configured_generic_javascript_names(
    tmp_path, monkeypatch
):
    config = tmp_path / "traceability.yaml"
    config.write_text(
        """
source_roots:
  - src/script
exclude: []
suggestions:
  javascript_generic_symbols:
    - update
  javascript_generic_tokens:
    - update
    - value
  strong_match_kinds:
    - pair
    - feature
    - dimension
    - path
    - template
""".lstrip()
    )
    source = tmp_path / "src/script/widgets/tableVisibility.mjs"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
export function update(value) {
    return value;
}

export function visibleColumns() {
    return "table visibility columns";
}
""".lstrip()
    )
    update_test = "tests_e2e/007_categories/test_table.py::test_update_widget"
    columns_test = (
        "tests_e2e/007_categories/test_table.py::test_table_visibility_columns"
    )
    test_file = tmp_path / "testing/tests_e2e/007_categories/test_table.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
def test_update_widget():
    widget.update("changed")


def test_table_visibility_columns():
    assert "table visibility columns"
""".lstrip()
    )
    monkeypatch.setattr(
        traceability,
        "collect_tests",
        lambda repo_root, roots=(): {
            update_test: make_test_case(
                update_test,
                runnable=True,
                path="tests_e2e/007_categories/test_table.py",
                qualname="test_update_widget",
                lineno=1,
            ),
            columns_test: make_test_case(
                columns_test,
                runnable=True,
                path="tests_e2e/007_categories/test_table.py",
                qualname="test_table_visibility_columns",
                lineno=5,
            ),
        },
    )

    report = traceability.build_report(
        tmp_path,
        Path("traceability.yaml"),
        source_path=source,
        suggest_sources=True,
    )

    assert [item["source"].qualname for item in report.source_test_suggestions] == [
        "visibleColumns"
    ]
    assert report.source_test_suggestions[0]["tests"][0].nodeid == columns_test


def test_test_focus_report_does_not_truncate_focused_tests():
    tests = {
        f"tests_unit/test_many.py::test_case_{index:02d}": make_test_case(
            f"tests_unit/test_many.py::test_case_{index:02d}",
            runnable=True,
            features=["submission"],
            dimensions=[f"dim-{index:02d}"],
        )
        for index in range(traceability.TEXT_SECTION_LIMIT + 2)
    }
    focused_tests = sorted(tests.values(), key=lambda test: test.nodeid)
    report = traceability.classify([], tests, suppress_orphan_tests=True)

    traceability.attach_test_focus(
        report, [], tests, focused_tests, "tests_unit/test_many.py", Path()
    )

    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)

    assert "test_case_11" in formatted
    assert "submission:dim-11" in formatted
    assert "... 2 more" not in formatted
    assert "test_case_11" in markdown
    assert "submission:dim-11" in markdown
    assert "_... 2 more_" not in markdown


def test_traceability_report_is_concise_by_default_and_verbose_is_exhaustive():
    symbols = [
        source_symbol("pkg/source.py", f"missing_{index:02d}", None)
        for index in range(traceability.TEXT_SECTION_LIMIT + 2)
    ]
    report = traceability.classify(symbols, {})
    report.summary["source_scope"] = "configured source roots"

    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)
    verbose = traceability.format_report(report, verbose=True)
    verbose_markdown = traceability.report_to_markdown(report, verbose=True)

    assert "missing_11" not in formatted
    assert "... 2 more" in formatted
    assert "Stale test references: 0" not in formatted
    assert "missing_11" not in markdown
    assert "2 more" in markdown
    assert "### Stale test references" not in markdown
    assert "missing_11" in verbose
    assert "missing_11" in verbose_markdown


def test_report_compacts_planned_and_todo_roadmap_by_default():
    symbols = [
        source_symbol(
            "pkg/source.py",
            "planned_widget",
            True,
            tests=["testing/tests_e2e/005_pages/test_005z_gap.py::test_page_gap"],
        ),
        source_symbol(
            "pkg/source.py",
            "planned_task",
            True,
            tests=["testing/tests_e2e/006_tasks/test_006z_gap.py::test_task_gap"],
        ),
    ]
    tests = {
        symbols[0].metadata.tests[0]: make_test_case(
            symbols[0].metadata.tests[0],
            runnable=False,
            todos=["cover page gap"],
        ),
        symbols[1].metadata.tests[0]: make_test_case(
            symbols[1].metadata.tests[0],
            runnable=False,
            todos=["cover task gap"],
        ),
    }
    report = traceability.classify(symbols, tests)
    report.summary["source_scope"] = "pkg"

    formatted = traceability.format_report(report)
    markdown = traceability.report_to_markdown(report)

    assert "Coverage references unfinished tests" not in formatted
    assert "Test TODOs by test folder" not in formatted
    assert "pkg/source.py::planned_widget" not in formatted
    assert "test_page_gap" not in formatted

    assert "Coverage references unfinished tests" not in markdown
    assert "Test TODOs by test folder" not in markdown
    assert "`pkg/source.py::planned_widget" not in markdown
    assert "test_page_gap" not in markdown

    verbose = traceability.format_report(report, verbose=True)
    verbose_markdown = traceability.report_to_markdown(report, verbose=True)

    assert "Coverage references unfinished tests: 2" in verbose
    assert "pkg/source.py::planned_widget:1" in verbose
    assert "Test TODOs: 2" in verbose
    assert "test_page_gap" in verbose

    assert "`pkg/source.py::planned_widget:1`" in verbose_markdown
    assert "`testing/tests_e2e/005_pages/test_005z_gap.py::test_page_gap`" in (
        verbose_markdown
    )


def test_missing_metadata_report_groups_unannotated_class_children():
    symbols = [
        source_symbol("pkg/source.py", "Widget", None, kind="class"),
        source_symbol("pkg/source.py", "Widget.value", None, kind="method"),
        source_symbol("pkg/source.py", "Widget.render", None, kind="method"),
        source_symbol("pkg/source.py", "standalone", None, kind="function"),
    ]
    report = traceability.classify(symbols, {})
    report.summary["source_scope"] = "configured source roots"

    formatted = traceability.format_report(report, verbose=True)
    markdown = traceability.report_to_markdown(report, verbose=True)

    assert "pkg/source.py::Widget:1 (unannotated children: 2)" in formatted
    assert "pkg/source.py::standalone:1" in formatted
    assert "pkg/source.py::Widget.value" not in formatted
    assert "pkg/source.py::Widget.render" not in formatted
    assert "`pkg/source.py::Widget:1` (unannotated children: 2)" in markdown
    assert "`pkg/source.py::standalone:1`" in markdown
    assert "pkg/source.py::Widget.value" not in markdown


def test_parse_args_accepts_multiple_source_paths():
    args = traceability.parse_args(
        ["--source", "src/alpha.py", "src/beta.py", "--source", "src/gamma.py"]
    )

    assert traceability.parsed_source_paths(args) == [
        Path("src/alpha.py"),
        Path("src/beta.py"),
        Path("src/gamma.py"),
    ]


def test_changed_tests_are_limited_to_edited_function_ranges():
    path = "tests_unit/test_sample.py"
    tests = {
        f"{path}::test_first": traceability.TestCase(
            nodeid=f"{path}::test_first",
            runnable=True,
            unfinished=False,
            metadata=traceability.Metadata(),
            path=path,
            qualname="test_first",
            lineno=10,
            start_lineno=8,
            end_lineno=16,
        ),
        f"{path}::test_second": traceability.TestCase(
            nodeid=f"{path}::test_second",
            runnable=True,
            unfinished=False,
            metadata=traceability.Metadata(),
            path=path,
            qualname="test_second",
            lineno=24,
            start_lineno=20,
            end_lineno=32,
        ),
    }
    changed_path = f"testing/{path}"

    focused = traceability.changed_tests_for_paths(
        tests,
        [changed_path],
        {changed_path: [(22, 22)]},
    )

    assert [test.qualname for test in focused] == ["test_second"]
    assert traceability.changed_tests_for_paths(
        tests,
        [changed_path],
        {changed_path: None},
    ) == list(tests.values())

    sources = [
        source_symbol("pkg/sample.py", "first", True),
        source_symbol("pkg/sample.py", "second", True),
    ]
    sources[0].start_lineno = 5
    sources[0].lineno = 7
    sources[0].end_lineno = 14
    sources[1].start_lineno = 18
    sources[1].lineno = 20
    sources[1].end_lineno = 30

    focused_sources = traceability.changed_sources_for_paths(
        sources,
        ["pkg/sample.py"],
        {"pkg/sample.py": [(24, 24)]},
    )

    assert [source.qualname for source in focused_sources] == ["second"]


def test_traceability_check_includes_template_contract_findings():
    report = traceability.classify([], {})
    report.template_contract_findings = [
        {
            "id": "template-contract:source",
            "kind": "template-contract",
            "severity": "error",
            "location": "home/panel.html::panel",
            "message": "macro not found",
        }
    ]

    findings = traceability.report_findings(report)

    assert [(finding["kind"], finding["location"]) for finding in findings] == [
        ("template-template-contract", "home/panel.html::panel")
    ]


def test_traceability_skips_current_result_gate_for_full_suite_structural_collector():
    report = traceability.classify([], {})
    report.summary["changed_scope"] = True
    structural = make_test_case(
        "tests_e2e/test_999_structural_evidence.py::"
        "test_structural_evidence_after_full_e2e_suite",
        runnable=True,
        path="tests_e2e/test_999_structural_evidence.py",
    )
    structural.execution = "failed"
    structural.execution_current = True
    report.changed_tests = [structural]

    findings = traceability.report_findings(report)

    assert not {
        "referenced-test-not-run",
        "referenced-test-not-passed",
    } & {finding["kind"] for finding in findings}


def source_symbol(
    path,
    qualname,
    testable,
    *,
    tests=None,
    features=None,
    dimensions=None,
    pairs=None,
    covered_by=None,
    reason=None,
    manual=False,
    kind="function",
    subkind=None,
    test_scaffolds=None,
    templates=None,
):
    return traceability.SourceSymbol(
        path=path,
        language="python",
        kind=kind,
        subkind=subkind,
        qualname=qualname,
        lineno=1,
        end_lineno=1,
        metadata=traceability.Metadata(
            testable=testable,
            tests=tests or [],
            test_scaffolds=test_scaffolds or [],
            templates=templates or [],
            features=features or [],
            dimensions=dimensions or [],
            pairs=pairs or [],
            covered_by=covered_by or [],
            reason=reason,
            manual=manual,
        ),
    )


def make_test_case(
    nodeid,
    *,
    runnable,
    features=None,
    dimensions=None,
    pairs=None,
    todos=None,
    templates=None,
    path="",
    qualname="",
    lineno=0,
):
    return traceability.TestCase(
        nodeid=nodeid,
        runnable=runnable,
        unfinished=not runnable,
        metadata=traceability.Metadata(
            features=features or [],
            dimensions=dimensions or [],
            pairs=pairs or [],
            todos=todos or [],
            templates=templates or [],
        ),
        path=path,
        qualname=qualname,
        lineno=lineno,
    )


def default_config():
    repo_root = Path(__file__).resolve().parents[2]
    return traceability.load_config(Path("testing/utility/traceability.yaml"), repo_root)
