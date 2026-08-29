"""Tests for semantic style candidates and traceability."""

import json
from pathlib import Path

import pytest

from testing.utility import (
    icon_traceability,
    style_candidates,
    style_registry,
    style_traceability,
    traceability,
    traceability_common,
)

pytestmark = pytest.mark.tooling


def test_icon_registry_schema_enforces_material_symbol_records():
    valid = {
        "dueDate": {"glyph": "event", "fill": 1},
        "filter": {
            "active": {"glyph": "filter_alt", "fill": 1},
            "inactive": {"glyph": "filter_alt", "fill": 0},
        },
    }
    assert style_registry.flatten_icon_definitions(valid) == {
        "dueDate": {"glyph": "event", "fill": 1},
        "filter.active": {"glyph": "filter_alt", "fill": 1},
        "filter.inactive": {"glyph": "filter_alt", "fill": 0},
    }

    with pytest.raises(ValueError, match="invalid icon ID segment due-date"):
        style_registry.flatten_icon_definitions(
            {"due-date": {"glyph": "event", "fill": 1}}
        )
    with pytest.raises(ValueError, match="Material Symbol name"):
        style_registry.flatten_icon_definitions(
            {"dueDate": {"glyph": "Calendar Event", "fill": 1}}
        )
    with pytest.raises(ValueError, match="fill must be 0 or 1"):
        style_registry.flatten_icon_definitions(
            {"dueDate": {"glyph": "event", "fill": 2}}
        )
    with pytest.raises(TypeError, match="non-empty mapping"):
        style_registry.flatten_icon_definitions({"filter": {}})


def test_icon_traceability_reports_unknown_and_unused_semantic_ids(tmp_path):
    write_file(
        tmp_path / "src/style/icons.yaml",
        """
dueDate:
  glyph: event
  fill: 1
filter:
  active:
    glyph: filter_alt
    fill: 1
unused:
  glyph: circle
  fill: 1
""",
    )
    write_file(
        tmp_path / "src/script/icons.mjs",
        """
button.className = ICONS.dueDate;
const row = { icon: "filter.active" };
const broken = { icon: "missingIcon" };
const registryPath = "src/style/icons.yaml";
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/icons.html",
        '{{ render_icon("dueDate") }}\n',
    )

    report = icon_traceability.build_report(
        tmp_path,
        definitions={
            "dueDate": {"glyph": "event", "fill": 1},
            "filter.active": {"glyph": "filter_alt", "fill": 1},
            "unused": {"glyph": "circle", "fill": 1},
        },
    )

    assert report.used == ["dueDate", "filter.active"]
    assert report.unused == ["unused"]
    assert [(item.icon_id, item.path, item.kind) for item in report.unknown] == [
        ("missingIcon", "src/script/icons.mjs", "context")
    ]


def test_style_candidates_reports_cleanup_candidates(tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
button:
  submit:
    classes: flex items-center gap-2
shared:
  row:
    classes: flex flex-row gap-2
unused:
  default:
    classes: text-base-dark italic
duplicate:
  first:
    classes: px-2 py-1 rounded
  second:
    classes: px-2 py-1 rounded
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/home.html",
        """
<button class="{{ styles.button.submit }} flex-1">Save</button>
<div class="flex flex-row gap-2"></div>
<div class="{{ styles.missing.value }}"></div>
<section class="grid grid-cols-1 gap-4 rounded-md bg-white shadow-sm text-base"></section>
""",
    )
    write_file(
        tmp_path / "src/script/view.mjs",
        """
import { STYLES } from "styles";

button.className = `${STYLES.button.submit} flex-1`;
panel.className = "grid grid-cols-1 gap-4 rounded-md bg-white shadow-sm text-base";
""",
    )

    report = style_candidates.build_report(tmp_path)

    assert report.summary["source_files_by_surface"] == {
        "javascript": 1,
        "template": 1,
    }
    assert "unused.default" in report.unused_style_definitions
    assert [item.name for item in report.unknown_style_references] == [
        "missing.value"
    ]
    assert [
        (item.style, item.extra_classes, item.surfaces)
        for item in report.cross_surface_style_extensions
    ] == [("button.submit", ["flex-1"], ["javascript", "template"])]
    assert any(
        item.matching_styles == ["shared.row"]
        for item in report.raw_class_matches_yaml
    )
    assert any(
        item.classes
        == ["grid", "grid-cols-1", "gap-4", "rounded-md", "bg-white", "shadow-sm", "text-base"]
        and item.count == 2
        for item in report.long_class_strings
    )
    assert report.duplicate_style_definitions[0].styles == [
        "duplicate.first",
        "duplicate.second",
    ]


def test_style_candidates_treats_dynamic_style_family_as_used(tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
editor:
  toolbar:
    container:
      page:
        classes: group/toolbar p-4
      form:
        classes: group/toolbar p-6
other:
  unused:
    classes: hidden
""",
    )
    write_file(
        tmp_path / "src/script/toolbar.mjs",
        """
import { STYLES } from "styles";

target.className = STYLES.editor.toolbar.container[this.kind];
""",
    )
    (tmp_path / "lagniappe/web/templates").mkdir(parents=True)

    report = style_candidates.build_report(tmp_path)

    assert "editor.toolbar.container.page" not in report.unused_style_definitions
    assert "editor.toolbar.container.form" not in report.unused_style_definitions
    assert "other.unused" in report.unused_style_definitions


