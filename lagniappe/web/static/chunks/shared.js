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

const PARSER = new DOMParser();
const TOKEN_REQUEST = {
	credentials: "include",
	headers: { "X-Lagniappe-Request": "true" },
};
const UPDATED_HEADER = "X-Lagniappe-Updated";
const INVALIDATE_CACHE_HEADER = "X-Lagniappe-Invalidate-Cache";
const ENTITY_REVISIONS_HEADER = "X-Lagniappe-Entity-Revisions";
const CSRF_FAILURE_HEADER = "X-Lagniappe-CSRF";
const CSRF_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const UPSTREAM_UPLOAD_OVERLOAD_ERROR = "Upload fewer files?";
const UPSTREAM_RESET_PATTERN =
	/upstream connect error|disconnect\/reset before headers|connection termination/i;
let _tokenRefresh = null;

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_non_csrf_bad_request_is_not_retried
 * @features csrf request-errors
 * @dimensions retry-classification
 */
const csrfFailed = (response) =>
	response.status === 400 &&
	response.headers.get(CSRF_FAILURE_HEADER)?.toLowerCase() === "invalid";

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason CSRF token lookup is part of the shared request envelope
 */
const _getToken = () => document.getElementById("token")?.value;

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_request_exposes_service_worker_updated_marker
 * @tests tests_js/test_009_request_csrf.py::test_request_exposes_client_cache_invalidation_marker
 * @tests tests_js/test_009_request_csrf.py::test_request_dispatches_entity_fingerprint_acknowledgement
 * @tests tests_js/test_009_request_csrf.py::test_request_supports_conditional_post_not_modified
 * @pair cache:conditional-response
 * @pair cache:etag
 * @pair cache:dom-refresh
 * @pair cache:invalidation
 * @pair cache:reload
 * @pair request:conditional-response
 * @pair request:etag
 * @pair request:dom-refresh
 * @pair request:invalidation
 * @pair request:reload
 * @pair request:acknowledgement
 * @pair request:response-headers
 * @pair request:multiple-entities
 * @pair edited-entity-notice:acknowledgement
 * @pair edited-entity-notice:response-headers
 * @pair edited-entity-notice:multiple-entities
 * @pair deferred-jobs:conditional-response
 * @pair deferred-jobs:etag
 */
