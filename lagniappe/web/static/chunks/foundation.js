/*! Third-party licenses: /third-party-licenses.txt */
import { a as applyNotificationStateHeader } from './notificationState.js?v=bed962f9';
import { c as connectivity } from './connectivity.js?v=bed962f9';

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

var errors = /*#__PURE__*/Object.freeze({
	__proto__: null,
	captureError: captureError,
	captureNetworkError: captureNetworkError,
	isSkippedViewTransitionError: isSkippedViewTransitionError,
	isTransientNetworkError: isTransientNetworkError
});

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

var utilities = /*#__PURE__*/Object.freeze({
	__proto__: null,
	areEqual: areEqual,
	base64ToUint8Array: base64ToUint8Array,
	clearRecentSearchResults: clearRecentSearchResults,
	debounce: debounce,
	generateElementId: generateElementId,
	showBriefly: showBriefly,
	simpleHash: simpleHash,
	uint8ArrayToBase64: uint8ArrayToBase64,
	waitForAttribute: waitForAttribute,
	withTransition: withTransition
});

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
	SiteAiModels: () => {
		return {
			setAiSettings: "/set-ai-settings",
		};
	},
	SiteDeployment: () => {
		return {
			setDeploymentSettings: "/set-deployment-settings",
		};
	},
	SiteImage: () => {
		return {
			setSiteImage: "/set-site-image",
		};
	},
	SiteMaintenance: () => {
		return {
			siteConfiguration: "/site-configuration",
			siteUpdate: "/site-update",
			rebuildCache: "/rebuild-cache",
		};
	},
	SiteSettings: () => {
		return {
			siteSettings: "/site-settings",
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

const PARSER = new DOMParser();
const TOKEN_REQUEST = {
	credentials: "include",
	headers: { "X-Lagniappe-Request": "true" },
};
const UPDATED_HEADER = "X-Lagniappe-Updated";
const INVALIDATE_CACHE_HEADER = "X-Lagniappe-Invalidate-Cache";
const ENTITY_REVISIONS_HEADER = "X-Lagniappe-Entity-Revisions";
const CSRF_FAILURE_HEADER = "X-Lagniappe-CSRF";
const POLL_CHANNEL_HEADER = "X-Lagniappe-Poll-Channel";
const POLL_REVISION_HEADER = "X-Lagniappe-Poll-Revision";
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
	applyNotificationStateHeader(response.headers);
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
	result.pollChannel = response.headers.get(POLL_CHANNEL_HEADER);
	result.pollRevision = response.headers.get(POLL_REVISION_HEADER);
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

const MOBILE_QUERY = "(max-width: 640px)";

/**
 * @testable false
 * @covered-by src/script/views/base/shell.mjs::ShellView
 */
const markPerformance = (name) => {
	if (typeof performance === "undefined" || !performance.mark) return;
	if (performance.getEntriesByName?.(name, "mark")?.length) return;
	performance.mark(name);
};

const whenIdle = () =>
	new Promise((resolve) => {
		if (typeof globalThis.requestIdleCallback === "function") {
			globalThis.requestIdleCallback(resolve, { timeout: 1000 });
			return;
		}
		setTimeout(resolve, 0);
	});

/**
 * Lightweight page shell. It owns only interaction interception, viewport
 * publication, pointer tracking, and the final ready markers shared by every
 * view. Feature managers belong to Core's deferred service layer.
 *
 * @testable infrastructure
 */
class ShellView {
	constructor(node) {
		this.elt = node;
		this.kind = node.dataset.kind;
		this.hash = node.dataset.hash || node.dataset.index;
		this.key = node.dataset.key;
		this.readonly = node.dataset.readonly === "true";
		this.mobile = window.matchMedia(MOBILE_QUERY).matches;
		this.online = connectivity.online;
		this.hidden = connectivity.hidden;
		this.components = {};
		this.SearchBox = null;
		this.Notifications = null;
		this.PollingCoordinator = null;

		this._destroyed = false;
		this._interactive = false;
		this._published = false;
		this.hasDeferredServices = false;
		this._coldActions = new Map();
		this._pointer = null;
		this.isDragging = false;

		this._handleClick = this._handleClick.bind(this);
		this._handleSubmit = this._handleSubmit.bind(this);
		this._pointerDown = this._pointerDown.bind(this);
		this._pointerMove = this._pointerMove.bind(this);
		this._pointerUp = this._pointerUp.bind(this);
		this._mobileChanged = this._mobileChanged.bind(this);

		this._publishedReady = new Promise((resolve) => {
			this._resolvePublished = resolve;
		});
		this.servicesReady = Promise.resolve(this);
	}

	async init() {
		if (this._interactive) return this;
		this._interactive = true;
		this.elt.addEventListener("click", this._handleClick);
		this.elt.addEventListener("submit", this._handleSubmit);
		this.elt.addEventListener("pointerdown", this._pointerDown);

		this._mobileQuery = window.matchMedia(MOBILE_QUERY);
		this._mobileQuery.addEventListener("change", this._mobileChanged);
		const mode = document
			.querySelector("meta[name='mode']")
			?.getAttribute("content");
		if (mode !== "public") this._installColdControlListeners?.();

		this.elt.dataset.interactive = "true";
		markPerformance("lagniappe:interaction-ready");
		if (!this.hasDeferredServices && mode !== "public") {
			this.hasDeferredServices = true;
			this._ownsShellServices = true;
			this._initializeShellServices();
		}
		return this;
	}

	_loadShellManager(promiseKey, handleKey, loader) {
		if (this[handleKey]) return Promise.resolve(this[handleKey]);
		if (this[promiseKey]) return this[promiseKey];
		const pending = Promise.resolve()
			.then(loader)
			.then((manager) => {
				if (this._destroyed) {
					manager?.destroy?.();
					return null;
				}
				if (manager) this[handleKey] = manager;
				return manager || null;
			})
			.catch((error) => {
				if (this[promiseKey] === pending) this[promiseKey] = null;
				throw error;
			});
		this[promiseKey] = pending;
		return pending;
	}

	ensurePollingCoordinator() {
		return this._loadShellManager(
			"_pollingPromise",
			"PollingCoordinator",
			async () => {
				const { PollingCoordinator } = await import('./polling.js?v=bed962f9');
				return this._destroyed ? null : new PollingCoordinator(this).init();
			},
		);
	}

	ensureSearchBox() {
		return this._loadShellManager("_searchPromise", "SearchBox", async () => {
			const search = document.querySelector("[lp-search]");
			if (!search) return null;
			const { SearchBox } = await import('./search.js?v=bed962f9');
			if (this._destroyed) return null;
			const box = new SearchBox(search);
			await box.init();
			return box;
		});
	}

	ensureNotifications() {
		return this._loadShellManager(
			"_notificationsPromise",
			"Notifications",
			async () => {
				if (!document.querySelector("[data-role='notifications']")) return null;
				await this.ensurePollingCoordinator();
				const { Notifications } = await import('./notifications.js?v=bed962f9');
				if (this._destroyed) return null;
				const notifications = new Notifications(this);
				notifications.init();
				return notifications;
			},
		);
	}

	_initializeShellServices() {
		this.servicesReady = this._publishedReady
			.then(() => whenIdle())
			.then(async () => {
				const warmers = [];
				if (document.querySelector("[lp-search]")) {
					warmers.push(this.ensureSearchBox());
				}
				if (document.querySelector("[data-role='notifications']")) {
					warmers.push(this.ensureNotifications());
				}
				const results = await Promise.allSettled(warmers);
				for (const result of results) {
					if (result.status === "rejected") {
						this.reportStartupError(
							result.reason,
							this.elt,
							"shell-service-startup",
						);
					}
				}
				return results;
			})
			.catch((error) => {
				this.reportStartupError(error, this.elt, "shell-service-startup");
				return [];
			})
			.then(async (result) => {
				await this._publishedReady;
				if (!this._destroyed) markPerformance("lagniappe:services-ready");
				return result;
			});
	}

	reportStartupError(error, element = this.elt, context = "lazy-control") {
		void Promise.resolve().then(function () { return errors; })
			.then(({ captureError }) => {
				captureError(error, element, { context });
			})
			.catch(() => {});
	}

	_installColdControlListeners() {
		this._shellColdControl = (event) => {
			const search = event.target?.closest?.("[lp-search]");
			if (search && !this.SearchBox) {
				this.runColdAction(
					search,
					() => this.ensureSearchBox(),
					(box) => this._activateSearchBox(box),
					search,
				);
				return;
			}
			const notifications = event.target?.closest?.(
				"[data-role='notifications']",
			);
			if (!notifications || this.Notifications) return;
			if (event.type === "click") {
				event.preventDefault();
				event.stopImmediatePropagation?.();
			}
			this.runColdAction(
				notifications,
				() => this.ensureNotifications(),
				(manager) => manager?.dropdown?.showPanel?.(),
				notifications,
			);
		};
		for (const type of ["input", "click"]) {
			document.addEventListener(type, this._shellColdControl, true);
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_lazy_search_replays_the_latest_live_input_after_loading
	 * @features search startup
	 * @dimensions navbar-results first-interaction single-flight
	 * @pairs search:navbar-results startup:first-interaction startup:single-flight
	 */
	_activateSearchBox(box) {
		if (!box) return;
		const input = box.element;
		if (input?.value?.trim()) box._input({ target: input });
		else box.showPanel?.();
	}

	_removeColdControlListeners() {
		if (!this._shellColdControl) return;
		for (const type of ["input", "click"]) {
			document.removeEventListener(type, this._shellColdControl, true);
		}
		this._shellColdControl = null;
	}

	async sync({ hidden = document.hidden } = {}) {
		this.hidden = hidden;
		this.online = connectivity.online;
		if (hidden || !this.online) this.PollingCoordinator?.pause();
		else await this.PollingCoordinator?.resume();
	}

	publish() {
		if (this._destroyed || this._published) return this;
		this._published = true;
		this.elt.setAttribute("initialized", "");
		this.elt._lp_view = this;
		markPerformance("lagniappe:view-ready");
		this._resolvePublished?.(this);
		if (!this.hasDeferredServices) {
			queueMicrotask(() => {
				if (!this._destroyed) markPerformance("lagniappe:services-ready");
			});
		}
		return this;
	}

	_mobileChanged(event) {
		this.mobile = event.matches;
		this.elt.dispatchEvent(new CustomEvent("mobile-resize"));
	}

	_pointerDown(event) {
		if (event.button !== undefined && event.button !== 0) return;
		this.isDragging = false;
		this._pointer = {
			id: event.pointerId,
			x: event.clientX,
			y: event.clientY,
		};
		window.addEventListener("pointermove", this._pointerMove);
		window.addEventListener("pointerup", this._pointerUp);
		window.addEventListener("pointercancel", this._pointerUp);
	}

	_pointerMove(event) {
		if (!this._pointer) return;
		if (
			this._pointer.id !== undefined &&
			event.pointerId !== undefined &&
			event.pointerId !== this._pointer.id
		)
			return;
		const deltaX = Math.abs(event.clientX - this._pointer.x);
		const deltaY = Math.abs(event.clientY - this._pointer.y);
		if (deltaX > 5 || deltaY > 5) this.isDragging = true;
	}

	_pointerUp() {
		this._pointer = null;
		window.removeEventListener("pointermove", this._pointerMove);
		window.removeEventListener("pointerup", this._pointerUp);
		window.removeEventListener("pointercancel", this._pointerUp);
	}

	_handleClick(event) {
		if (this.isDragging) {
			this.isDragging = false;
			return;
		}
		this._click(event);
	}

	_click() {}

	_handleSubmit(event) {
		if (!this.ensureSubmissionManager || event.defaultPrevented) return;
		const form = event.target;
		if (!form?.closest?.("[lp-component]")) return;

		event.preventDefault();
		event.stopPropagation();
		const submitter = event.submitter;
		if (submitter) submitter.disabled = true;
		let handedOff = false;
		this.runColdAction(
			form,
			() => this.ensureSubmissionManager(),
			(manager) => {
				if (this._destroyed || !form.isConnected || !manager) return;
				handedOff = true;
				return manager.submit(event);
			},
			submitter,
		).finally(() => {
			if (submitter && !handedOff) submitter.disabled = false;
		});
	}

	runColdAction(owner, load, activate, busyOwner = owner) {
		if (!owner || this._destroyed) return Promise.resolve(null);
		if (this._coldActions.has(owner)) return this._coldActions.get(owner);

		busyOwner?.setAttribute?.("aria-busy", "true");
		if (busyOwner?.dataset) busyOwner.dataset.loading = "true";
		const pending = Promise.resolve()
			.then(load)
			.then((value) => {
				if (this._destroyed) return null;
				return activate(value);
			})
			.catch((error) => {
				this.reportStartupError?.(error, owner);
				return null;
			})
			.finally(() => {
				busyOwner?.removeAttribute?.("aria-busy");
				if (busyOwner?.dataset) delete busyOwner.dataset.loading;
				if (this._coldActions.get(owner) === pending) {
					this._coldActions.delete(owner);
				}
			});
		this._coldActions.set(owner, pending);
		return pending;
	}

	destroy() {
		this._destroyed = true;
		this._pointerUp();
		this.elt.removeEventListener("click", this._handleClick);
		this.elt.removeEventListener("submit", this._handleSubmit);
		this.elt.removeEventListener("pointerdown", this._pointerDown);
		this._mobileQuery?.removeEventListener("change", this._mobileChanged);
		this._removeColdControlListeners?.();
		this._coldActions.clear();
		if (this._ownsShellServices) {
			this.Notifications?.destroy?.();
			this.PollingCoordinator?.destroy?.();
			this.SearchBox?.destroy?.();
		}
		if (this.elt._lp_view === this) delete this.elt._lp_view;
	}
}

export { ENDPOINTS as E, ShellView as S, captureError as a, whenIdle as b, clearRecentSearchResults as c, debounce as d, waitForAttribute as e, base64ToUint8Array as f, generateElementId as g, areEqual as h, simpleHash as i, errors as j, utilities as k, markPerformance as m, request as r, showBriefly as s, uint8ArrayToBase64 as u, withTransition as w };
