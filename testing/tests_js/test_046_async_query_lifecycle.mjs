import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { QueryLifecycle } from "../../src/script/shared/queryLifecycle.mjs";
import { BuilderDraft } from "../../src/script/views/builder/draft.mjs";
import { createBrowser } from "../utility/js/environment.mjs";

function deferred() {
	let resolve;
	const promise = new Promise((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

/** @matrix async-query : cancellation ordering repeated-key */
test("test_query_lifecycle_publishes_only_the_current_request", async () => {
	const lifecycle = new QueryLifecycle();
	const published = [];
	let live = "A";
	const firstA = deferred();
	let firstSignal;
	const first = lifecycle.run(
		"A",
		(token) => {
			firstSignal = token.signal;
			return firstA.promise;
		},
		(value) => published.push(value),
		{ getCurrentKey: () => live },
	);
	live = "B";
	const b = deferred();
	const second = lifecycle.run(
		"B",
		() => b.promise,
		(value) => published.push(value),
		{ getCurrentKey: () => live },
	);
	assert.equal(firstSignal.aborted, true);
	b.resolve("new-B");
	assert.equal(await second, true);
	firstA.resolve("old-A");
	assert.equal(await first, false);
	assert.deepEqual(published, ["new-B"]);

	live = "A";
	const oldA = deferred();
	const third = lifecycle.run(
		"A",
		() => oldA.promise,
		(value) => published.push(value),
		{ getCurrentKey: () => live },
	);
	live = "B";
	const middleB = deferred();
	const fourth = lifecycle.run(
		"B",
		() => middleB.promise,
		(value) => published.push(value),
		{ getCurrentKey: () => live },
	);
	live = "A";
	const newA = deferred();
	const fifth = lifecycle.run(
		"A",
		() => newA.promise,
		(value) => published.push(value),
		{ getCurrentKey: () => live },
	);
	oldA.resolve("repeated-old-A");
	middleB.resolve("middle-B");
	newA.resolve("repeated-new-A");
	assert.equal(await third, false);
	assert.equal(await fourth, false);
	assert.equal(await fifth, true);
	assert.deepEqual(published, ["new-B", "repeated-new-A"]);
});

/** @matrix async-query : error-propagation teardown */
test("test_query_lifecycle_invalidates_repeated_keys_and_destroyed_owners", async () => {
	let rejectLoader;
	const lifecycle = new QueryLifecycle();
	const pending = lifecycle.run(
		"active",
		() =>
			new Promise((_resolve, reject) => {
				rejectLoader = reject;
			}),
		() => {
			throw new Error("stale publisher ran");
		},
	);
	lifecycle.destroy();
	const abort = new Error("cancelled");
	abort.name = "AbortError";
	rejectLoader(abort);
	assert.equal(await pending, false);
	assert.equal(
		await lifecycle.run(
			"later",
			async () => 1,
			() => {},
		),
		false,
	);
});

/** @pair async-query:error-propagation */
test("test_query_lifecycle_propagates_current_loader_errors", async () => {
	const lifecycle = new QueryLifecycle();
	const expected = new Error("loader failed");
	await assert.rejects(
		lifecycle.run(
			"active",
			async () => {
				throw expected;
			},
			() => {},
		),
		(error) => error === expected,
	);
});

/** @matrix async-query combobox : debounce dismissal stale-publication teardown */
test("test_remote_combobox_invalidates_before_debounce_and_on_destroy", async () => {
	class ElementBoundary {
		constructor() {
			this.listeners = new Map();
			this.attributes = new Map();
			this.value = "A";
		}
		addEventListener(type, callback) {
			this.listeners.set(type, callback);
		}
		removeEventListener(type, callback) {
			if (this.listeners.get(type) === callback) this.listeners.delete(type);
		}
		setAttribute(name, value) {
			this.attributes.set(name, value);
		}
		removeAttribute(name) {
			this.attributes.delete(name);
		}
	}
	class Combobox {
		constructor(element) {
			this._destroyed = false;
			this.element = element;
			this.options = [];
			this.focusedIndex = -1;
			this.panelOpen = true;
			this.shows = 0;
		}
		init() {}
		hidePanel() {
			this.panelOpen = false;
			this.element.value = "";
		}
		showPanel() {
			this.shows += 1;
			return Promise.resolve(true);
		}
		destroy() {
			this._destroyed = true;
		}
	}
	const debounce = (callback) => {
		let pending = null;
		const delayed = (...args) => {
			pending = args;
		};
		delayed.fire = () => {
			const args = pending;
			pending = null;
			if (args) callback(...args);
		};
		delayed.cancel = () => {
			pending = null;
		};
		return delayed;
	};
	const { RemoteQueryCombobox } = await esmock.strict(
		"../../src/script/elements/combobox/remote.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureError: (error) => {
					throw error;
				},
			},
			"../../src/script/shared/queryLifecycle.mjs": { QueryLifecycle },
			"../../src/script/shared/utilities.mjs": { debounce },
			"../../src/script/elements/combobox/combobox.mjs": { Combobox },
		},
	);
	let inputs = 0;
	class TestBox extends RemoteQueryCombobox {
		_input() {
			inputs += 1;
		}
	}
	const element = new ElementBoundary();
	const box = new TestBox(element);
	box.init();
	assert.equal(element.attributes.get("aria-busy"), "false");
	let resolveRequest;
	let requestSignal;
	let publications = 0;
	const request = box.runQuery(
		"A",
		(token) => {
			requestSignal = token.signal;
			return new Promise((resolve) => {
				resolveRequest = resolve;
			});
		},
		() => {
			publications += 1;
		},
	);
	assert.equal(await box.showPanel(), false);
	assert.equal(box.shows, 0);
	assert.equal(element.attributes.get("aria-busy"), "true");
	element.value = "B";
	element.listeners.get("input")({ target: element });
	assert.equal(requestSignal.aborted, true);
	assert.equal(box.panelOpen, false);
	assert.equal(element.value, "B");
	assert.equal(inputs, 0);
	box.destroy();
	assert.equal(element.attributes.has("aria-busy"), false);
	box._debouncedInput.fire();
	assert.equal(inputs, 0);
	assert.equal(element.listeners.has("input"), false);
	resolveRequest("old-A");
	assert.equal(await request, false);
	assert.equal(publications, 0);
});

