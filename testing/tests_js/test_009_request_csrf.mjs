import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
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

function cloneHeaders(headers) {
	if (!headers) return {};
	if (headers instanceof Headers) return Object.fromEntries(headers.entries());
	return { ...headers };
}

async function setupRequest(t, { pathname = "/home" } = {}) {
	createBrowser(t, {
		url: `https://example.test${pathname}`,
		html: `<!doctype html>
			<meta name="analytics" content="true">
			<input id="token" value="stale-token">
			<main>mounted main</main>
			<div data-role="upstream-unavailable" data-build="test-build"
				data-release="1.2.0" data-visible="false" data-stale="false"
				data-outcome-uncertain="false">
				<span data-role="upstream-unavailable-message"></span>
				<button data-role="upstream-unavailable-retry">Try again</button>
			</div>`,
	});
	Object.defineProperty(navigator, "serviceWorker", {
		configurable: true,
		value: { controller: {}, addEventListener() {} },
	});
	const entityEvents = [];
	window.addEventListener("entity-updated", (event) =>
		entityEvents.push(event),
	);
	const networkErrors = [];
	const fetchCalls = [];
	const sentryEvents = [];
	window.Sentry = {
		captureMessage(message, options) {
			sentryEvents.push({ message, options });
		},
	};
	const banner = document.querySelector("[data-role='upstream-unavailable']");
	const bannerMessage = banner.querySelector(
		"[data-role='upstream-unavailable-message']",
	);
	const bannerButton = document.querySelector(
		"[data-role='upstream-unavailable-retry']",
	);
	const listeners = {};
	const addEventListener = bannerButton.addEventListener.bind(bannerButton);
	t.mock.method(bannerButton, "addEventListener", (type, listener, options) => {
		listeners[`banner-${type}`] = listener;
		return addEventListener(type, listener, options);
	});
	const nativeSetTimeout = globalThis.setTimeout;
	const shortTimeout = (callback, delay, ...args) =>
		nativeSetTimeout(callback, Math.min(delay, 5), ...args);
	t.mock.method(globalThis, "setTimeout", shortTimeout);
	t.mock.method(window, "setTimeout", shortTimeout);

	const state = { retrySucceeds: false };
	const fetchImpl = async (input, config = {}) => {
		const requestUrl = typeof input === "string" ? input : input.url;
		const path = new URL(requestUrl, window.location.href).pathname;
		fetchCalls.push({
			url: requestUrl,
			body: config.body,
			cache: config.cache || input?.cache,
			headers: cloneHeaders(config.headers),
			keepalive: Boolean(config.keepalive),
			method: config.method || "GET",
			signal: config.signal,
		});
		if (path === "/upstream-reset") {
			return new Response(
				"upstream connect error or disconnect/reset before headers. reset reason: connection termination",
				{
					status: 503,
					statusText: "Service Unavailable",
					headers: { "Content-Type": "text/plain" },
				},
			);
		}
		if (path === "/bad-request") {
			return new Response("invalid payload", {
				status: 400,
				statusText: "Bad Request",
				headers: { "Content-Type": "text/plain" },
			});
		}
		if (path === "/validation-json") {
			return new Response(
				JSON.stringify({
					error: "Invalid polling request.",
					code: "invalid_poll_contract",
					path: "subscriptions[0].revision",
					reason: "type",
				}),
				{
					status: 422,
					statusText: "Unprocessable Content",
					headers: { "Content-Type": "application/json" },
				},
			);
		}
		if (path === "/validation-text") {
			return new Response("Specific validation message.", {
				status: 422,
				statusText: "Unprocessable Entity",
				headers: { "Content-Type": "text/plain" },
			});
		}
		if (path === "/html-error") {
			return new Response("<main>replacement error page</main>", {
				status: 500,
				statusText: "Internal Server Error",
				headers: {
					"Content-Type": "text/html",
					"X-Lagniappe-Error": "Internal Server Error",
				},
			});
		}
		const rawMatch = path.match(/^\/raw-upstream\/(500|502|503|504)$/);
		if (rawMatch) {
			return new Response("<html>raw upstream error with private body</html>", {
				status: Number(rawMatch[1]),
				statusText: "Service Unavailable",
				headers: {
					"Content-Type": "text/html",
					Server: "x".repeat(200),
					"X-Cloud-Trace-Context": "private-trace-value",
				},
			});
		}
		if (path === "/retry-upstream") {
			const attempts = fetchCalls.filter(
				(call) => new URL(call.url, window.location.href).pathname === path,
			).length;
			if (attempts === 1 || !state.retrySucceeds) {
				return new Response("<html>raw upstream error</html>", {
					status: 503,
					statusText: "Service Unavailable",
					headers: { "Content-Type": "text/html" },
				});
			}
			return new Response(JSON.stringify({ recovered: true }), {
				status: 200,
				headers: { "Content-Type": "application/json" },
			});
		}
		if (path === "/unchanged") {
			return new Response(JSON.stringify({ rows: [] }), {
				status: 200,
				headers: {
					"Content-Type": "application/json",
					"X-Lagniappe-Updated": "false",
				},
			});
		}
		if (path === "/not-modified") {
			return new Response(null, {
				status: 304,
				headers: { ETag: '"deferred-state"' },
			});
		}
		if (path === "/invalidate") {
			return new Response(JSON.stringify({ targets: [] }), {
				status: 200,
				headers: {
					"Content-Type": "application/json",
					"X-Lagniappe-Invalidate-Cache": "True",
				},
			});
		}
		if (path === "/entity-response") {
			return new Response(JSON.stringify({ saved: true }), {
				status: 200,
				headers: {
					"Content-Type": "application/json",
					"X-Lagniappe-Entity-Revisions": JSON.stringify([
						{ key: "entity-key", fingerprint: "entity-fingerprint" },
						{ key: "owner-key", fingerprint: "owner-fingerprint" },
					]),
				},
			});
		}
		if (path === "/l/token") {
			await new Promise((resolve) => nativeSetTimeout(resolve, 5));
			return new Response("fresh-token", { status: 200 });
		}
		if (
			path === "/csrf-then-upstream" &&
			config.headers?.["X-CSRFToken"] === "fresh-token"
		) {
			return new Response(
				"<html>raw upstream error after csrf refresh</html>",
				{
					status: 503,
					statusText: "Service Unavailable",
					headers: { "Content-Type": "text/html" },
				},
			);
		}
		if (config.headers?.["X-CSRFToken"] === "fresh-token") {
			const data = path.endsWith("/users/logout")
				? { success: true, redirect: "/users/login" }
				: { accepted: true };
			return new Response(JSON.stringify(data), {
				status: 200,
				headers: { "Content-Type": "application/json" },
			});
		}
		return new Response("stale csrf", {
			status: 400,
			statusText: "Bad Request",
			headers: { "X-Lagniappe-CSRF": "invalid" },
		});
	};
	t.mock.method(globalThis, "fetch", fetchImpl);
	t.mock.method(window, "fetch", fetchImpl);
	const upstream = await import(
		"../../src/script/shared/upstreamUnavailable.mjs"
	);
	const { request } = await esmock.strict(
		"../../src/script/shared/request.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureNetworkError: (...args) => networkErrors.push(args),
			},
			"../../src/script/shared/notificationState.mjs": {
				applyNotificationStateHeader: () => null,
			},
			"../../src/script/shared/upstreamUnavailable.mjs": {
				handleUpstreamResponse: upstream.handleUpstreamResponse,
			},
		},
	);
	return {
		banner,
		bannerButton,
		bannerMessage,
		entityEvents,
		fetchCalls,
		listeners,
		networkErrors,
		request,
		sentryEvents,
		state,
		tokenElt: document.getElementById("token"),
		upstream,
	};
}

