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

/** @pairs manual:responsive-navigation startup:mobile-only-dropdown */
test("test_manual_dropdown_loads_only_in_mobile_mode", async (t) => {
	let mobileMode = false;
	const window = {
		addEventListener() {},
		removeEventListener() {},
	};
	replaceGlobal(t, "window", window);
	class ShellView {
		constructor(element) {
			this.elt = element;
			this.mobile = mobileMode;
			this._destroyed = false;
		}
		async init() {}
		destroy() {
			this._destroyed = true;
		}
	}
	const { default: Manual } = await esmock.strict(
		"../../src/script/views/manual.mjs",
		{
			"../../src/script/shared/endpoints.mjs": { ENDPOINTS: { manual: {} } },
			"../../src/script/shared/request.mjs": { request: {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
			"../../src/script/views/base/shell.mjs": { default: ShellView },
		},
	);
	const createRoot = () => {
		const listeners = new Map();
		return {
			listeners,
			addEventListener(type, listener) {
				listeners.set(type, listener);
			},
			querySelector: () => null,
			removeEventListener(type) {
				listeners.delete(type);
			},
		};
	};
	const desktopRoot = createRoot();
	const desktop = new Manual(desktopRoot);
	let desktopLoads = 0;
	desktop._ensureMobileDropdown = async () => {
		desktopLoads += 1;
	};
	await desktop.init();
	assert.equal(desktopLoads, 0);
	desktop.mobile = true;
	desktopRoot.listeners.get("mobile-resize")();
	assert.equal(desktopLoads, 1);
	desktop.destroy();

	mobileMode = true;
	const mobile = new Manual(createRoot());
	let mobileLoads = 0;
	mobile._ensureMobileDropdown = async () => {
		mobileLoads += 1;
	};
	await mobile.init();
	assert.equal(mobileLoads, 1);
});

/** @matrix manual admin : clipboard-fallback command-copy */
test("test_command_copy_falls_back_when_clipboard_is_unavailable", async (t) => {
	let copied = null;
	let textarea = null;
	const document = {
		body: {
			append(node) {
				textarea = node;
			},
		},
		createElement: () => ({
			remove() {
				this.removed = true;
			},
			select() {
				this.selected = true;
			},
			setAttribute() {},
			style: {},
			value: "",
		}),
		execCommand(command) {
			copied = command;
			return true;
		},
	};
	const navigator = {
		clipboard: {
			async writeText() {
				throw new Error("denied");
			},
		},
	};
	replaceGlobal(t, "document", document);
	replaceGlobal(t, "navigator", navigator);
	const { default: ShellView } = await esmock.strict(
		"../../src/script/views/base/shell.mjs",
		{
			"../../src/script/shared/connectivity.mjs": {
				connectivity: { online: true, hidden: false },
			},
		},
	);
	const shell = {
		querySelector: () => ({ textContent: "gcloud auth login" }),
	};
	const attributes = new Map();
	const button = {
		closest: () => shell,
		focus() {
			this.focused = true;
		},
		isConnected: true,
		setAttribute(name, value) {
			attributes.set(name, value);
		},
		textContent: "Copy",
	};
	const view = Object.create(ShellView.prototype);
	view.copyResetTimers = new Map();
	await view.copyCommand(button);
	assert.equal(copied, "copy");
	assert.equal(textarea?.value, "gcloud auth login");
	assert.equal(textarea.selected, true);
	assert.equal(textarea.removed, true);
	assert.equal(button.focused, true);
	assert.equal(button.textContent, "Copied!");
	assert.equal(attributes.get("aria-label"), "Command copied");
});

/** @matrix table-controls : eager-column-state lazy-checkbox-panel persistence */
test("test_column_visibility_state_applies_before_lazy_panel", async (t) => {
	const storage = new Map([["columns-tasks", "[2]"]]);
	let toggleListener = null;
	const unrelatedStyle = {};
	class CSSStyleSheet {
		replaceSync(css) {
			this.textContent = css;
		}
	}
	const document = { adoptedStyleSheets: [unrelatedStyle] };
	const localStorage = {
		getItem: (key) => storage.get(key) || null,
		setItem: (key, value) => storage.set(key, value),
	};
	for (const [name, value] of Object.entries({
		CSSStyleSheet,
		document,
		localStorage,
	}))
		replaceGlobal(t, name, value);
	const { TableVisibilityState } = await import(
		"../../src/script/widgets/tables/visibilityState.mjs"
	);
	const headers = ["name", "status", "owner"].map((column) => ({
		dataset: { column },
	}));
	const component = {
		elt: { id: "table", querySelectorAll: () => headers },
		widgets: {},
	};
	const view = {
		hash: "tasks",
		elt: {
			addEventListener(_type, listener) {
				toggleListener = listener;
			},
			removeEventListener() {
				toggleListener = null;
			},
		},
	};
	const state = new TableVisibilityState({
		component,
		view,
		selected: [],
		columns: headers.map(({ dataset }) => ({
			field: dataset.column,
			selected: true,
		})),
	}).init();
	const stylesheet = document.adoptedStyleSheets[1];
	assert.equal(stylesheet.textContent.includes("nth-child(2)"), true);
	assert.deepEqual(state.visibleColumns, ["name", "owner"]);
	toggleListener({ detail: { active: true, column: "status" } });
	assert.equal(stylesheet.textContent, "");
	assert.equal(storage.get("columns-tasks"), "[]");
	state.destroy();
	assert.deepEqual(document.adoptedStyleSheets, [unrelatedStyle]);
	assert.equal(toggleListener, null);
});

/** @matrix pages : photo-lazy-activation photo-visible-startup */
test("test_page_photo_initializes_only_when_selected_or_visible", async (t) => {
	const storage = new Map();
	const localStorage = {
		getItem: (key) => storage.get(key) || null,
		setItem: (key, value) => storage.set(key, value),
	};
	const window = { location: { pathname: "/pages/page-1", search: "" } };
	replaceGlobal(t, "localStorage", localStorage);
	replaceGlobal(t, "window", window);
	class Entity {
		constructor(element) {
			this.elt = element;
			this.hash = "page";
			this.key = "page-1";
		}
		async init() {}
		getComponent() {
			return this.component;
		}
		isSecondaryCardVisible() {
			return this.photoVisible;
		}
	}
	const { default: Page } = await esmock.strict(
		"../../src/script/views/page.mjs",
		{
			"../../src/script/shared/icons.mjs": { setIcon() {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
			"../../src/script/views/base/entity.mjs": { default: Entity },
		},
	);
	const photo = {};
	const createPage = ({ active = null, visible = false } = {}) => {
		const page = new Page({
			dataset: {},
			addEventListener() {},
			querySelector: (selector) => (selector === "#photo" ? photo : null),
		});
		let activations = 0;
		page.component = {
			active,
			async activate(name) {
				assert.equal(name, "PagePhoto");
				activations += 1;
			},
		};
		page.photoVisible = visible;
		return { page, activations: () => activations };
	};
	const hidden = createPage();
	await hidden.page.init();
	assert.equal(hidden.activations(), 0);
	const visible = createPage({ visible: true });
	await visible.page.init();
	assert.equal(visible.activations(), 1);
	const selected = createPage({ active: { name: "PagePhoto" } });
	await selected.page.init();
	assert.equal(selected.activations(), 0);
});

/** @matrix ai-report : concurrent-form-init lazy-form-runtime */
test("test_report_loads_base_form_only_for_present_forms_and_in_parallel", async (t) => {
	const events = [];
	const pending = new Map();
	class FakeBaseForm {
		constructor({ target }) {
			this.target = target;
		}
		init() {
			events.push(`start:${this.target.dataset.role}`);
			return new Promise((resolve) =>
				pending.set(this.target.dataset.role, resolve),
			);
		}
	}
	class Core {
		constructor(element) {
			this.elt = element;
		}
		async init() {}
	}
	const window = { addEventListener() {} };
	replaceGlobal(t, "window", window);
	const { default: Report } = await esmock.strict.p(
		"../../src/script/views/report.mjs",
		{
			"../../src/script/shared/icons.mjs": {
				createIcon() {},
				setIcon() {},
			},
			"../../src/script/shared/request.mjs": { request: {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
			"../../src/script/views/base/core.mjs": { default: Core },
			"../../src/script/forms/controller.mjs": {
				FormController: FakeBaseForm,
			},
		},
	);
	const createTarget = (role) => ({
		dataset: { role },
		addEventListener() {},
	});
	const targets = {
		run: createTarget("run-report-form"),
		revise: createTarget("revise-report-form"),
	};
	const formsRoot = {
		addEventListener() {},
		querySelector(selector) {
			if (selector.includes(",")) return targets.run;
			if (selector.includes("run-report-form")) return targets.run;
			if (selector.includes("revise-report-form")) return targets.revise;
			return null;
		},
		removeEventListener() {},
	};
	const empty = new Report({
		addEventListener() {},
		querySelector: () => null,
		removeEventListener() {},
	});
	await empty.init();
	assert.equal(events.length, 0);
	const report = new Report(formsRoot);
	const initializing = report.init();
	for (let index = 0; index < 4; index += 1) await Promise.resolve();
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(events.length, 2);
	assert.deepEqual(
		new Set(events),
		new Set(["start:run-report-form", "start:revise-report-form"]),
	);
	for (const resolve of pending.values()) resolve();
	await initializing;
});
