import { STYLES } from "../generated/styles.mjs";
import { createIcon, setIcon } from "../shared/icons.ts";
import { formatting } from "./formatting.ts";

interface ButtonAttributes {
	text?: string;
	type?: HTMLButtonElement["type"];
	icon?: string | null;
	style?: string;
	kind?: string | null;
	role?: string | null;
	data?: Record<string, string | number | boolean | null | undefined>;
	classes?: string[];
}

interface ActiveButtonAttributes extends ButtonAttributes {
	existingButton?: HTMLButtonElement | null;
	defaultText?: string | null;
	processingText?: string | false | null;
	processingIcon?: string | null;
	completedText?: string | null;
	completedIcon?: string | null;
}

const buttonContents = (icon: string | null, text: string) => {
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

const submit = (attributes: ButtonAttributes) => {
	return button({
		type: "submit",
		style: STYLES.button.submit,
		...attributes,
	});
};

const button = (attributes: ButtonAttributes) => {
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
		if (v != null) buttonElt.dataset[k] = String(v);
	}

	if (classes.length > 0) {
		buttonElt.classList.add(...classes);
	}

	return buttonElt;
};

const active = (attributes: ActiveButtonAttributes) => {
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
	const setState = (icon: string | null | undefined, text: string | null) => {
		let textElt = buttonElt.querySelector<HTMLElement>("[data-role='text']");
		if (!textElt) {
			textElt = document.createElement("span");
			textElt.dataset.role = "text";
			buttonElt.replaceChildren(textElt);
		}
		textElt.textContent = text;

		let iconElt = buttonElt.querySelector<HTMLElement>("[data-role='icon']");
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
		activate: (
			activeText: string | null = null,
			kind: string | null = null,
		) => {
			buttonElt.disabled = true;
			const text = activeText || processingText || defaultText;

			if (kind) buttonElt.dataset.kind = kind;
			setState(processingIcon, text);
		},
		deactivate: (
			inactiveText: string | null = null,
			kind: string | null = null,
		) => {
			buttonElt.disabled = false;
			const text = inactiveText || completedText || defaultText;

			if (kind) buttonElt.dataset.kind = kind;
			setState(completedIcon, text);
		},
	};
};

export const buttons = {
	default: button,
	submit,
	active,
};
