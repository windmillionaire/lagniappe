import "../style/main.css";

import { connectivity } from "./shared/connectivity";
import { applyNotificationStateHeader } from "./shared/notificationState";
import { connectivityMessage } from "./shared/protocol";
import { loadView } from "./viewRegistry";

/**
 * @testable true
 * @tests tests_js/test_017_main_lifecycle.py::test_navigation_fetch_abort_is_not_reported_as_application_error
 * @features startup
 * @dimensions error-reporting navigation transient-network
 * @pairs startup:error-reporting startup:navigation startup:transient-network
 */
async function onError(event) {
	const {
		captureError,
		isSkippedViewTransitionError,
		isTransientNetworkError,
	} = await import("./shared/errors");
	const error = event.error || event.reason || event.message || "Unknown error";
	if (isSkippedViewTransitionError(error) || isTransientNetworkError(error)) {
		event.preventDefault();
		return;
	}
	const context =
		event.type === "unhandledrejection"
			? { event: { type: "unhandledrejection" } }
			: {};
	const element =
		document.activeElement !== document.body ? document.activeElement : null;

	captureError(error, element, context);
}

window.__CONNECTIVITY__ = connectivity.snapshot();
// Optional observation boundary for callers that explicitly need the latest
// background connectivity cycle to settle. Rendering never awaits this.
window.__CONNECTIVITY_READY__ = Promise.resolve();

let __activeView = null;
/**
 * @testable true
 * @tests tests_e2e/001_site/test_001d_offline.py::test_testing_mode_navigation_resets_offline_state
 * @features offline
 * @dimensions view-reset
 */
const getView = async () => {
	const viewElt = document.querySelector("[lp-view]");
	if (!viewElt) return null;

	if (viewElt._lp_view) return viewElt._lp_view;

	if (__activeView) return await __activeView;

	__activeView = (async () => {
		const viewModule = await loadView(viewElt.dataset.kind);
		if (!viewModule) {
			const { captureError } = await import("./shared/errors");
			captureError(
				new Error(`Unknown view kind: ${viewElt.dataset.kind || "missing"}`),
				viewElt,
				{ view_kind: viewElt.dataset.kind || "" },
			);
			return null;
		}

		if (viewElt.isConnected === false) return null;
		const view = new viewModule.default(viewElt);
		await view.init();
		if (view._destroyed || viewElt.isConnected === false) return null;
		view.publish?.();
		return view;
	})();

	return await __activeView;
};

let _ping = null;

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
 * @tests tests_e2e/001_site/test_001d_offline.py::test_offline_poll_recovers_without_online_event
 * @tests tests_js/test_017_main_lifecycle.py::test_ping_uses_server_owned_cache_policy
 * @features offline
 * @dimensions server-health cache-policy
 */
async function pingServer() {
	if (_ping) return _ping;

	_ping = (async () => {
		const controller = new AbortController();
		const timeoutId = setTimeout(() => controller.abort(), 500);
		try {
			const response = await fetch("/l/ping", {
				method: "HEAD",
				signal: controller.signal,
			});
			applyNotificationStateHeader(response.headers);
			return response.ok;
		} catch {
			return false;
		} finally {
			clearTimeout(timeoutId);
			_ping = null;
		}
	})();
	window.__PING_PENDING__ = _ping;
	void _ping.finally(() => {
		if (window.__PING_PENDING__ === _ping) window.__PING_PENDING__ = null;
	});

	return _ping;
}

let _pollTimeout = null;

const KEEP_AWAKE_MS = 10 * 60 * 1000;
const POLL_MS = 2 * 1000;
const OFFLINE_POLL_MS = 5 * 1000;

/**
 * @testable false
 * @covered-by src/script/main.mjs::syncViewOnce
 * @covered-by src/script/main.mjs::pollServer
 * @reason timer cancellation is owned by the foreground/background sync lifecycle
 */
function stopPolling() {
	if (!_pollTimeout) return;
	clearTimeout(_pollTimeout);
	_pollTimeout = null;
}

/**
 * @testable false
 * @covered-by src/script/main.mjs::syncViewOnce
 * @reason timer scheduling supports the server-health sync contract
 */
