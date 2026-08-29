import { STYLES } from "styles";
import { BaseElement } from "./base/baseElement";
import { primitives } from "./primitives";

/**
 * @testable infrastructure
 * @tests tests_js/test_028_form_state_split.py::test_direct_form_controls_clear_inputs_and_textareas
 */
export class TextareaElement extends BaseElement {
	get value() {
		const textarea = this.elt?.matches?.("textarea")
			? this.elt
			: this.elt?.querySelector("textarea");
		if (textarea) return textarea.value;
		if (this.submission === null || this.submission === undefined) return null;
		return String(this.submission);
	}

	changed(value) {
		if (this.value === String(value ?? "")) return false;
		return true;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_direct_form_controls_clear_inputs_and_textareas
	 * @matrix forms : clear input textarea
	 */
	clear() {
		this.submission = null;
		const textarea = this._edit?.matches?.("textarea")
			? this._edit
			: this._edit?.querySelector("textarea");
		if (textarea) textarea.value = "";
	}

	get read() {
		if (this._read) return this._read;

		this._read = document.createElement("p");
		this._read.textContent = this.hasSubmission ? String(this.submission) : "";
		this._read.className = STYLES.form.submission.grows;
		this._read.classList.add("group-data-[mode=edit]/element:hidden");

		return this._read;
	}

	get edit() {
		if (this._edit) return this._edit;

		this._edit = primitives.textarea({
			label: this.label,
			name: this.schema.id,
			placeholder: this.schema.placeholder,
			rows: 3,
			value: this.submission,
			disabled: this.renderer.readonly,
		});

		const textarea = this._edit.matches?.("textarea")
			? this._edit
			: this._edit.querySelector("textarea");
		textarea?.classList.add("group-data-[mode=read]/element:hidden");

		return this._edit;
	}
}
