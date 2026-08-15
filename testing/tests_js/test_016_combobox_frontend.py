"""Node-backed checks for combobox positioning and interaction behavior."""

import textwrap


COMBOBOX_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...values) {
    values.forEach((value) => this.values.add(value));
  }

  remove(...values) {
    values.forEach((value) => this.values.delete(value));
  }

  contains(value) {
    return this.values.has(value);
  }
}

class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
    this.dispatched = [];
  }

  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(handler);
  }

  removeEventListener(type, handler) {
    this.listeners.get(type)?.delete(handler);
  }

  dispatchEvent(event) {
    event.target ||= this;
    this.dispatched.push(event);
    this.listeners.get(event.type)?.forEach((handler) => handler(event));
    return true;
  }
}

class FakeElement extends FakeEventTarget {
  constructor(tagName = "div", options = {}) {
    super();
    this.tagName = tagName.toUpperCase();
    this.attributes = new Map();
    this.children = [];
    this.classList = new FakeClassList();
    this.dataset = { ...(options.dataset || {}) };
    this.id = options.id || "";
    this.isConnected = true;
    this.name = options.name || "";
    this.parentElement = null;
    this.rect = options.rect || { width: 100 };
    this.style = {};
  }

  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }

  blur() {
    this.blurred = true;
  }

  closest(selector) {
    const role = selector.match(/^\[role="([^"]+)"\]$/)?.[1];
    let current = this;
    while (current) {
      if (role && current.getAttribute("role") === role) return current;
      current = current.parentElement;
    }
    return null;
  }

  contains(element) {
    if (element === this) return true;
    return this.children.some((child) => child.contains(element));
  }

  focus() {
    this.focused = true;
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  getBoundingClientRect() {
    return this.rect;
  }

  querySelector(selector) {
    if (selector === "select, input") {
      return this.formControl || null;
    }
    const index = selector.match(/^\[data-index="(\d+)"\]$/)?.[1];
    if (index !== undefined) {
      return this.children.find((child) => child.dataset.index === index) || null;
    }
    return null;
  }

  querySelectorAll(selector) {
    const role = selector.match(/^\[role='([^']+)'\]$/)?.[1];
    if (role) {
      return this.children.filter((child) => child.getAttribute("role") === role);
    }
    return [];
  }

  remove() {
    this.isConnected = false;
    if (this.parentElement) {
      this.parentElement.children = this.parentElement.children.filter(
        (child) => child !== this,
      );
    }
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  scrollIntoView(options) {
    this.scrolledWith = options;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
}

class FakeDocument extends FakeEventTarget {
  constructor() {
    super();
    this.body = new FakeElement("body");
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }

  querySelectorAll() {
    return [];
  }
}

class FakeIntersectionObserver {
  constructor(callback) {
    this.callback = callback;
    observers.push(this);
  }

  disconnect() {
    this.disconnected = true;
  }

  observe(element) {
    this.observed = element;
  }
}

class FakeEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = options.bubbles || false;
  }
}

function interactionEvent(options = {}) {
  return {
    defaultPrevented: false,
    propagationStopped: false,
    ...options,
    preventDefault() {
      this.defaultPrevented = true;
    },
    stopPropagation() {
      this.propagationStopped = true;
    },
  };
}

function makeComboboxElements() {
  const parent = new FakeElement("label", { dataset: { index: "people" } });
  const initial = new FakeElement("select", {
    dataset: { index: "people" },
    id: "people",
    name: "people",
  });
  parent.formControl = initial;
  parent.appendChild(initial);
  return { initial, parent };
}

function option(index, id) {
  const element = new FakeElement("button", {
    dataset: { index: String(index) },
    id,
  });
  element.setAttribute("role", "option");
  return element;
}

const autoUpdateCalls = [];
const computePositionCalls = [];
const capturedErrors = [];
const observers = [];

