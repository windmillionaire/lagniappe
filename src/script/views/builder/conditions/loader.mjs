const CONDITION_REGISTRY = {
	modify: () => import("./modify.mjs"),
	html: () => import("./html.mjs"),
	status: () => import("./status.mjs"),
	visibility: () => import("./visibility.mjs"),
	columns: () => import("./columns.mjs"),
	options: () => import("./options.mjs"),
};

/**
 * @testable infrastructure
 */
export const loadCondition = async (builder, condition) => {
	const module = await CONDITION_REGISTRY[condition]();
	return new module.default(builder);
};
