import { withTransition } from "./transitions.ts";

export const simpleHash = (str: string) => {
	let hash = 0;
	for (let i = 0; i < str.length; i++) {
		const char = str.charCodeAt(i);
		hash = (hash << 5) - hash + char;
	}
	return (hash >>> 0).toString(36).padStart(7, "0");
};

export const generateElementId = (type: string) => {
	return `${type}-${crypto.randomUUID().split("-")[0]}`;
};

const briefMessageTimers = new WeakMap<
	HTMLElement,
	ReturnType<typeof setTimeout>
>();

export const showBriefly = (
	element: HTMLElement,
	content: Node | string,
	duration = 1500,
) => {
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

export const debounce = <This, Args extends unknown[]>(
	func: (this: This, ...args: Args) => unknown,
	wait: number,
) => {
	let timeout: ReturnType<typeof setTimeout> | undefined;
	const debounced = function (this: This, ...args: Args) {
		clearTimeout(timeout);
		timeout = setTimeout(() => {
			timeout = undefined;
			func.apply(this, args);
		}, wait);
	};
	debounced.cancel = () => {
		clearTimeout(timeout);
		timeout = undefined;
	};
	return debounced;
};

export function waitForAttribute(
	element: Element,
	attributeName: string,
	timeout = 10000,
): Promise<string | null> {
	if (element.hasAttribute(attributeName)) {
		return Promise.resolve(element.getAttribute(attributeName));
	}

	return new Promise((resolve, reject) => {
		let observer: MutationObserver | null = null;
		let timeoutId: ReturnType<typeof setTimeout> | undefined;

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

function _sortObject(obj: unknown): unknown {
	if (Array.isArray(obj)) {
		return obj.map((value: unknown) => _sortObject(value));
	}
	if (obj === null || typeof obj !== "object") {
		return obj;
	}
	const record = obj as Record<string, unknown>;
	return Object.keys(record)
		.sort()
		.reduce<Record<string, unknown>>((result, key) => {
			result[key] = _sortObject(record[key]);
			return result;
		}, {});
}

export const areEqual = (a: unknown, b: unknown) => {
	return JSON.stringify(_sortObject(a)) === JSON.stringify(_sortObject(b));
};

export const base64ToUint8Array = (base64: string) => {
	const bin = atob(base64);
	const bytes = new Uint8Array(bin.length);
	for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
	return bytes;
};

export const uint8ArrayToBase64 = (bytes: Uint8Array) => {
	let bin = "";
	for (let i = 0; i < bytes.byteLength; i++)
		bin += String.fromCharCode(bytes[i]);
	return btoa(bin);
};
