import type {
	BrowserOptions,
	Contexts,
	Event,
	EventHint,
	RequestEventData,
} from "@sentry/browser";

type MonitoredEvent = Omit<Event, "type"> & {
	type?: Event["type"] | "generic";
	culprit?: string;
	metadata?: { title?: string };
};

type ErrorDetails = { name?: unknown; message?: unknown; target?: unknown };
type NetworkErrorOptions = {
	method?: string;
	forceReport?: boolean;
} & Record<string, unknown>;

const getErrorDetails = (error: unknown): ErrorDetails | undefined =>
	error && (typeof error === "object" || typeof error === "function")
		? error
		: undefined;

const getElementContext = (element: unknown) => {
	const context: Contexts = {};
	if (!(element instanceof Element)) return context;

	// Element's own info
	context.element = {
		tagName: element.tagName?.toLowerCase(),
		id: element.id || undefined,
		className: element.className || undefined,
		dataset: { ...(element as HTMLElement | SVGElement).dataset },
	};

	// Closest widget
	const widget = element.closest<HTMLElement>("[data-widget]");
	if (widget && widget !== element) {
		context.widget = widget.dataset;
	}

	// Closest lp-component
	const component = element.closest<HTMLElement>("[lp-component]");
	if (component && component !== element) {
		context.component = component.dataset;
	}

	// Closest lp-view
	const view = element.closest<HTMLElement>("[lp-view]");
	if (view && view !== element) {
		context.view = view.dataset;
	}

	// Current URL info
	context.page = {
		pathname: window.location.pathname,
	};

	return context;
};

const sanitizedObjectContext = (value: object): Record<string, unknown> =>
	Object.fromEntries(
		Object.entries(value).filter(([, child]) => {
			return (
				child !== undefined &&
				typeof child !== "function" &&
				typeof child !== "symbol"
			);
		}),
	);

