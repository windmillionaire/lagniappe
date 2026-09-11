"""Deterministic category filtering and bulk-delete request recovery."""

REPORT_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
let stored = null;
const context = {
  localStore: { getJSON: () => stored, setJSON: (_key, value) => { stored = value; } },
  withTransition: async (commit) => commit(),
  request: { delete: async () => ({ ok: true, deleted: [], skipped: [], failed: [] }) },
};
vm.createContext(context);
let base = fs.readFileSync("src/script/elements/base/baseList.mjs", "utf8").replace("export class", "class");
let source = fs.readFileSync("src/script/widgets/home/lists.mjs", "utf8")
  .replace(/^import .*;\n/gm, "")
  .replace(/export class/g, "class")
  .replace('await import("../../shared/request")', '({ request: globalThis.request })');
vm.runInContext(base + source + "\nglobalThis.ToolReportList = ToolReportList; globalThis.category = reportCategory;", context);

function fixture() {
  const items = [];
  const buttons = ["active", "executed", "ask"].map(filter => ({
    dataset: { filter }, count: {},
    setAttribute(name, value) { this[name] = value; },
    querySelector() { return this.count; },
  }));
  const empty = {}, clear = {}, result = {};
  const target = {
    dataset: {}, setAttribute() {},
    querySelectorAll(selector) {
      return selector.includes("report-filter") ? buttons : items;
    },
    querySelector(selector) {
      const key = selector.match(/^\[data-key="(.+)"\]$/)?.[1];
      if (key) return items.find(item => item.dataset.key === key) || null;
      return ({ "[data-role='report-empty']": empty, "[data-role='delete-executed-reports']": clear,
        "[data-role='report-delete-result']": result, "[data-role='report-items']": { prepend: (...rows) => items.unshift(...rows) } })[selector] || null;
    },
  };
  const component = { elt: { dataset: { reportUser: "user-1" }, querySelector: () => null } };
  const view = { addFlash() {}, async _refreshHomeWidget() {} };
  const widget = new context.ToolReportList({ target, component, view, name: "ToolReportList", visible: true });
  component.active = widget;
  function add(key, tool, status) {
    const item = { dataset: { key, tool, status }, remove() { items.splice(items.indexOf(this), 1); } };
    items.push(item);
    return item;
  }
  return { widget, items, buttons, empty, clear, result, add, target };
}
"""


# @matrix ai-report : filter-categories
def test_report_categories_and_saved_filter_selection(run_node):
    run_node(
        REPORT_HARNESS
        + r"""
for (const status of ["pending", "ready", "failed", "revising", "running", "undoing", "undone", "undo_failed", "draft", "complete"]) {
  assert.equal(context.category({ tool: "ask", status }), "ask");
  for (const tool of ["create", "organize"]) {
    assert.equal(context.category({ tool, status }), status === "complete" ? "executed" : "active");
  }
}
assert.equal(context.category({ tool: "unknown", status: "complete" }), "active");
for (const invalid of [null, "executed", {}, ["obsolete"]]) {
  stored = invalid;
  assert.deepEqual([...fixture().widget.filters], ["active", "ask"]);
}
stored = [];
assert.deepEqual([...fixture().widget.filters], []);
stored = ["executed"];
assert.deepEqual([...fixture().widget.filters], ["executed"]);
assert.equal(fixture().widget.storageKey, "home-report-filters:user-1");
"""
    )


# @matrix ai-report : filter-categories filter-counts filter-empty filter-persistence filter-create
def test_report_filters_count_hidden_categories_and_empty_selections(run_node):
    run_node(
        REPORT_HARNESS
        + r"""