/** @matrix search : recent-results stale-publication threshold */
test("test_search_threshold_settles_stale_work_and_restores_recent_results", async () => {
	const calls = [];
	class RemoteQueryCombobox {
		constructor(element) {
			this.element = element;
			this.styles = {};
		}
		init() {}
		settleQueryInput(options = {}) {
			calls.push(["settle", options.clear === true]);
		}
		updatePanel(html) {
			calls.push(["update", html]);
		}
		showPanel() {
			calls.push(["show"]);
		}
	}
	class Results {
		create() {
			return "recent-results";
		}
	}
	const { SearchBox } = await esmock.strict(
		"../../src/script/elements/combobox/search.mjs",
		{
			"../../src/script/generated/styles.mjs": {
				STYLES: { dropdown: { panel: "panel" } },
			},
			"../../src/script/shared/endpoints.mjs": {
				ENDPOINTS: { search: { bar: "/l/search-bar", page: "/l/search-page" } },
			},
			"../../src/script/shared/request.mjs": { request: {} },
			"../../src/script/elements/combobox/remote.mjs": { RemoteQueryCombobox },
			"../../src/script/elements/combobox/results.mjs": { Results },
		},
	);
	const box = new SearchBox({ value: "" });
	box._search = (query) => calls.push(["search", query]);
	box._input({ target: { value: "a" } });
	box._input({ target: { value: "" } });
	box._input({ target: { value: "ab" } });
	assert.deepEqual(calls, [
		["settle", true],
		["settle", false],
		["update", "recent-results"],
		["show"],
		["search", "ab"],
	]);
});

/** @matrix modal : exact-owner late-publication listener-teardown reuse */
test("test_modal_owns_exact_node_and_rejects_late_attachment", async (t) => {
	createBrowser(t);
	const listeners = new Map();
	const add = document.addEventListener.bind(document);
	const remove = document.removeEventListener.bind(document);
	t.mock.method(document, "addEventListener", (type, callback, options) => {
		listeners.set(type, callback);
		add(type, callback, options);
	});
	t.mock.method(document, "removeEventListener", (type, callback, options) => {
		if (listeners.get(type) === callback) listeners.delete(type);
		remove(type, callback, options);
	});
	let resolveLoad;
	const { Modal, OfflineModal } = await esmock.strict(
		"../../src/script/shared/modal.mjs",
		{
			"../../src/script/generated/styles.mjs": {
				STYLES: {
					modal: { wrapper: "", content: "", header: "" },
					button: { close: "" },
				},
			},
			"../../src/script/shared/endpoints.mjs": {
				ENDPOINTS: { delete: () => "", help: () => "" },
			},
			"../../src/script/shared/errors.mjs": {
				captureError: (error) => {
					throw error;
				},
			},
			"../../src/script/shared/request.mjs": {
				request: {
					get: () =>
						new Promise((resolve) => {
							resolveLoad = resolve;
						}),
				},
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => {
					callback();
					return true;
				},
			},
		},
	);
	const first = document.createElement("div");
	first.id = "modal";
	const modal = new Modal({}, null);
	assert.equal(await modal.attach(first), first);
	assert.equal(modal.modal, first);
	assert.equal(listeners.size, 2);
	await modal.remove();
	assert.equal(first.isConnected, false);
	assert.equal(modal.modal, null);
	assert.equal(listeners.size, 0);
	const triggerListeners = new Set();
	const trigger = {
		addEventListener(type, callback) {
			if (type === "click") triggerListeners.add(callback);
		},
		removeEventListener(type, callback) {
			if (type === "click") triggerListeners.delete(callback);
		},
	};
	const offline = new OfflineModal({}, trigger);
	offline.enable();
	offline.enable();
	assert.equal(triggerListeners.size, 1);
	offline.disable();
	offline.disable();
	assert.equal(triggerListeners.size, 0);
	offline.enable();
	offline.destroy();
	offline.destroy();
	assert.equal(triggerListeners.size, 0);
	const late = document.createElement("div");
	late.id = "modal";
	const pending = new Modal({}, { disabled: false });
	const loading = pending.load("/late");
	pending.destroy();
	resolveLoad({ html: late });
	assert.equal(await loading, null);
	assert.equal(late.isConnected, false);
	assert.equal(pending.modal, null);
});

