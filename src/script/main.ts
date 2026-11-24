import "../style/main.css";

import {
	type ConnectivityPatch,
	type ConnectivitySnapshot,
	connectivity,
} from "./shared/connectivity.ts";
import { applyNotificationStateHeader } from "./shared/notificationState.ts";
import { connectivityMessage } from "./shared/protocol.ts";
import { installUpstreamUnavailableBanner } from "./shared/upstreamUnavailable.ts";
import { type ActiveView, loadView } from "./viewRegistry.ts";
import type { ViewRoot, ViewSyncOptions } from "./views/base/shell.ts";

declare global {
	interface Window {
		__CONNECTIVITY__?: ConnectivitySnapshot;
		__CONNECTIVITY_READY__?: Promise<void>;
		__INITIALIZED__?: boolean;
		__NAVIGATION_TRANSITION_READY__?: Promise<void>;
		__NAVIGATION_TRANSITION_SETTLED__?: boolean;
		__PING_PENDING__?: Promise<boolean> | null;
	}
}

type LifecycleSyncOptions = ViewSyncOptions & {
	browser?: ConnectivitySnapshot["browser"];
};

async function onError(event: ErrorEvent | PromiseRejectionEvent) {
	const {
		captureError,
		isSkippedViewTransitionError,
		isTransientNetworkError,
	} = await import("./shared/errors.ts");
	const eventError: unknown = "error" in event ? event.error : undefined;
	const rejection: unknown = "reason" in event ? event.reason : undefined;
	const message = "message" in event ? event.message : undefined;
	const error = eventError || rejection || message || "Unknown error";
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

function publishNavigationTransitionReadiness() {
	// A parser-time observer can publish the exact `pagereveal` boundary before
	// this deferred module evaluates. Preserve it when available.
	if (window.__NAVIGATION_TRANSITION_READY__) return;
	window.__NAVIGATION_TRANSITION_SETTLED__ = false;
	window.__NAVIGATION_TRANSITION_READY__ = new Promise<void>((resolve) => {
		const publishWhenInactive = () => {
			const transition = document.activeViewTransition;
			if (transition) {
				Promise.resolve(transition.finished)
					.catch(() => undefined)
					.then(() => requestAnimationFrame(publishWhenInactive));
				return;
			}
			window.__NAVIGATION_TRANSITION_SETTLED__ = true;
			resolve();
		};

		if (document.activeViewTransition) {
			publishWhenInactive();
			return;
		}

		// Cross-document transitions begin after `pagereveal` and the first
		// rendered frame. Sample after that paint so an initially absent active
		// transition cannot be mistaken for a settled navigation.
		requestAnimationFrame(() => requestAnimationFrame(publishWhenInactive));
	});
}

// Product startup remains independent; browser tests can await visual
// completion after the destination view publishes structural readiness.
publishNavigationTransitionReadiness();

let __activeView: Promise<ActiveView | null> | null = null;
const getView = async () => {
	const viewElt = document.querySelector<ViewRoot>("[lp-view]");
	if (!viewElt) return null;

	if (viewElt._lp_view) return viewElt._lp_view;

	if (__activeView) return await __activeView;

	const disconnected = () => viewElt.isConnected === false;
	__activeView = (async () => {
		const viewModule = await loadView(viewElt.dataset.kind);
		if (!viewModule) {
			const { captureError } = await import("./shared/errors.ts");
			captureError(
				new Error(`Unknown view kind: ${viewElt.dataset.kind || "missing"}`),
				viewElt,
				{ view_kind: viewElt.dataset.kind || "" },
			);
			return null;
		}

		if (disconnected()) return null;
		const view = new viewModule.default(viewElt);
		await view.init();
		if (view._destroyed || disconnected()) return null;
		view.publish?.();
		return view;
	})();

	return await __activeView;
};

let _ping: Promise<boolean> | null = null;
// Include browser scheduling and connection setup, not just handler latency.
const SERVER_HEALTH_TIMEOUT_MS = 5_000;

export async function pingServer() {
	if (_ping) return _ping;

	_ping = (async () => {
		const controller = new AbortController();
		const timeoutId = setTimeout(
			() => controller.abort(),
			SERVER_HEALTH_TIMEOUT_MS,
		);
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
	const pending = _ping;
	window.__PING_PENDING__ = pending;
	void pending.finally(() => {
		if (window.__PING_PENDING__ === pending) window.__PING_PENDING__ = null;
	});

	return pending;
}

let _pollTimeout: ReturnType<typeof setTimeout> | null = null;

const KEEP_AWAKE_MS = 10 * 60 * 1000;
const POLL_MS = 2 * 1000;
const OFFLINE_POLL_MS = 5 * 1000;

function stopPolling() {
	if (!_pollTimeout) return;
	clearTimeout(_pollTimeout);
	_pollTimeout = null;
}

function pollServer(online: boolean) {
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

let _sync: Promise<void> | null = null;
let _syncPending: LifecycleSyncOptions | null = null;

/**
 * Treat a visible tab in an unfocused browser window as inactive. Focus runs
 * an explicit catch-up cycle, so ordinary periodic work can stop while the
 * user is working elsewhere. Rendered deferred operations receive the bounded
 * visible-blur exception downstream.
 *
 */
function documentInactive() {
	return document.hidden || document.hasFocus?.() === false;
}

function updateConnectivity(patch: ConnectivityPatch) {
	const state = connectivity.transition(patch);
	window.__CONNECTIVITY__ = state;
	navigator.serviceWorker?.controller?.postMessage(connectivityMessage(state));
	return state;
}

function queueSync({
	hidden,
	blurred,
	blurredAt,
	force = false,
	browser,
}: LifecycleSyncOptions = {}) {
	const pendingHidden =
		hidden === undefined ? _syncPending?.hidden : Boolean(hidden);
	const pendingBlurred =
		blurred === undefined ? _syncPending?.blurred : Boolean(blurred);
	const pendingBlurredAt =
		blurredAt === undefined ? _syncPending?.blurredAt : blurredAt;
	const pendingBrowser =
		browser === undefined ? _syncPending?.browser : browser;

	_syncPending = {
		force: Boolean(_syncPending?.force || force),
	};
	if (pendingHidden !== undefined) _syncPending.hidden = pendingHidden;
	if (pendingBlurred !== undefined) _syncPending.blurred = pendingBlurred;
	if (pendingBlurredAt !== undefined) _syncPending.blurredAt = pendingBlurredAt;
	if (pendingBrowser !== undefined) _syncPending.browser = pendingBrowser;
}

async function syncViewOnce({
	hidden = documentInactive(),
	blurred = hidden && !document.hidden && document.hasFocus?.() === false,
	blurredAt = blurred ? Date.now() : null,
	force = false,
	browser = navigator.onLine === false ? "offline" : "online",
}: LifecycleSyncOptions = {}) {
	const controller = navigator.serviceWorker?.controller
		? "controlled"
		: "uncontrolled";
	// Publish before view loading can issue a cached GET. A navigation may have
	// canceled the previous document's ping and left its worker state offline.
	updateConnectivity({
		browser,
		controller,
		visibility: hidden ? "hidden" : "visible",
	});
	const viewPromise = getView();
	if (hidden) {
		stopPolling();
		const view = await viewPromise;
		if (view?.sync) {
			await view.sync({ hidden: true, blurred, blurredAt, force });
		}
		return;
	}

	const online = await pingServer();

	updateConnectivity({ server: online ? "online" : "offline" });
	pollServer(online);

	const view = await viewPromise;
	if (view?.sync) {
		await view.sync({ hidden, blurred: false, blurredAt: null, force });
	}
}

export async function syncView(options: LifecycleSyncOptions = {}) {
	queueSync(options);
	if (_sync) return _sync;

	_sync = (async () => {
		let firstError: unknown = null;
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
 */
function browserConnectivityChanged(browser: ConnectivitySnapshot["browser"]) {
	updateConnectivity({ browser });
	return syncView({ browser });
}

export function suspendCurrentView({
	blurred = false,
	blurredAt = blurred ? Date.now() : null,
}: Pick<ViewSyncOptions, "blurred" | "blurredAt"> = {}) {
	updateConnectivity({
		browser: navigator.onLine === false ? "offline" : "online",
		controller: navigator.serviceWorker?.controller
			? "controlled"
			: "uncontrolled",
		visibility: "hidden",
	});
	return syncView({ hidden: true, blurred, blurredAt });
}

function setTestMode() {
	const mode = document
		?.querySelector("meta[name='mode']")
		?.getAttribute("content");
	if (mode === "testing") {
		window.__TESTING__ = true;
	}
}

function pageMode() {
	return document?.querySelector("meta[name='mode']")?.getAttribute("content");
}

async function startAnalytics() {
	const { analytics } = await import("./shared/analytics.ts");
	analytics.view();
}

function startErrorHandling() {
	window.addEventListener("unhandledrejection", onError);
	window.addEventListener("error", onError);
}

function startServiceWorker() {
	if (!("serviceWorker" in navigator)) return;
	navigator.serviceWorker.register("/sw.js").catch(async (error) => {
		const { captureNetworkError } = await import("./shared/errors.ts");
		captureNetworkError(error, "/sw.js", { context: "service_worker" });
	});

	navigator.serviceWorker.addEventListener("controllerchange", async () => {
		updateConnectivity({
			controller: navigator.serviceWorker?.controller
				? "controlled"
				: "uncontrolled",
		});
		const { clearRecentSearchResults } = await import("./shared/storage.ts");
		clearRecentSearchResults();
		syncView();
	});
}

async function startAuthenticatedLifecycle() {
	startErrorHandling();

	const [{ initializeLogoutForms }, { updateUserData }] = await Promise.all([
		import("./shared/logout.ts"),
		import("./shared/user.ts"),
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
	window.addEventListener("blur", () =>
		suspendCurrentView({ blurred: !document.hidden }),
	);
	window.addEventListener("focus", () =>
		syncView({ hidden: false, blurred: false, blurredAt: null }),
	);
	window.addEventListener("pagehide", () => suspendCurrentView());
	window.addEventListener("pageshow", (event) => {
		syncView({ force: event.persisted });
	});

	updateUserData();
}

export function initialize() {
	if (window.__INITIALIZED__) return;
	window.__INITIALIZED__ = true;
	setTestMode();
	installUpstreamUnavailableBanner();
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
