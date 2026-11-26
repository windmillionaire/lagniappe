import { STYLES } from "../generated/styles.mjs";
import { BaseElement } from "./base/baseElement.ts";
import { formatting } from "./formatting.ts";
import { primitives, wrapDateInput } from "./primitives.ts";

export class InputElement extends BaseElement {
	get value() {
		const input =
			this.elt instanceof HTMLInputElement
				? this.elt
				: this.elt?.querySelector("input");
		if (input) return input.value;
		if (this.submission === null || this.submission === undefined) return null;
		return String(this.submission);
	}

	changed(value: unknown) {
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

		const submission = this.submission;
		if (
			(typeof submission === "string" || submission instanceof Date) &&
			this.schema.input === "date"
		) {
			this._read.textContent = formatting.date(submission) || "";
		} else if (
			typeof submission === "string" &&
			submission &&
			this.schema.input === "time"
		) {
			this._read.textContent = formatting.time(submission);
		} else if (
			typeof submission === "string" &&
			submission &&
			this.schema.input === "tel"
		) {
			this._read.textContent = formatting.tel(submission);
		} else if (
			typeof submission === "string" &&
			submission &&
			this.schema.input === "email"
		) {
			this._read.appendChild(formatting.email(submission));
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

		const raw = primitives.input({
			label: this.label,
			name: this.schema.id || this.schema.name,
			type: this.schema.input || "text",
			placeholder: this.schema.placeholder,
			value: this.submission,
			disabled: this.renderer.readonly,
		});
		this._edit =
			!this.label &&
			this.schema.input === "date" &&
			!this.renderer.readonly &&
			raw instanceof HTMLInputElement
				? wrapDateInput(raw)
				: raw;

		const control = this._edit.matches?.("[data-role='date-input-wrap']")
			? this._edit
			: this._edit.querySelector("[data-role='date-input-wrap']") ||
				(this._edit.matches?.("input")
					? this._edit
					: this._edit.querySelector("input"));
		control?.classList.add("group-data-[mode=read]/element:hidden");

		return this._edit;
	}
}