def test_typed_style_aliases_resolve_and_hide_intentional_duplicates(tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
filters:
  actions:
    classes: flex gap-3
    intent: horizontal action group
    surfaces: [server]
modal:
  actions:
    alias: filters.actions
    intent: modal action group
    surfaces: [server]
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/home.html",
        """
<div class="{{ styles.filters.actions }}"></div>
<div class="{{ styles.modal.actions }}"></div>
""",
    )
    (tmp_path / "src/script").mkdir(parents=True)

    report = style_candidates.build_report(tmp_path)
    definitions = style_candidates.load_style_definitions(
        tmp_path, Path("src/style/styles.yaml")
    )

    assert definitions["modal.actions"].classes == "flex gap-3"
    assert definitions["modal.actions"].canonical == "filters.actions"
    assert report.duplicate_style_definitions == []

    with pytest.raises(ValueError, match="style alias cycle"):
        style_candidates.flatten_style_definitions(
            {
                "one": {"default": {"alias": "two.default"}},
                "two": {"default": {"alias": "one.default"}},
            }
        )


def test_style_pipeline_inventory_checks_imports_sources_and_python_parity(tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
button:
  submit:
    classes: flex items-center
""",
    )
    write_file(
        tmp_path / "src/style/pipeline.json",
        json.dumps(
            {
                "schema_version": 3,
                "frontend_entry": "src/script/main.mjs",
                "registry": {
                    "styles": "src/style/styles.yaml",
                    "schema": "src/style/registry.schema.json",
                    "icons": "src/style/icons.yaml",
                    "icons_schema": "src/style/icons.schema.json",
                    "virtual_module": "styles",
                    "python_styles": "lagniappe/web/start/styles/styles.py",
                    "python_icons": "lagniappe/web/start/styles/icons.py",
                },
                "css": {
                    "entry": "src/style/main.css",
                    "output": "style.css",
                    "tailwind_sources": ["src/style/styles.yaml"],
                    "authored_stylesheets": [
                        {"path": "src/style/main.css", "ownership": "pipeline"},
                        {"path": "src/style/components.css", "ownership": "structural"},
                    ],
                },
                "builds": {
                    "development": {
                        "config": "build/rollup.dev.config.mjs",
                        "transforms": ["tailwindcss"],
                    },
                    "production": {
                        "config": "build/rollup.config.mjs",
                        "transforms": ["tailwindcss", "cssnano"],
                    },
                },
            }
        ),
    )
    write_file(
        tmp_path / "src/style/main.css",
        '@import "./components.css";\n@source "./styles.yaml";\n',
    )
    write_file(
        tmp_path / "src/style/registry.schema.json",
        json.dumps(style_registry_schema()),
    )
    write_file(
        tmp_path / "src/style/icons.schema.json",
        json.dumps(
            {
                "schema_version": 2,
                "id_segment_pattern": "^[a-z][A-Za-z0-9]*$",
                "glyph_pattern": "^[a-z][a-z0-9_]*$",
                "record_fields": ["glyph", "fill", "weight", "spin"],
                "weights": [300, 400, 500, 600],
            }
        ),
    )
    write_file(
        tmp_path / "src/style/icons.yaml",
        "dueDate:\n  glyph: event\n  fill: 1\n",
    )
    write_file(tmp_path / "src/style/components.css", ".button { display: flex; }\n")
    write_file(
        tmp_path / "src/script/main.mjs",
        'import "../style/main.css";\nconst icon = createIcon("dueDate");\n',
    )
    write_file(
        tmp_path / "build/rollup.dev.config.mjs",
        "postcss({ plugins: [tailwindcss()] });\n",
    )
    write_file(
        tmp_path / "build/rollup.config.mjs",
        "postcss({ plugins: [tailwindcss(), cssnano()] });\n",
    )
    write_file(
        tmp_path / "package.json",
        json.dumps(
            {"devDependencies": {"@tailwindcss/postcss": "1", "cssnano": "1"}}
        ),
    )
    write_file(
        tmp_path / "lagniappe/web/start/styles/styles.py",
        'STYLES = {"button": {"submit": "flex items-center"}}\n',
    )
    write_file(
        tmp_path / "lagniappe/web/start/styles/icons.py",
        'ICONS = {"dueDate": {"glyph": "event", "fill": 1}}\n',
    )
    (tmp_path / "lagniappe/web/templates").mkdir(parents=True)

    manifest = style_traceability.build_manifest(tmp_path)

    assert manifest.pipeline.python_registry_parity is True
    assert manifest.pipeline.python_icons_parity is True
    assert manifest.pipeline.icon_count == 1
    assert manifest.pipeline.used_icon_count == 1
    assert manifest.pipeline.reachable_stylesheets == [
        "src/style/components.css",
        "src/style/main.css",
    ]
    assert manifest.pipeline.css_imports[0].target == "src/style/components.css"
    assert manifest.pipeline.issues == []


def test_style_manifest_records_semantic_raw_selector_and_input_inventory(tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
button:
  submit:
    classes: flex items-center
toolbar:
  item:
    page:
      classes: px-2 text-page-dark
    form:
      classes: px-2 text-form-dark
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/home.html",
        """
<button class="{{ styles.button.submit }} flex-1"></button>
""",
    )
    write_file(
        tmp_path / "src/script/view.mjs",
        """
import { STYLES } from "styles";
target.className = STYLES.toolbar.item[kind];
panel.className = "grid gap-2";
""",
    )
    write_file(
        tmp_path / "src/style/main.css",
        """
@media (min-width: 40rem) {
  .panel, [data-panel="active"] {
    display: grid;
  }
}
""",
    )
    write_file(tmp_path / "build/utility.mjs", "export const buildStyles = () => {};\n")
    write_file(tmp_path / "package.json", '{"name": "example"}\n')

    manifest = style_traceability.build_manifest(tmp_path)
    payload = style_traceability.manifest_payload(manifest)

    assert payload["schema_version"] == 3
    assert payload["kind"] == "style-manifest"
    assert payload["manifest_fingerprint"] == style_traceability.manifest_fingerprint(
        manifest
    )
    assert manifest.styles["button.submit"].source == {
        "path": "src/style/styles.yaml",
        "line": 2,
    }
    assert manifest.styles["button.submit"].observed_surfaces == ["server"]
    assert manifest.styles["toolbar.item.page"].observed_surfaces == ["frontend"]
    assert manifest.styles["toolbar.item.page"].consumers[0].resolution == "family"
    assert any(
        use.classes == "grid gap-2" and use.surface == "frontend"
        for use in manifest.raw_class_uses
    )
    assert [item.selector for item in manifest.css_selectors] == [
        ".panel",
        '[data-panel="active"]',
    ]
    assert manifest.css_selectors[0].at_rules == ["@media (min-width: 40rem)"]
    roles = {item.path: item.role for item in manifest.inputs}
    assert roles["src/style/styles.yaml"] == "semantic-registry"
    assert roles["src/style/main.css"] == "stylesheet"
    assert roles["build/utility.mjs"] == "build-pipeline"

    fingerprint = style_traceability.manifest_fingerprint(manifest)
    manifest.provenance = {"generated_at": "later"}
    assert style_traceability.manifest_fingerprint(manifest) == fingerprint

    query = style_traceability.query_manifest(
        manifest, consumer="lagniappe/web/templates/home.html"
    )
    assert [style["id"] for style in query["styles"]] == ["button.submit"]


def test_style_hooks_accept_compound_class_selectors(tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
badge:
  icon:
    classes: icon-base text-kind-default
    intent: icon presentation within badge
    surfaces: [server]
    hooks: [icon-base]
    css: [src/style/icons.css]
""",
    )
    write_file(
        tmp_path / "src/style/icons.css",
        """
/* @style badge.icon */
.icon.icon-base {
  inline-size: 1.5rem;
}
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/badge.html",
        '<span class="icon {{ styles.badge.icon }}"></span>\n',
    )
    (tmp_path / "src/script").mkdir(parents=True)

    manifest = style_traceability.build_manifest(tmp_path)

    selector = next(
        item for item in manifest.css_selectors if item.selector == ".icon.icon-base"
    )
    assert selector.owners == ["badge.icon"]
    assert not any(
        issue["kind"] == "style-hook-without-rule" for issue in manifest.issues
    )


def test_style_traceability_uses_shared_report_envelope_and_stable_findings(tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
button:
  submit:
    classes: flex items-center
unused:
  item:
    classes: hidden
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/home.html",
        """
<button class="{{ styles.missing.submit }}"></button>
""",
    )
    (tmp_path / "src/script").mkdir(parents=True)

    report, _manifest = style_traceability.build_report(tmp_path)
    payload = style_traceability.report_payload(report)

    assert payload["schema_version"] == traceability_common.TRACEABILITY_SCHEMA_VERSION
    assert payload["kind"] == "style-traceability-report"
    assert payload["finding_ids"] == [
        finding["id"] for finding in payload["findings"]
    ]
    assert {finding["kind"] for finding in payload["findings"]} == {
        "unknown-style-reference",
        "unused-style-definition",
    }
    assert payload["findings"][0]["severity"] == "error"


def test_style_manifest_links_explicit_test_evidence(tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
dropdown:
  panel:
    classes: absolute hidden
""",
    )
    write_file(
        tmp_path / "src/script/dropdown.mjs",
        """
import { STYLES } from "styles";
panel.className = STYLES.dropdown.panel;
""",
    )
    write_file(
        tmp_path / "testing/tests_js/test_dropdown.py",
        """
# @style dropdown.panel
def test_dropdown_panel():
    assert True
""",
    )
    write_file(
        tmp_path / "testing/utility/traceability.yaml",
        """
source_roots: []
test_roots: [tests_js]
""",
    )
    (tmp_path / "lagniappe/web/templates").mkdir(parents=True)

    manifest = style_traceability.build_manifest(tmp_path)

    assert [item.nodeid for item in manifest.styles["dropdown.panel"].evidence] == [
        "tests_js/test_dropdown.py::test_dropdown_panel"
    ]
    assert manifest.styles["dropdown.panel"].evidence[0].kind == "explicit"
    assert manifest.styles["dropdown.panel"].evidence[0].current is False
    assert manifest.styles["dropdown.panel"].fingerprint


def test_traceability_styles_mode_emits_manifest_json(capsys, tmp_path):
    write_file(
        tmp_path / "src/style/styles.yaml",
        """
button:
  submit:
    classes: flex items-center
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/home.html",
        '<button class="{{ styles.button.submit }}"></button>\n',
    )
    (tmp_path / "src/script").mkdir(parents=True)

    result = traceability.main(
        [
            "--repo-root",
            str(tmp_path),
            "--styles",
            "--json",
            "--no-manifest",
            "--no-report",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["kind"] == "style-traceability-report"
    assert payload["report"]["summary"]["used_style_definitions"] == 1


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.lstrip())


def style_registry_schema() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id_segment_pattern": "^[a-z][A-Za-z0-9]*$",
        "record_fields": [
            "alias",
            "classes",
            "intent",
            "surfaces",
            "markers",
            "hooks",
            "css",
            "exceptions",
        ],
        "required_metadata": [],
        "surfaces": ["server", "frontend"],
        "exception_fields": ["diagnostic", "target", "reason"],
        "exception_diagnostics": ["duplicate-style-value"],
    }
