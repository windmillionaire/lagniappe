import { ICONS } from "icons";

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_frontend_icon_helpers_render_structured_material_symbols
 * @matrix frontend-icons : lookup nested-ids registry
 */
export const iconDefinition = (name) => {
	let definition = ICONS;
	for (const part of String(name || "").split(".")) {
		if (!part || !definition || typeof definition !== "object") return null;
		definition = definition[part];
	}
	return definition?.glyph ? definition : null;
};

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_frontend_icon_helpers_render_structured_material_symbols
 * @matrix frontend-icons : accessibility animation fill semantic-markup weight
 */
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

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_frontend_icon_helpers_render_structured_material_symbols
 * @matrix frontend-icons : element-creation semantic-markup
 */
export const createIcon = (name, classes = "") => {
	return setIcon(document.createElement("span"), name, classes);
};
