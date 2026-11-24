import Sortable, { type MoveEvent } from "sortablejs";
import { STYLES } from "../../../generated/styles.mjs";
import { setIcon } from "../../../shared/icons.ts";
import type { FieldType } from "../../../types/forms.d.ts";
import type FormBuilder from "../builder.ts";
import { CONFIG } from "../config.ts";
import { builderControl } from "../controls.ts";

export class ComponentsPanel {
	declare builder: FormBuilder;
	declare column: HTMLElement;
	declare panel: HTMLElement;
	declare sortable: Sortable | null;

	constructor(builder: FormBuilder) {
		this.builder = builder;
		this.column = builderControl("components-column");
		this.panel = builderControl("components-panel");
		this._click = this._click.bind(this);
		this._move = this._move.bind(this);
		this.init();
	}

	init() {
		const componentConfig =
			this.builder.elt.dataset.formType === "page"
				? CONFIG.PAGE_COMPONENTS
				: CONFIG.FORM_COMPONENTS;

		const components: HTMLDivElement[] = [];

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

	_move(event: MoveEvent) {
		const type = event.dragged.dataset.type;
		if (this.builder.model.hasUniqueElement(type)) {
			this.builder.header.message(
				`Only one ${type} element is allowed per form`,
			);
			return false;
		}

		return true;
	}

	_click(event: MouseEvent) {
		const button = (event.target as Element | null)?.closest<HTMLElement>(
			"[data-role]",
		);
		if (button?.dataset.role === "add") {
			const type = button.closest<HTMLElement>("[data-type]")?.dataset.type as
				| FieldType
				| undefined;
			if (!type) return;
			if (this.builder.model.hasUniqueElement(type)) {
				this.builder.header.message(
					`Only one ${type} element is allowed per form`,
				);
				return;
			}

			const sortable = this.builder.model.sortable;
			if (!sortable) return;
			const element = this.builder.createElement({ type });
			sortable.el.appendChild(element);
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
