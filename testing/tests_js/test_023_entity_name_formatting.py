"""Node-backed checks for shared parent/name formatting."""

ENTITY_NAME_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

class FakeText {
  constructor(text) {
    this.textContent = text;
  }

  get outerHTML() {
    return escapeHtml(this.textContent);
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.attributes = new Map();
    this.children = [];
    this.className = "";
    this.dataset = {};
    this.id = "";
    this.innerHTML = "";
    this.textContent = "";
  }

  append(...children) {
    children.forEach((child) => this.appendChild(child));
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  get outerHTML() {
    const attributes = [...this.attributes.entries()];
    if (this.className) attributes.push(["class", this.className]);
    if (this.id) attributes.push(["id", this.id]);
    if (this.href) attributes.push(["href", String(this.href)]);
    const serializedAttributes = attributes
      .map(([name, value]) => ` ${name}="${value}"`)
      .join("");
    const content =
      this.innerHTML ||
      `${escapeHtml(this.textContent)}${this.children.map((child) => child.outerHTML).join("")}`;
    return `<${this.tagName.toLowerCase()}${serializedAttributes}>${content}</${this.tagName.toLowerCase()}>`;
  }
}

const values = new Map();
const context = {
  console,
  document: {
    createElement: (tagName) => new FakeElement(tagName),
    createTextNode: (text) => new FakeText(text),
  },
  iconDefinition(name) {
    return name === "page" ? { glyph: "draft", fill: 1 } : null;
  },
  setIcon(element, name, classes = "") {
    element.className = `icon ${classes}`.trim();
    element.dataset.icon = name;
    element.textContent = name === "page" ? "draft" : "";
    return element;
  },
  localStorage: {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  },
  localStore: {
    getJSON(key, fallback = null) {
      const value = values.get(key);
      return value === undefined ? fallback : JSON.parse(value);
    },
    remove: (key) => values.delete(key),
    setJSON: (key, value) => values.set(key, JSON.stringify(value)),
  },
  STYLES: {
    dropdown: {
      icon: "dropdown-option-icon",
      option: {
        flow: "dropdown-option dropdown-option-flow",
      },
      search: {
        link: "search-link",
        result: "search-result",
      },
    },
    entity: {
      name: {
        parent: "whitespace-nowrap",
        separator: "mx-1 text-base-medium",
        wrapper: "min-w-0",
      },
    },
    link: {
      emphasized: "link-emphasized",
    },
  },
  URL,
  values,
  window: {
    location: {
      origin: "https://example.test/",
    },
  },
};

vm.createContext(context);
let formattingSource = fs.readFileSync(
  "src/script/elements/formatting.mjs",
  "utf8",
);
formattingSource = formattingSource.replace(/^import .*;\n/gm, "");
formattingSource = formattingSource.replace(
  "export const formatting =",
  "globalThis.formatting =",
);
vm.runInContext(formattingSource, context);

let resultsSource = fs.readFileSync(
  "src/script/elements/combobox/results.mjs",
  "utf8",
);
resultsSource = resultsSource.replace(/^import .*;\n/gm, "");
resultsSource = resultsSource.replace(
  "export class Results",
  "class Results",
);
resultsSource = `(function () {\n${resultsSource}\nglobalThis.Results = Results;\n})();`;
vm.runInContext(resultsSource, context);

const formatting = context.formatting;
const Results = context.Results;
const STYLES = context.STYLES;

__ASSERTION__
"""


def run_entity_name_check(run_node, assertion: str):
    run_node(ENTITY_NAME_HARNESS.replace("__ASSERTION__", assertion))


# @matrix entity-name : accessibility parent-separator wrapping
# @styles entity.name.wrapper entity.name.parent entity.name.separator
def test_formatting_name_uses_a_text_separator_and_shared_wrapping_structure(run_node):
    run_entity_name_check(
        run_node,
        r"""
const formatted = formatting.name({
  id: "task-1",
  kind: "page",
  link: true,
  name: "A long child name",
  parent: { id: "category-1", kind: "category", name: "Medical" },
});

if (formatted.className !== STYLES.entity.name.wrapper) {
  throw new Error(`Unexpected wrapper style: ${formatted.className}`);
}
if (formatted.children.length !== 3) {
  throw new Error("Parent group, break opportunity, and entity name are not sibling flow items");
}

const [parent, breakOpportunity, name] = formatted.children;
if (!parent.className.includes(STYLES.entity.name.parent)) {
  throw new Error("Parent and separator are not kept together");
}
if (parent.children.length !== 2 || parent.children[0].textContent !== "Medical") {
  throw new Error("Parent name structure changed");
}

const separator = parent.children[1];
if (
  separator.tagName !== "SPAN" ||
  separator.textContent !== "/" ||
  separator.className !== STYLES.entity.name.separator ||
  separator.attributes.get("aria-hidden") !== "true"
) {
  throw new Error(`Separator is not shared accessible text: ${separator.outerHTML}`);
}
if (breakOpportunity.tagName !== "WBR") {
  throw new Error("Parent and entity name have no explicit wrapping opportunity");
}
if (name.tagName !== "A" || name.children.length !== 0) {
  throw new Error("Entity link is not a direct wrapping sibling of its parent group");
}
if (String(name.href) !== "https://example.test/pages/task-1") {
  throw new Error(`Unexpected entity URL: ${name.href}`);
}
""",
    )


# @pair user-groups:query-route
def test_group_name_uses_canonical_user_index_url(run_node):
    run_entity_name_check(
        run_node,
        r"""
const formatted = formatting.name({
  id: "group-1",
  kind: "group",
  link: true,
  name: "Editors",
});
const link = formatted.children[0];
if (String(link.href) !== "https://example.test/users/index?group=group-1") {
  throw new Error(`Unexpected group URL: ${link.href}`);
}
""",
    )


# @matrix combobox entity-name : parent-separator recent-results
# @styles entity.name.wrapper entity.name.parent entity.name.separator
def test_recent_combobox_results_reuse_shared_parent_name_formatting(run_node):
    run_entity_name_check(
        run_node,
        r"""
values.set(
  "recent-page",
  JSON.stringify([
    {
      id: "page-1",
      kind: "page",
      name: "A long child name",
      parent: { id: "category-1", kind: "category", name: "Medical" },
    },
  ]),
);

const recentHtml = new Results("page").create();
if (!recentHtml.includes('class="min-w-0"')) {
  throw new Error(`Recent result skipped the shared name wrapper: ${recentHtml}`);
}
if (!recentHtml.includes("whitespace-nowrap")) {
  throw new Error(`Recent result can separate its parent and slash: ${recentHtml}`);
}
if (
  !recentHtml.includes('aria-hidden="true"') ||
  !recentHtml.includes('>/</span>')
) {
  throw new Error(`Recent result did not render the text separator: ${recentHtml}`);
}
if (
  recentHtml.includes("<" + "i") ||
  !recentHtml.includes("icon")
) {
  throw new Error(`Recent result did not use semantic Material markup: ${recentHtml}`);
}
if (!recentHtml.includes(STYLES.dropdown.icon)) {
  throw new Error(`Recent result skipped shared dropdown icon spacing: ${recentHtml}`);
}
""",
    )


# @pair search:snippet-safety
def test_recent_search_snippets_allow_only_highlight_markup(run_node):
    run_entity_name_check(
        run_node,
        r"""
const recentHtml = new Results("search").create([
  {
    details: {
      id: "page-1",
      kind: "page",
      name: "Safe result",
    },
    text:
      'Before <b>hit &lt;tag&gt;</b> ' +
      '<img src=x onerror="globalThis.compromised=true"> ' +
      '&#x3c;script&#x3e;globalThis.compromised=true&#x3c;/script&#x3e;',
    url: "/pages/page-1",
  },
]);

if (!recentHtml.includes("<b>hit &lt;tag&gt;</b>")) {
  throw new Error(`Generated highlight markup was not preserved: ${recentHtml}`);
}
if (recentHtml.includes("<img") || recentHtml.includes("<script")) {
  throw new Error(`Unexpected snippet markup reached the result DOM: ${recentHtml}`);
}
if (
  !recentHtml.includes("&lt;img") ||
  !recentHtml.includes("&lt;script&gt;globalThis.compromised=true&lt;/script&gt;")
) {
  throw new Error(`Unexpected markup was not rendered as inert text: ${recentHtml}`);
}
if (Object.hasOwn(globalThis, "compromised")) {
  throw new Error("Snippet markup executed in the result renderer");
}
""",
    )
