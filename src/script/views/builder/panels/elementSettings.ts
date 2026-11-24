import { primitives } from "../../../elements/primitives.ts";
import { STYLES } from "../../../generated/styles.mjs";
import { withTransition } from "../../../shared/transitions.ts";
import type {
	FieldCondition,
	FieldOption,
	FormFieldSchema,
	InputType,
} from "../../../types/forms.d.ts";
import type FormBuilder from "../builder.ts";
import type { BuilderElement } from "../builder.ts";
import { CONFIG, type ConditionList } from "../config.ts";
import { builderControl } from "../controls.ts";

const _section = (name: string, elements: HTMLElement[]) => {
	const section = document.createElement("div");
	section.className = STYLES.builder.settings.section;
	section.append(...elements.filter(Boolean));
	section.dataset.setting = name;
	return section;
};

const _presentation = (schema: FormFieldSchema) => {
	const defaults = CONFIG.PRESENTATION_DEFAULTS[schema.type] as
		| Partial<Pick<FormFieldSchema, "title" | "input" | "location">>
		| undefined;
	return {
		title: schema.title ?? defaults?.title,
		input: schema.input ?? defaults?.input,
		location: schema.location ?? defaults?.location,
	};
};

const _toggle = (
	icon: string,
	role: string,
	kind = "form",
	disabled = false,
) => {
	const toggle = primitives.toggle({
		icon: icon,
		styles: {
			container: STYLES.builder.settings.toggle.container,
			icon: STYLES.builder.settings.toggle.icon,
		},
		data: {
			role: role,
		},
	});
	toggle.type = "button";
	toggle.dataset.kind = kind;
	if (disabled) {
		toggle.disabled = true;
		toggle.classList.add("opacity-50", "pointer-events-none");
	}
	return toggle;
};

const _condition = (condition: FieldCondition, index: number) => {
	const elt = document.createElement("li");
	elt.className = STYLES.builder.settings.item;
	elt.dataset.index = String(index);

	const wrapper = document.createElement("button");
	wrapper.type = "button";
	wrapper.className = STYLES.builder.settings.open;
	wrapper.dataset.role = "open";

	const target = wrapper.appendChild(document.createElement("span"));
	target.textContent = condition.name ?? null;
	target.className = `font-semibold text-form-dark`;

	const text = wrapper.appendChild(document.createElement("span"));
	text.className = `italic text-base-dark`;
	text.textContent = condition.checked ? " is " : " has the value ";

	const status = wrapper.appendChild(document.createElement("span"));
	status.className = `font-semibold text-project-default`;
	status.textContent = condition.checked
		? "checked"
		: (condition.label ?? null);

	const remove = _toggle("x", "remove", "delete");

	elt.append(wrapper, remove);
	return elt;
};

const _option = (option: FieldOption, index: number, length: number) => {
	const wrapper = document.createElement("li");
	wrapper.className = STYLES.builder.settings.item;
	wrapper.dataset.index = String(index);

	const name = wrapper.appendChild(document.createElement("button"));
	name.type = "button";
	name.textContent = option.label;
	name.className = STYLES.builder.settings.open;
	name.dataset.role = "open";

	const toggles = document.createElement("div");
	toggles.className = `flex shrink-0 flex-row items-center gap-1`;
	if (length > 1) {
		toggles.appendChild(
			_toggle("down", "moveDown", "form", index === length - 1),
		);
		toggles.appendChild(_toggle("up", "moveUp", "form", index === 0));
	}
	toggles.appendChild(_toggle("x", "remove", "delete"));

	wrapper.append(name, toggles);

	return wrapper;
};

const _column = (column: FormFieldSchema, index: number, length: number) => {
	const wrapper = document.createElement("li");
	wrapper.className = STYLES.builder.settings.item;
	wrapper.dataset.index = String(index);

	const name = primitives.label({
		icon: column.location || column.input || column.type,
		label: column.name || column.title,
		tag: "button",
		role: "open",
		styles: {
			label: STYLES.builder.settings.open,
			container: "flex flex-row items-center gap-1.5",
		},
	});
	(name as HTMLButtonElement).type = "button";

	const toggles = document.createElement("div");
	toggles.className = `flex shrink-0 flex-row items-center gap-1`;
	if (length > 1) {
		toggles.appendChild(
			_toggle("down", "moveDown", "form", index === length - 1),
		);
		toggles.appendChild(_toggle("up", "moveUp", "form", index === 0));
	}
	toggles.appendChild(_toggle("x", "remove", "delete"));

	wrapper.append(name, toggles);
	return wrapper;
};

const title = (schema: FormFieldSchema) => {
	const title = primitives.input({
		label: "Title",
		name: "title",
		value: _presentation(schema).title,
	});
	return _section("title", [title]);
};

