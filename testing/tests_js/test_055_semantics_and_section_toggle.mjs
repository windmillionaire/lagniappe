import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

test("test_section_toggle_renders_sibling_link_and_clear_buttons_without_nesting", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/pages/page-1",
		html: `
			<div class="wrapper">
				<button type="button"
				        data-action="select-form"
				        data-title="Attach Form"
				        data-kind="form"></button>
			</div>
		`,
	});

	const { SectionToggle } = await import(
		"../../src/script/elements/sectionToggle.ts"
	);
	const button = document.querySelector("button[data-action='select-form']");
	let cleared = 0;
	let toggled = 0;

	const parent = {
		button,
		action: "select-form",
		kind: "form",
		index: "form",
		active: true,
		open: false,
		details: {
			id: "form-123",
			kind: "form",
			name: "Monthly Apiary Hive Inspection Checklist",
		},
		clear() {
			cleared += 1;
			this.active = false;
			this.details = {};
			toggle.display();
		},
		toggleVisibility() {
			toggled += 1;
			this.open = !this.open;
			toggle.display();
		},
	};

	const toggle = new SectionToggle(parent, {});
	toggle.display();

	const row = button.parentElement;
	assert.equal(row?.dataset.role, "section-toggle-row");
	assert.equal(
		button.querySelectorAll("button, a").length,
		0,
		"Main section toggle button must never contain nested buttons or links",
	);
	assert.equal(
		button.title,
		"Monthly Apiary Hive Inspection Checklist",
		"Full entity name should be exposed in title tooltip",
	);
	assert.equal(button.getAttribute("aria-expanded"), "false");

	const openLink = row.querySelector(":scope > a[data-role='open-link']");
	assert.ok(openLink, "Active entity should render a sibling open-link");
	assert.equal(
		openLink.getAttribute("href"),
		"https://lagniappe.test/forms/form-123",
	);
	assert.equal(
		openLink.getAttribute("aria-label"),
		"Open Monthly Apiary Hive Inspection Checklist",
	);

	const clearBtn = row.querySelector(":scope > button[data-role='clear']");
	assert.ok(clearBtn, "Active toggle should render a sibling clear button");
	assert.equal(clearBtn.getAttribute("aria-label"), "Clear Attach Form");

	// Opening hides open-link and flips aria-expanded to true.
	button.click();
	assert.equal(toggled, 1);
	assert.equal(button.getAttribute("aria-expanded"), "true");
	assert.equal(row.querySelector(":scope > a[data-role='open-link']"), null);
	assert.equal(
		row
			.querySelector(":scope > button[data-role='clear']")
			?.getAttribute("aria-label"),
		"Close Attach Form",
	);

	// Clearing via sibling button removes active selection.
	row.querySelector(":scope > button[data-role='clear']").click();
	assert.equal(cleared, 1);
	assert.equal(button.title, "Attach Form");
});

test("test_search_results_facets_sync_aria_pressed_on_toggle_and_reset", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/l/search?q=hive&kind=page",
		html: `
			<div lp-view data-kind="results">
				<div data-role="search-summary">4 results for “hive”</div>
				<div data-role="facets" data-has-selection="false">
					<button type="button" data-role="reset" data-selected="true" aria-pressed="true" aria-label="Clear filters" title="Show all results">All <span>10</span></button>
					<button type="button" data-role="attribute" data-kind="page" data-selected="false" aria-pressed="false">Pages</button>
					<button type="button" data-role="attribute" data-kind="task" data-selected="false" aria-pressed="false">Tasks</button>
				</div>
				<div data-role="results"></div>
			</div>
		`,
	});
	window.matchMedia = () => ({
		matches: false,
		addEventListener() {},
		removeEventListener() {},
	});

	class ShellViewStub {
		async init() {}
	}
	const { default: Results } = await esmock.strict(
		"../../src/script/views/results.ts",
		{
			"../../src/script/shared/request.ts": {
				request: {
					async get(url) {
						const summary = url.includes("kind=")
							? "9 results for “hive”"
							: "10 results for “hive”";
						return {
							ok: true,
							html: new DOMParser().parseFromString(
								`<div data-role="search-summary">${summary}</div><div data-role="results"></div>`,
								"text/html",
							),
						};
					},
				},
			},
			"../../src/script/shared/transitions.ts": {
				withTransition: (cb) => cb(),
			},
			"../../src/script/views/base/shell.ts": { default: ShellViewStub },
		},
	);

	const view = new Results();
	await view.init();

	const pageBtn = document.querySelector(
		"[data-role='attribute'][data-kind='page']",
	);
	const taskBtn = document.querySelector(
		"[data-role='attribute'][data-kind='task']",
	);
	const resetBtn = document.querySelector("[data-role='reset']");

	assert.equal(pageBtn.getAttribute("aria-pressed"), "true");
	assert.equal(taskBtn.getAttribute("aria-pressed"), "false");
	assert.equal(resetBtn.dataset.selected, "false");
	assert.equal(resetBtn.getAttribute("aria-pressed"), "false");

	await view.handleFacetClick(new MouseEvent("click"), taskBtn);
	assert.equal(taskBtn.getAttribute("aria-pressed"), "true");
	assert.equal(taskBtn.dataset.selected, "true");
	assert.equal(
		document.querySelector("[data-role='search-summary']").textContent,
		"9 results for “hive”",
	);

	await view.handleResetClick(new MouseEvent("click"));
	assert.equal(pageBtn.getAttribute("aria-pressed"), "false");
	assert.equal(taskBtn.getAttribute("aria-pressed"), "false");
	assert.equal(resetBtn.dataset.selected, "true");
	assert.equal(resetBtn.getAttribute("aria-pressed"), "true");
	assert.equal(
		document.querySelector("[data-role='search-summary']").textContent,
		"10 results for “hive”",
	);
	assert.equal(resetBtn.getAttribute("aria-label"), "Clear filters");
});

