const KIB = 1024;

export const STARTUP_BUDGETS = Object.freeze({
	main: 32 * KIB,
	shell: 64 * KIB,
	core: 120 * KIB,
	builder: 224 * KIB,
});

export const SHELL_VIEW_ENTRIES = Object.freeze([
	"manual",
	"results",
	"analytics",
]);

export const CORE_VIEW_ENTRIES = Object.freeze([
	"project",
	"page",
	"home",
	"user",
	"index",
	"file",
	"report",
	"admin",
]);

export const CORE_FORBIDDEN_MODULES = Object.freeze([
	"/shared/offlineQueue.mjs",
	"/shared/sync.mjs",
	"/shared/editWatcher.mjs",
	"/shared/deferredOperations.mjs",
	"/shared/modal.mjs",
	"/elements/notifications.mjs",
	"/elements/entityMenu.mjs",
	"/elements/combobox/",
]);

const chunkMap = (bundle) =>
	new Map(
		Object.values(bundle)
			.filter((item) => item.type === "chunk")
			.map((chunk) => [chunk.fileName, chunk]),
	);

export const staticChunkClosure = (bundle, entryNames) => {
	const chunks = chunkMap(bundle);
	const entries = Object.values(bundle).filter(
		(item) => item.type === "chunk" && item.isEntry,
	);
	const pending = entries
		.filter((entry) => entryNames.includes(entry.name))
		.map((entry) => entry.fileName);
	const closure = new Set();
	while (pending.length) {
		const fileName = pending.pop();
		if (closure.has(fileName)) continue;
		const chunk = chunks.get(fileName);
		if (!chunk) continue;
		closure.add(fileName);
		for (const imported of chunk.imports || []) pending.push(imported);
	}
	return closure;
};

export const closureBytes = (bundle, files) =>
	Array.from(files).reduce((total, fileName) => {
		const item = bundle[fileName];
		return total + (item?.type === "chunk" ? Buffer.byteLength(item.code) : 0);
	}, 0);

const union = (...sets) => new Set(sets.flatMap((set) => [...set]));

const formatKiB = (bytes) => `${(bytes / KIB).toFixed(1)} KiB`;

export const validateStartupBudgets = (bundle) => {
	const main = staticChunkClosure(bundle, ["main"]);
	const failures = [];
	const check = (label, files, limit) => {
		const bytes = closureBytes(bundle, files);
		if (bytes > limit) {
			failures.push(`${label}: ${formatKiB(bytes)} > ${formatKiB(limit)}`);
		}
	};

	check("main boot closure", main, STARTUP_BUDGETS.main);
	for (const entry of SHELL_VIEW_ENTRIES) {
		check(
			`main + shell view ${entry}`,
			union(main, staticChunkClosure(bundle, [entry])),
			STARTUP_BUDGETS.shell,
		);
	}
	for (const entry of CORE_VIEW_ENTRIES) {
		const view = staticChunkClosure(bundle, [entry]);
		check(`main + Core view ${entry}`, union(main, view), STARTUP_BUDGETS.core);
		const modules = new Set(
			[...view].flatMap((fileName) =>
				Object.keys(bundle[fileName]?.modules || {}),
			),
		);
		for (const forbidden of CORE_FORBIDDEN_MODULES) {
			const match = [...modules].find((id) => id.includes(forbidden));
			if (match)
				failures.push(`Core view ${entry} statically includes ${match}`);
		}
	}
	check(
		"Builder view",
		staticChunkClosure(bundle, ["builder"]),
		STARTUP_BUDGETS.builder,
	);

	if (failures.length) {
		throw new Error(
			`Frontend startup budgets failed:\n- ${failures.join("\n- ")}`,
		);
	}
};

export const startupBudget = () => ({
	name: "startup-budget",
	generateBundle(_options, bundle) {
		validateStartupBudgets(bundle);
	},
});
