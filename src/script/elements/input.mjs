import { STYLES } from "styles";
import { BaseElement } from "./base/baseElement";
import { formatting } from "./formatting";
import { primitives } from "./primitives";

/**
 * @testable infrastructure
 */
export class InputElement extends BaseElement {
	get value() {
		const input = this.elt?.matches?.("input")
			? this.elt
			: this.elt?.querySelector("input");
		if (input) return input.value;
		if (this.submission === null || this.submission === undefined) return null;
		return String(this.submission);
	}

	changed(value) {
		if (this.value === String(value ?? "")) return false;
		return true;
	}

	clear() {
		this.submission = null;
		const input = this._edit?.querySelector("input");
		if (input) input.value = "";
	}

	focus() {
		const input = this._edit?.querySelector("input");
		if (input) input.focus();
	}

	get read() {
		if (this._read) return this._read;

		this._read = document.createElement("p");
		this._read.className = STYLES.form.submission.default;

		if (this.submission && this.schema.input === "date") {
			this._read.textContent = formatting.date(this.submission) || "";
		} else if (this.submission && this.schema.input === "time") {
			this._read.textContent = formatting.time(this.submission);
		} else if (this.submission && this.schema.input === "tel") {
			this._read.textContent = formatting.tel(this.submission);
		} else if (this.submission && this.schema.input === "email") {
			this._read.appendChild(formatting.email(this.submission));
		} else {
			this._read.textContent = this.hasSubmission
				? String(this.submission)
				: "";
		}
		this._read.classList.add("group-data-[mode=edit]/element:hidden");

		return this._read;
	}

	get cell() {
		if (this.cellEditing) return this.cellEdit;
		if (!this.hasSubmission) return null;
		return this.read.innerHTML;
	}

	get edit() {
		if (this._edit) return this._edit;

		this._edit = primitives.input({
			label: this.label,
			name: this.schema.id || this.schema.name,
			type: this.schema.input || "text",
			placeholder: this.schema.placeholder,
			value: this.submission,
			disabled: this.renderer.readonly,
		});

		const input = this._edit.matches?.("input")
			? this._edit
			: this._edit.querySelector("input");
		input?.classList.add("group-data-[mode=read]/element:hidden");

		return this._edit;
	}
}
