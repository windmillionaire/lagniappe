// biome-ignore lint/correctness/noUnusedVariables: build input replaced with the release build ID
const SW_VERSION = "b2fe2a09";
const CACHE = `static-cache`;
const RESPONSE_CACHE = `response-cache`;
const PRECACHE_URLS = [
	"/chunks/account.js?v=b2fe2a09",
	"/chunks/admin-tools.js?v=b2fe2a09",
	"/chunks/analytics.js?v=b2fe2a09",
	"/chunks/baseList.js?v=b2fe2a09",
	"/chunks/baseTable.js?v=b2fe2a09",
	"/chunks/builder-controls.js?v=b2fe2a09",
	"/chunks/builder.js?v=b2fe2a09",
	"/chunks/category.js?v=b2fe2a09",
	"/chunks/combobox.js?v=b2fe2a09",
	"/chunks/connectivity.js?v=b2fe2a09",
	"/chunks/core-foundation.js?v=b2fe2a09",
	"/chunks/deferredOperations.js?v=b2fe2a09",
	"/chunks/directUpload.js?v=b2fe2a09",
	"/chunks/document.js?v=b2fe2a09",
	"/chunks/documentHistory.js?v=b2fe2a09",
	"/chunks/editor-dialogs.js?v=b2fe2a09",
	"/chunks/editor.js?v=b2fe2a09",
	"/chunks/entity-foundation.js?v=b2fe2a09",
	"/chunks/fileInfo.js?v=b2fe2a09",
	"/chunks/filePdfPreview.js?v=b2fe2a09",
	"/chunks/filters.js?v=b2fe2a09",
	"/chunks/form-complex.js?v=b2fe2a09",
	"/chunks/form-sections.js?v=b2fe2a09",
	"/chunks/forms.js?v=b2fe2a09",
	"/chunks/foundation.js?v=b2fe2a09",
	"/chunks/home-tools.js?v=b2fe2a09",
	"/chunks/html.js?v=b2fe2a09",
	"/chunks/index-foundation.js?v=b2fe2a09",
	"/chunks/index-tools.js?v=b2fe2a09",
	"/chunks/ingress.js?v=b2fe2a09",
	"/chunks/location.js?v=b2fe2a09",
	"/chunks/messageComposer.js?v=b2fe2a09",
	"/chunks/modal.js?v=b2fe2a09",
	"/chunks/notifications.js?v=b2fe2a09",
	"/chunks/offline-replay.js?v=b2fe2a09",
	"/chunks/offline.js?v=b2fe2a09",
	"/chunks/offlineWork.js?v=b2fe2a09",
	"/chunks/page-tools.js?v=b2fe2a09",
	"/chunks/permissions.js?v=b2fe2a09",
	"/chunks/polling.js?v=b2fe2a09",
	"/chunks/project-tools.js?v=b2fe2a09",
	"/chunks/submission.js?v=b2fe2a09",
	"/chunks/sync.js?v=b2fe2a09",
	"/chunks/task-tools.js?v=b2fe2a09",
	"/chunks/ui-controls.js?v=b2fe2a09",
	"/chunks/ui-resources.js?v=b2fe2a09",
	"/chunks/uploads.js?v=b2fe2a09",
	"/chunks/upstreamUnavailable.js?v=b2fe2a09",
	"/chunks/user-tools.js?v=b2fe2a09",
	"/chunks/userSettings.js?v=b2fe2a09",
	"/chunks/views/admin.js?v=b2fe2a09",
	"/chunks/views/analytics.js?v=b2fe2a09",
	"/chunks/views/builder.js?v=b2fe2a09",
	"/chunks/views/file.js?v=b2fe2a09",
	"/chunks/views/help.js?v=b2fe2a09",
	"/chunks/views/home.js?v=b2fe2a09",
	"/chunks/views/index.js?v=b2fe2a09",
	"/chunks/views/manual.js?v=b2fe2a09",
	"/chunks/views/messages.js?v=b2fe2a09",
	"/chunks/views/page.js?v=b2fe2a09",
	"/chunks/views/project.js?v=b2fe2a09",
	"/chunks/views/public.js?v=b2fe2a09",
	"/chunks/views/report.js?v=b2fe2a09",
	"/chunks/views/results.js?v=b2fe2a09",
	"/chunks/views/user.js?v=b2fe2a09",
	"/chunks/watcher.js?v=b2fe2a09"
];
const UPDATED_HEADER = "X-Lagniappe-Updated";
const UPSTREAM_UNAVAILABLE_HEADER = "X-Lagniappe-Upstream-Unavailable";
const UPSTREAM_STATUS_HEADER = "X-Lagniappe-Upstream-Status";
const STALE_CACHE_HEADER = "X-Lagniappe-Stale-Cache";
const UPSTREAM_STATUSES = new Set([500, 502, 503, 504]);
const STATIC_RETRY_DELAYS_MS = [250, 750];
const BROWSER_PROTOCOL = {
	"id": "lagniappe-browser",
	"version": 4,
	"messages": {
		"CONNECTIVITY": "connectivity-state",
		"UPSTREAM_UNAVAILABLE": "upstream-unavailable"
	},
	"events": {},
	"connectivity": {
		"browser": [
			"online",
			"offline"
		],
		"server": [
			"unknown",
			"online",
			"offline"
		],
		"visibility": [
			"visible",
			"hidden"
		],
		"controller": [
			"controlled",
			"uncontrolled"
		]
	}
};
const TOKEN_REQUEST = {
	credentials: "include",
	headers: { "X-Lagniappe-Request": "true" },
};

