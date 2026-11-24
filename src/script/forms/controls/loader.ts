import type { FormController } from "../controller.ts";

export interface FormControlOptions {
	readonly?: boolean;
	onChange?: () => void;
}

// The Submitter mixin emits selected facet data on its trigger element.
export type FacetsUpdatedEvent = CustomEvent<{
	name: string;
	options: Record<string, { id: string; name: string; label?: string }>;
}>;

type FormControlHost = Pick<
	FormController,
	"target" | "readonly" | "markUnsavedState" | "destroyables" | "_destroyed"
>;

const CONTROLS = {
	"permission-sections": () => import("./permissionSections.ts"),
	"access-restrictions": () => import("./accessRestrictions.ts"),
};

const isFormControl = (
	name: string | undefined,
): name is keyof typeof CONTROLS =>
	name !== undefined && Object.hasOwn(CONTROLS, name);

/**
 * Enhance only controls declared by this form, including its own root.
 * Register ownership before awaiting initialization so teardown also covers
 * partially initialized controls and detached replacements.
 */
export async function initFormControls(form: FormControlHost) {
	const target = form.target;
	const selector = "[data-form-control]";
	const roots = [
		...(target.matches?.(selector) ? [target] : []),
		...(target.querySelectorAll?.<HTMLElement>(selector) ?? []),
	];
	for (const root of roots) {
		const name = root.dataset.formControl;
		if (!isFormControl(name)) throw new Error(`Unknown form control: ${name}`);
		const { default: Control } = await CONTROLS[name]();
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
