import { STYLES } from "styles";
import { FacetsBox } from "../elements/combobox";
import { BaseElement } from "./base/baseElement";
import { formatting } from "./formatting";
import { primitives } from "./primitives";

/**
 * @testable infrastructure
 */
export class FacetedSearchElement extends BaseElement {
	active(value) {
		return (
			this.combobox?.values.has(value) ??
			this.values.some((v) => v?.id === value || v === value)
		);
	}

	get values() {
		let submission = this.submission;
		if (typeof this.submission === "string") {
			submission = JSON.parse(this.submission);
			return Array.isArray(submission) ? submission : [submission];
		} else if (submission && typeof submission === "object") {
			return [submission];
		}
		return [];
	}

	get read() {
		if (this._read) return this._read;

		this._read = document.createElement("div");
		this._read.className = "flex flex-row flex-wrap gap-2";
		this._read.dataset.kind = this.renderer.kind;

		this.values.forEach((item) => {
			const container = this._read.appendChild(document.createElement("div"));
			container.className = STYLES.form.submission.default;
			container.appendChild(formatting.name(item));
			this._read.appendChild(container);
		});

		this._read.classList.add("group-data-[mode=edit]/element:hidden");
		return this._read;
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
		this._edit.querySelector("input").setAttribute("lp-select", "");

		this.combobox = new FacetsBox(this._edit);

		this.values.forEach((value) => {
			this.combobox.addOption(value);
		});
		this.combobox.init();
		this.destroyables.push(this.combobox);

		this._edit
			.querySelector("[lp-select]")
			.classList.add("group-data-[mode=read]/element:hidden");

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
