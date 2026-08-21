/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bc116afe';
import { j as areEqual } from './foundation.js?v=bc116afe';
import './connectivity.js?v=bc116afe';
import { p as primitives } from './primitives.js?v=bc116afe';
import { S as SelectBox } from './select2.js?v=bc116afe';
import { B as BaseElement } from './baseElement.js?v=bc116afe';
import './icons.js?v=bc116afe';
import './combobox.js?v=bc116afe';
import './results.js?v=bc116afe';
import './formatting.js?v=bc116afe';
import './submitter.js?v=bc116afe';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_selection_submission
 * @pairs pages:submission pages:selection-fields pages:read-mode
 */
class SelectElement extends BaseElement {
	get value() {
		if (this.combobox?.values.size > 0) {
			const values = Array.from(this.combobox.values);
			return this.schema.multiple ? values : values[0];
		}
		return null;
	}

	changed(value) {
		if (areEqual(this.value, value)) return false;
		return true;
	}

	active(value) {
		return this.combobox?.values.has(value) ?? this.values.includes(value);
	}

	get values() {
		if (!this.hasSubmission) return [];
		return typeof this.submission === "string"
			? [this.submission]
			: this.submission;
	}

	get read() {
		if (this._read) return this._read;
		if (!this.schema.options) return null;

		const options = this.schema.options;

		this._read = document.createElement("div");
		this._read.className = "flex flex-row flex-wrap gap-2";

		this.values.forEach((item) => {
			const option = options.find((opt) => opt.value === item);
			if (!option) return;

			const container = this._read.appendChild(document.createElement("div"));
			container.className = STYLES.form.submission.default;
			container.textContent = option.label;
		});

		this._read.classList.add("group-data-[mode=edit]/element:hidden");

		return this._read;
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
		this.edit.querySelector("select").value = "";
	}
}

export { SelectElement };