test("test_task_chips_tray_toggle_and_apply_update_preserves_open_form", async (t) => {
	createBrowser(t);
	const { setTaskTrayOpen, applyTaskChipUpdate } = await esmock.strict(
		"../../src/script/widgets/taskChips.ts",
		{
			"../../src/script/elements/combobox/facets.ts": {
				FacetsBox: class {},
				isFacetOption: () => false,
			},
			"../../src/script/elements/dueDate.ts": { DueDate: class {} },
			"../../src/script/elements/formatting.ts": { formatting: {} },
			"../../src/script/elements/taskUpload.ts": { TaskUpload: class {} },
			"../../src/script/shared/index.ts": { request: {} },
			"../../src/script/shared/transitions.ts": {
				withTransition: (cb) => cb(),
			},
		},
	);

	document.body.innerHTML = `
		<li id="task-1" data-open="TaskForm" data-name="Before">
			<div lp-nav data-nav="task-1">
				<span data-role="title">Before</span>
				<button data-role="save-toggle" data-saved="false" data-visible="true"></button>
				<div data-role="task-chips" data-tray-open="false">
					<button data-role="chip-tray-toggle" aria-expanded="false">
						<span class="icon" data-icon="plus"></span>
					</button>
				</div>
			</div>
			<form data-widget="TaskForm"><input name="notes" value="unsaved draft"></form>
		</li>
	`;

	const row = document.getElementById("task-1");
	setTaskTrayOpen(row, true);
	const chips = row.querySelector("[data-role='task-chips']");
	const toggle = row.querySelector("[data-role='chip-tray-toggle']");
	assert.equal(chips.dataset.trayOpen, "true");
	assert.equal(toggle.getAttribute("aria-expanded"), "true");
	assert.equal(toggle.querySelector(".icon").dataset.icon, "minus");

	const formNode = row.querySelector("[data-widget='TaskForm']");
	const inputNode = formNode.querySelector("input[name='notes']");
	let reconciledWith = null;
	const task = {
		name: "task-1",
		elt: row,
		widgets: { TaskForm: { name: "TaskForm", unsavedState: true } },
		active: { name: "TaskForm" },
		activeWidget: { name: "TaskForm" },
		nav: {
			reconcile(widget, name) {
				reconciledWith = [widget, name];
			},
		},
		_replaceNav(update) {
			const nextNav = update.querySelector("[lp-nav]");
			row.querySelector("[lp-nav]").replaceWith(nextNav);
		},
	};

	const responseHtml = new DOMParser().parseFromString(
		`<li id="task-1" data-name="After">
			<div lp-nav data-nav="task-1">
				<span data-role="title">After</span>
				<button data-role="save-toggle" data-saved="true" data-visible="false"></button>
				<div data-role="task-chips" data-tray-open="false">
					<button data-role="chip-tray-toggle" aria-expanded="false">
						<span class="icon" data-icon="plus"></span>
					</button>
				</div>
			</div>
			<form data-widget="TaskForm"><input name="notes" value="server value"></form>
		</li>`,
		"text/html",
	);

	await applyTaskChipUpdate(
		task,
		{ ok: true, html: responseHtml },
		{
			chipField: "name",
		},
	);

	assert.equal(row.querySelector("[data-role='title']").textContent, "After");
	assert.equal(
		row.querySelector("[data-role='task-chips']").dataset.trayOpen,
		"true",
	);
	assert.equal(
		row.querySelector("[data-role='chip-tray-toggle'] .icon").dataset.icon,
		"minus",
	);
	assert.equal(
		row.querySelector("[data-widget='TaskForm']"),
		formNode,
		"Non-form chip update must keep the open TaskForm DOM intact",
	);
	assert.equal(inputNode.value, "unsaved draft");
	assert.equal(
		row.querySelector("[data-role='save-toggle']").dataset.visible,
		"true",
	);
	assert.deepEqual(reconciledWith, ["TaskForm", "task-1"]);
});
