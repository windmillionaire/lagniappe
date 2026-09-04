/*! Third-party licenses: /third-party-licenses.txt */
import { B as BROWSER_PROTOCOL } from './connectivity.js?v=b052d07c';

const BROWSER_PROTOCOL_ID = BROWSER_PROTOCOL.id;
const BROWSER_PROTOCOL_VERSION = BROWSER_PROTOCOL.version;
const WORKER_MESSAGES = Object.freeze({ ...BROWSER_PROTOCOL.messages });

/**
 * @testable false
 * @covered-by src/script/shared/protocol.mjs::validateConnectivityState
 * @reason record-shape guard is exercised through connectivity validation
 */
function isRecord(value) {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_messages_are_versioned_and_validated
 * @matrix browser-protocol : connectivity validation
 */
function validateConnectivityState(state) {
	if (!isRecord(state)) return false;
	return (
		["online", "offline"].includes(state.browser) &&
		["unknown", "online", "offline"].includes(state.server) &&
		["visible", "hidden"].includes(state.visibility) &&
		["controlled", "uncontrolled"].includes(state.controller)
	);
}

/**
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_browser_protocol_contains_versioned_worker_messages
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_messages_are_versioned_and_validated
 * @matrix browser-protocol : connectivity envelope producer version
 */
function connectivityMessage(state) {
	if (!validateConnectivityState(state)) {
		throw new TypeError("Invalid connectivity state");
	}
	return {
		protocol: BROWSER_PROTOCOL_ID,
		protocol_version: BROWSER_PROTOCOL_VERSION,
		type: WORKER_MESSAGES.CONNECTIVITY,
		state: { ...state },
	};
}

const UPSTREAM_STATUSES = new Set([500, 502, 503, 504]);
const UPSTREAM_ERROR_HEADER = "X-Lagniappe-Error";
const UPSTREAM_UNAVAILABLE_HEADER = "X-Lagniappe-Upstream-Unavailable";
const UPSTREAM_STATUS_HEADER = "X-Lagniappe-Upstream-Status";
const STALE_CACHE_HEADER = "X-Lagniappe-Stale-Cache";
const UPSTREAM_RETRY_DELAY_MS = 500;
const REPORT_COOLDOWN_MS = 5 * 60 * 1000;
const MAX_SERVER_LENGTH = 128;
const ROUTE_CLASSES = new Set([
	"admin",
	"analytics",
	"categories",
	"files",
	"filters",
	"forms",
	"home",
	"internal",
	"manual",
	"messages",
	"pages",
	"process",
	"projects",
	"public",
	"reports",
	"root",
	"tasks",
	"testing",
	"users",
]);

const _reported = new Map();
let _retry = null;
let _retrying = false;
let _clientInstalled = false;

/**
 * @testable false
 * @covered-by src/script/shared/upstreamUnavailable.mjs::receiveUpstreamUnavailable
 * @covered-by src/script/shared/upstreamUnavailable.mjs::receiveUpstreamUnavailableMessage
 * @reason controlled-client state validation is exercised through the message receiver
 */
function _validWorkerDetails(details) {
	return Boolean(
		details &&
			UPSTREAM_STATUSES.has(Number(details.status)) &&
			["GET", "POST", "PUT", "PATCH", "DELETE"].includes(details.method) &&
			typeof details.route_class === "string" &&
			/^[a-z-]{1,32}$/.test(details.route_class) &&
			typeof details.server === "string" &&
			details.server.length <= 128 &&
			typeof details.trace_header_present === "boolean" &&
			typeof details.timestamp === "string" &&
			typeof details.online === "boolean" &&
			["controlled", "uncontrolled"].includes(details.service_worker) &&
			typeof details.stale === "boolean" &&
			typeof details.outcome_uncertain === "boolean" &&
			["not_attempted", "failed", "recovered", "service_worker"].includes(
				details.retry_outcome,
			),
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/upstreamUnavailable.mjs::isUpstreamUnavailableResponse
 * @reason origin resolution is exercised through the public response classifier
 */
function _sameOrigin(url) {
	try {
		const base = window.location.href || `${window.location.origin}/`;
		return new URL(url, base).origin === window.location.origin;
	} catch {
		return false;
	}
}

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_upstream_diagnostics_are_bounded_private_and_deduplicated
 * @matrix error-tracking request-errors : privacy route-class upstream-unavailable
 */
function upstreamRouteClass(url) {
	try {
		const base = window.location.href || `${window.location.origin}/`;
		const pathname = new URL(url, base).pathname;
		if (pathname === "/") return "root";
		const segment = pathname.split("/").filter(Boolean)[0] || "root";
		if (segment === "l") return "internal";
		return ROUTE_CLASSES.has(segment) ? segment : "other";
	} catch {
		return "other";
	}
}

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_all_unmarked_upstream_html_statuses_are_classified_without_dom_replacement
 * @tests tests_js/test_009_request_csrf.py::test_application_marked_html_error_keeps_existing_behavior
 * @matrix request-errors : application-error-marker classification upstream-unavailable
 */
function isUpstreamUnavailableResponse(response, url) {
	if (response?.headers?.get(UPSTREAM_UNAVAILABLE_HEADER) === "true") {
		return true;
	}
	return Boolean(
		response &&
			_sameOrigin(url) &&
			UPSTREAM_STATUSES.has(response.status) &&
			response.headers.get("content-type")?.includes("text/html") &&
			!response.headers.get(UPSTREAM_ERROR_HEADER),
	);
}

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_all_unmarked_upstream_html_statuses_are_classified_without_dom_replacement
 * @tests tests_js/test_009_request_csrf.py::test_failed_get_preserves_dom_and_exposes_safe_banner_retry
 * @tests tests_js/test_009_request_csrf.py::test_mutation_upstream_failure_is_uncertain_and_never_replayed
 * @matrix request-errors : classification dom-preservation explicit-retry mutation no-replay outcome-uncertain upstream-unavailable
 */
async function handleUpstreamResponse(
	response,
	{
		method,
		url,
		retryUpstream = true,
		fetchResponse,
		retryCurrent,
		retryOriginal,
	},
) {
	let upstreamFailure = isUpstreamUnavailableResponse(response, url)
		? response
		: null;
	let retryOutcome = "not_attempted";
	if (!upstreamFailure) {
		if (response.ok || response.status === 304) noteFreshApplicationResponse();
		return { response };
	}

	if (method === "GET" && retryUpstream) {
		await new Promise((resolve) =>
			setTimeout(resolve, UPSTREAM_RETRY_DELAY_MS),
		);
		response = await fetchResponse();
		retryOutcome = isUpstreamUnavailableResponse(response, url)
			? "failed"
			: "recovered";
		if (retryOutcome === "recovered") {
			reportUpstreamUnavailable(
				upstreamUnavailableDetails(upstreamFailure, {
					method,
					url,
					retryOutcome,
				}),
			);
			if (response.ok || response.status === 304)
				noteFreshApplicationResponse();
			return { response };
		}
		upstreamFailure = response;
	}

	const details = upstreamUnavailableDetails(upstreamFailure, {
		method,
		url,
		retryOutcome,
	});
	const outcomeUncertain = method !== "GET";
	reportUpstreamUnavailable(details);
	showUpstreamUnavailable(
		{ stale: details.stale, outcomeUncertain },
		outcomeUncertain ? retryCurrent : retryOriginal,
	);
	return {
		result: {
			ok: false,
			error: "The application server is temporarily unavailable.",
			code: "upstream_instance_unavailable",
			status: details.status,
			upstreamUnavailable: true,
			stale: details.stale,
			retryable: method === "GET",
			outcomeUncertain,
			retryOutcome,
		},
	};
}

/**
 * @testable false
 * @covered-by src/script/shared/upstreamUnavailable.mjs::upstreamUnavailableDetails
 * @covered-by src/script/shared/upstreamUnavailable.mjs::reportUpstreamUnavailable
 * @reason server sanitization is asserted through bounded diagnostic payloads
 */
function _boundedServer(value) {
	return String(value || "")
		.replace(/[^\x20-\x7E]/g, "")
		.slice(0, MAX_SERVER_LENGTH);
}

/**
 * @testable false
 * @covered-by src/script/shared/upstreamUnavailable.mjs::upstreamUnavailableDetails
 * @covered-by src/script/shared/upstreamUnavailable.mjs::receiveUpstreamUnavailable
 * @reason release metadata is asserted through browser diagnostic events
 */
function _releaseMetadata() {
	const banner = document.querySelector("[data-role='upstream-unavailable']");
	return {
		build: String(banner?.dataset.build || "").slice(0, 64),
		release: String(banner?.dataset.release || "").slice(0, 64),
	};
}

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_upstream_diagnostics_are_bounded_private_and_deduplicated
 * @matrix error-tracking request-errors : privacy response-metadata upstream-unavailable
 */
function upstreamUnavailableDetails(
	response,
	{
		method = "GET",
		url = "/",
		stale = null,
		retryOutcome = "not_attempted",
	} = {},
) {
	const originalStatus = Number(
		response.headers.get(UPSTREAM_STATUS_HEADER) || response.status,
	);
	return {
		status: UPSTREAM_STATUSES.has(originalStatus)
			? originalStatus
			: response.status,
		method: String(method).toUpperCase(),
		route_class: upstreamRouteClass(url),
		server: _boundedServer(response.headers.get("Server")),
		trace_header_present: Boolean(
			response.headers.get("X-Cloud-Trace-Context") ||
				response.headers.get("Traceparent"),
		),
		timestamp: new Date().toISOString(),
		online: navigator.onLine !== false,
		service_worker: navigator.serviceWorker?.controller
			? "controlled"
			: "uncontrolled",
		stale:
			stale === null
				? response.headers.get(STALE_CACHE_HEADER) === "true"
				: Boolean(stale),
		retry_outcome: retryOutcome,
		..._releaseMetadata(),
	};
}

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_upstream_diagnostics_are_bounded_private_and_deduplicated
 * @matrix error-tracking request-errors : cooldown fingerprint privacy upstream-unavailable warning
 */
function reportUpstreamUnavailable(details) {
	const diagnostic = {
		status: UPSTREAM_STATUSES.has(Number(details.status))
			? Number(details.status)
			: 503,
		method: ["GET", "POST", "PUT", "PATCH", "DELETE"].includes(
			String(details.method).toUpperCase(),
		)
			? String(details.method).toUpperCase()
			: "GET",
		route_class: ROUTE_CLASSES.has(details.route_class)
			? details.route_class
			: "other",
		server: _boundedServer(details.server),
		trace_header_present: details.trace_header_present === true,
		timestamp: String(details.timestamp || new Date().toISOString()).slice(
			0,
			40,
		),
		online: details.online !== false,
		service_worker:
			details.service_worker === "controlled" ? "controlled" : "uncontrolled",
		build: String(details.build || "").slice(0, 64),
		release: String(details.release || "").slice(0, 64),
		stale: details.stale === true,
		retry_outcome: [
			"not_attempted",
			"failed",
			"recovered",
			"service_worker",
		].includes(details.retry_outcome)
			? details.retry_outcome
			: "not_attempted",
	};
	const key = `${diagnostic.method}:${diagnostic.route_class}`;
	const now = Date.now();
	if (now - (_reported.get(key) || 0) < REPORT_COOLDOWN_MS) return false;
	_reported.set(key, now);

	window.Sentry?.captureMessage?.(
		"Application server temporarily unavailable",
		{
			level: "warning",
			fingerprint: ["upstream_instance_unavailable"],
			tags: {
				failure_code: "upstream_instance_unavailable",
				method: diagnostic.method,
				route_class: diagnostic.route_class,
			},
			contexts: { upstream_instance_unavailable: diagnostic },
		},
	);
	return true;
}

/**
 * @testable false
 * @covered-by src/script/shared/upstreamUnavailable.mjs::showUpstreamUnavailable
 * @reason DOM state rendering is asserted through the public banner boundary
 */
function _renderBanner(details) {
	const banner = document.querySelector("[data-role='upstream-unavailable']");
	if (!banner) return;
	const message = banner.querySelector(
		"[data-role='upstream-unavailable-message']",
	);
	const uncertain = details.outcomeUncertain === true;
	const stale = details.stale === true;
	if (message) {
		message.textContent = uncertain
			? "The server is temporarily unavailable. We could not confirm whether your change was saved. Check the current state before trying it again."
			: stale
				? "The server is temporarily unavailable. You are viewing saved content; your current work is still here."
				: "The server is temporarily unavailable. Your current page and unsaved work are unchanged.";
	}
	banner.dataset.visible = "true";
	banner.dataset.stale = stale ? "true" : "false";
	banner.dataset.outcomeUncertain = uncertain ? "true" : "false";
	banner.setAttribute("aria-hidden", "false");
}

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_failed_get_preserves_dom_and_exposes_safe_banner_retry
 * @matrix request-errors : banner dom-preservation retry upstream-unavailable
 */
function showUpstreamUnavailable(details, retry = null) {
	_retry = typeof retry === "function" ? retry : null;
	_renderBanner(details);
}

/**
 * Clear only at a fresh application-response boundary.
 *
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_failed_get_preserves_dom_and_exposes_safe_banner_retry
 * @matrix request-errors : banner fresh-response upstream-unavailable
 */
function noteFreshApplicationResponse() {
	const banner = document.querySelector("[data-role='upstream-unavailable']");
	if (!banner) return;
	_retry = null;
	banner.dataset.visible = "false";
	banner.dataset.stale = "false";
	banner.dataset.outcomeUncertain = "false";
	banner.setAttribute("aria-hidden", "true");
}

/**
 * @testable true
 * @tests tests_js/test_017_main_lifecycle.py::test_upstream_unavailable_worker_message_shows_retryable_banner
 * @matrix browser-protocol request-errors service-worker : banner client-message upstream-unavailable
 */
function receiveUpstreamUnavailable(details, retry = null) {
	if (!_validWorkerDetails(details)) return false;
	reportUpstreamUnavailable({ ...details, ..._releaseMetadata() });
	showUpstreamUnavailable(
		{
			stale: details.stale,
			outcomeUncertain: details.outcome_uncertain,
		},
		retry,
	);
	return true;
}

/**
 * @testable true
 * @tests tests_js/test_017_main_lifecycle.py::test_upstream_unavailable_worker_message_shows_retryable_banner
 * @matrix browser-protocol request-errors service-worker : banner client-message retry upstream-unavailable validation
 */
function receiveUpstreamUnavailableMessage(message) {
	if (!_validWorkerDetails(message?.state)) return false;
	return receiveUpstreamUnavailable(message.state, async () => {
		const { request } = await import('./foundation.js?v=b052d07c').then(function (n) { return n.o; });
		return request.get(window.location.pathname, null, {
			replaceErrorPage: false,
			retryUpstream: false,
		});
	});
}

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_failed_get_preserves_dom_and_exposes_safe_banner_retry
 * @tests tests_js/test_009_request_csrf.py::test_mutation_upstream_failure_is_uncertain_and_never_replayed
 * @matrix request-errors : banner explicit-retry no-replay upstream-unavailable
 */
function installUpstreamUnavailableBanner() {
	if (!_clientInstalled) {
		_clientInstalled = true;
		navigator.serviceWorker?.addEventListener?.("message", (event) => {
			const data = event.data;
			if (
				data?.protocol === BROWSER_PROTOCOL_ID &&
				Number(data.protocol_version) === BROWSER_PROTOCOL_VERSION &&
				data.type === WORKER_MESSAGES.UPSTREAM_UNAVAILABLE
			) {
				receiveUpstreamUnavailableMessage(data);
			}
		});
		if (window.__TESTING__) {
			window.__TEST_UPSTREAM_UNAVAILABLE__ = async () => {
				const { request } = await import('./foundation.js?v=b052d07c').then(function (n) { return n.o; });
				return request.get("/testing/upstream-unavailable");
			};
		}
	}
	const button = document.querySelector(
		"[data-role='upstream-unavailable-retry']",
	);
	if (!button || button.dataset.initialized === "true") return;
	button.dataset.initialized = "true";
	button.addEventListener("click", async () => {
		if (_retrying || !_retry) return;
		_retrying = true;
		button.disabled = true;
		button.textContent = "Trying…";
		try {
			await _retry();
		} finally {
			_retrying = false;
			button.disabled = false;
			button.textContent = "Try again";
		}
	});
}

export { connectivityMessage as c, handleUpstreamResponse as h, installUpstreamUnavailableBanner as i };
