import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

function replace(t, target, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(target, name);
	Object.defineProperty(target, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(target, name, descriptor);
		else delete target[name];
	});
}

test("test_due_date_section_toggle_avoids_undefined_repeat_label", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/home",
		html: `
			<div id="host">
				<button type="button"
				        data-action="schedule"
				        data-title="Schedule"
				        data-kind="task"></button>
			</div>
		`,
	});

	const { SectionToggle } = await import(
		"../../src/script/elements/sectionToggle.ts"
	);
	const button = document.querySelector("button[data-action='schedule']");
	const parent = {
		button,
		action: "schedule",
		kind: "task",
		active: true,
		open: false,
		schedule: { due: "2026-04-01", scheduled: {} },
		clear() {},
		toggleVisibility() {},
	};

	const toggle = new SectionToggle(parent, {});
	toggle.display();
	assert.doesNotMatch(button.textContent, /undefined/);
	assert.doesNotMatch(button.textContent, /\(repeats/);

	parent.schedule = {
		due: "2026-04-01",
		scheduled: { mode: undefined, text: "" },
	};
	toggle.display();
	assert.doesNotMatch(button.textContent, /undefined/);
	assert.doesNotMatch(button.textContent, /\(repeats/);

	parent.schedule = { due: "2026-04-01", scheduled: { mode: "weekly" } };
	toggle.display();
	assert.match(button.textContent, /\(repeats weekly\)/);

	// Enabling Scheduled on DueDate seeds mode="daily" so collapsing immediately is clean.
	const control = SectionToggle.date(
		{ key: null },
		document.querySelector("button[data-action='schedule']"),
	);
	control.init();
	control.toggleVisibility();
	const scheduledCheckbox = control.container?.querySelector(
		"input[name='scheduled']",
	);
	assert.ok(scheduledCheckbox);
	scheduledCheckbox.checked = true;
	scheduledCheckbox.dispatchEvent(new Event("change", { bubbles: true }));
	assert.equal(control.schedule.scheduled?.mode, "daily");
	assert.doesNotMatch(button.textContent, /undefined/);
});

test("test_modal_locks_scroll_with_refcount_moves_focus_and_restores_on_close", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/",
		html: `
			<button id="trigger-one" type="button">Open First</button>
			<button id="trigger-two" type="button">Open Second</button>
		`,
	});

	const { Modal } = await esmock.strict("../../src/script/shared/modal.ts", {
		"../../src/script/generated/styles.mjs": {
			STYLES: {
				modal: { wrapper: "", content: "", header: "" },
				button: { close: "" },
			},
		},
		"../../src/script/shared/endpoints.ts": {
			ENDPOINTS: { delete: () => "", help: () => "" },
		},
		"../../src/script/shared/errors.ts": {
			captureError: (error) => {
				throw error;
			},
		},
		"../../src/script/shared/request.ts": {
			request: { get: async () => ({}) },
		},
		"../../src/script/shared/transitions.ts": {
			withTransition: async (callback) => {
				callback();
				return true;
			},
		},
	});

	const triggerOne = document.querySelector("#trigger-one");
	const triggerTwo = document.querySelector("#trigger-two");
	triggerOne.focus();

	const firstDialog = document.createElement("div");
	firstDialog.id = "modal";
	firstDialog.innerHTML =
		'<div id="modal-content" role="dialog"><button id="close-one" lp-control="close">Close</button></div>';

	const modalOne = new Modal({}, triggerOne);
	await modalOne.attach(firstDialog);
	assert.equal(document.documentElement.style.overflow, "hidden");
	assert.equal(document.documentElement.dataset.modalLockCount, "1");
	assert.equal(document.activeElement, firstDialog.querySelector("#close-one"));

	const secondDialog = document.createElement("div");
	secondDialog.id = "modal";
	secondDialog.innerHTML =
		'<div id="modal-content" role="dialog"><button id="close-two" autofocus>OK</button></div>';

	triggerTwo.focus();
	const modalTwo = new Modal({}, triggerTwo);
	await modalTwo.attach(secondDialog);
	assert.equal(document.documentElement.style.overflow, "hidden");
	assert.equal(document.documentElement.dataset.modalLockCount, "2");
	assert.equal(
		document.activeElement,
		secondDialog.querySelector("#close-two"),
	);

	// Closing the second modal keeps scroll locked while the first modal stays open.
	await modalTwo.remove();
	assert.equal(document.documentElement.style.overflow, "hidden");
	assert.equal(document.documentElement.dataset.modalLockCount, "1");
	assert.equal(document.activeElement, triggerTwo);

	// Closing the last modal unlocks scroll and restores focus to its trigger.
	await modalOne.remove();
	assert.equal(document.documentElement.style.overflow, "");
	assert.equal(document.documentElement.dataset.modalLockCount, undefined);
	assert.equal(document.activeElement, triggerOne);

	// destroy() releases scroll lock without forcing focus back to the trigger.
	const thirdDialog = document.createElement("div");
	thirdDialog.id = "modal";
	thirdDialog.innerHTML =
		'<div id="modal-content" role="dialog"><button id="inside">Inside</button></div>';
	triggerOne.focus();
	const modalThree = new Modal({}, triggerOne);
	await modalThree.attach(thirdDialog);
	assert.equal(document.documentElement.style.overflow, "hidden");
	document.body.focus();
	modalThree.destroy();
	assert.equal(document.documentElement.style.overflow, "");
	assert.equal(document.documentElement.dataset.modalLockCount, undefined);
	assert.notEqual(document.activeElement, triggerOne);
});

