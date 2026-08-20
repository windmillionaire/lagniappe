"""Node-backed coverage for file-processing reconciliation state."""


# @pairs file:extract file:reload file:text-tab file:authoritative-remount
def test_file_info_extract_completion_requests_one_reload_notice(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
let hasTextTab = false;
class FormElement {
  updated() { events.push("base-updated"); }
  async postreconcile() { events.push("base-postreconcile"); }
  setEntityMetadata() { events.push("metadata"); }
}
const context = {
  console,
  document: {
    getElementById(id) { return id === "text" && hasTextTab ? {} : null; },
  },
  FormElement,
  InputElement: class {},
  primitives: {},
  SectionToggle: {},
  setIcon() {},
  STYLES: { label: { default: "" } },
  TextareaElement: class {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/fileInfo.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class FileInfo", "class FileInfo");
source += "\nglobalThis.FileInfo = FileInfo;";
vm.runInContext(source, context);

let notices = 0;
const info = Object.create(context.FileInfo.prototype);
info._refreshExtractOnReconcile = false;
info.view = { showExtractReloadNotice() { notices += 1; } };
const response = {
  html: {
    querySelector() {
      return {
        dataset: {
          options: JSON.stringify({
            extract: { complete: true, status: "Text extraction complete." },
          }),
        },
      };
    },
  },
};

(async () => {
  info.updated(response);
  if (!info._refreshExtractOnReconcile) {
    throw new Error("Extract completion did not stage a reload notice");
  }
  await info.postreconcile();
  await info.postreconcile();
  if (notices !== 1 || info._refreshExtractOnReconcile) {
    throw new Error(`Reload notice was not one-shot: ${notices}`);
  }

  hasTextTab = true;
  info.updated(response);
  await info.postreconcile();
  if (notices !== 1) {
    throw new Error("Mounted text tab incorrectly requested a reload");
  }

  hasTextTab = false;
  info.updated({ html: { querySelector() { return null; } } });
  await info.postreconcile();
  if (notices !== 1) {
    throw new Error("Missing replacement options reused stale extract state");
  }
  if (
    events.filter((event) => event === "base-updated").length !== 3 ||
    events.filter((event) => event === "base-postreconcile").length !== 4 ||
    events.filter((event) => event === "metadata").length !== 4
  ) {
    throw new Error(`Base form reconciliation drifted: ${JSON.stringify(events)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features file
# @dimensions extract reload text-tab authoritative-remount
def test_file_view_shows_extract_reload_only_for_matching_unmounted_text(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let reloads = 0;
class Entity {}
const context = {
  console,
  Entity,
  window: { location: { reload() { reloads += 1; } } },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/views/file.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export default class File", "class File");
source += "\nglobalThis.File = File;";
vm.runInContext(source, context);

const notice = { dataset: { visible: "false" } };
let hasTextTab = false;
const flashes = [];
const view = Object.create(context.File.prototype);
view.key = "file-key";
view.elt = {
  querySelector(selector) {
    if (selector === "#text") return hasTextTab ? {} : null;
    if (selector === "[data-role='extract-reload']") return notice;
    return null;
  },
};
view.addFlash = (node) => flashes.push(node);

view.afterReconcileChange({ type: "entity-poll", key: "file-key" });
view.afterReconcileChange({ type: "extract-complete", key: "other-file" });
if (notice.dataset.visible !== "false" || flashes.length) {
  throw new Error("Unrelated reconciliation displayed the reload notice");
}

hasTextTab = true;
view.afterReconcileChange({ type: "extract-complete", key: "file-key" });
if (notice.dataset.visible !== "false" || flashes.length) {
  throw new Error("Mounted text tab displayed the reload notice");
}

hasTextTab = false;
view.afterReconcileChange({ type: "extract-complete", key: "file-key" });
if (notice.dataset.visible !== "true" || flashes[0] !== notice) {
  throw new Error("Matching extract completion did not display the reload notice");
}

view._reloadAfterExtract({ target: { closest() { return null; } } });
view._reloadAfterExtract({ target: { closest() { return {}; } } });
if (reloads !== 1) {
  throw new Error(`Reload button did not reload exactly once: ${reloads}`);
}
'''
    )
