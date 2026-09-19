import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { test } from "node:test";
import esmock from "esmock";

registerHooks({
	load(url, context, nextLoad) {
		if (url.endsWith(".css")) {
			return { format: "module", source: "", shortCircuit: true };
		}
		return nextLoad(url, context);
	},
});

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

async function setupMain(t, { activeNavigationTransition = false } = {}) {
	const fetchCalls = [];
	const syncCalls = [];
	const controllerMessages = [];
	const serviceWorkerRegistrations = [];
	const serviceWorkerListeners = new Map();
	const documentListeners = new Map();
	const windowListeners = new Map();
	const analyticsCalls = [];
	const authenticatedCalls = [];
	const capturedErrors = [];
	const upstreamMessages = [];
	let viewElement = null;
	let focused = true;
	let pageMode = "production";
	let viewLoader = async () => null;
	let recentSearchCleanup = () => {};
	let resolveNavigationTransition;
	const navigationTransitionFinished = new Promise((resolve) => {
		resolveNavigationTransition = resolve;
	});
	const connectivityState = {
		browser: "online",
		server: "unknown",
		visibility: "visible",
		controller: "uncontrolled",
	};
	const connectivity = {
		get hidden() {
			return connectivityState.visibility === "hidden";
		},
		get online() {
			return (
				connectivityState.browser === "online" &&
				connectivityState.server !== "offline"
			);
		},
		snapshot: () => ({ ...connectivityState }),
		transition(patch = {}) {
			Object.assign(connectivityState, patch);
			return this.snapshot();
		},
	};
	const connectivityMessage = (state) => ({
		protocol: "lagniappe-browser",
		protocol_version: 4,
		type: "connectivity-state",
		state: { ...state },
	});
	const serviceWorker = {
		controller: null,
		addEventListener(type, listener) {
			serviceWorkerListeners.set(type, listener);
		},
		async register(url) {
			serviceWorkerRegistrations.push(url);
			return {};
		},
	};
	const document = {
		activeViewTransition: activeNavigationTransition
			? { finished: navigationTransitionFinished }
			: undefined,
		activeElement: null,
		body: {},
		hidden: false,
		readyState: "loading",
		addEventListener(type, listener) {
			documentListeners.set(type, listener);
		},
		hasFocus: () => focused,
		querySelector(selector) {
			if (selector === "[lp-view]") return viewElement;
			if (selector === "meta[name='mode']") {
				return { getAttribute: () => pageMode };
			}
			return null;
		},
	};
	document.activeElement = document.body;
	const window = {
		__TESTING__: true,
		addEventListener(type, listener) {
			windowListeners.set(type, listener);
		},
		dispatchEvent() {},
	};
	const navigator = { onLine: true, serviceWorker };
	const requestAnimationFrame = (callback) => setTimeout(callback, 0);
	for (const [name, value] of Object.entries({
		document,
		window,
		navigator,
		requestAnimationFrame,
	}))
		replaceGlobal(t, name, value);
	let fetchImpl = async (url, options = {}) => {
		fetchCalls.push({ url, options });
		return new Response("pong", { status: 200 });
	};
	replaceGlobal(t, "fetch", (...args) => fetchImpl(...args));
	const errorBoundary = {
		captureError(error) {
			capturedErrors.push(error);
		},
		captureNetworkError() {},
		isSkippedViewTransitionError: () => false,
		isTransientNetworkError: (error) => error?.message === "Failed to fetch",
	};
	const installUpstreamUnavailableBanner = () => {
		serviceWorker.addEventListener("message", (event) => {
			const data = event.data;
			if (
				data?.protocol === "lagniappe-browser" &&
				Number(data.protocol_version) === 4 &&
				data.type === "upstream-unavailable" &&
				data.state?.status === 503 &&
				data.state?.method === "GET"
			) {
				upstreamMessages.push({ data });
			}
		});
	};
	const module = await esmock.strict.p("../../src/script/main.mjs", {
		"../../src/script/shared/connectivity.mjs": { connectivity },
		"../../src/script/shared/notificationState.mjs": {
			applyNotificationStateHeader() {},
		},
		"../../src/script/shared/protocol.mjs": { connectivityMessage },
		"../../src/script/shared/upstreamUnavailable.mjs": {
			installUpstreamUnavailableBanner,
			receiveUpstreamUnavailable() {},
			receiveUpstreamUnavailableMessage(data) {
				upstreamMessages.push({ data });
			},
		},
		"../../src/script/viewRegistry.mjs": {
			loadView: (...args) => viewLoader(...args),
		},
		"../../src/script/shared/errors.mjs": errorBoundary,
		"../../src/script/shared/analytics.mjs": {
			analytics: { view: () => analyticsCalls.push("analytics") },
		},
		"../../src/script/shared/logout.mjs": {
			initializeLogoutForms: () => authenticatedCalls.push("logout"),
		},
		"../../src/script/shared/user.mjs": {
			updateUserData: () => authenticatedCalls.push("user"),
		},
		"../../src/script/shared/storage.mjs": {
			clearRecentSearchResults: () => recentSearchCleanup(),
		},
		"../../src/script/shared/request.mjs": {
			request: { get: async () => ({ ok: true }) },
		},
	});
	if (!activeNavigationTransition) {
		await window.__NAVIGATION_TRANSITION_READY__;
	}
	const context = {
		...module,
		analyticsCalls,
		authenticatedCalls,
		capturedErrors,
		connectivityState,
		controllerMessages,
		documentListeners,
		fetchCalls,
		serviceWorker,
		serviceWorkerListeners,
		serviceWorkerRegistrations,
		syncCalls,
		upstreamMessages,
		windowListeners,
		setView(value) {
			viewElement = value;
		},
		setViewLoader(loader) {
			viewLoader = loader;
		},
		setFocused(value) {
			focused = value;
		},
		setDocumentHidden(value) {
			document.hidden = value;
		},
		setMode(value) {
			pageMode = value;
		},
		setNavigatorOnline(value) {
			navigator.onLine = value;
		},
		setFetch(implementation) {
			fetchImpl = implementation;
		},
		setRecentSearchCleanup(callback) {
			recentSearchCleanup = callback;
		},
		resolveNavigationTransition() {
			document.activeViewTransition = undefined;
			resolveNavigationTransition();
		},
		async flushPaint() {
			await new Promise((resolve) => setTimeout(resolve, 10));
			for (let index = 0; index < 4; index += 1) await Promise.resolve();
		},
	};
	return context;
}

