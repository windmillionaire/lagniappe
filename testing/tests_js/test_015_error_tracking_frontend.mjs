import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import {
	captureError,
	configureSentry,
} from "../../src/script/shared/errors.mjs";
import { createBrowser } from "../utility/js/environment.mjs";

function setupErrorTracking(
	t,
	{
		dsn = "https://public-key@errors.example.test/42",
		initialized = true,
	} = {},
) {
	const meta = dsn ? `<meta name="sentry-dsn" content="${dsn}">` : "";
	createBrowser(t, {
		html: `<!doctype html><head>${meta}</head><body></body>`,
	});
	t.mock.method(console, "error", () => {});
	const captured = [];
	const inits = [];
	const options = {};
	const processors = [];
	window.Sentry = {
		addEventProcessor: (processor) => processors.push(processor),
		captureException: (...args) => captured.push(args),
		captureMessage: (...args) => captured.push(args),
		getClient: () =>
			initialized
				? {
						getOptions: () => options,
					}
				: null,
		init: (sentryOptions) => inits.push(sentryOptions),
	};
	return { captured, dsn, inits, options, processors };
}

/** @matrix error-tracking login : login-context shared-capture */
test("test_login_error_delegates_to_shared_capture", async (t) => {
	createBrowser(t);
	const navigatorObject = navigator;
	const descriptor = Object.getOwnPropertyDescriptor(
		navigatorObject,
		"userAgent",
	);
	Object.defineProperty(navigatorObject, "userAgent", {
		configurable: true,
		value: "Lagniappe Test Browser",
	});
	t.after(() => {
		if (descriptor) {
			Object.defineProperty(navigatorObject, "userAgent", descriptor);
		} else {
			delete navigatorObject.userAgent;
		}
	});
	const calls = [];
	const captureErrorBoundary = t.mock.fn((...args) => calls.push(args));
	const { captureLoginError } = await esmock.strict(
		"../../src/script/login/error.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureError: captureErrorBoundary,
			},
		},
	);
	const error = new Error("login failed");

	captureLoginError(error, "reset_password");

	assert.equal(calls.length, 1);
	assert.equal(calls[0][0], error);
	assert.equal(calls[0][1], null);
	assert.equal(calls[0][2].login.operation, "reset_password");
	assert.equal(calls[0][2].login.userAgent, "Lagniappe Test Browser");
	assert.ok(calls[0][2].login.timestamp);
});

/** @matrix error-tracking : normalization sentry-context */
test("test_capture_error_normalizes_sentry_context_values", (t) => {
	const { captured } = setupErrorTracking(t);
	captureError(new Error("boom"), null, {
		type: "unhandledrejection",
		route: "/widgets/example",
		event: { type: "unhandledrejection" },
		flags: ["alpha", "beta"],
		missing: undefined,
		skip: () => {},
		marker: Symbol("skip"),
	});

	const contexts = captured[0]?.[1]?.contexts;
	assert.ok(contexts);
	for (const [key, value] of Object.entries(contexts)) {
		assert.equal(
			Boolean(value && typeof value === "object" && !Array.isArray(value)),
			true,
			`Context ${key} was not normalized to an object`,
		);
	}
	assert.equal(contexts.type.value, "unhandledrejection");
	assert.equal(contexts.route.value, "/widgets/example");
	assert.equal(contexts.event.type, "unhandledrejection");
	assert.deepEqual(contexts.flags.values, ["alpha", "beta"]);
	for (const omitted of ["missing", "skip", "marker"]) {
		assert.equal(omitted in contexts, false);
	}
});

/** @matrix error-tracking : malformed-blocking-operation sentry-context */
test("test_configure_sentry_drops_malformed_blocking_operation_warning", (t) => {
	const { processors } = setupErrorTracking(t);
	configureSentry();
	assert.equal(processors.length, 1);
	const result = processors[0]({
		type: "generic",
		level: "warning",
		transaction: "internal.notifications",
		culprit: "internal.notifications",
		metadata: { title: "Blocking Operation" },
		contexts: {
			trace: {
				trace_id: "2ef4092f9ce74f18b84c868c5a569581",
				span_id: null,
				status: "unknown",
				type: "trace",
			},
		},
	});
	assert.equal(result, null);
});

/** @matrix error-tracking : sentry-context trace-normalization */
test("test_configure_sentry_removes_invalid_trace_context_without_dropping_event", (t) => {
	const { processors } = setupErrorTracking(t);
	configureSentry();
	const result = processors[0]({
		type: "generic",
		level: "info",
		contexts: {
			browser: { name: "Chrome" },
			trace: {
				trace_id: "2ef4092f9ce74f18b84c868c5a569581",
				span_id: null,
			},
		},
	});
	assert.notEqual(result, null);
	assert.equal("trace" in result.contexts, false);
	assert.equal(result.contexts.browser.name, "Chrome");
});

/** @matrix error-tracking : blocking-operation notification-transaction */
test("test_configure_sentry_filters_notification_long_task_spans", (t) => {
	const { options } = setupErrorTracking(t);
	configureSentry();
	const result = options.beforeSendTransaction(
		{
			type: "transaction",
			transaction: "internal.notifications",
			spans: [
				{ op: "ui.long-task", description: "Main UI thread blocked" },
				{
					op: "ui.long-animation-frame",
					description: "Main UI thread blocked",
				},
				{ op: "http.client", description: "GET /l/notifications" },
			],
		},
		{},
	);
	assert.equal(result.spans.length, 1);
	assert.equal(result.spans[0].op, "http.client");
});

/** @matrix error-tracking : payload-bounds privacy redaction request-context */
test("test_configure_sentry_redacts_browser_request_and_context_payloads", (t) => {
	const { processors } = setupErrorTracking(t);
	configureSentry();
	const result = processors[0]({
		request: {
			url: "https://example.test/items/private-id?token=query-secret",
			method: "POST",
			query_string: "token=query-secret",
			data: { document: "request-body-secret" },
			cookies: { session: "cookie-secret" },
			headers: {
				Accept: "application/json",
				Authorization: "Bearer authorization-secret",
				"User-Agent": "Lagniappe Privacy Test",
				"X-Api-Key": "header-secret",
			},
		},
		user: { email: "private@example.test" },
		contexts: {
			auth: {
				password: "context-secret",
				email: "nested-email-secret@example.test",
				refreshTokens: ["plural-token-secret"],
				input_tokens: 42,
				detail: 'password="quoted secret value"',
			},
		},
		exception: {
			values: [
				{
					value: "failed with password=exception-secret",
					stacktrace: {
						frames: [
							{ filename: "example.mjs", vars: { secret: "frame-secret" } },
						],
					},
				},
			],
		},
		spans: [
			{
				description: "provider request",
				data: {
					prompt: "prompt-secret",
					"http.response.status_code": 500,
				},
			},
		],
	});
	const serialized = JSON.stringify(result);
	for (const secret of [
		"private-id",
		"query-secret",
		"request-body-secret",
		"cookie-secret",
		"authorization-secret",
		"header-secret",
		"private@example.test",
		"context-secret",
		"nested-email-secret@example.test",
		"plural-token-secret",
		"quoted secret value",
		"exception-secret",
		"frame-secret",
		"prompt-secret",
	]) {
		assert.equal(
			serialized.includes(secret),
			false,
			`Sensitive value remained: ${secret}`,
		);
	}
	assert.deepEqual(result.request, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"User-Agent": "Lagniappe Privacy Test",
		},
	});
	assert.equal("user" in result, false);
	assert.equal(result.contexts.auth.password, "[REDACTED]");
	assert.equal(result.contexts.auth.refreshTokens, "[REDACTED]");
	assert.equal(result.contexts.auth.input_tokens, 42);
	assert.equal(result.spans[0].data.prompt, "[REDACTED]");
	assert.equal(result.spans[0].data["http.response.status_code"], 500);
});

/** @matrix error-tracking : malformed-breadcrumbs privacy */
test("test_configure_sentry_drops_malformed_breadcrumb_container", (t) => {
	const { processors } = setupErrorTracking(t);
	configureSentry();
	const result = processors[0]({
		message: "malformed breadcrumb event",
		breadcrumbs: { unexpected: "object instead of array" },
	});
	assert.equal("breadcrumbs" in result, false);
});

/** @matrix error-tracking : configured-dsn privacy */
test("test_configure_sentry_uses_installation_dsn_without_default_pii", (t) => {
	const { dsn, inits } = setupErrorTracking(t, { initialized: false });
	configureSentry();
	assert.equal(inits.length, 1);
	assert.equal(inits[0].dsn, dsn);
	assert.equal(inits[0].sendDefaultPii, false);
});

/** @matrix error-tracking : configured-dsn disabled */
test("test_configure_sentry_does_not_initialize_without_dsn", (t) => {
	const { inits, processors } = setupErrorTracking(t, {
		dsn: null,
		initialized: false,
	});
	configureSentry();
	assert.equal(inits.length, 0);
	assert.equal(processors.length, 0);
});
