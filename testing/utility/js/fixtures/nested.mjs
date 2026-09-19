import { test } from "node:test";

test("test_parent", async (t) => {
	await t.test("nested", () => {});
});
