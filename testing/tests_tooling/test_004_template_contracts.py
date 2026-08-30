"""Tests for the template contract reporter."""

from pathlib import Path

import pytest

from testing.utility import template_contracts

pytestmark = pytest.mark.tooling


def test_template_contract_uses_loader_root_and_follows_call_block_kwargs(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/home/panel.html",
        """
{% import 'controls.html' as controls %}
{% macro panel() %}
  {% call controls.wrapper(kind='thing') %}<span data-role="body"></span>{% endcall %}
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/controls.html",
        """
{% macro wrapper(kind=None) %}
  <section data-role="root-wrapper" data-kind="{{ kind }}">{{ caller() }}</section>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/home/controls.html",
        """
{% macro wrapper(kind=None) %}<div data-role="wrong-sibling"></div>{% endmacro %}
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_panel.py",
        """
# @template home/panel.html::panel
def test_panel():
    pass
""",
    )

    report = template_contracts.build_report(tmp_path, "test_panel.py")
    labels = {attribute.label for attribute in report.entries[0].attributes}

    assert "controls.html::wrapper(kind=thing)" in report.entries[0].included_macros
    assert "data-role=root-wrapper" in labels
    assert "data-kind=thing" in labels
    assert "data-role=wrong-sibling" not in labels


def test_template_contract_report_extracts_macro_js_checks_and_test_selectors(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/home/panel.html",
        """
{% import 'controls.html' as controls %}
{% from "common.html" import generate %}

{% macro create() %}
  <form lp-create
        data-widget="CreateThing"
        data-route="{{ url_for('things.create') }}"
        data-destination="things:ThingList"
        data-visible="false">
    <div data-role="header"><span data-role="title"></span></div>
    {{ controls.help("thing_help") }}
    {{ controls.close("things") }}
    {{ generate("thing") }}
  </form>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/controls.html",
        """
{% macro help(route) %}
  <button lp-control="help" data-controls="help" lp-help="{{ route }}" type="button"></button>
{% endmacro %}

{% macro close(target=None) %}
  <button lp-control="close" data-controls="close" lp-close="{{ target or '' }}" type="button"></button>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/common.html",
        """
{% macro generate(kind) %}
  <div data-role="generate">
    <button data-role="manual" type="button"></button>
    <button data-role="ai" type="button"></button>
    <textarea data-kind="{{ kind }}" name="user_description"></textarea>
  </div>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/home/home.html",
        """
<section id="things">
  <button lp-show="things:CreateThing" data-toggle="true"></button>
  <ul data-widget="ThingList"></ul>
</section>
""",
    )
    write_file(
        tmp_path / "src/script/widgets/thing.mjs",
        "export class CreateThing {}\nexport class ThingList {}\n",
    )
    write_file(
        tmp_path / "src/script/views/base/core.mjs",
        """
export default class Core {
  _click() {
    const control = button?.getAttribute("lp-control");
    if (control === "help") return this._showHelpModal(button);
    if (control || button?.hasAttribute("lp-show")) return this.renderComponent(button);
  }
}
""",
    )
    write_file(
        tmp_path / "src/script/elements/sections.mjs",
        """
target.querySelector('[data-role="generate"]');
target.querySelector("button[data-role='manual']");
target.querySelector("button[data-role='ai']");
""",
    )
    write_file(
        tmp_path / "testing/resources/home.py",
        """
class HomePage:
    CREATE_THING_FORM = "form[data-widget='CreateThing']"
""",
    )
    write_file(
        tmp_path / "testing/elements/site_common.py",
        """
class Buttons:
    AI_MODE = "button[data-role='ai']"
    LP_HELP = "button[lp-help]"
    LP_CLOSE = "button[lp-close]"
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template home/panel.html::create
# @todo cover generated attributes
def test_create_thing():
    home.CREATE_THING_FORM
    Buttons.AI_MODE
    Buttons.LP_HELP
    Buttons.LP_CLOSE
""",
    )

    report = template_contracts.build_report(
        tmp_path, "tests_e2e/test_thing.py::test_create_thing"
    )
    entry = report.entries[0]
    group = report.groups[0]
    labels = {attribute.label for attribute in entry.attributes}
    checks = {(check.status, check.kind, check.name) for check in entry.checks}
    evidence = {match for item in entry.selector_evidence for match in item.matches}

    assert report.summary["template_references"] == 1
    assert report.summary["template_partials"] == 1
    assert entry.reference.todos == ["cover generated attributes"]
    assert group.template_ref == "home/panel.html::create"
    assert "home/panel.html::create" in entry.included_macros
    assert "controls.html::help(thing_help)" in entry.included_macros
    assert "common.html::generate(thing)" in entry.included_macros
    assert "data-widget=CreateThing" in labels
    assert "lp-help=thing_help" in labels
    assert "lp-close=things" in labels
    assert ("ok", "widget", "CreateThing") in checks
    assert ("ok", "destination", "things:ThingList") in checks
    assert ("ok", "lp-control", "help") in checks
    assert "data-widget=CreateThing" in evidence
    assert "data-role=ai" in evidence
    assert "data-role=header" not in evidence
    assert "data-role=title" not in evidence
    assert "lp-help=thing_help" in evidence
    assert "data-widget=CreateThing" in group.touched_by_attribute
    assert "lp-create" in entry.not_directly_selected
    assert not entry.issues
    assert template_contracts.default_markdown_report_path(report) == Path(
        "reports/template-contracts-home-panel-html-create.md"
    )


