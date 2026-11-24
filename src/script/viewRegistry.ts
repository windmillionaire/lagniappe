import type { ViewRoot, ViewSyncOptions } from "./views/base/shell.ts";

interface ActiveView {
	_destroyed: boolean;
	init(): Promise<unknown>;
	publish?(): unknown;
	sync?(options?: ViewSyncOptions): Promise<unknown>;
}

interface ViewModule {
	default: new (root: ViewRoot) => ActiveView;
}

const BUILD_ID =
	typeof __BUILD_ID__ === "undefined" ? "development" : __BUILD_ID__;

/**
 * One registry owns both build inputs and runtime view selection. `entry` is a
 * stable emitted filename; `source` is consumed by the Rollup configuration.
 */
export type { ActiveView };

export const VIEW_REGISTRY = Object.freeze({
	project: { entry: "project", source: "./views/project.ts" },
	page: { entry: "page", source: "./views/page.ts" },
	home: { entry: "home", source: "./views/home.ts" },
	manual: { entry: "manual", source: "./views/manual.ts" },
	help: { entry: "help", source: "./views/base/shell.ts" },
	user: { entry: "user", source: "./views/user.ts" },
	form: { entry: "index", source: "./views/base/index.ts" },
	category: { entry: "index", source: "./views/base/index.ts" },
	task: { entry: "index", source: "./views/base/index.ts" },
	builder: { entry: "builder", source: "./views/builder/builder.ts" },
	results: { entry: "results", source: "./views/results.ts" },
	file: { entry: "file", source: "./views/file.ts" },
	report: { entry: "report", source: "./views/report.ts" },
	analytics: { entry: "analytics", source: "./views/analytics.ts" },
	admin: { entry: "admin", source: "./views/admin.ts" },
	messages: { entry: "messages", source: "./views/messages.ts" },
});

export const VIEW_ENTRIES = Object.freeze(
	Object.fromEntries(
		Object.values(VIEW_REGISTRY).map(({ entry, source }) => [entry, source]),
	),
);

export const viewEntryUrl = (kind: string | null | undefined) => {
	if (!kind || !Object.hasOwn(VIEW_REGISTRY, kind)) return null;
	const entry = VIEW_REGISTRY[kind as keyof typeof VIEW_REGISTRY].entry;
	return entry ? `./chunks/views/${entry}.js?v=${BUILD_ID}` : null;
};

export const loadView = (
	kind: string | null | undefined,
): Promise<ViewModule> | null => {
	const url = viewEntryUrl(kind);
	if (!url) return null;
	return import(url);
};