function pollServer(online) {
	stopPolling();
	// Healthy testing-mode views do not need the production keep-awake timer,
	// but an offline view still needs a retry in case the browser misses the
	// native online transition after an offline reload.
	if (window.__TESTING__ && online) return;

	const browserOnline = connectivity.snapshot().browser === "online";
	const delay = online
		? KEEP_AWAKE_MS
		: browserOnline
			? POLL_MS
			: OFFLINE_POLL_MS;
	_pollTimeout = setTimeout(syncView, delay);
}

let _sync = null;
let _syncPending = null;

/**
 * Treat a visible tab in an unfocused browser window as inactive. Focus runs
 * an explicit catch-up cycle, so periodic work can stop while the user is
 * working elsewhere.
 *
 * @testable false
 * @covered-by src/script/main.mjs::syncViewOnce
 * @covered-by src/script/main.mjs::initialize
 * @reason shared inactivity predicate is exercised through lifecycle entry points
 */
function documentInactive() {
	return document.hidden || document.hasFocus?.() === false;
}

/**
 * @testable false
 * @covered-by src/script/main.mjs::syncViewOnce
 * @covered-by src/script/main.mjs::suspendCurrentView
 * @reason connectivity publication is owned by the visible/hidden sync lifecycle
 */
function updateConnectivity(patch, { notifyController = true } = {}) {
	const state = connectivity.transition(patch);
	window.__CONNECTIVITY__ = state;
	if (notifyController) {
		navigator.serviceWorker?.controller?.postMessage(
			connectivityMessage(state),
		);
	}
	return state;
}

/**
 * @testable false
 * @covered-by src/script/main.mjs::syncView
 * @reason pending sync option merging is private queue plumbing for the public sync runner
 */