def test_template_contract_markdown_report_can_be_saved(tmp_path):
    report = template_contracts.Report(summary={"nodeid": None}, entries=[])
    report.summary.update(
        {
            "template_references": 0,
            "tests": 0,
            "template_partials": 0,
            "included_macros": 0,
            "contract_attributes": 0,
            "checks_ok": 0,
            "checks_warn": 0,
            "checks_review": 0,
            "checks_info": 0,
            "selector_evidence": 0,
            "not_directly_selected": 0,
            "review_notes": 0,
            "issues": 0,
        }
    )
    output = tmp_path / "reports" / "template-contracts.md"
    output.parent.mkdir()
    output.write_text("old")

    saved = template_contracts.save_markdown_report(
        report, tmp_path, Path("reports/template-contracts.md")
    )

    assert saved == output
    assert output.read_text().startswith("# Template Contract Report")


def test_template_contract_nodeid_filter_accepts_testing_prefix(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/home/panel.html",
        """
{% macro create() %}
  <form data-widget="CreateThing"></form>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template home/panel.html::create
def test_create_thing():
    pass
""",
    )

    report = template_contracts.build_report(
        tmp_path, "testing/tests_e2e/test_thing.py::test_create_thing"
    )

    assert report.summary["template_references"] == 1
    assert report.entries[0].reference.nodeid == (
        "tests_e2e/test_thing.py::test_create_thing"
    )

    shorthand_report = template_contracts.build_report(
        tmp_path, "test_thing.py::test_create_thing"
    )
    file_report = template_contracts.build_report(tmp_path, "test_thing.py")
    folder_report = template_contracts.build_report(tmp_path, "tests_e2e")
    template_report = template_contracts.build_report(
        tmp_path, "lagniappe/web/templates/home/panel.html"
    )
    template_macro_report = template_contracts.build_report(
        tmp_path, "home/panel.html::create"
    )

    assert shorthand_report.summary["template_references"] == 1
    assert file_report.summary["template_references"] == 1
    assert folder_report.summary["template_references"] == 1
    assert template_report.summary["template_references"] == 1
    assert template_macro_report.summary["template_references"] == 1