const callsFor = (context, pathname) =>
	context.fetchCalls.filter(
		(call) => new URL(call.url, window.location.href).pathname === pathname,
	);

/** @pair analytics:internal-request-exclusion */
test("test_analytics_skips_internal_requests", async (t) => {
	createBrowser(t, {
		url: "https://example.test/l/update",
		html: '<meta name="analytics" content="true"><input id="token" value="csrf">',
	});
	const sent = [];
	const fetchImpl = async (_url, options) => {
		sent.push(JSON.parse(options.body));
		return { ok: true };
	};
	t.mock.method(globalThis, "fetch", fetchImpl);
	t.mock.method(window, "fetch", fetchImpl);
	const { analytics } = await import("../../src/script/shared/analytics.mjs");
	for (const action of ["view", "public_view", "create", "update", "delete"]) {
		for (const path of [
			"/api",
			"/api/v1/me",
			"/mcp",
			"/mcp/tools",
			"/l",
			"/l/poll",
			"/analytics/",
		]) {
			await analytics.tag(action, { path });
		}
	}
	await analytics.tag("update");
	assert.equal(sent.length, 0);
	for (const path of [
		"/",
		"/pages/example",
		"/tools/api-plan/example",
		"/links",
	]) {
		await analytics.tag("view", { path });
	}
	assert.deepEqual(
		sent.map((row) => row.path),
		["/", "/pages/example", "/tools/api-plan/example", "/links"],
	);
});

