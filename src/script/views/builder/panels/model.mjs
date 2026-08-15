import Sortable from "sortablejs";
import { STYLES } from "styles";
import { CONFIG } from "../../../config/builder";
import { primitives } from "../../../elements/primitives";

/**
 * @testable infrastructure
 */
export class ModelPanel {
	constructor(builder) {
		this.builder = builder;
		this.panel = document.getElementById("model-panel");
		this.defaultPanel = document.getElementById("default-panel");
		this.uniqueElements = ["status", "signature", "bookmark"];
		this.defaultElements = ["name", "description"];
		this._addElement = this._addElement.bind(this);
		this._moveElement = this._moveElement.bind(this);
	}

	get elements() {
		return Array.from(this.panel.querySelectorAll(".form-element"));
	}

	get defaults() {
		return Array.from(this.defaultPanel.querySelectorAll(".form-element"));
	}

	show() {
		this.defaultPanel.dataset.visible =
			this.defaults.length > 0 ? "true" : "false";
		this.panel.dataset.visible = "true";
	}

	hide() {
		this.defaultPanel.dataset.visible = "false";
		this.panel.dataset.visible = "false";
	}

	init() {
		const elements = Array.from(this.builder.elements.values());
		const defaults = elements.filter((element) =>
			this.defaultElements.includes(element.schema.id),
		);
		if (defaults.length > 0) {
			this.defaultPanel.dataset.visible = "true";
		}

		elements.forEach((element) => {
			if (this.defaultElements.includes(element.schema.id)) {
				Array.from(element.item.querySelectorAll("input, textarea")).forEach(
					(input) => {
						input.remove();
					},
				);
				this.defaultPanel.appendChild(element.item);
			} else {
				this.panel.appendChild(element.item);
			}
		});

		this.sortable = Sortable.create(this.panel, {
			group: {
				name: "builder",
				pull: false,
				put: true,
			},
			animation: 150,
			onAdd: this._addElement,
			onUpdate: this._moveElement,
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_drag_component
	 * @features forms
	 * @dimensions builder-drag-component
	 */
	_addElement(event) {
		const item = this.builder.createElement({
			type: event.item.dataset.type,
		});
		event.item.remove();
		event.to.insertBefore(item, event.to.children[event.newDraggableIndex]);
		this.builder.updateSchemaOrder();
		this.builder.selectElement(item.id);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_drag_component
	 * @features forms
	 * @dimensions builder-drag-component
	 */
	_moveElement() {
		this.builder.updateSchemaOrder();
	}

	updateItem() {
		const element = this.builder.selectedElement;
		const item = ModelElement[element.schema.type](element.schema);
		element.item.replaceWith(item);
		element.item = item;
		this.selectItem();
	}

	selectItem() {
		const selected = this.builder.selectedElement.item;

		this.elements.forEach((element) => {
			element.dataset.selected = element === selected ? "true" : "false";
		});
		this.defaults.forEach((element) => {
			element.dataset.selected = element === selected ? "true" : "false";
		});
	}

	deselectItem() {
		this.builder.selectedElement.item.dataset.selected = "false";
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_signature_field_builder_unique_component
	 * @features forms signature
	 * @dimensions unique-component
	 */
	hasUniqueElement(type) {
		return (
			this.uniqueElements.includes(type) &&
			this.panel.querySelector(`[id^="${type}"]`)
		);
	}

	focusItem() {
		const selected = this.builder.selectedElement.item;
		this.elements.forEach((element) => {
			element.dataset.visible = element === selected ? "true" : "false";
		});
		this.panel.classList.remove("min-h-[300px]");
		this.defaultPanel.dataset.visible = "false";
	}

	blurItem() {
		this.elements.forEach((element) => {
			element.dataset.visible = "true";
		});
		if (this.defaultPanel.children.length > 0) {
			this.defaultPanel.dataset.visible = "true";
		}
		this.panel.classList.add("min-h-[300px]");
	}

	destroy() {
		this.sortable.destroy();
	}
}

/**
 * @testable infrastructure
 */
const _model = (schema) => {
	const element = document.createElement("div");
	element.id = schema.id;
	element.dataset.selected = "false";
	element.dataset.visible = "true";
	element.className = `${STYLES.builder.model}`;
	return element;
};

/**
 * @testable true
 * @tests tests_js/test_019_form_sync_frontend.py::test_builder_model_defaults_are_presentation_only
 * @features forms form-schema
 * @dimensions builder presentation-defaults immutable-schema
 */
const _presentation = (schema) => {
	const defaults = CONFIG.PRESENTATION_DEFAULTS[schema.type] || {};
	return {
		...schema,
		title: schema.title ?? defaults.title,
		input: schema.input ?? defaults.input,
		location: schema.location ?? defaults.location,
	};
};

/**
 * @testable infrastructure
 */
const checkbox = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-row", "gap-2");

	element.appendChild(
		primitives.checkbox({
			label: display.title,
			checked: !!schema.checked,
			name: schema.id,
			disabled: true,
		}),
	);

	return element;
};

/**
 * @testable infrastructure
 */
const html = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		icon: "html",
		label: display.title,
		tag: "h3",
	});
	element.appendChild(label);
	return element;
};

/**
 * @testable infrastructure
 */
const input = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const input = primitives.input({
		icon: display.input,
		label: display.title,
		name: schema.id,
		type: display.input,
		disabled: true,
		placeholder: schema.placeholder,
	});

