import Sortable from "sortablejs";
import { STYLES } from "styles";
import { CONFIG } from "../../../config/builder";
import { setIcon } from "../../../shared/icons";

/**
 * @testable infrastructure
 */
export class ComponentsPanel {
	constructor(builder) {
		this.builder = builder;
		this.column = document.getElementById("components-column");
		this.panel = document.getElementById("components-panel");
		this._click = this._click.bind(this);
		this._move = this._move.bind(this);
		this.init();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
	 * @tests tests_js/test_032_todo_element_frontend.py::test_todo_builder_registration_is_task_only
	 * @features forms
	 * @dimensions page-form task-form components
	 */
	init() {
		const componentConfig =
			this.builder.elt.dataset.formType === "page"
				? CONFIG.PAGE_COMPONENTS
				: CONFIG.FORM_COMPONENTS;

		const components = [];

		componentConfig.forEach(({ type, label, icon: iconType = type }) => {
			const component = document.createElement("div");
			component.className = `${STYLES.builder.component}`;
			component.dataset.type = type;

			const icon = component.appendChild(document.createElement("span"));
			setIcon(icon, iconType, "text-form-default");

			const name = component.appendChild(document.createElement("span"));
			name.textContent = label;

			const addButton = component.appendChild(document.createElement("button"));
			addButton.dataset.role = "add";
			addButton.type = "button";
			addButton.title = `Add ${label}`;
			addButton.setAttribute("aria-label", `Add ${label}`);
			addButton.className =
				"ml-auto grid size-6 place-items-center rounded-md text-form-default hover:bg-white hover:outline-2 hover:outline-form-default focus-visible:bg-white focus-visible:outline-2 focus-visible:outline-form-default";

			const addIcon = addButton.appendChild(document.createElement("span"));
			setIcon(addIcon, "add");

			components.push(component);
		});

		this.panel.append(...components);

		this.sortable = Sortable.create(this.panel, {
			group: {
				name: "builder",
				pull: "clone",
				put: false,
			},
			onMove: this._move,
			animation: 150,
			sort: false,
		});

		this.column.addEventListener("click", this._click);
	}

	_move(event) {
		const type = event.dragged.dataset.type;
		if (this.builder.model.hasUniqueElement(type)) {
			this.builder.header.message(
				`Only one ${type} element is allowed per form`,
			);
			return false;
		}

		return true;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_inputs_to_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_fields_to_form
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_signature_field_builder_unique_component
	 * @features forms
	 * @dimensions builder-add-inputs builder-add-fields unique-component
	 */
	_click(event) {
		const button = event.target.closest("[data-role]");
		if (button?.dataset.role === "add") {
			const type = button.closest("[data-type]").dataset.type;
			if (this.builder.model.hasUniqueElement(type)) {
				this.builder.header.message(
					`Only one ${type} element is allowed per form`,
				);
				return;
			}

			const element = this.builder.createElement({ type });
			this.builder.model.sortable.el.appendChild(element);
			this.builder.updateSchemaOrder();
			this.builder.selectElement(element.id);
		}
	}

	destroy() {
		this.column?.removeEventListener("click", this._click);
		this.sortable?.destroy();
		this.sortable = null;
	}
}