/** @matrix csrf : concurrent-refresh stale-token */
test("test_concurrent_stale_writes_share_server_controlled_token_refresh", async (t) => {
	const context = await setupRequest(t);
	const [post, put] = await Promise.all([
		context.request.post("/l/sync", { value: 1 }, { keepalive: true }),
		context.request.put("/pages/page-1/update", { value: 2 }),
	]);
	assert.equal(post.ok, true);
	assert.equal(put.ok, true);
	const tokenCalls = callsFor(context, "/l/token");
	assert.equal(tokenCalls.length, 1);
	assert.equal(tokenCalls[0].cache, undefined);
	assert.equal(tokenCalls[0].headers["Cache-Control"], undefined);
	assert.equal(context.tokenElt.value, "fresh-token");
	const writeCalls = context.fetchCalls.filter(
		(call) => new URL(call.url, window.location.href).pathname !== "/l/token",
	);
	assert.equal(
		writeCalls.filter((call) => call.headers["X-CSRFToken"] === "stale-token")
			.length,
		2,
	);
	assert.equal(
		writeCalls.filter((call) => call.headers["X-CSRFToken"] === "fresh-token")
			.length,
		2,
	);
	assert.equal(
		writeCalls.some((call) => call.keepalive),
		true,
	);
});

/** @matrix csrf request-errors : retry-classification */
test("test_non_csrf_bad_request_is_not_retried", async (t) => {
	const context = await setupRequest(t);
	const response = await context.request.post("/bad-request", {
		value: "invalid",
	});
	assert.equal(response.ok, false);
	assert.equal(response.error, "invalid payload");
	assert.equal(callsFor(context, "/bad-request").length, 1);
	assert.equal(callsFor(context, "/l/token").length, 0);
});

/** @source src/script/shared/request.mjs::_request */
/** @pair request:abort-signal */
test("test_requests_forward_abort_signal_to_fetch", async (t) => {
	const context = await setupRequest(t);
	const controller = new AbortController();
	await context.request.get("/unchanged", null, { signal: controller.signal });
	await context.request.post(
		"/unchanged",
		{ value: "convert" },
		{ signal: controller.signal },
	);
	const calls = callsFor(context, "/unchanged");
	assert.equal(calls.length, 2);
	assert.equal(
		calls.every((call) => call.signal === controller.signal),
		true,
	);
});

/** @matrix polling request-errors : diagnostics structured-validation */
test("test_request_preserves_structured_validation_error", async (t) => {
	const { request } = await setupRequest(t);
	const response = await request.post("/validation-json", { value: "invalid" });
	assert.equal(response.ok, false);
	assert.equal(response.status, 422);
	assert.equal(response.code, "invalid_poll_contract");
	assert.equal(response.path, "subscriptions[0].revision");
	assert.equal(response.reason, "type");
});

/** @matrix request-errors : diagnostics plain-validation */
test("test_request_preserves_plain_validation_error", async (t) => {
	const { request } = await setupRequest(t);
	const response = await request.post("/validation-text", { value: "invalid" });
	assert.equal(response.ok, false);
	assert.equal(response.status, 422);
	assert.equal(response.error, "Specific validation message.");
});

/** @matrix edited-entity-notice request-errors : non-invasive-probe reload-fallback */
test("test_request_can_return_html_error_without_replacing_page", async (t) => {
	const { request } = await setupRequest(t);
	document.documentElement.dataset.mounted = "page";
	const before = document.documentElement.innerHTML;
	const response = await request.get("/html-error", null, {
		replaceErrorPage: false,
	});
	assert.equal(response.ok, false);
	assert.equal(response.error, "Internal Server Error");
	assert.equal(document.documentElement.innerHTML, before);
});

