"""Node-backed checks for the shared style build contract."""


# @features style-build
# @dimensions runtime-parity
def test_virtual_and_python_style_payloads_share_one_runtime_value(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import {
  normalizeStyleRegistry,
  pythonStyleModuleSource,
  virtualIconModuleSource,
  virtualStyleModuleSource,
} from "./build/utility.mjs";

const typedRegistry = {
  button: {
    submit: {
      classes: "flex items-center",
      intent: "primary submission control",
      surfaces: ["server", "frontend"],
    },
  },
  label: {
    default: {
      classes: "font-semibold",
      intent: "default field label",
      surfaces: ["server"],
    },
  },
};
const registry = normalizeStyleRegistry(typedRegistry);
const icons = { page: { glyph: "draft", fill: 1 } };
const virtualStyles = await import(
  `data:text/javascript,${encodeURIComponent(virtualStyleModuleSource(registry))}`
);
const virtualIcons = await import(
  `data:text/javascript,${encodeURIComponent(virtualIconModuleSource(icons))}`
);
const pythonSource = pythonStyleModuleSource("STYLES", registry);
const pythonPayload = JSON.parse(pythonSource.split("STYLES = ", 2)[1]);

assert.deepEqual(virtualStyles.STYLES, registry);
assert.deepEqual(virtualIcons.ICONS, icons);
assert.deepEqual(Object.keys(virtualStyles), ["STYLES"]);
assert.deepEqual(Object.keys(virtualIcons), ["ICONS"]);
assert.deepEqual(pythonPayload, registry);
assert.deepEqual(virtualStyles.STYLES, pythonPayload);
""",
        module=True,
    )


# @features style-build
# @dimensions schema-validation
def test_style_registry_rejects_untyped_and_unknown_leaves(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { normalizeStyleRegistry } from "./build/utility.mjs";

assert.throws(
  () => normalizeStyleRegistry({ button: { submit: "flex" } }),
  /typed style record/,
);
assert.throws(
  () => normalizeStyleRegistry({
    button: {
      submit: {
        classes: "flex",
        intent: "button",
        surfaces: ["server"],
        typo: true,
      },
    },
  }),
  /unknown style fields: typo/,
);
assert.deepEqual(
  normalizeStyleRegistry({
    button: {
      submit: { classes: "flex", intent: "button", surfaces: ["server"] },
      alternate: {
        alias: "button.submit",
        intent: "alternate button",
        surfaces: ["frontend"],
      },
    },
  }),
  { button: { submit: "flex", alternate: "flex" } },
);
assert.throws(
  () => normalizeStyleRegistry({
    button: {
      one: { alias: "button.two", intent: "one", surfaces: ["server"] },
      two: { alias: "button.one", intent: "two", surfaces: ["server"] },
    },
  }),
  /style alias cycle/,
);
""",
        module=True,
    )


