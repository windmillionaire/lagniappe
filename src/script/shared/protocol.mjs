import BROWSER_PROTOCOL from "../../../config/browser_protocol.json";

export const BROWSER_PROTOCOL_ID = BROWSER_PROTOCOL.id;
export const BROWSER_PROTOCOL_VERSION = BROWSER_PROTOCOL.version;
export const EVENTS = Object.freeze({ ...BROWSER_PROTOCOL.events });
export const WORKER_MESSAGES = Object.freeze({ ...BROWSER_PROTOCOL.messages });

const SERVER_CHANGE_TYPES_WITH_KEYS = new Set([
	"delete",
	"extract-complete",
	"star",
	"summarize-complete",
	"unstar",
]);

/**
 * @testable false
 * @covered-by src/script/shared/protocol.mjs::validatePublicEvent
 * @covered-by src/script/shared/protocol.mjs::validateConnectivityState
 * @reason private object-shape primitive exercised through the public validators
 */
function isRecord(value) {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * @testable false
 * @covered-by src/script/shared/protocol.mjs::validatePublicEvent
 * @reason private identifier primitive exercised through public event schemas
 */
function hasIdentifier(value) {
	return typeof value === "string" && value.trim().length > 0;
}

/**
 * @testable false
 * @covered-by src/script/shared/protocol.mjs::validatePublicEvent
 * @reason private server-change routing is owned by the public event validator
 */
function validServerChange(detail) {
	if (!isRecord(detail) || !hasIdentifier(detail.type)) return false;
	if (SERVER_CHANGE_TYPES_WITH_KEYS.has(detail.type)) {
		return hasIdentifier(detail.key);
	}
	if (detail.type === "deferred-complete") {
		const validOperation =
			detail.operation === undefined || hasIdentifier(detail.operation);
		const validRevision =
			detail.revision === undefined ||
			(Number.isInteger(Number(detail.revision)) &&
				Number(detail.revision) >= 0);
		return (
			hasIdentifier(detail.source_widget) &&
			hasIdentifier(detail.destination) &&
			validOperation &&
			validRevision
		);
	}
	return false;
}

/**
 * @testable false
 * @covered-by src/script/shared/protocol.mjs::validatePublicEvent
 * @reason private sync identifier routing is owned by the public event validator
 */
function validSyncUpdate(detail) {
	const update = detail?.update;
	if (!isRecord(update)) return false;
	return hasIdentifier(update.sync_id);
}

/**
 * Validate the public window-event payloads that may cross worker or provider
 * boundaries. Element-private DOM events intentionally do not use this API.
 *
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_public_event_contract_accepts_current_messages
 * @tests tests_js/test_021_browser_protocol.py::test_public_event_contract_rejects_unknown_or_malformed_messages
 * @features browser-protocol
 * @dimensions notification server-change sync-update import-progress validation identifiers malformed-payload unknown-event
 */
export function validatePublicEvent(type, detail) {
	if (type === EVENTS.NOTIFICATION) {
		return isRecord(detail) && hasIdentifier(detail.html);
	}
	if (type === EVENTS.SERVER_CHANGE) return validServerChange(detail);
	if (type === EVENTS.SYNC_UPDATE) return validSyncUpdate(detail);
	if (type === EVENTS.IMPORT_RESULT) {
		return (
			isRecord(detail) &&
			hasIdentifier(detail.key) &&
			Number.isInteger(Number(detail.count)) &&
			Number(detail.count) >= 0
		);
	}
	if (
		[
			EVENTS.IMPORT_COMPLETE,
			EVENTS.IMPORT_STOPPED,
			EVENTS.IMPORT_ERROR,
		].includes(type)
	) {
		return isRecord(detail) && hasIdentifier(detail.key);
	}
	return false;
}

/**
 * Parse and validate a versioned service-worker message before it becomes a
 * public window CustomEvent.
 *
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_public_event_contract_accepts_current_messages
 * @tests tests_js/test_021_browser_protocol.py::test_public_event_contract_rejects_unknown_or_malformed_messages
 * @features browser-protocol
 * @dimensions envelope version strict-version validation incompatible-version malformed-payload unknown-event identifiers
 */
export function parseServiceWorkerMessage(data) {
	if (!isRecord(data) || !hasIdentifier(data.type)) return null;

	if (
		data.protocol !== BROWSER_PROTOCOL_ID ||
		Number(data.protocol_version) !== BROWSER_PROTOCOL_VERSION
	) {
		return null;
	}

	let detail;
	if (data.message === undefined) {
		detail = { ...data };
		delete detail.protocol;
		delete detail.protocol_version;
	} else {
		detail = data.message;
		if (typeof detail === "string") {
			try {
				detail = JSON.parse(detail);
			} catch {
				// Validation below rejects plain text for the owned public events.
			}
		}
	}

	if (!validatePublicEvent(data.type, detail)) return null;
	return {
		type: data.type,
		detail,
		version: BROWSER_PROTOCOL_VERSION,
	};
}

/**
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_messages_are_versioned_and_validated
 * @features connectivity
 * @dimensions worker-message state-validation version
 */
export function validateConnectivityState(state) {
	if (!isRecord(state)) return false;
	return Object.entries(BROWSER_PROTOCOL.connectivity).every(
		([field, values]) => {
			return values.includes(state[field]);
		},
	);
}

/**
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_messages_are_versioned_and_validated
 * @features connectivity
 * @dimensions worker-message producer version
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