function captureError(error, context = {}) {
	if (typeof self.Sentry !== "undefined" && self.Sentry) {
		if (error instanceof Error) {
			self.Sentry.captureException(error, context);
		} else {
			self.Sentry.captureMessage(error, context);
		}
	}
}

async function updateCaches() {
	await Promise.all([caches.delete(CACHE), caches.delete(RESPONSE_CACHE)]);

	const cache = await caches.open(CACHE);
	await cache.add("/offline");
}

async function precacheStaticAssets() {
	const cache = await caches.open(CACHE);
	await Promise.allSettled(
		PRECACHE_URLS.map(async (url) => {
			// Build-versioned URLs can reuse fresh HTTP-cached responses, including
			// modules fetched by HTML preloads before this worker took control.
			const request = new Request(new URL(url, self.location.origin).href);
			const cached = await cache.match(request, { ignoreVary: true });
			if (cached && !responsePreventsStorage(cached)) return;
			const response = await fetchStaticAsset(request);
			if (response.ok && !responsePreventsStorage(response)) {
				await cache.put(request, response.clone());
			}
		}),
	);
}

async function fetchStaticAsset(request) {
	let currentRequest = request;
	for (let attempt = 0; ; attempt += 1) {
		let response;
		try {
			response = await fetch(currentRequest);
		} catch (error) {
			if (
				request.method !== "GET" ||
				request.signal.aborted ||
				error?.name === "AbortError" ||
				attempt === STATIC_RETRY_DELAYS_MS.length
			) {
				throw error;
			}
		}
		if (
			response &&
			(request.method !== "GET" ||
				request.signal.aborted ||
				!UPSTREAM_STATUSES.has(response.status) ||
				response.headers.has("X-Lagniappe-Error") ||
				attempt === STATIC_RETRY_DELAYS_MS.length)
		) {
			return response;
		}
		// Discard failed bodies before another attempt, and avoid replaying an
		// HTTP-cache error or a conditional request without a usable cached body.
		await response?.body?.cancel().catch(() => {});
		await new Promise((resolve) =>
			setTimeout(resolve, STATIC_RETRY_DELAYS_MS[attempt]),
		);
		if (request.signal.aborted) throw request.signal.reason;
		currentRequest = networkRequest(request, { cache: "reload" });
	}
}

