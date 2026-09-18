import { withTransition } from "./transitions";

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
