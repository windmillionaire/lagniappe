"""Form composition and detached replacement ownership."""


_FORM_WIDGET = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const controllers = [];
let initialize = async () => {};
class Target {
  constructor(name, loaded = true) {
    this.dataset = {name, widget: "Example", visible: "true"};
    this.field = {value: name};
    this.attributes = new Set(loaded ? ["lp-load", "loaded"] : ["lp-load"]);
    this.inert = false;
  }
  cloneNode() { return new Target(this.field.value, this.hasAttribute("loaded")); }
  hasAttribute(name) { return this.attributes.has(name); }
  setAttribute(name) { this.attributes.add(name); }
  matches() { return false; }
  querySelector(selector) { return selector === "[name='name']" ? this.field : null; }
  addEventListener() {}
  replaceWith(next) { this.replacement = next; }
}
const context = {
  HTMLFormElement: Target,
  FormData: class extends Map {
    constructor(target) { super(target ? [["name", target.field.value]] : []); }
  },
  FormController: class {
    constructor(widget) { this.widget = widget; this.destroyed = 0; controllers.push(this); }
    async init() { await initialize(this); }
    destroy() { this.destroyed = 1; }
    syncOfflineState() {}
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("src/script/widgets/base/formWidget.mjs", "utf8")
  .replace(/^import .*;\n/gm, "").replace("export class FormWidget", "class FormWidget")
  + "\nglobalThis.FormWidget = FormWidget;", context);
const {FormWidget} = context;
const response = target => ({html: {querySelector: () => target}});
const makeWidget = (target = new Target("Original")) => new FormWidget({target, name: "Example"});
'''


# @matrix user-groups forms : initialization conditional-response single-reconciliation
def test_form_shell_waits_for_html_and_visibility_does_not_rebuild(run_node):
    run_node(_FORM_WIDGET + r'''
(async () => {
  const widget = makeWidget(new Target("", false));
  await widget.init();
  assert.equal(widget.initialized, false);
  assert.equal(widget.form, null);
  widget.updated({...response(new Target("Saved")), updated: false});
  await widget.prereconcile();
  widget.postreconcile();
  assert.equal(widget.initialized, true);
  assert.equal(widget.target.hasAttribute("initialized"), true);
  assert.equal(widget.formData.get("name"), "Saved");
  assert.equal(widget.revisionBaseline, widget.revisionSnapshot());
  const form = widget.form;
  await widget.prereconcile();
  widget.postreconcile();
  assert.equal(widget.form, form);
  assert.equal(controllers.length, 1);
})().catch(error => {console.error(error); process.exitCode = 1;});
''')


# @matrix forms user-groups : rebuild-serialization single-reconciliation
def test_form_replacements_serialize_and_adopt_only_latest_controls(run_node):
    run_node(_FORM_WIDGET + r'''
(async () => {
  const widget = makeWidget();
  await widget.init();
  const live = widget.form;
  let release;
  initialize = async controller => {
    controller.widget.selector = {target: controller.widget.target};
    if (controller.widget.target.dataset.name === "First") {
      await new Promise(resolve => {release = resolve;});
    }
  };
  widget.updated(response(new Target("First")));
  const first = widget.prereconcile();
  while (!release) await Promise.resolve();
  assert.equal(widget.target.inert, true);
  assert.equal(widget.selector, undefined, "Detached initialization mutated the live widget");
  widget.updated(response(new Target("Latest")));
  const second = widget.prereconcile();
  release();
  await Promise.all([first, second]);
  await widget.prereconcile();
  assert.equal(controllers.length, 3, "Repeated preparation rebuilt the same response");
  assert.equal(controllers[1].destroyed, 1);
  assert.equal(live.destroyed, 0);
  widget.postreconcile();
  assert.equal(widget.formData.get("name"), "Latest");
  assert.equal(widget.selector.target, widget.target);
  assert.equal(live.destroyed, 1);
  assert.equal(widget.form.destroyed, 0);
  assert.equal(widget.target.inert, false);
  assert.equal(widget.revisionBaseline, widget.revisionSnapshot());
  widget.form.widget.markUnsavedState();
  assert.equal(widget.unsavedState, true, "Adopted controller still writes detached state");
})().catch(error => {console.error(error); process.exitCode = 1;});
''')


# @matrix forms user-groups : rebuild-serialization single-reconciliation
def test_queued_commit_waits_for_newer_replacement(run_node):
    run_node(_FORM_WIDGET + r'''
(async () => {
  const widget = makeWidget();
  await widget.init();
  widget.target.inert = true;
  const live = widget.form;
  widget.updated(response(new Target("First")));
  await widget.prereconcile();
  let release;
  initialize = async () => await new Promise(resolve => {release = resolve;});
  widget.updated(response(new Target("Latest")));
  widget.postreconcile();
  assert.equal(widget.form, live, "A superseded preparation was committed");
  const pending = widget.prereconcile();
  while (!release) await Promise.resolve();
  widget.modified = false;
  widget.postreconcile();
  assert.equal(widget.modified, true);
  assert.equal(widget._updated, true);
  assert.equal(widget.form, live, "A queued commit interrupted the latest preparation");
  release();
  await pending;
  widget.postreconcile();
  assert.equal(widget.formData.get("name"), "Latest");
  assert.equal(widget._updated, false);
  assert.equal(widget.target.inert, true, "Replacement lost its prior inert state");
})().catch(error => {console.error(error); process.exitCode = 1;});
''')


# @matrix forms : teardown reset unsaved-preservation
def test_form_discard_and_failure_leave_live_controls_intact(run_node):
    run_node(_FORM_WIDGET + r'''
(async () => {
  const widget = makeWidget();
  await widget.init();
  const live = widget.form;
  let release;
  initialize = async () => await new Promise(resolve => {release = resolve;});
  const pending = widget.prepareReset({nextTarget: new Target("Discarded")});
  while (!release) await Promise.resolve();
  widget.discardPreparedReset();
  release();
  await pending;
  assert.equal(widget.commitReset(), false);
  assert.equal(controllers[1].destroyed, 1);
  assert.equal(live.destroyed, 0);
  assert.equal(widget.formData.get("name"), "Original");
  initialize = async controller => {
    controller.widget.target.field.value = "Partially initialized";
    throw new Error("control initialization failed");
  };
  widget.updated(response(new Target("Failed")));
  await assert.rejects(widget.prereconcile(), /control initialization failed/);
  assert.equal(controllers[2].destroyed, 1);
  assert.equal(live.destroyed, 0);
  assert.equal(widget.target.inert, false);
  assert.equal(widget.commitReset(), false);
  initialize = async () => {};
  await widget.prereconcile();
  widget.postreconcile();
  assert.equal(widget.formData.get("name"), "Failed", "Retry reused partially initialized markup");
})().catch(error => {console.error(error); process.exitCode = 1;});
''')


# @matrix forms : reset unsaved-preservation
def test_explicit_revision_reset_can_replace_dirty_form(run_node):
    run_node(_FORM_WIDGET + r'''
(async () => {
  const widget = makeWidget();
  await widget.init();
  widget.target.field.value = "Local draft";
  widget.markUnsavedState();
  const commit = await widget.prepareRevision(response(new Target("Saved elsewhere")));
  assert.equal(widget.formData.get("name"), "Local draft");
  commit();
  assert.equal(widget.formData.get("name"), "Saved elsewhere");
  assert.equal(widget.unsavedState, false);
  assert.equal(widget.revisionBaseline, widget.revisionSnapshot());
})().catch(error => {console.error(error); process.exitCode = 1;});
''')


# @matrix user-groups : conditional-response initialization
def test_validated_html_initializes_cold_widget_without_rebuilding_loaded_widget(run_node):
    run_node(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const context = {};
vm.createContext(context);
vm.runInContext(fs.readFileSync("src/script/views/base/component.mjs", "utf8")
  .replace(/^import .*;\n/gm, "").replace(/export (default )?/g, "")
  + "\nglobalThis.ViewComponent = ViewComponent;", context);
(async () => {
  const calls = [];
  const widget = {name: "GroupPermissions/one", route: "/group", initialized: false,
    updated(response) {calls.push(response);}};
  const component = Object.create(context.ViewComponent.prototype);
  component.active = widget;
  component.view = {load: async () => ({updated: false})};
  await component.load(widget);
  assert.equal(calls.length, 1);
  widget.initialized = true;
  await component.load(widget);
  assert.equal(calls.length, 1);
})().catch(error => {console.error(error); process.exitCode = 1;});
''')


