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
				<div data-role="facets" data-has-selection="false">
					<button type="button" data-role="attribute" data-kind="page" data-selected="false" aria-pressed="false">Pages</button>
					<button type="button" data-role="attribute" data-kind="task" data-selected="false" aria-pressed="false">Tasks</button>
					<button type="button" data-role="reset" aria-label="Clear filters" title="Clear filters"></button>
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
					async get() {
						return {
							ok: true,
							html: new DOMParser().parseFromString(
								'<div data-role="results"></div>',
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

	await view.handleFacetClick(new MouseEvent("click"), taskBtn);
	assert.equal(taskBtn.getAttribute("aria-pressed"), "true");
	assert.equal(taskBtn.dataset.selected, "true");

	await view.handleResetClick(new MouseEvent("click"));
	assert.equal(pageBtn.getAttribute("aria-pressed"), "false");
	assert.equal(taskBtn.getAttribute("aria-pressed"), "false");
	assert.equal(resetBtn.getAttribute("aria-label"), "Clear filters");
});
