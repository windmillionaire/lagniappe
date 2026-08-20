"""DOM-light checks for user widget reconciliation behavior."""


# @features users
# @dimensions create-form create-form-reset focus-preservation
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

class FormElement {
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
class PermissionsForm {}
class RadioElement {}

const context = {
  console,
  document,
  FacetedSearchElement,
  FormElement,
  InputElement,
  PermissionsForm,
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


# @features user-groups
# @dimensions rename reset-rebinding
def test_group_permissions_tracks_rename_draft_after_target_rebuild(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeEdit {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  input(value) {
    this.listeners.get("input")?.({
      target: {
        matches(selector) { return selector === "input[name='name']"; },
        value,
      },
    });
  }
}

class InputElement {
  constructor(_widget, _schema, submission) {
    this.edit = new FakeEdit();
    this.submission = submission;
  }
}

class PermissionsForm {
  constructor(attributes = {}) {
    Object.assign(this, attributes);
  }

  get formData() {
    return new Map();
  }

  get html() {
    return [];
  }

  updated(response) {
    this.lastResponse = response;
  }
}

const context = {
  console,
  FacetedSearchElement: class {},
  FormElement: class {},
  InputElement,
  PermissionsForm,
  RadioElement: class {},
};
vm.createContext(context);

let source = fs.readFileSync("src/script/widgets/user.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replaceAll("export class ", "class ");
source += "\nglobalThis.GroupPermissions = GroupPermissions;";
vm.runInContext(source, context);

const widget = new context.GroupPermissions({
  target: { dataset: { name: "Original Group" } },
});
const firstName = widget.html[0];
firstName.input("First Draft");
if (
  widget._draftName !== "First Draft" ||
  widget.target.dataset.name !== "First Draft"
) {
  throw new Error("Initial group-name control did not track its draft");
}

widget.target = { dataset: { name: "First Draft" } };
const rebuiltName = widget.html[0];
rebuiltName.input("Rebuilt Draft");
if (
  widget._draftName !== "Rebuilt Draft" ||
  widget.target.dataset.name !== "Rebuilt Draft"
) {
  throw new Error("Rebuilt group-name control lost its draft listener");
}

if (widget.formData.get("name") !== "Rebuilt Draft") {
  throw new Error("Rebuilt group rename was not retained for submission");
}
'''
    )
