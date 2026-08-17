// biome-ignore lint/correctness/noUnusedVariables: build input replaced with the release build ID
const SW_VERSION = "b57ebdcf";
const CACHE = `static-cache`;
const RESPONSE_CACHE = `response-cache`;
const PRECACHE_URLS = [
	"/chunks/activity.js?v=b57ebdcf",
	"/chunks/addImage.js?v=b57ebdcf",
	"/chunks/addLink.js?v=b57ebdcf",
	"/chunks/addYouTube.js?v=b57ebdcf",
	"/chunks/aiModels.js?v=b57ebdcf",
	"/chunks/analytics.js?v=b57ebdcf",
	"/chunks/base.js?v=b57ebdcf",
	"/chunks/base2.js?v=b57ebdcf",
	"/chunks/baseElement.js?v=b57ebdcf",
	"/chunks/baseForm.js?v=b57ebdcf",
	"/chunks/baseList.js?v=b57ebdcf",
	"/chunks/baseUpload.js?v=b57ebdcf",
	"/chunks/bookmark.js?v=b57ebdcf",
	"/chunks/builder.js?v=b57ebdcf",
	"/chunks/buttons.js?v=b57ebdcf",
	"/chunks/category.js?v=b57ebdcf",
	"/chunks/checkbox.js?v=b57ebdcf",
	"/chunks/collaborative.js?v=b57ebdcf",
	"/chunks/columns.js?v=b57ebdcf",
	"/chunks/combobox.js?v=b57ebdcf",
	"/chunks/connectivity.js?v=b57ebdcf",
	"/chunks/core-foundation.js?v=b57ebdcf",
	"/chunks/deferredOperations.js?v=b57ebdcf",
	"/chunks/deployment.js?v=b57ebdcf",
	"/chunks/documentHistory.js?v=b57ebdcf",
	"/chunks/documentSettings.js?v=b57ebdcf",
	"/chunks/dropdown.js?v=b57ebdcf",
	"/chunks/editWatcher.js?v=b57ebdcf",
	"/chunks/entity-foundation.js?v=b57ebdcf",
	"/chunks/entityMenu.js?v=b57ebdcf",
	"/chunks/facets.js?v=b57ebdcf",
	"/chunks/fileInfo.js?v=b57ebdcf",
	"/chunks/filePdfPreview.js?v=b57ebdcf",
	"/chunks/filters.js?v=b57ebdcf",
	"/chunks/form.js?v=b57ebdcf",
	"/chunks/form2.js?v=b57ebdcf",
	"/chunks/formatting.js?v=b57ebdcf",
	"/chunks/foundation.js?v=b57ebdcf",
	"/chunks/generateText.js?v=b57ebdcf",
	"/chunks/html.js?v=b57ebdcf",
	"/chunks/html2.js?v=b57ebdcf",
	"/chunks/icons.js?v=b57ebdcf",
	"/chunks/image.js?v=b57ebdcf",
	"/chunks/index-foundation.js?v=b57ebdcf",
	"/chunks/ingress.js?v=b57ebdcf",
	"/chunks/ingressUpload.js?v=b57ebdcf",
	"/chunks/input.js?v=b57ebdcf",
	"/chunks/link.js?v=b57ebdcf",
	"/chunks/lists.js?v=b57ebdcf",
	"/chunks/loader.js?v=b57ebdcf",
	"/chunks/location.js?v=b57ebdcf",
	"/chunks/logout.js?v=b57ebdcf",
	"/chunks/maintenance.js?v=b57ebdcf",
	"/chunks/menuItems.js?v=b57ebdcf",
	"/chunks/messageComposer.js?v=b57ebdcf",
	"/chunks/mobileTableControls.js?v=b57ebdcf",
	"/chunks/modal.js?v=b57ebdcf",
	"/chunks/modelTasks.js?v=b57ebdcf",
	"/chunks/note.js?v=b57ebdcf",
	"/chunks/notifications.js?v=b57ebdcf",
	"/chunks/offline.js?v=b57ebdcf",
	"/chunks/offlineQueue.js?v=b57ebdcf",
	"/chunks/offlineReplay.js?v=b57ebdcf",
	"/chunks/offlineWork.js?v=b57ebdcf",
	"/chunks/options.js?v=b57ebdcf",
	"/chunks/pageInfo.js?v=b57ebdcf",
	"/chunks/pagePermissions.js?v=b57ebdcf",
	"/chunks/pagePhoto.js?v=b57ebdcf",
	"/chunks/pageTaskList.js?v=b57ebdcf",
	"/chunks/pinVersion.js?v=b57ebdcf",
	"/chunks/polling.js?v=b57ebdcf",
	"/chunks/primitives.js?v=b57ebdcf",
	"/chunks/projectInfo.js?v=b57ebdcf",
	"/chunks/providers.js?v=b57ebdcf",
	"/chunks/radio.js?v=b57ebdcf",
	"/chunks/results.js?v=b57ebdcf",
	"/chunks/search.js?v=b57ebdcf",
	"/chunks/sectionToggle.js?v=b57ebdcf",
	"/chunks/sections.js?v=b57ebdcf",
	"/chunks/select.js?v=b57ebdcf",
	"/chunks/select2.js?v=b57ebdcf",
	"/chunks/setColor.js?v=b57ebdcf",
	"/chunks/setFontFamily.js?v=b57ebdcf",
	"/chunks/setImage.js?v=b57ebdcf",
	"/chunks/signature.js?v=b57ebdcf",
	"/chunks/siteExport.js?v=b57ebdcf",
	"/chunks/siteSettings.js?v=b57ebdcf",
	"/chunks/status.js?v=b57ebdcf",
	"/chunks/status2.js?v=b57ebdcf",
	"/chunks/styles.js?v=b57ebdcf",
	"/chunks/submission.js?v=b57ebdcf",
	"/chunks/submitter.js?v=b57ebdcf",
	"/chunks/sync.js?v=b57ebdcf",
	"/chunks/table.js?v=b57ebdcf",
	"/chunks/tableEditor.js?v=b57ebdcf",
	"/chunks/tableSorting.js?v=b57ebdcf",
	"/chunks/tableVisibility.js?v=b57ebdcf",
	"/chunks/tables.js?v=b57ebdcf",
	"/chunks/taskForm.js?v=b57ebdcf",
	"/chunks/taskSettings.js?v=b57ebdcf",
	"/chunks/tasks.js?v=b57ebdcf",
	"/chunks/textarea.js?v=b57ebdcf",
	"/chunks/todo.js?v=b57ebdcf",
	"/chunks/toolbar.js?v=b57ebdcf",
	"/chunks/toolbarButtons.js?v=b57ebdcf",
	"/chunks/tools.js?v=b57ebdcf",
	"/chunks/uploadFile.js?v=b57ebdcf",
	"/chunks/user.js?v=b57ebdcf",
	"/chunks/user2.js?v=b57ebdcf",
	"/chunks/views/admin.js?v=b57ebdcf",
	"/chunks/views/analytics.js?v=b57ebdcf",
	"/chunks/views/builder.js?v=b57ebdcf",
	"/chunks/views/file.js?v=b57ebdcf",
	"/chunks/views/home.js?v=b57ebdcf",
	"/chunks/views/index.js?v=b57ebdcf",
	"/chunks/views/manual.js?v=b57ebdcf",
	"/chunks/views/messages.js?v=b57ebdcf",
	"/chunks/views/page.js?v=b57ebdcf",
	"/chunks/views/project.js?v=b57ebdcf",
	"/chunks/views/report.js?v=b57ebdcf",
	"/chunks/views/results.js?v=b57ebdcf",
	"/chunks/views/user.js?v=b57ebdcf",
	"/chunks/visibility.js?v=b57ebdcf"
];
const UPDATED_HEADER = "X-Lagniappe-Updated";
const BROWSER_PROTOCOL = {
	"id": "lagniappe-browser",
	"version": 3,
	"messages": {
		"CONNECTIVITY": "connectivity-state"
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

/**
 * @testable false
 * @reason service-worker error reporting is best-effort diagnostics covered through focused tooling outside source traceability collection
 */
function captureError(error, context = {}) {
	if (typeof self.Sentry !== "undefined" && self.Sentry) {
		if (error instanceof Error) {
			self.Sentry.captureException(error, context);
		} else {
			self.Sentry.captureMessage(error, context);
		}
	}
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_activation_clears_only_application_owned_caches
 * @features cache
 * @dimensions service-worker activation ownership
 */
async function updateCaches() {
	await Promise.all([caches.delete(CACHE), caches.delete(RESPONSE_CACHE)]);

	const cache = await caches.open(CACHE);
	await cache.add("/offline");
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_precache_static_assets_warms_configured_urls_and_ignores_failures
 * @features cache
 * @dimensions service-worker static-assets precache
 */
async function precacheStaticAssets() {
	const cache = await caches.open(CACHE);
	await Promise.allSettled(
		PRECACHE_URLS.map(async (url) => {
			const request = new Request(new URL(url, self.location.origin).href, {
				cache: "reload",
			});
			const response = await fetch(request);
			if (response.ok && !responsePreventsStorage(response)) {
				await cache.put(request, response.clone());
			}
		}),
	);
}

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::checkForCacheInvalidation
 * @reason validate-user confirmation is exercised through the cache invalidation owner
 */
const _validateUser = async (cacheConfirmation = {}) => {
	try {
		const response = await fetch("/l/token", TOKEN_REQUEST);
		const newToken = await response.text();
		await fetch("/l/validate-user", {
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
			}),
		});
	} catch (error) {
		captureError(error, {
			context: "validate_user",
		});
		return null;
	}
};

let _cacheGeneration = 0;
let _cacheInvalidation = null;
let _validateUserRequest = null;

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::checkForCacheInvalidation
 * @covered-by src/script/sw.template.mjs::handleCacheable
 * @reason invalidation header lookup is exercised through cache invalidation and cacheable request owners
 */
function responseInvalidatesCache(response) {
	return response.headers.get("X-Lagniappe-Invalidate-Cache");
}

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::checkForCacheInvalidation
 * @reason local cache clearing is exercised through the cache invalidation owner
 */
async function clearClientCache() {
	if (!_cacheInvalidation) {
		const cacheGeneration = _cacheGeneration + 1;
		_cacheGeneration = cacheGeneration;
		_cacheInvalidation = (async () => {
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
			_cacheInvalidation = null;
		});
	}

	return _cacheInvalidation;
}

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::checkForCacheInvalidation
 * @reason validate-user request coalescing is exercised through the cache invalidation owner
 */
function validateUserOnce(cacheConfirmation) {
	if (!cacheConfirmation.cacheCleared) return null;
	if (!_validateUserRequest) {
		_validateUserRequest = _validateUser(cacheConfirmation).finally(() => {
			_validateUserRequest = null;
		});
	}
	return _validateUserRequest;
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_cache_invalidation_confirmation_posts_after_local_clear
 * @features cache
 * @dimensions invalidation service-worker
 */
async function checkForCacheInvalidation(response, options = {}) {
	if (!responseInvalidatesCache(response)) return { invalidated: false };
	const confirmation = await clearClientCache();
	if (options.validate !== false) await validateUserOnce(confirmation);
	return { invalidated: true, ...confirmation };
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_changed_validators_clear_only_same_path_query_siblings_for_configured_routes
 * @features cache
 * @dimensions service-worker sibling-invalidation route-class etag query
 */
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

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::handleUncacheableResponse
 * @covered-by src/script/sw.template.mjs::handleStatic
 * @covered-by src/script/sw.template.mjs::precacheStaticAssets
 * @reason response storage filtering is exercised through no-store, static, redirect, and precache owners
 */
function responsePreventsStorage(response) {
	if (response.redirected || response.type === "opaqueredirect") return true;

	return (
		response.headers
			.get("Cache-Control")
			?.split(",")
			.some((directive) => directive.trim().toLowerCase() === "no-store") ??
		false
	);
}

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::handleUncacheableResponse
 * @covered-by src/script/sw.template.mjs::handleCacheable
 * @reason cache entry discard behavior is exercised through no-store and redirected cacheable responses
 */
async function discardCachedResponse(cache, request) {
	await cache.delete(request, { ignoreVary: true });
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_no_store_304_discards_cached_response
 * @features cache
 * @dimensions no-store service-worker
 */
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
	event.waitUntil(checkForCacheInvalidation(response));
	return true;
}

let _lastEvictionCheck = 0;
const EVICTION_THROTTLE_MS = 60_000;

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_quota_eviction_is_throttled_and_bounded_to_oldest_entries
 * @tests tests_js/test_008_service_worker.py::test_quota_eviction_tolerates_unavailable_and_failed_estimates
 * @features cache
 * @dimensions service-worker quota eviction throttle batch failure unavailable
 */
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_worker_accepts_only_versioned_valid_connectivity_messages
 * @features connectivity browser-protocol
 * @dimensions service-worker validation version controller
 */
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

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::handleStatic
 * @covered-by src/script/sw.template.mjs::handleCacheable
 * @reason request classification is exercised through static and cacheable fetch owners
 */
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_no_store_static_response_is_not_cached
 * @features cache
 * @dimensions no-store service-worker static-assets
 */
async function handleStatic(event) {
	const cache = await caches.open(CACHE);
	const cached = await cache.match(event.request, { ignoreVary: true });

	if (cached) {
		if (!responsePreventsStorage(cached)) return cached;
		await cache.delete(event.request, { ignoreVary: true });
	}

	try {
		const response = await fetch(event.request);
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_navigation_failure_without_cached_offline_document_returns_503
 * @features offline cache
 * @dimensions service-worker navigation fallback cache-miss
 */
async function offlineFallback() {
	const cache = await caches.open(CACHE);
	const fallback = await cache.match("/offline");
	if (fallback) return fallback;
	return new Response("Offline", { status: 503, statusText: "Offline" });
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_application_get_failure_returns_503_instead_of_offline_html
 * @tests tests_js/test_008_service_worker.py::test_navigation_failure_uses_offline_document
 * @features offline cache
 * @dimensions service-worker response-shape navigation ajax
 */
async function unavailableResponse(request) {
	if (request.mode === "navigate") return offlineFallback();

	if (request.headers.get("X-Lagniappe-Request") === "true") {
		return new Response(
			JSON.stringify({ ok: false, error: "You are offline" }),
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_dynamic_fetch_preserves_browser_validators_without_stored_etag
 * @tests tests_js/test_008_service_worker.py::test_conditional_fetch_preserves_original_request_redirect_mode
 * @tests tests_js/test_008_service_worker.py::test_304_response_with_invalidation_header_fetches_fresh_response
 * @features cache
 * @dimensions browser-validators redirect-mode etag invalidation service-worker
 */
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_cached_304_marks_response_not_updated
 * @features cache request
 * @dimensions service-worker conditional-response dom-refresh
 */
function markResponseNotUpdated(response) {
	const headers = new Headers(response.headers);
	headers.set(UPDATED_HEADER, "false");
	return new Response(response.body, {
		status: response.status,
		statusText: response.statusText,
		headers,
	});
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_token_request_is_network_only_without_client_cache_directives
 * @features cache csrf
 * @dimensions service-worker token network-only
 */
async function handleNetworkOnlyGet(event) {
	const { request } = event;
	const cache = await caches.open(RESPONSE_CACHE);
	try {
		const response = await fetch(request);
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_no_store_304_discards_cached_response
 * @tests tests_js/test_008_service_worker.py::test_cached_304_marks_response_not_updated
 * @tests tests_js/test_008_service_worker.py::test_304_response_with_invalidation_header_fetches_fresh_response
 * @tests tests_js/test_008_service_worker.py::test_redirect_response_with_invalidation_header_clears_cache
 * @tests tests_js/test_008_service_worker.py::test_redirected_responses_are_discarded_and_not_cached
 * @tests tests_js/test_008_service_worker.py::test_cached_dynamic_get_waits_for_network_validation_before_using_cached_response
 * @features cache
 * @dimensions no-store invalidation service-worker redirected-response cached-response network-validation
 */
async function handleCacheable(event, pathname) {
	const { request } = event;
	const url = request.url;
	const requestCacheGeneration = _cacheGeneration;
	const cache = await caches.open(RESPONSE_CACHE);

	let cachedResponse = await cache.match(request, { ignoreVary: true });
	if (cachedResponse && responsePreventsStorage(cachedResponse)) {
		await discardCachedResponse(cache, request);
		cachedResponse = null;
	}
	const online =
		_connectivity.browser !== "offline" && _connectivity.server !== "offline";

	if (!online && cachedResponse) return cachedResponse;

	const storedETag = cachedResponse?.headers.get("ETag");

	const fetchRequest = networkRequest(request, { etag: storedETag });

	const networkPromise = (async () => {
		try {
			let response = await fetch(fetchRequest);
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_mutation_failure_returns_json_503
 * @features offline request
 * @dimensions service-worker mutation response-shape
 */
async function handleRequest(event, pathname) {
	const request = event.request;
	try {
		const response = await fetch(request);

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
