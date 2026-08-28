// biome-ignore lint/correctness/noUnusedVariables: build input replaced with the release build ID
const SW_VERSION = "be6b334a";
const CACHE = `static-cache`;
const RESPONSE_CACHE = `response-cache`;
const PRECACHE_URLS = [
	"/chunks/activity.js?v=be6b334a",
	"/chunks/addImage.js?v=be6b334a",
	"/chunks/addLink.js?v=be6b334a",
	"/chunks/addYouTube.js?v=be6b334a",
	"/chunks/administrators.js?v=be6b334a",
	"/chunks/aiModels.js?v=be6b334a",
	"/chunks/analytics.js?v=be6b334a",
	"/chunks/base.js?v=be6b334a",
	"/chunks/base2.js?v=be6b334a",
	"/chunks/baseElement.js?v=be6b334a",
	"/chunks/baseForm.js?v=be6b334a",
	"/chunks/baseList.js?v=be6b334a",
	"/chunks/baseUpload.js?v=be6b334a",
	"/chunks/bookmark.js?v=be6b334a",
	"/chunks/builder.js?v=be6b334a",
	"/chunks/buttons.js?v=be6b334a",
	"/chunks/category.js?v=be6b334a",
	"/chunks/checkbox.js?v=be6b334a",
	"/chunks/collaborative.js?v=be6b334a",
	"/chunks/columns.js?v=be6b334a",
	"/chunks/combobox.js?v=be6b334a",
	"/chunks/connectivity.js?v=be6b334a",
	"/chunks/core-foundation.js?v=be6b334a",
	"/chunks/deferredOperations.js?v=be6b334a",
	"/chunks/deployment.js?v=be6b334a",
	"/chunks/documentHistory.js?v=be6b334a",
	"/chunks/documentSettings.js?v=be6b334a",
	"/chunks/dropdown.js?v=be6b334a",
	"/chunks/editWatcher.js?v=be6b334a",
	"/chunks/entity-foundation.js?v=be6b334a",
	"/chunks/entityMenu.js?v=be6b334a",
	"/chunks/facets.js?v=be6b334a",
	"/chunks/fileInfo.js?v=be6b334a",
	"/chunks/filePdfPreview.js?v=be6b334a",
	"/chunks/filters.js?v=be6b334a",
	"/chunks/form.js?v=be6b334a",
	"/chunks/form2.js?v=be6b334a",
	"/chunks/formatting.js?v=be6b334a",
	"/chunks/foundation.js?v=be6b334a",
	"/chunks/generateText.js?v=be6b334a",
	"/chunks/html.js?v=be6b334a",
	"/chunks/html2.js?v=be6b334a",
	"/chunks/icons.js?v=be6b334a",
	"/chunks/image.js?v=be6b334a",
	"/chunks/index-foundation.js?v=be6b334a",
	"/chunks/ingress.js?v=be6b334a",
	"/chunks/ingressUpload.js?v=be6b334a",
	"/chunks/input.js?v=be6b334a",
	"/chunks/installationAccess.js?v=be6b334a",
	"/chunks/link.js?v=be6b334a",
	"/chunks/lists.js?v=be6b334a",
	"/chunks/loader.js?v=be6b334a",
	"/chunks/location.js?v=be6b334a",
	"/chunks/logout.js?v=be6b334a",
	"/chunks/maintenance.js?v=be6b334a",
	"/chunks/menuItems.js?v=be6b334a",
	"/chunks/messageComposer.js?v=be6b334a",
	"/chunks/mobileTableControls.js?v=be6b334a",
	"/chunks/modal.js?v=be6b334a",
	"/chunks/modelTasks.js?v=be6b334a",
	"/chunks/note.js?v=be6b334a",
	"/chunks/notifications.js?v=be6b334a",
	"/chunks/offline.js?v=be6b334a",
	"/chunks/offlineQueue.js?v=be6b334a",
	"/chunks/offlineReplay.js?v=be6b334a",
	"/chunks/offlineWork.js?v=be6b334a",
	"/chunks/options.js?v=be6b334a",
	"/chunks/pageInfo.js?v=be6b334a",
	"/chunks/pagePermissions.js?v=be6b334a",
	"/chunks/pagePhoto.js?v=be6b334a",
	"/chunks/pageTaskList.js?v=be6b334a",
	"/chunks/pinVersion.js?v=be6b334a",
	"/chunks/polling.js?v=be6b334a",
	"/chunks/primitives.js?v=be6b334a",
	"/chunks/projectInfo.js?v=be6b334a",
	"/chunks/providers.js?v=be6b334a",
	"/chunks/queryLifecycle.js?v=be6b334a",
	"/chunks/radio.js?v=be6b334a",
	"/chunks/remote.js?v=be6b334a",
	"/chunks/results.js?v=be6b334a",
	"/chunks/search.js?v=be6b334a",
	"/chunks/sectionToggle.js?v=be6b334a",
	"/chunks/sections.js?v=be6b334a",
	"/chunks/select.js?v=be6b334a",
	"/chunks/select2.js?v=be6b334a",
	"/chunks/setColor.js?v=be6b334a",
	"/chunks/setFontFamily.js?v=be6b334a",
	"/chunks/setImage.js?v=be6b334a",
	"/chunks/signature.js?v=be6b334a",
	"/chunks/siteSettings.js?v=be6b334a",
	"/chunks/status.js?v=be6b334a",
	"/chunks/status2.js?v=be6b334a",
	"/chunks/storage.js?v=be6b334a",
	"/chunks/styles.js?v=be6b334a",
	"/chunks/submission.js?v=be6b334a",
	"/chunks/submitter.js?v=be6b334a",
	"/chunks/sync.js?v=be6b334a",
	"/chunks/table.js?v=be6b334a",
	"/chunks/tableEditor.js?v=be6b334a",
	"/chunks/tableSorting.js?v=be6b334a",
	"/chunks/tableVisibility.js?v=be6b334a",
	"/chunks/tables.js?v=be6b334a",
	"/chunks/taskForm.js?v=be6b334a",
	"/chunks/taskSettings.js?v=be6b334a",
	"/chunks/tasks.js?v=be6b334a",
	"/chunks/textarea.js?v=be6b334a",
	"/chunks/todo.js?v=be6b334a",
	"/chunks/toolbar.js?v=be6b334a",
	"/chunks/toolbarButtons.js?v=be6b334a",
	"/chunks/tools.js?v=be6b334a",
	"/chunks/uploadFile.js?v=be6b334a",
	"/chunks/user.js?v=be6b334a",
	"/chunks/user2.js?v=be6b334a",
	"/chunks/views/admin.js?v=be6b334a",
	"/chunks/views/analytics.js?v=be6b334a",
	"/chunks/views/builder.js?v=be6b334a",
	"/chunks/views/file.js?v=be6b334a",
	"/chunks/views/home.js?v=be6b334a",
	"/chunks/views/index.js?v=be6b334a",
	"/chunks/views/manual.js?v=be6b334a",
	"/chunks/views/messages.js?v=be6b334a",
	"/chunks/views/page.js?v=be6b334a",
	"/chunks/views/project.js?v=be6b334a",
	"/chunks/views/public.js?v=be6b334a",
	"/chunks/views/report.js?v=be6b334a",
	"/chunks/views/results.js?v=be6b334a",
	"/chunks/views/user.js?v=be6b334a",
	"/chunks/visibility.js?v=be6b334a"
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
 * @matrix cache : activation ownership service-worker
 */
async function updateCaches() {
	await Promise.all([caches.delete(CACHE), caches.delete(RESPONSE_CACHE)]);

	const cache = await caches.open(CACHE);
	await cache.add("/offline");
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_precache_static_assets_warms_configured_urls_and_ignores_failures
 * @matrix cache : precache service-worker static-assets
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
	/**
	 * @testable false
	 * @covered-by src/script/sw.template.mjs::_validateUser
	 * @reason validation failures share one safe diagnostic shape
	 */
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
		return failed("validation-acknowledgement", validationResponse.status);
	}
	return true;
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
 * @tests tests_js/test_008_service_worker.py::test_cache_invalidation_requires_explicit_server_acknowledgement
 * @matrix cache : acknowledgement failure invalidation retry service-worker
 */
async function checkForCacheInvalidation(response, options = {}) {
	if (!responseInvalidatesCache(response)) return { invalidated: false };
	const confirmation = await clearClientCache();
	const acknowledged =
		options.validate !== false ? await validateUserOnce(confirmation) : null;
	return {
		invalidated: true,
		...confirmation,
		...(acknowledged === null ? {} : { acknowledged }),
	};
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_changed_validators_clear_only_same_path_query_siblings_for_configured_routes
 * @matrix cache : etag query route-class service-worker sibling-invalidation
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
 * @matrix cache : no-store service-worker
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
 * @matrix cache : batch eviction failure quota service-worker throttle unavailable
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
 * @matrix browser-protocol connectivity : controller service-worker validation version
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
 * @matrix cache : no-store service-worker static-assets
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
 * @matrix cache offline : cache-miss fallback navigation service-worker
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
 * @matrix cache offline : ajax navigation response-shape service-worker
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
 * @matrix cache : browser-validators etag invalidation redirect-mode service-worker
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
 * @matrix cache request : conditional-response dom-refresh service-worker
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
 * @matrix cache csrf : network-only service-worker token
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
 * @matrix cache : cached-response invalidation network-validation no-store redirected-response service-worker
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
 * @matrix offline request : mutation response-shape service-worker
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