const f = fixture();
const ready = f.add("ready", "create", "ready");
const executed = f.add("done", "organize", "complete");
const answer = f.add("answer", "ask", "complete");
f.widget.postreconcile();
assert.equal(ready.hidden, false);
assert.equal(executed.hidden, true);
assert.equal(answer.hidden, false);
assert.deepEqual(f.buttons.map(button => button.count.textContent), [1, 1, 1]);
assert.equal(f.clear.hidden, true);
for (const selection of [[], ["active"], ["executed"], ["ask"], ["active", "executed"], ["executed", "ask"], ["active", "ask"], ["active", "executed", "ask"]]) {
  f.widget.filters = new Set(selection);
  f.widget._renderFilters();
  assert.equal(f.clear.hidden, !(selection.length === 1 && selection[0] === "executed"));
  assert.equal(f.empty.hidden, selection.length > 0);
}
f.widget.filters.clear();
f.widget._renderFilters();
assert.equal(f.empty.textContent, "Select a report type to show.");
assert.equal(f.target.dataset.visible, "true");
f.widget.filters = new Set(["executed"]);
executed.remove();
f.widget.postreconcile();
assert.equal(f.empty.textContent, "No executed proposals.");
assert.equal(f.empty.hidden, false);
assert.equal(f.clear.hidden, true);
assert.equal(f.target.dataset.visible, "true");
ready.dataset.status = "complete";
f.widget.postreconcile();
assert.equal(ready.hidden, false);
assert.deepEqual(f.buttons.map(button => button.count.textContent), [0, 1, 1]);
const created = { dataset: { key: "new", tool: "ask", status: "pending" } };
f.widget.created({ html: { querySelectorAll: () => [created] } });
f.widget.postreconcile();
assert.equal(created.hidden, false);
assert.deepEqual([...f.widget.filters], ["executed", "ask"]);
f.widget.filters = new Set(["executed"]);
f.widget.created({ html: { querySelectorAll: () => [created] } });
f.widget.postreconcile();
assert.equal(f.items.filter(item => item.dataset.key === "new").length, 1);
assert.equal(created.hidden, false);
assert.deepEqual([...f.widget.filters], ["executed", "ask"]);
assert.deepEqual([...stored], ["executed", "ask"]);
"""
    )


# @matrix ai-report : bulk-delete delete-failure delete-snapshot loading-indicator
def test_bulk_delete_recovers_from_partial_and_network_failures(run_node):
    run_node(
        REPORT_HARNESS
        + r"""
(async () => {
  const f = fixture();
  f.widget.filters = new Set(["executed"]);
  f.add("deleted", "create", "complete");
  f.add("failed", "organize", "complete");
  f.add("new-arrival", "create", "complete");
  const spinner = { dataset: { visible: "false" } };
  const confirm = { querySelector: () => spinner }, error = {};
  const modal = { modal: { querySelector: (selector) => selector.includes("error") ? error : confirm }, async remove() { this.modal = null; } };
  context.request.delete = async (route, data) => {
    assert.equal(route, "/tools/reports/executed");
    assert.deepEqual(Array.from(data.keys), ["deleted", "failed", "changed"]);
    assert.equal(confirm.disabled, true);
    assert.equal(spinner.dataset.visible, "true");
    return { ok: true, deleted: ["deleted"], skipped: ["changed"], failed: ["failed"] };
  };
  await f.widget._deleteExecuted(["deleted", "failed", "changed"], "/tools/reports/executed", modal);
  assert.deepEqual(f.items.map(item => item.dataset.key), ["failed", "new-arrival"]);
  assert.match(f.result.textContent, /1 could not be deleted/);
  assert.equal(f.clear.disabled, false);
  assert.equal(spinner.dataset.visible, "false");
  modal.modal = { querySelector: (selector) => selector.includes("error") ? error : confirm };
  for (const failure of ["network", "http"]) {
    context.request.delete = async () => {
      assert.equal(confirm.disabled, true);
      assert.equal(spinner.dataset.visible, "true");
      if (failure === "network") throw new Error("offline");
      return { ok: false };
    };
    await f.widget._deleteExecuted(["failed"], "/tools/reports/executed", modal);
    assert.equal(error.hidden, false);
    assert.equal(confirm.disabled, false);
    assert.equal(spinner.dataset.visible, "false");
    assert.deepEqual(f.items.map(item => item.dataset.key), ["failed", "new-arrival"]);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )
