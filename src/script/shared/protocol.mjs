import BROWSER_PROTOCOL from "../../../config/browser_protocol.json";

export const BROWSER_PROTOCOL_ID = BROWSER_PROTOCOL.id;
export const BROWSER_PROTOCOL_VERSION = BROWSER_PROTOCOL.version;
export const WORKER_MESSAGES = Object.freeze({ ...BROWSER_PROTOCOL.messages });

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
export function validateConnectivityState(state) {
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
export function connectivityMessage(state) {
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

const UPSTREAM_METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);
const UPSTREAM_STATUSES = new Set([500, 502, 503, 504]);
const UPSTREAM_RETRY_OUTCOMES = new Set([
	"not_attempted",
	"failed",
	"recovered",
	"service_worker",
]);

/**
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_upstream_unavailable_messages_are_versioned_and_privacy_bounded
 * @matrix browser-protocol request-errors : upstream-unavailable validation
 */
export function validateUpstreamUnavailableState(state) {
	if (!isRecord(state)) return false;
	return (
		UPSTREAM_STATUSES.has(Number(state.status)) &&
		UPSTREAM_METHODS.has(state.method) &&
		typeof state.route_class === "string" &&
		/^[a-z-]{1,32}$/.test(state.route_class) &&
		typeof state.server === "string" &&
		state.server.length <= 128 &&
		typeof state.trace_header_present === "boolean" &&
		typeof state.timestamp === "string" &&
		typeof state.online === "boolean" &&
		["controlled", "uncontrolled"].includes(state.service_worker) &&
		typeof state.stale === "boolean" &&
		typeof state.outcome_uncertain === "boolean" &&
		UPSTREAM_RETRY_OUTCOMES.has(state.retry_outcome)
	);
}

/**
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_upstream_unavailable_messages_are_versioned_and_privacy_bounded
 * @matrix browser-protocol request-errors : envelope privacy producer upstream-unavailable version
 */
export function upstreamUnavailableMessage(state) {
	if (!validateUpstreamUnavailableState(state)) {
		throw new TypeError("Invalid upstream-unavailable state");
	}
	return {
		protocol: BROWSER_PROTOCOL_ID,
		protocol_version: BROWSER_PROTOCOL_VERSION,
		type: WORKER_MESSAGES.UPSTREAM_UNAVAILABLE,
		state: {
			status: Number(state.status),
			method: state.method,
			route_class: state.route_class,
			server: state.server,
			trace_header_present: state.trace_header_present,
			timestamp: state.timestamp,
			online: state.online,
			service_worker: state.service_worker,
			stale: state.stale,
			outcome_uncertain: state.outcome_uncertain,
			retry_outcome: state.retry_outcome,
		},
	};
}
