/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bb2fbed3';
import { s as setIcon } from './icons.js?v=bb2fbed3';

/**
 * @testable infrastructure
 */
const setAttributes = (elt, attributes) => {
	if (attributes.name) elt.name = attributes.name;
	if (attributes.id) elt.id = attributes.id;
	if (attributes.value != null) elt.value = attributes.value;
	if (attributes.required) elt.required = true;

	if (attributes.disabled) {
		elt.classList.add("pointer-events-none", "select-none");
		elt.readOnly = true;
		elt.tabIndex = -1;
		elt.disabled = true;
	}
	for (const [k, v] of Object.entries(attributes.data || {})) {
		if (v != null) elt.dataset[k] = v;
	}
};

/**
 * @testable infrastructure
 */
const label = (attributes) => {
	const {
		label,
		icon,
		role = "label",
		tag = "label",
		styles = {},
	} = attributes;

	const labelElt = document.createElement(tag);
	labelElt.className = `${styles.label ?? STYLES.form.elementLabel}`;

	const container = labelElt.appendChild(div({ role }));
	container.className = styles.container ?? "flex flex-row items-center gap-1";

	if (icon) {
		const iconElt = container.appendChild(document.createElement("span"));
		setIcon(iconElt, icon, styles.icon ?? STYLES.icon.default);
		const span = container.appendChild(document.createElement("span"));
		span.textContent = label;
	} else {
		const span = container.appendChild(document.createElement("span"));
		span.textContent = label;
	}

	return labelElt;
};

/**
 * @testable infrastructure
 */
const input = (attributes) => {
	const { type = "text", placeholder, styles = {} } = attributes;

	const elt = document.createElement("input");
	elt.type = type;
	elt.autocomplete = "off";
	elt.setAttribute("data-1p-ignore", "");

	if (placeholder) {
		elt.placeholder = placeholder;
		elt.dataset.placeholder = placeholder;
	}

	elt.className = styles.input ?? STYLES.input;
	attributes.name = attributes.name ?? attributes.id;
	attributes.data = {
		kind: attributes.kind,
		index: attributes.index,
		...attributes.data,
	};
	setAttributes(elt, attributes);

	if (["text", "email", "url", "tel"].includes(type)) {
		elt.pattern = ".*";
	} else if (type === "number") {
		elt.step = "any";
	}

	if (attributes.label) {
		const container = label(attributes);
		container.appendChild(elt);
		container.classList.add("flex-col");
		return container;
	}

	return elt;
};

/**
 * @testable infrastructure
 */
const textarea = (attributes) => {
	const { rows = 3, placeholder, styles = {} } = attributes;

	const elt = document.createElement("textarea");
	elt.rows = rows;
	if (placeholder) elt.placeholder = placeholder;
	elt.className = styles.textarea ?? STYLES.textarea;
	setAttributes(elt, attributes);

	if (attributes.label) {
		const container = label(attributes);
		container.appendChild(elt);
		container.classList.add("flex-col");
		return container;
	}

	return elt;
};

/**
 * @testable infrastructure
 */
const checkbox = (attributes) => {
	const { checked = false, styles = {}, visible = true } = attributes;

	styles.label ??= STYLES.checkbox.label;

	let element = null;
	const wrapper = document.createElement("div");
	wrapper.className = styles.container ?? STYLES.checkbox.container;

	const elt = wrapper.appendChild(document.createElement("input"));
	elt.type = "checkbox";
	elt.checked = checked;
	elt.className = styles.checkbox ?? STYLES.checkbox.default;
	setAttributes(elt, attributes);

	const icon = wrapper.appendChild(document.createElement("span"));
	setIcon(icon, "check", styles.icon ?? STYLES.checkbox.icon);

	if (attributes.label) {
		element = document.createElement("label");
		element.dataset.role = "label";
		const text = document.createElement("span");
		text.textContent = attributes.label;
		element.className = styles.label ?? STYLES.checkbox.label;
		wrapper.classList.add("order-first");
		element.append(wrapper, text);
	} else {
		element = wrapper;
	}

	if (!visible) element.dataset.visible = "false";
	return element;
};

/**
 * @testable infrastructure
 */
const radio = (attributes) => {
	const { checked = false, styles = {} } = attributes;

	const elt = document.createElement("input");
	elt.type = "radio";
	elt.checked = checked;
	elt.className = styles.radio ?? STYLES.radio.default;
	setAttributes(elt, attributes);

	const labelElt = document.createElement("label");
	labelElt.dataset.role = "label";
	const text = document.createElement("span");
	text.textContent = attributes.label;
	labelElt.className = styles.label ?? STYLES.radio.label;
	elt.classList.add("order-first");
	labelElt.append(elt, text);

	return labelElt;
};

/**
 * @testable infrastructure
 */
