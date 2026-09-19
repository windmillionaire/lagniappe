import assert from "node:assert/strict";
import { test } from "node:test";

test("test_pass", () => {
	console.log('{"type":"test:fail","name":"test_pass"}');
	assert.equal(1 + 1, 2);
	assert.equal(/ordinary pattern/.test("ordinary pattern"), true);
});
test("test_fail", () => assert.deepEqual({ actual: 1 }, { expected: 2 }));
test.skip("test_skip", () => {
	throw new Error("must not run");
});
test.todo("test_todo");
test("test_timeout", async () => {
	setInterval(() => {}, 1000);
	await new Promise(() => {});
});
test("test_missing_result", () => process.exit(0));
test("test_import_error", async () => {
	await import("./does-not-exist.mjs");
});
test("test_unhandled_error", () => {
	setImmediate(() => {
		throw new Error("late exception");
	});
});
test("test_caught_network", async () => {
	await fetch("https://unexpected.test/").catch(() => {});
});
test("test_write_global", () => {
	globalThis.leakedExample = true;
});
test("test_clean_global", () =>
	assert.equal(globalThis.leakedExample, undefined));
