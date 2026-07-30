import "../style/main.css";

import {
	analytics,
	captureError,
	captureNetworkError,
	clearRecentSearchResults,
	connectivity,
	connectivityMessage,
	initializeLogoutForms,
	isSkippedViewTransitionError,
	updateUserData,
} from "./shared";

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::captureError
 * @reason window error-event adapter delegates filtering, context, and capture behavior to the shared error helper
 */
function onError(event) {
	const error = event.error || event.reason || event.message || "Unknown error";
	if (isSkippedViewTransitionError(error)) {
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

window.addEventListener("unhandledrejection", onError);
window.addEventListener("error", onError);

const VIEWS = {
	project: () => import("./views/project"),
	page: () => import("./views/page"),
	home: () => import("./views/home"),
	manual: () => import("./views/manual"),
	user: () => import("./views/user"),
	form: () => import("./views/base/index"),
	category: () => import("./views/base/index"),
	task: () => import("./views/base/index"),
	builder: () => import("./views/builder/builder"),
	results: () => import("./views/results"),
	file: () => import("./views/file"),
	report: () => import("./views/report"),
	analytics: () => import("./views/analytics"),
	admin: () => import("./views/admin"),
};

window.__CONNECTIVITY__ = connectivity.snapshot();

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
		const viewLoader = VIEWS[viewElt.dataset.kind];
		if (!viewLoader) {
			captureError(
				new Error(`Unknown view kind: ${viewElt.dataset.kind || "missing"}`),
				viewElt,
				{ view_kind: viewElt.dataset.kind || "" },
			);
			return null;
		}

		const viewModule = await viewLoader();
		const view = new viewModule.default(viewElt);
		return await view.init();
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
			const response = await fetch("/ping", {
				method: "HEAD",
				signal: controller.signal,
			});
			return response.ok;
		} catch {
			return false;
		} finally {
			clearTimeout(timeoutId);
			_ping = null;
		}
	})();

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
	if (window.__TESTING__) return;

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
function queueSync({ hidden, force = false } = {}) {
	const pendingHidden =
		hidden === undefined ? _syncPending?.hidden : Boolean(hidden);

	_syncPending = {
		force: Boolean(_syncPending?.force || force),
	};
	if (pendingHidden !== undefined) _syncPending.hidden = pendingHidden;
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
 * @tests tests_e2e/001_site/test_001d_offline.py::test_offline_poll_recovers_without_online_event
 * @tests tests_e2e/001_site/test_001d_offline.py::test_rapid_offline_online_transitions
 * @tests tests_e2e/001_site/test_001d_offline.py::test_testing_mode_navigation_resets_offline_state
 * @tests tests_js/test_017_main_lifecycle.py::test_rapid_sync_requests_coalesce_and_retain_forced_transition
 * @features offline
 * @dimensions server-health transitions view-reset reconnect indicator browser-state coalescing rapid-transitions
 */
async function syncViewOnce({
	hidden = documentInactive(),
	force = false,
} = {}) {
	const controller = navigator.serviceWorker?.controller
		? "controlled"
		: "uncontrolled";
	const browser = navigator.onLine === false ? "offline" : "online";
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
 * @tests tests_e2e/001_site/test_001d_offline.py::test_rapid_offline_online_transitions
 * @features offline
 * @dimensions server-health transitions
 */
async function syncView(options = {}) {
	queueSync(options);
	if (_sync) return _sync;

	_sync = (async () => {
		while (_syncPending) {
			const nextSync = _syncPending;
			_syncPending = null;
			await syncViewOnce(nextSync);
		}
	})().finally(() => {
		_sync = null;
	});

	return _sync;
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

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
 * @tests tests_e2e/001_site/test_001d_offline.py::test_testing_mode_navigation_resets_offline_state
 * @tests tests_js/test_017_main_lifecycle.py::test_controller_replacement_receives_current_versioned_connectivity_state
 * @tests tests_js/test_017_main_lifecycle.py::test_window_blur_suspends_polling_until_focus_catchup
 * @pair offline:server-health
 * @pair offline:view-reset
 * @pair connectivity:controller-replacement
 * @pair connectivity:state-publication
 * @pair connectivity:version
 * @pair service-worker:controller-replacement
 * @pair service-worker:state-publication
 * @pair service-worker:version
 * @pair polling:blur
 * @pair polling:focus
 * @pair polling:visibility
 * @pair polling:catch-up
 */
function initialize() {
	if (window.__INITIALIZED__) return;
	window.__INITIALIZED__ = true;
	setTestMode();
	initializeLogoutForms();
	analytics.view();
	syncView();

	document.addEventListener("visibilitychange", () => {
		document.hidden ? suspendCurrentView() : syncView();
	});
	window.addEventListener("offline", () => syncView());
	window.addEventListener("online", () => syncView());
	window.addEventListener("blur", suspendCurrentView);
	window.addEventListener("focus", () => syncView());
	window.addEventListener("pagehide", suspendCurrentView);
	window.addEventListener("pageshow", (e) => {
		syncView({ force: e.persisted });
	});

	if ("serviceWorker" in navigator) {
		navigator.serviceWorker.register("/sw.js").catch((error) => {
			captureNetworkError(error, "/sw.js", { context: "service_worker" });
		});

		navigator.serviceWorker.addEventListener("controllerchange", () => {
			updateConnectivity({
				controller: navigator.serviceWorker?.controller
					? "controlled"
					: "uncontrolled",
			});
			clearRecentSearchResults();
			syncView();
		});
	}

	if (pageMode() !== "public") updateUserData();
}

document.readyState === "loading"
	? document.addEventListener("DOMContentLoaded", initialize, { once: true })
	: initialize();