const select = (attributes) => {
	const { placeholder, options = [], styles = {} } = attributes;

	const container = document.createElement("div");
	container.className = STYLES.select.wrapper;
	if (attributes.kind) container.dataset.kind = attributes.kind;

	const elt = container.appendChild(document.createElement("select"));
	elt.className = styles.select ?? STYLES.select.default;
	setAttributes(elt, attributes);

	if (attributes.name) elt.name = attributes.name;
	if (attributes.id) elt.id = attributes.id;
	if (attributes.required) elt.required = true;

	if (placeholder) {
		elt.dataset.placeholder = placeholder;
		const pl = elt.appendChild(document.createElement("option"));
		pl.textContent = placeholder;
		pl.value = "";
		pl.selected = true;
		pl.hidden = true;
	}

	for (const o of options) {
		const opt = elt.appendChild(document.createElement("option"));
		opt.value = o.value;
		opt.textContent = o.label;
		opt.dataset.details = JSON.stringify(
			o.details ?? { name: o.label, id: o.value },
		);
		if (o.selected) opt.selected = true;
	}

	const icon = container.appendChild(document.createElement("span"));
	const iconType =
		attributes.selectIcon || (options.length ? "dropdown" : "search");
	setIcon(icon, iconType, STYLES.select.icon);

	container.setAttribute("lp-select", "");

	if (attributes.label) {
		const labelElt = label(attributes);
		labelElt.appendChild(container);
		labelElt.classList.add("flex-col");
		return labelElt;
	}

	return container;
};

/**
 * @testable infrastructure
 */
const badge = (attributes) => {
	const { icon, text, kind, styles = {} } = attributes;

	const badge = document.createElement("div");
	badge.className = styles.badge ?? STYLES.badge.default;
	badge.dataset.kind = kind;

	const badgeIcon = badge.appendChild(document.createElement("span"));
	setIcon(badgeIcon, icon, styles.icon ?? STYLES.badge.icon);

	const name = badge.appendChild(document.createElement("span"));
	name.textContent = text;
	name.className = styles.text ?? "text-kind-default";

	return badge;
};

/**
 * @testable infrastructure
 */
const toggle = (attributes) => {
	const { icon, styles = {} } = attributes;
	const toggle = document.createElement("button");
	toggle.className = styles.container ?? STYLES.toggle.container;

	const iconElt = toggle.appendChild(document.createElement("span"));
	setIcon(iconElt, icon, styles.icon ?? "");
	setAttributes(toggle, attributes);

	return toggle;
};

/**
 * @testable infrastructure
 */
const explain_prompt = (attributes) => {
	const { visible = false, classes = [], explain = null } = attributes;

	const button = document.createElement("button");
	button.type = "submit";
	button.dataset.role = "explain";
	if (explain) button.dataset.explain = explain;
	button.className = STYLES.button.explain;
	if (visible) button.dataset.visible = "true";

	const promptIcon = button.appendChild(document.createElement("span"));
	setIcon(promptIcon, "prompt", "text-kind-default");
	const promptText = button.appendChild(document.createElement("span"));
	promptText.textContent = "Initial Prompt";

	if (classes.length > 0) {
		button.classList.add(...classes);
	}

	return button;
};

/**
 * @testable infrastructure
 */
const loading = () => {
	const wrapper = document.createElement("div");
	wrapper.className = STYLES.loading.wrapper;

	const pulse = "h-4 bg-base-light rounded-full animate-pulse";
	const delays = [0, 200, 400];
	wrapper.innerHTML = delays
		.map(
			(d) =>
				`<div class="${pulse}${d ? ` [animation-delay:${d}ms]` : ""}"></div>`,
		)
		.join("");

	return wrapper;
};

/**
 * @testable infrastructure
 */
const icon = (attributes) => {
	const { icon, kind = null, role = null, style = null } = attributes;

	const elt = document.createElement("span");
	if (kind) elt.dataset.kind = kind;
	if (role) elt.dataset.role = role;
	setIcon(elt, icon, `${style ?? ""} text-kind-default`.trim());

	return elt;
};

/**
 * @testable infrastructure
 */
const div = (attributes) => {
	const { kind = null, role = null, style = null, data = {} } = attributes;

	const elt = document.createElement("div");
	if (kind) elt.dataset.kind = kind;
	if (role) elt.dataset.role = role;
	if (style) elt.className = style;
	for (const [k, v] of Object.entries(data)) {
		if (v != null) elt.dataset[k] = v;
	}

	return elt;
};

/**
 * @testable infrastructure
 */
const error = (message) => {
	const error = document.createElement("div");
	error.className = STYLES.message;
	error.dataset.role = "error";
	error.dataset.visible = "false";
	error.dataset.kind = "error";
	if (message) error.textContent = message;
	return error;
};

/**
 * @testable infrastructure
 */
const span = (attributes) => {
	const { text = "", style = null, data = {} } = attributes;
	const span = document.createElement("span");
	span.textContent = text;
	if (style) span.className = style;
	for (const [k, v] of Object.entries(data)) {
		if (v != null) span.dataset[k] = v;
	}
	return span;
};

const primitives = {
	checkbox,
	input,
	radio,
	textarea,
	select,
	label,
	badge,
	toggle,
	loading,
	icon,
	div,
	error,
	explain_prompt,
	span,
};

export { primitives as p };
