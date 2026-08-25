import { captureError, isSkippedViewTransitionError } from "./errors";

/**
 * @testable false
 * @reason browser hash helper is exercised through builder condition IDs, not directly
 */
export const simpleHash = (str) => {
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
export const generateElementId = (type) => {
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
	if (typeof __BUILD_ID__ !== "undefined") return;

	const duration = performance.now() - started;
	if (duration <= 50) return;
	console.warn(
		`View transition commit "${label}" took ${duration.toFixed(1)}ms.`,
	);
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
		if (started !== null) reportSlowCommit(label, started);
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
export const withTransition = (callback, { label = "unlabeled" } = {}) => {
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
export const showBriefly = (element, content, duration = 1500) => {
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
export const debounce = (func, wait) => {
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
export function waitForAttribute(element, attributeName, timeout = 10000) {
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
export const areEqual = (a, b) => {
	return JSON.stringify(_sortObject(a)) === JSON.stringify(_sortObject(b));
};

/**
 * @testable false
 * @reason Yjs payload decoding is exercised through collaborative editor sync
 */
export const base64ToUint8Array = (base64) => {
	const bin = atob(base64);
	const bytes = new Uint8Array(bin.length);
	for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
	return bytes;
};

/**
 * @testable false
 * @reason Yjs payload encoding is exercised through collaborative editor sync
 */
export const uint8ArrayToBase64 = (bytes) => {
	let bin = "";
	for (let i = 0; i < bytes.byteLength; i++)
		bin += String.fromCharCode(bytes[i]);
	return btoa(bin);
};

/**
 * @testable false
 * @reason browser cache cleanup helper is exercised through service-worker and polling refresh flows
 */
export const clearRecentSearchResults = () => {
	const recentKeys = Array.from({ length: localStorage.length }, (_, index) =>
		localStorage.key(index),
	).filter((key) => key?.startsWith("recent-"));

	recentKeys.forEach((key) => {
		localStorage.removeItem(key);
	});
};
