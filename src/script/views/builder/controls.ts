/** The builder template supplies these controls before the view is created. */
export function builderControl(id: string): HTMLElement {
	const element = document.getElementById(id);
	if (!element) throw new Error(`Missing builder control: ${id}`);
	return element;
}
