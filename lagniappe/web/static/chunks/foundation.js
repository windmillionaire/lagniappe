/*! Third-party licenses: /third-party-licenses.txt */
import { c as connectivity } from './connectivity.js?v=bd163a0f';

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
 * @matrix error-tracking : normalization sentry-context
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

const NOTIFICATION_STATE_HEADER = "X-Lagniappe-Notification-State";

let invalidStateReported = false;

/**
 * Publish the notification badge's count, visibility, and accessible state as
 * one DOM commit.
 *
 * @testable true
 * @tests tests_js/test_036_notification_state.py::test_notification_state_updates_badge_and_reports_cache_miss
 * @matrix notifications : accessible-state badge
 */
const renderNotificationBadge = (count) => {
	const normalized = Number.isInteger(Number(count)) ? Number(count) : 0;
	const button = document.querySelector("[data-role='notifications']");
	const countElement = document.querySelector(
		"[data-role='notification-count']",
	);
	if (countElement) countElement.textContent = String(normalized);
	if (!button) return normalized;

	button.dataset.visible = "true";
	button.setAttribute("aria-hidden", "false");
	button.setAttribute("aria-busy", "false");
	button.setAttribute("aria-label", `Notifications: ${normalized}`);
	button.tabIndex = 0;
	return normalized;
};

/**
 * @testable false
 * @covered-by src/script/shared/notificationState.mjs::applyNotificationState
 * @reason input normalization is exercised through the public state publisher
 */
const _normalized = (raw) => {
	if (typeof raw === "string") {
		try {
			raw = JSON.parse(raw);
		} catch {
			return null;
		}
	}
	if (!raw || typeof raw !== "object") return null;
	if (raw.generation === null && raw.revision === null && raw.count === null) {
		return { generation: null, revision: null, count: null, miss: true };
	}
	if (
		typeof raw.generation !== "string" ||
		!raw.generation ||
		!Number.isInteger(raw.revision) ||
		raw.revision < 0 ||
		!Number.isInteger(raw.count) ||
		raw.count < 0
	) {
		return null;
	}
	return {
		generation: raw.generation,
		revision: raw.revision,
		count: raw.count,
		miss: false,
	};
};

/**
 * Publish compact notification state before the lazy menu module is loaded.
 *
 * @testable true
 * @tests tests_js/test_036_notification_state.py::test_notification_state_updates_badge_and_reports_cache_miss
 * @matrix notifications : badge cold-seed redis-projection
 */
const applyNotificationState = (raw) => {
	const state = _normalized(raw);
	if (!state) {
		if (raw !== null && raw !== undefined && !invalidStateReported) {
			invalidStateReported = true;
			captureError(
				new TypeError("Invalid notification state response."),
				null,
				{
					context: "notification-state-contract",
				},
			);
		}
		return null;
	}
	window.__NOTIFICATION_STATE__ = state;

	if (!state.miss) {
		renderNotificationBadge(state.count);
	}

	window.dispatchEvent(
		new CustomEvent("notification-state", { detail: { ...state } }),
	);
	return state;
};

/**
 * @testable true
 * @tests tests_js/test_036_notification_state.py::test_notification_state_updates_badge_and_reports_cache_miss
 * @pair notifications:response-header
 */
