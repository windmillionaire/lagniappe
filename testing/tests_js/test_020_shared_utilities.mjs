import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import {
	clearRecentSearchResults,
	localStore,
	sessionStore,
} from "../../src/script/shared/storage.mjs";
import {
	areEqual,
	debounce,
	waitForAttribute,
} from "../../src/script/shared/utilities.mjs";
import { createBrowser } from "../utility/js/environment.mjs";

function replace(t, target, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(target, name);
	Object.defineProperty(target, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(target, name, descriptor);
		else delete target[name];
	});
}

async function setupUser(t) {
	createBrowser(t);
	const geolocationCalls = [];
	const posts = [];
	let coords = { latitude: 37.7749, longitude: -122.4194 };
	let geolocationImplementation = (success) => success({ coords });
	let postImplementation = async () => ({ ok: true, userHash: "user-hash" });

	Object.defineProperty(navigator, "geolocation", {
		configurable: true,
		value: {
			getCurrentPosition(success, error, options) {
				geolocationCalls.push(options);
				geolocationImplementation(success, error);
			},
		},
	});
	t.mock.method(Intl, "DateTimeFormat", () => ({
		resolvedOptions: () => ({ timeZone: "America/Los_Angeles" }),
	}));
	const post = t.mock.fn(async (...args) => {
		posts.push(args);
		return postImplementation(...args);
	});
	const user = await esmock.strict("../../src/script/shared/user.mjs", {
		"../../src/script/shared/request.mjs": { request: { post } },
	});

	return {
		...user,
		geolocationCalls,
		posts,
		setCoords(value) {
			coords = value;
		},
		setGeolocationImplementation(value) {
			geolocationImplementation = value;
		},
		setPostImplementation(value) {
			postImplementation = value;
		},
	};
}

/** @pair async-query:debounce-teardown */
test("test_debounce_cancel_prevents_delayed_callback", async () => {
	let calls = 0;
	const delayed = debounce(() => {
		calls += 1;
	}, 5);
	delayed();
	delayed.cancel();
	await new Promise((resolve) => setTimeout(resolve, 15));
	assert.equal(calls, 0, "Cancelled debounce callback still ran");
});

/** @matrix frontend-utilities : cleanup mutation-observer */
test("test_wait_for_attribute_resolves_and_cleans_up_observers", async (t) => {
	const observers = [];
	replace(
		t,
		globalThis,
		"MutationObserver",
		class {
			constructor(callback) {
				this.callback = callback;
				this.disconnected = false;
				observers.push(this);
			}

			disconnect() {
				this.disconnected = true;
			}

			observe() {}
		},
	);
	const attributes = new Map();
	const element = {
		hasAttribute: (name) => attributes.has(name),
		getAttribute: (name) => attributes.get(name),
	};
	const pending = waitForAttribute(element, "data-ready", 50);
	assert.equal(observers.length, 1, "observer was not created");
	attributes.set("data-ready", "yes");
	observers[0].callback();
	assert.equal(await pending, "yes", "attribute value was not returned");
	assert.equal(
		observers[0].disconnected,
		true,
		"observer was not disconnected",
	);

	const timeoutElement = {
		hasAttribute: () => false,
		getAttribute: () => null,
	};
	await assert.rejects(
		waitForAttribute(timeoutElement, "data-never", 1),
		/data-never/,
		"missing attribute did not time out",
	);
	assert.equal(observers[1].disconnected, true, "timed-out observer leaked");
});

/** @matrix frontend-utilities : array-order deep-equality */
test("test_are_equal_normalizes_object_keys_but_preserves_array_order", () => {
	assert.equal(
		areEqual(
			{ b: 2, nested: { y: 2, x: 1 } },
			{ nested: { x: 1, y: 2 }, b: 2 },
		),
		true,
		"equivalent object key orders compared unequal",
	);
	assert.equal(
		areEqual(
			{ values: [{ b: 2, a: 1 }, { nested: { y: 2, x: 1 } }] },
			{ values: [{ a: 1, b: 2 }, { nested: { x: 1, y: 2 } }] },
		),
		true,
		"equivalent objects nested in arrays compared unequal",
	);
	assert.equal(
		areEqual({ values: [1, 2] }, { values: [2, 1] }),
		false,
		"array order was incorrectly normalized",
	);
});

/**
 * @matrix browser-storage : availability json
 * @pair browser-storage:recent-search-cleanup
 */
