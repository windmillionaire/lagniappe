"""DOM-light checks for user widget reconciliation behavior."""


# @matrix users : create-form create-form-reset focus-preservation visibility-isolation
def test_create_user_focuses_on_open_and_reset_without_stealing_live_field_focus(
    run_node,
):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let activeElement = null;
const body = { id: "body" };
const document = {
  body,
  get activeElement() { return activeElement; },
};

class FormWidget {
  constructor(attributes = {}) {
    Object.assign(this, attributes);
    this._created = false;
    this._updated = false;
  }

  async prereconcile() {}

  postreconcile() {
    this._created = false;
    this._updated = false;
  }
}

class FacetedSearchElement {}
class InputElement {}
class RadioElement {}

const context = {
  console,
  document,
  FacetedSearchElement,
  FormWidget,
  InputElement,
  RadioElement,
};
vm.createContext(context);

let source = fs.readFileSync("src/script/widgets/user.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replaceAll("export class ", "class ");
source += "\nglobalThis.CreateUser = CreateUser;";
vm.runInContext(source, context);

function createWidget(visible) {
  const name = { id: "name" };
  const email = { id: "email" };
  const submit = { id: "submit" };
  const target = {
    dataset: { visible: visible ? "true" : "false" },
    contains(element) {
      return [name, email, submit].includes(element);
    },
  };
  let focusCount = 0;
  const widget = new context.CreateUser({ target });
  widget.nameElement = {
    focus() {
      focusCount += 1;
      activeElement = name;
    },
  };
  widget.form = {
    resetSubmitButton() {
      widget.submitReset = true;
    },
  };
  widget.prepareReset = async () => {
    widget.resetPrepared = true;
  };
  widget.commitReset = () => {
    const resetName = { id: "reset-name" };
    widget.target = {
      dataset: { visible: "true" },
      contains(element) { return element === resetName; },
    };
    widget.nameElement = {
      focus() {
        focusCount += 1;
        activeElement = resetName;
      },
    };
    activeElement = body;
    return true;
  };
  return {
    email,
    get focusCount() { return focusCount; },
    submit,
    target,
    widget,
  };
}

(async () => {
  const opening = createWidget(false);
  activeElement = body;
  await opening.widget.prereconcile();
  opening.target.dataset.visible = "true";
  opening.widget.postreconcile();
  if (opening.focusCount !== 1) {
    throw new Error("Opening the create-user form did not focus its name field");
  }

  const movedDuringOpen = createWidget(false);
  activeElement = body;
  await movedDuringOpen.widget.prereconcile();
  activeElement = movedDuringOpen.email;
  movedDuringOpen.target.dataset.visible = "true";
  movedDuringOpen.widget.postreconcile();
  if (movedDuringOpen.focusCount !== 0 || activeElement !== movedDuringOpen.email) {
    throw new Error("Late open reconciliation stole focus from the email field");
  }

  const ordinary = createWidget(true);
  activeElement = ordinary.email;
  await ordinary.widget.prereconcile();
  ordinary.widget.postreconcile();
  if (ordinary.focusCount !== 0 || activeElement !== ordinary.email) {
    throw new Error("Ordinary reconciliation stole focus from a live form field");
  }

  const inactive = createWidget(false);
  inactive.widget.visible = false;
  inactive.widget.postreconcile();
  if (inactive.target.dataset.visible !== "false") {
    throw new Error("Inactive create-user reconciliation made the form visible");
  }

  const created = createWidget(true);
  created.widget._created = true;
  activeElement = created.submit;
  await created.widget.prereconcile();
  created.widget.postreconcile();
  if (
    !created.widget.resetPrepared ||
    !created.widget.submitReset ||
    created.focusCount !== 1 ||
    activeElement.id !== "reset-name"
  ) {
    throw new Error("A completed create did not reset and focus the fresh name field");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @matrix user-groups : rename reset-rebinding
def test_group_permissions_tracks_rename_draft_after_target_rebuild(run_node):
    run_node(
        r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const node = name => ({dataset: {name}, input: {value: name}, querySelector() {return this.input;}});
class FormWidget {
  constructor(attributes) {Object.assign(this, attributes);}
  get formData() {return new Map([["name", this.target.input.value]]);}
  async prepareSubmit() {return true;}
  markUnsavedState() {this.unsavedState = true;}
  async reset() {}
  async prepareRevision() {}
  postreconcile() {
    if (!this._updated) return;
    this.target = this.initialTarget;
    this._updated = false;
    this.unsavedState = false;
  }
}
const context = {FormWidget};
vm.createContext(context);
vm.runInContext(fs.readFileSync("src/script/widgets/userPermissions.mjs", "utf8")
  .replace(/^import .*;\n/gm, "").replaceAll("export class ", "class ")
  + "\nglobalThis.GroupPermissions = GroupPermissions;", context);
const label = {textContent: "Original"};
const button = {dataset: {key: "group"}, querySelector: () => label};
const widget = new context.GroupPermissions({target: node("Original"), key: "group",
  component: {elt: {querySelectorAll: () => [button]}}});
(async () => {
  widget.target.input.value = "First rename";
  await widget.prepareSubmit();
  widget.initialTarget = node("First rename");
  widget._updated = true;
  widget.postreconcile();
  assert.equal(label.textContent, "First rename");
  widget.target.input.value = "Second rename";
  assert.equal(widget.formData.get("name"), "Second rename");
  await widget.prepareSubmit();
  widget.target.input.value = "Newer draft";
  widget.initialTarget = node("Second rename");
  widget._updated = true;
  widget.postreconcile();
  assert.equal(widget.formData.get("name"), "Newer draft");
  assert.equal(label.textContent, "Second rename");
  assert.equal(widget.unsavedState, true);
  widget.revisionPreview = true;
  widget.initialTarget = node("Preview only");
  widget._updated = true;
  widget.postreconcile();
  assert.equal(label.textContent, "Second rename");
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    )
