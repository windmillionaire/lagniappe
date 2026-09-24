import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

function installShellEnvironment(t, mode) {
	const marks = [];
	const windowListeners = new Map();
	const documentListeners = new Map();
	const document = {
		hidden: false,
		addEventListener(type, listener) {
			documentListeners.set(type, listener);
		},
		querySelector(selector) {
			if (selector === "meta[name='mode']") {
				return { getAttribute: () => mode };
			}
			return null;
		},
		removeEventListener(type) {
			documentListeners.delete(type);
		},
	};
	const window = {
		addEventListener(type, listener) {
			windowListeners.set(type, listener);
		},
		location: { search: "" },
		matchMedia() {
			return {
				addEventListener() {},
				matches: false,
				removeEventListener() {},
			};
		},
		removeEventListener(type) {
			windowListeners.delete(type);
		},
	};
	const performance = {
		getEntriesByName(name) {
			return marks.includes(name) ? [{}] : [];
		},
		mark(name) {
			marks.push(name);
		},
	};
	class CustomEvent {
		constructor(type, options) {
			this.type = type;
			this.detail = options?.detail;
		}
	}
	for (const [name, value] of Object.entries({
		document,
		window,
		performance,
		CustomEvent,
	}))
		replaceGlobal(t, name, value);
	return { documentListeners, marks, windowListeners };
}

async function loadShellView(connectivity = { online: true, hidden: false }) {
	const { default: ShellView } = await esmock.strict(
		"../../src/script/views/base/shell.mjs",
		{
			"../../src/script/shared/connectivity.mjs": { connectivity },
		},
	);
	return ShellView;
}

function createRoot() {
	const listeners = new Map();
	const attributes = new Map();
	return {
		attributes,
		dataset: { kind: "manual" },
		isConnected: true,
		listeners,
		addEventListener(type, listener) {
			listeners.set(type, listener);
		},
		dispatchEvent() {},
		removeEventListener(type) {
			listeners.delete(type);
		},
		setAttribute(name, value) {
			attributes.set(name, value);
		},
	};
}

function createSubmit(form, submitter) {
	return {
		defaultPrevented: false,
		submitter,
		target: form,
		preventDefault() {
			this.defaultPrevented = true;
		},
		stopPropagation() {
			this.stopped = true;
		},
	};
}

