/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=bb55a6e4';
import { k as simpleHash } from './foundation.js?v=bb55a6e4';
import './connectivity.js?v=bb55a6e4';
import { C as Condition } from './base2.js?v=bb55a6e4';
import './styles.js?v=bb55a6e4';
import './icons.js?v=bb55a6e4';
import './baseForm.js?v=bb55a6e4';
import './loader.js?v=bb55a6e4';
import './select2.js?v=bb55a6e4';
import './combobox.js?v=bb55a6e4';
import './results.js?v=bb55a6e4';
import './storage.js?v=bb55a6e4';
import './formatting.js?v=bb55a6e4';
import './submitter.js?v=bb55a6e4';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
 * @pair forms:builder-select-options
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
		this.element.schema.options ??= [];

		if (this.index !== -1) {
			this.setTitle("Edit Option");
			this.messages.submit = "Update Option";
			this.setting = { ...this.element.schema.options[this.index] };
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
		delete this.setting.value;

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
			this.setting.value = `o${simpleHash(this.setting.label)}`;
		}
		return true;
	}
}

export { Options as default };
