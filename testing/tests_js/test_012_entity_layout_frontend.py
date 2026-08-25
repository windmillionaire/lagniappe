"""Node-backed checks for frontend entity layout reconciliation."""

import textwrap

def run_entity_layout_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
const storage = new Map();

class FakeClassList {{
  constructor() {{
    this.values = new Set();
  }}

  add(...values) {{
    values.forEach((value) => this.values.add(value));
  }}

  remove(...values) {{
    values.forEach((value) => this.values.delete(value));
  }}

  contains(value) {{
    return this.values.has(value);
  }}

  toggle(value, force) {{
    if (force) {{
      this.add(value);
    }} else {{
      this.remove(value);
    }}
  }}
}}

class FakeElement {{
  constructor(id, dataset = {{}}) {{
    this.id = id;
    this.dataset = {{ ...dataset }};
    this.children = [];
    this.parentElement = null;
    this.classList = new FakeClassList();
  }}

  addEventListener() {{}}

  appendChild(child) {{
    child.parentElement = this;
    this.children.push(child);
    return child;
  }}

  prepend(child) {{
    child.parentElement = this;
    this.children.unshift(child);
    return child;
  }}

  contains(element) {{
    if (element === this) return true;
    return this.children.some((child) => child.contains(element));
  }}

  querySelector() {{
    return null;
  }}

  querySelectorAll() {{
    return [];
  }}
}}

const root = new FakeElement("root");
const layout = new FakeElement("layout");
const tabsElement = new FakeElement("tabs", {{ visible: "false" }});
const desktopNav = new FakeElement("desktop-nav");
const mobileNav = new FakeElement("mobile-nav");
const infoElement = new FakeElement("info", {{ tab: "true" }});
const photoElement = new FakeElement("photo", {{
  attribute: "photo",
  persistent: "false",
  tab: "true",
  visible: "false",
}});

tabsElement.navElement = desktopNav;
tabsElement.appendChild(infoElement);
layout.appendChild(photoElement);
root.appendChild(layout);
root.appendChild(tabsElement);
root.appendChild(mobileNav);

const byId = new Map([
  [root.id, root],
  [layout.id, layout],
  [tabsElement.id, tabsElement],
  [desktopNav.id, desktopNav],
  [mobileNav.id, mobileNav],
  [infoElement.id, infoElement],
  [photoElement.id, photoElement],
]);

root.querySelector = (selector) => {{
  if (selector === "#tabs") return tabsElement;
  if (selector === "#layout") return layout;
  if (selector === "#photo") return photoElement;
  if (selector === "[lp-nav][data-nav='mobile']") return mobileNav;
  return null;
}};

root.querySelectorAll = (selector) => {{
  if (selector === "[lp-component][data-tab='true']") {{
    return [infoElement, photoElement];
  }}
  return [];
}};

tabsElement.querySelectorAll = (selector) => {{
  if (selector === "[lp-component][data-tab='true']") return [infoElement];
  return [];
}};

class NavElement {{
  constructor(component, element) {{
    this.component = component;
    this.element = element;
  }}
}}

const debounce = (func) => func;
let transitionCalls = 0;
let transitionDepth = 0;
const withTransition = async (callback) => {{
  transitionCalls += 1;
  transitionDepth += 1;
  try {{
    return await callback();
  }} finally {{
    transitionDepth -= 1;
  }}
}};

class FakeComponent {{
  constructor(element, view) {{
    this.elt = element;
    this.view = view;
    this.name = element.id;
    this.widgets = {{}};
    this._nav = null;
    this.reconcile = null;
  }}

  get nav() {{
    if (this._nav) return this._nav;
    if (this.elt.navElement) {{
      this._nav = {{ element: this.elt.navElement }};
    }}
    return this._nav;
  }}

  set nav(value) {{
    this._nav = value;
  }}

  async activate(show) {{
    events.push(`${{this.name}}:activate:${{show}}`);
  }}

  async prepareRender(visible) {{
    events.push(`${{this.name}}:prepare:${{visible}}`);
  }}

  render(visible) {{
    events.push(`${{this.name}}:render:${{visible}}`);
  }}
}}

class Core {{
  constructor(node) {{
    this.elt = node;
    this.components = {{}};
    this.hash = "entity-layout-test";
    this.kind = "page";
    this.mobile = false;
    this.readonly = false;
  }}

  async init() {{}}

  getComponent(element) {{
    if (!element) throw new Error("Missing component element");
    if (!this.components[element.id]) {{
      this.components[element.id] = new FakeComponent(element, this);
    }}
    return this.components[element.id];
  }}

