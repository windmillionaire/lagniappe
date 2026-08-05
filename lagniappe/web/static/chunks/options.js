/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=bfd37afb';
import { i as simpleHash } from './foundation.js?v=bfd37afb';
import './connectivity.js?v=bfd37afb';
import { C as Condition } from './base2.js?v=bfd37afb';
import './styles.js?v=bfd37afb';
import './icons.js?v=bfd37afb';
import './notificationState.js?v=bfd37afb';
import './baseForm.js?v=bfd37afb';
import './loader.js?v=bfd37afb';
import './select2.js?v=bfd37afb';
import './combobox.js?v=bfd37afb';
import './results.js?v=bfd37afb';
import './formatting.js?v=bfd37afb';
import './submitter.js?v=bfd37afb';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
 * @features forms
 * @dimensions builder-select-options
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