/** @matrix forms : builder-lifecycle late-publication listener-teardown */
test("test_builder_destroys_owned_search_modal_and_panels_during_startup", async (t) => {
	createBrowser(t, {
		html: `
			<input name="schema" value="[]">
			<div data-role="offline"></div>
			<input lp-search>
			<section id="builder" data-key="form-key" data-schema="[]"></section>
		`,
	});
	let resolveSearch;
	const searchReady = new Promise((resolve) => {
		resolveSearch = resolve;
	});
	const destroyed = [];
	const panelClass = (name) =>
		class {
			constructor() {
				this.name = name;
				this.saveButton = {
					dataset: {},
					getAttribute: () => null,
					setAttribute() {},
				};
				this.nameHidden = { value: "Form" };
			}
			init() {}
			saved() {}
			unsaved() {}
			destroy() {
				destroyed.push(name);
			}
		};
	class SearchBox {
		constructor() {
			SearchBox.instance = this;
			this.destroyed = 0;
			this._destroyed = false;
		}
		init() {
			return searchReady;
		}
		destroy() {
			if (this._destroyed) return;
			this._destroyed = true;
			this.destroyed += 1;
		}
	}
	class OfflineModal {
		constructor() {
			OfflineModal.instance = this;
			this.destroyed = 0;
		}
		enable() {}
		destroy() {
			this.destroyed += 1;
		}
	}
	class EntityMenu {
		destroy() {
			destroyed.push("entity-menu");
		}
	}
	const ComponentsPanel = panelClass("components");
	const ConditionPanel = panelClass("conditions");
	const ElementSettings = panelClass("settings");
	const FormSettings = panelClass("form-settings");
	const Header = panelClass("header");
	const ModelPanel = panelClass("model");
	const documentListeners = new Map();
	const add = document.addEventListener.bind(document);
	const remove = document.removeEventListener.bind(document);
	t.mock.method(document, "addEventListener", (type, callback, options) => {
		documentListeners.set(type, callback);
		add(type, callback, options);
	});
	t.mock.method(document, "removeEventListener", (type, callback, options) => {
		if (documentListeners.get(type) === callback)
			documentListeners.delete(type);
		remove(type, callback, options);
	});
	const { default: FormBuilder } = await esmock.strict(
		"../../src/script/views/builder/builder.mjs",
		{
			"../../src/script/elements/combobox/search.mjs": { SearchBox },
			"../../src/script/elements/entityMenu.mjs": { EntityMenu },
			"../../src/script/shared/directUpload.mjs": { directUpload: {} },
			"../../src/script/shared/index.mjs": {
				captureError: (error) => {
					throw error;
				},
				connectivity: { online: true, hidden: false },
				DeleteModal: class {},
				generateElementId: () => "generated",
				HelpModal: class {},
				OfflineModal,
				request: {},
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/views/builder/changeStatus.mjs": {
				FormChangeStatus: class {},
			},
			"../../src/script/views/builder/conditions/loader.mjs": {
				loadCondition: async () => null,
			},
			"../../src/script/views/builder/draft.mjs": { BuilderDraft },
			"../../src/script/views/builder/migrations.mjs": {
				fieldKind: () => "",
				needsMigration: () => false,
				repairConditions: () => {},
			},
			"../../src/script/views/builder/panels/components.mjs": {
				ComponentsPanel,
			},
			"../../src/script/views/builder/panels/condition.mjs": { ConditionPanel },
			"../../src/script/views/builder/panels/elementSettings.mjs": {
				ElementSettings,
			},
			"../../src/script/views/builder/panels/formSettings.mjs": {
				FormSettings,
			},
			"../../src/script/views/builder/panels/header.mjs": { Header },
			"../../src/script/views/builder/panels/model.mjs": {
				ModelElement: {},
				ModelPanel,
			},
		},
	);
	const builder = new FormBuilder(document.querySelector("#builder"));
	await builder.init();
	assert.equal(builder.SearchBox, SearchBox.instance);
	assert.equal(documentListeners.has("click"), true);
	builder.destroy();
	resolveSearch();
	await builder._searchPromise;
	assert.equal(SearchBox.instance.destroyed, 1);
	assert.equal(OfflineModal.instance.destroyed, 1);
	assert.deepEqual(
		destroyed.sort(),
		[
			"components",
			"conditions",
			"entity-menu",
			"form-settings",
			"header",
			"model",
			"settings",
		].sort(),
	);
	assert.equal(documentListeners.has("click"), false);
	assert.equal(builder.SearchBox, null);
});
