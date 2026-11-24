import { captureNetworkError } from "./errors.ts";
import { applyNotificationStateHeader } from "./notificationState.ts";
import { handleUpstreamResponse } from "./upstreamUnavailable.ts";

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

const csrfFailed = (response) =>
	response.status === 400 &&
	response.headers.get(CSRF_FAILURE_HEADER)?.toLowerCase() === "invalid";

const _getToken = () => document.getElementById("token")?.value;

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

const _friendlyError = (message, { body = null } = {}) => {
	if (_isUploadBody(body) && UPSTREAM_RESET_PATTERN.test(message || "")) {
		return UPSTREAM_UPLOAD_OVERLOAD_ERROR;
	}
	return message;
};

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
			// Conflict responses carry the same replacement HTML as successful
			// form responses, even though their HTTP status is not successful.
			if (typeof data.html === "string" && data.html) {
				data.html = PARSER.parseFromString(data.html, "text/html");
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

const _refreshToken = async () => {
	try {
		const response = await fetch("/l/token", TOKEN_REQUEST);
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
		captureNetworkError(error, "/l/token", {
			context: "token_refresh_utility",
		});
		return null;
	}
};

const refreshToken = async () => {
	if (!_tokenRefresh) {
		_tokenRefresh = _refreshToken().finally(() => {
			_tokenRefresh = null;
		});
	}
	return _tokenRefresh;
};

const postRequest = async (
	url,
	body,
	{ keepalive = false, headers = {}, signal = undefined } = {},
) => {
	return _request(url, {
		method: "POST",
		body,
		keepalive,
		requestHeaders: headers,
		signal,
	});
};

const patchRequest = async (url, body) => {
	return _request(url, { method: "PATCH", body });
};

const deleteRequest = async (url, body) => {
	return _request(url, { method: "DELETE", body });
};

const getRequest = async (url, params = null, options = {}) => {
	url = params ? `${url}?${new URLSearchParams(params).toString()}` : url;
	return _request(url, { method: "GET", ...options });
};

const putRequest = async (url, body, options = {}) => {
	return _request(url, { method: "PUT", body, ...options });
};

const _request = async (
	url,
	{
		method = "POST",
		body = null,
		keepalive = false,
		requestHeaders = {},
		acknowledgeEntities = true,
		replaceErrorPage = true,
		signal = undefined,
		retryUpstream = true,
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
		...(signal ? { signal } : {}),
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
	const classifyUpstream = (response, allowRetry = retryUpstream) =>
		handleUpstreamResponse(response, {
			method,
			url,
			retryUpstream: allowRetry,
			fetchResponse: () => fetch(url, config),
			retryCurrent: () =>
				_request(window.location.pathname, {
					method: "GET",
					replaceErrorPage: false,
					retryUpstream: false,
				}),
			retryOriginal: () =>
				_request(url, {
					method: "GET",
					requestHeaders,
					acknowledgeEntities: false,
					replaceErrorPage: false,
					retryUpstream: false,
				}),
		});

	try {
		let response = await fetch(url, config);
		let upstream = await classifyUpstream(response);
		if (upstream.result) return upstream.result;
		response = upstream.response;

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
			upstream = await classifyUpstream(response, false);
			if (upstream.result) return upstream.result;
			response = upstream.response;
		}

		if (response.status === 422) {
			return {
				...(await _formatError(response, {
					body,
					method,
					url,
					replaceErrorPage: false,
				})),
				status: response.status,
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
		captureNetworkError(error, url, { method, body, ...config });
		return {
			ok: false,
			error: error.message || "Network request failed",
		};
	}
};

export const request = {
	csrfFailed,
	token: refreshToken,
	put: putRequest,
	post: postRequest,
	patch: patchRequest,
	delete: deleteRequest,
	get: getRequest,
};
