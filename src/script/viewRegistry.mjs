const BUILD_ID =
	typeof __BUILD_ID__ === "undefined" ? "development" : __BUILD_ID__;

/**
 * One registry owns both build inputs and runtime view selection. `entry` is a
 * stable emitted filename; `source` is consumed by the Rollup configuration.
 */
export const VIEW_REGISTRY = Object.freeze({
	project: { entry: "project", source: "./views/project.mjs" },
	page: { entry: "page", source: "./views/page.mjs" },
	home: { entry: "home", source: "./views/home.mjs" },
	manual: { entry: "manual", source: "./views/manual.mjs" },
	user: { entry: "user", source: "./views/user.mjs" },
	form: { entry: "index", source: "./views/base/index.mjs" },
	category: { entry: "index", source: "./views/base/index.mjs" },
	task: { entry: "index", source: "./views/base/index.mjs" },
	builder: { entry: "builder", source: "./views/builder/builder.mjs" },
	results: { entry: "results", source: "./views/results.mjs" },
	file: { entry: "file", source: "./views/file.mjs" },
	report: { entry: "report", source: "./views/report.mjs" },
	analytics: { entry: "analytics", source: "./views/analytics.mjs" },
	admin: { entry: "admin", source: "./views/admin.mjs" },
});

export const VIEW_ENTRIES = Object.freeze(
	Object.fromEntries(
		Object.values(VIEW_REGISTRY).map(({ entry, source }) => [entry, source]),
	),
);

export const viewEntryUrl = (kind) => {
	const entry = VIEW_REGISTRY[kind]?.entry;
	return entry ? `./chunks/views/${entry}.js?v=${BUILD_ID}` : null;
};

export const loadView = (kind) => {
	const url = viewEntryUrl(kind);
	if (!url) return null;
	return import(url);
};
