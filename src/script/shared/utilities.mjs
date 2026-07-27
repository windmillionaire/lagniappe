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
export const withTransition = (callback) => {
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
export const showBriefly = (element, content) => {
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
export const debounce = (func, wait) => {
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
 * @reason browser cache cleanup helper is exercised through service-worker and server-change refresh flows
 */
export const clearRecentSearchResults = () => {
	const recentKeys = Array.from({ length: localStorage.length }, (_, index) =>
		localStorage.key(index),
	).filter((key) => key?.startsWith("recent-"));

	recentKeys.forEach((key) => {
		localStorage.removeItem(key);
	});
};
