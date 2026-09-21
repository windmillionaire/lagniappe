import assert from "node:assert/strict";
import { after } from "node:test";

export const unexpectedRequests = [];
export function unexpectedFetch(input) {
	const message = `Unexpected fetch: ${input?.url || String(input)}`;
	unexpectedRequests.push(message);
	return Promise.reject(new Error(message));
}
globalThis.fetch = unexpectedFetch;
after(() =>
	assert.deepEqual(unexpectedRequests, [], "Unaccounted network requests"),
);
