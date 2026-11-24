import assert from "node:assert/strict";
import { after, afterEach } from "node:test";

export const unexpectedRequests = [];
export function unexpectedFetch(input) {
	const message = `Unexpected fetch: ${input?.url || String(input)}`;
	unexpectedRequests.push(message);
	return Promise.reject(new Error(message));
}
globalThis.fetch = unexpectedFetch;
function assertNoUnexpectedRequests() {
	if (unexpectedRequests.length === 0) return;
	const found = unexpectedRequests.splice(0, unexpectedRequests.length);
	assert.deepEqual(found, [], "Unaccounted network requests");
}
afterEach(assertNoUnexpectedRequests);
after(assertNoUnexpectedRequests);
