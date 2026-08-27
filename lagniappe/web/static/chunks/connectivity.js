/*! Third-party licenses: /third-party-licenses.txt */
var id = "lagniappe-browser";
var version = 3;
var messages = {
	CONNECTIVITY: "connectivity-state"
};
var connectivity$1 = {
	browser: [
		"online",
		"offline"
	],
	server: [
		"unknown",
		"online",
		"offline"
	],
	visibility: [
		"visible",
		"hidden"
	],
	controller: [
		"controlled",
		"uncontrolled"
	]
};
var BROWSER_PROTOCOL = {
	id: id,
	version: version,
	messages: messages,
	connectivity: connectivity$1
};

const DEFAULT_STATE = Object.freeze({
	browser: "online",
	server: "unknown",
	visibility: "visible",
	controller: "uncontrolled",
});

/**
 * Owns the four independent connectivity signals used by the application.
 * Server reachability remains authoritative for application requests, while
 * browser link state is a scheduling hint and unknown server state is treated
 * optimistically during startup.
 *
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_state_table_covers_lifecycle_transitions
 * @matrix connectivity : browser-state controller polling-recovery server-health startup visibility
 */
class ConnectivityState {
	constructor(initial = {}) {
		this._state = DEFAULT_STATE;
		this.transition(initial);
	}

	get online() {
		return this._state.browser === "online" && this._state.server !== "offline";
	}

	get hidden() {
		return this._state.visibility === "hidden";
	}

	snapshot() {
		return Object.freeze({ ...this._state });
	}

	transition(patch = {}) {
		const next = { ...this._state };
		for (const [field, value] of Object.entries(patch)) {
			const allowed = BROWSER_PROTOCOL.connectivity[field];
			if (!allowed?.includes(value)) {
				throw new TypeError(`Invalid connectivity ${field}: ${value}`);
			}
			next[field] = value;
		}
		this._state = Object.freeze(next);
		return this.snapshot();
	}
}

const browserOnline =
	typeof navigator === "undefined" || navigator.onLine !== false;
const visible = typeof document === "undefined" || document.hidden !== true;
const controlled = Boolean(
	typeof navigator !== "undefined" && navigator.serviceWorker?.controller,
);

const connectivity = new ConnectivityState({
	browser: browserOnline ? "online" : "offline",
	visibility: visible ? "visible" : "hidden",
	controller: controlled ? "controlled" : "uncontrolled",
});

export { BROWSER_PROTOCOL as B, connectivity as c };