test("test_combobox_focusout_dismisses_only_when_focus_leaves_control_and_panel", async (t) => {
	createBrowser(t, { url: "https://lagniappe.test/" });
	class IntersectionObserver {
		observe() {}
		disconnect() {}
	}
	replace(t, globalThis, "IntersectionObserver", IntersectionObserver);
	replace(t, window, "IntersectionObserver", IntersectionObserver);
	replace(t, window, "matchMedia", () => ({ matches: false }));

	const { Combobox } = await esmock.strict(
		"../../src/script/elements/combobox/combobox.ts",
		{
			"@floating-ui/dom": {
				autoUpdate: (_ref, _panel, cb) => {
					cb();
					return () => {};
				},
				computePosition: () => Promise.resolve({ x: 0, y: 0 }),
				flip: (options) => ({ name: "flip", options }),
				offset: (value) => ({ name: "offset", value }),
				shift: (options) => ({ name: "shift", options }),
			},
		},
	);

	const parent = document.createElement("div");
	const input = document.createElement("input");
	const outside = document.createElement("button");
	outside.textContent = "Outside";
	parent.appendChild(input);
	document.body.append(parent, outside);

	const combobox = new Combobox(parent);
	combobox.selectOption = () => {};
	combobox.init();
	combobox.items = [{ id: "opt-1", name: "Option 1" }];
	combobox.updatePanel(
		'<button role="option" data-index="0">Option 1</button>',
	);
	t.mock.method(combobox, "_startAutoUpdate", () => Promise.resolve(true));

	await combobox.showPanel();
	assert.equal(combobox.panelOpen, true);

	const option = combobox.panel.querySelector('[role="option"]');
	input.focus();

	// Focus moving inside the panel keeps the combobox open.
	input.dispatchEvent(
		new window.FocusEvent("focusout", { bubbles: true, relatedTarget: option }),
	);
	await Promise.resolve();
	assert.equal(combobox.panelOpen, true);

	// Focus moving outside trigger and panel dismisses the combobox.
	outside.focus();
	input.dispatchEvent(
		new window.FocusEvent("focusout", {
			bubbles: true,
			relatedTarget: outside,
		}),
	);
	await Promise.resolve();
	assert.equal(combobox.panelOpen, false);
});

test("test_builder_compact_fields_render_preview_hints", async (t) => {
	createBrowser(t, { url: "https://lagniappe.test/forms/form-1" });
	const { ModelElement } = await import(
		"../../src/script/views/builder/panels/model.ts"
	);

	const cases = [
		[
			ModelElement.status({ id: "s1", type: "status", title: "Status" }),
			"Automatic status",
		],
		[
			ModelElement.status({
				id: "s2",
				type: "status",
				title: "Status",
				status: [{ id: "chk", checked: true }],
			}),
			"1 status rule",
		],
		[
			ModelElement.status({
				id: "s3",
				type: "status",
				title: "Status",
				status: [
					{ id: "c1", checked: true },
					{ id: "c2", checked: false },
				],
			}),
			"2 status rules",
		],
		[
			ModelElement.todo({ id: "t1", type: "todo", title: "Checklist" }),
			"Checklist items",
		],
		[
			ModelElement.signature({
				id: "g1",
				type: "signature",
				title: "Sign-Off",
			}),
			"Signature capture",
		],
		[
			ModelElement.bookmark({ id: "b1", type: "bookmark", title: "Bookmark" }),
			"Page bookmark",
		],
		[
			ModelElement.html({ id: "h1", type: "html", title: "Instructions" }),
			"Formatted text",
		],
		[
			ModelElement.link({
				id: "l1",
				type: "link",
				title: "Reference URL",
				location: "out",
			}),
			"External link",
		],
	];

	for (const [el, expected] of cases) {
		const hint = el.querySelector("[data-role='field-preview-hint']");
		assert.ok(hint, `Expected field-preview-hint on ${el.id}`);
		assert.equal(hint.textContent, expected);
	}
});