/** @pairs startup:settled-boundary view-transition:navigation */
test("test_cross_document_transition_publishes_settled_readiness", async (t) => {
	const context = await setupMain(t, { activeNavigationTransition: true });
	assert.equal(window.__NAVIGATION_TRANSITION_SETTLED__, false);
	let boundaryResolved = false;
	window.__NAVIGATION_TRANSITION_READY__.then(() => {
		boundaryResolved = true;
	});
	await Promise.resolve();
	assert.equal(boundaryResolved, false);
	context.resolveNavigationTransition();
	await window.__NAVIGATION_TRANSITION_READY__;
	assert.equal(boundaryResolved, true);
	assert.equal(window.__NAVIGATION_TRANSITION_SETTLED__, true);
});

/** @matrix startup : error-reporting navigation transient-network */
test("test_navigation_fetch_abort_is_not_reported_as_application_error", async (t) => {
	const context = await setupMain(t);
	context.initialize();
	const handler = context.windowListeners.get("unhandledrejection");
	assert.ok(handler);
	const transient = {
		type: "unhandledrejection",
		reason: new TypeError("Failed to fetch"),
		prevented: false,
		preventDefault() {
			this.prevented = true;
		},
	};
	await handler(transient);
	assert.equal(transient.prevented, true);
	assert.equal(context.capturedErrors.length, 0);
	await handler({
		type: "unhandledrejection",
		reason: new Error("broken startup"),
		preventDefault() {},
	});
	assert.equal(context.capturedErrors.length, 1);
	assert.equal(context.capturedErrors[0].message, "broken startup");
});

