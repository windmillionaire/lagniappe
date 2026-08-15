/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b2884058';
import { s as setIcon } from './icons.js?v=b2884058';
import { f as formatting } from './formatting.js?v=b2884058';

const SEARCH_ENTITY_PATTERN = /&(#(?:x[0-9a-f]+|\d+)|amp|apos|gt|lt|quot);/gi;
const SEARCH_ENTITIES = Object.freeze({
	amp: "&",
	apos: "'",
	gt: ">",
	lt: "<",
	quot: '"',
});

/**
 * @testable false
 * @covered-by src/script/elements/combobox/results.mjs::Results.create
 * @reason entity decoding is exercised through safe highlighted result rendering
 */
const decodeSearchEntities = (text) =>
	String(text).replace(SEARCH_ENTITY_PATTERN, (entity, name) => {
		if (!name.startsWith("#"))
			return SEARCH_ENTITIES[name.toLowerCase()] ?? entity;

		const hexadecimal = name[1]?.toLowerCase() === "x";
		const value = Number.parseInt(
			name.slice(hexadecimal ? 2 : 1),
			hexadecimal ? 16 : 10,
		);
		if (
			!Number.isInteger(value) ||
			value <= 0 ||
			value > 0x10ffff ||
			(value >= 0xd800 && value <= 0xdfff)
		) {
			return "\uFFFD";
		}
		return String.fromCodePoint(value);
	});

/**
 * Preserve only the server's generated <b> highlight markers. Every text
 * segment is decoded and appended as a text node, so unexpected markup never
 * becomes executable DOM.
 *
 * @testable false
 * @covered-by src/script/elements/combobox/results.mjs::Results.create
 * @reason allowlisted highlight rendering is exercised through recent search results
 */
const appendHighlightedSearchText = (element, markup) => {
	let target = element;
	for (const part of String(markup).split(/(<\/?b>)/gi)) {
		if (part.toLowerCase() === "<b>") {
			target = document.createElement("b");
			element.appendChild(target);
		} else if (part.toLowerCase() === "</b>") {
			target = element;
		} else if (part) {
			target.appendChild(document.createTextNode(decodeSearchEntities(part)));
		}
	}
};

/**
 * @testable infrastructure
 */
const option = (details) => {
	const option = document.createElement("div");
	option.className = STYLES.dropdown.option.flow;
	option.setAttribute("role", "option");
	if (details.id) {
		option.id = details.id;
		option.dataset.id = details.id;
	}

	if (details.icon) {
		option.appendChild(icon(details));
	}

	option.append(formatting.name(details));

	return option.outerHTML;
};

/**
 * @testable infrastructure
 */
const icon = (details) => {
	const iconType = details.icon || details.kind || details.type;
	if (iconType) {
		const container = document.createElement("span");
		container.className = "text-kind-default";
		container.dataset.kind = details.kind || details.index;
		const iconElement = container.appendChild(document.createElement("span"));
		setIcon(iconElement, iconType, STYLES.dropdown.icon);
		return container;
	}
};

/**
 * @testable infrastructure
 */
const name = (details) => {
	const p1 = document.createElement("p");

	p1.append(...[icon(details), formatting.name(details)].filter(Boolean));

	return p1;
};

/**
 * @testable infrastructure
 */
const search = (result) => {
	const option = document.createElement("div");
	option.className = STYLES.dropdown.search.link;
	option.setAttribute("role", "option");
	option.dataset.result = JSON.stringify(result);
	option.dataset.url = result.url;

	option.appendChild(name(result.details));

	if (result.form_field) {
		const p2 = document.createElement("p");
		p2.className = `italic font-normal text-base-default`;

		const fieldSpan = document.createElement("span");
		fieldSpan.className = "font-semibold text-form-default";
		fieldSpan.textContent = `${result.form_field}:`;
		p2.appendChild(fieldSpan);

		const formValueText = document.createElement("span");
		formValueText.className = "ml-1";
		formValueText.textContent = `${result.form_value}`;
		p2.appendChild(formValueText);

		option.appendChild(p2);
	}

	if (result.text) {
		const p3 = document.createElement("p");
		p3.className = `italic font-normal text-base-default`;
		appendHighlightedSearchText(p3, result.text);
		option.appendChild(p3);
	}

	return option.outerHTML;
};

/**
 * @testable infrastructure
 */
const facet = (details) => {
	const option = document.createElement("div");
	option.className = `${STYLES.dropdown.search.result}`;
	option.setAttribute("role", "option");
	option.dataset.details = JSON.stringify(details);
	option.dataset.id = details.id;
	option.dataset.name = details.name;
	option.dataset.kind = details.kind;

	option.appendChild(name(details));

	return option.outerHTML;
};

/**
 * @testable infrastructure
 */
class Results {
	constructor(index) {
		this.index = index;
		this.added = [];
	}

	get options() {
		return JSON.parse(localStorage.getItem(`recent-${this.index}`) || "[]");
	}

	add(option) {
		this.added.unshift(option);
	}

	save(option) {
		const recent = this.options;
		let filtered;
		if (this.index === "search" && option.dataset.result) {
			filtered = recent.filter((o) => o.url !== option.dataset.url);
			const result = JSON.parse(option.dataset.result);
			result.url = option.dataset.url;
			filtered.unshift(result);
		} else if (option.dataset.id) {
			filtered = recent.filter((o) => o.id !== option.dataset.id);
			const details = JSON.parse(option.dataset.details);
			filtered.unshift(details);
		}
		if (Array.isArray(filtered)) {
			localStorage.setItem(
				`recent-${this.index}`,
				JSON.stringify(filtered.slice(0, 10)),
			);
		}
	}

	unique(options) {
		return options.filter(
			(o, index, self) => index === self.findIndex((t) => t.id === o.id),
		);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_023_entity_name_formatting.py::test_recent_combobox_results_reuse_shared_parent_name_formatting
	 * @tests tests_js/test_023_entity_name_formatting.py::test_recent_search_snippets_allow_only_highlight_markup
	 * @pair combobox:parent-separator
	 * @pair combobox:recent-results
	 * @pair entity-name:recent-results
	 * @pair search:snippet-safety
	 */
	create(items = []) {
		let options = items;
		if (!items.length) {
			options = this.unique([...this.added, ...this.options]).slice(0, 10);
		}
		if (!options.length) return "";

		if (this.index === "search") {
			return options.map(search).join("");
		} else if (this.index) {
			return options.map(facet).join("");
		} else {
			return options.map(option).join("");
		}
	}
}

export { Results as R };
