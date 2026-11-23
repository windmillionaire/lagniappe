/**
 * Compare field representations without importing form controllers or UI.
 *
 */
export const compatibleField = (before, after) => {
	if (!before || !after) return false;
	const kind = (field) =>
		field.type === "input"
			? field.input || "text"
			: field.type === "link"
				? field.location || "out"
				: field.type;
	if (
		kind(before) !== kind(after) ||
		Boolean(before.multiple) !== Boolean(after.multiple)
	)
		return false;
	if (
		before.options?.some(
			({ value }) => !after.options?.some((option) => option.value === value),
		)
	)
		return false;
	return !before.columns?.some(
		(column) =>
			!compatibleField(
				column,
				after.columns?.find((item) => item.id === column.id),
			),
	);
};
export const incompatibleSchema = (before, after) =>
	(before || []).some(
		(field) =>
			!compatibleField(
				field,
				(after || []).find((item) => item.id === field.id),
			),
	);