/** @matrix request-errors : application-error-marker classification dom-replacement */
test("test_application_marked_html_error_keeps_existing_behavior", async (t) => {
	const context = await setupRequest(t);
	const main = document.querySelector("main");
	main.innerHTML = "current application main";
	const response = await context.request.get("/html-error");
	assert.equal(response.ok, false);
	assert.equal(response.error, "Internal Server Error");
	assert.equal(main.innerHTML, "<main>replacement error page</main>");
	assert.equal(document.title, "Internal Server Error");
	assert.equal(context.banner.dataset.visible, "false");
});

/** @matrix request-errors : classification dom-preservation upstream-unavailable */
test("test_all_unmarked_upstream_html_statuses_are_classified_without_dom_replacement", async (t) => {
	const context = await setupRequest(t);
	const main = document.querySelector("main");
	main.innerHTML = '<form><input name="draft" value="saved value"></form>';
	const draft = main.querySelector("input");
	draft.value = "unsaved edit";
	const before = main.innerHTML;
	for (const status of [500, 502, 503, 504]) {
		const result = await context.request.get(`/raw-upstream/${status}`);
		assert.equal(result.ok, false, String(status));
		assert.equal(result.code, "upstream_instance_unavailable", String(status));
		assert.equal(result.status, status, String(status));
		assert.equal(result.upstreamUnavailable, true, String(status));
		assert.equal(result.retryOutcome, "failed", String(status));
		assert.equal(document.querySelector("main"), main, String(status));
		assert.equal(main.querySelector("input"), draft, String(status));
		assert.equal(main.innerHTML, before, String(status));
		assert.equal(draft.value, "unsaved edit", String(status));
	}
	const markedByWorker = new Response(JSON.stringify({ ok: false }), {
		status: 503,
		headers: {
			"Content-Type": "application/json",
			"X-Lagniappe-Upstream-Unavailable": "true",
		},
	});
	assert.equal(
		context.upstream.isUpstreamUnavailableResponse(
			markedByWorker,
			"/pages/example",
		),
		true,
	);
});

/** @matrix request-errors : banner dom-preservation explicit-retry fresh-response retry upstream-unavailable */
test("test_failed_get_preserves_dom_and_exposes_safe_banner_retry", async (t) => {
	const context = await setupRequest(t);
	context.upstream.installUpstreamUnavailableBanner();
	const main = document.querySelector("main");
	main.innerHTML = '<form><input value="entered form"></form>';
	const before = main.innerHTML;
	context.tokenElt.value = "entered-form-state";
	context.state.retrySucceeds = false;
	const result = await context.request.get("/retry-upstream");
	assert.equal(result.ok, false);
	assert.equal(result.retryable, true);
	assert.equal(result.outcomeUncertain, false);
	assert.equal(result.retryOutcome, "failed");
	assert.equal(callsFor(context, "/retry-upstream").length, 2);
	assert.equal(main.innerHTML, before);
	assert.equal(context.tokenElt.value, "entered-form-state");
	assert.equal(context.banner.dataset.visible, "true");
	assert.match(context.bannerMessage.textContent, /unchanged/);
	context.state.retrySucceeds = true;
	await context.listeners["banner-click"]();
	assert.equal(callsFor(context, "/retry-upstream").length, 3);
	assert.equal(context.banner.dataset.visible, "false");
	assert.equal(context.tokenElt.value, "entered-form-state");
});

/** @matrix request-errors : mutation no-replay outcome-uncertain upstream-unavailable */
test("test_mutation_upstream_failure_is_uncertain_and_never_replayed", async (t) => {
	const context = await setupRequest(t);
	context.upstream.installUpstreamUnavailableBanner();
	const result = await context.request.patch("/raw-upstream/503", {
		private: "entered form data",
	});
	assert.equal(result.ok, false);
	assert.equal(result.retryable, false);
	assert.equal(result.outcomeUncertain, true);
	assert.equal(result.code, "upstream_instance_unavailable");
	assert.equal(callsFor(context, "/raw-upstream/503").length, 1);
	assert.match(context.bannerMessage.textContent, /could not confirm/);
	await context.listeners["banner-click"]();
	assert.equal(
		callsFor(context, "/raw-upstream/503").filter(
			(call) => call.method === "PATCH",
		).length,
		1,
	);
	assert.equal(
		callsFor(context, "/home").some((call) => call.method === "GET"),
		true,
	);
});

