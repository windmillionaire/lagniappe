import { readFileSync } from "node:fs";
import vm from "node:vm";

function requestUrl(request) {
	return typeof request === "string" ? request : request.url;
}

class CacheMock {
	constructor() {
		this.deletes = [];
		this.entries = new Map();
		this.puts = 0;
	}

	async delete(request) {
		const url = requestUrl(request);
		this.deletes.push(url);
		return this.entries.delete(url);
	}

	async add(request) {
		this.entries.set(requestUrl(request), new Response("offline"));
	}

	async keys(request = null, options = {}) {
		const keys = [...this.entries.keys()];
		if (!request) return keys.map((url) => new Request(url));

		const target = new URL(requestUrl(request));
		return keys
			.filter((url) => {
				const candidate = new URL(url);
				if (options.ignoreSearch) {
					return (
						candidate.origin === target.origin &&
						candidate.pathname === target.pathname
					);
				}
				return candidate.href === target.href;
			})
			.map((url) => new Request(url));
	}

	async match(request) {
		return this.entries.get(requestUrl(request));
	}

	async put(request, response) {
		this.puts += 1;
		this.entries.set(requestUrl(request), response.clone());
	}
}

export function createServiceWorkerContext() {
	const responseCache = new CacheMock();
	const staticCache = new CacheMock();
	const fetchCalls = [];
	const clientMessages = [];
	const deletedCaches = [];
	const listeners = new Map();
	const cacheNames = new Set([
		"static-cache",
		"response-cache",
		"third-party-cache",
	]);
	const context = {
		clearTimeout,
		console,
		deletedCaches,
		fetchCalls,
		clientMessages,
		Headers,
		navigator: { onLine: true },
		Request,
		Response,
		listeners,
		self: {
			addEventListener(type, listener) {
				listeners.set(type, listener);
			},
			clients: {
				matchAll: async () => [
					{
						postMessage(message) {
							clientMessages.push(message);
						},
					},
				],
			},
			location: new URL("https://example.test/"),
			navigator: {},
			Sentry: null,
			skipWaiting: async () => {},
		},
		setTimeout,
		URL,
	};
	context.caches = {
		async delete(name) {
			deletedCaches.push(name);
			return cacheNames.delete(name);
		},
		async keys() {
			return [...cacheNames];
		},
		async has(name) {
			return cacheNames.has(name);
		},
		async open(name) {
			cacheNames.add(name);
			return name === "response-cache" ? responseCache : staticCache;
		},
	};

	vm.createContext(context);
	const browserProtocol = JSON.parse(
		readFileSync("config/browser_protocol.json", "utf8"),
	);
	const workerSource = readFileSync(
		"src/script/sw.template.mjs",
		"utf8",
	).replace("/* __BROWSER_PROTOCOL__ */ null", JSON.stringify(browserProtocol));
	vm.runInContext(workerSource, context);
	vm.runInContext(
		`realCheckForCacheInvalidation = checkForCacheInvalidation;
checkForCacheInvalidation = async () => {};`,
		context,
	);

	return {
		cacheNames,
		clientMessages,
		context,
		deletedCaches,
		fetchCalls,
		listeners,
		responseCache,
		staticCache,
		vm,
	};
}