const _validateUser = async (cacheConfirmation = {}) => {
	const failed = (stage, status = null) => {
		captureError(new Error("User validation acknowledgement failed."), {
			context: "validate_user",
			stage,
			...(Number.isInteger(status) ? { status } : {}),
		});
		return false;
	};

	let tokenResponse;
	try {
		tokenResponse = await fetch("/l/token", TOKEN_REQUEST);
	} catch {
		return failed("token-request");
	}
	if (!tokenResponse?.ok)
		return failed("token-response", tokenResponse?.status);

	let newToken;
	try {
		newToken = (await tokenResponse.text()).trim();
	} catch {
		return failed("token-body", tokenResponse.status);
	}
	if (!newToken) return failed("token-empty", tokenResponse.status);

	let validationResponse;
	try {
		validationResponse = await fetch("/l/validate-user", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-CSRFToken": newToken,
				"X-Lagniappe-Request": "true",
			},
			credentials: "include",
			body: JSON.stringify({
				cacheCleared: cacheConfirmation.cacheCleared === true,
				responseCacheCleared: cacheConfirmation.responseCacheCleared === true,
				cacheGeneration: cacheConfirmation.cacheGeneration,
				cacheRevision: cacheConfirmation.cacheRevision,
			}),
		});
	} catch {
		return failed("validation-request");
	}
	if (!validationResponse?.ok) {
		return failed("validation-response", validationResponse?.status);
	}

	let acknowledgement;
	try {
		acknowledgement = await validationResponse.json();
	} catch {
		return failed("validation-body", validationResponse.status);
	}
	if (acknowledgement?.cacheCleared !== true) {
		// A newer permission mutation can legitimately supersede this clear.
		if (acknowledgement?.retry === true) return false;
		return failed("validation-acknowledgement", validationResponse.status);
	}
	return true;
};

let _cacheGeneration = 0;
const _cacheInvalidations = new Map();
const _validateUserRequests = new Map();

function responseInvalidatesCache(response) {
	return response.headers.get("X-Lagniappe-Invalidate-Cache");
}

async function clearClientCache(cacheRevision = null) {
	if (!_cacheInvalidations.has(cacheRevision)) {
		const cacheGeneration = _cacheGeneration + 1;
		_cacheGeneration = cacheGeneration;
		const pending = (async () => {
			await caches.delete(RESPONSE_CACHE);
			const responseCacheCleared =
				typeof caches.has === "function"
					? !(await caches.has(RESPONSE_CACHE))
					: true;
			return {
				cacheCleared: responseCacheCleared,
				responseCacheCleared,
				cacheGeneration,
			};
		})().finally(() => {
			_cacheInvalidations.delete(cacheRevision);
		});
		_cacheInvalidations.set(cacheRevision, pending);
	}

	return _cacheInvalidations.get(cacheRevision);
}

function validateUserOnce(cacheConfirmation) {
	if (!cacheConfirmation.cacheCleared) return null;
	const revision = cacheConfirmation.cacheRevision;
	if (!_validateUserRequests.has(revision)) {
		_validateUserRequests.set(
			revision,
			_validateUser(cacheConfirmation).finally(() => {
				_validateUserRequests.delete(revision);
			}),
		);
	}
	return _validateUserRequests.get(revision);
}

async function checkForCacheInvalidation(response, options = {}) {
	if (!responseInvalidatesCache(response)) return { invalidated: false };
	const cacheRevision = response.headers.get("X-Lagniappe-Cache-Revision");
	const confirmation = {
		...(await clearClientCache(cacheRevision)),
		cacheRevision,
	};
	const acknowledged =
		options.validate !== false ? await validateUserOnce(confirmation) : null;
	return {
		invalidated: true,
		...confirmation,
		...(acknowledged === null ? {} : { acknowledged }),
	};
}

async function clearSiblingCacheEntries(newETag, storedETag, url, pathname) {
	if (storedETag && newETag && storedETag === newETag) return;
	const shouldClear =
		pathname === "/" ||
		pathname.startsWith("/l/get") ||
		pathname.startsWith("/categories") ||
		pathname.includes("/index") ||
		pathname.includes("/rows");
	if (!shouldClear) return;

	const cache = await caches.open(RESPONSE_CACHE);
	const siblingReqs = await cache.keys(new Request(url), {
		ignoreSearch: true,
	});
	const staleReqs = siblingReqs.filter((req) => req.url !== url);
	if (staleReqs.length > 0) {
		await Promise.all(staleReqs.map((req) => cache.delete(req)));
	}
}

function responsePreventsStorage(response) {
	if (responseInvalidatesCache(response)) return true;
	if (response.redirected || response.type === "opaqueredirect") return true;

	return (
		response.headers
			.get("Cache-Control")
			?.split(",")
			.some((directive) => directive.trim().toLowerCase() === "no-store") ??
		false
	);
}

async function discardCachedResponse(cache, request) {
	await cache.delete(request, { ignoreVary: true });
}

async function handleUncacheableResponse(
	event,
	cache,
	request,
	response,
	options = {},
) {
	if (!responsePreventsStorage(response)) return false;
	const discard = discardCachedResponse(cache, request);
	if (options.awaitDiscard) {
		await discard;
	} else {
		event.waitUntil(discard);
	}
	// Preserve the acknowledgement boundary for invalidating dynamic responses,
	// including those now explicitly marked no-store by the server.
	await checkForCacheInvalidation(response);
	return true;
}

let _lastEvictionCheck = 0;
const EVICTION_THROTTLE_MS = 60_000;

async function maybeEvictForQuota() {
	const now = Date.now();
	if (now - _lastEvictionCheck < EVICTION_THROTTLE_MS) return;
	_lastEvictionCheck = now;
	const storage = self.navigator?.storage;
	if (!storage?.estimate) return;

	try {
		const { usage, quota } = await storage.estimate();
		if (!usage || !quota) return;

		const THRESHOLD = 0.9; // 90%
		const BATCH_SIZE = 200; // delete up to 200 oldest entries per pass

		if (usage / quota < THRESHOLD) return;

		const cache = await caches.open(RESPONSE_CACHE);
		const keys = await cache.keys(); // insertion order: oldest first
		if (keys.length === 0) return;

		const toDelete = keys.slice(0, Math.min(BATCH_SIZE, keys.length));
		await Promise.all(toDelete.map((req) => cache.delete(req)));
	} catch (e) {
		console.warn("Quota-based eviction failed:", e);
	}
}

let _connectivity = {
	browser: navigator.onLine === false ? "offline" : "online",
	server: "unknown",
	visibility: "visible",
	controller: "uncontrolled",
};

function receiveConnectivityMessage(data) {
	if (
		data?.protocol !== BROWSER_PROTOCOL.id ||
		Number(data?.protocol_version) !== BROWSER_PROTOCOL.version ||
		data?.type !== BROWSER_PROTOCOL.messages.CONNECTIVITY
	) {
		return false;
	}

	const state = data.state;
	if (!state || typeof state !== "object" || Array.isArray(state)) return false;
	const valid = Object.entries(BROWSER_PROTOCOL.connectivity).every(
		([field, values]) => values.includes(state[field]),
	);
	if (!valid) return false;

	_connectivity = { ...state };
	return true;
}

function isUpstreamUnavailableResponse(response) {
	return Boolean(
		response &&
			UPSTREAM_STATUSES.has(response.status) &&
			response.headers.get("content-type")?.includes("text/html") &&
			!response.headers.get("X-Lagniappe-Error"),
	);
}

function upstreamRouteClass(pathname) {
	if (pathname === "/") return "root";
	const segment = pathname.split("/").filter(Boolean)[0] || "root";
	if (segment === "l") return "internal";
	const allowed = new Set([
		"admin",
		"analytics",
		"categories",
		"files",
		"filters",
		"forms",
		"home",
		"manual",
		"messages",
		"pages",
		"process",
		"projects",
		"public",
		"reports",
		"tasks",
		"testing",
		"users",
	]);
	return allowed.has(segment) ? segment : "other";
}

function boundedServer(response) {
	return String(response.headers.get("Server") || "")
		.replace(/[^\x20-\x7E]/g, "")
		.slice(0, 128);
}

async function notifyUpstreamUnavailable(
	request,
	response,
	{ stale = false } = {},
) {
	const pathname = new URL(request.url).pathname;
	const method = String(request.method || "GET").toUpperCase();
	const message = {
		protocol: BROWSER_PROTOCOL.id,
		protocol_version: BROWSER_PROTOCOL.version,
		type: BROWSER_PROTOCOL.messages.UPSTREAM_UNAVAILABLE,
		state: {
			status: response.status,
			method,
			route_class: upstreamRouteClass(pathname),
			server: boundedServer(response),
			trace_header_present: Boolean(
				response.headers.get("X-Cloud-Trace-Context") ||
					response.headers.get("Traceparent"),
			),
			timestamp: new Date().toISOString(),
			online: _connectivity.browser !== "offline",
			service_worker: "controlled",
			stale: Boolean(stale),
			outcome_uncertain: method !== "GET",
			retry_outcome: "service_worker",
		},
	};
	const clients = await self.clients.matchAll({
		type: "window",
		includeUncontrolled: false,
	});
	for (const client of clients) client.postMessage?.(message);
}

function upstreamHeaders(
	response,
	{ stale = false, originalResponse = response } = {},
) {
	const headers = new Headers(response?.headers || {});
	headers.set(UPSTREAM_UNAVAILABLE_HEADER, "true");
	headers.set(
		UPSTREAM_STATUS_HEADER,
		String(originalResponse?.status || response?.status || 503),
	);
	const server = boundedServer(originalResponse);
	if (server) headers.set("Server", server);
	headers.set(STALE_CACHE_HEADER, stale ? "true" : "false");
	headers.set("Cache-Control", "no-store");
	headers.set("Retry-After", "5");
	return headers;
}

function markedStaleResponse(cached, upstream) {
	return new Response(cached.body, {
		status: cached.status,
		statusText: cached.statusText,
		headers: upstreamHeaders(cached, {
			stale: true,
			originalResponse: upstream,
		}),
	});
}

function brandedUpstreamResponse(request, upstream) {
	const headers = upstreamHeaders(upstream);
	if (request.mode === "navigate") {
		headers.set("Content-Type", "text/html; charset=utf-8");
		return new Response(
			`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lagniappe temporarily unavailable</title><body style="font:16px system-ui,sans-serif;margin:0;background:#f8fafc;color:#0f172a"><main style="max-width:42rem;margin:12vh auto;padding:2rem"><section style="background:white;border:1px solid #cbd5e1;border-radius:.75rem;padding:2rem;box-shadow:0 8px 24px #0f172a14"><h1>Lagniappe is temporarily unavailable</h1><p>The application server could not complete this request. Your saved work remains safe. Wait a moment, then try again.</p><a href="" style="display:inline-block;margin-top:1rem;padding:.65rem 1rem;border-radius:.4rem;background:#334155;color:white;text-decoration:none;font-weight:650">Try again</a></section></main></body></html>`,
			{ status: 503, statusText: "Service Unavailable", headers },
		);
	}

	const applicationRequest =
		request.headers.get("X-Lagniappe-Request") === "true" ||
		request.method !== "GET";
	if (applicationRequest) {
		headers.set("Content-Type", "application/json");
		return new Response(
			JSON.stringify({
				ok: false,
				error: "The application server is temporarily unavailable.",
				code: "upstream_instance_unavailable",
				upstreamUnavailable: true,
				stale: false,
				retryable: request.method === "GET",
				outcomeUncertain: request.method !== "GET",
			}),
			{ status: 503, statusText: "Service Unavailable", headers },
		);
	}

	headers.set("Content-Type", "text/plain; charset=utf-8");
	return new Response(
		"Lagniappe is temporarily unavailable. Try again shortly.",
		{
			status: 503,
			statusText: "Service Unavailable",
			headers,
		},
	);
}

function handleUpstreamUnavailable(event, request, response, cached = null) {
	event.waitUntil(
		notifyUpstreamUnavailable(request, response, { stale: Boolean(cached) }),
	);
	return cached
		? markedStaleResponse(cached, response)
		: brandedUpstreamResponse(request, response);
}

self.addEventListener("message", (event) => {
	receiveConnectivityMessage(event.data);
});

self.addEventListener("install", (event) => {
	event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
	event.waitUntil(
		(async () => {
			await updateCaches();
			await self.clients.claim();
			await precacheStaticAssets();
		})(),
	);
});

function isStatic(pathname) {
	return (
		pathname.startsWith("/fonts/") ||
		pathname.startsWith("/images/") ||
		pathname.startsWith("/chunks/") ||
		pathname.startsWith("/offline") ||
		/\.(css|js|mjs|map|json|txt|ico)(\?|$)/.test(pathname)
	);
}

self.addEventListener("fetch", (event) => {
	const requestUrl = event.request.url;
	const url = new URL(requestUrl);
	const pathname = url.pathname;

	if (requestUrl.includes("extension://")) return;
	if (url.origin !== self.location.origin) return;
	if (pathname === "/l/ping") return;
	if (pathname === "/l/token" && event.request.method === "GET") {
		event.respondWith(handleNetworkOnlyGet(event));
		return;
	}

	if (isStatic(pathname)) {
		event.respondWith(handleStatic(event));
		return;
	} else if (event.request.method === "GET") {
		event.respondWith(handleCacheable(event, pathname));
		return;
	}

	event.respondWith(handleRequest(event, pathname));
});

async function handleStatic(event) {
	const cache = await caches.open(CACHE);
	const cached = await cache.match(event.request, { ignoreVary: true });

	if (cached) {
		if (!responsePreventsStorage(cached)) return cached;
		await cache.delete(event.request, { ignoreVary: true });
	}

	try {
		const response = await fetchStaticAsset(event.request);
		if (isUpstreamUnavailableResponse(response)) {
			return handleUpstreamUnavailable(event, event.request, response);
		}
		if (responsePreventsStorage(response)) {
			event.waitUntil(cache.delete(event.request, { ignoreVary: true }));
		} else if (response.ok) {
			event.waitUntil(cache.put(event.request, response.clone()));
		}
		return response;
	} catch (error) {
		captureError(error, {
			url: event.request.url,
			context: "fetch_static_asset_failed",
		});
		return unavailableResponse(event.request);
	}
}

async function offlineFallback() {
	const cache = await caches.open(CACHE);
	const fallback = await cache.match("/offline");
	if (fallback) return fallback;
	return new Response("Offline", { status: 503, statusText: "Offline" });
}

async function unavailableResponse(request) {
	if (request.mode === "navigate") return offlineFallback();

	if (request.headers.get("X-Lagniappe-Request") === "true") {
		return new Response(
			JSON.stringify({
				ok: false,
				error: "You are offline",
				retryable: false,
				outcomeUncertain: true,
			}),
			{
				status: 503,
				headers: { "Content-Type": "application/json" },
			},
		);
	}

	return new Response("Offline", {
		status: 503,
		statusText: "Offline",
		headers: { "Content-Type": "text/plain" },
	});
}

function networkRequest(request, { etag, cache } = {}) {
	const headers = new Headers(request.headers);
	if (cache === "reload") {
		headers.delete("If-None-Match");
		headers.delete("If-Modified-Since");
	}
	if (etag) {
		headers.set("If-None-Match", etag);
		headers.delete("If-Modified-Since");
	}

	const options = { headers };
	if (cache) options.cache = cache;
	return new Request(request, options);
}

function markResponseNotUpdated(response) {
	const headers = new Headers(response.headers);
	headers.set(UPDATED_HEADER, "false");
	return new Response(response.body, {
		status: response.status,
		statusText: response.statusText,
		headers,
	});
}

async function handleNetworkOnlyGet(event) {
	const { request } = event;
	const cache = await caches.open(RESPONSE_CACHE);
	try {
		const response = await fetch(request);
		if (isUpstreamUnavailableResponse(response)) {
			return handleUpstreamUnavailable(event, request, response);
		}
		await discardCachedResponse(cache, request);
		event.waitUntil(checkForCacheInvalidation(response));
		return response;
	} catch (error) {
		captureError(error, {
			context: "fetch_network_only_failed",
			url: request.url,
		});
		return unavailableResponse(request);
	}
}

