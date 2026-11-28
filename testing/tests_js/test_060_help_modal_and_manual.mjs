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

function parseDocument(markup) {
	return new DOMParser().parseFromString(markup, "text/html");
}

test("test_modal_marks_page_landmarks_inert_and_restores_before_focus", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/",
		html: `
			<nav class="main-nav"><a id="nav-link" href="/home">Home</a></nav>
			<section data-role="upstream-unavailable" data-visible="false"></section>
			<main><button id="help-btn" type="button">Help</button></main>
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

	const nav = document.querySelector("nav.main-nav");
	const upstream = document.querySelector(
		"section[data-role='upstream-unavailable']",
	);
	const main = document.querySelector("main");
	const trigger = document.querySelector("#help-btn");
	trigger.focus();

	const dialogOne = document.createElement("div");
	dialogOne.id = "modal";
	dialogOne.innerHTML =
		'<div id="modal-content" role="dialog"><button data-role="help-modal-back" hidden>Back</button><button id="close-one" lp-control="close">Close</button></div>';

	const modalOne = new Modal({}, trigger);
	await modalOne.attach(dialogOne);
	for (const landmark of [nav, upstream, main]) {
		assert.equal(landmark.inert, true);
		assert.equal(landmark.hasAttribute("inert"), true);
	}
	assert.equal(document.activeElement, dialogOne.querySelector("#close-one"));

	// Tabbing wraps among visible focusable controls and skips hidden Back button.
	const tabEvent = new KeyboardEvent("keydown", {
		key: "Tab",
		bubbles: true,
		cancelable: true,
	});
	document.dispatchEvent(tabEvent);
	assert.equal(document.activeElement, dialogOne.querySelector("#close-one"));

	const dialogTwo = document.createElement("div");
	dialogTwo.id = "modal";
	dialogTwo.innerHTML =
		'<div id="modal-content" role="dialog"><button id="close-two">OK</button></div>';
	const modalTwo = new Modal({}, dialogOne.querySelector("#close-one"));
	await modalTwo.attach(dialogTwo);
	for (const landmark of [nav, upstream, main]) {
		assert.equal(landmark.inert, true);
	}

	await modalTwo.remove();
	for (const landmark of [nav, upstream, main]) {
		assert.equal(landmark.inert, true);
	}

	await modalOne.remove();
	for (const landmark of [nav, upstream, main]) {
		assert.equal(landmark.inert, false);
		assert.equal(landmark.hasAttribute("inert"), false);
	}
	assert.equal(document.activeElement, trigger);
});

test("test_help_modal_navigates_topic_links_in_place_and_supports_back", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/analytics/",
		html: '<main><button id="help-trigger" lp-control="help" lp-help="analytics">?</button></main>',
	});

	const modalMarkup = (topicId, title, extraLinks = "") =>
		parseDocument(`
			<div id="modal">
				<div id="modal-content" role="dialog" aria-modal="true" aria-labelledby="modal-title">
					<div>
						<button type="button" data-role="help-modal-back" hidden>Back</button>
						<h2 id="modal-title">${title}</h2>
						<button type="button" lp-control="close">Close</button>
					</div>
					<div data-role="help-modal-body">
						<div data-role="help-body" data-topic="${topicId}">${extraLinks}</div>
						<a href="/help/" data-help-index>All help topics</a>
						<a href="/manual/">User manual</a>
					</div>
				</div>
			</div>
		`);

	const calls = [];
	const { HelpModal } = await esmock.strict(
		"../../src/script/shared/modal.ts",
		{
			"../../src/script/generated/styles.mjs": {
				STYLES: {
					modal: { wrapper: "", content: "", header: "" },
					button: { close: "" },
				},
			},
			"../../src/script/shared/endpoints.ts": {
				ENDPOINTS: {
					delete: () => "",
					help: (section) => `/reference/section/${section}`,
				},
			},
			"../../src/script/shared/errors.ts": {
				captureError: (error) => {
					throw error;
				},
			},
			"../../src/script/shared/request.ts": {
				request: {
					get: async (route) => {
						calls.push(route);
						if (route === "/reference/section/analytics") {
							return {
								html: modalMarkup(
									"analytics",
									"Analytics & AI Observability",
									'<a id="next-topic" href="/help/external_ai">External AI Connections</a>',
								),
							};
						}
						if (route === "/reference/section/external_ai") {
							return {
								html: modalMarkup(
									"external_ai",
									"External AI Connections",
									"<p>Remote MCP details</p>",
								),
							};
						}
						throw new Error(`Unexpected route: ${route}`);
					},
				},
			},
			"../../src/script/shared/transitions.ts": {
				withTransition: async (callback) => {
					callback();
					return true;
				},
			},
		},
	);

	const trigger = document.querySelector("#help-trigger");
	const modal = new HelpModal({}, trigger);
	await modal.init();

	assert.deepEqual(calls, ["/reference/section/analytics"]);
	assert.equal(
		document.querySelector("#modal-title").textContent,
		"Analytics & AI Observability",
	);
	const backButton = document.querySelector("[data-role='help-modal-back']");
	assert.equal(backButton.hidden, true);

	const currentWindow = window;
	const unintercepted = [];
	const preventRealNav = (event) => {
		if (!event.defaultPrevented && event.target?.closest?.("a")) {
			unintercepted.push(event.target.closest("a").getAttribute("href"));
			event.preventDefault();
		}
	};
	currentWindow.addEventListener("click", preventRealNav);
	t.after(() => currentWindow.removeEventListener("click", preventRealNav));

	// Modified clicks must not hijack the link into in-place modal navigation.
	const topicLink = document.querySelector("#next-topic");
	topicLink.dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true }),
	);
	assert.deepEqual(unintercepted, ["/help/external_ai"]);
	assert.deepEqual(calls, ["/reference/section/analytics"]);

	// Unmodified left-click loads the linked topic inside the existing modal.
	const linkClick = new MouseEvent("click", {
		bubbles: true,
		cancelable: true,
		button: 0,
	});
	topicLink.dispatchEvent(linkClick);
	assert.equal(linkClick.defaultPrevented, true);
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert.deepEqual(calls, [
		"/reference/section/analytics",
		"/reference/section/external_ai",
	]);
	assert.equal(
		document.querySelector("#modal-title").textContent,
		"External AI Connections",
	);
	assert.equal(backButton.hidden, false);
	assert.equal(document.activeElement, backButton);
	assert.ok(document.querySelector("[data-topic='external_ai']"));

	// Index and manual links should remain standard navigation links.
	document
		.querySelector("[data-help-index]")
		.dispatchEvent(
			new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }),
		);
	document
		.querySelector("a[href='/manual/']")
		.dispatchEvent(
			new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }),
		);
	assert.deepEqual(unintercepted, ["/help/external_ai", "/help/", "/manual/"]);
	assert.deepEqual(calls, [
		"/reference/section/analytics",
		"/reference/section/external_ai",
	]);

	// Back returns to the prior topic and hides Back once the stack is empty.
	const backClick = new MouseEvent("click", {
		bubbles: true,
		cancelable: true,
		button: 0,
	});
	backButton.dispatchEvent(backClick);
	assert.equal(backClick.defaultPrevented, true);
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert.deepEqual(calls, [
		"/reference/section/analytics",
		"/reference/section/external_ai",
		"/reference/section/analytics",
	]);
	assert.equal(
		document.querySelector("#modal-title").textContent,
		"Analytics & AI Observability",
	);
	assert.equal(backButton.hidden, true);
	assert.equal(
		document.activeElement,
		document.querySelector("[lp-control='close']"),
	);

	await modal.remove();
});

test("test_manual_mobile_dropdown_marks_active_and_restores_from_popstate", async (t) => {
	const sections = [
		{
			key: "overview",
			name: "Overview",
			icon: "manual",
			kind: "page",
			metadata: {
				title: "Overview — Manual",
				description: "Overview",
				robots: "index, follow",
				canonical_url: "https://lagniappe.test/manual/",
				path: "/manual/",
			},
		},
		{
			key: "quickstart",
			name: "Quickstart",
			icon: "launch",
			kind: "page",
			metadata: {
				title: "Quickstart — Manual",
				description: "Quickstart",
				robots: "index, follow",
				canonical_url: "https://lagniappe.test/manual/quickstart",
				path: "/manual/quickstart",
			},
		},
		{
			key: "ai",
			name: "AI Integration",
			icon: "generate",
			kind: "form",
			metadata: {
				title: "AI Integration — Manual",
				description: "AI",
				robots: "index, follow",
				canonical_url: "https://lagniappe.test/manual/ai",
				path: "/manual/ai",
			},
		},
	];
	createBrowser(t, {
		url: "https://lagniappe.test/manual/quickstart",
		html: `
			<div id="manual-page">
				<button id="manual-nav-button" type="button">
					<span data-role="manual-nav-label">Quickstart</span>
				</button>
				<button type="button" data-section="overview" data-active="false">Overview</button>
				<button type="button" data-section="quickstart" data-active="true">Quickstart</button>
				<button type="button" data-section="ai" data-active="false">AI Integration</button>
				<div data-role="manual-content"><h1>Quickstart</h1></div>
			</div>
		`,
	});
	document.querySelector("#manual-nav-button").dataset.sections =
		JSON.stringify(sections);

	replace(t, window, "matchMedia", () => ({
		matches: true,
		addEventListener() {},
		removeEventListener() {},
	}));
	replace(t, window, "scrollTo", () => {});
	const pushed = [];
	replace(t, globalThis, "history", {
		pushState(state, _title, url) {
			pushed.push({ state, url });
		},
	});

	let capturedMenu = null;
	class FakeDropdown {
		init(menu) {
			capturedMenu = menu;
			return this;
		}
		destroy() {}
	}

	const fetched = [];
	const manualModule = await esmock.strict.p(
		"../../src/script/views/manual.ts",
		{
			"../../src/script/elements/combobox/dropdown.ts": {
				Dropdown: FakeDropdown,
			},
			"../../src/script/generated/styles.mjs": {
				STYLES: { manual: { mobilePanel: "mobile-panel-style" } },
			},
			"../../src/script/shared/connectivity.ts": {
				connectivity: { online: true, hidden: false },
			},
			"../../src/script/shared/endpoints.ts": {
				ENDPOINTS: { manual: { section: (key) => `/manual/section/${key}` } },
			},
			"../../src/script/shared/request.ts": {
				request: {
					get: async (route) => {
						fetched.push(route);
						return { html: parseDocument(`<p>${route}</p>`) };
					},
				},
			},
			"../../src/script/shared/transitions.ts": {
				withTransition: async (callback) => {
					callback();
					return true;
				},
			},
		},
	);
	t.after(() => esmock.purge(manualModule));
	const { default: Manual } = manualModule;

	const root = document.querySelector("#manual-page");
	const view = new Manual(root);
	await view.init();

	assert.equal(view.activeSection, "quickstart");
	assert.equal(capturedMenu?.styles?.panel, "mobile-panel-style");
	assert.deepEqual(
		capturedMenu.loadOptions().map((item) => [item.name, item.active]),
		[
			["Overview", false],
			["Quickstart", true],
			["AI Integration", false],
		],
	);

	await view.fetchSection("ai", true);
	assert.equal(view.activeSection, "ai");
	assert.equal(
		root.querySelector("[data-role='manual-nav-label']").textContent,
		"AI Integration",
	);
	assert.equal(pushed[0].url, "/manual/ai");
	assert.deepEqual(
		capturedMenu.loadOptions().map((item) => [item.name, item.active]),
		[
			["Overview", false],
			["Quickstart", false],
			["AI Integration", true],
		],
	);

	// Popstate without state falls back cleanly to the current URL pathname.
	window.dispatchEvent(new window.PopStateEvent("popstate", { state: null }));
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert.deepEqual(fetched, [
		"/manual/section/ai",
		"/manual/section/quickstart",
	]);
	assert.equal(view.activeSection, "quickstart");
	assert.equal(
		root.querySelector("[data-role='manual-nav-label']").textContent,
		"Quickstart",
	);
	view.destroy();
});

test("test_shell_view_routes_help_button_click_to_help_modal", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/analytics/",
		html: '<div id="view"><button id="help-btn" type="button" lp-control="help" lp-help="analytics">?</button></div>',
	});

	replace(t, window, "matchMedia", () => ({
		matches: false,
		addEventListener() {},
		removeEventListener() {},
	}));

	const inits = [];
	class FakeHelpModal {
		constructor(view, trigger) {
			this.view = view;
			this.trigger = trigger;
		}
		async init() {
			inits.push(this.trigger.getAttribute("lp-help"));
		}
	}

	const shellModule = await esmock.strict.p(
		"../../src/script/views/base/shell.ts",
		{
			"../../src/script/shared/connectivity.ts": {
				connectivity: { online: true, hidden: false },
			},
			"../../src/script/shared/modal.ts": {
				HelpModal: FakeHelpModal,
			},
		},
	);
	t.after(() => esmock.purge(shellModule));
	const { default: ShellView } = shellModule;

	const root = document.querySelector("#view");
	const view = new ShellView(root);
	await view.init();

	document
		.querySelector("#help-btn")
		.dispatchEvent(
			new MouseEvent("click", { bubbles: true, cancelable: true }),
		);
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert.deepEqual(inits, ["analytics"]);
	view.destroy();
});