	element.appendChild(input);
	return element;
};

/**
 * @testable infrastructure
 */
const link = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	let linkElt;
	if (display.location === "out") {
		linkElt = primitives.label({
			icon: display.location,
			label: display.title,
			tag: "h3",
		});
	} else {
		linkElt = primitives.select({
			label: display.title,
			icon: display.location,
			selectIcon: "search",
			disabled: true,
		});
	}

	element.appendChild(linkElt);
	return element;
};

/**
 * @testable infrastructure
 */
const bookmark = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		icon: "bookmark",
		label: display.title,
	});

	element.appendChild(label);
	return element;
};

/**
 * @testable infrastructure
 */
const location = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const input = primitives.input({
		label: display.title,
		icon: "location",
		name: schema.id,
		selectIcon: "search",
		type: "text",
		disabled: true,
		placeholder: schema.placeholder,
	});

	element.appendChild(input);
	return element;
};

/**
 * @testable infrastructure
 */
const select = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const select = primitives.select({
		label: display.title,
		icon: "select",
		selectIcon: "dropdown",
		name: schema.id,
		disabled: true,
		placeholder: schema.placeholder || "select an option...",
	});

	element.appendChild(select);
	return element;
};

/**
 * @testable infrastructure
 */
const radio = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const fieldset = element.appendChild(document.createElement("fieldset"));
	fieldset.className = `${STYLES.radio.fieldset.column}`;

	fieldset.appendChild(
		primitives.label({
			icon: "radio",
			tag: "legend",
			label: display.title,
		}),
	);

	if (!schema.options) {
		return element;
	}

	schema.options.forEach((option) => {
		fieldset.appendChild(
			primitives.radio({
				label: option.label,
				value: option.value,
				name: schema.id,
				disabled: true,
				styles: {
					label: `${STYLES.radio.label} first-of-type:pt-1`,
				},
			}),
		);
	});

	return element;
};

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_signature_field_builder_unique_component
 * @features forms signature
 * @dimensions builder-signature-field builder-preview
 */
const signature = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		icon: "signature",
		label: display.title,
		tag: "h3",
	});

	element.appendChild(label);
	return element;
};

/**
 * @testable infrastructure
 */
const status = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		tag: "h3",
		label: display.title,
		icon: "status",
	});

	element.appendChild(label);
	return element;
};

/**
 * @testable infrastructure
 */
const textarea = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const textarea = primitives.textarea({
		label: display.title,
		placeholder: schema.placeholder || "",
		icon: "textarea",
		disabled: true,
		rows: 2,
	});

	element.appendChild(textarea);
	return element;
};

/**
 * @testable infrastructure
 */
const todo = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	element.appendChild(
		primitives.label({
			icon: "checklist",
			label: display.title,
			tag: "h3",
		}),
	);
	return element;
};

/**
 * @testable infrastructure
 */
const table = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");
	const columns = schema.columns || [];

	const label = primitives.label({
		icon: "table",
		label: display.title,
		tag: "h3",
	});
	element.appendChild(label);

	const badgesContainer = element.appendChild(document.createElement("div"));
	badgesContainer.className = `flex flex-row gap-2 empty:hidden flex-wrap`;

	columns.forEach((column) => {
		badgesContainer.appendChild(
			primitives.badge({
				icon: column.location || column.input || column.type,
				text: column.title,
				kind: "form",
				styles: {
					badge: `${STYLES.badge.builder}`,
					text: "text-base-dark",
				},
			}),
		);
	});

	return element;
};

export const ModelElement = {
	checkbox,
	html,
	input,
	link,
	bookmark,
	location,
	radio,
	select,
	signature,
	status,
	textarea,
	table,
	todo,
};
