/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=be1b1fb2';
import { s as setIcon } from './icons.js?v=be1b1fb2';
import { B as BaseElement } from './baseElement.js?v=be1b1fb2';
import { p as primitives } from './primitives.js?v=be1b1fb2';

/**
 * @testable infrastructure
 */
class CheckboxElement extends BaseElement {
	active() {
		const input = this.elt?.querySelector("input");
		if (input) return input.checked;
		if ([true, false].includes(this.submission)) return this.submission;
		return Boolean(this.schema.checked);
	}

	get value() {
		return this.active();
	}

	changed(value) {
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

		const value = [true, false].includes(this.submission)
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

export { CheckboxElement };
