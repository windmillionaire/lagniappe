export class MobileTableControls {
	constructor(attributes) {
		Object.assign(this, attributes);
	}

	get target() {
		return this.view.elt.querySelector("[data-widget='MobileTableControls']");
	}

	async init() {
		const visibility = await this.component.loadWidget("TableVisibility");

		this._syncVisibilityButtons(visibility.visibleColumns);
		this.target.addEventListener("click", (e) => this._handleButtonClick(e));
	}

	postreconcile() {
		const sorting = this.component.widgets.TableSorting;
		if (sorting?.initialized) sorting.refreshRows();
	}

	_syncVisibilityButtons(visibleColumns) {
		this.target
			.querySelectorAll("button[data-toggle='visibility']")
			.forEach((button) => {
				const column = button.closest("[data-column]").dataset.column;
				button.dataset.active = visibleColumns.includes(column)
					? "true"
					: "false";
			});
	}

	_handleButtonClick(e) {
		const button = e.target.closest("button");
		if (!button) return;

		const active = button.dataset.active === "false";
		button.dataset.active = active ? "true" : "false";

		if (button.matches("[data-toggle='visibility']")) {
			this._dispatchVisibilityToggle(button, active);
		} else if (button.matches("[data-toggle='filter']")) {
			this._dispatchFilterToggle(button);
		}
	}

	_dispatchVisibilityToggle(button, active) {
		const event = new CustomEvent("toggle-column-visibility", {
			detail: {
				column: button.closest("[data-column]").dataset.column,
				active: active,
			},
			bubbles: true,
		});
		this.target.dispatchEvent(event);
	}

	_dispatchFilterToggle(button) {
		const event = new CustomEvent("toggle-column-filter", {
			detail: {
				column: button.closest("[data-column]").dataset.column,
			},
			bubbles: true,
		});
		this.target.dispatchEvent(event);
	}
}
