import type { ToggleColumnFilterDetail } from "../../elements/base/baseTable.ts";
import type ViewComponent from "../../views/base/component.ts";
import type { TableWidgets } from "./types.d.ts";
import type { TableVisibilityToggle } from "./visibilityState.ts";

interface MobileTableControlAttributes {
	view: { elt: HTMLElement };
	component: ViewComponent & { widgets: TableWidgets };
}

export class MobileTableControls {
	declare view: MobileTableControlAttributes["view"];
	declare component: MobileTableControlAttributes["component"];

	constructor(attributes: MobileTableControlAttributes) {
		Object.assign(this, attributes);
	}

	get target() {
		return this.view.elt.querySelector<HTMLElement>(
			"[data-widget='MobileTableControls']",
		);
	}

	async init() {
		await this.component.loadWidget("TableVisibility");
		const visibility = this.component.widgets.TableVisibility;

		this._syncVisibilityButtons(visibility?.visibleColumns ?? []);
		this.target?.addEventListener("click", (e) => this._handleButtonClick(e));
	}

	postreconcile() {
		const sorting = this.component.widgets.TableSorting;
		if (sorting?.initialized) sorting.refreshRows?.();
	}

	_syncVisibilityButtons(visibleColumns: readonly string[]) {
		this.target
			?.querySelectorAll<HTMLButtonElement>("button[data-toggle='visibility']")
			.forEach((button) => {
				const column =
					button.closest<HTMLElement>("[data-column]")?.dataset.column;
				button.dataset.active =
					column !== undefined && visibleColumns.includes(column)
						? "true"
						: "false";
			});
	}

	_handleButtonClick(e: MouseEvent) {
		const button =
			e.target instanceof Element ? e.target.closest("button") : null;
		if (!button) return;

		const active = button.dataset.active === "false";
		button.dataset.active = active ? "true" : "false";

		if (button.matches("[data-toggle='visibility']")) {
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