/** @matrix startup : deferred-services destroy-safety interaction-ready performance-marks single-flight */
/** @pair forms:submit-interception */
test("test_shell_intercepts_interactions_before_deferred_services", async (t) => {
	const { marks } = installShellEnvironment(t, "public");
	const ShellView = await loadShellView();
	const root = createRoot();
	const view = new ShellView(root);
	let clicks = 0;
	view._click = () => {
		clicks += 1;
	};
	let resolveManager;
	let managerLoads = 0;
	let submits = 0;
	const managerReady = new Promise((resolve) => {
		resolveManager = resolve;
	});
	view.ensureSubmissionManager = () => {
		managerLoads += 1;
		return managerReady;
	};

	await view.init();
	assert.equal(root.dataset.interactive, "true");
	root.listeners.get("click")({});
	assert.equal(clicks, 1);
	assert.deepEqual(marks, ["lagniappe:interaction-ready"]);

	const form = {
		dataset: {},
		isConnected: true,
		closest: (selector) => (selector === "[lp-component]" ? form : null),
		removeAttribute() {},
		setAttribute() {},
	};
	const submitter = {
		dataset: {},
		disabled: false,
		removeAttribute(name) {
			if (name === "aria-busy") this.busy = false;
		},
		setAttribute(name) {
			if (name === "aria-busy") this.busy = true;
		},
	};
	const first = createSubmit(form, submitter);
	const second = createSubmit(form, submitter);
	root.listeners.get("submit")(first);
	root.listeners.get("submit")(second);
	assert.equal(first.defaultPrevented, true);
	assert.equal(second.defaultPrevented, true);
	assert.equal(submitter.busy, true);
	await Promise.resolve();
	assert.equal(managerLoads, 1);
	resolveManager({
		submit() {
			submits += 1;
		},
	});
	await view._coldActions.get(form);
	assert.equal(submits, 1);
	assert.equal(submitter.busy, false);
	assert.equal(submitter.dataset.loading, undefined);

	view.publish();
	await Promise.resolve();
	assert.equal(root._lp_view, view);
	assert.equal(root.attributes.has("initialized"), true);
	assert.deepEqual(marks, [
		"lagniappe:interaction-ready",
		"lagniappe:view-ready",
		"lagniappe:services-ready",
	]);

	const destroyedRoot = createRoot();
	const destroyed = new ShellView(destroyedRoot);
	let resolveDestroyedManager;
	let destroyedSubmits = 0;
	destroyed.ensureSubmissionManager = () =>
		new Promise((resolve) => {
			resolveDestroyedManager = resolve;
		});
	await destroyed.init();
	const destroyedForm = {
		dataset: {},
		isConnected: true,
		closest: () => destroyedForm,
		removeAttribute() {},
		setAttribute() {},
	};
	destroyedRoot.listeners.get("submit")(createSubmit(destroyedForm, null));
	await Promise.resolve();
	destroyed.destroy();
	resolveDestroyedManager({
		submit() {
			destroyedSubmits += 1;
		},
	});
	await Promise.resolve();
	await Promise.resolve();
	assert.equal(destroyedSubmits, 0);
	assert.equal(destroyedRoot.listeners.size, 0);

	const retryRoot = createRoot();
	const retryView = new ShellView(retryRoot);
	let attempts = 0;
	let retrySubmits = 0;
	retryView.reportStartupError = () => {};
	retryView.ensureSubmissionManager = async () => {
		attempts += 1;
		if (attempts === 1) throw new Error("chunk unavailable");
		return {
			submit() {
				retrySubmits += 1;
			},
		};
	};
	await retryView.init();
	const retryForm = {
		dataset: {},
		isConnected: true,
		closest: () => retryForm,
		removeAttribute() {},
		setAttribute() {},
	};
	const retryButton = {
		dataset: {},
		disabled: false,
		removeAttribute() {},
		setAttribute() {},
	};
	retryRoot.listeners.get("submit")(createSubmit(retryForm, retryButton));
	await retryView._coldActions.get(retryForm);
	assert.equal(retryButton.disabled, false);
	assert.equal(retryButton.dataset.loading, undefined);
	retryRoot.listeners.get("submit")(createSubmit(retryForm, retryButton));
	await retryView._coldActions.get(retryForm);
	assert.equal(attempts, 2);
	assert.equal(retrySubmits, 1);
});

/** @matrix startup : first-interaction single-flight */
/** @pair search:navbar-results */
test("test_lazy_search_replays_the_latest_live_input_after_loading", async (t) => {
	const coreSource = readFileSync("src/script/views/base/core.mjs", "utf8");
	assert.equal(
		coreSource.includes("(box) => this._activateSearchBox(box)"),
		true,
	);
	assert.equal(coreSource.includes("search.value"), false);
	const { documentListeners } = installShellEnvironment(t, "testing");
	const ShellView = await loadShellView();
	const root = createRoot();
	const search = {
		dataset: {},
		removeAttribute(name) {
			delete this[name];
		},
		setAttribute(name, value) {
			this[name] = value;
		},
	};
	const input = {
		value: "first query",
		closest: (selector) => (selector === "[lp-search]" ? search : null),
	};
	const view = new ShellView(root);
	view.hasDeferredServices = true;
	let loadCount = 0;
	let resolveSearch;
	const loaded = new Promise((resolve) => {
		resolveSearch = resolve;
	});
	view.ensureSearchBox = () => {
		loadCount += 1;
		return loaded;
	};
	await view.init();

	documentListeners.get("input")({ target: input });
	input.value = "latest query";
	documentListeners.get("input")({ target: input });
	await Promise.resolve();
	assert.equal(loadCount, 1);
	const queries = [];
	resolveSearch({
		element: input,
		_input(event) {
			queries.push(event.target.value);
		},
		showPanel() {
			throw new Error("A populated search opened without replaying");
		},
	});
	await view._coldActions.get(search);
	assert.deepEqual(queries, ["latest query"]);
	assert.equal(search["aria-busy"], undefined);
	assert.equal(search.dataset.loading, undefined);
});

