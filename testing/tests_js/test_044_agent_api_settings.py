"""Node-backed checks for shown-once external-agent API key controls."""


# @matrix agent-api user-settings : copy expiry revoke rotate shown-once
def test_agent_api_key_controls_keep_secret_ephemeral(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let clipboard = null;
let stored = false;
const context = {
  AbortController,
  clearTimeout() {},
  console,
  document: { execCommand() { return false; } },
  FormElement: class {},
  InputElement: class {},
  RadioElement: class {},
  sections: {},
  SectionToggle: {},
  TextareaElement: class {},
  captureError() {},
  navigator: { clipboard: { async writeText(value) { clipboard = value; } } },
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
  setTimeout(callback) { return callback; },
  withTransition() {},
  window: { confirm() { return true; } },
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
  value: { value: "", select() {} },
  message: { dataset: {}, textContent: "" },
  copy: { focus() {}, isConnected: true, textContent: "Copy API key" },
};
const selectors = new Map([
  ["[data-role='api-key-status']", elements.status],
  ["[data-action='issue-api-key']", elements.issue],
  ["[data-action='revoke-api-key']", elements.revoke],
  ["[data-role='api-key-secret']", elements.secret],
  ["[data-role='api-key-value']", elements.value],
  ["[data-role='api-key-message']", elements.message],
  ["[data-action='copy-api-key']", elements.copy],
]);
const section = { querySelector(selector) { return selectors.get(selector) || null; } };
const widget = Object.create(context.UserSettings.prototype);

(async () => {
  await widget._issueApiKey(section, "/users/me/api-key");
  if (elements.value.value !== "lgn_identifier.secret" ||
      elements.secret.dataset.visible !== "true" ||
      elements.issue.textContent !== "Regenerate API key") {
    throw new Error("Issued key was not shown once with rotation state");
  }

  await widget._copyApiKey(section);
  if (clipboard !== "lgn_identifier.secret" || elements.copy.textContent !== "Copied") {
    throw new Error("Full API key was not copied");
  }

  widget._renderApiKey(section, {
    active: true,
    display_prefix: "lgn_ident…",
    expires_at: "2026-09-30T12:00:00+00:00",
  });
  if (elements.value.value !== "" || elements.secret.dataset.visible !== "false") {
    throw new Error("Status refresh retained the shown-once secret");
  }

  await widget._revokeApiKey(section, "/users/me/api-key");
  if (elements.revoke.dataset.visible !== "false" ||
      elements.issue.textContent !== "Generate API key") {
    throw new Error("Revocation did not clear active-key controls");
  }
  if (stored) throw new Error("API key touched browser storage");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
