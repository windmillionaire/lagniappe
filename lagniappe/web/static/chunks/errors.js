/*! Third-party licenses: /third-party-licenses.txt */
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
const isSkippedViewTransitionError = (error) => {
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

/**
 * Fetch threw before a response (offline, navigation abort, tab freeze, etc.).
 * Not useful as a Sentry exception — noise on mobile especially.
 *
 * @testable false
 * @covered-by src/script/shared/errors.mjs::captureNetworkError
 * @reason transient-network predicate feeds network capture suppression
 */
const isTransientNetworkError = (error) => {
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
 * @features error-tracking
 * @dimensions sentry-context normalization
 */
const captureError = (error, element, context) => {
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
const captureNetworkError = (error, url, options = {}) => {
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

export { captureError, captureNetworkError, isSkippedViewTransitionError, isTransientNetworkError };