  queryParam() {{
    return null;
  }}

  querySlug(value) {{
    return value;
  }}
}}

const context = {{
  console,
  Core,
  CustomEvent: class CustomEvent {{}},
  debounce,
  document: {{
    getElementById: (id) => byId.get(id) || null,
  }},
  Element: FakeElement,
  events,
  localStorage: {{
    getItem: (key) => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
  }},
  NavElement,
  transitionActive: () => transitionDepth > 0,
  transitionCalls: () => transitionCalls,
  withTransition,
}};

vm.createContext(context);
let source = fs.readFileSync("src/script/views/base/entity.mjs", "utf8");
source = source.replace('import {{ NavElement }} from "../../elements/nav";\\n', "");
source = source.replace('import {{ debounce, withTransition }} from "../../shared/utilities";\\n', "");
source = source.replace('import Core from "./core";\\n', "");
source = source.replace(
  "export default class Entity extends Core",
  "class Entity extends Core",
);
source += "\\nglobalThis.Entity = Entity;";
vm.runInContext(source, context);

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @matrix entity-layout : nested-layout reconcile-callback
def test_entity_layout_ignores_already_consumed_reconcile_callback(run_node):
    run_entity_layout_check(
        run_node,
        """
const view = new context.Entity(root);
const outer = await view._prepareLayoutBody();
const inner = await view._prepareLayoutBody();
await context.withTransition(() => {
  view._commitLayoutBody(inner);
  view._commitLayoutBody(outer);
});

const renders = events.filter((event) => event === "info:render:true").length;
if (renders !== 2) {
  throw new Error(`Expected nested and outer tab renders, got ${renders}`);
}

if (layout.dataset.visible !== "true") {
  throw new Error("Expected layout to be visible after render");
}
if (tabsElement.dataset.visible !== "true") {
  throw new Error("Expected the resolved tabs card to be visible after render");
}

const tabs = view.getComponent(tabsElement);
if (tabs.reconcile !== null) {
  throw new Error("Expected nested layout to consume the tabs callback");
}
""",
    )


# @pair startup:view-ready
def test_initial_entity_layout_prepares_widget_before_one_transition(run_node):
    run_entity_layout_check(
        run_node,
        """
const view = new context.Entity(root);
const info = view.getComponent(infoElement);
let resolveActivation;
let markActivationStarted;
let activationTransitioned = false;
const activationStarted = new Promise((resolve) => { markActivationStarted = resolve; });
info.activate = () => {
  activationTransitioned = context.transitionActive();
  markActivationStarted();
  return new Promise((resolve) => { resolveActivation = resolve; });
};

const initializing = view.init();
await activationStarted;

if (
  layout.dataset.visible === "true" ||
  tabsElement.dataset.visible === "true" ||
  infoElement.dataset.visible === "true"
) {
  throw new Error("Entity tab selection committed before widget preparation");
}
if (context.transitionCalls() !== 0 || activationTransitioned) {
  throw new Error("Widget activation ran inside the visual transition");
}

resolveActivation();
await initializing;
if (
  context.transitionCalls() !== 1 ||
  layout.dataset.visible !== "true" ||
  tabsElement.dataset.visible !== "true" ||
  infoElement.dataset.visible !== "true"
) {
  throw new Error("Prepared entity layout was not committed in one transition");
}
""",
    )


# @pair entity-layout:dynamic-secondary
def test_dynamic_mobile_secondary_uses_final_layout_state(run_node):
    run_entity_layout_check(
        run_node,
        """
const view = new context.Entity(root);
view.mobile = true;
Object.defineProperty(view, "secondaryCard", {
  get() {
    return root.dataset.secondary === "true" ? photoElement : null;
  },
});

await view.updateLayout({
  activeTabId: "photo",
  secondary: photoElement,
  secondaryActive: true,
});

if (photoElement.parentElement !== tabsElement) {
  throw new Error("Dynamic secondary card was not moved into the mobile tabs card");
}
if (
  photoElement.dataset.visible !== "true" ||
  photoElement.dataset.persistent !== "false"
) {
  throw new Error("Dynamic secondary card did not acquire mobile tab visibility");
}
if (infoElement.dataset.visible !== "false") {
  throw new Error("Previous mobile tab remained visible beside the secondary card");
}

await view.updateLayout({ activeTabId: "info" });

if (photoElement.dataset.visible !== "false") {
  throw new Error("Dynamic secondary card remained visible after selecting another tab");
}
if (infoElement.dataset.visible !== "true") {
  throw new Error("Standard mobile tab did not recover after leaving the secondary card");
}
""",
    )
