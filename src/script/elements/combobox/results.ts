import { STYLES } from "../../generated/styles.mjs";
import { setIcon } from "../../shared/icons.ts";
import { localStore } from "../../shared/storage.ts";
import { formatting } from "../formatting.ts";
import type { ComboboxOption } from "./combobox.ts";

export type ResultDetails = ComboboxOption & {
	disabled?: boolean;
	icon?: string;
	index?: string;
	type?: string;
	link?: boolean;
	parent?: { id?: string; kind?: string; name?: string } | null;
};

type SearchResult = {
	id?: string;
	url?: string;
	details: ResultDetails;
	form_field?: string | null;
	form_value?: unknown;
	text?: string | null;
};

type ResultEntry = ResultDetails | SearchResult;

const SEARCH_ENTITY_PATTERN = /&(#(?:x[0-9a-f]+|\d+)|amp|apos|gt|lt|quot);/gi;
const SEARCH_ENTITIES = Object.freeze({
	amp: "&",
	apos: "'",
	gt: ">",
	lt: "<",
	quot: '"',
});

const decodeSearchEntities = (text: string) =>
	String(text).replace(SEARCH_ENTITY_PATTERN, (entity, name: string) => {
		if (!name.startsWith("#"))
			return (
				SEARCH_ENTITIES[name.toLowerCase() as keyof typeof SEARCH_ENTITIES] ??
				entity
			);

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
 */
const appendHighlightedSearchText = (element: HTMLElement, markup: string) => {
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

const option = (details: ResultDetails) => {
	const option = document.createElement("div");
	option.className = STYLES.dropdown.option.flow;
	option.setAttribute("role", "option");
	if (details.disabled) {
		option.setAttribute("aria-disabled", "true");
		option.classList.add("opacity-50", "cursor-not-allowed");
	}
	if (details.id) {
		option.id = details.id;
		option.dataset.id = details.id;
	}

	const decoration = details.icon && icon(details);
	if (decoration) option.appendChild(decoration);

	option.append(formatting.name(details));

	return option.outerHTML;
};

const icon = (details: ResultDetails) => {
	const iconType = details.icon || details.kind || details.type;
	if (iconType) {
		const container = document.createElement("span");
		container.className = "text-kind-default";
		container.dataset.kind = String(details.kind || details.index);
		const iconElement = container.appendChild(document.createElement("span"));
		setIcon(iconElement, iconType, STYLES.dropdown.icon);
		return container;
	}
};

const name = (details: ResultDetails) => {
	const p1 = document.createElement("p");

	const decoration = icon(details);
	if (decoration) p1.append(decoration);
	p1.append(formatting.name(details));

	return p1;
};

const search = (result: SearchResult) => {
	const option = document.createElement("div");
	option.className = STYLES.dropdown.search.link;
	option.setAttribute("role", "option");
	option.dataset.result = JSON.stringify(result);
	option.dataset.url = String(result.url);

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

const facet = (details: ResultDetails) => {
	const option = document.createElement("div");
	option.className = `${STYLES.dropdown.search.result}`;
	option.setAttribute("role", "option");
	option.dataset.details = JSON.stringify(details);
	option.dataset.id = String(details.id);
	option.dataset.name = String(details.name);
	option.dataset.kind = String(details.kind);

	option.appendChild(name(details));

	return option.outerHTML;
};

export class Results {
	declare index: string | undefined;
	declare added: ResultEntry[];

	constructor(index?: string) {
		this.index = index;
		this.added = [];
	}

	get options() {
		const key = `recent-${this.index}`;
		const recent = localStore.getJSON(key, []);
		if (Array.isArray(recent)) return recent as ResultEntry[];
		localStore.remove(key);
		return [];
	}

	add(option: ResultEntry) {
		this.added.unshift(option);
	}

	save(option: HTMLElement) {
		const recent = this.options;
		let filtered: ResultEntry[] | undefined;
		if (this.index === "search" && option.dataset.result) {
			filtered = recent.filter((o) => o.url !== option.dataset.url);
			const result: SearchResult = JSON.parse(option.dataset.result);
			result.url = option.dataset.url;
			filtered.unshift(result);
		} else if (option.dataset.id) {
			filtered = recent.filter((o) => o.id !== option.dataset.id);
			const details: ResultDetails = JSON.parse(String(option.dataset.details));
			filtered.unshift(details);
		}
		if (Array.isArray(filtered)) {
			localStore.setJSON(`recent-${this.index}`, filtered.slice(0, 10));
		}
	}

	unique(options: ResultEntry[]) {
		return options.filter(
			(o, index, self) => index === self.findIndex((t) => t.id === o.id),
		);
	}

	create(items: ResultEntry[] = []) {
		let options = items;
		if (!items.length) {
			options = this.unique([...this.added, ...this.options]).slice(0, 10);
		}
		if (!options.length) return "";

		// Each index stores entries in the shape of its corresponding renderer.
		if (this.index === "search") {
			return (options as SearchResult[]).map(search).join("");
		} else if (this.index) {
			return options.map(facet).join("");
		} else {
			return options.map(option).join("");
		}
	}
}
