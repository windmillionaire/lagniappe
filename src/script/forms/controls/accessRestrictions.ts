import { FacetsBox } from "../../elements/combobox/facets.mjs";
import type { FacetsUpdatedEvent, FormControlOptions } from "./loader.ts";

/**
 * Local administrator/group choices shared by Page, User Settings and Builder.
 */
export default class AccessRestrictions {
	declare private root: HTMLElement;
	declare private readonly: boolean;
	declare private onChange: () => void;
	declare private select: FacetsBox | null;
	declare private _destroyed: boolean;

	constructor(
		root: HTMLElement,
		{ readonly = false, onChange = () => {} }: FormControlOptions = {},
	) {
		this.root = root;
		this.readonly = readonly;
		this.onChange = onChange;
		this.select = null;
		this._destroyed = false;
		this._updated = this._updated.bind(this);
		this._change = this._change.bind(this);
		this._click = this._click.bind(this);
	}

	async init() {
		if (this.readonly) return;
		const input = this.root.querySelector<HTMLInputElement>(
			"[data-role='restrict-group-input']",
		);
		if (!input) throw new Error("Access restriction picker is missing");
		this.select = new FacetsBox(input);
		await this.select.init();
		if (this._destroyed) return;
		this.root.addEventListener("updated", this._updated);
		this.root.addEventListener("change", this._change);
		this.root.addEventListener("click", this._click);
	}

	get list() {
		return this.root.querySelector<HTMLUListElement>(
			"[data-role='restricted-group-list']",
		);
	}

	_updated(event: Event) {
		const select = this.select;
		if (!select || event.target !== select.element) return;
		const options = Object.entries(
			(event as FacetsUpdatedEvent).detail.options,
		);
		if (!options.length) return;
		const list = this.list;
		const template = this.root.querySelector<HTMLTemplateElement>(
			"[data-role='restriction-template']",
		);
		const admin = this.root.querySelector<HTMLInputElement>("[name='admin']");
		if (!list || !template || !admin)
			throw new Error("Access restriction fields are missing");
		const selected = new Set(
			Array.from(
				list.querySelectorAll<HTMLInputElement>("[name='group-key']"),
				(input) => input.value,
			),
		);
		admin.checked = false;
		for (const [key, option] of options) {
			if (selected.has(key)) continue;
			const item = template.content.firstElementChild?.cloneNode(true);
			if (!(item instanceof Element))
				throw new Error("Access restriction row template is empty");
			const input = item.querySelector<HTMLInputElement>("[name='group-key']");
			const name = item.querySelector("[data-role='group-name']");
			const button = item.querySelector("button");
			if (!input || !name || !button)
				throw new Error("Access restriction row fields are missing");
			input.value = key;
			name.textContent = option.name;
			button.dataset.key = key;
			list.append(item);
			selected.add(key);
		}
		select.clear({ notify: false });
		this.onChange();
	}

	_change(event: Event) {
		const input = event.target;
		if (
			!(input instanceof HTMLInputElement) ||
			input.name !== "admin" ||
			!input.checked
		)
			return;
		const list = this.list;
		if (!list) throw new Error("Access restriction list is missing");
		list.replaceChildren();
		this.select?.clear({ notify: false });
		this.onChange();
	}

	_click(event: Event) {
		const target = event.target;
		if (!(target instanceof Element)) return;
		const button = target.closest("[data-role='remove-restriction']");
		if (!button || !this.root.contains(button)) return;
		event.preventDefault();
		button.closest("li")?.remove();
		this.onChange();
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this.root.removeEventListener("updated", this._updated);
		this.root.removeEventListener("change", this._change);
		this.root.removeEventListener("click", this._click);
		this.select?.destroy();
	}
}
