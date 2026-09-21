import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { Submitter } from "../../src/script/elements/combobox/submitter.mjs";
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

function installBrowserBoundaries(t, options = {}) {
	createBrowser(t, options);
	class IntersectionObserver {
		constructor(callback) {
			this.callback = callback;
		}

		observe(element) {
			this.observed = element;
		}

		disconnect() {
			this.disconnected = true;
		}
	}
	replace(t, globalThis, "IntersectionObserver", IntersectionObserver);
	replace(t, window, "IntersectionObserver", IntersectionObserver);
	replace(t, window, "matchMedia", () => ({ matches: false }));
}

function makeComboboxElements() {
	const parent = document.createElement("label");
	parent.dataset.index = "people";
	const initial = document.createElement("select");
	initial.dataset.index = "people";
	initial.id = "people";
	initial.name = "people";
	parent.appendChild(initial);
	document.body.appendChild(parent);
	return { initial, parent };
}

function option(index, id) {
	const element = document.createElement("button");
	element.dataset.index = String(index);
	element.id = id;
	element.setAttribute("role", "option");
	element.scrollIntoView = () => {};
	return element;
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

async function setupFloating(t) {
	installBrowserBoundaries(t);
	const autoUpdateCalls = [];
	const computePositionCalls = [];
	let computePositionImpl = (_reference, _panel, options) =>
		Promise.resolve({ placement: options.placement, x: 101, y: 202 });
	const autoUpdate = (reference, panel, callback) => {
		const call = { callback, cleaned: false, panel, reference };
		autoUpdateCalls.push(call);
		callback();
		return () => {
			call.cleaned = true;
		};
	};
	const computePosition = (reference, panel, options) => {
		computePositionCalls.push({ options, panel, reference });
		return computePositionImpl(reference, panel, options);
	};
	const flip = (options) => ({ name: "flip", options });
	const offset = (value) => ({ name: "offset", value });
	const shift = (options) => ({ name: "shift", options });
	const { Combobox } = await esmock.strict(
		"../../src/script/elements/combobox/combobox.mjs",
		{
			"@floating-ui/dom": {
				autoUpdate,
				computePosition,
				flip,
				offset,
				shift,
			},
		},
	);
	const { Dropdown } = await esmock.strict(
		"../../src/script/elements/combobox/dropdown.mjs",
		{
			"../../src/script/elements/combobox/combobox.mjs": { Combobox },
		},
	);
	return {
		autoUpdateCalls,
		Combobox,
		computePositionCalls,
		Dropdown,
		setComputePosition(value) {
			computePositionImpl = value;
		},
	};
}

/** @matrix location : initialization on-demand */
test("test_location_combobox_starts_location_sync_on_init", async (t) => {
	installBrowserBoundaries(t, {
		html: '<label><input name="place" placeholder="Search for a place"></label>',
	});
	const updateUserLocation = t.mock.fn(async () => true);
	const { LocationBox } = await esmock.strict(
		"../../src/script/elements/combobox/location.mjs",
		{
			"../../src/script/shared/user.mjs": { updateUserLocation },
		},
	);
	const element = document.querySelector("input");
	const box = new LocationBox(element);
	box.init();

	assert.equal(
		updateUserLocation.mock.callCount(),
		1,
		"LocationBox initialization did not start one location update",
	);
	assert.equal(element.name, "");
	assert.equal(box.hiddenInput?.name, "place:id");
	box.destroy();
});

/** @matrix location : request-ordering session-update */
test("test_location_combobox_waits_for_session_sync_before_search", async (t) => {
	installBrowserBoundaries(t, { html: "<label><input></label>" });
	const calls = [];
	let releaseLocation;
	const locationReady = new Promise((resolve) => {
		releaseLocation = resolve;
	});
	const updateUserLocation = t.mock.fn(() => {
		calls.push("location");
		return locationReady;
	});
	const get = t.mock.fn(async () => {
		calls.push("request");
		return { ok: false };
	});
	const { LocationBox } = await esmock.strict(
		"../../src/script/elements/combobox/location.mjs",
		{
			"../../src/script/shared/request.mjs": { request: { get } },
			"../../src/script/shared/user.mjs": { updateUserLocation },
		},
	);
	const element = document.querySelector("input");
	element.value = "coffee";
	const box = new LocationBox(element);
	t.mock.method(box, "_appendManualOption", () => {});
	t.mock.method(box, "showPanel", () => {
		calls.push("panel");
		return Promise.resolve(true);
	});
	const search = box._search("coffee");
	await Promise.resolve();
	assert.deepEqual(
		calls,
		["location"],
		"Places search did not wait for location",
	);

	releaseLocation(true);
	await search;
	assert.deepEqual(calls, ["location", "request", "panel"]);
});

/**
 * @matrix combobox dropdown : positioning
 * @style dropdown.panel
 * @style dropdown.menu
 */
test("test_combobox_positioning_uses_live_element_by_default_and_explicit_reference_when_configured", async (t) => {
	const env = await setupFloating(t);
	const { parent } = makeComboboxElements();
	const combobox = new env.Combobox(parent);
	const replacementInput = document.createElement("input");
	replacementInput.classList.add("w-full");
	t.mock.method(replacementInput, "getBoundingClientRect", () => ({
		width: 123.6,
	}));
	combobox.element = replacementInput;
	combobox.panel = document.createElement("div");
	await combobox._startAutoUpdate();

	assert.equal(env.autoUpdateCalls[0].reference, replacementInput);
	assert.equal(env.computePositionCalls[0].reference, replacementInput);
	assert.equal(combobox.panel.style.width, "124px");
	assert.equal(combobox.panel.style.left, "101px");
	assert.equal(combobox.panel.style.top, "202px");

	const trigger = document.createElement("button");
	document.body.appendChild(trigger);
	const title = document.createElement("span");
	t.mock.method(title, "getBoundingClientRect", () => ({ width: 197.2 }));
	const dropdown = new env.Dropdown(trigger).init({
		items: [],
		matchReferenceWidth: true,
		placement: "bottom-start",
		positionReference: title,
	});
	dropdown.panel = document.createElement("div");
	await dropdown._startAutoUpdate();
	assert.equal(env.autoUpdateCalls[1].reference, title);
	assert.equal(env.computePositionCalls[1].options.placement, "bottom-start");
	assert.equal(dropdown.panel.style.minWidth, "198px");
	assert.deepEqual(env.computePositionCalls[1].options.middleware, [
		{ name: "offset", value: 4 },
		{ name: "flip", options: { padding: 5 } },
		{ name: "shift", options: { padding: 5 } },
	]);

	env.setComputePosition((_reference, _panel, _options) =>
		Promise.resolve({ placement: "bottom-end", x: 25, y: 30 }),
	);
	env.autoUpdateCalls[1].callback();
	await Promise.resolve();
	env.autoUpdateCalls[1].callback();
	await Promise.resolve();
	assert.equal(
		env.computePositionCalls.at(-1).options.placement,
		"bottom-start",
		"A flip replaced the preferred placement on a later update",
	);
});

/**
 * @pair combobox:teardown
 * @style dropdown.panel
 */
test("test_combobox_positioning_stops_after_destroy", async (t) => {
	const env = await setupFloating(t);
	const { parent } = makeComboboxElements();
	const combobox = new env.Combobox(parent);
	const input = document.createElement("input");
	input.classList.add("w-full");
	t.mock.method(input, "getBoundingClientRect", () => ({ width: 123.6 }));
	combobox.element = input;
	combobox.panel = document.createElement("div");
	await combobox._startAutoUpdate();
	const call = env.autoUpdateCalls[0];
	const panel = call.panel;
	const positioned = panel.getAttribute("style");

	combobox.destroy();
	call.callback();
	await Promise.resolve();
	assert.equal(call.cleaned, true);
	assert.equal(combobox.panel, null);
	assert.equal(
		panel.getAttribute("style"),
		positioned,
		"Canceled positioning mutated the detached panel",
	);
});

/**
 * @matrix combobox : positioning-readiness readiness
 * @style dropdown.panel
 */
test("test_combobox_exposes_initial_positioning_readiness", async (t) => {
	const env = await setupFloating(t);
	const { initial, parent } = makeComboboxElements();
	const combobox = new env.Combobox(parent);
	combobox.init();
	combobox._createPanel();
	combobox.panel.appendChild(option(0, "first-option"));
	combobox.options = [{ id: "first" }];
	let resolvePosition;
	env.setComputePosition(
		(_reference, _panel, options) =>
			new Promise((resolve) => {
				resolvePosition = () =>
					resolve({ placement: options.placement, x: 35, y: 47 });
			}),
	);

	const ready = combobox.showPanel();
	assert.equal(combobox.panelOpen, true);
	assert.equal(initial.getAttribute("aria-expanded"), "true");
	assert.equal(combobox.panel.dataset.positioned, "false");
	assert.equal(combobox._documentHandlersAdded, true);
	resolvePosition();
	assert.equal(await ready, true);
	assert.equal(combobox.panel.dataset.positioned, "true");
	assert.equal(combobox.panel.style.left, "35px");
	assert.equal(combobox.panel.style.top, "47px");
});

/**
 * @matrix combobox : positioning-readiness transition-race
 * @style dropdown.panel
 */
test("test_combobox_initial_position_ignores_superseded_transition_geometry", async (t) => {
	const env = await setupFloating(t);
	const { parent } = makeComboboxElements();
	const combobox = new env.Combobox(parent);
	combobox.init();
	combobox._createPanel();
	combobox.panel.appendChild(option(0, "first-option"));
	combobox.options = [{ id: "first" }];
	const positions = [];
	env.setComputePosition(
		(_reference, _panel, options) =>
			new Promise((resolve) => {
				positions.push((x, y) =>
					resolve({ placement: options.placement, x, y }),
				);
			}),
	);

	const ready = combobox.showPanel();
	env.autoUpdateCalls[0].callback();
	assert.equal(positions.length, 2);
	positions[1](35, 47);
	assert.equal(await ready, true);
	positions[0](900, 901);
	await Promise.resolve();
	assert.equal(combobox.panel.style.left, "35px");
	assert.equal(combobox.panel.style.top, "47px");
});

/**
 * @matrix combobox : aria keyboard
 * @style dropdown.panel
 */
test("test_combobox_aria_and_keyboard_state_follow_the_open_panel", async (t) => {
	const env = await setupFloating(t);
	const { initial, parent } = makeComboboxElements();
	const combobox = new env.Combobox(parent);
	combobox.init();
	combobox._createPanel();
	assert.equal(initial.getAttribute("role"), "combobox");
	assert.equal(initial.getAttribute("aria-expanded"), "false");
	assert.equal(initial.getAttribute("aria-haspopup"), "listbox");
	assert.equal(initial.getAttribute("aria-controls"), combobox.panel.id);
	assert.equal(combobox.panel.getAttribute("role"), "listbox");
	assert.equal(combobox.panel.getAttribute("aria-labelledby"), initial.id);

	const first = option(0, "first-option");
	const second = option(1, "second-option");
	combobox.panel.append(first, second);
	combobox.options = [{ id: "first" }, { id: "second" }];
	t.mock.method(combobox, "_startAutoUpdate", () => Promise.resolve(true));
	await combobox.showPanel();
	assert.equal(initial.getAttribute("aria-expanded"), "true");

	const down = interactionEvent({ key: "ArrowDown" });
	combobox.elementKeydown(down);
	assert.equal(down.defaultPrevented, true);
	assert.equal(down.propagationStopped, true);
	assert.equal(combobox.focusedIndex, 0);
	assert.equal(initial.getAttribute("aria-activedescendant"), first.id);
	assert.equal(first.getAttribute("aria-selected"), "true");

	const up = interactionEvent({ key: "ArrowUp" });
	combobox.elementKeydown(up);
	assert.equal(combobox.focusedIndex, 1);
	assert.equal(initial.getAttribute("aria-activedescendant"), second.id);
	assert.equal(first.getAttribute("aria-selected"), "false");
	let selected = null;
	combobox.selectOption = (selectedOption) => {
		selected = selectedOption;
	};
	const enter = interactionEvent({ key: "Enter" });
	combobox.elementKeydown(enter);
	assert.equal(selected, second);
	assert.equal(enter.defaultPrevented, true);
	assert.equal(enter.propagationStopped, true);

	combobox.elementKeydown(interactionEvent({ key: "Tab" }));
	assert.equal(combobox.panelOpen, false);
	assert.equal(initial.getAttribute("aria-expanded"), "false");
	assert.equal(initial.getAttribute("aria-activedescendant"), null);
});

/**
 * @matrix combobox : dismissal pointer
 * @style dropdown.panel
 */
test("test_combobox_pointer_and_dismissal_events_preserve_trigger_focus", async (t) => {
	const env = await setupFloating(t);
	const { initial, parent } = makeComboboxElements();
	const combobox = new env.Combobox(parent);
	combobox.init();
	combobox._createPanel();
	const first = option(0, "first-option");
	const child = document.createElement("span");
	first.appendChild(child);
	combobox.panel.appendChild(first);
	combobox.options = [{ id: "first" }];
	combobox.panelOpen = true;
	const added = [];
	const addEventListener = combobox.panel.addEventListener.bind(combobox.panel);
	t.mock.method(
		combobox.panel,
		"addEventListener",
		(type, handler, options) => {
			added.push(type);
			return addEventListener(type, handler, options);
		},
	);
	combobox._addPanelHandlers();
	assert.equal(added.includes("pointermove"), true);
	assert.equal(added.includes("pointerover"), false);

	combobox._panelPointerMove(interactionEvent({ target: child }));
	assert.equal(combobox.focusedIndex, 0);
	assert.equal(initial.getAttribute("aria-activedescendant"), first.id);
	const pointerDown = interactionEvent({ target: child });
	combobox._panelPointerDown(pointerDown);
	assert.equal(pointerDown.defaultPrevented, true);
	let selected = null;
	combobox.selectOption = (selectedOption) => {
		selected = selectedOption;
	};
	const click = interactionEvent({ target: child });
	combobox._optionClick(click);
	assert.equal(selected, first);
	assert.equal(click.propagationStopped, true);

	let deactivated = 0;
	initial.addEventListener("deactivate", () => {
		deactivated += 1;
	});
	combobox._documentClick({ target: document.createElement("aside") });
	assert.equal(combobox.panelOpen, false);
	assert.equal(deactivated, 1);
	combobox.panelOpen = true;
	combobox._documentKeydown({ key: "Escape" });
	assert.equal(combobox.panelOpen, false);
	assert.equal(deactivated, 2);
});

/**
 * @pair combobox:empty-results
 * @style dropdown.panel
 */
test("test_combobox_hides_empty_recent_panel_but_keeps_server_empty_result_row", async (t) => {
	const env = await setupFloating(t);
	const { parent } = makeComboboxElements();
	const combobox = new env.Combobox(parent);
	combobox.init();
	combobox._createPanel();
	t.mock.method(combobox, "_startAutoUpdate", () => Promise.resolve(true));
	combobox.panelOpen = true;
	combobox.panel.classList.remove("hidden");
	combobox.panel.dataset.visible = "true";
	combobox.updatePanel("   ");
	combobox.options = [{ id: "selected-but-not-rendered" }];
	await combobox.showPanel();
	assert.equal(combobox.panelOpen, false);
	assert.equal(combobox.panel.classList.contains("hidden"), true);
	assert.equal(combobox.panel.dataset.visible, "false");
	assert.equal(combobox.element.getAttribute("aria-expanded"), "false");

	combobox.updatePanel('<div role="option">No Results</div>');
	await combobox.showPanel();
	assert.equal(combobox.panelOpen, true);
	assert.equal(combobox.panel.classList.contains("hidden"), false);
	assert.equal(combobox.options.length, 1);
});

/**
 * @pair combobox:dataset-configuration
 * @style dropdown.panel
 */
test("test_combobox_copies_only_supported_dataset_configuration", async (t) => {
	const env = await setupFloating(t);
	const { initial, parent } = makeComboboxElements();
	Object.assign(parent.dataset, {
		kind: "user",
		preload: '[{"id":"existing-user"}]',
		placeholder: "parent placeholder",
	});
	Object.assign(initial.dataset, {
		placeholder: "choose a user...",
		multiple: "true",
		creatable: "true",
		formType: "task",
		includeUsers: "false",
		permission: "assign",
		panel: "closed",
		values: "true",
		options: "corrupted-options",
		element: "corrupted-element",
		hidePanel: "corrupted-method",
		mobile: "corrupted-mobile-state",
		unrelated: "unrelated-value",
	});
	const combobox = new env.Combobox(parent);
	assert.deepEqual(
		{
			index: combobox.index,
			kind: combobox.kind,
			placeholder: combobox.placeholder,
			preload: combobox.preload,
			multiple: combobox.multiple,
			creatable: combobox.creatable,
			formType: combobox.formType,
			includeUsers: combobox.includeUsers,
			permission: combobox.permission,
		},
		{
			index: "people",
			kind: "user",
			placeholder: "choose a user...",
			preload: '[{"id":"existing-user"}]',
			multiple: true,
			creatable: "true",
			formType: "task",
			includeUsers: "false",
			permission: "assign",
		},
	);
	assert.equal(combobox.element, initial);
	assert.equal(combobox.panel, null);
	assert.equal(Array.isArray(combobox.options), true);
	assert.equal(typeof combobox.values.add, "function");
	assert.equal(typeof combobox.values.has, "function");
	assert.equal(typeof combobox.hidePanel, "function");
	assert.equal(typeof combobox.mobile, "boolean");
	assert.equal("unrelated" in combobox, false);
	combobox.init();
	combobox.updatePanel("");
	assert.equal(combobox.panel instanceof HTMLElement, true);
	assert.equal(combobox.panelOpen, false);
	assert.equal(combobox.panel.classList.contains("hidden"), true);
	assert.equal(combobox.element.dataset.panel, "closed");
	combobox.destroy();

	const single = makeComboboxElements();
	single.initial.dataset.multiple = "false";
	assert.equal(new env.Combobox(single.parent).multiple, false);
});

/** @pair combobox:clear-notification */
test("test_submitter_clear_can_suppress_change_notification", async (t) => {
	const env = await setupFloating(t);
	const { parent } = makeComboboxElements();
	const SubmitterCombobox = Submitter(env.Combobox);
	const combobox = new SubmitterCombobox(parent);
	const updateModes = [];
	t.mock.method(combobox, "hidePanel", () => {});
	t.mock.method(combobox, "updateSelect", (preloading) =>
		updateModes.push(preloading),
	);
	combobox.values.add("group-key");
	combobox.clear({ notify: false });
	assert.equal(combobox.values.size, 0);
	assert.equal(updateModes[0], true);
	combobox.values.add("second-group-key");
	combobox.clear();
	assert.equal(combobox.values.size, 0);
	assert.equal(updateModes[1], false);
});

/**
 * @matrix dropdown : callback-index dynamic-options mixed-options rerender
 * @style dropdown.panel
 */
test("test_dynamic_dropdown_rerenders_each_open_and_keeps_mixed_option_indexes", async (t) => {
	const env = await setupFloating(t);
	const trigger = document.createElement("button");
	document.body.appendChild(trigger);
	let load = 0;
	const dropdown = new env.Dropdown(trigger).init({
		loadOptions: async () => {
			load += 1;
			return [{ name: `Version ${load}` }];
		},
	});
	dropdown.panel = document.createElement("div");
	t.mock.method(dropdown, "_startAutoUpdate", () => Promise.resolve(true));
	const rendered = [];
	const renderOptions = dropdown._renderOptions;
	t.mock.method(dropdown, "_renderOptions", function (...args) {
		rendered.push(this.items.map((item) => item.name));
		return renderOptions.call(this, ...args);
	});
	await dropdown.showPanel();
	await dropdown.showPanel();
	assert.equal(load, 2);
	assert.deepEqual(rendered, [["Version 1"], ["Version 2"]]);

	const selected = [];
	const mixedTrigger = document.createElement("button");
	document.body.appendChild(mixedTrigger);
	const mixed = new env.Dropdown(mixedTrigger);
	mixed.items = [
		{
			html: '<button role="option">Custom</button>',
			onClick: () => selected.push("custom"),
		},
		{ name: "Standard", onClick: () => selected.push("standard") },
	];
	mixed.panel = document.createElement("div");
	mixed._renderOptions();
	assert.match(mixed.panel.textContent, /Custom/);
	assert.match(mixed.panel.textContent, /Standard/);
	mixed.selectOption(mixed.panel.querySelector('[data-index="1"]'));
	assert.deepEqual(selected, ["standard"]);
});

/**
 * @matrix entity-menu : readiness state-linking title-menu title-positioning
 * @style dropdown.menu
 */
test("test_entity_title_menu_anchors_to_the_title_bottom_left", async (t) => {
	installBrowserBoundaries(t, {
		html: `
			<section data-menu-anchor>
				<h2 data-role="title">Title</h2>
				<div data-key="entity-key">
					<div id="menu-container">
						<button data-role="menu-trigger">Menu</button>
						<div data-role="menu-items">
							<button data-menu-item>Delete</button>
						</div>
					</div>
				</div>
			</section>
		`,
	});
	let configuredMenu = null;
	let dropdown = null;
	class FakeDropdown {
		constructor(element) {
			this.element = element;
			dropdown = this;
		}

		init(menu) {
			configuredMenu = menu;
			return this;
		}

		showPanel() {
			return Promise.resolve(true);
		}

		destroy() {
			this.destroyed = true;
		}
	}
	const { EntityMenu } = await esmock.strict(
		"../../src/script/elements/entityMenu.mjs",
		{
			"../../src/script/elements/combobox/dropdown.mjs": {
				Dropdown: FakeDropdown,
			},
		},
	);
	const container = document.querySelector("#menu-container");
	const title = document.querySelector("[data-role='title']");
	const menu = new EntityMenu({});
	assert.equal(await menu.toggle(container), true);
	assert.ok(configuredMenu);
	assert.equal(configuredMenu.positionReference, title);
	assert.equal(configuredMenu.placement, "bottom-start");
	assert.equal(configuredMenu.matchReferenceWidth, true);
	assert.equal(configuredMenu.popupRole, "menu");
	assert.equal(configuredMenu.optionRole, "menuitem");
	assert.equal(configuredMenu.triggerRole, null);
	assert.match(configuredMenu.items[0].html, /data-entity-key="entity-key"/);
	const firstHtml = configuredMenu.items[0].html;
	const refreshedItems = await configuredMenu.loadOptions();
	assert.equal(refreshedItems.length, 1);
	assert.equal(refreshedItems[0].html, firstHtml);
	assert.equal(dropdown.element.isConnected, true);
});