const normalizeContextValue = (
	value: unknown,
): Record<string, unknown> | null => {
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

const normalizeContext = (context: unknown): Contexts => {
	if (!(context instanceof Object)) return {};

	return Object.fromEntries(
		Object.entries(context).flatMap(([key, value]) => {
			const normalized = normalizeContextValue(value);
			return normalized && Object.keys(normalized).length
				? [[key, normalized]]
				: [];
		}),
	);
};

const getErrorText = (error: unknown) => {
	if (!error) return "";
	if (typeof error === "string") return error;
	const details = getErrorDetails(error);
	return `${details?.name || ""} ${details?.message || ""} ${String(error)}`.trim();
};

/**
 * View transition skips/aborts are expected during fast navigation, concurrent
 * transitions, and cross-document transitions. They should not be reported.
 *
 */
export const isSkippedViewTransitionError = (error: unknown) => {
	if (!error) return false;

	if (error instanceof DOMException && /transition/i.test(error.message)) {
		return true;
	}

	const text = getErrorText(error);
	if (!text) return false;

	return (
		/transition was (skipped|aborted)/i.test(text) ||
		(getErrorDetails(error)?.name === "InvalidStateError" &&
			/transition/i.test(text))
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

const _normalizedSentryKey = (key: string) =>
	String(key)
		.replace(/([a-z0-9])([A-Z])/g, "$1_$2")
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "_")
		.replace(/^_+|_+$/g, "");

const _isSensitiveSentryKey = (key: string) => {
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

const _sanitizeSentryText = (value: unknown) => {
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

type SanitizedValue =
	| string
	| number
	| boolean
	| null
	| SanitizedValue[]
	| { [key: string]: SanitizedValue };

const _sanitizeSentryValue = (
	value: unknown,
	key: string | null = null,
	depth = 0,
): SanitizedValue => {
	if (key !== null && _isSensitiveSentryKey(key)) return SENTRY_REDACTED;
	if (depth >= SENTRY_MAX_CONTEXT_DEPTH) return "[MAX DEPTH]";
	if (
		value === null ||
		typeof value === "boolean" ||
		typeof value === "number"
	) {
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

const _sanitizeSentryRequest = (request: RequestEventData | undefined) => {
	if (!request || typeof request !== "object") return undefined;

	const sanitized: RequestEventData = {};
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

const _invalidSentryTraceContext = (trace: unknown) => {
	if (!trace) return false;
	const traceId =
		typeof trace === "object" && "trace_id" in trace ? trace.trace_id : null;
	const spanId =
		typeof trace === "object" && "span_id" in trace ? trace.span_id : null;
	return (
		!SENTRY_TRACE_ID_PATTERN.test(String(traceId || "")) ||
		!SENTRY_SPAN_ID_PATTERN.test(String(spanId || ""))
	);
};

const _isNotificationTransaction = (event: MonitoredEvent) => {
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

const _isMalformedBlockingOperationWarning = (event: MonitoredEvent) => {
	return (
		event?.type === "generic" &&
		event?.level === "warning" &&
		event?.metadata?.title === SENTRY_BLOCKING_OPERATION_TITLE &&
		_invalidSentryTraceContext(event?.contexts?.trace) &&
		_isNotificationTransaction(event)
	);
};

const SANITIZED_SENTRY_FIELDS = [
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
] as const;

type SanitizedSentryField = (typeof SANITIZED_SENTRY_FIELDS)[number];

const _sanitizeSentryEvent = <T extends MonitoredEvent>(event: T): T | null => {
	if (!event) return event;
	if (_isMalformedBlockingOperationWarning(event)) return null;
	const sanitized: Omit<MonitoredEvent, SanitizedSentryField> &
		Partial<Record<SanitizedSentryField, unknown>> = {
		...event,
	};
	delete sanitized.user;

	const request = _sanitizeSentryRequest(event.request);
	if (request) sanitized.request = request;
	else delete sanitized.request;

	if ("breadcrumbs" in sanitized && !Array.isArray(sanitized.breadcrumbs)) {
		delete sanitized.breadcrumbs;
	}

	for (const key of SANITIZED_SENTRY_FIELDS) {
		if (key in sanitized) {
			sanitized[key] = _sanitizeSentryValue(event[key]);
		}
	}

	const sanitizedContexts = sanitized.contexts;
	if (
		sanitizedContexts &&
		typeof sanitizedContexts === "object" &&
		"trace" in sanitizedContexts &&
		_invalidSentryTraceContext(sanitizedContexts.trace)
	) {
		const { trace, ...contexts } = sanitizedContexts;
		sanitized.contexts =
			Object.keys(contexts).length > 0 ? contexts : undefined;
	}
	// The SDK callback receives the original event type with its reportable
	// values redacted, bounded, or removed.
	return sanitized as T;
};

const _filterNotificationBlockingSpans = <T extends MonitoredEvent>(
	event: T,
): T => {
	if (!_isNotificationTransaction(event) || !Array.isArray(event?.spans)) {
		return event;
	}

	const spans = event.spans.filter(
		(span) => !SENTRY_BLOCKING_SPAN_OPS.has(span?.op ?? ""),
	);
	return spans.length === event.spans.length ? event : { ...event, spans };
};

/**
 * Initialize the locally bundled browser Sentry client with the installation's
 * configured DSN, then apply the shared privacy and noise filters.
 *
 */
export const configureSentry = () => {
	const Sentry = typeof window !== "undefined" ? window.Sentry : null;
	if (!Sentry) return;

	const dsn =
		typeof document !== "undefined"
			? document
					.querySelector<HTMLMetaElement>('meta[name="sentry-dsn"]')
					?.content?.trim() || null
			: null;
	if (!dsn) return;

	Sentry.addEventProcessor?.(_sanitizeSentryEvent);

	const filterTransitionNoise = <T>(event: T, hint: EventHint) => {
		if (isSkippedViewTransitionError(hint?.originalException)) return null;
		return event;
	};

	type BeforeSend = NonNullable<BrowserOptions["beforeSend"]>;
	type BeforeSendTransaction = NonNullable<
		BrowserOptions["beforeSendTransaction"]
	>;
	const beforeSend =
		(prior?: BeforeSend): BeforeSend =>
		(event, hint) => {
			const transitionFiltered = filterTransitionNoise(event, hint);
			if (transitionFiltered === null) return null;

			const sanitized = _sanitizeSentryEvent(transitionFiltered);
			if (sanitized === null) return null;

			return prior ? prior(sanitized, hint) : sanitized;
		};

	const beforeSendTransaction =
		(prior?: BeforeSendTransaction): BeforeSendTransaction =>
		(event, hint) => {
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

	// Preserve the existing initialization setting alongside the SDK's options.
	const options: BrowserOptions & { sendDefaultPii: false } = {
		dsn,
		sendDefaultPii: false,
		ignoreErrors: SENTRY_IGNORED_TRANSITION_ERRORS,
		beforeSend: beforeSend(),
		beforeSendTransaction: beforeSendTransaction(),
	};
	Sentry.init?.(options);
};

/**
 * Fetch threw before a response (offline, navigation abort, tab freeze, etc.).
 * Not useful as a Sentry exception — noise on mobile especially.
 *
 */
export const isTransientNetworkError = (error: unknown) => {
	if (!error) return false;
	if (getErrorDetails(error)?.name === "AbortError") return true;
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

export const captureError = (
	error: unknown,
	element?: unknown,
	context?: object | null,
) => {
	if (isSkippedViewTransitionError(error)) {
		return;
	}
	const normalized = normalizeContext({
		...getElementContext(element || getErrorDetails(error)?.target),
		...(context || {}),
	});

	if (typeof window !== "undefined" && window.Sentry) {
		const captureContext =
			Object.keys(normalized).length > 0 ? { contexts: normalized } : undefined;

		if (error instanceof Error) {
			window.Sentry.captureException(error, captureContext);
		} else {
			window.Sentry.captureMessage(String(error), {
				level: "error",
				...captureContext,
			});
		}
	}

	const hasContext = Object.keys(normalized).length > 0;
	console.error("[ERROR]", error);
	if (hasContext) console.error("Context:", normalized);
};

export const captureNetworkError = (
	error: unknown,
	url: string | URL,
	options: NetworkErrorOptions = {},
) => {
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
