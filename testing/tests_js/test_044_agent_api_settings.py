"""Node-backed checks for shown-once external-agent API key controls."""


# @matrix agent-api : expiry poll-reconcile revoke rotate shown-once status
# @matrix user-settings : poll-reconcile status
# @pair mcp-package:setup-panel
def test_agent_api_key_controls_keep_secret_ephemeral(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let stored = false;
const context = {
  AbortController,
  clearTimeout() {},
  console,
  FormElement: class {},
  InputElement: class {},
  RadioElement: class {},
  sections: {},
  SectionToggle: {},
  TextareaElement: class {},
  captureError() {},
  request: {
    async post() {
      return {
        ok: true,
        token: "lgn_identifier.secret",
        credential: {
          active: true,
          display_prefix: "lgn_ident…",
          expires_at: "2026-09-30T12:00:00+00:00",
        },
      };
    },
    async delete() {
      return { ok: true, credential: { active: false } };
    },
  },
  localStorage: {
    getItem() { stored = true; throw new Error("API key read from storage"); },
    setItem() { stored = true; throw new Error("API key written to storage"); },
  },
  withTransition() {},
  window: {},
};
context.PagePermissions = class {
  constructor() { this.destroyables = []; }
};
context.globalThis = context;
vm.createContext(context);

let source = fs.readFileSync("src/script/widgets/pageInfo.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replaceAll("export class ", "class ");
source += "\nglobalThis.UserSettings = UserSettings;";
vm.runInContext(source, context);

const elements = {
  status: { textContent: "" },
  issue: { disabled: false, textContent: "Generate API key" },
  revoke: { dataset: {}, disabled: false },
  secret: { dataset: {} },
  value: { textContent: "" },
  message: { dataset: {}, textContent: "" },
};
const selectors = new Map([
  ["[data-role='api-key-status']", elements.status],
  ["[data-action='issue-api-key']", elements.issue],
  ["[data-action='revoke-api-key']", elements.revoke],
  ["[data-role='api-key-secret']", elements.secret],
  ["[data-role='api-key-value']", elements.value],
  ["[data-role='api-key-message']", elements.message],
]);
const section = { querySelector(selector) { return selectors.get(selector) || null; } };
const widget = Object.create(context.UserSettings.prototype);
const confirmations = [];
widget._confirmApiKeyAction = async (_section, _trigger, options) => {
  confirmations.push(options);
  return true;
};

(async () => {
  await widget._issueApiKey(section, "/users/me/api-key");
  if (elements.value.textContent !== "lgn_identifier.secret" ||
      elements.secret.dataset.visible !== "true" ||
      elements.issue.textContent !== "Regenerate API key") {
    throw new Error("Issued key was not shown once with rotation state");
  }

  await widget._issueApiKey(section, "/users/me/api-key");
  if (confirmations.length !== 1 ||
      confirmations[0].title !== "Regenerate API key" ||
      confirmations[0].label !== "Regenerate API key") {
    throw new Error("Rotation did not use the application confirmation modal");
  }

  widget._renderApiKey(section, {
    active: true,
    display_prefix: "lgn_ident…",
    expires_at: "2026-09-30T12:00:00+00:00",
  });
  if (elements.value.textContent !== "" || elements.secret.dataset.visible !== "false") {
    throw new Error("Status refresh retained the shown-once secret");
  }

  await widget._revokeApiKey(section, "/users/me/api-key");
  if (confirmations.length !== 2 ||
      confirmations[1].title !== "Revoke API key" ||
      confirmations[1].label !== "Revoke API key") {
    throw new Error("Revocation did not use the application confirmation modal");
  }
  if (elements.revoke.dataset.visible !== "false" ||
      elements.issue.textContent !== "Generate API key") {
    throw new Error("Revocation did not clear active-key controls");
  }
  if (stored) throw new Error("API key touched browser storage");

  const initialized = [];
  widget._updated = true;
  widget.target = { dataset: {} };
  widget.commitReset = () => initialized.push("commit");
  widget._initGroups = () => initialized.push("groups");
  widget._initPageSelect = () => initialized.push("page-select");
  widget._initRemovePage = () => initialized.push("remove-page");
  widget._initApiKey = () => initialized.push("api-key");
  widget._initMcpSetup = () => initialized.push("mcp-setup");
  widget.setEntityMetadata = () => initialized.push("metadata");
  widget.postreconcile();
  if (initialized.join(",") !==
      "commit,groups,page-select,remove-page,api-key,mcp-setup,metadata" ||
      widget._updated !== false || widget.target.dataset.visible !== "true") {
    throw new Error("Polling replacement did not reinitialize API key status");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @matrix agent-api user-settings : confirmation-modal
def test_agent_api_key_confirmation_uses_app_modal(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const modalInstances = [];
class Modal {
  constructor(view, trigger) {
    this.view = view;
    this.trigger = trigger;
    this.removed = false;
    modalInstances.push(this);
  }
  async attach(element) {
    this.element = element;
    return element;
  }
  async remove() {
    this.removed = true;
  }
}

let capturedError = null;
const context = {
  AbortController,
  FormElement: class {},
  InputElement: class {},
  Modal,
  RadioElement: class {},
  sections: {},
  SectionToggle: {},
  TextareaElement: class {},
  captureError(error) { capturedError = error; },
  request: {},
  withTransition() {},
};
context.PagePermissions = class {
  constructor() { this.destroyables = []; }
};
context.globalThis = context;
vm.createContext(context);

let source = fs.readFileSync("src/script/widgets/pageInfo.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replaceAll("export class ", "class ");
source += "\nglobalThis.UserSettings = UserSettings;";
vm.runInContext(source, context);

let fixture = null;
function newFixture() {
  const title = { textContent: "" };
  const description = { textContent: "" };
  const label = { textContent: "" };
  let click = null;
  const confirm = {
    disabled: false,
    focused: false,
    querySelector(selector) {
      return selector === "[data-role='text']" ? label : null;
    },
    addEventListener(type, callback) {
      if (type === "click") click = callback;
    },
    focus() { this.focused = true; },
    async activate() { return click(); },
  };
  const modalElement = {
    querySelector(selector) {
      if (selector === "[data-role='confirmation-title']") return title;
      if (selector === "[data-role='confirmation-description']") return description;
      if (selector === "[data-role='confirmation-confirm']") return confirm;
      return null;
    },
  };
  return { confirm, description, label, modalElement, title };
}
const template = {
  content: {
    querySelector(selector) {
      if (selector !== "#modal") return null;
      return {
        cloneNode() {
          fixture = newFixture();
          return fixture.modalElement;
        },
      };
    },
  },
};
const section = {
  querySelector(selector) {
    return selector === "template[data-role='api-key-confirmation-template']"
      ? template
      : null;
  },
};
const trigger = {};
const widget = Object.create(context.UserSettings.prototype);
widget.view = { dataset: { kind: "user" } };

(async () => {
  const confirmed = widget._confirmApiKeyAction(section, trigger, {
    title: "Regenerate API key",
    description: "The old key will stop working.",
    label: "Regenerate API key",
  });
  await new Promise((resolve) => setImmediate(resolve));
  if (capturedError || modalInstances.length !== 1 ||
      fixture.title.textContent !== "Regenerate API key" ||
      fixture.description.textContent !== "The old key will stop working." ||
      fixture.label.textContent !== "Regenerate API key" ||
      fixture.confirm.focused !== true) {
    throw new Error("Application confirmation modal was not prepared correctly");
  }
  await fixture.confirm.activate();
  if (await confirmed !== true || modalInstances[0].removed !== true) {
    throw new Error("Confirm did not resolve true and close the application modal");
  }

  const cancelled = widget._confirmApiKeyAction(section, trigger, {
    title: "Revoke API key",
    description: "The key will stop working.",
    label: "Revoke API key",
  });
  await new Promise((resolve) => setImmediate(resolve));
  await modalInstances[1].remove();
  if (await cancelled !== false || modalInstances[1].removed !== true) {
    throw new Error("Modal dismissal did not cancel the API key operation");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