function queueSync({ hidden, force = false, browser } = {}) {
	const pendingHidden =
		hidden === undefined ? _syncPending?.hidden : Boolean(hidden);
	const pendingBrowser =
		browser === undefined ? _syncPending?.browser : browser;

	_syncPending = {
		force: Boolean(_syncPending?.force || force),
	};
	if (pendingHidden !== undefined) _syncPending.hidden = pendingHidden;
	if (pendingBrowser !== undefined) _syncPending.browser = pendingBrowser;
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
 * @tests tests_e2e/001_site/test_001d_offline.py::test_offline_poll_recovers_without_online_event
 * @tests tests_e2e/001_site/test_001d_offline.py::test_testing_mode_navigation_resets_offline_state
 * @tests tests_js/test_017_main_lifecycle.py::test_rapid_sync_requests_coalesce_and_retain_forced_transition
 * @features offline
 * @dimensions server-health transitions view-reset reconnect indicator browser-state coalescing rapid-transitions
 */
async function syncViewOnce({
	hidden = documentInactive(),
	force = false,
	browser = navigator.onLine === false ? "offline" : "online",
} = {}) {
	const controller = navigator.serviceWorker?.controller
		? "controlled"
		: "uncontrolled";
	updateConnectivity(
		{
			browser,
			controller,
			visibility: hidden ? "hidden" : "visible",
		},
		{ notifyController: hidden },
	);
	const viewPromise = getView();
	if (hidden) {
		stopPolling();
		const view = await viewPromise;
		if (view?.sync) await view.sync({ hidden: true, force });
		return;
	}

	const online = await pingServer();

	updateConnectivity({ server: online ? "online" : "offline" });
	pollServer(online);

	const view = await viewPromise;
	if (view?.sync) await view.sync({ hidden, force });
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
 * @tests tests_js/test_017_main_lifecycle.py::test_rapid_sync_requests_coalesce_and_retain_forced_transition
 * @tests tests_js/test_017_main_lifecycle.py::test_native_connectivity_state_publishes_before_async_view_sync_and_exposes_settled_boundary
 * @features offline
 * @dimensions server-health transitions browser-state settled-boundary
 */
async function syncView(options = {}) {
	queueSync(options);
	if (_sync) return _sync;

	_sync = (async () => {
		let firstError = null;
		while (_syncPending) {
			const nextSync = _syncPending;
			_syncPending = null;
			try {
				await syncViewOnce(nextSync);
			} catch (error) {
				firstError ||= error;
			}
		}
		if (firstError) throw firstError;
	})().finally(() => {
		_sync = null;
	});
	window.__CONNECTIVITY_READY__ = _sync;

	return _sync;
}

/**
 * Publish native browser-link changes before scheduling health checks, view
 * synchronization, or replay. Consumers can read connectivity synchronously;
 * only callers that need the background cycle's completion await the result.
 *
 * @testable true
 * @tests tests_js/test_017_main_lifecycle.py::test_native_connectivity_state_publishes_before_async_view_sync_and_exposes_settled_boundary
 * @features connectivity offline
 * @dimensions browser-state transitions settled-boundary
 */
function browserConnectivityChanged(browser) {
	updateConnectivity({ browser });
	return syncView({ browser });
}

/**
 * @testable true
 * @tests tests_js/test_017_main_lifecycle.py::test_suspend_current_view_deregisters_without_health_check
 * @features offline sync
 * @dimensions pagehide visibility deregistration
 */
function suspendCurrentView() {
	updateConnectivity({
		browser: navigator.onLine === false ? "offline" : "online",
		controller: navigator.serviceWorker?.controller
			? "controlled"
			: "uncontrolled",
		visibility: "hidden",
	});
	return syncView({ hidden: true });
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001d_offline.py::test_testing_mode_navigation_resets_offline_state
 * @features offline
 * @dimensions view-reset
 */
function setTestMode() {
	const mode = document
		?.querySelector("meta[name='mode']")
		?.getAttribute("content");
	if (mode === "testing") {
		window.__TESTING__ = true;
	}
}

/**
 * @testable false
 * @covered-by src/script/main.mjs::initialize
 * @reason mode metadata lookup only gates authenticated session startup work
 */
function pageMode() {
	return document?.querySelector("meta[name='mode']")?.getAttribute("content");
}

async function startAnalytics() {
	const { analytics } = await import("./shared/analytics");
	analytics.view();
}

function startErrorHandling() {
	window.addEventListener("unhandledrejection", onError);
	window.addEventListener("error", onError);
}

/**
 * @testable true
 * @tests tests_js/test_017_main_lifecycle.py::test_service_worker_registration_starts_immediately
 * @pair startup:interaction-ready
 * @pair service-worker:registration
 */
function startServiceWorker() {
	if (!("serviceWorker" in navigator)) return;
	navigator.serviceWorker.register("/sw.js").catch(async (error) => {
		const { captureNetworkError } = await import("./shared/errors");
		captureNetworkError(error, "/sw.js", { context: "service_worker" });
	});

	navigator.serviceWorker.addEventListener("controllerchange", async () => {
		updateConnectivity({
			controller: navigator.serviceWorker?.controller
				? "controlled"
				: "uncontrolled",
		});
		const { clearRecentSearchResults } = await import("./shared/utilities");
		clearRecentSearchResults();
		syncView();
	});
}

/**
 * @testable true
 * @tests tests_js/test_017_main_lifecycle.py::test_public_page_skips_authenticated_lifecycle
 * @pair startup:public-boundary
 * @pair startup:deferred-lifecycle
 * @pair startup:analytics
 */
async function startAuthenticatedLifecycle() {
	startErrorHandling();

	const [{ initializeLogoutForms }, { updateUserData }] = await Promise.all([
		import("./shared/logout"),
		import("./shared/user"),
	]);
	initializeLogoutForms();
	void startAnalytics();
	void syncView();

	document.addEventListener("visibilitychange", () => {
		document.hidden ? suspendCurrentView() : syncView();
	});
	window.addEventListener("offline", () =>
		browserConnectivityChanged("offline"),
	);
	window.addEventListener("online", () => browserConnectivityChanged("online"));
	window.addEventListener("blur", suspendCurrentView);
	window.addEventListener("focus", () => syncView());
	window.addEventListener("pagehide", suspendCurrentView);
	window.addEventListener("pageshow", (event) => {
		syncView({ force: event.persisted });
	});

	updateUserData();
}

/**
 * @testable infrastructure
 */
function initialize() {
	if (window.__INITIALIZED__) return;
	window.__INITIALIZED__ = true;
	setTestMode();
	const mode = pageMode();
	// Registration is fire-and-forget, but the controller/cache boundary is
	// foundational infrastructure. Establish it before view startup instead of
	// introducing it later during live interaction.
	startServiceWorker();
	if (mode === "public") {
		void getView();
		startErrorHandling();
		void startAnalytics();
		return;
	}
	void startAuthenticatedLifecycle();
}

document.readyState === "loading"
	? document.addEventListener("DOMContentLoaded", initialize, { once: true })
	: initialize();
