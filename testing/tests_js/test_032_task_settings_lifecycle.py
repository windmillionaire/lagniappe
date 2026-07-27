"""Node-backed checks for task-settings action-control lifecycle behavior."""


# @features tasks
# @dimensions action-control-lifecycle teardown
def test_task_settings_awaits_action_controls_and_cleans_up(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
let resolveUpload;
const uploadReady = new Promise((resolve) => { resolveUpload = resolve; });

class FormElement {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.destroyables = [];
  }

  async _initForm() {
    events.push("form:init");
  }

  destroy() {
    events.push("form:destroy");
    for (const destroyable of this.destroyables) destroyable.destroy?.();
    this.destroyables = [];
  }
}

const controls = {};
function createControl(kind) {
  const control = {
    kind,
    async init() {
      events.push(`${kind}:init`);
      if (kind === "upload") await uploadReady;
      events.push(`${kind}:ready`);
    },
    destroy() {
      events.push(`${kind}:destroy`);
    },
  };
  controls[kind] = control;
  return control;
}

const SectionToggle = {
  facet: () => createControl("facet"),
  date: () => createControl("date"),
  upload: () => createControl("upload"),
};

let updatedListener = null;
const actionButtons = {
  querySelectorAll(selector) {
    if (selector !== "button[data-action]") {
      throw new Error(`Unexpected action selector: ${selector}`);
    }
    return [
      { dataset: { action: "uploadFile" } },
      { dataset: { action: "selectProject" } },
    ];
  },
  addEventListener(name, listener) {
    events.push(`listener:add:${name}`);
    updatedListener = listener;
  },
  removeEventListener(name, listener) {
    if (name === "updated" && listener === updatedListener) {
      events.push(`listener:remove:${name}`);
      updatedListener = null;
    }
  },
};
const target = {
  querySelector(selector) {
    if (selector === "[data-role='action-buttons']") return actionButtons;
    return null;
  },
};

const context = {
  FormElement,
  InputElement: class {},
  SectionToggle,
  TextareaElement: class {},
  console,
};
vm.createContext(context);

let source = fs.readFileSync("src/script/widgets/taskSettings.mjs", "utf8");
source = source.replace(/import .*?;\n/g, "");
source = source.replaceAll("export class ", "class ");
source += "\nglobalThis.BaseTaskSettings = BaseTaskSettings;";
vm.runInContext(source, context);

(async () => {
  const widget = new context.BaseTaskSettings({ target });

  if (widget.actions !== actionButtons || events.length !== 0) {
    throw new Error("Reading actions should not initialize controls");
  }

  let settled = false;
  const initializing = widget._initForm().then(() => { settled = true; });
  await new Promise((resolve) => setImmediate(resolve));

  const pendingEvents = JSON.stringify(events);
  if (settled ||
      pendingEvents !== JSON.stringify(["form:init", "upload:init"])) {
    throw new Error(`Task settings did not await upload readiness: ${pendingEvents}`);
  }
  if (updatedListener || Object.keys(widget.buttons).length !== 0 ||
      widget.destroyables.length !== 0) {
    throw new Error("Pending controls were exposed before becoming ready");
  }

  resolveUpload();
  await initializing;

  const readyEvents = JSON.stringify(events);
  const expectedReady = JSON.stringify([
    "form:init",
    "upload:init",
    "upload:ready",
    "facet:init",
    "facet:ready",
    "listener:add:updated",
  ]);
  if (readyEvents !== expectedReady) {
    throw new Error(`Action controls initialized out of order: ${readyEvents}`);
  }
  if (widget.buttons.uploadFile !== controls.upload ||
      widget.buttons.selectProject !== controls.facet ||
      widget.destroyables.length !== 2 ||
      !updatedListener) {
    throw new Error("Ready action controls were not registered");
  }

  widget.destroy();
  const destroyedEvents = JSON.stringify(events.slice(-4));
  const expectedDestroyed = JSON.stringify([
    "listener:remove:updated",
    "form:destroy",
    "upload:destroy",
    "facet:destroy",
  ]);
  if (destroyedEvents !== expectedDestroyed ||
      Object.keys(widget.buttons).length !== 0 ||
      widget.destroyables.length !== 0 ||
      updatedListener) {
    throw new Error(`Task settings cleanup was incomplete: ${JSON.stringify(events)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )
