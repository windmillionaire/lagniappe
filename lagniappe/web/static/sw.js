// biome-ignore lint/correctness/noUnusedVariables: build input replaced with the release build ID
const SW_VERSION = "bcb7426f";
const CACHE = `static-cache`;
const RESPONSE_CACHE = `response-cache`;
const PRECACHE_URLS = [
	"/chunks/activity.js?v=bcb7426f",
	"/chunks/addImage.js?v=bcb7426f",
	"/chunks/addLink.js?v=bcb7426f",
	"/chunks/addYouTube.js?v=bcb7426f",
	"/chunks/administrators.js?v=bcb7426f",
	"/chunks/aiModels.js?v=bcb7426f",
	"/chunks/analytics.js?v=bcb7426f",
	"/chunks/base.js?v=bcb7426f",
	"/chunks/base2.js?v=bcb7426f",
	"/chunks/baseElement.js?v=bcb7426f",
	"/chunks/baseForm.js?v=bcb7426f",
	"/chunks/baseList.js?v=bcb7426f",
	"/chunks/baseUpload.js?v=bcb7426f",
	"/chunks/bookmark.js?v=bcb7426f",
	"/chunks/builder.js?v=bcb7426f",
	"/chunks/buttons.js?v=bcb7426f",
	"/chunks/category.js?v=bcb7426f",
	"/chunks/checkbox.js?v=bcb7426f",
	"/chunks/collaborative.js?v=bcb7426f",
	"/chunks/columns.js?v=bcb7426f",
	"/chunks/combobox.js?v=bcb7426f",
	"/chunks/connectivity.js?v=bcb7426f",
	"/chunks/core-foundation.js?v=bcb7426f",
	"/chunks/deferredOperations.js?v=bcb7426f",
	"/chunks/deployment.js?v=bcb7426f",
	"/chunks/documentHistory.js?v=bcb7426f",
	"/chunks/documentSettings.js?v=bcb7426f",
	"/chunks/dropdown.js?v=bcb7426f",
	"/chunks/editWatcher.js?v=bcb7426f",
	"/chunks/entity-foundation.js?v=bcb7426f",
	"/chunks/entityMenu.js?v=bcb7426f",
	"/chunks/facets.js?v=bcb7426f",
	"/chunks/fileInfo.js?v=bcb7426f",
	"/chunks/filePdfPreview.js?v=bcb7426f",
	"/chunks/filters.js?v=bcb7426f",
	"/chunks/form.js?v=bcb7426f",
	"/chunks/form2.js?v=bcb7426f",
	"/chunks/formatting.js?v=bcb7426f",
	"/chunks/foundation.js?v=bcb7426f",
	"/chunks/generateText.js?v=bcb7426f",
	"/chunks/html.js?v=bcb7426f",
	"/chunks/html2.js?v=bcb7426f",
	"/chunks/icons.js?v=bcb7426f",
	"/chunks/image.js?v=bcb7426f",
	"/chunks/index-foundation.js?v=bcb7426f",
	"/chunks/ingress.js?v=bcb7426f",
	"/chunks/ingressUpload.js?v=bcb7426f",
	"/chunks/input.js?v=bcb7426f",
	"/chunks/installationAccess.js?v=bcb7426f",
	"/chunks/link.js?v=bcb7426f",
	"/chunks/lists.js?v=bcb7426f",
	"/chunks/loader.js?v=bcb7426f",
	"/chunks/location.js?v=bcb7426f",
	"/chunks/logout.js?v=bcb7426f",
	"/chunks/maintenance.js?v=bcb7426f",
	"/chunks/menuItems.js?v=bcb7426f",
	"/chunks/messageComposer.js?v=bcb7426f",
	"/chunks/mobileTableControls.js?v=bcb7426f",
	"/chunks/modal.js?v=bcb7426f",
	"/chunks/modelTasks.js?v=bcb7426f",
	"/chunks/note.js?v=bcb7426f",
	"/chunks/notifications.js?v=bcb7426f",
	"/chunks/offline.js?v=bcb7426f",
	"/chunks/offlineQueue.js?v=bcb7426f",
	"/chunks/offlineReplay.js?v=bcb7426f",
	"/chunks/offlineWork.js?v=bcb7426f",
	"/chunks/options.js?v=bcb7426f",
	"/chunks/pageInfo.js?v=bcb7426f",
	"/chunks/pagePermissions.js?v=bcb7426f",
	"/chunks/pagePhoto.js?v=bcb7426f",
	"/chunks/pageTaskList.js?v=bcb7426f",
	"/chunks/pinVersion.js?v=bcb7426f",
	"/chunks/polling.js?v=bcb7426f",
	"/chunks/primitives.js?v=bcb7426f",
	"/chunks/projectInfo.js?v=bcb7426f",
	"/chunks/providers.js?v=bcb7426f",
	"/chunks/queryLifecycle.js?v=bcb7426f",
	"/chunks/radio.js?v=bcb7426f",
	"/chunks/remote.js?v=bcb7426f",
	"/chunks/results.js?v=bcb7426f",
	"/chunks/search.js?v=bcb7426f",
	"/chunks/sectionToggle.js?v=bcb7426f",
	"/chunks/sections.js?v=bcb7426f",
	"/chunks/select.js?v=bcb7426f",
	"/chunks/select2.js?v=bcb7426f",
	"/chunks/setColor.js?v=bcb7426f",
	"/chunks/setFontFamily.js?v=bcb7426f",
	"/chunks/setImage.js?v=bcb7426f",
	"/chunks/signature.js?v=bcb7426f",
	"/chunks/siteSettings.js?v=bcb7426f",
	"/chunks/status.js?v=bcb7426f",
	"/chunks/status2.js?v=bcb7426f",
	"/chunks/storage.js?v=bcb7426f",
	"/chunks/styles.js?v=bcb7426f",
	"/chunks/submission.js?v=bcb7426f",
	"/chunks/submitter.js?v=bcb7426f",
	"/chunks/sync.js?v=bcb7426f",
	"/chunks/table.js?v=bcb7426f",
	"/chunks/tableEditor.js?v=bcb7426f",
	"/chunks/tableSorting.js?v=bcb7426f",
	"/chunks/tableVisibility.js?v=bcb7426f",
	"/chunks/tables.js?v=bcb7426f",
	"/chunks/taskForm.js?v=bcb7426f",
	"/chunks/taskSettings.js?v=bcb7426f",
	"/chunks/tasks.js?v=bcb7426f",
	"/chunks/textarea.js?v=bcb7426f",
	"/chunks/todo.js?v=bcb7426f",
	"/chunks/toolbar.js?v=bcb7426f",
	"/chunks/toolbarButtons.js?v=bcb7426f",
	"/chunks/tools.js?v=bcb7426f",
	"/chunks/uploadFile.js?v=bcb7426f",
	"/chunks/upstreamUnavailable.js?v=bcb7426f",
	"/chunks/user.js?v=bcb7426f",
	"/chunks/user2.js?v=bcb7426f",
	"/chunks/views/admin.js?v=bcb7426f",
	"/chunks/views/analytics.js?v=bcb7426f",
	"/chunks/views/builder.js?v=bcb7426f",
	"/chunks/views/file.js?v=bcb7426f",
	"/chunks/views/home.js?v=bcb7426f",
	"/chunks/views/index.js?v=bcb7426f",
	"/chunks/views/manual.js?v=bcb7426f",
	"/chunks/views/messages.js?v=bcb7426f",
	"/chunks/views/page.js?v=bcb7426f",
	"/chunks/views/project.js?v=bcb7426f",
	"/chunks/views/public.js?v=bcb7426f",
	"/chunks/views/report.js?v=bcb7426f",
	"/chunks/views/results.js?v=bcb7426f",
	"/chunks/views/user.js?v=bcb7426f",
	"/chunks/visibility.js?v=bcb7426f"
];
const UPDATED_HEADER = "X-Lagniappe-Updated";
const UPSTREAM_UNAVAILABLE_HEADER = "X-Lagniappe-Upstream-Unavailable";
const UPSTREAM_STATUS_HEADER = "X-Lagniappe-Upstream-Status";
const STALE_CACHE_HEADER = "X-Lagniappe-Stale-Cache";
const UPSTREAM_STATUSES = new Set([500, 502, 503, 504]);
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_worker_classifies_only_unmarked_upstream_html_failures
 * @matrix request-errors service-worker : application-error-marker classification upstream-unavailable
 */
