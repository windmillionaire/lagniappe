/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=be0d9638';
import { s as setIcon } from './icons.js?v=be0d9638';
import { f as formatting } from './formatting.js?v=be0d9638';

/**
 * @testable infrastructure
 * @covered-by src/script/elements/buttons.mjs::button
 */
const buttonContents = (icon, text) => {
	if (icon && text) {
		return formatting.iconLabel({
			icon,
			content: text,
		});
	}
	if (icon) {
		const iconElt = document.createElement("span");
		setIcon(iconElt, icon);
		return iconElt;
	}
	const textElt = document.createElement("span");
	textElt.textContent = text;
	return textElt;
};

/**
 * @testable infrastructure
 */
const submit = (attributes) => {
	return button({
		type: "submit",
		style: STYLES.button.submit,
		...attributes,
	});
};

/**
 * @testable infrastructure
 */
const button = (attributes) => {
	const {
		text = "",
		type = "button",
		icon = null,
		style = STYLES.button.submit,
		kind = null,
		role = null,
		data = {},
		classes = [],
	} = attributes;

	const buttonElt = document.createElement("button");
	buttonElt.type = type;
	buttonElt.className = style;

	if (icon || text) buttonElt.appendChild(buttonContents(icon, text));

	if (kind) buttonElt.dataset.kind = kind;
	if (role) buttonElt.dataset.role = role;

	for (const [k, v] of Object.entries(data)) {
		if (v != null) buttonElt.dataset[k] = v;
	}

	if (classes.length > 0) {
		buttonElt.classList.add(...classes);
	}

	return buttonElt;
};

/**
 * @testable infrastructure
 */
const active = (attributes) => {
	const buttonElt = attributes.existingButton || button(attributes);
	const {
		defaultText = attributes.defaultText ||
			attributes.text ||
			buttonElt.textContent,
		processingText = attributes.processingText || false,
		processingIcon = attributes.processingIcon || "spinner",
		completedText = attributes.completedText ||
			attributes.text ||
			buttonElt.textContent,
		completedIcon = attributes.completedIcon || attributes.icon,
	} = attributes;

	return {
		element: buttonElt,
		activate: (activeText = null, kind = null) => {
			buttonElt.disabled = true;
			const text = activeText || processingText || defaultText;

			if (kind) buttonElt.dataset.kind = kind;

			if (processingIcon) {
				buttonElt.replaceChildren(buttonContents(processingIcon, text));
			} else {
				buttonElt.replaceChildren(buttonContents(null, text));
			}
		},
		deactivate: (inactiveText = null, kind = null) => {
			buttonElt.disabled = false;
			const text = inactiveText || completedText || defaultText;

			if (kind) buttonElt.dataset.kind = kind;

			if (completedIcon) {
				buttonElt.replaceChildren(buttonContents(completedIcon, text));
			} else {
				buttonElt.replaceChildren(buttonContents(null, text));
			}
		},
	};
};

const buttons = {
	default: button,
	submit,
	active,
};

export { buttons as b };