def test_changed_contract_scope_selects_only_related_templates_and_frontend(
    tmp_path,
):
    write_file(
        tmp_path / "lagniappe/web/templates/alpha.html",
        """
{% macro panel() %}
  <section data-role="alpha"></section>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "lagniappe/web/templates/beta.html",
        """
{% macro panel() %}
  <section data-role="beta"></section>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "src/script/alpha.mjs",
        """document.querySelector("[data-role='alpha']");""",
    )
    write_file(
        tmp_path / "src/script/beta.mjs",
        """document.querySelector("[data-role='beta']");""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_contracts.py",
        """
# @template alpha.html::panel
def test_alpha():
    pass


# @template beta.html::panel
def test_beta():
    pass
""",
    )

    template_report = template_contracts.build_report(
        tmp_path,
        changed_paths=["lagniappe/web/templates/alpha.html"],
    )
    frontend_report = template_contracts.build_report(
        tmp_path,
        changed_paths=["src/script/alpha.mjs"],
    )

    assert [entry.reference.nodeid for entry in template_report.entries] == [
        "tests_e2e/test_contracts.py::test_alpha"
    ]
    assert [entry.reference.nodeid for entry in frontend_report.entries] == [
        "tests_e2e/test_contracts.py::test_alpha"
    ]
    assert template_report.summary["template_references"] == 1
    assert template_report.summary["tests"] == 1
    assert template_report.summary["template_partials"] == 1
    assert frontend_report.summary["template_references"] == 1
    assert frontend_report.summary["tests"] == 1
    assert frontend_report.summary["template_partials"] == 1


def test_template_contract_groups_multiple_tests_for_one_partial(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/home/panel.html",
        """
{% macro create() %}
  <form lp-create data-widget="CreateThing" data-mode="manual"></form>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "testing/resources/home.py",
        """
class HomePage:
    CREATE_THING_FORM = "form[data-widget='CreateThing']"
    CREATE_THING_MODE = "form[data-mode='manual']"
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template home/panel.html::create
def test_create_thing_form():
    home.CREATE_THING_FORM


# @template home/panel.html::create
def test_create_thing_mode():
    home.CREATE_THING_MODE
""",
    )

    report = template_contracts.build_report(tmp_path, "test_thing.py")
    group = report.groups[0]

    assert report.summary["template_references"] == 2
    assert report.summary["template_partials"] == 1
    assert len(group.entries) == 2
    assert group.touched_by_attribute["data-widget=CreateThing"] == [
        "tests_e2e/test_thing.py::test_create_thing_form via HomePage.CREATE_THING_FORM"
    ]
    assert group.touched_by_attribute["data-mode=manual"] == [
        "tests_e2e/test_thing.py::test_create_thing_mode via HomePage.CREATE_THING_MODE"
    ]
    assert "data-mode=manual" not in group.not_directly_selected
    assert "lp-create" in group.not_directly_selected


