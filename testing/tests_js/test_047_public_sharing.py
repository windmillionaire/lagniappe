"""Node-backed checks for the dependency-free public sharing control."""


# @matrix public-pages : entrypoint initialization
def test_public_share_entry_initializes_once(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

let calls = 0;
const context = {
  initializePublicSharing() { calls += 1; },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/public.mjs", "utf8");
source = source.replace(
  'import { initializePublicSharing } from "./shared/publicShare";',
  "const initializePublicSharing = globalThis.initializePublicSharing;",
);
source = source.replace(/export /g, "");
vm.runInContext(source, context);
if (calls !== 1) throw new Error("Public sharing entry did not initialize once");
"""
    )


# @matrix public-pages : abort clipboard fallback native-share selectable-url sharing
def test_public_share_uses_native_api_and_clipboard_fallbacks(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const state = { native: [], clipboard: [], legacy: 0, selected: 0 };
const status = { textContent: "" };
const label = { textContent: "Share" };
const input = { focus() {}, select() { state.selected += 1; } };
const fallback = {
  classList: { remove(value) { if (value === "hidden") this.visible = true; } },
  querySelector() { return input; },
};
const container = {
  querySelector(selector) {
    if (selector.includes("share-status")) return status;
    if (selector.includes("share-fallback")) return fallback;
    return null;
  },
};
const button = {
  dataset: {
    shareUrl: "https://site.test/pages/public/id",
  },
  closest() { return container; },
  querySelector(selector) {
    return selector.includes("share-label") ? label : null;
  },
};
const root = {
  body: { append() {} },
  createElement() {
    return {
      value: "",
      style: {},
      setAttribute() {},
      select() {},
      remove() {},
    };
  },
  execCommand() { state.legacy += 1; return true; },
};
const context = {
  console,
  document: root,
  navigator: {
    canShare() { return true; },
    async share(payload) { state.native.push(payload); },
    clipboard: { async writeText(value) { state.clipboard.push(value); } },
  },
  withTransition(callback) { callback(); return Promise.resolve(true); },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/publicShare.mjs", "utf8");
source = source.replace(
  'import { withTransition } from "./utilities";',
  "const withTransition = globalThis.withTransition;",
);
source = source.replace(/export /g, "");
source += `
globalThis.copyPublicUrl = copyPublicUrl;
globalThis.sharePublicPage = sharePublicPage;
`;
vm.runInContext(source, context);

(async () => {
  await context.sharePublicPage(button, root);
  if (state.native.length !== 1 || state.clipboard.length !== 0) {
    throw new Error("Native share was not preferred");
  }
  const nativePayload = state.native[0];
  if (Object.keys(nativePayload).join(",") !== "url" ||
      nativePayload.url !== button.dataset.shareUrl) {
    throw new Error("Native share included content other than the public URL");
  }
  if (label.textContent !== "Shared" || status.textContent !== "Page shared") {
    throw new Error("Native share completion was not visible");
  }

  context.navigator.share = async () => { throw new Error("unavailable"); };
  await context.sharePublicPage(button, root);
  if (state.clipboard.join(",") !== button.dataset.shareUrl ||
      status.textContent !== "Link copied" || label.textContent !== "Copied") {
    throw new Error("Clipboard fallback was not used after native failure");
  }

  context.navigator.share = async () => {
    const error = new Error("cancelled");
    error.name = "AbortError";
    throw error;
  };
  status.textContent = "";
  await context.sharePublicPage(button, root);
  if (state.clipboard.length !== 1 || status.textContent !== "" ||
      label.textContent !== "Share") {
    throw new Error("Cancelled native sharing reported or copied unexpectedly");
  }

  context.navigator.share = undefined;
  context.navigator.clipboard.writeText = async () => { throw new Error("denied"); };
  await context.sharePublicPage(button, root);
  if (state.legacy !== 1 || status.textContent !== "Link copied" ||
      label.textContent !== "Copied") {
    throw new Error("Legacy copy fallback did not complete");
  }

  root.execCommand = () => false;
  await context.sharePublicPage(button, root);
  if (!fallback.classList.visible || state.selected !== 1 ||
      label.textContent !== "Copy link") {
    throw new Error("Selectable URL fallback was not revealed");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @matrix public-pages : initialization sharing
def test_public_share_initialization_binds_one_click_handler(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

let listeners = 0;
const button = {
  dataset: {},
  addEventListener(type) { if (type === "click") listeners += 1; },
};
const context = {
  console,
  document: { querySelector() { return button; } },
  navigator: {},
  withTransition(callback) { callback(); return Promise.resolve(true); },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/publicShare.mjs", "utf8");
source = source.replace(
  'import { withTransition } from "./utilities";',
  "const withTransition = globalThis.withTransition;",
);
source = source.replace(/export /g, "");
source += "\nglobalThis.initializePublicSharing = initializePublicSharing;";
vm.runInContext(source, context);

context.initializePublicSharing(context.document);
context.initializePublicSharing(context.document);
if (listeners !== 1 || button.dataset.shareInitialized !== "true") {
  throw new Error("Sharing initialized more than once");
}
"""
    )