/** @matrix offline sync : deregistration pagehide visibility */
test("test_suspend_current_view_deregisters_without_health_check", async (t) => {
	const context = await setupMain(t);
	context.setView({
		_lp_view: { sync: (options) => context.syncCalls.push(options) },
	});
	await context.suspendCurrentView();
	assert.equal(context.syncCalls.length, 1);
	assert.equal(context.syncCalls[0].hidden, true);
	assert.equal(context.syncCalls[0].blurred, false);
	assert.equal(context.syncCalls[0].blurredAt, null);
	assert.equal(context.fetchCalls.length, 0);
});

/** @matrix polling : blur catch-up focus visibility */
/** @pair offline:visible-blur */
test("test_window_blur_soft_suspends_visible_tab_until_focus_catchup", async (t) => {
	const context = await setupMain(t);
	context.setView({
		_lp_view: {
			async sync(options) {
				context.syncCalls.push(options);
			},
		},
	});
	context.initialize();
	await context.flushPaint();
	await context.syncView();
	context.fetchCalls.length = 0;
	context.syncCalls.length = 0;
	context.setFocused(false);
	await context.windowListeners.get("blur")();
	assert.equal(context.fetchCalls.length, 0);
	assert.equal(context.syncCalls.length, 1);
	assert.equal(context.syncCalls[0].hidden, true);
	assert.equal(context.syncCalls[0].blurred, true);
	assert.equal(Number.isFinite(context.syncCalls[0].blurredAt), true);
	context.fetchCalls.length = 0;
	context.syncCalls.length = 0;
	context.setDocumentHidden(true);
	await context.documentListeners.get("visibilitychange")();
	assert.equal(context.fetchCalls.length, 0);
	assert.deepEqual(context.syncCalls[0], {
		hidden: true,
		blurred: false,
		blurredAt: null,
		force: false,
	});
	context.fetchCalls.length = 0;
	context.syncCalls.length = 0;
	context.setDocumentHidden(false);
	context.setFocused(true);
	await context.windowListeners.get("focus")();
	assert.equal(context.fetchCalls.length, 1);
	assert.equal(context.syncCalls.length, 1);
	assert.equal(context.syncCalls[0].hidden, false);
	assert.equal(context.syncCalls[0].blurred, false);
	assert.equal(context.syncCalls[0].blurredAt, null);
});

/** @matrix offline : cache-policy server-health */
test("test_ping_uses_server_owned_cache_policy", async (t) => {
	const context = await setupMain(t);
	assert.equal(await context.pingServer(), true);
	assert.equal(context.fetchCalls.length, 1);
	const call = context.fetchCalls[0];
	assert.equal(call.url, "/l/ping");
	assert.equal(call.options.method, "HEAD");
	assert.equal("cache" in call.options, false);
	assert.equal(new Headers(call.options.headers).has("Cache-Control"), false);
});

/** @matrix offline : pending-ownership server-health settled-cleanup */
test("test_ping_clears_only_the_settled_pending_promise", async (t) => {
	const context = await setupMain(t);
	const settled = context.pingServer();
	assert.ok(window.__PING_PENDING__);
	await settled;
	await Promise.resolve();
	assert.equal(window.__PING_PENDING__, null);
	let releaseFetch;
	context.setFetch(
		() =>
			new Promise((resolve) => {
				releaseFetch = resolve;
			}),
	);
	const superseded = context.pingServer();
	const successor = Promise.resolve(true);
	window.__PING_PENDING__ = successor;
	releaseFetch(new Response("pong", { status: 200 }));
	await superseded;
	await Promise.resolve();
	assert.equal(window.__PING_PENDING__, successor);
});