const placeholder = (schema: FormFieldSchema) => {
	const placeholder = primitives.input({
		label: "Placeholder",
		name: "placeholder",
		value: schema.placeholder || "",
	});
	return _section("placeholder", [placeholder]);
};

const visibility = (schema: FormFieldSchema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Visibility",
		tag: "h3",
	});
	const toggle = _toggle("add", "add");
	title.append(label, toggle);

	if (schema.visibility) {
		const visibilityList = document.createElement("ul");
		visibilityList.className = `flex flex-col gap-1`;
		schema.visibility.forEach((condition, index) => {
			visibilityList.appendChild(_condition(condition, index));
		});
		return _section("visibility", [title, visibilityList]);
	}
	return _section("visibility", [title]);
};

const status = (schema: FormFieldSchema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Status",
		tag: "h3",
	});
	const toggle = _toggle("add", "add");
	title.append(label, toggle);

	if (schema.status) {
		const statusList = document.createElement("ul");
		statusList.className = `flex flex-col gap-1`;
		schema.status.forEach((status, index) => {
			statusList.appendChild(_condition(status, index));
		});
		return _section("status", [title, statusList]);
	} else {
		return _section("status", [title]);
	}
};

const options = (schema: FormFieldSchema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Options",
		tag: "h3",
	});
	const toggle = _toggle("add", "add");
	title.append(label, toggle);

	if (schema.options) {
		const optionList = document.createElement("ul");
		optionList.className = `flex flex-col gap-1`;
		const length = schema.options.length;
		schema.options.forEach((option, index) => {
			optionList.appendChild(_option(option, index, length));
		});
		return _section("options", [title, optionList]);
	} else {
		return _section("options", [title]);
	}
};

const editor = () => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Editor",
		tag: "h3",
	});
	const toggle = _toggle("edit", "edit");
	title.append(label, toggle);
	return _section("html", [title]);
};

const input = (schema: FormFieldSchema) => {
	const display = _presentation(schema);
	const fieldset = document.createElement("fieldset");
	fieldset.className = STYLES.radio.fieldset.column;
	fieldset.dataset.kind = "base";

	const legend = fieldset.appendChild(document.createElement("legend"));
	legend.textContent = "Input Type";
	legend.className = `${STYLES.label.sectionHeading}`;

	CONFIG.INPUTS.forEach((type) => {
		fieldset.appendChild(
			primitives.radio({
				icon: type.type,
				label: type.name,
				name: "input",
				value: type.type,
				checked: type.type === display.input,
			}),
		);
	});

	return _section("input", [fieldset]);
};

const location = (schema: FormFieldSchema) => {
	const display = _presentation(schema);
	const fieldset = document.createElement("fieldset");
	fieldset.className = STYLES.radio.fieldset.column;
	fieldset.dataset.kind = "form";

	const legend = fieldset.appendChild(document.createElement("legend"));
	legend.textContent = "Link Type";
	legend.className = `${STYLES.label.sectionHeading}`;

	CONFIG.LINKS.forEach((type) => {
		fieldset.appendChild(
			primitives.radio({
				icon: type.type,
				label: type.name,
				name: "location",
				value: type.type,
				checked: type.type === display.location,
			}),
		);
	});

	return _section("location", [fieldset]);
};

const columns = (schema: FormFieldSchema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Columns",
		tag: "h3",
	});
	const toggle = _toggle("add", "add");
	title.append(label, toggle);

	if (schema.columns?.length) {
		const columnList = document.createElement("ul");
		columnList.className = `flex flex-col gap-1`;
		const length = schema.columns.length;
		schema.columns.forEach((column, index) => {
			columnList.appendChild(_column(column, index, length));
		});
		return _section("columns", [title, columnList]);
	} else {
		return _section("columns", [title]);
	}
};

const required = (schema: FormFieldSchema) => {
	const required = primitives.checkbox({
		label: "Required",
		name: "required",
		checked: !!schema.required,
	});
	return _section("required", [required]);
};

const multiple = (schema: FormFieldSchema) => {
	const multiple = primitives.checkbox({
		label: "Multiple",
		name: "multiple",
		checked: !!schema.multiple,
	});
	return _section("multiple", [multiple]);
};

const checked = (schema: FormFieldSchema) => {
	const checked = primitives.checkbox({
		label: "Default",
		name: "checked",
		checked: !!schema.checked,
	});
	return _section("checked", [checked]);
};

const deleteButton = () => {
	const button = document.createElement("button");
	button.textContent = "Replace or Delete";
	button.dataset.kind = "form";
	button.dataset.role = "delete";
	button.dataset.setting = "deleteButton";
	button.className = `${STYLES.button.submit}`;
	return button;
};