const autoUpdate = (reference, panel, callback) => {
  const call = { callback, cleaned: false, panel, reference };
  autoUpdateCalls.push(call);
  callback();
  return () => {
    call.cleaned = true;
  };
};
let computePositionImpl = (reference, panel, options) => Promise.resolve({
  placement: options.placement,
  x: 101,
  y: 202,
});
const computePosition = (reference, panel, options) => {
  computePositionCalls.push({ options, panel, reference });
  return computePositionImpl(reference, panel, options);
};
const flip = (options) => ({ name: "flip", options });
const offset = (value) => ({ name: "offset", value });
const shift = (options) => ({ name: "shift", options });

const document = new FakeDocument();
const context = {
  autoUpdate,
  captureError(error) { capturedErrors.push(error); },
  capturedErrors,
  computePosition,
  console,
  document,
  Event: FakeEvent,
  flip,
  generateElementId: () => "generated-combobox",
  IntersectionObserver: FakeIntersectionObserver,
  offset,
  primitives: {},
  setIcon(element, name, classes = "") {
    element.className = `icon ${classes}`.trim();
    element.dataset.icon = name;
    element.textContent = name;
    return element;
  },
  shift,
  setComputePosition(implementation) { computePositionImpl = implementation; },
  STYLES: {
    dropdown: {
      icon: "dropdown-option-icon",
      option: {
        action: "dropdown-option dropdown-option-action",
      },
      panel: "dropdown-panel hidden",
    },
  },
  window: {
    matchMedia() {
      return { matches: false };
    },
  },
};

vm.createContext(context);
let comboboxSource = fs.readFileSync(
  "src/script/elements/combobox/combobox.mjs",
  "utf8",
);
comboboxSource = comboboxSource.replace(
  /import \{[\s\S]*?\} from "@floating-ui\/dom";\n/,
  "",
);
comboboxSource = comboboxSource.replace('import { STYLES } from "styles";\n', "");
comboboxSource = comboboxSource.replace(
  'import { captureError, generateElementId } from "../../shared";\n',
  "",
);
comboboxSource = comboboxSource.replace(
  'import { primitives } from "../primitives";\n',
  "",
);
comboboxSource = comboboxSource.replace("export class Combobox", "class Combobox");
comboboxSource += "\nglobalThis.Combobox = Combobox;";
vm.runInContext(comboboxSource, context);

let submitterSource = fs.readFileSync(
  "src/script/elements/combobox/submitter.mjs",
  "utf8",
);
submitterSource = submitterSource.replace(
  "export const Submitter",
  "const Submitter",
);
submitterSource += "\nglobalThis.Submitter = Submitter;";
vm.runInContext(submitterSource, context);

let dropdownSource = fs.readFileSync(
  "src/script/elements/combobox/dropdown.mjs",
  "utf8",
);
dropdownSource = dropdownSource.replace(/^import .*;\n/gm, "");
dropdownSource = dropdownSource.replace("export class Dropdown", "class Dropdown");
dropdownSource += "\nglobalThis.Dropdown = Dropdown;";
vm.runInContext(dropdownSource, context);

const Combobox = context.Combobox;
const Dropdown = context.Dropdown;
const Submitter = context.Submitter;

