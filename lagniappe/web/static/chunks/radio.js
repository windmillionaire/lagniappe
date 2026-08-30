/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bd163a0f';
import { B as BaseElement } from './baseElement.js?v=bd163a0f';
import { p as primitives } from './primitives.js?v=bd163a0f';
import './icons.js?v=bd163a0f';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_selection_submission
 * @matrix pages : read-mode selection-fields submission
 */
class RadioElement extends BaseElement {
	get value() {
		return Array.from(this.elt.querySelectorAll("input[type='radio']")).find(
			(radio) => radio.checked,
		)?.value;
	}

	changed(value) {
		if (this.value === value) return false;
		return true;
	}

	active(value) {
		return (
			this.elt?.querySelector(`input[type="radio"][value="${value}"]`)
				?.checked ?? this.submission === value
		);
	}

	get read() {
		if (this._read) return this._read;

		const option = this.schema.options.find(
			(opt) => opt.value === this.submission,
		);

		this._read = document.createElement("div");
		this._read.className = STYLES.form.submission.default;

		if (option) {
			this._read.textContent = option.label;
		}

		this._read.classList.add("group-data-[mode=edit]/element:hidden");

		return this._read;
	}

	get edit() {
		if (this._edit) return this._edit;

		this._edit = document.createElement("fieldset");

		if (this.label) {
			const legend = primitives.label({
				label: this.label,
				tag: "legend",
			});
			legend.classList.add("mb-1");
			this._edit.appendChild(legend);
		}

		const container = this._edit.appendChild(document.createElement("div"));
		const layout = this.schema.layout ?? "column";
		container.className = `${STYLES.radio.fieldset[layout]}`;

		this.schema.options.forEach((option) => {
			container.appendChild(
				primitives.radio({
					label: option.label,
					value: option.value,
					name: this.schema.id || this.schema.name,
					checked: this.submission === option.value,
				}),
			);
		});

		container.classList.add("group-data-[mode=read]/element:hidden");

		return this._edit;
	}

	clear() {
		this.submission = null;
		this.edit.querySelectorAll('input[type="radio"]').forEach((radio) => {
			radio.checked = false;
		});
	}
}

export { RadioElement };
