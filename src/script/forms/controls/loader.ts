const CONTROLS = {
	"permission-sections": () => import("./permissionSections.ts"),
	"access-restrictions": () => import("./accessRestrictions.ts"),
};

/**
 * Enhance only controls declared by this form, including its own root.
 * Register ownership before awaiting initialization so teardown also covers
 * partially initialized controls and detached replacements.
 */
export async function initFormControls(form) {
	const target = form.target;
	const selector = "[data-form-control]";
	const roots = [
		...(target.matches?.(selector) ? [target] : []),
		...(target.querySelectorAll?.(selector) ?? []),
	];
	for (const root of roots) {
		const load = CONTROLS[root.dataset.formControl];
		if (!load)
			throw new Error(`Unknown form control: ${root.dataset.formControl}`);
		const { default: Control } = await load();
		if (form._destroyed) return;
		const control = new Control(root, {
			readonly: form.readonly,
			onChange: form.markUnsavedState,
		});
		form.destroyables.push(control);
		await control.init();
		if (form._destroyed) {
			control.destroy();
			return;
		}
	}
}
