"""Node-backed checks for login action-button state."""


# @features login
# @dimensions submit-button loading-state
def test_login_action_button_uses_fixed_icon_and_text_slots(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.textContent = "";
    this.attributes = {};
  }

  querySelector(selector) {
    const match = selector.match(/\[data-role='([^']+)'\]/);
    return match
      ? this.children.find((child) => child.dataset.role === match[1]) || null
      : null;
  }

  replaceChildren(...children) {
    this.children = children;
  }

  prepend(child) {
    this.children.unshift(child);
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }
}

const createIcon = (name) => {
  const icon = new FakeElement();
  icon.dataset.icon = name;
  return icon;
};
const context = {
  createIcon,
  document: {
    createElement: () => new FakeElement(),
  },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/login/forms.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace(
  /export \{[\s\S]*?\};/,
  "globalThis.setLoginActionButton = setLoginActionButton;",
);
vm.runInContext(source, context);

const button = new FakeElement();
const iconSlot = new FakeElement();
iconSlot.dataset.role = "icon";
iconSlot.dataset.visible = "false";
const textSlot = new FakeElement();
textSlot.dataset.role = "text";
textSlot.textContent = "Continue";
button.replaceChildren(iconSlot, textSlot);

context.setLoginActionButton(button, "Checking Email", "spinner");
if (button.children[0] !== iconSlot || button.children[1] !== textSlot) {
  throw new Error("Login button replaced its fixed icon or text slot");
}
if (
  iconSlot.dataset.visible !== "true" ||
  iconSlot.children[0]?.dataset.icon !== "spinner"
) {
  throw new Error("Login button did not render its spinner in the icon slot");
}
if (textSlot.textContent !== "Checking Email") {
  throw new Error("Login button did not update its text slot");
}

context.setLoginActionButton(button, "Continue");
if (iconSlot.dataset.visible !== "false" || iconSlot.children.length !== 0) {
  throw new Error("Login button did not clear and hide its icon slot");
}
if (textSlot.textContent !== "Continue") {
  throw new Error("Login button did not restore its text slot");
}

const unstructuredButton = new FakeElement();
context.setLoginActionButton(unstructuredButton, "Sign In", "spinner");
if (
  unstructuredButton.children[0]?.dataset.role !== "icon" ||
  unstructuredButton.children[1]?.dataset.role !== "text"
) {
  throw new Error("Login helper did not normalize an unstructured button");
}
"""
    )


# @features login
# @dimensions owner-bootstrap disabled-provider
def test_owner_setup_supports_password_only_mode(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeClassList {
  constructor(...names) { this.names = new Set(names); }
  add(name) { this.names.add(name); }
  remove(name) { this.names.delete(name); }
  contains(name) { return this.names.has(name); }
}

class FakeElement {
  constructor(selectors = {}, classes = []) {
    this.selectors = selectors;
    this.classList = new FakeClassList(...classes);
    this.dataset = {};
    this.textContent = "";
    this.value = "";
  }
  querySelector(selector) { return this.selectors[selector] || null; }
  querySelectorAll() { return []; }
  addEventListener() {}
  setAttribute(name, value) { this[name] = value; }
  replaceChildren(...children) { this.children = children; }
  prepend(child) { this.children = [child, ...(this.children || [])]; }
  focus() { this.focused = true; }
}

const googleError = new FakeElement({}, ["hidden"]);
const passwordError = new FakeElement({}, ["hidden"]);
const success = new FakeElement({}, ["hidden"]);
const password = new FakeElement();
const googleSetup = new FakeElement(
  { "[data-role='error']": googleError },
  ["hidden"],
);
const passwordSetup = new FakeElement({
  "[data-role='error']": passwordError,
  "input[type='password']": password,
});
const actionText = new FakeElement();
actionText.textContent = "Create Password";
actionText.dataset.role = "text";
const actionButton = new FakeElement({ "[data-role='text']": actionText });
const form = new FakeElement({
  "[data-role='error']": googleError,
  "[data-role='success']": success,
  "[data-role='owner-google-setup']": googleSetup,
  "[data-role='owner-password-setup']": passwordSetup,
  "[data-role='signin']": actionButton,
}, ["hidden"]);

const context = {
  createIcon() { return new FakeElement(); },
  document: { createElement: () => new FakeElement() },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/login/forms.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace(
  /export \{[\s\S]*?\};/,
  "globalThis.OwnerSetupForm = OwnerSetupForm;",
);
vm.runInContext(source, context);

const ownerSetup = new context.OwnerSetupForm({}, form);
ownerSetup.data = { email: "owner@example.test", error: "Provider unavailable" };
ownerSetup.show();

if (ownerSetup.error !== passwordError) {
  throw new Error("Password-only owner setup did not select its visible error slot");
}
if (passwordSetup.classList.contains("hidden")) {
  throw new Error("Password-only owner setup hid its available setup pane");
}
if (form.classList.contains("hidden")) {
  throw new Error("Password-only owner setup did not open");
}
if (passwordError.textContent !== "Provider unavailable") {
  throw new Error("Password-only owner setup did not display its error safely");
}
"""
    )