test("test_safe_storage_adapters_handle_browser_failures_and_json", (t) => {
	replace(t, globalThis, "localStorage", null);
	Object.defineProperty(globalThis, "localStorage", {
		configurable: true,
		get() {
			throw new Error("blocked");
		},
	});
	assert.equal(localStore.get("missing", "fallback"), "fallback");
	assert.equal(localStore.set("key", "value"), false);
	assert.equal(localStore.remove("key"), false);
	assert.throws(() => clearRecentSearchResults(), /blocked/);

	const values = new Map();
	const storage = {
		get length() {
			return values.size;
		},
		key(index) {
			return [...values.keys()][index] ?? null;
		},
		getItem(key) {
			return values.get(key) ?? null;
		},
		setItem(key, value) {
			values.set(key, String(value));
		},
		removeItem(key) {
			values.delete(key);
		},
	};
	Object.defineProperty(globalThis, "localStorage", {
		configurable: true,
		writable: true,
		value: storage,
	});
	replace(t, globalThis, "sessionStorage", storage);

	assert.equal(localStore.set("plain", "value"), true);
	assert.equal(localStore.get("plain", "fallback"), "value");
	assert.equal(localStore.remove("plain"), true);
	assert.equal(localStore.get("plain", "fallback"), "fallback");

	values.set("broken", "{not-json");
	assert.deepEqual(localStore.getJSON("broken", []), []);
	assert.equal(values.has("broken"), false);
	assert.equal(sessionStore.setJSON("state", { active: true }), true);
	assert.deepEqual(sessionStore.getJSON("state"), { active: true });

	values.set("recent-pages", "pages");
	values.set("recent-tasks", "tasks");
	values.set("other-recent-key", "keep");
	values.set("recent", "keep-too");
	assert.equal(clearRecentSearchResults(), undefined);
	assert.deepEqual(
		[...values],
		[
			["state", '{"active":true}'],
			["other-recent-key", "keep"],
			["recent", "keep-too"],
		],
	);
	clearRecentSearchResults();
	assert.equal(values.size, 3);
	values.clear();
	assert.equal(clearRecentSearchResults(), undefined);
	assert.equal(values.size, 0);

	const circular = {};
	circular.self = circular;
	assert.equal(localStore.setJSON("circular", circular), false);
	storage.setItem = () => {
		throw new Error("quota");
	};
	assert.equal(sessionStore.setJSON("quota", { active: true }), false);
});

/**
 * @matrix timezone : page-load session-update
 * @pair location:permission-deferral
 */
test("test_user_data_sync_posts_timezone_without_requesting_location", async (t) => {
	const env = await setupUser(t);
	assert.equal(
		await env.updateUserData(),
		true,
		"Successful timezone update was not reported",
	);
	assert.equal(env.geolocationCalls.length, 0, "Startup requested location");
	assert.equal(env.posts.length, 1, "Startup did not post exactly once");

	const [url, body, options] = env.posts[0];
	assert.equal(url, "/l/update-session");
	assert.equal(body.timezone, "America/Los_Angeles");
	assert.equal("location" in body, false);
	assert.equal(options.keepalive, true);
	assert.equal(
		sessionStorage.getItem("timezone_sent"),
		"America/Los_Angeles",
		"Successful timezone update was not cached for the session",
	);
	assert.equal(sessionStorage.getItem("userHash"), "user-hash");
});

/**
 * @matrix location : deduplication geolocation on-demand session-update
 * @pair timezone:serialized-update
 */
test("test_user_location_sync_starts_on_demand_and_deduplicates", async (t) => {
	const env = await setupUser(t);
	const startup = env.updateUserData();
	const firstLocation = env.updateUserLocation();
	const secondLocation = env.updateUserLocation();
	assert.equal(
		firstLocation,
		secondLocation,
		"On-demand location update was not deduplicated",
	);
	assert.notEqual(
		firstLocation,
		startup,
		"On-demand location update reused the timezone promise",
	);
	assert.equal(
		await firstLocation,
		true,
		"Successful on-demand location update was not reported",
	);
	assert.equal(env.geolocationCalls.length, 1);
	assert.equal(env.posts.length, 2);

	const timezoneBody = env.posts[0][1];
	const locationBody = env.posts[1][1];
	assert.equal(timezoneBody.timezone, "America/Los_Angeles");
	assert.equal("location" in timezoneBody, false);
	assert.equal("timezone" in locationBody, false);
	assert.deepEqual(locationBody.location, {
		latitude: 37.7749,
		longitude: -122.4194,
	});
});

/** @matrix location : retry session-update */
test("test_user_location_sync_retries_failed_session_update", async (t) => {
	const env = await setupUser(t);
	await env.updateUserData();
	env.posts.length = 0;
	let attempts = 0;
	env.setPostImplementation(async () => ({
		ok: ++attempts > 1,
		userHash: "retry-user",
	}));

	assert.equal(
		await env.updateUserLocation(),
		false,
		"Failed location update was reported as successful",
	);
	assert.equal(
		await env.updateUserLocation(),
		true,
		"Location update did not retry successfully",
	);
	assert.equal(env.geolocationCalls.length, 2);
	assert.equal(env.posts.length, 2, "Failed update was not retried");
});

/** @pairs location:unavailable timezone:session-update */
test("test_unavailable_user_location_does_not_affect_timezone_sync", async (t) => {
	const env = await setupUser(t);
	env.setGeolocationImplementation((_success, error) => error({ code: 1 }));

	assert.equal(
		await env.updateUserData(),
		true,
		"Timezone update was not reported as synchronized",
	);
	assert.equal(
		env.geolocationCalls.length,
		0,
		"Timezone synchronization requested browser location",
	);
	assert.equal(env.posts.length, 1);
	const body = env.posts[0][1];
	assert.equal(body.timezone, "America/Los_Angeles");
	assert.equal("location" in body, false);
	assert.equal(
		sessionStorage.getItem("timezone_sent"),
		"America/Los_Angeles",
		"Timezone was not cached after success",
	);
	assert.equal(
		await env.updateUserLocation(),
		false,
		"Unavailable location was reported as synchronized",
	);
	await env.updateUserLocation();
	assert.equal(env.geolocationCalls.length, 1);
	assert.equal(
		env.posts.length,
		1,
		"Unavailable geolocation was retried repeatedly on one page",
	);
});