const SettingsElement = {
	title: title,
	placeholder: placeholder,
	visibility: visibility,
	status: status,
	options: options,
	input: input,
	location: location,
	columns: columns,
	required: required,
	multiple: multiple,
	checked: checked,
	editor: editor,
	deleteButton: deleteButton,
};

export class ElementSettings {
	declare builder: FormBuilder;
	declare panel: HTMLElement;

	constructor(builder: FormBuilder) {
		this.builder = builder;
		this.panel = builderControl("settings-panel");
		this._input = this._input.bind(this);
		this._change = this._change.bind(this);
		this._click = this._click.bind(this);
		this._blur = this._blur.bind(this);
	}

	init() {
		this.panel.addEventListener("input", this._input);
		this.panel.addEventListener("change", this._change);
		this.panel.addEventListener("click", this._click);
		this.panel.addEventListener("blur", this._blur, true);
	}

	destroy() {
		this.panel.removeEventListener("input", this._input);
		this.panel.removeEventListener("change", this._change);
		this.panel.removeEventListener("click", this._click);
		this.panel.removeEventListener("blur", this._blur, true);
	}

	_input(e: Event) {
		const target = e.target as HTMLInputElement | null;
		const element = this.builder.selectedElement;
		if (!target || !element) return;
		if (target.closest("[data-setting=title]")) {
			this._setTitle(element, target.value);
		} else if (target.closest("[data-setting=placeholder]")) {
			this._setPlaceholder(element, target.value);
		}
		this.builder.updateSchema(false, `${element.schema.id}:${target.name}`);
	}

	_change(e: Event) {
		const target = e.target as HTMLInputElement | null;
		const element = this.builder.selectedElement;
		if (!target || !element) return;
		if (target.closest("[data-setting=required]")) {
			this._setRequired(element, target.checked);
		} else if (target.closest("[data-setting=checked]")) {
			this._setChecked(element, target.checked);
		} else if (target.closest("[data-setting=multiple]")) {
			this._setMultiple(element, target.checked);
		} else if (target.closest("[data-setting=input]")) {
			this._setInput(element, target.value as InputType);
		} else if (target.closest("[data-setting=location]")) {
			this._setLocation(element, target.value as "in" | "out");
		}
		this.builder.updateSchema();
	}

	_click(e: MouseEvent) {
		const target = e.target as Element | null;
		if (!target || target.closest("button")?.disabled) return;
		const element = this.builder.selectedElement;
		if (!element) return;
		const role = target.closest<HTMLElement>("[data-role]")?.dataset.role;
		const setting = target.closest<HTMLElement>("[data-index]");
		const index = setting ? parseInt(setting.dataset.index ?? "", 10) : -1;
		const name = target.closest<HTMLElement>("[data-setting]")?.dataset.setting;
		const list =
			name === "visibility" ||
			name === "status" ||
			name === "columns" ||
			name === "options"
				? name
				: null;

		if (role === "remove" && list) {
			this._removeSchemaListItem(element.schema[list], index);
		} else if ((role === "moveUp" || role === "moveDown") && list) {
			this._moveSchemaListItem(element, list, index, role);
		} else if (
			(role === "add" || role === "edit" || role === "open") &&
			(list || name === "html")
		) {
			this.builder.showCondition(list || "html", index);
		} else if (role === "delete") {
			this.builder.showCondition("modify");
		}
	}

	_blur() {
		this.builder.updateSchema();
		if (this.builder.draft) this.builder.draft.group = null;
	}

	_removeSchemaListItem(
		schema:
			| FieldCondition[]
			| FieldOption[]
			| FormFieldSchema[]
			| null
			| undefined,
		index: number,
	) {
		if (!schema) return;
		schema.splice(index, 1);
		this.builder.updateSchema();
		withTransition(() => {
			const selected = this.builder.selectedElement;
			if (!selected) return;
			this.builder.model.updateItem();
			selected.settings = this.create(selected.schema);
			this.updateItem();
		});
	}

	_moveSchemaListItem(
		element: BuilderElement,
		name: ConditionList,
		index: number,
		direction: "moveUp" | "moveDown",
	) {
		const arr:
			| (FieldCondition | FieldOption | FormFieldSchema)[]
			| null
			| undefined = element.schema[name];
		if (!arr) return;
		const newIndex = direction === "moveUp" ? index - 1 : index + 1;
		if (newIndex < 0 || newIndex >= arr.length) return;
		[arr[index], arr[newIndex]] = [arr[newIndex], arr[index]];
		this.builder.updateSchema();
		withTransition(() => {
			const selected = this.builder.selectedElement;
			if (!selected) return;
			this.builder.model.updateItem();
			selected.settings = this.create(selected.schema);
			this.updateItem();
		});
	}

	_setTitle(element: BuilderElement, value: string) {
		element.schema.title = value;
		const label = element.item.querySelector(
			"[data-role='label'] > span:not([data-icon])",
		);
		if (label) label.textContent = value;
	}

