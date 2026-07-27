/**
 * @testable infrastructure
 */
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

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_controls_open_with_task_columns
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_controls_open_with_page_columns
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_controls_handle_form_columns
	 * @features table-controls
	 * @dimensions mobile-controls columns form-columns
	 */
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

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_visibility_toggle_hides_column
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_visibility_toggle_hides_column
	 * @features table-controls
	 * @dimensions mobile-controls column-visibility
	 */
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

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_filter_button_opens_sorting_panel
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_filter_button_opens_sorting_panel
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_controls_handle_form_columns
	 * @features table-controls
	 * @dimensions mobile-controls sorting form-columns
	 */
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
