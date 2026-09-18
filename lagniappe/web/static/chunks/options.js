/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=bf6747aa';
import { g as generateElementId } from './foundation.js?v=bf6747aa';
import './connectivity.js?v=bf6747aa';
import { C as Condition } from './base2.js?v=bf6747aa';
import './styles.js?v=bf6747aa';
import './icons.js?v=bf6747aa';
import './upstreamUnavailable.js?v=bf6747aa';
import './select2.js?v=bf6747aa';
import './combobox.js?v=bf6747aa';
import './results.js?v=bf6747aa';
import './storage.js?v=bf6747aa';
import './formatting.js?v=bf6747aa';
import './submitter.js?v=bf6747aa';
import './controller.js?v=bf6747aa';
import './loader.js?v=bf6747aa';

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