def test_template_contract_counts_spinner_submit_contract_evidence(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/home/panel.html",
        """
{% macro create() %}
  <form lp-create data-widget="CreateThing"></form>
{% endmacro %}

{% macro update() %}
  <form lp-update data-widget="ThingInfo"></form>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "src/script/views/base/core.mjs",
        """
export default class Core {
  _submit() {
    component.active.target.hasAttribute("lp-create");
    component.active.target.hasAttribute("lp-update");
  }
}
""",
    )
    write_file(
        tmp_path / "testing/resources/home.py",
        """
class HomePage:
    def create_manual_project(self, project):
        SpinnerButtons.CREATE.click(self.form)
""",
    )
    write_file(
        tmp_path / "testing/elements/forms_common.py",
        """
class SpinnerButtons:
    CREATE = "button[type='submit']:has-text('Create')"
    UPDATE = "button[type='submit']:has-text('Update')"
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template home/panel.html::create
def test_create_thing(home):
    home.create_manual_project(None)


# @template home/panel.html::update
def test_update_thing(info_form):
    SpinnerButtons.UPDATE.click(info_form)
""",
    )

    report = template_contracts.build_report(tmp_path, "test_thing.py")
    create_group = next(
        group for group in report.groups if group.template_ref == "home/panel.html::create"
    )
    update_group = next(
        group for group in report.groups if group.template_ref == "home/panel.html::update"
    )
    checks = {(check.status, check.kind, check.name) for group in report.groups for check in group.checks}

    assert create_group.touched_by_attribute["lp-create"] == [
        "tests_e2e/test_thing.py::test_create_thing via HomePage.create_manual_project"
    ]
    assert update_group.touched_by_attribute["lp-update"] == [
        "tests_e2e/test_thing.py::test_update_thing via SpinnerButtons.UPDATE"
    ]
    assert "lp-create" not in create_group.not_directly_selected
    assert "lp-update" not in update_group.not_directly_selected
    assert ("ok", "submit-contract", "lp-create") in checks
    assert ("ok", "submit-contract", "lp-update") in checks


def test_template_contract_rejects_unsupported_lp_vocabulary(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/things.html",
        """
{% macro stale_controls() %}
  <button lp-star type="button"></button>
  <button lp-control="expand" type="button"></button>
  <button lp-control="menu" lp-show="{{ target }}" type="button"></button>
  <span lp-menu="title"></span>
  <span lp-edited-marker></span>
  <div lp-sprocket></div>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template things.html::stale_controls
def test_stale_controls():
    pass
""",
    )

    report = template_contracts.build_report(tmp_path, "test_thing.py")
    group = report.groups[0]
    checks = {(check.status, check.kind, check.name) for check in group.checks}

    assert report.summary["issues"] == 3
    assert any("lp-star" in issue and 'lp-control="star"' in issue for issue in group.issues)
    assert any("lp-sprocket" in issue for issue in group.issues)
    assert not any("lp-menu" in issue for issue in group.issues)
    assert not any("lp-edited-marker" in issue for issue in group.issues)
    assert not any("lp-control value 'menu'" in issue for issue in group.issues)
    assert any("lp-control value 'expand'" in issue for issue in group.issues)
    assert ("warn", "lp-control", "expand") in checks


def test_template_contract_rejects_unresolved_routed_controls(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/things.html",
        """
{% macro routed_controls() %}
  <form data-widget="ThingInfo" data-reset="things:ThingInfo"></form>
  <button lp-control="form"
          data-controls="show"
          lp-show="things:ThingForm"
          type="button"></button>
  <button lp-control="reset"
          data-controls="show"
          type="button"></button>
  <button lp-control="history"
          type="button"></button>
  <button lp-control="filters"
          data-controls="show"
          type="button"></button>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template things.html::routed_controls
def test_routed_controls():
    pass
""",
    )

    report = template_contracts.build_report(tmp_path, "test_thing.py")
    group = report.groups[0]

    assert report.summary["issues"] == 3
    assert any(
        "lp-control value 'history'" in issue and 'data-controls="show"' in issue
        for issue in group.issues
    )
    assert any(
        "lp-control value 'history'" in issue and "data-history" in issue
        for issue in group.issues
    )
    assert any(
        "lp-control value 'filters'" in issue and "data-filters" in issue
        for issue in group.issues
    )
    assert not any("lp-control value 'form'" in issue for issue in group.issues)
    assert not any("lp-control value 'reset'" in issue for issue in group.issues)


def test_template_contract_counts_common_helper_evidence(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/things.html",
        """
{% macro item() %}
  <li lp-entity data-key="{{ thing.key }}">
    <a data-role="title" href="/things/{{ thing.key }}">Thing</a>
  </li>
{% endmacro %}

""",
    )
    write_file(
        tmp_path / "src/script/views/base/core.mjs",
        """
export default class Core {
  _submit() {
    component.active.target.hasAttribute("lp-update");
  }
}
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template things.html::item
def test_common_helpers(project_list):
    item = project_list.new_ai_generated_item()
    Link(item).click()
""",
    )

    report = template_contracts.build_report(tmp_path, "test_thing.py")
    item_group = next(
        group for group in report.groups if group.template_ref == "things.html::item"
    )
    assert item_group.touched_by_attribute["lp-entity"] == [
        "tests_e2e/test_thing.py::test_common_helpers via List.new_ai_generated_item"
    ]
    assert item_group.touched_by_attribute["data-key={{ thing.key }}"] == [
        "tests_e2e/test_thing.py::test_common_helpers via List.new_ai_generated_item"
    ]
    assert item_group.touched_by_attribute["data-role=title"] == [
        "tests_e2e/test_thing.py::test_common_helpers via Link.click"
    ]
def test_template_contract_counts_resource_property_evidence(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/projects/info.html",
        """
{% macro info_tab() %}
  <div lp-component data-visible="false">
    {{ info_form() }}
  </div>
{% endmacro %}

{% macro info_form() %}
  <form lp-update data-widget="ProjectInfo">
    <button type="submit"></button>
  </form>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "src/script/widgets/projectInfo.mjs",
        "export class ProjectInfo {}\n",
    )
    write_file(
        tmp_path / "src/script/views/base/core.mjs",
        """
export default class Core {
  _submit() {
    component.active.target.hasAttribute("lp-update");
  }
}
""",
    )
    write_file(
        tmp_path / "testing/resources/project.py",
        """
class Project:
    INFO_FORM = "[data-widget='ProjectInfo']"

    @property
    def info_form(self):
        return self.user.locate(self.INFO_FORM)
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_project.py",
        """
# @template projects/info.html::info_tab
def test_project_info(get_user):
    project = Projects.test_project.get(get_user)
    info_form = project.info_form
    SpinnerButtons.UPDATE.click(info_form)
""",
    )

    report = template_contracts.build_report(tmp_path, "test_project.py")
    group = next(
        group for group in report.groups if group.template_ref == "projects/info.html::info_tab"
    )

    assert group.touched_by_attribute["data-widget=ProjectInfo"] == [
        "tests_e2e/test_project.py::test_project_info via Project.info_form"
    ]
    assert group.touched_by_attribute["lp-update"] == [
        "tests_e2e/test_project.py::test_project_info via SpinnerButtons.UPDATE"
    ]
    assert "data-widget=ProjectInfo" not in group.not_directly_selected
    assert "lp-component" not in group.not_directly_selected


def test_template_contract_downgrades_touched_selector_only_widget(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/things.html",
        """
{% macro preview() %}
  <div data-widget="PreviewOnly"></div>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "testing/resources/thing.py",
        """
class Page:
    PREVIEW = "[data-widget='PreviewOnly']"
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template things.html::preview
def test_preview_widget():
    Page.PREVIEW
""",
    )

    report = template_contracts.build_report(tmp_path, "test_thing.py")
    group = report.groups[0]
    widget_check = next(
        check for check in group.checks if check.kind == "widget" and check.name == "PreviewOnly"
    )

    assert widget_check.status == "info"
    assert "selector-only widget touched by tests" in widget_check.detail
    assert report.summary["checks_warn"] == 0


