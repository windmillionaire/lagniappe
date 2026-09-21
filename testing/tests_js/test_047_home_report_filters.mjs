import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";

function replaceGlobal(t, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
	Object.defineProperty(globalThis, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(globalThis, name, descriptor);
		else delete globalThis[name];
	});
}

async function loadToolReportList() {
	let stored = null;
	const { ToolReportList } = await esmock.strict(
		"../../src/script/widgets/home/lists.mjs",
		{
			"../../src/script/shared/storage.mjs": {
				localStore: {
					getJSON: () => stored,
					setJSON: (_key, value) => {
						stored = value;
					},
				},
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (commit) => await commit(),
			},
		},
	);
	return {
		ToolReportList,
		getStored: () => stored,
		setStored: (value) => {
			stored = value;
		},
	};
}

function fixture(ToolReportList) {
	const items = [];
	const buttons = ["active", "executed", "answers"].map((filter) => ({
		dataset: { filter },
		count: {},
		setAttribute(name, value) {
			this[name] = value;
		},
		querySelector() {
			return this.count;
		},
	}));
	const empty = {};
	const clear = {};
	const result = {};
	const target = {
		dataset: {},
		setAttribute() {},
		querySelectorAll(selector) {
			return selector.includes("report-filter") ? buttons : items;
		},
		querySelector(selector) {
			const key = selector.match(/^\[data-key="(.+)"\]$/)?.[1];
			if (key) return items.find((item) => item.dataset.key === key) || null;
			return (
				{
					"[data-role='report-empty']": empty,
					"[data-role='delete-executed-reports']": clear,
					"[data-role='report-delete-result']": result,
					"[data-role='report-items']": {
						prepend: (...rows) => items.unshift(...rows),
					},
				}[selector] || null
			);
		},
	};
	const component = {
		elt: {
			dataset: { reportUser: "user-1" },
			querySelector: () => null,
		},
	};
	const view = {
		addFlash() {},
		async _refreshHomeWidget() {},
	};
	const widget = new ToolReportList({
		target,
		component,
		view,
		name: "ToolReportList",
		visible: true,
	});
	component.active = widget;
	function add(key, tool, status) {
		const item = {
			dataset: { key, outputKind: tool, status },
			remove() {
				items.splice(items.indexOf(this), 1);
			},
		};
		items.push(item);
		return item;
	}
	return { widget, items, buttons, empty, clear, result, add, target };
}

function renderedCategory(ToolReportList, dataset) {
	const f = fixture(ToolReportList);
	f.add("report", dataset.outputKind, dataset.status);
	f.widget._renderFilters();
	const populated = f.buttons.filter(
		(button) => button.count.textContent === 1,
	);
	assert.equal(populated.length, 1);
	return populated[0].dataset.filter;
}

// @matrix ai-report : filter-categories
test("test_report_categories_and_saved_filter_selection", async () => {
	const state = await loadToolReportList();
	for (const status of [
		"pending",
		"ready",
		"failed",
		"revising",
		"running",
		"undoing",
		"undone",
		"undo_failed",
		"draft",
		"complete",
	]) {
		assert.equal(
			renderedCategory(state.ToolReportList, {
				outputKind: "answer",
				status,
			}),
			"answers",
		);
		assert.equal(
			renderedCategory(state.ToolReportList, {
				outputKind: "proposal",
				status,
			}),
			status === "complete" ? "executed" : "active",
		);
	}
	assert.equal(
		renderedCategory(state.ToolReportList, {
			outputKind: "unknown",
			status: "complete",
		}),
		"active",
	);
	for (const invalid of [null, "executed", {}, ["obsolete"]]) {
		state.setStored(invalid);
		assert.deepEqual(
			[...fixture(state.ToolReportList).widget.filters],
			["active", "answers"],
		);
	}
	state.setStored([]);
	assert.deepEqual([...fixture(state.ToolReportList).widget.filters], []);
	state.setStored(["executed"]);
	assert.deepEqual(
		[...fixture(state.ToolReportList).widget.filters],
		["executed"],
	);
	assert.equal(
		fixture(state.ToolReportList).widget.storageKey,
		"home-report-filters:user-1",
	);
});

