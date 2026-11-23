import { FacetsBox } from "../../elements/combobox/facets.mjs";

/**
 * Local administrator/group choices shared by Page, User Settings and Builder.
 */
export default class AccessRestrictions {
	constructor(root, { readonly = false, onChange = () => {} } = {}) {
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
		this.select = new FacetsBox(
			this.root.querySelector("[data-role='restrict-group-input']"),
		);
		await this.select.init();
		if (this._destroyed) return;
		this.root.addEventListener("updated", this._updated);
		this.root.addEventListener("change", this._change);
		this.root.addEventListener("click", this._click);
	}

	get list() {
		return this.root.querySelector("[data-role='restricted-group-list']");
	}

	_updated(event) {
		if (event.target !== this.select.element) return;
		const options = Object.entries(event.detail.options);
		if (!options.length) return;
		const list = this.list;
		const template = this.root.querySelector(
			"[data-role='restriction-template']",
		);
		const selected = new Set(
			Array.from(
				list.querySelectorAll("[name='group-key']"),
				(input) => input.value,
			),
		);
		this.root.querySelector("[name='admin']").checked = false;
		for (const [key, option] of options) {
			if (selected.has(key)) continue;
			const item = template.content.firstElementChild.cloneNode(true);
			item.querySelector("[name='group-key']").value = key;
			item.querySelector("[data-role='group-name']").textContent = option.name;
			item.querySelector("button").dataset.key = key;
			list.append(item);
			selected.add(key);
		}
		this.select.clear({ notify: false });
		this.onChange();
	}

	_change(event) {
		if (event.target.name !== "admin" || !event.target.checked) return;
		this.list.replaceChildren();
		this.select.clear({ notify: false });
		this.onChange();
	}

	_click(event) {
		const button = event.target.closest("[data-role='remove-restriction']");
		if (!button || !this.root.contains(button)) return;
		event.preventDefault();
		button.closest("li").remove();
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
