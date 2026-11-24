const CONDITION_REGISTRY = {
	modify: () => import("./modify.ts"),
	html: () => import("./html.ts"),
	status: () => import("./status.ts"),
	visibility: () => import("./visibility.ts"),
	columns: () => import("./columns.ts"),
	options: () => import("./options.ts"),
};

export const loadCondition = async (builder, condition) => {
	const module = await CONDITION_REGISTRY[condition]();
	return new module.default(builder);
};
