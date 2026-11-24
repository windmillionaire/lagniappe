import BROWSER_PROTOCOL from "../../../config/browser_protocol.json" with {
	type: "json",
};

export type ConnectivitySnapshot = Readonly<{
	browser: "online" | "offline";
	server: "unknown" | "online" | "offline";
	visibility: "visible" | "hidden";
	controller: "controlled" | "uncontrolled";
}>;

export type ConnectivityPatch = Partial<ConnectivitySnapshot>;

const DEFAULT_STATE: ConnectivitySnapshot = Object.freeze({
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
 */
export class ConnectivityState {
	declare private _state: ConnectivitySnapshot;

	constructor(initial: ConnectivityPatch = {}) {
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

	transition(patch: ConnectivityPatch = {}): ConnectivitySnapshot {
		const next: Record<string, string> = { ...this._state };
		for (const [field, value] of Object.entries<string>(patch)) {
			const allowed =
				BROWSER_PROTOCOL.connectivity[field as keyof ConnectivitySnapshot];
			if (!allowed?.includes(value)) {
				throw new TypeError(`Invalid connectivity ${field}: ${value}`);
			}
			next[field] = value;
		}
		// The previous snapshot is complete and each changed value was validated.
		this._state = Object.freeze(next) as ConnectivitySnapshot;
		return this.snapshot();
	}
}

const browserOnline =
	typeof navigator === "undefined" || navigator.onLine !== false;
const visible = typeof document === "undefined" || document.hidden !== true;
const controlled = Boolean(
	typeof navigator !== "undefined" && navigator.serviceWorker?.controller,
);

export const connectivity = new ConnectivityState({
	browser: browserOnline ? "online" : "offline",
	visibility: visible ? "visible" : "hidden",
	controller: controlled ? "controlled" : "uncontrolled",
});
