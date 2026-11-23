import { ICONS } from "../generated/icons.mjs";

export const iconDefinition = (name) => {
	let definition = ICONS;
	for (const part of String(name || "").split(".")) {
		if (!part || !definition || typeof definition !== "object") return null;
		definition = definition[part];
	}
	return definition?.glyph ? definition : null;
};

export const setIcon = (element, name, classes = "") => {
	const definition = iconDefinition(name);
	if (!definition) {
		element.replaceChildren();
		element.removeAttribute("data-icon");
		return element;
	}

	const classNames = ["icon"];
	if (definition.spin) classNames.push("icon-spin");
	if (classes) classNames.push(...String(classes).split(/\s+/).filter(Boolean));

	element.className = classNames.join(" ");
	element.dataset.icon = name;
	element.dataset.fill = String(definition.fill);
	element.setAttribute("aria-hidden", "true");
	if (definition.weight) {
		element.dataset.weight = String(definition.weight);
	} else {
		delete element.dataset.weight;
	}
	const glyph = document.createElement("span");
	glyph.className = "icon-glyph";
	glyph.textContent = definition.glyph;
	element.replaceChildren(glyph);
	return element;
};

export const createIcon = (name, classes = "") => {
	return setIcon(document.createElement("span"), name, classes);
};
