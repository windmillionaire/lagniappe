/*! Third-party licenses: /third-party-licenses.txt */
import { captureNetworkError } from './errors.js?v=b55964c3';

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

export { request as r };
