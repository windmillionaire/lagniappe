/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=b751984f';
import { g as generateElementId } from './foundation.js?v=b751984f';
import './connectivity.js?v=b751984f';
import { C as Condition } from './base2.js?v=b751984f';
import './styles.js?v=b751984f';
import './icons.js?v=b751984f';
import './upstreamUnavailable.js?v=b751984f';
import './baseForm.js?v=b751984f';
import './loader.js?v=b751984f';
import './select2.js?v=b751984f';
import './combobox.js?v=b751984f';
import './results.js?v=b751984f';
import './storage.js?v=b751984f';
import './formatting.js?v=b751984f';
import './submitter.js?v=b751984f';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
 * @pair forms:builder-select-options
 * @matrix forms : stable-identity
 */
class Options extends Condition {
	constructor(builder) {
		super(builder);
		this.key = "options";
		this.messages = {
			submit: "Add Option",
		};
	}

	init() {
		if (this.index !== -1) {
			this.setTitle("Edit Option");
			this.messages.submit = "Update Option";
			this.setting = { ...this.element.schema.options?.[this.index] };
		} else {
			this.setTitle("Create Option");
			this.messages.submit = "Add Option";
			this.setting = {};
		}

		super.init();

		this.showProgress();
	}

	showProgress() {
		this.addOptionName();
		if (this.setting.label) {
			this.complete = true;
		}
		super.showProgress();
	}

	addOptionName() {
		if (this.options.has("name")) return;

		const optionName = primitives.input({
			label: "Option Name",
			placeholder: "enter option name...",
			name: "option-name",
			type: "text",
			value: this.setting.label || null,
		});

		this.options.set("name", optionName);
		this.focusTarget = optionName;

		optionName.addEventListener("input", (e) => {
			this.setting.label = e.target.value;
			this.showProgress();
		});
	}

	validate() {
		if (!this.setting.label) {
			this.form.showError("Please enter an option name.");
			return false;
		}
		if (!this.setting.value) {
			do {
				this.setting.value = generateElementId("option");
			} while (
				this.element.schema.options?.some(
					(option) => option.value === this.setting.value,
				)
			);
		}
		return true;
	}
}

export { Options as default };