const _formatResponse = async (
	response,
	{ acknowledgeEntities = true } = {},
) => {
	if (response.status === 304) {
		return {
			ok: true,
			unchanged: true,
			etag: response.headers.get("ETag"),
		};
	}
	const contentType = response.headers.get("content-type");
	let result = null;
	if (contentType?.includes("application/json")) {
		const data = (await response.json()) || {};
		result = {
			ok: response.ok,
			...data,
		};
	} else {
		result = {
			ok: response.ok,
			html: (await response.text()) || "",
		};
	}
	result.updated = response.headers.get(UPDATED_HEADER) !== "false";
	result.etag = response.headers.get("ETag");
	result.reload =
		Boolean(result.reload) || response.headers.has(INVALIDATE_CACHE_HEADER);
	const revisions = new Map();
	const revisionHeader = response.headers.get(ENTITY_REVISIONS_HEADER);
	if (revisionHeader) {
		try {
			for (const revision of JSON.parse(revisionHeader)) {
				if (revision?.key && revision?.fingerprint) {
					revisions.set(revision.key, revision);
				}
			}
		} catch {
			// Ignore a malformed optional acknowledgement header.
		}
	}
	result.entities = Array.from(revisions.values());
	if (acknowledgeEntities) {
		for (const entity of result.entities) {
			window.dispatchEvent(
				new CustomEvent("entity-updated", { detail: entity }),
			);
		}
	}
	if (result.html) {
		result.html = PARSER.parseFromString(result.html, "text/html");
	} else if (result.modal) {
		result.modal = PARSER.parseFromString(result.modal, "text/html");
	}
	return result;
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason upload overload detection is part of the shared error envelope
 */
const _isUploadBody = (body) => {
	if (!(body instanceof FormData)) return false;
	if (typeof body.has === "function" && body.has("direct_uploads")) return true;
	if (typeof body.has === "function" && body.has("assets")) return true;
	if (typeof body.entries !== "function") return true;

	for (const [, value] of body.entries()) {
		if (typeof File !== "undefined" && value instanceof File) return true;
		if (typeof Blob !== "undefined" && value instanceof Blob) return true;
	}
	return false;
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason proxy reset wording is not useful in upload forms
 */
const _friendlyError = (message, { body = null } = {}) => {
	if (_isUploadBody(body) && UPSTREAM_RESET_PATTERN.test(message || "")) {
		return UPSTREAM_UPLOAD_OVERLOAD_ERROR;
	}
	return message;
};

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_plain_text_upstream_error_stays_in_request_error_path
 * @tests tests_js/test_009_request_csrf.py::test_request_can_return_html_error_without_replacing_page
 * @pairs request-errors:proxy-text-error request-errors:ajax-upload
 * @pairs request-errors:non-invasive-probe request-errors:reload-fallback
 * @pairs edited-entity-notice:non-invasive-probe edited-entity-notice:reload-fallback
 */
const _formatError = async (
	response,
	{ replaceErrorPage = true, ...context } = {},
) => {
	const contentType = response.headers.get("content-type");
	if (contentType?.includes("application/json")) {
		const text = await response.text();
		try {
			const data = JSON.parse(text);
			if (data.error) {
				data.error = _friendlyError(data.error, context);
			}
			return { ok: false, ...data };
		} catch {
			return { ok: false, error: _friendlyError(text, context) };
		}
	}

	const text = await response.text();
	const title = response.headers.get("X-Lagniappe-Error");
	const fallback =
		text.trim() || title || response.statusText || "Network request failed";
	const error = _friendlyError(fallback, context);

	if (!contentType?.includes("text/html")) {
		return {
			ok: false,
			error,
		};
	}

	if (error !== fallback) {
		return {
			ok: false,
			error,
		};
	}

	if (!replaceErrorPage) {
		return {
			ok: false,
			error: _friendlyError(title || response.statusText || fallback, context),
		};
	}

	if (!title) {
		document.documentElement.innerHTML = text;
		document.title = response.statusText;
	} else {
		document.querySelector("main").innerHTML = text;
		document.title = title;
	}

	return {
		ok: false,
		error: _friendlyError(title || response.statusText || fallback, context),
	};
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason token refresh is the retry branch of the shared request wrapper
 */
const _refreshToken = async () => {
	try {
		const response = await fetch("/token", TOKEN_REQUEST);
		if (!response.ok) {
			throw new Error(`Failed to refresh token: ${response.statusText}`);
		}
		const newToken = (await response.text()).trim();
		if (!newToken) {
			throw new Error("Failed to refresh token: empty response");
		}
		const tokenElt = document.getElementById("token");
		if (tokenElt) {
			tokenElt.value = newToken;
		}
		return newToken;
	} catch (error) {
		captureNetworkError(error, "/token", { });
		return null;
	}
};

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_concurrent_stale_writes_share_server_controlled_token_refresh
 * @features csrf
 * @dimensions stale-token concurrent-refresh
 */
const refreshToken = async () => {
	if (!_tokenRefresh) {
		_tokenRefresh = _refreshToken().finally(() => {
			_tokenRefresh = null;
		});
	}
	return _tokenRefresh;
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason POST helper delegates to the shared request wrapper
 */
const postRequest = async (
	url,
	body,
	{ keepalive = false, headers = {} } = {},
) => {
	return _request(url, {
		method: "POST",
		body,
		keepalive,
		requestHeaders: headers,
	});
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason PATCH helper delegates to the shared request wrapper
 */
const patchRequest = async (url, body) => {
	return _request(url, { method: "PATCH", body });
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason DELETE helper delegates to the shared request wrapper
 */
const deleteRequest = async (url, body) => {
	return _request(url, { method: "DELETE", body });
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason GET helper delegates to the shared request wrapper
 */
const getRequest = async (url, params = null, options = {}) => {
	url = params ? `${url}?${new URLSearchParams(params).toString()}` : url;
	return _request(url, { method: "GET", ...options });
};

/**
 * @testable false
 * @covered-by src/script/shared/request.mjs::_request
 * @reason PUT helper delegates to the shared request wrapper
 */
const putRequest = async (url, body, options = {}) => {
	return _request(url, { method: "PUT", body, ...options });
};

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_request_supports_conditional_post_not_modified
 * @pair request:post-headers
 * @pair deferred-jobs:post-headers
 */
const _request = async (
	url,
	{
		method = "POST",
		body = null,
		keepalive = false,
		requestHeaders = {},
		acknowledgeEntities = true,
		replaceErrorPage = true,
	} = {},
) => {
	method = method.toUpperCase();
	const token = _getToken();
	const headers = {
		"Content-Type": "application/json",
		"X-CSRFToken": token,
		"X-Lagniappe-Request": "true",
		...requestHeaders,
	};

	const config = {
		method,
		headers,
		credentials: "include",
		...(keepalive ? { keepalive: true } : {}),
	};

	if (body) {
		if (body instanceof FormData) {
			delete headers["Content-Type"];
			config.body = body;
		} else {
			config.body = JSON.stringify(body);
		}
	}

	if (!CSRF_METHODS.has(method)) {
		delete headers["X-CSRFToken"];
	}

	try {
		let response = await fetch(url, config);

		if (CSRF_METHODS.has(method) && csrfFailed(response)) {
			const newToken = await refreshToken();
			if (!newToken) {
				return {
					ok: false,
					error: "Failed to refresh authentication token",
				};
			}
			config.headers["X-CSRFToken"] = newToken;
			response = await fetch(url, config);
		}

		if (response.status === 422) {
			return {
				ok: false,
				error: await response.text(),
			};
		}

		if (response.redirected) {
			window.location.href = response.url;
			return;
		}

		return response.ok || response.status === 304
			? _formatResponse(response, { acknowledgeEntities })
			: _formatError(response, { body, method, url, replaceErrorPage });
	} catch (error) {
		captureNetworkError(error, url, { method, ...config });
		return {
			ok: false,
			error: error.message || "Network request failed",
		};
	}
};

const request = {
	csrfFailed,
	token: refreshToken,
	put: putRequest,
	post: postRequest,
	patch: patchRequest,
	delete: deleteRequest,
	get: getRequest,
};

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason metadata lookup is private analytics payload plumbing
 */
const meta = (name) =>
	document.querySelector(`meta[name="${name}"]`)?.getAttribute("content") || "";

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason CSRF token lookup is private analytics request plumbing
 */
const token = () => document.getElementById("token")?.value || "";

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason analytics enablement is owned by the shared manager contract
 */
const analyticsEnabled = () => meta("analytics") === "true";

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason browser navigation metadata is private analytics payload plumbing
 */
const navigationType = () => {
	const navigation = performance.getEntriesByType?.("navigation")?.[0];
	return navigation?.type || "";
};

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason analytics title lookup prefers entity view headers without requiring every route to add metadata
 */
const pageTitle = () =>
	meta("analytics-title") ||
	document
		.querySelector("[lp-view] [data-nav='view'] [data-role='title']")
		?.textContent?.trim() ||
	document.title.trim();

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason view payload construction is owned by the shared analytics manager
 */
const viewData = (action) => {
	const view = document.querySelector("[lp-view]");
	return {
		action,
		path: window.location.pathname,
		query: window.location.search || "",
		page_title: pageTitle(),
		view_kind: view?.dataset.kind || "",
		entity_key: view?.dataset.key || "",
		entity_hash: view?.dataset.hash || "",
		index: view?.dataset.index || "",
		public_id: meta("analytics-public-id"),
		referrer: document.referrer || "",
		navigation_type: navigationType(),
	};
};

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_analytics_dashboard_owner_filter_and_retention_clear
 * @features analytics
 * @dimensions page-load
 */
class AnalyticsManager {
	get enabled() {
		return analyticsEnabled();
	}

	get mode() {
		return meta("mode");
	}

	async tag(action, payload = {}) {
		if (!this.enabled) return;

		const path = payload.path || window.location.pathname;
		if (
			["view", "public_view"].includes(action) &&
			path.startsWith("/analytics")
		) {
			return;
		}

		try {
			const body = JSON.stringify({ ...payload, action, path });
			const send = () =>
				fetch("/analytics/track", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						"X-CSRFToken": token(),
						"X-Lagniappe-Request": "true",
					},
					credentials: "include",
					keepalive: true,
					body,
				});
			const response = await send();
			if (request.csrfFailed(response) && (await request.token())) {
				await send();
			}
		} catch {
			// Analytics must never affect the page using it.
		}
	}

	view() {
		const action = meta("analytics-action") || "view";
		this.tag(action, viewData(action));
	}
}

const analytics = new AnalyticsManager();

var id = "lagniappe-browser";
var version = 3;
var messages = {
	CONNECTIVITY: "connectivity-state"
};
var connectivity$1 = {
	browser: [
		"online",
		"offline"
	],
	server: [
		"unknown",
		"online",
		"offline"
	],
	visibility: [
		"visible",
		"hidden"
	],
	controller: [
		"controlled",
		"uncontrolled"
	]
};
var BROWSER_PROTOCOL = {
	id: id,
	version: version,
	messages: messages,
	connectivity: connectivity$1
};

const DEFAULT_STATE = Object.freeze({
	browser: "online",
	server: "unknown",
	visibility: "visible",
	controller: "uncontrolled",
});

/**
 * Owns the four independent connectivity signals used by the application.
 * Server reachability remains authoritative for application requests, while
 * browser link state is a scheduling hint and unknown server state is treated
 * optimistically during startup.
 *
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_state_table_covers_lifecycle_transitions
 * @features connectivity
 * @dimensions startup browser-state server-health polling-recovery visibility controller
 */
class ConnectivityState {
	constructor(initial = {}) {
		this._state = DEFAULT_STATE;
		this.transition(initial);
	}

	get online() {
		return this._state.browser === "online" && this._state.server !== "offline";
	}

	get hidden() {
		return this._state.visibility === "hidden";
	}

	snapshot() {
		return Object.freeze({ ...this._state });
	}

	transition(patch = {}) {
		const next = { ...this._state };
		for (const [field, value] of Object.entries(patch)) {
			const allowed = BROWSER_PROTOCOL.connectivity[field];
			if (!allowed?.includes(value)) {
				throw new TypeError(`Invalid connectivity ${field}: ${value}`);
			}
			next[field] = value;
		}
		this._state = Object.freeze(next);
		return this.snapshot();
	}
}

const browserOnline =
	typeof navigator === "undefined" || navigator.onLine !== false;
const visible = typeof document === "undefined" || document.hidden !== true;
const controlled = Boolean(
	typeof navigator !== "undefined" && navigator.serviceWorker?.controller,
);

const connectivity = new ConnectivityState({
	browser: browserOnline ? "online" : "offline",
	visibility: visible ? "visible" : "hidden",
	controller: controlled ? "controlled" : "uncontrolled",
});

const ICONS = {
  "add": {
    "glyph": "add",
    "fill": 1
  },
  "addRow": {
    "glyph": "add_circle",
    "fill": 0
  },
  "alignCenter": {
    "glyph": "format_align_center",
    "fill": 1
  },
  "alignJustify": {
    "glyph": "format_align_justify",
    "fill": 1
  },
  "alignMenu": {
    "glyph": "subject",
    "fill": 1
  },
  "alignLeft": {
    "glyph": "format_align_left",
    "fill": 1
  },
  "alignRight": {
    "glyph": "format_align_right",
    "fill": 1
  },
  "analytics": {
    "glyph": "graph_3",
    "fill": 1
  },
  "ask": {
    "glyph": "chat",
    "fill": 1
  },
  "assignedBy": {
    "glyph": "person_edit",
    "fill": 1
  },
  "assignedTo": {
    "glyph": "assignment_ind",
    "fill": 1
  },
  "attribute": {
    "add": {
      "glyph": "add_circle",
      "fill": 1
    },
    "remove": {
      "glyph": "do_not_disturb_on",
      "fill": 1
    }
  },
  "back": {
    "glyph": "arrow_back",
    "fill": 1
  },
  "billing": {
    "glyph": "credit_card",
    "fill": 1
  },
  "block": {
    "glyph": "vertical_distribute",
    "fill": 1
  },
  "bold": {
    "glyph": "format_bold",
    "fill": 1
  },
  "bookmark": {
    "glyph": "bookmark",
    "fill": 1
  },
  "builder": {
    "saved": {
      "glyph": "cloud_done",
      "fill": 1
    },
    "unsaved": {
      "glyph": "cloud_alert",
      "fill": 1
    }
  },
  "cached": {
    "glyph": "cloud_off",
    "fill": 1
  },
  "category": {
    "glyph": "stacks",
    "fill": 1
  },
  "center": {
    "glyph": "align_horizontal_center",
    "fill": 1
  },
  "check": {
    "glyph": "check",
    "fill": 1
  },
  "checkbox": {
    "glyph": "check_box",
    "fill": 1
  },
  "checklist": {
    "glyph": "checklist",
    "fill": 1
  },
  "clear": {
    "glyph": "do_not_disturb_on",
    "fill": 1
  },
  "clearFormat": {
    "glyph": "format_clear",
    "fill": 1
  },
  "close": {
    "glyph": "close",
    "fill": 1
  },
  "cloudflare": {
    "glyph": "cloud",
    "fill": 1
  },
  "code": {
    "glyph": "code",
    "fill": 1
  },
  "column": {
    "glyph": "view_column",
    "fill": 1
  },
  "columns": {
    "glyph": "dehaze",
    "fill": 1
  },
  "completed": {
    "glyph": "event_available",
    "fill": 1
  },
  "completedBy": {
    "glyph": "person_check",
    "fill": 1
  },
  "configuration": {
    "glyph": "tune",
    "fill": 1
  },
  "contract": {
    "glyph": "arrow_drop_down",
    "fill": 1
  },
  "create": {
    "glyph": "wb_iridescent",
    "fill": 1
  },
  "csv": {
    "glyph": "csv",
    "fill": 1
  },
  "database": {
    "glyph": "database",
    "fill": 1
  },
  "date": {
    "glyph": "event",
    "fill": 1
  },
  "delete": {
    "glyph": "delete_forever",
    "fill": 1
  },
  "directory": {
    "glyph": "signpost",
    "fill": 1
  },
  "document": {
    "glyph": "article",
    "fill": 1
  },
  "down": {
    "glyph": "keyboard_arrow_down",
    "fill": 1
  },
  "download": {
    "glyph": "cloud_download",
    "fill": 1
  },
  "dropdown": {
    "glyph": "keyboard_arrow_down",
    "fill": 1
  },
  "dueDate": {
    "glyph": "event",
    "fill": 1
  },
  "edit": {
    "glyph": "amend",
    "fill": 0
  },
  "email": {
    "glyph": "alternate_email",
    "fill": 1
  },
  "error": {
    "glyph": "error",
    "fill": 1
  },
  "expand": {
    "glyph": "arrow_right",
    "fill": 1
  },
  "file": {
    "glyph": "description",
    "fill": 1
  },
  "fileText": {
    "glyph": "description",
    "fill": 1
  },
  "files": {
    "glyph": "work",
    "fill": 1
  },
  "filter": {
    "active": {
      "glyph": "filter_list",
      "fill": 1
    },
    "inactive": {
      "glyph": "filter_list_off",
      "fill": 0
    },
    "list": {
      "glyph": "action_key",
      "fill": 1
    }
  },
  "flipper": {
    "left": {
      "glyph": "chevron_left",
      "fill": 1
    }
  },
  "floatLeft": {
    "glyph": "format_image_left",
    "fill": 1
  },
  "floatRight": {
    "glyph": "format_image_right",
    "fill": 1
  },
  "fontStyle": {
    "glyph": "brand_family",
    "fill": 1
  },
  "form": {
    "glyph": "dynamic_form",
    "fill": 1
  },
  "generate": {
    "glyph": "memory",
    "fill": 1
  },
  "google": {
    "glyph": "public",
    "fill": 1
  },
  "group": {
    "glyph": "group",
    "fill": 1
  },
  "h1": {
    "glyph": "format_h1",
    "fill": 1
  },
  "h2": {
    "glyph": "format_h2",
    "fill": 1
  },
  "h3": {
    "glyph": "format_h3",
    "fill": 1
  },
  "help": {
    "glyph": "question_mark",
    "fill": 1
  },
  "history": {
    "glyph": "history",
    "fill": 1
  },
  "home": {
    "glyph": "home",
    "fill": 1
  },
  "html": {
    "glyph": "html",
    "fill": 1
  },
  "image": {
    "glyph": "image",
    "fill": 1
  },
  "imageAlign": {
    "left": {
      "glyph": "format_image_break_left",
      "fill": 1
    },
    "center": {
      "glyph": "align_justify_center",
      "fill": 1
    },
    "right": {
      "glyph": "format_image_break_right",
      "fill": 1
    }
  },
  "import": {
    "glyph": "upload_file",
    "fill": 1
  },
  "increase": {
    "glyph": "add",
    "fill": 1
  },
  "indexTools": {
    "glyph": "build_circle",
    "fill": 1
  },
  "insert": {
    "glyph": "add",
    "fill": 1
  },
  "in": {
    "glyph": "open_in_new_down",
    "fill": 1
  },
  "info": {
    "glyph": "ballot",
    "fill": 1
  },
  "input": {
    "glyph": "keyboard_alt",
    "fill": 0
  },
  "installation": {
    "glyph": "download",
    "fill": 1
  },
  "integration": {
    "glyph": "extension",
    "fill": 1
  },
  "italic": {
    "glyph": "format_italic",
    "fill": 1
  },
  "launch": {
    "glyph": "rocket_launch",
    "fill": 1
  },
  "left": {
    "glyph": "arrow_back",
    "fill": 1
  },
  "link": {
    "glyph": "link_2",
    "fill": 1
  },
  "listOl": {
    "glyph": "format_list_numbered",
    "fill": 1
  },
  "listUl": {
    "glyph": "format_list_bulleted",
    "fill": 1
  },
  "location": {
    "glyph": "location_on",
    "fill": 1
  },
  "login": {
    "glyph": "login",
    "fill": 1
  },
  "logout": {
    "glyph": "logout",
    "fill": 1
  },
  "manual": {
    "glyph": "help",
    "fill": 1
  },
  "map": {
    "glyph": "map",
    "fill": 1
  },
  "maximize": {
    "glyph": "fullscreen",
    "fill": 1
  },
  "menu": {
    "glyph": "keyboard_arrow_down",
    "fill": 1
  },
  "minimize": {
    "glyph": "fullscreen_exit",
    "fill": 1
  },
  "minus": {
    "glyph": "remove",
    "fill": 1,
    "weight": 600
  },
  "model": {
    "glyph": "automation",
    "fill": 1
  },
  "next": {
    "glyph": "arrow_forward",
    "fill": 1
  },
  "nextWeek": {
    "glyph": "calendar_month",
    "fill": 1
  },
  "notes": {
    "glyph": "note_stack",
    "fill": 1
  },
  "number": {
    "glyph": "tag",
    "fill": 1
  },
  "offline": {
    "glyph": "cloud_off",
    "fill": 1
  },
  "organize": {
    "glyph": "folder",
    "fill": 1
  },
  "out": {
    "glyph": "open_in_new",
    "fill": 1
  },
  "overview": {
    "glyph": "collections_bookmark",
    "fill": 1
  },
  "page": {
    "glyph": "draft",
    "fill": 1
  },
  "paragraph": {
    "glyph": "format_paragraph",
    "fill": 1
  },
  "paste": {
    "glyph": "content_paste",
    "fill": 1
  },
  "permissions": {
    "glyph": "lock_open",
    "fill": 1
  },
  "personalization": {
    "glyph": "palette",
    "fill": 1
  },
  "pin": {
    "glyph": "keep",
    "fill": 1
  },
  "plus": {
    "glyph": "add_2",
    "fill": 1,
    "weight": 600
  },
  "private": {
    "glyph": "lock",
    "fill": 1
  },
  "project": {
    "glyph": "flowsheet",
    "fill": 0
  },
  "prompt": {
    "glyph": "terminal",
    "fill": 1
  },
  "public": {
    "glyph": "public",
    "fill": 1
  },
  "question": {
    "glyph": "help",
    "fill": 1
  },
  "quoteRight": {
    "glyph": "format_quote",
    "fill": 1
  },
  "radio": {
    "glyph": "radio_button_checked",
    "fill": 1
  },
  "recurring": {
    "glyph": "repeat",
    "fill": 1
  },
  "redo": {
    "glyph": "redo",
    "fill": 1
  },
  "remove": {
    "glyph": "cancel",
    "fill": 1
  },
  "removeDueDate": {
    "glyph": "event_busy",
    "fill": 1
  },
  "replace": {
    "glyph": "sync",
    "fill": 1
  },
  "reset": {
    "glyph": "restart_alt",
    "fill": 1
  },
  "right": {
    "glyph": "arrow_forward",
    "fill": 1
  },
  "run": {
    "active": {
      "glyph": "play_arrow",
      "fill": 1
    },
    "inactive": {
      "glyph": "play_arrow",
      "fill": 0
    }
  },
  "search": {
    "glyph": "search",
    "fill": 1
  },
  "security": {
    "glyph": "key",
    "fill": 1
  },
  "select": {
    "glyph": "top_panel_open",
    "fill": 1
  },
  "selected": {
    "glyph": "check_box",
    "fill": 1
  },
  "settings": {
    "page": {
      "glyph": "settings",
      "fill": 1
    }
  },
  "signature": {
    "glyph": "draw",
    "fill": 1
  },
  "sitemap": {
    "glyph": "account_tree",
    "fill": 1
  },
  "siteOwner": {
    "glyph": "admin_panel_settings",
    "fill": 1
  },
  "siteSettings": {
    "glyph": "settings",
    "fill": 1
  },
  "skipped": {
    "glyph": "assignment_late",
    "fill": 1
  },
  "snooze": {
    "glyph": "snooze",
    "fill": 1
  },
  "spinner": {
    "glyph": "donut_large",
    "fill": 1,
    "spin": true
  },
  "star": {
    "home": {
      "glyph": "star",
      "fill": 1
    },
    "active": {
      "glyph": "star",
      "fill": 1
    },
    "inactive": {
      "glyph": "star",
      "fill": 0,
      "weight": 300
    }
  },
  "start": {
    "glyph": "first_page",
    "fill": 1
  },
  "status": {
    "glyph": "sticky_note_2",
    "fill": 1
  },
  "strikethrough": {
    "glyph": "format_strikethrough",
    "fill": 1
  },
  "subscript": {
    "glyph": "subscript",
    "fill": 1
  },
  "success": {
    "glyph": "check_circle",
    "fill": 1
  },
  "superscript": {
    "glyph": "superscript",
    "fill": 1
  },
  "table": {
    "glyph": "table",
    "fill": 1
  },
  "tableEdit": {
    "glyph": "table_edit",
    "fill": 0
  },
  "task": {
    "glyph": "check_box",
    "fill": 1
  },
  "tasks": {
    "glyph": "check_box",
    "fill": 1
  },
  "tel": {
    "glyph": "phone",
    "fill": 1
  },
  "text": {
    "glyph": "keyboard_alt",
    "fill": 0
  },
  "textColor": {
    "glyph": "format_color_text",
    "fill": 1
  },
  "textStyle": {
    "glyph": "text_format",
    "fill": 1
  },
  "textarea": {
    "glyph": "subject",
    "fill": 1
  },
  "time": {
    "glyph": "schedule",
    "fill": 1
  },
  "todo": {
    "ok": {
      "glyph": "calendar_today",
      "fill": 1
    },
    "overdue": {
      "glyph": "calendar_clock",
      "fill": 1
    },
    "today": {
      "glyph": "today",
      "fill": 1
    }
  },
  "tomorrow": {
    "glyph": "fast_forward",
    "fill": 1
  },
  "trash": {
    "active": {
      "glyph": "delete_forever",
      "fill": 1
    },
    "inactive": {
      "glyph": "delete_forever",
      "fill": 0,
      "weight": 300
    }
  },
  "underline": {
    "glyph": "format_underlined",
    "fill": 1
  },
  "undo": {
    "glyph": "undo",
    "fill": 1
  },
  "unselected": {
    "glyph": "check_box_outline_blank",
    "fill": 0
  },
  "up": {
    "glyph": "keyboard_arrow_up",
    "fill": 1
  },
  "upload": {
    "glyph": "cloud_upload",
    "fill": 1
  },
  "url": {
    "glyph": "highlight_mouse_cursor",
    "fill": 1
  },
  "user": {
    "glyph": "person",
    "fill": 1
  },
  "users": {
    "glyph": "group",
    "fill": 1
  },
  "weekend": {
    "glyph": "date_range",
    "fill": 1
  },
  "x": {
    "glyph": "close",
    "fill": 1,
    "weight": 600
  },
  "youtube": {
    "glyph": "smart_display",
    "fill": 1
  }
};
const STYLES = {
  "badge": {
    "builder": "ring-kind-light inline-flex items-center gap-1.5 rounded-md bg-white py-1 pr-2.5 pl-2 text-sm/6 font-medium whitespace-nowrap text-base-default ring ring-inset sm:text-xs/5",
    "default": "lp-badge ring-kind-light inline-flex min-w-0 max-w-full items-center gap-1 overflow-hidden rounded-md bg-white py-1 pl-2 pr-2.5 text-sm/6 font-medium whitespace-nowrap text-kind-default ring ring-inset",
    "icon": "icon-base text-kind-default"
  },
  "builder": {
    "component": "text-md flex cursor-move flex-row items-center gap-3 rounded-md bg-form-bg px-3 py-1.5 font-semibold text-base-dark shadow-sm outline-2 outline-form-default hover:bg-form-light hover:outline-form-dark",
    "model": "form-element rounded-md bg-base-bg p-2 text-sm data-[selected=true]:outline-2 data-[selected=true]:outline-kind-default",
    "settings": {
      "item": "flex flex-row items-center justify-between group",
      "section": "flex flex-col gap-1 sm:text-sm p-2 rounded-md outline-2 bg-form-bg outline-form-default",
      "title": "sm:text-sm font-semibold flex justify-between items-center text-base-dark",
      "toggle": {
        "container": "grid place-items-center rounded-md hover:bg-white text-form-default transition-colors duration-100 hover:outline-kind-default focus:outline-none focus-visible:outline-kind-default focus-visible:bg-white hover:shadow-sm",
        "icon": "icon-xs text-kind-default"
      }
    }
  },
  "button": {
    "submit": "grid grow place-items-center rounded-md bg-kind-default px-3 py-1.5 text-base font-semibold text-white shadow-sm action-button",
    "explain": "inline-flex items-center gap-1 text-sm font-semibold justify-center",
    "close": "ml-2 text-center text-base rounded-md px-2.5 py-1 font-semibold shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 hover:outline-2 hover:outline-offset-2 text-white bg-delete-default hover:bg-delete-dark outline-delete-default hover:outline-delete-dark",
    "group": "flex flex-col sm:flex-row gap-3",
    "cancel": "ml-auto grid size-6 translate-x-1 place-items-center rounded-md text-delete-default hover:outline-2 hover:outline-delete-default focus-visible:outline-2 focus-visible:outline-delete-default hover:bg-delete-bg focus-visible:bg-delete-bg transition-colors duration-100"
  },
  "checkbox": {
    "container": "grid size-5 shrink-0 place-items-center",
    "default": "form-input [grid-area:1/1] size-5 appearance-none rounded-sm text-white",
    "icon": "checkbox-icon [grid-area:1/1] pointer-events-none text-white",
    "label": "flex flex-row items-start gap-2 font-semibold text-base-dark sm:text-sm py-1",
    "grid": "grid grid-cols-[repeat(auto-fit,minmax(100px,1fr))] lg:grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-x-4 gap-y-2 sm:text-sm border-t border-base-medium pt-4"
  },
  "dropdown": {
    "menu": "absolute z-101 flex min-w-37.5 flex-col gap-1 rounded-md bg-white p-1 shadow-lg outline outline-base-light/50",
    "icon": "dropdown-option-icon",
    "option": {
      "action": "dropdown-option dropdown-option-action cursor-default",
      "flow": "dropdown-option dropdown-option-flow cursor-default",
      "multiple": "dropdown-option-multiple"
    },
    "panel": "p-1 scrollbar-thin scrollbar-thumb-base-light scrollbar-track-transparent absolute z-50 hidden max-h-96 min-w-64 overflow-y-auto rounded-md bg-white shadow-lg outline outline-base-light/50",
    "search": {
      "result": "dropdown-option dropdown-option-flow cursor-default",
      "link": "dropdown-option dropdown-option-flow cursor-pointer"}
  },
  "editor": {
    "toolbar": {
      "container": {
        "page": "group/toolbar sticky top-16 z-40 border-b border-base-light/50 bg-base-bg p-4 sm:border-t sm:px-6",
        "project": "group/toolbar sticky top-16 z-40 border-b border-base-light/50 bg-base-bg p-4 sm:border-t sm:px-6",
        "form": "group/toolbar border-b border-base-light/50 bg-base-bg p-4 sm:p-6",
        "email": "group/toolbar border-b border-base-light/50 bg-base-bg p-2 sm:p-4",
        "default": "group/toolbar mt-4 border-base-light/50 bg-base-bg"
      },
      "divider": "mx-1 hidden h-6 w-px bg-base-light/50 md:block md:first:hidden md:last:hidden",
      "section": "flex flex-row items-center gap-2",
      "tool": "grid size-8 place-items-center rounded-md bg-white outline outline-base-light/50 shadow-sm",
      "menu": "flex min-h-8 w-fit flex-row items-center gap-1 rounded-md bg-white outline outline-base-light/50 px-2 py-1 text-center text-base font-semibold shadow-sm",
      "optionHeader": "text-lg font-bold pt-2 text-kind-default pb-1",
      "optionPanel": "outline rounded-md px-4 pb-4 flex flex-col bg-white outline-base-light mt-2",
      "tools": "flex flex-row flex-wrap items-center gap-2 sm:gap-3",
      "imageSettings": "group mt-4 hidden flex-row flex-wrap items-center gap-2 group-data-[open-form='setImage']/toolbar:flex",
      "iconContext": "editor-toolbar-icon-context",
      "portalIconContext": "editor-toolbar-portal-icon-context",
      "menuIcon": "editor-toolbar-menu-icon",
      "historyIcon": "editor-toolbar-history-icon",
      "caret": "editor-toolbar-caret opacity-50"
    },
    "container": "html-content min-h-50 px-4 pt-6 pb-4 focus:outline-none sm:px-6 sm:pt-8 sm:pb-6"
  },
  "entity": {
    "name": {
      "wrapper": "min-w-0",
      "parent": "whitespace-nowrap",
      "separator": "mx-1 text-base-medium"}
  },
  "form": {
    "header": {
      "container": "flex flex-row items-center justify-between gap-6",
      "title": "text-lg font-semibold text-kind-default flex flex-row items-center gap-2",
      "controls": "flex flex-row items-center gap-1"
    },
    "icon": "text-kind-default hover:text-kind-dark focus-visible:text-kind-dark focus-visible:bg-kind-bg focus-visible:outline-none ml-1 inline-grid place-items-center rounded-full",
    "table": {
      "body": "divide-y-kind-bg w-full border-t border-base-light",
      "container": "max-w-full flex flex-col gap-2 min-w-0",
      "table": "w-max min-w-full table-auto border-collapse bg-white sm:text-sm",
      "form": "table-container rounded-md p-4 flex flex-col gap-6 bg-base-bg",
      "cell": {
        "th": "w-72 min-w-48 max-w-88 p-3 text-left font-medium whitespace-nowrap",
        "default": "w-72 min-w-48 max-w-88 px-3 py-2 align-top text-left font-medium whitespace-normal [overflow-wrap:anywhere]",
        "compact": {
          "th": "w-28 min-w-24 max-w-32 p-3 text-left font-medium leading-snug whitespace-normal",
          "default": "w-28 min-w-24 max-w-32 px-3 py-2 align-top text-left font-medium whitespace-nowrap"
        },
        "title": "flex flex-row items-center gap-1"
      },
      "rowActions": "table-row-actions absolute top-0 right-0 z-20 m-0 flex h-8 w-max flex-row items-center rounded-bl-md border-b border-l border-kind-bg bg-base-bg px-1",
      "rowActionCell": "sticky right-0 z-20 w-px min-w-px max-w-px p-0 align-top overflow-visible",
      "rowActionHeader": "w-px min-w-px max-w-px p-0",
      "actionButton": "grid size-6 place-items-center rounded-sm text-kind-default outline-offset-0 transition-colors duration-100 hover:bg-white hover:text-kind-dark hover:outline hover:outline-kind-default focus-visible:bg-white focus-visible:text-kind-dark focus-visible:outline focus-visible:outline-kind-default disabled:pointer-events-none disabled:opacity-50"
    },
    "elementLabel": "flex flex-col gap-1 font-semibold sm:text-sm text-base-dark",
    "submission": {
      "default": "submission-outline flex min-h-10 w-fit flex-row items-center justify-center rounded-md bg-white/60 px-3 py-1.25 font-medium shadow-xs sm:text-sm",
      "grows": "submission-outline w-fit rounded-md bg-white/60 px-3 py-2.5 font-medium shadow-xs sm:text-sm"
    }
  },
  "note": {
    "item": {
      "home": "group/note flex items-start justify-between gap-3 rounded-sm border border-note-light bg-note-bg px-3 py-3 text-base-dark shadow-sm"},
    "content": "flex min-w-0 flex-1 flex-col gap-3",
    "body": "whitespace-pre-wrap break-words text-sm font-medium leading-relaxed text-base-dark",
    "photo": {
      "home": "max-h-48 w-auto max-w-full rounded-md object-contain"},
    "meta": "flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-normal text-base-medium",
    "discard": "grid size-7 shrink-0 place-items-center rounded-md text-base-medium hover:bg-white hover:text-delete-default focus-visible:outline-2 focus-visible:outline-delete-default"
  },
  "icon": {
    "default": "text-kind-default"
  },
  "iconLabel": {
    "wrapper": "flow-root min-w-0 text-left",
    "icon": "float-left mr-2"
  },
  "index": {
    "tools": {
      "dropdown": {
        "toggle": "rounded-md px-2 py-1.5 font-semibold text-kind-default hover:bg-kind-light hover:text-kind-dark text-right",
        "panel": "outline-kind-light absolute z-101 flex min-w-37.5 flex-col gap-1 rounded-md outline-2 bg-kind-bg p-1 shadow-lg"
      }}
  },
  "input": "h-10 form-input w-full rounded-md px-3 py-1.25 text-base sm:text-sm font-normal",
  "label": {
    "default": "sm:text-sm font-semibold text-base-dark",
    "row": "flex flex-row items-center gap-1 sm:text-sm font-semibold text-base-dark",
    "sectionHeading": "sm:text-sm font-semibold text-base-dark mb-1"
  },
  "link": {
    "default": "focus-visible:outline-none focus-visible:underline link-default",
    "emphasized": "focus-visible:outline-none focus-visible:underline link-default font-semibold",
    "title": "font-semibold focus-visible:outline-none focus-visible:underline link-title"},
  "siteSettings": {
    "migration": {
      "releaseSummary": "cursor-pointer font-semibold",
      "migrationList": "mt-1 space-y-2 pl-3",
      "completion": "text-xs text-base-medium",
      "attemptList": "mt-1 space-y-1 text-xs text-base-medium"
    }
  },
  "loading": {
    "wrapper": "mt-4 space-y-3"},
  "message": "w-full sm:text-sm italic rounded-md px-3 py-2 outline-kind-default bg-kind-bg",
  "modal": {
    "wrapper": "fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-50 transition-opacity duration-100",
    "content": "bg-white rounded-lg shadow-xl max-w-4xl mx-4 max-h-[90vh] overflow-y-auto relative",
    "header": "sticky top-0 bg-white border-b px-6 py-4 flex justify-between items-center"},
  "radio": {
    "default": "form-input order-first size-4 shrink-0 appearance-none rounded-full",
    "fieldset": {
      "grid": "grid grid-cols-[repeat(auto-fit,minmax(80px,1fr))] gap-x-4 gap-y-2 sm:text-sm",
      "row": "flex flex-row items-center gap-4 sm:text-sm font-semibold",
      "column": "flex flex-col gap-1 sm:text-sm font-semibold"
    },
    "label": "flex items-center gap-2 font-semibold sm:text-sm text-base-dark"
  },
  "section": "outline outline-base-light rounded-md px-4 pb-4 bg-white w-full",
  "select": {
    "wrapper": "grid grid-cols-1 h-10",
    "default": "form-input col-start-1 row-start-1 h-10 w-full appearance-none rounded-md py-1.25 pr-8 pl-3 sm:text-sm placeholder:text-base-medium",
    "icon": "select-icon pointer-events-none col-start-1 row-start-1 mr-2.5 self-center justify-self-end z-25 text-base-medium"},
  "signature": {
    "pad": "relative rounded-md w-full h-40 bg-white outline-base-light outline",
    "reset": "absolute top-2 left-2 px-2 py-1 text-base sm:text-sm border rounded shadow-sm text-base-dark border-base-light hover:bg-delete-default hover:text-white"
  },
  "table": {
    "thead": {
      "actionCell": "sticky right-0 z-20 w-px min-w-px max-w-px p-0 align-top overflow-visible",
      "actions": "absolute top-1/2 right-0 z-20 m-0 grid -translate-y-1/2 place-items-center",
      "actionButton": "grid size-7 place-items-center rounded-md bg-white text-kind-default outline-offset-0 transition-colors duration-100 hover:text-kind-dark hover:outline-2 hover:outline-kind-default focus-visible:text-kind-dark focus-visible:outline-2 focus-visible:outline-kind-default",
      "actionIcon": "embedded-table-action-icon"
    }},
  "task": {
    "home": {
      "complete": "float-left mt-0.5 mr-2 grid size-5 place-items-center",
      "group": "text-sm font-semibold italic px-3 py-2 due-date",
      "item": "flex flex-col my-2 pt-1",
      "header": "flex flex-col px-3 text-sm font-semibold",
      "details": "grid grid-cols-[minmax(0,1fr)_auto] items-start w-full",
      "title": "min-w-0 font-semibold text-base leading-relaxed",
      "snooze": "home-task-snooze grid size-8 place-items-center rounded-sm text-xl text-kind-default",
      "notification": "text-sm italic border rounded-md w-fit px-3 py-2 mx-3 mt-3 empty:hidden text-delete-default border-delete-default"
    }
  },
  "textarea": "form-input block w-full rounded-md px-3 py-2 text-base font-normal placeholder:text-base-medium sm:text-sm",
  "toggle": {
    "container": "group/toggle action-icon-button transition-colors duration-100 group-data-[visible=true]/form:shadow-sm group-data-[visible=true]/form:bg-white hover:bg-white shrink-0",
    "icon": {
      "active": "invisible group-data-[active=false]/toggle:group-hover/toggle:visible group-data-[active=true]/toggle:group-[:not(:hover)]/toggle:visible",
      "inactive": "invisible group-data-[active=true]/toggle:group-hover/toggle:visible group-data-[active=false]/toggle:group-[:not(:hover)]/toggle:visible"}
  },
  "upload": {
    "options": "outline rounded-md px-4 pb-4 flex flex-col gap-4 bg-white outline-base-light",
    "processing": "pt-4 border-t flex flex-col gap-2 bg-white",
    "context": "pt-4 border-t flex flex-col gap-2 outline-base-light bg-white",
    "contextRow": "flex flex-col sm:flex-row gap-3",
    "header": "text-lg font-bold pt-2 pb-1 text-kind-default",
    "dropzone": "relative flex h-24 w-full flex-col content-center justify-center rounded-md border-2 border-dashed border-base-light bg-white p-3 text-center text-sm text-base-medium italic"}
};

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_frontend_icon_helpers_render_structured_material_symbols
 * @features frontend-icons
 * @dimensions registry lookup nested-ids
 */
const iconDefinition = (name) => {
	let definition = ICONS;
	for (const part of String(name || "").split(".")) {
		if (!part || !definition || typeof definition !== "object") return null;
		definition = definition[part];
	}
	return definition?.glyph ? definition : null;
};

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_frontend_icon_helpers_render_structured_material_symbols
 * @features frontend-icons
 * @dimensions semantic-markup fill weight animation accessibility
 */
const setIcon = (element, name, classes = "") => {
	const definition = iconDefinition(name);
	if (!definition) {
		element.replaceChildren();
		element.removeAttribute("data-icon");
		return element;
	}

	const classNames = ["icon"];
	if (definition.spin) classNames.push("icon-spin");
	if (classes) classNames.push(...String(classes).split(/\s+/).filter(Boolean));

	element.className = classNames.join(" ");
	element.dataset.icon = name;
	element.dataset.fill = String(definition.fill);
	element.setAttribute("aria-hidden", "true");
	if (definition.weight) {
		element.dataset.weight = String(definition.weight);
	} else {
		delete element.dataset.weight;
	}
	const glyph = document.createElement("span");
	glyph.className = "icon-glyph";
	glyph.textContent = definition.glyph;
	element.replaceChildren(glyph);
	return element;
};

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_frontend_icon_helpers_render_structured_material_symbols
 * @features frontend-icons
 * @dimensions semantic-markup element-creation
 */
const createIcon = (name, classes = "") => {
	return setIcon(document.createElement("span"), name, classes);
};

/**
 * @testable false
 * @covered-by src/script/shared/deferredOperations.mjs::DeferredOperationManager
 * @reason coordinator-owned bounded elapsed-time presentation
 */
function elapsedLabel(seconds) {
	seconds = Math.max(Number(seconds) || 0, 0);
	if (seconds < 10) return "just now";
	if (seconds < 60) return `${Math.floor(seconds)} seconds`;
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes} min`;
	const hours = Math.floor(minutes / 60);
	return `${hours} hr ${minutes % 60} min`;
}

/**
 * @testable false
 * @covered-by src/script/shared/deferredOperations.mjs::DeferredOperationManager
 * @reason coordinator-owned DOM lookup for operation decorations
 */
function operationNodes(key) {
	return Array.from(document.querySelectorAll("[data-operation]")).filter(
		(node) => node.dataset.operation === key,
	);
}

/**
 * Reconcile every visible deferred operation through the shared poll contract.
 *
 * @testable true
 * @tests tests_js/test_023_deferred_operations.py::test_deferred_operation_manager_batches_orders_and_renders_status
 * @features deferred-jobs
 * @dimensions status revision polling progress timing backoff teardown decoration-opt-out
 */
class DeferredOperationManager {
	constructor(view) {
		this.view = view;
		this.operations = new Map();
		this.destroyed = false;
		this.ignored = new Set();
		this.unsubscribers = new Map();
	}

	init() {
		this.scan();
		return this;
	}

	scan(root = document) {
		const nodes = Array.from(root.querySelectorAll?.("[data-operation]") || []);
		if (root.matches?.("[data-operation]")) nodes.unshift(root);
		for (const node of nodes) {
			this.track(node.dataset.operation, {
				revision: Number(node.dataset.operationRevision) || 0,
				node,
			});
		}
	}

	track(key, { revision = 0, node = null } = {}) {
		if (this.destroyed || !key || this.ignored.has(key)) return false;
		const decorationNode =
			node?.dataset?.deferredStatus === "false" ? null : node;
		const previous = decorationNode?.dataset?.operation;
		if (previous && previous !== key) {
			this.operations.delete(previous);
			this.unsubscribers.get(previous)?.();
			this.unsubscribers.delete(previous);
			this._ignore(previous);
		}
		if (decorationNode) this.decorate(decorationNode, key);
		const current = this.operations.get(key);
		this.operations.set(key, {
			...current,
			revision: Math.max(Number(current?.revision) || 0, Number(revision) || 0),
		});
		if (!this.unsubscribers.has(key)) {
			const unsubscribe = this.view.PollingCoordinator?.subscribe(
				{
					id: `operation:${key}`,
					type: "operation",
					key,
					revision: null,
					operation_revision: null,
				},
				{
					onResult: async (result) => {
						if (result.status === "changed" && result.payload) {
							return await this.receive(result.payload);
						} else if (
							result.status === "error" ||
							result.status === "unavailable"
						) {
							this._renderStatusDelay([key]);
						} else {
							this._refreshCachedStatuses([key]);
						}
					},
				},
			);
			if (unsubscribe) this.unsubscribers.set(key, unsubscribe);
		}
		return true;
	}

	decorate(node, key) {
		if (!node || !key) return;
		node.dataset.operation = key;
		const formLocked = node.dataset.deferredLock === "form";
		if (formLocked) {
			node.setAttribute("aria-busy", "true");
			for (const control of node.querySelectorAll(
				"input, textarea, select, button",
			)) {
				control.disabled = true;
			}
		}
		if (node.querySelector("[data-role='deferred-phase']")) return;
		const autofill = node.querySelector("[data-role='autofill']");
		const submitGroup = node.querySelector("[data-role='submit-group']");
		const autofillSubmitGroup = node.querySelector(
			"[data-role='autofill-submit-group']",
		);
		const autofillTarget = (autofill && submitGroup) || autofillSubmitGroup;
		const progress = document.createElement("p");
		progress.dataset.role = "deferred-progress";
		progress.dataset.operation = key;
		progress.className = autofillTarget
			? "flex min-h-10 items-center justify-center gap-2 rounded-md bg-kind-default px-4 py-2 text-sm font-semibold text-white shadow-sm"
			: "mt-2 text-sm text-base-medium";
		progress.setAttribute("aria-live", "polite");
		const icon = createIcon("spinner");
		icon.setAttribute("aria-hidden", "true");
		const phase = document.createElement("span");
		phase.dataset.role = "deferred-phase";
		phase.textContent = autofillTarget ? "Autofill queued" : "Waiting to start";
		const separator = document.createElement("span");
		separator.setAttribute("aria-hidden", "true");
		separator.textContent = " · ";
		const elapsed = document.createElement("span");
		elapsed.dataset.role = "deferred-elapsed";
		elapsed.textContent = "just now";
		if (autofillTarget) {
			progress.append(icon, phase, separator, elapsed);
			autofillTarget.replaceWith(progress);
			if (autofill && autofill !== autofillTarget) autofill.remove();
		} else {
			progress.append(phase, separator, elapsed);
			node.append(progress);
		}
	}

	nudge(key, revision = null) {
		const current = key ? this.operations.get(key) : null;
		if (
			current &&
			revision !== null &&
			revision !== undefined &&
			Number(revision) < (Number(current.revision) || 0)
		)
			return false;
		if (key && !this.track(key, { revision })) return false;
		this.view.PollingCoordinator?.trigger(key ? `operation:${key}` : null);
		return true;
	}

	async poll() {
		return this.view.PollingCoordinator?.trigger(
			Array.from(this.operations.keys(), (key) => `operation:${key}`),
		);
	}

	async receive(status) {
		if (this.destroyed || !status?.key || !this.operations.has(status.key))
			return false;
		const current = this.operations.get(status.key);
		const revision = Number(status.revision) || 0;
		const previousRevision = Number(current?.revision) || 0;
		if (revision < previousRevision) return false;
		this.operations.set(status.key, {
			revision,
			status: { ...status },
			receivedAt: Date.now(),
		});
		this._render(status);

		window.dispatchEvent(
			new CustomEvent("deferred-operation", { detail: { ...status } }),
		);
		if (status.terminal) {
			let reconciled = true;
			try {
				this.view.EditWatcher?.expectDeferredCompletion?.(
					status.entity_key,
					status.key,
				);
				await this.view.reconcileChange?.({
					type: "deferred-complete",
					key: status.entity_key,
					source_widget: status.source_widget,
					destination: status.destination,
					deferred_revision: `${status.key}:${revision}`,
				});
			} catch {
				reconciled = false;
			}
			if (reconciled) {
				this.operations.delete(status.key);
				this.unsubscribers.get(status.key)?.();
				this.unsubscribers.delete(status.key);
				this._ignore(status.key);
			} else {
				this._renderStatusDelay([status.key]);
			}
			return reconciled;
		}
		return true;
	}

	_render(status, elapsedSeconds = status.elapsed_seconds) {
		for (const node of operationNodes(status.key)) {
			node.dataset.operationRevision = String(Number(status.revision) || 0);
			node.dataset.operationStatus = status.status || "unknown";
			node.dataset.operationPhase = status.phase || "unknown";
			node.dataset.operationTerminal = status.terminal ? "true" : "false";
			const phase = node.querySelector("[data-role='deferred-phase']");
			if (phase) {
				phase.textContent = status.error
					? `${status.phase_label}: ${status.error}`
					: status.recovering
						? `${status.phase_label}. Automatic recovery is active.`
						: status.phase_label;
			}
			const elapsed = node.querySelector("[data-role='deferred-elapsed']");
			if (elapsed) elapsed.textContent = elapsedLabel(elapsedSeconds);
		}
	}

	_refreshCachedStatuses(keys = Array.from(this.operations.keys())) {
		for (const key of keys) {
			const operation = this.operations.get(key);
			if (!operation?.status) continue;
			const elapsed =
				(Number(operation.status.elapsed_seconds) || 0) +
				Math.max(Math.floor((Date.now() - operation.receivedAt) / 1000), 0);
			this._render(operation.status, elapsed);
		}
	}

	_renderStatusDelay(keys = Array.from(this.operations.keys())) {
		for (const key of keys) {
			for (const node of operationNodes(key)) {
				const phase = node.querySelector("[data-role='deferred-phase']");
				if (phase) phase.textContent = "Status check delayed. Retrying.";
			}
		}
	}

	_ignore(key) {
		if (!key) return;
		this.ignored.add(key);
		if (this.ignored.size > 100) {
			this.ignored.delete(this.ignored.values().next().value);
		}
	}

	destroy() {
		this.destroyed = true;
		for (const unsubscribe of this.unsubscribers.values()) unsubscribe();
		this.unsubscribers.clear();
		this.operations.clear();
		this.ignored.clear();
	}
}

const ENDPOINTS = {
	CollaborativeDocument: (settings) => {
		return {
			sendUpdates: `/assets/${settings.key}/document/update`,
			saveDocument: `/assets/${settings.key}/document/save`,
			addImage: `/assets/${settings.key}/document/image`,
			generateText: `/assets/${settings.key}/document/generate`,
			removeUser: `/assets/${settings.key}/document/remove-user`,
			getContent: `/assets/${settings.key}/document/state`,
			history: `/assets/${settings.key}/document/history`,
		};
	},
	Filters: (settings) => {
		return {
			condition: `/filters/${settings.key}/condition`,
			options: `/filters/${settings.key}/options`,
			save: `/filters/${settings.key}/save`,
			test: `/filters/${settings.key}/test`,
			get: `/filters/${settings.key}/get`,
		};
	},
	FileInfo: (settings) => {
		return {
			html: `/files/${settings.key}/html`,
		};
	},
	PagePhoto: (settings) => {
		return {
			upload: `/assets/${settings.key}/add-page-image`,
			generate: `/assets/${settings.key}/generate-page-image`,
			remove: `/assets/${settings.key}/remove-page-image`,
		};
	},
	PageInfo: (settings) => {
		return {
			attribute: (attribute) =>
				`/pages/${settings.key}/attributes/${attribute}`,
			disablePhoto: `/pages/${settings.key}/attributes/photo`,
		};
	},
	ProjectInfo: (settings) => {
		return {
			attribute: (attribute) =>
				`/projects/${settings.key}/attributes/${attribute}`,
		};
	},
	SiteSettings: () => {
		return {
			siteSettings: "/site-settings",
			setAiSettings: "/set-ai-settings",
			setDeploymentSettings: "/set-deployment-settings",
			setSiteImage: "/set-site-image",
			siteConfiguration: "/site-configuration",
			siteUpdate: "/site-update",
			rebuildCache: "/rebuild-cache",
		};
	},
	SiteExport: () => {
		return {
			start: "/site-export",
		};
	},
	HomeTaskList: () => {
		return {
			completeTask: (key) => {
				return `/tasks/${key}/complete`;
			},
			changeDueDate: (key) => {
				return `/tasks/${key}/change-due-date`;
			},
		};
	},
	TaskForm: (settings) => {
		return {
			latestHistorySubmission: `/tasks/${settings.key}/history/latest-submission`,
			saveDefaultField: `/tasks/${settings.key}/default-submission`,
		};
	},
	TaskUpload: (settings) => {
		return {
			upload: `/tasks/${settings.key}/upload-file`,
			remove: (fileKey) => `/tasks/${settings.key}/files/${fileKey}`,
		};
	},
	ImportData: () => {
		return {
			get: (key) => `/files/ingress?key=${key}`,
			setStage: (key) => `/files/ingress/${key}/stage`,
			update: (key) => `/files/ingress/${key}/update`,
			next: (key) => `/files/ingress/${key}/next`,
			import: (key) => `/files/ingress/${key}/import`,
			stop: (key) => `/files/ingress/${key}/stop`,
			deleteImported: (key) => `/files/ingress/${key}/delete-imported`,
			getPageForm: (key) => `/files/ingress/${key}/get-page-form`,
		};
	},
	search: {
		bar: "/search-bar",
		page: "/search-page",
	},
	linkPreview: "/preview",
	location: "/search-location",
	facet: (index) => {
		return `/search-index/${index}`;
	},
	html: (key, field) => {
		return {
			save: `/assets/${key}/form-html/${field}`,
			addImage: `/assets/${key}/document/image?field=${field}`,
			generateText: `/assets/${key}/document/generate?field=${field}`,
			getContent: `/assets/${key}/html/${field}`,
		};
	},
	renderer: {
		validateRow: (key, table_id) => `/forms/${key}/validate-row/${table_id}`,
		expandTableCell: (key, table_id) =>
			`/forms/${key}/expand-table-cell/${table_id}`,
		getSchema: (key) => `/forms/${key}/schema`,
	},
	manual: {
		section: (key) => {
			return `/manual/section/${key}`;
		},
	},
	collaboration: {
		start: `/collaboration/start`,
		stop: `/collaboration/stop`,
	},
	delete: (key) => `/delete/${key}`,
	toggleStar: (key) => {
		return `/toggle-star/${key}`;
	},
	activity: (key) => `/activity/${key}`,
	poll: "/poll",
	notifications: "/notifications",
	help: (key) => {
		return `/reference/section/${key}`;
	},
	createSchema: "/forms/create-schema",
	restrictions: (key) => `/forms/${key}/restrictions`,
	PagePermissions: (settings) => {
		return {
			viewAccess: `/pages/${settings.key}/view-access`,
			restrictAccess: `/pages/${settings.key}/restrictions`,
		};
	},
	UserSettings: (settings) => {
		return ENDPOINTS.PagePermissions(settings);
	},
	sync: "/sync",
};

/**
 * Widget Contract:
 * - target: Element - DOM element for this widget
 * - enable(): Set this.active = true,
 * - disable(): Set this.active = false, cleanup
 * - reconcile(): Sync this.visible → target.dataset.visible (in transition)
 * - updated(response): Handle server response
 * - created(response): Post-create handling (reset forms)
 * - data: FormData getter for submissions
 * - destroy(): Cleanup listeners
 */


const WIDGETS = {
	BaseList: () => import('./baseList.js?v=bda9a134'),
	CategoryInfo: () => import('./category.js?v=bda9a134'),
	CollaborativeDocument: () => import('./collaborative.js?v=bda9a134'),
	CreateCategory: () => import('./category.js?v=bda9a134'),
	CreateForm: () => import('./form.js?v=bda9a134'),
	CreateModelTask: () => import('./modelTasks.js?v=bda9a134'),
	CreateNote: () => import('./note.js?v=bda9a134'),
	CreatePage: () => import('./pageInfo.js?v=bda9a134'),
	CreateProject: () => import('./projectInfo.js?v=bda9a134'),
	CreateToolReport: () => import('./tools.js?v=bda9a134'),
	CreateUserTask: () => import('./taskSettings.js?v=bda9a134'),
	CreateTask: () => import('./taskSettings.js?v=bda9a134'),
	CreateUser: () => import('./user.js?v=bda9a134'),
	CreateUserGroup: () => import('./user.js?v=bda9a134'),
	DirectoryList: () => import('./lists.js?v=bda9a134'),
	DocumentSettings: () => import('./documentSettings.js?v=bda9a134'),
	FileInfo: () => import('./fileInfo.js?v=bda9a134'),
	PDFPreview: () => import('./filePdfPreview.js?v=bda9a134'),
	FileUpload: () => import('./uploadFile.js?v=bda9a134'),
	Filters: () => import('./filters.js?v=bda9a134'),
	FilterResults: () => import('./tables.js?v=bda9a134'),
	GeneratePages: () => import('./category.js?v=bda9a134'),
	GroupPermissions: () => import('./user.js?v=bda9a134'),
	HomeActivityList: () => import('./activity.js?v=bda9a134'),
	HomePageList: () => import('./lists.js?v=bda9a134'),
	HomeTaskList: () => import('./tasks.js?v=bda9a134'),
	HomeProjectList: () => import('./lists.js?v=bda9a134'),
	HomeCategoryList: () => import('./lists.js?v=bda9a134'),
	ImportData: () => import('./ingress.js?v=bda9a134'),
	IndexTable: () => import('./tables.js?v=bda9a134'),
	IngressFileUpload: () => import('./ingressUpload.js?v=bda9a134'),
	IngressList: () => import('./lists.js?v=bda9a134'),
	MobileTableControls: () => import('./mobileTableControls.js?v=bda9a134'),
	ModelTaskInfo: () => import('./modelTasks.js?v=bda9a134'),
	ModelTaskList: () => import('./modelTasks.js?v=bda9a134'),
	PageInfo: () => import('./pageInfo.js?v=bda9a134'),
	PagePermissions: () => import('./pagePermissions.js?v=bda9a134'),
	PagePhoto: () => import('./pagePhoto.js?v=bda9a134'),
	PageTaskList: () => import('./pageTaskList.js?v=bda9a134'),
	ProjectInfo: () => import('./projectInfo.js?v=bda9a134'),
	PublicPermissions: () => import('./user.js?v=bda9a134'),
	SavedFilters: () => import('./filters.js?v=bda9a134'),
	SiteExport: () => import('./siteExport.js?v=bda9a134'),
	SiteSettings: () => import('./siteSettings.js?v=bda9a134'),
	StarredList: () => import('./lists.js?v=bda9a134'),
	TableEditor: () => import('./tableEditor.js?v=bda9a134'),
	TableSorting: () => import('./tableSorting.js?v=bda9a134'),
	TableVisibility: () => import('./tableVisibility.js?v=bda9a134'),
	TaskForm: () => import('./taskForm.js?v=bda9a134'),
	TaskHistory: () => import('./tables.js?v=bda9a134'),
	TaskCombine: () => import('./taskSettings.js?v=bda9a134'),
	TaskMove: () => import('./taskSettings.js?v=bda9a134'),
	ToolReportList: () => import('./lists.js?v=bda9a134'),
	TaskSettings: () => import('./taskSettings.js?v=bda9a134'),
	UserSettings: () => import('./pageInfo.js?v=bda9a134'),
};

/** Sync-capable widgets that can run without a mounted view (offline replay). */
const HEADLESS_WIDGETS = {
	document: {
		load: () => import('./collaborative.js?v=bda9a134'),
		name: "CollaborativeDocument",
	},
};

const JSON_ATTRIBUTES = [
	"attributes",
	"submission",
	"schema",
	"conditions",
	"columns",
	"selected",
	"preload",
	"options",
];

/**
 * @testable infrastructure
 */
const _attributes = (component, show) => {
	const settings = {
		component: component,
		view: component.view,
		name: show,
		visible: false,
		modified: false,
	};

	// Components that cam be toggled visibly should have a target element
	// either in the html or as a getter in the widget
	const target = component.elt.querySelector(`[data-widget="${show}"]`);
	if (target) {
		settings.target = target;
		settings.key = target.dataset.key || component.key || settings.view.key;
		settings.kind = target.dataset.kind || component.kind || "default";
		settings.persistent = target.dataset.persistent === "true";
		settings.visible = target.dataset.visible === "true";
	}

	settings.route = target?.dataset.route || component.elt.dataset.route;

	JSON_ATTRIBUTES.filter((attribute) => target?.dataset[attribute]).forEach(
		(attribute) => {
			settings[attribute] = JSON.parse(target.dataset[attribute]);
		},
	);

	if (show in ENDPOINTS) {
		settings.endpoints = ENDPOINTS[show](settings);
	}

	return settings;
};

/**
 * @testable false
 * @covered-by src/script/widgets/loader.mjs::loadWidget
 * @reason widget readonly is part of the widget construction contract
 */
const _defineReadonly = (widget, component) => {
	Object.defineProperty(widget, "readonly", {
		configurable: true,
		enumerable: true,
		get() {
			return component.readonly || widget.target?.dataset.readonly === "true";
		},
	});
};

/**
 * @testable infrastructure
 */
class DefaultWidget {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.DEFAULT = true;
	}
}

/**
 * @testable infrastructure
 */
async function loadWidget(component, show, extraAttributes = {}) {
	let widget;
	const attributes = { ..._attributes(component, show), ...extraAttributes };
	const name = show.split("/")[0];

	if (name in WIDGETS) {
		const module = await WIDGETS[name]();
		widget = new module[name](attributes);
	} else {
		widget = new DefaultWidget(attributes);
	}

	_defineReadonly(widget, component);

	if (widget.init) await widget.init();

	widget.enable = () => {
		widget.modified = widget.modified || widget.visible !== true;
		widget.visible = true;
	};

	widget.disable = (force = false) => {
		widget.modified = force || widget.visible !== false;
		widget.visible = false;
	};

	// All DOM manipulation should be done here, this is wrapped in a transition
	// it is called for each changed widget in the component's render() method
	widget.reconcile = async (silent = false) => {
		if (widget.target && !widget.persistent) {
			widget.target.dataset.visible = widget.visible ? "true" : "false";
		}

		if (!widget.modified) return;
		widget.modified = false;

		if (widget.postreconcile && !silent) await widget.postreconcile();
	};

	if (widget.target) widget.target._lp_widget = widget;
	return widget;
}

/**
 * Build a fully rendered, detached copy of a form widget for revision
 * comparison. The response document is cloned so the original remains
 * available if the user chooses to apply it.
 *
 * @testable infrastructure
 */
async function loadRevisionPreview(
	liveWidget,
	response,
	{ readonly = liveWidget.readonly } = {},
) {
	const responseTarget = response.html?.querySelector(
		`[data-widget='${liveWidget.name}']`,
	);
	if (!responseTarget) return null;

	const container = document.createElement("div");
	container.appendChild(responseTarget.cloneNode(true));
	const view = {
		key: liveWidget.key,
		kind: liveWidget.kind,
		readonly,
		online: true,
		hidden: false,
		showExtractReloadNotice() {},
	};
	const component = {
		elt: container,
		view,
		key: liveWidget.key,
		kind: liveWidget.kind,
		widgets: {},
		get readonly() {
			return readonly;
		},
	};
	const preview = await loadWidget(component, liveWidget.name, {
		revisionPreview: true,
		schema: response.schema ?? null,
		submission: response.submission ?? null,
	});
	const previewResponse = {
		...response,
		html: response.html?.cloneNode(true),
	};

	if (preview.updated) await preview.updated(previewResponse);
	if (preview.postreconcile) await preview.postreconcile();
	return preview;
}

/**
 * @testable false
 * @covered-by src/script/widgets/loader.mjs::loadHeadlessWidget
 * @reason helper owned by the headless sync widget loader
 */
function _headlessKind(sync_id) {
	if (sync_id.endsWith(":document")) return "document";
	return null;
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
 * @features sync
 * @dimensions headless-widget document offline-replay concurrency
 *
 * Construct a sync-capable widget with no view or DOM chrome.
 * Caller runs init(), assigns remote/offlineRecord, then sync().
 */
async function loadHeadlessWidget({ sync_id, remote, offline }) {
	const kind = _headlessKind(sync_id);
	if (!kind) return null;

	const { load, name } = HEADLESS_WIDGETS[kind];
	const module = await load();
	const Widget = module[name];

	const target = document.createElement("div");
	target.setAttribute("lp-sync", sync_id);
	const fingerprint = remote?.fingerprint ?? offline?.fingerprint;
	if (fingerprint) target.setAttribute("lp-fingerprint", fingerprint);
	return new Widget({
		target,
		headless: true,
		view: null,
		readonly: true,
		key: remote?.key ?? offline?.key,
	});
}

/**
 * @testable false
 * @reason browser hash helper is exercised through builder condition IDs, not directly
 */
const simpleHash = (str) => {
	let hash = 0;
	for (let i = 0; i < str.length; i++) {
		const char = str.charCodeAt(i);
		hash = (hash << 5) - hash + char;
	}
	return (hash >>> 0).toString(36).padStart(7, "0");
};

/**
 * @testable false
 * @reason browser element ID helper is exercised through renderer/combobox wiring
 */
const generateElementId = (type) => {
	return `${type}-${crypto.randomUUID().split("-")[0]}`;
};

/**
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::withTransition
 * @reason no-transition fallback is part of the transition wrapper
 */
const runWithoutTransition = async (callback) => {
	try {
		await callback();
		return true;
	} catch (error) {
		captureError(error);
		return false;
	}
};

/**
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::withTransition
 * @reason transition queue prevents concurrent View Transitions API aborts
 */
let transitionQueue = Promise.resolve();
let transitionDepth = 0;

/**
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::withTransition
 * @reason single-transition runner is private to the queued wrapper
 */
const executeTransition = async (callback) => {
	if (!document.startViewTransition) {
		return runWithoutTransition(callback);
	}

	try {
		const transition = document.startViewTransition(async () => {
			transitionDepth += 1;
			try {
				await callback();
			} finally {
				transitionDepth -= 1;
			}
		});
		transition.ready.catch(() => {});
		try {
			await transition.finished;
			return true;
		} catch (error) {
			if (isSkippedViewTransitionError(error)) {
				return runWithoutTransition(callback);
			}

			captureError(error);
			return false;
		}
	} catch (error) {
		if (isSkippedViewTransitionError(error)) {
			return runWithoutTransition(callback);
		}

		captureError(error);
		return false;
	}
};

/**
 * @testable true
 * @tests tests_js/test_011_view_transitions_frontend.py::test_nested_transition_joins_active_transition_without_error_report
 * @features view-transition
 * @dimensions nested-callback error-reporting
 */
const withTransition = (callback) => {
	if (transitionDepth > 0) {
		// Nested callers are already inside the browser's transition update.
		return runWithoutTransition(callback);
	}

	const result = transitionQueue.then(() => executeTransition(callback));
	transitionQueue = result.catch(() => {});
	return result;
};

/**
 * @testable false
 * @covered-by src/script/views/base/component.mjs::ViewComponent
 * @covered-by src/script/elements/base/baseForm.mjs::BaseForm
 * @reason transient UI feedback helper exercised through form/component flows
 */
const showBriefly = (element, content) => {
	element.replaceChildren(content);
	element.dataset.visible = "true";
	element.classList.add("fade-out");
	element.addEventListener(
		"animationend",
		() => {
			element.classList.remove("fade-out");
			element.dataset.visible = "false";
			element.replaceChildren();
		},
		{ once: true },
	);
};

/**
 * @testable infrastructure
 */
const debounce = (func, wait) => {
	let timeout;
	return function (...args) {
		clearTimeout(timeout);
		timeout = setTimeout(() => func.apply(this, args), wait);
	};
};

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_wait_for_attribute_resolves_and_cleans_up_observers
 * @pairs frontend-utilities:mutation-observer frontend-utilities:cleanup
 */
function waitForAttribute(element, attributeName, timeout = 10000) {
	if (element.hasAttribute(attributeName)) {
		return Promise.resolve(element.getAttribute(attributeName));
	}

	return new Promise((resolve, reject) => {
		let observer = null;
		let timeoutId = null;

		/**
		 * @testable false
		 * @covered-by src/script/shared/utilities.mjs::waitForAttribute
		 * @reason observer cleanup is private waitForAttribute lifecycle plumbing
		 */
		const cleanup = () => {
			observer?.disconnect();
			clearTimeout(timeoutId);
		};

		timeoutId = setTimeout(() => {
			cleanup();
			reject(new Error(`Timeout waiting for attribute '${attributeName}'`));
		}, timeout);

		observer = new MutationObserver(() => {
			if (element.hasAttribute(attributeName)) {
				cleanup();
				resolve(element.getAttribute(attributeName));
			}
		});

		observer.observe(element, {
			attributes: true,
			attributeFilter: [attributeName],
		});
	});
}

/**
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::areEqual
 * @reason object sorting is private deep-comparison normalization
 */
function _sortObject(obj) {
	if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
		return obj;
	}
	return Object.keys(obj)
		.sort()
		.reduce((result, key) => {
			result[key] = _sortObject(obj[key]);
			return result;
		}, {});
}

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_are_equal_normalizes_object_keys_but_preserves_array_order
 * @pairs frontend-utilities:deep-equality frontend-utilities:array-order
 */
const areEqual = (a, b) => {
	return JSON.stringify(_sortObject(a)) === JSON.stringify(_sortObject(b));
};

/**
 * @testable false
 * @reason Yjs payload decoding is exercised through collaborative editor sync
 */
const base64ToUint8Array = (base64) => {
	const bin = atob(base64);
	const bytes = new Uint8Array(bin.length);
	for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
	return bytes;
};

/**
 * @testable false
 * @reason Yjs payload encoding is exercised through collaborative editor sync
 */
const uint8ArrayToBase64 = (bytes) => {
	let bin = "";
	for (let i = 0; i < bytes.byteLength; i++)
		bin += String.fromCharCode(bytes[i]);
	return btoa(bin);
};

/**
 * @testable false
 * @reason browser cache cleanup helper is exercised through service-worker and polling refresh flows
 */
const clearRecentSearchResults = () => {
	const recentKeys = Array.from({ length: localStorage.length }, (_, index) =>
		localStorage.key(index),
	).filter((key) => key?.startsWith("recent-"));

	recentKeys.forEach((key) => {
		localStorage.removeItem(key);
	});
};

/**
 * @testable infrastructure
 */
class Modal {
	constructor(view, trigger) {
		this.trigger = trigger;
		this.view = view;
		this.keydown = this._keydown.bind(this);
		this.click = this._click.bind(this);
		this.key = null;
	}

	_attachListeners() {
		document.addEventListener("keydown", this.keydown);
		document.addEventListener("click", this.click);
		this.modal._lp_modal = this;
	}

	destroy() {
		document.removeEventListener("keydown", this.keydown);
		document.removeEventListener("click", this.click);
		if (this.modal) this.modal.remove();
		if (this.trigger) this.trigger.disabled = false;
	}

	get modal() {
		return document.getElementById("modal");
	}

	_keydown(event) {
		const modal = this.modal;
		if (!modal) return;

		if (event.key === "Escape") {
			this.remove();
		} else if (event.key === "Enter" && event.target.tagName === "BUTTON") {
			event.target.click();
		} else if (event.key === "Tab") {
			const focusable = modal.querySelectorAll(
				'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
			);
			if (!focusable.length) return;

			const first = focusable[0];
			const last = focusable[focusable.length - 1];

			if (event.shiftKey) {
				if (
					document.activeElement === first ||
					!modal.contains(document.activeElement)
				) {
					event.preventDefault();
					last.focus();
				}
			} else {
				if (
					document.activeElement === last ||
					!modal.contains(document.activeElement)
				) {
					event.preventDefault();
					first.focus();
				}
			}
		}
	}

	_click(event) {
		const modal = this.modal;

		if (this.trigger?.contains(event.target)) return;

		const content = modal?.querySelector("#modal-content");
		if (content && !content.contains(event.target)) {
			this.remove();
		} else if (event.target.closest("[lp-control='close']")) {
			event.stopPropagation();
			this.remove();
		}
	}

	async remove() {
		await withTransition(async () => {
			this.destroy();
		});
	}

	async load(route) {
		if (this.trigger) this.trigger.disabled = true;
		try {
			const modal = await request.get(route);
			if (!modal.html) {
				captureError(new Error("No modal HTML provided"), this.trigger, {
					view: this.view?.dataset,
					route,
					modal,
				});
				if (this.trigger) this.trigger.disabled = false;
				return null;
			}
			this.attach(modal.html);
			if (this.trigger) this.trigger.disabled = false;
		} catch (error) {
			captureError(error, this.trigger, this.view?.dataset);
			if (this.trigger) this.trigger.disabled = false;
		}
	}

	attach(html, component) {
		try {
			if (this.trigger) this.trigger.disabled = true;
			const modal = html.querySelector("#modal") || html;
			document.body.appendChild(modal);
			this._attachListeners();
		} catch (error) {
			captureError(error, component, this.view?.dataset);
		}
	}
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_delete_category
 * @tests tests_e2e/002_home/test_002b_home_projects.py::test_delete_project
 * @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_delete_model_task
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_delete_page_from_title_menu
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_delete_page_task_from_page_row
 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_delete_task_from_row
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_delete_user_can_preserve_page
 * @pairs categories:delete projects:delete model-tasks:delete pages:delete
 * @pairs tasks:delete task-index:delete forms:delete users:delete users:options
 */
class DeleteModal extends Modal {
	async init() {
		const entity =
			this.trigger.closest("[lp-entity]") ||
			this.trigger
				.closest("[lp-component]")
				?._lp_component?.active?.target?.closest("[lp-entity]");
		this.key = entity?.dataset?.key || entity?.id;

		if (!this.key || !this.view) {
			captureError(
				new Error("No key or view provided"),
				this.trigger,
				this.view?.dataset,
			);
			return;
		}

		await this.load(ENDPOINTS.delete(this.key));

		const modal = this.modal;
		if (!modal) {
			if (this.trigger) this.trigger.disabled = false;
			return;
		}

		this.deleteButton = modal.querySelector("[data-role='delete']");
		if (!this.deleteButton) {
			if (this.trigger) this.trigger.disabled = false;
			captureError(
				new Error("Delete modal missing [data-role='delete']"),
				this.trigger,
				{ view: this.view?.dataset },
			);
			return;
		}
		this.deleteButton.addEventListener("click", this.delete.bind(this));
		this.deleteButton.focus();
	}

	removeEntity(key) {
		document.querySelectorAll(`[data-key='${key}']`).forEach((elt) => {
			elt.closest("[lp-component]");
			if (elt._lp_component) elt._lp_component.destroy();
			elt.remove();
		});
	}

	async delete() {
		try {
			this.deleteButton.disabled = true;
			this.deleteButton.querySelector("#spinner").dataset.visible = "true";
			const route = this.deleteButton.dataset.route;
			const options = Array.from(
				this.modal.querySelectorAll("[data-delete-option][name]"),
			);
			const data = options.length
				? Object.fromEntries(
						options.map((option) => [option.name, option.checked]),
					)
				: null;

			const response = await request.delete(route, data);
			if (!response.ok) {
				this.deleteButton.disabled = false;
				this.deleteButton.querySelector("#spinner").dataset.visible = "false";
				return;
			}

			await this.remove();
			const returnUrl = this.trigger?.dataset.returnUrl;
			if (returnUrl) {
				window.location.assign(returnUrl);
				return;
			}

			await this.view?.reconcileChange?.({ type: "delete", key: this.key });
		} catch (error) {
			this.deleteButton.disabled = false;
			this.deleteButton.querySelector("#spinner").dataset.visible = "false";
			captureError(error, this.deleteButton, this.view.dataset);
		}
	}
}

/**
 * @testable infrastructure
 */
class HelpModal extends Modal {
	async init() {
		const section =
			this.trigger.closest("[lp-component]")?._lp_component?.help ||
			this.trigger.getAttribute("lp-help") ||
			this.trigger.closest("nav[lp-help]").getAttribute("lp-help");

		if (!section) {
			captureError(
				new Error("No section provided"),
				this.trigger,
				this.view.dataset,
			);
			return;
		}

		await this.load(ENDPOINTS.help(section));
	}
}

/**
 * @testable infrastructure
 */
class OfflineModal extends Modal {
	attach() {
		const modal = document.createElement("div");
		modal.id = "modal";
		modal.className = STYLES.modal.wrapper;

		const content = modal.appendChild(document.createElement("div"));
		content.className = STYLES.modal.content;
		content.id = "modal-content";

		const header = content.appendChild(document.createElement("div"));
		header.className = STYLES.modal.header;
		const headerText = header.appendChild(document.createElement("h2"));
		headerText.textContent = "Offline";
		headerText.className = "text-lg font-bold text-base-dark";
		const close = header.appendChild(document.createElement("button"));
		close.textContent = "Close";
		close.className = `${STYLES.button.close}`;
		close.onclick = () => {
			modal.remove();
		};

		const body = content.appendChild(document.createElement("div"));
		body.className = "p-6 text-slate-600";
		const bodyText = body.appendChild(document.createElement("p"));
		bodyText.textContent =
			"You are offline (or the server is starting up). You will be able to view any pages that have been " +
			"cached, but search, documents and forms will be in read-only mode until you are online again.";

		super.attach(modal);
	}

	enable() {
		if (!this.trigger) return;
		this.trigger.addEventListener("click", this.attach.bind(this));
	}
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_offline_submission_conflict_keeps_queue_until_choice
 * @features forms
 * @dimensions readonly-preview submission-choice latest-schema queued-conflict
 */
class FormRevisionModal extends Modal {
	constructor(watcher, marker, widget, state) {
		super(watcher.view, marker.querySelector("[data-role='edited-reset']"));
		this.watcher = watcher;
		this.marker = marker;
		this.widget = widget;
		this.state = state;
		this.selections = new Map();
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editWatcher.mjs::FormRevisionModal
	 * @reason private schema-summary copy is part of the reconciliation modal
	 */
	_schemaSummary() {
		const before = new Map(
			(this.widget.schema ?? []).map((field) => [field?.id, field]),
		);
		const after = new Map(
			(this.state.response?.schema ?? []).map((field) => [field?.id, field]),
		);
		const added = [...after.keys()].filter((id) => id && !before.has(id));
		const removed = [...before.keys()].filter((id) => id && !after.has(id));
		const changed = [...after.keys()].filter(
			(id) => id && before.has(id) && !areEqual(before.get(id), after.get(id)),
		);
		const parts = [];
		if (added.length) parts.push(`${added.length} added`);
		if (removed.length) parts.push(`${removed.length} removed`);
		if (changed.length) parts.push(`${changed.length} changed`);
		return parts.length ? `Schema update: ${parts.join(", ")}.` : null;
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editWatcher.mjs::FormRevisionModal
	 * @reason private readonly value extraction is part of the reconciliation modal
	 */
	_value(element) {
		const rendered = element?.elt?.cloneNode(true);
		if (!rendered) {
			const empty = document.createElement("p");
			empty.className = "text-sm italic text-base-medium";
			empty.textContent = "Not provided";
			return empty;
		}

		const label = rendered.matches?.("[data-role='label']")
			? rendered
			: rendered.querySelector?.("[data-role='label']");
		label?.remove();
		rendered.removeAttribute?.("id");
		rendered.querySelectorAll?.("[id]").forEach((node) => {
			node.removeAttribute("id");
		});
		rendered.querySelectorAll?.("button").forEach((button) => {
			button.remove();
		});
		for (const node of [
			rendered,
			...rendered.querySelectorAll("[data-visible]"),
		]) {
			node.dataset.visible = "true";
		}
		return rendered;
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editWatcher.mjs::FormRevisionModal
	 * @reason private changed-field projection is part of the reconciliation modal
	 */
	async _differences(localResponse) {
		const [localPreview, savedPreview] = await Promise.all([
			loadRevisionPreview(this.widget, localResponse, { readonly: true }),
			loadRevisionPreview(this.widget, this.state.response, { readonly: true }),
		]);
		if (!localPreview || !savedPreview) {
			localPreview?.destroy?.();
			savedPreview?.destroy?.();
			throw new Error("Could not render form revision values");
		}

		try {
			const elements = (preview) =>
				new Map(
					Array.from(preview.form?.renderer?.elements?.values?.() ?? []).map(
						(element) => [element.schema?.id, element],
					),
				);
			const localElements = elements(localPreview);
			const savedElements = elements(savedPreview);
			const localSubmission = localResponse.submission ?? {};
			const savedSubmission = this.state.response.submission ?? {};

			return (this.state.response.schema ?? [])
				.filter(
					(field) =>
						field?.id &&
						!areEqual(
							localSubmission[field.id] ?? null,
							savedSubmission[field.id] ?? null,
						),
				)
				.map((field) => ({
					id: field.id,
					label: field.title || field.label || "Untitled field",
					local: this._value(localElements.get(field.id)),
					saved: this._value(savedElements.get(field.id)),
				}));
		} finally {
			localPreview.destroy?.();
			savedPreview.destroy?.();
		}
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editWatcher.mjs::FormRevisionModal
	 * @reason private per-field choice composition is part of the reconciliation modal
	 */
	_choice(field, source, value) {
		const button = document.createElement("button");
		button.type = "button";
		button.setAttribute("role", "radio");
		button.setAttribute("aria-checked", (source === "server").toString());
		button.setAttribute(
			"aria-label",
			`${source === "server" ? "Saved" : this.state.record ? "Queued" : "Current"} value for ${field.label}`,
		);
		button.dataset.revisionSource = source;
		button.className =
			"min-w-0 rounded-md border border-base-light/50 bg-white p-3 text-left transition-colors hover:bg-base-bg aria-checked:bg-kind-bg aria-checked:outline-2 aria-checked:outline-kind-default";

		const heading = button.appendChild(document.createElement("span"));
		heading.className = "mb-2 block text-xs font-semibold text-base-medium";
		heading.textContent =
			source === "server"
				? "Saved value"
				: this.state.record
					? "Queued value"
					: "Value in this tab";
		button.appendChild(value);

		button.addEventListener("click", () => {
			const group = button.closest("[role='radiogroup']");
			group?.querySelectorAll("[role='radio']").forEach((choice) => {
				choice.setAttribute("aria-checked", (choice === button).toString());
			});
			this.selections.set(field.id, source);
		});
		return button;
	}

	async init() {
		const local = this.widget.buildLocalRevision(this.state.response);
		const differences = await this._differences(local.response);
		if (!differences.length) return false;
		for (const field of differences) this.selections.set(field.id, "server");

		const modal = document.createElement("div");
		modal.id = "modal";
		modal.className = STYLES.modal.wrapper;
		modal.dataset.kind =
			this.widget.kind ||
			this.widget.component?.kind ||
			this.watcher.view.kind ||
			"default";
		const content = modal.appendChild(document.createElement("div"));
		content.id = "modal-content";
		content.className = `${STYLES.modal.content} w-full sm:max-w-3xl`;

		const header = content.appendChild(document.createElement("header"));
		header.className = STYLES.modal.header;
		const title = header.appendChild(document.createElement("h2"));
		title.className = "text-lg font-bold text-base-dark";
		title.textContent = "Choose form values";
		const close = header.appendChild(document.createElement("button"));
		close.type = "button";
		close.setAttribute("lp-control", "close");
		close.className = STYLES.button.close;
		close.textContent = "Close";

		const body = content.appendChild(document.createElement("div"));
		body.className = "space-y-4 p-4 sm:p-6";
		const intro = body.appendChild(document.createElement("p"));
		intro.className = "text-sm text-base-medium";
		intro.textContent =
			"Choose a value for each changed field. Saved values are selected by default.";
		const schemaSummary = this._schemaSummary();
		if (schemaSummary) {
			const schema = body.appendChild(document.createElement("p"));
			schema.className = STYLES.message;
			schema.textContent = schemaSummary;
		}

		const fields = body.appendChild(document.createElement("div"));
		fields.className = "space-y-4";
		for (const field of differences) {
			const row = fields.appendChild(document.createElement("section"));
			row.className = "rounded-md border border-base-light/50 bg-base-bg p-3";
			const label = row.appendChild(document.createElement("h3"));
			label.className = "mb-2 font-semibold text-base-dark";
			label.textContent = field.label;
			const choices = row.appendChild(document.createElement("div"));
			choices.setAttribute("role", "radiogroup");
			choices.setAttribute("aria-label", field.label);
			choices.className = "grid gap-2 sm:grid-cols-2";
			choices.append(
				this._choice(field, "local", field.local),
				this._choice(field, "server", field.saved),
			);
		}
		const actions = body.appendChild(document.createElement("div"));
		actions.className = "ml-auto flex w-fit";
		const update = actions.appendChild(document.createElement("button"));
		update.type = "button";
		update.className = STYLES.button.submit;
		update.textContent = "Update values";

		update.addEventListener("click", async () => {
			await this.watcher.resolveRevision(this.marker, {
				localResponse: local.response,
				selections: Object.fromEntries(this.selections),
			});
			await this.remove();
		});

		super.attach(modal, this.widget.component);
		update.focus();
		return true;
	}
}

/**
 * @testable false
 * @covered-by src/script/shared/editWatcher.mjs::EditWatcher
 * @reason private whole-form conflict UI is selected by capability-aware watcher state
 */
class WholeFormRevisionModal extends Modal {
	constructor(watcher, marker, widget) {
		super(watcher.view, marker.querySelector("[data-role='edited-reset']"));
		this.watcher = watcher;
		this.marker = marker;
		this.widget = widget;
	}

	async init() {
		const modal = document.createElement("div");
		modal.id = "modal";
		modal.className = STYLES.modal.wrapper;
		modal.dataset.kind =
			this.widget.kind ||
			this.widget.component?.kind ||
			this.watcher.view.kind ||
			"default";
		const content = modal.appendChild(document.createElement("div"));
		content.id = "modal-content";
		content.className = `${STYLES.modal.content} w-full sm:max-w-lg`;

		const header = content.appendChild(document.createElement("header"));
		header.className = STYLES.modal.header;
		const title = header.appendChild(document.createElement("h2"));
		title.className = "text-lg font-bold text-base-dark";
		title.textContent = "Choose form version";
		const close = header.appendChild(document.createElement("button"));
		close.type = "button";
		close.setAttribute("lp-control", "close");
		close.className = STYLES.button.close;
		close.textContent = "Close";

		const body = content.appendChild(document.createElement("div"));
		body.className = "space-y-4 p-4 sm:p-6";
		const copy = body.appendChild(document.createElement("p"));
		copy.className = "text-sm text-base-medium";
		copy.textContent =
			"This form cannot be compared field by field. Use the saved version or retry the complete queued version.";

		const actions = body.appendChild(document.createElement("div"));
		actions.className =
			"flex flex-col-reverse gap-2 sm:flex-row sm:justify-end";
		const retry = actions.appendChild(document.createElement("button"));
		retry.type = "button";
		retry.className = STYLES.button.cancel;
		retry.textContent = "Retry queued version";
		const saved = actions.appendChild(document.createElement("button"));
		saved.type = "button";
		saved.className = STYLES.button.submit;
		saved.textContent = "Use saved version";

		retry.addEventListener("click", async () => {
			await this.watcher.resolveRevision(this.marker, "local");
			await this.remove();
		});
		saved.addEventListener("click", async () => {
			await this.watcher.resolveRevision(this.marker, "server");
			await this.remove();
		});

		super.attach(modal, this.widget.component);
		saved.focus();
	}
}

/**
 * View-scoped detector for committed edits to forms represented by
 * lp-edited-marker descendants.
 *
 * @testable true
 * @tests tests_js/test_024_edit_watcher.py::test_edit_watcher_compares_and_resets_each_form_independently
 * @tests tests_js/test_024_edit_watcher.py::test_edit_watcher_coalesces_overlapping_revision_probes
 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_separates_schema_and_renderer_value_changes
 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_reconciles_independent_field_selections
 * @tests tests_js/test_028_form_state_split.py::test_owned_deferred_completion_replaces_clean_active_form
 * @tests tests_e2e/004_projects/test_004b_info.py::test_project_revision_notice_only_resets_changed_form
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @features edited-entity-notice
 * @dimensions entity-ancestor batching per-form comparison acknowledgement acknowledgement-no-probe targeted-reset reload-fallback timestamp-only formdata staged-reset no-reload dirty-state active-state focused-state replacement info-form side-effect-free overlap-follow-up coalescing renderer-capability latest-schema schema-only local-values submission-choice per-field-selection whole-form-selection clean-state transition owned-deferred-completion
 * @pairs edited-entity-notice:entity-ancestor edited-entity-notice:batching
 * @pairs edited-entity-notice:per-form edited-entity-notice:comparison
 * @pairs edited-entity-notice:acknowledgement edited-entity-notice:acknowledgement-no-probe
 * @pairs edited-entity-notice:targeted-reset edited-entity-notice:reload-fallback
 * @pairs edited-entity-notice:overlap-follow-up edited-entity-notice:clean-state
 * @pair edited-entity-notice:coalescing
 * @pair edited-entity-notice:dirty-state
 * @pairs edited-entity-notice:active-state
 * @pairs edited-entity-notice:owned-deferred-completion
 * @pair deferred-jobs:owned-deferred-completion
 * @pairs edited-entity-notice:focused-state edited-entity-notice:transition
 * @pairs edited-entity-notice:renderer-capability edited-entity-notice:latest-schema
 * @pairs edited-entity-notice:schema-only edited-entity-notice:local-values
 * @pairs edited-entity-notice:whole-form-selection
 * @pairs edited-entity-notice:visibility edited-entity-notice:subscription-lifecycle
 * @pairs edited-entity-notice:submission-choice reconnect-refresh:dirty-form-preservation form-schema:notice
 */
class EditWatcher {
	constructor(view) {
		this.view = view;
		this._unsubscribers = new Map();
		this._markerRevisions = new WeakMap();
		this._latestRevisions = new Map();
		this._deferredCompletions = new Map();
		this._destroyed = false;

		this._click = this._click.bind(this);
		this._entityUpdated = this._entityUpdated.bind(this);
		this.check = this.check.bind(this);
	}

	init() {
		this.view.elt.addEventListener("click", this._click);
		window.addEventListener("entity-updated", this._entityUpdated);
		if (this.view.key && this.view.elt.dataset.fingerprint) {
			this._latestRevisions.set(this.view.key, {
				fingerprint: this.view.elt.dataset.fingerprint,
				modified: this.view.elt.dataset.modified ?? null,
			});
		}
		for (const component of Object.values(this.view.components ?? {})) {
			for (const widget of Object.values(component.widgets ?? {})) {
				if (widget._offlineConflict) {
					this.stageConflict(widget, widget._offlineConflict);
				}
			}
		}
		this.resume();
	}

	get entities() {
		return this._entities();
	}

	_componentVisible(component) {
		if (component?.visible !== true) return false;
		let ancestor = component.elt?.parentElement?.closest?.("[lp-component]");
		while (ancestor) {
			if (ancestor.dataset.visible === "false") return false;
			ancestor = ancestor.parentElement?.closest?.("[lp-component]");
		}
		return true;
	}

	_markerActive(marker) {
		const widget = marker.closest?.("form[data-widget]")?._lp_widget;
		return Boolean(
			widget &&
				widget.component?.active === widget &&
				this._componentVisible(widget.component) &&
				widget.visible === true,
		);
	}

	_markerRevision(marker, anchor) {
		let revision = this._markerRevisions.get(marker);
		if (!revision) {
			revision = {
				fingerprint: anchor.dataset.fingerprint ?? null,
				modified: anchor.dataset.modified ?? null,
			};
			this._markerRevisions.set(marker, revision);
		}
		return revision;
	}

	_entities({ activeOnly = true } = {}) {
		const entities = new Map();
		const markers = this.view.elt.querySelectorAll("[lp-edited-marker]");

		for (const marker of markers) {
			const anchor = marker.closest("[lp-entity]");
			const key = anchor?.dataset.key;
			const revision = anchor ? this._markerRevision(marker, anchor) : null;
			const fingerprint = revision?.fingerprint;
			if (!anchor || !key || !fingerprint) {
				captureError(
					new Error("Edited marker has no fingerprinted entity anchor"),
					marker,
				);
				continue;
			}
			if (activeOnly && !this._markerActive(marker)) continue;

			const entity = entities.get(key) ?? {
				key,
				fingerprint,
				modified: revision.modified,
				anchors: new Set(),
				markers: new Set(),
			};
			entity.anchors.add(anchor);
			entity.markers.add(marker);
			entities.set(key, entity);
		}

		return entities;
	}

	_state(marker) {
		marker._lp_edited_state ??= {
			mode: "reset",
			response: null,
			fingerprint: null,
			modified: null,
			record: null,
			remoteSnapshot: null,
			schemaChanged: false,
			submissionChoice: false,
			token: null,
			probePromise: null,
			probeRevision: null,
			pendingProbe: null,
			conflictPromise: null,
		};
		return marker._lp_edited_state;
	}

	expectDeferredCompletion(key, operation) {
		if (!key || !operation) return false;
		const operations = this._deferredCompletions.get(key) ?? new Set();
		operations.add(operation);
		this._deferredCompletions.set(key, operations);
		return true;
	}

	_ownedDeferredCompletion(marker, widget) {
		const key = marker.closest?.("[lp-entity]")?.dataset?.key;
		const operation = widget?._deferredOperation;
		if (
			!key ||
			!operation ||
			!this._deferredCompletions.get(key)?.has(operation)
		) {
			return null;
		}
		return { key, operation };
	}

	_forgetDeferredCompletion(completion) {
		if (!completion) return;
		const operations = this._deferredCompletions.get(completion.key);
		operations?.delete(completion.operation);
		if (!operations?.size) this._deferredCompletions.delete(completion.key);
	}

	_setAction(marker, mode, message = null) {
		const state = this._state(marker);
		state.mode = mode;
		const button = marker.querySelector("[data-role='edited-reset']");
		if (button) {
			button.textContent =
				{
					reset: "Reset form",
					reload: "Reload page",
					review: "Review values",
					"whole-review": "Review versions",
					apply: "Continue",
					dismiss: "Dismiss",
				}[mode] ?? "Review update";
		}
		const copy = marker.querySelector("[data-role='edited-message']");
		if (copy && message) copy.textContent = message;
	}

	_hide(marker) {
		if (!marker) return;
		marker.dataset.visible = "false";
		const state = this._state(marker);
		state.response = null;
		state.fingerprint = null;
		state.modified = null;
		state.record = null;
		state.remoteSnapshot = null;
		state.schemaChanged = false;
		state.submissionChoice = false;
		this._setAction(marker, "reset");
	}

	_show(marker) {
		const wasVisible = marker.dataset.visible === "true";
		marker.dataset.visible = "true";
		if (!wasVisible) this.view.addFlash?.(marker);
	}

	_fallback(marker, error = null) {
		const state = this._state(marker);
		state.response = null;
		this._setAction(marker, "reload");
		this._show(marker);
		if (error) captureError(error, marker);
	}

	_rendererCapable(widget, response) {
		const objectSubmission = (submission) =>
			Boolean(submission) &&
			typeof submission === "object" &&
			!Array.isArray(submission);
		return Boolean(
			widget.form?.renderer &&
				Array.isArray(widget.schema) &&
				widget.schema.length &&
				objectSubmission(widget.submission) &&
				Array.isArray(response.schema) &&
				response.schema.length &&
				objectSubmission(response.submission),
		);
	}

	_rendererValuesDiffer(response, localResponse) {
		const saved = response.submission ?? {};
		const local = localResponse.submission ?? {};
		return (response.schema ?? []).some(
			(field) =>
				field?.id &&
				!areEqual(local[field.id] ?? null, saved[field.id] ?? null),
		);
	}

	_storeRevision(
		marker,
		response,
		{
			fingerprint,
			modified,
			record,
			remoteSnapshot,
			schemaChanged,
			submissionChoice,
		},
	) {
		const next = this._state(marker);
		next.response = response;
		next.fingerprint = fingerprint;
		next.modified = modified;
		next.record = record;
		next.remoteSnapshot = remoteSnapshot;
		next.schemaChanged = schemaChanged;
		next.submissionChoice = submissionChoice;
		return next;
	}

	async _stageRevision(
		marker,
		widget,
		response,
		{ fingerprint = null, modified = null, record = null } = {},
	) {
		const state = this._state(marker);
		record ??= state.record;
		const token = state.token;
		const anchor = marker.closest?.("[lp-entity]");
		const baselineFingerprint =
			record?.fingerprint ?? anchor?.dataset?.fingerprint ?? null;
		const baselineModified =
			record?.modified ?? anchor?.dataset?.modified ?? null;
		const fingerprintChanged = Boolean(
			fingerprint && baselineFingerprint && baselineFingerprint !== fingerprint,
		);
		const schemaOnlyRevision = Boolean(
			fingerprintChanged &&
				modified &&
				baselineModified &&
				baselineModified === modified,
		);
		const observedSchemaChanged = !areEqual(
			widget.schema ?? null,
			response.schema ?? null,
		);
		const schemaChanged = observedSchemaChanged || schemaOnlyRevision;

		const remotePreview = await loadRevisionPreview(widget, response);
		if (token && state.token !== token) {
			remotePreview?.destroy?.();
			return;
		}
		if (!remotePreview || !widget.revisionCanReset(remotePreview)) {
			remotePreview?.destroy?.();
			this._fallback(marker);
			return;
		}
		const remoteSnapshot = remotePreview.revisionSnapshot();
		remotePreview.destroy?.();

		const queued = Boolean(record || widget.form?._queued === true);
		const unsaved = widget.unsavedState === true;
		const focused = Boolean(
			typeof document !== "undefined" &&
				widget.target?.contains?.(document.activeElement),
		);
		const active =
			widget.component?.active === widget && widget.visible === true;
		const ownedDeferredCompletion =
			!unsaved && !queued
				? this._ownedDeferredCompletion(marker, widget)
				: null;
		const protectedRevision =
			unsaved || queued || (!ownedDeferredCompletion && (active || focused));
		if (!protectedRevision) {
			await withTransition(async () => {
				await widget.applyRevision(response);
				this._hide(
					widget.target?.querySelector("[lp-edited-marker]") ?? marker,
				);
			});
			return;
		}

		const current = widget.revisionSnapshot();
		const rendererCapable = this._rendererCapable(widget, response);
		const local = widget.buildLocalRevision(response);
		const localPreview = await loadRevisionPreview(widget, local.response);
		if (token && state.token !== token) {
			localPreview?.destroy?.();
			return;
		}
		if (!localPreview || !widget.revisionCanReset(localPreview)) {
			localPreview?.destroy?.();
			this._fallback(marker);
			return;
		}
		const localSnapshot = localPreview.revisionSnapshot();
		localPreview.destroy?.();
		const rendererValuesDiffer =
			rendererCapable && this._rendererValuesDiffer(response, local.response);

		if (rendererValuesDiffer && !schemaOnlyRevision) {
			this._storeRevision(marker, response, {
				fingerprint,
				modified,
				record,
				remoteSnapshot,
				schemaChanged,
				submissionChoice: true,
			});
			this._setAction(
				marker,
				"review",
				schemaChanged
					? "The form fields and saved values changed elsewhere."
					: "Saved values changed elsewhere.",
			);
			this._show(marker);
			return;
		}

		if (rendererCapable && schemaChanged) {
			await withTransition(async () => {
				await widget.applyLocalRevision(response, { remoteSnapshot });
				marker = widget.target.querySelector("[lp-edited-marker]") ?? marker;
				this._storeRevision(marker, response, {
					fingerprint,
					modified,
					record,
					remoteSnapshot,
					schemaChanged,
					submissionChoice: false,
				});
				this._setAction(
					marker,
					record ? "apply" : "dismiss",
					"This form's fields have changed. It has been updated to reflect the latest schema.",
				);
				this._show(marker);
			});
			return;
		}

		if (rendererCapable && remoteSnapshot === widget.revisionBaseline) {
			await withTransition(async () => {
				await widget.applyLocalRevision(response, { remoteSnapshot });
				marker = widget.target.querySelector("[lp-edited-marker]") ?? marker;
			});
			if (record) {
				const rebased = await this.view.offlineQueue?.rebaseSubmit(
					record,
					widget,
					{ fingerprint, modified },
				);
				if (rebased) await this.view.offlineQueue?.replay();
			}
			this._hide(marker);
			return;
		}

		if (localSnapshot === remoteSnapshot || current === remoteSnapshot) {
			if (record) await this.view.offlineQueue?.cancel(record.id);
			await withTransition(async () => {
				await widget.applyRevision(response);
				this._hide(
					widget.target?.querySelector("[lp-edited-marker]") ?? marker,
				);
			});
			return;
		}

		this._storeRevision(marker, response, {
			fingerprint,
			modified,
			record,
			remoteSnapshot,
			schemaChanged,
			submissionChoice: queued,
		});
		this._setAction(
			marker,
			queued ? "whole-review" : "reset",
			queued
				? "The saved form changed while this update was queued."
				: "This form changed elsewhere. Reset it to load the saved version.",
		);
		this._show(marker);
	}

	async _installUninitialized(marker, response) {
		const form = marker.closest("form[data-widget]");
		const name = form?.dataset.widget;
		const replacement = name
			? response.html?.querySelector(`[data-widget='${name}']`)
			: null;
		if (!form || !replacement) return false;

		const visible = form.dataset.visible;
		const fresh = replacement.cloneNode(true);
		if (visible !== undefined) fresh.dataset.visible = visible;
		await withTransition(() => form.replaceWith(fresh));
		return true;
	}

	_sameProbeRevision(left, right) {
		return Boolean(
			left &&
				right &&
				left.fingerprint === right.fingerprint &&
				left.modified === right.modified,
		);
	}

	_probe(marker, fingerprint, modified = null) {
		const state = this._state(marker);
		const requested = { fingerprint, modified };
		if (state.conflictPromise) {
			state.pendingProbe = requested;
			return state.conflictPromise.then(() => {
				const pending = state.pendingProbe;
				if (!pending) return;
				state.pendingProbe = null;
				return this._probe(
					marker,
					pending.fingerprint,
					pending.modified,
				);
			});
		}
		if (
			state.probePromise &&
			this._sameProbeRevision(state.probeRevision, requested)
		) {
			return state.probePromise;
		}
		if (!this._sameProbeRevision(state.pendingProbe, requested)) {
			state.pendingProbe = requested;
		}
		if (state.probePromise) return state.probePromise;

		const drain = async () => {
			let processed = null;
			while (state.pendingProbe) {
				const next = state.pendingProbe;
				state.pendingProbe = null;
				if (this._sameProbeRevision(processed, next)) continue;
				state.probeRevision = next;
				await this._runProbe(marker, next.fingerprint, next.modified);
				processed = next;
			}
		};
		const promise = drain().finally(() => {
			if (state.probePromise !== promise) return;
			state.probePromise = null;
			state.probeRevision = null;
		});
		state.probePromise = promise;
		return promise;
	}

	async _runProbe(marker, fingerprint, modified = null) {
		if (!marker?.isConnected && marker?.isConnected !== undefined) return;
		const state = this._state(marker);
		const token = {};
		state.token = token;
		const route = marker.dataset.editedRoute;
		if (!route) {
			this._fallback(
				marker,
				new Error("Edited marker has no replacement route"),
			);
			return;
		}

		try {
			const response = await request.get(route, null, {
				acknowledgeEntities: false,
				replaceErrorPage: false,
			});
			if (state.token !== token) return;
			const form = marker.closest("form[data-widget]");
			const widget = form?._lp_widget;
			const completion = this._ownedDeferredCompletion(marker, widget);
			if (response?.unchanged) {
				this._hide(marker);
				this._markerRevisions.set(marker, { fingerprint, modified });
				this._forgetDeferredCompletion(completion);
				return;
			}
			if (!response?.ok) {
				this._fallback(marker);
				this._forgetDeferredCompletion(completion);
				return;
			}

			if (!widget) {
				if (await this._installUninitialized(marker, response)) return;
				this._fallback(marker, new Error("Replacement response has no form"));
				return;
			}

			if (widget.revisionBaseline === null) widget.commitRevisionBaseline();
			await this._stageRevision(marker, widget, response, {
				fingerprint,
				modified,
			});
			this._markerRevisions.set(marker, { fingerprint, modified });
			this._forgetDeferredCompletion(completion);
		} catch (error) {
			if (state.token === token) this._fallback(marker, error);
		}
	}

	async _probeEntity(key, fingerprint, modified = null) {
		const entity = this.entities.get(key);
		if (!entity) return;
		const revision = { fingerprint, modified };
		const stale = Array.from(entity.markers).filter((marker) => {
			const current = this._markerRevisions.get(marker);
			return (
				current?.fingerprint !== fingerprint ||
				(Boolean(modified) && current?.modified !== modified) ||
				Boolean(
					this._ownedDeferredCompletion(
						marker,
						marker.closest?.("form[data-widget]")?._lp_widget,
					),
				)
			);
		});
		await Promise.all(
			stale.map((marker) => this._probe(marker, fingerprint, modified)),
		);
		const latest = this._latestRevisions.get(key);
		const anchorRevision = latest?.fingerprint ? latest : revision;
		for (const anchor of entity.anchors) {
			anchor.dataset.fingerprint = anchorRevision.fingerprint;
			if (anchorRevision.modified) {
				anchor.dataset.modified = anchorRevision.modified;
			}
		}
	}

	async receiveEntityResult(key, result) {
		if (!key || !result) return;
		if (result.status === "unavailable") {
			for (const marker of this.entities.get(key)?.markers ?? []) {
				this._fallback(marker);
			}
			return;
		}
		if (
			result.status === "unchanged" &&
			this._deferredCompletions.has(key)
		) {
			const revision = this._latestRevisions.get(key) ?? {
				fingerprint: result.revision ?? null,
				modified: null,
			};
			if (revision.fingerprint) {
				await this._probeEntity(
					key,
					revision.fingerprint,
					revision.modified,
				);
			}
			return;
		}
		if (result.status !== "changed" || !result.payload?.fingerprint) return;
		const revision = {
			fingerprint: result.payload.fingerprint,
			modified: result.payload.modified ?? null,
		};
		this._latestRevisions.set(key, revision);
		await this._probeEntity(key, revision.fingerprint, revision.modified);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_restores_active_autofill_without_form_sync
	 * @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
	 * @features edited-entity-notice deferred-jobs
	 * @dimensions active-operation reload form-lock
	 */
	_lockEntity(entity, descriptor) {
		if (!entity || !descriptor?.operation) return;
		const forms = new Set();
		for (const marker of entity.markers ?? []) {
			const form = marker.closest("form[data-widget]");
			if (form) forms.add(form);
		}
		for (const anchor of entity.anchors ?? []) {
			for (const form of anchor.querySelectorAll?.(
				"form[data-widget='PageInfo'], form[data-widget='TaskForm']",
			) ?? []) {
				forms.add(form);
			}
		}

		for (const form of forms) {
			if (
				form.dataset.deferredLock !== "form" &&
				!["PageInfo", "TaskForm"].includes(form.dataset.widget)
			)
				continue;

			const widget = form._lp_widget;
			if (widget?._deferredOperation !== descriptor.operation) {
				widget?.lockDeferredOperation?.(descriptor);
			}
			if (!widget) {
				form.dataset.operation = descriptor.operation;
				form.dataset.operationRevision = String(
					Number(descriptor.revision) || 0,
				);
				form.dataset.deferredLock = "form";
			}
			this.view.DeferredOperations?.track(descriptor.operation, {
				revision: Number(descriptor.revision) || 0,
				node: widget?.target ?? form,
			});
		}
	}

	_syncSubscriptions() {
		const mounted = this.entities;
		const active = new Set();
		for (const entity of mounted.values()) {
			const entityId = `edit:${entity.key}`;
			const lockId = `lock:${entity.key}`;
			active.add(lockId);
			if (entity.key !== this.view.key) active.add(entityId);
			if (entity.key !== this.view.key && !this._unsubscribers.has(entityId)) {
				this._unsubscribers.set(
					entityId,
					this.view.PollingCoordinator?.subscribe(
						{
							id: entityId,
							type: "entity",
							key: entity.key,
							revision: entity.fingerprint,
						},
						{
							onResult: (result) =>
								this.receiveEntityResult(entity.key, result),
						},
					) ?? (() => {}),
				);
			}
			if (!this._unsubscribers.has(lockId)) {
				this._unsubscribers.set(
					lockId,
					this.view.PollingCoordinator?.subscribe(
						{
							id: lockId,
							type: "form-lock",
							key: entity.key,
							revision: "unlocked",
						},
						{
							onResult: async (result) => {
								if (result.status !== "changed") return;
								if (result.payload?.locked) {
									this._lockEntity(
										this.entities.get(entity.key),
										result.payload,
									);
								} else if (
									Array.from(this.entities.get(entity.key)?.markers ?? []).some(
										(marker) =>
											marker
												.closest?.("form[data-widget]")
												?.hasAttribute("data-deferred-lock"),
									)
								) {
									await this.view.reconcileChange?.({
										type: "poll",
										key: entity.key,
									});
								}
							},
						},
					) ?? (() => {}),
				);
			}
		}
		for (const [id, unsubscribe] of this._unsubscribers) {
			if (active.has(id)) continue;
			unsubscribe();
			this._unsubscribers.delete(id);
		}
		return mounted;
	}

	async reconcileSubscriptions() {
		const mounted = this._syncSubscriptions();
		await Promise.all(
			Array.from(mounted.values(), async (entity) => {
				const latest = this._latestRevisions.get(entity.key);
				if (!latest) return;
				await this._probeEntity(
					entity.key,
					latest.fingerprint,
					latest.modified,
				);
			}),
		);
		return mounted;
	}

	check(keys = null) {
		const mounted = this._syncSubscriptions();
		const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
		const ids = requested.flatMap((key) => [
			key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
			`lock:${key}`,
		]);
		return this.view.PollingCoordinator?.trigger(ids);
	}

	enqueue(keys = null) {
		const mounted = this._syncSubscriptions();
		const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
		const ids = requested.flatMap((key) => [
			key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
			`lock:${key}`,
		]);
		this.view.PollingCoordinator?.enqueue(ids);
	}

	invalidate(keys) {
		if (!keys) return this.check();
		const requested = Array.isArray(keys) ? keys : [keys];
		return this.check(requested.filter(Boolean));
	}

	acknowledge({ key, fingerprint, modified = null } = {}) {
		if (!key || !fingerprint) return;
		this._latestRevisions.set(key, { fingerprint, modified });
		if (this.view.key === key) {
			this.view.elt.dataset.fingerprint = fingerprint;
			if (modified) this.view.elt.dataset.modified = modified;
		}
		this.view.PollingCoordinator?.acknowledge(`edit:${key}`, fingerprint);
		this.view.PollingCoordinator?.acknowledge(
			`view:entity:${key}`,
			fingerprint,
		);

		const entity = this.entities.get(key);
		if (!entity) return;
		for (const anchor of entity.anchors) {
			anchor.dataset.fingerprint = fingerprint;
			if (modified) anchor.dataset.modified = modified;
		}
		for (const marker of entity.markers) {
			this._markerRevisions.set(marker, { fingerprint, modified });
		}
	}

	pause() {}

	resume() {
		if (this._destroyed || !this.view.online || this.view.hidden) return;
		return this.reconcileSubscriptions();
	}

	async stageConflict(widget, { record, response } = {}) {
		const marker = widget?.target?.querySelector?.("[lp-edited-marker]");
		if (!marker || !record || !response) return false;
		const revision = (response.entities || []).find(
			(entity) => entity.key === record.target_key,
		);
		const state = this._state(marker);
		const reconcile = (async () => {
			if (state.probePromise) await state.probePromise;
			state.token = {};
			if (widget.revisionBaseline === null) widget.commitRevisionBaseline();
			await this._stageRevision(marker, widget, response, {
				fingerprint: revision?.fingerprint ?? null,
				modified: revision?.modified ?? null,
				record,
			});
			delete widget._offlineConflict;
			return true;
		})();
		state.conflictPromise = reconcile;
		try {
			return await reconcile;
		} finally {
			if (state.conflictPromise === reconcile) {
				state.conflictPromise = null;
			}
		}
	}

	async resolveRevision(marker, choice) {
		const state = this._state(marker);
		const widget = marker.closest("form[data-widget]")?._lp_widget;
		if (!widget || !state.response) {
			this._fallback(marker);
			return false;
		}

		const fieldSelection =
			choice && typeof choice === "object" ? (choice.selections ?? {}) : null;
		const localSelected = fieldSelection
			? Object.values(fieldSelection).some((source) => source === "local")
			: choice === "local";

		if (!localSelected) {
			if (state.record) await this.view.offlineQueue?.cancel(state.record.id);
			await withTransition(() => widget.applyRevision(state.response));
		} else {
			let selectedSubmission;
			if (fieldSelection) {
				selectedSubmission = structuredClone(state.response.submission ?? {});
				const localSubmission = choice.localResponse?.submission ?? {};
				for (const [id, source] of Object.entries(fieldSelection)) {
					if (source !== "local") continue;
					if (Object.hasOwn(localSubmission, id)) {
						selectedSubmission[id] = structuredClone(localSubmission[id]);
					} else {
						delete selectedSubmission[id];
					}
				}
			}
			await withTransition(() =>
				widget.applyLocalRevision(state.response, {
					remoteSnapshot: state.remoteSnapshot,
					markUnsaved: !state.record,
					selectedSubmission,
				}),
			);
			if (state.record) {
				const rebased = await this.view.offlineQueue?.rebaseSubmit(
					state.record,
					widget,
					{
						fingerprint: state.fingerprint,
						modified: state.modified,
					},
				);
				if (rebased) await this.view.offlineQueue?.replay();
			}
		}

		const currentMarker =
			widget.target?.querySelector("[lp-edited-marker]") ?? marker;
		this._hide(currentMarker);
		return true;
	}

	async _click(event) {
		const button = event.target.closest("[data-role='edited-reset']");
		if (!button) return;
		const marker = button.closest("[lp-edited-marker]");
		const state = marker ? this._state(marker) : null;
		if (!marker || !state) return;

		if (state.mode === "reload") {
			window.location.reload();
			return;
		}
		if (state.mode === "dismiss") {
			this._hide(marker);
			return;
		}
		const widget = marker.closest("form[data-widget]")?._lp_widget;
		if (!widget || !state.response) {
			this._fallback(marker);
			return;
		}

		button.disabled = true;
		try {
			if (state.mode === "review") {
				const modal = new FormRevisionModal(this, marker, widget, state);
				const shown = await modal.init();
				if (!shown && state.record) {
					await new WholeFormRevisionModal(this, marker, widget).init();
				} else if (!shown) {
					this._setAction(
						marker,
						"reset",
						"This form changed elsewhere. Reset it to load the saved version.",
					);
				}
			} else if (state.mode === "whole-review") {
				await new WholeFormRevisionModal(this, marker, widget).init();
			} else if (state.mode === "apply" && state.record) {
				await this.resolveRevision(marker, "local");
			} else {
				await this.resolveRevision(marker, "server");
			}
		} catch (error) {
			this._fallback(
				widget.target?.querySelector("[lp-edited-marker]") ?? marker,
				error,
			);
		} finally {
			button.disabled = false;
		}
	}

	_entityUpdated(event) {
		this.acknowledge(event.detail);
	}

	destroy() {
		this._destroyed = true;
		for (const unsubscribe of this._unsubscribers.values()) unsubscribe();
		this._unsubscribers.clear();
		this._deferredCompletions.clear();
		this.view.elt.removeEventListener("click", this._click);
		window.removeEventListener("entity-updated", this._entityUpdated);
	}
}

const LOGOUT_BUTTON_SELECTOR = "[data-action='logout'][data-route]";

let initialized = false;

/**
 * @testable false
 * @covered-by src/script/shared/logout.mjs::initializeLogoutForms
 * @reason private logout request helper is exercised through logout controls
 */
const submitLogout = async (route, { submitter = null, state = null } = {}) => {
	state = state || submitter;
	if (state?.dataset?.submitting === "true") return;
	if (state?.dataset) state.dataset.submitting = "true";
	if (submitter && "disabled" in submitter) {
		submitter.disabled = true;
	}

	const response = await request.post(route);
	if (response?.redirect) {
		window.location.href = response.redirect;
	} else if (response?.ok) {
		window.location.href = "/users/login";
	} else {
		if (state?.dataset) state.dataset.submitting = "false";
		if (submitter && "disabled" in submitter) {
			submitter.disabled = false;
		}
	}
};

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_logout_clears_session_and_returns_login
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
 * @tests tests_js/test_009_request_csrf.py::test_logout_button_posts_without_hidden_form
 * @features login
 * @dimensions logout redirect button
 */
const initializeLogoutForms = (root = document) => {
	if (initialized) return;
	initialized = true;

	root.addEventListener("click", async (event) => {
		const button = event.target?.closest?.(LOGOUT_BUTTON_SELECTOR);
		if (!button) return;

		event.preventDefault();
		await submitLogout(button.dataset.route, {
			submitter: button,
			state: button,
		});
	});
};

const DB_NAME = "offline-db";
const DB_VERSION = 5;
const SYNC_STORE = "sync";
const MUTATION_STORE = "mutations";

/**
 * @testable true
 * @tests tests_js/test_028_form_state_split.py::test_offline_database_upgrade_discards_legacy_activity_records
 * @features offline
 * @dimensions database-upgrade legacy-record-discard mutation-store
 */
function openDB() {
	return new Promise((resolve, reject) => {
		const request = indexedDB.open(DB_NAME, DB_VERSION);
		request.onerror = () => reject(request.error);
		request.onsuccess = () => {
			const db = request.result;
			db.onversionchange = () => db.close();
			resolve(db);
		};
		request.onupgradeneeded = (event) => {
			const db = event.target.result;
			if (event.oldVersion < 2) {
				// The store fields were renamed sync_id (snake_case) to match the
				// wire format; nuke old v1 stores so the keyPath matches records.
				if (db.objectStoreNames.contains(SYNC_STORE)) {
					db.deleteObjectStore(SYNC_STORE);
				}
			}
			if (!db.objectStoreNames.contains(SYNC_STORE)) {
				db.createObjectStore(SYNC_STORE, { keyPath: "sync_id" });
			}

			if (db.objectStoreNames.contains("activity")) {
				db.deleteObjectStore("activity");
			}
			if (db.objectStoreNames.contains("submit")) {
				db.deleteObjectStore("submit");
			}
			if (!db.objectStoreNames.contains(MUTATION_STORE)) {
				db.createObjectStore(MUTATION_STORE, { keyPath: "id" });
			}
		};
	});
}

/**
 * @testable false
 * @covered-by src/script/shared/offline.mjs::updateSyncRecord
 * @covered-by src/script/shared/offline.mjs::getAllOfflineRecords
 * @reason transaction wrapper is exercised through the offline record API
 */
function withTransaction(storeNames, mode, executor) {
	return openDB().then(
		(db) =>
			new Promise((resolve, reject) => {
				const tx = db.transaction(storeNames, mode);
				tx.oncomplete = () => db.close();
				tx.onerror = () => {
					db.close();
					reject(tx.error);
				};
				try {
					executor(tx, resolve, reject);
				} catch (e) {
					reject(e);
				}
			}),
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/offline.mjs::updateSyncRecord
 * @covered-by src/script/shared/offline.mjs::getAllOfflineRecords
 * @reason request promisification is private IndexedDB plumbing
 */
function promisify(request) {
	return new Promise((resolve, reject) => {
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_failed_offline_replay_keeps_queue_and_retries
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
 * @features sync
 * @dimensions offline-replay replay-order queue-preserved dedupe reload
 */
function updateSyncRecord(record) {
	const timestamp = Date.now();
	return withTransaction(
		SYNC_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			const store = tx.objectStore(SYNC_STORE);
			try {
				const existing = await promisify(store.get(record.sync_id));
				const merged = existing
					? {
							...existing,
							...record,
							save: existing.save || record.save,
							timestamp,
						}
					: { ...record, timestamp };
				if (existing && !Object.hasOwn(record, "html")) delete merged.html;
				await promisify(store.put(merged));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/sync.mjs::SyncManager.state
 * @reason single-record lookup is owned by the widget state sync path
 */
function getSyncRecord(sync_id) {
	return withTransaction(
		[SYNC_STORE],
		"readonly",
		async (tx, resolve, reject) => {
			try {
				const record = await promisify(tx.objectStore(SYNC_STORE).get(sync_id));
				resolve(record ?? null);
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_failed_offline_replay_keeps_queue_and_retries
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
 * @features sync
 * @dimensions offline-replay replay-order queue-preserved dedupe reload
 */
function getAllOfflineRecords() {
	return withTransaction(
		[SYNC_STORE, MUTATION_STORE],
		"readonly",
		async (tx, resolve, reject) => {
			try {
				const sync = await promisify(tx.objectStore(SYNC_STORE).getAll());
				const mutations = await promisify(
					tx.objectStore(MUTATION_STORE).getAll(),
				);
				resolve({ sync, mutations });
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/sync.mjs::SyncManager._reconcile
 * @reason single-record deletion is owned by successful state reconciliation
 */
function deleteSyncRecord(sync_id) {
	return withTransaction(
		SYNC_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			try {
				await promisify(tx.objectStore(SYNC_STORE).delete(sync_id));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
 * @features sync
 * @dimensions offline-replay queue-clear dedupe
 */
function deleteSyncRecords(sync_ids) {
	if (!sync_ids?.length) return Promise.resolve();
	return withTransaction(
		SYNC_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			try {
				const store = tx.objectStore(SYNC_STORE);
				await Promise.all(sync_ids.map((id) => promisify(store.delete(id))));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_create_mutations_persist_after_reload
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @pairs offline:queue-create offline:queue-submit offline:reload
 */
function setOfflineMutation(record) {
	return withTransaction(
		MUTATION_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			try {
				await promisify(tx.objectStore(MUTATION_STORE).put(record));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutation_overlay_hides_deleted_items
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutations_replay_when_online
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @features offline
 * @dimensions cached-overlay replay queue-submit
 */
function getOfflineMutations() {
	return withTransaction(
		MUTATION_STORE,
		"readonly",
		async (tx, resolve, reject) => {
			try {
				const records = await promisify(
					tx.objectStore(MUTATION_STORE).getAll(),
				);
				resolve(records);
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutations_replay_when_online
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @pairs offline:replay offline:queue-clear offline:notification
 */
function deleteOfflineMutations(ids) {
	if (!ids?.length) return Promise.resolve();
	return withTransaction(
		MUTATION_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			try {
				const store = tx.objectStore(MUTATION_STORE);
				await Promise.all(ids.map((id) => promisify(store.delete(id))));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private queue id helper exercised through queued offline mutations
 */
function createId() {
	if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
	return `offline-mutation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private response helper used by optimistic offline rendering
 */
function elementResponse(element) {
	const html = document.implementation.createHTMLDocument("");
	if (element) html.body.appendChild(element);
	return {
		ok: true,
		html,
	};
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private IndexedDB serialization helper owned by offline queue behavior
 */
function serializeFormData(data) {
	const fields = [];
	const files = [];

	for (const [name, value] of data.entries()) {
		if (value instanceof File) {
			if (value.size > 0 && value.name) {
				files.push({
					name,
					file: value,
					filename: value.name,
					type: value.type,
				});
			}
		} else {
			fields.push([name, value]);
		}
	}

	return { fields, files };
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private request payload rehydration helper owned by replay behavior
 */
function formDataFromRecord(record) {
	const data = new FormData();
	for (const [name, value] of record.fields || []) {
		data.append(name, value);
	}
	for (const file of record.files || []) {
		data.append(file.name, file.file, file.filename);
	}
	if (record.method !== "DELETE") {
		data.set("offline", "True");
		if (record.fingerprint) {
			data.set("offline-fingerprint", record.fingerprint);
		}
	}
	return data;
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private queued-form lookup helper used by optimistic renderers
 */
function field(record, name) {
	return (record.fields || []).find(([key]) => key === name)?.[1] || "";
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_create_mutations_persist_after_reload
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutation_overlay_hides_deleted_items
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutations_replay_when_online
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_offline_submit_restores_queued_form_after_reload
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_offline_submission_conflict_keeps_queue_until_choice
 * @tests tests_js/test_028_form_state_split.py::test_offline_submit_record_keeps_originating_entity_fingerprint
 * @tests tests_js/test_028_form_state_split.py::test_offline_submit_record_keeps_renderer_snapshot_out_of_replay_payload
 * @tests tests_js/test_028_form_state_split.py::test_offline_replay_keeps_stale_submission_queued_for_reconciliation
 * @tests tests_js/test_028_form_state_split.py::test_offline_replay_removes_committed_record_before_acknowledgement
 * @tests tests_js/test_028_form_state_split.py::test_offline_replay_retries_a_conflict_rebased_by_the_form
 * @features offline
 * @dimensions queue-submit cached-overlay replay notification fingerprint immutable-command form-restore reload renderer-snapshot replay-payload replay-precondition conflict-review fingerprint-precondition conflict-durability conflict-rebase dispatch acknowledgement-order
 */
class OfflineQueue {
	constructor(view) {
		this.view = view;
		this.records = [];
		this._replaying = false;
	}

	async init() {
		this.records = await getOfflineMutations();
	}

	get widgets() {
		return Object.values(this.view.components).flatMap((component) => {
			return Object.values(component.widgets);
		});
	}

	get targets() {
		return this.widgets.filter(
			(widget) => typeof widget.handleOfflineQueue === "function",
		);
	}

	async _dispatch(context, targets = this.targets) {
		return Promise.all(
			[...new Set(targets)].filter(Boolean).map(async (target) => {
				if (typeof target === "function") return target(context);
				return target.handleOfflineQueue?.(context);
			}),
		);
	}

	_responseFromResults(results) {
		return results.find((result) => {
			return result && typeof result === "object" && "ok" in result;
		});
	}

	async queueSubmit(component, data, route, method = "POST") {
		const widget = component.active;
		const target = widget?.target;
		if (!target?.hasAttribute("lp-offline")) return null;
		if (typeof widget.offline !== "function") return null;

		await this._destinationWidget(component);

		const action = method === "POST" ? "create" : "update";
		const partial = await widget.offline({
			action,
			queue: this,
			component,
			data,
			method,
			route,
			widget,
		});
		if (!partial) return null;
		const fingerprint =
			partial.fingerprint ??
			target.closest?.("[lp-entity]")?.dataset?.fingerprint ??
			this.view.elt?.dataset?.fingerprint ??
			null;
		const modified =
			partial.modified ??
			target.closest?.("[lp-entity]")?.dataset?.modified ??
			this.view.elt?.dataset?.modified ??
			null;
		const rendererSubmission =
			partial.renderer_submission ??
			widget.form?.renderer?._packageSubmission?.() ??
			null;
		const formControls = Array.from(
			target.querySelectorAll?.("[data-combobox-id]") || [],
		)
			.filter((control) => !control.closest?.(".form-element"))
			.map((control) => {
				const combobox = control._lp_combobox;
				if (!combobox?.name) return null;
				const options = (combobox.options || []).filter((option) =>
					combobox.values?.has(option.id),
				);
				return { name: combobox.name, options };
			})
			.filter(Boolean);

		const result = await this.queue({
			action,
			method,
			route,
			data,
			...partial,
			fingerprint,
			modified,
			renderer_submission: rendererSubmission,
			form_controls: formControls,
		});

		return result.response
			? { ...result.response, queued: true }
			: { ok: true, queued: true };
	}

	async _destinationWidget(component) {
		const destination = component.active?.target?.dataset.destination;
		if (!destination) return null;

		const [componentId, widgetName] = destination.split(":");
		if (!widgetName) return null;

		const componentElt =
			componentId === component.name
				? component.elt
				: document.getElementById(componentId);
		const destinationComponent = this.view.getComponent(componentElt);
		if (!destinationComponent) return null;

		return (
			destinationComponent.widgets[widgetName] ||
			(await destinationComponent.loadWidget(widgetName))
		);
	}

	async applyResponse(response, route = "") {
		if (!response?.html) return response;

		this._applyTombstones(response.html);
		await this._applyOverlays(response.html, route);

		return response;
	}

	async replay() {
		if (!this.view.online || this._replaying) return 0;

		this._replaying = true;
		const completed = [];

		try {
			for (const record of this._sortedRecords()) {
				let current = record;
				while (current) {
					const response = await this._send(current);
					if (response?.conflict) {
						const attemptedFingerprint = current.fingerprint;
						current.conflictResponse = response;
						await this._dispatch({
							phase: "conflict",
							queue: this,
							record: current,
							response,
						});
						const rebased = this.records.find(
							(queued) => queued.id === current.id,
						);
						if (
							!rebased ||
							rebased.fingerprint === attemptedFingerprint
						) {
							break;
						}
						current = rebased;
						continue;
					}
					if (!response?.ok || response.error) break;

					await deleteOfflineMutations([current.id]);
					this.records = this.records.filter(
						(queued) => queued.id !== current.id,
					);
					completed.push(current.id);
					if (current.method === "PUT") {
						this._acknowledgeResponse(response);
					}
					this._finalize(current, response);
					await this._dispatch({
						phase: "replayed",
						queue: this,
						record: current,
						response,
					});
					break;
				}
			}
		} finally {
			this._replaying = false;
		}

		return completed.length;
	}

	async rebaseSubmit(record, widget, { fingerprint, modified } = {}) {
		if (!record?.id || !widget) return null;
		const data = widget.component?.formData ?? widget.formData;
		if (!(data instanceof FormData)) return null;

		const serialized = serializeFormData(data);
		const currentFileNames = new Set(serialized.files.map((file) => file.name));
		serialized.files.push(
			...(record.files || []).filter(
				(file) => !currentFileNames.has(file.name),
			),
		);
		const rebased = {
			...record,
			fingerprint: fingerprint || record.fingerprint || null,
			modified: modified || record.modified || null,
			renderer_submission:
				widget.form?.renderer?._packageSubmission?.() ??
				record.renderer_submission ??
				null,
			fields: serialized.fields,
			files: serialized.files,
		};
		delete rebased.conflictResponse;

		await this._store(rebased);
		await this._dispatch({
			phase: "queued",
			queue: this,
			record: rebased,
		});
		return rebased;
	}

	async queue(record) {
		const queued = this._queuedRecord(record);
		await this._store(queued);
		const results = await this._dispatch({
			phase: "queued",
			queue: this,
			record: queued,
		});
		return {
			record: queued,
			response: this._responseFromResults(results),
		};
	}

	_queuedRecord(record) {
		const id = record.id || createId();
		const serialized = record.data
			? serializeFormData(record.data)
			: {
					fields: record.fields || [],
					files: record.files || [],
				};
		return {
			id,
			action:
				record.action || (record.method === "DELETE" ? "delete" : "submit"),
			kind: record.kind,
			method: record.method || "POST",
			route: record.route,
			client_key:
				record.client_key ||
				(record.action === "create" ? `offline:${id}` : null),
			target_key: record.target_key,
			fingerprint: record.fingerprint || null,
			modified: record.modified || null,
			renderer_submission: record.renderer_submission ?? null,
			form_controls: record.form_controls || [],
			fields: serialized.fields,
			files: serialized.files,
			created_at: record.created_at || Date.now(),
		};
	}

	response(element) {
		return elementResponse(element);
	}

	field(record, name) {
		return field(record, name);
	}

	recordsFor({ kind = null, action = null } = {}) {
		return this._sortedRecords().filter((record) => {
			if (kind && record.kind !== kind) return false;
			if (action && record.action !== action) return false;
			return true;
		});
	}

	async cancel(match) {
		const records = this.records.filter((record) => {
			return this._recordMatches(record, match);
		});
		if (records.length === 0) return [];

		await deleteOfflineMutations(records.map((record) => record.id));
		const ids = new Set(records.map((record) => record.id));
		this.records = this.records.filter((record) => !ids.has(record.id));
		await Promise.all(
			records.map((record) => {
				return this._dispatch({
					phase: "cancelled",
					queue: this,
					record,
				});
			}),
		);
		return records;
	}

	_recordMatches(record, match) {
		if (typeof match === "function") return match(record);
		if (typeof match === "string") {
			return [record.id, record.client_key, record.target_key].includes(match);
		}
		if (!match || typeof match !== "object") return false;

		return Object.entries(match).every(([key, value]) => record[key] === value);
	}

	async _store(record) {
		await setOfflineMutation(record);
		this.records = [
			...this.records.filter((existing) => existing.id !== record.id),
			record,
		];
	}

	_sortedRecords() {
		return [...this.records].sort((a, b) => a.created_at - b.created_at);
	}

	async _send(record) {
		if (record.method === "DELETE") return request.delete(record.route);

		const data = formDataFromRecord(record);
		if (record.method === "PUT") {
			return request.put(record.route, data, { acknowledgeEntities: false });
		}
		return request.post(record.route, data);
	}

	_acknowledgeResponse(response) {
		for (const entity of response?.entities || []) {
			window.dispatchEvent(
				new CustomEvent("entity-updated", { detail: entity }),
			);
		}
	}

	_finalize(record, response) {
		const key =
			record.action === "create" ? record.client_key : record.target_key;
		if (!key) return;
		const current = document.querySelector(`[data-key="${key}"]`);

		if (record.action === "create") {
			const replacement = response.html?.querySelector("li,[lp-entity]");
			if (current && replacement) current.replaceWith(replacement);
			else if (current && response.removed) current.remove();
			return;
		}

		if (["complete", "delete"].includes(record.action) && current) {
			current.remove();
		}
	}

	_applyTombstones(documentFragment) {
		for (const key of this._hiddenKeys()) {
			documentFragment
				.querySelectorAll(`[data-key="${key}"]`)
				.forEach((item) => {
					item.remove();
				});
		}
	}

	_hiddenKeys() {
		return this.records
			.filter((record) => {
				return ["delete", "complete"].includes(record.action);
			})
			.map((record) => record.target_key)
			.filter(Boolean);
	}

	async _applyOverlays(documentFragment, route) {
		const context = {
			phase: "overlay",
			queue: this,
			html: documentFragment,
			records: this._sortedRecords(),
			route,
		};

		await this._dispatch(context);
	}
}

const MAX_SUBSCRIPTIONS_PER_REQUEST = 64;
const CLIENT_ID_KEY = "lagniappe-poll-client";
const ORDINARY_INTERVALS = [15_000, 15_000, 30_000, 30_000, 60_000];
const TYPE_INTERVALS = Object.freeze({
	document: 2_000,
	ingress: 2_500,
	operation: 4_000,
});

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason page-scoped client identity creation is exercised through coordinator requests
 */
function clientId() {
	let value = null;
	try {
		value = sessionStorage.getItem(CLIENT_ID_KEY);
	} catch {
		// Storage can be unavailable in hardened/private browser contexts.
	}
	if (!value) {
		value =
			globalThis.crypto?.randomUUID?.() ||
			`poll-${Date.now()}-${Math.random().toString(16).slice(2)}`;
		try {
			sessionStorage.setItem(CLIENT_ID_KEY, value);
		} catch {
			// The in-memory identity remains valid for this page lifetime.
		}
	}
	return value;
}

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason bounded scheduling jitter is exercised through coordinator cadence
 */
function jitter(delay, factor = 0.9 + Math.random() * 0.2) {
	return Math.max(Math.round(delay * factor), 250);
}

/**
 * One view-scoped scheduler for every server-state subscription.
 *
 * @testable true
 * @tests tests_js/test_034_polling_coordinator.py::test_polling_coordinator_batches_due_subscriptions_and_applies_results
 * @tests tests_js/test_034_polling_coordinator.py::test_polling_coordinator_enqueues_reentrant_followup_without_waiting
 * @features polling
 * @dimensions batching cadence lifecycle coalescing acknowledgement reentrancy requested-cycle
 */
class PollingCoordinator {
	constructor(view) {
		this.view = view;
		this.clientId = clientId();
		this.subscriptions = new Map();
		this.timer = null;
		this.activePoll = null;
		this.activeIds = new Set();
		this.inflight = null;
		this.followup = false;
		this.queuedIds = new Set();
		this.destroyed = false;
	}

	init() {
		return this;
	}

	subscribe(descriptor, { onResult = null, beforePoll = null } = {}) {
		if (this.destroyed || !descriptor?.id || !descriptor?.type) return () => {};
		const existing = this.subscriptions.get(descriptor.id);
		const now = Date.now();
		this.subscriptions.set(descriptor.id, {
			...existing,
			descriptor: { ...existing?.descriptor, ...descriptor },
			onResult: onResult ?? existing?.onResult ?? null,
			beforePoll: beforePoll ?? existing?.beforePoll ?? null,
			dueAt: Math.min(existing?.dueAt ?? now, now),
			quiet: existing?.quiet ?? 0,
			errorCount: existing?.errorCount ?? 0,
		});
		this.pause();
		this._schedule(0);
		return () => this.unsubscribe(descriptor.id);
	}

	unsubscribe(id) {
		this.subscriptions.delete(id);
		this.queuedIds.delete(id);
		if (!this.subscriptions.size) this.pause();
		else this._schedule();
	}

	get(id) {
		return this.subscriptions.get(id)?.descriptor ?? null;
	}

	update(id, patch = {}) {
		const subscription = this.subscriptions.get(id);
		if (!subscription) return;
		Object.assign(subscription.descriptor, patch);
	}

	acknowledge(id, revision) {
		const subscription = this.subscriptions.get(id);
		if (!subscription || revision === undefined || revision === null) return;
		subscription.descriptor.revision = revision;
		subscription.quiet = 0;
	}

	/**
	 * Mark subscriptions for an immediate cycle without exposing a promise that
	 * a callback in the active cycle could accidentally await.
	 */
	enqueue(ids = null) {
		const requested =
			ids === null
				? new Set(this.subscriptions.keys())
				: new Set(Array.isArray(ids) ? ids : [ids]);
		const now = Date.now();
		for (const [id, subscription] of this.subscriptions) {
			if (!requested.has(id)) continue;
			subscription.dueAt = now;
			if (this.activePoll) this.queuedIds.add(id);
		}
		if (this.activePoll) {
			this.followup = true;
			return;
		}
		this._schedule(0);
	}

	trigger(ids = null) {
		const requested =
			ids === null
				? new Set(this.subscriptions.keys())
				: new Set(Array.isArray(ids) ? ids : [ids]);
		if (
			this.activePoll &&
			Array.from(requested).every((id) => this.activeIds.has(id))
		) {
			return this.activePoll;
		}
		this.enqueue(ids);
		if (this.activePoll) {
			const current = this.activePoll;
			const followup = () =>
				Promise.resolve().then(() => this.activePoll ?? this._poll());
			return current.then(followup, followup);
		}
		return this._poll();
	}

	pause() {
		if (this.timer) window.clearTimeout(this.timer);
		this.timer = null;
	}

	resume() {
		if (this.destroyed) return Promise.resolve([]);
		return this.trigger();
	}

	async closeDocuments(syncIds) {
		const closed = Array.from(new Set(syncIds || [])).filter(Boolean);
		if (!closed.length || !this.view.online) return;
		if (this.activePoll) await this.activePoll;
		return request.post(
			ENDPOINTS.poll,
			{
				version: 1,
				client_id: this.clientId,
				subscriptions: [],
				closed_documents: closed,
			},
			{ keepalive: true },
		);
	}

	_interval(subscription, result) {
		if (result?.status === "error") {
			subscription.errorCount += 1;
			return Math.min(2 ** subscription.errorCount * 2_000, 60_000);
		}
		subscription.errorCount = 0;
		if (result?.status === "changed") subscription.quiet = 0;
		else subscription.quiet += 1;

		if (subscription.descriptor.type === "operation") {
			const steps = [4_000, 8_000, 16_000, 30_000];
			return steps[Math.min(subscription.quiet, steps.length - 1)];
		}
		if (TYPE_INTERVALS[subscription.descriptor.type]) {
			return (
				Number(result?.poll_after_ms) ||
				TYPE_INTERVALS[subscription.descriptor.type]
			);
		}
		return ORDINARY_INTERVALS[
			Math.min(subscription.quiet, ORDINARY_INTERVALS.length - 1)
		];
	}

	_applyProtocolState(subscription, result) {
		if (result.revision !== undefined) {
			subscription.descriptor.revision = result.revision;
		}
		if (result.operation_revision !== undefined) {
			subscription.descriptor.operation_revision = result.operation_revision;
		}
		if (subscription.descriptor.type === "document" && result.payload) {
			if (result.payload.generation) {
				subscription.descriptor.generation = result.payload.generation;
			}
			if (result.payload.presence_digest) {
				subscription.descriptor.presence_digest =
					result.payload.presence_digest;
			}
		}
	}

	_due() {
		const now = Date.now();
		return Array.from(this.subscriptions.values())
			.filter((subscription) => subscription.dueAt <= now)
			.slice(0, MAX_SUBSCRIPTIONS_PER_REQUEST);
	}

	_poll() {
		if (this.destroyed || this.view.hidden || !this.view.online) {
			return Promise.resolve([]);
		}
		if (this.activePoll) {
			this.followup = true;
			return this.activePoll;
		}

		const cycle = this._runPoll();
		this.activePoll = cycle;
		const complete = () => {
			if (this.activePoll !== cycle) return;
			this.activePoll = null;
			this.activeIds.clear();
			const followup = this.followup;
			this.followup = false;
			if (followup) {
				queueMicrotask(() => this._poll());
			} else {
				this._schedule();
			}
		};
		void cycle.then(complete, complete);
		return cycle;
	}

	async _runPoll() {
		let due = [];
		let results = [];
		try {
			due = this._due();
			if (!due.length) return [];
			this.activeIds = new Set(due.map(({ descriptor }) => descriptor.id));
			for (const { descriptor } of due) {
				this.queuedIds.delete(descriptor.id);
			}
			const hooks = new Set(
				due.map(({ beforePoll }) => beforePoll).filter(Boolean),
			);
			for (const hook of hooks) await hook();
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			due = due.filter(
				(subscription) =>
					this.subscriptions.get(subscription.descriptor.id) === subscription,
			);
			if (!due.length) return [];

			this.pause();
			const byId = new Map(
				due.map((subscription) => [subscription.descriptor.id, subscription]),
			);
			this.inflight = request.post(ENDPOINTS.poll, {
				version: 1,
				client_id: this.clientId,
				subscriptions: due.map(({ descriptor }) => ({ ...descriptor })),
				closed_documents: [],
			});
			const response = await this.inflight;
			if (
				!response?.ok ||
				response.version !== 1 ||
				!Array.isArray(response.results)
			) {
				throw new Error("Invalid polling response");
			}
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			results = response.results;
			const received = new Set();
			const cycleJitter = 0.9 + Math.random() * 0.2;
			const scheduledAt = Date.now();
			for (const result of results) {
				const subscription = byId.get(result?.id);
				if (!subscription || this.subscriptions.get(result.id) !== subscription)
					continue;
				received.add(result.id);
				const previousDescriptor = { ...subscription.descriptor };
				try {
					this._applyProtocolState(subscription, result);
					const accepted = await subscription.onResult?.(result);
					if (accepted === false) {
						subscription.descriptor = previousDescriptor;
					}
					subscription.dueAt =
						scheduledAt +
						jitter(this._interval(subscription, result), cycleJitter);
				} catch (error) {
					subscription.descriptor = previousDescriptor;
					captureError(error, this.view.elt, {
						context: "polling-subscription",
						subscription_id: result.id,
					});
					subscription.dueAt =
						scheduledAt +
						jitter(
							this._interval(subscription, {
								status: "error",
							}),
							cycleJitter,
						);
				}
			}
			for (const [id, subscription] of byId) {
				if (received.has(id)) continue;
				const missing = {
					id,
					status: "error",
					type: subscription.descriptor.type,
				};
				subscription.dueAt =
					scheduledAt +
					jitter(this._interval(subscription, missing), cycleJitter);
			}
		} catch (error) {
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			captureError(error, this.view.elt, { context: "polling-coordinator" });
			const cycleJitter = 0.9 + Math.random() * 0.2;
			const scheduledAt = Date.now();
			for (const subscription of due) {
				subscription.dueAt =
					scheduledAt +
					jitter(
						this._interval(subscription, {
							status: "error",
						}),
						cycleJitter,
					);
				await subscription.onResult?.({
					id: subscription.descriptor.id,
					type: subscription.descriptor.type,
					status: "error",
				});
			}
		} finally {
			this.inflight = null;
			const now = Date.now();
			for (const id of this.queuedIds) {
				const subscription = this.subscriptions.get(id);
				if (subscription) subscription.dueAt = now;
			}
		}
		return results;
	}

	_schedule(delay = null) {
		if (
			this.destroyed ||
			this.timer ||
			!this.subscriptions.size ||
			this.view.hidden ||
			!this.view.online
		)
			return;
		const nextDue = Math.min(
			...Array.from(this.subscriptions.values(), ({ dueAt }) => dueAt),
		);
		const wait = delay ?? Math.max(nextDue - Date.now(), 0);
		this.timer = window.setTimeout(() => {
			this.timer = null;
			void this._poll();
		}, wait);
	}

	destroy() {
		this.destroyed = true;
		this.pause();
		this.subscriptions.clear();
		this.activeIds.clear();
		this.queuedIds.clear();
	}
}

const BROWSER_PROTOCOL_ID = BROWSER_PROTOCOL.id;
const BROWSER_PROTOCOL_VERSION = BROWSER_PROTOCOL.version;
const WORKER_MESSAGES = Object.freeze({ ...BROWSER_PROTOCOL.messages });

/**
 * @testable false
 * @covered-by src/script/shared/protocol.mjs::validateConnectivityState
 * @reason record-shape guard is exercised through connectivity validation
 */
function isRecord(value) {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_messages_are_versioned_and_validated
 * @features browser-protocol
 * @dimensions connectivity validation
 */
function validateConnectivityState(state) {
	if (!isRecord(state)) return false;
	return (
		["online", "offline"].includes(state.browser) &&
		["unknown", "online", "offline"].includes(state.server) &&
		["visible", "hidden"].includes(state.visibility) &&
		["controlled", "uncontrolled"].includes(state.controller)
	);
}

/**
 * @testable true
 * @tests tests_js/test_021_browser_protocol.py::test_browser_protocol_contains_only_connectivity_messages
 * @tests tests_js/test_021_browser_protocol.py::test_connectivity_messages_are_versioned_and_validated
 * @features browser-protocol
 * @dimensions connectivity-only connectivity producer version envelope
 */
function connectivityMessage(state) {
	if (!validateConnectivityState(state)) {
		throw new TypeError("Invalid connectivity state");
	}
	return {
		protocol: BROWSER_PROTOCOL_ID,
		protocol_version: BROWSER_PROTOCOL_VERSION,
		type: WORKER_MESSAGES.CONNECTIVITY,
		state: { ...state },
	};
}

/**
 * Coordinate Yjs document updates through the shared polling protocol.
 *
 * @testable true
 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
 * @features sync polling
 * @dimensions document collaboration offline-replay cursor-retention presence lifecycle batching
 */
class SyncManager {
	constructor(view) {
		this.view = view;
		this._initialized = false;
		this._subscriptions = new Map();
		this._cursors = new Map();
		this._checkpointRetries = new Set();
		this._checkpointPollFirst = new Set();
		this._pendingParentTouches = new Set();
		this._activating = new Set();
		this._registerPromise = null;
		this._sendPromise = null;
		this._queuedSend = null;
		this.ready = Promise.resolve(this);
		this._syncSave = () => this.sendUpdates(true);
	}

	init() {
		if (this._initialized) return this;
		this._initialized = true;
		window.addEventListener("sync-save", this._syncSave);
		this.ready = this.register();
		return this;
	}

	get widgets() {
		const entries = [];
		for (const component of Object.values(this.view.components ?? {})) {
			for (const widget of Object.values(component.widgets ?? {})) {
				if (widget.syncId) {
					entries.push([widget.syncId, widget]);
				}
			}
		}
		return Object.fromEntries(entries);
	}

	_componentVisible(component) {
		if (component?.visible !== true) return false;
		let ancestor = component.elt?.parentElement?.closest?.("[lp-component]");
		while (ancestor) {
			if (ancestor.dataset.visible === "false") return false;
			ancestor = ancestor.parentElement?.closest?.("[lp-component]");
		}
		return true;
	}

	_widgetVisible(widget) {
		return Boolean(
			widget?.component?.active === widget &&
				this._componentVisible(widget.component) &&
				widget.visible === true,
		);
	}

	_descriptor(widget) {
		const protocol =
			this.view.PollingCoordinator?.get(`document:${widget.syncId}`) ??
			this._cursors.get(widget.syncId);
		return {
			key: widget.component?.key ?? widget.key,
			sync_id: widget.syncId,
			fingerprint: widget.fingerprint,
			generation: protocol?.generation ?? null,
			revision: Number(protocol?.revision) || 0,
		};
	}

	_rememberCursor(syncId, patch = null) {
		const active = this.view.PollingCoordinator?.get(`document:${syncId}`);
		const current = this._cursors.get(syncId) ?? {};
		const source = { ...current, ...active, ...patch };
		this._cursors.set(syncId, {
			generation: source.generation ?? null,
			revision: Number(source.revision) || 0,
		});
	}

	_subscribe(widget, { force = false } = {}) {
		if (!widget?.syncId || this._subscriptions.has(widget.syncId)) return;
		if (!force && !this._widgetVisible(widget)) return;
		const id = `document:${widget.syncId}`;
		const descriptor = {
			id,
			type: "document",
			...this._descriptor(widget),
		};
		const unsubscribe = this.view.PollingCoordinator?.subscribe(descriptor, {
			beforePoll: () => {
				const current = this.widgets[widget.syncId] ?? widget;
				if (
					!this._widgetVisible(current) &&
					!this._activating.has(widget.syncId)
				)
					return;
				return this.sendUpdates(
					this._checkpointRetries.has(widget.syncId) &&
						!this._checkpointPollFirst.has(widget.syncId),
				);
			},
			onResult: async (result) => {
				const current = this.widgets[widget.syncId] ?? widget;
				if (
					!this._widgetVisible(current) &&
					!this._activating.has(widget.syncId)
				)
					return false;
				this._rememberCursor(widget.syncId);
				if (result.status !== "changed" || !result.payload) return;
				// state() consumes its forced result directly, so its cursor is
				// safe to accept while the editor's async create event is still
				// completing. Any later result must wait for the mounted widget.
				if (!current.initialized) return this._activating.has(widget.syncId);
				current.remote = result.payload;
				await current.sync();
				if (
					!current.readonly &&
					(result.payload.checkpoint_required ||
						this._checkpointRetries.has(widget.syncId))
				) {
					this._checkpointPollFirst.delete(widget.syncId);
					await this.sendUpdates(true);
				}
			},
		});
		if (unsubscribe) {
			this._subscriptions.set(widget.syncId, unsubscribe);
			this._rememberCursor(widget.syncId, descriptor);
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @tests tests_js/test_029_core_startup.py::test_collaborative_document_waits_for_sync_manager_before_state
	 * @pairs sync:editor-readiness sync:state-only sync:offline-replay polling:document
	 */
	async state(widget) {
		await this.ready;
		const offline = await getSyncRecord(widget.syncId);
		if (offline) widget.offlineRecord = offline;
		if (!this.view.online) return null;
		this._activating.add(widget.syncId);
		try {
			this._subscribe(widget, { force: true });
			const results = await this.view.PollingCoordinator?.trigger(
				`document:${widget.syncId}`,
			);
			return results?.find(
				(result) => result.id === `document:${widget.syncId}`,
			)?.payload;
		} finally {
			this._activating.delete(widget.syncId);
		}
	}

	register() {
		if (this._registerPromise) return this._registerPromise;
		const pending = this._register();
		this._registerPromise = pending;
		const complete = () => {
			if (this._registerPromise === pending) this._registerPromise = null;
		};
		void pending.then(complete, complete);
		return pending;
	}

	async _register() {
		const { sync: allOffline } = await getAllOfflineRecords();
		const offline = allOffline.filter(({ sync_id }) =>
			sync_id?.endsWith(":document"),
		);
		const obsolete = allOffline.filter(
			({ sync_id }) => !sync_id?.endsWith(":document"),
		);
		if (obsolete.length) {
			await deleteSyncRecords(obsolete.map(({ sync_id }) => sync_id));
		}
		for (const widget of Object.values(this.widgets)) this._subscribe(widget);
		if (offline.length) await this._reconcile(offline);
	}

	/**
	 * Keep document presence and its fast polling cadence scoped to the active,
	 * visible document widget.
	 *
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @features sync polling
	 * @dimensions active-widget visibility presence lifecycle
	 * @pairs sync:active-widget sync:visibility
	 * @pairs polling:active-widget polling:visibility
	 */
	async reconcileSubscriptions() {
		if (!this.view.online || this.view.hidden) return;
		const widgets = this.widgets;
		const active = new Map(
			Object.entries(widgets).filter(([, widget]) =>
				this._widgetVisible(widget),
			),
		);
		const closing = [...this._subscriptions.keys()].filter(
			(syncId) => !active.has(syncId) && !this._activating.has(syncId),
		);
		if (closing.length) {
			await this.sendUpdates(true, null, { touchSyncIds: closing });
			for (const syncId of closing) {
				this._rememberCursor(syncId);
				this._subscriptions.get(syncId)?.();
				this._subscriptions.delete(syncId);
			}
			await this.view.PollingCoordinator?.closeDocuments(closing);
		}
		for (const widget of active.values()) this._subscribe(widget);
	}

	async deregister() {
		const syncIds = [...this._subscriptions.keys()];
		await this.sendUpdates(true, null, {
			keepalive: true,
			touchSyncIds: syncIds,
		});
		for (const syncId of syncIds) this._rememberCursor(syncId);
		for (const unsubscribe of this._subscriptions.values()) unsubscribe();
		this._subscriptions.clear();
		await this.view.PollingCoordinator?.closeDocuments(syncIds);
	}

	async _waitForWidgetInitialized(widget) {
		if (widget.initialized) return;
		const target = widget.container ?? widget.target;
		if (target) await waitForAttribute(target, "initialized");
	}

	/**
	 * Fetch the authoritative state newer than an offline record's base cursor.
	 *
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
	 * @pairs sync:offline-replay sync:headless sync:merge
	 * @pairs polling:document polling:current-state polling:cursor
	 */
	async _pollOfflineState(offline) {
		const id = `replay:${offline.sync_id}`;
		const unsubscribe = this.view.PollingCoordinator?.subscribe({
			id,
			type: "document",
			key: offline.key,
			sync_id: offline.sync_id,
			fingerprint: offline.fingerprint,
			generation: offline.generation ?? null,
			revision: Number(offline.revision) || 0,
		});
		if (!unsubscribe) return null;

		try {
			const results = await this.view.PollingCoordinator.trigger(id);
			const result = results?.find((candidate) => candidate.id === id);
			if (
				!result ||
				!["changed", "unchanged"].includes(result.status) ||
				(result.status === "changed" && !result.payload)
			) {
				return null;
			}
			const descriptor = this.view.PollingCoordinator.get(id);
			if (!descriptor?.generation) return null;
			const cursor = {
				generation: descriptor.generation,
				revision: Number(descriptor.revision) || 0,
			};
			this._rememberCursor(offline.sync_id, cursor);
			return { cursor, payload: result.payload ?? null };
		} finally {
			unsubscribe();
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
	 * @pairs sync:offline-replay sync:headless sync:merge sync:queue-clear
	 */
	async _reconcile(offlineRecords) {
		const replays = [];
		const headless = [];
		try {
			for (const offline of offlineRecords) {
				if (
					offline.touch_parent &&
					!offline.update &&
					!offline.ydoc &&
					!Object.hasOwn(offline, "html")
				) {
					replays.push({
						key: offline.key,
						sync_id: offline.sync_id,
						fingerprint: offline.fingerprint,
						generation: offline.generation ?? null,
						revision: Number(offline.revision) || 0,
						save: true,
						touch_parent: true,
					});
					continue;
				}
				let widget = this.widgets[offline.sync_id];
				if (!widget) {
					widget = await loadHeadlessWidget({
						sync_id: offline.sync_id,
						offline,
					});
					if (!widget) continue;
					headless.push(widget);
					await widget.init();
					await this._waitForWidgetInitialized(widget);
				}

				const current = await this._pollOfflineState(offline);
				if (!current) continue;
				widget.remote = current.payload;
				widget.offlineRecord = offline;
				await widget.sync();

				const saveData = widget.saveData;
				if (!saveData) {
					if (offline.touch_parent) {
						replays.push({
							key: widget.component?.key ?? widget.key ?? offline.key,
							sync_id: offline.sync_id,
							fingerprint: widget.fingerprint ?? offline.fingerprint,
							...current.cursor,
							save: true,
							touch_parent: true,
						});
					} else {
						await deleteSyncRecord(offline.sync_id);
					}
					continue;
				}
				replays.push({
					key: widget.component?.key ?? widget.key ?? offline.key,
					sync_id: offline.sync_id,
					fingerprint: widget.fingerprint ?? offline.fingerprint,
					...current.cursor,
					...saveData,
					save: true,
					touch_parent: true,
				});
			}
			if (replays.length) await this.sendUpdates(false, replays);
		} finally {
			for (const widget of headless) {
				widget.destroy();
			}
			await this.view.PollingCoordinator?.closeDocuments(
				headless.map((widget) => widget.syncId),
			);
		}
	}

	_collect(save, { touchSyncIds = [] } = {}) {
		const batch = [];
		const touches = new Set(touchSyncIds);
		const included = new Set();
		for (const widget of Object.values(this.widgets)) {
			const payload = save ? widget.saveData : widget.syncData;
			if (!payload) continue;
			const update = { ...this._descriptor(widget), ...payload, save };
			if (save && touches.has(widget.syncId)) update.touch_parent = true;
			batch.push(update);
			included.add(widget.syncId);
		}
		if (save) {
			for (const syncId of touches) {
				if (
					included.has(syncId) ||
					!this._pendingParentTouches.has(syncId)
				)
					continue;
				const widget = this.widgets[syncId];
				if (!widget) continue;
				batch.push({
					...this._descriptor(widget),
					save: true,
					touch_parent: true,
				});
			}
		}
		return batch;
	}

	async _sendUpdatesNow(
		save = false,
		updates = null,
		{ keepalive = false, touchSyncIds = [] } = {},
	) {
		const batch = updates ?? this._collect(save, { touchSyncIds });
		if (!batch.length) return null;
		if (!this.view.online) {
			for (const update of batch) await updateSyncRecord(update);
			return null;
		}
		const response = await request.post(
			ENDPOINTS.sync,
			{
				client_id: this.view.PollingCoordinator?.clientId,
				updates: batch,
			},
			{ keepalive },
		);
		if (response?.ok === false) {
			for (const update of batch) {
				await updateSyncRecord(update);
				this._checkpointRetries.add(update.sync_id);
				this._checkpointPollFirst.delete(update.sync_id);
			}
			return response;
		}
		const submitted = new Map(batch.map((update) => [update.sync_id, update]));
		for (const acknowledgement of response?.updates ?? []) {
			const update = submitted.get(acknowledgement.sync_id);
			if (acknowledgement.checkpoint_accepted) {
				const cursor = {
					generation: acknowledgement.generation,
					revision: acknowledgement.revision,
				};
				this.view.PollingCoordinator?.update(
					`document:${acknowledgement.sync_id}`,
					cursor,
				);
				this._rememberCursor(acknowledgement.sync_id, cursor);
				this._checkpointRetries.delete(acknowledgement.sync_id);
				this._checkpointPollFirst.delete(acknowledgement.sync_id);
			}
			if (acknowledgement.checkpoint_persisted) {
				if (update?.save && update.ydoc) {
					const widget = this.widgets[acknowledgement.sync_id];
					if (widget) widget.snapshot = update.ydoc;
				}
				if (acknowledgement.entity_touched) {
					this._pendingParentTouches.delete(acknowledgement.sync_id);
				} else {
					this._pendingParentTouches.add(acknowledgement.sync_id);
				}
				await deleteSyncRecord(acknowledgement.sync_id);
			} else if (acknowledgement.entity_touched) {
				this._pendingParentTouches.delete(acknowledgement.sync_id);
				await deleteSyncRecord(acknowledgement.sync_id);
			} else if (update?.save) {
				this._checkpointRetries.add(acknowledgement.sync_id);
				this._checkpointPollFirst.add(acknowledgement.sync_id);
				await updateSyncRecord(update);
			}
		}
		return response;
	}

	async sendUpdates(save = false, updates = null, options = {}) {
		if (this._sendPromise) {
			if (updates) {
				await this._sendPromise;
				return this.sendUpdates(save, updates, options);
			}
			this._queuedSend = {
				save: Boolean(this._queuedSend?.save || save),
				keepalive: Boolean(this._queuedSend?.keepalive || options.keepalive),
				touchSyncIds: new Set([
					...(this._queuedSend?.touchSyncIds ?? []),
					...(options.touchSyncIds ?? []),
				]),
			};
			return this._sendPromise;
		}
		this._sendPromise = (async () => {
			let response = await this._sendUpdatesNow(save, updates, options);
			while (this._queuedSend) {
				const queued = this._queuedSend;
				this._queuedSend = null;
				response = await this._sendUpdatesNow(queued.save, null, {
					keepalive: queued.keepalive,
					touchSyncIds: queued.touchSyncIds,
				});
			}
			return response;
		})();
		try {
			return await this._sendPromise;
		} finally {
			this._sendPromise = null;
		}
	}

	destroy() {
		for (const unsubscribe of this._subscriptions.values()) unsubscribe();
		this._subscriptions.clear();
		this._cursors.clear();
		this._checkpointRetries.clear();
		this._checkpointPollFirst.clear();
		this._pendingParentTouches.clear();
		this._activating.clear();
		this._registerPromise = null;
		window.removeEventListener("sync-save", this._syncSave);
		this._initialized = false;
	}
}

/**
 * @testable false
 * @reason session timezone heartbeat has no focused frontend assertion yet
 */
async function updateUserData() {
	const currentTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
	const sentThisSession = sessionStorage.getItem("timezone_sent");
	const userHash = sessionStorage.getItem("userHash");

	if (sentThisSession === currentTimezone && userHash) return;

	sessionStorage.setItem("timezone_sent", currentTimezone);
	const response = await request.post(
		"/update-session",
		{ timezone: currentTimezone },
		{ keepalive: true },
	);
	if (response?.ok) {
		if (response.userHash)
			sessionStorage.setItem("userHash", response.userHash);
	} else {
		sessionStorage.removeItem("timezone_sent");
	}
}

/**
 * @testable false
 * @covered-by src/script/shared/user.mjs::updateUserLocation
 * @reason geolocation lookup is private location-update plumbing
 */
function _getCurrentPosition(options) {
	return new Promise((resolve) => {
		if (!("geolocation" in navigator)) {
			resolve(null);
			return;
		}
		navigator.geolocation.getCurrentPosition(
			(pos) => resolve(pos),
			() => resolve(null),
			options,
		);
	});
}

/**
 * @testable false
 * @covered-by src/script/shared/user.mjs::updateUserLocation
 * @reason session location POST is owned by the exported location updater
 */
async function _updateUserLocation(newLocation) {
	localStorage.setItem("location", JSON.stringify(newLocation));
	await request.post(
		"/update-session",
		{ location: newLocation },
		{ keepalive: true },
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/user.mjs::updateUserLocation
 * @reason distance threshold is private location-update plumbing
 */
function _approxDistanceKm(a, b) {
	// Equirectangular approximation; good enough for metro-area checks
	/**
	 * @testable false
	 * @covered-by src/script/shared/user.mjs::_approxDistanceKm
	 * @reason radians conversion is private distance math
	 */
	const toRad = (deg) => (deg * Math.PI) / 180;
	const R = 6371;
	const phi1 = toRad(a.latitude);
	const phi2 = toRad(b.latitude);
	const dPhi = toRad(b.latitude - a.latitude);
	const dLambda = toRad(b.longitude - a.longitude);
	const x = dLambda * Math.cos((phi1 + phi2) / 2);
	const y = dPhi;
	return Math.sqrt(x * x + y * y) * R;
}

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_user_location_updates_only_for_initial_or_distant_positions
 * @pairs location:geolocation location:distance-threshold location:session-update
 */
async function updateUserLocation() {
	const METRO_RADIUS_KM = 50; // rough same-metro threshold

	const cachedLocation = localStorage.getItem("location");
	const oldLocation = cachedLocation ? JSON.parse(cachedLocation) : null;

	const position = await _getCurrentPosition({
		enableHighAccuracy: false,
		maximumAge: 3600000, // up to 1 hour old
		timeout: 8000,
	});
	if (!position) return;

	const newLocation = {
		latitude: position.coords.latitude,
		longitude: position.coords.longitude,
	};

	if (!oldLocation) {
		await _updateUserLocation(newLocation);
		return;
	}

	const distance = _approxDistanceKm(oldLocation, newLocation);

	if (distance > METRO_RADIUS_KM) {
		await _updateUserLocation(newLocation);
	}
}

export { simpleHash as A, updateUserLocation as B, DeleteModal as D, ENDPOINTS as E, HelpModal as H, Modal as M, OfflineModal as O, PollingCoordinator as P, STYLES as S, captureError as a, initializeLogoutForms as b, connectivity as c, analytics as d, captureNetworkError as e, clearRecentSearchResults as f, connectivityMessage as g, generateElementId as h, isSkippedViewTransitionError as i, createIcon as j, debounce as k, loadWidget as l, showBriefly as m, DeferredOperationManager as n, EditWatcher as o, OfflineQueue as p, SyncManager as q, request as r, setIcon as s, waitForAttribute as t, updateUserData as u, uint8ArrayToBase64 as v, withTransition as w, base64ToUint8Array as x, iconDefinition as y, areEqual as z };
