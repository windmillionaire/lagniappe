import { STYLES } from "styles";
import { CONFIG } from "../../../config/builder";
import { primitives } from "../../../elements/primitives";
import { withTransition } from "../../../shared";

/**
 * @testable infrastructure
 */
const _section = (name, elements) => {
	const section = document.createElement("div");
	section.className = STYLES.builder.settings.section;
	section.append(...elements.filter(Boolean));
	section.dataset.setting = name;
	return section;
};

/**
 * @testable infrastructure
 */
const _presentation = (schema) => {
	const defaults = CONFIG.PRESENTATION_DEFAULTS[schema.type] || {};
	return {
		title: schema.title ?? defaults.title,
		input: schema.input ?? defaults.input,
		location: schema.location ?? defaults.location,
	};
};

/**
 * @testable true
 * @tests tests_js/test_036_form_builder_frontend.py::test_builder_schema_lists_use_button_surfaces_and_centered_actions
 * @matrix forms : action-button-centering builder-list-actions
 */
const _toggle = (icon, role, kind = "form", disabled = false) => {
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

/**
 * @testable infrastructure
 */
const _condition = (condition, index) => {
	const elt = document.createElement("li");
	elt.className = STYLES.builder.settings.item;
	elt.dataset.index = index;

	const wrapper = document.createElement("button");
	wrapper.type = "button";
	wrapper.className = STYLES.builder.settings.open;
	wrapper.dataset.role = "open";

	const target = wrapper.appendChild(document.createElement("span"));
	target.textContent = condition.name;
	target.className = `font-semibold text-form-dark`;

	const text = wrapper.appendChild(document.createElement("span"));
	text.className = `italic text-base-dark`;
	text.textContent = condition.checked ? " is " : " has the value ";

	const status = wrapper.appendChild(document.createElement("span"));
	status.className = `font-semibold text-project-default`;
	status.textContent = condition.checked ? "checked" : condition.label;

	const remove = _toggle("x", "remove", "delete");

	elt.append(wrapper, remove);
	return elt;
};

/**
 * @testable infrastructure
 */
const _option = (option, index, length) => {
	const wrapper = document.createElement("li");
	wrapper.className = STYLES.builder.settings.item;
	wrapper.dataset.index = index;

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

/**
 * @testable infrastructure
 */
const _column = (column, index, length) => {
	const wrapper = document.createElement("li");
	wrapper.className = STYLES.builder.settings.item;
	wrapper.dataset.index = index;

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
	name.type = "button";

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

/**
 * @testable infrastructure
 */
const title = (schema) => {
	const title = primitives.input({
		label: "Title",
		name: "title",
		value: _presentation(schema).title,
	});
	return _section("title", [title]);
};

/**
 * @testable infrastructure
 */
const placeholder = (schema) => {
	const placeholder = primitives.input({
		label: "Placeholder",
		name: "placeholder",
		value: schema.placeholder || "",
	});
	return _section("placeholder", [placeholder]);
};

/**
 * @testable infrastructure
 */
const visibility = (schema) => {
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

/**
 * @testable infrastructure
 */
const status = (schema) => {
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

/**
 * @testable infrastructure
 */
const options = (schema) => {
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

/**
 * @testable infrastructure
 */
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

/**
 * @testable infrastructure
 */
const input = (schema) => {
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

/**
 * @testable infrastructure
 */
const location = (schema) => {
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

/**
 * @testable infrastructure
 */
const columns = (schema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Columns",
		tag: "h3",
	});
	const toggle = _toggle("add", "add");
	title.append(label, toggle);

	if (schema.columns) {
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

/**
 * @testable infrastructure
 */
const required = (schema) => {
	const required = primitives.checkbox({
		label: "Required",
		name: "required",
		checked: !!schema.required,
	});
	return _section("required", [required]);
};

/**
 * @testable infrastructure
 */
const multiple = (schema) => {
	const multiple = primitives.checkbox({
		label: "Multiple",
		name: "multiple",
		checked: !!schema.multiple,
	});
	return _section("multiple", [multiple]);
};

/**
 * @testable infrastructure
 */
const checked = (schema) => {
	const checked = primitives.checkbox({
		label: "Default",
		name: "checked",
		checked: !!schema.checked,
	});
	return _section("checked", [checked]);
};

/**
 * @testable infrastructure
 */
const deleteButton = () => {
	const button = document.createElement("button");
	button.textContent = "Delete";
	button.dataset.kind = "delete";
	button.dataset.role = "delete";
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

/**
 * @testable infrastructure
 */
export class ElementSettings {
	constructor(builder) {
		this.builder = builder;
		this.panel = document.getElementById("settings-panel");
		this._input = this._input.bind(this);
		this._change = this._change.bind(this);
		this._click = this._click.bind(this);
		this._blur = this._blur.bind(this);
	}

	init() {
		this.panel.addEventListener("input", this._input);
		this.panel.addEventListener("change", this._change);
		this.panel.addEventListener("click", this._click);
		this.panel.addEventListener("blur", this._blur);
	}

	destroy() {
		this.panel.removeEventListener("input", this._input);
		this.panel.removeEventListener("change", this._change);
		this.panel.removeEventListener("click", this._click);
		this.panel.removeEventListener("blur", this._blur);
	}

	_input(e) {
		const element = this.builder.selectedElement;
		if (e.target.closest("[data-setting=title]")) {
			this._setTitle(element, e.target.value);
		} else if (e.target.closest("[data-setting=placeholder]")) {
			this._setPlaceholder(element, e.target.value);
		}
	}

	_change(e) {
		const element = this.builder.selectedElement;
		if (e.target.closest("[data-setting=required]")) {
			this._setRequired(element, e.target.checked);
		} else if (e.target.closest("[data-setting=checked]")) {
			this._setChecked(element, e.target.checked);
		} else if (e.target.closest("[data-setting=multiple]")) {
			this._setMultiple(element, e.target.checked);
		} else if (e.target.closest("[data-setting=input]")) {
			this._setInput(element, e.target.value);
		} else if (e.target.closest("[data-setting=location]")) {
			this._setLocation(element, e.target.value);
		}
		this.builder.updateSchema();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_field_visibility
	 * @matrix forms : builder-field-visibility builder-select-options
	 */
	_click(e) {
		const element = this.builder.selectedElement;
		const role = e.target.closest("[data-role]")?.dataset.role;
		const setting = e.target.closest("[data-index]");
		const index = setting ? parseInt(setting.dataset.index, 10) : -1;
		const name = e.target.closest("[data-setting]")?.dataset.setting;

		if (role === "remove") {
			this._removeSchemaListItem(element.schema[name], index);
		} else if (["moveUp", "moveDown"].includes(role)) {
			this._moveSchemaListItem(element, name, index, role);
		} else if (["add", "edit", "open"].includes(role)) {
			this.builder.showCondition(name, index);
		} else if (role === "delete") {
			this.builder.removeElement();
			this.deselectItem();
			this.builder.formSettings.visible = true;
		}
	}

	_blur() {
		this.builder.updateSchema();
	}

	_removeSchemaListItem(schema, index) {
		schema.splice(index, 1);
		this.builder.updateSchema();
		withTransition(() => {
			this.builder.model.updateItem();
			this.builder.selectedElement.settings = this.create(
				this.builder.selectedElement.schema,
			);
			this.updateItem();
		});
	}

	_moveSchemaListItem(element, name, index, direction) {
		const arr = element.schema[name];
		const newIndex = direction === "moveUp" ? index - 1 : index + 1;
		if (newIndex < 0 || newIndex >= arr.length) return;
		[arr[index], arr[newIndex]] = [arr[newIndex], arr[index]];
		this.builder.updateSchema();
		withTransition(() => {
			this.builder.model.updateItem();
			this.builder.selectedElement.settings = this.create(
				this.builder.selectedElement.schema,
			);
			this.updateItem();
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
	 * @pairs forms:builder-field-title frontend-icons:material-icon-preservation
	 */
	_setTitle(element, value) {
		element.schema.title = value;
		element.item.querySelector(
			"[data-role='label'] > span:not([data-icon])",
		).textContent = value;
	}

	_setPlaceholder(element, value) {
		element.schema.placeholder = value;
		const input = element.item.querySelector("input, textarea");
		if (input) input.placeholder = value;
	}

	_setRequired(element, value) {
		element.schema.required = value;
	}

	_setChecked(element, value) {
		element.schema.checked = value;
		element.item.querySelector("input[type='checkbox']").checked = value;
	}

	_setMultiple(element, value) {
		element.schema.multiple = value;
	}

	_setInput(element, value) {
		element.schema.input = value;
		const label = primitives.label({
			icon: value,
			label: _presentation(element.schema).title,
		});
		element.item
			.querySelector("label > div")
			.replaceWith(label.querySelector("div"));
	}

	_setLocation(element, value) {
		element.schema.location = value;
		const label = primitives.label({
			icon: value,
			label: _presentation(element.schema).title,
			tag: "h3",
		});
		element.item.querySelector("h3").replaceWith(label);
	}

	create(schema) {
		const settings = CONFIG.DEFAULT_SETTINGS[schema.type].map((setting) => {
			if (
				["name", "description"].includes(schema.id) &&
				setting === "deleteButton"
			) {
				return null;
			}
			return SettingsElement[setting](schema);
		});
		return settings.filter(Boolean);
	}

	selectItem() {
		const item = this.builder.selectedElement;
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
		this.panel.replaceChildren(...item.settings);
		this.panel.dataset.visible = "true";
	}
}