# @features style-build
# @dimensions icon-schema-validation
def test_icon_registry_rejects_invalid_ids_and_material_symbol_records(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { normalizeIconRegistry } from "./build/utility.mjs";

assert.deepEqual(
  normalizeIconRegistry({
    dueDate: { glyph: "event", fill: 1 },
    filter: {
      active: { glyph: "filter_alt", fill: 1 },
      inactive: { glyph: "filter_alt", fill: 0 },
    },
  }),
  {
    dueDate: { glyph: "event", fill: 1 },
    filter: {
      active: { glyph: "filter_alt", fill: 1 },
      inactive: { glyph: "filter_alt", fill: 0 },
    },
  },
);
assert.throws(
  () => normalizeIconRegistry({ "due-date": { glyph: "event", fill: 1 } }),
  /invalid icon ID segment due-date/,
);
assert.throws(
  () => normalizeIconRegistry({ dueDate: { glyph: "Calendar Event", fill: 1 } }),
  /Material Symbol name/,
);
assert.throws(
  () => normalizeIconRegistry({ dueDate: { glyph: "event", fill: 2 } }),
  /fill must be 0 or 1/,
);
assert.throws(
  () => normalizeIconRegistry({
    spinner: { glyph: "progress_activity", fill: 1, spin: "yes" },
  }),
  /spin must be a boolean/,
);
assert.throws(
  () => normalizeIconRegistry({
    plus: { glyph: "add_2", fill: 1, weight: 700 },
  }),
  /weight must be one of 300, 400, 500, 600/,
);
assert.throws(
  () => normalizeIconRegistry({ dueDate: [] }),
  /icons.dueDate must be a non-empty mapping/,
);
""",
        module=True,
    )


# @features style-build
# @dimensions pipeline-contract
# @style button.submit
# @style dropdown.option.action
# @style dropdown.option.flow
# @style dropdown.search.result
# @style home.toggleLabel
def test_style_pipeline_contract_names_authored_inputs_and_outputs(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { buildStyles, STYLE_PIPELINE } from "./build/utility.mjs";

assert.equal(STYLE_PIPELINE.registry.styles, "src/style/styles.yaml");
assert.equal(STYLE_PIPELINE.registry.schema, "src/style/registry.schema.json");
assert.equal(STYLE_PIPELINE.registry.icons, "src/style/icons.yaml");
assert.equal(STYLE_PIPELINE.registry.icons_schema, "src/style/icons.schema.json");
assert.equal(STYLE_PIPELINE.registry.virtual_module, "styles");
assert.equal(STYLE_PIPELINE.registry.icons_virtual_module, "icons");
assert.equal(
  STYLE_PIPELINE.registry.python_styles,
  "lagniappe/web/start/styles/styles.py",
);
assert.equal(STYLE_PIPELINE.css.entry, "src/style/main.css");
assert.deepEqual(STYLE_PIPELINE.css.tailwind_sources, [
  "src/style/styles.yaml",
]);
assert.ok(
  STYLE_PIPELINE.css.authored_stylesheets.some(
    ({ path, ownership }) =>
      path === "src/style/navigation.css" && ownership === "semantic",
  ),
);
assert.deepEqual(STYLE_PIPELINE.builds.production.transforms, [
  "tailwindcss",
  "cssnano",
]);
const plugin = buildStyles();
assert.equal(plugin.resolveId(STYLE_PIPELINE.registry.virtual_module), "styles");
assert.equal(
  plugin.resolveId(STYLE_PIPELINE.registry.icons_virtual_module),
  "icons",
);
const runtimeStyles = await import(
  `data:text/javascript,${encodeURIComponent(plugin.load(STYLE_PIPELINE.registry.virtual_module))}`
);
const runtimeIcons = await import(
  `data:text/javascript,${encodeURIComponent(plugin.load(STYLE_PIPELINE.registry.icons_virtual_module))}`
);
assert.equal(typeof runtimeStyles.STYLES.button.submit, "string");
assert.match(runtimeStyles.STYLES.button.submit, /\bw-full\b/);
assert.match(runtimeStyles.STYLES.button.submit, /\bgrow\b/);
assert.match(runtimeStyles.STYLES.button.submit, /\baction-button\b/);
assert.deepEqual(runtimeIcons.ICONS.page, { glyph: "draft", fill: 1 });
assert.equal(runtimeStyles.ICONS, undefined);
assert.equal(runtimeIcons.STYLES, undefined);
assert.match(
  runtimeStyles.STYLES.dropdown.option.action,
  /\bdropdown-option-action\b/,
);
assert.match(
  runtimeStyles.STYLES.home.toggleLabel,
  /\bflex\b[\s\S]*\bitems-center\b[\s\S]*\bgap-2\b/,
);
assert.doesNotMatch(runtimeStyles.STYLES.home.toggleLabel, /\bflow-root\b/);
assert.match(
  runtimeStyles.STYLES.dropdown.option.flow,
  /\bdropdown-option-flow\b/,
);
assert.equal(
  runtimeStyles.STYLES.dropdown.search.result,
  runtimeStyles.STYLES.dropdown.option.flow,
);
""",
        module=True,
    )


