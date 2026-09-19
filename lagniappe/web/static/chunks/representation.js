/*! Third-party licenses: /third-party-licenses.txt */
/**
 * Compare field representations without importing form controllers or UI.
 *
 * @testable true
 * @tests tests_js/test_036c_form_migrations.py::test_incompatible_local_values_require_review
 * @matrix form-migration : stale-input representation-aware
 */
const compatibleField = (before, after) => {
	if (!before || !after) return false;
	/** @testable infrastructure */
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
/**
 * @testable true
 * @tests tests_js/test_036c_form_migrations.py::test_incompatible_local_values_require_review
 * @matrix form-migration : stale-input representation-aware
 */
const incompatibleSchema = (before, after) =>
	(before || []).some(
		(field) =>
			!compatibleField(
				field,
				(after || []).find((item) => item.id === field.id),
			),
	);

export { compatibleField as c, incompatibleSchema as i };