// @matrix ai-report : filter-categories filter-counts filter-empty filter-persistence filter-create
test("test_report_filters_count_hidden_categories_and_empty_selections", async () => {
	const state = await loadToolReportList();
	const f = fixture(state.ToolReportList);
	const ready = f.add("ready", "proposal", "ready");
	const executed = f.add("done", "proposal", "complete");
	const answer = f.add("answer", "answer", "complete");
	f.widget.postreconcile();
	assert.equal(ready.hidden, false);
	assert.equal(executed.hidden, true);
	assert.equal(answer.hidden, false);
	assert.deepEqual(
		f.buttons.map((button) => button.count.textContent),
		[1, 1, 1],
	);
	assert.equal(f.clear.hidden, true);
	for (const selection of [
		[],
		["active"],
		["executed"],
		["answers"],
		["active", "executed"],
		["executed", "answers"],
		["active", "answers"],
		["active", "executed", "answers"],
	]) {
		f.widget.filters = new Set(selection);
		f.widget._renderFilters();
		assert.equal(
			f.clear.hidden,
			!(selection.length === 1 && selection[0] === "executed"),
		);
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
	assert.deepEqual(
		f.buttons.map((button) => button.count.textContent),
		[0, 1, 1],
	);
	const created = {
		dataset: { key: "new", outputKind: "answer", status: "pending" },
	};
	f.widget.created({ html: { querySelectorAll: () => [created] } });
	f.widget.postreconcile();
	assert.equal(created.hidden, false);
	assert.deepEqual([...f.widget.filters], ["executed", "answers"]);

	f.widget.filters = new Set(["executed"]);
	f.widget.created({ html: { querySelectorAll: () => [created] } });
	f.widget.postreconcile();
	assert.equal(f.items.filter((item) => item.dataset.key === "new").length, 1);
	assert.equal(created.hidden, false);
	assert.deepEqual([...f.widget.filters], ["executed", "answers"]);
	assert.deepEqual(state.getStored(), ["executed", "answers"]);
});

// @matrix ai-report : bulk-delete delete-failure delete-snapshot loading-indicator
test("test_bulk_delete_recovers_from_partial_and_network_failures", async (t) => {
	replaceGlobal(t, "DOMParser", class {});
	const { request } = await import("../../src/script/shared/request.mjs");
	const originalDelete = request.delete;
	t.after(() => {
		request.delete = originalDelete;
	});
	const state = await loadToolReportList();
	const f = fixture(state.ToolReportList);
	f.widget.filters = new Set(["executed"]);
	f.add("deleted", "proposal", "complete");
	f.add("failed", "proposal", "complete");
	f.add("new-arrival", "proposal", "complete");
	const spinner = { dataset: { visible: "false" } };
	const confirm = { querySelector: () => spinner };
	const error = {};
	const modal = {
		modal: {
			querySelector: (selector) =>
				selector.includes("error") ? error : confirm,
		},
		async remove() {
			this.modal = null;
		},
	};
	request.delete = async (route, data) => {
		assert.equal(route, "/tools/reports/executed");
		assert.deepEqual(Array.from(data.keys), ["deleted", "failed", "changed"]);
		assert.equal(confirm.disabled, true);
		assert.equal(spinner.dataset.visible, "true");
		return {
			ok: true,
			deleted: ["deleted"],
			skipped: ["changed"],
			failed: ["failed"],
		};
	};
	await f.widget._deleteExecuted(
		["deleted", "failed", "changed"],
		"/tools/reports/executed",
		modal,
	);
	assert.deepEqual(
		f.items.map((item) => item.dataset.key),
		["failed", "new-arrival"],
	);
	assert.match(f.result.textContent, /1 could not be deleted/);
	assert.equal(f.clear.disabled, false);
	assert.equal(spinner.dataset.visible, "false");

	modal.modal = {
		querySelector: (selector) => (selector.includes("error") ? error : confirm),
	};
	for (const failure of ["network", "http"]) {
		request.delete = async () => {
			assert.equal(confirm.disabled, true);
			assert.equal(spinner.dataset.visible, "true");
			if (failure === "network") throw new Error("offline");
			return { ok: false };
		};
		await f.widget._deleteExecuted(
			["failed"],
			"/tools/reports/executed",
			modal,
		);
		assert.equal(error.hidden, false);
		assert.equal(confirm.disabled, false);
		assert.equal(spinner.dataset.visible, "false");
		assert.deepEqual(
			f.items.map((item) => item.dataset.key),
			["failed", "new-arrival"],
		);
	}
});
