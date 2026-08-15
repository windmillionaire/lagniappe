"""Node-backed checks for the task-form todo list element."""


# @pairs form-todo:normalization form-todo:history-fill form-todo:checked-state
def test_todo_value_normalization_and_history_reset(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class BaseElement {}
const context = { BaseElement };
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/todo.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace(
  "export const normalizeTodoValue =",
  "const normalizeTodoValue =",
);
source = source.replace("export class TodoElement", "class TodoElement");
source += `
globalThis.normalizeTodoValue = normalizeTodoValue;
globalThis.TodoElement = TodoElement;
`;
vm.runInContext(source, context);

const input = {
  items: [
    { text: "  First  ", checked: true },
    { text: "", checked: true },
    { text: "Second", checked: false },
  ],
};
const normalized = context.normalizeTodoValue(input);
if (JSON.stringify(normalized) !== JSON.stringify({
  items: [
    { text: "First", checked: true },
    { text: "Second", checked: false },
  ],
})) {
  throw new Error(`Unexpected normalized value: ${JSON.stringify(normalized)}`);
}

const todo = Object.create(context.TodoElement.prototype);
Object.assign(todo, {
  submission: null,
  _input: null,
  _editing: true,
  _draftVisible: true,
  _draft: "pending",
  _renamingIndex: 0,
});
let rendered = 0;
let changed = 0;
todo._render = () => { rendered += 1; };
todo._notifyChange = () => { changed += 1; };

const filled = todo.fillFromHistory(input);
if (!filled || rendered !== 1 || changed !== 1) {
  throw new Error("History fill did not redraw and publish one change");
}
if (todo.historyFillPersistsDefault !== false) {
  throw new Error("Todo history fill must not become a repeating default");
}
if (todo.submission.items.some((item) => item.checked)) {
  throw new Error("History fill retained a completed checkbox");
}
if (todo._editing || todo._draftVisible || todo._renamingIndex !== null) {
  throw new Error("History fill did not return the list to normal mode");
}
'''
    )


# @pair form-todo:keyboard
def test_todo_keyboard_commit_contract(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class BaseElement {}
const context = { BaseElement };
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/todo.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace(
  "export const normalizeTodoValue =",
  "const normalizeTodoValue =",
);
source = source.replace("export class TodoElement", "class TodoElement");
source += "\nglobalThis.TodoElement = TodoElement;";
vm.runInContext(source, context);

const todo = Object.create(context.TodoElement.prototype);
let commits = 0;
todo._commitDraft = () => { commits += 1; };

const event = (key, shiftKey = false) => ({
  key,
  shiftKey,
  target: { dataset: { role: "todo-draft" } },
  prevented: false,
  preventDefault() { this.prevented = true; },
});

const enter = event("Enter");
todo._keydown(enter);
const tab = event("Tab");
todo._keydown(tab);
const reverseTab = event("Tab", true);
todo._keydown(reverseTab);

if (!enter.prevented || !tab.prevented || commits !== 2) {
  throw new Error("Enter and forward Tab must commit the current draft");
}
if (reverseTab.prevented) {
  throw new Error("Shift+Tab must remain an escape path from the list");
}

const list = Object.create(context.TodoElement.prototype);
Object.assign(list, {
  submission: { items: [{ text: "Before", checked: true }] },
  _input: null,
  _draft: "New item",
  _draftVisible: true,
  _renamingIndex: 0,
  _renameValue: "After",
});
list._render = () => {};
list._notifyChange = () => {};
list._focus = () => {};
list._commitDraft();
if (JSON.stringify(list.submission) !== JSON.stringify({
  items: [
    { text: "After", checked: true },
    { text: "New item", checked: false },
  ],
})) {
  throw new Error("Committing a draft lost the active item rename");
}
'''
    )


# @pair form-todo:title-actions
def test_todo_title_actions_use_table_style_semantics(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class Node {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.value = "";
  }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  querySelector(selector) {
    return selector === "[data-role='label']" ? this.labelControls : null;
  }
}

class BaseElement {
  historyFillButton() {
    const button = new Node("button");
    button.className = "form-title-action";
    button.dataset.role = "history-fill";
    return button;
  }
}

const context = {
  BaseElement,
  STYLES: {
    form: {
      icon: "form-title-action",
      table: { actionButton: "outlined-row-action" },
      todo: { list: "", row: "", actions: "", text: "", completeText: "", inlineInput: "" },
    },
    label: { row: "" },
  },
  document: { createElement: (tagName) => new Node(tagName) },
  primitives: {
    label() {
      const label = new Node("h3");
      label.labelControls = label.appendChild(new Node("div"));
      return label;
    },
  },
  setIcon(element, name) { element.dataset.icon = name; return element; },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/todo.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export const normalizeTodoValue =", "const normalizeTodoValue =");
source = source.replace("export class TodoElement", "class TodoElement");
source += "\nglobalThis.TodoElement = TodoElement;";
vm.runInContext(source, context);

const todo = Object.create(context.TodoElement.prototype);
Object.assign(todo, {
  _elt: new Node("div"),
  _input: new Node("input"),
  _editing: false,
  _draftVisible: false,
  _renamingIndex: null,
  _historyValue: { items: [{ text: "Earlier", checked: false }] },
  _historyOnFill: null,
  label: "Checklist",
  readonly: false,
  hasSubmission: false,
  submission: null,
});

todo._render();
let controls = todo._elt.children[1].children;
const add = controls.find((child) => child.dataset.role === "todo-edit");
const history = controls.find((child) => child.dataset.role === "history-fill");
const actionOrder = controls
  .map((child) => child.dataset.role)
  .filter(Boolean);
if (JSON.stringify(actionOrder) !== JSON.stringify(["history-fill", "todo-edit"])) {
  throw new Error(`Unexpected Todo title action order: ${JSON.stringify(actionOrder)}`);
}
if (add?.className !== "form-title-action" || add.dataset.kind !== "add") {
  throw new Error("Empty Todo add action did not match the green table title action");
}
if (history?.className !== "form-title-action" || history.dataset.kind) {
  throw new Error("Todo history action did not retain the form title color");
}

todo._editing = true;
todo._render();
controls = todo._elt.children[1].children;
const done = controls.find((child) => child.dataset.role === "todo-done");
if (done?.className !== "form-title-action" || done.dataset.kind !== "success") {
  throw new Error("Todo done action did not use the lightweight green title treatment");
}

const remove = todo._button({
  role: "todo-remove",
  icon: "remove",
  label: "Remove item",
  kind: "delete",
});
if (remove.className !== "outlined-row-action") {
  throw new Error("Todo item actions lost their bounded row-action treatment");
}
'''
    )


# @pair forms:components
def test_todo_builder_registration_is_task_only(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = {};
vm.createContext(context);
let source = fs.readFileSync("src/script/config/builder.mjs", "utf8");
source = source.replace("const CONFIG =", "globalThis.CONFIG =");
source = source.replace("export { CONFIG };", "");
vm.runInContext(source, context);

const taskTodo = context.CONFIG.FORM_COMPONENTS.find(({ type }) => type === "todo");
const pageTodo = context.CONFIG.PAGE_COMPONENTS.find(({ type }) => type === "todo");
if (!taskTodo || taskTodo.label !== "Todo List" || taskTodo.icon !== "checklist") {
  throw new Error("Task builder palette is missing the todo list component");
}
if (pageTodo) {
  throw new Error("Page builder palette exposed the task-only todo list");
}
if (context.CONFIG.PRESENTATION_DEFAULTS.todo.title !== "Todo List") {
  throw new Error("Todo presentation defaults are missing");
}
if (!context.CONFIG.DEFAULT_SETTINGS.todo.includes("title")) {
  throw new Error("Todo builder settings are missing title editing");
}
'''
    )