function isUpstreamUnavailableResponse(response) {
	return Boolean(
		response &&
			UPSTREAM_STATUSES.has(response.status) &&
			response.headers.get("content-type")?.includes("text/html") &&
			!response.headers.get("X-Lagniappe-Error"),
	);
}

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::notifyUpstreamUnavailable
 * @reason route privacy is asserted through the controlled-client message
 */
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

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::notifyUpstreamUnavailable
 * @covered-by src/script/sw.template.mjs::upstreamHeaders
 * @reason server sanitization is asserted through client messages and internal headers
 */
function boundedServer(response) {
	return String(response.headers.get("Server") || "")
		.replace(/[^\x20-\x7E]/g, "")
		.slice(0, 128);
}

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_upstream_failure_notifies_controlled_clients_with_bounded_state
 * @matrix browser-protocol request-errors service-worker : client-message privacy upstream-unavailable
 */
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

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::markedStaleResponse
 * @covered-by src/script/sw.template.mjs::brandedUpstreamResponse
 * @reason internal markers are asserted through stale and branded response owners
 */
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_upstream_failure_uses_marked_stale_cache_without_caching_5xx
 * @matrix cache request-errors service-worker : stale-cache upstream-unavailable
 */
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_upstream_failure_without_cache_returns_branded_retryable_503
 * @tests tests_js/test_008_service_worker.py::test_mutation_upstream_failure_returns_uncertain_json_without_replay
 * @matrix request-errors service-worker : branded-response mutation no-replay retry upstream-unavailable
 */
function brandedUpstreamResponse(request, upstream) {
	const headers = upstreamHeaders(upstream);
	if (request.mode === "navigate") {
		headers.set("Content-Type", "text/html; charset=utf-8");
		return new Response(
			`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lagniappe temporarily unavailable</title><style>body{font:16px system-ui,sans-serif;margin:0;background:#f8fafc;color:#0f172a}main{max-width:42rem;margin:12vh auto;padding:2rem}section{background:white;border:1px solid #cbd5e1;border-radius:.75rem;padding:2rem;box-shadow:0 8px 24px #0f172a14}a{display:inline-block;margin-top:1rem;padding:.65rem 1rem;border-radius:.4rem;background:#334155;color:white;text-decoration:none;font-weight:650}</style><main><section><h1>Lagniappe is temporarily unavailable</h1><p>The application server could not complete this request. Your saved work remains safe. Wait a moment, then try again.</p><a href="">Try again</a></section></main></html>`,
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

/**
 * @testable false
 * @covered-by src/script/sw.template.mjs::handleCacheable
 * @covered-by src/script/sw.template.mjs::handleRequest
 * @reason response selection and notification are exercised through fetch strategy owners
 */
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

/**
 * @testable true
 * @tests tests_js/test_008_service_worker.py::test_mutation_failure_returns_json_503
 * @matrix offline request : mutation response-shape service-worker
 */
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