	_setPlaceholder(element: BuilderElement, value: string) {
		element.schema.placeholder = value;
		const input = element.item.querySelector<
			HTMLInputElement | HTMLTextAreaElement
		>("input, textarea");
		if (input) input.placeholder = value;
	}

	_setRequired(element: BuilderElement, value: boolean) {
		element.schema.required = value;
	}

	_setChecked(element: BuilderElement, value: boolean) {
		element.schema.checked = value;
		const input = element.item.querySelector<HTMLInputElement>(
			"input[type='checkbox']",
		);
		if (input) input.checked = value;
	}

	_setMultiple(element: BuilderElement, value: boolean) {
		element.schema.multiple = value;
	}

	_setInput(element: BuilderElement, value: InputType) {
		element.schema.input = value;
		const label = primitives.label({
			icon: value,
			label: _presentation(element.schema).title,
		});
		const inner = label.querySelector("div");
		if (inner) element.item.querySelector("label > div")?.replaceWith(inner);
	}

	_setLocation(element: BuilderElement, value: "in" | "out") {
		element.schema.location = value;
		const label = primitives.label({
			icon: value,
			label: _presentation(element.schema).title,
			tag: "h3",
		});
		element.item.querySelector("h3")?.replaceWith(label);
	}

	create(schema: FormFieldSchema): HTMLElement[] {
		const display = { ...schema };
		for (const key of ["visibility", "status"] as const) {
			if (Array.isArray(schema[key]))
				display[key] = schema[key].map((condition) => {
					const target = condition.id
						? this.builder.elements.get(condition.id)?.schema
						: undefined;
					return {
						...condition,
						name: target?.title ?? condition.name,
						label:
							target?.options?.find(
								(option) => option.value === condition.value,
							)?.label ?? condition.label,
					};
				});
		}
		const settings = CONFIG.DEFAULT_SETTINGS[schema.type].map((setting) => {
			if (
				["name", "description"].includes(schema.id) &&
				setting === "deleteButton"
			) {
				return null;
			}
			return SettingsElement[setting](display);
		});
		const sections = settings.filter((section) => section !== null);
		this.refreshSavedState(schema, sections);
		return sections;
	}

	refreshSavedState(
		schema = this.builder.selectedElement?.schema,
		sections: Iterable<HTMLElement> = this.panel
			.children as HTMLCollectionOf<HTMLElement>,
	) {
		if (!schema) return;
		const saved = this.builder.savedField(schema.id);
		if (!saved) return;
		for (const section of sections) {
			const setting = section.dataset.setting;
			if (setting === "input") {
				if (!section.querySelector("[data-role='saved-input-type']")) {
					const notice = document.createElement("p");
					notice.dataset.role = "saved-input-type";
					notice.className = "text-sm text-base-medium";
					if (["name", "description"].includes(schema.id)) {
						notice.textContent = "This input's type cannot be changed.";
					} else {
						const action = document.createElement("strong");
						action.textContent = "Replace or Delete";
						notice.append(
							"Click ",
							action,
							" in order to change this input's type.",
						);
					}
					section.replaceChildren(notice);
				}
			}
			if (setting === "multiple" || setting === "location") {
				const controls = section.matches("button, input, select")
					? [
							section as
								| HTMLButtonElement
								| HTMLInputElement
								| HTMLSelectElement,
						]
					: section.querySelectorAll<
							HTMLButtonElement | HTMLInputElement | HTMLSelectElement
						>("button, input, select");
				for (const control of controls) control.disabled = true;
			}
			if (setting === "options" || setting === "columns") {
				for (const row of section.querySelectorAll<HTMLElement>(
					"[data-index]",
				)) {
					const index = Number(row.dataset.index);
					const wasSaved =
						setting === "options"
							? saved.options?.some(
									(option) => option.value === schema.options?.[index]?.value,
								)
							: saved.columns?.some(
									(column) => column.id === schema.columns?.[index]?.id,
								);
					if (wasSaved) {
						const remove = row.querySelector<HTMLButtonElement>(
							"[data-role='remove']",
						);
						if (remove) {
							remove.disabled = false;
							remove.title =
								"Save will clear values for this removed choice or column.";
						}
					}
				}
			}
		}
	}

	selectItem() {
		const item = this.builder.selectedElement;
		if (!item) return;
		item.settings = this.create(item.schema);
		this.panel.replaceChildren(...item.settings);
		this.panel.dataset.visible = "true";
		this.builder.formSettings.visible = false;
	}

	deselectItem() {
		this.panel.dataset.visible = "false";
	}

	updateItem() {
		this.panel.dataset.visible = "false";
		const item = this.builder.selectedElement;
		if (!item) return;
		this.panel.replaceChildren(...item.settings);
		this.panel.dataset.visible = "true";
	}
}
