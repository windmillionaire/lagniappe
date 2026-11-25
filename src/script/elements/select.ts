import { STYLES } from "../generated/styles.mjs";
import { areEqual } from "../shared/utilities.ts";
import { BaseElement } from "./base/baseElement.ts";
import { SelectBox } from "./combobox/index.ts";
import { primitives } from "./primitives.ts";

export class SelectElement extends BaseElement {
	declare combobox?: SelectBox;

	get value() {
		if (this.combobox?.values.size) {
			const values = Array.from(this.combobox.values);
			return this.schema.multiple ? values : values[0];
		}
		return null;
	}

	changed(value: unknown) {
		if (areEqual(this.value, value)) return false;
		return true;
	}

	active(value: unknown) {
		return (
			typeof value === "string" &&
			(this.combobox?.values.has(value) ?? this.values.includes(value))
		);
	}

	get values() {
		if (!this.hasSubmission) return [];
		const submission = this.submission;
		return typeof submission === "string"
			? [submission]
			: Array.isArray(submission)
				? submission.filter(
						(value): value is string => typeof value === "string",
					)
				: [];
	}

	get read() {
		if (this._read) return this._read;
		if (!this.schema.options) return null;

		const options = this.schema.options;
		const read = document.createElement("div");

		if (this.schema.multiple) {
			read.className = `${STYLES.form.submission.default} flex-wrap gap-1.5`;
			this.values.forEach((item) => {
				const option = options.find((opt) => opt.value === item);
				if (!option) return;

				const chip = read.appendChild(document.createElement("span"));
				chip.className = STYLES.form.submission.chip;
				chip.textContent = option.label;
			});
		} else {
			read.className = STYLES.form.submission.default;
			const option = options.find((opt) => opt.value === this.values[0]);
			if (option) read.textContent = option.label;
		}

		read.classList.add("group-data-[mode=edit]/element:hidden");
		this._read = read;
		return read;
	}

	get edit() {
		if (this._edit) return this._edit;
		if (!this.schema.options) return null;

		this._edit = primitives.select({
			options: this.schema.options || [],
			label: this.label,
			name: this.schema.id || this.schema.name,
			kind: this.renderer.kind,
			data: {
				placeholder: this.schema.placeholder || "select an option...",
				multiple: this.schema.multiple,
				preload: this.values
					? JSON.stringify(this.values.map((value) => ({ id: value })))
					: "[]",
			},
		});

		this.combobox = new SelectBox(this._edit);
		this.combobox.init();
		this.destroyables.push(this.combobox);

		const select = this._edit.matches?.("[lp-select]")
			? this._edit
			: this._edit.querySelector("[lp-select]");
		select?.classList.add("group-data-[mode=read]/element:hidden");

		return this._edit;
	}

	clear() {
		if (this.combobox) {
			this.combobox.clear();
		}
		this.submission = null;
		const select = this.edit?.querySelector("select");
		if (select) select.value = "";
	}
}
