/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b13679a7';
import { c as createIcon, s as setIcon } from './icons.js?v=b13679a7';
import { f as formatting } from './formatting.js?v=b13679a7';

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
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_active_action_buttons_preserve_full_width_icon_slots
 * @features ui-action
 * @dimensions loading-state fixed-layout
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
	/**
	 * @testable false
	 * @covered-by src/script/elements/buttons.mjs::active
	 * @reason slot updates are exercised through each public active-button state
	 */
	const setState = (icon, text) => {
		let textElt = buttonElt.querySelector("[data-role='text']");
		if (!textElt) {
			textElt = document.createElement("span");
			textElt.dataset.role = "text";
			buttonElt.replaceChildren(textElt);
		}
		textElt.textContent = text;

		let iconElt = buttonElt.querySelector("[data-role='icon']");
		if (!iconElt) {
			iconElt = document.createElement("span");
			iconElt.dataset.role = "icon";
			iconElt.setAttribute("aria-hidden", "true");
			buttonElt.prepend(iconElt);
		}
		if (icon) {
			iconElt.replaceChildren(createIcon(icon));
			iconElt.dataset.visible = "true";
		} else {
			iconElt.replaceChildren();
			iconElt.dataset.visible = "false";
		}
	};

	setState(attributes.icon, defaultText);

	return {
		element: buttonElt,
		activate: (activeText = null, kind = null) => {
			buttonElt.disabled = true;
			const text = activeText || processingText || defaultText;

			if (kind) buttonElt.dataset.kind = kind;
			setState(processingIcon, text);
		},
		deactivate: (inactiveText = null, kind = null) => {
			buttonElt.disabled = false;
			const text = inactiveText || completedText || defaultText;

			if (kind) buttonElt.dataset.kind = kind;
			setState(completedIcon, text);
		},
	};
};

const buttons = {
	default: button,
	submit,
	active,
};

export { buttons as b };