async function handleCacheable(event, pathname) {
	const { request } = event;
	const url = request.url;
	const requestCacheGeneration = _cacheGeneration;
	const cache = await caches.open(RESPONSE_CACHE);

	let cachedResponse = await cache.match(request, { ignoreVary: true });
	const storedInvalidation =
		cachedResponse && responseInvalidatesCache(cachedResponse);
	if (cachedResponse && responsePreventsStorage(cachedResponse)) {
		await discardCachedResponse(cache, request);
		cachedResponse = null;
	}
	const online =
		_connectivity.browser !== "offline" && _connectivity.server !== "offline";

	if (!online && cachedResponse) return cachedResponse;

	const storedETag = cachedResponse?.headers.get("ETag");

	const fetchRequest = networkRequest(request, {
		etag: storedETag,
		...(storedInvalidation ? { cache: "reload" } : {}),
	});

	const networkPromise = (async () => {
		try {
			let response = await fetch(fetchRequest);
			if (isUpstreamUnavailableResponse(response)) {
				return handleUpstreamUnavailable(
					event,
					request,
					response,
					cachedResponse,
				);
			}
			let invalidationResult = { invalidated: false };
			let uncacheableResponse = await handleUncacheableResponse(
				event,
				cache,
				request,
				response,
				{ awaitDiscard: response.status === 304 },
			);

			if (response.status === 304) {
				let shouldFetchFresh = false;
				if (uncacheableResponse) {
					shouldFetchFresh = true;
				} else if (responseInvalidatesCache(response)) {
					invalidationResult = (await checkForCacheInvalidation(response)) || {
						invalidated: true,
					};
					cachedResponse = null;
					shouldFetchFresh = true;
				} else if (cachedResponse) {
					return markResponseNotUpdated(cachedResponse);
				}
				if (!shouldFetchFresh) {
					console.warn("304 but no cached response, fetching fresh:", url);
					shouldFetchFresh = true;
				}
				if (shouldFetchFresh) {
					response = await fetch(networkRequest(request, { cache: "reload" }));
					if (isUpstreamUnavailableResponse(response)) {
						return handleUpstreamUnavailable(
							event,
							request,
							response,
							cachedResponse,
						);
					}
					uncacheableResponse = await handleUncacheableResponse(
						event,
						cache,
						request,
						response,
						{ awaitDiscard: response.status === 304 },
					);
				}
			} else if (!uncacheableResponse && responseInvalidatesCache(response)) {
				invalidationResult = (await checkForCacheInvalidation(response)) || {
					invalidated: true,
				};
				cachedResponse = null;
			}

			if (response.ok) {
				if (uncacheableResponse) return response;
				if (
					invalidationResult.invalidated ||
					requestCacheGeneration !== _cacheGeneration
				) {
					return response;
				}

				const newETag = response.headers.get("ETag");
				event.waitUntil(cache.put(request, response.clone()));
				event.waitUntil(maybeEvictForQuota());
				event.waitUntil(
					clearSiblingCacheEntries(newETag, storedETag, url, pathname),
				);
				event.waitUntil(checkForCacheInvalidation(response));
			}

			return response;
		} catch {
			return null;
		}
	})();

	if (cachedResponse) {
		const result = await networkPromise;
		return result || cachedResponse;
	}

	const result = await networkPromise;
	if (result) return result;

	return unavailableResponse(request);
}

async function handleRequest(event, pathname) {
	const request = event.request;
	try {
		const response = await fetch(request);
		if (isUpstreamUnavailableResponse(response)) {
			return handleUpstreamUnavailable(event, request, response);
		}

		if (pathname !== "/l/validate-user" && responseInvalidatesCache(response)) {
			event.waitUntil(checkForCacheInvalidation(response));
		}

		return response;
	} catch (error) {
		captureError(error, {
			context: "request_fetch_failed",
			url: request.url,
			method: request.method,
		});
		return new Response(
			JSON.stringify({ ok: false, error: "You are offline" }),
			{
				status: 503,
				headers: { "Content-Type": "application/json" },
			},
		);
	}
}