/** @source src/script/shared/request.mjs::_request */
/** @matrix csrf : stale-token */
/** @matrix request-errors : dom-preservation no-replay outcome-uncertain upstream-unavailable */
test("test_mutation_upstream_failure_after_csrf_refresh_is_classified_without_replay", async (t) => {
	const context = await setupRequest(t);
	const main = document.querySelector("main");
	main.innerHTML = '<form><input name="draft" value="saved value"></form>';
	const draft = main.querySelector("input");
	draft.value = "unsaved edit";
	const before = main.innerHTML;
	const result = await context.request.post("/csrf-then-upstream", {
		private: "form data",
	});
	assert.equal(result.ok, false);
	assert.equal(result.retryable, false);
	assert.equal(result.outcomeUncertain, true);
	assert.equal(result.code, "upstream_instance_unavailable");
	assert.equal(
		callsFor(context, "/csrf-then-upstream").filter(
			(call) => call.method === "POST",
		).length,
		2,
	);
	assert.equal(document.querySelector("main"), main);
	assert.equal(main.querySelector("input"), draft);
	assert.equal(main.innerHTML, before);
	assert.equal(draft.value, "unsaved edit");
});

/** @matrix error-tracking request-errors : cooldown fingerprint privacy response-metadata route-class upstream-unavailable warning */
test("test_upstream_diagnostics_are_bounded_private_and_deduplicated", async (t) => {
	const context = await setupRequest(t);
	const upstreamResponse = new Response("<html>private response body</html>", {
		status: 503,
		headers: {
			"Content-Type": "text/html",
			Server: "x".repeat(200),
			Traceparent: "private-trace-value",
		},
	});
	const details = context.upstream.upstreamUnavailableDetails(
		upstreamResponse,
		{
			method: "GET",
			url: "/pages/private-entity-id?secret=query",
			retryOutcome: "failed",
		},
	);
	context.upstream.reportUpstreamUnavailable({
		...details,
		query: "secret=query",
		body: "entered form data",
		response_html: "private response body",
		cookie: "private cookie",
	});
	context.upstream.reportUpstreamUnavailable(details);
	assert.equal(context.sentryEvents.length, 1);
	const event = context.sentryEvents[0];
	const diagnostic = event.options.contexts.upstream_instance_unavailable;
	assert.equal(event.options.level, "warning");
	assert.deepEqual(event.options.fingerprint, [
		"upstream_instance_unavailable",
	]);
	assert.equal(diagnostic.route_class, "pages");
	assert.equal(diagnostic.server.length, 128);
	assert.equal(diagnostic.trace_header_present, true);
	assert.equal(diagnostic.build, "test-build");
	assert.equal(diagnostic.release, "1.2.0");
	const allowed = [
		"build",
		"method",
		"online",
		"release",
		"retry_outcome",
		"route_class",
		"server",
		"service_worker",
		"stale",
		"status",
		"timestamp",
		"trace_header_present",
	];
	assert.deepEqual(Object.keys(diagnostic).sort(), allowed.sort());
	const serialized = JSON.stringify(event);
	for (const secret of [
		"private-entity-id",
		"secret=query",
		"entered form data",
		"private response body",
		"private cookie",
		"private-trace-value",
	]) {
		assert.equal(serialized.includes(secret), false, secret);
	}
});

/** @matrix cache request : conditional-response dom-refresh */
test("test_request_exposes_service_worker_updated_marker", async (t) => {
	const { request } = await setupRequest(t);
	const response = await request.get("/unchanged");
	assert.equal(response.updated, false);
	assert.equal(Array.isArray(response.rows), true);
});

/** @matrix cache : conditional-response etag */
/** @matrix deferred-jobs request : conditional-response etag post-headers */
test("test_request_supports_conditional_post_not_modified", async (t) => {
	const context = await setupRequest(t);
	const response = await context.request.post(
		"/not-modified",
		{ operations: ["operation-a"] },
		{ headers: { "If-None-Match": '"deferred-state"' } },
	);
	assert.equal(response.ok, true);
	assert.equal(response.unchanged, true);
	assert.equal(response.etag, '"deferred-state"');
	assert.equal(
		callsFor(context, "/not-modified")[0].headers["If-None-Match"],
		'"deferred-state"',
	);
});

