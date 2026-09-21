/**
 * @testable true
 * @tests tests_js/test_036c_form_migrations.mjs::test_schema_changes_and_condition_repairs_are_local
 * @matrix form-migration : schema-only stable-identity conditions
 */
export const fieldKind = (field) =>
	field.type === "input"
		? field.input || "text"
		: field.type === "link"
			? field.location || "out"
			: field.type === "select" && field.multiple
				? "multiple"
				: field.type;

/**
 * @testable true
 * @tests tests_js/test_036c_form_migrations.mjs::test_schema_changes_and_condition_repairs_are_local
 * @matrix form-migration : schema-only stable-identity
 */
export const needsMigration = (before, after) =>
	before.some((field) => {
		if (["html", "status"].includes(field.type)) return false;
		const target = after.find(({ id }) => id === field.id);
		if (!target) return true;
		if (fieldKind(field) !== fieldKind(target)) return true;
		if (
			field.options?.some(
				({ value }) =>
					!target.options?.some((option) => option.value === value),
			)
		)
			return true;
		return field.columns
			? needsMigration(field.columns, target.columns || [])
			: false;
	});

/**
 * @testable true
 * @tests tests_js/test_036c_form_migrations.mjs::test_schema_changes_and_condition_repairs_are_local
 * @matrix form-migration : conditions
 */
export const repairConditions = (schema) => {
	let removed = 0;
	for (const field of schema)
		for (const key of ["visibility", "status"]) {
			if (!Array.isArray(field[key])) continue;
			field[key] = field[key].filter((condition) => {
				const source = schema.find(({ id }) => id === condition.id);
				const selected = condition.value ?? condition.checked;
				const values = Array.isArray(selected) ? selected : [selected];
				const supported =
					source &&
					(["radio", "select"].includes(source.type)
						? values.every((value) =>
								source.options?.some((option) => option.value === value),
							)
						: source.type === "checkbox" && condition.type === "checkbox");
				if (supported) condition.type = source.type;
				else removed++;
				return supported;
			});
		}
	return removed;
};