const applyNotificationStateHeader = (headers) => {
	const raw = headers?.get?.(NOTIFICATION_STATE_HEADER);
	return raw ? applyNotificationState(raw) : null;
};

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
const runWithoutTransition = async (callback, label = "unlabeled") => {
	try {
		const result = callback();
		if (result?.then) {
			captureError(
				new TypeError(
					`View transition commit "${label}" returned a promise. Prepare asynchronous work before committing DOM changes.`,
				),
			);
			await result;
		}
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
let pendingTransitionBatch = null;

/**
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::withTransition
 * @reason development-only timing diagnostic is part of the transition wrapper
 */
const reportSlowCommit = (label, started) => {
	if (typeof performance === "undefined" || !performance.now) return;
	return;
};

/**
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::withTransition
 * @reason exact-once commit execution is exercised through the public transition wrapper
 */
const runCommit = (callback, label) => {
	const started =
		typeof performance !== "undefined" && performance.now
			? performance.now()
			: null;
	try {
		const result = callback();
		if (!result?.then) {
			if (started !== null) reportSlowCommit(label, started);
			return true;
		}

		captureError(
			new TypeError(
				`View transition commit "${label}" returned a promise. Prepare asynchronous work before committing DOM changes.`,
			),
		);
		return Promise.resolve(result)
			.then(() => true)
			.catch((error) => {
				captureError(error);
				return false;
			})
			.finally(() => {
				if (started !== null) reportSlowCommit(label, started);
			});
	} catch (error) {
		captureError(error);
		return false;
	}
};

/**
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::withTransition
 * @reason same-turn commit batching is exercised through the public transition wrapper
 */
const runTransitionBatch = (entries) => {
	const results = new Array(entries.length).fill(false);
	const pending = [];

	transitionDepth += 1;
	entries.forEach(({ callback, label }, index) => {
		const result = runCommit(callback, label);
		if (result?.then) {
			pending.push(
				result.then((successful) => {
					results[index] = successful;
				}),
			);
		} else {
			results[index] = result;
		}
	});

	if (!pending.length) {
		transitionDepth -= 1;
		return { results, pending: null };
	}

	return {
		results,
		pending: Promise.all(pending).finally(() => {
			transitionDepth -= 1;
		}),
	};
};

/**
 * @testable false
 * @covered-by src/script/shared/utilities.mjs::withTransition
 * @reason single-transition runner is private to the queued wrapper
 */
const executeTransition = async (entries) => {
	let batch = null;
	let updateStarted = false;
	/**
	 * @testable false
	 * @covered-by src/script/shared/utilities.mjs::withTransition
	 * @reason browser update callback is private transition-wrapper plumbing
	 */
	const update = () => {
		updateStarted = true;
		batch = runTransitionBatch(entries);
		return batch.pending || undefined;
	};

	let transition = null;
	if (document.startViewTransition) {
		try {
			transition = document.startViewTransition(update);
		} catch (error) {
			if (!isSkippedViewTransitionError(error)) captureError(error);
		}
	}

	if (!transition) {
		if (!updateStarted) update();
		if (batch?.pending) await batch.pending;
		entries.forEach((entry, index) => {
			entry.resolve(batch.results[index]);
		});
		return;
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/utilities.mjs::withTransition
	 * @reason transition promise observation is exercised through public error handling
	 */
	const observeTransitionError = (error) => {
		if (!isSkippedViewTransitionError(error)) captureError(error);
	};
	void transition.ready?.catch(observeTransitionError);

	const updateDone = transition.updateCallbackDone || transition.finished;
	if (transition.finished !== updateDone) {
		void transition.finished?.catch(observeTransitionError);
	}
	try {
		await updateDone;
	} catch (error) {
		observeTransitionError(error);
	}

	entries.forEach((entry, index) => {
		entry.resolve(batch?.results[index] ?? false);
	});
};

/**
 * @testable true
 * @tests tests_js/test_011_view_transitions_frontend.py::test_nested_transition_joins_active_transition_without_error_report
 * @tests tests_js/test_011_view_transitions_frontend.py::test_transition_resolves_after_update_without_waiting_for_animation
 * @tests tests_js/test_011_view_transitions_frontend.py::test_same_turn_commits_share_one_transition_and_run_once
 * @tests tests_js/test_011_view_transitions_frontend.py::test_ready_rejection_does_not_replay_commit
 * @matrix view-transition : animation-lifecycle coalescing error-reporting exact-once nested-callback queueing ready-rejection update-completion
 */
const withTransition = (callback, { label = "unlabeled" } = {}) => {
	if (transitionDepth > 0) {
		// Nested callers are already inside the browser's transition update.
		return runWithoutTransition(callback, label);
	}

	return new Promise((resolve) => {
		if (!pendingTransitionBatch) {
			pendingTransitionBatch = [];
			queueMicrotask(() => {
				const entries = pendingTransitionBatch;
				pendingTransitionBatch = null;
				transitionQueue = transitionQueue
					.then(() => executeTransition(entries))
					.catch((error) => {
						captureError(error);
						entries.forEach((entry) => {
							entry.resolve(false);
						});
					});
			});
		}
		pendingTransitionBatch.push({ callback, label, resolve });
	});
};

/**
 * @testable false
 * @covered-by src/script/views/base/component.mjs::ViewComponent
 * @covered-by src/script/elements/base/baseForm.mjs::BaseForm
 * @reason transient UI feedback helper exercised through form/component flows
 */
const briefMessageTimers = new WeakMap();

/**
 * @testable false
 * @covered-by src/script/elements/base/baseForm.mjs::BaseForm
 * @covered-by src/script/views/base/component.mjs::ViewComponent
 * @reason transient status feedback is exercised through form and component flows
 */
const showBriefly = (element, content, duration = 1500) => {
	clearTimeout(briefMessageTimers.get(element));
	void withTransition(
		() => {
			element.replaceChildren(content);
			element.dataset.visible = "true";
		},
		{ label: "brief-message-show" },
	);

	const timer = setTimeout(() => {
		briefMessageTimers.delete(element);
		void withTransition(
			() => {
				element.dataset.visible = "false";
				element.replaceChildren();
			},
			{ label: "brief-message-hide" },
		);
	}, duration);
	briefMessageTimers.set(element, timer);
};

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_debounce_cancel_prevents_delayed_callback
 * @pair async-query:debounce-teardown
 */
const debounce = (func, wait) => {
	let timeout = null;
	/**
	 * @testable false
	 * @covered-by src/script/shared/utilities.mjs::debounce
	 * @reason callable wrapper behavior is exercised through the debounce contract
	 */
	const debounced = function (...args) {
		clearTimeout(timeout);
		timeout = setTimeout(() => {
			timeout = null;
			func.apply(this, args);
		}, wait);
	};
	debounced.cancel = () => {
		clearTimeout(timeout);
		timeout = null;
	};
	return debounced;
};

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_wait_for_attribute_resolves_and_cleans_up_observers
 * @matrix frontend-utilities : cleanup mutation-observer
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
	if (Array.isArray(obj)) {
		return obj.map((value) => _sortObject(value));
	}
	if (obj === null || typeof obj !== "object") {
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
 * @matrix frontend-utilities : array-order deep-equality
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
			setAiSettings: "/l/set-ai-settings",
		};
	},
	SiteAdministrators: () => {
		return {
			promote: "/l/site-administrators",
			demote: (key) => `/l/site-administrators/${key}`,
		};
	},
	SiteDeployment: () => {
		return {
			setDeploymentSettings: "/l/set-deployment-settings",
		};
	},
	SiteImage: () => {
		return {
			setSiteImage: "/l/set-site-image",
		};
	},
	SiteMaintenance: () => {
		return {
			siteConfiguration: "/l/site-configuration",
			siteUpdate: "/l/site-update",
			rebuildCache: "/l/rebuild-cache",
		};
	},
	SiteSettings: () => {
		return {
			siteSettings: "/l/site-settings",
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
		bar: "/l/search-bar",
		page: "/l/search-page",
	},
	linkPreview: "/l/preview",
	location: "/l/search-location",
	facet: (index) => {
		return `/l/search-index/${index}`;
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
	delete: (key) => `/l/delete/${key}`,
	toggleStar: (key) => {
		return `/l/toggle-star/${key}`;
	},
	activity: (key) => `/l/activity/${key}`,
	poll: "/l/poll",
	notifications: "/l/notifications",
	messages: {
		conversations: "/l/messages/conversations",
		history: (key) => `/l/messages/conversations/${key}`,
		send: "/l/messages",
		read: (key) => `/l/messages/conversations/${key}/read`,
		remove: (key) => `/l/messages/${key}`,
		clearModal: (key) => `/l/messages/conversations/${key}/delete`,
	},
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
	sync: "/l/sync",
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
 * @matrix csrf request-errors : retry-classification
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
 * @matrix cache : conditional-response dom-refresh etag invalidation reload
 * @matrix deferred-jobs : conditional-response etag
 * @matrix edited-entity-notice : acknowledgement multiple-entities response-headers
 * @matrix request : acknowledgement conditional-response dom-refresh etag invalidation multiple-entities reload response-headers
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
 * @matrix edited-entity-notice : non-invasive-probe reload-fallback
 * @matrix request-errors : ajax-upload non-invasive-probe proxy-text-error reload-fallback
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
			});
		return null;
	}
};

