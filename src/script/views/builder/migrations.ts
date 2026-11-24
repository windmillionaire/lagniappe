import type { FormFieldSchema, FormSchema } from "../../types/forms.d.ts";
import type { FieldKind } from "./types.ts";

export const fieldKind = (field: FormFieldSchema): FieldKind =>
	field.type === "input"
		? field.input || "text"
		: field.type === "link"
			? field.location || "out"
			: field.type === "select" && field.multiple
				? "multiple"
				: field.type;

export const needsMigration = (
	before: FormSchema,
	after: FormSchema,
): boolean =>
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

export const repairConditions = (schema: FormSchema) => {
	let removed = 0;
	for (const field of schema)
		for (const key of ["visibility", "status"] as const) {
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
