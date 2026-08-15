"""Node-backed checks for AI email address selection and copy behavior."""


# @features ai-email frontend
# @dimensions tool-selection eligibility clipboard fallback status-reset absent-markup
def test_ai_email_address_selection_and_copy_controls(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const appended = [];
const timers = [];
let clipboardText = null;
let fallbackCopies = 0;
const context = {
  console,
  navigator: { clipboard: { async writeText(value) { clipboardText = value; } } },
  document: {
    body: { append(node) { appended.push(node); } },
    createElement() {
      return {
        value: "",
        style: {},
        setAttribute() {},
        select() {},
        remove() {},
      };
    },
    execCommand(command) {
      if (command === "copy") fallbackCopies += 1;
      return true;
    },
  },
  setTimeout(callback) { timers.push(callback); return timers.length; },
  clearTimeout() {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/tools.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace(
  "export class CreateToolReport extends BaseUpload",
  "class CreateToolReport extends class {}",
);
source += "\nglobalThis.CreateToolReport = CreateToolReport;";
vm.runInContext(source, context);

const widget = Object.create(context.CreateToolReport.prototype);
widget.emailSubmissions = {
  dataset: {
    addressAsk: "ask@inbound.example.com",
    addressCreate: "create@inbound.example.com",
  },
};
widget.emailAddress = { textContent: "ask@inbound.example.com" };
widget.emailCopyButton = {
  textContent: "Copy",
  isConnected: true,
  focus() {},
};

(async () => {
  widget.updateEmailAddress("create");
  if (widget.emailAddress.textContent !== "create@inbound.example.com") {
    throw new Error("Eligible tool selection did not update the address");
  }
  widget.updateEmailAddress("organize");
  if (widget.emailAddress.textContent !== "create@inbound.example.com") {
    throw new Error("Missing/ineligible address should not replace the visible value");
  }

  await widget.copyEmailAddress();
  if (clipboardText !== "create@inbound.example.com" ||
      widget.emailCopyButton.textContent !== "Copied") {
    throw new Error("Clipboard success was not reported");
  }
  timers.shift()();
  if (widget.emailCopyButton.textContent !== "Copy") {
    throw new Error("Copy status did not reset");
  }

  context.navigator.clipboard.writeText = async () => { throw new Error("denied"); };
  await widget.copyEmailAddress();
  if (fallbackCopies !== 1 || appended.length !== 1 ||
      widget.emailCopyButton.textContent !== "Copied") {
    throw new Error("Clipboard fallback did not copy and report success");
  }

  const absent = Object.create(context.CreateToolReport.prototype);
  absent.emailSubmissions = null;
  absent.emailAddress = null;
  absent.emailCopyButton = null;
  absent.updateEmailAddress("ask");
  await absent.copyEmailAddress();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )
