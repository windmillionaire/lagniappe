"""Node-backed checks for frontend error-tracking helpers."""

import textwrap


def run_error_tracking_check(run_node, assertion: str):
    script = f"""
	const fs = require("node:fs");
	const vm = require("node:vm");

	const captured = [];
	const sentryOptions = {{}};
	const sentryInits = [];
	const sentryProcessors = [];
	const sentryState = {{
	  dsn: "https://public-key@errors.example.test/42",
	  initialized: true,
	}};
	const context = {{
	  console: {{
	    error() {{}},
	  }},
	  document: {{
	    querySelector(selector) {{
	      if (selector !== 'meta[name="sentry-dsn"]' || !sentryState.dsn) return null;
	      return {{ content: sentryState.dsn }};
	    }},
	  }},
	  DOMException,
	  Element: class Element {{}},
	  sentryInits,
	  sentryOptions,
	  sentryProcessors,
	  sentryState,
	  window: {{
	    Sentry: {{
	      captureException: (...args) => captured.push(args),
	      captureMessage: (...args) => captured.push(args),
	      getClient: () =>
	        sentryState.initialized
	          ? {{
	              getOptions: () => sentryOptions,
	            }}
	          : null,
	      init: (options) => sentryInits.push(options),
	      addEventProcessor: (processor) => sentryProcessors.push(processor),
	    }},
	  }},
	}};

	vm.createContext(context);
	let source = fs.readFileSync("src/script/shared/errors.mjs", "utf8");
	source = source.replaceAll("export const ", "const ");
	source += "\\nglobalThis.captureError = captureError;";
	source += "\\nglobalThis.configureSentry = configureSentry;";
	source += "\\nglobalThis.sentryInits = sentryInits;";
	source += "\\nglobalThis.sentryOptions = sentryOptions;";
	source += "\\nglobalThis.sentryProcessors = sentryProcessors;";
	source += "\\nglobalThis.sentryState = sentryState;";
	vm.runInContext(source, context);
	const captureError = context.captureError;
	const configureSentry = context.configureSentry;
	const sentryInitsRef = context.sentryInits;
	const sentryOptionsRef = context.sentryOptions;
	const sentryProcessorsRef = context.sentryProcessors;
	const sentryStateRef = context.sentryState;

	{textwrap.indent(assertion, "")}
	"""

    run_node(script)


# @features error-tracking login
# @dimensions shared-capture login-context
def test_login_error_delegates_to_shared_capture(run_node):
    run_node(
        """
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
const context = {
  calls,
  navigator: { userAgent: "Lagniappe Test Browser" },
};

vm.createContext(context);
let source = fs.readFileSync("src/script/login/error.mjs", "utf8");
source = source.replace(
  'import { captureError } from "../shared/errors.mjs";',
  "const captureError = (...args) => calls.push(args);",
);
source = source.replace("export const captureLoginError", "const captureLoginError");
source += "\\nglobalThis.captureLoginError = captureLoginError;";
vm.runInContext(source, context);

const error = new Error("login failed");
context.captureLoginError(error, "reset_password");

if (calls.length !== 1) {
  throw new Error(`Expected one shared capture call, got ${calls.length}`);
}
const [capturedError, element, captureContext] = calls[0];
if (capturedError.message !== "login failed" || element !== null) {
  throw new Error("Login wrapper changed the captured error or element");
}
if (captureContext.login.operation !== "reset_password") {
  throw new Error("Login operation context was not preserved");
}
if (captureContext.login.userAgent !== "Lagniappe Test Browser") {
  throw new Error("Login user-agent context was not preserved");
}
if (!captureContext.login.timestamp) {
  throw new Error("Login timestamp context was not provided");
}
"""
    )


# @features error-tracking
# @dimensions sentry-context normalization
def test_capture_error_normalizes_sentry_context_values(run_node):
    run_error_tracking_check(
        run_node,
        """
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
if (!contexts) {
  throw new Error("Expected Sentry contexts to be provided");
}

for (const [key, value] of Object.entries(contexts)) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Context ${key} was not normalized to an object`);
  }
}
if (contexts.type.value !== "unhandledrejection") {
  throw new Error("Primitive context value was not wrapped");
}
if (contexts.route.value !== "/widgets/example") {
  throw new Error("Route context was not wrapped");
}
if (contexts.event.type !== "unhandledrejection") {
  throw new Error("Object context was not preserved");
}
if (contexts.flags.values.join(",") !== "alpha,beta") {
  throw new Error("Array context was not wrapped");
}
for (const omitted of ["missing", "skip", "marker"]) {
  if (omitted in contexts) {
    throw new Error(`Unsupported context ${omitted} was not omitted`);
  }
}
	""",
	    )


# @features error-tracking
# @dimensions malformed-blocking-operation sentry-context
def test_configure_sentry_drops_malformed_blocking_operation_warning(run_node):
    run_error_tracking_check(
        run_node,
        """
configureSentry();

if (sentryProcessorsRef.length !== 1) {
  throw new Error(`Expected one Sentry event processor, got ${sentryProcessorsRef.length}`);
}

const result = sentryProcessorsRef[0]({
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

if (result !== null) {
  throw new Error("Expected malformed blocking-operation warning to be dropped");
}
""",
    )


