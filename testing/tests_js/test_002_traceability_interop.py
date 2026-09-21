"""Real Python/Node traceability integration; Python-only policies stay in tooling."""

from pathlib import Path

import pytest

from testing.utility import traceability


pytestmark = [pytest.mark.js, pytest.mark.usefixtures("node_binary")]


def default_config():
    repo_root = Path(__file__).resolve().parents[2]
    return traceability.load_config(Path("testing/utility/traceability.yaml"), repo_root)


# @node-program testing/utility/traceability_js.mjs
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


# @node-program testing/utility/traceability_js.mjs
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


# @node-program testing/utility/traceability_js.mjs
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


# @node-program testing/utility/traceability_js.mjs
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
     * @pair search:url-state
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


# @node-program testing/utility/traceability_js.mjs
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
     * @pair forms:owner-restricted
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
# @pair forms:owner-restricted
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
                lineno=2,
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


# @node-program testing/utility/traceability_js.mjs
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
            update_test: traceability.TestCase(
                nodeid=update_test,
                unfinished=False,
                metadata=traceability.Metadata(),
                runnable=True,
                path="tests_e2e/007_categories/test_table.py",
                qualname="test_update_widget",
                lineno=1,
            ),
            columns_test: traceability.TestCase(
                nodeid=columns_test,
                unfinished=False,
                metadata=traceability.Metadata(),
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