/** @matrix cache request : invalidation reload */
test("test_request_exposes_client_cache_invalidation_marker", async (t) => {
	const { request } = await setupRequest(t);
	const response = await request.post("/invalidate", { targets: [] });
	assert.equal(response.reload, true);
	assert.equal(Array.isArray(response.targets), true);
});

/** @matrix edited-entity-notice request : acknowledgement multiple-entities response-headers */
test("test_request_dispatches_entity_fingerprint_acknowledgement", async (t) => {
	const context = await setupRequest(t);
	const response = await context.request.put("/entity-response", {
		value: "saved",
	});
	assert.equal("entity" in response, false);
	assert.equal(response.entities?.length, 2);
	assert.equal(context.entityEvents.length, 2);
	assert.equal(context.entityEvents[0].type, "entity-updated");
	assert.equal(
		context.entityEvents[0].detail.fingerprint,
		"entity-fingerprint",
	);
	assert.equal(context.entityEvents[1].detail.key, "owner-key");
	context.entityEvents.splice(0);
	const probe = await context.request.get("/entity-response", null, {
		acknowledgeEntities: false,
	});
	assert.equal(probe.entities?.length, 2);
	assert.equal(context.entityEvents.length, 0);
});

/** @matrix request-errors : ajax-upload proxy-text-error */
test("test_plain_text_upstream_error_stays_in_request_error_path", async (t) => {
	const { request } = await setupRequest(t);
	const before = document.documentElement.innerHTML;
	const data = new FormData();
	data.append("assets", "{}");
	const response = await request.post("/upstream-reset", data);
	assert.equal(response.ok, false);
	assert.equal(response.error, "Upload fewer files?");
	assert.equal(document.documentElement.innerHTML, before);
});

/** @matrix login : button logout */
test("test_logout_button_posts_without_hidden_form", async (t) => {
	const context = await setupRequest(t);
	// Observe the navigation assignment without asking jsdom to navigate.
	const currentLocation = window.location;
	const redirects = [];
	const location = {
		get href() {
			return currentLocation.href;
		},
		set href(destination) {
			redirects.push(destination);
		},
		origin: currentLocation.origin,
		pathname: currentLocation.pathname,
	};
	replace(t, globalThis, "window", {
		location,
		dispatchEvent: window.dispatchEvent.bind(window),
		Sentry: window.Sentry,
	});
	const { initializeLogoutForms } = await esmock.strict(
		"../../src/script/shared/logout.mjs",
		{
			"../../src/script/shared/request.mjs": { request: context.request },
		},
	);
	const listeners = {};
	const root = {
		addEventListener(type, listener) {
			listeners[type] = listener;
		},
	};
	initializeLogoutForms(root);
	const button = {
		dataset: {
			action: "logout",
			route: "https://example.test/users/logout",
		},
		disabled: false,
		closest(selector) {
			return selector === "[data-action='logout'][data-route]" ? this : null;
		},
	};
	let defaultPrevented = false;
	await listeners.click({
		target: button,
		preventDefault() {
			defaultPrevented = true;
		},
	});
	assert.equal(defaultPrevented, true);
	assert.deepEqual(redirects, ["/users/login"]);
	assert.equal(button.disabled, true);
	assert.equal(button.dataset.submitting, "true");
	assert.equal(callsFor(context, "/l/token").length, 1);
	const logoutCalls = callsFor(context, "/users/logout");
	assert.equal(logoutCalls.length, 2);
	assert.equal(logoutCalls[0].headers["X-CSRFToken"], "stale-token");
	assert.equal(logoutCalls[1].headers["X-CSRFToken"], "fresh-token");
	assert.equal(
		logoutCalls.some((call) => call.body),
		false,
	);
});

