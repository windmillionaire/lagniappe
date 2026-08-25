/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::captureError
 * @reason context extraction is reported through the public error capture helper
 */
const getElementContext = (element) => {
	const context = {};
	if (!(element instanceof Element)) return context;

	// Element's own info
	context.element = {
		tagName: element.tagName?.toLowerCase(),
		id: element.id || undefined,
		className: element.className || undefined,
		dataset: { ...element.dataset },
	};

	// Closest widget
	const widget = element.closest("[data-widget]");
	if (widget && widget !== element) {
		context.widget = widget.dataset;
	}

	// Closest lp-component
	const component = element.closest("[lp-component]");
	if (component && component !== element) {
		context.component = component.dataset;
	}

	// Closest lp-view
	const view = element.closest("[lp-view]");
	if (view && view !== element) {
		context.view = view.dataset;
	}

	// Current URL info
	context.page = {
		pathname: window.location.pathname,
	};

	return context;
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::captureError
 * @reason context value normalization is reported through the public error capture helper
 */
const sanitizedObjectContext = (value) =>
	Object.fromEntries(
		Object.entries(value).filter(([, child]) => {
			return (
				child !== undefined &&
				typeof child !== "function" &&
				typeof child !== "symbol"
			);
		}),
	);

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::captureError
 * @reason context value normalization is reported through the public error capture helper
 */
const normalizeContextValue = (value) => {
	if (
		value === undefined ||
		typeof value === "function" ||
		typeof value === "symbol"
	) {
		return null;
	}
	if (Array.isArray(value)) return { values: value };
	if (value && typeof value === "object") return sanitizedObjectContext(value);
	return { value };
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::captureError
 * @reason context normalization is reported through the public error capture helper
 */
const normalizeContext = (context) => {
	if (!(context instanceof Object)) return {};

	return Object.fromEntries(
		Object.entries(context)
			.map(([key, value]) => [key, normalizeContextValue(value)])
			.filter(([, value]) => value && Object.keys(value).length > 0),
	);
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::isSkippedViewTransitionError
 * @reason error text normalization only supports transition-noise filtering
 */
const getErrorText = (error) => {
	if (!error) return "";
	if (typeof error === "string") return error;
	return `${error.name || ""} ${error.message || ""} ${String(error)}`.trim();
};

/**
 * View transition skips/aborts are expected during fast navigation, concurrent
 * transitions, and cross-document transitions. They should not be reported.
 *
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::withTransition
 * @reason transition-noise predicate is exercised through the transition wrapper
 */
export const isSkippedViewTransitionError = (error) => {
	if (!error) return false;

	if (error instanceof DOMException && /transition/i.test(error.message)) {
		return true;
	}

	const text = getErrorText(error);
	if (!text) return false;

	return (
		/transition was (skipped|aborted)/i.test(text) ||
		(error.name === "InvalidStateError" && /transition/i.test(text))
	);
};

const SENTRY_IGNORED_TRANSITION_ERRORS = [
	/^Transition was (skipped|aborted)/i,
	/^InvalidStateError: Transition was (skipped|aborted)/i,
];

const SENTRY_SPAN_ID_PATTERN = /^[a-f0-9]{16}$/i;
const SENTRY_TRACE_ID_PATTERN = /^[a-f0-9]{32}$/i;
const SENTRY_BLOCKING_OPERATION_TITLE = "Blocking Operation";
const SENTRY_BLOCKING_SPAN_OPS = new Set([
	"ui.long-task",
	"ui.long-animation-frame",
]);
const SENTRY_NOTIFICATION_TRANSACTION_PATTERNS = [
	/^internal\.notifications$/,
	/(^|\s|\/)notifications(\?|$|\s)/,
];
const SENTRY_REDACTED = "[REDACTED]";
const SENTRY_MAX_CONTEXT_DEPTH = 8;
const SENTRY_MAX_CONTEXT_ITEMS = 25;
const SENTRY_MAX_CONTEXT_STRING_LENGTH = 512;
const SENTRY_ALLOWED_HEADERS = new Set([
	"accept",
	"user-agent",
	"x-lagniappe-request",
	"x-requested-with",
]);
const SENTRY_SAFE_TOKEN_METADATA_KEYS = new Set([
	"input_token_count",
	"input_tokens",
	"output_token_count",
	"output_tokens",
	"token_count",
	"total_token_count",
	"total_tokens",
]);
const SENTRY_SENSITIVE_KEYS = new Set([
	"authorization",
	"body",
	"content",
	"contents",
	"cookie",
	"cookies",
	"credential",
	"credentials",
	"document",
	"document_text",
	"dsn",
	"email",
	"email_address",
	"entity",
	"file_name",
	"filename",
	"form",
	"input",
	"inputs",
	"ip_address",
	"json",
	"locals",
	"message_history",
	"messages",
	"output",
	"outputs",
	"password",
	"passwd",
	"passphrase",
	"payload",
	"prompt",
	"prompts",
	"query",
	"query_string",
	"referer",
	"referrer",
	"remote_addr",
	"request_body",
	"response_body",
	"secret",
	"session",
	"sessionid",
	"set_cookie",
	"url",
	"user",
	"user_id",
	"username",
	"vars",
]);
const SENTRY_SECRET_ASSIGNMENT_PATTERN =
	/(["']?(?:password|passwd|passphrase|secret|api[_-]?key|private[_-]?key|access[_-]?token|refresh[_-]?token|auth(?:orization)?|cookie|session(?:id)?)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)/gi;
const SENTRY_AUTH_VALUE_PATTERN = /\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi;
const SENTRY_JWT_PATTERN =
	/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g;

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason event key normalization is exercised through Sentry privacy filtering
 */
const _normalizedSentryKey = (key) =>
	String(key)
		.replace(/([a-z0-9])([A-Z])/g, "$1_$2")
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "_")
		.replace(/^_+|_+$/g, "");

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason sensitive-key matching is exercised through Sentry privacy filtering
 */
const _isSensitiveSentryKey = (key) => {
	const normalized = _normalizedSentryKey(key);
	if (SENTRY_SENSITIVE_KEYS.has(normalized)) return true;

	const parts = new Set(normalized.split("_"));
	if (
		[
			"authorization",
			"cookie",
			"credential",
			"password",
			"passwd",
			"passphrase",
			"secret",
			"session",
		].some((part) => parts.has(part))
	) {
		return true;
	}
	if (parts.has("token") || parts.has("tokens")) {
		return !SENTRY_SAFE_TOKEN_METADATA_KEYS.has(normalized);
	}
	return (
		["api", "key"].every((part) => parts.has(part)) ||
		["private", "key"].every((part) => parts.has(part)) ||
		["signing", "key"].every((part) => parts.has(part)) ||
		["access", "code"].every((part) => parts.has(part))
	);
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason event text redaction and bounds are exercised through Sentry privacy filtering
 */
const _sanitizeSentryText = (value) => {
	let text = String(value);
	if (
		text.toUpperCase().includes("-----BEGIN") &&
		text.toUpperCase().includes("PRIVATE KEY-----")
	) {
		return SENTRY_REDACTED;
	}

	text = text
		.replace(
			SENTRY_SECRET_ASSIGNMENT_PATTERN,
			(_match, prefix) => `${prefix}${SENTRY_REDACTED}`,
		)
		.replace(SENTRY_AUTH_VALUE_PATTERN, SENTRY_REDACTED)
		.replace(SENTRY_JWT_PATTERN, SENTRY_REDACTED);
	return text.length > SENTRY_MAX_CONTEXT_STRING_LENGTH
		? `${text.slice(0, SENTRY_MAX_CONTEXT_STRING_LENGTH)}… [truncated]`
		: text;
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason recursive event sanitization is owned by the public Sentry setup helper
 */
const _sanitizeSentryValue = (value, key = null, depth = 0) => {
	if (key !== null && _isSensitiveSentryKey(key)) return SENTRY_REDACTED;
	if (depth >= SENTRY_MAX_CONTEXT_DEPTH) return "[MAX DEPTH]";
	if (value === null || ["boolean", "number"].includes(typeof value)) {
		return value;
	}
	if (typeof value === "string") return _sanitizeSentryText(value);
	if (Array.isArray(value)) {
		return value
			.slice(0, SENTRY_MAX_CONTEXT_ITEMS)
			.map((child) => _sanitizeSentryValue(child, null, depth + 1));
	}
	if (value && typeof value === "object") {
		return Object.fromEntries(
			Object.entries(value)
				.slice(0, SENTRY_MAX_CONTEXT_ITEMS)
				.map(([childKey, child]) => [
					_sanitizeSentryText(childKey),
					_sanitizeSentryValue(child, childKey, depth + 1),
				]),
		);
	}
	return `<${typeof value}>`;
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason SDK request fields are reduced through Sentry privacy filtering
 */
const _sanitizeSentryRequest = (request) => {
	if (!request || typeof request !== "object") return undefined;

	const sanitized = {};
	if (request.method) sanitized.method = _sanitizeSentryText(request.method);
	if (request.headers && typeof request.headers === "object") {
		const headers = Object.fromEntries(
			Object.entries(request.headers)
				.filter(([name]) => SENTRY_ALLOWED_HEADERS.has(name.toLowerCase()))
				.map(([name, value]) => [name, _sanitizeSentryText(value)]),
		);
		if (Object.keys(headers).length > 0) sanitized.headers = headers;
	}
	return Object.keys(sanitized).length > 0 ? sanitized : undefined;
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason Sentry-generated trace contexts are normalized through the public setup helper
 */
const _invalidSentryTraceContext = (trace) => {
	if (!trace) return false;
	return (
		!SENTRY_TRACE_ID_PATTERN.test(String(trace.trace_id || "")) ||
		!SENTRY_SPAN_ID_PATTERN.test(String(trace.span_id || ""))
	);
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason notification transaction detection only feeds Sentry warning filtering
 */
const _isNotificationTransaction = (event) => {
	const values = [
		event?.transaction,
		event?.culprit,
		event?.request?.url,
	].filter(Boolean);
	return values.some((value) =>
		SENTRY_NOTIFICATION_TRANSACTION_PATTERNS.some((pattern) =>
			pattern.test(String(value)),
		),
	);
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason Sentry-generated blocking-operation events bypass beforeSend
 */
const _isMalformedBlockingOperationWarning = (event) => {
	return (
		event?.type === "generic" &&
		event?.level === "warning" &&
		event?.metadata?.title === SENTRY_BLOCKING_OPERATION_TITLE &&
		_invalidSentryTraceContext(event?.contexts?.trace) &&
		_isNotificationTransaction(event)
	);
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason malformed Sentry trace contexts otherwise create invalid Relay events
 */
const _sanitizeSentryEvent = (event) => {
	if (!event) return event;
	if (_isMalformedBlockingOperationWarning(event)) return null;
	const sanitized = {
		...event,
	};
	delete sanitized.user;

	const request = _sanitizeSentryRequest(event.request);
	if (request) sanitized.request = request;
	else delete sanitized.request;

	if ("breadcrumbs" in sanitized && !Array.isArray(sanitized.breadcrumbs)) {
		delete sanitized.breadcrumbs;
	}

	for (const key of [
		"breadcrumbs",
		"contexts",
		"exception",
		"extra",
		"fingerprint",
		"logentry",
		"message",
		"spans",
		"tags",
		"threads",
	]) {
		if (key in sanitized) {
			sanitized[key] = _sanitizeSentryValue(sanitized[key]);
		}
	}

	if (_invalidSentryTraceContext(sanitized.contexts?.trace)) {
		const contexts = { ...sanitized.contexts };
		delete contexts.trace;
		sanitized.contexts =
			Object.keys(contexts).length > 0 ? contexts : undefined;
	}
	return sanitized;
};

/**
 * @testable false
 * @covered-by src/script/shared/errors.mjs::configureSentry
 * @reason notification refresh long-task spans are noisy Sentry-generated warnings
 */
const _filterNotificationBlockingSpans = (event) => {
	if (!_isNotificationTransaction(event) || !Array.isArray(event?.spans)) {
		return event;
	}

	const spans = event.spans.filter(
		(span) => !SENTRY_BLOCKING_SPAN_OPS.has(span?.op),
	);
	return spans.length === event.spans.length ? event : { ...event, spans };
};

/**
 * Initialize the locally bundled browser Sentry client with the installation's
 * configured DSN, then apply the shared privacy and noise filters.
 *
 * @testable true
 * @tests tests_js/test_015_error_tracking_frontend.py::test_configure_sentry_drops_malformed_blocking_operation_warning
 * @tests tests_js/test_015_error_tracking_frontend.py::test_configure_sentry_removes_invalid_trace_context_without_dropping_event
 * @tests tests_js/test_015_error_tracking_frontend.py::test_configure_sentry_filters_notification_long_task_spans
 * @tests tests_js/test_015_error_tracking_frontend.py::test_configure_sentry_redacts_browser_request_and_context_payloads
 * @tests tests_js/test_015_error_tracking_frontend.py::test_configure_sentry_drops_malformed_breadcrumb_container
 * @tests tests_js/test_015_error_tracking_frontend.py::test_configure_sentry_uses_installation_dsn_without_default_pii
 * @tests tests_js/test_015_error_tracking_frontend.py::test_configure_sentry_does_not_initialize_without_dsn
 * @matrix error-tracking : blocking-operation configured-dsn disabled malformed-blocking-operation malformed-breadcrumbs notification-transaction payload-bounds privacy redaction request-context sentry-context trace-normalization
 */
export const configureSentry = () => {
	const Sentry = typeof window !== "undefined" ? window.Sentry : null;
	if (!Sentry) return;

	const dsn =
		typeof document !== "undefined"
			? document.querySelector('meta[name="sentry-dsn"]')?.content?.trim() ||
				null
			: null;
	if (!dsn) return;

	Sentry.addEventProcessor?.(_sanitizeSentryEvent);

	/**
	 * @testable false
	 * @covered-by src/script/shared/errors.mjs::configureSentry
	 * @reason private beforeSend predicate for Sentry transition-noise filtering
	 */
	const filterTransitionNoise = (_event, hint) => {
		if (isSkippedViewTransitionError(hint?.originalException)) return null;
		return _event;
	};

	/**
	 * @testable false
	 * @covered-by src/script/shared/errors.mjs::configureSentry
	 * @reason callback composition is exercised through configureSentry setup tests
	 */
	const beforeSend = (prior) => (event, hint) => {
		const transitionFiltered = filterTransitionNoise(event, hint);
		if (transitionFiltered === null) return null;

		const sanitized = _sanitizeSentryEvent(transitionFiltered);
		if (sanitized === null) return null;

		return prior ? prior(sanitized, hint) : sanitized;
	};

	/**
	 * @testable false
	 * @covered-by src/script/shared/errors.mjs::configureSentry
	 * @reason callback composition is exercised through configureSentry setup tests
	 */
	const beforeSendTransaction = (prior) => (event, hint) => {
		const sanitized = _sanitizeSentryEvent(event);
		if (sanitized === null) return null;

		const filtered = _filterNotificationBlockingSpans(sanitized);
		return prior ? prior(filtered, hint) : filtered;
	};

	const client = Sentry.getClient?.();
	if (client) {
		const options = client.getOptions();
		options.beforeSend = beforeSend(options.beforeSend);
		options.beforeSendTransaction = beforeSendTransaction(
			options.beforeSendTransaction,
		);
		options.ignoreErrors = [
			...(options.ignoreErrors || []),
			...SENTRY_IGNORED_TRANSITION_ERRORS,
		];
		return;
	}

	Sentry.init?.({
		dsn,
		sendDefaultPii: false,
		ignoreErrors: SENTRY_IGNORED_TRANSITION_ERRORS,
		beforeSend: beforeSend(),
		beforeSendTransaction: beforeSendTransaction(),
	});
};

/**
 * Fetch threw before a response (offline, navigation abort, tab freeze, etc.).
 * Not useful as a Sentry exception — noise on mobile especially.
 *
 * @testable false
 * @covered-by src/script/shared/errors.mjs::captureNetworkError
 * @reason transient-network predicate feeds network capture suppression
 */
export const isTransientNetworkError = (error) => {
	if (!error) return false;
	if (error.name === "AbortError") return true;
	if (error instanceof TypeError) {
		const msg = error.message || "";
		return (
			msg === "Failed to fetch" ||
			msg === "Load failed" ||
			/NetworkError when attempting to fetch resource/i.test(msg)
		);
	}
	return false;
};

/**
 * @testable true
 * @tests tests_js/test_015_error_tracking_frontend.py::test_capture_error_normalizes_sentry_context_values
 * @matrix error-tracking : normalization sentry-context
 */
export const captureError = (error, element, context) => {
	if (isSkippedViewTransitionError(error)) {
		return;
	}
	context = normalizeContext({
		...getElementContext(element || error?.target),
		...(context || {}),
	});

	if (typeof window !== "undefined" && window.Sentry) {
		const captureContext =
			Object.keys(context).length > 0 ? { contexts: context } : undefined;

		if (error instanceof Error) {
			window.Sentry.captureException(error, captureContext);
		} else {
			window.Sentry.captureMessage(String(error), {
				level: "error",
				...captureContext,
			});
		}
	}

	const hasContext = Object.keys(context).length > 0;
	console.error("[ERROR]", error);
	if (hasContext) console.error("Context:", context);
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason network capture is reached through shared request failure handling
 */
export const captureNetworkError = (error, url, options = {}) => {
	if (!options.forceReport && isTransientNetworkError(error)) {
		return;
	}
	const context = {
		network: {
			url,
			method: options.method || "GET",
			timestamp: new Date().toISOString(),
			online: navigator.onLine,
		},
	};

	captureError(error, null, context);
};