(async () => {
__ASSERTION__
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


ENTITY_MENU_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

let configuredMenu = null;
let clonedItem = null;

class FakeDropdown {
  constructor(element) {
    this.element = element;
    this.panelOpen = false;
  }

  destroy() {
    this.destroyed = true;
  }

  init(menu) {
    configuredMenu = menu;
    return this;
  }

  showPanel() {
    this.panelOpen = true;
    return Promise.resolve(true);
  }
}

const trigger = { isConnected: true };
const title = { name: "title" };
const anchor = {
  querySelector(selector) {
    return selector === "[data-role='title']" ? title : null;
  },
};
const entity = { dataset: { key: "entity-key" } };
const sourceItem = {
  dataset: {},
  disabled: false,
  isConnected: true,
  cloneNode() {
    clonedItem = {
      dataset: {},
      hidden: true,
      outerHTML: "<button role='menuitem'>Delete</button>",
      querySelectorAll() {
        return [];
      },
      removeAttribute() {},
      setAttribute() {},
    };
    return clonedItem;
  },
};
const container = {
  closest(selector) {
    if (selector === "[data-menu-anchor]") return anchor;
    if (selector === "[data-key]") return entity;
    return null;
  },
  querySelector(selector) {
    return selector === ":scope > [data-role='menu-trigger']" ? trigger : null;
  },
  querySelectorAll(selector) {
    return selector.includes("[data-menu-item]") ? [sourceItem] : [];
  },
};

const context = {
  console,
  Dropdown: FakeDropdown,
  STYLES: { dropdown: { menu: "dropdown-menu" } },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/entityMenu.mjs", "utf8");
source = source.replace('import { STYLES } from "styles";\n', "");
source = source.replace(
  'import { Dropdown } from "./combobox/dropdown";\n',
  "",
);
source = source.replace("export class EntityMenu", "class EntityMenu");
source += "\nglobalThis.EntityMenu = EntityMenu;";
vm.runInContext(source, context);

const menu = new context.EntityMenu({});
const toggleReady = menu.toggle(container);

(async () => {
__ASSERTION__
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def run_combobox_check(run_node, assertion: str):
    script = COMBOBOX_HARNESS.replace(
        "__ASSERTION__", textwrap.indent(assertion.strip(), "  ")
    )
    run_node(script)


# @pair combobox:positioning
# @pair dropdown:positioning
# @styles dropdown.panel dropdown.menu
def test_combobox_positioning_uses_live_element_by_default_and_explicit_reference_when_configured(
    run_node,
):
    run_combobox_check(
        run_node,
        r"""
const { parent } = makeComboboxElements();
const combobox = new Combobox(parent);
const replacementInput = new FakeElement("input", { rect: { width: 123.6 } });
replacementInput.classList.add("w-full");
combobox.element = replacementInput;
combobox.panel = new FakeElement("div");

combobox._startAutoUpdate();
await Promise.resolve();

if (autoUpdateCalls[0].reference !== replacementInput) {
  throw new Error("Default positioning did not follow the live replacement input");
}
if (computePositionCalls[0].reference !== replacementInput) {
  throw new Error("Floating position was computed from the stale constructor element");
}
if (combobox.panel.style.width !== "124px") {
  throw new Error(`Expected live full-width input width, got ${combobox.panel.style.width}`);
}
if (combobox.panel.style.left !== "101px" || combobox.panel.style.top !== "202px") {
  throw new Error(`Position result was not applied: ${JSON.stringify(combobox.panel.style)}`);
}

const trigger = new FakeElement("button");
const title = new FakeElement("span", { rect: { width: 197.2 } });
const dropdown = new Dropdown(trigger).init({
  items: [],
  matchReferenceWidth: true,
  placement: "bottom-start",
  positionReference: title,
});
dropdown.panel = new FakeElement("div");
dropdown._startAutoUpdate();
await Promise.resolve();

if (autoUpdateCalls[1].reference !== title) {
  throw new Error("Configured dropdown reference was ignored");
}
if (computePositionCalls[1].options.placement !== "bottom-start") {
  throw new Error(`Unexpected placement: ${computePositionCalls[1].options.placement}`);
}
if (dropdown.panel.style.minWidth !== "198px") {
  throw new Error(`Expected reference width, got ${dropdown.panel.style.minWidth}`);
}

const middleware = computePositionCalls[1].options.middleware;
if (
  middleware[0].name !== "offset" || middleware[0].value !== 4 ||
  middleware[1].name !== "shift" || middleware[1].options.padding !== 5 ||
  middleware[2].name !== "flip" || middleware[2].options.padding !== 5
) {
  throw new Error(`Position safeguards changed: ${JSON.stringify(middleware)}`);
}
""",
    )


# @pair combobox:teardown
# @style dropdown.panel
def test_combobox_positioning_stops_after_destroy(run_node):
    run_combobox_check(
        run_node,
        r"""
const { parent } = makeComboboxElements();
const combobox = new Combobox(parent);
const input = new FakeElement("input", { rect: { width: 123.6 } });
input.classList.add("w-full");
combobox.element = input;
combobox.panel = new FakeElement("div");

combobox._startAutoUpdate();
await Promise.resolve();
const call = autoUpdateCalls[0];
const panel = call.panel;
const positioned = { ...panel.style };

combobox.destroy();
call.callback();
await Promise.resolve();

if (!call.cleaned || combobox.panel !== null) {
  throw new Error("Destroy did not cancel and release combobox positioning");
}
if (JSON.stringify(panel.style) !== JSON.stringify(positioned)) {
  throw new Error(`Canceled positioning mutated the detached panel: ${JSON.stringify(panel.style)}`);
}
""",
    )


# @features combobox
# @dimensions positioning readiness
# @pair combobox:positioning-readiness
# @pair combobox:readiness
# @style dropdown.panel
def test_combobox_exposes_initial_positioning_readiness(run_node):
    run_combobox_check(
        run_node,
        r"""
const { initial, parent } = makeComboboxElements();
const combobox = new Combobox(parent);
combobox.init();
combobox._createPanel();
combobox.panel.appendChild(option(0, "first-option"));
combobox.options = [{ id: "first" }];

let resolvePosition;
context.setComputePosition(
  (reference, panel, options) => new Promise((resolve) => {
    resolvePosition = () => resolve({
      placement: options.placement,
      x: 35,
      y: 47,
    });
  }),
);

const ready = combobox.showPanel();
if (
  !combobox.panelOpen ||
  initial.getAttribute("aria-expanded") !== "true" ||
  combobox.panel.dataset.positioned !== "false" ||
  !combobox._documentHandlersAdded
) {
  throw new Error("Open panel did not publish pending initial placement");
}

resolvePosition();
if ((await ready) !== true) {
  throw new Error("Positioned panel did not report readiness");
}
if (
  !combobox.panelOpen ||
  initial.getAttribute("aria-expanded") !== "true" ||
  combobox.panel.dataset.positioned !== "true" ||
  !combobox._documentHandlersAdded ||
  combobox.panel.style.left !== "35px" ||
  combobox.panel.style.top !== "47px"
) {
  throw new Error("Panel did not publish its completed initial placement");
}
""",
    )


# @features combobox
# @dimensions positioning readiness transition-race
# @pair combobox:positioning-readiness
# @pair combobox:transition-race
# @style dropdown.panel
def test_combobox_initial_position_ignores_superseded_transition_geometry(run_node):
    run_combobox_check(
        run_node,
        r"""
const { parent } = makeComboboxElements();
const combobox = new Combobox(parent);
combobox.init();
combobox._createPanel();
combobox.panel.appendChild(option(0, "first-option"));
combobox.options = [{ id: "first" }];

const positions = [];
context.setComputePosition(
  (reference, panel, options) => new Promise((resolve) => {
    positions.push((x, y) => resolve({ placement: options.placement, x, y }));
  }),
);

const ready = combobox.showPanel();
autoUpdateCalls[0].callback();
if (positions.length !== 2) {
  throw new Error(`Expected transition layout to supersede initial geometry: ${positions.length}`);
}

positions[1](35, 47);
if ((await ready) !== true) {
  throw new Error("Latest transition geometry did not make the panel ready");
}
positions[0](900, 901);
await Promise.resolve();

if (
  combobox.panel.style.left !== "35px" ||
  combobox.panel.style.top !== "47px"
) {
  throw new Error(`Stale transition geometry moved the ready panel: ${JSON.stringify(combobox.panel.style)}`);
}
""",
    )


# @features combobox
# @dimensions aria keyboard
# @style dropdown.panel
def test_combobox_aria_and_keyboard_state_follow_the_open_panel(run_node):
    run_combobox_check(
        run_node,
        r"""
const { initial, parent } = makeComboboxElements();
const combobox = new Combobox(parent);
combobox.init();
combobox._createPanel();

if (initial.getAttribute("role") !== "combobox") {
  throw new Error("Trigger role was not initialized");
}
if (initial.getAttribute("aria-expanded") !== "false") {
  throw new Error("Closed combobox did not initialize aria-expanded=false");
}
if (initial.getAttribute("aria-haspopup") !== "listbox") {
  throw new Error("Trigger does not describe its listbox popup");
}
if (initial.getAttribute("aria-controls") !== combobox.panel.id) {
  throw new Error("Trigger does not control the generated panel");
}
if (
  combobox.panel.getAttribute("role") !== "listbox" ||
  combobox.panel.getAttribute("aria-labelledby") !== initial.id
) {
  throw new Error("Panel ARIA relationship was not initialized");
}

const first = option(0, "first-option");
const second = option(1, "second-option");
combobox.panel.appendChild(first);
combobox.panel.appendChild(second);
combobox.options = [{ id: "first" }, { id: "second" }];
combobox._startAutoUpdate = () => Promise.resolve(true);
await combobox.showPanel();

if (initial.getAttribute("aria-expanded") !== "true") {
  throw new Error("Opening the panel did not update aria-expanded");
}

const down = interactionEvent({ key: "ArrowDown" });
combobox.elementKeydown(down);
if (
  !down.defaultPrevented || !down.propagationStopped ||
  combobox.focusedIndex !== 0 ||
  initial.getAttribute("aria-activedescendant") !== first.id ||
  first.getAttribute("aria-selected") !== "true"
) {
  throw new Error("ArrowDown did not focus and expose the first option");
}

const up = interactionEvent({ key: "ArrowUp" });
combobox.elementKeydown(up);
if (
  combobox.focusedIndex !== 1 ||
  initial.getAttribute("aria-activedescendant") !== second.id ||
  first.getAttribute("aria-selected") !== "false"
) {
  throw new Error("ArrowUp did not wrap focus to the last option");
}

let selected = null;
combobox.selectOption = (selectedOption) => {
  selected = selectedOption;
};
const enter = interactionEvent({ key: "Enter" });
combobox.elementKeydown(enter);
if (selected !== second || !enter.defaultPrevented || !enter.propagationStopped) {
  throw new Error("Enter did not select the ARIA-active option");
}

combobox.elementKeydown(interactionEvent({ key: "Tab" }));
if (
  combobox.panelOpen ||
  initial.getAttribute("aria-expanded") !== "false" ||
  initial.getAttribute("aria-activedescendant") !== null
) {
  throw new Error("Tab did not close the panel and clear active descendant state");
}
""",
    )


# @features combobox
# @dimensions pointer dismissal
# @style dropdown.panel
def test_combobox_pointer_and_dismissal_events_preserve_trigger_focus(run_node):
    run_combobox_check(
        run_node,
        r"""
const { initial, parent } = makeComboboxElements();
const combobox = new Combobox(parent);
combobox.init();
combobox._createPanel();

const first = option(0, "first-option");
const child = new FakeElement("span");
first.appendChild(child);
combobox.panel.appendChild(first);
combobox.options = [{ id: "first" }];
combobox.panelOpen = true;

combobox._panelPointerOver(interactionEvent({ target: child }));
if (
  combobox.focusedIndex !== 0 ||
  initial.getAttribute("aria-activedescendant") !== first.id
) {
  throw new Error("Pointer hover did not expose the hovered option as active");
}

const pointerDown = interactionEvent({ target: child });
combobox._panelPointerDown(pointerDown);
if (!pointerDown.defaultPrevented) {
  throw new Error("Pointer down was allowed to steal focus from the trigger");
}

let selected = null;
combobox.selectOption = (selectedOption) => {
  selected = selectedOption;
};
const click = interactionEvent({ target: child });
combobox._optionClick(click);
if (selected !== first || !click.propagationStopped) {
  throw new Error("Option click did not select without escaping the panel");
}

let deactivated = 0;
initial.addEventListener("deactivate", () => {
  deactivated += 1;
});
combobox._documentClick({ target: new FakeElement("aside") });
if (combobox.panelOpen || deactivated !== 1) {
  throw new Error("Outside click did not close and deactivate the combobox");
}

combobox.panelOpen = true;
combobox._documentKeydown({ key: "Escape" });
if (combobox.panelOpen || deactivated !== 2) {
  throw new Error("Escape did not close and deactivate the combobox");
}
""",
    )


# @pair combobox:empty-results
# @style dropdown.panel
def test_combobox_hides_empty_recent_panel_but_keeps_server_empty_result_row(run_node):
    run_combobox_check(
        run_node,
        r"""
const { parent } = makeComboboxElements();
const combobox = new Combobox(parent);
combobox.init();
combobox._createPanel();
combobox._startAutoUpdate = () => Promise.resolve(true);

combobox.panelOpen = true;
combobox.panel.classList.remove("hidden");
combobox.panel.dataset.visible = "true";
combobox.updatePanel("   ");
combobox.options = [{ id: "selected-but-not-rendered" }];
await combobox.showPanel();

if (
  combobox.panelOpen ||
  !combobox.panel.classList.contains("hidden") ||
  combobox.panel.dataset.visible !== "false" ||
  combobox.element.getAttribute("aria-expanded") !== "false"
) {
  throw new Error("Empty recent-result markup left a visible combobox panel");
}

const noResults = option(0, "no-results");
combobox.panel.appendChild(noResults);
combobox.updatePanel('<div role="option">No Results</div>');
await combobox.showPanel();

if (
  !combobox.panelOpen ||
  combobox.panel.classList.contains("hidden") ||
  combobox.options.length !== 1
) {
  throw new Error("Server no-results row was treated as an empty panel");
}
""",
    )


# @features combobox
# @dimensions dataset-configuration
# @style dropdown.panel
def test_combobox_copies_only_supported_dataset_configuration(run_node):
    run_combobox_check(
        run_node,
        r"""
const { initial, parent } = makeComboboxElements();
parent.dataset.kind = "user";
parent.dataset.preload = '[{"id":"existing-user"}]';
parent.dataset.placeholder = "parent placeholder";
initial.dataset.placeholder = "choose a user...";
initial.dataset.multiple = "true";
initial.dataset.creatable = "true";
initial.dataset.formType = "task";
initial.dataset.includeUsers = "false";
initial.dataset.permission = "assign";

// Runtime and unrelated DOM state must not become instance fields.
initial.dataset.panel = "closed";
initial.dataset.values = "true";
initial.dataset.options = "corrupted-options";
initial.dataset.element = "corrupted-element";
initial.dataset.hidePanel = "corrupted-method";
initial.dataset.mobile = "corrupted-mobile-state";
initial.dataset.unrelated = "unrelated-value";

const combobox = new Combobox(parent);
if (
  combobox.index !== "people" ||
  combobox.kind !== "user" ||
  combobox.placeholder !== "choose a user..." ||
  combobox.preload !== '[{"id":"existing-user"}]' ||
  combobox.multiple !== true ||
  combobox.creatable !== "true" ||
  combobox.formType !== "task" ||
  combobox.includeUsers !== "false" ||
  combobox.permission !== "assign"
) {
  throw new Error(`Supported dataset configuration changed: ${JSON.stringify({
    index: combobox.index,
    kind: combobox.kind,
    placeholder: combobox.placeholder,
    preload: combobox.preload,
    multiple: combobox.multiple,
    creatable: combobox.creatable,
    formType: combobox.formType,
    includeUsers: combobox.includeUsers,
    permission: combobox.permission,
  })}`);
}

if (
  combobox.element !== initial ||
  combobox.panel !== null ||
  !Array.isArray(combobox.options) ||
  typeof combobox.values?.add !== "function" ||
  typeof combobox.values?.has !== "function" ||
  typeof combobox.hidePanel !== "function" ||
  typeof combobox.mobile !== "boolean" ||
  "unrelated" in combobox
) {
  throw new Error("Unapproved dataset state replaced combobox internals");
}

combobox.init();
combobox.updatePanel("");
if (
  !(combobox.panel instanceof FakeElement) ||
  combobox.panelOpen ||
  !combobox.panel.classList.contains("hidden") ||
  combobox.element.dataset.panel !== "closed"
) {
  throw new Error("Panel did not initialize and close safely");
}
combobox.destroy();

const single = makeComboboxElements();
single.initial.dataset.multiple = "false";
if (new Combobox(single.parent).multiple !== false) {
  throw new Error('data-multiple="false" was retained as a truthy string');
}
""",
    )


# @features combobox
# @dimensions clear-notification
def test_submitter_clear_can_suppress_change_notification(run_node):
    run_combobox_check(
        run_node,
        r"""
const { parent } = makeComboboxElements();
const SubmitterCombobox = Submitter(Combobox);
const combobox = new SubmitterCombobox(parent);
const updateModes = [];
combobox.hidePanel = () => {};
combobox.updateSelect = (preloading) => updateModes.push(preloading);

combobox.values.add("group-key");
combobox.clear({ notify: false });
if (combobox.values.size !== 0 || updateModes[0] !== true) {
  throw new Error("Silent clear did not suppress the updated/change events");
}

combobox.values.add("second-group-key");
combobox.clear();
if (combobox.values.size !== 0 || updateModes[1] !== false) {
  throw new Error("Normal clear stopped notifying listeners");
}
""",
    )


# @features dropdown
# @dimensions dynamic-options rerender mixed-options callback-index
# @style dropdown.panel
def test_dynamic_dropdown_rerenders_each_open_and_keeps_mixed_option_indexes(run_node):
    run_combobox_check(
        run_node,
        r"""
const trigger = new FakeElement("button");
let load = 0;
const dropdown = new Dropdown(trigger).init({
  loadOptions: async () => {
    load += 1;
    return [{ name: `Version ${load}` }];
  },
});
dropdown.panel = new FakeElement("div");
dropdown._startAutoUpdate = () => Promise.resolve(true);
const rendered = [];
dropdown._renderOptions = () => {
  rendered.push(dropdown.items.map((item) => item.name));
  dropdown.options = dropdown.items;
};

await dropdown.showPanel();
await dropdown.showPanel();

if (load !== 2 || rendered.length !== 2) {
  throw new Error(`Dynamic options were not loaded and rendered twice: ${load}/${rendered.length}`);
}
if (rendered[0][0] !== "Version 1" || rendered[1][0] !== "Version 2") {
  throw new Error(`Stale dynamic options were retained: ${JSON.stringify(rendered)}`);
}

const selected = [];
const mixed = new Dropdown(new FakeElement("button"));
mixed.items = [
  { html: '<button role="option">Custom</button>', onClick: () => selected.push("custom") },
  { name: "Standard", onClick: () => selected.push("standard") },
];
mixed._createDropdownButton = (item) => `<button role="option">${item.name}</button>`;
let html = null;
mixed.updatePanel = (value) => { html = value; };
mixed._renderOptions();

if (!html.includes("Custom") || !html.includes("Standard")) {
  throw new Error(`Mixed custom and standard options did not both render: ${html}`);
}
mixed.hidePanel = () => {};
mixed.selectOption({ dataset: { index: "1" } });
if (selected.join(",") !== "standard") {
  throw new Error(`Mixed option callback index drifted: ${selected.join(",")}`);
}
""",
    )


# @features entity-menu
# @dimensions title-menu title-positioning state-linking readiness
# @style dropdown.menu
def test_entity_title_menu_anchors_to_the_title_bottom_left(run_node):
    script = ENTITY_MENU_HARNESS.replace(
        "__ASSERTION__",
        textwrap.dedent(
            r"""
            if (!configuredMenu) {
              throw new Error("Entity menu did not configure a dropdown");
            }
            if ((await toggleReady) !== true) {
              throw new Error("Entity menu did not return the dropdown readiness boundary");
            }
            if (configuredMenu.positionReference !== title) {
              throw new Error("Entity menu was not anchored to its title");
            }
            if (configuredMenu.placement !== "bottom-start") {
              throw new Error(`Unexpected title placement: ${configuredMenu.placement}`);
            }
            if (configuredMenu.matchReferenceWidth !== true) {
              throw new Error("Title width was not retained as the dropdown minimum");
            }
            if (clonedItem.dataset.entityKey !== "entity-key") {
              throw new Error("Portal menu item was not linked to its source entity");
            }
            const initialClone = clonedItem;
            const refreshedItems = await configuredMenu.loadOptions();
            if (refreshedItems.length !== 1 || clonedItem === initialClone) {
              throw new Error("Entity menu did not rebuild its options from the live source");
            }
            if (
              configuredMenu.popupRole !== "menu" ||
              configuredMenu.optionRole !== "menuitem" ||
              configuredMenu.triggerRole !== null
            ) {
              throw new Error("Entity menu ARIA roles changed while configuring position");
            }
            """
        ).strip(),
    )
    run_node(script)