/** @pair login:csrf-refresh */
test("test_login_handoff_refreshes_csrf_before_submit_and_retries_once", async (t) => {
	const calls = [];
	const errors = [];
	const tokenElt = { value: "expired-page-token" };
	const refreshedTokens = ["fresh-token", "race-retry-token"];
	let handoffAttempts = 0;
	const fakeWindow = {
		location: { href: "", pathname: "/users/login" },
	};
	replace(t, globalThis, "window", fakeWindow);
	replace(t, globalThis, "document", {
		getElementById(id) {
			return id === "token" ? tokenElt : null;
		},
	});
	const request = {
		csrfFailed(response) {
			return (
				response.status === 400 &&
				response.headers.get("X-Lagniappe-CSRF") === "invalid"
			);
		},
		async token() {
			const token = refreshedTokens.shift();
			calls.push({ type: "token", token });
			tokenElt.value = token;
			return token;
		},
	};
	const fetchImpl = async (url, config) => {
		handoffAttempts += 1;
		calls.push({
			type: "handoff",
			url,
			token: config.headers["X-CSRFToken"],
			body: JSON.parse(config.body),
		});
		if (handoffAttempts === 1) {
			return new Response("expired csrf", {
				status: 400,
				headers: { "X-Lagniappe-CSRF": "invalid" },
			});
		}
		return new Response(JSON.stringify({ success: true, redirect: "/home" }), {
			status: 200,
			headers: { "Content-Type": "application/json" },
		});
	};
	replace(t, globalThis, "fetch", fetchImpl);
	const { handleIdentityUser } = await esmock.strict(
		"../../src/script/login/tools.mjs",
		{
			"../../src/script/shared/analytics.mjs": {
				analytics: {
					tag(name, data) {
						calls.push({ type: "analytics", name, data });
					},
				},
			},
			"../../src/script/shared/request.mjs": { request },
		},
	);
	const user = {
		displayName: "Test User",
		email: "test@example.test",
		idToken: "identity-id-token",
	};
	const form = {
		auth: {},
		getToken: () => tokenElt.value,
		remember: () => true,
		showError(message) {
			errors.push(message);
		},
		showConfirmation(message) {
			throw new Error(`Unexpected success message: ${message}`);
		},
	};
	await handleIdentityUser(user, form);
	const securityCalls = calls.filter(
		(call) => call.type === "token" || call.type === "handoff",
	);
	assert.deepEqual(
		securityCalls.map((call) => `${call.type}:${call.token}`),
		[
			"token:fresh-token",
			"handoff:fresh-token",
			"token:race-retry-token",
			"handoff:race-retry-token",
		],
	);
	assert.deepEqual(errors, []);
	assert.equal(fakeWindow.location.href, "/home");
	assert.equal(
		calls
			.filter((call) => call.type === "handoff")
			.every((call) => call.body.authResult === "identity-id-token"),
		true,
	);
});

/** @matrix login : csrf-refresh verify-email */
test("test_login_verification_email_reuses_refreshed_csrf", async (t) => {
	const verificationCalls = [];
	const stored = [];
	replace(t, globalThis, "window", {
		location: { href: "", pathname: "/users/login" },
	});
	replace(t, globalThis, "document", {});
	replace(t, globalThis, "localStorage", {
		setItem(key, value) {
			stored.push({ key, value });
		},
	});
	replace(t, globalThis, "fetch", async () => ({
		async json() {
			return { requires_verification: true };
		},
	}));
	const request = {
		csrfFailed: () => false,
		token: async () => "fresh-verification-token",
	};
	const { handleIdentityUser } = await esmock.strict(
		"../../src/script/login/tools.mjs",
		{
			"../../src/script/shared/analytics.mjs": {
				analytics: { tag() {} },
			},
			"../../src/script/shared/request.mjs": { request },
		},
	);
	const user = {
		displayName: "Test User",
		email: "test@example.test",
		idToken: "identity-id-token",
	};
	const form = {
		auth: {
			async sendEmailVerification(sentUser, csrfToken) {
				verificationCalls.push({ sentUser, csrfToken });
			},
		},
		getToken: () => "expired-page-token",
		remember: () => false,
		showError(message) {
			throw new Error(`Unexpected error: ${message}`);
		},
		showConfirmation() {},
	};
	await handleIdentityUser(user, form);
	assert.equal(verificationCalls.length, 1);
	assert.equal(verificationCalls[0].sentUser, user);
	assert.equal(verificationCalls[0].csrfToken, "fresh-verification-token");
	assert.deepEqual(stored, [{ key: "verificationEmail", value: user.email }]);
});
