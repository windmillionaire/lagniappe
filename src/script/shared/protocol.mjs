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
 * @features browser-protocol
 * @dimensions connectivity validation
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
 * @tests tests_js/test_021_browser_protocol.py::test_browser_protocol_contains_only_connectivity_messages
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_messages_are_versioned_and_validated
 * @features browser-protocol
 * @dimensions connectivity-only connectivity producer version envelope
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
