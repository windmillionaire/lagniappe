import { STYLES } from "../generated/styles.mjs";
import { setIcon } from "../shared/icons.ts";
import { BaseElement } from "./base/baseElement.ts";
import { primitives } from "./primitives.ts";

export class CheckboxElement extends BaseElement {
	active() {
		const input = this.elt?.querySelector("input");
		if (input) return input.checked;
		if (typeof this.submission === "boolean") return this.submission;
		return Boolean(this.schema.checked);
	}

	get value() {
		return this.active();
	}

	changed(value: unknown) {
		if (this.value === value) return false;
		return true;
	}

	get cell() {
		if (this.cellEditing) return this.cellEdit;
		if (!this.submission) return null;

		const icon = primitives.icon({ icon: "check", kind: "success" });
		return icon.outerHTML;
	}

	get read() {
		if (this._read) return this._read;
		if (!this.readonly) return null;

		this._read = document.createElement("div");
		this._read.className = STYLES.form.submission.default;

		const icon = this._read.appendChild(document.createElement("span"));
		if (this.submission) {
			setIcon(icon, "check", "text-success mr-1.5");
			this._read.append(icon, document.createTextNode("True"));
		} else {
			setIcon(icon, "x", "text-failure mr-1.5");
			this._read.append(icon, document.createTextNode("False"));
		}

		this._read.classList.add(
			"group-data-[mode=edit]/element:hidden",
			"text-base-dark",
		);

		return this._read;
	}
	get edit() {
		if (this._edit) return this._edit;

		const value =
			typeof this.submission === "boolean"
				? this.submission
				: this.schema.checked;

		this._edit = primitives.checkbox({
			label: this.label,
			checked: value,
			name: this.schema.id || this.schema.name,
			disabled: this.renderer.readonly,
			styles: {
				label: STYLES.checkbox.label,
			},
		});
		return this._edit;
	}
}
