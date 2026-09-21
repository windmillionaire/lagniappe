import assert from "node:assert/strict";
import * as idb from "fake-indexeddb";
import { JSDOM, VirtualConsole } from "jsdom";
import { unexpectedFetch } from "./bootstrap.mjs";

const nativeData = Object.fromEntries(
	["File", "Blob", "FormData", "structuredClone"].map((name) => [
		name,
		globalThis[name],
	]),
);

function replace(t, target, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(target, name);
	Object.defineProperty(target, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(target, name, descriptor);
		else delete target[name];
	});
}

export function createBrowser(
	t,
	{
		html = "<!doctype html><body></body>",
		url = "https://lagniappe.test/",
		formData = "dom",
	} = {},
) {
	assert.ok(
		["dom", "native"].includes(formData),
		"formData must be dom or native",
	);
	const errors = [];
	const virtualConsole = new VirtualConsole();
	virtualConsole.on("jsdomError", (error) => errors.push(error));
	const dom = new JSDOM(html, { url, virtualConsole, pretendToBeVisual: true });
	const { window } = dom;
	const globals = [
		"window",
		"document",
		"navigator",
		"location",
		"localStorage",
		"sessionStorage",
		"DOMParser",
		"Node",
		"Element",
		"HTMLElement",
		"HTMLFormElement",
		"HTMLInputElement",
		"Event",
		"CustomEvent",
		"EventTarget",
		"MouseEvent",
		"KeyboardEvent",
		"MutationObserver",
		"DOMException",
		"AbortController",
		"AbortSignal",
		"getComputedStyle",
		"requestAnimationFrame",
		"cancelAnimationFrame",
	];
	for (const name of globals) {
		const value = [
			"getComputedStyle",
			"requestAnimationFrame",
			"cancelAnimationFrame",
		].includes(name)
			? window[name].bind(window)
			: window[name];
		replace(t, globalThis, name, value);
	}
	for (const name of ["FormData", "File", "Blob"]) {
		const value = formData === "native" ? nativeData[name] : window[name];
		replace(t, globalThis, name, value);
		if (formData === "native") replace(t, window, name, value);
	}
	for (const name of [
		"Request",
		"Response",
		"Headers",
		"structuredClone",
		"fetch",
	])
		window[name] = globalThis[name];
	// jsdom XHR/WebSocket can initiate networking even with subresources disabled.
	for (const name of ["XMLHttpRequest", "WebSocket"]) {
		const blocked = class {
			constructor() {
				const error = new Error(
					`Unexpected ${name}; provide an explicit test boundary`,
				);
				errors.push(error);
				throw error;
			}
		};
		replace(t, globalThis, name, blocked);
		window[name] = blocked;
	}
	t.after(() => {
		window.close();
		assert.deepEqual(
			errors,
			[],
			"Unhandled jsdom errors (use an explicit boundary for unsupported browser APIs)",
		);
	});
	return dom;
}

export function installIndexedDB(t, window = globalThis.window) {
	const factory = new idb.IDBFactory();
	const connections = new Set();
	const open = factory.open.bind(factory);
	factory.open = (...args) => {
		const request = open(...args);
		request.addEventListener("success", () => connections.add(request.result));
		return request;
	};
	for (const target of new Set([globalThis, window].filter(Boolean))) {
		replace(t, target, "indexedDB", factory);
		replace(t, target, "structuredClone", nativeData.structuredClone);
		for (const [name, value] of Object.entries(idb))
			if (name.startsWith("IDB")) replace(t, target, name, value);
	}
	t.after(() => {
		for (const db of connections) db.close();
	});
	return factory;
}

export function mockFetch(t, handler, window = globalThis.window) {
	const calls = [];
	const fetch = t.mock.fn(async (input, init = {}) => {
		const url = new URL(
			typeof input === "string" ? input : input?.url || String(input),
			window?.location.href || "https://lagniappe.test/",
		);
		const call = {
			url,
			input,
			init,
			method: init.method || input?.method || "GET",
		};
		calls.push(call);
		const signal = init.signal || input?.signal;
		if (signal?.aborted) throw signal.reason;
		let abort;
		try {
			const response = Promise.resolve(handler(call));
			const result = signal
				? await Promise.race([
						response,
						new Promise((_, reject) => {
							abort = () => reject(signal.reason);
							signal.addEventListener("abort", abort, { once: true });
							if (signal.aborted) abort();
						}),
					])
				: await response;
			return result === undefined ? unexpectedFetch(input) : result;
		} finally {
			if (abort) signal.removeEventListener("abort", abort);
		}
	});
	replace(t, globalThis, "fetch", fetch);
	if (window) replace(t, window, "fetch", fetch);
	return { fetch, calls };
}

export function useClock(t, { now = 0 } = {}) {
	t.mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now });
	if (globalThis.window) {
		for (const name of [
			"Date",
			"setTimeout",
			"clearTimeout",
			"setInterval",
			"clearInterval",
		])
			replace(t, window, name, globalThis[name]);
	}
	return t.mock.timers;
}