# @features error-tracking
# @dimensions sentry-context trace-normalization
def test_configure_sentry_removes_invalid_trace_context_without_dropping_event(run_node):
    run_error_tracking_check(
        run_node,
        """
configureSentry();

const result = sentryProcessorsRef[0]({
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

if (result === null) {
  throw new Error("Non-blocking event should not be dropped");
}
if ("trace" in result.contexts) {
  throw new Error("Invalid trace context was not removed");
}
if (result.contexts.browser.name !== "Chrome") {
  throw new Error("Non-trace context was not preserved");
}
""",
    )


# @features error-tracking
# @dimensions blocking-operation notification-transaction
def test_configure_sentry_filters_notification_long_task_spans(run_node):
    run_error_tracking_check(
        run_node,
        """
configureSentry();

const event = {
  type: "transaction",
  transaction: "internal.notifications",
  spans: [
    { op: "ui.long-task", description: "Main UI thread blocked" },
    { op: "ui.long-animation-frame", description: "Main UI thread blocked" },
    { op: "http.client", description: "GET /l/notifications" },
  ],
};

const result = sentryOptionsRef.beforeSendTransaction(event, {});

if (result.spans.length !== 1) {
  throw new Error(`Expected one span to remain, got ${result.spans.length}`);
}
if (result.spans[0].op !== "http.client") {
  throw new Error("Non-blocking notification span was not preserved");
}
""",
    )


# @features error-tracking
# @dimensions privacy redaction request-context payload-bounds
def test_configure_sentry_redacts_browser_request_and_context_payloads(run_node):
    run_error_tracking_check(
        run_node,
        """
configureSentry();

const event = {
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
    values: [{
      value: "failed with password=exception-secret",
      stacktrace: {
        frames: [{
          filename: "example.mjs",
          vars: { secret: "frame-secret" },
        }],
      },
    }],
  },
  spans: [{
    description: "provider request",
    data: {
      prompt: "prompt-secret",
      "http.response.status_code": 500,
    },
  }],
};

const result = sentryProcessorsRef[0](event);
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
  if (serialized.includes(secret)) {
    throw new Error(`Sensitive value remained in event: ${secret}`);
  }
}
if (JSON.stringify(result.request) !== JSON.stringify({
  method: "POST",
  headers: {
    Accept: "application/json",
    "User-Agent": "Lagniappe Privacy Test",
  },
})) {
  throw new Error(`Unexpected request allowlist: ${JSON.stringify(result.request)}`);
}
if ("user" in result) {
  throw new Error("Sentry user context was not removed");
}
if (result.contexts.auth.password !== "[REDACTED]") {
  throw new Error("Nested password was not redacted");
}
if (result.contexts.auth.refreshTokens !== "[REDACTED]") {
  throw new Error("Plural token credential was not redacted");
}
if (result.contexts.auth.input_tokens !== 42) {
  throw new Error("Non-secret token count metadata was not preserved");
}
if (result.spans[0].data.prompt !== "[REDACTED]") {
  throw new Error("Provider prompt was not redacted");
}
if (result.spans[0].data["http.response.status_code"] !== 500) {
  throw new Error("Structural span metadata was not preserved");
}
""",
    )


# @features error-tracking
# @dimensions malformed-breadcrumbs privacy
def test_configure_sentry_drops_malformed_breadcrumb_container(run_node):
    run_error_tracking_check(
        run_node,
        """
configureSentry();

const result = sentryProcessorsRef[0]({
  message: "malformed breadcrumb event",
  breadcrumbs: { unexpected: "object instead of array" },
});

if ("breadcrumbs" in result) {
  throw new Error(`Malformed breadcrumbs reached the SDK: ${JSON.stringify(result)}`);
}
""",
    )


# @features error-tracking
# @dimensions configured-dsn privacy
def test_configure_sentry_uses_installation_dsn_without_default_pii(run_node):
    run_error_tracking_check(
        run_node,
        """
sentryStateRef.initialized = false;
configureSentry();

if (sentryInitsRef.length !== 1) {
  throw new Error(`Expected one Sentry initialization, got ${sentryInitsRef.length}`);
}
const options = sentryInitsRef[0];
if (options.dsn !== sentryStateRef.dsn) {
  throw new Error("Browser Sentry did not use the installation DSN");
}
if (options.sendDefaultPii !== false) {
  throw new Error("Browser Sentry did not explicitly disable default PII");
}
""",
    )


# @features error-tracking
# @dimensions disabled configured-dsn
def test_configure_sentry_does_not_initialize_without_dsn(run_node):
    run_error_tracking_check(
        run_node,
        """
sentryStateRef.initialized = false;
sentryStateRef.dsn = null;
configureSentry();

if (sentryInitsRef.length !== 0 || sentryProcessorsRef.length !== 0) {
  throw new Error("Browser Sentry initialized without a configured DSN");
}
""",
    )