def test_template_contract_marks_included_macro_coverage(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/things.html",
        """
{% macro main() %}
  <section>
    {{ mobile_nav() }}
  </section>
{% endmacro %}

{% macro mobile_nav() %}
  <nav lp-nav data-nav="mobile">
    <div data-flipped="false">
      <button data-role="flipper"></button>
    </div>
  </nav>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "src/script/views/base/core.mjs",
        """
button.closest("[data-flipped]");
target.querySelector("[data-role='flipper']");
""",
    )
    write_file(
        tmp_path / "testing/elements/mobile.py",
        """
class MobileNav:
    FLIPPER = "[data-role='flipper']"
    WRAPPER = "[data-flipped]"
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template things.html::main
def test_main_shell():
    pass


# @template things.html::mobile_nav
def test_mobile_nav():
    MobileNav.FLIPPER
    MobileNav.WRAPPER
""",
    )

    report = template_contracts.build_report(tmp_path, "things.html")
    main_group = next(
        group for group in report.groups if group.template_ref == "things.html::main"
    )

    assert "data-role=flipper" not in main_group.not_directly_selected
    assert "data-flipped=false" not in main_group.not_directly_selected
    assert main_group.covered_by_template["data-role=flipper"] == [
        "things.html::mobile_nav: tests_e2e/test_thing.py::test_mobile_nav via MobileNav.FLIPPER"
    ]
    assert main_group.covered_by_template["data-flipped=false"] == [
        "things.html::mobile_nav: tests_e2e/test_thing.py::test_mobile_nav via MobileNav.WRAPPER"
    ]


def test_template_contract_counts_resource_method_selector_evidence(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/home/panel.html",
        """
{% macro create() %}
  <section id="things">
    <button lp-show="things:CreateThing" data-toggle="true"></button>
    <form lp-create data-widget="CreateThing"></form>
    <li lp-entity data-key="{{ thing.key }}"></li>
    <span data-role="doc-only"></span>
  </section>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "src/script/widgets/thing.mjs",
        "export class CreateThing {}\n",
    )
    write_file(
        tmp_path / "src/script/views/base/core.mjs",
        """
export default class Core {
  _click() {
    if (button?.hasAttribute("lp-show")) return this.renderComponent(button);
  }
  _submit() {
    component.active.target.hasAttribute("lp-create");
  }
}
""",
    )
    write_file(
        tmp_path / "testing/resources/home.py",
        """
class HomePage:
    CREATE_THING_TOGGLE = "button[lp-show='things:CreateThing'][data-toggle]"
    CREATE_THING_FORM = "form[data-widget='CreateThing']"

    def create_thing_form(self):
        '''Documentation mentions [data-role="doc-only"] but should not count.'''
        self.user.locate(self.CREATE_THING_TOGGLE).click()
        form = self.user.locate(self.CREATE_THING_FORM)
        return form

    def created_thing(self, key):
        return self.user.locate(f"li[data-key='{key}']")
""",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_thing.py",
        """
# @template home/panel.html::create
def test_create_thing(home):
    home.create_thing_form()
    home.created_thing("abc")
""",
    )

    report = template_contracts.build_report(tmp_path, "test_thing.py")
    group = report.groups[0]

    assert group.touched_by_attribute["lp-show=things:CreateThing"] == [
        "tests_e2e/test_thing.py::test_create_thing via HomePage.create_thing_form"
    ]
    assert group.touched_by_attribute["data-toggle=true"] == [
        "tests_e2e/test_thing.py::test_create_thing via HomePage.create_thing_form"
    ]
    assert group.touched_by_attribute["data-widget=CreateThing"] == [
        "tests_e2e/test_thing.py::test_create_thing via HomePage.create_thing_form"
    ]
    assert group.touched_by_attribute["data-key={{ thing.key }}"] == [
        "tests_e2e/test_thing.py::test_create_thing via HomePage.created_thing"
    ]
    assert all(
        evidence.selector != "li[data-key='"
        for entry in group.entries
        for evidence in entry.selector_evidence
    )
    assert "data-role=doc-only" not in group.touched_by_attribute
    assert "data-widget=CreateThing" not in group.not_directly_selected