/** @matrix offline : coalescing rapid-transitions server-health transitions */
test("test_rapid_sync_requests_coalesce_and_retain_forced_transition", async (t) => {
	const context = await setupMain(t);
	context.setView({
		_lp_view: {
			async sync(options) {
				context.syncCalls.push(options);
			},
		},
	});
	const first = context.syncView();
	const second = context.syncView({ force: true });
	const third = context.syncView({ hidden: false });
	await Promise.all([first, second, third]);
	assert.equal(context.syncCalls.length, 2);
	assert.equal(context.syncCalls[1].force, true);
	assert.equal(context.syncCalls[1].hidden, false);
	assert.equal(context.fetchCalls.length, 2);
});

/** @matrix connectivity offline : browser-state error-recovery settled-boundary transitions */
test("test_native_connectivity_state_publishes_before_async_view_sync_and_exposes_settled_boundary", async (t) => {
	const context = await setupMain(t);
	context.initialize();
	await context.flushPaint();
	await window.__CONNECTIVITY_READY__;
	let rejectOfflineSync;
	context.setView({
		_lp_view: {
			async sync(options) {
				context.syncCalls.push(options);
				if (context.syncCalls.length === 1) {
					await new Promise((_resolve, reject) => {
						rejectOfflineSync = reject;
					});
				}
			},
		},
	});
	context.setNavigatorOnline(false);
	const offlineCycle = context.windowListeners.get("offline")();
	const offlineBoundary = window.__CONNECTIVITY_READY__;
	assert.equal(context.connectivityState.browser, "offline");
	assert.equal(window.__CONNECTIVITY__.browser, "offline");
	assert.ok(offlineBoundary);
	for (let index = 0; index < 8 && !rejectOfflineSync; index += 1)
		await Promise.resolve();
	assert.ok(rejectOfflineSync);
	context.setNavigatorOnline(true);
	const onlineCycle = context.windowListeners.get("online")();
	assert.equal(context.connectivityState.browser, "online");
	assert.equal(window.__CONNECTIVITY__.browser, "online");
	assert.equal(window.__CONNECTIVITY_READY__, offlineBoundary);
	void offlineCycle.catch(() => {});
	void onlineCycle.catch(() => {});
	rejectOfflineSync(new Error("failed offline cycle"));
	await assert.rejects(window.__CONNECTIVITY_READY__, /failed offline cycle/);
	assert.equal(context.syncCalls.length, 2);
	assert.equal(context.connectivityState.browser, "online");
});

/** @matrix connectivity service-worker : state-publication startup */
test("test_startup_publishes_worker_state_before_loading_view_with_pending_ping", async (t) => {
	const context = await setupMain(t);
	let workerState = { browser: "online", server: "offline" };
	context.serviceWorker.controller = {
		postMessage(message) {
			context.controllerMessages.push(message);
			workerState = message.state;
		},
	};
	let stateWhenViewLoads;
	context.setView({ dataset: { kind: "page" }, isConnected: true });
	context.setViewLoader(async () => ({
		default: class {
			async init() {
				stateWhenViewLoads = { ...workerState };
			}
			async sync() {}
		},
	}));
	let releasePing;
	context.setFetch(
		() =>
			new Promise((resolve) => {
				releasePing = resolve;
			}),
	);
	const cycle = context.syncView();
	await context.flushPaint();
	assert.ok(stateWhenViewLoads);
	releasePing(new Response(null, { status: 200 }));
	await cycle;
	assert.equal(stateWhenViewLoads.server, "unknown");
	assert.equal(stateWhenViewLoads.controller, "controlled");
	assert.equal(workerState.server, "online");
});

