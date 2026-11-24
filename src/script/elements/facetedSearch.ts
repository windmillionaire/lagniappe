import { STYLES } from "../generated/styles.mjs";
import { BaseElement } from "./base/baseElement.ts";
import { FacetsBox, isFacetOption } from "./combobox/facets.ts";
import { formatting } from "./formatting.ts";
import { primitives } from "./primitives.ts";

export class FacetedSearchElement extends BaseElement {
	declare combobox?: FacetsBox;

	active(value: unknown) {
		return (
			(typeof value === "string"
				? this.combobox?.values.has(value)
				: undefined) ??
			this.values.some((option) => option.id === value || option === value)
		);
	}

	get values() {
		let submission: unknown = this.submission;
		if (typeof submission === "string") {
			submission = JSON.parse(submission);
			return (Array.isArray(submission) ? submission : [submission]).filter(
				isFacetOption,
			);
		}
		return isFacetOption(submission) ? [submission] : [];
	}

	get read() {
		if (this._read) return this._read;

		const read = document.createElement("div");
		read.className = "flex flex-row flex-wrap gap-2";
		read.dataset.kind = String(this.renderer.kind);

		this.values.forEach((item) => {
			const container = read.appendChild(document.createElement("div"));
			container.className = STYLES.form.submission.default;
			container.appendChild(formatting.name(item));
		});

		read.classList.add("group-data-[mode=edit]/element:hidden");
		this._read = read;
		return read;
	}

	get edit() {
		if (this._edit) return this._edit;

		this._edit = primitives.input({
			label: this.schema.title || this.schema.label,
			name: this.schema.id || this.schema.name,
			data: {
				placeholder: this.schema.placeholder || "search...",
				multiple: this.schema.multiple,
				kind: this.renderer.kind,
				index: this.schema.index,
				creatable: this.schema.creatable,
			},
		});
		this._edit.querySelector("input")?.setAttribute("lp-select", "");

		const combobox = new FacetsBox(this._edit);
		this.combobox = combobox;

		this.values.forEach((value) => {
			combobox.addOption(value);
		});
		combobox.init();
		this.destroyables.push(combobox);

		this._edit
			.querySelector("[lp-select]")
			?.classList.add("group-data-[mode=read]/element:hidden");

		return this._edit;
	}

	clear() {
		this.combobox?.clear();
		this.submission = null;
	}

	destroy() {
		this.combobox?.destroy();
	}
}