# @matrix forms : initialization teardown readonly
def test_declared_controls_are_lazy_owned_and_cleaned_on_failed_initialization(run_node):
    run_node(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const loads = [];
const controls = [];
let failure = false;
let release = null;
class Control {
  constructor(root, options) {Object.assign(this, {root, options, destroyed: 0}); controls.push(this);}
  async init() {
    if (failure) throw new Error("failed control");
    await new Promise(resolve => {release = resolve;});
  }
  destroy() {this.destroyed = 1;}
}
const context = {
  loadControl: async name => {loads.push(name); return {default: Control};},
};
vm.createContext(context);
for (const path of ["src/script/forms/controls/loader.mjs", "src/script/forms/controller.mjs"]) {
  vm.runInContext(fs.readFileSync(path, "utf8")
    .replace(/^import .*;\n/gm, "").replace(/export /g, "")
    .replace(/import\("\.\/([^\"]+)"\)/g, 'loadControl("$1")'), context);
}
vm.runInContext("globalThis.FormController = FormController;", context);
function root(marked = false) {
  return {dataset: {formControl: "access-restrictions"},
    querySelector: () => null, querySelectorAll: () => [],
    matches: () => marked, setAttribute() {}, addEventListener() {}, removeEventListener() {}};
}
function makeForm(target, readonly = false) {
  const form = new context.FormController({target, readonly});
  form._initSubmitButton = form._initOfflineState = form._initUnsavedState = () => {};
  return form;
}
(async () => {
  await makeForm(root()).init();
  assert.equal(loads.length, 0);
  const form = makeForm(root(true), true);
  const pending = form.init();
  while (!release) await Promise.resolve();
  assert.equal(controls[0].options.readonly, true);
  assert.equal(form.destroyables[0], controls[0]);
  form.destroy();
  release();
  await pending;
  assert.equal(controls[0].destroyed, 1);
  failure = true;
  await assert.rejects(makeForm(root(true)).init(), /failed control/);
  assert.equal(controls[1].destroyed, 1);
})().catch(error => {console.error(error); process.exitCode = 1;});
''')