/** @matrix connectivity service-worker : controller-replacement state-publication version */
/** @pair service-worker:recent-search-cleanup */
test("test_controller_replacement_receives_current_versioned_connectivity_state", async (t) => {
	const context = await setupMain(t);
	const firstController = {
		postMessage: (message) =>
			context.controllerMessages.push({ owner: "first", message }),
	};
	const secondController = {
		postMessage: (message) =>
			context.controllerMessages.push({ owner: "second", message }),
	};
	let cleanupCalls = 0;
	context.setRecentSearchCleanup(() => {
		cleanupCalls += 1;
	});
	context.serviceWorker.controller = firstController;
	context.initialize();
	await context.flushPaint();
	await context.syncView();
	assert.equal(cleanupCalls, 0);
	context.serviceWorker.controller = secondController;
	const replace = context.serviceWorkerListeners.get("controllerchange");
	assert.ok(replace);
	await replace();
	await context.syncView();
	assert.equal(cleanupCalls, 1);
	const replacement = context.controllerMessages.find(
		({ owner }) => owner === "second",
	);
	assert.ok(replacement);
	assert.equal(replacement.message.protocol, "lagniappe-browser");
	assert.equal(replacement.message.protocol_version, 4);
	assert.equal(replacement.message.type, "connectivity-state");
	assert.equal(replacement.message.state.controller, "controlled");
	assert.equal(replacement.message.state.visibility, "visible");
	await replace();
	assert.equal(cleanupCalls, 2);
});

/** @matrix browser-protocol request-errors service-worker : banner client-message upstream-unavailable validation retry */
test("test_upstream_unavailable_worker_message_shows_retryable_banner", async (t) => {
	const context = await setupMain(t);
	context.initialize();
	await context.flushPaint();
	const receive = context.serviceWorkerListeners.get("message");
	assert.ok(receive);
	const state = {
		status: 503,
		method: "GET",
		route_class: "pages",
		server: "Google Frontend",
		trace_header_present: true,
		timestamp: "2026-09-01T12:00:00.000Z",
		online: true,
		service_worker: "controlled",
		stale: false,
		outcome_uncertain: false,
		retry_outcome: "service_worker",
	};
	await receive({
		data: {
			protocol: "lagniappe-browser",
			protocol_version: 4,
			type: "upstream-unavailable",
			state,
		},
	});
	assert.equal(context.upstreamMessages.length, 1);
	assert.equal(context.upstreamMessages[0].data.state, state);
	await receive({
		data: {
			protocol: "lagniappe-browser",
			protocol_version: 3,
			type: "upstream-unavailable",
			state,
		},
	});
	assert.equal(context.upstreamMessages.length, 1);
});

/** @pairs service-worker:registration startup:interaction-ready */
test("test_service_worker_registration_starts_immediately", async (t) => {
	const context = await setupMain(t);
	let resolveView;
	const viewReady = new Promise((resolve) => {
		resolveView = resolve;
	});
	const root = {
		dataset: { kind: "page" },
		isConnected: true,
		setAttribute() {},
	};
	context.setView(root);
	context.setViewLoader(async () => ({
		default: class {
			constructor(element) {
				this.elt = element;
			}
			async init() {
				await viewReady;
			}
			publish() {
				this.elt._lp_view = this;
			}
		},
	}));
	context.initialize();
	assert.deepEqual(context.serviceWorkerRegistrations, ["/sw.js"]);
	resolveView();
	await context.flushPaint();
	assert.equal(context.serviceWorkerRegistrations.length, 1);
});

/** @matrix startup : analytics deferred-lifecycle public-boundary */
/** @pair service-worker:registration */
test("test_public_page_skips_authenticated_lifecycle", async (t) => {
	const context = await setupMain(t);
	context.setMode("public");
	context.setView({
		_lp_view: { sync: () => context.syncCalls.push("private-sync") },
	});
	context.initialize();
	await context.flushPaint();
	assert.equal(context.analyticsCalls.length, 1);
	assert.equal(context.authenticatedCalls.length, 0);
	assert.equal(context.fetchCalls.length, 0);
	assert.equal(context.syncCalls.length, 0);
	assert.deepEqual(context.serviceWorkerRegistrations, ["/sw.js"]);
	assert.deepEqual([...context.serviceWorkerListeners.keys()].sort(), [
		"controllerchange",
		"message",
	]);
	assert.deepEqual([...context.windowListeners.keys()].sort(), [
		"error",
		"unhandledrejection",
	]);
});
