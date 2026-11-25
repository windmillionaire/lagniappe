import BROWSER_PROTOCOL from "../../../config/browser_protocol.json" with {
	type: "json",
};
import type { UpstreamRetryOutcome } from "../types/api.d.ts";
import type { ConnectivitySnapshot } from "./connectivity.ts";

export const BROWSER_PROTOCOL_ID = BROWSER_PROTOCOL.id;
export const BROWSER_PROTOCOL_VERSION = BROWSER_PROTOCOL.version;

export const WORKER_MESSAGES = Object.freeze({ ...BROWSER_PROTOCOL.messages });

type UpstreamMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface UpstreamUnavailableState {
	// The protocol has always accepted status values coercible to a number.
	status: unknown;
	method: UpstreamMethod;
	route_class: string;
	server: string;
	trace_header_present: boolean;
	timestamp: string;
	online: boolean;
	service_worker: ConnectivitySnapshot["controller"];
	stale: boolean;
	outcome_uncertain: boolean;
	retry_outcome: UpstreamRetryOutcome;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isMember<T extends string>(
	choices: readonly T[],
	value: unknown,
): value is T {
	return (
		typeof value === "string" && choices.some((choice) => choice === value)
	);
}

export function validateConnectivityState(
	state: unknown,
): state is ConnectivitySnapshot {
	if (!isRecord(state)) return false;
	return (
		isMember(["online", "offline"], state.browser) &&
		isMember(["unknown", "online", "offline"], state.server) &&
		isMember(["visible", "hidden"], state.visibility) &&
		isMember(["controlled", "uncontrolled"], state.controller)
	);
}

export function connectivityMessage(state: unknown) {
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

const UPSTREAM_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
const UPSTREAM_STATUSES = new Set([500, 502, 503, 504]);
const UPSTREAM_RETRY_OUTCOMES = [
	"not_attempted",
	"failed",
	"recovered",
	"service_worker",
] as const;

export function validateUpstreamUnavailableState(
	state: unknown,
): state is UpstreamUnavailableState {
	if (!isRecord(state)) return false;
	return (
		UPSTREAM_STATUSES.has(Number(state.status)) &&
		isMember(UPSTREAM_METHODS, state.method) &&
		typeof state.route_class === "string" &&
		/^[a-z-]{1,32}$/.test(state.route_class) &&
		typeof state.server === "string" &&
		state.server.length <= 128 &&
		typeof state.trace_header_present === "boolean" &&
		typeof state.timestamp === "string" &&
		typeof state.online === "boolean" &&
		isMember(["controlled", "uncontrolled"], state.service_worker) &&
		typeof state.stale === "boolean" &&
		typeof state.outcome_uncertain === "boolean" &&
		isMember(UPSTREAM_RETRY_OUTCOMES, state.retry_outcome)
	);
}

export function upstreamUnavailableMessage(state: unknown) {
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
