import type { ToggleColumnFilterDetail } from "../../elements/base/baseTable.ts";
import type ViewComponent from "../../views/base/component.ts";
import type { TableWidgets } from "./types.d.ts";
import type { TableVisibilityToggle } from "./visibilityState.ts";

interface MobileTableControlAttributes {
	view: { elt: HTMLElement; mobile?: boolean };
	component: ViewComponent & { widgets: TableWidgets };
	visible?: boolean;
}

export class MobileTableControls {
	declare view: MobileTableControlAttributes["view"];
	declare component: MobileTableControlAttributes["component"];
	declare visible?: boolean;

	constructor(attributes: MobileTableControlAttributes) {
		Object.assign(this, attributes);
	}

	get target() {
		return this.view.elt.querySelector<HTMLElement>(
			"[data-widget='MobileTableControls']",
		);
	}

	async init() {
		await Promise.all([
			this.component.loadWidget("TableVisibility"),
			this.component.loadWidget("TableSorting"),
		]);
		this.sync();
		this.target?.addEventListener("click", (e) => this._handleButtonClick(e));
	}

	sync() {
		const visibility = this.component.widgets.TableVisibility;
		this._syncVisibilityButtons(visibility?.visibleColumns ?? []);
		const sorting = this.component.widgets.TableSorting;
		if (sorting && !sorting.initialized) sorting.init?.();
	}

	postreconcile() {
		if (this.target && this.visible !== undefined) {
			this.target.dataset.visible = this.visible ? "true" : "false";
		}
		this.sync();
		const sorting = this.component.widgets.TableSorting;
		if (sorting?.initialized) sorting.refreshRows?.();
	}

	_syncVisibilityButtons(visibleColumns: readonly string[]) {
		this.target
			?.querySelectorAll<HTMLButtonElement>("button[data-toggle='visibility']")
			.forEach((button) => {
				const column =
					button.closest<HTMLElement>("[data-column]")?.dataset.column;
				const active = column !== undefined && visibleColumns.includes(column);
				button.dataset.active = active ? "true" : "false";
				button.setAttribute("aria-pressed", active ? "true" : "false");
			});
	}

	_handleButtonClick(e: MouseEvent) {
		const button =
			e.target instanceof Element ? e.target.closest("button") : null;
		if (!button) return;

		if (button.matches("[data-toggle='visibility']")) {
			const active = button.dataset.active === "false";
			button.dataset.active = active ? "true" : "false";
			button.setAttribute("aria-pressed", active ? "true" : "false");
			this._dispatchVisibilityToggle(button, active);
		} else if (button.matches("[data-toggle='filter']")) {
			this._dispatchFilterToggle(button);
		}
	}

	_dispatchVisibilityToggle(button: HTMLButtonElement, active: boolean) {
		const event = new CustomEvent<TableVisibilityToggle>(
			"toggle-column-visibility",
			{
				detail: {
					column: button.closest<HTMLElement>("[data-column]")?.dataset.column,
					active: active,
				},
				bubbles: true,
			},
		);
		this.target?.dispatchEvent(event);
	}

	_dispatchFilterToggle(button: HTMLButtonElement) {
		const event = new CustomEvent<Omit<ToggleColumnFilterDetail, "button">>(
			"toggle-column-filter",
			{
				detail: {
					column: button.closest<HTMLElement>("[data-column]")?.dataset.column,
				},
				bubbles: true,
			},
		);
		this.target?.dispatchEvent(event);
	}
}
