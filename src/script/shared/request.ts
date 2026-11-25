import type { EntityRevision, RequestResult } from "../types/api.d.ts";
import { captureNetworkError } from "./errors.ts";
import { applyNotificationStateHeader } from "./notificationState.ts";
import { handleUpstreamResponse } from "./upstreamUnavailable.ts";

const PARSER = new DOMParser();
const TOKEN_REQUEST: RequestInit = {
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
type ResponseJson = Omit<Partial<RequestResult>, "html" | "modal"> & {
	html?: string | null;
	modal?: string;
};
type RequestUrl = string | URL;
type RequestBody = object | string | number | boolean | null;
type QueryParams =
	| string
	| URLSearchParams
	| FormData
	| string[][]
	| Record<string, string | number | boolean>;
type RequestOptions = {
	keepalive?: boolean;
	requestHeaders?: Record<string, string>;
	acknowledgeEntities?: boolean;
	replaceErrorPage?: boolean;
	signal?: AbortSignal;
	retryUpstream?: boolean;
};
type PostOptions = Pick<
	RequestOptions,
	"keepalive" | "signal" | "replaceErrorPage"
> & { headers?: Record<string, string> };

let _tokenRefresh: Promise<string | null> | null = null;

const csrfFailed = (response: Pick<Response, "status" | "headers">) =>
	response.status === 400 &&
	response.headers.get(CSRF_FAILURE_HEADER)?.toLowerCase() === "invalid";

const _tokenInput = () => document.querySelector<HTMLInputElement>("#token");

const _parseHtml = (html: string | null) =>
	html === "" || html === null
		? html
		: PARSER.parseFromString(html, "text/html");

const _isEntityRevision = (revision: unknown): revision is EntityRevision =>
	Boolean(
		revision &&
			typeof revision === "object" &&
			"key" in revision &&
			"fingerprint" in revision &&
			typeof revision.key === "string" &&
			revision.key &&
			typeof revision.fingerprint === "string" &&
			revision.fingerprint &&
			(!("modified" in revision) ||
				revision.modified === null ||
				typeof revision.modified === "string"),
	);

const _formatResponse = async (
	response: Response,
	{ acknowledgeEntities = true } = {},
): Promise<RequestResult> => {
	applyNotificationStateHeader(response.headers);
	if (response.status === 304) {
		return {
			ok: true,
			unchanged: true,
			etag: response.headers.get("ETag"),
		};
	}
	const contentType = response.headers.get("content-type");
	const json: ResponseJson | null = contentType?.includes("application/json")
		? await response.json()
		: { html: (await response.text()) || "" };
	const { html, modal, ...data } = json ?? {};
	const revisions = new Map<string, EntityRevision>();
	const revisionHeader = response.headers.get(ENTITY_REVISIONS_HEADER);
	if (revisionHeader) {
		try {
			const parsed: unknown = JSON.parse(revisionHeader);
			if (Array.isArray(parsed)) {
				for (const revision of parsed) {
					if (_isEntityRevision(revision))
						revisions.set(revision.key, revision);
				}
			}
		} catch {
			// Ignore a malformed optional acknowledgement header.
		}
	}
	const entities = Array.from(revisions.values());
	if (acknowledgeEntities) {
		for (const entity of entities) {
			window.dispatchEvent(
				new CustomEvent("entity-updated", { detail: entity }),
			);
		}
	}
	return {
		ok: response.ok,
		...data,
		updated: response.headers.get(UPDATED_HEADER) !== "false",
		etag: response.headers.get("ETag"),
		pollChannel: response.headers.get(POLL_CHANNEL_HEADER),
		pollRevision: response.headers.get(POLL_REVISION_HEADER),
		reload:
			Boolean(data.reload) || response.headers.has(INVALIDATE_CACHE_HEADER),
		entities,
		...(html !== undefined ? { html: _parseHtml(html) } : {}),
		...(modal !== undefined
			? {
					modal:
						modal && !html ? PARSER.parseFromString(modal, "text/html") : modal,
				}
			: {}),
	};
};

const _isUploadBody = (body: RequestBody) => {
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

const _friendlyError = (message: string, body: RequestBody) => {
	if (
		_isUploadBody(body) &&
		UPSTREAM_RESET_PATTERN.test(String(message || ""))
	) {
		return UPSTREAM_UPLOAD_OVERLOAD_ERROR;
	}
	return message;
};

const _formatError = async (
	response: Response,
	{
		replaceErrorPage = true,
		body = null,
	}: {
		replaceErrorPage?: boolean;
		body?: RequestBody;
	} = {},
): Promise<RequestResult> => {
	const contentType = response.headers.get("content-type");
	if (contentType?.includes("application/json")) {
		const text = await response.text();
		try {
			const parsed: ResponseJson | null = JSON.parse(text);
			if (parsed === null) {
				return { ok: false, error: _friendlyError(text, body) };
			}
			const { html, ...data } = parsed;
			if (data.error) {
				data.error = _friendlyError(data.error, body);
			}
			// Conflict responses carry the same replacement HTML as successful
			// form responses, even though their HTTP status is not successful.
			return {
				ok: false,
				...data,
				...(html !== undefined ? { html: _parseHtml(html) } : {}),
			};
		} catch {
			return { ok: false, error: _friendlyError(text, body) };
		}
	}

	const text = await response.text();
	const title = response.headers.get("X-Lagniappe-Error");
	const fallback =
		text.trim() || title || response.statusText || "Network request failed";
	const error = _friendlyError(fallback, body);

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
			error: _friendlyError(title || response.statusText || fallback, body),
		};
	}

	if (!title) {
		document.documentElement.innerHTML = text;
		document.title = response.statusText;
	} else {
		const main = document.querySelector("main");
		if (main) main.innerHTML = text;
		document.title = title;
	}

	return {
		ok: false,
		error: _friendlyError(title || response.statusText || fallback, body),
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
		const tokenElt = _tokenInput();
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

const postRequest = async <T extends object = Record<never, never>>(
	url: RequestUrl,
	body?: RequestBody,
	{
		keepalive = false,
		headers = {},
		signal = undefined,
		replaceErrorPage = true,
	}: PostOptions = {},
) => {
	return _request<T>(url, {
		method: "POST",
		body,
		keepalive,
		requestHeaders: headers,
		signal,
		replaceErrorPage,
	});
};

const patchRequest = async <T extends object = Record<never, never>>(
	url: RequestUrl,
	body?: RequestBody,
) => _request<T>(url, { method: "PATCH", body });

const deleteRequest = async <T extends object = Record<never, never>>(
	url: RequestUrl,
	body?: RequestBody,
) => _request<T>(url, { method: "DELETE", body });

const getRequest = async <T extends object = Record<never, never>>(
	url: RequestUrl,
	params: QueryParams | null = null,
	options: RequestOptions = {},
) => {
	if (params) {
		let query: URLSearchParams;
		if (
			typeof params === "string" ||
			params instanceof URLSearchParams ||
			Array.isArray(params)
		) {
			query = new URLSearchParams(params);
		} else {
			const entries: Iterable<[string, unknown]> =
				params instanceof FormData ? params.entries() : Object.entries(params);
			query = new URLSearchParams(
				Array.from(entries, ([key, value]) => [key, String(value)]),
			);
		}
		url = `${url}?${query}`;
	}
	return _request<T>(url, { method: "GET", ...options });
};

const putRequest = async <T extends object = Record<never, never>>(
	url: RequestUrl,
	body?: RequestBody,
	options: RequestOptions = {},
) => _request<T>(url, { method: "PUT", body, ...options });

type TransportOptions = RequestOptions & {
	method?: string;
	body?: RequestBody;
};

const _request = <T extends object>(
	url: RequestUrl,
	options: TransportOptions,
): Promise<RequestResult<T> | undefined> =>
	// Route-specific fields are supplied by the caller's endpoint contract.
	_requestResponse(url, options) as Promise<RequestResult<T> | undefined>;

const _requestResponse = async (
	url: RequestUrl,
	{
		method = "POST",
		body = null,
		keepalive = false,
		requestHeaders = {},
		acknowledgeEntities = true,
		replaceErrorPage = true,
		signal = undefined,
		retryUpstream = true,
	}: TransportOptions,
): Promise<RequestResult | undefined> => {
	method = method.toUpperCase();
	const token = _tokenInput()?.value;
	const headers: Record<string, string> = {
		"Content-Type": "application/json",
		"X-CSRFToken": String(token),
		"X-Lagniappe-Request": "true",
		...requestHeaders,
	};

	const config: RequestInit = {
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
	const classifyUpstream = (response: Response, allowRetry = retryUpstream) =>
		handleUpstreamResponse(response, {
			method,
			url,
			retryUpstream: allowRetry,
			fetchResponse: () => fetch(url, config),
			retryCurrent: () =>
				_requestResponse(window.location.pathname, {
					method: "GET",
					replaceErrorPage: false,
					retryUpstream: false,
				}),
			retryOriginal: () =>
				_requestResponse(url, {
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
		if ("result" in upstream) return upstream.result;
		response = upstream.response;

		if (CSRF_METHODS.has(method) && csrfFailed(response)) {
			const newToken = await refreshToken();
			if (!newToken) {
				return {
					ok: false,
					error: "Failed to refresh authentication token",
				};
			}
			headers["X-CSRFToken"] = newToken;
			response = await fetch(url, config);
			upstream = await classifyUpstream(response, false);
			if ("result" in upstream) return upstream.result;
			response = upstream.response;
		}

		if (response.status === 422) {
			return {
				...(await _formatError(response, { body, replaceErrorPage: false })),
				status: response.status,
			};
		}

		if (response.redirected) {
			window.location.href = response.url;
			return;
		}

		return response.ok || response.status === 304
			? _formatResponse(response, { acknowledgeEntities })
			: _formatError(response, { body, replaceErrorPage });
	} catch (error) {
		captureNetworkError(error, url, { method, body, ...config });
		return {
			ok: false,
			error:
				error &&
				typeof error === "object" &&
				"message" in error &&
				typeof error.message === "string" &&
				error.message
					? error.message
					: "Network request failed",
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
