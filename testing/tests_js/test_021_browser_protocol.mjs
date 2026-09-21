import assert from "node:assert/strict";
import { test } from "node:test";
import { ConnectivityState } from "../../src/script/shared/connectivity.mjs";
import {
	connectivityMessage,
	upstreamUnavailableMessage,
	validateConnectivityState,
	validateUpstreamUnavailableState,
	WORKER_MESSAGES,
} from "../../src/script/shared/protocol.mjs";

/** @matrix browser-protocol : message-types */
test("test_browser_protocol_contains_versioned_worker_messages", () => {
	const details = `Unexpected worker protocol: ${JSON.stringify(WORKER_MESSAGES)}`;
	assert.equal(Object.keys(WORKER_MESSAGES).length, 2, details);
	assert.equal(WORKER_MESSAGES.CONNECTIVITY, "connectivity-state", details);
	assert.equal(
		WORKER_MESSAGES.UPSTREAM_UNAVAILABLE,
		"upstream-unavailable",
		details,
	);
});

/** @matrix browser-protocol : connectivity envelope producer validation version */
test("test_connectivity_messages_are_versioned_and_validated", () => {
	const state = {
		browser: "online",
		server: "offline",
		visibility: "hidden",
		controller: "controlled",
	};
	assert.equal(
		validateConnectivityState(state),
		true,
		"Explicit connectivity state was rejected",
	);
	const message = connectivityMessage(state);
	const details = `Connectivity message was not versioned: ${JSON.stringify(message)}`;
	assert.equal(message.protocol, "lagniappe-browser", details);
	assert.equal(message.protocol_version, 4, details);
	assert.equal(message.type, "connectivity-state", details);
	assert.notEqual(message.state, state, details);

	for (const invalid of [
		null,
		{ ...state, server: "maybe" },
		{ browser: "online", server: "online" },
	]) {
		assert.equal(
			validateConnectivityState(invalid),
			false,
			`Invalid connectivity state was accepted: ${JSON.stringify(invalid)}`,
		);
	}
	assert.throws(
		() => connectivityMessage({ ...state, controller: "replacing" }),
		TypeError,
		"Invalid connectivity producer state was not rejected",
	);
});

/**
 * @matrix browser-protocol request-errors : envelope privacy producer upstream-unavailable validation version
 */
test("test_upstream_unavailable_messages_are_versioned_and_privacy_bounded", () => {
	const state = {
		status: 503,
		method: "GET",
		route_class: "pages",
		server: "Google Frontend",
		trace_header_present: true,
		timestamp: "2026-09-01T12:00:00.000Z",
		online: true,
		service_worker: "controlled",
		stale: false,
		outcome_uncertain: false,
		retry_outcome: "failed",
	};
	assert.equal(
		validateUpstreamUnavailableState(state),
		true,
		"Bounded upstream-unavailable state was rejected",
	);
	const message = upstreamUnavailableMessage(state);
	const details = `Upstream message was not versioned: ${JSON.stringify(message)}`;
	assert.equal(message.protocol, "lagniappe-browser", details);
	assert.equal(message.protocol_version, 4, details);
	assert.equal(message.type, "upstream-unavailable", details);
	assert.notEqual(message.state, state, details);

	for (const invalid of [
		{ ...state, status: 501 },
		{ ...state, method: "OPTIONS" },
		{ ...state, route_class: "pages/secret-id" },
		{ ...state, server: "x".repeat(129) },
	]) {
		assert.equal(
			validateUpstreamUnavailableState(invalid),
			false,
			`Invalid upstream state was accepted: ${JSON.stringify(invalid)}`,
		);
	}
	const extra = { ...state, query: "private=yes" };
	const produced = upstreamUnavailableMessage(extra);
	assert.equal(
		"query" in produced.state,
		false,
		"Producer retained an unexpected diagnostic field",
	);
});

/**
 * @matrix connectivity : browser-state controller polling-recovery server-health startup visibility
 */
test("test_connectivity_state_table_covers_lifecycle_transitions", () => {
	const state = new ConnectivityState();
	const cases = [
		{
			name: "startup",
			patch: {},
			expected: {
				browser: "online",
				server: "unknown",
				visibility: "visible",
				controller: "uncontrolled",
				online: true,
			},
		},
		{
			name: "offline browser",
			patch: { browser: "offline" },
			expected: { browser: "offline", online: false },
		},
		{
			name: "failed ping while browser online",
			patch: { browser: "online", server: "offline" },
			expected: { browser: "online", server: "offline", online: false },
		},
		{
			name: "polling recovery",
			patch: { server: "online" },
			expected: { server: "online", online: true },
		},
		{
			name: "hidden",
			patch: { visibility: "hidden" },
			expected: { visibility: "hidden", hidden: true },
		},
		{
			name: "visible with controller replacement",
			patch: { visibility: "visible", controller: "controlled" },
			expected: {
				visibility: "visible",
				controller: "controlled",
				hidden: false,
			},
		},
	];

	for (const testCase of cases) {
		const snapshot = state.transition(testCase.patch);
		for (const [field, expected] of Object.entries(testCase.expected)) {
			const actual =
				field === "online"
					? state.online
					: field === "hidden"
						? state.hidden
						: snapshot[field];
			assert.equal(
				actual,
				expected,
				`${testCase.name}: expected ${field}=${expected}, got ${actual}`,
			);
		}
	}

	assert.throws(
		() => state.transition({ server: "sometimes" }),
		TypeError,
		"Invalid state transition was accepted",
	);
});
