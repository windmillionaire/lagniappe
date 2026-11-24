import Sortable, { type SortableEvent } from "sortablejs";
import { primitives } from "../../../elements/primitives.ts";
import { STYLES } from "../../../generated/styles.mjs";
import type { FieldType, FormFieldSchema } from "../../../types/forms.d.ts";
import type FormBuilder from "../builder.ts";
import { CONFIG } from "../config.ts";
import { builderControl } from "../controls.ts";

export class ModelPanel {
	declare builder: FormBuilder;
	declare panel: HTMLElement;
	declare defaultPanel: HTMLElement;
	declare sortable: Sortable | null;
	declare uniqueElements: string[];
	declare defaultElements: string[];

	constructor(builder: FormBuilder) {
		this.builder = builder;
		this.panel = builderControl("model-panel");
		this.defaultPanel = builderControl("default-panel");
		this.uniqueElements = ["status", "signature", "bookmark"];
		this.defaultElements = ["name", "description"];
		this._addElement = this._addElement.bind(this);
		this._moveElement = this._moveElement.bind(this);
	}

	get elements() {
		return Array.from(
			this.panel.querySelectorAll<HTMLElement>(".form-element"),
		);
	}

	get defaults() {
		return Array.from(
			this.defaultPanel.querySelectorAll<HTMLElement>(".form-element"),
		);
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

	_addElement(event: SortableEvent) {
		const type = event.item.dataset.type as FieldType | undefined;
		if (!type) return;
		const item = this.builder.createElement({ type });
		event.item.remove();
		event.to.insertBefore(
			item,
			event.to.children[event.newDraggableIndex ?? -1] ?? null,
		);
		this.builder.updateSchemaOrder();
		this.builder.selectElement(item.id);
	}

	_moveElement() {
		this.builder.updateSchemaOrder();
	}

	updateItem() {
		const element = this.builder.selectedElement;
		if (!element) return;
		const item = ModelElement[element.schema.type](element.schema);
		element.item.replaceWith(item);
		element.item = item;
		this.selectItem();
	}

	selectItem() {
		const selected = this.builder.selectedElement?.item;
		if (!selected) return;

		this.elements.forEach((element) => {
			element.dataset.selected = element === selected ? "true" : "false";
		});
		this.defaults.forEach((element) => {
			element.dataset.selected = element === selected ? "true" : "false";
		});
	}

	deselectItem() {
		const selected = this.builder.selectedElement;
		if (selected) selected.item.dataset.selected = "false";
	}

	hasUniqueElement(type: string | undefined) {
		return (
			type !== undefined &&
			this.uniqueElements.includes(type) &&
			Array.from(this.builder.elements.values()).some(
				(element) => element.schema.type === type,
			)
		);
	}

	focusItem() {
		const selected = this.builder.selectedElement?.item;
		if (!selected) return;
		this.elements.forEach((element) => {
			element.dataset.visible = element === selected ? "true" : "false";
		});
		this.panel.classList.remove("min-h-75");
		this.defaultPanel.dataset.visible = "false";
	}

	blurItem() {
		this.elements.forEach((element) => {
			element.dataset.visible = "true";
		});
		if (this.defaultPanel.children.length > 0) {
			this.defaultPanel.dataset.visible = "true";
		}
		this.panel.classList.add("min-h-75");
	}

	destroy() {
		this.sortable?.destroy();
		this.sortable = null;
	}
}

const _model = (schema: FormFieldSchema) => {
	const element = document.createElement("div");
	element.id = schema.id;
	element.dataset.selected = "false";
	element.dataset.visible = "true";
	element.className = `${STYLES.builder.model}`;
	return element;
};

const _presentation = (schema: FormFieldSchema) => {
	const defaults = CONFIG.PRESENTATION_DEFAULTS[schema.type] as
		| Partial<Pick<FormFieldSchema, "title" | "input" | "location">>
		| undefined;
	return {
		...schema,
		title: schema.title ?? defaults?.title,
		input: schema.input ?? defaults?.input,
		location: schema.location ?? defaults?.location,
	};
};

const checkbox = (schema: FormFieldSchema) => {
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

const html = (schema: FormFieldSchema) => {
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

const input = (schema: FormFieldSchema) => {
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

const link = (schema: FormFieldSchema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	let linkElt: HTMLElement;
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

const bookmark = (schema: FormFieldSchema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		icon: "bookmark",
		label: display.title,
	});

	element.appendChild(label);
	return element;
};

const location = (schema: FormFieldSchema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const input = primitives.input({
		label: display.title,
		icon: "location",
		name: schema.id,
		type: "text",
		disabled: true,
		placeholder: schema.placeholder,
	});

	element.appendChild(input);
	return element;
};

const select = (schema: FormFieldSchema) => {
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

const radio = (schema: FormFieldSchema) => {
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

const signature = (schema: FormFieldSchema) => {
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

const status = (schema: FormFieldSchema) => {
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

const textarea = (schema: FormFieldSchema) => {
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

const todo = (schema: FormFieldSchema) => {
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

const table = (schema: FormFieldSchema) => {
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