# @features ui-action
# @dimensions loading-state fixed-layout
# @style button.submit
def test_active_action_buttons_preserve_full_width_icon_slots(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { rollup } from "rollup";
import { buildStyles } from "./build/utility.mjs";

const build = await rollup({
  input: "./src/script/elements/buttons.mjs",
  plugins: [buildStyles()],
});
const { output } = await build.generate({ format: "esm" });
await build.close();

class FakeClassList {
  constructor() { this.names = new Set(); }
  add(...names) { names.forEach((name) => this.names.add(name)); }
}

class FakeElement {
  constructor(tagName = "span") {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.classList = new FakeClassList();
    this.className = "";
    this.disabled = false;
    this._textContent = "";
  }
  get textContent() {
    return this._textContent || this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) { this._textContent = String(value); }
  appendChild(child) { this.children.push(child); return child; }
  prepend(child) { this.children.unshift(child); }
  replaceChildren(...children) {
    this.children = children;
    this._textContent = "";
  }
  querySelector(selector) {
    const match = selector.match(/\[data-role='([^']+)'\]/);
    return match
      ? this.children.find((child) => child.dataset.role === match[1]) || null
      : null;
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
}

globalThis.document = {
  createElement: (tagName) => new FakeElement(tagName),
};

const module = await import(
  `data:text/javascript,${encodeURIComponent(output[0].code)}`
);
const button = new FakeElement("button");
button.textContent = "Refresh Cache";
const action = module.buttons.active({
  existingButton: button,
  icon: "database",
  text: "Refresh Cache",
  processingText: "Refreshing Cache",
  completedText: "Cache Refreshed",
  completedIcon: "check",
});

const iconSlot = button.querySelector("[data-role='icon']");
const textSlot = button.querySelector("[data-role='text']");
assert.ok(iconSlot);
assert.ok(textSlot);
assert.equal(iconSlot.children[0]?.dataset.icon, "database");
assert.equal(textSlot.textContent, "Refresh Cache");

action.activate();
assert.equal(button.disabled, true);
assert.equal(button.querySelector("[data-role='icon']"), iconSlot);
assert.equal(button.querySelector("[data-role='text']"), textSlot);
assert.equal(iconSlot.children[0]?.dataset.icon, "spinner");
assert.equal(textSlot.textContent, "Refreshing Cache");

action.deactivate();
assert.equal(button.disabled, false);
assert.equal(button.querySelector("[data-role='icon']"), iconSlot);
assert.equal(button.querySelector("[data-role='text']"), textSlot);
assert.equal(iconSlot.children[0]?.dataset.icon, "check");
assert.equal(textSlot.textContent, "Cache Refreshed");
""",
        module=True,
    )


# @features frontend-icons
# @dimensions registry lookup nested-ids semantic-markup fill weight animation accessibility element-creation
def test_frontend_icon_helpers_render_structured_material_symbols(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { rollup } from "rollup";
import { buildStyles } from "./build/utility.mjs";

const build = await rollup({
  input: "./src/script/shared/icons.mjs",
  plugins: [buildStyles()],
});
const { output } = await build.generate({ format: "esm" });
await build.close();
const module = await import(
  `data:text/javascript,${encodeURIComponent(output[0].code)}`
);

class FakeElement {
  constructor() {
    this.className = "";
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
    this.children = [];
  }
  setAttribute(name, value) {
    this.attributes[name] = value;
  }
  removeAttribute(name) {
    delete this.attributes[name];
  }
  replaceChildren(...children) {
    this.children = children;
    this.textContent = children.map((child) => child.textContent).join("");
  }
}
globalThis.document = { createElement: () => new FakeElement() };

const project = module.createIcon("project", "text-project-default");
assert.equal(project.textContent, "flowsheet");
assert.equal(project.dataset.icon, "project");
assert.equal(project.dataset.fill, "0");
assert.equal(project.attributes["aria-hidden"], "true");
assert.match(project.className, /icon/);
assert.match(project.className, /text-project-default/);
assert.equal(project.children.length, 1);
assert.equal(project.children[0].className, "icon-glyph");
assert.equal(project.children[0].textContent, "flowsheet");

const plus = module.createIcon("plus");
assert.equal(plus.textContent, "add_2");
assert.equal(plus.dataset.weight, "600");

const edit = module.createIcon("edit");
assert.equal(edit.textContent, "amend");
assert.equal(edit.dataset.fill, "0");

const clear = module.createIcon("clear");
assert.equal(clear.textContent, "do_not_disturb_on");

const attributeAdd = module.createIcon("attribute.add");
assert.equal(attributeAdd.textContent, "add_circle");

const attributeRemove = module.createIcon("attribute.remove");
assert.equal(attributeRemove.textContent, "do_not_disturb_on");

const close = module.createIcon("x");
assert.equal(close.dataset.weight, "600");

const spinner = module.createIcon("spinner");
assert.match(spinner.className, /icon-spin/);

const trash = module.createIcon("trash.active");
assert.equal(trash.textContent, "delete_forever");
assert.equal(trash.dataset.fill, "1");

module.setIcon(plus, "star.inactive");
assert.equal(plus.textContent, "star");
assert.equal(plus.dataset.fill, "0");
assert.equal(plus.dataset.weight, "300");
assert.equal(plus.children[0].className, "icon-glyph");
""",
        module=True,
    )


# @style dropdown.icon
# @style entity.tabIcon
def test_material_symbol_size_exceptions_use_semantic_css(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const css = readFileSync("./src/style/icons.css", "utf8");
const buttonsCss = readFileSync("./src/style/buttons.css", "utf8");
const contentCss = readFileSync("./src/style/content.css", "utf8");
const navigationCss = readFileSync("./src/style/navigation.css", "utf8");
const primitivesSource = readFileSync("./src/script/elements/primitives.mjs", "utf8");
assert.match(
  css,
  /\.icon\s*\{[\s\S]*?--icon-box-size: 1\.45em;[\s\S]*?--icon-default-size: 1\.3em;[\s\S]*?inline-size: var\(--icon-box-size\);[\s\S]*?block-size: var\(--icon-box-size\);/,
);
assert.match(
  css,
  /\.icon-glyph\s*\{[\s\S]*?font-size: var\(--icon-size, var\(--icon-default-size\)\);[\s\S]*?transform: translate\(/,
);
assert.match(
  css,
  /\.icon\[data-icon="plus"\]\s*\{\s*--icon-size: 1\.25em;/,
);
assert.match(
  css,
  /\.icon\[data-icon="page"\]\s*\{\s*--icon-size: 1\.2em;/,
);
assert.match(
  css,
  /\.icon\[data-icon="help"\]\s*\{\s*--icon-size: 1\.2rem;/,
);
assert.match(
  css,
  /\.icon\[data-icon="document"\],\s*\.icon\[data-icon="info"\]\s*\{\s*--icon-size: 1\.55em;/,
);
assert.match(
  css,
  /button\.tab-icon \.icon\s*\{[\s\S]*?--icon-box-size: 1\.55em;[\s\S]*?--icon-size: 1\.55em;/,
);
assert.match(
  css,
  /\.icon\[data-icon="close"\],\s*\.icon\[data-icon="x"\]\s*\{\s*--icon-offset-y: 1px;/,
);
assert.match(
  css,
  /\.editor-toolbar-icon-context \.icon,\s*\.editor-toolbar-portal-icon-context \.icon\s*\{[\s\S]*?--icon-box-size: 1\.45em;[\s\S]*?--icon-default-size: 1\.45em;[\s\S]*?--icon-size: 1\.45em;/,
);
assert.match(
  css,
  /\.editor-toolbar-icon-context \.editor-toolbar-menu-icon\s*\{\s*--icon-offset-y: 1px;/,
);
assert.match(
  css,
  /\.editor-toolbar-icon-context \.editor-toolbar-history-icon\s*\{\s*--icon-offset-y: 1px;/,
);
assert.match(
  css,
  /\.editor-toolbar-icon-context \.editor-toolbar-caret\s*\{[\s\S]*?--icon-box-size: 1\.2em;[\s\S]*?--icon-size: 1\.2em;[\s\S]*?--icon-offset-y: 1px;/,
);
assert.doesNotMatch(css, /\.dropdown-icon/);
assert.match(
  contentCss,
  /\.dropdown-option\s*\{[\s\S]*?border-radius: var\(--radius-sm\);[\s\S]*?line-height: 1\.5;[\s\S]*?padding: 0\.375rem 0\.5rem;[\s\S]*?text-align: left;[\s\S]*?width: 100%;/,
);
assert.match(
  contentCss,
  /\.dropdown-option-flow\s*\{\s*display: block;/,
);
assert.match(
  contentCss,
  /\.dropdown-option-action\s*\{[\s\S]*?align-items: center;[\s\S]*?display: flex;[\s\S]*?gap: 0\.25rem;/,
);
assert.doesNotMatch(
  contentCss,
  /\.dropdown-option-action > span:not\(\.icon\)/,
);
assert.match(
  contentCss,
  /\.dropdown-option-flow \.dropdown-option-icon\s*\{\s*margin-inline-end: 0\.25rem;/,
);
assert.match(
  css,
  /\.icon\[data-icon="menu"\]\s*\{[\s\S]*?--icon-box-size: 1\.25rem;[\s\S]*?--icon-size: 1\.3rem;/,
);
assert.match(
  css,
  /\[lp-menu="title"\] \.icon\[data-icon="menu"\]\s*\{[\s\S]*?--icon-box-size: 1\.45rem;[\s\S]*?--icon-offset-y: 0\.125rem;/,
);
assert.match(
  css,
  /\.icon\[data-icon="spinner"\]\s*\{\s*--icon-size: 1\.1em;/,
);
assert.match(
  css,
  /\.icon\[data-icon="spinner"\] \.icon-glyph\s*\{\s*display: none;/,
);
assert.match(
  css,
  /\.icon\[data-icon="spinner"\]::before\s*\{[\s\S]*?box-shadow:[\s\S]*?color-mix\([\s\S]*?content: "";/,
);
assert.match(
  css,
  /\.icon-spin\s*\{\s*animation: icon-spin 1\.25s linear infinite;/,
);
assert.match(
  css,
  /\.icon\[data-icon="star\.active"\],\s*\.icon\[data-icon="star\.inactive"\]\s*\{\s*--icon-size: 1\.5em;/,
);
assert.match(
  css,
  /\.icon\[data-icon="star\.home"\]\s*\{[\s\S]*?--icon-size: 1\.5em;[\s\S]*?--icon-offset-y: -1px;/,
);
assert.doesNotMatch(css, /\.dropdown-option-action \.icon\[data-icon=/);
assert.doesNotMatch(css, /\.home-toggle-label > \.icon/);
for (const [name, size] of [
  ["xs", "0.75rem"],
  ["sm", "0.875rem"],
  ["base", "1rem"],
  ["lg", "1.125rem"],
  ["xl", "1.25rem"],
  ["2xl", "1.5rem"],
]) {
  assert.ok(
    css.includes(`.icon-${name} {\n\tfont-size: ${size};`),
    `missing icon-owned ${name} scale`,
  );
}
assert.match(
  css,
  /\.checkbox-icon\s*\{[\s\S]*?--icon-box-size: 1rem;[\s\S]*?--icon-size: 1rem;[\s\S]*?font-size: 1rem;/,
);
assert.match(
  css,
  /\.nav-search-icon\s*\{[\s\S]*?--icon-offset-y: 1px;[\s\S]*?font-size: 1rem;/,
);
assert.match(
  css,
  /\.select-icon\s*\{[\s\S]*?--icon-box-size: 1\.25rem;[\s\S]*?font-size: 1rem;/,
);
assert.match(
  buttonsCss,
  /\.action-icon-button \.icon\s*\{\s*grid-area: 1 \/ 1;\s*\}/,
);
assert.match(
  buttonsCss,
  /\.action-icon-button\s*\{[\s\S]*?translate: var\(--action-offset-x, 0\) var\(--action-offset-y, 0\);/,
);
assert.match(
  buttonsCss,
  /\.action-icon-button\s*\{[\s\S]*?vertical-align: middle;/,
);
assert.match(
  buttonsCss,
  /\.action-icon-button\[data-role="menu-trigger"\]\s*\{\s*--action-offset-y: -0\.125rem;/,
);
assert.match(
  primitivesSource,
  /const explain_prompt = [\s\S]*?button\.className = STYLES\.button\.explain;[\s\S]*?setIcon\(promptIcon, "prompt", "text-kind-default"\);/,
);
assert.doesNotMatch(
  buttonsCss,
  /--action-icon(?:-button)?-size/,
);
assert.doesNotMatch(
  navigationCss,
  /--action-icon(?:-button)?-size/,
);
for (const filename of readdirSync("./src/style")) {
  if (!filename.endsWith(".css") || filename === "icons.css") continue;
  assert.doesNotMatch(
    readFileSync(`./src/style/${filename}`, "utf8"),
    /--icon-(?:box-size|default-size|size|offset-[xy])/,
    `${filename} must not override icon-owned geometry`,
  );
}
assert.doesNotMatch(navigationCss, /button\.tab-icon > \.icon/);
""",
        module=True,
    )


def test_style_candidate_validator_uses_the_authored_tailwind_design_system(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { validateStyleCandidates } from "./testing/utility/style_compile.mjs";

const result = await validateStyleCandidates({
  cssEntry: "src/style/main.css",
  candidates: ["flex", "text-kind-default", "group/example", "not-a-real-utility"],
  ignored: ["group/example"],
});

assert.equal(result.checked, 4);
assert.deepEqual(result.ignored, ["group/example"]);
assert.deepEqual(result.invalid, ["not-a-real-utility"]);
""",
        module=True,
    )