async function loadCore(connectivity = { online: true }) {
	class ShellView {}
	const emptyService = () => null;
	const { default: Core } = await esmock.strict(
		"../../src/script/views/base/core.mjs",
		{
			"../../src/script/shared/connectivity.mjs": { connectivity },
			"../../src/script/shared/endpoints.mjs": { ENDPOINTS: {} },
			"../../src/script/shared/errors.mjs": { captureError() {} },
			"../../src/script/shared/request.mjs": { request: {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/views/base/component.mjs": { default: class {} },
			"../../src/script/views/base/reconciliation.mjs": {
				collectRefreshTargets: () => [],
				reconcileChange() {},
				refreshCollectionComponents() {},
			},
			"../../src/script/views/base/services.mjs": {
				ensureDeferredOperations: emptyService,
				ensureEditWatcher: emptyService,
				ensureEntityMenu: emptyService,
				ensureModalClasses: emptyService,
				ensureNotifications: emptyService,
				ensureOfflineModal: emptyService,
				ensureOfflineQueue: emptyService,
				ensurePollingCoordinator: emptyService,
				ensureSearchBox: emptyService,
				ensureSubmissionManager: emptyService,
				ensureSyncManager: emptyService,
				initializeCoreServices() {},
			},
			"../../src/script/views/base/shell.mjs": { default: ShellView },
			"../../src/script/views/base/task.mjs": { Task: class {} },
		},
	);
	return Core;
}

/** @matrix navigation tasks : delegated-toggle task-open-event */
test("test_component_open_event_follows_delegated_toggle", async (t) => {
	const { createBrowser } = await import("../utility/js/environment.mjs");
	createBrowser(t);
	const Core = await loadCore();
	const node = document.createElement("li");
	node.id = "task";
	const trigger = document.createElement("div");
	trigger.setAttribute("lp-show", "task:active");
	trigger.dataset.toggle = "true";
	node.append(trigger);
	document.body.append(node);
	const component = {
		elt: node,
		name: "task",
		active: null,
		visible: true,
		async activate(show) {
			this.active = show ? { name: "TaskForm", visible: true } : null;
			return Boolean(show);
		},
		async prepareRender() {},
		render(visible) {
			node.dataset.open = visible ? "TaskForm" : "false";
		},
	};
	const view = Object.create(Core.prototype);
	view._componentActions = new Map();
	view._destroyed = false;
	view.getComponent = () => component;
	view._setLoadingTrigger = () => null;
	view._clearLoadingTrigger = () => {};
	const opened = [];
	node.addEventListener("component-opened", (event) =>
		opened.push(event.detail.trigger),
	);
	await view.renderComponent(trigger);
	assert.equal(node.dataset.open, "TaskForm");
	assert.deepEqual(opened, [trigger]);
	await view.renderComponent(trigger);
	assert.equal(node.dataset.open, "false");
	assert.deepEqual(opened, [trigger], "Closing must not emit an open event");
});

/** @matrix polling : active-widget channel entity nonblocking refresh subscription-lifecycle visibility */
/** @matrix startup : nonblocking single-flight */
test("test_core_polling_subscription_lifecycle", async () => {
	const Core = await loadCore();
	const subscriptions = [];
	const polling = {
		subscribe(descriptor, options) {
			subscriptions.push({ descriptor, options });
		},
	};
	let refreshes = 0;
	const collection = Object.create(Core.prototype);
	Object.assign(collection, {
		PollingCoordinator: polling,
		elt: {
			dataset: { fingerprint: "pages-v1", index: "pages" },
			querySelector: () => null,
		},
		kind: "page",
		key: null,
		async refresh() {
			refreshes += 1;
		},
	});
	collection._initPollingSubscription();
	const channel = subscriptions[0];
	assert.equal(channel.descriptor.type, "channel");
	assert.equal(channel.descriptor.channel, "pages");
	assert.equal(channel.descriptor.revision, "pages-v1");
	await channel.options.onResult({ status: "changed" });
	assert.equal(refreshes, 1);

	let filteredRefreshes = 0;
	const filtered = Object.create(Core.prototype);
	Object.assign(filtered, {
		PollingCoordinator: polling,
		elt: {
			dataset: {
				fingerprint: "filter-v1",
				pollChannel: "tasks",
				pollRevision: "tasks-v1",
				pollEntityRevision: "filter-entity-v1",
			},
			querySelector: () => null,
		},
		kind: "task",
		key: "filter-key",
		async refresh() {
			filteredRefreshes += 1;
		},
		async reconcileChange() {
			filteredRefreshes += 1;
		},
	});
	filtered._initPollingSubscription();
	const filteredSubscription = subscriptions[1];
	assert.equal(filteredSubscription.descriptor.id, "view:channel:tasks");
	assert.equal(filteredSubscription.descriptor.type, "channel");
	assert.equal(filteredSubscription.descriptor.channel, "tasks");
	assert.equal(filteredSubscription.descriptor.revision, "tasks-v1");
	await filteredSubscription.options.onResult({ status: "changed" });
	assert.equal(filteredRefreshes, 1);
	const filteredEntity = subscriptions[2];
	assert.equal(filteredEntity.descriptor.id, "view:entity:filter-key");
	assert.equal(filteredEntity.descriptor.revision, "filter-entity-v1");
	assert.equal(filteredEntity.options.mode, "periodic");
	assert.equal(filteredSubscription.options.mode, "periodic");
	await filteredEntity.options.onResult({ status: "changed" });
	assert.equal(filteredRefreshes, 2);

	const changes = [];
	const editResults = [];
	const watcher = {
		async receiveEntityResult(key, result) {
			editResults.push(`${key}:${result.status}`);
		},
	};
	const entity = Object.create(Core.prototype);
	Object.assign(entity, {
		PollingCoordinator: polling,
		elt: {
			dataset: { fingerprint: "entity-v1" },
			querySelector: () => ({}),
		},
		key: "entity-key",
		ensureEditWatcher: async () => watcher,
		async reconcileChange(change) {
			changes.push(change);
		},
	});
	entity._initPollingSubscription();
	const entitySubscription = subscriptions[3];
	await entitySubscription.options.onResult({ status: "changed" });
	await entitySubscription.options.onResult({ status: "unavailable" });
	assert.deepEqual(
		changes.map(({ type }) => type),
		["entity-poll", "delete"],
	);
	assert.deepEqual(editResults, [
		"entity-key:changed",
		"entity-key:unavailable",
	]);

	const lifecycleEvents = [];
	const lifecycle = Object.create(Core.prototype);
	Object.assign(lifecycle, {
		_destroyed: false,
		hidden: false,
		online: true,
		EditWatcher: {
			async reconcileSubscriptions() {
				lifecycleEvents.push("forms");
			},
		},
		SyncManager: {
			async reconcileSubscriptions() {
				lifecycleEvents.push("documents");
			},
		},
		components: {
			active: {
				widgets: {
					ingress: {
						async syncPollingSubscription() {
							lifecycleEvents.push("ingress");
						},
					},
				},
			},
		},
	});
	await lifecycle.reconcilePollingSubscriptions();
	lifecycle.hidden = true;
	await lifecycle.reconcilePollingSubscriptions();
	assert.deepEqual(lifecycleEvents, ["forms", "documents", "ingress"]);

	let resolveFirstPass;
	let passes = 0;
	let activePasses = 0;
	let maximumActivePasses = 0;
	const firstPass = new Promise((resolve) => {
		resolveFirstPass = resolve;
	});
	const scheduled = Object.create(Core.prototype);
	Object.assign(scheduled, {
		_destroyed: false,
		hidden: false,
		online: true,
		_pollingReconcileRequested: false,
		_pollingReconcileTask: null,
		elt: {},
		reportStartupError(error) {
			throw error;
		},
		async reconcilePollingSubscriptions() {
			passes += 1;
			activePasses += 1;
			maximumActivePasses = Math.max(maximumActivePasses, activePasses);
			if (passes === 1) await firstPass;
			activePasses -= 1;
		},
	});
	const scheduledFirst = scheduled.schedulePollingReconciliation();
	await Promise.resolve();
	await Promise.resolve();
	const scheduledSecond = scheduled.schedulePollingReconciliation();
	assert.equal(scheduledFirst, scheduledSecond);
	assert.equal(passes, 1);
	resolveFirstPass();
	await scheduledFirst;
	assert.equal(passes, 2);
	assert.equal(maximumActivePasses, 1);
});

/** @matrix polling : blur visibility */
/** @pair sync:deregistration */
test("test_core_sync_distinguishes_visible_blur_from_hard_suspension", async () => {
	const Core = await loadCore({ online: true });
	const events = [];
	const blurStarts = [];
	const view = Object.create(Core.prototype);
	Object.assign(view, {
		hidden: false,
		blurred: false,
		online: true,
		connectivityGeneration: 0,
		EditWatcher: { pause: () => events.push("forms:pause") },
		PollingCoordinator: {
			blur(startedAt) {
				blurStarts.push(startedAt);
				events.push("polling:blur");
			},
			pause: () => events.push("polling:pause"),
		},
		SyncManager: {
			async deregister() {
				events.push("documents:deregister");
			},
		},
	});
	Object.defineProperty(view, "offline", {
		configurable: true,
		writable: true,
		value: false,
	});

	await view.sync({ hidden: true, blurred: true, blurredAt: 42 });
	const startedAt = view.blurredAt;
	assert.deepEqual(events, [
		"forms:pause",
		"polling:blur",
		"documents:deregister",
	]);
	assert.equal(view.blurred, true);
	assert.deepEqual(blurStarts, [startedAt]);
	assert.equal(startedAt, 42);
	await view.sync({ hidden: true, blurred: true, blurredAt: 99 });
	assert.equal(events.length, 3);
	assert.equal(view.blurredAt, startedAt);
	await view.sync({ hidden: true, blurred: false });
	assert.deepEqual(events.slice(3), [
		"forms:pause",
		"polling:pause",
		"documents:deregister",
	]);
	assert.equal(view.blurred, false);
	assert.equal(view.blurredAt, null);
});

async function loadViewComponent() {
	const { default: ViewComponent } = await esmock.strict(
		"../../src/script/views/base/component.mjs",
		{
			"../../src/script/elements/nav.mjs": { NavElement: class {} },
			"../../src/script/shared/errors.mjs": { captureError() {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/widgets/loader.mjs": {
				loadWidget: async () => null,
			},
		},
	);
	return ViewComponent;
}

/** @covers src/script/views/base/component.mjs::ViewComponent.activate */
/** @matrix navigation tabs : static-component visibility */
test("test_static_component_without_default_widget_activates", async () => {
	const ViewComponent = await loadViewComponent();
	const component = Object.create(ViewComponent.prototype);
	Object.assign(component, {
		active: null,
		_destroyed: false,
		_nav: null,
		elt: { dataset: {}, querySelector: () => null },
		name: "backups",
	});
	component.loadWidget = async () => {
		throw new Error("A static component must not load a placeholder widget");
	};
	const activated = await component.activate("active");
	assert.equal(activated, true);
	assert.equal(component.active, null);
});

/** @matrix deferred-jobs : rendered-visibility */
test("test_task_form_operation_subscription_follows_component_visibility", async () => {
	const ViewComponent = await loadViewComponent();
	const events = [];
	const widget = {
		name: "TaskForm",
		target: { dataset: { widget: "TaskForm" } },
		visible: true,
		disable() {
			this.visible = false;
			events.push("disable");
		},
		enable() {
			this.visible = true;
			events.push("enable");
		},
		reconcile() {},
	};
	const component = Object.create(ViewComponent.prototype);
	Object.assign(component, {
		active: widget,
		_destroyed: false,
		_nav: null,
		elt: { dataset: {}, querySelector: () => null },
		name: "task",
		view: {
			DeferredOperations: {
				suspendTaskForm() {
					events.push("suspend");
				},
				resumeTaskForm() {
					events.push("resume");
				},
			},
		},
	});
	component.loadWidget = async () => widget;
	assert.equal(await component.activate("TaskForm"), true);
	assert.deepEqual(events, ["suspend", "disable", "enable", "resume"]);
	component.deactivate();
	assert.deepEqual(events.slice(-2), ["suspend", "disable"]);
});

/** @matrix polling : component-render nonblocking subscription-lifecycle */
/** @matrix startup : component-render deferred-services nonblocking */
test("test_component_render_does_not_wait_for_polling_reconciliation", async (t) => {
	replaceGlobal(t, "document", { getElementById: () => null });
	const ViewComponent = await loadViewComponent();
	let scheduled = 0;
	let reconciled = 0;
	const neverSettles = new Promise(() => {});
	const component = Object.create(ViewComponent.prototype);
	Object.assign(component, {
		active: null,
		_nav: null,
		elt: { dataset: {}, querySelector: () => null },
		name: "info",
		view: {
			schedulePollingReconciliation() {
				scheduled += 1;
				return neverSettles;
			},
		},
		widgets: {
			info: {
				async reconcile() {
					reconciled += 1;
				},
			},
		},
		_setParentComponent() {},
	});
	const outcome = component.render(true);
	assert.equal(outcome, undefined);
	assert.equal(reconciled, 1);
	assert.equal(scheduled, 1);
});

/** @pair forms:queue-independent-initial-render */
test("test_offline_queue_does_not_block_initial_form_render", async () => {
	const { FormWidget } = await esmock.strict(
		"../../src/script/widgets/base/formWidget.mjs",
		{
			"../../src/script/forms/controller.mjs": { FormController: class {} },
			"../../src/script/forms/migrationNotice.mjs": {
				installMigrationNotice: () => null,
			},
			"../../src/script/forms/representation.mjs": {
				compatibleField: () => true,
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
		},
	);
	let initialized = false;
	let renderCalls = 0;
	let presented = false;
	const initialReplayReady = new Promise(() => {});
	const target = {
		cloneNode: () => ({}),
		hasAttribute: () => false,
		setAttribute(name) {
			if (name === "initialized") initialized = true;
		},
	};
	const form = new FormWidget({
		target,
		view: {
			initialReplayReady,
			offlineQueue: {
				presentFor() {
					presented = true;
					return new Promise(() => {});
				},
			},
		},
		readonly: false,
	});
	form.handleOfflineQueue = () => {};
	form._initForm = async () => {
		renderCalls += 1;
	};
	form.commitRevisionBaseline = () => {};
	const outcome = await Promise.race([
		form.init().then(() => "rendered"),
		new Promise((resolve) => setTimeout(() => resolve("blocked"), 50)),
	]);
	assert.equal(outcome, "rendered");
	assert.equal(initialized, true);
	assert.equal(renderCalls, 1);
	assert.equal(presented, true);
});

async function loadCollaborativeDocument({ editor } = {}) {
	const Y = {
		Doc: class {},
		encodeStateAsUpdate: () => null,
		mergeUpdates: () => null,
	};
	const { CollaborativeDocument } = await esmock.strict(
		"../../src/script/elements/editor/collaborative.mjs",
		{
			yjs: Y,
			"../../src/script/generated/styles.mjs": {
				STYLES: { editor: { container: "editor-container" } },
			},
			"../../src/script/shared/utilities.mjs": {
				base64ToUint8Array: () => null,
				uint8ArrayToBase64: () => "",
				waitForAttribute: async () => {},
			},
			"../../src/script/elements/editor/editor.mjs": {
				collaborativeEditor: () => editor,
			},
			"../../src/script/elements/editor/extensions/index.mjs": {
				MentionSuggestions: class {},
			},
			"../../src/script/elements/editor/toolbar.mjs": { Toolbar: class {} },
		},
	);
	return CollaborativeDocument;
}

/** @matrix sync : editor-readiness loader-free state-only */
test("test_collaborative_document_renders_before_initial_state", async (t) => {
	let resolveSync;
	let loaderAppends = 0;
	const loadedAttributes = [];
	const syncReady = new Promise((resolve) => {
		resolveSync = resolve;
	});
	const document = {
		createElement() {
			return {
				dataset: {},
				className: "",
				classList: { add() {} },
				appendChild() {
					loaderAppends += 1;
				},
				setAttribute(name) {
					loadedAttributes.push(name);
				},
			};
		},
	};
	replaceGlobal(t, "document", document);
	const CollaborativeDocument = await loadCollaborativeDocument();
	let stateCalls = 0;
	const shellCalls = [];
	const documentWidget = Object.create(CollaborativeDocument.prototype);
	Object.assign(documentWidget, {
		headless: false,
		remote: null,
		syncId: "page-1:document",
		view: { syncReady },
		target: {
			replaceChildren(container) {
				shellCalls.push("container");
				this.container = container;
			},
		},
		_initEditor() {
			shellCalls.push("editor");
		},
		_initToolbar() {
			shellCalls.push("toolbar");
		},
	});
	const result = documentWidget.init();
	assert.equal(result, undefined);
	assert.deepEqual(shellCalls, ["container", "editor", "toolbar"]);
	assert.equal(loaderAppends, 0);
	let stateSettled = false;
	documentWidget.initialStateReady.then(() => {
		stateSettled = true;
	});
	await Promise.resolve();
	assert.equal(stateCalls, 0);
	assert.equal(stateSettled, false);
	assert.equal(loadedAttributes.includes("loaded"), false);
	resolveSync({
		async state(widget) {
			stateCalls += 1;
			assert.equal(widget, documentWidget);
			return { fingerprint: "remote-fingerprint" };
		},
	});
	await documentWidget.initialStateReady;
	assert.equal(stateCalls, 1);
	assert.equal(documentWidget.remote?.fingerprint, "remote-fingerprint");
	assert.equal(loadedAttributes.includes("loaded"), true);
});

/** @matrix editor : empty-content initialization save-guard */
/** @matrix sync : checkpoint concurrent-edit dirty-state empty-content initialization intentional-clear response-contract save-guard */
test("test_collaborative_document_does_not_save_untouched_empty_state", async () => {
	let editorHandler;
	let ydocUpdateHandler;
	const editorStub = {
		on(name, handler) {
			if (name === "create") editorHandler = handler;
		},
		getHTML: () => "<p></p>",
	};
	const CollaborativeDocument = await loadCollaborativeDocument({
		editor: editorStub,
	});
	const documentWidget = Object.create(CollaborativeDocument.prototype);
	Object.assign(documentWidget, {
		initialized: false,
		_dirty: false,
		_applyingRemote: false,
		updateQueue: [],
		snapshot: null,
		container: {},
		editor: null,
		target: { dataset: {} },
		ydoc: {
			on(name, handler) {
				if (name === "update") ydocUpdateHandler = handler;
			},
		},
		_packageState() {
			return this.currentState;
		},
		_packageUpdates() {
			this.updateQueue.length = 0;
			return "user-update";
		},
		currentState: "fresh-empty-state",
	});
	documentWidget._initEditor();
	assert.ok(editorHandler);
	assert.ok(ydocUpdateHandler);
	ydocUpdateHandler("setup-update", "local");
	assert.equal(documentWidget._dirty, false);
	documentWidget._commitInitialBaseline();
	documentWidget.initialized = true;
	documentWidget.currentState = "current-document-state";
	documentWidget.updateQueue.push("pending-user-update");
	const syncPayload = documentWidget.syncData;
	assert.equal(syncPayload?.update, "user-update");
	assert.equal(syncPayload?.ydoc, "current-document-state");
	assert.equal(documentWidget.updateQueue.length, 0);
	assert.equal(documentWidget.saveData, null);

	documentWidget.snapshot = "existing-content-state";
	documentWidget.currentState = "intentionally-cleared-state";
	ydocUpdateHandler("clear-update", "local");
	const clearPayload = documentWidget.saveData;
	assert.equal(clearPayload?.html, "");
	assert.equal(clearPayload?.ydoc, "intentionally-cleared-state");
	assert.equal(clearPayload?.update, "user-update");
	documentWidget.commitSavedBaseline(clearPayload.ydoc);
	documentWidget.currentState = "remote-only-state";
	assert.equal(documentWidget._dirty, false);
	assert.equal(documentWidget.saveData, null);
	ydocUpdateHandler("later-user-update", "local");
	assert.notEqual(documentWidget.saveData, null);
});
