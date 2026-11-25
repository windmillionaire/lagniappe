import { ICONS } from "../generated/icons.mjs";

interface IconDefinition {
	glyph: string;
	fill: number;
	spin?: boolean;
	weight?: number;
}

export const iconDefinition = (name: string | null | undefined) => {
	let definition: unknown = ICONS;
	for (const part of String(name || "").split(".")) {
		if (!part || !definition || typeof definition !== "object") return null;
		definition = (definition as Record<string, unknown>)[part];
	}
	if (
		!definition ||
		typeof definition !== "object" ||
		!("glyph" in definition)
	) {
		return null;
	}
	return definition.glyph ? (definition as IconDefinition) : null;
};

export const setIcon = <T extends HTMLElement>(
	element: T,
	name: string | null | undefined,
	classes = "",
): T => {
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
	element.dataset.icon = String(name);
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

export const createIcon = (name: string, classes = "") => {
	return setIcon(document.createElement("span"), name, classes);
};