def test_template_contract_counts_static_selector_against_dynamic_attribute(tmp_path):
    write_file(
        tmp_path / "lagniappe/web/templates/badge.html",
        """
{% macro entity_badge() %}
  <div data-kind="{{ details.kind }}">
    <a data-role="title"></a>
  </div>
{% endmacro %}
""",
    )
    write_file(
        tmp_path / "testing/elements/badges.py",
        """
class Badges:
    PROJECT = 'div[data-kind="project"]'
""",
    )
    write_file(
        tmp_path / "src/script/elements/badge.mjs",
        "target.querySelector('[data-role=\"title\"]');\n",
    )
    write_file(
        tmp_path / "testing/tests_e2e/test_badge.py",
        """
# @template badge.html::entity_badge
def test_project_badge():
    Badges.PROJECT
    kind = "project"
    f"div[data-kind='{kind}']"


# @template badge.html::entity_badge
def test_badge_text_only():
    assert True
""",
    )

    report = template_contracts.build_report(tmp_path, "test_badge.py")
    group = report.groups[0]

    assert (
        "tests_e2e/test_badge.py::test_project_badge via Badges.PROJECT"
        in group.touched_by_attribute["data-kind={{ details.kind }}"]
    )
    assert (
        "tests_e2e/test_badge.py::test_project_badge via literal"
        in group.touched_by_attribute["data-kind={{ details.kind }}"]
    )
    assert all(
        evidence.selector != "div[data-kind='"
        for entry in group.entries
        for evidence in entry.selector_evidence
    )
    assert not any("dynamic data-kind" in note for note in group.review)
    assert "data-role=title" in group.not_directly_selected


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.lstrip())
