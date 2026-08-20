const CONDITION_REGISTRY = {
	html: () => import("./html"),
	status: () => import("./status"),
	visibility: () => import("./visibility"),
	columns: () => import("./columns"),
	options: () => import("./options"),
};

/**
 * @testable infrastructure
 */
export const loadCondition = async (builder, condition) => {
	const module = await CONDITION_REGISTRY[condition]();
	return new module.default(builder);
};