/**
 * @testable true
 * @tests tests_js/test_009_request_csrf.py::test_concurrent_stale_writes_share_server_controlled_token_refresh
 * @matrix csrf : concurrent-refresh stale-token
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
 * @tests tests_js/test_009_request_csrf.py::test_request_preserves_structured_validation_error
 * @tests tests_js/test_009_request_csrf.py::test_request_preserves_plain_validation_error
 * @matrix deferred-jobs request : post-headers
 * @matrix polling : diagnostics structured-validation
 * @matrix request-errors : diagnostics plain-validation structured-validation
 * @pair request:abort-signal
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
		signal = undefined,
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

/**
 * @testable false
 * @covered-by src/script/views/base/services.mjs::initializeCoreServices
 * @reason idle scheduling is an implementation detail of deferred service startup
 */
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
		this.copyResetTimers = new Map();
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

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_shell_intercepts_interactions_before_deferred_services
	 * @pair startup:performance-marks
	 */
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
				const { PollingCoordinator } = await import('./polling.js?v=bd163a0f');
				return this._destroyed ? null : new PollingCoordinator(this).init();
			},
		);
	}

	ensureSearchBox() {
		return this._loadShellManager("_searchPromise", "SearchBox", async () => {
			const search = document.querySelector("[lp-search]");
			if (!search) return null;
			const { SearchBox } = await import('./search.js?v=bd163a0f');
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
				const { Notifications } = await import('./notifications.js?v=bd163a0f');
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
	 * @matrix startup : first-interaction single-flight
	 * @pair search:navbar-results
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

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_shell_intercepts_interactions_before_deferred_services
	 * @pair startup:performance-marks
	 */
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
		const copyButton = event.target?.closest?.(
			"[data-role='manual-command-copy']",
		);
		if (copyButton) {
			event.preventDefault();
			void this.copyCommand(copyButton);
			return;
		}
		this._click(event);
	}

	_click() {}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_installation_commands_are_copyable_and_scroll_on_mobile
	 * @tests tests_e2e/008_users/test_008d_admin_data_protection.py::test_backups_tab_reveals_static_status_panel
	 * @tests tests_js/test_038_startup_specializations.py::test_command_copy_falls_back_when_clipboard_is_unavailable
	 * @matrix manual admin : clipboard-fallback command-copy
	 */
	async copyCommand(button) {
		const command = button
			.closest("[data-role='manual-command-shell']")
			?.querySelector("[data-role='manual-command'] code")?.textContent;
		if (!command) return;

		let copied = false;
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(command);
				copied = true;
			}
		} catch {
			copied = false;
		}

		if (!copied) {
			const textarea = document.createElement("textarea");
			textarea.value = command;
			textarea.setAttribute("readonly", "");
			textarea.style.position = "fixed";
			textarea.style.opacity = "0";
			document.body.append(textarea);
			textarea.select();
			try {
				copied = document.execCommand("copy");
			} catch {
				copied = false;
			}
			textarea.remove();
			button.focus();
		}

		const resetTimer = this.copyResetTimers.get(button);
		if (resetTimer) clearTimeout(resetTimer);
		button.textContent = copied ? "Copied!" : "Copy failed";
		button.setAttribute(
			"aria-label",
			copied ? "Command copied" : "Command could not be copied",
		);
		this.copyResetTimers.set(
			button,
			setTimeout(() => {
				if (button.isConnected) {
					button.textContent = "Copy";
					button.setAttribute("aria-label", "Copy command");
				}
				this.copyResetTimers.delete(button);
			}, 2000),
		);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_shell_intercepts_interactions_before_deferred_services
	 * @pair forms:submit-interception
	 */
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

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_shell_intercepts_interactions_before_deferred_services
	 * @pair startup:single-flight
	 */
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

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_shell_intercepts_interactions_before_deferred_services
	 * @pair startup:destroy-safety
	 */
	destroy() {
		this._destroyed = true;
		for (const timer of this.copyResetTimers.values()) clearTimeout(timer);
		this.copyResetTimers.clear();
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

export { ENDPOINTS as E, ShellView as S, clearRecentSearchResults as a, whenIdle as b, captureError as c, debounce as d, applyNotificationStateHeader as e, areEqual as f, generateElementId as g, renderNotificationBadge as h, waitForAttribute as i, base64ToUint8Array as j, simpleHash as k, errors as l, markPerformance as m, utilities as n, request as r, showBriefly as s, uint8ArrayToBase64 as u, withTransition as w };
